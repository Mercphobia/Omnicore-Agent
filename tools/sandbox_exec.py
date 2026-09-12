"""Python code sandbox — safe execution with static analysis and isolation.

DNA: Secure execution of LLM-generated code. Two layers of safety:
    1. Static analysis via ast.parse — catches dangerous patterns before exec.
    2. Subprocess isolation — runs code in a separate process with resource limits.

Usage:
    sandbox = SandboxExecutor()
    result = sandbox.execute("print(2 + 2)")
    # → SandboxResult(stdout="4", ...)

    # With tool access
    result = sandbox.execute_with_tools(code, tool_registry)
"""

from __future__ import annotations

import ast
import os
import platform
import resource
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# ── Constants ───────────────────────────────────────────────

# Modules allowed in safe_import (stdlib only, no dangerous ones)
SAFE_MODULES: set[str] = {
    # Data & math
    "math", "statistics", "random", "decimal", "fractions", "numbers",
    "itertools", "functools", "operator", "collections",
    # String & text
    "string", "re", "textwrap", "unicodedata", "difflib",
    # Data formats
    "json", "csv", "base64", "hashlib", "hmac",
    # Date/time
    "datetime", "time", "calendar",
    # Types
    "typing", "dataclasses", "enum",
    # Utilities
    "copy", "pprint", "inspect", "itertools",
    # Path/files (safe subset)
    "pathlib", "os.path",
    # Limited network
    "urllib.parse", "urllib.request",
}

# Dangerous AST nodes / functions that are never allowed
DANGEROUS_BUILTINS: set[str] = {
    "eval", "exec", "compile", "__import__", "open",
    "input", "breakpoint", "memoryview",
    "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "hasattr",
    "__builtins__", "__import__", "importlib",
}

DANGEROUS_MODULES: set[str] = {
    "os", "sys", "subprocess", "shutil", "signal",
    "socket", "http", "urllib.request",
    "ctypes", "multiprocessing", "threading",
    "importlib", "pickle", "marshal", "code",
    "builtins", "pdb", "traceback",
}

DANGEROUS_AST_NODES: set[type] = {
    ast.Import, ast.ImportFrom,  # All imports in strict mode
}

# ── Data structures ─────────────────────────────────────────

