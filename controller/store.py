"""SQLite store shared by the controller and the Allinone MCP tools.

tasks   — prompts run through Claude Code (queue + results)
memory  — notes that persist across sessions and gateways
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created     REAL NOT NULL,
    started     REAL,
    finished    REAL,
    gateway     TEXT,
    model       TEXT,
    project     TEXT,
    prompt      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    result      TEXT,
    session_id  TEXT,
    cost_usd    REAL,
    num_turns   INTEGER,
    duration_ms INTEGER,
    exit_code   INTEGER
);
CREATE INDEX IF NOT EXISTS tasks_status ON tasks(status, id);
CREATE TABLE IF NOT EXISTS memory (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    created REAL NOT NULL,
    text    TEXT NOT NULL,
    tags    TEXT NOT NULL DEFAULT '',
    source  TEXT NOT NULL DEFAULT ''
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(SCHEMA)
    return conn


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.conn = connect(path)

    # ------------------------------------------------------------- tasks
    def add_task(self, prompt: str, gateway: str, model: str, project: str, status: str = "pending") -> int:
        cur = self.conn.execute(
            "INSERT INTO tasks(created, gateway, model, project, prompt, status) VALUES (?,?,?,?,?,?)",
            (time.time(), gateway, model, project, prompt, status))
        self.conn.commit()
        return int(cur.lastrowid)

    def mark_running(self, task_id: int) -> None:
        self.conn.execute("UPDATE tasks SET status='running', started=? WHERE id=?", (time.time(), task_id))
        self.conn.commit()

    def finish_task(self, task_id: int, res: Dict[str, Any]) -> None:
        status = "failed" if res.get("is_error") else "done"
        self.conn.execute(
            "UPDATE tasks SET status=?, finished=?, result=?, session_id=?, cost_usd=?, num_turns=?, "
            "duration_ms=?, exit_code=? WHERE id=?",
            (status, time.time(), res.get("result"), res.get("session_id"), res.get("cost_usd"),
             res.get("num_turns"), res.get("duration_ms"), res.get("exit_code"), task_id))
        self.conn.commit()

    def fail_task(self, task_id: int, message: str) -> None:
        self.conn.execute("UPDATE tasks SET status='failed', finished=?, result=? WHERE id=?",
                          (time.time(), message, task_id))
        self.conn.commit()

    def next_pending(self) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM tasks WHERE status='pending' ORDER BY id LIMIT 1").fetchone()

    def get_task(self, task_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()

    def list_tasks(self, limit: int = 20) -> List[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def reset_stuck(self) -> int:
        cur = self.conn.execute("UPDATE tasks SET status='pending', started=NULL WHERE status='running'")
        self.conn.commit()
        return cur.rowcount

    # ------------------------------------------------------------ memory
    def remember(self, text: str, tags: str = "", source: str = "") -> int:
        cur = self.conn.execute("INSERT INTO memory(created, text, tags, source) VALUES (?,?,?,?)",
                                (time.time(), text, tags, source))
        self.conn.commit()
        return int(cur.lastrowid)

    def search_memory(self, query: str, limit: int = 10) -> List[sqlite3.Row]:
        words = [w for w in query.split() if w]
        if not words:
            return self.recent_memory(limit)
        clause = " AND ".join("(text LIKE ? OR tags LIKE ?)" for _ in words)
        params: List[Any] = []
        for w in words:
            params += [f"%{w}%", f"%{w}%"]
        return self.conn.execute(f"SELECT * FROM memory WHERE {clause} ORDER BY id DESC LIMIT ?",
                                 (*params, limit)).fetchall()

    def recent_memory(self, limit: int = 10) -> List[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM memory ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def forget(self, memory_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM memory WHERE id=?", (memory_id,))
        self.conn.commit()
        return cur.rowcount > 0
