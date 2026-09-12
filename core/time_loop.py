"""Time-Loop Oracle — Groundhog Day problem solving through iterative learning.

DNA: reinforcement learning (explore/exploit) + backtracking search +
     Groundhog Day principle (every failure maps the solution space).

The TimeLoop treats every attempt as a data point. Each failure is not wasted —
it narrows what doesn't work. Like the movie Groundhog Day, you relive the
problem until you master it. Unlike brute force, each iteration LEARNS from
the last and adjusts strategy.

Usage::

    loop = TimeLoop(max_attempts=5)
    result = loop.solve(lambda: risky_operation(), max_attempts=5)
    if result.success:
        print(f"Solved in {result.attempts_needed} attempts")
    else:
        print(f"Best partial result: {loop.best_attempt().output}")
"""

from __future__ import annotations

import copy
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")

# ── Data types ──────────────────────────────────────────────────────────


@dataclass
class Attempt:
    """One attempt in the time-loop trajectory."""

    attempt_number: int
    strategy: str  # description of approach used
    input_params: dict[str, Any] = field(default_factory=dict)
    output: Any = None
    success: bool = False
    error: Optional[str] = None
    error_type: str = ""  # CRASH, WRONG_OUTPUT, TIMEOUT, PARTIAL, NO_PROGRESS
    lesson: str = ""  # extracted lesson from this attempt
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Lesson:
    """A lesson extracted from a failed attempt."""

    attempt_number: int
    what_went_wrong: str  # symptom-level description
    why_it_failed: str  # root cause
    fix_applied: str  # what was changed for next attempt
    constraint_discovered: str  # new information about the solution space
    confidence: float = 1.0  # how sure we are about this lesson


@dataclass
class SolveResult:
    """Complete result from a time-loop solve operation."""

    success: bool
    final_output: Any = None
    attempts_needed: int = 0
    total_duration_ms: float = 0.0
    trajectory: list[Attempt] = field(default_factory=list)
    lessons_learned: list[Lesson] = field(default_factory=list)
    convergence: str = "unknown"  # CONVERGED, DIVERGED, OSCILLATING, TRUNCATED
    best_attempt_idx: int = -1


@dataclass
class ConvergenceReport:
    """Analysis of whether attempts are converging."""

    trend: str  # CONVERGING, DIVERGING, OSCILLATING, STUCK, FIRST_ATTEMPT
    confidence: float
    slope: float  # positive = improving, negative = degrading
    recommendation: str
    detail: str


# ── Strategy generation ─────────────────────────────────────────────────

def _default_strategies() -> list[str]:
    """Generate default strategy palette for problem-solving."""
    return [
        "direct_approach",
        "decompose_and_conquer",
        "analogy_transfer",
        "constraint_relaxation",
        "working_backwards",
        "simplify_then_extend",
        "random_restart",
        "ensemble_hybrid",
        "metaphor_inspired",
        "first_principles",
    ]


# ── Core engine ─────────────────────────────────────────────────────────


