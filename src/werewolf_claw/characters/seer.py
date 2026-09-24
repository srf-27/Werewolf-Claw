"""Seer：每晚查验一名玩家的阵营。"""

from __future__ import annotations

from typing import Any

from werewolf_claw.core.character import Character


class SeerCharacter(Character):
    """Seer：查一个还没查过的人；查验不改变场上状态，只给自己一条情报。"""

    role = "Seer"
    camp = "好人阵营"
    skill = "查验"
    describe = (
        "你是 Seer。每晚可以查验一名存活玩家的阵营，结果只有你自己知道："
        "好人叫金水，Werewolf 叫查杀；不能查自己。"
        "白天轮到你发言时报出查验结果，带好人把票投到狼身上；"
        "你可以先不报查验结果，等别人假装 Seer 时跟他反跳"
        "Werewolf 可能冒充 Seer，你要用查验结果站住脚。"
    )

    def skill_action(self, player: Any) -> dict[str, Any] | None:
        checked = {target for target, _ in player.checks()}
        rest = [seat for seat in player.others() if seat not in checked]
        return {
            "phase": self.role,
            "target": rest[0] if rest else None,
            "effect": "check",
            "candidates": tuple(rest),
        }
