"""对话记忆：消息存进 SQLite，按会话 id 隔离，上下文接近上限时自动压缩。

四张表：

- `sessions`：会话索引，存每个会话的标题和创建/更新时间。
- `messages`：每个会话的完整消息流水。压缩不删数据，只把老消息标记成 `compacted=1`。
- `summaries`：每个会话最新的一份历史摘要，压缩时由模型生成。
- `long_term_memory`：只有用户明确要求记住的内容才写进来。

压缩策略：上下文用到 `max_context_tokens * compress_threshold`（默认 128k 的 90%）时，
把较早的消息交给模型压成摘要，最近 `keep_recent` 条原样保留。再次压缩会把上一版摘要
一起交给模型，所以早期信息不会断线。

会话标题由 `update_title()` 调模型生成，`list_sessions()` 返回 `{会话 id: 标题}`，
用于"进入哪个旧会话"这类选择。

用法：

    memory = Memory("game-1")
    memory.add_user("请记住我习惯用中文")
    completion = chat_full(memory.build_context("你是狼人杀主持人"))
    memory.add_assistant(completion.choices[0].message.content or "", usage=completion.usage)
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionMessageParam

from .llm import chat

DEFAULT_DB_PATH = Path("memory") / "chat.db"

MAX_CONTEXT_TOKENS = 128_000
COMPRESS_THRESHOLD = 0.9
KEEP_RECENT_MESSAGES = 4
MAX_MEMORY_ENTRIES = 20

# 用户明确要求"记住"时的触发词，命中才写长期记忆。
REMEMBER_MARKERS = (
    "记住",
    "牢记",
    "记下来",
    "记一下",
    "别忘了",
    "永久记忆",
    "长期记忆",
    "remember",
    "keep in mind",
)

ROLE_LABELS = {
    "system": "系统",
    "user": "用户",
    "assistant": "助手",
    "tool": "工具",
}

SUMMARY_PROMPT = """把下面的对话压缩成一段摘要，供之后的对话继续使用。

要求：

1. 保留人物、立场、已经确定的事实和结论；
2. 保留尚未解决的问题和当前进度；
3. 保留用户的偏好和明确要求；
4. 按时间顺序写，直接输出摘要正文，不要标题，不要代码块。

{previous}对话内容：

{transcript}"""

MEMORY_MERGE_PROMPT = """把下面的长期记忆条目合并压缩：去掉重复和过时的内容，保留仍然有效的偏好、事实和要求。
每条一行，用「- 」开头，直接输出结果，不要额外说明。

{entries}"""

TITLE_PROMPT = """用不超过 12 个字概括下面这段对话的主题，作为会话标题。
只输出标题本身，不要引号，不要解释。

对话内容：

{transcript}"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    extra TEXT,
    compacted INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, seq);

