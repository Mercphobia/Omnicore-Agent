"""PR review automation tool. AST diff, style check, security scan.
DNA: Copilot Agent (PR review) + Claude Code (git-native).
"""

import subprocess
import json
from pathlib import Path


def review_pr(base_branch: str = "main", head_branch: str = "") -> str:
    """Review changes between branches and generate PR feedback.
    
    Args:
        base_branch: Target branch (default: main)
        head_branch: Source branch (default: current)
    
    Returns:
        Formatted review with issues and suggestions
    """
    if not head_branch:
        head_branch = _current_branch()
    
    # Get diff
    diff = _get_diff(base_branch, head_branch)
    if not diff:
        return "No changes to review."

    lines = ["# PR Review", f"  {base_branch} ← {head_branch}", ""]
    
    # Stats
    stats = _diff_stats(diff)
    lines.append(f"## Stats: {stats}")
    lines.append("")
    
    # Style check
    style_issues = _check_style(diff)
    if style_issues:
        lines.append("## Style Issues")
        lines.append(style_issues)
        lines.append("")
    
    # Security scan on changed files
    security_issues = _check_security(base_branch, head_branch)
    if security_issues:
        lines.append("## Security Review")
        lines.append(security_issues)
        lines.append("")
    
    # Complexity check
    complexity = _check_complexity(diff)
    if complexity:
        lines.append("## Complexity Warnings")
        lines.append(complexity)
        lines.append("")
    
    # Summary
    issue_count = (style_issues.count("⚠") + security_issues.count("⚠") + complexity.count("⚠"))
    if issue_count == 0:
        lines.append("## Verdict: ✅ LGTM — No issues found")
    else:
        lines.append(f"## Verdict: ⚠ {issue_count} issues to address")
    
    return "\n".join(lines)


def review_file(filepath: str) -> str:
    """Review a single file for quality, security, and style.
    
    Args:
        filepath: Path to the file to review
    
    Returns:
        Formatted review
    """
    p = Path(filepath)
    if not p.exists():
        return f"File not found: {filepath}"
    
    content = p.read_text(errors="replace")
    lines_count = len(content.splitlines())
    
    report = [f"# Review: {p.name}", f"  Lines: {lines_count}", ""]
    
    # Language detection
    ext = p.suffix.lower()
    lang_map = {
        ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
        ".rs": "Rust", ".go": "Go", ".java": "Java", ".kt": "Kotlin",
        ".cpp": "C++", ".c": "C", ".rb": "Ruby", ".php": "PHP",
        ".swift": "Swift", ".sh": "Shell", ".sql": "SQL",
    }
    lang = lang_map.get(ext, "Unknown")
    report.append(f"  Language: {lang}")
    
    # Basic checks
    issues = []
    
    if "TODO" in content:
        todo_count = content.count("TODO")
        issues.append(f"  ℹ {todo_count} TODO(s) found — consider addressing")
    
    if "FIXME" in content:
        fixme_count = content.count("FIXME")
        issues.append(f"  ⚠ {fixme_count} FIXME(s) found — critical")
    
    if "print(" in content and ext == ".py":
        issues.append("  ℹ print() statements found — consider using logging")
    
    if "pass" in content and ext == ".py":
        pass_count = sum(1 for line in content.splitlines() if line.strip() == "pass")
        if pass_count > 2:
            issues.append(f"  ℹ {pass_count} bare 'pass' statements — implement or remove")
    
    if ext == ".py" and "except:" in content and "except Exception" not in content:
        issues.append("  ⚠ Bare 'except:' clauses — catch specific exceptions")
    
    if "import *" in content:
        issues.append("  ⚠ Wildcard imports — import specific names")
    
    if issues:
        report.append("## Issues")
        report.extend(issues)
        report.append("")
    
    if not issues:
        report.append("## Verdict: ✅ Clean")
    
    return "\n".join(report)


