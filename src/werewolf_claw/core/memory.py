"""对话记忆：消息存进 SQLite，按会话 id 隔离，上下文接近上限时自动压缩。

四张表：

- `sessions`：会话索引，存每个会话的标题和创建/更新时间。
- `messages`：每个会话的完整消息流水。压缩不删数据，只把老消息标记成 `compacted=1`。
- `summaries`：每个会话最新的一份历史摘要，压缩时由模型生成。
- `long_term_memory`：只有用户明确要求记住的内容才写进来。

压缩策略：上下文用到 `max_context_tokens * compress_threshold`（默认 128k 的 90%）时，
把较早的消息交给模型压成摘要，最近 `keep_recent` 条原样保留。再次压缩会把上一版摘要
一起交给模型，所以早期信息不会断线。

会话标题由 `auto_title()` 按前几条消息总结，用户用 `rename()` 改过（`title_locked`）之后
就不再自动覆盖；`list_sessions()` 返回 `{会话 id: 标题}`，没有标题的用第一条用户消息兜底。

`export_session()` / `import_session()` 用来把整个会话导出成 JSON 再在别处还原。

用法：

    memory = Memory("game-1")
    memory.add_user("请记住我习惯用中文")
    completion = chat_full(memory.build_context("你是狼人杀主持人"))
    memory.add_assistant(completion.choices[0].message.content or "", usage=completion.usage)
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionMessageParam

from .llm import chat

DEFAULT_DB_PATH = Path("memory") / "chat.db"

# 库路径可以用环境变量覆盖，所有入口都走 default_db_path()，保证命令行和 Web 用同一个库。
DB_PATH_ENV = "WEREWOLF_DB"

# 会话 id 允许 1-64 个字符，不能带空白和 / \ ? # %（这些会破坏 URL 或路径）
SESSION_ID_PATTERN = re.compile(r"^[^\s/\\?#%]{1,64}$")
RESERVED_SESSION_IDS = {".", ".."}

MAX_CONTEXT_TOKENS = 128_000
COMPRESS_THRESHOLD = 0.9
KEEP_RECENT_MESSAGES = 4
MAX_MEMORY_ENTRIES = 20

# 导出文件的标识和版本，导入时用它确认文件类型。
EXPORT_FORMAT = "werewolf-claw-session"
EXPORT_VERSION = 1

# 库结构版本，改表结构时 +1；打开库时比对，只在落后时才跑建表和补列
SCHEMA_VERSION = 2

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

# extra 里这些键属于 OpenAI 的消息参数，可以原样带进上下文；其他键（重新生成次数等）只给页面看。
MESSAGE_PARAM_KEYS = ("tool_calls", "tool_call_id", "name")

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

TITLE_PROMPT = """用不超过 12 个字概括下面这些用户发言的主题，作为会话标题。
只能根据用户说的话来概括，不要参考助手的回答。
只输出标题本身，不要引号，不要解释。

用户发言：

{transcript}"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    title_locked INTEGER NOT NULL DEFAULT 0,
    pinned INTEGER NOT NULL DEFAULT 0,
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


def new_session_id() -> str:
    """给新会话生成一个带时间戳的 id，前端不展示，只用来区分会话。

    末尾加一小段随机串，避免同一秒内新建两个会话撞 id。
    """
    return f"chat-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:4]}"


def default_db_path() -> Path:
    """默认库路径：优先环境变量 `WEREWOLF_DB`，其次 `memory/chat.db`（相对当前工作目录）。"""
    configured = os.environ.get(DB_PATH_ENV)
    return Path(configured) if configured else DEFAULT_DB_PATH


