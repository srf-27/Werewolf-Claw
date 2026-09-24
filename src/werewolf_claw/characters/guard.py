"""Guard：每晚守一名玩家免受 Werewolf 袭击，不能连着两晚守同一个人。"""

from __future__ import annotations

from typing import Any

from werewolf_claw.core.character import Character


class GuardCharacter(Character):
    """Guard：每晚守一个人，上一晚守过的人今晚不能再守。"""

    role = "Guard"
    camp = "好人阵营"
    skill = "守护"
    describe = (
        "你是 Guard。每晚可以守一名玩家，让他免受 Werewolf 当晚的袭击；可以守自己，"
        "但不能连着两晚守同一个人。守卫只挡狼刀，不挡毒药。"
        "白天你要藏好身份，用发言帮好人找狼。"
    )

    def skill_action(self, player: Any) -> dict[str, Any] | None:
        last = player.last_target("protect")
        candidates = [player.seat, *player.others()]
        if last is not None:
            candidates = [seat for seat in candidates if seat != last]
        return {
            "phase": self.role,
            "target": candidates[0] if candidates else None,
            "effect": "protect",
            # 这一夜能守的人：自己 + 场上其他人，去掉上一晚守过的那个
            "candidates": tuple(candidates),
        }