class TimeLoop:
    """Groundhog Day problem solver — iterate, fail, learn, converge.

    The TimeLoop treats every attempt as a data point mapping the solution
    space. Each failure narrows what doesn't work. The loop continues until
    success or max_attempts, extracting lessons and adjusting strategy
    after each iteration.

    Parameters:
        max_attempts: Default maximum attempts before giving up.
        strategies: Custom strategy list. If None, uses default palette.
        record_trajectory: Whether to keep full attempt history.
    """

    def __init__(
        self,
        max_attempts: int = 5,
        strategies: Optional[list[str]] = None,
        record_trajectory: bool = True,
    ) -> None:
        self.max_attempts = max(1, max_attempts)
        self.strategies = strategies or _default_strategies()
        self.record_trajectory = record_trajectory

        # Internal state per solve run
        self._attempts: list[Attempt] = []
        self._lessons: list[Lesson] = []
        self._constraints: set[str] = set()

    # ── Public API ──────────────────────────────────────────────────

    def solve(
        self,
        problem: Callable[..., T],
        max_attempts: Optional[int] = None,
        *,
        strategy_hint: str = "",
        timeout_per_attempt_ms: float = 0.0,
        **problem_kwargs: Any,
    ) -> SolveResult:
        """Solve a problem by iterating through attempts, learning from failure.

        Args:
            problem: A callable that takes **kwargs and returns a result.
                     Raise an exception on failure, or return a falsy value
                     if your convention uses return codes.
            max_attempts: Override the instance default.
            strategy_hint: Preferred initial strategy name.
            timeout_per_attempt_ms: Per-attempt timeout (0=disabled).
            **problem_kwargs: Forwarded to the problem callable.

        Returns:
            SolveResult with full trajectory, lessons, and convergence analysis.
        """
        self._attempts = []
        self._lessons = []
        self._constraints = set()

        limit = max_attempts or self.max_attempts
        strategy_idx = 0
        if strategy_hint and strategy_hint in self.strategies:
            strategy_idx = self.strategies.index(strategy_hint)

        start_time = time.perf_counter()

        for i in range(limit):
            strategy = self.strategies[strategy_idx % len(self.strategies)]

            attempt = Attempt(
                attempt_number=i + 1,
                strategy=strategy,
                input_params=dict(problem_kwargs),
            )

            t0 = time.perf_counter()
            try:
                result = problem(**problem_kwargs)
                attempt.output = result
                attempt.duration_ms = (time.perf_counter() - t0) * 1000.0

                # Success check: truthy return = success by default
                if result:
                    attempt.success = True
                    self._attempts.append(attempt)
                    total_ms = (time.perf_counter() - start_time) * 1000.0
                    return SolveResult(
                        success=True,
                        final_output=result,
                        attempts_needed=i + 1,
                        total_duration_ms=total_ms,
                        trajectory=list(self._attempts),
                        lessons_learned=list(self._lessons),
                        convergence=self.converge_check(list(self._attempts)).trend,
                        best_attempt_idx=i,
                    )
                else:
                    attempt.error_type = "WRONG_OUTPUT"
                    attempt.error = "Returned falsy/invalid result"

            except TimeoutError:
                attempt.error_type = "TIMEOUT"
                attempt.error = f"Timed out after {timeout_per_attempt_ms}ms"
                attempt.duration_ms = timeout_per_attempt_ms
            except Exception as exc:
                attempt.error_type = "CRASH"
                attempt.error = f"{type(exc).__name__}: {exc}"
                attempt.duration_ms = (time.perf_counter() - t0) * 1000.0

            # Extract and apply lesson
            lesson = self.extract_lesson(attempt)
            self._lessons.append(lesson)
            attempt.lesson = lesson.fix_applied
            self._attempts.append(attempt)

            # Apply lesson: modify kwargs for next attempt
            problem_kwargs = self.apply_lesson(lesson, problem_kwargs)

            # Rotate strategy on failure
            strategy_idx += 1

        total_ms = (time.perf_counter() - start_time) * 1000.0
        best_idx, _ = self._find_best()

        return SolveResult(
            success=False,
            attempts_needed=limit,
            total_duration_ms=total_ms,
            trajectory=list(self._attempts),
            lessons_learned=list(self._lessons),
            convergence=self.converge_check(list(self._attempts)).trend,
            best_attempt_idx=best_idx,
        )

    def extract_lesson(self, failure: Attempt) -> Lesson:
        """Extract a lesson from a failed attempt — what went wrong and why.

        Args:
            failure: The failed Attempt to analyze.

        Returns:
            A Lesson with root cause analysis and suggested fix.
        """
        what = failure.error or "Unknown failure"
        error_type = failure.error_type

        # Pattern-based root cause analysis
        cause_map = {
            "CRASH": self._analyze_crash,
            "WRONG_OUTPUT": self._analyze_wrong_output,
            "TIMEOUT": self._analyze_timeout,
            "NO_PROGRESS": self._analyze_no_progress,
        }

        analyzer = cause_map.get(error_type, self._analyze_generic)
        why, fix, constraint = analyzer(failure)

        return Lesson(
            attempt_number=failure.attempt_number,
            what_went_wrong=what,
            why_it_failed=why,
            fix_applied=fix,
            constraint_discovered=constraint,
            confidence=self._lesson_confidence(failure),
        )

    def apply_lesson(
        self, lesson: Lesson, next_params: dict[str, Any]
    ) -> dict[str, Any]:
        """Modify problem parameters based on the extracted lesson.

        Args:
            lesson: The Lesson to apply.
            next_params: Current parameter dict (modified in place copy).

        Returns:
            Modified parameter dict for next attempt.
        """
        params = copy.deepcopy(next_params)
        self._constraints.add(lesson.constraint_discovered)

        # Add constraint metadata so the problem fn can adapt
        if "_time_loop_constraints" not in params:
            params["_time_loop_constraints"] = list(self._constraints)
        else:
            params["_time_loop_constraints"] = list(self._constraints)

        # Apply strategy rotation
        if "_time_loop_strategy" not in params:
            params["_time_loop_strategy"] = self.strategies[lesson.attempt_number % len(self.strategies)]

        # Signal the lesson to the problem callable
        params["_time_loop_lesson"] = lesson.fix_applied
        params["_time_loop_attempt"] = lesson.attempt_number + 1

        return params

    def trajectory(self) -> list[dict[str, Any]]:
        """Return full attempt history with lessons as a serializable list.

        Returns:
            List of dicts, one per attempt, with all fields.
        """
        return [
            {
                "attempt": a.attempt_number,
                "strategy": a.strategy,
                "success": a.success,
                "error_type": a.error_type,
                "error": a.error,
                "lesson": a.lesson,
                "duration_ms": round(a.duration_ms, 2),
                "output_summary": str(a.output)[:200] if a.output else None,
            }
            for a in self._attempts
        ]

    def converge_check(self, attempts: Optional[list[Attempt]] = None) -> ConvergenceReport:
        """Detect if attempts are converging toward a solution or diverging.

        Args:
            attempts: List of Attempts to analyze (uses internal if None).

        Returns:
            ConvergenceReport with trend, confidence, and recommendation.
        """
        atts = attempts if attempts is not None else self._attempts
        if not atts:
            return ConvergenceReport(
                trend="NO_DATA",
                confidence=0.0,
                slope=0.0,
                recommendation="No attempts recorded yet.",
                detail="",
            )

        if len(atts) == 1:
            return ConvergenceReport(
                trend="FIRST_ATTEMPT",
                confidence=0.3,
                slope=0.0,
                recommendation="Need at least 2 attempts to assess convergence.",
                detail="Single data point — no trend detectable.",
            )

        # Score each attempt: success=1.0, partial based on error type
        scores = [self._attempt_score(a) for a in atts]

        # Linear regression on attempt number vs score
        n = len(scores)
        xs = list(range(1, n + 1))
        mean_x = sum(xs) / n
        mean_y = sum(scores) / n

        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, scores))
        den = sum((x - mean_x) ** 2 for x in xs)

        if abs(den) < 1e-10:
            slope = 0.0
        else:
            slope = num / den

        # Classify the trend
        if slope > 0.05:
            trend = "CONVERGING"
            rec = "Approaching solution — continue current strategy direction."
        elif slope < -0.05:
            trend = "DIVERGING"
            rec = "Getting worse — hard pivot to a different strategy family."
        elif self._detect_oscillation(scores):
            trend = "OSCILLATING"
            rec = "Oscillating between states — try hybrid/ensemble approach."
        else:
            trend = "STUCK"
            rec = "No meaningful progress — try constraint relaxation or random restart."

        confidence = min(abs(slope) * 10, 0.95) if trend != "STUCK" else 0.6

        return ConvergenceReport(
            trend=trend,
            confidence=round(confidence, 3),
            slope=round(slope, 4),
            recommendation=rec,
            detail=f"Score trend over {n} attempts: slope={slope:.4f}, scores={[round(s,2) for s in scores]}",
        )

    def best_attempt(self) -> Optional[Attempt]:
        """Return the best attempt even if none succeeded.

        Returns:
            The Attempt with the highest internal score, or None if no attempts.
        """
        idx, attempt = self._find_best()
        return attempt

    # ── Internal helpers ────────────────────────────────────────────

    def _find_best(self) -> tuple[int, Optional[Attempt]]:
        """Find the best attempt by internal scoring."""
        if not self._attempts:
            return -1, None

        best_idx = 0
        best_score = self._attempt_score(self._attempts[0])

        for i, a in enumerate(self._attempts):
            score = self._attempt_score(a)
            if score > best_score:
                best_score = score
                best_idx = i

        return best_idx, self._attempts[best_idx]

    def _attempt_score(self, a: Attempt) -> float:
        """Score an attempt: success=1.0, then degraded by error severity."""
        if a.success:
            return 1.0

        error_weights = {
            "CRASH": 0.1,
            "WRONG_OUTPUT": 0.3,
            "TIMEOUT": 0.2,
            "PARTIAL": 0.5,
            "NO_PROGRESS": 0.0,
        }
        base = error_weights.get(a.error_type, 0.15)

        # Bonus: faster attempts score slightly higher (we prefer efficiency)
        if a.duration_ms > 0:
            speed_bonus = max(0, 0.1 * (1 - min(a.duration_ms / 10000, 1.0)))
        else:
            speed_bonus = 0.0

        return min(base + speed_bonus, 0.99)

    def _analyze_crash(self, failure: Attempt) -> tuple[str, str, str]:
        err = failure.error or ""
        if "AttributeError" in err:
            return (
                "Called method/attribute that doesn't exist",
                "Add existence check before attribute access",
                f"No attribute: {err.split('AttributeError:')[-1].strip() if 'AttributeError:' in err else err}",
            )
        elif "KeyError" in err:
            return (
                "Accessed missing dictionary key",
                "Use .get() with default or check 'in' before access",
                f"Missing key in data: {err.split('KeyError:')[-1].strip() if 'KeyError:' in err else err}",
            )
        elif "ValueError" in err:
            return (
                "Invalid value passed to operation",
                "Add input validation before processing",
                f"Invalid value constraint: {err.split('ValueError:')[-1].strip() if 'ValueError:' in err else err}",
            )
        elif "TypeError" in err:
            return (
                "Wrong type passed to function/operation",
                "Add type checking or conversion",
                f"Type constraint violated: {err.split('TypeError:')[-1].strip() if 'TypeError:' in err else err}",
            )
        elif "IndexError" in err or "list index" in err.lower():
            return (
                "Index out of bounds",
                "Check length before indexing",
                "Collection length constraint needed",
            )
        elif "ZeroDivisionError" in err:
            return (
                "Division by zero",
                "Guard against zero denominator",
                "Non-zero denominator constraint",
            )
        elif "FileNotFoundError" in err:
            return (
                "Required file doesn't exist",
                "Check file existence, provide fallback path",
                f"File must exist: {err.split('FileNotFoundError:')[-1].strip() if 'FileNotFoundError:' in err else err}",
            )
        elif "ImportError" in err or "ModuleNotFoundError" in err:
            return (
                "Missing dependency/import",
                "Check import availability, provide fallback",
                f"Dependency required: {err.split('Error:')[-1].strip() if 'Error:' in err else err}",
            )
        else:
            return (
                f"Unexpected crash: {err[:100]}",
                "Add broader exception handling and logging",
                f"Unknown constraint triggered: {err[:80]}",
            )

    def _analyze_wrong_output(self, failure: Attempt) -> tuple[str, str, str]:
        return (
            "Output was incorrect or unexpected",
            "Verify assumptions, add output validation, try alternative algorithm",
            f"Current approach '{failure.strategy}' produces wrong output",
        )

    def _analyze_timeout(self, failure: Attempt) -> tuple[str, str, str]:
        return (
            "Operation exceeded time limit",
            "Add timeout, optimize algorithm, or use approximation",
            f"Time constraint: operation too slow with strategy '{failure.strategy}'",
        )

    def _analyze_no_progress(self, failure: Attempt) -> tuple[str, str, str]:
        return (
            "No progress — can't execute at all",
            "Identify blocker (missing dependency, permission, env)",
            f"Environment constraint: can't execute with '{failure.strategy}'",
        )

    def _analyze_generic(self, failure: Attempt) -> tuple[str, str, str]:
        return (
            str(failure.error)[:200],
            "Try different strategy or decompose problem",
            f"Generic failure under strategy '{failure.strategy}'",
        )

    def _lesson_confidence(self, failure: Attempt) -> float:
        """Estimate confidence in the extracted lesson."""
        confidence_map = {
            "CRASH": 0.95,
            "WRONG_OUTPUT": 0.7,
            "TIMEOUT": 0.85,
            "PARTIAL": 0.6,
            "NO_PROGRESS": 0.8,
        }
        return confidence_map.get(failure.error_type, 0.5)

    def _detect_oscillation(self, scores: list[float]) -> bool:
        """Detect if scores are oscillating up/down/up/down."""
        if len(scores) < 4:
            return False

        direction_changes = 0
        prev_dir = 0
        for i in range(1, len(scores)):
            diff = scores[i] - scores[i - 1]
            cur_dir = 1 if diff > 0.01 else (-1 if diff < -0.01 else 0)
            if cur_dir != 0 and prev_dir != 0 and cur_dir != prev_dir:
                direction_changes += 1
            if cur_dir != 0:
                prev_dir = cur_dir

        return direction_changes >= 2


