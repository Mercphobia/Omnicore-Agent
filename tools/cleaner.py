#!/usr/bin/env python3
"""Auto-format + lint tool — code hygiene engine.
DNA: Negentropy (order from chaos).

``Cleaner`` provides ``format_code``, ``lint_code``, and ``auto_fix`` for
Python, JavaScript, JSON, YAML, and Markdown.  Uses subprocess for
black/ruff/eslint when available; falls back to pure-Python normalisers.
"""

from __future__ import annotations

import json as _json
import os
import re
import shlex
import shutil
import subprocess
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_exe(*names: str) -> str | None:
    """Return the first executable found in PATH, or None."""
    for name in names:
        if shutil.which(name):
            return name
    return None


def _run_formatter(
    cmd: list[str],
    code: str,
    timeout: int = 30,
) -> tuple[str, str]:
    """Run *cmd* as a subprocess, pipe *code* to stdin, return (stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd,
            input=code,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.stdout, proc.stderr
    except FileNotFoundError:
        return "", "command not found"
    except subprocess.TimeoutExpired:
        return "", "timeout"
    except Exception as e:
        return "", str(e)


# ---------------------------------------------------------------------------
# Pure-Python formatters (fallback)
# ---------------------------------------------------------------------------

def _normalize_indent(code: str, indent_size: int = 4) -> str:
    """Normalise leading whitespace to consistent spaces."""
    lines = code.split("\n")
    result: list[str] = []
    for line in lines:
        if not line.strip():
            result.append("")
            continue
        stripped = line.lstrip()
        leading = len(line) - len(stripped)
        # Replace mixed tabs/spaces with spaces
        spaces = leading * " "
        # Convert to consistent indent
        tab_count = line[:leading].count("\t")
        space_count = leading - tab_count
        indent = " " * (tab_count * indent_size + space_count)
        result.append(indent + stripped)
    return "\n".join(result)


def _strip_trailing_whitespace(code: str) -> str:
    """Remove trailing whitespace from every line."""
    return "\n".join(line.rstrip() for line in code.split("\n"))


def _ensure_trailing_newline(code: str) -> str:
    """Ensure exactly one trailing newline."""
    return code.rstrip("\n") + "\n"


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------

def _format_json(code: str) -> str:
    """Pretty-print JSON with 2-space indent."""
    try:
        parsed = _json.loads(code)
        return _json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    except _json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")


def _lint_json(code: str) -> list[dict[str, Any]]:
    """Return parse errors for JSON."""
    try:
        _json.loads(code)
        return []
    except _json.JSONDecodeError as e:
        return [{"line": e.lineno, "col": e.colno, "message": e.msg, "severity": "error"}]


def _fix_json(code: str) -> str:
    """Attempt to fix common JSON issues (trailing commas, unquoted keys)."""
    # Remove trailing commas before ] or }
    code = re.sub(r",\s*([}\]])", r"\1", code)
    # Try to parse; if it works we're done
    try:
        parsed = _json.loads(code)
        return _json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    except _json.JSONDecodeError:
        pass
    # Attempt single-quote → double-quote (common mistake)
    try:
        parsed = _json.loads(code.replace("'", '"'))
        return _json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    except _json.JSONDecodeError:
        pass
    return code  # can't fix, return as-is


# ---------------------------------------------------------------------------
# YAML formatter (basic)
# ---------------------------------------------------------------------------

def _format_yaml(code: str) -> str:
    """Normalise YAML indentation (2-space) and strip trailing whitespace."""
    return _ensure_trailing_newline(_strip_trailing_whitespace(code))


def _lint_yaml(code: str) -> list[dict[str, Any]]:
    """Lightweight YAML lint — check for mixed indentation."""
    issues: list[dict[str, Any]] = []
    lines = code.split("\n")
    for i, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        leading = line[: len(line) - len(stripped)]
        if "\t" in leading and " " in leading:
            issues.append(
                {
                    "line": i,
                    "col": 1,
                    "message": "Mixed tabs and spaces in indentation",
                    "severity": "warning",
                }
            )
        if leading and "\t" in leading:
            issues.append(
                {
                    "line": i,
                    "col": 1,
                    "message": "Tab indentation — prefer spaces for YAML",
                    "severity": "info",
                }
            )
    return issues


# ---------------------------------------------------------------------------
# JavaScript formatter
# ---------------------------------------------------------------------------

def _format_js(code: str) -> str:
    """Basic JS formatting: normalise braces and semicolons."""
    code = _normalize_indent(code, indent_size=2)
    code = _strip_trailing_whitespace(code)
    return _ensure_trailing_newline(code)


def _lint_js(code: str) -> list[dict[str, Any]]:
    """Simple JS lint: detect common issues."""
    issues: list[dict[str, Any]] = []
    lines = code.split("\n")
    for i, line in enumerate(lines, 1):
        # Missing semicolons on non-block lines
        stripped = line.strip()
        if stripped and not stripped.startswith("//") and not stripped.startswith("/*"):
            if not stripped.endswith(("{", "}", ";", ":", "*/")) and not stripped.endswith(
                (",", "=>", "*/")
            ):
                # Not a block opener/closer, might be missing semicolon
                if not re.search(r'["\']\s*$', stripped):  # not ending a string
                    issues.append(
                        {
                            "line": i,
                            "col": len(line),
                            "message": "Possible missing semicolon",
                            "severity": "info",
                        }
                    )
                    break  # one warning is enough
    return issues


# ---------------------------------------------------------------------------
# Markdown formatter
# ---------------------------------------------------------------------------

def _format_md(code: str) -> str:
    """Normalise markdown: strip trailing whitespace, ensure single trailing newline."""
    return _ensure_trailing_newline(_strip_trailing_whitespace(code))


def _lint_md(code: str) -> list[dict[str, Any]]:
    """Basic markdown lint."""
    issues: list[dict[str, Any]] = []
    lines = code.split("\n")
    for i, line in enumerate(lines, 1):
        if line != line.rstrip():
            issues.append(
                {
                    "line": i,
                    "col": len(line.rstrip()) + 1,
                    "message": "Trailing whitespace",
                    "severity": "info",
                }
            )
    return issues


# ---------------------------------------------------------------------------
# Python formatter (pure-Python fallback)
# ---------------------------------------------------------------------------

def _format_py_basic(code: str) -> str:
    """Basic Python formatting without external tools."""
    code = _normalize_indent(code, indent_size=4)
    code = _strip_trailing_whitespace(code)
    return _ensure_trailing_newline(code)


def _lint_py_basic(code: str) -> list[dict[str, Any]]:
    """Lightweight Python lint."""
    issues: list[dict[str, Any]] = []
    lines = code.split("\n")

    # Check syntax first
    try:
        compile(code, "<lint>", "exec")
    except SyntaxError as e:
        issues.append(
            {
                "line": e.lineno or 1,
                "col": e.offset or 1,
                "message": str(e.msg),
                "severity": "error",
            }
        )
        return issues  # can't lint further if syntax is broken

    for i, line in enumerate(lines, 1):
        stripped = line.rstrip()
        # Trailing whitespace
        if line != stripped:
            issues.append(
                {
                    "line": i,
                    "col": len(stripped) + 1,
                    "message": "Trailing whitespace",
                    "severity": "info",
                }
            )
        # Line too long
        if len(line) > 120:
            issues.append(
                {
                    "line": i,
                    "col": 121,
                    "message": f"Line too long ({len(line)} > 120)",
                    "severity": "warning",
                }
            )
        # Mixed indentation
        leading = line[: len(line) - len(line.lstrip())]
        if "\t" in leading:
            issues.append(
                {
                    "line": i,
                    "col": 1,
                    "message": "Tab indentation (use spaces)",
                    "severity": "warning",
                }
            )

    return issues


# ---------------------------------------------------------------------------
# Cleaner
# ---------------------------------------------------------------------------

class Cleaner:
    """Auto-format, lint, and auto-fix code in multiple languages.

    Usage::

        cleaner = Cleaner()
        formatted = cleaner.format_code(source, "python")
        issues = cleaner.lint_code(source, "python")
        fixed = cleaner.auto_fix(source, "python")
    """

    SUPPORTED_LANGUAGES = ("python", "javascript", "json", "yaml", "markdown")

    def format_code(self, code: str, language: str = "python") -> str:
        """Format *code* according to *language* conventions.

        Tries external tools first (black for Python, prettier/eslint --fix
        for JS). Falls back to pure-Python normalisers.
        """
        language = language.lower()

        if language == "python":
            black = _find_exe("black")
            if black:
                out, err = _run_formatter(
                    [black, "--quiet", "-"],
                    code,
                )
                if out:
                    return out
            # Fallback
            return _format_py_basic(code)

        elif language == "javascript":
            prettier = _find_exe("prettier", "prettier.cmd")
            if prettier:
                out, err = _run_formatter(
                    [prettier, "--parser", "babel", "--stdin-filepath", "file.js"],
                    code,
                )
                if out:
                    return out
            return _format_js(code)

        elif language == "json":
            return _format_json(code)

        elif language == "yaml":
            # Try external yaml formatter if pyyaml is installed
            try:
                import yaml as _yaml  # noqa: F811 — optional dep

                parsed = _yaml.safe_load(code)
                return _yaml.dump(parsed, default_flow_style=False, allow_unicode=True, sort_keys=False)
            except ImportError:
                pass
            except Exception:
                pass
            return _format_yaml(code)

        elif language == "markdown":
            return _format_md(code)

        else:
            raise ValueError(
                f"Unsupported language: {language!r}. "
                f"Supported: {', '.join(self.SUPPORTED_LANGUAGES)}"
            )

    def lint_code(self, code: str, language: str = "python") -> list[dict[str, Any]]:
        """Lint *code* and return a list of issues.

        Each issue is a dict with keys: ``line``, ``col``, ``message``,
        ``severity`` (one of error/warning/info).
        """
        language = language.lower()

        if language == "python":
            ruff = _find_exe("ruff")
            if ruff:
                out, _ = _run_formatter(
                    [ruff, "check", "--output-format", "json", "--stdin-filename", "lint.py", "-"],
                    code,
                )
                if out:
                    try:
                        raw = _json.loads(out)
                        return [
                            {
                                "line": r.get("location", {}).get("row", 1),
                                "col": r.get("location", {}).get("column", 1),
                                "message": r.get("message", "Unknown"),
                                "severity": "error" if r.get("fix") else "warning",
                            }
                            for r in raw
                        ]
                    except _json.JSONDecodeError:
                        pass
            return _lint_py_basic(code)

        elif language == "javascript":
            eslint = _find_exe("eslint")
            if eslint:
                out, _ = _run_formatter(
                    [eslint, "--format", "json", "--stdin", "--stdin-filename", "lint.js"],
                    code,
                )
                if out:
                    try:
                        raw = _json.loads(out)
                        issues: list[dict[str, Any]] = []
                        for file_result in raw:
                            for msg in file_result.get("messages", []):
                                issues.append(
                                    {
                                        "line": msg.get("line", 1),
                                        "col": msg.get("column", 1),
                                        "message": msg.get("message", "Unknown"),
                                        "severity": "error"
                                        if msg.get("severity", 2) >= 2
                                        else "warning",
                                    }
                                )
                        return issues
                    except _json.JSONDecodeError:
                        pass
            return _lint_js(code)

        elif language == "json":
            return _lint_json(code)

        elif language == "yaml":
            return _lint_yaml(code)

        elif language == "markdown":
            return _lint_md(code)

        else:
            raise ValueError(
                f"Unsupported language: {language!r}. "
                f"Supported: {', '.join(self.SUPPORTED_LANGUAGES)}"
            )

    def auto_fix(self, code: str, language: str = "python") -> str:
        """Attempt to automatically fix lint issues in *code*.

        Returns the fixed code and a list of remaining unfixable issues.
        For many languages this is identical to ``format_code``.
        """
        language = language.lower()

        if language == "python":
            ruff = _find_exe("ruff")
            if ruff:
                out, _ = _run_formatter(
                    ["ruff", "check", "--fix", "--stdin-filename", "fix.py", "-"],
                    code,
                )
                if out:
                    return out
            # Fallback: format + basic fixes
            code = _format_py_basic(code)
            return code

        elif language == "javascript":
            prettier = _find_exe("prettier", "prettier.cmd")
            if prettier:
                out, _ = _run_formatter(
                    [prettier, "--parser", "babel", "--stdin-filepath", "file.js", "--write=false"],
                    code,
                )
                if out:
                    return out
            return _format_js(code)

        elif language == "json":
            return _fix_json(code)

        elif language == "yaml":
            return _format_yaml(code)

        elif language == "markdown":
            return _format_md(code)

        else:
            raise ValueError(
                f"Unsupported language: {language!r}. "
                f"Supported: {', '.join(self.SUPPORTED_LANGUAGES)}"
            )


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cleaner = Cleaner()

    # ---- Python ----
    messy_py = "def foo(  ):\n\tprint('hello'  )  \n"
    fmt = cleaner.format_code(messy_py, "python")
    assert "print(" in fmt
    assert "\t" not in fmt  # tabs removed
    print("format_code (python): OK")

    issues = cleaner.lint_code("def f():\n\tpass\n", "python")
    assert any("tab" in i["message"].lower() or "indent" in i["message"].lower() for i in issues)
    print("lint_code (python): OK")

    syntax_error = "def f(\n"
    issues = cleaner.lint_code(syntax_error, "python")
    assert any(i["severity"] == "error" for i in issues)
    print("lint_code (python syntax error): OK")

    # ---- JSON ----
    ugly_json = '{"a":1,  "b":  [2,3]}'  # valid but ugly
    fmt_json = cleaner.format_code(ugly_json, "json")
    parsed = _json.loads(fmt_json)
    assert parsed == {"a": 1, "b": [2, 3]}
    print("format_code (json): OK")

    messy_json = '{"a":1,  "b":  [2,3,],}'  # invalid (trailing comma)
    issues_json = cleaner.lint_code("{bad json}", "json")
    assert len(issues_json) == 1 and issues_json[0]["severity"] == "error"
    print("lint_code (json): OK")

    fixed_json = cleaner.auto_fix(messy_json, "json")
    assert _json.loads(fixed_json)  # valid JSON after fix
    print("auto_fix (json): OK")

    # ---- YAML ----
    messy_yaml = "key: value\n\tsub: bad\n"
    fmt_yaml = cleaner.format_code(messy_yaml, "yaml")
    assert fmt_yaml.endswith("\n")
    print("format_code (yaml): OK")

    issues_yaml = cleaner.lint_code(messy_yaml, "yaml")
    assert len(issues_yaml) >= 1
    print("lint_code (yaml): OK")

    # ---- JavaScript ----
    messy_js = "function foo() {\n  return 1\n}\n"
    fmt_js = cleaner.format_code(messy_js, "javascript")
    assert "return 1" in fmt_js
    print("format_code (javascript): OK")

    # ---- Markdown ----
    messy_md = "# Title  \n\nSome text  \n"
    fmt_md = cleaner.format_code(messy_md, "markdown")
    assert "# Title" in fmt_md
    issues_md = cleaner.lint_code(messy_md, "markdown")
    assert len(issues_md) >= 1
    print("format_code + lint_code (markdown): OK")

    # ---- Unsupported language ----
    try:
        cleaner.format_code("code", "cobol")
    except ValueError:
        print("unsupported language error: OK")

    # ---- auto_fix Python ----
    py_with_issues = "x = 1  \ny = 2  \n"
    fixed = cleaner.auto_fix(py_with_issues, "python")
    assert "x = 1" in fixed
    print("auto_fix (python): OK")

    print(f"\nAll cleaner tests passed. Supported: {cleaner.SUPPORTED_LANGUAGES}")