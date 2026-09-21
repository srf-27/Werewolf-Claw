"""法官 Agent：一个 Node + Flow 写成的对局循环。

每个环节一个 Node，连成一条 Flow：

    开场白 -> 分发身份 -> 判断游戏是否结束
        结束 -> 输出胜利者
        未结束 -> 输出天数 -> 天黑 -> 按阶段唤醒特殊身份（自环）
                -> 夜晚结算 -> 天亮 -> 平安夜判定 -> 排发言顺序
                -> 等玩家发言（自环）-> 收集投票（自环）-> 计票与放逐
                -> 回到「判断游戏是否结束」

「有几个特殊身份」「有几个玩家」这类循环交给自环节点：payload 里放还没处理的
名单，每转一圈切掉一个，切完就走另一条边。

两条通道：公开大屏（所有人可读）和私聊通道（身份卡、唤醒、夜间回执）。隔离的
判定只有 `Message.visible_to()` 一处。

雏形的取舍：胜负判定、平安夜判定、票型统计都是纯函数，写在这个文件里，不调用
模型；措辞交给可选的 `narrate` 回调，没给就用模板。事实由法官给出，模型只能换说法。
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from werewolf_claw.core.node import DEFAULT_ACTION, Flow, Node

# ------------------------------------------------------------------ 常量

# 消息通道
PUBLIC = "public"
TEAM = "team"
PRIVATE = "private"

# 角色
WOLF = "狼人"
GUARD = "守卫"
SEER = "预言家"
WITCH = "女巫"
HUNTER = "猎人"
VILLAGER = "村民"

CAMP_WOLF = "狼人阵营"
CAMP_GOOD = "好人阵营"

ROLE_CAMP: dict[str, str] = {
    WOLF: CAMP_WOLF,
    GUARD: CAMP_GOOD,
    SEER: CAMP_GOOD,
    WITCH: CAMP_GOOD,
    HUNTER: CAMP_GOOD,
    VILLAGER: CAMP_GOOD,
}

# 夜间阶段表：按这个顺序逐个叫醒，板子里没有的角色自动跳过。
# 猎人和村民没有夜间动作，所以不出现在这里。
NIGHT_ORDER = (GUARD, WOLF, WITCH, SEER)

# 达到天数上限时的收尾说法。
DRAW = "平局"

# 播报回调：(事件类型, 事实) -> 中文台词。
NarrateFn = Callable[[str, Mapping[str, Any]], str]


# ------------------------------------------------------------------ 协议


@dataclass(frozen=True)
class Message:
    """大屏或私聊里的一条消息。

    `text` 是给人看的台词，`facts` 是给 Agent 用的结构化事实，两者走同一个可见性判定。
    """

    seq: int
    day: int
    text: str
    channel: str = PUBLIC
    audience: tuple[int, ...] = ()
    kind: str = ""
    facts: dict[str, Any] = field(default_factory=dict)

    def visible_to(self, seat: int) -> bool:
        """信息隔离的唯一判定：公开的人人可读，队伍和私聊只给收件人。"""
        return self.channel == PUBLIC or seat in self.audience


class PlayerProtocol(Protocol):
    """法官和玩家之间的协议：法官只认这几个方法，不关心背后是模型还是规则。"""

    def receive(self, messages: Sequence[Message]) -> int:
        """收下法官投递的消息，返回新收了几条。"""

    def night_action(self, phase: str, alive: Sequence[int]) -> dict[str, Any]:
        """报一次夜间动作，例如 {"phase": "wolf", "target": 3}。"""

    def statement(self, alive: Sequence[int]) -> dict[str, Any]:
        """报一次公开发言，例如 {"text": "…", "target": 3}。"""

    def ballot(self, alive: Sequence[int]) -> dict[str, Any]:
        """报一次投票，例如 {"target": 3}；target 为 None 表示弃票。"""

    def reflect(self, day: int, outcome: Mapping[str, Any]) -> str:
        """把这一天的结果交给玩家，由他自己写反思。"""


@dataclass
class NightState:
    """一夜的暂存结果，天亮时才结算。"""

    guard: int | None = None
    kill: int | None = None
    save: int | None = None
    poison: int | None = None
    wolf_votes: dict[int, int] = field(default_factory=dict)


# ------------------------------------------------------------------ 各个 Node


class OpeningNode(Node):
    """开场白：报人数和座位号。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        self.judge.say("opening", {"seats": self.judge.seats, "count": len(self.judge.seats)})
        return "发身份", None