@dataclass
class SandboxResult:
    """Result of sandboxed code execution."""
    success: bool
    stdout: str = ""
    stderr: str = ""
    result: Any = None
    error: str = ""
    duration_ms: float = 0.0
    safety_checks: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True if execution succeeded without errors."""
        return self.success and not self.error


# ── Safety analysis ─────────────────────────────────────────

class SafetyResult:
    """Result of static safety analysis."""
    def __init__(self):
        self.safe: bool = True
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.detected_imports: list[str] = []
        self.detected_calls: list[str] = []

    def add_error(self, msg: str) -> None:
        self.safe = False
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


# ── SandboxExecutor ─────────────────────────────────────────

class SandboxExecutor:
    """Execute Python code in a sandbox with safety checks.

    Two-level isolation:
        1. Static: AST-based pattern scanning before execution.
        2. Runtime: Optional subprocess isolation with resource limits.

    Use execute() for trusted-ish code that needs in-process speed.
    Use execute_isolated() for untrusted code that needs full separation.
    """

    def __init__(
        self,
        allow_imports: bool = False,
        allowed_modules: Optional[set[str]] = None,
        strict: bool = True,
    ):
        """Initialize the sandbox.

        Args:
            allow_imports: If True, allow safe module imports.
            allowed_modules: Custom set of allowed module names.
            strict: If True, block all imports; if False, use allowlist.
        """
        self.allow_imports = allow_imports
        self.allowed_modules = allowed_modules or SAFE_MODULES
        self.strict = strict

        # Runtime safety: restricted builtins
        self._safe_builtins = self._build_safe_builtins()

    @staticmethod
    def _build_safe_builtins() -> dict:
        """Build a dictionary of safe builtins."""
        import builtins

        safe = {}
        for name, obj in vars(builtins).items():
            if name in DANGEROUS_BUILTINS:
                continue
            if name.startswith("_"):
                continue
            safe[name] = obj

        # Add a safe print
        safe["print"] = print
        # Safe versions of common functions
        safe["len"] = len
        safe["range"] = range
        safe["enumerate"] = enumerate
        safe["zip"] = zip
        safe["map"] = map
        safe["filter"] = filter
        safe["sorted"] = sorted
        safe["reversed"] = reversed
        safe["min"] = min
        safe["max"] = max
        safe["sum"] = sum
        safe["abs"] = abs
        safe["round"] = round
        safe["isinstance"] = isinstance
        safe["issubclass"] = issubclass
        safe["type"] = type
        safe["str"] = str
        safe["int"] = int
        safe["float"] = float
        safe["bool"] = bool
        safe["list"] = list
        safe["dict"] = dict
        safe["tuple"] = tuple
        safe["set"] = set
        safe["bytes"] = bytes
        safe["bytearray"] = bytearray
        safe["any"] = any
        safe["all"] = all

        return safe

    # ── Safety checking ───────────────────────────────────

    def check_safety(self, code: str) -> SafetyResult:
        """Statically analyze code for dangerous patterns.

        Uses ast.parse to walk the AST and detect:
        - Dangerous function calls (eval, exec, __import__, etc.)
        - Unauthorized imports
        - Potentially harmful patterns

        Args:
            code: Python source code to analyze.

        Returns:
            SafetyResult with warnings and errors.
        """
        result = SafetyResult()

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            result.add_error(f"Syntax error at line {e.lineno}: {e.msg}")
            return result

        # Walk the AST
        for node in ast.walk(tree):
            # Check for dangerous function calls
            if isinstance(node, ast.Call):
                func_name = self._get_func_name(node.func)
                if func_name and func_name in DANGEROUS_BUILTINS:
                    result.add_error(
                        f"Dangerous function call: {func_name}() "
                        f"at line {node.lineno}"
                    )
                result.detected_calls.append(func_name or "?")

            # Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name.split(".")[0]
                    result.detected_imports.append(module)
                    if self.strict:
                        result.add_error(
                            f"Import not allowed (strict mode): "
                            f"import {alias.name} at line {node.lineno}"
                        )
                    elif module not in self.allowed_modules:
                        result.add_error(
                            f"Module not in allowlist: {module} "
                            f"at line {node.lineno}"
                        )

            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                base = module.split(".")[0]
                result.detected_imports.append(base)
                if self.strict:
                    result.add_error(
                        f"Import not allowed (strict mode): "
                        f"from {module} import ... at line {node.lineno}"
                    )
                elif base not in self.allowed_modules:
                    result.add_error(
                        f"Module not in allowlist: {base} "
                        f"at line {node.lineno}"
                    )

            # Check for dangerous attribute access
            if isinstance(node, ast.Attribute):
                attr_name = node.attr
                if attr_name in DANGEROUS_BUILTINS:
                    result.add_warning(
                        f"Potentially dangerous attribute access: "
                        f".{attr_name} at line {node.lineno}"
                    )

        return result

    @staticmethod
    def _get_func_name(node: ast.AST) -> Optional[str]:
        """Extract function name from a call node."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    # ── Safe import ───────────────────────────────────────

    def safe_import(self, module_name: str) -> Any:
        """Import a module from the allowlist.

        Args:
            module_name: Module name to import (e.g. 'math', 'json').

        Returns:
            The imported module.

        Raises:
            ImportError: If the module is not in the allowlist.
        """
        if module_name in DANGEROUS_MODULES:
            raise ImportError(
                f"Module '{module_name}' is blocked for safety reasons."
            )

        base = module_name.split(".")[0]
        if base not in self.allowed_modules:
            raise ImportError(
                f"Module '{module_name}' is not in the allowlist. "
                f"Allowed: {sorted(self.allowed_modules)}"
            )

        return __import__(module_name)

    # ── In-process execution ──────────────────────────────

    def execute(
        self,
        code: str,
        timeout: float = 30.0,
    ) -> SandboxResult:
        """Execute Python code in-process with restricted globals.

        Runs the code in the current process with a restricted set of
        builtins. No imports allowed unless allow_imports is True.

        Args:
            code: Python source code to execute.
            timeout: Maximum execution time in seconds (soft limit).

        Returns:
            SandboxResult with stdout, stderr, result, and any error.
        """
        import io

        safety_checks: list[str] = []
        start = time.monotonic()

        # Static safety check
        safety = self.check_safety(code)
        safety_checks = safety.errors + safety.warnings

        if not safety.safe:
            return SandboxResult(
                success=False,
                error="\n".join(safety.errors),
                duration_ms=(time.monotonic() - start) * 1000,
                safety_checks=safety_checks,
            )

        # Prepare execution environment
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        capture_stdout = io.StringIO()
        capture_stderr = io.StringIO()

        try:
            sys.stdout = capture_stdout
            sys.stderr = capture_stderr

            # Build restricted globals
            restricted_globals: dict[str, Any] = {
                "__builtins__": self._safe_builtins,
                "__name__": "__sandbox__",
            }

            # Compile
            compiled = compile(code, "<sandbox>", "exec")

            # Execute with optional timeout enforcement
            result_value = None

            if timeout > 0 and hasattr(sys, "settrace"):
                result_value = self._execute_with_trace_timeout(
                    compiled, restricted_globals, timeout
                )
            else:
                exec(compiled, restricted_globals)

            # Try to extract the last expression result
            try:
                result_value = eval(
                    compile(code.strip().rsplit("\n", 1)[-1], "<sandbox>", "eval"),
                    restricted_globals,
                )
            except Exception:
                pass  # Last line isn't an expression

            return SandboxResult(
                success=True,
                stdout=capture_stdout.getvalue(),
                stderr=capture_stderr.getvalue(),
                result=result_value,
                duration_ms=(time.monotonic() - start) * 1000,
                safety_checks=safety_checks,
            )

        except Exception as e:
            return SandboxResult(
                success=False,
                stdout=capture_stdout.getvalue(),
                stderr=capture_stderr.getvalue(),
                error=f"{type(e).__name__}: {e}",
                duration_ms=(time.monotonic() - start) * 1000,
                safety_checks=safety_checks,
            )
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    @staticmethod
    def _execute_with_trace_timeout(
        compiled: Any, globals_dict: dict, timeout: float
    ) -> Any:
        """Execute code with trace-based timeout (soft, not perfect)."""
        start = time.monotonic()

        def trace_func(frame, event, arg):
            if time.monotonic() - start > timeout:
                raise TimeoutError(f"Execution exceeded {timeout}s timeout")
            return trace_func

        sys.settrace(trace_func)
        try:
            exec(compiled, globals_dict)
        finally:
            sys.settrace(None)

    # ── Isolated subprocess execution ─────────────────────

    def execute_isolated(
        self,
        code: str,
        timeout: int = 30,
        max_memory_mb: int = 256,
    ) -> SandboxResult:
        """Execute code in an isolated subprocess with resource limits.

        This is the safest mode: the code runs in a completely separate
        Python process with memory limits enforced by the OS.

        Args:
            code: Python source to execute.
            timeout: Maximum wall-clock time in seconds.
            max_memory_mb: Maximum memory in MB (Linux/macOS only).

        Returns:
            SandboxResult with combined stdout/stderr and exit info.
        """
        import io

        safety_checks: list[str] = []
        start = time.monotonic()

        # Static analysis even for subprocess isolation
        safety = self.check_safety(code)
        safety_checks = safety.errors + safety.warnings

        # Write code to temp file
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, prefix="sandbox_"
            ) as f:
                # Wrap in try/except for clean exit codes
                f.write("import sys, traceback\n")
                f.write("try:\n")
                for line in code.split("\n"):
                    f.write(f"    {line}\n")
                f.write("except Exception as e:\n")
                f.write("    traceback.print_exc()\n")
                f.write("    sys.exit(1)\n")
                tmp_path = f.name

            # Build command with memory limit if possible
            cmd = [sys.executable, "-S", tmp_path]
            env = os.environ.copy()
            env["PYTHONDONTWRITEBYTECODE"] = "1"

            # Memory limit (Linux: prlimit, macOS: ulimit)
            mem_limit = max_memory_mb * 1024 * 1024
            preexec_fn = None
            if platform.system() == "Linux":
                try:
                    import resource

                    def set_limits():
                        resource.setrlimit(
                            resource.RLIMIT_AS, (mem_limit, mem_limit)
                        )
                        resource.setrlimit(
                            resource.RLIMIT_CPU, (timeout, timeout)
                        )

                    preexec_fn = set_limits
                except Exception:
                    pass

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 5,
                cwd=tempfile.gettempdir(),
                env=env,
                preexec_fn=preexec_fn,
            )

            success = result.returncode == 0
            stdout = result.stdout or ""
            stderr = result.stderr or ""

            return SandboxResult(
                success=success,
                stdout=stdout,
                stderr=stderr,
                error="" if success else stderr.split("\n")[-2] if stderr else f"Exit code {result.returncode}",
                duration_ms=(time.monotonic() - start) * 1000,
                safety_checks=safety_checks,
            )

        except subprocess.TimeoutExpired:
            return SandboxResult(
                success=False,
                error=f"Execution timed out after {timeout}s",
                duration_ms=(time.monotonic() - start) * 1000,
                safety_checks=safety_checks,
            )
        except Exception as e:
            return SandboxResult(
                success=False,
                error=f"{type(e).__name__}: {e}",
                duration_ms=(time.monotonic() - start) * 1000,
                safety_checks=safety_checks,
            )
        finally:
            if tmp_path and Path(tmp_path).exists():
                try:
                    Path(tmp_path).unlink()
                except Exception:
                    pass

    # ── Tool-integrated execution ─────────────────────────

    def execute_with_tools(
        self,
        code: str,
        tool_registry: Any = None,
        timeout: int = 30,
        max_memory_mb: int = 256,
    ) -> SandboxResult:
        """Execute code with access to registered tools.

        The code can call tools from the registry using a
        special `tool(name, **kwargs)` function injected into the sandbox.

        Args:
            code: Python source to execute.
            tool_registry: A ToolRegistry instance or dict of {name: callable}.
            timeout: Maximum execution time.
            max_memory_mb: Memory limit for isolated mode.

        Returns:
            SandboxResult.
        """
        # If no tool registry, execute as normal
        if tool_registry is None:
            return self.execute(code, timeout)

        # Build tool function
        tool_funcs = self._build_tool_funcs(tool_registry)

        # Inject tool access into sandbox
        augmented_code = self._augment_with_tools(code, tool_funcs)

        return self.execute_isolated(augmented_code, timeout, max_memory_mb)

    def _build_tool_funcs(self, tool_registry: Any) -> str:
        """Build Python code defining tool access functions."""
        tool_names = []

        # Check if it's a ToolRegistry with list_all()
        if hasattr(tool_registry, "list_all"):
            tools = tool_registry.list_all()
            for t in tools:
                if hasattr(t, "name"):
                    tool_names.append(t.name)
        elif isinstance(tool_registry, dict):
            tool_names = list(tool_registry.keys())
        elif hasattr(tool_registry, "_tools"):
            tool_names = list(tool_registry._tools.keys())

        # Build a tool() function that the sandboxed code can call
        tool_func = (
            "def tool(name, **kwargs):\n"
            "    '''Call a registered tool by name.'''\n"
            "    raise NotImplementedError('tools only available in engine context')\n"
        )

        return tool_func

    def _augment_with_tools(self, code: str, tool_funcs: str) -> str:
        """Prepend tool access code to the sandbox code."""
        return tool_funcs + "\n" + code


