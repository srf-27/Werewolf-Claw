"""默认板子：9 人标准板（3 Werewolf + 3 Villager + Seer + Witch + Hunter）。

目录结构：

- `roles.py`：`ROLES` 一张表放身份、阵营、技能，阵营分布从它派生；
- `board.py`：具体板子类，把人数、身份分布、阵营分布、特殊身份技能、夜晚阶段给出来；

角色实现放在和 `boards/` 平级的 `werewolf_claw/characters/`，一个身份一个类，可以被
多个板子复用。
"""

from .board import DefaultBoard
from .roles import (
    CAMP,
    HUNTER,
    ROLE_CAMP,
    ROLES,
    SEER,
    VILLAGER,
    WITCH,
    WOLF,
    RoleSpec,
)

# 默认板子的实例。玩家和法官不给板子时就用它。
DEFAULT_BOARD = DefaultBoard()

__all__ = [
    "CAMP",
    "DEFAULT_BOARD",
    "HUNTER",
    "ROLE_CAMP",
    "ROLES",
    "SEER",
    "VILLAGER",
    "WITCH",
    "WOLF",
    "DefaultBoard",
    "RoleSpec",
]
