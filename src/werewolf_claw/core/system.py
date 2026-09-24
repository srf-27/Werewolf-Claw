"""系统级：昼夜与天数、存活数镜像，以及发言和投票两个阶段的节奏。

大屏归系统级管：每位玩家的发言、每人投给谁、谁被放逐，都是系统打印上去的。
发言每人最多 60s（含思考时间）、投票每人 10s 的计时还没实现，标了「待实现」。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from werewolf_claw.core.player import PlayerProtocol
from werewolf_claw.core.screen import Screen

PHASE_NIGHT = "night"
PHASE_DAY = "day"


class SystemProtocol(Protocol):
    """法官跟系统级打交道的接口。"""

    # 系统级持有大屏：发言、票型、出局名单都打印到它上面。
    screen: Screen

    def set_phase(self, phase: str) -> None:
        """法官切到夜晚/白天；收到白天表示这一夜结束，系统把天数加一。"""

    def sync_alive(self, alive: Sequence[int]) -> None:
        """和法官对齐存活表。"""

    def run_speech(
        self, day: int, order: Sequence[int], players: Mapping[int, PlayerProtocol]
    ) -> None:
        """发言阶段：按 `order` 命令每个玩家发言，每人最多 60s（含思考时间）。"""

    def run_vote(
        self, day: int, alive: Sequence[int], players: Mapping[int, PlayerProtocol]
    ) -> dict[int, int | None]:
        """投票阶段：给每个玩家 10s 同步做出选择，返回「座位 -> 投票目标」。"""

    def announce_deaths(self, day: int, seats: Sequence[int]) -> None:
        """把出局的人打印到大屏。"""

    def check_winner(self, camps: Mapping[int, str], alive: Sequence[int]) -> str | None:
        """胜负判定：一方阵营全部出局，或者会杀人的阵营人数已经不少于其他人。"""

    def mark_killer(self, camp: str) -> None:
        """记下哪个阵营夜里杀过人（人数持平速判要用）。"""


class LocalSystem:
    """系统级的本地直通实现：不卡时间，同步跑完两个阶段。

    天数、昼夜、存活数按约定镜像一份：法官说「白天」时表示一夜结束，天数加一。
    """

    def __init__(
        self,
        screen: Screen | None = None,
        pace: Callable[[float], None] | None = None,
    ) -> None:
        self.screen = screen or Screen()
        # pace 是节奏回调：让系统每一步等一下，方便人类看清（暂停、倍速都在里面）
        self.pace = pace or (lambda seconds: None)
        self.phase = PHASE_NIGHT
        self.day = 0
        self.alive: tuple[int, ...] = ()
        self.deaths: tuple[int, ...] = ()
        self.killers: set[str] = set()  # 夜里杀过人的阵营

    def set_phase(self, phase: str) -> None:
        if phase == PHASE_DAY and self.phase == PHASE_NIGHT:
            self.day += 1  # 夜晚到白天，天数加一
        self.phase = phase

    def sync_alive(self, alive: Sequence[int]) -> None:
        self.alive = tuple(sorted(alive))

    def run_speech(
        self, day: int, order: Sequence[int], players: Mapping[int, PlayerProtocol]
    ) -> None:
        # 待实现：每人 60s 上限（含思考时间）由系统级计时，超时按弃权处理。
        alive = tuple(sorted(order))
        for seat in order:
            player = players.get(seat)
            if player is None:
                continue
            self.pace(SPEECH_PAUSE)
            said = player.statement(alive)
            text = str(said.get("text") or "").strip() or f"{seat} 号没有发言。"
            self.screen.publish(
                day, f"{seat} 号：{text}", kind="statement", facts=dict(said, seat=seat)
            )
            for other in players.values():
                other.watch()  # 每一人发言完都要同步大屏消息到记忆

    def run_vote(
        self, day: int, alive: Sequence[int], players: Mapping[int, PlayerProtocol]
    ) -> dict[int, int | None]:
        # 待实现：每人 10s 的同步计时由系统级负责，超时按弃票处理。
        alive = tuple(sorted(alive))
        ballots: dict[int, int | None] = {}
        for seat in alive:
            player = players.get(seat)
            if player is None:
                continue
            self.pace(VOTE_PAUSE)
            payload = player.ballot(alive)
            target = payload.get("target")
            ballots[seat] = None if target is None else int(target)
            self.screen.publish(
                day,
                self._ballot_text(seat, ballots[seat]),
                kind="ballot",
                facts={"seat": seat, "target": ballots[seat]},
            )
        return ballots

    def announce_deaths(self, day: int, seats: Sequence[int]) -> None:
        self.deaths = tuple(seats)
        for seat in seats:
            self.screen.publish(day, f"{seat} 号出局。", kind="death", facts={"seat": seat})

    def check_winner(self, camps: Mapping[int, str], alive: Sequence[int]) -> str | None:
        """胜负判定。两条规则，先全灭，再人数持平：

        1. 某一方阵营的人全部出局 → 另一方获胜；
        2. 会杀人的阵营人数不少于其他所有人 → 该阵营立即获胜（屠边/绑票的速判）。
        都不满足就继续；同归于尽交给法官按天数上限收尾。
        """
        counts = Counter(camps[seat] for seat in alive if seat in camps)
        if not counts:
            return None
        if len(counts) == 1:
            return next(iter(counts))

        total = sum(counts.values())
        for camp in self.killers:
            if camp in counts and counts[camp] * 2 >= total:
                return camp
        return None

    def mark_killer(self, camp: str) -> None:
        """记下哪个阵营夜里杀过人；判胜负时它才有资格用人数持平速判。"""
        if camp:
            self.killers.add(camp)

    def _ballot_text(self, seat: int, target: int | None) -> str:
        return f"{seat} 号投给 {target} 号。" if target is not None else f"{seat} 号弃票。"


# 每个步骤之间的基本等待（秒），倍速会压缩它
SPEECH_PAUSE = 0.8
VOTE_PAUSE = 0.4
