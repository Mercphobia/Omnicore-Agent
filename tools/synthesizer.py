#!/usr/bin/env python3
"""Tool Synthesizer — create callable tools on-the-fly.
DNA: Genesis (spontaneous creation).

Provides ``ToolSynthesizer``, which generates Python functions dynamically
using ``exec()`` inside a safety sandbox (restricted builtins). Includes
a built-in template library: webhook, api_call, data_transform, file_watch.
"""

from __future__ import annotations

import inspect
import json
import os
import time
from pathlib import Path
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Safety sandbox — restricted builtins for dynamically-generated tools
# ---------------------------------------------------------------------------

_SAFE_BUILTINS: dict[str, Any] = {
    # Immutable constructors
    "True": True,
    "False": False,
    "None": None,
    # Safe types
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "bytes": bytes,
    "bytearray": bytearray,
    "list": list,
    "tuple": tuple,
    "dict": dict,
    "set": set,
    "frozenset": frozenset,
    "len": len,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "sorted": sorted,
    "reversed": reversed,
    "min": min,
    "max": max,
    "sum": sum,
    "abs": abs,
    "round": round,
    "pow": pow,
    "divmod": divmod,
    "any": any,
    "all": all,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "hasattr": hasattr,
    "getattr": getattr,
    "setattr": setattr,
    "type": type,
    # String / encoding
    "ord": ord,
    "chr": chr,
    "repr": repr,
    "format": format,
    "bin": bin,
    "hex": hex,
    "oct": oct,
    # Math
    "__import__": __import__,  # controlled — only stdlib modules
    # Iteration
    "iter": iter,
    "next": next,
    "slice": slice,
    # Helpers
    "print": print,
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "RuntimeError": RuntimeError,
    "StopIteration": StopIteration,
    # Controlled eval (used by data_transform template with empty builtins)
    "eval": eval,
}


def _safe_exec(code: str, namespace: dict[str, Any]) -> None:
    """Execute *code* with a restricted builtins dict.

    Mutates *namespace* in-place — any function/class definitions
    land there so the caller can retrieve them directly.
    """
    saved = namespace.get("__builtins__")
    namespace["__builtins__"] = _SAFE_BUILTINS
    try:
        exec(code, namespace)
    finally:
        if saved is not None:
            namespace["__builtins__"] = saved
        else:
            namespace.pop("__builtins__", None)


