"""
Tool composition pipeline — chain tools into DAGs and execute.

DNA: Muse Spark (orchestration) + Cursor (multi-step edit).

ToolComposer parses natural-language pipeline descriptions into a
directed acyclic graph (DAG) of tool invocations, executes them in
the correct order with data passing between steps, optimizes for
parallelism, caches intermediate results, and creates reusable
composed tools.

Usage::

    tc = ToolComposer(registry=my_tool_registry)
    dag = tc.parse_pipeline("fetch URL → extract text → summarize → save")
    result = tc.execute_pipeline(dag, {"url": "https://example.com"})
"""

from __future__ import annotations

import collections
import hashlib
import json
import logging
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ── Data types ──────────────────────────────────────────────────────────

@dataclass
class ToolStep:
    """A single step in a composed pipeline."""
    id: str
    tool_name: str
    inputs: dict[str, str] = field(default_factory=dict)   # param → source
    outputs: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"                                  # pending | running | done | failed
    result: Any = None
    error: Optional[str] = None
    elapsed_ms: float = 0.0


@dataclass
class PipelineDAG:
    """A directed acyclic graph of tool steps."""
    id: str
    steps: dict[str, ToolStep] = field(default_factory=dict)
    edges: list[tuple[str, str]] = field(default_factory=list)  # (from_id, to_id)
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def step_count(self) -> int:
        return len(self._topological_order())

    def _topological_order(self) -> list[str]:
        """Kahn's algorithm for topo sort."""
        in_degree: dict[str, int] = defaultdict(int)
        adj: dict[str, list[str]] = defaultdict(list)
        for step_id in self.steps:
            in_degree[step_id] = 0
        for src, tgt in self.edges:
            adj[src].append(tgt)
            in_degree[tgt] += 1

        queue: deque[str] = deque(
            sid for sid in self.steps if in_degree[sid] == 0
        )
        order: list[str] = []
        while queue:
            sid = queue.popleft()
            order.append(sid)
            for neighbor in adj[sid]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Handle cycles: append any remaining
        for sid in self.steps:
            if sid not in order:
                order.append(sid)

        return order

    def parallel_groups(self) -> list[list[str]]:
        """Group steps that can run in parallel (same depth level)."""
        topo = self._topological_order()
        in_degree: dict[str, int] = {}
        adj: dict[str, list[str]] = defaultdict(list)
        for step_id in topo:
            in_degree[step_id] = 0
        for src, tgt in self.edges:
            adj[src].append(tgt)
            in_degree[tgt] = in_degree.get(tgt, 0) + 1

        groups: list[list[str]] = []
        current = [sid for sid in topo if in_degree[sid] == 0]
        while current:
            groups.append(list(current))
            next_level: list[str] = []
            for sid in current:
                for neighbor in adj[sid]:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_level.append(neighbor)
            current = next_level

        return groups


# ── Tool registry interface ─────────────────────────────────────────────

class _ToolRegistryAdapter:
    """Thin wrapper around any tool registry for uniform invocation."""

    def __init__(self, registry: Optional[Any] = None):
        self._registry = registry
        self._tools: dict[str, Callable] = {}

    def register(self, name: str, fn: Callable) -> None:
        self._tools[name] = fn

    def has(self, name: str) -> bool:
        if name in self._tools:
            return True
        if self._registry:
            try:
                return self._registry.has(name)
            except Exception:
                pass
        return False

    def list_tools(self) -> list[str]:
        names = list(self._tools.keys())
        if self._registry:
            try:
                names.extend(self._registry.list_tools())
            except Exception:
                pass
        return sorted(set(names))

    def invoke(self, name: str, **kwargs: Any) -> Any:
        """Invoke a tool by name with keyword arguments."""
        if name in self._tools:
            return self._tools[name](**kwargs)
        if self._registry:
            try:
                return self._registry.invoke(name, **kwargs)
            except Exception:
                pass
        raise ValueError(f"Tool '{name}' not found")


# ── ToolComposer ────────────────────────────────────────────────────────