class DealRoleNode(Node):
    """分发身份：一张卡一条私聊，只有本人收得到。

    身份卡不经过 `narrate`，因为它是事实而不是措辞。
    """

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        for seat in self.judge.seats:
            role = self.judge.roles[seat]
            facts = {"seat": seat, "role": role, "camp": ROLE_CAMP[role]}
            self.judge.tell([seat], self.judge.template("role", facts), kind="role", facts=facts)
        self.judge.deliver()
        return "判胜负", None


class CheckFinishNode(Node):
    """判断游戏是否结束。纯函数，模型不参与。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        winner = self.judge.check_finish()
        if winner is None and self.judge.day >= self.judge.max_days:
            winner = DRAW
        if winner:
            return "结束", winner
        return "继续", None


class AnnounceDayNode(Node):
    """输出天数。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        self.judge.day += 1
        self.judge.say("day", {"day": self.judge.day})
        return "天黑", None


class NightStartNode(Node):
    """天黑：清掉昨晚的暂存结果，并把这一晚的阶段表交下去。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        self.judge.begin_night()
        self.judge.say("night", {"day": self.judge.day})
        return "阶段", self.judge.night_schedule()


class WakeRoleNode(Node):
    """按阶段唤醒特殊身份。payload 是还没叫醒的阶段表，转一圈切掉一个。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Sequence[tuple[str, tuple[int, ...]]]) -> tuple[str, Any]:
        if not payload:
            return "公布", None

        role, actors = payload[0]
        for seat in actors:
            if not self.judge.is_alive(seat):
                continue
            self.judge.wake(seat, role)
            self.judge.deliver()  # 先让他看到被叫醒，再问他要动作
            action = self.judge.players[seat].night_action(role, self.judge.alive_seats())
            self.judge.record_night_action(seat, role, action)

        if role == WOLF:
            self.judge.close_wolf_phase()
            self.judge.deliver()
        return "阶段", payload[1:]


class NightResolveNode(Node):
    """夜晚结算：守卫挡刀、解药救人、毒药必死，死者先记下来，天亮才公布。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        self.judge.resolve_night()
        return "天亮", None


class DawnNode(Node):
    """天亮。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        self.judge.say("dawn", {"day": self.judge.day})
        return "判定", None


class NightResultNode(Node):
    """平安夜判定：没人出局就是平安夜，有人出局就只公布名单、不公布死因。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        self.judge.say("result", {"day": self.judge.day, "deaths": list(self.judge.last_deaths)})
        self.judge.deliver()
        return "发言", None


class SpeakOrderNode(Node):
    """排发言顺序：顺序由法官排定，模型只决定说什么，不决定轮到谁。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        order = self.judge.speaking_order()
        self.judge.say("order", {"order": list(order)})
        return "发言", order


class SpeakNode(Node):
    """等玩家发言完毕。payload 是还没发言的座位，转一圈切掉一个。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Sequence[int]) -> tuple[str, Any]:
        if not payload:
            return "投票", self.judge.alive_seats()
        seat = payload[0]
        if self.judge.is_alive(seat):
            player = self.judge.players[seat]
            self.judge.collect_statement(seat, player.statement(self.judge.alive_seats()))
        return "发言", payload[1:]


class VoteNode(Node):
    """收集投票。payload 是还没投票的座位，转一圈切掉一个。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Sequence[int]) -> tuple[str, Any]:
        if not payload:
            return "计票", None
        seat = payload[0]
        if self.judge.is_alive(seat):
            player = self.judge.players[seat]
            self.judge.collect_ballot(seat, player.ballot(self.judge.alive_seats()))
        return "投票", payload[1:]