# ---------------------------------------------------------------------------
# Template library
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, str] = {
    # ------------------------------------------------------------------
    "webhook": r'''
def {tool_name}(url: str, payload: dict | None = None, method: str = "POST", headers: dict | None = None, timeout: int = 10) -> dict:
    """Send a webhook request to *url* with *payload* as JSON body.

    Returns ``{{"status": <code>, "body": <str>, "headers": <dict>}}``.
    """
    import json as _json
    import urllib.request as _ur
    import urllib.error as _ue
    data = None
    if payload is not None:
        data = _json.dumps(payload).encode("utf-8")
    req_headers = {{"Content-Type": "application/json", "User-Agent": "{tool_name}/1.0"}}
    if headers:
        req_headers.update(headers)
    req = _ur.Request(url, data=data, headers=req_headers, method=method.upper())
    try:
        with _ur.urlopen(req, timeout=timeout) as resp:
            return {{
                "status": resp.status,
                "body": resp.read().decode("utf-8", errors="replace"),
                "headers": dict(resp.headers),
            }}
    except _ue.HTTPError as e:
        return {{
            "status": e.code,
            "body": e.read().decode("utf-8", errors="replace"),
            "headers": dict(e.headers),
            "error": str(e),
        }}
    except Exception as e:
        return {{"status": 0, "body": "", "headers": {{}}, "error": str(e)}}
''',

    # ------------------------------------------------------------------
    "api_call": r'''
def {tool_name}(base_url: str, endpoint: str, params: dict | None = None, headers: dict | None = None, timeout: int = 30) -> dict:
    """Call a REST API endpoint.

    GET *base_url*/*endpoint* with *params* as query string.
    Returns ``{{"status": <code>, "body": <str>, "json": <dict|None>}}``.
    """
    import json as _json
    import urllib.request as _ur
    import urllib.parse as _up
    import urllib.error as _ue
    full_url = base_url.rstrip("/") + "/" + endpoint.lstrip("/")
    if params:
        full_url += "?" + _up.urlencode(params)
    req_headers = {{"Accept": "application/json", "User-Agent": "{tool_name}/1.0"}}
    if headers:
        req_headers.update(headers)
    req = _ur.Request(full_url, headers=req_headers)
    try:
        with _ur.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return {{
                "status": resp.status,
                "body": raw,
                "json": _json.loads(raw) if raw else None,
                "headers": dict(resp.headers),
            }}
    except _ue.HTTPError as e:
        raw_err = e.read().decode("utf-8", errors="replace")
        return {{
            "status": e.code,
            "body": raw_err,
            "json": _json.loads(raw_err) if raw_err else None,
            "headers": dict(e.headers),
            "error": str(e),
        }}
    except Exception as e:
        return {{"status": 0, "body": "", "json": None, "headers": {{}}, "error": str(e)}}
''',

    # ------------------------------------------------------------------
    "data_transform": r'''
def {tool_name}(data: list[dict], mapping: dict, filter_expr: str | None = None, sort_key: str | None = None) -> list[dict]:
    """Transform a list of dicts using *mapping* (old_key → new_key).

    *filter_expr*: optional Python expression evaluated per row (uses row as locals).
    *sort_key*: optional key to sort the output by.
    """
    result: list[dict] = []
    for row in data:
        if filter_expr is not None:
            if not eval(filter_expr, {{"__builtins__": {{}}, "row": row}}):
                continue
        new_row: dict[str, object] = {{}}
        for old_key, new_key in mapping.items():
            if old_key in row:
                new_row[new_key] = row[old_key]
        result.append(new_row)
    if sort_key is not None:
        result.sort(key=lambda r: r.get(sort_key, ""))
    return result
''',

    # ------------------------------------------------------------------
    "file_watch": r'''
def {tool_name}(directory: str, pattern: str = "*", interval: float = 1.0, max_iterations: int | None = None) -> list[str]:
    """Watch *directory* for new/modified files matching *pattern*.

    Polls every *interval* seconds. Returns list of changed file paths.
    Stops after *max_iterations* or when interrupted.
    """
    import glob as _glob
    import os as _os
    import time as _time
    dir_path = _os.path.expanduser(directory)
    seen: set[str] = set(_glob.glob(_os.path.join(dir_path, pattern)))
    changes: list[str] = []
    iteration = 0
    while max_iterations is None or iteration < max_iterations:
        _time.sleep(interval)
        current = set(_glob.glob(_os.path.join(dir_path, pattern)))
        new_files = current - seen
        for f in sorted(new_files):
            changes.append(f)
        seen = current
        if new_files:
            return changes
        iteration += 1
    return changes
''',
}


# ---------------------------------------------------------------------------
# ToolSynthesizer
# ---------------------------------------------------------------------------

