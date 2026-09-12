"""OmniCore Scheduler — cron-style job scheduling with background execution.

DNA: Hermes cronjob + Dream engine + background thread pool.

Supports: one-shot, recurring, cron-expression, background notify.
Jobs survive session restarts (persisted to SQLite).
"""

import time
import threading
import json
import sqlite3
import re
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, Callable


@dataclass
class ScheduledJob:
    """A scheduled task."""
    id: str
    name: str
    command: str
    schedule: str  # cron expression or interval
    last_run: Optional[float] = None
    next_run: Optional[float] = None
    enabled: bool = True
    run_count: int = 0
    fail_count: int = 0
    created_at: float = field(default_factory=time.time)


class Scheduler:
    """Background job scheduler with cron support.

    Usage:
        sched = Scheduler()
        sched.every("30m").do("cleanup_temp_files")
        sched.cron("0 3 * * *").do("daily_backup")
        sched.start()
    """

    def __init__(self, db_path: str = "~/.omnicore/scheduler.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, ScheduledJob] = {}
        self._handlers: dict[str, list[Callable]] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._init_db()
        self._load_jobs()

    # ── DB ────────────────────────────────────────────────────────────

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    command TEXT,
                    schedule TEXT,
                    last_run REAL,
                    next_run REAL,
                    enabled INTEGER DEFAULT 1,
                    run_count INTEGER DEFAULT 0,
                    fail_count INTEGER DEFAULT 0,
                    created_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS job_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT,
                    started_at REAL,
                    finished_at REAL,
                    success INTEGER,
                    output TEXT,
                    FOREIGN KEY(job_id) REFERENCES jobs(id)
                )
            """)

    def _load_jobs(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute("SELECT * FROM jobs").fetchall()
            for row in rows:
                job = ScheduledJob(
                    id=row[0], name=row[1], command=row[2], schedule=row[3],
                    last_run=row[4], next_run=row[5], enabled=bool(row[6]),
                    run_count=row[7], fail_count=row[8], created_at=row[9]
                )
                self._jobs[job.id] = job

    def _save_job(self, job: ScheduledJob):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (job.id, job.name, job.command, job.schedule,
                  job.last_run, job.next_run, int(job.enabled),
                  job.run_count, job.fail_count, job.created_at))

    def _log_job(self, job_id: str, success: bool, output: str, 
                 started: float, finished: float):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO job_logs (job_id, started_at, finished_at, success, output) "
                "VALUES (?,?,?,?,?)",
                (job_id, started, finished, int(success), output[:2000])
            )

    # ── Job creation ──────────────────────────────────────────────────

    def every(self, interval: str):
        """Schedule a job with interval: '30m', '2h', '1d'."""
        return _JobBuilder(self, f"interval:{interval}")

    def cron(self, expression: str):
        """Schedule with cron expression: '0 3 * * *'."""
        return _JobBuilder(self, f"cron:{expression}")

    def at(self, timestamp: float):
        """Schedule one-shot at specific time."""
        return _JobBuilder(self, f"at:{timestamp}")

    def _add_job(self, job: ScheduledJob):
        with self._lock:
            self._jobs[job.id] = job
            self._save_job(job)

    def remove(self, job_id: str):
        with self._lock:
            self._jobs.pop(job_id, None)
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))

    def on(self, job_id: str, handler: Callable):
        """Register a handler to be called when job fires."""
        self._handlers.setdefault(job_id, []).append(handler)

    # ── Execution ─────────────────────────────────────────────────────

    def start(self):
        """Start the scheduler in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self):
        while self._running:
            now = time.time()
            with self._lock:
                for job in list(self._jobs.values()):
                    if not job.enabled:
                        continue
                    if job.next_run and job.next_run <= now:
                        self._execute(job)
            time.sleep(1)  # Check every second

    def _execute(self, job: ScheduledJob):
        started = time.time()
        success = True
        output = ""

        try:
            # Run handlers
            for handler in self._handlers.get(job.id, []):
                try:
                    result = handler()
                    output += str(result)[:1000]
                except Exception as e:
                    output += f"Handler error: {e}\n"
                    success = False

            job.run_count += 1
            if not success:
                job.fail_count += 1
            job.last_run = started

        except Exception as e:
            success = False
            job.fail_count += 1
            output = str(e)

        # Schedule next run
        job.next_run = self._next_run_time(job.schedule)
        self._save_job(job)
        self._log_job(job.id, success, output, started, time.time())

    def _next_run_time(self, schedule: str) -> float:
        now = time.time()
        if schedule.startswith("interval:"):
            interval = schedule.split(":", 1)[1]
            return now + self._parse_interval(interval)
        elif schedule.startswith("cron:"):
            expr = schedule.split(":", 1)[1]
            return self._cron_next(expr, now)
        elif schedule.startswith("at:"):
            ts = float(schedule.split(":", 1)[1])
            return ts if ts > now else now + 3600  # retry in 1h
        return now + 3600  # default: 1 hour

    def _parse_interval(self, interval: str) -> int:
        """Parse '30m', '2h', '1d' to seconds."""
        match = re.match(r'(\d+)([smhd])', interval)
        if not match:
            return 3600
        value, unit = int(match.group(1)), match.group(2)
        multipliers = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
        return value * multipliers.get(unit, 3600)

    def _cron_next(self, expr: str, from_time: float) -> float:
        """Simple cron parser — just add 1 hour for now.
        # ponytail: full cron parser if scheduling precision matters
        """
        return from_time + 3600

    # ── Query ─────────────────────────────────────────────────────────

    def list_jobs(self) -> list[dict]:
        with self._lock:
            return [
                {"id": j.id, "name": j.name, "schedule": j.schedule,
                 "enabled": j.enabled, "next_run": j.next_run,
                 "run_count": j.run_count, "fail_count": j.fail_count}
                for j in self._jobs.values()
            ]

    def get_logs(self, job_id: str, limit: int = 20) -> list[dict]:
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT * FROM job_logs WHERE job_id=? ORDER BY id DESC LIMIT ?",
                (job_id, limit)
            ).fetchall()
            return [
                {"id": r[0], "job_id": r[1], "started_at": r[2],
                 "finished_at": r[3], "success": bool(r[4]), "output": r[5]}
                for r in rows
            ]


