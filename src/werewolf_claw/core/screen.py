"""大屏与私聊：对局里所有消息的出口。

大屏（`PUBLIC`）人人都能读，私聊（`PRIVATE`）只有收件人能读。两条通道共用一套
序号：玩家的收件箱是大屏和私聊合起来的，按序号去重才不会漏消息。

信息隔离的判定只有 `Message.visible_to()` 一处；大屏的渲染在 `demos/` 的看板里做，
这里只负责记账。
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

PUBLIC = "public"
PRIVATE = "private"


@dataclass(frozen=True)
class Message:
    """一条消息。`text` 是给人看的台词，`facts` 是给 Agent 用的结构化事实。"""

    seq: int
    day: int
    text: str
    channel: str = PUBLIC
    audience: tuple[int, ...] = ()
    kind: str = ""
    facts: dict[str, Any] = field(default_factory=dict)

    def visible_to(self, seat: int) -> bool:
        """隔离判定：大屏人人可读，私聊只给收件人。"""
        return self.channel == PUBLIC or seat in self.audience


class Screen:
    """大屏：公开发过的消息，谁都能读。

    私聊也从这里走，因为两条通道要用同一个序号；`send()` 发的消息不会出现在大屏上。
    """

    def __init__(self, recorder: Any = None) -> None:
        self.messages: list[Message] = []
        # recorder 是落库钩子：每发一条消息就交给它（大屏/私人记忆分开存）
        self.recorder = recorder
        # 对局跑在后台线程、大屏和网页在别的线程读，序号和列表都要锁住
        self._lock = threading.Lock()

    def publish(
        self,
        day: int,
        text: str,
        *,
        kind: str = "",
        facts: Mapping[str, Any] | None = None,
    ) -> Message:
        """发到大屏：所有人都能读到。"""
        return self._emit(day, text, channel=PUBLIC, audience=(), kind=kind, facts=facts)

    def send(
        self,
        audience: Sequence[int],
        day: int,
        text: str,
        *,
        kind: str = "",
        facts: Mapping[str, Any] | None = None,
    ) -> Message:
        """私聊：只有收件人能读到。"""
        return self._emit(
            day, text, channel=PRIVATE, audience=audience, kind=kind, facts=facts
        )

    def _emit(
        self,
        day: int,
        text: str,
        *,
        channel: str,
        audience: Sequence[int],
        kind: str,
        facts: Mapping[str, Any] | None,
    ) -> Message:
        with self._lock:
            message = Message(
                seq=len(self.messages) + 1,
                day=day,
                text=text,
                channel=channel,
                audience=tuple(audience),
                kind=kind,
                facts=dict(facts or {}),
            )
            self.messages.append(message)
        # 落库放在锁外面：写库慢的时候不能把读大屏的线程也堵住
        if self.recorder is not None:
            self.recorder(message)
        return message

    def public(self) -> list[Message]:
        """大屏上已有的内容。"""
        with self._lock:
            return [message for message in self.messages if message.channel == PUBLIC]

    def read(self, seat: int) -> list[Message]:
        """某个座位能读到的全部消息：大屏 + 投给他的私聊。"""
        with self._lock:
            return [message for message in self.messages if message.visible_to(seat)]

    def snapshot(self) -> list[Message]:
        """全部消息的副本（大屏 + 私聊），给看板这类旁路读者用。"""
        with self._lock:
            return list(self.messages)
