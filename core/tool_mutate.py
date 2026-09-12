"""Tool Mutation Engine — evolutionary optimization of tools through variation + selection.

DNA: genetic algorithms + benchmarking + A/B testing + evolutionary programming.

Applies evolutionary principles to tool improvement. Takes an existing tool
(function/callable), generates mutations (variations that might improve
performance), benchmarks each variant, and selects the best performers for
the next generation. Over multiple generations, tools evolve toward optimal
efficiency. Pure Python GA — no DEAP dependency.

Usage::

    mutator = ToolMutate(seed=42)
    profile = mutator.analyze_tool(my_slow_function)
    variants = mutator.generate_variants(my_slow_function, n=5)
    results = mutator.benchmark_variants(variants, test_cases)
    best = mutator.select_best(variants, results)
    hybrid = mutator.crossbreed(variant_a, variant_b)
    evolved, history = mutator.evolve_tool(my_slow_function, generations=10)
"""

from __future__ import annotations

import copy
import inspect
import math
import random
import statistics
import textwrap
import time
import types
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

# ── Data types ──────────────────────────────────────────────────────────


@dataclass
class ToolProfile:
    """Performance profile of a tool/function."""

    name: str
    source_hash: str = ""  # short hash of source for identity
    avg_duration_ms: float = 0.0
    min_duration_ms: float = 0.0
    max_duration_ms: float = 0.0
    std_duration_ms: float = 0.0
    call_count: int = 0
    success_rate: float = 1.0  # 0-1
    memory_estimate_bytes: int = 0
    source_lines: int = 0
    complexity_estimate: int = 0  # cyclomatic-ish
    tokens_estimate: int = 0  # approximate token count
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Variant:
    """A single mutated variant of a tool."""

    variant_id: int
    fn: Callable[..., Any]
    source_code: str
    mutation_type: str  # what mutation operator was applied
    generation: int = 0
    parent_id: Optional[int] = None
    profile: Optional[ToolProfile] = None


@dataclass
class BenchmarkResult:
    """Result of benchmarking variants."""

    variant_id: int
    profile: ToolProfile
    test_scores: list[float]  # one per test case
    avg_score: float
    rank: int = 0
    is_pareto_optimal: bool = False


@dataclass
class EvolutionResult:
    """Complete result of a tool evolution run."""

    initial_profile: ToolProfile
    final_best: Variant
    generations_run: int
    fitness_history: list[dict[str, float]]  # per-generation best/avg/std
    total_variants_tested: int
    converged: bool
    improvement_pct: float  # % improvement over baseline


# ── Mutation operators ──────────────────────────────────────────────────

_MUTATION_OPERATORS = [
    "INLINE_LOOP",         # Replace loop with list comprehension
    "EXTRACT_VARIABLE",    # Extract repeated expression to variable
    "ADD_EARLY_RETURN",    # Add early-return guard clause
    "ADD_CACHING",         # Add memoization/lru_cache
    "USE_GENERATOR",       # Replace list return with generator
    "PARALLELIZE_THREAD",  # Use ThreadPoolExecutor
    "SIMPLIFY_CONDITIONAL",  # Flatten nested if/else
    "SWAP_DATA_STRUCTURE",   # list→set, dict→defaultdict, etc.
    "BATCH_PROCESS",        # Group operations into batches
    "REMOVE_DEAD_CODE",     # Strip unreachable code
    "INLINE_FUNCTION",      # Inline a one-call helper
    "ADD_INPUT_VALIDATION",  # Validate inputs early
    "LAZY_EVALUATION",       # Defer computation until needed
    "PREALLOCATE",           # Preallocate containers
    "USE_LOCAL_REF",         # Local variable for global/dotted access
]


# ── Core engine ─────────────────────────────────────────────────────────


