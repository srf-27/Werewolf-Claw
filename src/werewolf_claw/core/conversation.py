"""一轮问答的基础实现：写用户消息、取上下文、调模型、写回回复。

一步问答拆成三段，方便上层在中间插入别的步骤（网页版聊天 Agent 就是靠这个在
「写用户消息」和「写回回复」之间插工具调用）：

- `open_turn()`：写入用户消息，拿回 `TurnHandle`；
- `ask()`：按当前记忆拼上下文问一次模型（可以带工具清单）；
- `answer_turn()`：把回答写回记忆，拼成 `TurnResult`。

`send()` / `edit_last()` / `regenerate()` 是不带工具的简单路径，命令行 demo 直接用它们。

这里不依赖任何 Web 框架，也不打印任何东西，抛的是领域错误：

- `InvalidRequest`：参数不合法（空消息、引用不在本会话等）。
- `ConflictError`：当前状态不允许（没有可编辑的消息、重新生成次数用尽等）。
- `ModelError`：调用模型失败。

Web 层负责把这些错误映射成 HTTP 状态码，命令行层负责打印。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from openai import NOT_GIVEN, OpenAIError
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionMessageParam

from .llm import chat_full
from .memory import Memory

SYSTEM_PROMPT = "你是一个狼人杀辅助助手，用中文回答玩家的问题。"

# 采样温度：越高越随机。
TEMPERATURE = 0.7

# 一条回复最多重新生成几次。
MAX_REGENERATE = 5

REVISE_PROMPT = """
上面这个问题已经回答过 {round} 次，之前的回答是：

{attempts}

