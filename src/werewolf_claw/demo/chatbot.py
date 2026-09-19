"""简单聊天机器人：Node + Flow 组链路，对话记录交给 Memory 持久化。

链路：InputNode -"reply"-> ReplyNode -"default"-> InputNode（回到输入，形成循环），
InputNode -"history"-> HistoryNode -> InputNode，InputNode -"sessions"-> SessionsNode
-> InputNode，InputNode -"exit"-> ExitNode 结束。

运行：

    uv run python -m werewolf_claw.demo.chatbot            # 先问要不要进旧会话
    uv run python -m werewolf_claw.demo.chatbot game-1     # 直接进指定会话

记录存在 memory/chat.db，按会话 id 隔离：退出时会用模型给会话起个标题，下次启动
会列出「会话 id -> 标题」让你挑，进去先回放最近 10 条消息。聊天中输入 `history`
看当前会话的全部历史，`sessions` 看所有会话。用户明确说"记住…"时写长期记忆，
上下文到 90% 时自动压缩。配置从项目根目录的 .env 读取。
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from dotenv import load_dotenv

from werewolf_claw.core.llm import chat_full
from werewolf_claw.core.memory import ROLE_LABELS, Memory
from werewolf_claw.core.node import DEFAULT_ACTION, Flow, Node

# .env 是本地配置的唯一来源，系统里已有同名环境变量时也以 .env 为准。
load_dotenv(override=True)

SYSTEM_PROMPT = "你是狼人杀游戏里的助手，用中文简短回答玩家的问题。"

EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit"}
HISTORY_COMMANDS = {"history", "/history", "hist"}
SESSIONS_COMMANDS = {"sessions", "/sessions"}

# 只用来打开库、列会话，不写消息，所以不会出现在会话列表里。
LIST_ONLY_SESSION_ID = "__list_sessions__"

# 进入旧会话时回放的消息条数。
RECENT_MESSAGES_ON_ENTER = 10


class InputNode(Node):
    """读一行玩家输入，写进记忆，决定继续对话还是退出。"""

    def __init__(self, memory: Memory, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.memory = memory

    def exec(self, payload: Any) -> tuple[str, Any]:
        try:
            text = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return "exit", None
        lowered = text.lower()
        if not lowered or lowered in EXIT_COMMANDS:
            return "exit", None
        if lowered in HISTORY_COMMANDS:
            return "history", None
        if lowered in SESSIONS_COMMANDS:
            return "sessions", None
        if self.memory.add_user(text):
            print("（收到，已记入长期记忆）")
        return "reply", text


class ReplyNode(Node):
    """从记忆里取上下文发给 LLM，打印回复，再把回复写回记忆。"""

    def __init__(self, memory: Memory, system_prompt: str = SYSTEM_PROMPT, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.memory = memory
        self.system_prompt = system_prompt

    def exec(self, payload: Any) -> tuple[str, Any]:
        completion = chat_full(self.memory.build_context(self.system_prompt), temperature=0.7)
        reply = completion.choices[0].message.content or ""
        print(f"机器人: {reply}")
        if self.memory.add_assistant(reply, usage=completion.usage):
            print("（上下文已压缩，更早的内容转入摘要）")
        return DEFAULT_ACTION, reply


class ExitNode(Node):
    """收尾：打印道别。"""

    def exec(self, payload: Any) -> tuple[str, Any]:
        print("再见。")
        return DEFAULT_ACTION, None


class HistoryNode(Node):
    """打印当前会话的全部历史，然后回到输入。"""

    def __init__(self, memory: Memory, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.memory = memory

    def exec(self, payload: Any) -> tuple[str, Any]:
        print_history(self.memory)
        return DEFAULT_ACTION, None


class SessionsNode(Node):
    """打印所有会话的 id 和标题，然后回到输入。"""

    def __init__(self, memory: Memory, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.memory = memory

    def exec(self, payload: Any) -> tuple[str, Any]:
        print_sessions(self.memory)
        return DEFAULT_ACTION, None


def print_messages(messages: Iterable[dict[str, Any]]) -> None:
    """按角色打印消息正文。"""
    for message in messages:
        label = ROLE_LABELS.get(str(message["role"]), str(message["role"]))
        print(f"  {label}：{message['content']}")


def format_time(value: str) -> str:
    """把库里存的 UTC 时间转成本地时间的简写。"""
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


def print_sessions(memory: Memory) -> None:
    """打印库里所有会话的 id 和标题。"""
    sessions = memory.list_sessions()
    if not sessions:
        print("还没有任何会话。")
        return
    print(f"共 {len(sessions)} 个会话（id -> 标题）：")
    for session_id, title in sessions.items():
        current = "（当前）" if session_id == memory.session_id else ""
        print(f"  {session_id} -> {title or '（无标题）'}{current}")


def print_history(memory: Memory) -> None:
    """打印当前会话的全部历史信息：基本信息、长期记忆、摘要、所有消息。"""
    rows = memory.timeline()
    memories = memory.long_term_memories()
    compacted = sum(1 for row in rows if row["compacted"])

    print(f"会话 {memory.session_id}｜标题：{memory.title() or '（无标题）'}")
    print(f"消息 {len(rows)} 条（其中已压缩 {compacted} 条），长期记忆 {len(memories)} 条")
    if memories:
        print("长期记忆：")
        for item in memories:
            print(f"  - {item}")
    summary = memory.summary()
    if summary:
        print(f"历史摘要：\n  {summary}")
    if not rows:
        print("还没有消息。")
        return

    print("全部消息：")
    for row in rows:
        label = ROLE_LABELS.get(str(row["role"]), str(row["role"]))
        mark = "（已压缩）" if row["compacted"] else ""
        print(f"  [{row['seq']}] {label} {format_time(str(row['created_at']))}{mark}")
        print(f"    {row['content']}")


def build_flow(memory: Memory, system_prompt: str = SYSTEM_PROMPT) -> Flow:
    """按 action 把节点连成一条带循环的链路。"""
    input_node = InputNode(memory)
    reply_node = ReplyNode(memory, system_prompt)
    history_node = HistoryNode(memory)
    sessions_node = SessionsNode(memory)
    exit_node = ExitNode()

    input_node - "reply" >> reply_node
    input_node - "history" >> history_node
    input_node - "sessions" >> sessions_node
    input_node - "exit" >> exit_node
    # 回复、看历史、看会话列表之后都回到输入节点，形成多轮对话。
    reply_node - DEFAULT_ACTION >> input_node
    history_node - DEFAULT_ACTION >> input_node
    sessions_node - DEFAULT_ACTION >> input_node
    return Flow(input_node)


def new_session_id() -> str:
    """给新会话生成一个带时间戳的 id。"""
    return f"chat-{datetime.now():%Y%m%d-%H%M%S}"


def pick_session() -> str:
    """启动时问要不要进旧会话，返回这次要用的会话 id。"""
    with Memory(LIST_ONLY_SESSION_ID) as probe:
        sessions = probe.list_sessions()

    if not sessions:
        session_id = new_session_id()
        print(f"还没有旧会话，新建会话 {session_id}。")
        return session_id

    print(f"现有 {len(sessions)} 个旧会话（id -> 标题）：")
    for session_id, title in sessions.items():
        print(f"  {session_id} -> {title or '（无标题）'}")

    answer = input("输入会话 id 进入旧会话，直接回车新建会话：").strip()
    if answer:
        return answer
    session_id = new_session_id()
    print(f"新建会话 {session_id}。")
    return session_id


def run_session(session_id: str) -> None:
    """进入一个会话：先回放最近的消息，再开始聊天。"""
    with Memory(session_id) as memory:
        before = len(memory.messages(include_compacted=True))
        recent = memory.messages(limit=RECENT_MESSAGES_ON_ENTER, include_compacted=True)
        if recent:
            print(f"进入会话 {session_id}，标题：{memory.title() or '（无标题）'}")
            print(f"上次的最后 {len(recent)} 条消息：")
            print_messages(recent)
        else:
            print(f"新会话 {session_id}。")
        print("直接输入问题开始聊天；history 看全部历史，sessions 看所有会话，quit 退出。")

        build_flow(memory).run()

        after = len(memory.messages(include_compacted=True))
        if after and (after > before or not memory.title()):
            try:
                title = memory.update_title()
            except Exception as exc:  # 标题生成失败不影响已经存好的记录
                title = None
                print(f"标题生成失败：{exc}")
            if title:
                print(f"会话标题已保存：{title}")
        print(f"现在历史共 {after} 条消息。")


def main() -> None:
    """命令行入口：给了会话 id 就直接进，否则先问要不要进旧会话。"""
    session_id = sys.argv[1] if len(sys.argv) > 1 else pick_session()
    run_session(session_id)


if __name__ == "__main__":
    main()
