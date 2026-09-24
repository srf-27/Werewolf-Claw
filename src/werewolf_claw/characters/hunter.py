"""Hunter：出局时可以开枪带走一个人，被毒死时不能开枪。"""

from __future__ import annotations

from typing import Any

from werewolf_claw.core.character import Character

ROLE = "Hunter"
CAMP = "好人阵营"
SKILL = "开枪"


class HunterCharacter(Character):
    """Hunter：被刀、被票出局时开枪带走一个人；被毒死不能开枪。"""

    role = ROLE
    camp = CAMP
    skill = SKILL
    describe = (
        "你是 Hunter，没有夜间技能。你被 Werewolf 杀死或被投票放逐时，可以开枪带走场上任意一个人；"
        "但如果你是被人毒死的，就不能开枪。白天你要藏好身份，别早早把枪暴露给狼。"
    )

    def skill_action(self, player: Any) -> dict[str, Any] | None:
        # 这个技能只在出局时触发；被毒死不带枪
        if player.alive or player.death_cause == "poison":
            return None
        suspects = list(player.suspects()) or [seat for seat in player.others()]
        if not suspects:
            return None
        return {
            "phase": ROLE,
            "target": suspects[0],
            "effect": "shoot",
            "candidates": tuple(suspects),
        }
