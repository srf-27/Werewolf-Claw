"""
9 人标准板的具体板子类：3 Werewolf + 3 Villager + Seer + Witch + Hunter。
板子包含的数据：人数、身份分布、阵营分布、特殊身份技能（身份 -> 角色实现）、夜晚阶段。

和 Werewolf-VectorDB 的板子完全对齐：3 狼 3 民预女猎，9 人。
"""

from __future__ import annotations

from werewolf_claw.characters import (
    HunterCharacter,
    SeerCharacter,
    VillagerCharacter,
    WitchCharacter,
    WolfCharacter,
)
from werewolf_claw.core.board import Board

from .roles import HUNTER, ROLE_CAMP, SEER, VILLAGER, WITCH, WOLF


class DefaultBoard(Board):
    """
    人数、
    身份分布、
    阵营分布、
    特殊身份技能、
    具体夜晚阶段
    技能本身写在 `werewolf_claw/characters/` 的角色类里。
    """

    def __init__(self) -> None:
        super().__init__(
            distribution=(
                WOLF, WOLF, WOLF,
                VILLAGER, VILLAGER, VILLAGER,
                SEER, WITCH, HUNTER,
            ),
            camps=ROLE_CAMP,
            characters={
                WOLF: WolfCharacter(),
                VILLAGER: VillagerCharacter(),
                SEER: SeerCharacter(),
                WITCH: WitchCharacter(),
                HUNTER: HunterCharacter(),
            },
            # 夜间顺序：Werewolf 出刀 -> Seer 查验 -> Witch 看刀口决定用药
            # （Witch 是 informed 阶段，必须排在所有会出刀的阶段后面）
            night_phases=(WOLF, SEER, WITCH),
            informed=(WITCH,),
        )
