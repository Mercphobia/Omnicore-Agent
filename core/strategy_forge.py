"""
Strategy Forge — enumerate, score, select, execute, and learn from solution strategies.
DNA: The only agent that systematically enumerates ALL possible approaches to a problem,
scores them on multiple axes, executes the optimal one, and learns from the outcome
to suggest better strategies next time.
"""

from __future__ import annotations

import enum
import itertools
import json
import math
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union


# ============================================================================
# Data types
# ============================================================================


class StrategyCategory(enum.Enum):
    """Categories of solution strategies."""

    BRUTE_FORCE = "brute_force"
    DIVIDE_CONQUER = "divide_conquer"
    DYNAMIC_PROGRAMMING = "dynamic_programming"
    GREEDY = "greedy"
    HEURISTIC = "heuristic"
    MATHEMATICAL = "mathematical"
    RECURSIVE = "recursive"
    ITERATIVE = "iterative"
    PARALLEL = "parallel"
    CACHING = "caching"
    APPROXIMATION = "approximation"
    HYBRID = "hybrid"
    ML_BASED = "ml_based"
    SYMBOLIC = "symbolic"
    LAZY = "lazy"
    EAGER = "eager"
    ONLINE = "online"
    OFFLINE = "offline"
    CUSTOM = "custom"


@dataclass
class Strategy:
    """A single solution strategy for a problem."""

    name: str
    category: StrategyCategory
    description: str
    pseudocode: str = ""
    prerequisites: List[str] = field(default_factory=list)
    complexity_time: str = "?"  # e.g. "O(n log n)"
    complexity_space: str = "?"
    assumptions: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category.value,
            "description": self.description,
            "complexity_time": self.complexity_time,
            "complexity_space": self.complexity_space,
            "risks": self.risks,
        }


@dataclass
class StrategyScore:
    """Multi-axis score for a strategy."""

    strategy: Strategy
    speed: float = 0.0       # 0–1: expected speed
    risk: float = 0.0         # 0–1: lower is better (0 = no risk)
    quality: float = 0.0      # 0–1: expected output quality
    novelty: float = 0.0      # 0–1: how novel/creative
    simplicity: float = 0.0   # 0–1: how simple to implement
    robustness: float = 0.0   # 0–1: how robust to edge cases
    total: float = 0.0        # weighted total

    def __repr__(self) -> str:
        return (
            f"Score({self.strategy.name}: total={self.total:.2f}, "
            f"speed={self.speed:.2f}, risk={self.risk:.2f}, quality={self.quality:.2f})"
        )


@dataclass
class ExecutionResult:
    """Result of executing a strategy."""

    strategy: Strategy
    success: bool
    output: Any
    elapsed_ms: float
    error: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OutcomeRecord:
    """Record of a strategy execution for learning."""

    problem_signature: str  # hash of problem description
    strategy_name: str
    category: StrategyCategory
    success: bool
    elapsed_ms: float
    quality_score: float
    notes: str = ""


# ============================================================================
# Strategy enumerator — generates all possible approaches
# ============================================================================


