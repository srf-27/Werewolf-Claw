"""
法官 Agent：

法官只做三件事：
把该说的话说出去、
按板子给的节奏叫醒特殊身份、在关键节点和系统级对齐存活情况。

workflows：
    开场 [pub] -> 发身份 [priv] -> 通知系统进入夜晚
        -> NIGHT：按板子给的顺序逐个阶段
           （叫醒 [pub] + 这个阶段的人私聊问答 [priv] + 固定等待 [pub]）
        -> 天亮 [pub] -> 公布存活情况 [pub] 并与系统对齐存活数
        -> 发言 -> 投票通知 -> 投票 -> 计票 -> 判胜负 [pub]
        -> 继续则进入下一夜

"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from werewolf_claw.boards import DEFAULT_BOARD
from werewolf_claw.core.board import Board
from werewolf_claw.core.node import DEFAULT_ACTION, Flow, Node
from werewolf_claw.core.player import PlayerProtocol
from werewolf_claw.core.screen import PRIVATE, Message, Screen
from werewolf_claw.core.system import PHASE_DAY, PHASE_NIGHT, LocalSystem, SystemProtocol

# 达到天数上限时的收尾说法。
DRAW = "平局"

# 多人同夜行动时的讨论轮数：狼人先说意见，再各自投票
TEAM_TALK_ROUNDS = 1

# 每个夜间阶段之间等多久（秒），倍速会压缩它
PHASE_PAUSE = 0.6

# 每条公开播报停留多久（秒）：大屏上的悬停框显示完这一句，才发下一句
ANNOUNCE_PAUSE = 3.0

# 播报回调：(事件类型, 事实) -> 中文台词。
NarrateFn = Callable[[str, Mapping[str, Any]], str]


@dataclass
class NightState:
    """一夜收到的原始动作：阶段 -> 座位 -> 动作。天亮时由法官结算。"""

    actions: dict[str, dict[int, dict[str, Any]]] = field(default_factory=dict)

    def put(self, phase: str, seat: int, action: Mapping[str, Any]) -> None:
        self.actions.setdefault(phase, {})[seat] = dict(action)

    def of_effect(self, effect: str) -> list[dict[str, Any]]:
        """所有效果属于这一类的动作，按阶段顺序排。"""
        return [
            action
            for phase in self.actions
            for action in self.actions[phase].values()
            if action.get("effect") == effect
        ]


def deal_roles(board: Board, *, seed: int | None = None) -> dict[int, str]:
    """发身份：把板子上的身份洗牌，按座位号从 1 开始发。"""
    roles = list(board.distribution)
    random.Random(seed).shuffle(roles)
    return dict(zip(range(1, board.size + 1), roles))


# ------------------------------------------------------------------ Node


class OpeningNode(Node):
    """opening[pub]：报人数和座位号。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        self.judge.say("opening", {"seats": self.judge.seats, "count": len(self.judge.seats)})
        return "发身份", None


class RollRoleNode(Node):
    """rollrole[priv]：把身份和位置 id 私聊给本人。

    身份卡不经过 `narrate`，因为它是事实而不是措辞；队友不写在身份卡里，
    狼人到狼人阶段跟队友共用一次对话时才知道。
    """

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        for seat in self.judge.seats:
            role = self.judge.roles[seat]
            facts = {"seat": seat, "role": role, "camp": self.judge.board.camps[role]}
            self.judge.tell([seat], self.judge.template("role", facts), kind="role", facts=facts)
        self.judge.deliver()
        return "天黑", None


