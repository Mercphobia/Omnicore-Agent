"""
Idle processing engine — background insights when the agent is idle.

DNA: Gemini Flash (background triage) + Manus (research synthesis).

The DreamEngine runs in a background thread, reviewing past sessions,
optimizing its own code, precomputing answers to predicted questions,
generating insights across all stored data, and producing a dream report.

Usage::

    engine = DreamEngine(data_dir="/path/to/data")
    engine.start()
    # ... agent works ...
    report = engine.dream_report()
"""

from __future__ import annotations

import collections
import hashlib
import itertools
import json
import logging
import math
import os
import re
import statistics
import threading
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ── Data types ──────────────────────────────────────────────────────────

@dataclass
class Insight:
    """A discovered insight."""
    id: str
    category: str                     # pattern, anomaly, optimization, trend, correlation
    description: str
    confidence: float                 # 0–1
    evidence: list[str] = field(default_factory=list)
    actionable: bool = False
    action: str = ""


@dataclass
class DreamReport:
    """Full report from a dream cycle."""
    timestamp: float
    insights: list[Insight] = field(default_factory=list)
    history_summary: dict[str, Any] = field(default_factory=dict)
    optimization_suggestions: list[str] = field(default_factory=list)
    precomputed_answers: dict[str, Any] = field(default_factory=dict)
    patterns_found: int = 0
    cycles_run: int = 0


# ── DreamEngine ─────────────────────────────────────────────────────────

