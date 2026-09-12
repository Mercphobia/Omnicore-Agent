"""
Self-modifying runtime — autonomously grow capabilities.

DNA: Astra GPT-6 (self-verify) + Devin (autonomous loop) + ToolSynthesizer.

The SelfModify engine detects capability gaps, generates new tools via
ToolSynthesizer, validates them against test cases, and hot-loads them
into the running agent without restart.  The `evolve_self()` method
loops continuously: detect → generate → validate → load.

Usage::

    sm = SelfModify(tool_registry=registry, synthesizer=synth)
    sm.evolve_self()  # runs until interrupted
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import inspect
import json
import logging
import sys
import textwrap
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ── Result types ────────────────────────────────────────────────────────

@dataclass
class GapAnalysis:
    """Result of capability-gap detection."""
    task_description: str
    missing_capability: str                    # human-readable description
    required_inputs: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    existing_tools: list[str] = field(default_factory=list)
    confidence: float = 0.0                    # 0.0 – 1.0
    suggested_name: str = ""


@dataclass
class ValidationResult:
    """Outcome of tool validation against test cases."""
    tool_name: str
    passed: int
    failed: int
    total: int
    failures: list[dict[str, Any]] = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total > 0 else 0.0


@dataclass
class EvolutionReport:
    """Report from one evolution cycle."""
    cycle: int
    gap: Optional[GapAnalysis] = None
    tool_name: Optional[str] = None
    validation: Optional[ValidationResult] = None
    hot_loaded: bool = False
    error: Optional[str] = None


# ── SelfModify engine ───────────────────────────────────────────────────

class SelfModify:
    """Autonomous self-improvement engine.

    Detects capability gaps, synthesizes new tools, validates them,
    and hot-loads into the running agent without restart.
    """

    def __init__(
        self,
        tool_registry: Optional[Any] = None,
        synthesizer: Optional[Any] = None,
        tools_dir: str | Path = "",
        max_cycles: int = 100,
        validation_timeout: float = 30.0,
    ):
        self._tool_registry = tool_registry
        self._synthesizer = synthesizer
        self._tools_dir = Path(tools_dir) if tools_dir else Path.cwd() / "generated_tools"
        self._tools_dir.mkdir(parents=True, exist_ok=True)
        self._max_cycles = max_cycles
        self._validation_timeout = validation_timeout
        self._loaded_tools: dict[str, Callable] = {}
        self._history: list[EvolutionReport] = []
        self._running = False

    # ── Gap detection ───────────────────────────────────────────────

    def detect_gap(self, task_description: str) -> GapAnalysis:
        """Analyze a task description to identify missing capabilities.

        Examines the task against the current tool registry to determine
        what capability is absent and what would be required to fulfill it.

        Args:
            task_description: Natural-language description of what needs doing.

        Returns:
            GapAnalysis with the missing capability, required inputs/outputs,
            and a suggested tool name.
        """
        existing_tools = self._list_available_tools()

        # Heuristic keyword-based gap detection
        keywords = self._extract_keywords(task_description.lower())
        capability = self._infer_missing_capability(keywords, set(existing_tools))

        required_inputs, expected_outputs = self._infer_io(keywords)

        return GapAnalysis(
            task_description=task_description,
            missing_capability=capability,
            required_inputs=required_inputs,
            expected_outputs=expected_outputs,
            existing_tools=existing_tools,
            confidence=self._confidence_estimate(keywords, capability),
            suggested_name=self._suggest_tool_name(keywords),
        )

    def _list_available_tools(self) -> list[str]:
        """Collect names of all registered / loadable tools."""
        names: list[str] = []
        if self._tool_registry is not None:
            try:
                names.extend(self._tool_registry.list_tools())
            except Exception:
                pass
        # Also check generated tools dir
        if self._tools_dir.exists():
            for p in self._tools_dir.glob("*.py"):
                if p.stem != "__init__":
                    names.append(p.stem)
        names.extend(self._loaded_tools.keys())
        return sorted(set(names))

    @staticmethod
    def _extract_keywords(text: str) -> set[str]:
        """Pull meaningful tokens from a task description."""
        stop = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "can", "shall",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "and", "or", "but", "not", "this", "that", "it", "i", "we",
            "you", "they", "he", "she", "his", "her", "its", "my", "our",
            "their", "me", "him", "us", "them", "need", "want", "please",
        }
        return {w.strip(".,;:!?()[]{}") for w in text.split() if len(w.strip(".,;:!?()[]{}")) > 2 and w not in stop}

    _CAPABILITY_HINTS: dict[str, str] = {
        "image": "image processing / manipulation",
        "video": "video processing / editing",
        "audio": "audio processing / transcription",
        "pdf": "PDF parsing / generation",
        "excel": "Excel / spreadsheet operations",
        "csv": "CSV parsing / transformation",
        "json": "JSON transformation / validation",
        "xml": "XML parsing / transformation",
        "sql": "SQL generation / query execution",
        "api": "API client / integration",
        "email": "email sending / parsing",
        "notification": "notification dispatch",
        "schedule": "scheduling / cron",
        "encrypt": "encryption / decryption",
        "hash": "hashing / checksums",
        "compress": "compression / archiving",
        "network": "network operations",
        "scrape": "web scraping",
        "browser": "browser automation",
        "database": "database operations",
        "cloud": "cloud provider operations",
        "docker": "container operations",
        "k8s": "Kubernetes operations",
        "git": "Git operations beyond basics",
        "test": "test generation / execution",
        "lint": "linting / static analysis",
        "format": "code formatting",
        "deploy": "deployment automation",
        "monitor": "monitoring / observability",
        "search": "search / indexing",
        "translate": "translation",
        "summarize": "summarization",
        "classify": "classification",
        "extract": "data extraction",
        "convert": "format conversion",
        "validate": "validation / verification",
        "generate": "generation (code/text/config)",
        "optimize": "optimization",
        "benchmark": "benchmarking",
        "diagram": "diagram / chart generation",
        "report": "report generation",
        "diff": "diff / comparison",
        "merge": "merge / reconciliation",
        "backup": "backup / restore",
        "scan": "security scanning",
        "audit": "audit trail / logging",
    }

    @classmethod
    def _infer_missing_capability(
        cls, keywords: set[str], existing: set[str]
    ) -> str:
        """Guess what capability is missing based on keywords vs existing tools."""
        for kw in sorted(keywords):
            if kw in cls._CAPABILITY_HINTS:
                hint = cls._CAPABILITY_HINTS[kw]
                # Check if a tool roughly covers this
                covered = any(
                    kw in name.lower() or hint.lower() in name.lower()
                    for name in existing
                )
                if not covered:
                    return hint
        return "general task automation"

    @staticmethod
    def _infer_io(keywords: set[str]) -> tuple[list[str], list[str]]:
        """Heuristically guess required inputs and expected outputs."""
        inputs: list[str] = []
        outputs: list[str] = []
        io_map = {
            "file": ("file_path", "result"),
            "url": ("url", "response"),
            "text": ("text", "processed_text"),
            "image": ("image_path", "processed_image"),
            "json": ("json_data", "json_result"),
            "csv": ("csv_path", "dataframe"),
            "pdf": ("pdf_path", "extracted_text"),
            "api": ("endpoint", "response_json"),
            "database": ("connection_string", "query_result"),
            "convert": ("input_data", "converted_output"),
            "generate": ("specification", "generated_output"),
            "validate": ("data", "validation_report"),
            "extract": ("source", "extracted_data"),
        }
        for kw in keywords:
            if kw in io_map:
                inp, out = io_map[kw]
                if inp not in inputs:
                    inputs.append(inp)
                if out not in outputs:
                    outputs.append(out)
        if not inputs:
            inputs = ["input_data"]
        if not outputs:
            outputs = ["result"]
        return inputs, outputs

    @staticmethod
    def _confidence_estimate(keywords: set[str], capability: str) -> float:
        """Estimate confidence (0–1) that the gap is correctly identified."""
        if capability == "general task automation":
            return 0.3
        matched = sum(1 for kw in keywords if kw in capability.lower())
        return min(0.95, 0.4 + matched * 0.15)

    @staticmethod
    def _suggest_tool_name(keywords: set[str]) -> str:
        """Generate a snake_case tool name from keywords."""
        base = "_".join(sorted(keywords)[:3])
        base = "".join(c if c.isalnum() or c == "_" else "_" for c in base)
        base = base.strip("_").lower()
        return base if base else "custom_tool"

    # ── Tool generation ─────────────────────────────────────────────

    def generate_tool(self, gap: GapAnalysis) -> Callable:
        """Generate a new tool function to fill the capability gap.

        Uses the ToolSynthesizer if available; otherwise builds a stub.

        Args:
            gap: GapAnalysis from detect_gap().

        Returns:
            A callable tool function ready for validation.
        """
        if self._synthesizer is not None:
            try:
                tool_fn = self._synthesizer.synthesize(
                    description=gap.missing_capability,
                    name=gap.suggested_name,
                    inputs=gap.required_inputs,
                    outputs=gap.expected_outputs,
                )
                if callable(tool_fn):
                    return tool_fn
            except Exception as exc:
                logger.warning("ToolSynthesizer failed: %s — falling back to stub", exc)

        # Fallback: build a stub function
        return self._build_stub(gap)

    def _build_stub(self, gap: GapAnalysis) -> Callable:
        """Construct a minimal stub function from the gap analysis."""

        def stub(**kwargs: Any) -> dict[str, Any]:
            """Auto-generated stub for: {desc}""".format(desc=gap.missing_capability)
            return {
                "status": "stub",
                "tool": gap.suggested_name,
                "capability": gap.missing_capability,
                "inputs_received": list(kwargs.keys()),
                "result": None,
            }

        stub.__name__ = gap.suggested_name
        stub.__doc__ = f"Stub for: {gap.missing_capability}"
        return stub

    # ── Tool validation ─────────────────────────────────────────────

    def validate_tool(
        self, tool_fn: Callable, test_cases: list[dict[str, Any]]
    ) -> ValidationResult:
        """Run a generated tool against test cases and verify output.

        Args:
            tool_fn: The tool function to validate.
            test_cases: List of dicts with 'input' (dict) and 'expected' keys.

        Returns:
            ValidationResult with pass/fail breakdown and details.
        """
        tool_name = getattr(tool_fn, "__name__", "unknown")
        passed, failed = 0, 0
        failures: list[dict[str, Any]] = []
        t0 = time.perf_counter()

        for i, case in enumerate(test_cases):
            try:
                inp = case.get("input", {})
                expected = case.get("expected")
                start = time.perf_counter()
                result = tool_fn(**inp) if isinstance(inp, dict) else tool_fn(inp)
                elapsed = (time.perf_counter() - start) * 1000

                if expected is not None:
                    match = self._check_match(result, expected)
                else:
                    match = result is not None  # existence check only

                if match:
                    passed += 1
                else:
                    failed += 1
                    failures.append({
                        "case_index": i,
                        "input": inp,
                        "expected": expected,
                        "got": result,
                        "elapsed_ms": elapsed,
                    })
            except Exception as exc:
                failed += 1
                failures.append({
                    "case_index": i,
                    "input": case.get("input", {}),
                    "expected": case.get("expected"),
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                })

        total_elapsed = (time.perf_counter() - t0) * 1000
        return ValidationResult(
            tool_name=tool_name,
            passed=passed,
            failed=failed,
            total=len(test_cases),
            failures=failures,
            elapsed_ms=total_elapsed,
        )

    @staticmethod
    def _check_match(result: Any, expected: Any) -> bool:
        """Flexible result matching for validation."""
        if isinstance(expected, dict) and isinstance(result, dict):
            for k, v in expected.items():
                if k not in result:
                    return False
                if v is not None and result[k] != v:
                    return False
            return True
        if isinstance(expected, str) and isinstance(result, str):
            return expected.lower() in result.lower()
        if callable(expected):
            try:
                return bool(expected(result))
            except Exception:
                return False
        return result == expected

    # ── Hot-loading ─────────────────────────────────────────────────

    def hot_load(self, tool_name: str, tool_fn: Callable) -> bool:
        """Register a tool into the running agent without restart.

        Writes the tool source to the generated tools directory and
        registers it with the tool registry.

        Args:
            tool_name: Unique name for the tool.
            tool_fn: The callable tool function.

        Returns:
            True if successfully loaded.
        """
        self._loaded_tools[tool_name] = tool_fn

        # Persist source code to disk
        try:
            source = inspect.getsource(tool_fn)
        except (OSError, TypeError):
            source = f"# Auto-generated stub\ndef {tool_name}(**kwargs):\n    return {{}}"

        tool_path = self._tools_dir / f"{tool_name}.py"
        tool_path.write_text(textwrap.dedent(source), encoding="utf-8")

        # Register with tool registry if available
        if self._tool_registry is not None:
            try:
                self._tool_registry.register(tool_name, tool_fn)
            except Exception as exc:
                logger.warning("Tool registry register failed for %s: %s", tool_name, exc)

        # Also insert into sys.modules for import access
        spec = importlib.util.spec_from_file_location(
            f"generated_tools.{tool_name}", str(tool_path)
        )
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            setattr(module, tool_name, tool_fn)
            sys.modules[f"generated_tools.{tool_name}"] = module

        logger.info("Hot-loaded tool: %s", tool_name)
        return True

    # ── Evolution loop ──────────────────────────────────────────────

    def evolve_self(
        self,
        task_queue: Optional[list[str]] = None,
        test_cases: Optional[dict[str, list[dict[str, Any]]]] = None,
    ) -> list[EvolutionReport]:
        """Continuous improvement loop: detect → generate → validate → load.

        Runs until max_cycles is reached or the task queue is exhausted.

        Args:
            task_queue: Optional list of task descriptions to process.
            test_cases: Optional mapping of tool_name → list of test cases.

        Returns:
            List of EvolutionReport entries, one per cycle.
        """
        self._running = True
        tasks = task_queue.copy() if task_queue else []
        cycle = 0

        while self._running and cycle < self._max_cycles:
            cycle += 1
            report = EvolutionReport(cycle=cycle)

            try:
                # Pick a task
                if tasks:
                    task = tasks.pop(0)
                else:
                    task = self._generate_improvement_task()
                    if task is None:
                        break

                # Detect gap
                gap = self.detect_gap(task)
                report.gap = gap

                if gap.confidence < 0.2:
                    report.error = f"Low confidence ({gap.confidence:.2f}) — skipping"
                    self._history.append(report)
                    continue

                # Generate tool
                tool_fn = self.generate_tool(gap)
                tool_name = gap.suggested_name
                report.tool_name = tool_name

                # Validate
                cases = (test_cases or {}).get(tool_name, [])
                if not cases:
                    # Build minimal self-test
                    cases = self._build_default_test_cases(gap)
                validation = self.validate_tool(tool_fn, cases)
                report.validation = validation

                # Hot-load if validation passes
                if validation.pass_rate >= 0.5:  # at least half pass
                    self.hot_load(tool_name, tool_fn)
                    report.hot_loaded = True

            except Exception as exc:
                report.error = str(exc)
                logger.error("Evolution cycle %d failed: %s", cycle, exc)

            self._history.append(report)

        return self._history

    def _generate_improvement_task(self) -> Optional[str]:
        """Generate a self-improvement task by introspecting available tools."""
        existing = self._list_available_tools()
        if not existing:
            return None
        # Propose a task that bridges missing capabilities
        gaps = []
        for cap in list(self._CAPABILITY_HINTS.values())[:10]:
            covered = any(
                cap.lower() in name.lower() or name.lower() in cap.lower()
                for name in existing
            )
            if not covered:
                gaps.append(cap)
        if gaps:
            import random
            return f"Add capability for: {random.choice(gaps)}"
        return None

    @staticmethod
    def _build_default_test_cases(gap: GapAnalysis) -> list[dict[str, Any]]:
        """Construct minimal smoke-test cases."""
        return [
            {
                "input": {inp: "test_value" for inp in gap.required_inputs},
                "expected": None,  # existence check only
            }
        ]

    def stop(self) -> None:
        """Signal the evolution loop to stop."""
        self._running = False

    @property
    def loaded_tool_count(self) -> int:
        return len(self._loaded_tools)

    @property
    def history(self) -> list[EvolutionReport]:
        return list(self._history)


# ── Self-test ───────────────────────────────────────────────────────────

def _self_test() -> None:
    """Verify SelfModify core operations."""
    sm = SelfModify(max_cycles=3)

    # detect_gap
    gap = sm.detect_gap("I need to convert images to WebP format")
    assert gap.missing_capability, "Should detect missing capability"
    assert gap.suggested_name, "Should suggest a name"
    print(f"  detect_gap: {gap.missing_capability} (confidence={gap.confidence:.2f})")

    # generate_tool
    fn = sm.generate_tool(gap)
    assert callable(fn), "Generated tool must be callable"
    result = fn(image_path="test.png")
    assert isinstance(result, dict), "Tool should return dict"
    print(f"  generate_tool: {fn.__name__}() → {result}")

    # validate_tool
    validation = sm.validate_tool(fn, [
        {"input": {"image_path": "test.png"}, "expected": None},
    ])
    assert validation.total == 1, "Should have tested one case"
    print(f"  validate_tool: {validation.passed}/{validation.total} passed")

    # hot_load
    loaded = sm.hot_load("image_converter", fn)
    assert loaded, "Should hot-load successfully"
    assert "image_converter" in sm._loaded_tools
    print(f"  hot_load: loaded={loaded}, count={sm.loaded_tool_count}")

    print("  self_modify: ALL TESTS PASSED")


if __name__ == "__main__":
    _self_test()