class NightFallNode(Node):
    """天黑：通知系统进入夜晚，清掉上一夜的暂存，把叫醒顺序交下去。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        self.judge.begin_night()
        self.judge.system.set_phase(PHASE_NIGHT)
        return "叫醒", self.judge.night_schedule()


class AskActionNode(Node):
    """NIGHT：按板子给的顺序叫醒，一个阶段转一圈。

    每个阶段三步，和 rules 里的 askAction + waiting 对应：

    1. 叫醒 [pub]：次序固定，这个身份死没死都照叫；
    2. 私聊问答 [priv]：只联系这个阶段还活着的人。阶段里有多个行动者时他们共用
       一次对话，名单和彼此的提案都在这条通道里；
    3. 固定等待 [pub]：等他们闭眼再进下一阶段，避免用时长差看出谁出局。
    """

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Sequence[str]) -> tuple[str, Any]:
        if not payload:
            return "天亮", None

        phase = payload[0]
        self.judge.say("wake", {"phase": phase})
        self.judge.open_phase(phase)
        self.judge.close_phase(phase)
        self.judge.say("phase_over", {"phase": phase})
        return "叫醒", payload[1:]


class DawnNode(Node):
    """WAKE 天亮：结算前一夜，公布天亮和出局情况。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        self.judge.system.set_phase(PHASE_DAY)  # 一夜结束，系统天数加一
        self.judge.day += 1
        self.judge.resolve_night()
        # 公布的是「昨夜」名单（day_deaths），不是最近一次 apply_deaths 的名单：
        # 白天票出局会改写 last_deaths，用它会让夜里公布的结果被后来的人盖掉
        self.judge.say("result", {"day": self.judge.day, "deaths": list(self.judge.day_deaths)})
        self.judge.deliver()
        return "存活", None


class CheckAliveNode(Node):
    """checkalive[pub]：公布存活情况，和系统对齐存活数，准备进发言阶段。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        alive = self.judge.alive_seats()
        self.judge.system.sync_alive(alive)
        self.judge.say("alive", {"alive": list(alive), "count": len(alive)})
        self.judge.deliver()
        return "发言", None


class SpeechNode(Node):
    """发言阶段：法官抽顺序，系统命令每人发言并把发言打印到大屏。

    「告知系统进入发言阶段」和「等待发言完毕」由 `run_speech` 一次调用覆盖。
    """

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        order = self.judge.speaking_order()
        self.judge.say("order", {"order": list(order)})
        self.judge.deliver()
        self.judge.system.run_speech(self.judge.day, order, self.judge.players)
        self.judge.deliver()
        return "投票通知", None


class VoteNoticeNode(Node):
    """在公屏发送投票通知。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        self.judge.say("vote_notice", {"day": self.judge.day})
        self.judge.deliver()
        return "投票", None


class VoteNode(Node):
    """投票阶段：系统收齐选择、把票型打印到大屏，法官接住结果。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        self.judge.ballots = self.judge.system.run_vote(
            self.judge.day, self.judge.alive_seats(), self.judge.players
        )
        return "计票", None


class TallyNode(Node):
    """计票与放逐：更新存活表，把出局的人交给系统打印。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        self.judge.resolve_vote()
        self.judge.system.sync_alive(self.judge.alive_seats())
        self.judge.deliver()
        return "判胜负", None


class CheckEndNode(Node):
    """checkifend[pub]：输出「游戏继续」或胜负。纯函数，模型不参与。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        winner = self.judge.check_finish()
        if winner is None and self.judge.day >= self.judge.max_days:
            winner = DRAW
        if winner:
            return "结束", winner
        self.judge.say("continue", {"day": self.judge.day})
        self.judge.deliver()
        return "继续", None


class GameOverNode(Node):
    """输出胜利者。没有后继节点，Flow 到这里结束。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: str) -> tuple[str, Any]:
        self.judge.finish(payload)
        self.judge.deliver()
        return DEFAULT_ACTION, None


# ------------------------------------------------------------------ Agent


