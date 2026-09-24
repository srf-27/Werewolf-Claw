"""角色实现，和 `boards/` 平级，一个身份一个类，可以被多个板子复用。

角色只声明身份、阵营、技能名、角色规则（`Character.describe`），并给出技能本身
（`Character.skill_action`）；询问、校验模型输出、回执、发言都在 `agents/` 里实现。
板子按身份登记角色：`characters={身份: 角色实例}`。
"""

from werewolf_claw.characters.guard import GuardCharacter
from werewolf_claw.characters.hunter import HunterCharacter
from werewolf_claw.characters.seer import SeerCharacter
from werewolf_claw.characters.villager import VillagerCharacter
from werewolf_claw.characters.witch import WitchCharacter
from werewolf_claw.characters.wolf import WolfCharacter

__all__ = [
    "GuardCharacter",
    "HunterCharacter",
    "SeerCharacter",
    "VillagerCharacter",
    "WitchCharacter",
    "WolfCharacter",
]
