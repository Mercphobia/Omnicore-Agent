"""OmniCore Todo — task list tracker for multi-step work.

DNA: Hermes todo_list + Checkpoint persistence.

Tracks tasks with status, priority, dependencies.
Persists to SQLite, survives restarts.
"""

import time
import json
import sqlite3
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Task:
    id: str
    title: str
    status: str = "pending"  # pending | in_progress | done | blocked
    priority: str = "medium"  # high | medium | low
    parent_id: Optional[str] = None
    notes: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None


class TodoList:
    """Multi-step task tracker with persistence.

    Usage:
        todo = TodoList()
        todo.add("Deploy to production", priority="high")
        todo.add("Write tests", parent=todo.add("Refactor module"))
        todo.start(todo.find("Deploy to production"))
        todo.done(todo.find("Deploy to production"))
        todo.dashboard()
    """

    def __init__(self, db_path: str = "~/.omnicore/todo.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    status TEXT DEFAULT 'pending',
                    priority TEXT DEFAULT 'medium',
                    parent_id TEXT,
                    notes TEXT DEFAULT '',
                    created_at REAL,
                    updated_at REAL,
                    completed_at REAL
                )
            """)

    def add(self, title: str, priority: str = "medium",
            parent_id: Optional[str] = None, notes: str = "") -> str:
        """Add a task. Returns task ID."""
        task_id = f"task_{int(time.time())}_{hash(title) % 10000}"
        now = time.time()

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?)",
                (task_id, title, "pending", priority, parent_id,
                 notes, now, now, None)
            )
        return task_id

    def start(self, task_id: str):
        """Mark task as in_progress."""
        self._update(task_id, status="in_progress")

    def done(self, task_id: str):
        """Mark task as done."""
        now = time.time()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "UPDATE tasks SET status='done', updated_at=?, completed_at=? WHERE id=?",
                (now, now, task_id)
            )

    def block(self, task_id: str, reason: str = ""):
        """Mark task as blocked."""
        self._update(task_id, status="blocked", notes=reason)

    def _update(self, task_id: str, **kwargs):
        now = time.time()
        kwargs["updated_at"] = now
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [task_id]
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(f"UPDATE tasks SET {sets} WHERE id=?", vals)

    def remove(self, task_id: str):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM tasks WHERE id=? OR parent_id=?", 
                        (task_id, task_id))

    def get(self, task_id: str) -> Optional[Task]:
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id=?", 
                              (task_id,)).fetchone()
            if row:
                return Task(*row)
        return None

    def list(self, status: str = "") -> list[Task]:
        """List tasks, optionally filtered by status."""
        with sqlite3.connect(str(self.db_path)) as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE status=? ORDER BY priority, created_at",
                    (status,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks ORDER BY "
                    "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
                    "created_at"
                ).fetchall()
            return [Task(*r) for r in rows]

    def subtasks(self, parent_id: str) -> list[Task]:
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE parent_id=? ORDER BY created_at",
                (parent_id,)
            ).fetchall()
            return [Task(*r) for r in rows]

    def progress(self) -> dict:
        """Get progress statistics."""
        with sqlite3.connect(str(self.db_path)) as conn:
            total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            done = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status='done'"
            ).fetchone()[0]
            in_progress = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status='in_progress'"
            ).fetchone()[0]
            blocked = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status='blocked'"
            ).fetchone()[0]

        return {
            "total": total,
            "done": done,
            "in_progress": in_progress,
            "blocked": blocked,
            "pending": total - done - in_progress - blocked,
            "percent": round(done / max(total, 1) * 100),
        }

    def dashboard(self) -> str:
        """Rich dashboard of tasks."""
        p = self.progress()
        bar_len = 20
        filled = int(p["percent"] / 100 * bar_len)

        lines = [
            "╔══════════════════════════════════╗",
            "║       TODO — Task Dashboard     ║",
            "╠══════════════════════════════════╣",
            f"║  Progress: [{'█' * filled}{'░' * (bar_len - filled)}] {p['percent']}%  ║",
            f"║  Total: {p['total']:<2d} | ✓ {p['done']:<2d} | ● {p['in_progress']:<2d} | ✗ {p['blocked']:<2d} | ○ {p['pending']:<2d}  ║",
            "╠══════════════════════════════════╣",
        ]

        active = self.list()
        if not active:
            lines.append("║  No tasks yet. Add one!         ║")
        else:
            for t in active[:8]:
                icon = {"done": "✓", "in_progress": "●", "blocked": "✗"}.get(t.status, "○")
                line = f"║  {icon} [{t.priority[0].upper()}] {t.title[:35]:<35s} ║"
                lines.append(line)

        lines.append("╚══════════════════════════════════╝")
        return "\n".join(lines)


# ── Self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile

    db = Path(tempfile.gettempdir()) / "test_todo.db"
    todo = TodoList(str(db))

    # Add tasks
    t1 = todo.add("Setup CI/CD pipeline", priority="high")
    t2 = todo.add("Write unit tests", priority="medium")
    t3 = todo.add("Fix login bug", priority="high", parent_id=t1)
    t4 = todo.add("Deploy to staging", priority="medium")
    t5 = todo.add("Update docs", priority="low")

    # Progress
    todo.start(t1)
    todo.done(t2)
    todo.block(t3, "Waiting for API key")
    todo.start(t4)

    p = todo.progress()
    print(f"Progress: {p['done']}/{p['total']} done ({p['percent']}%)")
    assert p["done"] == 1
    assert p["in_progress"] == 2
    assert p["blocked"] == 1

    # Subtasks
    subs = todo.subtasks(t1)
    print(f"Subtasks of t1: {len(subs)}")
    assert len(subs) == 1
    assert subs[0].title == "Fix login bug"

    # List by status
    blocked = todo.list("blocked")
    print(f"Blocked tasks: {len(blocked)}")
    assert len(blocked) == 1

    # Dashboard
    print(todo.dashboard())

    # Cleanup
    db.unlink(missing_ok=True)
    print("\n✓ TodoList self-tests passed")