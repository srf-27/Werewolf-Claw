"""把 `.env` 里的模型接成 Agent：法官一个，每个玩家一个。

法官的 `narrate()` 只换说法，事实由法官给；只有重要的播报才调用模型，机械的流程播报
（天黑、请闭眼）直接用模板，省调用也省时间。玩家的 `chat()` 是一问一答，出错就抛回去，
玩家自己会退回规则版。

每个 Agent 各自统计调用次数、耗时和错误，网页看板上显示。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Any

from openai import OpenAI

from werewolf_claw.core import llm

# 法官播报的字数上限（模板本身也在 30 字以内）
MAX_NARRATION_CHARS = 60

# 只有这些播报交给模型润色，其余用模板
NARRATED_KINDS = frozenset({"opening", "dawn", "result", "vote", "elimination", "continue", "game_over"})


@dataclass
class AgentStats:
    """一个 Agent 的模型调用统计。"""

    name: str
    calls: int = 0
    seconds: float = 0.0
    errors: int = 0
    last_error: str = ""
    _lock: Lock = field(default_factory=Lock, repr=False)

    def record(self, seconds: float, error: str = "") -> None:
        with self._lock:
            self.calls += 1
            self.seconds += seconds
            if error:
                self.errors += 1
                self.last_error = error

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "calls": self.calls,
                "seconds": round(self.seconds, 2),
                "errors": self.errors,
                "last_error": self.last_error,
            }


def agent_chat(
    stats: AgentStats,
    *,
    temperature: float = 0.8,
    stop: Event | None = None,
    profile: Mapping[str, str] | None = None,
) -> Callable[..., str]:
    """玩家的对话入口：调 `.env` 里的模型，失败记账后抛给玩家回退。

    `stop` 一旦被设置（对局被结束），后面的调用直接失败，玩家立刻退回规则版跑完这一局。
    `profile` 指定用哪一套配置（`llm.list_profiles()` 里的一项），不给就用当前生效的那套。
    """
    client = (
        _client_for(profile) if profile else None
    )
    model = (profile or {}).get("model") or ""

    def chat(prompt: str, *, system: str | None = None) -> str:
        if stop is not None and stop.is_set():
            raise RuntimeError("对局已结束，不再调用模型")
        started = time.monotonic()
        error = ""
        try:
            if client is None:
                return llm.chat(prompt, system=system, temperature=temperature)
            completion = client.chat.completions.create(
                model=model or llm.default_model(),
                messages=llm.build_messages(prompt, system=system),
                temperature=temperature,
            )
            return completion.choices[0].message.content or ""
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            stats.record(time.monotonic() - started, error)

    def chat_with_tools(
        prompt: str,
        *,
        system: str | None = None,
        tools: Sequence[Mapping[str, Any]] = (),
    ) -> tuple[str, list[Any]]:
        """带工具的一问一答：返回 (文本, tool_calls)，给玩家自己查大屏/记笔记用。"""
        if stop is not None and stop.is_set():
            raise RuntimeError("对局已结束，不再调用模型")
        started = time.monotonic()
        error = ""
        try:
            messages = llm.build_messages(prompt, system=system)
            if client is None:
                completion = llm.chat_full(
                    messages, model=model or None, temperature=temperature, tools=list(tools)
                )
            else:
                completion = client.chat.completions.create(
                    model=model or llm.default_model(),
                    messages=messages,
                    temperature=temperature,
                    tools=list(tools),
                )
            message = completion.choices[0].message
            return (message.content or ""), list(message.tool_calls or ())
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            stats.record(time.monotonic() - started, error)

    # 玩家侧靠这个属性判断模型入口支不支持工具（纯规则模式没有）
    chat.with_tools = chat_with_tools
    chat.supports_tools = True
    return chat


def judge_narrate(
    stats: AgentStats,
    template: Callable[[str, Mapping[str, Any]], str],
    *,
    stop: Event | None = None,
    speed: Callable[[], float] | None = None,
    profile: Mapping[str, str] | None = None,
) -> Callable[[str, Mapping[str, Any]], str]:
    """法官的口播：事实由法官给，模型只换说法；不合格或出错就用模板。"""

    def narrate(kind: str, facts: Mapping[str, Any]) -> str:
        fallback = template(kind, facts)
        if kind not in NARRATED_KINDS or (stop is not None and stop.is_set()):
            return fallback
        if speed is not None and speed() >= 2:
            # 倍速下不再让模型润色播报，直接用模板
            return fallback

        prompt = (
            f"把下面这句狼人杀播报换一种说法，事实一个字都不能变：\n{fallback}\n"
            f"要求：中文，不超过 {MAX_NARRATION_CHARS} 字，只输出这一句话。"
        )
        started = time.monotonic()
        error = ""
        try:
            system = "你是狼人杀法官，只负责播报，不添加任何新信息。"
            client = _client_for(profile) if profile else None
            if client is None:
                text = llm.chat(prompt, system=system, temperature=0.7)
            else:
                completion = client.chat.completions.create(
                    model=(profile or {}).get("model") or llm.default_model(),
                    messages=llm.build_messages(prompt, system=system),
                    temperature=0.7,
                )
                text = completion.choices[0].message.content or ""
            text = text.strip().strip('"').splitlines()[0].strip()
            if not text or len(text) > MAX_NARRATION_CHARS:
                raise ValueError("模型播报不合格")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            text = fallback
        finally:
            stats.record(time.monotonic() - started, error)
        return text

    return narrate


def _client_for(profile: Mapping[str, str]) -> OpenAI:
    """按某一套 `.env` 配置建一个客户端（网页里可以给每个 Agent 单独选）。"""
    return OpenAI(api_key=profile["api_key"], base_url=profile["base_url"] or None)
