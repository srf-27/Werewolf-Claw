"""
角色父类：身份、阵营、技能名、角色规则，加上技能本身。
"""

from __future__ import annotations

from typing import Any


class Character:
    """角色父类：身份、阵营、技能名、角色规则，以及技能本身。"""

    role: str = ""
    camp: str = ""
    skill: str | None = None
    describe: str = ""  # 这个角色的规则说明，player_agent 读进 prompt
    # 这个角色夜里能产生的效果（如狼人的 "kill"）。法官靠它判断哪些阶段会出刀，
    # 好把「informed 阶段必须晚于出刀阶段」这条板子约束校验出来。
    effects: tuple[str, ...] = ()
    # 这一夜的技能可以主动不用（女巫捏着药不救）。False 时模型/人类必须给目标，
    # 缺目标会退回规则建议；True 时空目标被接受为「不用技能」，不烧掉次数。
    can_pass: bool = False

    def skill_action(self, player: Any) -> dict[str, Any] | None:
        """这一夜的技能动作；普通身份没有技能，返回 None。

        动作是 {"phase", "target", "effect"}，可以再给 "candidates"（这一夜允许选的目标）。
        """
        return None
