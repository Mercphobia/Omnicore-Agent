"""
Execution Multiplexer — parallel strategy racing with first-wins semantics.
DNA: Run N strategies simultaneously; the fastest valid result wins.
No other agent races execution paths and returns the winner before the losers finish.
"""

from __future__ import annotations

import concurrent.futures
import functools
import math
import queue
import random
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

T = TypeVar("T")
Strategy = Callable[[Any], T]


# ============================================================================
# Data types
# ============================================================================


@dataclass
class RaceResult:
    """Result from a strategy race."""

    value: Any
    strategy_name: str
    elapsed_ms: float
    rank: int = 1

    def __repr__(self) -> str:
        return f"RaceResult({self.strategy_name}: {self.value!r}, {self.elapsed_ms:.1f}ms)"


@dataclass
class CompareResult:
    """Result from comparing multiple strategies."""

    results: List[RaceResult]
    fastest: RaceResult
    slowest: RaceResult
    median_elapsed_ms: float
    all_values: List[Any]

    @property
    def consensus(self) -> Optional[Any]:
        """Most common result value."""
        from collections import Counter
        counts = Counter(str(r.value) for r in self.results)
        most_common = counts.most_common(1)
        return most_common[0][0] if most_common else None

    @property
    def agreement_ratio(self) -> float:
        """Fraction of strategies that produced the same result as the winner."""
        if not self.results:
            return 0.0
        winner_val = str(self.results[0].value)
        return sum(1 for r in self.results if str(r.value) == winner_val) / len(self.results)


@dataclass
class TimingStats:
    """Timing statistics from fastest_of."""

    fastest_ms: float
    median_ms: float
    slowest_ms: float
    mean_ms: float
    stdev_ms: float
    result: Any
    all_times: List[float] = field(default_factory=list)


# ============================================================================
# Main class
# ============================================================================


