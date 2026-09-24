"""人类接管一个座位：玩家要问模型时改成问人。

接管时把 `PlayerAgent.chat` 换成这里的 `ask()`：对局线程停下来等网页提交答案，超时就
抛回去，玩家自己退回规则版继续。退出接管后换回原来的模型入口，Agent 的收件箱和私有
记忆都还在，等于原地重连。

网页只需要知道「谁、什么身份、现在要干什么」，不需要看 prompt——那些信息人类自己能从
大屏看到。
"""

from __future__ import annotations

import threading
import time
from typing import Any

# 每种动作给人类多少时间（秒），和 rules 里的 60s 发言、10s 投票对齐
TIMEOUTS: dict[str, float] = {
    "发言": 60.0,
    "投票": 10.0,
    "技能": 10.0,
    "讨论": 20.0,
    "出局技能": 10.0,
}
DEFAULT_TIMEOUT = 20.0


class HumanSeat:
    """一个座位的人类输入通道。"""

    def __init__(self, player: Any, name: str) -> None:
        self.player = player
        self.seat = int(player.seat)
        self.name = name
        self._lock = threading.Lock()
        self._answered = threading.Event()
        self._cancel = threading.Event()
        self._answer = ""
        self._pending: dict[str, Any] | None = None

    # ------------------------------------------------------------------ 玩家侧

    def ask(self, prompt: str, *, system: str | None = None) -> str:
        """替代模型入口：把「该谁做什么」挂出来，等人类回答；超时就抛回去。"""
        kind = str(getattr(self.player, "request_kind", "") or "操作")
        timeout = TIMEOUTS.get(kind, DEFAULT_TIMEOUT)
        # 女巫专属上下文：前端据此展示"救/毒/不用"选项
        context: dict[str, Any] = {}
        role = str(getattr(self.player, "role", ""))
        if role == "Witch" and kind == "技能":
            context = {
                "attacked": getattr(self.player, "attacked", None),
                "used_save": bool(self.player.used("save")),
                "used_poison": bool(self.player.used("poison")),
            }
        with self._lock:
            self._answer = ""
            self._pending = {
                "seat": self.seat,
                "name": self.name,
                "kind": kind,
                "role": role,
                "camp": str(getattr(self.player, "camp", "")),
                "allies": sorted(getattr(self.player, "allies", ())),
                "context": context,
                "timeout": timeout,
                "deadline": time.time() + timeout,
                "asked": time.time(),
            }
            self._answered.clear()
            self._cancel.clear()

        answered = self._answered.wait(timeout)
        with self._lock:
            answer = self._answer
            self._pending = None
        if self._cancel.is_set():
            raise RuntimeError("人类退出接管，改用模型")
        if not answered:
            raise TimeoutError(f"{kind}超时，交给 Agent 自己决定")
        return answer

    # ------------------------------------------------------------------ 网页侧

    def submit(self, text: str) -> bool:
        """网页提交答案；没有在等答案时返回 False。"""
        with self._lock:
            if self._pending is None:
                return False
            self._answer = text
        self._answered.set()
        return True

    def cancel(self) -> None:
        """退出接管：让等待中的请求结束，玩家回退到规则版。"""
        self._cancel.set()

    def pending(self) -> dict[str, Any] | None:
        """当前挂起的东西，给网页显示（身份 + 要做什么 + 倒计时）。"""
        with self._lock:
            if self._pending is None:
                return None
            pending = dict(self._pending)
        pending["waited"] = round(time.time() - pending.pop("asked", time.time()), 1)
        pending["left"] = round(max(0.0, pending["deadline"] - time.time()), 1)
        return pending