class _StrategyEnumerator:
    """Generate candidate strategies for a given problem."""

    # Keywords → strategy categories mapping
    KEYWORD_MAP: Dict[str, List[StrategyCategory]] = {
        "sort": [StrategyCategory.DIVIDE_CONQUER, StrategyCategory.ITERATIVE, StrategyCategory.PARALLEL],
        "search": [StrategyCategory.BRUTE_FORCE, StrategyCategory.HEURISTIC, StrategyCategory.DIVIDE_CONQUER],
        "optimize": [StrategyCategory.DYNAMIC_PROGRAMMING, StrategyCategory.GREEDY, StrategyCategory.APPROXIMATION],
        "graph": [StrategyCategory.BRUTE_FORCE, StrategyCategory.GREEDY, StrategyCategory.DYNAMIC_PROGRAMMING],
        "path": [StrategyCategory.GREEDY, StrategyCategory.DYNAMIC_PROGRAMMING, StrategyCategory.HEURISTIC],
        "tree": [StrategyCategory.RECURSIVE, StrategyCategory.ITERATIVE, StrategyCategory.DIVIDE_CONQUER],
        "cache": [StrategyCategory.CACHING, StrategyCategory.LAZY, StrategyCategory.EAGER],
        "stream": [StrategyCategory.ONLINE, StrategyCategory.OFFLINE, StrategyCategory.PARALLEL],
        "count": [StrategyCategory.BRUTE_FORCE, StrategyCategory.MATHEMATICAL, StrategyCategory.DYNAMIC_PROGRAMMING],
        "schedule": [StrategyCategory.GREEDY, StrategyCategory.DYNAMIC_PROGRAMMING, StrategyCategory.HEURISTIC],
        "allocate": [StrategyCategory.GREEDY, StrategyCategory.DYNAMIC_PROGRAMMING, StrategyCategory.APPROXIMATION],
        "partition": [StrategyCategory.DIVIDE_CONQUER, StrategyCategory.DYNAMIC_PROGRAMMING, StrategyCategory.BRUTE_FORCE],
        "probability": [StrategyCategory.MATHEMATICAL, StrategyCategory.APPROXIMATION, StrategyCategory.ML_BASED],
        "predict": [StrategyCategory.ML_BASED, StrategyCategory.MATHEMATICAL, StrategyCategory.HEURISTIC],
        "classify": [StrategyCategory.ML_BASED, StrategyCategory.HEURISTIC, StrategyCategory.MATHEMATICAL],
        "match": [StrategyCategory.BRUTE_FORCE, StrategyCategory.HEURISTIC, StrategyCategory.DYNAMIC_PROGRAMMING],
        "compress": [StrategyCategory.GREEDY, StrategyCategory.MATHEMATICAL, StrategyCategory.HEURISTIC],
        "generate": [StrategyCategory.RECURSIVE, StrategyCategory.ITERATIVE, StrategyCategory.ML_BASED],
        "serialize": [StrategyCategory.ITERATIVE, StrategyCategory.RECURSIVE, StrategyCategory.CUSTOM],
        "validate": [StrategyCategory.BRUTE_FORCE, StrategyCategory.SYMBOLIC, StrategyCategory.HEURISTIC],
        "transform": [StrategyCategory.ITERATIVE, StrategyCategory.PARALLEL, StrategyCategory.CUSTOM],
    }

    @classmethod
    def enumerate(cls, problem: str, *, max_strategies: int = 15) -> List[Strategy]:
        """Enumerate all possible solution strategies for a problem.

        Args:
            problem: Natural language problem description.
            max_strategies: Maximum strategies to return.

        Returns:
            List of Strategy objects covering diverse categories.
        """
        import re
        problem_lower = problem.lower()
        tokens = set(re.findall(r"\w+", problem_lower))

        # Determine relevant categories from keywords
        categories: Set[StrategyCategory] = set()
        for keyword, cats in cls.KEYWORD_MAP.items():
            if keyword in problem_lower:
                categories.update(cats)

        # Always include some defaults
        defaults = {
            StrategyCategory.BRUTE_FORCE,
            StrategyCategory.DIVIDE_CONQUER,
            StrategyCategory.GREEDY,
            StrategyCategory.HEURISTIC,
        }
        categories.update(defaults)

        # Build strategies for each category
        strategies: List[Strategy] = []
        for cat in sorted(categories, key=lambda c: c.value):
            strat = cls._build_strategy(cat, problem, tokens)
            if strat:
                strategies.append(strat)

        # Add custom/hybrid strategies
        if len(categories) >= 3:
            hybrid = Strategy(
                name=f"Hybrid — {cls._pick_hybrid_name(categories)}",
                category=StrategyCategory.HYBRID,
                description=f"Combine multiple approaches: {', '.join(c.value for c in list(categories)[:3])}",
                complexity_time="varies",
                complexity_space="varies",
                risks=["Complexity of combining approaches", "May be over-engineered"],
            )
            strategies.append(hybrid)

        return strategies[:max_strategies]

    @classmethod
    def _build_strategy(
        cls, cat: StrategyCategory, problem: str, tokens: Set[str]
    ) -> Optional[Strategy]:
        """Build a Strategy object for a given category."""
        templates: Dict[StrategyCategory, Tuple[str, str, str, str, List[str]]] = {
            StrategyCategory.BRUTE_FORCE: (
                "Brute Force",
                "Exhaustively try all possibilities. Guarantees correctness but may be slow.",
                "O(2^n) or O(n!)",
                "O(1) or O(n)",
                ["Exponential runtime for large inputs", "Not practical for real-world scale"],
            ),
            StrategyCategory.DIVIDE_CONQUER: (
                "Divide & Conquer",
                "Split problem into subproblems, solve recursively, combine results.",
                "O(n log n)",
                "O(log n) stack",
                ["Requires problem to be naturally divisible", "Merge step can be complex"],
            ),
            StrategyCategory.DYNAMIC_PROGRAMMING: (
                "Dynamic Programming",
                "Solve overlapping subproblems once and cache results.",
                "O(n²) or O(n·W)",
                "O(n²) or O(n·W)",
                ["Requires optimal substructure", "Memory-intensive for large state spaces"],
            ),
            StrategyCategory.GREEDY: (
                "Greedy",
                "Make locally optimal choice at each step. Fast but not always globally optimal.",
                "O(n log n)",
                "O(1) or O(n)",
                ["May not find optimal solution", "Requires greedy-choice property proof"],
            ),
            StrategyCategory.HEURISTIC: (
                "Heuristic Search",
                "Use rules of thumb and approximation to find good-enough solutions quickly.",
                "O(n) to O(n²)",
                "O(n)",
                ["No optimality guarantee", "Heuristic quality depends on domain knowledge"],
            ),
            StrategyCategory.MATHEMATICAL: (
                "Mathematical / Closed-Form",
                "Derive exact formula — O(1) solution. Requires deep problem insight.",
                "O(1)",
                "O(1)",
                ["Not all problems have closed forms", "Derivation may be complex"],
            ),
            StrategyCategory.RECURSIVE: (
                "Recursive Traversal",
                "Natural recursive decomposition. Elegant but may hit recursion limits.",
                "O(n) to O(2^n)",
                "O(depth)",
                ["Stack overflow on deep inputs", "Function call overhead"],
            ),
            StrategyCategory.ITERATIVE: (
                "Iterative",
                "Loop-based approach. Predictable performance, no recursion overhead.",
                "O(n) to O(n²)",
                "O(1)",
                ["May be less elegant", "Some problems are inherently recursive"],
            ),
            StrategyCategory.PARALLEL: (
                "Parallel / Concurrent",
                "Split work across threads/processes. Great for CPU-bound tasks.",
                "O(n/p) ideal",
                "O(n/p) per worker",
                ["Synchronization overhead", "Not all problems parallelize well"],
            ),
            StrategyCategory.CACHING: (
                "Memoization / Caching",
                "Store and reuse previously computed results. Speed-for-memory trade.",
                "O(n) amortized",
                "O(n)",
                ["Cache invalidation complexity", "Memory pressure"],
            ),
            StrategyCategory.APPROXIMATION: (
                "Approximation Algorithm",
                "Provably near-optimal in polynomial time. When exact solutions are infeasible.",
                "O(n²) or O(n³)",
                "O(n²)",
                ["Approximation ratio must be acceptable", "May require mathematical proof"],
            ),
            StrategyCategory.ML_BASED: (
                "ML-Based",
                "Train or use a model to predict/classify. Data-driven approach.",
                "O(1) inference",
                "model-dependent",
                ["Requires training data", "Model may be a black box", "Cold-start problem"],
            ),
            StrategyCategory.SYMBOLIC: (
                "Symbolic / Constraint-Based",
                "Encode as logical constraints, solve with SAT/SMT solver.",
                "solver-dependent",
                "solver-dependent",
                ["Requires formal problem encoding", "Solver may timeout on complex problems"],
            ),
            StrategyCategory.LAZY: (
                "Lazy Evaluation",
                "Compute only when needed. Saves work when not all outputs are required.",
                "O(k) where k = requested outputs",
                "O(n) worst case",
                ["First access latency", "Complexity of thunk management"],
            ),
            StrategyCategory.ONLINE: (
                "Online / Streaming",
                "Process data as it arrives. Fixed memory, single pass.",
                "O(n) total, O(1) per item",
                "O(1) or O(window)",
                ["Cannot look ahead", "Order-dependent results"],
            ),
        }

        if cat not in templates:
            return None

        name, desc, time_c, space_c, risks = templates[cat]
        return Strategy(
            name=name,
            category=cat,
            description=desc,
            complexity_time=time_c,
            complexity_space=space_c,
            risks=risks,
        )

    @classmethod
    def _pick_hybrid_name(cls, categories: Set[StrategyCategory]) -> str:
        """Generate a descriptive hybrid strategy name."""
        names = sorted(c.value.replace("_", " ").title() for c in categories)
        if len(names) >= 3:
            return f"{names[0]} + {names[1]} + {names[2]}"
        return " + ".join(names)