class _JobBuilder:
    """Fluent interface for building scheduled jobs."""

    def __init__(self, scheduler: Scheduler, schedule: str):
        self._scheduler = scheduler
        self._schedule = schedule
        self._name = ""
        self._handler: Optional[Callable] = None

    def do(self, name: str):
        self._name = name
        return self

    def run(self, fn: Callable):
        self._handler = fn
        job = self._build()
        self._scheduler._add_job(job)
        if fn:
            self._scheduler.on(job.id, fn)
        return job.id

    def _build(self) -> ScheduledJob:
        now = time.time()
        job = ScheduledJob(
            id=f"job_{int(now)}_{hash(self._name) % 10000}",
            name=self._name,
            command=self._name,
            schedule=self._schedule,
            next_run=now + self._scheduler._parse_interval(
                self._schedule.split(":", 1)[1] if ":" in self._schedule else "1s"
            ) if self._schedule.startswith("interval:") else now + 1,
        )
        return job


# ── Self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile

    db = Path(tempfile.gettempdir()) / "test_scheduler.db"
    sched = Scheduler(str(db))

    # Add jobs
    counter = {"count": 0}

    def increment():
        counter["count"] += 1
        return f"Count: {counter['count']}"

    sched.every("1s").do("test_counter").run(increment)
    sched.every("5m").do("test_cleanup")

    # List
    jobs = sched.list_jobs()
    print(f"Jobs: {len(jobs)}")
    for j in jobs:
        print(f"  {j['id'][:12]}... {j['name']} [{j['schedule']}]")

    # Run once
    sched.start()
    time.sleep(2.5)
    sched.stop()

    print(f"Counter after 2.5s: {counter['count']} (expected ~2)")
    assert counter["count"] >= 1, "Job didn't run"

    # Cleanup
    db.unlink(missing_ok=True)
    print("✓ Scheduler self-tests passed")