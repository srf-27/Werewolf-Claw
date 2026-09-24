"""对局节奏：暂停、倍速、以及每个步骤之间的等待。

对局里的等待都走 `sleep()`：暂停时不再扣时间，倍速把等待按倍数压缩。计时器用
`elapsed()` 计算，暂停的时间不计入。
"""

from __future__ import annotations

import threading
import time


class Pace:
    """一局的节奏控制器。"""

    def __init__(self) -> None:
        self._gate = threading.Event()
        self._gate.set()
        self.speed = 1.0
        self.paused_total = 0.0
        self._paused_since: float | None = None

    # ------------------------------------------------------------------ 暂停

    @property
    def paused(self) -> bool:
        return not self._gate.is_set()

    def pause(self) -> None:
        if self._gate.is_set():
            self._paused_since = time.monotonic()
            self._gate.clear()

    def resume(self) -> None:
        if not self._gate.is_set():
            if self._paused_since is not None:
                self.paused_total += time.monotonic() - self._paused_since
                self._paused_since = None
            self._gate.set()

    def set_speed(self, speed: float) -> None:
        self.speed = min(8.0, max(0.5, float(speed)))

    # ------------------------------------------------------------------ 计时

    def wait_gate(self) -> None:
        """暂停时卡在这里；返回后可以继续干活。"""
        while not self._gate.wait(0.2):
            pass

    def sleep(self, seconds: float) -> None:
        """等待一小段时间：暂停不扣时间，倍速压缩等待。"""
        remaining = max(0.0, seconds) / self.speed
        while remaining > 0:
            if not self._gate.is_set():
                self._gate.wait()
                continue
            step = min(0.05, remaining)
            time.sleep(step)
            remaining -= step

    def elapsed(self, started: float, finished: float = 0.0) -> float:
        """对局已用时间：不算暂停的那段。"""
        end = finished or time.monotonic()
        paused = self.paused_total
        if self._paused_since is not None:
            paused += end - self._paused_since
        return max(0.0, end - started - paused)
