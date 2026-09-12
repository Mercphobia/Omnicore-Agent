"""
Live performance tracker — SQLite-backed, Rich CLI dashboard.

DNA: GPT-5.5 (structured metrics) + Codex CLI (sandbox profiling).

BenchmarkTracker records every task with type, token count, latency,
and success status.  Persists to SQLite for historical analysis.
Produces a Rich CLI dashboard with charts and trends.

Usage::

    bt = BenchmarkTracker()
    bt.record_task("code_generation", tokens=1500, latency=2.3, success=True)
    bt.record_task("debugging", tokens=800, latency=5.1, success=False)
    bt.tokens_saved_report()
    bt.dashboard()
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import statistics
import textwrap
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Optional Rich import ────────────────────────────────────────────────

_rich_available = False
_console: Any = None
_Table: Any = None
_BarColumn: Any = None
_Text: Any = None
_Panel: Any = None
try:
    from rich.console import Console as _Console
    from rich.table import Table as _Table
    from rich.progress import BarColumn as _BarColumn
    from rich.text import Text as _Text
    from rich.panel import Panel as _Panel
    from rich import box
    _console = _Console()
    _Table = _Table  # noqa: F811
    _BarColumn = _BarColumn
    _Text = _Text
    _Panel = _Panel
    _rich_available = True
except ImportError:
    pass


# ── Data types ──────────────────────────────────────────────────────────

@dataclass
class TaskRecord:
    """A single recorded task metric."""
    id: int
    task_type: str
    tokens: int
    latency: float                     # seconds
    success: bool
    timestamp: float
    model: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenSavingsReport:
    """Ponytail impact analysis — tokens saved via optimization."""
    total_tokens_without_optimization: int
    total_tokens_with_optimization: int
    tokens_saved: int
    savings_percentage: float
    avg_savings_per_task: float
    top_optimized_categories: list[tuple[str, int]]


@dataclass
class SuccessRateReport:
    """Success rate breakdown."""
    overall: float
    by_category: dict[str, float]
    trend: list[float]                 # per-day success rates
    volatility: float                  # std dev of success rate


# ── SQLite schema ───────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    tokens INTEGER NOT NULL DEFAULT 0,
    latency REAL NOT NULL DEFAULT 0.0,
    success INTEGER NOT NULL DEFAULT 0,
    timestamp REAL NOT NULL,
    model TEXT DEFAULT '',
    extra TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_task_type ON tasks(task_type);
CREATE INDEX IF NOT EXISTS idx_timestamp ON tasks(timestamp);
CREATE INDEX IF NOT EXISTS idx_success ON tasks(success);

CREATE TABLE IF NOT EXISTS token_baseline (
    task_type TEXT PRIMARY KEY,
    baseline_tokens INTEGER NOT NULL,
    optimized_tokens INTEGER NOT NULL,
    updated_at REAL NOT NULL
);
"""


# ── BenchmarkTracker ────────────────────────────────────────────────────