class VoteResultNode(Node):
    """计票与放逐。玩家闭环的最后一步「反思」也在这里被触发。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: Any) -> tuple[str, Any]:
        self.judge.resolve_vote()
        self.judge.reflect_all()
        return "判胜负", None


class GameOverNode(Node):
    """输出胜利者。没有后继节点，Flow 到这里结束。"""

    def __init__(self, judge: "JudgeAgent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.judge = judge

    def exec(self, payload: str) -> tuple[str, Any]:
        self.judge.finish(payload)
        return DEFAULT_ACTION, None


# ------------------------------------------------------------------ Agent


class JudgeAgent:
    """法官：持有全部真相，按 Flow 把该说的话说出去、该问的人叫醒。"""

    def __init__(
        self,
        roles: Mapping[int, str],
        *,
        narrate: NarrateFn | None = None,
        seed: int | None = None,
        max_days: int = 8,
    ) -> None:
        unknown = [role for role in roles.values() if role not in ROLE_CAMP]
        if unknown:
            raise ValueError(f"未知角色：{sorted(set(unknown))}")

        self.roles = dict(roles)
        self.seats = tuple(sorted(self.roles))
        self.alive: set[int] = set(self.seats)
        self.narrate = narrate
        self.rng = random.Random(seed)
        self.max_days = max_days

        self.day = 0
        self.winner: str | None = None
        self.log: list[Message] = []
        self.players: dict[int, PlayerProtocol] = {}

        self.night = NightState()
        self.ballots: dict[int, int | None] = {}
        self.last_deaths: tuple[int, ...] = ()
        self.last_eliminated: int | None = None

        self.flow = self.build_flow()

    def build_flow(self) -> Flow:
        """把各个 Node 连成循环。返回的 Flow 从开场进，到输出胜利者结束。"""
        opening = OpeningNode(self)
        deal = DealRoleNode(self)
        check = CheckFinishNode(self)
        day = AnnounceDayNode(self)
        night = NightStartNode(self)
        wake = WakeRoleNode(self)
        resolve = NightResolveNode(self)
        dawn = DawnNode(self)
        result = NightResultNode(self)
        order = SpeakOrderNode(self)
        speak = SpeakNode(self)
        vote = VoteNode(self)
        tally = VoteResultNode(self)
        over = GameOverNode(self)

        opening - "发身份" >> deal
        deal - "判胜负" >> check
        check - "结束" >> over
        check - "继续" >> day
        day - "天黑" >> night
        night - "阶段" >> wake
        wake - "阶段" >> wake  # 自环：有几个特殊身份就转几圈
        wake - "公布" >> resolve
        resolve - "天亮" >> dawn
        dawn - "判定" >> result
        result - "发言" >> order
        order - "发言" >> speak
        speak - "发言" >> speak  # 自环：有几个玩家就转几圈
        speak - "投票" >> vote
        vote - "投票" >> vote  # 自环：有几个存活玩家就转几圈
        vote - "计票" >> tally
        tally - "判胜负" >> check  # 回到循环头
        return Flow(opening)

    # ------------------------------------------------------------------ 入口

    def play(self, players: Mapping[int, PlayerProtocol]) -> str:
        """接管这批玩家，跑完整局，返回获胜阵营。"""
        self.players = dict(players)
        self.flow.run(None)
        return self.winner or DRAW

    # ------------------------------------------------------------------ 通道

    def _emit(
        self,
        text: str,
        *,
        channel: str = PUBLIC,
        audience: Sequence[int] = (),
        kind: str = "",
        facts: Mapping[str, Any] | None = None,
    ) -> Message:
        message = Message(
            seq=len(self.log) + 1,
            day=self.day,
            text=text,
            channel=channel,
            audience=tuple(audience),
            kind=kind,
            facts=dict(facts or {}),
        )
        self.log.append(message)
        return message

    def say(self, kind: str, facts: Mapping[str, Any]) -> Message:
        """公开播报：事实由法官给，措辞可以交给模型。"""
        text = self.narrate(kind, facts) if self.narrate else self.template(kind, facts)
        return self._emit(text, kind=kind, facts=facts)

    def tell(
        self,
        audience: Sequence[int],
        text: str,
        *,
        channel: str = PRIVATE,
        kind: str = "",
        facts: Mapping[str, Any] | None = None,
    ) -> Message:
        """私聊投递：身份卡、唤醒、夜间回执都走这里。"""
        return self._emit(text, channel=channel, audience=audience, kind=kind, facts=facts)

    def report(self) -> list[Message]:
        """大屏：所有人都能读的那部分。"""
        return [message for message in self.log if message.channel == PUBLIC]

    def inbox(self, seat: int) -> list[Message]:
        """某个座位能读到的全部消息：公开 + 投给他的。"""
        return [message for message in self.log if message.visible_to(seat)]

    def deliver(self) -> None:
        """把各自的收件箱推给玩家。玩家按 seq 去重，所以重复投递是安全的。"""
        for seat, player in self.players.items():
            player.receive(self.inbox(seat))

    # ------------------------------------------------------------------ 查询

    def role_of(self, seat: int) -> str:
        return self.roles[seat]

    def is_alive(self, seat: int) -> bool:
        return seat in self.alive

    def alive_seats(self) -> tuple[int, ...]:
        return tuple(sorted(self.alive))

    def wolves(self) -> tuple[int, ...]:
        return tuple(seat for seat in self.alive_seats() if self.roles[seat] == WOLF)

    def check_finish(self) -> str | None:
        """判断游戏是否结束。纯函数，模型不参与。"""
        wolves = self.wolves()
        goods = [seat for seat in self.alive_seats() if self.roles[seat] != WOLF]
        if not wolves:
            return CAMP_GOOD
        if not goods or len(wolves) >= len(goods):
            return CAMP_WOLF
        return None

    def night_schedule(self) -> list[tuple[str, tuple[int, ...]]]:
        """夜间阶段表：板子里有谁，就排谁的阶段。"""
        schedule: list[tuple[str, tuple[int, ...]]] = []
        for role in NIGHT_ORDER:
            actors = tuple(seat for seat in self.alive_seats() if self.roles[seat] == role)
            if actors:
                schedule.append((role, actors))
        return schedule

    def speaking_order(self) -> tuple[int, ...]:
        """发言顺序：默认从昨天出局者的下一位开始。"""
        alive = self.alive_seats()
        if not alive:
            return ()
        start = self.last_deaths[0] % len(self.roles) + 1 if self.last_deaths else alive[0]
        return tuple(seat for seat in alive if seat >= start) + tuple(
            seat for seat in alive if seat < start
        )

    # ------------------------------------------------------------------ 夜间

    def begin_night(self) -> None:
        self.night = NightState()
        self.ballots = {}

    def wake(self, seat: int, role: str) -> Message:
        """单独叫醒一个身份。女巫额外知道自己今晚要救谁。"""
        text = f"{role}请睁眼。"
        facts: dict[str, Any] = {"phase": role, "seat": seat}
        if role == WITCH:
            facts["attacked"] = self.night.kill
            text += (
                f"今晚被袭击的是 {self.night.kill} 号。"
                if self.night.kill is not None
                else "今晚没有人被袭击。"
            )
        return self.tell([seat], text, kind="wake", facts=facts)

    def record_night_action(self, seat: int, phase: str, action: Mapping[str, Any]) -> Message:
        """收下一个夜间动作，回执走私聊（狼人走队伍频道）。"""
        target = action.get("target")
        facts = dict(action)
        facts.setdefault("phase", phase)
        facts["seat"] = seat

        if phase == GUARD:
            self.night.guard = int(target) if target is not None else None
            return self.tell([seat], f"你守护了 {self.night.guard} 号。", kind="night", facts=facts)
        if phase == WOLF:
            if target is not None:
                self.night.wolf_votes[seat] = int(target)
            return self.tell(
                self.wolves(),
                f"{seat} 号提议袭击 {target} 号。",
                channel=TEAM,
                kind="night",
                facts=facts,
            )
        if phase == SEER:
            camp = ROLE_CAMP[self.roles[int(target)]] if target in self.roles else ""
            facts["camp"] = camp
            return self.tell(
                [seat], f"你查验了 {target} 号，结果是{camp}。", kind="night", facts=facts
            )

        if action.get("save"):
            self.night.save = self.night.kill
        if action.get("poison") is not None:
            self.night.poison = int(action["poison"])
        return self.tell([seat], self._witch_receipt(action), kind="night", facts=facts)

    def _witch_receipt(self, action: Mapping[str, Any]) -> str:
        parts: list[str] = []
        if action.get("save"):
            parts.append(f"你用解药救下 {self.night.kill} 号")
        if action.get("poison") is not None:
            parts.append(f"你用毒药毒了 {action['poison']} 号")
        return "，".join(parts) + "。" if parts else "今晚你没有用药。"

    def close_wolf_phase(self) -> Message:
        """狼队意见汇总：票数最多的目标出线，平票取座位号最小的。"""
        votes = self.night.wolf_votes
        if not votes:
            self.night.kill = None
            text = "狼队今晚没有提交目标，视为空刀。"
        else:
            counts = Counter(votes.values())
            best = max(counts.values())
            self.night.kill = min(seat for seat, count in counts.items() if count == best)
            text = f"狼队今晚的袭击目标是 {self.night.kill} 号。"
        return self.tell(
            self.wolves(),
            text,
            channel=TEAM,
            kind="night",
            facts={"phase": WOLF, "target": self.night.kill, "votes": dict(votes)},
        )

    def resolve_night(self) -> None:
        """夜晚结算：守卫挡刀、解药救人、毒药必死。纯函数。"""
        deaths: list[int] = []
        kill = self.night.kill
        if kill is not None and self.night.guard != kill and self.night.save != kill:
            deaths.append(kill)
        if self.night.poison is not None:
            deaths.append(self.night.poison)

        self.last_deaths = tuple(dict.fromkeys(deaths))
        self.alive.difference_update(self.last_deaths)

    # ------------------------------------------------------------------ 白天

    def collect_statement(self, seat: int, payload: Mapping[str, Any]) -> Message:
        """玩家发言进大屏。正文由玩家给，法官只负责公开。"""
        text = str(payload.get("text") or "").strip() or f"{seat} 号没有发言。"
        return self._emit(f"{seat} 号：{text}", kind="statement",
                          facts=dict(payload, seat=seat))

    def collect_ballot(self, seat: int, payload: Mapping[str, Any]) -> Message:
        """票型进大屏。"""
        target = payload.get("target")
        self.ballots[seat] = int(target) if target is not None else None
        text = f"{seat} 号投给 {target} 号。" if target is not None else f"{seat} 号弃票。"
        return self._emit(text, kind="ballot",
                          facts={"seat": seat, "target": self.ballots[seat]})

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
            self.alive.discard(self.last_eliminated)
            emitted.append(self.say("elimination", {"seat": self.last_eliminated}))
        self.deliver()
        return emitted

    def reflect_all(self) -> None:
        """把这一天的结果发给每个玩家，触发他们闭环里的「反思」。"""
        outcome = {
            "day": self.day,
            "deaths": list(self.last_deaths),
            "eliminated": self.last_eliminated,
            "ballots": dict(self.ballots),
        }
        for player in self.players.values():
            player.reflect(self.day, outcome)
        self.deliver()

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
        if kind == "day":
            return f"第 {facts.get('day', 0)} 天。"
        if kind == "night":
            return "天黑请闭眼。"
        if kind == "dawn":
            return f"第 {facts.get('day', 0)} 天，天亮了。"
        if kind == "result":
            deaths = list(facts.get("deaths") or ())
            if not deaths:
                return "昨晚是平安夜，没有人出局。"
            return "昨晚出局：" + "、".join(f"{seat} 号" for seat in deaths) + "。"
        if kind == "order":
            order = "、".join(f"{seat} 号" for seat in facts.get("order", ()))
            return f"请按顺序发言：{order}。"
        if kind == "vote":
            counts = facts.get("counts") or {}
            if not counts:
                return "本轮全员弃票，没有人被放逐。"
            detail = "，".join(f"{seat} 号 {count} 票" for seat, count in counts.items())
            if facts.get("eliminated") is None:
                return f"投票结果：{detail}。平票，本轮无人出局。"
            return f"投票结果：{detail}。"
        if kind == "elimination":
            return f"{facts.get('seat')} 号被放逐出局。"
        if kind == "game_over":
            return f"游戏结束，{facts.get('winner', '')}获胜。"
        return ""
