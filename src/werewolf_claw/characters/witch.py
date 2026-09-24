"""Witch：一瓶解药、一瓶毒药，各用一次。"""

from __future__ import annotations

from typing import Any

from werewolf_claw.core.character import Character

ROLE = "Witch"
CAMP = "好人阵营"
SKILL = "解药与毒药"


class WitchCharacter(Character):
    """Witch：知道今晚谁被袭击，可以用解药救人，或用毒药毒一个人。"""

    role = ROLE
    camp = CAMP
    skill = SKILL
    effects = ()
    # 女巫可以捏着药不用：空目标合法，不能强迫她兜底自动救人
    can_pass = True
    describe = (
        "你是 Witch，有一瓶解药和一瓶毒药，各只能用一次。"
        "每晚法官会告诉你狼队今晚袭击了谁：你可以用解药救他，也可以毒死场上任意一个人，"
        "但一晚上只能用一瓶药，也可以两瓶都不用（target 给 null 即可）。"
        "解药救不了自己之后被票出局，毒药会直接毒死目标。"
        "白天你要藏好身份，用发言帮好人找狼。"
    )

    def skill_action(self, player: Any) -> dict[str, Any] | None:
        attacked = player.attacked
        if attacked is not None and not player.used("save"):
            return {
                "phase": ROLE,
                "target": attacked,
                "effect": "save",
                "candidates": (attacked,),
            }
        if not player.used("poison"):
            suspects = list(player.suspects())
            if suspects:
                return {
                    "phase": ROLE,
                    "target": suspects[0],
                    "effect": "poison",
                    "candidates": tuple(suspects),
                }
        return {"phase": ROLE, "target": None, "effect": ""}