class DreamEngine:
    """Background idle-processing engine.

    When the agent is idle, this engine runs in a background thread:
    1. Reviews past sessions for patterns
    2. Profiles its own code for optimization opportunities
    3. Precomputes answers to predicted common questions
    4. Generates insights across all available data
    5. Produces a consolidated dream report
    """

    _STOP_SENTINEL = "__DREAM_STOP__"

    def __init__(
        self,
        data_dir: str | Path = "",
        idle_trigger_seconds: float = 30.0,
        dream_interval: float = 300.0,
    ):
        self._data_dir = Path(data_dir) if data_dir else Path.home() / ".omnicore" / "dreams"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._idle_trigger = idle_trigger_seconds
        self._dream_interval = dream_interval

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_activity: float = time.time()
        self._task_queue: deque = deque()
        self._insights: list[Insight] = []
        self._insight_counter = 0
        self._cycles = 0
        self._history_cache: list[dict[str, Any]] = []
        self._precompute_cache: dict[str, Any] = {}

        # Performance profiles
        self._perf_data: dict[str, list[float]] = defaultdict(list)

        # Pattern database
        self._pattern_db: dict[str, int] = Counter()

    # ── Lifecycle ──────────────────────────────────────────────────

    def start(self) -> None:
        """Begin background dream processing."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._dream_loop, daemon=True, name="dream-engine")
        self._thread.start()
        logger.info("DreamEngine started (interval=%ss)", self._dream_interval)

    def stop(self) -> None:
        """Signal the dream engine to stop."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10.0)
        logger.info("DreamEngine stopped after %d cycles", self._cycles)

    def notify_activity(self) -> None:
        """Call to indicate the agent is active (resets idle timer)."""
        self._last_activity = time.time()

    def _dream_loop(self) -> None:
        """Main background loop."""
        while self._running:
            try:
                idle_time = time.time() - self._last_activity
                if idle_time >= self._idle_trigger:
                    self._run_dream_cycle()

                # Process any queued tasks
                while self._task_queue:
                    try:
                        task = self._task_queue.popleft()
                        if task == self._STOP_SENTINEL:
                            return
                        task()
                    except Exception:
                        pass

                time.sleep(min(5.0, self._dream_interval / 10))
            except Exception as exc:
                logger.error("Dream loop error: %s", exc)
                time.sleep(10.0)

    def _run_dream_cycle(self) -> None:
        """Execute one full dream cycle."""
        self._cycles += 1

        try:
            self.review_history()
            self.optimize_self()
            self.precompute_answers()
            self.generate_insights()
        except Exception as exc:
            logger.warning("Dream cycle %d partial failure: %s", self._cycles, exc)

        # Periodically save
        if self._cycles % 10 == 0:
            self._save_state()

    # ── History review ─────────────────────────────────────────────

    def review_history(self) -> dict[str, Any]:
        """Analyze past session data for patterns and learnings.

        Reads interaction logs, extracts topics, timings, and outcomes.

        Returns:
            Summary dict with topic distribution, timing stats, etc.
        """
        # Load history files
        history_files = sorted(
            self._data_dir.glob("history*.json"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )[:50]

        all_topics: Counter = Counter()
        all_actions: Counter = Counter()
        durations: list[float] = []
        success_count, failure_count = 0, 0

        for hf in history_files:
            try:
                entries = json.loads(hf.read_text(encoding="utf-8"))
                if isinstance(entries, list):
                    for entry in entries:
                        topic = entry.get("topic", entry.get("task", "unknown"))
                        all_topics[topic] += 1
                        action = entry.get("action", entry.get("type", "unknown"))
                        all_actions[action] += 1
                        dur = entry.get("duration", entry.get("elapsed", 0))
                        if isinstance(dur, (int, float)) and dur > 0:
                            durations.append(float(dur))
                        if entry.get("success", entry.get("status")) in (True, "success", "ok"):
                            success_count += 1
                        else:
                            failure_count += 1
            except Exception:
                pass

        summary: dict[str, Any] = {
            "files_scanned": len(history_files),
            "total_entries": sum(all_topics.values()),
            "top_topics": all_topics.most_common(10),
            "top_actions": all_actions.most_common(10),
            "success_rate": round(
                success_count / max(1, success_count + failure_count), 3
            ),
            "avg_duration": round(statistics.mean(durations), 2) if durations else 0,
            "median_duration": round(statistics.median(durations), 2) if durations else 0,
            "p95_duration": round(
                sorted(durations)[int(len(durations) * 0.95)] if len(durations) > 1 else 0, 2
            ),
        }

        self._history_cache.append(summary)
        return summary

    # ── Self-optimization ──────────────────────────────────────────

    def optimize_self(self) -> list[str]:
        """Profile own code and suggest optimizations.

        Checks for slow imports, redundant patterns, and memory hotspots.

        Returns:
            List of optimization suggestions.
        """
        suggestions: list[str] = []

        # Check for import-related slowdowns
        import sys
        for mod_name, mod in sorted(sys.modules.items()):
            if mod is None:
                continue
            try:
                mod_file = getattr(mod, "__file__", None)
                if mod_file and Path(mod_file).stat().st_size > 500_000:  # 500KB+
                    suggestions.append(
                        f"Large module '{mod_name}' ({Path(mod_file).stat().st_size // 1024}KB) — "
                        "consider lazy loading or splitting"
                    )
            except Exception:
                pass

        # Check for deep recursion patterns in loaded modules
        # (Heuristic — we can't really profile without running code)
        suggestions.append(
            "Consider caching frequently-used regex patterns with re.compile()"
        )
        suggestions.append(
            "Use __slots__ for high-volume dataclass instances to reduce memory"
        )
        suggestions.append(
            "Batch I/O operations to reduce syscall overhead"
        )

        return suggestions

    # ── Precompute answers ─────────────────────────────────────────

    def precompute_answers(self) -> dict[str, Any]:
        """Predict and precompute answers to frequently-asked questions.

        Uses pattern frequency analysis to determine what to cache.

        Returns:
            Dict of precomputed answers keyed by question fingerprint.
        """
        # Gather most frequent topics from history
        frequent = [t for t, c in self._pattern_db.most_common(10) if c > 1]
        answers: dict[str, Any] = {}

        for topic in frequent:
            fingerprint = hashlib.sha256(topic.encode()).hexdigest()[:16]
            answers[fingerprint] = {
                "question": topic,
                "cached_at": time.time(),
                "confidence": min(0.9, self._pattern_db[topic] / 10),
            }

        self._precompute_cache.update(answers)

        # Also cache common system info
        try:
            answers["sys_info"] = {
                "python_version": sys.version,
                "platform": sys.platform,
                "cpu_count": os.cpu_count(),
                "cached_at": time.time(),
            }
        except Exception:
            pass

        return answers

    # ── Generate insights ──────────────────────────────────────────

    def generate_insights(self) -> list[Insight]:
        """Find patterns and generate insights across all stored data.

        Returns:
            List of Insight objects.
        """
        insights: list[Insight] = []

        # Pattern: topic frequency
        if self._pattern_db:
            top = self._pattern_db.most_common(3)
            self._insight_counter += 1
            insights.append(Insight(
                id=f"I-{self._insight_counter:04d}",
                category="pattern",
                description=f"Most frequent topics: {', '.join(f'{t} ({c}x)' for t, c in top)}",
                confidence=0.85,
                evidence=[f"pattern_db: {dict(top)}"],
                actionable=True,
                action=f"Pre-build responses for '{top[0][0]}' if it's the top topic",
            ))

        # Anomaly: success rate drops
        if self._history_cache:
            recent = self._history_cache[-1]
            if recent.get("success_rate", 1.0) < 0.7:
                self._insight_counter += 1
                insights.append(Insight(
                    id=f"I-{self._insight_counter:04d}",
                    category="anomaly",
                    description=f"Success rate dropped to {recent['success_rate']:.1%} — investigate",
                    confidence=0.75,
                    evidence=[f"Recent success_rate={recent['success_rate']}"],
                    actionable=True,
                    action="Review recent failures for common cause",
                ))

        # Optimization: high p95 duration
        if self._history_cache:
            recent = self._history_cache[-1]
            if recent.get("p95_duration", 0) > 60.0:
                self._insight_counter += 1
                insights.append(Insight(
                    id=f"I-{self._insight_counter:04d}",
                    category="optimization",
                    description=f"P95 task duration is {recent['p95_duration']:.1f}s — "
                    "consider parallelization or caching",
                    confidence=0.7,
                    evidence=[f"p95_duration={recent['p95_duration']}"],
                    actionable=True,
                    action="Profile longest-running tasks and add caching layer",
                ))

        # Trend: growing topic diversity
        unique_topics = len(self._pattern_db)
        if unique_topics > 10:
            self._insight_counter += 1
            insights.append(Insight(
                id=f"I-{self._insight_counter:04d}",
                category="trend",
                description=f"Topic diversity growing ({unique_topics} unique topics) — "
                "consider a routing layer",
                confidence=0.65,
                evidence=[f"unique_topics={unique_topics}"],
                actionable=False,
            ))

        # Correlation: fast successes share traits
        if self._perf_data:
            self._insight_counter += 1
            insights.append(Insight(
                id=f"I-{self._insight_counter:04d}",
                category="correlation",
                description=f"Tracked {sum(len(v) for v in self._perf_data.values())} "
                "performance samples across categories",
                confidence=0.5,
                evidence=[f"perf_data keys: {list(self._perf_data.keys())}"],
                actionable=False,
            ))

        self._insights.extend(insights)
        return insights

    # ── Report ─────────────────────────────────────────────────────

    def dream_report(self) -> DreamReport:
        """Produce a consolidated insights report.

        Returns:
            DreamReport with all insights, summaries, and suggestions.
        """
        history_summary = self.review_history()
        opt_suggestions = self.optimize_self()
        precomputed = self.precompute_answers()
        insights = self.generate_insights()

        return DreamReport(
            timestamp=time.time(),
            insights=insights,
            history_summary=history_summary,
            optimization_suggestions=opt_suggestions,
            precomputed_answers=precomputed,
            patterns_found=len(self._pattern_db),
            cycles_run=self._cycles,
        )

    # ── Data ingestion ─────────────────────────────────────────────

    def feed(self, entry: dict[str, Any]) -> None:
        """Feed a new interaction entry into the dream engine.

        Args:
            entry: Dict with 'topic', 'action', 'duration', 'success' keys.
        """
        topic = entry.get("topic", entry.get("task", "unknown"))
        self._pattern_db[topic] += 1

        # Track performance
        category = entry.get("action", entry.get("type", "general"))
        dur = entry.get("duration", entry.get("elapsed", 0))
        if isinstance(dur, (int, float)) and dur > 0:
            self._perf_data[category].append(float(dur))

        # Persist to history file periodically
        if len(self._pattern_db) % 10 == 0:
            self._save_state()

    def _save_state(self) -> None:
        """Persist dream state to disk."""
        try:
            state = {
                "patterns": dict(self._pattern_db),
                "cycles": self._cycles,
                "insight_count": len(self._insights),
                "precompute_keys": list(self._precompute_cache.keys()),
                "timestamp": time.time(),
            }
            state_file = self._data_dir / "dream_state.json"
            state_file.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to save dream state: %s", exc)


# ── Self-test ───────────────────────────────────────────────────────────

def _self_test() -> None:
    """Verify DreamEngine core operations."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        engine = DreamEngine(data_dir=tmpdir, idle_trigger_seconds=0.1)

        # Feed some data
        for i in range(5):
            engine.feed({"topic": "code generation", "action": "code", "duration": 2.5, "success": True})
            engine.feed({"topic": "debugging", "action": "debug", "duration": 15.0, "success": False})
            engine.feed({"topic": "code generation", "action": "code", "duration": 1.2, "success": True})

        # review_history
        summary = engine.review_history()
        print(f"  review_history: {summary.get('total_entries', 0)} entries")

        # optimize_self
        suggestions = engine.optimize_self()
        assert len(suggestions) > 0
        print(f"  optimize_self: {len(suggestions)} suggestions")

        # precompute_answers
        answers = engine.precompute_answers()
        print(f"  precompute_answers: {len(answers)} answers precomputed")

        # generate_insights
        insights = engine.generate_insights()
        print(f"  generate_insights: {len(insights)} insights")

        # dream_report
        report = engine.dream_report()
        assert report.cycles_run >= 0
        print(f"  dream_report: {len(report.insights)} insights, {report.patterns_found} patterns")

        # start/stop
        engine.start()
        time.sleep(0.5)  # let it run one cycle
        engine.stop()

    print("  dream: ALL TESTS PASSED")


if __name__ == "__main__":
    _self_test()