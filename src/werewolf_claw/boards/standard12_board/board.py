"""12 人标准板的具体板子类：4 Werewolf + 4 Villager + Seer / Witch / Hunter / Guard（已废弃切换）。"""

from __future__ import annotations

from werewolf_claw.characters import (
    GuardCharacter,
    HunterCharacter,
    SeerCharacter,
    VillagerCharacter,
    WitchCharacter,
    WolfCharacter,
)
from werewolf_claw.core.board import Board

from .roles import GUARD, HUNTER, ROLE_CAMP, SEER, VILLAGER, WITCH, WOLF


class Standard12Board(Board):
    """12 人标准板：4 Werewolf + 4 Villager，Seer、Witch、Hunter、Guard 各一个（已废弃切换）。"""

    def __init__(self) -> None:
        super().__init__(
            distribution=(
                WOLF,
                WOLF,
                WOLF,
                WOLF,
                VILLAGER,
                VILLAGER,
                VILLAGER,
                VILLAGER,
                SEER,
                WITCH,
                HUNTER,
                GUARD,
            ),
            camps=ROLE_CAMP,
            characters={
                WOLF: WolfCharacter(),
                VILLAGER: VillagerCharacter(),
                SEER: SeerCharacter(),
                WITCH: WitchCharacter(),
                HUNTER: HunterCharacter(),
                GUARD: GuardCharacter(),
            },
            # 女巫要在狼人之后、看着今晚的刀口决定用药
            night_phases=(GUARD, WOLF, WITCH, SEER),
            informed=(WITCH,),
        )
