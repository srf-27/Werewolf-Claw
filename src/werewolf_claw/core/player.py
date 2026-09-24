"""玩家对外的契约。

法官和系统级只认这几个方法，不关心背后是模型、规则还是测试替身。玩家的具体实现
见 `werewolf_claw.agents.player_agent.PlayerAgent`。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from werewolf_claw.core.screen import Message

class PlayerProtocol(Protocol):
    """一个座位上的玩家。"""

    # IS_special 标识：有它才和法官建立夜间私聊。
    is_special: bool

    def receive(self, messages: Sequence[Message]) -> int:
        """收下投递的消息，返回新收了几条。"""

    def night_action(self, phase: str, alive: Sequence[int]) -> dict[str, Any]:
        """私聊回答一次夜间动作，例如 {"phase": "Werewolf", "target": 3}。"""

    def statement(self, alive: Sequence[int]) -> dict[str, Any]:
        """报一次公开发言，例如 {"text": "…", "target": 3}。"""

    def ballot(self, alive: Sequence[int]) -> dict[str, Any]:
        """报一次投票，例如 {"target": 3}；target 为 None 表示弃票。"""

    def team_talk(self, phase: str, alive: Sequence[int], round_no: int) -> str:
        """多人同夜行动时的队伍讨论：说一句自己的意见（狼人商量刀谁）。"""

    def death_action(self, cause: str, alive: Sequence[int]) -> dict[str, Any] | None:
        """出局时发动死亡触发技（猎人开枪），没有就返回 None。"""

    def watch(self) -> None:
        """没有请求时的一次轮询：只同步大屏，不产出动作。"""
