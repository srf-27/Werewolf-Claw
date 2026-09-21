"""玩家 Agent：一个 Node + Flow 写成的闭环。

每个环节一个 Node，连成一条 Flow：

    得知身份 -> 读取大屏 -> 推理 -> 决策 -> 表达 / 投票 / 夜间行动 / 反思
                                                  |      |        |
                                                  +------+--------+
                                                         v
                                                    回到读取大屏
                                              （这一轮的活干完了就结束）

法官要什么，`DecideNode` 就往哪条支路走；支路做完回到「读取大屏」，下一轮再从
那里进来，闭环就接上了。`ReadBoardNode` 在「这一个请求已经产出过产物」时直接
返回「结束」，所以 Flow 转一圈就停，不会自己转下去。

信息隔离有两道闸门：构造时只给一张身份卡，`receive()` 按 `Message.visible_to()`
丢掉不属于自己的消息。

不真正信任模型：表达和夜间动作先让模型产出，产物过 `_check_*`，不通过就带上原因
重写一次，再不过就用规则兜底，并记进私有记忆。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from werewolf_claw.core.node import DEFAULT_ACTION, Flow, Node

from .judge_agent import CAMP_GOOD, CAMP_WOLF, GUARD, SEER, WITCH, WOLF, Message

# 模型入口：(prompt, system) -> 文本。省略就是纯规则模式。
ChatFn = Callable[..., str]

# 一条公开发言的字数上限。
MAX_STATEMENT_CHARS = 200

# 模型输出被打回后最多重写几次。
MAX_REWRITE = 1

# 法官这一次要什么。
KIND_NIGHT = "夜间"
KIND_SPEECH = "发言"
KIND_BALLOT = "投票"
KIND_REFLECT = "反思"

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


# ------------------------------------------------------------------ 上下文对象


@dataclass
class Belief:
    """推理节点的产物：对每个座位的怀疑分和理由。"""

    day: int = 0
    suspicions: dict[int, float] = field(default_factory=dict)
    reasons: dict[int, str] = field(default_factory=dict)
    summary: str = ""

    def top(self, alive: Sequence[int] | None = None) -> int | None:
        """最可疑的那个座位；给了 `alive` 就只在场上的玩家里挑。"""
        members = None if alive is None else set(alive)
        ranked = sorted(self.suspicions.items(), key=lambda item: -item[1])
        for seat, _ in ranked:
            if members is None or seat in members:
                return seat
        return None

    def score(self, seat: int) -> float:
        return self.suspicions.get(seat, 0.0)


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
    outcome: Mapping[str, Any] = field(default_factory=dict)
    seq: int = 0


@dataclass
class Turn:
    """一次 Flow 里传下去的东西：请求、已经答过没有、产物。"""

    request: Request
    answered: int = 0
    decision: Decision | None = None
    result: Any = None


# ------------------------------------------------------------------ 各个 Node


class RoleNode(Node):
    """得知身份。第一次跑的时候把身份卡和队友写进私有记忆，之后直接放行。"""

    def __init__(self, player: "PlayerAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.player = player

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        if not self.player.knows_role:
            self.player.learn_role()
        return "读取", payload


class ReadBoardNode(Node):
    """读取大屏：把还没读过的新消息收进上下文。

    这一个请求已经产出过产物就直接收尾，所以 Flow 转一圈就停。
    """

    def __init__(self, player: "PlayerAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.player = player

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        if payload.answered == payload.request.seq:
            return "结束", payload
        self.player.read_board()
        return "推理", payload


class ReasonNode(Node):
    """推理：算一份显式的信念状态。

    反思这一轮不重算：反思比的是「这一轮行动时的判断」和实际结果，重算会把要
    反思的那份判断覆盖掉。
    """

    def __init__(self, player: "PlayerAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.player = player

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        if payload.request.kind != KIND_REFLECT:
            self.player.belief = self.player.reason(payload.request.alive)
        return "决策", payload


class DecideNode(Node):
    """决策：按法官要的东西挑一条支路。"""

    def __init__(self, player: "PlayerAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.player = player

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        payload.decision = self.player.decide(payload.request.alive)
        kind = payload.request.kind
        if kind == KIND_NIGHT:
            return "夜间", payload
        if kind == KIND_SPEECH:
            return "发言", payload
        if kind == KIND_BALLOT:
            return "投票", payload
        if kind == KIND_REFLECT:
            return "反思", payload
        raise ValueError(f"不认识的请求类型：{kind}")


class SpeakNode(Node):
    """表达：把决策说成一句话，交给校验和回退。"""

    def __init__(self, player: "PlayerAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.player = player

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        assertion = payload.decision or Decision()
        payload.result = self.player.express(assertion, payload.request.alive)
        payload.answered = payload.request.seq
        return "读取", payload


class BallotNode(Node):
    """投票：目标必须在场上，不合格就退到规则兜底。"""

    def __init__(self, player: "PlayerAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.player = player

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        decision = payload.decision or Decision()
        payload.result = self.player.cast_ballot(payload.request.alive, decision)
        payload.answered = payload.request.seq
        return "读取", payload


class NightActionNode(Node):
    """夜间行动：夜间动作的决策就是动作本身，所以和校验连在一起。"""

    def __init__(self, player: "PlayerAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.player = player

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        payload.result = self.player.choose_night_action(
            payload.request.phase, payload.request.alive
        )
        payload.answered = payload.request.seq
        return "读取", payload


class ReflectNode(Node):
    """反思：对比自己的预测和实际结果，写进私有记忆。"""

    def __init__(self, player: "PlayerAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.player = player

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        outcome = payload.request.outcome
        day = int(outcome.get("day") or 0)
        payload.result = self.player.write_reflection(day, outcome)
        payload.answered = payload.request.seq
        return "读取", payload


class DoneNode(Node):
    """收尾：产物已经放在 payload 里，交回给调用方。"""

    def exec(self, payload: Turn) -> tuple[str, Turn]:
        return DEFAULT_ACTION, payload


# ------------------------------------------------------------------ Agent


class PlayerAgent:
    """一个座位上的玩家。对外只暴露法官需要的那几个方法。"""

    def __init__(
        self,
        seat: int,
        role: str,
        *,
        chat: ChatFn | None = None,
        allies: Iterable[int] = (),
    ) -> None:
        self.seat = seat
        self.role = role
        self.chat = chat
        self.allies = set(allies)

        self.inbox: list[Message] = []  # 投给自己的消息
        self.notes: list[str] = []  # 私有记忆：身份、查验结果、发言账本、反思
        self.belief = Belief()
        self.knows_role = False

        self._seen = 0  # 收到了哪条消息，用来去重
        self._read = 0  # 读到哪条消息，交给「读取大屏」节点推
        self._seq = 0  # 第几次请求
        self._used_potions: set[str] = set()
        self._flow = self.build_flow()

    def build_flow(self) -> Flow:
        """把各个 Node 连成闭环。返回的 Flow 从「得知身份」进，从「收尾」出。"""
        role = RoleNode(self)
        read = ReadBoardNode(self)
        reason = ReasonNode(self)
        decide = DecideNode(self)
        speak = SpeakNode(self)
        ballot = BallotNode(self)
        night = NightActionNode(self)
        reflect = ReflectNode(self)
        done = DoneNode()

        role - "读取" >> read
        read - "推理" >> reason
        reason - "决策" >> decide
        decide - "发言" >> speak
        decide - "投票" >> ballot
        decide - "夜间" >> night
        decide - "反思" >> reflect
        # 支路做完回到「读取大屏」，下一轮再从那里进，闭环就是这么接上的
        speak - "读取" >> read
        ballot - "读取" >> read
        night - "读取" >> read
        reflect - "读取" >> read
        # 这一轮的活干完了，收尾
        read - "结束" >> done
        return Flow(role)

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
            if message.kind == "role":
                self.notes.append(
                    f"我的身份是{message.facts.get('role')}（{message.facts.get('camp')}）"
                )
        return len(fresh)

    def transcript(self, *, limit: int = 40) -> str:
        return "\n".join(
            f"#{message.seq} 第 {message.day} 天 {message.text}"
            for message in self.inbox[-limit:]
        )

    # ------------------------------------------------------------------ 法官协议

    def night_action(self, phase: str, alive: Sequence[int]) -> dict[str, Any]:
        """法官调用：报一次夜间动作。"""
        result = self._run(Request(kind=KIND_NIGHT, phase=phase, alive=tuple(alive)))
        return result if isinstance(result, dict) else self._rule_night_action(phase, alive)

    def statement(self, alive: Sequence[int]) -> dict[str, Any]:
        """法官调用：报一次公开发言。"""
        result = self._run(Request(kind=KIND_SPEECH, alive=tuple(alive)))
        return result if isinstance(result, dict) else self._rule_statement(self.belief)

    def ballot(self, alive: Sequence[int]) -> dict[str, Any]:
        """法官调用：报一次投票。"""
        result = self._run(Request(kind=KIND_BALLOT, alive=tuple(alive)))
        return result if isinstance(result, dict) else {"target": None, "reason": "无法决策"}

    def reflect(self, day: int, outcome: Mapping[str, Any]) -> str:
        """法官调用：把这一天的结果交给玩家，由他自己写反思。"""
        result = self._run(Request(kind=KIND_REFLECT, outcome=outcome))
        return result if isinstance(result, str) else ""

    def _run(self, request: Request) -> Any:
        """跑一次闭环：读取 -> 推理 -> 决策 -> 支路 -> 回到读取 -> 收尾。"""
        request.seq = self._seq
        self._seq += 1
        _, turn = self._flow.run(Turn(request=request))
        return turn.result

    # ------------------------------------------------------------------ 闭环各步

    def learn_role(self) -> None:
        """得知身份：记下自己是几号、什么身份、队友是谁。"""
        self.knows_role = True
        if self.role == WOLF and self.allies:
            self.notes.append("队友：" + "、".join(f"{seat} 号" for seat in sorted(self.allies)))

    def read_board(self) -> int:
        """读取大屏：把没读过的新消息标成已读，返回读了几条。"""
        fresh = [message for message in self.inbox if message.seq > self._read]
        if not fresh:
            return 0
        self._read = fresh[-1].seq
        return len(fresh)

    def reason(self, alive: Sequence[int]) -> Belief:
        """推理：用公开信息和自己的私有信息算一份怀疑分。

        这里是 ReAct 节点的位置。雏形给的是规则先验（基线 + 自己的查验结果），
        真接模型时在这一步查大屏、查某人的历史发言，再把结论盖到 suspicions 上。
        """
        suspicions: dict[int, float] = {}
        reasons: dict[int, str] = {}
        for seat in alive:
            if seat == self.seat or seat in self.allies:
                continue  # 自己人先排除，狼队不会互相怀疑
            suspicions[seat] = 1.0
            reasons[seat] = "基线"

        for target, camp in self._checks():
            if target not in suspicions:
                continue
            if camp == CAMP_WOLF:
                suspicions[target] = 5.0
                reasons[target] = "我查验过是狼人"
            elif camp == CAMP_GOOD:
                suspicions[target] = 0.0
                reasons[target] = "我查验过是好人"

        day = self.inbox[-1].day if self.inbox else 0
        top = max(suspicions.items(), key=lambda item: item[1], default=None)
        summary = f"第 {day} 天最可疑的是 {top[0]} 号。" if top else "场上没有其他人。"
        return Belief(day=day, suspicions=suspicions, reasons=reasons, summary=summary)

    def decide(self, alive: Sequence[int]) -> Decision:
        """决策：挑一个目标，并带上理由。"""
        target = self.belief.top(alive)
        if target is None:
            target = next((seat for seat in alive if seat != self.seat), None)
        return Decision(target=target, reason=self.belief.reasons.get(target, "票型可疑"))

    def express(self, decision: Decision, alive: Sequence[int]) -> dict[str, Any]:
        """表达：产出一段公开发言。模型先写，校验不过就重写，再不过用规则版。"""
        draft = self._rule_statement(self.belief)
        if self.chat is None:
            self.notes.append(f"第 {self.belief.day} 天我公开说：{draft['text']}")
            return draft

        problems: list[str] = []
        prompt = self._statement_prompt(alive, decision)
        for attempt in range(MAX_REWRITE + 1):
            try:
                candidate = self._parse_statement(
                    self.chat(prompt, system=self._statement_system())
                )
            except Exception:
                problems = ["模型输出无法解析"]
                break
            problems = self._check_statement(candidate, alive)
            if not problems:
                self.notes.append(f"第 {self.belief.day} 天我公开说：{candidate['text']}")
                return candidate
            prompt = f"{prompt}\n\n上一次的发言不合格，原因：{'；'.join(problems)}。请重写。"

        self.notes.append("表达节点回退到规则输出：" + "；".join(problems))
        return draft

    def cast_ballot(self, alive: Sequence[int], decision: Decision) -> dict[str, Any]:
        """投票：目标必须还在场上，否则退回兜底目标。"""
        target = decision.target
        if target is not None and target not in set(alive):
            self.notes.append(f"投票回退：{target} 号不在场上")
            target = self.decide(alive).target

        if self.chat is not None:
            try:
                data = parse_json_object(
                    self.chat(self._vote_prompt(alive), system=self._vote_system())
                )
                chosen = data.get("target")
                if chosen is not None and int(chosen) in set(alive) and int(chosen) != self.seat:
                    target = int(chosen)
                elif chosen is not None:
                    self.notes.append(f"投票回退：模型投的 {chosen} 号不合法")
            except Exception:
                self.notes.append("投票回退：模型输出无法解析")

        return {
            "target": target,
            "reason": self.belief.reasons.get(target, "票型可疑") if target else "",
        }

    def write_reflection(self, day: int, outcome: Mapping[str, Any]) -> str:
        """反思：对比自己的预测和实际结果，写进私有记忆。闭环的最后一环。"""
        suspected = self.belief.top()
        deaths = list(outcome.get("deaths") or ())
        eliminated = outcome.get("eliminated")
        actual = eliminated if eliminated is not None else (deaths[0] if deaths else None)

        text = f"第 {day} 天回顾："
        if suspected is None:
            text += "这一轮我没有明确的怀疑对象"
        else:
            text += f"我最怀疑 {suspected} 号"
        if actual is None:
            text += "，今天没有人出局。"
        elif suspected is None:
            text += f"，实际出局的是 {actual} 号，没有可对比的判断。"
        else:
            agree = "与预测一致" if actual == suspected else "与预测不一致"
            text += f"，实际出局的是 {actual} 号，{agree}。"
        self.notes.append(text)
        return text

    # ------------------------------------------------------------------ 私有信息

    def _checks(self) -> list[tuple[int, str]]:
        """自己查验过的结果，只来自投给自己的私聊消息。"""
        results: list[tuple[int, str]] = []
        for message in self.inbox:
            if message.facts.get("phase") != SEER:
                continue
            target, camp = message.facts.get("target"), message.facts.get("camp")
            if target is not None and camp:
                results.append((int(target), str(camp)))
        return results

    def _attacked_tonight(self) -> int | None:
        """女巫被叫醒时，法官会在私聊里告诉她今晚谁被袭击。"""
        for message in reversed(self.inbox):
            if "attacked" in message.facts:
                attacked = message.facts["attacked"]
                return None if attacked is None else int(attacked)
        return None

    # ------------------------------------------------------------------ 规则版决策

    def _rule_statement(self, belief: Belief) -> dict[str, Any]:
        """规则版发言：预言家报查验，其他人指认自己最怀疑的那个。"""
        checks = self._checks()
        if self.role == SEER and checks:
            target, camp = checks[-1]
            label = "狼人" if camp == CAMP_WOLF else "好人"
            return {
                "text": f"我是 {self.seat} 号，我跳预言家。{target} 号是{label}，我查验过。",
                "claim_role": SEER,
                "target": target,
            }

        target = belief.top()
        if target is None:
            return {"text": f"我是 {self.seat} 号，我这边没有新的信息，先过。", "target": None}
        reason = belief.reasons.get(target, "票型可疑")
        return {"text": f"我是 {self.seat} 号。我觉得 {target} 号最像狼，{reason}。", "target": target}

    def _rule_night_action(self, phase: str, alive: Sequence[int]) -> dict[str, Any]:
        """规则版夜间动作。每个角色都有一个「不用技能也不违规」的选项。"""
        others = [seat for seat in alive if seat != self.seat]

        if phase == WOLF:
            goods = [seat for seat in others if seat not in self.allies]
            return {
                "phase": WOLF,
                "target": goods[0] if goods else None,
                "reason": "先挑队友之外的目标",
            }
        if phase == GUARD:
            return {"phase": GUARD, "target": self.seat, "reason": "先守自己"}
        if phase == SEER:
            checked = {target for target, _ in self._checks()}
            rest = [seat for seat in others if seat not in checked]
            return {
                "phase": SEER,
                "target": rest[0] if rest else None,
                "reason": "查一个还没查过的人",
            }
        if phase == WITCH:
            attacked = self._attacked_tonight()
            if attacked is not None and "解药" not in self._used_potions:
                self._used_potions.add("解药")
                return {"phase": WITCH, "target": attacked, "save": True, "reason": "救下被袭击的人"}
            return {
                "phase": WITCH,
                "target": None,
                "save": False,
                "poison": None,
                "reason": "留药",
            }
        return {"phase": phase, "target": None}

    def choose_night_action(self, phase: str, alive: Sequence[int]) -> dict[str, Any]:
        """夜间动作：先算好规则兜底，再让模型在合法集合里挑，不合格就退回。"""
        fallback = self._rule_night_action(phase, alive)
        if self.chat is None:
            return fallback

        try:
            candidate = self._parse_action(
                self.chat(self._night_prompt(phase, alive), system=self._action_system())
            )
        except Exception:
            self.notes.append("夜间动作回退：模型输出无法解析")
            return fallback

        problems = self._check_night_action(candidate, phase, alive)
        if problems:
            self.notes.append("夜间动作回退：" + "；".join(problems))
            return fallback
        return candidate

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
        return problems

    def _check_night_action(
        self, payload: Mapping[str, Any], phase: str, alive: Sequence[int]
    ) -> list[str]:
        problems: list[str] = []
        if payload.get("phase") not in (None, phase):
            problems.append("阶段对不上")
        target = payload.get("target")
        if target is not None and int(target) not in set(alive):
            problems.append(f"{target} 号不在场上")
        if phase == SEER and target is not None and int(target) == self.seat:
            problems.append("预言家不能查自己")
        if phase == WOLF and target is None:
            problems.append("狼人必须给出目标")
        return problems

    # ------------------------------------------------------------------ 模型输出

    def _parse_statement(self, raw: str) -> dict[str, Any]:
        data = parse_json_object(raw)
        target = data.get("target")
        return {
            "text": str(data.get("text") or "").strip(),
            "target": None if target in (None, "", "null") else int(target),
            "claim_role": str(data.get("claim_role") or ""),
        }

    def _parse_action(self, raw: str) -> dict[str, Any]:
        data = parse_json_object(raw)
        target = data.get("target")
        poison = data.get("poison")
        return {
            "phase": str(data.get("phase") or ""),
            "target": None if target in (None, "", "null") else int(target),
            "save": bool(data.get("save")),
            "poison": None if poison in (None, "", "null") else int(poison),
            "reason": str(data.get("reason") or ""),
        }

    # ------------------------------------------------------------------ 提示词

    def _statement_system(self) -> str:
        return (
            f"你是狼人杀里 {self.seat} 号玩家，身份是{self.role}。"
            f"现在轮到你公开发言：只用中文，不超过 {MAX_STATEMENT_CHARS} 字，"
            "只能引用大屏上公开出现过的事，不要提别人看不到的内容；被指认时先正面回应。"
            '只输出 JSON：{"text": "发言正文", "target": 3, "claim_role": "预言家"}。'
        )

    def _vote_system(self) -> str:
        return (
            f"你是狼人杀里 {self.seat} 号玩家，身份是{self.role}。"
            "现在投票放逐一名玩家，只能投场上还活着的人，不要和自己公开发表的立场矛盾。"
            '只输出 JSON：{"target": 3}，弃票时 target 用 null。'
        )

    def _action_system(self) -> str:
        return (
            f"你是狼人杀里 {self.seat} 号玩家，身份是{self.role}。"
            "现在是夜间行动阶段，只有你和法官知道你的选择。"
            '只输出 JSON：{"phase": "wolf", "target": 3, "save": false, "poison": null}。'
        )

    def _statement_prompt(self, alive: Sequence[int], decision: Decision) -> str:
        return (
            f"场上还活着：{'、'.join(str(seat) for seat in alive)}。\n"
            f"你的判断：{self.belief.summary} 你现在最怀疑 {decision.target} 号"
            f"（{decision.reason}）。\n"
            f"你看到的内容：\n{self.transcript(limit=30)}\n"
            f"你的私有记忆：\n{chr(10).join(self.notes[-5:])}\n"
            "给出你的公开发言。"
        )

    def _vote_prompt(self, alive: Sequence[int]) -> str:
        return (
            f"场上还活着：{'、'.join(str(seat) for seat in alive)}。\n"
            f"你的判断：{self.belief.summary}\n"
            "给出你的投票目标。"
        )

    def _night_prompt(self, phase: str, alive: Sequence[int]) -> str:
        detail = [
            f"你在执行夜间动作，阶段是 {phase}。",
            f"场上还活着：{'、'.join(str(seat) for seat in alive)}。",
            f"你看到的内容：\n{self.transcript(limit=20)}",
        ]
        if phase == WITCH:
            detail.append(f"今晚被袭击的是：{self._attacked_tonight()} 号。")
        return "\n".join(detail)
