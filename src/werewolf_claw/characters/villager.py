"""Villager：没有技能，夜里闭眼，靠白天的发言和投票找狼。"""

from __future__ import annotations

from werewolf_claw.core.character import Character


class VillagerCharacter(Character):
    """Villager：没有技能，白天按通用说法发言、投票。"""

    role = "Villager"
    camp = "好人阵营"
    describe = (
        "你是 Villager，没有夜间技能，夜里闭眼。"
        "只能靠白天听到的发言、看到的态度和票型判断谁是 Werewolf，把票投给最像狼的人，"
        "帮好人把狼全部投出去。"
    )