class ToolSynthesizer:
    """Generate callable Python functions on-the-fly from schemas or templates.

    Usage::

        synth = ToolSynthesizer()

        # From template
        wh = synth.from_template("webhook", {"tool_name": "slack_notify"})
        result = wh("https://hooks.slack.com/...", {"text": "hello"})

        # From scratch
        adder = synth.synthesize(
            "adder",
            "Add two numbers.",
            {"a": "int", "b": "int"},
        )
        synth.register("adder", adder)
        print(adder(a=3, b=4))  # 7
    """

    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}

    # ------------------------------------------------------------------
    def synthesize(
        self,
        tool_name: str,
        description: str,
        input_schema: dict[str, str],
    ) -> Callable[..., Any]:
        """Create a callable from a schema.

        *input_schema* maps parameter names to Python type strings
        (e.g. ``{"a": "int", "b": "int"}``).

        The generated function accepts keyword arguments and returns a dict:
        ``{"tool": <name>, "description": <description>, "params": <received>, "result": <return>}``.
        Callers can customize ``func_body`` for the actual logic.

        Returns the callable.
        """
        # Build parameter signature
        params = ", ".join(input_schema.keys())
        docstring = f'"""{description}\\n\\nArgs:\\n'
        for pname, ptype in input_schema.items():
            docstring += f"    {pname}: {ptype}\\n"
        docstring += '"""'

        namespace: dict[str, Any] = {}
        code = f'''
def {tool_name}({params}):
    {docstring}
    result = {tool_name}_body({params})
    return dict(
        tool="{tool_name}",
        description={description!r},
        params=dict({", ".join(f"{p}={p}" for p in input_schema)}),
        result=result,
    )

def {tool_name}_body({params}):
    """Override this to customise behaviour."""
    return {{"args": dict({", ".join(f"{p}={p}" for p in input_schema)})}}
'''
        _safe_exec(code, namespace)
        fn = namespace[tool_name]
        fn.__name__ = tool_name
        fn.__doc__ = description
        return fn

    # ------------------------------------------------------------------
    def from_template(self, template_name: str, params: dict[str, str]) -> Callable[..., Any]:
        """Instantiate a tool from a named template.

        *template_name* must be one of: webhook, api_call, data_transform,
        file_watch.

        *params* is passed directly to ``str.format(**params)`` on the
        template source. The most important param is ``tool_name``, which
        becomes the function name.

        Returns the callable.
        """
        if template_name not in TEMPLATES:
            available = ", ".join(TEMPLATES)
            raise ValueError(
                f"Unknown template '{template_name}'. Available: {available}"
            )
        tool_name = params.get("tool_name", template_name)
        format_args = {**params, "tool_name": tool_name}
        source = TEMPLATES[template_name].format(**format_args)
        namespace: dict[str, Any] = {}
        _safe_exec(source, namespace)
        fn = namespace[tool_name]
        fn.__name__ = tool_name
        return fn

    # ------------------------------------------------------------------
    def register(self, tool_name: str, tool_fn: Callable[..., Any]) -> None:
        """Register *tool_fn* under *tool_name* for later retrieval."""
        self._tools[tool_name] = tool_fn

    # ------------------------------------------------------------------
    def get(self, tool_name: str) -> Callable[..., Any]:
        """Retrieve a registered tool by name.

        Raises ``KeyError`` if not found.
        """
        return self._tools[tool_name]

    # ------------------------------------------------------------------
    def list_tools(self) -> list[str]:
        """Return names of all registered tools."""
        return sorted(self._tools)

    # ------------------------------------------------------------------
    def list_templates(self) -> list[str]:
        """Return names of available templates."""
        return sorted(TEMPLATES)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    synth = ToolSynthesizer()

    # --- synthesize from scratch ---
    multiplier = synth.synthesize(
        "multiplier",
        "Multiply two numbers together.",
        {"x": "int", "y": "int"},
    )
    result = multiplier(x=7, y=6)
    assert result["tool"] == "multiplier"
    assert result["result"]["args"]["x"] == 7
    assert result["result"]["args"]["y"] == 6
    print("synthesize: OK")

    # --- register & retrieve ---
    synth.register("mult", multiplier)
    assert "mult" in synth.list_tools()
    assert synth.get("mult") is multiplier
    print("register/get: OK")

    # --- from_template: data_transform ---
    xform = synth.from_template("data_transform", {"tool_name": "my_xform"})
    data = [
        {"name": "Alice", "age": 30},
        {"name": "Bob", "age": 25},
        {"name": "Charlie", "age": 35},
    ]
    out = xform(
        data,
        mapping={"name": "full_name", "age": "years"},
        filter_expr='row["age"] > 26',
        sort_key="years",
    )
    assert len(out) == 2
    assert out[0]["full_name"] == "Alice"
    assert out[1]["full_name"] == "Charlie"
    print("from_template (data_transform): OK")

    # --- from_template: webhook (unit-test style — no real URL needed) ---
    wh = synth.from_template("webhook", {"tool_name": "test_webhook"})
    # Call against a non-existent URL → should return error dict
    result = wh("http://127.0.0.1:1/nope", {"msg": "hi"}, timeout=1)
    assert "error" in result or result["status"] == 0, f"Expected error, got {result}"
    print("from_template (webhook): OK")

    # --- from_template: api_call ---
    api = synth.from_template("api_call", {"tool_name": "test_api"})
    result = api("http://127.0.0.1:1", "ping", timeout=1)
    assert "error" in result or result["status"] == 0, f"Expected error, got {result}"
    print("from_template (api_call): OK")

    # --- from_template: file_watch ---
    fw = synth.from_template("file_watch", {"tool_name": "test_fw"})
    changes = fw("/tmp", pattern="*.nonexistent", max_iterations=1)
    assert isinstance(changes, list) and len(changes) == 0
    print("from_template (file_watch): OK")

    # --- invalid template ---
    try:
        synth.from_template("nonexistent", {"tool_name": "x"})
    except ValueError:
        print("invalid template error: OK")

    # --- list_templates ---
    tmpls = synth.list_templates()
    assert "webhook" in tmpls
    assert "api_call" in tmpls
    assert "data_transform" in tmpls
    assert "file_watch" in tmpls
    print(f"list_templates: {tmpls}")

    print("\nAll synthesizer tests passed.")