"""
玩家 Agent：玩家 Agent共用的父类

workflows：
    确认身份 -> 等待法官请求 ->（夜间请求先走私聊）
             -> 读取大屏 -> 简单推理 -> 决策 -> 发言 / 投票 / 夜间动作 -> 收尾

"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from werewolf_claw.boards import DEFAULT_BOARD
from werewolf_claw.core.board import Board
from werewolf_claw.core.character import Character
from werewolf_claw.core.node import DEFAULT_ACTION, Flow, Node
from werewolf_claw.core.screen import PRIVATE, PUBLIC, Message
from werewolf_claw.tools import GoalState, ToolExecutor, get_tools

# 模型入口：(prompt, system) -> 文本。省略就是纯规则模式。
ChatFn = Callable[..., str]

# 一条公开发言的字数上限。
MAX_STATEMENT_CHARS = 100

# 队伍讨论里一句意见的字数上限。
MAX_TEAM_TALK_CHARS = 50

# 模型输出被打回后最多重写几次。
MAX_REWRITE = 2

# 一次发言/投票里最多让模型查几轮工具；跑满之后不再给工具，直接要正文
MAX_TOOL_ROUNDS = 2

# 公开发言里和私聊原文连续重合多少字，就算疑似泄露私聊内容（「超过 12 个字符」）
LEAK_SUBSTRING_CHARS = 12

# 狼人公开发言里同时提到几个队友座位号，就算疑似暴露队友
ALLY_EXPOSE_MENTIONS = 2

# 发言的三种立场：指认 / 保人 / 报自己的查验。旧消息没有这个字段时按 accuse 处理
STATEMENT_ACTIONS = ("accuse", "defend", "report")
DEFAULT_STATEMENT_ACTION = "accuse"

# 公开压力（被指认次数 - 被保次数）每一档对置信度的影响
PRESSURE_WEIGHT = 0.1

# 公开压力最多按几档算，免得一串发言把置信度直接拉满
MAX_PRESSURE_STEPS = 3

# 「给后来被票出局的人投过票」的好人面权重：按次累加，置信度最后仍夹在 0~1
VOTE_SIGNAL_BONUS = 0.05

# 法官这一次要什么。
KIND_NIGHT = "夜间"
KIND_SPEECH = "发言"
KIND_BALLOT = "投票"
KIND_IDLE = "空闲"

_FENCED = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_object(text: str) -> dict[str, Any]:
    """从模型输出里掏出 JSON 对象，容忍 ```json 围栏和前后废话。"""
    raw = (text or "").strip()
    fenced = _FENCED.search(raw)
    if fenced:
        raw = fenced.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("模型没有返回 JSON 对象") from None
        data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("模型返回的不是 JSON 对象")
    return data


def mentions_seat(text: str, seat: int) -> bool:
    """文本里有没有提到这个座位号。

    前后都加数字断言：`13 号` 不能被当成 `1 号` 或 `3 号`，`3 号` 也不会匹配 `13 号`。
    """
    return re.search(rf"(?<!\d){seat}\s*号(?!\d)", text) is not None


def shared_substring(text: str, others: Sequence[str], length: int) -> str:
    """`text` 和 `others` 里任意一段有没有连续重合超过 `length` 个字符，返回命中的那段。

    公开发言的泄露校验用它：和私聊原文有长句重合，说明模型在复述私聊内容。
    """
    window = length + 1
    compact = "".join(text.split())
    for other in others:
        haystack = "".join(str(other).split())
        if len(haystack) < window:
            continue
        for start in range(len(compact) - window + 1):
            piece = compact[start : start + window]
            if piece in haystack:
                return piece
    return ""


# ------------------------------------------------------------------ 上下文对象


@dataclass
class Guess:
    """推测表里的一格：对这个座位身份的推测和置信度。"""

    role: str = ""
    confidence: float = 0.5
    reason: str = ""


@dataclass
class Belief:
    """推理节点的产物：每个座位一格推测，推理完整张表换新。"""

    day: int = 0
    table: dict[int, Guess] = field(default_factory=dict)

    def update(self, seat: int, role: str, confidence: float, reason: str) -> None:
        """写一格推测，置信度夹在 0~1。"""
        self.table[seat] = Guess(
            role=role, confidence=min(1.0, max(0.0, confidence)), reason=reason
        )

    def guess(self, seat: int) -> Guess:
        return self.table.get(seat, Guess())


@dataclass
class Decision:
    """决策节点的产物：要动谁、为什么。"""

    target: int | None = None
    reason: str = ""


@dataclass
class Request:
    """法官这一次要什么。"""

    kind: str
    phase: str = ""
    alive: tuple[int, ...] = ()


@dataclass
class Turn:
    """一次 Flow 里传下去的东西：请求、决策、产物。"""

    request: Request
    decision: Decision | None = None
    result: Any = None


# ------------------------------------------------------------------ 各个 Node


class InitNode(Node):
    """init：确认身份并设置。身份卡来自法官的私聊。"""

    def __init__(self, player: "PlayerAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.player = player

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        if not self.player.knows_role:
            self.player.learn_role()
        return "等待", payload


class AwaitJudgeNode(Node):
    """等待法官请求。法官没请求就不触发私聊，但每个玩家都有这个节点。

    夜间请求先走私聊（和法官一问一答），发言和投票直接读大屏。
    """

    def __init__(self, player: "PlayerAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.player = player

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        kind = payload.request.kind
        if kind == KIND_NIGHT:
            return "私聊", payload
        if kind in (KIND_SPEECH, KIND_BALLOT):
            return "处理", payload
        if kind == KIND_IDLE:
            return "空闲", payload
        raise ValueError(f"不认识的请求类型：{kind}")


class PrivateChatNode(Node):
    """私聊：夜间和法官的一问一答，把问到的信息写进私有记忆。"""

    def __init__(self, player: "PlayerAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.player = player

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        self.player.open_private_chat()
        return "读取", payload


class ReadBoardNode(Node):
    """读取大屏：新消息同步进记忆，同时更新天数和自己的生死，然后判断生死。

    「每一人发言完都要同步大屏消息到记忆」就落在这一步：轮到自己的时候，
    前面所有人的发言都已经在大屏里读进来了。出局的人到这里就收尾，不再发言投票。
    """

    def __init__(self, player: "PlayerAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.player = player

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        self.player.sync_board()
        if not self.player.alive:
            return "出局", payload
        return "推理", payload


class ListenBoardNode(Node):
    """空闲：法官没有请求，只把大屏同步进记忆，不发言也不投票。"""

    def __init__(self, player: "PlayerAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.player = player

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        self.player.sync_board()
        return "收尾", payload


class ReasonNode(Node):
    """简单推理：重新算一份推测表。"""

    def __init__(self, player: "PlayerAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.player = player

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        self.player.belief = self.player.reason(payload.request.alive)
        return "决策", payload


class DecideNode(Node):
    """决策：按法官要的东西挑一条支路。"""

    def __init__(self, player: "PlayerAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.player = player

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        kind = payload.request.kind
        if kind == KIND_NIGHT:
            # 夜间动作的实现在角色类里（NightActionNode → choose_night_action），
            # 这里算出来的 Decision 没人读，直接跳过，省一次 suspects 排序
            payload.decision = None
            return "夜间", payload
        payload.decision = self.player.decide(payload.request.alive)
        if kind == KIND_SPEECH:
            return "发言", payload
        if kind == KIND_BALLOT:
            return "投票", payload
        raise ValueError(f"不认识的请求类型：{kind}")


class SpeakNode(Node):
    """发言：交给玩家的 `express()`——它内部先带工具问一轮（`_ask`），
    需要查大屏/推理就自己查，然后校验、不合格重写、再不合格用规则版。"""

    def __init__(self, player: "PlayerAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.player = player

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        payload.result = self.player.express(payload.request.alive)
        return "收尾", payload


class VoteNode(Node):
    """投票：bestchoice 必须在场上，不合格就退到规则兜底。"""

    def __init__(self, player: "PlayerAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.player = player

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        payload.result = self.player.cast_ballot(
            payload.request.alive, payload.decision or Decision()
        )
        return "收尾", payload


class NightActionNode(Node):
    """夜间动作节点：这里只留流程，具体实现在角色类里。

    真正的选择、校验由 `Board.characters[阶段]` 那个角色类负责，节点只把请求交给
    玩家，玩家再交给角色。
    """

    def __init__(self, player: "PlayerAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.player = player

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        payload.result = self.player.choose_night_action(
            payload.request.phase, payload.request.alive
        )
        return "收尾", payload


class DoneNode(Node):
    """收尾：产物已经放在 payload 里，交回给调用方。"""

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        return DEFAULT_ACTION, payload


# ------------------------------------------------------------------ Agent


class PlayerAgent:
    """玩家父类：所有身份共用同一条 Flow，身份差异全部来自角色类。

    身份从板子取（`Board.characters[role]` 是一个 `Character`），技能问角色类要
    （`Character.skill_action`），技能名取 `Character.skill`；询问、校验模型输出、
    回执、结算、发言和投票都在这里（回执和结算在法官那边）。没有特殊技的身份就是
    普通身份：夜里不被叫醒，发言用通用说法。
    """

    def __init__(
        self,
        seat: int,
        role: str,
        *,
        board: Board | None = None,
        chat: ChatFn | None = None,
    ) -> None:
        self.board = board or DEFAULT_BOARD
        self.seat = seat
        self.role = role
        self.camp = self.board.camps[role]
        # 身份对应的角色实现：技能和发言都在它上面。
        self.character: Character = self.board.characters[role]
        # IS_special 标识：夜里会被叫醒才和法官建立私聊。
        self.is_special = role in self.board.night_phases
        self.skill = self.character.skill
        self.chat = chat

        self.inbox: list[Message] = []  # 投给自己的消息
        self.notes: list[str] = []  # 私有记忆：身份、情报、公屏与私聊同步、发言账本
        # 公屏记忆：只装公屏上的内容。公开发言的 prompt 只读它——`notes` 里有私聊原文
        # （查验回执、狼队频道、法官提醒），整段端给公开发言会诱导模型把私密信息说出去
        self.public_notes: list[str] = []
        self.belief = Belief()
        self.knows_role = False
        self.alive = True
        self.day = 0
        self.alive_list: tuple[int, ...] = ()  # 本次请求给的存活表
        self.allies: set[int] = set()  # 到夜间阶段跟队友共用一次对话时才知道
        self.skill_history: list[dict[str, Any]] = []  # 自己用过的技能，角色类可以读
        self.attacked: int | None = None  # 法官私下告诉自己的今晚刀口（女巫用）
        self.death_cause = ""  # 出局原因：poison / attack / vote，猎人读它
        self.request_kind = ""  # 当前在做什么（发言/投票/技能/讨论），人类接管时显示
        # 目标：玩家的 goal 就是赢下这一局；工具让它在发言/投票前自己查大屏、记笔记
        self.aim = "获得游戏胜利"
        self.goal = GoalState(self.aim, True)
        self.tools = ToolExecutor(get_tools(self))

        self._seen = 0  # 收到了哪条消息，用来去重
        self._read = 0  # 大屏读到哪条
        self._chat_read = 0  # 私聊读到哪条
        self._flow = self.build_flow()

    def build_flow(self) -> Flow:
        """把各个 Node 连成闭环。返回的 Flow 从「确认身份」进，从「收尾」出。"""
        init = InitNode(self)
        await_judge = AwaitJudgeNode(self)
        chat = PrivateChatNode(self)
        read = ReadBoardNode(self)
        listen = ListenBoardNode(self)
        reason = ReasonNode(self)
        decide = DecideNode(self)
        speak = SpeakNode(self)
        vote = VoteNode(self)
        night = NightActionNode(self)
        done = DoneNode()

        init - "等待" >> await_judge
        await_judge - "私聊" >> chat  # 夜间请求：先和法官对话
        await_judge - "处理" >> read  # 发言 / 投票：直接读大屏
        await_judge - "空闲" >> listen  # 没有请求：只同步大屏
        chat - "读取" >> read
        read - "推理" >> reason
        read - "出局" >> done  # 读取大屏之后判断生死：出局的人不再发言投票
        listen - "收尾" >> done
        reason - "决策" >> decide
        decide - "发言" >> speak
        decide - "投票" >> vote
        decide - "夜间" >> night
        speak - "收尾" >> done
        vote - "收尾" >> done
        night - "收尾" >> done
        return Flow(init)

    # ------------------------------------------------------------------ 闸门

    def receive(self, messages: Sequence[Message]) -> int:
        """收下法官投递的消息，返回新收了几条。

        隔离的第二道闸门：不是投给这个座位的消息直接丢掉，不进上下文。
        """
        fresh = [
            message
            for message in messages
            if message.seq > self._seen and message.visible_to(self.seat)
        ]
        if not fresh:
            return 0
        self._seen = max(message.seq for message in fresh)
        self.inbox.extend(fresh)
        for message in fresh:
            self._apply_facts(message)
        return len(fresh)

    def transcript(self, *, limit: int = 40, channel: str | None = None) -> str:
        """按序号列出自己收到的消息。

        `channel` 省略表示全部（公开大屏 + 投给自己的私聊）；给 `PUBLIC` 只拿公屏，
        给 `PRIVATE` 只拿私聊。公开发言这类 prompt 只能传公屏：`inbox` 是公私混装的，
        整段端出去会让模型把查验回执、狼队频道这些私密内容当公开信息引用。
        """
        rows = [
            message
            for message in self.inbox
            if channel is None or message.channel == channel
        ]
        return "\n".join(
            f"#{message.seq} 第 {message.day} 天 {message.text}"
            for message in rows[-limit:]
        )

    # ------------------------------------------------------------------ 法官协议

    def night_action(self, phase: str, alive: Sequence[int]) -> dict[str, Any]:
        """法官调用：私聊里报一次夜间动作。自己的动作记进技能历史，下次可能要用。"""
        self.request_kind = "技能"
        result = self._run(Request(kind=KIND_NIGHT, phase=phase, alive=tuple(alive)))
        if not isinstance(result, dict) or not self.alive:
            result = (
                self.rule_night_action(phase, alive)
                if self.alive
                else {"phase": phase, "target": None, "effect": ""}
            )
        # candidates 是角色给的候选名单，只用来校验，不进对局记录
        action = {key: value for key, value in result.items() if key != "candidates"}
        self.skill_history.append(dict(action))
        return action

    def last_target(self, effect: str) -> int | None:
        """自己上一次用这类效果时选的目标；角色类读它来限住自己。

        守卫用它判断「上一晚守了谁」：连着两晚不能守同一个人。
        """
        for action in reversed(self.skill_history):
            if action.get("effect") != effect:
                continue
            target = action.get("target")
            return None if target is None else int(target)
        return None

    def used(self, effect: str) -> bool:
        """这类技能之前用过了吗（女巫的解药、毒药各只能一次）。"""
        return any(action.get("effect") == effect for action in self.skill_history)

    def death_action(self, cause: str, alive: Sequence[int]) -> dict[str, Any] | None:
        """法官调用：这个人刚出局，问他的身份有没有死亡触发技（猎人开枪）。"""
        self.request_kind = "出局技能"
        self.death_cause = cause
        self.alive_list = tuple(alive)
        if self.chat is None:
            return self.rule_death_action(alive)
        try:
            raw = self.chat(
                self._death_prompt(cause, alive), system=self._death_system()
            )
        except Exception:
            self.notes.append("出局技能回退：模型调用失败")
            return self.rule_death_action(alive)
        try:
            candidate = self._parse_action(raw)
        except Exception:
            self.notes.append("出局技能回退：模型输出无法解析")
            return self.rule_death_action(alive)
        problems = self._check_night_action(candidate, self.role, alive, {})
        if problems:
            self.notes.append("出局技能回退：" + "；".join(problems))
            return self.rule_death_action(alive)
        return {**candidate, "effect": "shoot"}

    def rule_death_action(self, alive: Sequence[int]) -> dict[str, Any] | None:
        """规则版出局技能：问角色类要。"""
        return self.character.skill_action(self)

    def team_talk(self, phase: str, alive: Sequence[int], round_no: int) -> str:
        """法官调用：多人同夜行动前，先说一句自己的意见（狼队商量刀谁）。

        `round_no` 是第几轮讨论（原来的参数名 `round` 会遮蔽内建函数，改名保持一致）。
        """
        self.request_kind = "讨论"
        self.alive_list = tuple(alive)
        fallback = self.rule_team_talk(phase, alive)
        if self.chat is None:
            return fallback

        try:
            raw = self.chat(
                self._team_prompt(phase, alive, round_no), system=self._team_system(phase)
            )
        except Exception:
            self.notes.append("队伍讨论回退：模型调用失败")
            return fallback

        text = " ".join(str(raw or "").split())
        if not text:
            self.notes.append("队伍讨论回退：模型没有输出")
            return fallback
        return text[:MAX_TEAM_TALK_CHARS]

    def rule_team_talk(self, phase: str, alive: Sequence[int]) -> str:
        """规则版队伍讨论：直接说自己想动的目标。"""
        target = self.rule_night_action(phase, alive).get("target")
        return f"我倾向 {target} 号。" if target is not None else "我没有明确目标。"

    def statement(self, alive: Sequence[int]) -> dict[str, Any]:
        """法官调用：报一次公开发言。"""
        self.request_kind = "发言"
        result = self._run(Request(kind=KIND_SPEECH, alive=tuple(alive)))
        if isinstance(result, dict):
            return result
        if not self.alive:
            return {"text": "", "target": None}
        return self.rule_statement(alive)

    def ballot(self, alive: Sequence[int]) -> dict[str, Any]:
        """法官调用：报一次投票。"""
        self.request_kind = "投票"
        result = self._run(Request(kind=KIND_BALLOT, alive=tuple(alive)))
        if isinstance(result, dict):
            return result
        if not self.alive:
            return {"target": None}
        return {"target": None}

    def watch(self) -> None:
        """没有法官请求时的一次轮询：只把大屏同步进记忆，不产出动作。

        对应 rules 里的「等待 judge 请求（没有就不触发私聊）」。别人发言的时候，
        系统可以这样把大屏推给每个玩家。
        """
        self._run(Request(kind=KIND_IDLE))

    def _run(self, request: Request) -> Any:
        """跑一次闭环：确认身份 -> 等请求 -> 读大屏 -> 推理 -> 决策 -> 动作 -> 收尾。"""
        self.alive_list = tuple(request.alive)
        _, turn = self._flow.run(Turn(request=request))
        return turn.result

    # ------------------------------------------------------------------ 闭环各步

    def learn_role(self) -> None:
        """确认身份并设置：记下座位号、身份、阵营和特殊技。队友不在这里给。"""
        self.knows_role = True
        for message in self.inbox:
            if message.kind != "role":
                continue
            self.role = str(message.facts.get("role") or self.role)
            self.camp = str(message.facts.get("camp") or self.board.camps.get(self.role, ""))

        self.character = self.board.characters[self.role]
        self.is_special = self.role in self.board.night_phases
        self.skill = self.character.skill
        note = f"我是 {self.seat} 号，身份是{self.role}（{self.camp}）"
        if self.skill:
            note += f"，特殊技：{self.skill}"
        self.notes.append(note + "。")

    def open_private_chat(self) -> None:
        """私聊：把法官这一轮的私聊请求记进私有记忆。"""
        asked = [
            message
            for message in self.inbox
            if message.channel == PRIVATE and message.seq > self._chat_read
        ]
        if not asked:
            return
        self._chat_read = asked[-1].seq
        for message in asked:
            self.notes.append(f"法官私聊：{message.text}")

    def sync_board(self) -> int:
        """读取大屏：新消息同步进记忆，返回读了几条。

        公屏记进 `public_notes`（公开发言只读它），私聊只进 `notes`；两条都按通道标好来源，
        免得私聊内容被当成「大屏上看到的」。
        """
        fresh = [message for message in self.inbox if message.seq > self._read]
        if not fresh:
            return 0
        self._read = fresh[-1].seq
        for message in fresh:
            self._apply_facts(message)
            label = "大屏" if message.channel == PUBLIC else "私聊"
            line = f"{label} #{message.seq}：{message.text}"
            self.notes.append(line)
            if message.channel == PUBLIC:
                self.public_notes.append(line)
        return len(fresh)

    def _apply_facts(self, message: Message) -> None:
        """从消息里更新自己的状态：天数、生死、队友。

        天亮那条给出完整存活表；夜里的出局名单、白天被放逐的人也都直接改状态。
        队友名单来自「同一阶段共用一次对话」的那条消息，所以狼人是在狼人阶段
        才知道队友的。
        """
        if message.kind == "dawn":
            self.day = int(message.facts.get("day") or self.day)
        elif message.kind == "alive":
            seats = {int(seat) for seat in message.facts.get("alive") or ()}
            self.alive = self.seat in seats
        elif message.kind == "result":
            if self.seat in {int(seat) for seat in message.facts.get("deaths") or ()}:
                self.alive = False
        elif message.kind == "death":
            if message.facts.get("seat") == self.seat:
                self.alive = False
        elif message.kind == "phase":
            seats = {int(seat) for seat in message.facts.get("seats") or ()}
            self.allies |= seats - {self.seat}
        if "attacked" in message.facts:
            attacked = message.facts["attacked"]
            self.attacked = None if attacked is None else int(attacked)

    def reason(self, alive: Sequence[int]) -> Belief:
        """简单推理：先按板子的人数给先验，再盖自己的情报，更新推测表。

        两个公开信号的口径：

        - **净压力**：被公开指认 +1、被公开保 -1、报查验不计，净值为正说明他被大家盯着；
        - **票型**：给后来被票出局的人投过票，说明这一票和好人的方向一致，好人面微升。

        这里是 ReAct 节点的位置。雏形给的是规则先验（板子比例 + 公开压力 + 票型 +
        自己的情报），真接模型时在这一步查大屏、查某人的历史发言，再把结论盖到推测表上。
        """
        members = [seat for seat in alive if seat != self.seat]
        others = [role for role in self.board.distribution if role != self.role]
        own_side = [
            role for role in self.board.distribution if self.board.camps[role] == self.camp
        ]
        hostile = [
            role for role in self.board.distribution if self.board.camps[role] != self.camp
        ]
        prior_role = Counter(others).most_common(1)[0][0] if others else ""
        mate_role = Counter(own_side).most_common(1)[0][0] if own_side else prior_role
        enemy_role = Counter(hostile).most_common(1)[0][0] if hostile else prior_role
        prior = others.count(prior_role) / max(len(others), 1)
        pressure = self._pressures()
        voted_out = self._vote_pressure()

        belief = Belief(day=self.day)
        for seat in members:
            if seat in self.allies:
                belief.update(seat, mate_role, 1.0, "队友，夜里那次对话里确认的")
                continue
            net = pressure.get(seat, 0)
            # 净压力为正（被指认得多）压狼面，为负（被保得多）抬好人面，最多算 MAX_PRESSURE_STEPS 档
            steps = max(-MAX_PRESSURE_STEPS, min(MAX_PRESSURE_STEPS, net))
            confidence = (
                prior
                - PRESSURE_WEIGHT * steps
                + VOTE_SIGNAL_BONUS * voted_out.get(seat, 0)
            )
            reasons = []
            if net:
                reasons.append(f"公开压力 {net:+d}")
            if voted_out.get(seat):
                reasons.append(f"跟着票出过 {voted_out[seat]} 次")
            belief.update(
                seat,
                prior_role,
                confidence,
                "，".join(reasons) or "先验：按板子的人数比例",
            )
        for target, camp in self.checks():
            if target not in belief.table:
                continue
            if camp == self.camp:
                belief.update(target, mate_role, 0.9, f"我自己查到的：{camp}")
            else:
                belief.update(target, enemy_role, 0.95, f"我自己查到的：{camp}")
        return belief

    def _threat(self, seat: int) -> float:
        """这个座位不是自己人的可能性：推测和我不同阵营就取置信度，否则取反面。"""
        guess = self.belief.guess(seat)
        if guess.role and self.board.camps.get(guess.role, self.camp) != self.camp:
            return guess.confidence
        return 1.0 - guess.confidence

    def _belief_summary(self, alive: Sequence[int]) -> str:
        suspects = self.suspects(alive)
        if not suspects:
            return f"第 {self.day} 天场上没有可怀疑的人。"
        target = suspects[0]
        guess = self.belief.guess(target)
        return (
            f"第 {self.day} 天最可疑的是 {target} 号，"
            f"推测是{guess.role}（置信度 {guess.confidence:.2f}）。"
        )

    def others(self) -> tuple[int, ...]:
        """本次请求里场上除自己以外的人，角色类可以读它。"""
        return tuple(seat for seat in self.alive_list if seat != self.seat)

    def suspects(self, alive: Sequence[int] | None = None) -> tuple[int, ...]:
        """推测表里最可疑的排最前面，自己人除外。"""
        members = self.alive_list if alive is None else alive
        blocked = {self.seat} | self.allies
        return tuple(
            sorted(
                (seat for seat in members if seat not in blocked),
                key=lambda seat: (-self._threat(seat), seat),
            )
        )

    def decide(self, alive: Sequence[int]) -> Decision:
        """决策：bestchoice —— 推测表里最可疑的那个，自己人除外。"""
        suspects = self.suspects(alive)
        if not suspects:
            return Decision(target=None, reason="场上没有可投的对象")
        target = suspects[0]
        return Decision(target=target, reason=self.belief.guess(target).reason or "票型可疑")

    def express(self, alive: Sequence[int]) -> dict[str, Any]:
        """表达：规则版先写一版，模型改写，校验不过就重写，再不过用规则版。"""
        draft = self.rule_statement(alive)
        if self.chat is None:
            self._note_public_statement(draft["text"])
            return draft

        problems: list[str] = []
        prompt = self.statement_prompt(alive)
        for _ in range(MAX_REWRITE + 1):
            try:
                candidate = self._parse_statement(
                    self._ask(prompt, self._statement_system(), with_tools=True)
                )
            except Exception:
                # 解析失败也消耗一次重写机会：模型偶尔会回一段解释而不是 JSON，
                # 直接 break 等于把重写次数白扔掉
                problems = ["模型输出无法解析"]
                prompt = f"{prompt}\n\n上一次的输出不是 JSON。请只输出 JSON 对象，再给一版发言。"
                continue
            problems = self._check_statement(candidate, alive)
            if not problems:
                self._note_public_statement(candidate["text"])
                return candidate
            prompt = f"{prompt}\n\n上一次的发言不合格，原因：{'；'.join(problems)}。请重写。"

        self.notes.append("表达节点回退到规则版：" + "；".join(problems))
        return draft

    def _note_public_statement(self, text: str) -> None:
        """记下自己公开说过的话：私有记忆和公屏记忆各记一份（后者给公开发言的 prompt 用）。"""
        line = f"第 {self.day} 天我公开说：{text}"
        self.notes.append(line)
        self.public_notes.append(line)

    def cast_ballot(self, alive: Sequence[int], decision: Decision) -> dict[str, Any]:
        """投票：bestchoice 必须还在场上，否则退回规则兜底目标。"""
        target = decision.target
        if target is not None and target not in set(alive):
            self.notes.append(f"投票回退：{target} 号不在场上")
            target = self.decide(alive).target

        if self.chat is not None:
            try:
                data = parse_json_object(
                    self._ask(self._vote_prompt(alive), self._vote_system(), with_tools=True)
                )
                chosen = data.get("target")
                if chosen is not None and int(chosen) in set(alive) and int(chosen) != self.seat:
                    target = int(chosen)
                elif chosen is not None:
                    self.notes.append(f"投票回退：模型投的 {chosen} 号不合法")
            except Exception:
                self.notes.append("投票回退：模型输出无法解析")

        self._note_ballot_gap(target)
        return {"target": target}

    def _note_ballot_gap(self, target: int | None) -> None:
        """投票和最近一次公开发言对不上就记一笔，供后续 `reason()` 参考。

        prompt 要求「不要和公开发表的立场矛盾」，但模型投了谁都直接接受，言行不一的信号
        就丢了。这里只记录（不要求改票）：那次发言是 accuse / defend / report 都算，
        保了 3 号却投 5 号、报了 3 号却投 3 号，都是值得留着的不一致。
        """
        said = self._last_public_statement_target()
        if said is None or said == target:
            return
        voted = f"投了 {target} 号" if target is not None else "弃票"
        self.notes.append(f"言行不一：发言指认 {said} 号，实际{voted}。")

    def _last_public_statement_target(self) -> int | None:
        """自己最近一次公开发言提到的目标；没发过言或没提到人时返回 None。"""
        for message in reversed(self.inbox):
            if message.kind != "statement":
                continue
            if int(message.facts.get("seat") or 0) != self.seat:
                continue
            target = message.facts.get("target")
            return None if target is None else int(target)
        return None

    def choose_night_action(self, phase: str, alive: Sequence[int]) -> dict[str, Any]:
        """夜间动作：规则版由角色类给，模型给的结果过校验才用。"""
        character = self.board.characters.get(phase)
        if character is None:
            self.notes.append(f"板子里没有 {phase} 的身份，这一阶段没有动作")
            return {"phase": phase, "target": None, "effect": ""}

        fallback = self.rule_night_action(phase, alive)
        if self.chat is None:
            return fallback

        try:
            candidate = self._parse_action(
                self.chat(
                    self._night_prompt(phase, alive, fallback.get("candidates") or alive),
                    system=self._action_system(phase),
                )
            )
        except Exception:
            self.notes.append("夜间动作回退：模型输出无法解析")
            return fallback

        problems = self._check_night_action(candidate, phase, alive, fallback)
        if problems:
            self.notes.append("夜间动作回退：" + "；".join(problems))
            return fallback
        # 「不用技能」（女巫捏着药）：空目标必须是明确的弃权，效果置空，
        # 不能继承规则建议的 save/poison——否则空手会把这瓶药白白烧掉
        character = self.board.characters.get(phase)
        if candidate.get("target") is None and character is not None and character.can_pass:
            return {"phase": phase, "target": None, "effect": candidate.get("effect", "")}
        # 人类可以指定效果（女巫选 save 还是 poison）；模型只能选目标，效果由角色类定
        if candidate.get("effect") and character is not None and character.can_pass:
            return {**candidate, "effect": candidate["effect"]}
        # 效果由角色类定，模型只能选目标，不能改效果
        return {**candidate, "effect": fallback.get("effect", "")}

    # ------------------------------------------------------------------ 规则版

    def _ask(self, prompt: str, system: str, *, with_tools: bool = False) -> str:
        """问模型。开了工具就先让它自己查：要查大屏/查某人发言/记笔记都行，
        工具结果只写进私有记忆，再把结果接回去让它继续回答
        （参考脚本的 chat→tool→chat，最多 `MAX_TOOL_ROUNDS` 轮工具）。
        """
        asker = getattr(self.chat, "with_tools", None) if self.chat is not None else None
        if not (with_tools and asker is not None):
            return self.chat(prompt, system=system)

        follow = prompt
        lines: list[str] = []
        text = ""
        # 最多跑 MAX_TOOL_ROUNDS 轮工具；跑满之后不再给工具、直接要正文，避免死循环
        for _ in range(MAX_TOOL_ROUNDS):
            text, calls = asker(follow, system=system, tools=self.tools.llm_tools())
            if not calls:
                return text
            lines.extend(self._tool_lines(calls))
            follow = (
                f"{prompt}\n\n你刚才调用了工具，结果如下：\n"
                + "\n".join(lines)
                + "\n现在按上面的要求给出结果。"
            )
        return self.chat(follow, system=system) or text

    def _tool_lines(self, calls: Sequence[Any]) -> list[str]:
        """执行模型这一轮要调的工具：结果进私有记忆，返回能拼进 prompt 的文本行。"""
        lines: list[str] = []
        for result in self.tools.execute_all(self.tools.parse_tool_calls({"tool_calls": calls})):
            self.notes.append(f"工具 {result.name}：{result.content[:200]}")
            lines.append(f"[工具 {result.name}] {result.content}")
        return lines

    def rule_night_action(self, phase: str, alive: Sequence[int]) -> dict[str, Any]:
        """规则版夜间动作：问角色类要。"""
        character = self.board.characters.get(phase)
        if character is None:
            return {"phase": phase, "target": None, "effect": ""}
        return character.skill_action(self) or {"phase": phase, "target": None, "effect": ""}

    def rule_statement(self, alive: Sequence[int]) -> dict[str, Any]:
        """规则版发言：有查验情报就先报，否则指认最可疑的人。

        回报里带 `action`：报查验是 report、指认是 accuse（没目标时也给 accuse，
        因为这一票的压力本来就没落在谁身上）。
        """
        checks = self.checks()
        if checks:
            target, camp = checks[-1]
            return {
                "text": f"我是 {self.seat} 号，我查验过 {target} 号，是{camp}。",
                "target": target,
                "action": "report",
            }
        suspects = self.suspects(alive)
        if not suspects:
            return {
                "text": f"我是 {self.seat} 号，我这边没有新的信息，先过。",
                "target": None,
                "action": DEFAULT_STATEMENT_ACTION,
            }
        target = suspects[0]
        reason = self.belief.guess(target).reason or "票型可疑"
        return {
            "text": f"我是 {self.seat} 号。我觉得 {target} 号最可疑，{reason}。",
            "target": target,
            "action": DEFAULT_STATEMENT_ACTION,
        }

    def checks(self) -> list[tuple[int, str]]:
        """自己收到的阵营情报（比如预言家查到的结果），只来自私聊。"""
        results: list[tuple[int, str]] = []
        for message in self.inbox:
            check = message.facts.get("check") or {}
            target, camp = check.get("target"), check.get("camp")
            if target is not None and camp:
                results.append((int(target), str(camp)))
        return results

    def _pressures(self) -> Counter[int]:
        """大屏上公开施加的净压力：指认 +1、保人 -1、报查验不计。

        原来是「有 target 就算被指认」，会把预言家报查验和保人发言都算成指认，
        让被保的人反而更可疑。现在按 `action` 区分（旧消息没有 action 时按 accuse 处理）。
        """
        counts: Counter[int] = Counter()
        for message in self.inbox:
            if message.kind != "statement":
                continue
            target = message.facts.get("target")
            if target is None:
                continue
            action = str(message.facts.get("action") or DEFAULT_STATEMENT_ACTION)
            if action == "report":
                continue
            if action == "defend":
                counts[int(target)] -= 1
            else:
                counts[int(target)] += 1
        return counts

    def _vote_pressure(self) -> Counter[int]:
        """给后来被票出局的人投过票的次数：跟对了放逐方向，是好人面的微升信号。

        数据来自大屏逐条的 `kind=="ballot"`（谁投了谁）；谁被放逐看 `kind=="vote"` 的
        `eliminated`。不做「只算最近一天」：死者生前的投票记录也是有效历史。
        """
        eliminated: set[int] = set()
        for message in self.inbox:
            if message.kind != "vote":
                continue
            seat = message.facts.get("eliminated")
            if seat is not None:
                eliminated.add(int(seat))
        counts: Counter[int] = Counter()
        if not eliminated:
            return counts
        for message in self.inbox:
            if message.kind != "ballot":
                continue
            seat = message.facts.get("seat")
            target = message.facts.get("target")
            if seat is None or target is None:
                continue
            if int(target) in eliminated:
                counts[int(seat)] += 1
        return counts

    # ------------------------------------------------------------------ 校验

    def _check_statement(self, payload: Mapping[str, Any], alive: Sequence[int]) -> list[str]:
        problems: list[str] = []
        text = str(payload.get("text") or "").strip()
        if not text:
            problems.append("发言是空的")
        elif len(text) > MAX_STATEMENT_CHARS:
            problems.append(f"发言超过 {MAX_STATEMENT_CHARS} 字")

        target = payload.get("target")
        if target is not None:
            if int(target) == self.seat:
                problems.append("指认了自己")
            elif int(target) not in set(alive):
                problems.append(f"{target} 号不在场上")
        if text:
            problems.extend(
                self._privacy_problems(
                    text, action=str(payload.get("action") or DEFAULT_STATEMENT_ACTION)
                )
            )
        return problems

    def _privacy_problems(self, text: str, *, action: str) -> list[str]:
        """公开发言的内容级校验（启发式，不上模型）：别复述私聊原文、狼人别点名队友。

        只对模型候选生效（`express` 调 `_check_statement`），规则兜底发言是自家措辞，天生安全。
        `action == "report"` 是公开自己查到的阵营（预言家的本职），这时和查验回执重合是正常的，
        所以豁免；其它立场一旦和私聊原文有长句重合，就判疑似泄露。
        """
        problems: list[str] = []
        if action != "report":
            private = [message.text for message in self.inbox if message.channel == PRIVATE]
            hit = shared_substring(text, private, LEAK_SUBSTRING_CHARS)
            if hit:
                problems.append(f"疑似泄露私聊内容（和私聊原文重合「{hit}」）")
        # 已知局限：豁免的钥匙是候选发言的 action，而 action 是模型自报的，狼人可以把 action
        # 填成 report 绕过检查。这里本来就是启发式校验，可以接受；要加固就改成「重合的那条私聊
        # 是查验回执（facts 里有 check.target）且它的 target 和这次发言的 target 一致」才豁免，
        # 那样自报 report 也对不上回执。
        if self.allies:
            mentioned = [seat for seat in sorted(self.allies) if mentions_seat(text, seat)]
            if len(mentioned) >= ALLY_EXPOSE_MENTIONS:
                problems.append("疑似暴露队友：" + "、".join(f"{seat} 号" for seat in mentioned))
        return problems

    def _check_night_action(
        self,
        payload: Mapping[str, Any],
        phase: str,
        alive: Sequence[int],
        fallback: Mapping[str, Any],
    ) -> list[str]:
        """校验模型给的夜间动作。规则版怎么走，模型就怎么走。"""
        problems: list[str] = []
        if payload.get("phase") not in (None, "", phase):
            problems.append("阶段对不上")

        target = payload.get("target")
        effect = str(payload.get("effect") or "")
        character = self.board.characters.get(phase)
        can_pass = bool(character and character.can_pass)
        candidates = fallback.get("candidates")
        # 人类指定了效果时，按那个效果的约束校验，不套规则兜底的候选名单
        if effect and can_pass:
            if effect == "save":
                # 救人只能救今晚被袭击的那个
                attacked = getattr(self, "attacked", None)
                if target is None:
                    problems.append("救人要给目标")
                elif attacked is not None and int(target) != int(attacked):
                    problems.append("解药只能救今晚被袭击的人")
                elif int(target) not in set(alive):
                    problems.append(f"{target} 号不在场上")
            elif effect == "poison":
                # 毒人可以选场上任意活人（规则里 witch 的 suspects 排除了队友）
                if target is None:
                    problems.append("毒人要给目标")
                elif int(target) not in set(alive):
                    problems.append(f"{target} 号不在场上")
            # effect 为空字符串 = 明确弃权，target 必须是 None
            elif target is not None:
                problems.append("不用技能时不该给目标")
            return problems
        if target is not None:
            if int(target) not in set(alive):
                problems.append(f"{target} 号不在场上")
            elif candidates is not None and int(target) not in {int(seat) for seat in candidates}:
                problems.append(f"{target} 号这一夜不能选")
            elif candidates is None and int(target) == self.seat and fallback.get("target") != self.seat:
                problems.append("不能选自己")
        elif fallback.get("target") is not None and not can_pass:
            # 规则建议有目标但模型没给： normally 不合法；但女巫这类可以主动不用技能
            problems.append("缺少目标")
        return problems

    # ------------------------------------------------------------------ 模型输出

    def _parse_statement(self, raw: str) -> dict[str, Any]:
        data = parse_json_object(raw)
        target = data.get("target")
        action = str(data.get("action") or "").strip()
        return {
            "text": str(data.get("text") or "").strip(),
            "target": None if target in (None, "", "null") else int(target),
            "claim_role": str(data.get("claim_role") or ""),
            # 模型没给（或给了不认识的）立场时按 accuse 处理，和旧数据一致
            "action": action if action in STATEMENT_ACTIONS else DEFAULT_STATEMENT_ACTION,
        }

    def _parse_action(self, raw: str) -> dict[str, Any]:
        data = parse_json_object(raw)
        target = data.get("target")
        return {
            "phase": str(data.get("phase") or ""),
            "target": None if target in (None, "", "null") else int(target),
            "effect": str(data.get("effect") or ""),
        }

    # ------------------------------------------------------------------ 提示词

    def _system_prompt(self, task: str) -> str:
        """三条链路共用的开头：身份、角色规则、板子信息。"""
        board = "、".join(
            f"{role}×{self.board.distribution.count(role)}"
            for role in dict.fromkeys(self.board.distribution)
        )
        return (
            f"你是狼人杀里的 {self.seat} 号玩家，身份是{self.role}（{self.camp}）。\n"
            f"你的角色规则：{self.character.describe}\n"
            f"本局板子：{self.board.size} 人（{board}）。\n"
            f"{task}"
        )

    def _team_system(self, phase: str) -> str:
        return self._system_prompt(
            f"现在是{phase}阶段的队伍讨论：只用一句中文说你的意见"
            f"（不超过 {MAX_TEAM_TALK_CHARS} 字），直接输出这句话，不要报身份、不要 JSON。"
        )

    def _death_system(self) -> str:
        return self._system_prompt(
            "你刚刚出局，如果你的身份有出局技能，现在可以发动；"
            '只输出 JSON：{"phase": "身份", "target": 几号}，没有技能就输出 {"target": null}。'
        )

    def _death_prompt(self, cause: str, alive: Sequence[int]) -> str:
        cause_text = {"poison": "被毒死", "vote": "被投票放逐", "attack": "被 Werewolf 杀死"}.get(
            cause, "出局"
        )
        return (
            f"你{cause_text}出局了。\n"
            f"场上还活着：{'、'.join(str(seat) for seat in alive)}。\n"
            f"你收到的全部消息（含只有你能看到的私聊）：\n{self.transcript(limit=20)}\n"
            "如果要发动出局技能，给出你的目标。"
        )

    def _team_prompt(self, phase: str, alive: Sequence[int], round_no: int) -> str:
        return (
            f"场上还活着：{'、'.join(str(seat) for seat in alive)}。\n"
            f"队伍频道（只有你和队友看得到）：\n{self._team_transcript()}\n"
            f"大屏（公开信息）：\n{self.transcript(limit=20, channel=PUBLIC)}\n"
            f"这是第 {round_no} 轮讨论，说一句你的意见。"
        )

    def _team_transcript(self) -> str:
        """队伍频道里的消息：多人私聊就是队伍频道。"""
        rows = [
            f"#{message.seq} {message.text}"
            for message in self.inbox
            if message.channel == PRIVATE and len(message.audience) > 1
        ]
        return "\n".join(rows[-10:]) if rows else "（还没有人说话）"

    def _statement_system(self) -> str:
        return self._system_prompt(
            f"现在轮到你公开发言：只用中文，不超过 {MAX_STATEMENT_CHARS} 字，"
            "只能引用大屏上公开出现过的事，不要提别人看不到的内容；"
            "先回应前面玩家的发言（谁可疑、谁值得保），再结合自己的发言位置给出判断；"
            "被指认时先正面回应。"
            "发言前可以调用 retrieve_similar 检索相似历史对局里同角色在相似阶段是怎么发言的，"
            "参考他们的措辞和立场，但不要照抄——你要结合自己这局的实际情报。"
            '只输出 JSON：{"text": "发言正文", "target": 3, "action": "accuse", '
            '"claim_role": "想认的身份"}；'
            "action 是指这次的立场：accuse（指认，默认）、defend（保人）、report（报自己的查验）。"
        )

    def speak_context(self) -> tuple[str, str]:
        """自己的发言位置，和前面已经发过言的人（用于组织发言）。"""
        order: tuple[int, ...] = ()
        for message in reversed(self.inbox):
            if message.kind == "order":
                order = tuple(int(seat) for seat in message.facts.get("order") or ())
                break
        if not order:
            return "你是本轮第一个发言的人。", ""
        if self.seat not in order:
            return "", ""
        place = order.index(self.seat) + 1
        earlier = order[: place - 1]
        position = f"你是第 {place} 个发言（共 {len(order)} 人）。"
        if not earlier:
            return position + " 你是第一个开口的。", ""
        seats = "、".join(f"{seat} 号" for seat in earlier)
        return position + f" 在你之前发言的是：{seats}。", seats

    def _vote_system(self) -> str:
        return self._system_prompt(
            "现在投票放逐一名玩家，只能投场上还活着的人，不要和自己公开发表的立场矛盾。"
            "投票前可以先用工具核对判断（reason 重新推理一遍、top_suspects 看推测表、"
            "read_board 或 search_statements 查发言和票型），"
            "也可以 retrieve_similar 检索相似局里同角色在相似处境下投了谁、投完之后局势怎么走。"
            '只输出 JSON：{"target": 3}，弃票时 target 用 null。'
        )

    def _action_system(self, phase: str) -> str:
        character = self.board.characters.get(phase)
        pass_hint = (
            "；这个技能可以不用，决定不用时 target 用 null" if character and character.can_pass else ""
        )
        return self._system_prompt(
            f"现在是夜间行动阶段（{phase}），只有你和法官知道你的选择。"
            "决策前可以调用 retrieve_similar 检索相似局里同角色在相似阶段"
            "（夜间技能、刀口、查验、救人/毒人）是怎么选目标的，参考他们的选择和后续局势。"
            f'只输出 JSON：{{"phase": "{phase}", "target": 3}}；target 必须是给出的可选项之一{pass_hint}。'
        )

    def _belief_text(self, alive: Sequence[int]) -> str:
        rows = [
            f"{seat} 号：推测 {guess.role}（置信度 {guess.confidence:.2f}，{guess.reason}）"
            for seat in sorted(alive)
            if seat != self.seat
            for guess in (self.belief.guess(seat),)
        ]
        return "\n".join(rows) if rows else "暂无可推测的对象"

    def statement_prompt(self, alive: Sequence[int]) -> str:
        suspects = self.suspects(alive)
        top = suspects[0] if suspects else None
        position, earlier = self.speak_context()
        return (
            f"场上还活着：{'、'.join(str(seat) for seat in alive)}。\n"
            f"你的发言位置：{position}\n"
            f"{'你要先回应上面这些人的发言，再给出自己的怀疑对象和理由。' if earlier else ''}\n"
            f"你的推测表：\n{self._belief_text(alive)}\n"
            f"你的判断：{self._belief_summary(alive)}"
            f"你打算指认 {top} 号。\n"
            f"大屏（公开信息）：\n{self.transcript(limit=30, channel=PUBLIC)}\n"
            "你在公屏上看到和说过的事：\n"
            f"{chr(10).join(self.public_notes[-5:]) or '（公屏上还没有内容）'}\n"
            "给出你的公开发言。"
        )

    def _vote_prompt(self, alive: Sequence[int]) -> str:
        return (
            f"场上还活着：{'、'.join(str(seat) for seat in alive)}。\n"
            f"你的推测表：\n{self._belief_text(alive)}\n"
            f"你的判断：{self._belief_summary(alive)}\n"
            "给出你的投票目标。"
        )

    def _night_prompt(
        self, phase: str, alive: Sequence[int], candidates: Sequence[int]
    ) -> str:
        lines = [
            f"你在执行夜间技能：{phase}。",
            f"场上还活着：{'、'.join(str(seat) for seat in alive)}。",
        ]
        if candidates:
            lines.append(f"这一夜你可以选的目标：{'、'.join(str(seat) for seat in candidates)}。")
        lines += [
            f"你的私有记忆：\n{chr(10).join(self.notes[-5:])}",
            f"你收到的全部消息（含只有你能看到的私聊）：\n{self.transcript(limit=20)}",
        ]
        return "\n".join(lines)