CREATE TABLE IF NOT EXISTS summaries (
    session_id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS long_term_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, content)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数。中文约 1.5 字一个 token，这里按偏保守的取值算。"""
    return max(1, round(len(text) / 1.5))


def estimate_context_tokens(messages: Iterable[dict[str, Any]]) -> int:
    """估算一整段上下文的大小，每条消息额外算 4 个 token 的结构开销。"""
    return sum(estimate_tokens(str(message.get("content") or "")) + 4 for message in messages)


def is_remember_request(text: str) -> bool:
    """用户是否明确要求记住这条信息。"""
    lowered = text.lower()
    return any(marker in lowered for marker in REMEMBER_MARKERS)


class Memory:
    """一个会话的记忆。读写都带 session_id，多个会话共用一个库也不会串。"""

    def __init__(
        self,
        session_id: str,
        *,
        db_path: Path | str = DEFAULT_DB_PATH,
        max_context_tokens: int = MAX_CONTEXT_TOKENS,
        compress_threshold: float = COMPRESS_THRESHOLD,
        keep_recent: int = KEEP_RECENT_MESSAGES,
        max_memory_entries: int = MAX_MEMORY_ENTRIES,
    ) -> None:
        if not session_id:
            raise ValueError("session_id 不能为空")
        if keep_recent < 0:
            raise ValueError("keep_recent 不能为负数")
        self.session_id = session_id
        self.db_path = Path(db_path)
        self.max_context_tokens = max_context_tokens
        self.compress_threshold = compress_threshold
        self.keep_recent = keep_recent
        self.max_memory_entries = max_memory_entries

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._backfill_sessions()

    # ------------------------------------------------------------------ 写入

    def add_user(self, text: str) -> bool:
        """写入一条用户消息。

        用户明确要求记住时，同时写进长期记忆，返回 True。
        """
        self.add_message("user", text)
        if is_remember_request(text):
            self.remember(text)
            return True
        return False

    def add_assistant(
        self,
        text: str,
        *,
        usage: CompletionUsage | None = None,
        extra: dict[str, Any] | None = None,
    ) -> bool:
        """写入一条助手回复，并在上下文接近上限时压缩。返回是否触发了压缩。"""
        total_tokens = usage.total_tokens if usage is not None else None
        self.add_message("assistant", text, extra=extra, total_tokens=total_tokens)
        return self.maybe_compress(total_tokens)

    def add_message(
        self,
        role: str,
        content: str,
        *,
        extra: dict[str, Any] | None = None,
        total_tokens: int | None = None,
    ) -> int:
        """写入任意角色的消息，返回这条消息的 id。"""
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO messages"
                " (session_id, seq, role, content, extra, total_tokens, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    self.session_id,
                    self._next_seq(),
                    role,
                    content,
                    json.dumps(extra, ensure_ascii=False) if extra else None,
                    total_tokens,
                    _now(),
                ),
            )
        self._touch_session()
        return int(cursor.lastrowid or 0)

    def remember(self, content: str) -> bool:
        """写入一条长期记忆，重复内容会被忽略。返回是否真的写入了。"""
        text = content.strip()
        if not text:
            return False
        with self._conn:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO long_term_memory (session_id, content, created_at)"
                " VALUES (?, ?, ?)",
                (self.session_id, text, _now()),
            )
        self._touch_session()
        return cursor.rowcount > 0

    def set_title(self, title: str) -> None:
        """写入当前会话的标题。"""
        self._touch_session()
        with self._conn:
            self._conn.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE session_id = ?",
                (title.strip(), _now(), self.session_id),
            )

    def update_title(self, limit: int = 20) -> str | None:
        """让模型给当前会话起一个短标题并存下来，会话里还没有消息时返回 None。"""
        rows = self._visible_rows(include_compacted=True)
        if not rows:
            return None
        if len(rows) > limit:
            half = limit // 2
            rows = [*rows[:half], *rows[-half:]]

        transcript = "\n".join(
            f"{ROLE_LABELS.get(str(row['role']), str(row['role']))}: {row['content']}"
            for row in rows
        )
        title = chat(TITLE_PROMPT.format(transcript=transcript)).strip().strip("「」\"'“”《》")
        title = " ".join(title.split())
        if not title:
            return None
        self.set_title(title[:30])
        return self.title()

    # ------------------------------------------------------------------ 读取

    def messages(
        self,
        *,
        include_compacted: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """按顺序返回消息。

        默认只返回还参与上下文的消息；`limit` 表示只取最后 N 条（`include_compacted=True`
        时就是完整的最后 N 条历史）。
        """
        rows = self._visible_rows(include_compacted)
        if limit is not None:
            rows = rows[-limit:] if limit > 0 else []
        return [self._row_to_message(row) for row in rows]

    def timeline(self) -> list[dict[str, Any]]:
        """给查看历史用的完整时间线：序号、角色、内容、时间和压缩标记。"""
        return [
            {
                "seq": int(row["seq"]),
                "role": str(row["role"]),
                "content": str(row["content"]),
                "compacted": bool(row["compacted"]),
                "created_at": str(row["created_at"]),
            }
            for row in self._visible_rows(include_compacted=True)
        ]

    def summary(self) -> str | None:
        """返回当前会话的历史摘要。"""
        row = self._conn.execute(
            "SELECT content FROM summaries WHERE session_id = ?",
            (self.session_id,),
        ).fetchone()
        return str(row["content"]) if row else None

    def long_term_memories(self) -> list[str]:
        """按写入顺序返回长期记忆。"""
        rows = self._conn.execute(
            "SELECT content FROM long_term_memory WHERE session_id = ? ORDER BY id",
            (self.session_id,),
        ).fetchall()
        return [str(row["content"]) for row in rows]

    def title(self) -> str:
        """返回当前会话的标题，没有就返回空字符串。"""
        row = self._conn.execute(
            "SELECT title FROM sessions WHERE session_id = ?",
            (self.session_id,),
        ).fetchone()
        return str(row["title"]) if row else ""

    def list_sessions(self) -> dict[str, str]:
        """返回库里所有会话的 `{会话 id: 标题}`，最近更新过的排在前面。

        这是跨会话查询，不受当前 `session_id` 限制；没有消息的会话不会列出来。
        """
        rows = self._conn.execute(
            "SELECT s.session_id AS session_id, s.title AS title FROM sessions s"
            " WHERE EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.session_id)"
            " ORDER BY s.updated_at DESC, s.session_id"
        ).fetchall()
        return {str(row["session_id"]): str(row["title"]) for row in rows}

    def build_context(self, system_prompt: str = "") -> list[ChatCompletionMessageParam]:
        """组装发给模型的消息：system（含长期记忆）+ 历史摘要 + 最近消息。"""
        context: list[ChatCompletionMessageParam] = []

        system = system_prompt.strip()
        memories = self.long_term_memories()
        if memories:
            block = "长期记忆：\n" + "\n".join(f"- {item}" for item in memories)
            system = f"{system}\n\n{block}" if system else block
        if system:
            context.append({"role": "system", "content": system})

        summary = self.summary()
        if summary:
            context.append({"role": "system", "content": f"更早对话的摘要：\n{summary}"})

        context.extend(self.messages())
        return context

    def context_tokens(self) -> int:
        """当前上下文大小：优先用上一轮接口返回的 total_tokens，没有就本地估算。"""
        row = self._conn.execute(
            "SELECT total_tokens FROM messages"
            " WHERE session_id = ? AND total_tokens IS NOT NULL"
            " ORDER BY seq DESC, id DESC LIMIT 1",
            (self.session_id,),
        ).fetchone()
        if row is not None:
            return int(row["total_tokens"])
        return estimate_context_tokens(self.build_context())

    def should_compress(self, total_tokens: int | None = None) -> bool:
        """上下文是否已经用到阈值（默认 90%）。"""
        tokens = self.context_tokens() if total_tokens is None else total_tokens
        return tokens >= self.max_context_tokens * self.compress_threshold

    # ------------------------------------------------------------------ 压缩

    def maybe_compress(self, total_tokens: int | None = None) -> bool:
        """到阈值就压缩，返回是否真的压缩了。"""
        if not self.should_compress(total_tokens):
            return False
        return self.compress() is not None

    def compress(self) -> str | None:
        """把较早的消息压成摘要，保留最近 `keep_recent` 条。没得压时返回 None。"""
        rows = self._visible_rows()
        if len(rows) <= self.keep_recent:
            return None

        split = len(rows) - self.keep_recent
        # 不要把 assistant 的 tool_calls 和它后面的 tool 结果切开。
        while split > 0 and rows[split]["role"] == "tool":
            split -= 1
        old_rows = rows[:split]
        if not old_rows:
            return None

        summary = self._summarize(old_rows)
        if not summary:
            return None

        self._save_summary(summary)
        self._mark_compacted(old_rows)
        self._compress_long_term_memory()
        return summary

    def _summarize(self, rows: Sequence[sqlite3.Row]) -> str:
        transcript = "\n".join(
            f"{ROLE_LABELS.get(str(row['role']), str(row['role']))}: {row['content']}"
            for row in rows
        )
        previous = self.summary()
        previous_block = f"已有的历史摘要：\n{previous}\n\n" if previous else ""
        prompt = SUMMARY_PROMPT.format(previous=previous_block, transcript=transcript)
        return chat(prompt).strip()

    def _save_summary(self, summary: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO summaries (session_id, content, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(session_id) DO UPDATE SET content = excluded.content,"
                " updated_at = excluded.updated_at",
                (self.session_id, summary, _now()),
            )

    def _mark_compacted(self, rows: Sequence[sqlite3.Row]) -> None:
        ids = [int(row["id"]) for row in rows]
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        with self._conn:
            self._conn.execute(
                f"UPDATE messages SET compacted = 1 WHERE id IN ({placeholders})",
                ids,
            )

    def _compress_long_term_memory(self) -> bool:
        """长期记忆条目过多时合并一次，避免每次都塞满上下文。"""
        memories = self.long_term_memories()
        if len(memories) <= self.max_memory_entries:
            return False

        entries = "\n".join(f"- {item}" for item in memories)
        merged = chat(MEMORY_MERGE_PROMPT.format(entries=entries)).strip()
        items = [line.lstrip("-* 　").strip() for line in merged.splitlines() if line.strip()]
        if not items:
            return False

        with self._conn:
            self._conn.execute(
                "DELETE FROM long_term_memory WHERE session_id = ?",
                (self.session_id,),
            )
            self._conn.executemany(
                "INSERT OR IGNORE INTO long_term_memory (session_id, content, created_at)"
                " VALUES (?, ?, ?)",
                [(self.session_id, item, _now()) for item in items],
            )
        return True

    # ------------------------------------------------------------------ 维护

    def clear(self) -> None:
        """清空当前会话的消息、摘要、长期记忆和标题，其他会话不受影响。"""
        with self._conn:
            self._conn.execute("DELETE FROM messages WHERE session_id = ?", (self.session_id,))
            self._conn.execute("DELETE FROM summaries WHERE session_id = ?", (self.session_id,))
            self._conn.execute("DELETE FROM long_term_memory WHERE session_id = ?", (self.session_id,))
            self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (self.session_id,))

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Memory":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"Memory(session_id={self.session_id!r}, db_path={str(self.db_path)!r})"

    # ------------------------------------------------------------------ 内部

    def _touch_session(self) -> None:
        """会话有新内容时更新索引行，标题保持不变。"""
        now = _now()
        with self._conn:
            self._conn.execute(
                "INSERT INTO sessions (session_id, title, created_at, updated_at)"
                " VALUES (?, '', ?, ?)"
                " ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at",
                (self.session_id, now, now),
            )

    def _backfill_sessions(self) -> None:
        """老库里没有 sessions 行时，按已有消息补一份，保证旧会话也能列出来。"""
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO sessions (session_id, title, created_at, updated_at)"
                " SELECT session_id, '', MIN(created_at), MAX(created_at)"
                " FROM messages GROUP BY session_id"
            )

    def _next_seq(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM messages WHERE session_id = ?",
            (self.session_id,),
        ).fetchone()
        return int(row["next"])

    def _visible_rows(self, include_compacted: bool = False) -> list[sqlite3.Row]:
        sql = "SELECT * FROM messages WHERE session_id = ?"
        if not include_compacted:
            sql += " AND compacted = 0"
        sql += " ORDER BY seq, id"
        return list(self._conn.execute(sql, (self.session_id,)).fetchall())

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> dict[str, Any]:
        message: dict[str, Any] = {"role": row["role"], "content": row["content"]}
        if row["extra"]:
            message.update(json.loads(row["extra"]))
        return message
