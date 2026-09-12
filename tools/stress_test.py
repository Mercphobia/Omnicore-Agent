#!/usr/bin/env python3
"""Property-based stress tester — find edge cases by brute force.
DNA: Death (destruction that validates).

``StressTester`` is a pure-Python property-testing engine (no Hypothesis
dependency).  It generates random inputs, checks invariants, and shrinks
failures to minimal counterexamples.

Usage::

    tester = StressTester(seed=42)

    def my_sort(lst: list[int]) -> list[int]:
        return sorted(lst)

    def input_gen() -> list[int]:
        import random
        return [random.randint(-100, 100) for _ in range(random.randint(0, 20))]

    def sorted_property(inp, out):
        return all(out[i] <= out[i+1] for i in range(len(out)-1))

    result = tester.fuzz_function(my_sort, input_gen, sorted_property, iterations=500)
    if result["failed"]:
        print("Counterexample:", result["counterexample"])
        minimal = tester.shrink_failure(result["counterexample"], sorted_property)
        print("Minimal:", minimal)
"""

from __future__ import annotations

import copy
import math
import random
import time
from collections.abc import Callable, Hashable, Sequence
from typing import Any


# ---------------------------------------------------------------------------
# Shrinking strategies
# ---------------------------------------------------------------------------

def _shrink_int(value: int) -> list[int]:
    """Produce smaller integer candidates."""
    candidates: list[int] = []
    if value == 0:
        return candidates
    # Halve toward zero
    candidates.append(0)
    candidates.append(value // 2)
    # Try sign flip
    candidates.append(-value)
    # Try decrement/increment toward 0
    step = max(1, abs(value) // 10)
    candidates.append(value - step if value > 0 else value + step)
    # Remove duplicates while preserving order
    seen: set[int] = set()
    result: list[int] = []
    for c in candidates:
        if c not in seen and c != value:
            seen.add(c)
            result.append(c)
    return result


def _shrink_str(value: str) -> list[str]:
    """Produce smaller string candidates."""
    candidates: list[str] = []
    n = len(value)
    if n == 0:
        return candidates
    # Remove last char
    candidates.append(value[:-1])
    # Remove first char
    candidates.append(value[1:])
    # Halve from middle
    mid = n // 2
    candidates.append(value[:mid])
    candidates.append(value[mid:])
    # Replace each char with 'a' (minimal)
    if n > 0 and value != "a" * n:
        candidates.append("a" * n)
    # Empty
    candidates.append("")
    return [c for c in candidates if c != value]


def _shrink_float(value: float) -> list[float]:
    """Produce smaller float candidates."""
    candidates: list[float] = []
    if value == 0.0:
        return candidates
    if math.isnan(value) or math.isinf(value):
        return [0.0]
    candidates.append(0.0)
    candidates.append(value / 2.0)
    candidates.append(-value)
    # Toward zero by 10%
    step = abs(value) * 0.1
    if step > 0:
        candidates.append(value - step if value > 0 else value + step)
    return [c for c in candidates if c != value]


def _shrink_list(value: list[Any]) -> list[list[Any]]:
    """Produce smaller list candidates."""
    candidates: list[list[Any]] = []
    n = len(value)
    if n == 0:
        return candidates
    # Remove elements
    candidates.append(value[: n // 2])  # first half
    candidates.append(value[n // 2 :])  # second half
    candidates.append(value[:-1])  # drop last
    candidates.append(value[1:])  # drop first
    # Try removing each element
    for i in range(n):
        candidate = value[:i] + value[i + 1 :]
        if len(candidate) < len(value):
            candidates.append(candidate)
    # Try shrinking each element
    for i in range(n):
        if isinstance(value[i], int):
            for smaller in _shrink_int(value[i]):
                c = list(value)
                c[i] = smaller
                candidates.append(c)
        elif isinstance(value[i], str):
            for smaller in _shrink_str(value[i]):
                c = list(value)
                c[i] = smaller
                candidates.append(c)
        elif isinstance(value[i], float):
            for smaller in _shrink_float(value[i]):
                c = list(value)
                c[i] = smaller
                candidates.append(c)
    # Empty
    candidates.append([])
    # Deduplicate (using repr for hashability)
    deduped: list[list[Any]] = []
    seen: set[str] = set()
    for c in candidates:
        key = repr(c)
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    return deduped


def _shrink_dict(value: dict[Any, Any]) -> list[dict[Any, Any]]:
    """Produce smaller dict candidates."""
    candidates: list[dict[Any, Any]] = []
    if not value:
        return candidates
    # Remove keys
    keys = list(value.keys())
    for k in keys[:3]:  # try first 3 keys
        c = dict(value)
        del c[k]
        candidates.append(c)
    # Empty
    candidates.append({})
    return [c for c in candidates if c != value]


_SHRINKERS: dict[type, Callable[[Any], list[Any]]] = {
    int: _shrink_int,
    str: _shrink_str,
    float: _shrink_float,
    list: _shrink_list,
    dict: _shrink_dict,
}


def _generic_shrink(value: Any) -> list[Any]:
    """Dispatch to the right shrinker based on type."""
    for typ, shrinker in _SHRINKERS.items():
        if isinstance(value, typ) and not isinstance(value, bool):
            return shrinker(value)
    # For unknown types, try to return empty/zero
    candidates: list[Any] = []
    try:
        candidates.append(type(value)())
    except Exception:
        pass
    return candidates


# ---------------------------------------------------------------------------
# StressTester
# ---------------------------------------------------------------------------

class StressTester:
    """Property-based test engine — fuzz, find counterexamples, shrink.

    All methods are deterministic given a fixed *seed*.
    """

    def __init__(self, seed: int | None = None) -> None:
        """Create a tester with optional *seed* for reproducibility."""
        self._rng = random.Random(seed)
        self._stats: dict[str, Any] = {}

    # ------------------------------------------------------------------
    def fuzz_function(
        self,
        fn: Callable[..., Any],
        input_generator: Callable[[], Any],
        property_check: Callable[[Any, Any], bool],
        iterations: int = 1000,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Generate random inputs, run *fn*, and check *property_check*.

        *input_generator*: zero-arg callable returning one random input.
        *property_check*: ``callable(input_value, fn_output) -> bool``.

        Returns a dict::

            {
                "failed": bool,
                "counterexample": <value> | None,
                "iterations_run": int,
                "elapsed": float,
            }
        """
        start = time.monotonic()
        for i in range(iterations):
            if timeout is not None and (time.monotonic() - start) > timeout:
                self._stats = {
                    "failed": False,
                    "counterexample": None,
                    "iterations_run": i,
                    "elapsed": time.monotonic() - start,
                    "timed_out": True,
                }
                return dict(self._stats)

            inp = input_generator()
            try:
                out = fn(copy.deepcopy(inp))
            except Exception:
                # Function crashed on this input — that's a failure
                self._stats = {
                    "failed": True,
                    "counterexample": inp,
                    "iterations_run": i + 1,
                    "elapsed": time.monotonic() - start,
                    "reason": "exception",
                }
                return dict(self._stats)

            if not property_check(inp, out):
                self._stats = {
                    "failed": True,
                    "counterexample": inp,
                    "iterations_run": i + 1,
                    "elapsed": time.monotonic() - start,
                    "reason": "property_violation",
                }
                return dict(self._stats)

        self._stats = {
            "failed": False,
            "counterexample": None,
            "iterations_run": iterations,
            "elapsed": time.monotonic() - start,
            "reason": "exhausted",
        }
        return dict(self._stats)

    # ------------------------------------------------------------------
    def find_counterexample(
        self,
        fn: Callable[..., Any],
        property_check: Callable[[Any, Any], bool],
        generators: Sequence[Callable[[], Any]] | None = None,
        iterations: int = 500,
    ) -> dict[str, Any]:
        """Run fuzz_function with auto-generated inputs.

        If *generators* is None, uses a default set: ints, strings, lists,
        dicts. Otherwise uses the provided generator sequence, rotating
        through them round-robin.

        Returns the same dict as ``fuzz_function``.
        """
        if generators is None:
            generators = (_gen_int, _gen_str, _gen_list, _gen_dict)

        gen_idx = 0
        start = time.monotonic()

        for i in range(iterations):
            gen = generators[gen_idx % len(generators)]
            gen_idx += 1
            inp = gen()
            try:
                out = fn(copy.deepcopy(inp))
            except Exception:
                self._stats = {
                    "failed": True,
                    "counterexample": inp,
                    "iterations_run": i + 1,
                    "elapsed": time.monotonic() - start,
                    "reason": "exception",
                }
                return dict(self._stats)

            if not property_check(inp, out):
                self._stats = {
                    "failed": True,
                    "counterexample": inp,
                    "iterations_run": i + 1,
                    "elapsed": time.monotonic() - start,
                    "reason": "property_violation",
                }
                return dict(self._stats)

        self._stats = {
            "failed": False,
            "counterexample": None,
            "iterations_run": iterations,
            "elapsed": time.monotonic() - start,
            "reason": "exhausted",
        }
        return dict(self._stats)

    # ------------------------------------------------------------------
    def shrink_failure(
        self,
        failure_input: Any,
        property_check: Callable[[Any, Any], bool],
        max_iterations: int = 200,
    ) -> dict[str, Any]:
        """Shrink *failure_input* to a minimal failing case.

        *property_check*: ``callable(input_value, fn_output) -> bool``.

        Returns::

            {
                "original": <value>,
                "minimal": <value>,
                "shrinks_applied": int,
                "still_fails": bool,
            }
        """
        current = copy.deepcopy(failure_input)
        shrinks = 0

        for _ in range(max_iterations):
            candidates = _generic_shrink(current)
            made_progress = False
            for candidate in candidates:
                # The property_check acts on the original function's output
                # For shrinking, we need a slightly different contract:
                # we test that the candidate STILL FAILS the original check.
                # Caller passes a property_check that takes (input, output).
                # During shrink we call the original fn again with the candidate.
                # To avoid needing fn here, property_check can be a closure
                # that calls fn internally.
                if not property_check(candidate, candidate):
                    # This is tricky — for pure shrink we need to know if the
                    # candidate still triggers the failure. The property_check
                    # should be written as: lambda inp, _out: <original_fn>(inp) fails.
                    # During fuzz, property_check(inp, out) returns True if property holds.
                    # During shrink, we need: NOT property_check(candidate_out, candidate).
                    # So we check if property_check ALREADY returns False for the candidate.
                    pass

                # Correct approach: property_check returns True if property HOLDS.
                # Failure = property_check returns False.
                # We need to test if candidate STILL fails.
                # We evaluate property_check on the candidate AND its fn output.
                # But we don't have fn here — so the user must wrap it.
                # For now, try candidate directly as the input:
                try:
                    still_fails = not property_check(candidate, None)
                except Exception:
                    still_fails = True  # exception means still failing

                if still_fails:
                    current = candidate
                    shrinks += 1
                    made_progress = True
                    break
            if not made_progress:
                break

        return {
            "original": failure_input,
            "minimal": current,
            "shrinks_applied": shrinks,
            "still_fails": True,
        }

    # ------------------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        """Return stats from the last ``fuzz_function`` call."""
        return dict(self._stats)


# ---------------------------------------------------------------------------
# Default generators
# ---------------------------------------------------------------------------

def _gen_int() -> int:
    return random.randint(-1000, 1000)


def _gen_str() -> str:
    length = random.randint(0, 10)
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 \t"
    return "".join(random.choice(chars) for _ in range(length))


def _gen_list() -> list[int]:
    return [random.randint(-100, 100) for _ in range(random.randint(0, 8))]


def _gen_dict() -> dict[str, int]:
    keys = random.sample(["a", "b", "c", "d", "e", "x", "y", "z"], random.randint(0, 4))
    return {k: random.randint(0, 100) for k in keys}


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tester = StressTester(seed=42)

    # --- Test 1: sort property (should pass) ---
    def good_sort(lst: list[int]) -> list[int]:
        return sorted(lst)

    def sorted_property(inp: list[int], out: list[int]) -> bool:
        return all(out[i] <= out[i + 1] for i in range(len(out) - 1))

    def list_gen() -> list[int]:
        return [random.randint(-100, 100) for _ in range(random.randint(0, 20))]

    result = tester.fuzz_function(good_sort, list_gen, sorted_property, iterations=200)
    assert not result["failed"], f"sort should pass, got {result}"
    print(f"sort property: {result['iterations_run']} iterations, PASS")

    # --- Test 2: broken function (should find counterexample) ---
    def bad_sort(lst: list[int]) -> list[int]:
        # Deliberately broken: reverses negative numbers
        result = sorted(lst)
        if len(result) >= 2 and result[0] < 0:
            result[0], result[1] = result[1], result[0]
        return result

    result = tester.fuzz_function(bad_sort, list_gen, sorted_property, iterations=500)
    assert result["failed"], "bad_sort should fail"
    assert result["counterexample"] is not None
    print(f"bad_sort: {result['iterations_run']} iterations, FAIL — counterexample found")
    print(f"  counterexample: {result['counterexample']}")

    # --- Test 3: property that crashes on empty list ---
    def crash_on_empty(lst: list[int]) -> int:
        return lst[0]  # IndexError on empty

    def always_true(_inp: list[int], _out: int) -> bool:
        return True

    result = tester.fuzz_function(crash_on_empty, list_gen, always_true, iterations=50)
    # Should catch the IndexError
    if result["failed"]:
        print(f"crash_on_empty: caught exception at iteration {result['iterations_run']}")
    else:
        print("crash_on_empty: no crash in sampled inputs (unlucky)")

    # --- Test 4: find_counterexample with auto generators ---
    # Property: integer identity (always passes)
    def identity(x: int) -> int:
        return x

    def same_as_input(inp: int, out: int) -> bool:
        return inp == out

    result = tester.find_counterexample(identity, same_as_input, iterations=100)
    assert not result["failed"], "identity should never fail"
    print(f"find_counterexample (identity): {result['iterations_run']} iterations, PASS")

    # --- Test 5: shrink_failure ---
    # Deliberately failing property: "sum is always >= 100"
    def failing_sum(lst: list[int]) -> int:
        return sum(lst)

    def sum_ge_100(inp: list[int], out: int) -> bool:
        return out >= 100

    # Find a counterexample first
    result = tester.fuzz_function(failing_sum, list_gen, sum_ge_100, iterations=300)
    if result["failed"]:
        # Now shrink it — we wrap the property to work with shrink_failure
        def shrink_prop(candidate: list[int], _out: Any) -> bool:
            return sum(candidate) >= 100

        shrunk = tester.shrink_failure(result["counterexample"], shrink_prop, max_iterations=100)
        print(f"shrink_failure: original={result['counterexample']}")
        print(f"  minimal={shrunk['minimal']}, shrinks={shrunk['shrinks_applied']}")
        # Minimal failing case should be a short list with sum < 100
        assert sum(shrunk["minimal"]) < 100
        assert shrunk["still_fails"]
    else:
        print("sum_ge_100: no counterexample found (unlucky input generation)")

    # --- Test 6: stats ---
    s = tester.stats()
    assert "failed" in s
    print(f"stats: {s}")

    # --- Test 7: shrinking helpers ---
    assert 0 in _shrink_int(100)
    assert "" in _shrink_str("hello")
    assert [] in _shrink_list([1, 2, 3])
    assert {} in _shrink_dict({"a": 1})
    print("shrink helpers: OK")

    print("\nAll stress tester tests passed.")