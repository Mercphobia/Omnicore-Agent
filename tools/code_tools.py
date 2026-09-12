"""Code analysis tools — AST parsing, linting, formatting.
DNA: Cursor (multi-file context) + Copilot (PR review).
"""

import subprocess
from pathlib import Path


def analyze_code(file_path: str) -> str:
    """Analyze a Python file for structure, complexity, issues."""
    p = Path(file_path).expanduser().resolve()
    if not p.exists():
        return f"File not found: {file_path}"
    
    try:
        code = p.read_text()
    except Exception as e:
        return f"Error reading: {e}"

    lines = code.split("\n")
    total_lines = len(lines)
    
    # Count functions, classes, imports
    import ast
    try:
        tree = ast.parse(code)
        functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        imports = [node.names[0].name for node in ast.walk(tree) if isinstance(node, ast.Import)]
        from_imports = [f"{node.module}.{n.name}" for node in ast.walk(tree) 
                       if isinstance(node, ast.ImportFrom) for n in node.names]
    except SyntaxError as e:
        return f"Syntax error at line {e.lineno}: {e.msg}"

    # Complexity: count lines with high indentation
    deep_lines = sum(1 for line in lines if line.startswith("        "))  # 8+ spaces
    
    # Comment ratio
    comments = sum(1 for line in lines if line.strip().startswith("#"))
    comment_ratio = comments / total_lines if total_lines else 0

    report = f"""Code Analysis: {p.name}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Lines: {total_lines}
Functions: {len(functions)} ({', '.join(functions[:10])}{'...' if len(functions) > 10 else ''})
Classes: {len(classes)} ({', '.join(classes[:5])}{'...' if len(classes) > 5 else ''})
Imports: {len(imports) + len(from_imports)}
Comment ratio: {comment_ratio:.1%}
Deep indentation lines: {deep_lines}
"""
    
    # Warnings
    if comment_ratio < 0.05:
        report += "\n⚠ Low comment ratio — consider adding docstrings"
    if deep_lines > total_lines * 0.3:
        report += "\n⚠ High nesting depth — consider refactoring deeply nested code"
    if len(functions) == 0 and len(classes) == 0:
        report += "\n⚠ No functions or classes defined"
    
    return report


def lint_code(file_path: str) -> str:
    """Run Python linter (ruff or flake8)."""
    p = Path(file_path).expanduser().resolve()
    if not p.exists():
        return f"File not found: {file_path}"

    # Try ruff first (fast)
    try:
        result = subprocess.run(
            ["ruff", "check", str(p), "--output-format", "concise"],
            capture_output=True, text=True, timeout=30
        )
        if result.stdout.strip():
            return result.stdout.strip()
        return "No linting issues found (ruff)"
    except FileNotFoundError:
        pass

    # Fallback: basic Python compilation check
    try:
        compile(p.read_text(), str(p), "exec")
        return "No syntax errors (basic check)"
    except SyntaxError as e:
        return f"Syntax error at line {e.lineno}: {e.msg}"


def format_code(file_path: str) -> str:
    """Auto-format Python code (black or ruff)."""
    p = Path(file_path).expanduser().resolve()
    if not p.exists():
        return f"File not found: {file_path}"

    # Try ruff format first
    try:
        result = subprocess.run(
            ["ruff", "format", str(p)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return f"Formatted: {file_path} (ruff)"
    except FileNotFoundError:
        pass

    # Try black
    try:
        result = subprocess.run(
            ["black", str(p)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return f"Formatted: {file_path} (black)"
    except FileNotFoundError:
        pass

    return "No formatter available. Install: pip install ruff"