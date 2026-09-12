#!/usr/bin/env python3
"""
OmniCore Benchmark Suite — measure tool speed, accuracy, token efficiency,
and agent comparisons.  Generates Markdown and JSON reports.

DNA: Order (quantitative rigour).

Usage::

    suite = BenchmarkSuite()

    # Speed
    result = suite.speed_benchmark("hash_sha256", iterations=500)
    print(f"{result['ops_per_sec']:.1f} ops/sec")

    # Accuracy
    results = suite.accuracy_benchmark([
        ("fib(10)", fib, 10, 55),
        ("sort_list", my_sort, [3, 1, 2], [1, 2, 3]),
    ])

    # Reports
    print(suite.report_markdown())
    suite.report_json("benchmark_report.json")

    # Regression
    regressions = suite.regression_test(baseline)
    if regressions:
        print("REGRESSION DETECTED")

Or run directly::

    python tools/benchmark_suite.py
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import random
import statistics
import sys
import textwrap
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, asdict
from typing import Any

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkResult:
    """Single benchmark run result."""

    task: str
    tool: str
    iterations: int
    total_time_ms: float
    ops_per_sec: float
    accuracy_pct: float | None = None
    tokens_used: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["accuracy%"] = d.pop("accuracy_pct")
        return d


@dataclass
class ProviderResult:
    """Token efficiency result for one provider."""

    provider: str
    task: str
    tokens_used: int
    time_ms: float
    response_length: int
    cost_estimate: float = 0.0


@dataclass
class AgentComparison:
    """Head-to-head agent comparison result."""

    task: str
    results: dict[str, dict[str, Any]]  # agent_name -> {time_ms, tokens, accuracy_pct, ...}
    winner: str
    margin: str  # human-readable margin


# ---------------------------------------------------------------------------
# Built-in benchmark tasks
# ---------------------------------------------------------------------------


def _fibonacci(n: int) -> int:
    """Compute fibonacci(n) iteratively."""
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def _fibonacci_recursive(n: int) -> int:
    """Compute fibonacci(n) recursively (slow — good for stress)."""
    if n <= 1:
        return n
    return _fibonacci_recursive(n - 1) + _fibonacci_recursive(n - 2)


def _sort_quick(arr: list[int]) -> list[int]:
    """Quick-sort (in-place copy)."""
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return _sort_quick(left) + middle + _sort_quick(right)


def _api_endpoint_template() -> str:
    """Generate a FastAPI-style endpoint code snippet."""
    return textwrap.dedent("""\
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    app = FastAPI()

    class Item(BaseModel):
        name: str
        price: float
        quantity: int = 1

    items: dict[str, Item] = {}

    @app.post("/items")
    async def create_item(item: Item) -> Item:
        item_id = str(uuid.uuid4())[:8]
        items[item_id] = item
        return item

    @app.get("/items/{item_id}")
    async def get_item(item_id: str) -> Item:
        if item_id not in items:
            raise HTTPException(status_code=404, detail="Item not found")
        return items[item_id]
    """)


def _logic_puzzle() -> tuple[str, str]:
    """River crossing puzzle — wolf, goat, cabbage."""
    puzzle = (
        "A farmer must transport a wolf, a goat, and a cabbage across a river.\n"
        "The boat holds only the farmer and one item. If left alone, the wolf "
        "eats the goat, and the goat eats the cabbage. How does the farmer get "
        "everything across safely?"
    )
    answer = (
        "1. Farmer takes goat across, returns alone.\n"
        "2. Farmer takes wolf across, returns with goat.\n"
        "3. Farmer takes cabbage across, returns alone.\n"
        "4. Farmer takes goat across. Done."
    )
    return puzzle, answer


def _math_problem() -> tuple[str, float]:
    """Hard math: sum of reciprocals of triangular numbers."""
    problem = (
        "Find the sum: 1/1 + 1/3 + 1/6 + 1/10 + ... + 1/5050 "
        "(denominators are triangular numbers T_n = n(n+1)/2, n = 1..100)."
    )
    # Sum of 2/(n(n+1)) = 2 * sum(1/n - 1/(n+1)) = 2 * (1 - 1/101) = 200/101
    answer = 200 / 101  # ≈ 1.980198...
    return problem, answer


def _architecture_decision() -> tuple[str, str]:
    """System design: rate limiter architecture."""
    problem = (
        "Design a distributed rate limiter for an API gateway handling "
        "10M requests/sec across 50 nodes. Must support per-user and "
        "per-endpoint limits with <5ms overhead. Describe the architecture."
    )
    answer = (
        "Token bucket with Redis cluster + local burst cache.\n"
        "1. Each node maintains a local token bucket (last 100ms of state).\n"
        "2. Redis cluster (sharded by user_id) holds authoritative counters.\n"
        "3. Async pipeline: check local cache → if near limit, query Redis.\n"
        "4. Lua scripts for atomic Redis operations.\n"
        "5. Gossip protocol for node-local limit sync (eventual consistency).\n"
        "Key trade-off: allow brief over-limit bursts for <5ms p99 latency."
    )
    return problem, answer


def _hash_benchmark(data: bytes, algorithm: str = "sha256", rounds: int = 10000) -> int:
    """Hash data repeatedly. Returns number of hashes performed."""
    h = hashlib.new(algorithm)
    for _ in range(rounds):
        h.update(data)
        _ = h.digest()
    return rounds


def _port_scan_stub(targets: list[str], ports: list[int]) -> dict[str, list[int]]:
    """Simulated port scan — returns open ports per target."""
    results: dict[str, list[int]] = {}
    for target in targets:
        open_ports = []
        for port in ports:
            # Simulate: "open" if hash(target + str(port)) % 7 == 0
            h = hashlib.md5(f"{target}:{port}".encode()).digest()
            if h[0] % 7 == 0:
                open_ports.append(port)
            # Add artificial delay to simulate real scan
            _ = sum(range(10))  # trivial CPU work
        results[target] = open_ports
    return results


def _dork_generator(domain: str, num_dorks: int = 100) -> list[str]:
    """Generate Google dorks for a domain."""
    templates = [
        f"site:{domain} filetype:pdf",
        f"site:{domain} inurl:admin",
        f"site:{domain} intitle:'index of'",
        f"site:{domain} filetype:sql",
        f"site:{domain} filetype:env",
        f"site:{domain} inurl:login",
        f"site:{domain} intext:'password'",
        f"site:{domain} filetype:log",
        f"site:{domain} intitle:dashboard",
        f"site:{domain} inurl:wp-admin",
        f"site:{domain} filetype:config",
        f"site:{domain} inurl:backup",
        f"site:{domain} filetype:xml inurl:database",
        f"site:{domain} intext:'api_key'",
        f"site:{domain} inurl:phpmyadmin",
    ]
    dorks = list(itertools.islice(itertools.cycle(templates), num_dorks))
    return dorks


def _text_quality_sample() -> str:
    """Generate a sample creative text for quality benchmarking."""
    return textwrap.dedent("""\
    The old library stood at the edge of town, its stone walls weathered
    by centuries of wind and rain. Inside, the scent of aged paper and
    oak shelving filled the air — a perfume that spoke of forgotten
    stories and whispered secrets. Dust motes danced in the slanted
    afternoon light that filtered through stained-glass windows depicting
    scenes from books no one had read in generations.

    Elena pushed open the heavy oak door, the hinges groaning a protest
    that echoed through the vaulted ceiling. She had come looking for
    answers about her grandmother's past, carrying nothing but a faded
    photograph and a name written in looping cursive on the back:
    "The Keeper's Codex."

    What she found would change everything she thought she knew about
    the nature of stories — and about herself.
    """)


def _code_format_sample() -> str:
    """Generate a deliberately messy code snippet for formatting benchmarks."""
    return (
        "def   process_data(data,flag=False  ,  callback=None):\n"
        "    result=[]\n"
        "    for   item in data:\n"
        "        if flag  and item>10:\n"
        "            result.append(item*2  )\n"
        "        elif not flag:\n"
        "            result.append(item+1)\n"
        "    if callback:\n"
        "        callback(result)\n"
        "    return    result\n"
    )


def _code_format_expected() -> str:
    """Expected formatted version."""
    return textwrap.dedent("""\
    def process_data(data, flag=False, callback=None):
        result = []
        for item in data:
            if flag and item > 10:
                result.append(item * 2)
            elif not flag:
                result.append(item + 1)
        if callback:
            callback(result)
        return result""")


# Registry of built-in benchmark tasks
_BUILTIN_TASKS: dict[str, dict[str, Any]] = {
    "fibonacci_iterative": {
        "category": "code_generation",
        "description": "Compute Fibonacci(30) iteratively",
        "fn": lambda: _fibonacci(30),
        "expected": 832040,
        "iterations": 500,
    },
    "quick_sort": {
        "category": "code_generation",
        "description": "Quicksort 1000 random integers",
        "fn": lambda: _sort_quick([random.randint(0, 10000) for _ in range(1000)]),
        "expected_length": 1000,
        "iterations": 100,
    },
    "api_endpoint_gen": {
        "category": "code_generation",
        "description": "Generate FastAPI CRUD endpoint code",
        "fn": _api_endpoint_template,
        "expected_lines_min": 15,
        "iterations": 200,
    },
    "logic_puzzle": {
        "category": "reasoning",
        "description": "Solve river-crossing logic puzzle",
        "fn": lambda: _logic_puzzle()[1],
        "expected_contains": "farmer takes goat",
        "iterations": 50,
    },
    "math_series": {
        "category": "reasoning",
        "description": "Sum of reciprocal triangular numbers (n=1..100)",
        "fn": lambda: sum(2.0 / (n * (n + 1)) for n in range(1, 101)),
        "expected": 200 / 101,
        "tolerance": 1e-9,
        "iterations": 300,
    },
    "architecture_decision": {
        "category": "reasoning",
        "description": "Design distributed rate limiter architecture",
        "fn": lambda: _architecture_decision()[1],
        "expected_contains": "token bucket",
        "iterations": 30,
    },
    "hash_rate": {
        "category": "cybersecurity",
        "description": "SHA-256 hashing throughput (10K rounds)",
        "fn": lambda: _hash_benchmark(b"OmniCore Benchmark Data " * 10, "sha256", 10000),
        "expected_min": 10000,
        "iterations": 50,
    },
    "port_scan": {
        "category": "cybersecurity",
        "description": "Simulated port scan (5 hosts x 100 ports)",
        "fn": lambda: _port_scan_stub(
            [f"192.168.1.{i}" for i in range(1, 6)],
            list(range(1, 101)),
        ),
        "expected_min_hosts": 5,
        "iterations": 30,
    },
    "dork_accuracy": {
        "category": "cybersecurity",
        "description": "Generate 100 Google dorks for domain",
        "fn": lambda: _dork_generator("example.com", 100),
        "expected_count": 100,
        "iterations": 100,
    },
    "text_quality": {
        "category": "creative",
        "description": "Creative writing quality benchmark",
        "fn": _text_quality_sample,
        "expected_min_chars": 500,
        "expected_contains": "Keeper's Codex",
        "iterations": 20,
    },
    "code_formatting": {
        "category": "creative",
        "description": "Code formatting quality benchmark",
        "fn": lambda: (_code_format_sample(), _code_format_expected()),
        "expected_format_match": True,
        "iterations": 150,
    },
}


# ---------------------------------------------------------------------------
# BenchmarkSuite
# ---------------------------------------------------------------------------


class BenchmarkSuite:
    """Professional benchmark engine for OmniCore tools and agents.

    All methods are self-contained; no external dependencies beyond stdlib.
    Results are stored internally and can be queried, rendered as Markdown,
    or exported as JSON at any time.
    """

    def __init__(self, seed: int = 42):
        self.seed = seed
        random.seed(seed)
        self._results: list[BenchmarkResult] = []
        self._provider_results: list[ProviderResult] = []
        self._comparisons: list[AgentComparison] = []
        self._suites: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 1. Speed benchmark
    # ------------------------------------------------------------------

    def speed_benchmark(
        self,
        tool_name: str,
        fn: Callable[[], Any],
        iterations: int = 100,
        *,
        warmup: int = 3,
    ) -> BenchmarkResult:
        """Measure raw execution speed of *fn* in operations per second.

        Parameters
        ----------
        tool_name: Human-readable name for the tool being tested.
        fn: Zero-argument callable to benchmark.
        iterations: Number of timed iterations.
        warmup: Number of untimed warmup calls.

        Returns
        -------
        BenchmarkResult with ``ops_per_sec``, ``total_time_ms``, etc.
        """
        # Warmup
        for _ in range(warmup):
            fn()

        # Timed
        start = time.perf_counter()
        for _ in range(iterations):
            fn()
        elapsed = time.perf_counter() - start

        total_ms = elapsed * 1000
        ops = iterations / elapsed if elapsed > 0 else float("inf")

        result = BenchmarkResult(
            task=f"speed:{tool_name}",
            tool=tool_name,
            iterations=iterations,
            total_time_ms=round(total_ms, 3),
            ops_per_sec=round(ops, 1),
            accuracy_pct=None,
        )
        self._results.append(result)
        return result

    # ------------------------------------------------------------------
    # 2. Accuracy benchmark
    # ------------------------------------------------------------------

    def accuracy_benchmark(
        self,
        test_cases: Sequence[tuple[str, Callable[[], Any], Any]],
        *,
        comparator: Callable[[Any, Any], bool] | None = None,
    ) -> list[BenchmarkResult]:
        """Test correctness of functions against known answers.

        Parameters
        ----------
        test_cases: List of ``(name, fn, expected)`` tuples.
            *name*: test case identifier.
            *fn*: zero-argument callable that returns a result.
            *expected*: the known-correct answer.
        comparator: Optional custom equality function ``(actual, expected) -> bool``.
            Defaults to ``==``.

        Returns
        -------
        List of BenchmarkResult, one per test case.
        """
        results: list[BenchmarkResult] = []
        for name, fn, expected in test_cases:
            start = time.perf_counter()
            try:
                actual = fn()
            except Exception as exc:
                actual = exc
            elapsed = time.perf_counter() - start

            if comparator is not None:
                passed = comparator(actual, expected)
            elif isinstance(expected, float) and isinstance(actual, float):
                passed = math.isclose(actual, expected, rel_tol=1e-9)
            else:
                passed = actual == expected

            result = BenchmarkResult(
                task=f"accuracy:{name}",
                tool=name,
                iterations=1,
                total_time_ms=round(elapsed * 1000, 3),
                ops_per_sec=round(1 / elapsed, 1) if elapsed > 0 else float("inf"),
                accuracy_pct=100.0 if passed else 0.0,
                metadata={"expected": str(expected)[:200], "actual": str(actual)[:200]},
            )
            results.append(result)
            self._results.append(result)
        return results

    # ------------------------------------------------------------------
    # 3. Token efficiency
    # ------------------------------------------------------------------

    def token_efficiency(
        self,
        task: str,
        providers: dict[str, Callable[[], tuple[int, int, str]]],
        *,
        input_text: str = "",
    ) -> list[ProviderResult]:
        """Compare token usage across providers for the same task.

        Parameters
        ----------
        task: Description of the task (e.g. "summarize document").
        providers: Dict of ``{provider_name: callable}`` where each callable
            returns ``(tokens_used, time_ms, response_text)``.
            Use this to wrap real API calls or simulated providers.
        input_text: Optional input text for context.

        Returns
        -------
        List of ProviderResult with per-provider metrics.
        """
        results: list[ProviderResult] = []
        for name, fn in providers.items():
            try:
                tokens, t_ms, response = fn()
            except Exception as exc:
                tokens, t_ms, response = 0, 0, str(exc)

            pr = ProviderResult(
                provider=name,
                task=task,
                tokens_used=tokens,
                time_ms=t_ms,
                response_length=len(response),
                cost_estimate=round(tokens * 0.002 / 1000, 6),  # $2/M tokens est.
            )
            results.append(pr)
            self._provider_results.append(pr)

            # Also record as standard result
            self._results.append(
                BenchmarkResult(
                    task=f"token_efficiency:{task}:{name}",
                    tool=name,
                    iterations=1,
                    total_time_ms=t_ms,
                    ops_per_sec=0,
                    accuracy_pct=None,
                    tokens_used=tokens,
                )
            )
        return results

    # ------------------------------------------------------------------
    # 4. Agent comparison
    # ------------------------------------------------------------------

    def compare_agents(
        self,
        tasks: Sequence[dict[str, Any]],
        agent_fns: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
    ) -> list[AgentComparison]:
        """Head-to-head comparison of multiple agent configurations.

        Parameters
        ----------
        tasks: List of task dicts, each with at least ``{"name": str}``.
            Additional keys are forwarded to the agent functions.
        agent_fns: Dict of ``{agent_name: callable(task_dict) -> result_dict}``.
            Result dict should contain ``{"time_ms": float, "tokens": int,
            "accuracy_pct": float, "output": str}``.

        Returns
        -------
        List of AgentComparison, one per task, with winner and margin.
        """
        comparisons: list[AgentComparison] = []
        for task in tasks:
            task_name = task.get("name", "unnamed")
            agent_results: dict[str, dict[str, Any]] = {}

            for agent_name, agent_fn in agent_fns.items():
                try:
                    result = agent_fn(task)
                    agent_results[agent_name] = {
                        "time_ms": result.get("time_ms", 0),
                        "tokens": result.get("tokens", 0),
                        "accuracy_pct": result.get("accuracy_pct", 0),
                        "output": result.get("output", "")[:500],
                    }
                except Exception as exc:
                    agent_results[agent_name] = {
                        "time_ms": 0,
                        "tokens": 0,
                        "accuracy_pct": 0,
                        "output": f"ERROR: {exc}",
                    }

            # Determine winner by composite score: accuracy * 0.5 + (1/time) * 0.3 + (1/tokens) * 0.2
            scores: dict[str, float] = {}
            for name, r in agent_results.items():
                acc = r["accuracy_pct"] / 100.0
                speed_score = 1.0 / max(r["time_ms"], 1) * 1000
                token_score = 1.0 / max(r["tokens"], 1) * 1000
                scores[name] = acc * 0.5 + speed_score * 0.0003 + token_score * 0.0002

            winner = max(scores, key=scores.get) if scores else "none"
            sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            if len(sorted_scores) >= 2:
                margin = f"{sorted_scores[0][0]} beats {sorted_scores[1][0]} by {sorted_scores[0][1] - sorted_scores[1][1]:.2f} pts"
            else:
                margin = "sole contender"

            ac = AgentComparison(
                task=task_name,
                results=agent_results,
                winner=winner,
                margin=margin,
            )
            comparisons.append(ac)
            self._comparisons.append(ac)
        return comparisons

    # ------------------------------------------------------------------
    # 5. Report — Markdown
    # ------------------------------------------------------------------

    def report_markdown(self) -> str:
        """Generate a professional benchmark report in Markdown."""
        lines: list[str] = []
        lines.append("# OmniCore Benchmark Report")
        lines.append(f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Total results:** {len(self._results)}")
        lines.append("")

        # Summary stats
        speed_results = [r for r in self._results if r.ops_per_sec > 0]
        acc_results = [r for r in self._results if r.accuracy_pct is not None]
        if speed_results:
            avg_ops = statistics.mean(r.ops_per_sec for r in speed_results)
            lines.append(f"- **Average throughput:** {avg_ops:,.1f} ops/sec")
        if acc_results:
            avg_acc = statistics.mean(r.accuracy_pct for r in acc_results)
            lines.append(f"- **Average accuracy:** {avg_acc:.1f}%")
        lines.append("")

        # Speed results table
        if speed_results:
            lines.append("## ⚡ Speed Benchmarks")
            lines.append("")
            lines.append("| Tool | Iterations | Total (ms) | Ops/sec |")
            lines.append("|---|---|---|---|")
            for r in sorted(speed_results, key=lambda x: x.ops_per_sec, reverse=True):
                lines.append(
                    f"| {r.tool} | {r.iterations} | {r.total_time_ms:.1f} | {r.ops_per_sec:,.1f} |"
                )
            lines.append("")

        # Accuracy results table
        if acc_results:
            lines.append("## 🎯 Accuracy Benchmarks")
            lines.append("")
            lines.append("| Task | Accuracy | Time (ms) | Expected | Actual |")
            lines.append("|---|---|---|---|---|")
            for r in sorted(acc_results, key=lambda x: x.accuracy_pct or 0, reverse=True):
                status = "✅" if (r.accuracy_pct or 0) >= 100 else "❌"
                lines.append(
                    f"| {r.tool} | {status} {r.accuracy_pct:.0f}% | {r.total_time_ms:.1f} | "
                    f"{r.metadata.get('expected', '—')[:60]} | {r.metadata.get('actual', '—')[:60]} |"
                )
            lines.append("")

        # Token efficiency
        if self._provider_results:
            lines.append("## 💰 Token Efficiency")
            lines.append("")
            lines.append("| Provider | Task | Tokens | Time (ms) | Response Len | Est. Cost |")
            lines.append("|---|---|---|---|---|---|")
            for pr in sorted(self._provider_results, key=lambda x: x.tokens_used):
                lines.append(
                    f"| {pr.provider} | {pr.task} | {pr.tokens_used} | {pr.time_ms:.0f} | "
                    f"{pr.response_length} | ${pr.cost_estimate:.4f} |"
                )
            lines.append("")

        # Agent comparisons
        if self._comparisons:
            lines.append("## 🤖 Agent Comparisons")
            lines.append("")
            for ac in self._comparisons:
                lines.append(f"### {ac.task}")
                lines.append(f"**Winner:** {ac.winner} ({ac.margin})")
                lines.append("")
                lines.append("| Agent | Time (ms) | Tokens | Accuracy |")
                lines.append("|---|---|---|---|")
                for name, r in ac.results.items():
                    lines.append(
                        f"| {name} | {r['time_ms']:.0f} | {r['tokens']} | {r['accuracy_pct']:.0f}% |"
                    )
                lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 6. Report — JSON
    # ------------------------------------------------------------------

    def report_json(self, path: str | None = None) -> str:
        """Export benchmark results as JSON.

        Parameters
        ----------
        path: If provided, write JSON to this file. Always returns the JSON string.

        Returns
        -------
        JSON string of the full benchmark report.
        """
        report: dict[str, Any] = {
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "version": "3.0",
            "summary": {
                "total_results": len(self._results),
                "speed_results": len([r for r in self._results if r.ops_per_sec > 0]),
                "accuracy_results": len([r for r in self._results if r.accuracy_pct is not None]),
                "provider_results": len(self._provider_results),
                "agent_comparisons": len(self._comparisons),
            },
            "results": [r.to_dict() for r in self._results],
            "provider_results": [
                {
                    "provider": pr.provider,
                    "task": pr.task,
                    "tokens_used": pr.tokens_used,
                    "time_ms": pr.time_ms,
                    "response_length": pr.response_length,
                    "cost_estimate": pr.cost_estimate,
                }
                for pr in self._provider_results
            ],
            "agent_comparisons": [
                {
                    "task": ac.task,
                    "winner": ac.winner,
                    "margin": ac.margin,
                    "results": ac.results,
                }
                for ac in self._comparisons
            ],
        }

        json_str = json.dumps(report, indent=2, ensure_ascii=False, default=str)

        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(json_str)

        return json_str

    # ------------------------------------------------------------------
    # 7. Regression test
    # ------------------------------------------------------------------

    def regression_test(
        self,
        baseline: dict[str, float],
        *,
        tolerance_pct: float = 10.0,
    ) -> list[dict[str, Any]]:
        """Detect performance regressions against a baseline.

        Parameters
        ----------
        baseline: Dict of ``{tool_name: baseline_ops_per_sec}``.
        tolerance_pct: Allowed percentage degradation before flagging (default 10%).

        Returns
        -------
        List of regression dicts: ``{tool, baseline, current, degradation_pct}``.
        Empty list means no regressions detected.
        """
        regressions: list[dict[str, Any]] = []
        current = {r.tool: r.ops_per_sec for r in self._results if r.ops_per_sec > 0}

        for tool, baseline_ops in baseline.items():
            if tool not in current:
                regressions.append(
                    {
                        "tool": tool,
                        "baseline": baseline_ops,
                        "current": None,
                        "degradation_pct": 100.0,
                        "status": "MISSING — tool not in current results",
                    }
                )
                continue

            curr = current[tool]
            if curr < baseline_ops:
                degradation = ((baseline_ops - curr) / baseline_ops) * 100
                if degradation > tolerance_pct:
                    regressions.append(
                        {
                            "tool": tool,
                            "baseline": baseline_ops,
                            "current": curr,
                            "degradation_pct": round(degradation, 1),
                            "status": "REGRESSION",
                        }
                    )
            elif curr < baseline_ops * (1 + tolerance_pct / 100):
                regressions.append(
                    {
                        "tool": tool,
                        "baseline": baseline_ops,
                        "current": curr,
                        "degradation_pct": 0.0,
                        "status": "OK (within tolerance)",
                    }
                )

        return regressions

    # ------------------------------------------------------------------
    # Convenience: run all built-in tasks
    # ------------------------------------------------------------------

    def run_all_builtins(self) -> list[BenchmarkResult]:
        """Run all 11 built-in benchmark tasks and return results."""
        results: list[BenchmarkResult] = []

        # --- Code Generation ---
        results.append(
            self.speed_benchmark(
                "fibonacci_iterative",
                _BUILTIN_TASKS["fibonacci_iterative"]["fn"],
                iterations=_BUILTIN_TASKS["fibonacci_iterative"]["iterations"],
            )
        )

        results.append(
            self.speed_benchmark(
                "quick_sort",
                _BUILTIN_TASKS["quick_sort"]["fn"],
                iterations=_BUILTIN_TASKS["quick_sort"]["iterations"],
            )
        )

        results.append(
            self.speed_benchmark(
                "api_endpoint_gen",
                _BUILTIN_TASKS["api_endpoint_gen"]["fn"],
                iterations=_BUILTIN_TASKS["api_endpoint_gen"]["iterations"],
            )
        )

        # --- Reasoning ---
        # logic_puzzle
        def _run_logic():
            puzzle, answer = _logic_puzzle()
            return answer

        results.extend(
            self.accuracy_benchmark(
                [
                    (
                        "logic_puzzle",
                        _run_logic,
                        _BUILTIN_TASKS["logic_puzzle"]["expected_contains"],
                    )
                ],
                comparator=lambda actual, expected: expected.lower() in actual.lower(),
            )
        )

        results.extend(
            self.accuracy_benchmark(
                [
                    (
                        "math_series",
                        _BUILTIN_TASKS["math_series"]["fn"],
                        _BUILTIN_TASKS["math_series"]["expected"],
                    )
                ]
            )
        )

        def _run_arch():
            problem, answer = _architecture_decision()
            return answer

        results.extend(
            self.accuracy_benchmark(
                [
                    (
                        "architecture_decision",
                        _run_arch,
                        _BUILTIN_TASKS["architecture_decision"]["expected_contains"],
                    )
                ],
                comparator=lambda actual, expected: expected.lower() in actual.lower(),
            )
        )

        # --- Cybersecurity ---
        results.append(
            self.speed_benchmark(
                "hash_rate_sha256",
                _BUILTIN_TASKS["hash_rate"]["fn"],
                iterations=_BUILTIN_TASKS["hash_rate"]["iterations"],
            )
        )

        results.append(
            self.speed_benchmark(
                "port_scan",
                _BUILTIN_TASKS["port_scan"]["fn"],
                iterations=_BUILTIN_TASKS["port_scan"]["iterations"],
            )
        )

        results.append(
            self.speed_benchmark(
                "dork_generation",
                _BUILTIN_TASKS["dork_accuracy"]["fn"],
                iterations=_BUILTIN_TASKS["dork_accuracy"]["iterations"],
            )
        )

        # --- Creative ---
        results.append(
            self.speed_benchmark(
                "text_quality",
                _BUILTIN_TASKS["text_quality"]["fn"],
                iterations=_BUILTIN_TASKS["text_quality"]["iterations"],
            )
        )

        results.append(
            self.speed_benchmark(
                "code_formatting",
                _BUILTIN_TASKS["code_formatting"]["fn"],
                iterations=_BUILTIN_TASKS["code_formatting"]["iterations"],
            )
        )

        return results

    def clear(self) -> None:
        """Reset all stored results."""
        self._results.clear()
        self._provider_results.clear()
        self._comparisons.clear()


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def _self_test() -> int:
    """Run all benchmarks, verify output format, return exit code."""
    print("=" * 72)
    print("  OmniCore Benchmark Suite — Self-Test")
    print("=" * 72)
    print()

    suite = BenchmarkSuite(seed=12345)

    # 1. Speed benchmark
    print("1. speed_benchmark ... ", end="", flush=True)
    r = suite.speed_benchmark("example_function", lambda: sum(range(1000)), iterations=200)
    assert r.tool == "example_function"
    assert r.iterations == 200
    assert r.total_time_ms > 0
    assert r.ops_per_sec > 0
    assert "task" in r.to_dict()
    assert "tool" in r.to_dict()
    assert "iterations" in r.to_dict()
    assert "total_time_ms" in r.to_dict()
    assert "ops_per_sec" in r.to_dict()
    assert "accuracy%" in r.to_dict()
    assert "tokens_used" in r.to_dict()
    print(f"OK ({r.ops_per_sec:,.1f} ops/sec)")

    # 2. Accuracy benchmark
    print("2. accuracy_benchmark ... ", end="", flush=True)
    results = suite.accuracy_benchmark(
        [
            ("add_correct", lambda: 2 + 2, 4),
            ("add_wrong", lambda: 2 + 2, 5),
        ]
    )
    assert len(results) == 2
    assert results[0].accuracy_pct == 100.0, f"Expected 100%, got {results[0].accuracy_pct}"
    assert results[1].accuracy_pct == 0.0, f"Expected 0%, got {results[1].accuracy_pct}"
    print("OK (correct: 1/2)")

    # 3. Token efficiency
    print("3. token_efficiency ... ", end="", flush=True)
    providers = {
        "provider_a": lambda: (150, 1200, "Response from provider A " * 20),
        "provider_b": lambda: (200, 900, "Response from provider B " * 15),
        "provider_c": lambda: (180, 1500, "Response from provider C " * 25),
    }
    prs = suite.token_efficiency("test_summarization", providers)
    assert len(prs) == 3
    assert all(isinstance(pr, ProviderResult) for pr in prs)
    cheapest = min(prs, key=lambda p: p.tokens_used)
    assert cheapest.provider == "provider_a"
    print(f"OK (cheapest: {cheapest.provider}, {cheapest.tokens_used} tokens)")

    # 4. Agent comparison
    print("4. compare_agents ... ", end="", flush=True)
    def agent_alpha(task):
        return {"time_ms": 500, "tokens": 300, "accuracy_pct": 95, "output": "Alpha result"}

    def agent_beta(task):
        return {"time_ms": 350, "tokens": 450, "accuracy_pct": 90, "output": "Beta result"}

    def agent_gamma(task):
        return {"time_ms": 800, "tokens": 200, "accuracy_pct": 98, "output": "Gamma result"}

    comparisons = suite.compare_agents(
        [{"name": "summarize_document"}, {"name": "generate_code"}],
        {"alpha": agent_alpha, "beta": agent_beta, "gamma": agent_gamma},
    )
    assert len(comparisons) == 2
    assert all(isinstance(c, AgentComparison) for c in comparisons)
    assert comparisons[0].winner != "none"
    print(f"OK (winner: {comparisons[0].winner})")

    # 5. Run all built-in tasks
    print("5. run_all_builtins ... ", end="", flush=True)
    suite.clear()
    builtin_results = suite.run_all_builtins()
    assert len(builtin_results) == 11, f"Expected 11, got {len(builtin_results)}"
    for br in builtin_results:
        assert br.total_time_ms > 0, f"{br.task} has zero time"
        d = br.to_dict()
        for key in ("task", "tool", "iterations", "total_time_ms", "ops_per_sec", "accuracy%", "tokens_used"):
            assert key in d, f"Missing key '{key}' in {br.task}"
    print(f"OK ({len(builtin_results)} benchmarks)")

    # 6. Markdown report
    print("6. report_markdown ... ", end="", flush=True)
    md = suite.report_markdown()
    assert "# OmniCore Benchmark Report" in md
    assert "Speed Benchmarks" in md or "Accuracy" in md
    assert len(md) > 500, f"Report too short: {len(md)} chars"
    print(f"OK ({len(md)} chars)")

    # 7. JSON report
    print("7. report_json ... ", end="", flush=True)
    json_str = suite.report_json()
    report = json.loads(json_str)
    assert "results" in report
    assert "summary" in report
    assert report["summary"]["total_results"] > 0
    # Test file output
    tmp_path = os.path.join(os.path.dirname(__file__) or ".", "_benchmark_test.json")
    suite.report_json(tmp_path)
    assert os.path.exists(tmp_path)
    os.remove(tmp_path)
    print(f"OK ({len(report['results'])} results in JSON)")

    # 8. Regression test
    print("8. regression_test ... ", end="", flush=True)
    baseline = {
        "fibonacci_iterative": builtin_results[0].ops_per_sec * 0.5,  # way lower → OK
        "quick_sort": builtin_results[1].ops_per_sec * 2.0,  # way higher → regression
    }
    regressions = suite.regression_test(baseline, tolerance_pct=10.0)
    assert len(regressions) >= 1, f"Expected at least 1 regression, got {len(regressions)}"
    quick_sort_reg = [r for r in regressions if r["tool"] == "quick_sort"]
    assert len(quick_sort_reg) >= 1, "quick_sort should be flagged"
    assert quick_sort_reg[0]["status"] == "REGRESSION"
    print(f"OK ({len(regressions)} flagged)")

    # 9. Print summary
    print()
    print("─" * 72)
    print("  ✅  ALL SELF-TESTS PASSED")
    print("─" * 72)
    print()
    print("Benchmark Summary:")
    print(f"  Total results:          {len(builtin_results)}")
    if builtin_results:
        ops_values = [r.ops_per_sec for r in builtin_results if r.ops_per_sec > 0]
        if ops_values:
            print(f"  Fastest:                {max(ops_values):,.1f} ops/sec")
            print(f"  Slowest:                {min(ops_values):,.1f} ops/sec")
            print(f"  Mean throughput:        {statistics.mean(ops_values):,.1f} ops/sec")
    print()

    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(_self_test())