class JudgeAgent:
    """法官：持有全部真相，按 Flow 把该说的话说出去、该问的人叫醒。"""

    def __init__(
        self,
        roles: Mapping[int, str],
        *,
        board: Board | None = None,
        screen: Screen | None = None,
        system: SystemProtocol | None = None,
        narrate: NarrateFn | None = None,
        pace: Callable[[float], None] | None = None,
        seed: int | None = None,
        max_days: int = 8,
    ) -> None:
        self.board = board or DEFAULT_BOARD
        unknown = sorted({role for role in roles.values() if role not in self.board.camps})
        if unknown:
            raise ValueError(f"未知身份：{unknown}")
        if Counter(roles.values()) != Counter(self.board.distribution):
            raise ValueError("身份分布和板子对不上")
        # 夜间顺序相关的约束一次校验完：板子本身没错，错的是「这个板子配这个法官工作流」
        self._check_night_order()

        self.roles = dict(roles)
        self.seats = tuple(sorted(self.roles))
        self.alive: set[int] = set(self.seats)
        self.screen = screen or (system.screen if system is not None else Screen())
        self.system: SystemProtocol = system or LocalSystem(self.screen)
        self.narrate = narrate
        # 节奏回调：暂停、倍速都由调用方决定怎么等（默认不等）
        self.pace = pace or (lambda seconds: None)
        # 发言顺序、平票随机用派生 seed：和发牌（`deal_roles`）的随机序列解耦，
        # 否则同一 seed 下「谁先发言」和「谁是什么身份」会相关。seed 为 None 时保持真随机。
        self.rng = random.Random(f"{seed}:judge" if seed is not None else None)
        self.max_days = max_days

        self.day = 0
        self.winner: str | None = None
        self.ledger: list[Message] = []  # 私人库：夜间原始动作，玩家看不到
        self.players: dict[int, PlayerProtocol] = {}

        self.night = NightState()
        self.decisions: dict[str, int | None] = {}  # 一晚里按票数定下的目标
        self.ballots: dict[int, int | None] = {}
        self.phases_done: set[str] = set()  # 这一夜已经走完的阶段，informed 阶段靠它确认刀口算出来了
        # 昨夜死亡名单（含猎人的夜枪）：天亮公布用它，白天的票出局不会改它
        self.day_deaths: tuple[int, ...] = ()
        # 最近一次 apply_deaths 的名单：夜间结算、白天放逐、猎人开枪都会改写它。
        # 想要「昨夜名单」请用 day_deaths，别用这个
        self.last_deaths: tuple[int, ...] = ()
        self.last_eliminated: int | None = None

        self.flow = self.build_flow()

    def _check_night_order(self) -> None:
        """校验板子的夜间顺序，不满足就报错（错的是「板子 + 法官工作流」这个组合）。

        两条约束：

        1. 夜间阶段不能重复——重复阶段会让叫醒顺序和动作归属读不清；
        2. informed 阶段（女巫这类要看刀口的身份）必须排在所有会出刀的阶段后面。否则
           她在刀定下来之前就被叫醒，看到的是「今晚没有人被袭击」，而且这个还没算出来的
           None 会被 `decide_effect` 缓存一整晚，污染整夜结算。
        """
        problems: list[str] = []
        phases = list(self.board.night_phases)
        duplicated = sorted(phase for phase, count in Counter(phases).items() if count > 1)
        if duplicated:
            problems.append(f"夜间阶段重复：{'、'.join(duplicated)}")

        missing = [phase for phase in self.board.informed if phase not in phases]
        if missing:
            problems.append(f"informed 阶段不在夜间阶段里：{'、'.join(missing)}")

        for phase in self.board.informed:
            if phase not in phases:
                continue
            position = phases.index(phase)
            later_kills = [kill for kill in self.kill_phases() if phases.index(kill) > position]
            if later_kills:
                problems.append(
                    f"{phase} 阶段排在会出刀的 {'、'.join(later_kills)} 阶段前面："
                    "informed 阶段必须晚于所有会出刀的阶段，否则拿到的刀口还没算出来"
                )

        if problems:
            raise ValueError("板子的夜间顺序不合法：\n- " + "\n- ".join(problems))

    def build_flow(self) -> Flow:
        """把各个 Node 连成循环。返回的 Flow 从开场进，到输出胜利者结束。"""
        opening = OpeningNode(self)
        roll = RollRoleNode(self)
        night = NightFallNode(self)
        ask = AskActionNode(self)
        dawn = DawnNode(self)
        alive = CheckAliveNode(self)
        speech = SpeechNode(self)
        notice = VoteNoticeNode(self)
        vote = VoteNode(self)
        tally = TallyNode(self)
        end = CheckEndNode(self)
        over = GameOverNode(self)

        opening - "发身份" >> roll
        roll - "天黑" >> night
        night - "叫醒" >> ask
        ask - "叫醒" >> ask  # 自环：按板子给的夜间阶段一个个走
        ask - "天亮" >> dawn
        dawn - "存活" >> alive
        alive - "发言" >> speech
        speech - "投票通知" >> notice
        notice - "投票" >> vote
        vote - "计票" >> tally
        tally - "判胜负" >> end
        end - "继续" >> night  # 新的一天：回到天黑
        end - "结束" >> over
        return Flow(opening)

    # ------------------------------------------------------------------ 入口

    def play(self, players: Mapping[int, PlayerProtocol]) -> str:
        """接管这批玩家，跑完整局，返回获胜阵营。"""
        self.players = dict(players)
        self.flow.run(None)
        return self.winner or DRAW

    # ------------------------------------------------------------------ 通道

    def say(self, kind: str, facts: Mapping[str, Any]) -> Message:
        """公开播报：事实由法官给，措辞可以交给模型。"""
        text = self.narrate(kind, facts) if self.narrate else self.template(kind, facts)
        message = self.screen.publish(self.day, text, kind=kind, facts=facts)
        self.pace(ANNOUNCE_PAUSE)  # 大屏上这一句停留够了再往下走
        return message

    def tell(
        self,
        audience: Sequence[int],
        text: str,
        *,
        kind: str = "",
        facts: Mapping[str, Any] | None = None,
    ) -> Message:
        """私聊投递：身份卡、叫醒、夜间回执都走这里。"""
        return self.screen.send(audience, self.day, text, kind=kind, facts=facts)

    def record(self, text: str, facts: Mapping[str, Any]) -> None:
        """记进私人库（夜间原始动作），玩家看不到。"""
        self.ledger.append(
            Message(
                seq=len(self.ledger) + 1,
                day=self.day,
                text=text,
                channel=PRIVATE,
                audience=(),
                kind="ledger",
                facts=dict(facts),
            )
        )

    def report(self) -> list[Message]:
        """大屏：所有人都能读的那部分。"""
        return self.screen.public()

    def deliver(self) -> None:
        """把各自的收件箱推给玩家。玩家按 seq 去重，所以重复投递是安全的。"""
        for seat, player in self.players.items():
            player.receive(self.screen.read(seat))

    # ------------------------------------------------------------------ 查询

    def is_alive(self, seat: int) -> bool:
        return seat in self.alive

    def alive_seats(self) -> tuple[int, ...]:
        return tuple(sorted(self.alive))

    def phase_actors(self, phase: str, *, alive_only: bool = True) -> tuple[int, ...]:
        """某个夜间阶段的行动者。"""
        return tuple(
            seat
            for seat in self.seats
            if self.roles[seat] == phase and (not alive_only or self.is_alive(seat))
        )

    def check_finish(self) -> str | None:
        """判断游戏是否结束。纯函数，模型不参与。

        判法在系统层（`SystemProtocol.check_winner`）：一方阵营全部出局就结束，
        狼人全死好人赢、好人全死狼人赢；只看阵营是否还有人活着，不比人数。
        """
        camps = {seat: self.board.camps[self.roles[seat]] for seat in self.roles}
        return self.system.check_winner(camps, self.alive_seats())

    def night_schedule(self) -> tuple[str, ...]:
        """夜间阶段表：组成和顺序由板子给，死没死都照样排进去。"""
        return tuple(self.board.night_phases)

    def kill_phases(self) -> tuple[str, ...]:
        """会出刀的夜间阶段：角色类的 `effects` 里声明了 kill 的那些。

        `informed` 阶段必须排在它们后面，`_check_night_order()` 和运行时兜底都读这个。
        """
        return tuple(
            phase
            for phase in self.board.night_phases
            if "kill" in self.board.characters[phase].effects
        )

    def speaking_order(self) -> tuple[int, ...]:
        """发言顺序：随机抽开始发言的人，再随机顺时针或逆时针。"""
        alive = self.alive_seats()
        if not alive:
            return ()
        start = self.rng.randrange(len(alive))
        if self.rng.random() < 0.5:
            return alive[start:] + alive[:start]
        return alive[: start + 1][::-1] + alive[start + 1 :][::-1]

    # ------------------------------------------------------------------ 夜间

    def begin_night(self) -> None:
        self.night = NightState()
        self.decisions = {}
        self.ballots = {}
        self.phases_done = set()

    def open_phase(self, phase: str) -> None:
        """联系这个阶段的行动者，收下各自的动作。

        阶段里有多个行动者时（狼人阶段），他们共用一次对话：名单和彼此的提案都在
        这一次对话里，所以人是这时候才知道队友的。
        """
        self.pace(PHASE_PAUSE)
        talking = tuple(
            seat
            for seat in self.phase_actors(phase)
            if (player := self.players.get(seat)) is not None and player.is_special
        )
        if talking:
            self._ask_phase(phase, talking)
        # 阶段走完记一笔：后面的 informed 阶段（女巫）靠它确认今晚的刀算出来了。
        # 放在这里而不是提前 return，是为了让「阶段里没人可问」（例如狼全出局）也算走完
        self.phases_done.add(phase)

    def _ask_phase(self, phase: str, talking: Sequence[int]) -> None:
        """叫醒之后的问答：先把问题私聊给这个阶段的人（informed 阶段带上刀口），再收动作。"""
        text = self._phase_prompt(phase, talking)
        facts: dict[str, Any] = {"phase": phase, "seats": list(talking)}
        if phase in self.board.informed:
            # 女巫这类身份要看着今晚的刀口决定用药
            attacked = self._attacked_tonight(phase)
            facts["attacked"] = attacked
            text += (
                f"今晚被袭击的是 {attacked} 号。"
                if attacked is not None
                else "今晚没有人被袭击。"
            )
        self.tell(
            talking,
            text,
            kind="phase",
            facts=facts,
        )
        self.deliver()
        self.team_talk(phase, talking)
        for seat in talking:
            action = self.players[seat].night_action(phase, self.alive_seats())
            self.record_action(phase, seat, action)

    def _attacked_tonight(self, phase: str) -> int | None:
        """informed 阶段（女巫）看到的今晚刀口。

        防御：这个阶段必须排在所有会出刀的阶段后面。真排到前面时，`decide_effect` 会把一个
        还没算出来的 None 缓存一整晚，污染整夜结算，所以这里再拦一次（板子层面的同类问题
        在 `_check_night_order()` 里已经报错了）。
        """
        pending = [kill for kill in self.kill_phases() if kill not in self.phases_done]
        if pending:
            raise ValueError(
                f"{phase} 阶段排在会出刀的 {'、'.join(pending)} 阶段前面："
                "informed 阶段必须晚于所有会出刀的阶段，否则拿到的刀口还没算出来"
            )
        return self.decide_effect("kill")

    def team_talk(self, phase: str, talking: Sequence[int]) -> None:
        """多人同夜行动：先让每个人说一句意见，再投票，商量过程进队伍频道。"""
        if len(talking) < 2 or TEAM_TALK_ROUNDS < 1:
            return
        for round_no in range(1, TEAM_TALK_ROUNDS + 1):
            for seat in talking:
                player = self.players.get(seat)
                if player is None:
                    continue
                text = player.team_talk(phase, self.alive_seats(), round_no).strip()
                if not text:
                    continue
                self.tell(
                    talking,
                    f"{seat} 号：{text}",
                    kind="team_talk",
                    facts={"phase": phase, "seat": seat, "round": round_no},
                )
                self.deliver()  # 队友立刻看到这条意见

    def _phase_prompt(self, phase: str, talking: Sequence[int]) -> str:
        if len(talking) > 1:
            seats = "、".join(f"{seat} 号" for seat in sorted(talking))
            return f"{phase}请睁眼，你们是 {seats}。"
        return f"轮到你行动：{phase}。"

    def record_action(self, phase: str, seat: int, action: Mapping[str, Any]) -> None:
        """收下一个夜间动作：原始选择进私人库，回执发给这个阶段的人。"""
        self.night.put(phase, seat, action)
        self.record(
            f"{seat} 号在{phase}阶段的动作：{dict(action)}",
            {"phase": phase, "seat": seat, **dict(action)},
        )
        text, extra = self.receipt(seat, action)
        self.tell(
            self.phase_actors(phase),
            text,
            kind="receipt",
            facts={"phase": phase, "seat": seat, **dict(action), **extra},
        )
        self.deliver()  # 同阶段的人立刻看到彼此的提案

    def decide_effect(self, effect: str) -> int | None:
        """定下这类效果的最终目标：票数最多者胜，平票在最高的几个座位里随机取一个。

        「一晚只算一次」意味着什么时候问很关键：问的越晚，收到的动作越全。所以会读刀口的
        informed 阶段（女巫）必须排在所有会出刀的阶段后面——否则这里会把「还没出刀」当成
        空刀，把 None 缓存一整晚。板子层面的约束在 `_check_night_order()` 里校验，运行时在
        `_attacked_tonight()` 里再兜一层。
        """
        if effect in self.decisions:
            return self.decisions[effect]

        targets = [
            int(action["target"])
            for action in self.night.of_effect(effect)
            if action.get("target") is not None
        ]
        target: int | None = None
        if targets:
            counts = Counter(targets)
            best = max(counts.values())
            # 平票随机：原来固定取最小座位号，低座位会系统性占优
            target = self.rng.choice(sorted(seat for seat, count in counts.items() if count == best))
        self.decisions[effect] = target
        return target

    def close_phase(self, phase: str) -> Message | None:
        """阶段收尾：这一阶段有杀人动作时，把定下来的目标告诉这一阶段的人。"""
        actions = self.night.actions.get(phase, {})
        if not any(action.get("effect") == "kill" for action in actions.values()):
            return None
        target = self.decide_effect("kill")
        if target is not None:
            # 这一夜谁动过刀，系统级记一笔：判胜负时它才有资格用人数持平速判。
            # 空刀（目标定不下来）不算「杀过人」，这里不标记
            self.system.mark_killer(self.board.camps[phase])
        message = self.tell(
            self.phase_actors(phase),
            f"今晚的目标 → {target} 号。" if target is not None else "今晚没有定下目标（空刀）。",
            kind="phase_target",
            facts={"phase": phase, "target": target, "votes": list(actions)},
        )
        self.deliver()
        return message

    def receipt(self, seat: int, action: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        """回执措辞：按动作的 effect 分类，措辞属于流程，写在法官这边。"""
        target = action.get("target")
        effect = action.get("effect")
        if effect == "kill":
            return f"{seat} 号提议袭击 {target} 号。", {"proposal": target}
        if effect == "protect":
            return f"{seat} 号守护了 {target} 号。", {"guard": target}
        if effect == "check":
            role = self.roles.get(int(target)) if target is not None else None
            camp = self.board.camps.get(role, "") if role else ""
            text = f"{seat} 号查验了 {target} 号，结果是{camp}。" if camp else "没有查验对象。"
            return text, {"check": {"target": target, "camp": camp}}
        if effect == "save" and target is not None:
            return f"{seat} 号救下了 {target} 号。", {"save": target}
        if effect == "poison" and target is not None:
            return f"{seat} 号毒了 {target} 号。", {"poison": target}
        return f"{seat} 号这一夜没有动作。", {}

    def resolve_night(self) -> None:
        """天亮结算：刀、守、救、毒一起算，然后处理死亡触发技。纯函数。"""
        kill = self.decide_effect("kill")
        save = self.decide_effect("save")
        protects = {
            int(action["target"])
            for action in self.night.of_effect("protect")
            if action.get("target") is not None
        }

        deaths: list[int] = []
        causes: dict[int, str] = {}
        if kill is not None and kill != save and kill not in protects:
            deaths.append(kill)
            causes[kill] = "attack"
        poison = self.decide_effect("poison")
        if poison is not None and poison not in deaths:
            deaths.append(poison)
            causes[poison] = "poison"
        self.apply_deaths(deaths, causes)
        # 昨夜名单在这里定下来，含猎人的夜枪（apply_deaths 里追加的也算）。
        # 白天的票出局、白天开枪只会改 last_deaths，不会再动 day_deaths
        self.day_deaths = self.last_deaths

    def apply_deaths(self, deaths: Sequence[int], causes: Mapping[int, str]) -> None:
        """公布出局名单，再让出局的人发动死亡触发技（猎人开枪）。

        `last_deaths` 的语义是「最近一次 `apply_deaths` 的名单」：夜里结算、白天放逐、
        猎人开枪都会改写它。要「昨夜名单」请用 `day_deaths`（在 `resolve_night()` 末尾落值）。
        """
        self.last_deaths = tuple(deaths)
        self.alive.difference_update(self.last_deaths)
        if self.last_deaths:
            self.system.announce_deaths(self.day, self.last_deaths)
        self.deliver()
        self.record(
            f"第 {self.day} 天出局：{list(self.last_deaths)}",
            {"deaths": list(self.last_deaths), "causes": dict(causes)},
        )

        for seat in tuple(self.last_deaths):
            player = self.players.get(seat)
            if player is None:
                continue
            action = player.death_action(causes.get(seat, ""), self.alive_seats())
            target = action.get("target") if action else None
            if not action or action.get("effect") != "shoot" or target is None:
                continue
            if int(target) not in self.alive:
                continue
            self.say("hunter_shot", {"seat": seat, "target": int(target)})
            self.alive.discard(int(target))
            self.last_deaths = (*self.last_deaths, int(target))
            self.system.announce_deaths(self.day, (int(target),))
            self.deliver()

    # ------------------------------------------------------------------ 白天

    def resolve_vote(self) -> list[Message]:
        """计票与放逐。平票时本轮无人出局。"""
        counts = Counter(target for target in self.ballots.values() if target is not None)
        if not counts:
            self.last_eliminated = None
            return [self.say("vote", {"counts": {}, "eliminated": None})]

        best = max(counts.values())
        top = sorted(seat for seat, count in counts.items() if count == best)
        self.last_eliminated = top[0] if len(top) == 1 else None

        emitted = [
            self.say(
                "vote",
                {
                    "counts": {str(seat): count for seat, count in sorted(counts.items())},
                    "top": top,
                    "eliminated": self.last_eliminated,
                },
            )
        ]
        if self.last_eliminated is not None:
            # 被票出局也算一次出局，猎人在这里可以开枪
            self.apply_deaths((self.last_eliminated,), {self.last_eliminated: "vote"})
        return emitted

    def finish(self, winner: str) -> Message:
        self.winner = winner
        return self.say("game_over", {"winner": winner, "roles": dict(self.roles)})

    # ------------------------------------------------------------------ 模板

    def template(self, kind: str, facts: Mapping[str, Any]) -> str:
        """默认措辞。换成模型润色时，只能改到这里为止。"""
        if kind == "opening":
            seats = "、".join(f"{seat} 号" for seat in facts.get("seats", ()))
            return f"本局 {facts.get('count', 0)} 人，座位号 {seats}。天黑请闭眼。"
        if kind == "role":
            return f"你的身份是{facts.get('role', '')}（{facts.get('camp', '')}）。"
        if kind == "wake":
            return f"{facts.get('phase', '')}请睁眼。"
        if kind == "phase_over":
            return f"{facts.get('phase', '')}请闭眼。"
        if kind == "result":
            deaths = list(facts.get("deaths") or ())
            if not deaths:
                return "昨晚是平安夜，没有人出局。"
            return "昨晚出局：" + "、".join(f"{seat} 号" for seat in deaths) + "。"
        if kind == "hunter_shot":
            # 猎人开枪不交给模型润色（不在 NARRATED_KINDS 里），模板必须有这一支
            return f"{facts.get('seat', '')} 号（Hunter）开枪带走了 {facts.get('target', '')} 号。"
        if kind == "alive":
            seats = "、".join(f"{seat} 号" for seat in facts.get("alive", ()))
            return f"当前存活 {facts.get('count', 0)} 人：{seats}。"
        if kind == "order":
            order = "、".join(f"{seat} 号" for seat in facts.get("order", ()))
            return f"请按顺序发言：{order}。"
        if kind == "vote_notice":
            return "发言结束，请投票放逐一名玩家。"
        if kind == "vote":
            counts = facts.get("counts") or {}
            if not counts:
                return "本轮全员弃票，没有人被放逐。"
            detail = "，".join(f"{seat} 号 {count} 票" for seat, count in counts.items())
            if facts.get("eliminated") is None:
                return f"投票结果：{detail}。平票，本轮无人出局。"
            return f"投票结果：{detail}。"
        if kind == "continue":
            return f"第 {facts.get('day', 0)} 天结束，游戏继续。"
        if kind == "game_over":
            return f"游戏结束，{facts.get('winner', '')}获胜。"
        return ""