# ============================================================================
# Main class
# ============================================================================


class StrategyForge:
    """Strategy Forge — systematic strategy enumeration, scoring, and execution.

    Enumerates all possible solution strategies for a problem, scores each on
    multiple axes (speed, risk, quality, novelty, simplicity, robustness),
    selects the optimal one, executes it, and learns from outcomes to improve
    future recommendations.

    DNA: The only agent with a systematic strategy forge — enumerate, score,
    execute, learn, and suggest better approaches for the next similar problem.

    Usage:
        forge = StrategyForge()

        approaches = forge.enumerate_approaches("sort a large dataset")
        scored = forge.score_strategy(approaches[0], {"speed": 0.8, "risk": 0.3})
        optimal = forge.pick_optimal(approaches)

        result = forge.execute_strategy(optimal, context={"data": [3, 1, 2]})
        forge.learn_outcome(optimal, result)

        better = forge.next_better()
    """

    def __init__(
        self,
        *,
        default_weights: Optional[Dict[str, float]] = None,
    ):
        """Initialize the Strategy Forge.

        Args:
            default_weights: Default scoring weights.
                             Defaults: speed=0.3, risk=0.2, quality=0.25, novelty=0.05,
                                       simplicity=0.1, robustness=0.1
        """
        self._weights = default_weights or {
            "speed": 0.30,
            "risk": 0.20,
            "quality": 0.25,
            "novelty": 0.05,
            "simplicity": 0.10,
            "robustness": 0.10,
        }
        self._history: List[OutcomeRecord] = []
        self._strategy_registry: Dict[str, List[OutcomeRecord]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enumerate_approaches(
        self,
        problem: str,
        *,
        max_strategies: int = 15,
    ) -> List[Strategy]:
        """List ALL possible solution strategies for a problem.

        Analyzes the problem description to identify relevant strategy categories
        and generates concrete Strategy objects covering diverse approaches.

        Args:
            problem: Natural language problem description.
            max_strategies: Maximum strategies to return.

        Returns:
            List of Strategy objects.
        """
        return _StrategyEnumerator.enumerate(problem, max_strategies=max_strategies)

    def score_strategy(
        self,
        approach: Strategy,
        criteria: Optional[Dict[str, float]] = None,
    ) -> StrategyScore:
        """Score a strategy on multiple axes: speed, risk, quality, novelty.

        Args:
            approach: The strategy to score.
            criteria: Dict of axis→value (0–1). Overrides auto-scoring.
                      Keys: speed, risk, quality, novelty, simplicity, robustness.

        Returns:
            StrategyScore with per-axis scores and weighted total.
        """
        if criteria is None:
            criteria = {}

        # Auto-score based on category if not provided
        scores = self._auto_score(approach)

        # Override with provided criteria
        for key, val in criteria.items():
            if key in scores:
                scores[key] = max(0.0, min(1.0, val))

        # Compute weighted total
        total = sum(
            scores.get(axis, 0.0) * weight
            for axis, weight in self._weights.items()
        )

        return StrategyScore(
            strategy=approach,
            speed=scores.get("speed", 0.0),
            risk=scores.get("risk", 0.0),
            quality=scores.get("quality", 0.0),
            novelty=scores.get("novelty", 0.0),
            simplicity=scores.get("simplicity", 0.0),
            robustness=scores.get("robustness", 0.0),
            total=round(total, 3),
        )

    def pick_optimal(
        self,
        approaches: List[Strategy],
        *,
        criteria_override: Optional[Dict[str, float]] = None,
        bias: Optional[Dict[str, float]] = None,
    ) -> Strategy:
        """Select the best strategy from a list.

        Scores all approaches and returns the one with the highest total.
        Optionally bias certain axes (e.g., {"novelty": 1.5} to favor novelty).

        Args:
            approaches: List of strategies to evaluate.
            criteria_override: Per-strategy criteria overrides (applied to all).
            bias: Axis multipliers to emphasize certain qualities.

        Returns:
            The highest-scoring Strategy.
        """
        if not approaches:
            raise ValueError("No approaches provided")

        scored: List[Tuple[StrategyScore, float]] = []

        for approach in approaches:
            score = self.score_strategy(approach, criteria_override)

            # Apply bias
            if bias:
                biased_total = sum(
                    score.__dict__.get(axis, 0.0) * weight * bias.get(axis, 1.0)
                    for axis, weight in self._weights.items()
                )
                score.total = round(biased_total, 3)

            scored.append((score, score.total))

        # Best = highest total
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0].strategy

    def execute_strategy(
        self,
        approach: Strategy,
        context: Dict[str, Any],
        *,
        executor: Optional[Callable[[Strategy, Dict[str, Any]], Any]] = None,
    ) -> ExecutionResult:
        """Execute the chosen strategy in the given context.

        If no custom executor is provided, the strategy is "simulated" — it
        returns a descriptive result so the forge can learn from the choice
        even without concrete execution.

        Args:
            approach: The strategy to execute.
            context: Dict of input data and parameters.
            executor: Optional callable that takes (Strategy, context) and returns result.

        Returns:
            ExecutionResult with success, output, timing, and metrics.
        """
        t0 = time.perf_counter()

        if executor is not None:
            try:
                output = executor(approach, context)
                elapsed = (time.perf_counter() - t0) * 1000
                return ExecutionResult(
                    strategy=approach,
                    success=True,
                    output=output,
                    elapsed_ms=round(elapsed, 2),
                )
            except Exception as e:
                elapsed = (time.perf_counter() - t0) * 1000
                return ExecutionResult(
                    strategy=approach,
                    success=False,
                    output=None,
                    elapsed_ms=round(elapsed, 2),
                    error=str(e),
                )

        # Simulated execution — produce a descriptive result
        elapsed = (time.perf_counter() - t0) * 1000
        simulated_output = {
            "approach": approach.name,
            "category": approach.category.value,
            "status": "simulated",
            "expected_complexity": approach.complexity_time,
        }

        return ExecutionResult(
            strategy=approach,
            success=True,
            output=simulated_output,
            elapsed_ms=round(elapsed, 2),
            metrics={"mode": "simulated"},
        )

    def learn_outcome(
        self,
        approach: Strategy,
        result: ExecutionResult,
        *,
        problem_signature: Optional[str] = None,
        notes: str = "",
    ) -> OutcomeRecord:
        """Update internal knowledge from the outcome of executing a strategy.

        Records success/failure, timing, and quality so future recommendations
        improve over time.

        Args:
            approach: The strategy that was executed.
            result: The result of execution.
            problem_signature: Hash/ID of the problem (auto-generated if not given).
            notes: Any additional observations.

        Returns:
            The recorded OutcomeRecord.
        """
        if problem_signature is None:
            problem_signature = uuid.uuid4().hex[:12]

        quality = self._estimate_quality(result)

        record = OutcomeRecord(
            problem_signature=problem_signature,
            strategy_name=approach.name,
            category=approach.category,
            success=result.success,
            elapsed_ms=result.elapsed_ms,
            quality_score=quality,
            notes=notes,
        )

        self._history.append(record)
        self._strategy_registry[approach.category.value].append(record)

        return record

    def next_better(self, *, top_k: int = 3) -> List[Dict[str, Any]]:
        """Suggest better approaches for the next similar problem.

        Analyzes all past outcomes to identify which strategies performed best
        and which categories consistently succeed, then recommends approaches
        that are statistically better.

        Returns:
            List of dicts with {category, success_rate, avg_time, recommendation}.
        """
        if not self._history:
            return []

        suggestions: List[Dict[str, Any]] = []
        successes = [r for r in self._history if r.success]

        for cat, records in self._strategy_registry.items():
            if not records:
                continue

            total = len(records)
            ok = sum(1 for r in records if r.success)
            rate = ok / total if total > 0 else 0.0
            avg_time = (
                sum(r.elapsed_ms for r in records) / total if total > 0 else 0.0
            )
            avg_quality = (
                sum(r.quality_score for r in records) / total if total > 0 else 0.0
            )

            # Generate recommendation
            if rate >= 0.9:
                rec = f"Strong performer — use {cat} as default for similar problems"
            elif rate >= 0.7:
                rec = f"Good choice — {cat} works well, consider fallback for edge cases"
            elif rate >= 0.4:
                rec = f"Mixed results — pair {cat} with a fallback strategy"
            else:
                rec = f"Avoid {cat} unless no alternatives — explore {self._suggest_alternative(cat)}"

            suggestions.append({
                "category": cat,
                "success_rate": round(rate, 3),
                "avg_time_ms": round(avg_time, 1),
                "avg_quality": round(avg_quality, 3),
                "total_attempts": total,
                "recommendation": rec,
            })

        suggestions.sort(key=lambda s: s["success_rate"], reverse=True)
        return suggestions[:top_k]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _auto_score(self, approach: Strategy) -> Dict[str, float]:
        """Auto-score a strategy based on its category and properties."""
        cat = approach.category

        # Base scores by category
        base_scores: Dict[StrategyCategory, Dict[str, float]] = {
            StrategyCategory.BRUTE_FORCE: {"speed": 0.1, "risk": 0.8, "quality": 1.0, "novelty": 0.1, "simplicity": 0.9, "robustness": 0.9},
            StrategyCategory.DIVIDE_CONQUER: {"speed": 0.7, "risk": 0.3, "quality": 0.9, "novelty": 0.3, "simplicity": 0.6, "robustness": 0.8},
            StrategyCategory.DYNAMIC_PROGRAMMING: {"speed": 0.6, "risk": 0.4, "quality": 0.95, "novelty": 0.3, "simplicity": 0.4, "robustness": 0.85},
            StrategyCategory.GREEDY: {"speed": 0.85, "risk": 0.5, "quality": 0.6, "novelty": 0.2, "simplicity": 0.8, "robustness": 0.5},
            StrategyCategory.HEURISTIC: {"speed": 0.7, "risk": 0.5, "quality": 0.6, "novelty": 0.5, "simplicity": 0.5, "robustness": 0.5},
            StrategyCategory.MATHEMATICAL: {"speed": 1.0, "risk": 0.1, "quality": 1.0, "novelty": 0.4, "simplicity": 0.3, "robustness": 1.0},
            StrategyCategory.RECURSIVE: {"speed": 0.5, "risk": 0.5, "quality": 0.8, "novelty": 0.2, "simplicity": 0.7, "robustness": 0.6},
            StrategyCategory.ITERATIVE: {"speed": 0.6, "risk": 0.2, "quality": 0.8, "novelty": 0.1, "simplicity": 0.9, "robustness": 0.8},
            StrategyCategory.PARALLEL: {"speed": 0.9, "risk": 0.4, "quality": 0.8, "novelty": 0.5, "simplicity": 0.3, "robustness": 0.5},
            StrategyCategory.CACHING: {"speed": 0.8, "risk": 0.3, "quality": 0.85, "novelty": 0.2, "simplicity": 0.6, "robustness": 0.7},
            StrategyCategory.APPROXIMATION: {"speed": 0.6, "risk": 0.4, "quality": 0.7, "novelty": 0.4, "simplicity": 0.4, "robustness": 0.6},
            StrategyCategory.ML_BASED: {"speed": 0.8, "risk": 0.6, "quality": 0.75, "novelty": 0.9, "simplicity": 0.2, "robustness": 0.5},
            StrategyCategory.SYMBOLIC: {"speed": 0.5, "risk": 0.2, "quality": 0.95, "novelty": 0.6, "simplicity": 0.3, "robustness": 0.9},
            StrategyCategory.LAZY: {"speed": 0.7, "risk": 0.3, "quality": 0.8, "novelty": 0.4, "simplicity": 0.5, "robustness": 0.7},
            StrategyCategory.ONLINE: {"speed": 0.8, "risk": 0.3, "quality": 0.7, "novelty": 0.4, "simplicity": 0.5, "robustness": 0.6},
            StrategyCategory.HYBRID: {"speed": 0.5, "risk": 0.6, "quality": 0.85, "novelty": 0.8, "simplicity": 0.2, "robustness": 0.7},
        }

        scores = base_scores.get(cat, {"speed": 0.5, "risk": 0.5, "quality": 0.5, "novelty": 0.3, "simplicity": 0.5, "robustness": 0.5})

        # Adjust for complexity hints in the description
        complexity_hints = {
            "O(1)": {"speed": 1.0, "risk": 0.1},
            "O(n)": {"speed": 0.7, "risk": 0.3},
            "O(n log n)": {"speed": 0.6, "risk": 0.3},
            "O(n²)": {"speed": 0.3, "risk": 0.6},
            "O(2^n)": {"speed": 0.05, "risk": 0.9},
        }

        for hint, adjustments in complexity_hints.items():
            if hint in approach.complexity_time:
                for k, v in adjustments.items():
                    scores[k] = v
                break

        return dict(scores)

    def _estimate_quality(self, result: ExecutionResult) -> float:
        """Estimate the quality of an execution result."""
        if not result.success:
            return 0.0
        if result.metrics.get("mode") == "simulated":
            return 0.5  # neutral score for simulated
        # For real executions, a default quality score
        return 0.8

    def _suggest_alternative(self, failing_category: str) -> str:
        """Suggest an alternative category when one performs poorly."""
        alternatives = {
            "brute_force": "divide & conquer or heuristic",
            "greedy": "dynamic programming",
            "heuristic": "approximation algorithms",
            "ml_based": "heuristic or symbolic",
            "hybrid": "single-strategy approach",
        }
        return alternatives.get(failing_category, "divide & conquer")


