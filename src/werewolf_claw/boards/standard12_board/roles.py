"""12 人标准板的身份和阵营（已废弃切换，仅保留文件避免依赖断裂）。

角色名和向量库对齐：Werewolf / Villager / Seer / Witch / Hunter / Guard。
"""

from __future__ import annotations

from dataclasses import dataclass

# 身份
WOLF = "Werewolf"
GUARD = "Guard"
SEER = "Seer"
WITCH = "Witch"
HUNTER = "Hunter"
VILLAGER = "Villager"

# 阵营
CAMP: list[str] = [
    "Werewolf 阵营",
    "好人阵营",
]


@dataclass(frozen=True)
class RoleSpec:
    """一个身份的说明：名字、阵营、特殊技（普通身份没有技能）。"""

    # 名称
    name: str
    # 阵营
    camp: str
    # 技能
    skill: str | None = None


# 身份 -> 说明
ROLES: dict[str, RoleSpec] = {
    WOLF: RoleSpec("Werewolf", "Werewolf 阵营", "袭击"),
    GUARD: RoleSpec("Guard", "好人阵营", "守护"),
    SEER: RoleSpec("Seer", "好人阵营", "查验"),
    WITCH: RoleSpec("Witch", "好人阵营", "解药与毒药"),
    HUNTER: RoleSpec("Hunter", "好人阵营", "开枪"),
    VILLAGER: RoleSpec("Villager", "好人阵营"),
}

# 阵营分布：身份 -> 阵营，从 ROLES 派生，板子直接用它
ROLE_CAMP: dict[str, str] = {name: spec.camp for name, spec in ROLES.items()}
