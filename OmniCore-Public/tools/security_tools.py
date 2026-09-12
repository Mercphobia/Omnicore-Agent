"""Security scanning tool. Semgrep + Bandit integration.
DNA: Gemini Cyber (vuln detection + auto-patch).
"""

import subprocess
import json
from pathlib import Path


def security_scan(path: str = ".", scanner: str = "auto") -> str:
    """Scan code for security vulnerabilities.
    
    Args:
        path: Directory or file to scan
        scanner: "semgrep" | "bandit" | "auto" (tries both)
    
    Returns:
        Formatted vulnerability report
    """
    target = Path(path).resolve()
    if not target.exists():
        return f"Path not found: {path}"

    results = []
    
    if scanner in ("auto", "semgrep"):
        semgrep_result = _run_semgrep(target)
        if semgrep_result:
            results.append(semgrep_result)
    
    if scanner in ("auto", "bandit"):
        bandit_result = _run_bandit(target)
        if bandit_result:
            results.append(bandit_result)
    
    if not results:
        return "No security scanners available. Install: pip install semgrep bandit"
    
    return "\n\n".join(results)


def _run_semgrep(target: Path) -> str:
    """Run Semgrep if available."""
    try:
        r = subprocess.run(
            ["semgrep", "--config=auto", "--json", str(target)],
            capture_output=True, text=True, timeout=120
        )
        if r.returncode in (0, 1):  # 0=clean, 1=findings
            data = json.loads(r.stdout) if r.stdout.strip() else {"results": []}
            findings = data.get("results", [])
            if not findings:
                return "✅ Semgrep: No issues found"
            
            lines = [f"🔍 Semgrep: {len(findings)} finding(s)"]
            for f in findings[:20]:
                severity = f.get("extra", {}).get("severity", "?")
                msg = f.get("extra", {}).get("message", "?")
                filepath = f.get("path", "?")
                line = f.get("start", {}).get("line", "?")
                lines.append(f"  [{severity.upper()}] {filepath}:{line} — {msg}")
            
            if len(findings) > 20:
                lines.append(f"  ... and {len(findings) - 20} more")
            return "\n".join(lines)
        else:
            return f"⚠ Semgrep error: {r.stderr[:200]}"
    except FileNotFoundError:
        return ""  # Semgrep not installed
    except Exception as e:
        return f"⚠ Semgrep exception: {e}"


def _run_bandit(target: Path) -> str:
    """Run Bandit if available."""
    try:
        r = subprocess.run(
            ["bandit", "-r", "-f", "json", str(target)],
            capture_output=True, text=True, timeout=120
        )
        if r.returncode in (0, 1):
            data = json.loads(r.stdout) if r.stdout.strip() else {"results": []}
            findings = data.get("results", [])
            if not findings:
                return "✅ Bandit: No issues found"
            
            lines = [f"🔍 Bandit: {len(findings)} finding(s)"]
            for f in findings[:20]:
                severity = f.get("issue_severity", "?")
                confidence = f.get("issue_confidence", "?")
                test_name = f.get("test_name", "?")
                filename = f.get("filename", "?")
                lineno = f.get("line_number", "?")
                lines.append(f"  [{severity}/{confidence}] {test_name} — {filename}:{lineno}")
            
            if len(findings) > 20:
                lines.append(f"  ... and {len(findings) - 20} more")
            return "\n".join(lines)
        else:
            return f"⚠ Bandit error: {r.stderr[:200]}"
    except FileNotFoundError:
        return ""
    except Exception as e:
        return f"⚠ Bandit exception: {e}"


def audit_dependencies(path: str = ".") -> str:
    """Audit Python dependencies for known vulnerabilities."""
    target = Path(path).resolve()
    
    # Check for requirements.txt or pyproject.toml
    req_file = target / "requirements.txt"
    pyro_file = target / "pyproject.toml"
    
    if not req_file.exists() and not pyro_file.exists():
        return "No requirements.txt or pyproject.toml found"
    
    lines = ["📦 Dependency Audit:"]
    
    # pip-audit
    try:
        r = subprocess.run(
            ["pip-audit", "--format=json"],
            capture_output=True, text=True, timeout=60
        )
        if r.returncode == 0:
            lines.append("  ✅ pip-audit: No known vulnerabilities")
        else:
            data = json.loads(r.stdout) if r.stdout.strip() else {"vulnerabilities": []}
            vulns = data.get("vulnerabilities", [])
            if vulns:
                lines.append(f"  ⚠ pip-audit: {len(vulns)} known vulns")
                for v in vulns[:10]:
                    lines.append(f"    - {v.get('name', '?')} {v.get('version', '?')}: {v.get('id', '?')}")
    except FileNotFoundError:
        lines.append("  ℹ pip-audit not installed (pip install pip-audit)")
    except Exception as e:
        lines.append(f"  ⚠ pip-audit error: {e}")
    
    # Safety check
    try:
        r = subprocess.run(
            ["safety", "check", "--json"],
            capture_output=True, text=True, timeout=60
        )
        if r.returncode == 0:
            lines.append("  ✅ Safety: No known vulnerabilities")
    except FileNotFoundError:
        pass
    
    return "\n".join(lines)


def generate_security_fix(finding: str, code_snippet: str = "") -> str:
    """Generate a security fix for a finding.
    
    Args:
        finding: Description of the vulnerability
        code_snippet: The vulnerable code (optional)
    
    Returns:
        Suggested fix as code diff
    """
    # Common patterns with fixes
    FIX_PATTERNS = {
        "sql_injection": "Use parameterized queries: cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))",
        "xss": "Use html.escape() or template auto-escaping: {{ user_input | e }}",
        "hardcoded_secret": "Use environment variables: api_key = os.environ.get('API_KEY')",
        "path_traversal": "Use os.path.basename() or Path.resolve() validation",
        "insecure_deserialization": "Never use pickle.loads on untrusted data. Use json.loads instead.",
        "command_injection": "Use subprocess.run with list args (not shell=True): subprocess.run(['ls', user_dir])",
        "weak_crypto": "Use bcrypt/scrypt/argon2 for passwords. AES-256-GCM for encryption. SHA-256 minimum.",
        "open_redirect": "Validate redirect URL against allowlist: if url in ALLOWED_HOSTS: redirect(url)",
        "ssrf": "Validate and sanitize URL. Block internal IPs. Use allowlist for domains.",
    }
    
    finding_lower = finding.lower()
    for pattern, fix in FIX_PATTERNS.items():
        if pattern in finding_lower:
            return f"🔧 Suggested fix for {pattern}:\n\n{fix}\n\nCode:\n```python\n{code_snippet or '# Add fix here'}\n```"
    
    return f"🔧 Generic fix suggestion for: {finding}\n\nReview the OWASP Cheat Sheet for detailed guidance."