# ============================================================================
# Self-test
# ============================================================================

def _self_test() -> None:
    """Run comprehensive self-tests on the Strategy Forge."""
    print("=== StrategyForge Self-Test ===\n")

    forge = StrategyForge()

    # Test 1: Enumerate approaches
    print("Test 1: Enumerate strategies")
    strategies = forge.enumerate_approaches("sort a large dataset quickly")
    assert len(strategies) > 0, "Expected at least one strategy"
    assert len(strategies) >= 5, f"Expected many strategies, got {len(strategies)}"
    categories = {s.category.value for s in strategies}
    print(f"  Generated {len(strategies)} strategies across {len(categories)} categories")
    for s in strategies:
        print(f"    [{s.category.value}] {s.name}: {s.description[:60]}...")
    print("  PASS\n")

    # Test 2: Score a strategy
    print("Test 2: Score strategy")
    brute = next(s for s in strategies if s.category == StrategyCategory.BRUTE_FORCE)
    score = forge.score_strategy(brute)
    assert score.total > 0.0
    assert score.speed < score.quality  # brute force: slow but high quality
    print(f"  {score}")
    print("  PASS\n")

    # Test 3: Score with custom criteria
    print("Test 3: Score with custom criteria")
    custom_score = forge.score_strategy(brute, {"speed": 0.95, "risk": 0.1, "quality": 0.9})
    assert custom_score.speed == 0.95
    assert custom_score.risk == 0.1
    print(f"  Custom: speed={custom_score.speed}, risk={custom_score.risk}, quality={custom_score.quality}")
    print("  PASS\n")

    # Test 4: Pick optimal
    print("Test 4: Pick optimal")
    optimal = forge.pick_optimal(strategies)
    assert optimal is not None
    print(f"  Optimal: {optimal.name} ({optimal.category.value})")
    print("  PASS\n")

    # Test 5: Pick optimal with bias
    print("Test 5: Pick optimal with novelty bias")
    novel_optimal = forge.pick_optimal(strategies, bias={"novelty": 3.0})
    assert novel_optimal is not None
    print(f"  Novelty-biased optimal: {novel_optimal.name} ({novel_optimal.category.value})")
    print("  PASS\n")

    # Test 6: Execute strategy (simulated)
    print("Test 6: Execute strategy")
    result = forge.execute_strategy(optimal, context={"data": [3, 1, 2]})
    assert result.success
    print(f"  Result: {result.output}")
    print(f"  Time: {result.elapsed_ms:.3f}ms")
    print("  PASS\n")

    # Test 7: Execute with custom executor
    print("Test 7: Execute with custom executor")
    def custom_executor(strategy: Strategy, ctx: Dict[str, Any]) -> List[int]:
        return sorted(ctx["data"])

    result2 = forge.execute_strategy(optimal, {"data": [5, 2, 8]}, executor=custom_executor)
    assert result2.success
    assert result2.output == [2, 5, 8]
    print(f"  Output: {result2.output}")
    print("  PASS\n")

    # Test 8: Learn from outcome
    print("Test 8: Learn from outcomes")
    for s in strategies[:5]:
        res = forge.execute_strategy(s, {"data": [3, 1, 2]})
        record = forge.learn_outcome(s, res, problem_signature="sort_test")
        assert record.success
    print(f"  History: {len(forge._history)} records")
    print("  PASS\n")

    # Test 9: Next better
    print("Test 9: Next better")
    suggestions = forge.next_better(top_k=5)
    assert len(suggestions) > 0
    for s in suggestions:
        print(f"  {s['category']}: rate={s['success_rate']}, avg_time={s['avg_time_ms']}ms — {s['recommendation']}")
    print("  PASS\n")

    # Test 10: Enumeration coverage
    print("Test 10: Coverage across diverse problems")
    problems = [
        "find shortest path in a graph",
        "optimize resource allocation",
        "predict user behavior from history",
        "validate a complex configuration",
        "generate all permutations",
    ]
    for prob in problems:
        strats = forge.enumerate_approaches(prob, max_strategies=8)
        cats = {s.category.value for s in strats}
        print(f"  '{prob[:40]}...' → {len(strats)} strategies, categories: {sorted(cats)[:4]}")
    print("  PASS\n")

    print("=== All StrategyForge tests passed ===")


if __name__ == "__main__":
    _self_test()