def is_valid_session_id(value: str) -> bool:
    """会话 id 是否合法：1-64 个非空白字符，不含 `/ \\ ? # %`，也不是 `.` / `..`。"""
    return value not in RESERVED_SESSION_IDS and bool(SESSION_ID_PATTERN.match(value))


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
        db_path: Path | str | None = None,
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
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        self.max_context_tokens = max_context_tokens
        self.compress_threshold = compress_threshold
        self.keep_recent = keep_recent
        self.max_memory_entries = max_memory_entries

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._tune()
        self._ensure_schema()

    def _tune(self) -> None:
        """连接级设置。

        - `journal_mode=WAL`：写入先进 WAL 文件，读写不再互相阻塞（库级设置，设一次就记住）；
        - `synchronous=FULL`：每次提交都 fsync WAL，断电也不会丢已提交的数据；
        - `busy_timeout`：并发写时等锁最多 5 秒，而不是立刻报 database is locked。
        """
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            # 放在网络盘等不支持 WAL 的位置时退回默认日志模式，功能不受影响
            pass
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA busy_timeout=5000")

    def _ensure_schema(self) -> None:
        """只在库结构落后时建表和补列，避免每个请求都重跑一遍 DDL。"""
        current = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if current < SCHEMA_VERSION:
            self._conn.executescript(SCHEMA)
            self._migrate()
            with self._conn:
                self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._backfill_sessions()

    # ------------------------------------------------------------------ 写入

    def add_user(self, text: str, quote: Mapping[str, Any] | None = None) -> bool:
        """写入一条用户消息。

        `quote` 是引用信息（会话 id、序号、摘要），单独存在 `extra` 里，
        正文保持用户自己说的话；拼上下文时再把引用摘要加回去。
        用户明确要求记住时，同时写进长期记忆，返回 True。
        """
        self.add_message("user", text, extra={"quote": dict(quote)} if quote else None)
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
            # 和消息写在同一个事务里，一次提交就够（每条 COMMIT 都要 fsync）
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

    def rename(self, title: str) -> str:
        """手工重命名会话。改过之后不再自动生成标题。"""
        text = " ".join(title.split())
        if not text:
            raise ValueError("标题不能为空")
        self._write_title(text[:50], locked=True)
        return self.title()

    def auto_title(self, limit: int = 6) -> str | None:
        """按最前面的几条**用户消息**总结标题。

        用户重命名过（`title_locked`）就直接返回现有标题，不再调用模型；
        用户还没有发过消息时返回 None。
        """
        if self.title_locked():
            return self.title()

        rows = self._conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? AND role = 'user'"
            " ORDER BY seq, id LIMIT ?",
            (self.session_id, limit),
        ).fetchall()
        if not rows:
            return None

        transcript = "\n".join(
            f"用户：{row['content']}"
            for row in rows
        )
        title = chat(TITLE_PROMPT.format(transcript=transcript)).strip().strip("「」\"'“”《》")
        title = " ".join(title.split())
        if not title:
            return None
        self._write_title(title[:30], locked=False)
        return self.title()

    def _write_title(self, title: str, *, locked: bool) -> None:
        """写标题；`locked=True` 表示这是用户改的，之后不再自动覆盖。"""
        with self._conn:
            self._touch_session()
            self._conn.execute(
                "UPDATE sessions SET title = ?, title_locked = ?, updated_at = ?"
                " WHERE session_id = ?",
                (title.strip(), 1 if locked else 0, _now(), self.session_id),
            )

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
        return [self._row_to_timeline(row) for row in self._visible_rows(include_compacted=True)]

    def message_page(
        self,
        limit: int = 30,
        before_seq: int | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """从最新往前按页取消息，返回 (这一页按时间正序的消息, 是否还有更早的)。

        `before_seq` 省略时取最新的那一页，给了就取序号更小的那一页。
        """
        if limit <= 0:
            return [], False

        sql = "SELECT * FROM messages WHERE session_id = ?"
        params: list[Any] = [self.session_id]
        if before_seq is not None:
            sql += " AND seq < ?"
            params.append(before_seq)
        sql += " ORDER BY seq DESC LIMIT ?"
        params.append(limit + 1)

        rows = list(self._conn.execute(sql, params).fetchall())
        has_more = len(rows) > limit
        rows = rows[:limit]
        rows.reverse()
        return [self._row_to_timeline(row) for row in rows], has_more

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

    def title_locked(self) -> bool:
        """标题是否是用户手工改的（是的话不再自动生成）。"""
        row = self._conn.execute(
            "SELECT title_locked FROM sessions WHERE session_id = ?",
            (self.session_id,),
        ).fetchone()
        return bool(row["title_locked"]) if row else False

    def display_title(self) -> str:
        """页面和列表里显示的标题：生成过就用它，否则用第一条用户消息兜底。"""
        title = self.title()
        if title:
            return title
        row = self._conn.execute(
            "SELECT content FROM messages WHERE session_id = ? AND role = 'user'"
            " ORDER BY seq LIMIT 1",
            (self.session_id,),
        ).fetchone()
        return self._display_title("", row["content"] if row else "")

    def message_count(self, *, include_compacted: bool = True) -> int:
        """消息条数，默认包含已经压缩的老消息。"""
        sql = "SELECT COUNT(*) AS total FROM messages WHERE session_id = ?"
        if not include_compacted:
            sql += " AND compacted = 0"
        row = self._conn.execute(sql, (self.session_id,)).fetchone()
        return int(row["total"])

    def overview(self) -> dict[str, Any]:
        """会话概览：标题、摘要、长期记忆和消息条数，供上层拼响应或展示。"""
        total = self.message_count()
        active = self.message_count(include_compacted=False)
        return {
            "session_id": self.session_id,
            "title": self.display_title(),
            "title_locked": self.title_locked(),
            "summary": self.summary(),
            "memories": self.long_term_memories(),
            "message_count": total,
            "compacted_count": total - active,
        }

    def outline(self, rounds: int = 500, excerpt: int = 60) -> list[dict[str, Any]]:
        """每轮问答的摘要（用户那句 + 助手那句），给右侧导航用，不带全文。"""
        rows = self._conn.execute(
            "SELECT seq, role, content FROM messages WHERE session_id = ? ORDER BY seq LIMIT ?",
            (self.session_id, rounds * 2),
        ).fetchall()

        if excerpt <= 0:
            excerpt = 10_000
        entries: list[dict[str, Any]] = []
        for row in rows:
            role = str(row["role"])
            text = " ".join(str(row["content"]).split())
            if len(text) > excerpt:
                text = f"{text[:excerpt]}…"
            if role == "user":
                entries.append({"seq": int(row["seq"]), "user": text, "assistant": ""})
            elif role == "assistant" and entries:
                entries[-1]["assistant"] = text
        return entries

    def last_exchange(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """最后一条用户消息，以及它后面的助手回复（还没回复时为 None）。

        走 `(session_id, seq)` 索引各取一条，不再把整个会话读进内存。
        """
        user = self._conn.execute(
            "SELECT * FROM messages WHERE session_id = ? AND role = 'user'"
            " ORDER BY seq DESC, id DESC LIMIT 1",
            (self.session_id,),
        ).fetchone()
        if user is None:
            return None, None

        reply = self._conn.execute(
            "SELECT * FROM messages WHERE session_id = ? AND seq > ?"
            " ORDER BY seq, id LIMIT 1",
            (self.session_id, int(user["seq"])),
        ).fetchone()
        if reply is not None and str(reply["role"]) != "assistant":
            reply = None
        return self._row_to_exchange(user), (self._row_to_exchange(reply) if reply else None)

    def message_extra(self, seq: int) -> dict[str, Any]:
        """某条消息的附加数据，重新生成的次数和历史回答都放这里。"""
        row = self._conn.execute(
            "SELECT extra FROM messages WHERE session_id = ? AND seq = ?",
            (self.session_id, seq),
        ).fetchone()
        if row is None or not row["extra"]:
            return {}
        return dict(json.loads(row["extra"]))

    def message_excerpt(self, seq: int, limit: int = 120) -> str | None:
        """取某条消息的引用摘要；这条消息不在当前会话里就返回 None。"""
        row = self._conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? AND seq = ?",
            (self.session_id, seq),
        ).fetchone()
        if row is None:
            return None
        label = ROLE_LABELS.get(str(row["role"]), str(row["role"]))
        text = " ".join(str(row["content"]).split())
        return f"{label}：{text[:limit]}{'…' if len(text) > limit else ''}"

    def update_message(
        self,
        seq: int,
        content: str,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        """覆盖某条消息的内容和附加数据。"""
        with self._conn:
            self._conn.execute(
                "UPDATE messages SET content = ?, extra = ? WHERE session_id = ? AND seq = ?",
                (
                    content,
                    json.dumps(extra, ensure_ascii=False) if extra else None,
                    self.session_id,
                    seq,
                ),
            )

    def truncate_last_exchange(self) -> int:
        """删掉最后一条用户消息和它之后的消息，返回删掉的条数（编辑消息时用）。"""
        row = self._conn.execute(
            "SELECT seq FROM messages WHERE session_id = ? AND role = 'user'"
            " ORDER BY seq DESC, id DESC LIMIT 1",
            (self.session_id,),
        ).fetchone()
        if row is None:
            return 0
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM messages WHERE session_id = ? AND seq >= ?",
                (self.session_id, int(row["seq"])),
            )
        return int(cursor.rowcount or 0)

    def list_sessions(self) -> dict[str, str]:
        """返回库里所有会话的 `{会话 id: 标题}`，置顶的排前面，然后按最近更新排。

        这是跨会话查询，不受当前 `session_id` 限制；没有消息的会话不会列出来。
        还没生成标题的会话用第一条用户消息兜底，保证列表里每一项都有可读的名字。
        """
        return {entry["id"]: entry["title"] for entry in self.list_session_entries()}

    def list_session_entries(self) -> list[dict[str, Any]]:
        """会话列表明细：id、标题、是否置顶。置顶的排前面。"""
        rows = self._conn.execute(
            "SELECT s.session_id AS session_id, s.title AS title, s.pinned AS pinned,"
            " s.updated_at AS updated_at,"
            " (SELECT m.content FROM messages m"
            "  WHERE m.session_id = s.session_id AND m.role = 'user'"
            "  ORDER BY m.seq LIMIT 1) AS first_user"
            " FROM sessions s"
            " WHERE EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.session_id)"
            " ORDER BY s.pinned DESC, s.updated_at DESC, s.session_id"
        ).fetchall()
        return [
            {
                "id": str(row["session_id"]),
                "title": self._display_title(str(row["title"]), row["first_user"]),
                "pinned": bool(row["pinned"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def pin_sessions(self, session_ids: Iterable[str], pinned: bool = True) -> int:
        """批量置顶 / 取消置顶，返回改动的会话数。"""
        ids = [session_id for session_id in session_ids if session_id]
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        with self._conn:
            cursor = self._conn.execute(
                f"UPDATE sessions SET pinned = ? WHERE session_id IN ({placeholders})",
                [1 if pinned else 0, *ids],
            )
        return int(cursor.rowcount or 0)

    def delete_sessions(self, session_ids: Iterable[str]) -> int:
        """批量删除会话，返回删掉的会话数。"""
        ids = [session_id for session_id in session_ids if session_id]
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        with self._conn:
            self._conn.execute(f"DELETE FROM messages WHERE session_id IN ({placeholders})", ids)
            self._conn.execute(f"DELETE FROM summaries WHERE session_id IN ({placeholders})", ids)
            self._conn.execute(
                f"DELETE FROM long_term_memory WHERE session_id IN ({placeholders})", ids
            )
            cursor = self._conn.execute(
                f"DELETE FROM sessions WHERE session_id IN ({placeholders})", ids
            )
        return int(cursor.rowcount or 0)

    @staticmethod
    def _display_title(title: str, first_user: Any) -> str:
        """列表里显示的标题：优先用生成的标题，没有就用第一条用户消息。"""
        if title:
            return title
        preview = " ".join(str(first_user or "").split())
        if not preview:
            return "空会话"
        return preview[:20] + ("…" if len(preview) > 20 else "")

    def build_context(
        self,
        system_prompt: str = "",
        *,
        without_last_reply: bool = False,
    ) -> list[ChatCompletionMessageParam]:
        """组装发给模型的消息：system（含长期记忆）+ 历史摘要 + 最近消息。

        `without_last_reply=True` 会把最后一条助手回复去掉，重新生成回复时用。
        """
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
        if without_last_reply and context and context[-1].get("role") == "assistant":
            context.pop()
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

    def export_session(self) -> dict[str, Any]:
        """导出当前会话的全部数据，用于备份或在别的机器上还原。"""
        return {
            "format": EXPORT_FORMAT,
            "version": EXPORT_VERSION,
            "exported_at": _now(),
            "session_id": self.session_id,
            "title": self.title(),
            "title_locked": self.title_locked(),
            "summary": self.summary(),
            "memories": self.long_term_memories(),
            "messages": self.timeline(),
        }

    @classmethod
    def import_session(
        cls,
        data: Mapping[str, Any],
        *,
        db_path: Path | str = DEFAULT_DB_PATH,
    ) -> str:
        """把导出文件写进库，返回落地的会话 id。

        原 id 没被占用就沿用，这样才算完全还原；被占用了就换一个新 id，不影响已有会话。
        """
        if not isinstance(data, Mapping) or data.get("format") != EXPORT_FORMAT:
            raise ValueError("不是 Werewolf-Claw 的会话导出文件")
        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("导出文件里没有消息")

        session_id = str(data.get("session_id") or "").strip() or new_session_id()
        memory = cls(session_id, db_path=db_path)
        if memory.messages(include_compacted=True):
            memory.close()
            session_id = f"{session_id}-{uuid4().hex[:4]}"
            memory = cls(session_id, db_path=db_path)
        try:
            memory._restore(data, messages)
        finally:
            memory.close()
        return session_id

    def _restore(self, data: Mapping[str, Any], messages: Sequence[Any]) -> None:
        """按导出内容重建当前会话：先清空，再连序号和时间一起写回去。"""
        with self._conn:
            self._conn.execute("DELETE FROM messages WHERE session_id = ?", (self.session_id,))
            self._conn.execute("DELETE FROM summaries WHERE session_id = ?", (self.session_id,))
            self._conn.execute("DELETE FROM long_term_memory WHERE session_id = ?", (self.session_id,))

            for index, message in enumerate(messages, start=1):
                if not isinstance(message, Mapping) or "content" not in message:
                    raise ValueError("导出文件里的消息格式不对")
                self._conn.execute(
                    "INSERT INTO messages"
                    " (session_id, seq, role, content, compacted, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        self.session_id,
                        int(message.get("seq") or index),
                        str(message.get("role") or "user"),
                        str(message.get("content") or ""),
                        1 if message.get("compacted") else 0,
                        str(message.get("created_at") or _now()),
                    ),
                )

            summary = data.get("summary")
            if summary:
                self._conn.execute(
                    "INSERT INTO summaries (session_id, content, updated_at) VALUES (?, ?, ?)",
                    (self.session_id, str(summary), _now()),
                )
            for item in data.get("memories") or []:
                self._conn.execute(
                    "INSERT OR IGNORE INTO long_term_memory (session_id, content, created_at)"
                    " VALUES (?, ?, ?)",
                    (self.session_id, str(item), _now()),
                )

        with self._conn:
            self._touch_session()
        self._write_title(str(data.get("title") or ""), locked=bool(data.get("title_locked")))

    def clear(self) -> None:
        """删除当前会话的消息、摘要、长期记忆和标题，其他会话不受影响。"""
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

    def _migrate(self) -> None:
        """老库补列：`title_locked`、`pinned` 都是后加的。"""
        columns = {str(row["name"]) for row in self._conn.execute("PRAGMA table_info(sessions)")}
        with self._conn:
            if "title_locked" not in columns:
                self._conn.execute(
                    "ALTER TABLE sessions ADD COLUMN title_locked INTEGER NOT NULL DEFAULT 0"
                )
            if "pinned" not in columns:
                self._conn.execute(
                    "ALTER TABLE sessions ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
                )

    def _touch_session(self) -> None:
        """更新会话索引行的更新时间，标题保持不变。

        只负责执行 SQL，事务由调用方开：这样写消息 / 写记忆 / 写标题都能和它共用一次提交。
        """
        now = _now()
        self._conn.execute(
            "INSERT INTO sessions (session_id, title, created_at, updated_at)"
            " VALUES (?, '', ?, ?)"
            " ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at",
            (self.session_id, now, now),
        )

    def _backfill_sessions(self) -> None:
        """老库里没有 sessions 行时补一份；先做一次存在性检查，避免每次打开都全表扫。"""
        missing = self._conn.execute(
            "SELECT 1 FROM messages m"
            " LEFT JOIN sessions s ON s.session_id = m.session_id"
            " WHERE s.session_id IS NULL LIMIT 1"
        ).fetchone()
        if missing is None:
            return
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
        """转成发给模型的消息：引用摘要拼回正文，只带上消息参数，别的 extra 不发给模型。"""
        extra = json.loads(row["extra"]) if row["extra"] else {}
        message: dict[str, Any] = {"role": row["role"], "content": row["content"]}
        quote = extra.get("quote") or {}
        if quote.get("excerpt"):
            message["content"] = f"> 引用 {quote['excerpt']}\n\n{message['content']}"
        for key in MESSAGE_PARAM_KEYS:
            if key in extra:
                message[key] = extra[key]
        return message

    @staticmethod
    def _row_to_timeline(row: sqlite3.Row) -> dict[str, Any]:
        extra = json.loads(row["extra"]) if row["extra"] else {}
        return {
            "seq": int(row["seq"]),
            "role": str(row["role"]),
            "content": str(row["content"]),
            "compacted": bool(row["compacted"]),
            "created_at": str(row["created_at"]),
            "regenerate_count": int(extra.get("regenerate_count") or 0),
            "quote": extra.get("quote") or None,
        }

    @staticmethod
    def _row_to_exchange(row: sqlite3.Row) -> dict[str, Any]:
        """给编辑/重新生成用的单条消息，带上附加数据。"""
        return {
            "seq": int(row["seq"]),
            "role": str(row["role"]),
            "content": str(row["content"]),
            "extra": dict(json.loads(row["extra"])) if row["extra"] else {},
        }
