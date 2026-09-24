"""板子：人数、身份分布、阵营分布、特殊身份技能、具体夜晚阶段。

只有数据，不放任何实现：技能写在角色类里（`core.character.Character`，实现在
`werewolf_claw.characters`），一局怎么跑写在法官和系统级里。具体板子见
`werewolf_claw.boards`，一个板子一个目录（`roles.py` + `board.py`）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from werewolf_claw.core.character import Character


@dataclass(frozen=True)
class Board:
    """
    一个板子的全部信息。
    `distribution` 的长度就是人数；`characters` 是身份到角色实现的登记表，特殊身份技能
    也在这里（技能名和技能实现都在角色类上；角色实现放在 `werewolf_claw.characters`，
    可以被多个板子复用）。
    """

    distribution: tuple[str, ...]  # 身份分布：一个位置一个身份名
    camps: Mapping[str, str]  # 阵营分布：身份 -> 阵营
    characters: Mapping[str, Character]  # 特殊身份技能：身份 -> 角色实现
    night_phases: tuple[str, ...] = ()  # 具体夜晚阶段：按这个顺序叫醒
    informed: tuple[str, ...] = ()  # 这些身份夜里还会被告知狼刀目标（如女巫）

    def __post_init__(self) -> None:
        known = set(self.distribution)
        missing_camp = sorted(role for role in known if role not in self.camps)
        if missing_camp:
            raise ValueError(f"这些身份没有给阵营：{missing_camp}")
        missing_character = sorted(role for role in known if role not in self.characters)
        if missing_character:
            raise ValueError(f"这些身份没有给角色实现：{missing_character}")
        for role in sorted(known):
            character = self.characters[role]
            if character.role and character.role != role:
                raise ValueError(f"角色实现和身份对不上：{role} -> {character.role}")
            if character.camp and character.camp != self.camps[role]:
                raise ValueError(f"角色阵营和阵营分布对不上：{role} -> {character.camp}")
        for phase in self.night_phases:
            if phase not in self.characters:
                raise ValueError(f"夜晚阶段 {phase} 没有角色实现")
        for role in self.informed:
            if role not in self.night_phases:
                raise ValueError(f"要告知信息的身份 {role} 不在夜晚阶段里")

    @property
    def size(self) -> int:
        """人数。"""
        return len(self.distribution)