class BenchmarkTracker:
    """Live performance tracker with SQLite persistence and Rich dashboard.

    Records every task execution with type, token usage, latency, and
    success. Provides token savings analysis, success rate trends,
    time-to-solution tracking, auto-optimization suggestions, and a
    Rich CLI dashboard.
    """

    def __init__(
        self,
        db_path: str | Path = "",
        auto_commit: bool = True,
    ):
        self._db_path = str(Path(db_path) if db_path else Path.home() / ".omnicore" / "benchmark.db")
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._auto_commit = auto_commit
        self._lock = threading.Lock()
        self._pending: list[TaskRecord] = []

        self._init_db()

    def _init_db(self) -> None:
        """Create tables on first connection."""
        with self._get_conn() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a thread-safe connection."""
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    # ── Record ─────────────────────────────────────────────────────

    def record_task(
        self,
        task_type: str,
        tokens: int = 0,
        latency: float = 0.0,
        success: bool = True,
        model: str = "",
        extra: Optional[dict[str, Any]] = None,
    ) -> TaskRecord:
        """Record a task execution metric.

        Args:
            task_type: Category (e.g., 'code_generation', 'debugging').
            tokens: Number of tokens consumed.
            latency: Wall-clock time in seconds.
            success: Whether the task succeeded.
            model: Optional model identifier.
            extra: Optional extra metadata.

        Returns:
            The TaskRecord object.
        """
        record = TaskRecord(
            id=0,  # assigned by DB
            task_type=task_type,
            tokens=tokens,
            latency=latency,
            success=success,
            timestamp=time.time(),
            model=model,
            extra=extra or {},
        )

        with self._lock:
            self._pending.append(record)
            if self._auto_commit and len(self._pending) >= 10:
                self._flush()

        return record

    def _flush(self) -> None:
        """Write pending records to SQLite."""
        if not self._pending:
            return
        with self._get_conn() as conn:
            conn.executemany(
                "INSERT INTO tasks (task_type, tokens, latency, success, timestamp, model, extra) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (r.task_type, r.tokens, r.latency, int(r.success),
                     r.timestamp, r.model, json.dumps(r.extra))
                    for r in self._pending
                ],
            )
            conn.commit()
        self._pending.clear()

    def flush(self) -> None:
        """Force-write all pending records to disk."""
        with self._lock:
            self._flush()

    # ── Tokens saved report ────────────────────────────────────────

    def tokens_saved_report(self) -> TokenSavingsReport:
        """Ponytail impact analysis — tokens saved via optimization.

        Compares current token usage against baselines to estimate
        savings from optimization strategies.

        Returns:
            TokenSavingsReport with full breakdown.
        """
        self._flush()
        with self._get_conn() as conn:
            # Total tokens used
            row = conn.execute("SELECT SUM(tokens) as total FROM tasks").fetchone()
            total_with_opt = row["total"] or 0

            # Get baselines
            baselines = conn.execute("SELECT * FROM token_baseline").fetchall()
            total_without = total_with_opt

            category_savings: list[tuple[str, int]] = []
            for bl in baselines:
                total_without += bl["baseline_tokens"] - bl["optimized_tokens"]
                saved = bl["baseline_tokens"] - bl["optimized_tokens"]
                if saved > 0:
                    category_savings.append((bl["task_type"], saved))

            tokens_saved = total_without - total_with_opt
            pct = (tokens_saved / max(1, total_without)) * 100

            task_count = conn.execute("SELECT COUNT(*) as cnt FROM tasks").fetchone()["cnt"]

            return TokenSavingsReport(
                total_tokens_without_optimization=total_without,
                total_tokens_with_optimization=total_with_opt,
                tokens_saved=max(0, tokens_saved),
                savings_percentage=round(pct, 2),
                avg_savings_per_task=round(tokens_saved / max(1, task_count), 1),
                top_optimized_categories=sorted(category_savings, key=lambda x: x[1], reverse=True)[:5],
            )

    def set_token_baseline(self, task_type: str, baseline: int, optimized: int) -> None:
        """Set or update a token baseline for a task type.

        Args:
            task_type: The category.
            baseline: Tokens before optimization.
            optimized: Tokens after optimization.
        """
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO token_baseline (task_type, baseline_tokens, optimized_tokens, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (task_type, baseline, optimized, time.time()),
            )
            conn.commit()

    # ── Success rate ───────────────────────────────────────────────

    def success_rate_trend(self, window_days: int = 30) -> SuccessRateReport:
        """Track success rate over time with per-category breakdown.

        Args:
            window_days: How many days of history to analyze.

        Returns:
            SuccessRateReport with overall rate, per-category, and trend.
        """
        self._flush()
        cutoff = time.time() - (window_days * 86400)

        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT task_type, success, timestamp FROM tasks WHERE timestamp >= ?",
                (cutoff,),
            ).fetchall()

            if not rows:
                return SuccessRateReport(overall=0.0, by_category={}, trend=[], volatility=0.0)

            categories: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))  # success, total
            daily: dict[int, tuple[int, int]] = defaultdict(lambda: (0, 0))

            for r in rows:
                task_type, success, ts = r["task_type"], r["success"], r["timestamp"]
                s, t = categories[task_type]
                categories[task_type] = (s + (1 if success else 0), t + 1)

                day = int(ts // 86400)
                ds, dt = daily[day]
                daily[day] = (ds + (1 if success else 0), dt + 1)

            overall_success = sum(s for s, t in categories.values())
            overall_total = sum(t for s, t in categories.values())

            by_category = {
                cat: round(s / max(1, t), 3)
                for cat, (s, t) in categories.items()
            }

            # Daily trend sorted by day
            trend = [
                round(s / max(1, t), 3)
                for day, (s, t) in sorted(daily.items())
            ]

            volatility = statistics.stdev(trend) if len(trend) > 1 else 0.0

            return SuccessRateReport(
                overall=round(overall_success / max(1, overall_total), 3),
                by_category=by_category,
                trend=trend,
                volatility=round(volatility, 4),
            )

    # ── Time to solution ───────────────────────────────────────────

    def time_to_solution(self, task_type: str = "") -> dict[str, Any]:
        """Average time per task type.

        Args:
            task_type: Optional filter for a specific category.

        Returns:
            Dict with mean, median, p95, min, max per category.
        """
        self._flush()

        with self._get_conn() as conn:
            where = "WHERE task_type = ?" if task_type else ""
            params = (task_type,) if task_type else ()

            rows = conn.execute(
                f"SELECT task_type, latency FROM tasks {where} ORDER BY task_type",
                params,
            ).fetchall()

        grouped: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            grouped[r["task_type"]].append(r["latency"])

        result: dict[str, Any] = {}
        for cat, lats in grouped.items():
            if not lats:
                continue
            sorted_lats = sorted(lats)
            result[cat] = {
                "count": len(lats),
                "mean": round(statistics.mean(lats), 3),
                "median": round(statistics.median(lats), 3),
                "p95": round(sorted_lats[int(len(sorted_lats) * 0.95)] if len(sorted_lats) > 1 else lats[0], 3),
                "min": round(min(lats), 3),
                "max": round(max(lats), 3),
                "total": round(sum(lats), 3),
            }

        return result

    # ── Auto-optimize ──────────────────────────────────────────────

    def auto_optimize(self) -> list[str]:
        """Suggest optimizations based on performance trends.

        Analyzes latency distributions and token usage to recommend
        specific improvements.

        Returns:
            List of optimization suggestions.
        """
        suggestions: list[str] = []
        tts = self.time_to_solution()

        for cat, stats in tts.items():
            count = stats.get("count", 0)
            p95 = stats.get("p95", 0)
            mean = stats.get("mean", 0)

            if count >= 5 and p95 > mean * 3:
                suggestions.append(
                    f"[{cat}] High variance (p95={p95}s vs mean={mean}s) — "
                    "consider caching or parallelizing"
                )
            if count >= 10 and mean > 5.0:
                suggestions.append(
                    f"[{cat}] Slow average ({mean}s) — "
                    "profile and optimize the critical path"
                )

        # Token analysis
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT task_type, AVG(tokens) as avg_tok, COUNT(*) as cnt "
                "FROM tasks GROUP BY task_type HAVING cnt >= 5 AND avg_tok > 2000"
            ).fetchall()

        for r in row:
            suggestions.append(
                f"[{r['task_type']}] High token usage (avg {int(r['avg_tok'])} tokens) — "
                "consider context compression or prompt optimization"
            )

        return suggestions

    # ── Dashboard ──────────────────────────────────────────────────

    def dashboard(self) -> str:
        """Produce a Rich CLI dashboard with charts and metrics.

        Returns:
            Formatted string (Rich markup if Rich is available, else plain).
        """
        self._flush()
        metrics = self._compute_dashboard_metrics()

        if not _rich_available:
            return self._plain_dashboard(metrics)

        return self._rich_dashboard(metrics)

    def _compute_dashboard_metrics(self) -> dict[str, Any]:
        """Gather all metrics needed for the dashboard."""
        self._flush()

        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) as cnt FROM tasks").fetchone()["cnt"]
            avg_tokens = conn.execute("SELECT AVG(tokens) as avg FROM tasks").fetchone()["avg"] or 0
            avg_latency = conn.execute("SELECT AVG(latency) as avg FROM tasks").fetchone()["avg"] or 0
            success_rate = conn.execute(
                "SELECT AVG(success) as rate FROM tasks"
            ).fetchone()["rate"] or 0

            # Per-category breakdown
            cats = conn.execute(
                "SELECT task_type, COUNT(*) as cnt, AVG(tokens) as avg_tok, "
                "AVG(latency) as avg_lat, AVG(success) as succ "
                "FROM tasks GROUP BY task_type ORDER BY cnt DESC LIMIT 10"
            ).fetchall()

            # Recent trend (last 100)
            trend_rows = conn.execute(
                "SELECT timestamp, tokens, latency, success FROM tasks "
                "ORDER BY timestamp DESC LIMIT 100"
            ).fetchall()

        return {
            "total_tasks": total,
            "avg_tokens": avg_tokens,
            "avg_latency": avg_latency,
            "success_rate": success_rate,
            "categories": cats,
            "recent": list(reversed(trend_rows)),
        }

    def _rich_dashboard(self, metrics: dict[str, Any]) -> str:
        """Build a Rich-formatted dashboard."""
        from io import StringIO
        buf = StringIO()
        tmp_console = _Console(file=buf, force_terminal=True, width=100)

        # Title
        tmp_console.print(_Panel.fit(
            "[bold cyan]OmniCore Benchmark Dashboard[/bold cyan]",
            border_style="cyan",
        ))

        # Summary table
        summary = _Table(title="Summary", box=box.ROUNDED)
        summary.add_column("Metric", style="cyan")
        summary.add_column("Value", style="green")
        summary.add_row("Total Tasks", str(metrics["total_tasks"]))
        summary.add_row("Success Rate", f"{metrics['success_rate']*100:.1f}%")
        summary.add_row("Avg Tokens/Task", f"{metrics['avg_tokens']:.0f}")
        summary.add_row("Avg Latency", f"{metrics['avg_latency']:.2f}s")
        tmp_console.print(summary)

        # Category breakdown
        cat_table = _Table(title="Category Breakdown", box=box.ROUNDED)
        cat_table.add_column("Category", style="cyan")
        cat_table.add_column("Count", justify="right")
        cat_table.add_column("Avg Tokens", justify="right")
        cat_table.add_column("Avg Latency", justify="right")
        cat_table.add_column("Success Rate", justify="right")

        for cat in metrics["categories"]:
            cat_table.add_row(
                cat["task_type"],
                str(cat["cnt"]),
                f"{cat['avg_tok']:.0f}",
                f"{cat['avg_lat']:.2f}s",
                f"{cat['succ']*100:.0f}%",
            )
        tmp_console.print(cat_table)

        # Success rate bar
        rate = metrics["success_rate"]
        bar_width = 30
        filled = int(rate * bar_width)
        bar_color = "green" if rate >= 0.8 else "yellow" if rate >= 0.5 else "red"
        bar = "█" * filled + "░" * (bar_width - filled)
        tmp_console.print(f"\n[bold]Success Rate:[/bold] [{bar_color}]{bar}[/{bar_color}] {rate*100:.1f}%")

        # Recent trend sparkline
        if metrics["recent"]:
            recent_vals = [r["success"] for r in metrics["recent"]]
            # Simple ASCII sparkline
            chars = " ▁▂▃▄▅▆▇█"
            scaled = [min(7, int(s * 7)) for s in recent_vals]
            spark = "".join(chars[s] for s in scaled)
            tmp_console.print(f"\n[bold]Recent Trend (100 tasks):[/bold] {spark}")

        tmp_console.print(f"\n[dim]Last updated: {time.strftime('%Y-%m-%d %H:%M:%S')}[/dim]")

        return buf.getvalue()

    def _plain_dashboard(self, metrics: dict[str, Any]) -> str:
        """Plain-text dashboard for when Rich is unavailable."""
        lines = [
            "=" * 60,
            "  OmniCore Benchmark Dashboard",
            "=" * 60,
            f"  Total Tasks:    {metrics['total_tasks']}",
            f"  Success Rate:   {metrics['success_rate']*100:.1f}%",
            f"  Avg Tokens:     {metrics['avg_tokens']:.0f}",
            f"  Avg Latency:    {metrics['avg_latency']:.2f}s",
            "-" * 60,
        ]
        for cat in metrics["categories"]:
            lines.append(
                f"  {cat['task_type']:<20} count={cat['cnt']:<5} "
                f"tok={cat['avg_tok']:.0f}  lat={cat['avg_lat']:.2f}s  "
                f"succ={cat['succ']*100:.0f}%"
            )
        lines.append("=" * 60)
        return "\n".join(lines)

    # ── Query helpers ──────────────────────────────────────────────

    def get_recent_tasks(self, limit: int = 20) -> list[TaskRecord]:
        """Get the most recent task records."""
        self._flush()
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_tasks_by_type(self, task_type: str, limit: int = 100) -> list[TaskRecord]:
        """Get task records filtered by type."""
        self._flush()
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE task_type = ? ORDER BY timestamp DESC LIMIT ?",
                (task_type, limit),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            id=row["id"],
            task_type=row["task_type"],
            tokens=row["tokens"],
            latency=row["latency"],
            success=bool(row["success"]),
            timestamp=row["timestamp"],
            model=row["model"],
            extra=json.loads(row["extra"]) if row["extra"] else {},
        )

    # ── Cleanup ────────────────────────────────────────────────────

    def vacuum(self) -> None:
        """Compact the database."""
        self._flush()
        with self._get_conn() as conn:
            conn.execute("VACUUM")

    def clear(self, before_days: Optional[int] = None) -> int:
        """Clear old records. If before_days is set, only clears older records."""
        self._flush()
        with self._get_conn() as conn:
            if before_days is not None:
                cutoff = time.time() - (before_days * 86400)
                result = conn.execute("DELETE FROM tasks WHERE timestamp < ?", (cutoff,))
            else:
                result = conn.execute("DELETE FROM tasks")
            conn.commit()
            return result.rowcount


# ── Self-test ───────────────────────────────────────────────────────────

def _self_test() -> None:
    """Verify BenchmarkTracker core operations."""
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        bt = BenchmarkTracker(db_path=db_path, auto_commit=False)

        # record_task
        for i in range(15):
            bt.record_task(
                "code_generation",
                tokens=500 + i * 100,
                latency=1.0 + i * 0.3,
                success=(i % 3 != 0),
            )
            bt.record_task(
                "debugging",
                tokens=300 + i * 50,
                latency=3.0 + i * 0.5,
                success=(i % 4 != 0),
            )
        bt.flush()
        print(f"  record_task: 30 records written")

        # Set baseline
        bt.set_token_baseline("code_generation", 1500, 800)
        bt.set_token_baseline("debugging", 1000, 600)

        # tokens_saved_report
        savings = bt.tokens_saved_report()
        print(f"  tokens_saved_report: {savings.tokens_saved} tokens saved ({savings.savings_percentage:.1f}%)")

        # success_rate_trend
        trend = bt.success_rate_trend(window_days=365)
        assert 0 <= trend.overall <= 1.0
        print(f"  success_rate_trend: overall={trend.overall:.2f}, categories={len(trend.by_category)}")

        # time_to_solution
        tts = bt.time_to_solution()
        assert "code_generation" in tts
        print(f"  time_to_solution: {tts['code_generation']['mean']:.2f}s avg")

        # auto_optimize
        suggestions = bt.auto_optimize()
        print(f"  auto_optimize: {len(suggestions)} suggestions")

        # dashboard
        dash = bt.dashboard()
        assert "OmniCore Benchmark" in dash
        print(f"  dashboard: {len(dash)} chars")

        # get_recent
        recent = bt.get_recent_tasks(5)
        assert len(recent) <= 5
        print(f"  get_recent_tasks: {len(recent)} returned")

        # clear
        deleted = bt.clear()
        print(f"  clear: {deleted} records deleted")

    finally:
        Path(db_path).unlink(missing_ok=True)

    print("  benchmark: ALL TESTS PASSED")


if __name__ == "__main__":
    _self_test()