请先指出这些回答的不足，再给出一个更好的回答。严格按下面两段输出，不要写别的内容：
【不足】用一两句话说明之前回答的问题
【回答】改进后的完整回答
"""

LLM_ERRORS = (OpenAIError, RuntimeError)


class ChatError(RuntimeError):
    """对话流程里可以预期到的错误。"""


class InvalidRequest(ChatError):
    """参数不合法。"""


class ConflictError(ChatError):
    """当前状态不允许这个操作。"""


class ModelError(ChatError):
    """调用模型失败。"""


@dataclass(frozen=True)
class Quote:
    """引用某条消息：会话 id + 消息序号，两者都要对得上。"""

    session_id: str
    seq: int


@dataclass
class TurnResult:
    """一轮问答的结果，供各个入口拼自己的响应。"""

    reply: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    remembered: bool = False
    compressed: bool = False
    title: str = ""
    regenerate_count: int = 0
    max_regenerate: int = MAX_REGENERATE


@dataclass(frozen=True)
class TurnHandle:
    """已经写进记忆、还没生成回答的一轮问答。"""

    # 这条用户消息的序号，写回回答前用它确认这轮没被编辑或撤回。
    seq: int
    # 用户这句是否命中了长期记忆触发词。
    remembered: bool = False


@dataclass(frozen=True)
class ModelAnswer:
    """一次模型调用的结果：正文、要调的工具、用量。"""

    content: str
    # 模型返回的 tool_calls（SDK 对象），交给 `tools.ToolExecutor.parse_tool_calls()` 解析。
    tool_calls: list[Any] = field(default_factory=list)
    usage: CompletionUsage | None = None


def split_revision(text: str) -> tuple[str, str]:
    """从「先总结不足再回答」的输出里拆出回答和不足说明。"""
    marker = "【回答】"
    if text and marker in text:
        head, _, body = text.partition(marker)
        return body.strip() or text.strip(), head.replace("【不足】", "").strip()
    return text.strip(), ""


def _resolve_quote(memory: Memory, quote: Quote | None) -> dict[str, Any] | None:
    """校验引用：必须属于当前会话，且这条消息真的存在。"""
    if quote is None:
        return None
    if quote.session_id != memory.session_id:
        raise InvalidRequest("引用的消息不在这个会话里")
    excerpt = memory.message_excerpt(quote.seq)
    if excerpt is None:
        raise InvalidRequest("引用的消息不在这个会话里")
    return {"session_id": quote.session_id, "seq": quote.seq, "excerpt": excerpt}


def _call(
    context: list[ChatCompletionMessageParam],
    *,
    tools: Sequence[Mapping[str, Any]] | None = None,
    temperature: float = TEMPERATURE,
) -> ModelAnswer:
    """调一次模型，把 SDK 的回复压成 `ModelAnswer`，失败时抛 `ModelError`。"""
    try:
        completion = chat_full(context, temperature=temperature, tools=tools or NOT_GIVEN)
    except LLM_ERRORS as exc:
        raise ModelError(f"调用模型失败：{exc}") from exc
    message = completion.choices[0].message
    return ModelAnswer(
        content=message.content or "",
        tool_calls=list(message.tool_calls or ()),
        usage=completion.usage,
    )


def _refresh_title(memory: Memory) -> str:
    """第一轮之后自动生成标题，失败不影响这一轮对话。"""
    title = memory.display_title()
    if not memory.title() and not memory.title_locked():
        try:
            title = memory.auto_title() or title
        except LLM_ERRORS:
            pass
    return title


def open_turn(memory: Memory, text: str, quote: Quote | None = None) -> TurnHandle:
    """写入用户消息，返回这一轮的凭据。

    空消息抛 `InvalidRequest`；引用不在本会话也在这里拦下。
    """
    content = text.strip()
    if not content:
        raise InvalidRequest("消息内容不能为空")

    remembered = memory.add_user(content, _resolve_quote(memory, quote))
    user, _ = memory.last_exchange()
    if user is None:
        raise ConflictError("这条消息已被编辑或撤回，本次回复已丢弃")
    return TurnHandle(seq=int(user["seq"]), remembered=remembered)


def ask(
    memory: Memory,
    *,
    system: str | None = None,
    tools: Sequence[Mapping[str, Any]] | None = None,
    extra_messages: Sequence[Mapping[str, Any]] = (),
    temperature: float = TEMPERATURE,
) -> ModelAnswer:
    """按当前记忆拼上下文问一次模型。

    `system` 省略时用 `SYSTEM_PROMPT`；`tools` 是给模型的工具清单；
    `extra_messages` 接在历史后面，用来把工具调用那一轮（assistant 的 tool_calls +
    每条 tool 结果）补进上下文。
    """
    context = memory.build_context(system or SYSTEM_PROMPT)
    context.extend(dict(message) for message in extra_messages)
    return _call(context, tools=tools, temperature=temperature)


def answer_turn(
    memory: Memory,
    handle: TurnHandle,
    reply: str,
    usage: CompletionUsage | None = None,
) -> TurnResult:
    """把回答写回记忆，返回这一轮的结果。

    等待期间这轮被编辑或撤回了（最后一条用户消息不再是刚才那条）就把回答丢掉，不写进记忆。
    """
    current_user, _ = memory.last_exchange()
    if current_user is None or int(current_user["seq"]) != handle.seq:
        raise ConflictError("这条消息已被编辑或撤回，本次回复已丢弃")

    compressed = memory.add_assistant(reply, usage=usage)
    added, _ = memory.message_page(limit=2)
    return TurnResult(
        reply=reply,
        messages=added,
        remembered=handle.remembered,
        compressed=compressed,
        title=_refresh_title(memory),
    )


def send(memory: Memory, text: str, quote: Quote | None = None) -> TurnResult:
    """发一条用户消息：写库、调模型、写回回复，必要时自动生成标题。

    这是不带工具的简单路径。要带工具就按 `open_turn()` -> `ask()` -> `answer_turn()`
    三步自己接（见 `agents/chat_agent.py` 的推断节点和回复节点）。
    """
    handle = open_turn(memory, text, quote)
    answer = ask(memory)
    return answer_turn(memory, handle, answer.content, answer.usage)


def retract_last(memory: Memory) -> int:
    """撤回最后一轮问答，返回删掉的条数；没有可撤的回答就抛 `ConflictError`。"""
    removed = memory.truncate_last_exchange()
    if removed == 0:
        raise ConflictError("没有可编辑的消息")
    return removed


def edit_last(memory: Memory, text: str) -> TurnResult:
    """撤回最后一轮问答，用编辑后的内容重新提问。

    这是不带工具的简单路径：先 `retract_last()` 再 `send()`。网页版聊天 Agent 把这两步
    分开，撤回之后重新走一遍「推断要不要调工具」。
    """
    retract_last(memory)
    return send(memory, text)


def regenerate(memory: Memory) -> TurnResult:
    """重新生成最后一条回复，最多 MAX_REGENERATE 次。

    每次都把之前几次的回答交给模型，让它先总结不足再重新回答；
    旧回答只留在数据库的 extra 里，不作为消息显示。
    """
    user, reply = memory.last_exchange()
    if user is None or reply is None:
        raise ConflictError("还没有可重新生成的回复")

    extra = memory.message_extra(reply["seq"])
    count = int(extra.get("regenerate_count") or 0)
    if count >= MAX_REGENERATE:
        raise ConflictError(f"一条回复最多重新生成 {MAX_REGENERATE} 次")

    attempts = [str(item) for item in extra.get("attempts") or []] or [reply["content"]]
    context = memory.build_context(SYSTEM_PROMPT, without_last_reply=True)
    context.append(
        {
            "role": "user",
            "content": REVISE_PROMPT.format(
                round=count + 1,
                attempts="\n\n".join(
                    f"第 {index} 次：{text}" for index, text in enumerate(attempts, start=1)
                ),
            ),
        }
    )

    raw = _call(context)
    new_reply, shortcoming = split_revision(raw.content)
    memory.update_message(
        reply["seq"],
        new_reply,
        extra={
            **extra,
            "regenerate_count": count + 1,
            "attempts": [*attempts, reply["content"]],
            "shortcomings": [
                *[str(item) for item in extra.get("shortcomings") or []],
                *([shortcoming] if shortcoming else []),
            ],
        },
    )
    return TurnResult(
        reply=new_reply,
        messages=[memory.timeline()[-1]],
        title=memory.display_title(),
        regenerate_count=count + 1,
    )
