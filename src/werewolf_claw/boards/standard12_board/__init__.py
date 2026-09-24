"""12 人标准板（4 Werewolf + 4 Villager + Seer / Witch / Hunter / Guard）。已废弃切换，仅保留文件。

- `roles.py`：`ROLES` 一张表放身份、阵营、技能，阵营分布从它派生；
- `board.py`：具体板子类。

角色实现复用和 `boards/` 平级的 `werewolf_claw/characters/`。
"""

from .board import Standard12Board
from .roles import CAMP, ROLE_CAMP, ROLES, RoleSpec

# 这个板子的实例。
STANDARD12_BOARD = Standard12Board()

__all__ = ["CAMP", "ROLE_CAMP", "ROLES", "STANDARD12_BOARD", "RoleSpec", "Standard12Board"]
