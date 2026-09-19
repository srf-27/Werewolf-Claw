"""LLM 调用封装，基于 openai SDK。

对外提供两个入口：

- `chat()`: 简单调用。给一句提示词，直接拿回回复文本。
- `chat_full()`: 全参数调用。透传 SDK 的生成参数，拿回原始 `ChatCompletion` 对象，
  可以继续读 `usage`、`tool_calls`、`finish_reason` 等字段。

配置从环境变量读取：

- `OPENAI_API_KEY`: 必填，API 密钥。
- `OPENAI_BASE_URL`: 可选，兼容 OpenAI 协议的服务地址。
- `LLM_MODEL` 或 `OPENAI_MODEL`: 可选，默认模型名。
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from openai import NOT_GIVEN, NotGiven, OpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam

DEFAULT_MODEL = os.environ.get("LLM_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"

_client: OpenAI | None = None


def get_client() -> OpenAI:
    """返回全局客户端，首次调用时根据环境变量创建。"""
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("未设置环境变量 OPENAI_API_KEY")
        _client = OpenAI(api_key=api_key, base_url=os.environ.get("OPENAI_BASE_URL"))
    return _client


def set_client(client: OpenAI | None) -> None:
    """替换全局客户端；传 None 表示清除缓存。

    用于测试注入假客户端，或接入 AzureOpenAI 等自定义实例。
    """
    global _client
    _client = client


def build_messages(
    prompt: str,
    system: str | None = None,
    history: Iterable[ChatCompletionMessageParam] | None = None,
) -> list[ChatCompletionMessageParam]:
    """拼装消息列表，顺序为：system、history、当前 user 提示词。"""
    messages: list[ChatCompletionMessageParam] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.extend(history or [])
    messages.append({"role": "user", "content": prompt})
    return messages


def chat(
    prompt: str,
    *,
    system: str | None = None,
    history: Iterable[ChatCompletionMessageParam] | None = None,
    model: str = DEFAULT_MODEL,
    temperature: float | None = None,
) -> str:
    """简单调用，返回模型回复的纯文本。

    >>> chat("用一句话介绍狼人杀")
    """
    completion = chat_full(
        build_messages(prompt, system=system, history=history),
        model=model,
        temperature=NOT_GIVEN if temperature is None else temperature,
    )
    return completion.choices[0].message.content or ""


def chat_full(
    messages: Iterable[ChatCompletionMessageParam],
    *,
    model: str = DEFAULT_MODEL,
    temperature: float | NotGiven = NOT_GIVEN,
    top_p: float | NotGiven = NOT_GIVEN,
    max_tokens: int | NotGiven = NOT_GIVEN,
    max_completion_tokens: int | NotGiven = NOT_GIVEN,
    n: int | NotGiven = NOT_GIVEN,
    stop: str | Sequence[str] | NotGiven = NOT_GIVEN,
    presence_penalty: float | NotGiven = NOT_GIVEN,
    frequency_penalty: float | NotGiven = NOT_GIVEN,
    logit_bias: Mapping[str, int] | NotGiven = NOT_GIVEN,
    seed: int | NotGiven = NOT_GIVEN,
    response_format: Mapping[str, Any] | NotGiven = NOT_GIVEN,
    tools: Iterable[Mapping[str, Any]] | NotGiven = NOT_GIVEN,
    tool_choice: str | Mapping[str, Any] | NotGiven = NOT_GIVEN,
    parallel_tool_calls: bool | NotGiven = NOT_GIVEN,
    reasoning_effort: str | NotGiven = NOT_GIVEN,
    service_tier: str | NotGiven = NOT_GIVEN,
    store: bool | NotGiven = NOT_GIVEN,
    metadata: Mapping[str, str] | NotGiven = NOT_GIVEN,
    user: str | NotGiven = NOT_GIVEN,
    timeout: float | None = None,
    extra_body: Mapping[str, Any] | None = None,
) -> ChatCompletion:
    """全参数调用，返回原始 `ChatCompletion` 对象。

    参数默认值是 `NOT_GIVEN`，表示不发送该字段，交给服务端取默认值。
    要显式传空值时用 `None`，例如 `stop=None`。
    流式输出未封装，需要时用 `get_client().chat.completions.create(..., stream=True)`。
    """
    optional: dict[str, Any] = {
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "max_completion_tokens": max_completion_tokens,
        "n": n,
        "stop": stop,
        "presence_penalty": presence_penalty,
        "frequency_penalty": frequency_penalty,
        "logit_bias": logit_bias,
        "seed": seed,
        "response_format": response_format,
        "tools": tools,
        "tool_choice": tool_choice,
        "parallel_tool_calls": parallel_tool_calls,
        "reasoning_effort": reasoning_effort,
        "service_tier": service_tier,
        "store": store,
        "metadata": metadata,
        "user": user,
        "timeout": timeout,
        "extra_body": extra_body,
    }
    kwargs = {name: value for name, value in optional.items() if not isinstance(value, NotGiven)}
    return get_client().chat.completions.create(messages=list(messages), model=model, **kwargs)
