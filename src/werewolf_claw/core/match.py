"""对局存储：大屏、私人记忆和对局档案都落在 `memory/match.db`。

三张表：

- `match`：一局的档案（板子、状态、天数、昼夜、座位表、Agent 统计），对局栏和快照都用它；
- `pub`：大屏消息，按对局 id 存/取；
- `priv`：私人消息，一条消息给几个座位就写几行，按对局 id + 座位 id 存/取，
  这样每个座位读到的永远只是自己能看的东西，隔离在存储层就做完了。

删除一局就删这三张表里对应的行；历史对局（进程重启后）也能靠 `match` + `pub`/`priv` 还原快照。
"""

from __future__ import annotations

import json
import os
import threading
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_MATCH_DB = Path("memory") / "match.db"
MATCH_DB_ENV = "WEREWOLF_MATCH_DB"


def default_match_db() -> Path:
    """对局库路径：`WEREWOLF_MATCH_DB` 优先，默认 memory/match.db。"""
    return Path(os.environ.get(MATCH_DB_ENV) or DEFAULT_MATCH_DB)


class MatchStore:
    """对局库。所有方法都自己开连接，线程安全交给 SQLite。"""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else default_match_db()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # 一条连接用完整个进程：原来每条消息都重连一次，太费
        self._conn = sqlite3.connect(self.db_path, timeout=5, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    # ------------------------------------------------------------------ 建表

    @contextmanager
    def _connect(self):
        """复用同一条连接，并串行化访问（SQLite 连接不是线程安全的）。"""
        with self._lock:
            with self._conn as conn:
                yield conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS match (
                    id TEXT PRIMARY KEY,
                    board TEXT NOT NULL,
                    board_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'ready',
                    winner TEXT NOT NULL DEFAULT '',
                    day INTEGER NOT NULL DEFAULT 0,
                    phase TEXT NOT NULL DEFAULT 'night',
                    stopped INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL DEFAULT 0,
                    started REAL NOT NULL DEFAULT 0,
                    finished REAL NOT NULL DEFAULT 0,
                    elapsed REAL NOT NULL DEFAULT 0,
                    options TEXT NOT NULL DEFAULT '{}',
                    seats TEXT NOT NULL DEFAULT '[]',
                    agents TEXT NOT NULL DEFAULT '[]',
                    updated REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS pub (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    day INTEGER NOT NULL DEFAULT 1,
                    kind TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL DEFAULT '',
                    facts TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS pub_match ON pub(match_id, seq);
                CREATE TABLE IF NOT EXISTS priv (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id TEXT NOT NULL,
                    seat INTEGER NOT NULL,
                    seq INTEGER NOT NULL,
                    day INTEGER NOT NULL DEFAULT 0,
                    kind TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL DEFAULT '',
                    facts TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS priv_match_seat ON priv(match_id, seat, seq);
                """
            )
            # 上次进程没跑完就退出的对局，状态改成 interrupted，别让网页以为它还在跑
            conn.execute(
                "UPDATE match SET status = 'interrupted' WHERE status IN ('running', 'ready')"
            )

    # ------------------------------------------------------------------ 对局档案

    def save_match(self, record: Mapping[str, Any]) -> None:
        """写入 / 更新一局的档案（对局栏、快照都读它）。"""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO match (id, board, board_name, status, winner, day, phase, stopped,
                                   created, started, finished, elapsed, options, seats, agents, updated)
                VALUES (:id, :board, :board_name, :status, :winner, :day, :phase, :stopped,
                        :created, :started, :finished, :elapsed, :options, :seats, :agents, :updated)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status, winner=excluded.winner, day=excluded.day,
                    phase=excluded.phase, stopped=excluded.stopped, finished=excluded.finished,
                    elapsed=excluded.elapsed, seats=excluded.seats, agents=excluded.agents,
                    updated=excluded.updated
                """,
                {
                    "id": record["id"],
                    "board": record.get("board", ""),
                    "board_name": record.get("board_name", ""),
                    "status": record.get("status", "ready"),
                    "winner": record.get("winner", ""),
                    "day": int(record.get("day") or 0),
                    "phase": record.get("phase", "night"),
                    "stopped": 1 if record.get("stopped") else 0,
                    "created": float(record.get("created") or 0),
                    "started": float(record.get("started") or 0),
                    "finished": float(record.get("finished") or 0),
                    "elapsed": float(record.get("elapsed") or 0),
                    "options": json.dumps(record.get("options") or {}, ensure_ascii=False),
                    "seats": json.dumps(record.get("seats") or [], ensure_ascii=False),
                    "agents": json.dumps(record.get("agents") or [], ensure_ascii=False),
                    "updated": float(record.get("updated") or 0),
                },
            )

    def list_matches(self) -> list[dict[str, Any]]:
        """对局栏：新的排前面。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM match ORDER BY created DESC"
            ).fetchall()
        return [self._match_row(row) for row in rows]

    def get_match(self, match_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM match WHERE id = ?", (match_id,)).fetchone()
        return self._match_row(row) if row else None

    def delete_match(self, match_id: str) -> bool:
        """删掉一局：档案、大屏、私人记忆一起删。"""
        with self._connect() as conn:
            exists = conn.execute("SELECT 1 FROM match WHERE id = ?", (match_id,)).fetchone()
            conn.execute("DELETE FROM pub WHERE match_id = ?", (match_id,))
            conn.execute("DELETE FROM priv WHERE match_id = ?", (match_id,))
            conn.execute("DELETE FROM match WHERE id = ?", (match_id,))
        return exists is not None

    def _match_row(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["stopped"] = bool(data["stopped"])
        for key in ("options", "seats", "agents"):
            try:
                data[key] = json.loads(data.get(key) or "null")
            except json.JSONDecodeError:
                data[key] = {} if key == "options" else []
        return data

    # ------------------------------------------------------------------ 大屏

    def append_public(
        self,
        match_id: str,
        *,
        seq: int,
        day: int,
        kind: str,
        text: str,
        facts: Mapping[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO pub (match_id, seq, day, kind, text, facts) VALUES (?, ?, ?, ?, ?, ?)",
                (match_id, seq, day, kind, text, json.dumps(dict(facts or {}), ensure_ascii=False)),
            )

    def read_public(self, match_id: str, *, after_seq: int = 0) -> list[dict[str, Any]]:
        """读大屏：只给对局 id 就能拿到全部公开信息。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pub WHERE match_id = ? AND seq > ? ORDER BY seq",
                (match_id, after_seq),
            ).fetchall()
        return [self._message_row(row) for row in rows]

    # ------------------------------------------------------------------ 私人记忆

    def append_private(
        self,
        match_id: str,
        seats: Sequence[int],
        *,
        seq: int,
        day: int,
        kind: str,
        text: str,
        facts: Mapping[str, Any] | None = None,
    ) -> None:
        """私聊入库：收件人一人一行，读的时候按座位取，天然隔离。"""
        payload = json.dumps(dict(facts or {}), ensure_ascii=False)
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO priv (match_id, seat, seq, day, kind, text, facts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(match_id, int(seat), seq, day, kind, text, payload) for seat in seats],
            )

    def read_private(self, match_id: str, seat: int, *, after_seq: int = 0) -> list[dict[str, Any]]:
        """读某个座位的私人记忆：对局 id + 座位 id。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM priv WHERE match_id = ? AND seat = ? AND seq > ? ORDER BY seq",
                (match_id, int(seat), after_seq),
            ).fetchall()
        return [self._message_row(row) for row in rows]

    def _message_row(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data.pop("id", None)
        data.pop("match_id", None)
        try:
            data["facts"] = json.loads(data.get("facts") or "{}")
        except json.JSONDecodeError:
            data["facts"] = {}
        return data

    # ------------------------------------------------------------------ 快照

    def snapshot(self, match_id: str, *, god: bool = False) -> dict[str, Any] | None:
        """从库里还原一局的快照（进程重启后也能看历史对局）。"""
        match = self.get_match(match_id)
        if match is None:
            return None
        public = self.read_public(match_id)
        seats = match.get("seats") or []
        for seat in seats:
            # 非上帝视角：身份和私聊都不给（座位表是带身份的存档）
            if god:
                seat["private"] = self.read_private(match_id, int(seat["seat"]))
            else:
                for key in ("role", "camp", "skill", "describe"):
                    seat.pop(key, None)
                seat["private"] = []
        return {
            "id": match["id"],
            "status": match["status"],
            "winner": match["winner"],
            "error": "",
            "day": match["day"],
            "phase": match["phase"],
            "alive": [seat["seat"] for seat in seats if seat.get("alive")],
            "elapsed": match["elapsed"],
            "stopped": match["stopped"],
            "paused": False,
            "speed": 1.0,
            "humans": [],
            "pending": None,
            "options": match.get("options") or {},
            "model": match.get("options", {}).get("profile_name", ""),
            "judge_model": match.get("options", {}).get("judge_model", ""),
            "board": match.get("options", {}).get("board") or {},
            "agents": match.get("agents") or [],
            "messages": public,
            "seats": seats,
            "ledger": [],
        }
