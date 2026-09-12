"""Output verification pipeline. 5-dimension gate before delivering.
DNA: Astra GPT-6 (self-verify code arena).

Verifies: correctness, completeness, security, style, evidence.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Verdict:
    passed: bool
    score: float  # 0.0 - 1.0
    dimensions: dict[str, bool]  # dimension_name → passed
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


class Verifier:
    """5-dimension output verification gate."""

    DIMENSIONS = {
        "correctness": "Does the solution actually solve the problem?",
        "completeness": "Is the solution fully implemented? No stubs or TODOs?",
        "security": "Are there obvious security vulnerabilities?",
        "style": "Does the code follow conventions and best practices?",
        "evidence": "Are claims backed by verifiable evidence?",
    }

    def verify(self, task: str, output: str, code: str = "") -> Verdict:
        """Run all 5 verification dimensions."""
        results = {}
        issues = []
        suggestions = []

        # 1. Correctness
        corr_ok, corr_issues = self._check_correctness(task, output, code)
        results["correctness"] = corr_ok
        issues.extend(corr_issues)

        # 2. Completeness
        comp_ok, comp_issues = self._check_completeness(output, code)
        results["completeness"] = comp_ok
        issues.extend(comp_issues)

        # 3. Security
        sec_ok, sec_issues = self._check_security(code)
        results["security"] = sec_ok
        issues.extend(sec_issues)

        # 4. Style
        style_ok, style_issues = self._check_style(code)
        results["style"] = style_ok
        issues.extend(style_issues)

        # 5. Evidence
        evid_ok, evid_issues = self._check_evidence(output)
        results["evidence"] = evid_ok
        issues.extend(evid_issues)

        passed = all(results.values())
        score = sum(1 for v in results.values() if v) / len(results)

        return Verdict(
            passed=passed,
            score=score,
            dimensions=results,
            issues=issues,
            suggestions=suggestions,
        )

    def verify_or_reject(self, task: str, output: str, code: str = "",
                         min_score: float = 0.6) -> tuple[bool, str]:
        """Verify and either approve or return with feedback."""
        verdict = self.verify(task, output, code)
        
        if verdict.passed:
            return True, f"✅ {verdict.score:.0%} — All checks passed"
        elif verdict.score >= min_score:
            return False, f"⚠ {verdict.score:.0%} — Minor issues:\n" + "\n".join(f"  - {i}" for i in verdict.issues)
        else:
            return False, f"❌ {verdict.score:.0%} — Rejected:\n" + "\n".join(f"  - {i}" for i in verdict.issues)

    # ── Dimension checks ─────────────────────────────────────

    def _check_correctness(self, task: str, output: str, code: str) -> tuple[bool, list[str]]:
        issues = []
        
        # Check if output is too short (likely incomplete)
        if len(output) < 20:
            issues.append("[correctness] Output too short — likely incomplete")
        
        # Check for error messages in output
        error_markers = ["error", "exception", "traceback", "failed", "cannot", "unable"]
        for marker in error_markers:
            if marker in output.lower():
                issues.append(f"[correctness] Output contains '{marker}' — possible failure")
                break
        
        # Check if code has obvious syntax issues (basic)
        if code:
            if code.count("(") != code.count(")"):
                issues.append("[correctness] Unbalanced parentheses")
            if code.count("[") != code.count("]"):
                issues.append("[correctness] Unbalanced brackets")
        
        return len(issues) == 0, issues

    def _check_completeness(self, output: str, code: str) -> tuple[bool, list[str]]:
        issues = []
        
        stub_markers = ["TODO", "FIXME", "pass  # TODO", "raise NotImplementedError",
                       "placeholder", "stub", "..."]
        for marker in stub_markers:
            if marker in output or marker in code:
                issues.append(f"[completeness] Found stub marker: '{marker}'")
        
        return len(issues) == 0, issues

    def _check_security(self, code: str) -> tuple[bool, list[str]]:
        if not code:
            return True, []
        
        issues = []
        
        dangerous = [
            ("eval(", "[security] eval() usage — potential RCE"),
            ("exec(", "[security] exec() usage — potential RCE"),
            ("shell=True", "[security] shell=True — command injection risk"),
            ("pickle.load", "[security] pickle.load() — insecure deserialization"),
            ("password = \"", "[security] Hardcoded password string"),
            ("api_key = \"", "[security] Hardcoded API key"),
            ("secret = \"", "[security] Hardcoded secret"),
            ("token = \"", "[security] Hardcoded token"),
        ]
        
        for pattern, msg in dangerous:
            if pattern in code:
                issues.append(msg)
        
        return len(issues) == 0, issues

    def _check_style(self, code: str) -> tuple[bool, list[str]]:
        if not code:
            return True, []
        
        issues = []
        lines = code.split("\n")
        
        # Long lines
        long_lines = [(i+1, len(l)) for i, l in enumerate(lines) if len(l) > 120]
        if long_lines:
            issues.append(f"[style] {len(long_lines)} line(s) exceed 120 chars")
        
        # Trailing whitespace
        trailing = sum(1 for l in lines if l.rstrip() != l)
        if trailing > 2:
            issues.append(f"[style] {trailing} line(s) with trailing whitespace")
        
        # Mixed indentation
        tabs = sum(1 for l in lines if l.startswith("\t"))
        spaces = sum(1 for l in lines if l.startswith("    "))
        if tabs > 0 and spaces > 0:
            issues.append("[style] Mixed tabs and spaces")
        
        return len(issues) == 0, issues

    def _check_evidence(self, output: str) -> tuple[bool, list[str]]:
        issues = []
        
        # Look for evidence markers
        evidence_markers = ["result:", "output:", "status:", "evidence:", "verified:",
                           "```", "exit code", "passed", "✅"]
        has_evidence = any(m in output.lower() for m in evidence_markers)
        
        if not has_evidence and len(output) > 100:
            issues.append("[evidence] Long output without clear evidence markers")
        
        # Vague language
        vague = ["should work", "probably", "might", "maybe", "i think", "possibly"]
        for v in vague:
            if v in output.lower():
                issues.append(f"[evidence] Vague claim: '{v}' — provide evidence")
                break
        
        return len(issues) == 0, issues


# ── Self-critique loop (Astra DNA) ────────────────────────────

class SelfCritique:
    """Recursive self-critique: generate → verify → improve → repeat."""

    def __init__(self, verifier: Verifier | None = None, max_depth: int = 3):
        self.verifier = verifier or Verifier()
        self.max_depth = max_depth

    async def refine(self, task: str, generate_fn, code_fn=None) -> str:
        """Generate and refine until passing verification or max depth."""
        best_output = ""
        best_score = 0.0

        for depth in range(self.max_depth):
            output = await generate_fn(task, feedback=best_output if best_output else None)
            code = code_fn() if code_fn else ""

            verdict = self.verifier.verify(task, output, code)

            if verdict.score > best_score:
                best_output = output
                best_score = verdict.score

            if verdict.passed:
                return f"[Depth {depth+1}] {output}"

        return f"[Max depth {self.max_depth}, score {best_score:.0%}] {best_output}"