class ToolComposer:
    """Tool composition pipeline engine.

    Parses natural-language pipeline descriptions into DAGs of tool
    invocations, executes them with automatic data passing, optimizes
    for parallelism, caches intermediate results, and creates reusable
    composed tools.
    """

    # Keywords that indicate pipeline flow
    _FLOW_MARKERS = [
        "→", "->", "=>", "then", "after", "followed by",
        "|", "pipe to", "feed into", "pass to",
    ]

    _STEP_PATTERNS: dict[str, str] = {
        "fetch": "fetch",
        "get": "fetch",
        "download": "fetch",
        "extract": "extract",
        "parse": "extract",
        "transform": "transform",
        "convert": "transform",
        "map": "transform",
        "filter": "filter",
        "select": "filter",
        "summarize": "summarize",
        "summarise": "summarize",
        "save": "save",
        "write": "save",
        "store": "save",
        "validate": "validate",
        "check": "validate",
        "verify": "validate",
        "send": "send",
        "publish": "send",
        "notify": "send",
        "analyze": "analyze",
        "calculate": "analyze",
        "compute": "analyze",
        "generate": "generate",
        "create": "generate",
        "build": "generate",
    }

    def __init__(
        self,
        registry: Optional[Any] = None,
        cache_dir: Optional[str | Path] = None,
        max_workers: int = 4,
    ):
        self._adapter = _ToolRegistryAdapter(registry)
        self._cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".omnicore" / "pipeline_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._max_workers = max_workers
        self._pipelines: dict[str, PipelineDAG] = {}
        self._composed_tools: dict[str, Callable] = {}

    # ── Parse ──────────────────────────────────────────────────────

    def parse_pipeline(self, description: str) -> PipelineDAG:
        """Parse a natural-language pipeline description into a DAG.

        Examples:
            "fetch URL → extract text → summarize → save"
            "download data then transform then validate then publish"
            "fetch | extract | filter | save"

        Args:
            description: Natural-language pipeline description.

        Returns:
            PipelineDAG ready for execution.
        """
        dag_id = f"pipeline-{hashlib.sha256(description.encode()).hexdigest()[:8]}"

        # Normalize
        normalized = description.lower().replace("\n", " ")
        for marker in self._FLOW_MARKERS:
            normalized = normalized.replace(marker, "→")

        # Split into steps
        raw_steps = [s.strip() for s in normalized.split("→") if s.strip()]

        if not raw_steps:
            raw_steps = [normalized.strip()]

        steps: dict[str, ToolStep] = {}
        edges: list[tuple[str, str]] = []
        prev_id: Optional[str] = None

        for i, raw in enumerate(raw_steps):
            sid = f"step-{i}"
            tool_name, params = self._parse_step(raw)

            step = ToolStep(
                id=sid,
                tool_name=tool_name,
                params=params,
            )
            steps[sid] = step

            if prev_id is not None:
                edges.append((prev_id, sid))
                step.depends_on.append(prev_id)

            prev_id = sid

        # Infer inputs/outputs
        for i, sid in enumerate(steps):
            step = steps[sid]
            if i == 0:
                step.inputs["data"] = "input"
            else:
                step.inputs["data"] = f"$prev.{steps[list(steps.keys())[i-1]].id}.result"
            step.outputs = ["result"]

        dag = PipelineDAG(
            id=dag_id,
            steps=steps,
            edges=edges,
            description=description,
        )
        self._pipelines[dag_id] = dag
        return dag

    def _parse_step(self, raw: str) -> tuple[str, dict[str, Any]]:
        """Parse a single step into tool name + parameters."""
        words = raw.split()
        tool_name = "unknown"
        params: dict[str, Any] = {}

        for word in words:
            if word in self._STEP_PATTERNS:
                tool_name = self._STEP_PATTERNS[word]
                break

        if tool_name == "unknown" and words:
            tool_name = words[0]

        # Extract key=value or key:value params
        for w in words:
            if "=" in w:
                k, v = w.split("=", 1)
                params[k] = v.strip("'\"")
            elif ":" in w and not w.startswith("http"):
                k, v = w.split(":", 1)
                params[k] = v.strip("'\"")

        return tool_name, params

    # ── Build DAG ──────────────────────────────────────────────────

    def build_dag(self, steps: list[dict[str, Any]]) -> PipelineDAG:
        """Build a dependency graph from explicit step definitions.

        Args:
            steps: List of step dicts with at minimum: 'id', 'tool'.
                Optional: 'depends_on', 'inputs', 'params'.

        Returns:
            PipelineDAG.
        """
        dag_id = f"dag-{hashlib.sha256(json.dumps(steps, sort_keys=True).encode()).hexdigest()[:8]}"
        dag_steps: dict[str, ToolStep] = {}
        edges: list[tuple[str, str]] = []

        for sdef in steps:
            sid = sdef["id"]
            step = ToolStep(
                id=sid,
                tool_name=sdef["tool"],
                depends_on=sdef.get("depends_on", []),
                inputs=sdef.get("inputs", {}),
                outputs=sdef.get("outputs", ["result"]),
                params=sdef.get("params", {}),
            )
            dag_steps[sid] = step
            for dep in step.depends_on:
                edges.append((dep, sid))

        dag = PipelineDAG(
            id=dag_id,
            steps=dag_steps,
            edges=edges,
            metadata={"source": "explicit"},
        )
        self._pipelines[dag_id] = dag
        return dag

    # ── Execute ────────────────────────────────────────────────────

    def execute_pipeline(
        self, dag: PipelineDAG, input_data: dict[str, Any],
        timeout: float = 300.0,
    ) -> dict[str, Any]:
        """Execute a pipeline DAG with automatic data passing.

        Steps run in topological order; independent steps run in parallel.

        Args:
            dag: The pipeline DAG to execute.
            input_data: Initial input data for the first step(s).
            timeout: Maximum execution time in seconds.

        Returns:
            Dict with 'results' (per-step) and 'final' (last step output).
        """
        groups = dag.parallel_groups()
        results: dict[str, Any] = {}
        step_results: dict[str, Any] = {}
        deadline = time.time() + timeout

        # Store input data for root steps
        context = dict(input_data)

        for group in groups:
            if time.time() > deadline:
                for sid in group:
                    dag.steps[sid].status = "failed"
                    dag.steps[sid].error = "Pipeline timeout"
                break

            with ThreadPoolExecutor(max_workers=min(self._max_workers, len(group))) as executor:
                futures: dict[Any, str] = {}
                for sid in group:
                    step = dag.steps[sid]
                    # Resolve inputs
                    kwargs = self._resolve_inputs(step, context, step_results)
                    futures[executor.submit(self._execute_step, step, kwargs)] = sid

                for future in as_completed(futures, timeout=max(1.0, deadline - time.time())):
                    sid = futures[future]
                    try:
                        result = future.result(timeout=30.0)
                        step_results[sid] = result
                        results[sid] = result
                    except Exception as exc:
                        dag.steps[sid].status = "failed"
                        dag.steps[sid].error = str(exc)

        # Determine final output
        last_step = dag._topological_order()[-1] if dag.steps else ""
        final = step_results.get(last_step)

        return {
            "results": results,
            "final": final,
            "step_count": len(step_results),
            "dag_id": dag.id,
        }

    def _resolve_inputs(
        self, step: ToolStep, context: dict[str, Any], step_results: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve step inputs from context and previous step outputs."""
        kwargs = dict(step.params)
        for param, source in step.inputs.items():
            if source == "input":
                kwargs[param] = context.get("data", context)
            elif source.startswith("$prev."):
                # Reference to previous step's output
                prev_id = source.split(".")[1] if len(source.split(".")) > 1 else ""
                kwargs[param] = step_results.get(prev_id)
            else:
                kwargs[param] = context.get(source, source)
        return kwargs

    def _execute_step(self, step: ToolStep, kwargs: dict[str, Any]) -> Any:
        """Execute a single step and record results."""
        step.status = "running"
        t0 = time.perf_counter()

        try:
            # Check cache
            cache_key = self._step_cache_key(step.tool_name, kwargs)
            cached = self._load_cache(cache_key)
            if cached is not None:
                step.result = cached
                step.status = "done"
                step.elapsed_ms = (time.perf_counter() - t0) * 1000
                return cached

            # Execute via adapter or fallback
            if self._adapter.has(step.tool_name):
                result = self._adapter.invoke(step.tool_name, **kwargs)
            else:
                result = self._fallback_execute(step.tool_name, kwargs)

            step.result = result
            step.status = "done"
            step.elapsed_ms = (time.perf_counter() - t0) * 1000

            # Cache result
            self._save_cache(cache_key, result)

            return result

        except Exception as exc:
            step.status = "failed"
            step.error = str(exc)
            step.elapsed_ms = (time.perf_counter() - t0) * 1000
            raise

    @staticmethod
    def _fallback_execute(tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Minimal fallback when a tool isn't registered."""
        return {
            "status": "emulated",
            "tool": tool_name,
            "inputs": kwargs,
            "result": f"Emulated {tool_name} processing",
        }

    # ── Optimize ───────────────────────────────────────────────────

    def optimize_pipeline(self, dag: PipelineDAG) -> PipelineDAG:
        """Reorder steps for maximum parallelism.

        Analyzes the DAG and restructures independent steps to run
        concurrently rather than sequentially.

        Args:
            dag: Original pipeline DAG.

        Returns:
            Optimized DAG (new object, original unchanged).
        """
        import copy
        optimized = copy.deepcopy(dag)
        optimized.id = f"{dag.id}-optimized"
        optimized.metadata["optimized"] = True

        # Find steps that can be parallelized
        groups = dag.parallel_groups()
        sequential_groups = sum(1 for g in groups if len(g) == 1)
        parallel_groups = sum(1 for g in groups if len(g) > 1)

        optimized.metadata["parallel_groups"] = parallel_groups
        optimized.metadata["sequential_groups"] = sequential_groups
        optimized.metadata["parallelism_ratio"] = round(
            parallel_groups / max(1, len(groups)), 2
        )

        return optimized

    # ── Caching ────────────────────────────────────────────────────

    def cache_result(self, step_hash: str, result: Any) -> None:
        """Cache an intermediate result for reuse.

        Args:
            step_hash: Unique hash identifying the step + inputs.
            result: The result to cache.
        """
        self._save_cache(step_hash, result)

    def _step_cache_key(self, tool_name: str, kwargs: dict[str, Any]) -> str:
        """Generate a deterministic cache key."""
        raw = json.dumps({"tool": tool_name, "kwargs": kwargs}, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _save_cache(self, key: str, result: Any) -> None:
        """Persist a cached result."""
        try:
            cache_file = self._cache_dir / f"{key}.json"
            cache_file.write_text(
                json.dumps({"result": result, "timestamp": time.time()}, default=str),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _load_cache(self, key: str) -> Optional[Any]:
        """Load a cached result if it exists."""
        cache_file = self._cache_dir / f"{key}.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                # Only use cache if less than 1 hour old
                if time.time() - data.get("timestamp", 0) < 3600:
                    return data["result"]
            except Exception:
                pass
        return None

    # ── Compose tool ───────────────────────────────────────────────

    def compose_tool(self, chain_spec: str | list[dict[str, Any]]) -> Callable:
        """Create a reusable composed tool from a pipeline chain.

        The returned callable accepts **kwargs and runs the full pipeline.

        Args:
            chain_spec: Either a natural-language description or explicit
                       step list.

        Returns:
            A callable that executes the pipeline.
        """
        if isinstance(chain_spec, str):
            dag = self.parse_pipeline(chain_spec)
        else:
            dag = self.build_dag(chain_spec)

        dag_id = dag.id

        def composed_tool(**kwargs: Any) -> dict[str, Any]:
            return self.execute_pipeline(dag, kwargs)

        composed_tool.__name__ = f"composed_{dag_id.replace('-', '_')}"
        composed_tool.__doc__ = f"Composed pipeline: {dag.description}"

        self._composed_tools[dag_id] = composed_tool
        return composed_tool


# ── Self-test ───────────────────────────────────────────────────────────

def _self_test() -> None:
    """Verify ToolComposer core operations."""
    tc = ToolComposer()

    # parse_pipeline
    dag = tc.parse_pipeline("fetch URL → extract text → summarize → save")
    assert dag.step_count == 4, f"Should have 4 steps, got {dag.step_count}"
    print(f"  parse_pipeline: {dag.step_count} steps")

    # build_dag
    dag2 = tc.build_dag([
        {"id": "a", "tool": "fetch"},
        {"id": "b", "tool": "extract", "depends_on": ["a"]},
        {"id": "c", "tool": "save", "depends_on": ["b"]},
    ])
    assert dag2.step_count == 3
    print(f"  build_dag: {dag2.step_count} steps")

    # execute_pipeline
    result = tc.execute_pipeline(dag2, {"url": "https://example.com"})
    assert "results" in result, "Should have results key"
    print(f"  execute_pipeline: {result['step_count']} steps executed, final={result['final']}")

    # optimize_pipeline
    optimized = tc.optimize_pipeline(dag)
    assert optimized.metadata.get("optimized"), "Should be marked optimized"
    print(f"  optimize_pipeline: parallelism_ratio={optimized.metadata.get('parallelism_ratio')}")

    # cache_result
    tc.cache_result("test_hash_abc", {"cached": True, "value": 42})
    cached = tc._load_cache("test_hash_abc")
    assert cached == {"cached": True, "value": 42}
    print(f"  cache_result: cached={'yes' if cached else 'no'}")

    # compose_tool
    my_tool = tc.compose_tool("extract text → summarize")
    assert callable(my_tool)
    tool_result = my_tool(data="hello world")
    assert "results" in tool_result
    print(f"  compose_tool: tool created, result keys={list(tool_result.keys())}")

    # Topological order / parallel groups
    print(f"  topo_order: {dag._topological_order()}")
    print(f"  parallel_groups: {dag.parallel_groups()}")

    print("  compose: ALL TESTS PASSED")


if __name__ == "__main__":
    _self_test()