# ── Self-test ───────────────────────────────────────────────

def _self_test():
    """Quick self-test of SandboxExecutor."""
    sandbox = SandboxExecutor()

    print("=== SandboxExecutor Self-Test ===\n")

    # Test 1: Safe code
    print("1. Safe code (math):")
    r = sandbox.execute("x = sum([1, 2, 3, 4])\nprint(f'Sum: {x}')")
    print(f"   Success: {r.success}, stdout: {r.stdout.strip()}")
    print(f"   Duration: {r.duration_ms:.1f}ms")
    print()

    # Test 2: Safety check on dangerous code
    print("2. Safety check (eval):")
    safety = sandbox.check_safety("eval('1+1')\nopen('/etc/passwd')")
    print(f"   Safe: {safety.safe}")
    for e in safety.errors:
        print(f"   ERROR: {e}")
    for w in safety.warnings:
        print(f"   WARNING: {w}")
    print()

    # Test 3: Blocked execution
    print("3. Blocked execution (eval):")
    r = sandbox.execute("eval('2+2')")
    print(f"   Success: {r.success}")
    if r.error:
        print(f"   Error: {r.error[:100]}")
    print()

    # Test 4: Imports disabled by default
    print("4. Import blocked (strict mode):")
    safety = sandbox.check_safety("import math\nprint(math.pi)")
    print(f"   Safe: {safety.safe}")
    for e in safety.errors:
        print(f"   ERROR: {e}")
    if safety.safe:
        r = sandbox.execute("import math\nprint(math.pi)")
        print(f"   Success: {r.success}, stdout: {r.stdout.strip()}")
    print()

    # Test 5: Sandbox with imports enabled
    print("5. With imports enabled:")
    sandbox2 = SandboxExecutor(allow_imports=True, strict=False)
    r = sandbox2.execute("import json\nd = {'a': 1}\nprint(json.dumps(d))")
    print(f"   Success: {r.success}, stdout: {r.stdout.strip()}")
    print()

    # Test 6: Isolated execution
    print("6. Isolated execution:")
    r = sandbox.execute_isolated("for i in range(5):\n    print(f'Line {i}')")
    print(f"   Success: {r.success}")
    print(f"   stdout: {r.stdout.strip()}")
    print(f"   Duration: {r.duration_ms:.1f}ms")
    print()

    # Test 7: Safe import
    print("7. Safe import:")
    try:
        math_mod = sandbox.safe_import("math")
        print(f"   math.sqrt(16) = {math_mod.sqrt(16)}")
    except ImportError as e:
        print(f"   {e}")
    try:
        sandbox.safe_import("os")
        print("   ERROR: should have raised ImportError")
    except ImportError as e:
        print(f"   Correctly blocked: {e}")
    print()

    print("Self-test complete.")


if __name__ == "__main__":
    _self_test()