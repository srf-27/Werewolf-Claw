"""Werewolf：夜里和队友一起选一个目标袭击，可以空刀或自刀。"""

from __future__ import annotations

from typing import Any

from werewolf_claw.core.character import Character


class WolfCharacter(Character):
    """Werewolf：狼队共同决定袭击目标，可以刀好人、刀队友，也可以自刀。"""

    role = "Werewolf"
    camp = "Werewolf 阵营"
    skill = "袭击"
    # 夜里能出刀：法官靠它认出「会出刀的阶段」，好校验女巫这类 informed 阶段排在它后面。
    effects = ("kill",)
    describe = (
        "你是 Werewolf，夜里和队友一起行动。每晚狼队共同决定一个袭击目标：可以刀好人、"
        "刀队友，也可以自刀（自刀常用来骗药或做局），也可以空刀；"
        "目标被守卫守住则这一夜不出局。白天你要藏住身份、混在好人里发言，把票引到好人身上。"
        "狼队的目标是淘汰所有 Villager 或神职。"
    )

    def skill_action(self, player: Any) -> dict[str, Any] | None:
        # Werewolf 可以自刀，所以候选里连自己和队友都在
        candidates = [player.seat, *player.others()]
        enemies = [seat for seat in player.others() if seat not in player.allies]
        return {
            "phase": self.role,
            "target": (enemies or candidates or [None])[0],
            "effect": "kill",
            "candidates": tuple(candidates),
        }