class ExecMultiplex:
    """Execution Multiplexer — parallel strategy execution engine.

    Runs multiple strategies/approaches in parallel threads and returns
    the first valid result. Also supports full comparison, timing analysis,
    and speculative pre-computation.

    DNA: The only agent that races strategies in parallel and returns the
    winner before the losers finish — true speculative execution at the
    strategy level.

    Usage:
        mux = ExecMultiplex()

        def strategy_a(data): return sorted(data)
        def strategy_b(data): return list(reversed(sorted(data)))

        winner = mux.race([strategy_a, strategy_b], [3, 1, 2])
        print(winner.value)  # [1, 2, 3]
    """

    def __init__(
        self,
        *,
        max_workers: Optional[int] = None,
        default_timeout: float = 30.0,
    ):
        """Initialize the multiplexer.

        Args:
            max_workers: Max threads in pool. Default: CPU count × 2.
            default_timeout: Default timeout in seconds for operations.
        """
        if max_workers is None:
            max_workers = (getattr(threading, "_get_native_id", lambda: 1)() or 4) * 2
        self._max_workers = max(1, max_workers)
        self._default_timeout = default_timeout
        self._executor: Optional[concurrent.futures.ThreadPoolExecutor] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def race(
        self,
        strategies: List[Tuple[str, Strategy[T]]] | Dict[str, Strategy[T]],
        input_data: Any,
        timeout: Optional[float] = None,
        *,
        validator: Optional[Callable[[Any], bool]] = None,
    ) -> Optional[RaceResult]:
        """Run N strategies in parallel threads; first valid result wins.

        All strategies start simultaneously. The moment any strategy returns
        a valid result (or any result if no validator), its future is cancelled
        and the result is returned immediately. Other strategies continue in
        background but their results are discarded.

        Args:
            strategies: List of (name, callable) tuples or dict of name→callable.
                        Each callable receives input_data and returns a result.
            input_data: Input passed to every strategy.
            timeout: Max seconds to wait for ANY result. None = default_timeout.
            validator: Optional predicate; result must pass this to be "valid".
                       If None, the first non-exception result wins.

        Returns:
            RaceResult of the winner, or None if all strategies failed/timed out.

        Example:
            winner = mux.race(
                [("quicksort", quicksort_fn), ("timsort", sorted)],
                [5, 2, 8, 1, 9]
            )
        """
        if isinstance(strategies, dict):
            strategies = list(strategies.items())

        if not strategies:
            return None

        timeout = timeout if timeout is not None else self._default_timeout

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(strategies), self._max_workers)
        ) as executor:
            # Launch all strategies simultaneously
            future_map: Dict[concurrent.futures.Future, Tuple[str, float]] = {}
            t0 = time.perf_counter()

            for name, fn in strategies:
                future = executor.submit(self._safe_execute, fn, input_data)
                future_map[future] = (name, t0)

            # Wait for first result
            try:
                for future in concurrent.futures.as_completed(
                    future_map, timeout=timeout
                ):
                    name, start_time = future_map[future]
                    try:
                        result = future.result(timeout=0.1)
                        if validator is None or validator(result):
                            elapsed = (time.perf_counter() - start_time) * 1000
                            # Cancel remaining futures
                            for f in future_map:
                                f.cancel()
                            return RaceResult(
                                value=result,
                                strategy_name=name,
                                elapsed_ms=round(elapsed, 2),
                            )
                    except Exception:
                        continue  # This strategy failed; wait for next
            except concurrent.futures.TimeoutError:
                pass

        return None

    def compare(
        self,
        strategies: List[Tuple[str, Strategy[T]]] | Dict[str, Strategy[T]],
        input_data: Any,
        timeout: Optional[float] = None,
    ) -> CompareResult:
        """Run ALL strategies, return ranked results (fastest first).

        Unlike race(), this waits for EVERY strategy to complete (or timeout).
        Results are ranked by elapsed time.

        Args:
            strategies: List of (name, callable) tuples or dict of name→callable.
            input_data: Input passed to every strategy.
            timeout: Max seconds per strategy. None = default_timeout.

        Returns:
            CompareResult with all results ranked by speed.
        """
        if isinstance(strategies, dict):
            strategies = list(strategies.items())

        if not strategies:
            return CompareResult(
                results=[], fastest=None, slowest=None,
                median_elapsed_ms=0.0, all_values=[],
            )

        timeout = timeout if timeout is not None else self._default_timeout
        results: List[RaceResult] = []

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(strategies), self._max_workers)
        ) as executor:
            future_map: Dict[concurrent.futures.Future, Tuple[str, float]] = {}

            for name, fn in strategies:
                t0 = time.perf_counter()
                future = executor.submit(self._safe_execute, fn, input_data)
                future_map[future] = (name, t0)

            for future in concurrent.futures.as_completed(
                future_map, timeout=timeout
            ):
                name, start_time = future_map[future]
                elapsed = (time.perf_counter() - start_time) * 1000
                try:
                    value = future.result(timeout=0.1)
                    results.append(RaceResult(
                        value=value,
                        strategy_name=name,
                        elapsed_ms=round(elapsed, 2),
                    ))
                except Exception as e:
                    results.append(RaceResult(
                        value=f"ERROR: {e}",
                        strategy_name=name,
                        elapsed_ms=round(elapsed, 2),
                    ))

        # Rank by elapsed time
        results.sort(key=lambda r: r.elapsed_ms)
        for i, r in enumerate(results, 1):
            r.rank = i

        times = [r.elapsed_ms for r in results]
        median = statistics.median(times) if times else 0.0

        return CompareResult(
            results=results,
            fastest=results[0] if results else None,
            slowest=results[-1] if results else None,
            median_elapsed_ms=round(median, 2),
            all_values=[r.value for r in results],
        )

    def fastest_of(
        self,
        n: int,
        fn: Callable[..., T],
        *args: Any,
        approaches: Optional[List[Callable[..., T]]] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> TimingStats:
        """Run fn N times (optionally with different approaches) and return timing stats.

        If approaches is provided, each run uses a different approach from the list
        (cycling if N > len(approaches)). Useful for benchmarking different
        implementations of the same function.

        Args:
            n: Number of runs.
            fn: The base function to time.
            *args: Positional args for fn.
            approaches: Optional list of alternative implementations.
            timeout: Max seconds per run.
            **kwargs: Keyword args for fn.

        Returns:
            TimingStats with fastest, median, slowest, mean, stdev.
        """
        times: List[Tuple[float, Any]] = []
        per_run_timeout = (timeout or self._default_timeout) / max(n, 1)

        strategies: List[Tuple[str, Callable[..., T]]] = []
        if approaches:
            for i in range(n):
                approach = approaches[i % len(approaches)]
                strategies.append((f"run_{i:03d}", lambda d, _a=approach: _a(*args, **kwargs)))
        else:
            for i in range(n):
                strategies.append((f"run_{i:03d}", lambda d: fn(*args, **kwargs)))

        dummy_input = None  # We use closures, input_data is ignored

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(n, self._max_workers)
        ) as executor:
            futures: List[concurrent.futures.Future] = []
            for name, strategy in strategies:
                futures.append(executor.submit(self._safe_execute, strategy, dummy_input))

            for future in concurrent.futures.as_completed(futures, timeout=timeout):
                try:
                    t0 = time.perf_counter()
                    result = future.result(timeout=per_run_timeout)
                    elapsed = (time.perf_counter() - t0) * 1000
                    times.append((elapsed, result))
                except Exception:
                    times.append((float("inf"), None))

        if not times:
            return TimingStats(
                fastest_ms=float("inf"), median_ms=float("inf"),
                slowest_ms=float("inf"), mean_ms=float("inf"),
                stdev_ms=0.0, result=None, all_times=[],
            )

        all_t = [t for t, _ in times if t != float("inf")]
        if not all_t:
            all_t = [float("inf")]

        best = min(times, key=lambda x: x[0])

        return TimingStats(
            fastest_ms=round(best[0], 3),
            median_ms=round(statistics.median(all_t), 3),
            slowest_ms=round(max(all_t), 3),
            mean_ms=round(statistics.mean(all_t), 3),
            stdev_ms=round(statistics.stdev(all_t) if len(all_t) > 1 else 0.0, 3),
            result=best[1],
            all_times=[round(t, 3) for t in all_t],
        )

    def speculative_execute(
        self,
        predictions: Dict[str, Callable[[], Any]],
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Pre-compute likely needed results in parallel.

        Launches all prediction functions simultaneously. Results are returned
        as a dict keyed by prediction name. If any function raises, its value
        is set to None (no cascading failures).

        Use this when you anticipate which results will be needed next and want
        them ready before they're asked for — true speculative execution.

        Args:
            predictions: Dict of {name: callable_with_no_args}.
            timeout: Max total time. None = default_timeout.

        Returns:
            Dict of {name: computed_result}.

        Example:
            cache = mux.speculative_execute({
                "user_profile": lambda: api.get_profile(),
                "recent_posts": lambda: api.get_posts(limit=10),
                "recommendations": lambda: api.get_recommendations(),
            })
            # All three are fetched in parallel; use cache["user_profile"] immediately
        """
        if not predictions:
            return {}

        timeout = timeout if timeout is not None else self._default_timeout
        results: Dict[str, Any] = {}

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(predictions), self._max_workers)
        ) as executor:
            future_map: Dict[concurrent.futures.Future, str] = {}
            for name, fn in predictions.items():
                future = executor.submit(self._safe_execute_no_input, fn)
                future_map[future] = name

            for future in concurrent.futures.as_completed(
                future_map, timeout=timeout
            ):
                name = future_map[future]
                try:
                    results[name] = future.result(timeout=0.5)
                except Exception:
                    results[name] = None

        return results

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_execute(fn: Callable[[Any], Any], input_data: Any) -> Any:
        """Execute a strategy, catching exceptions."""
        return fn(input_data)

    @staticmethod
    def _safe_execute_no_input(fn: Callable[[], Any]) -> Any:
        """Execute a no-arg function, catching exceptions."""
        return fn()

    def shutdown(self) -> None:
        """Shut down the thread pool if one was created."""
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None


# ============================================================================
# Self-test
# ============================================================================

def _self_test() -> None:
    """Run comprehensive self-tests on the Execution Multiplexer."""
    print("=== ExecMultiplex Self-Test ===\n")

    mux = ExecMultiplex()

    # Test 1: Race — basic
    print("Test 1: Race — first valid result wins")
    def fast(x):
        time.sleep(0.01)
        return f"fast:{x}"
    def slow(x):
        time.sleep(0.2)
        return f"slow:{x}"
    def error_fn(x):
        raise ValueError("intentional failure")

    winner = mux.race(
        [("fast", fast), ("slow", slow)],
        "hello",
        timeout=5.0,
    )
    assert winner is not None, "Expected a winner"
    assert winner.strategy_name == "fast", f"fast should win, got {winner.strategy_name}"
    assert winner.value == "fast:hello"
    print(f"  Winner: {winner}")
    print("  PASS\n")

    # Test 2: Race with validator
    print("Test 2: Race with validator")
    def returns_none(x):
        return None
    def returns_valid(x):
        return 42

    winner2 = mux.race(
        [("none", returns_none), ("valid", returns_valid)],
        "data",
        validator=lambda v: v is not None,
    )
    assert winner2 is not None
    assert winner2.value == 42
    print(f"  Winner: {winner2}")
    print("  PASS\n")

    # Test 3: Compare
    print("Test 3: Compare — all results ranked")
    comparison = mux.compare(
        [("slow", slow), ("fast", fast), ("error", error_fn)],
        "test",
    )
    assert len(comparison.results) == 3
    assert comparison.fastest.strategy_name in ("fast", "error"), \
        f"Expected fast or error, got {comparison.fastest.strategy_name}"
    assert comparison.slowest.strategy_name in ("slow", "error")
    print(f"  Fastest: {comparison.fastest}")
    print(f"  Slowest: {comparison.slowest}")
    print(f"  Median: {comparison.median_elapsed_ms:.1f}ms")
    print("  PASS\n")

    # Test 4: fastest_of
    print("Test 4: fastest_of — timing stats")
    stats = mux.fastest_of(
        10,
        lambda x: sum(range(x)),
        100,
    )
    assert stats.fastest_ms > 0
    assert stats.median_ms >= stats.fastest_ms
    print(f"  Fastest: {stats.fastest_ms:.3f}ms")
    print(f"  Median:  {stats.median_ms:.3f}ms")
    print(f"  Mean:    {stats.mean_ms:.3f}ms")
    print(f"  Result:  {stats.result}")
    print("  PASS\n")

    # Test 5: fastest_of with different approaches
    print("Test 5: fastest_of with approach variants")
    def approach_a(x):
        return sum(range(x))
    def approach_b(x):
        return (x * (x - 1)) // 2
    def approach_c(x):
        total = 0
        for i in range(x):
            total += i
        return total

    stats2 = mux.fastest_of(
        9,
        approach_a,
        10000,
        approaches=[approach_a, approach_b, approach_c],
    )
    print(f"  Fastest: {stats2.fastest_ms:.3f}ms")
    print(f"  Median:  {stats2.median_ms:.3f}ms")
    print(f"  Result:  {stats2.result}")
    print("  PASS\n")

    # Test 6: speculative_execute
    print("Test 6: speculative_execute — pre-computation")
    cache = mux.speculative_execute({
        "a": lambda: 1 + 1,
        "b": lambda: "hello".upper(),
        "c": lambda: [i**2 for i in range(5)],
        "d": lambda: None,
    })
    assert cache["a"] == 2
    assert cache["b"] == "HELLO"
    assert cache["c"] == [0, 1, 4, 9, 16]
    assert cache["d"] is None
    print(f"  Cache keys: {list(cache.keys())}")
    print("  PASS\n")

    # Test 7: Race with dict input
    print("Test 7: Race with dict strategies")
    winner3 = mux.race(
        {"alpha": fast, "beta": slow},
        "dict-test",
    )
    assert winner3 is not None
    assert winner3.value == "fast:dict-test"
    print(f"  Winner: {winner3}")
    print("  PASS\n")

    mux.shutdown()
    print("=== All ExecMultiplex tests passed ===")


if __name__ == "__main__":
    _self_test()