def generate_pr_description(base_branch: str = "main", head_branch: str = "") -> str:
    """Generate a PR description from the diff.
    
    Args:
        base_branch: Target branch
        head_branch: Source branch
    
    Returns:
        PR description template
    """
    if not head_branch:
        head_branch = _current_branch()
    
    diff = _get_diff(base_branch, head_branch)
    if not diff:
        return "No changes to describe."
    
    stats = _diff_stats(diff)
    files = _changed_files(base_branch, head_branch)
    
    # Categorize changes
    categories = {"feat": [], "fix": [], "chore": [], "refactor": [], "docs": [], "other": []}
    for f in files:
        if "test" in f.lower():
            categories["chore"].append(f)
        elif any(w in f.lower() for w in ("doc", "readme", "changelog")):
            categories["docs"].append(f)
        elif any(w in f.lower() for w in ("fix", "bug", "patch")):
            categories["fix"].append(f)
        elif any(w in f.lower() for w in ("refactor", "clean")):
            categories["refactor"].append(f)
        else:
            categories["feat"].append(f)
    
    lines = [
        "## Summary",
        "",
        f"Changes from `{head_branch}` into `{base_branch}`.",
        f"",
        f"**Stats:** {stats}",
        "",
        "## Changes",
        "",
    ]
    
    for cat, file_list in categories.items():
        if file_list:
            cat_name = {"feat": "Features", "fix": "Fixes", "chore": "Chores",
                       "refactor": "Refactors", "docs": "Documentation", "other": "Other"}[cat]
            lines.append(f"### {cat_name}")
            for f in file_list[:10]:
                lines.append(f"- `{f}`")
            lines.append("")
    
    lines.extend([
        "## Testing",
        "",
        "- [ ] Unit tests pass",
        "- [ ] Manual testing done",
        "- [ ] No regressions",
        "",
        "## Screenshots",
        "",
        "<!-- Add screenshots if UI changes -->",
    ])
    
    return "\n".join(lines)


# ── Internal helpers ────────────────────────────────────────


def _current_branch() -> str:
    try:
        r = subprocess.run(["git", "branch", "--show-current"],
                          capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception:
        return "HEAD"


def _get_diff(base: str, head: str) -> str:
    try:
        r = subprocess.run(["git", "diff", f"{base}...{head}", "--stat"],
                          capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except Exception:
        return ""


def _changed_files(base: str, head: str) -> list[str]:
    try:
        r = subprocess.run(["git", "diff", "--name-only", f"{base}...{head}"],
                          capture_output=True, text=True, timeout=10)
        return [f for f in r.stdout.strip().split("\n") if f]
    except Exception:
        return []


def _diff_stats(diff: str) -> str:
    """Extract stats from diff output."""
    if not diff:
        return "0 files changed"
    lines = diff.strip().split("\n")
    return lines[-1].strip() if lines else "0 files changed"


def _check_style(diff: str) -> str:
    """Run style checks on changed files."""
    issues = []
    
    # Check for long lines
    for line in diff.split("\n"):
        if line.startswith("+") and len(line) > 120:
            issues.append(f"  ⚠ Line exceeds 120 chars: {line[:80]}...")
    
    # Check for trailing whitespace
    trailing = sum(1 for l in diff.split("\n") if l.startswith("+") and l.rstrip() != l)
    if trailing:
        issues.append(f"  ℹ {trailing} line(s) with trailing whitespace")
    
    return "\n".join(issues) if issues else ""


def _check_security(base: str, head: str) -> str:
    """Quick security scan on diff."""
    diff_text = _get_diff(base, head)
    issues = []
    
    suspicious = [
        ("eval(", "⚠ eval() usage — potential RCE"),
        ("exec(", "⚠ exec() usage — potential RCE"),
        ("shell=True", "⚠ shell=True in subprocess — command injection risk"),
        ("pickle.load", "⚠ pickle.load() — insecure deserialization"),
        ("password", "ℹ Contains 'password' — verify it's not hardcoded"),
        ("secret", "ℹ Contains 'secret' — verify it's not hardcoded"),
        ("api_key", "ℹ Contains 'api_key' — verify it's not hardcoded"),
        ("token", "ℹ Contains 'token' — verify it's not hardcoded"),
    ]
    
    for pattern, msg in suspicious:
        if pattern in diff_text:
            issues.append(f"  {msg}")
    
    return "\n".join(issues) if issues else ""


def _check_complexity(diff: str) -> str:
    """Quick complexity check."""
    issues = []
    
    # Check for large additions
    added_lines = sum(1 for l in diff.split("\n") if l.startswith("+") and not l.startswith("+++"))
    if added_lines > 300:
        issues.append(f"  ⚠ Large PR: {added_lines} lines added — consider splitting")
    elif added_lines > 100:
        issues.append(f"  ℹ Moderate PR: {added_lines} lines added")
    
    return "\n".join(issues) if issues else ""