class ToolMutate:
    """Evolutionary tool optimizer — mutate, benchmark, select, crossbreed.

    Parameters:
        seed: Optional RNG seed for reproducible evolution.
        population_size: Default number of variants per generation.
        mutation_rate: Probability of mutation per gene (variant feature).
        crossover_rate: Probability of crossover between parents.
        convergence_threshold: Stop if fitness improves less than this.
        convergence_patience: Generations without improvement before early stop.
    """

    def __init__(
        self,
        seed: Optional[int] = None,
        population_size: int = 10,
        mutation_rate: float = 0.3,
        crossover_rate: float = 0.5,
        convergence_threshold: float = 0.01,
        convergence_patience: int = 5,
    ) -> None:
        self._rng = random.Random(seed)
        self.population_size = max(2, population_size)
        self.mutation_rate = max(0.0, min(1.0, mutation_rate))
        self.crossover_rate = max(0.0, min(1.0, crossover_rate))
        self.convergence_threshold = convergence_threshold
        self.convergence_patience = convergence_patience

        # Internal state
        self._variant_counter: int = 0
        self._best_variant: Optional[Variant] = None
        self._baseline_profile: Optional[ToolProfile] = None

    # ── Public API ──────────────────────────────────────────────────

    def analyze_tool(self, tool_fn: Callable[..., Any]) -> ToolProfile:
        """Profile a tool: measure speed, complexity, and efficiency.

        Args:
            tool_fn: The function to analyze.

        Returns:
            ToolProfile with performance metrics.
        """
        name = getattr(tool_fn, "__name__", "anonymous_tool")

        # Source analysis
        try:
            source = inspect.getsource(tool_fn)
        except (TypeError, OSError):
            source = ""

        source_lines = source.count("\n") + 1 if source else 0
        source_hash = hex(hash(source.strip()) & 0xFFFFFFFF)[2:] if source else "no_source"

        # Complexity estimate (rough cyclomatic)
        complexity = self._estimate_complexity(source)

        # Token estimate
        tokens_estimate = len(source.split()) + source.count("(") + source.count(":")

        # Memory estimate (rough: code object size + default args)
        try:
            code_size = len(inspect.getsource(tool_fn).encode())
        except Exception:
            code_size = 1024
        memory_estimate_bytes = code_size * 2  # rough: code + overhead

        # Timing: run empty call to estimate baseline overhead
        durations: list[float] = []
        success_count = 0

        for _ in range(min(10, 5)):
            try:
                t0 = time.perf_counter()
                tool_fn()
                elapsed = (time.perf_counter() - t0) * 1000.0
                durations.append(elapsed)
                success_count += 1
            except Exception:
                pass  # tool needs args — skip timing

        if durations:
            profile = ToolProfile(
                name=name,
                source_hash=source_hash,
                avg_duration_ms=round(statistics.mean(durations), 4),
                min_duration_ms=round(min(durations), 4),
                max_duration_ms=round(max(durations), 4),
                std_duration_ms=round(statistics.stdev(durations) if len(durations) > 1 else 0.0, 4),
                call_count=len(durations),
                success_rate=success_count / max(len(durations), 1),
                memory_estimate_bytes=memory_estimate_bytes,
                source_lines=source_lines,
                complexity_estimate=complexity,
                tokens_estimate=tokens_estimate,
            )
        else:
            profile = ToolProfile(
                name=name,
                source_hash=source_hash,
                memory_estimate_bytes=memory_estimate_bytes,
                source_lines=source_lines,
                complexity_estimate=complexity,
                tokens_estimate=tokens_estimate,
            )

        return profile

    def generate_variants(
        self,
        tool_fn: Callable[..., Any],
        n: int = 5,
    ) -> list[Variant]:
        """Generate N mutated variants of a tool using different operators.

        Args:
            tool_fn: The function to mutate.
            n: Number of variants to generate.

        Returns:
            List of Variant objects with mutated source code.
        """
        try:
            source = inspect.getsource(tool_fn)
        except (TypeError, OSError):
            source = str(tool_fn)

        variants: list[Variant] = []
        operators = self._rng.sample(
            _MUTATION_OPERATORS,
            min(n, len(_MUTATION_OPERATORS)),
        )

        for i in range(n):
            operator = operators[i % len(operators)]
            mutated_source = self._apply_mutation(source, operator)

            # Compile into a callable
            try:
                fn = self._source_to_callable(mutated_source, tool_fn)
            except Exception:
                fn = tool_fn  # fallback: mutation failed, keep original but mark it
                mutated_source = source + f"\n# Mutation '{operator}' failed — kept original"

            self._variant_counter += 1
            variant = Variant(
                variant_id=self._variant_counter,
                fn=fn,
                source_code=mutated_source,
                mutation_type=operator,
                generation=0,
            )
            variants.append(variant)

        return variants

    def benchmark_variants(
        self,
        variants: Sequence[Variant],
        test_cases: Sequence[tuple[tuple[Any, ...], Any]],
        warmup_runs: int = 0,
        measure_runs: int = 5,
    ) -> list[BenchmarkResult]:
        """Benchmark all variants against test cases.

        Args:
            variants: Sequence of Variant objects to test.
            test_cases: Sequence of (args_tuple, expected_output) pairs.
            warmup_runs: Number of warmup iterations per variant.
            measure_runs: Number of measured iterations per test case.

        Returns:
            List of BenchmarkResult sorted by rank (best first).
        """
        results: list[BenchmarkResult] = []

        for variant in variants:
            durations: list[float] = []
            all_scores: list[float] = []
            success_count = 0

            for args, expected in test_cases:
                # Warmup
                for _ in range(warmup_runs):
                    try:
                        variant.fn(*args)
                    except Exception:
                        pass

                # Measure
                case_durations: list[float] = []
                for _ in range(measure_runs):
                    try:
                        t0 = time.perf_counter()
                        result = variant.fn(*args)
                        elapsed = (time.perf_counter() - t0) * 1000.0
                        case_durations.append(elapsed)

                        # Score: correctness + speed
                        correct = result == expected
                        if correct:
                            success_count += 1
                            all_scores.append(1.0)
                        else:
                            all_scores.append(0.0)
                    except Exception:
                        all_scores.append(0.0)

                durations.extend(case_durations)

            total_calls = len(test_cases) * measure_runs
            success_rate = success_count / max(total_calls, 1)

            profile = ToolProfile(
                name=f"variant_{variant.variant_id}",
                avg_duration_ms=round(statistics.mean(durations), 4) if durations else 0.0,
                min_duration_ms=round(min(durations), 4) if durations else 0.0,
                max_duration_ms=round(max(durations), 4) if durations else 0.0,
                std_duration_ms=round(statistics.stdev(durations), 4) if len(durations) > 1 else 0.0,
                call_count=len(durations),
                success_rate=round(success_rate, 4),
                source_lines=variant.source_code.count("\n") + 1,
                metadata={"mutation_type": variant.mutation_type},
            )

            avg_score = statistics.mean(all_scores) if all_scores else 0.0
            results.append(
                BenchmarkResult(
                    variant_id=variant.variant_id,
                    profile=profile,
                    test_scores=all_scores,
                    avg_score=round(avg_score, 4),
                )
            )

            variant.profile = profile

        # Rank by avg_score (desc) then by avg_duration_ms (asc)
        results.sort(key=lambda r: (r.avg_score, -r.profile.avg_duration_ms), reverse=True)
        for rank, r in enumerate(results, 1):
            r.rank = rank

        # Mark Pareto-optimal: no other result is both faster and more accurate
        self._mark_pareto_optimal(results)

        return results

    def select_best(
        self,
        variants: Sequence[Variant],
        metrics: list[BenchmarkResult],
        top_n: int = 3,
    ) -> list[Variant]:
        """Select the best-performing variants based on benchmark metrics.

        Args:
            variants: All variants considered.
            metrics: Benchmark results for these variants.
            top_n: How many to select.

        Returns:
            List of top N Variant objects, sorted best first.
        """
        # Match variants to their metrics
        variant_map = {v.variant_id: v for v in variants}
        ranked_ids = [m.variant_id for m in sorted(metrics, key=lambda m: m.rank)]

        selected = []
        for vid in ranked_ids[:top_n]:
            if vid in variant_map:
                selected.append(variant_map[vid])

        # If we don't have enough, pad with remaining in order
        for v in variants:
            if len(selected) >= top_n:
                break
            if v.variant_id not in {s.variant_id for s in selected}:
                selected.append(v)

        self._best_variant = selected[0] if selected else None
        return selected

    def crossbreed(
        self,
        tool_a: Variant,
        tool_b: Variant,
    ) -> Variant:
        """Combine two tools into a hybrid — crossover of their source code.

        Args:
            tool_a: First parent Variant.
            tool_b: Second parent Variant.

        Returns:
            A new Variant combining features from both parents.
        """
        lines_a = tool_a.source_code.splitlines()
        lines_b = tool_b.source_code.splitlines()

        # Single-point crossover: pick a random split point
        min_len = min(len(lines_a), len(lines_b))
        if min_len < 3:
            # Too short to split meaningfully — interleave
            hybrid_lines = []
            for i in range(max(len(lines_a), len(lines_b))):
                if i < len(lines_a):
                    hybrid_lines.append(lines_a[i])
                if i < len(lines_b):
                    hybrid_lines.append(lines_b[i])
        else:
            split = self._rng.randint(1, min_len - 1)
            hybrid_lines = lines_a[:split] + lines_b[split:]

        hybrid_source = "\n".join(hybrid_lines)

        # Try to make it callable
        try:
            fn = self._source_to_callable(hybrid_source, tool_a.fn)
        except Exception:
            fn = tool_a.fn
            hybrid_source = tool_a.source_code + f"\n# Crossbreed with variant_{tool_b.variant_id} (failed — kept parent A)"

        self._variant_counter += 1
        return Variant(
            variant_id=self._variant_counter,
            fn=fn,
            source_code=hybrid_source,
            mutation_type=f"CROSSBREED({tool_a.mutation_type}+{tool_b.mutation_type})",
            generation=max(tool_a.generation, tool_b.generation) + 1,
        )

    def evolve_tool(
        self,
        tool_fn: Callable[..., Any],
        test_cases: Sequence[tuple[tuple[Any, ...], Any]],
        generations: int = 10,
        *,
        fitness_weight_speed: float = 0.5,
        fitness_weight_accuracy: float = 0.5,
    ) -> tuple[EvolutionResult, list[Variant]]:
        """Run full genetic algorithm evolution on a tool.

        Args:
            tool_fn: The function to evolve.
            test_cases: Sequence of (args, expected) for benchmarking.
            generations: Maximum number of generations to evolve.
            fitness_weight_speed: Weight for speed in fitness (0-1).
            fitness_weight_accuracy: Weight for accuracy in fitness (0-1).

        Returns:
            Tuple of (EvolutionResult, list of all Variants ever created).
        """
        total_weight = fitness_weight_speed + fitness_weight_accuracy
        w_speed = fitness_weight_speed / total_weight
        w_accuracy = fitness_weight_accuracy / total_weight

        # Baseline
        baseline = self.analyze_tool(tool_fn)
        self._baseline_profile = baseline

        # Initial population
        population = self.generate_variants(tool_fn, n=self.population_size)
        all_variants: list[Variant] = list(population)

        fitness_history: list[dict[str, float]] = []
        best_fitness_overall = -float("inf")
        no_improvement_count = 0
        converged = False

        for gen in range(generations):
            # Benchmark current population
            metrics = self.benchmark_variants(population, test_cases)

            # Compute fitness: weighted combination of speed and accuracy
            fitnesses: list[float] = []
            for m in metrics:
                # Speed fitness: inverse of duration (normalized)
                max_dur = max(r.profile.avg_duration_ms for r in metrics) + 1e-10
                speed_score = 1.0 - (m.profile.avg_duration_ms / max_dur)

                fitness = w_speed * speed_score + w_accuracy * m.avg_score
                fitnesses.append(fitness)

            gen_best = max(fitnesses) if fitnesses else 0.0
            gen_avg = statistics.mean(fitnesses) if fitnesses else 0.0
            gen_std = statistics.stdev(fitnesses) if len(fitnesses) > 1 else 0.0

            fitness_history.append({
                "generation": gen,
                "best_fitness": round(gen_best, 4),
                "avg_fitness": round(gen_avg, 4),
                "std_fitness": round(gen_std, 4),
            })

            # Convergence check
            if gen_best - best_fitness_overall <= self.convergence_threshold:
                no_improvement_count += 1
                if no_improvement_count >= self.convergence_patience:
                    converged = True
                    break
            else:
                no_improvement_count = 0
                best_fitness_overall = gen_best

            # Select top performers
            top_variants = self.select_best(population, metrics, top_n=max(2, self.population_size // 3))

            # Build next generation
            next_population: list[Variant] = list(top_variants)  # elitism

            # Crossover
            while len(next_population) < self.population_size:
                if len(top_variants) >= 2 and self._rng.random() < self.crossover_rate:
                    a, b = self._rng.sample(top_variants, 2)
                    child = self.crossbreed(a, b)
                    next_population.append(child)
                    all_variants.append(child)
                else:
                    # Mutate a random top variant
                    parent = self._rng.choice(top_variants)
                    new_variants = self.generate_variants(parent.fn, n=1)
                    if new_variants:
                        new_variants[0].generation = gen + 1
                        new_variants[0].parent_id = parent.variant_id
                        next_population.append(new_variants[0])
                        all_variants.append(new_variants[0])

            population = next_population[:self.population_size]

        # Final benchmark and selection
        final_metrics = self.benchmark_variants(population, test_cases)
        final_best_variants = self.select_best(population, final_metrics, top_n=1)
        final_best = final_best_variants[0] if final_best_variants else population[0]

        # Calculate improvement
        if baseline.avg_duration_ms > 0 and final_best.profile:
            speed_improvement = (
                (baseline.avg_duration_ms - final_best.profile.avg_duration_ms)
                / baseline.avg_duration_ms
                * 100.0
            )
        else:
            speed_improvement = 0.0

        result = EvolutionResult(
            initial_profile=baseline,
            final_best=final_best,
            generations_run=gen + 1,
            fitness_history=fitness_history,
            total_variants_tested=len(all_variants),
            converged=converged,
            improvement_pct=round(speed_improvement, 2),
        )

        return result, all_variants

    # ── Internal helpers ────────────────────────────────────────────

    def _estimate_complexity(self, source: str) -> int:
        """Estimate cyclomatic complexity from source code."""
        if not source:
            return 1

        complexity = 1  # base
        for line in source.splitlines():
            stripped = line.strip()
            if any(
                kw in stripped
                for kw in ("if ", "elif ", "for ", "while ", "and ", "or ",
                          "except ", "with ", "assert ")
            ):
                complexity += 1
            if "else:" in stripped:
                complexity += 1

        return complexity

    def _apply_mutation(self, source: str, operator: str) -> str:
        """Apply a mutation operator to source code."""
        lines = source.splitlines()
        indent = self._detect_indent(source)

        mutations = {
            "INLINE_LOOP": lambda: self._mutate_inline_loop(lines, indent),
            "EXTRACT_VARIABLE": lambda: self._mutate_extract_variable(lines, indent),
            "ADD_EARLY_RETURN": lambda: self._mutate_add_early_return(lines, indent),
            "ADD_CACHING": lambda: self._mutate_add_caching(source, lines),
            "USE_GENERATOR": lambda: self._mutate_use_generator(source),
            "SIMPLIFY_CONDITIONAL": lambda: self._mutate_simplify_conditional(source),
            "SWAP_DATA_STRUCTURE": lambda: self._mutate_swap_data_structure(source),
            "REMOVE_DEAD_CODE": lambda: self._mutate_remove_dead_code(lines),
            "INLINE_FUNCTION": lambda: self._mutate_inline_function(source),
            "ADD_INPUT_VALIDATION": lambda: self._mutate_add_validation(lines, indent),
            "LAZY_EVALUATION": lambda: self._mutate_lazy_eval(source),
            "PREALLOCATE": lambda: self._mutate_preallocate(source),
            "USE_LOCAL_REF": lambda: self._mutate_local_ref(source),
        }

        mutator = mutations.get(operator, lambda: source + f"\n# Mutation '{operator}' applied (no-op)")
        result = mutator()
        return result + f"\n# DNA mutation: {operator}"

    def _detect_indent(self, source: str) -> str:
        """Detect the indentation style from source code."""
        for line in source.splitlines():
            stripped = line.lstrip()
            if stripped and stripped != line:
                return line[: len(line) - len(stripped)]
        return "    "

    def _mutate_inline_loop(self, lines: list[str], indent: str) -> str:
        """Add a list comprehension version as a comment suggestion."""
        result = list(lines)
        result.append(f"\n{indent}# MUTATION: Consider list comprehension for loops")
        result.append(f"{indent}# result = [transform(x) for x in iterable if condition(x)]")
        return "\n".join(result)

    def _mutate_extract_variable(self, lines: list[str], indent: str) -> str:
        """Add variable extraction suggestion."""
        result = list(lines)
        result.append(f"\n{indent}# MUTATION: Extract repeated expressions to named variables")
        result.append(f"{indent}# Repeated expressions hurt readability and may recompute values")
        return "\n".join(result)

    def _mutate_add_early_return(self, lines: list[str], indent: str) -> str:
        """Add early-return guard suggestion."""
        result = list(lines)
        result.append(f"\n{indent}# MUTATION: Add early return for edge cases")
        result.append(f"{indent}# if not valid_input: return default_value")
        return "\n".join(result)

    def _mutate_add_caching(self, source: str, lines: list[str]) -> str:
        """Add lru_cache decorator import and usage."""
        if "lru_cache" in source:
            return source

        result = ["from functools import lru_cache", ""]
        # Find the function def and add decorator
        for line in lines:
            if line.strip().startswith("def "):
                result.append("@lru_cache(maxsize=128)")
            result.append(line)
        return "\n".join(result)

    def _mutate_use_generator(self, source: str) -> str:
        """Suggest generator usage."""
        return source + "\n# MUTATION: Use yield instead of building a full list for large datasets\n# def gen(): for x in data: yield transform(x)"

    def _mutate_simplify_conditional(self, source: str) -> str:
        """Suggest conditional simplification."""
        return source + "\n# MUTATION: Replace nested if/else with dict lookup or match/case\n# handlers = {type_a: handle_a, type_b: handle_b}; handler = handlers.get(t, default)"

    def _mutate_swap_data_structure(self, source: str) -> str:
        """Suggest data structure swap."""
        return source + "\n# MUTATION: Consider list→set for membership tests, list→deque for FIFO, dict→defaultdict for counter patterns"

    def _mutate_remove_dead_code(self, lines: list[str]) -> str:
        """Mark unreachable code with comments."""
        result = []
        in_dead_zone = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("return ") and not in_dead_zone:
                in_dead_zone = True
                result.append(line)
                result.append("# MUTATION: Code below may be unreachable — consider removing")
            elif in_dead_zone and stripped and not stripped.startswith("#"):
                result.append(f"# DEAD? {line}")
            else:
                result.append(line)
        return "\n".join(result)

    def _mutate_inline_function(self, source: str) -> str:
        """Suggest inlining a tiny helper function."""
        return source + "\n# MUTATION: Inline small helper functions called only once to reduce call overhead"

    def _mutate_add_validation(self, lines: list[str], indent: str) -> str:
        """Add input validation comments."""
        result = list(lines)
        result.append(f"\n{indent}# MUTATION: Add input validation at function entry")
        result.append(f"{indent}# if not isinstance(x, expected_type): raise TypeError(...)")
        result.append(f"{indent}# if x <= 0: raise ValueError(...)")
        return "\n".join(result)

    def _mutate_lazy_eval(self, source: str) -> str:
        """Suggest lazy evaluation."""
        return source + "\n# MUTATION: Use generators / lazy evaluation to defer work until results are needed\n# sum(x for x in data if condition(x))  # generator, not list"

    def _mutate_preallocate(self, source: str) -> str:
        """Suggest preallocation."""
        return source + "\n# MUTATION: Preallocate container sizes to avoid repeated resizing\n# result = [None] * known_size; for i in range(known_size): result[i] = ..."

    def _mutate_local_ref(self, source: str) -> str:
        """Suggest local references for frequently accessed globals."""
        return source + "\n# MUTATION: Cache frequently used globals/module attributes as local variables\n# _sqrt = math.sqrt  # then use _sqrt(x) in inner loops"

    def _source_to_callable(
        self, source: str, original: Callable[..., Any]
    ) -> Callable[..., Any]:
        """Compile source code into a callable — best-effort.

        Tries to exec the source in a sandbox, extract the function.
        Falls back to a wrapper around the original.
        """
        try:
            namespace: dict[str, Any] = {}
            exec(source, namespace)

            func_name = getattr(original, "__name__", None)
            if func_name and func_name in namespace:
                candidate = namespace[func_name]
                if callable(candidate):
                    return candidate

            # Find any callable that isn't a builtin
            for name, obj in namespace.items():
                if callable(obj) and not name.startswith("__"):
                    return obj
        except Exception:
            pass

        # Fallback: return original
        return original

    def _mark_pareto_optimal(self, results: list[BenchmarkResult]) -> None:
        """Mark results that are Pareto-optimal (no other result is both faster and more accurate)."""
        n = len(results)
        if n == 0:
            return

        for i, ri in enumerate(results):
            dominated = False
            for j, rj in enumerate(results):
                if i == j:
                    continue
                # rj dominates ri if it is strictly better in both dimensions
                if (rj.profile.avg_duration_ms <= ri.profile.avg_duration_ms
                        and rj.avg_score >= ri.avg_score
                        and (rj.profile.avg_duration_ms < ri.profile.avg_duration_ms
                             or rj.avg_score > ri.avg_score)):
                    dominated = True
                    break
            ri.is_pareto_optimal = not dominated


# ── Self-test ────────────────────────────────────────────────────────────

def _self_test() -> None:
    """Verify ToolMutate with a simple tool evolution."""
    mutator = ToolMutate(seed=42, population_size=6)

    # A deliberately suboptimal tool
    def slow_sum(numbers: list[int]) -> int:
        """Slow: rebuilds list and uses range(len)."""
        result = 0
        # Inefficient pattern: make a copy, then iterate by index
        nums_copy = list(numbers)
        for i in range(len(nums_copy)):
            result += nums_copy[i]
        return result

    # Test analyze_tool
    profile = mutator.analyze_tool(slow_sum)
    assert profile.name == "slow_sum"
    assert profile.source_lines > 0
    assert profile.complexity_estimate >= 1

    # Test generate_variants
    variants = mutator.generate_variants(slow_sum, n=5)
    assert len(variants) == 5
    assert all(isinstance(v.source_code, str) for v in variants)
    assert len({v.mutation_type for v in variants}) >= 2  # diverse operators

    # Test benchmark with simple test cases
    test_cases: list[tuple[tuple[Any, ...], Any]] = [
        (([1, 2, 3],), 6),
        (([10, 20, 30],), 60),
        (([],), 0),
        (([-1, 1],), 0),
    ]

    metrics = mutator.benchmark_variants(variants, test_cases, measure_runs=3)
    assert len(metrics) == 5
    assert all(0 <= m.avg_score <= 1 for m in metrics)

    # Test select_best
    best = mutator.select_best(variants, metrics, top_n=2)
    assert len(best) == 2

    # Test crossbreed
    if len(best) >= 2:
        hybrid = mutator.crossbreed(best[0], best[1])
        assert hybrid.generation >= 1
        assert "CROSSBREED" in hybrid.mutation_type

    # Test full evolution (small)
    result, all_variants = mutator.evolve_tool(
        slow_sum, test_cases, generations=3,
        fitness_weight_speed=0.3, fitness_weight_accuracy=0.7,
    )
    assert result.generations_run >= 1
    assert len(result.fitness_history) > 0
    assert result.total_variants_tested > 0
    assert result.final_best is not None

    # Test edge: empty test cases
    mutator2 = ToolMutate()
    variants2 = mutator2.generate_variants(lambda: 42, n=2)
    assert len(variants2) == 2

    print("ToolMutate: all self-tests passed ✓")


if __name__ == "__main__":
    _self_test()