# ── Self-test ────────────────────────────────────────────────────────────

def _self_test() -> None:
    """Verify TimeLoop with simple converging problems."""
    import sys

    loop = TimeLoop(max_attempts=15)

    # Problem 1: Simple counter that succeeds after N iterations
    state = {"count": 0}

    def counting_problem(target: int = 5, **kwargs: Any) -> int:
        state["count"] += 1
        if state["count"] >= target:
            return state["count"]
        return 0  # falsy = failure

    result = loop.solve(counting_problem, max_attempts=10, target=3)
    assert result.success, f"Expected success, got success={result.success}, attempts={result.attempts_needed}"
    assert result.attempts_needed >= 2, f"Should need at least 2 attempts, got {result.attempts_needed}"
    assert len(result.trajectory) == result.attempts_needed
    assert len(result.lessons_learned) > 0, f"Should have lessons from failures, got {len(result.lessons_learned)}"

    # Test convergence check
    conv = loop.converge_check()
    assert conv.trend in ("CONVERGING", "STUCK", "DIVERGING", "OSCILLATING", "FIRST_ATTEMPT", "NO_DATA"), f"Unexpected trend: {conv.trend}"

    # Test best_attempt
    best = loop.best_attempt()
    assert best is not None

    # Test trajectory serialization
    traj = loop.trajectory()
    assert isinstance(traj, list)
    assert all(isinstance(t, dict) for t in traj)

    # Test with immediate success
    result3 = loop.solve(lambda **kw: 42, max_attempts=3)
    assert result3.success
    assert result3.attempts_needed == 1

    # Test with permanent failure
    def always_crash(**kw: Any) -> int:
        raise RuntimeError("permanent failure")

    result2 = loop.solve(always_crash, max_attempts=3)
    assert not result2.success
    assert result2.attempts_needed == 3
    assert loop.best_attempt() is not None  # even failures have a "best"

    print("TimeLoop: all self-tests passed ✓")


if __name__ == "__main__":
    _self_test()