"""具体板子。一个板子一个目录：`roles.py` 放身份与阵营，`board.py` 放具体板子类。

角色实现不在板子里，在和 `boards/` 平级的 `werewolf_claw/characters/`，一个身份一个类，
可以被多个板子复用；板子只按身份登记它们。

当前只保留默认板子：9 人标准板（3 Werewolf + 3 Villager + Seer + Witch + Hunter），
和 Werewolf-VectorDB 的板子完全对齐。`standard12_board/` 的文件仍保留以便后续扩展，
但已从可选板子里移除，前端不再能切换。
"""

from werewolf_claw.boards.default_board import (
    CAMP,
    DEFAULT_BOARD,
    HUNTER,
    ROLE_CAMP,
    ROLES,
    SEER,
    VILLAGER,
    WITCH,
    WOLF,
    DefaultBoard,
    RoleSpec,
)
from werewolf_claw.boards.standard12_board import STANDARD12_BOARD
from werewolf_claw.characters import (
    GuardCharacter,
    HunterCharacter,
    SeerCharacter,
    VillagerCharacter,
    WitchCharacter,
    WolfCharacter,
)
from werewolf_claw.core.board import Board

# 网页端能选的板子：id -> 板子实例。只有一种板子，切换已废弃。
BOARDS: dict[str, Board] = {
    "default_board": DEFAULT_BOARD,
}

# 板子在界面上的名字
BOARD_LABELS: dict[str, str] = {
    "default_board": "9 人标准板",
}


def board_by_id(board_id: str) -> Board:
    """按 id 取板子，取不到就用默认板子。"""
    return BOARDS.get(board_id, DEFAULT_BOARD)


def board_id_of(board: Board) -> str:
    """反查板子的 id。"""
    for board_id, candidate in BOARDS.items():
        if candidate is board:
            return board_id
    return ""


def board_options() -> list[dict[str, object]]:
    """给网页的板子清单。"""
    return [
        {
            "id": board_id,
            "name": BOARD_LABELS.get(board_id, board_id),
            "size": board.size,
            "distribution": list(board.distribution),
            "night_phases": list(board.night_phases),
        }
        for board_id, board in BOARDS.items()
    ]

__all__ = [
    "BOARDS",
    "BOARD_LABELS",
    "CAMP",
    "DEFAULT_BOARD",
    "STANDARD12_BOARD",
    "HUNTER",
    "ROLE_CAMP",
    "ROLES",
    "SEER",
    "VILLAGER",
    "WITCH",
    "WOLF",
    "DefaultBoard",
    "RoleSpec",
    "GuardCharacter",
    "HunterCharacter",
    "SeerCharacter",
    "VillagerCharacter",
    "WitchCharacter",
    "WolfCharacter",
    "board_by_id",
    "board_id_of",
    "board_options",
]
