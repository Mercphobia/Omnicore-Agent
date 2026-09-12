"""SQLite persistent memory store. Survives restarts.
DNA: Hermes Agent (cross-session memory).
"""

import json
import time
import sqlite3
from pathlib import Path
from typing import Optional


class MemoryStore:
    """Persistent key-value + conversation store backed by SQLite."""

    def __init__(self, db_path: str = "~/.omnicore/memory.db"):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS facts (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id);
        """)
        self.conn.commit()

    # ── Facts (key-value memory) ────────────────────────────

    def remember(self, key: str, value: str) -> None:
        """Store a fact. Overwrites if key exists."""
        self.conn.execute(
            "INSERT OR REPLACE INTO facts (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, time.time()),
        )
        self.conn.commit()

    def recall(self, key: str) -> Optional[str]:
        """Retrieve a fact by key."""
        row = self.conn.execute(
            "SELECT value FROM facts WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def forget(self, key: str) -> None:
        self.conn.execute("DELETE FROM facts WHERE key = ?", (key,))
        self.conn.commit()

    def all_facts(self) -> dict[str, str]:
        """Return all stored facts."""
        rows = self.conn.execute("SELECT key, value FROM facts ORDER BY updated_at DESC").fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ── Conversations ───────────────────────────────────────

    def save_message(self, session_id: str, role: str, content: str) -> None:
        self.conn.execute(
            "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, time.time()),
        )
        self.conn.commit()
        # Update session timestamp
        self.conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (time.time(), session_id),
        )
        self.conn.commit()

    def get_messages(self, session_id: str, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT role, content FROM conversations WHERE session_id = ? ORDER BY id ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def search_messages(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search across all conversations."""
        rows = self.conn.execute(
            "SELECT session_id, role, content FROM conversations WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
        return [{"session_id": r["session_id"], "role": r["role"], "content": r["content"][:200]} for r in rows]

    # ── Sessions ────────────────────────────────────────────

    def create_session(self, session_id: str, title: str = "") -> None:
        now = time.time()
        self.conn.execute(
            "INSERT OR IGNORE INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (session_id, title or f"Session {session_id[:8]}", now, now),
        )
        self.conn.commit()

    def list_sessions(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_session_title(self, session_id: str) -> str:
        row = self.conn.execute("SELECT title FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return row["title"] if row else ""

    def close(self):
        self.conn.close()