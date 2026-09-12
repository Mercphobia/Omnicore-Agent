"""Devil's advocate mode. Auto-challenge agent's own outputs.
DNA: Grok 4 (contrarian mode, truth engine).

Finds weaknesses, assumptions, and blind spots in any solution.
"""

from dataclasses import dataclass, field


@dataclass
class Challenge:
    """A single challenge to a claim or assumption."""
    claim: str
    challenge: str
    severity: str  # "critical" | "major" | "minor"
    category: str  # "logic" | "assumption" | "edge_case" | "security" | "performance"


@dataclass
class Critique:
    """Full critique of a solution."""
    score: float  # 0.0 = deeply flawed, 1.0 = bulletproof
    challenges: list[Challenge] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    alternative_approach: str = ""


class Critic:
    """Automatically challenge outputs from multiple angles."""

    ANGLES = [
        "logical_fallacy",       # Is the reasoning sound?
        "missing_assumption",     # What unstated assumptions exist?
        "edge_case",             # What edge cases break this?
        "security_threat",       # How could this be exploited?
        "performance_issue",    # Where are the bottlenecks?
        "simpler_alternative",  # Is there an easier way?
        "failure_mode",         # How does this fail?
        "stakeholder_conflict", # Who loses from this decision?
    ]

    def critique(self, task: str, solution: str, code: str = "") -> Critique:
        """Generate a full critique of a solution."""
        challenges = []
        strengths = []

        # 1. Logical analysis
        logic_challenges = self._check_logic(task, solution)
        challenges.extend(logic_challenges)

        # 2. Assumption detection
        assumption_challenges = self._check_assumptions(solution)
        challenges.extend(assumption_challenges)

        # 3. Edge cases
        edge_challenges = self._check_edge_cases(task, solution)
        challenges.extend(edge_challenges)

        # 4. Security
        sec_challenges = self._check_security_threats(code or solution)
        challenges.extend(sec_challenges)

        # 5. Performance
        perf_challenges = self._check_performance(code or solution)
        challenges.extend(perf_challenges)

        # 6. Simpler alternative
        alt = self._suggest_alternative(task, solution)

        # 7. Strengths
        strengths = self._identify_strengths(task, solution, code)

        # Calculate score
        severity_weights = {"critical": 0.3, "major": 0.15, "minor": 0.05}
        penalty = sum(severity_weights.get(c.severity, 0.05) for c in challenges)
        score = max(0.0, min(1.0, 1.0 - penalty))

        return Critique(
            score=score,
            challenges=challenges,
            strengths=strengths,
            alternative_approach=alt,
        )

    def challenge_claims(self, text: str) -> list[Challenge]:
        """Extract and challenge specific claims from text."""
        challenges = []

        # Find strong claims
        strong_claim_words = ["always", "never", "must", "guaranteed",
                             "obviously", "clearly", "definitely", "certainly"]
        lines = text.split("\n")
        for i, line in enumerate(lines):
            for word in strong_claim_words:
                if word in line.lower():
                    challenges.append(Challenge(
                        claim=line.strip()[:100],
                        challenge=f"Is '{word}' really justified? What are the counterexamples?",
                        severity="minor",
                        category="logic",
                    ))

        return challenges

    def devil_advocate(self, solution: str) -> str:
        """Play devil's advocate: argue against the solution from all angles."""
        critique = self.critique("", solution)

        lines = [f"## Devil's Advocate Review (score: {critique.score:.0%})\n"]

        if critique.strengths:
            lines.append("### Strengths")
            for s in critique.strengths[:3]:
                lines.append(f"+ {s}")
            lines.append("")

        if critique.challenges:
            lines.append(f"### Challenges ({len(critique.challenges)})")
            for c in critique.challenges:
                lines.append(f"- [{c.severity.upper()}] [{c.category}] {c.challenge}")
            lines.append("")

        if critique.alternative_approach:
            lines.append("### Alternative Approach")
            lines.append(critique.alternative_approach)

        return "\n".join(lines)

    # ── Internal checks ──────────────────────────────────────

    def _check_logic(self, task: str, solution: str) -> list[Challenge]:
        challenges = []

        # Circular reasoning
        if task and task.lower() in solution.lower():
            # Check if solution just restates the task
            if len(solution) < len(task) * 2:
                challenges.append(Challenge(
                    claim="Solution",
                    challenge="Solution appears to just restate the problem without adding value",
                    severity="critical",
                    category="logic",
                ))

        # False dichotomy
        either_or = ["either", "or else", "the only way", "no other option"]
        for phrase in either_or:
            if phrase in solution.lower():
                challenges.append(Challenge(
                    claim=f"'{phrase}' framing",
                    challenge="This may be a false dichotomy. Are there other options?",
                    severity="major",
                    category="logic",
                ))
                break

        return challenges

    def _check_assumptions(self, solution: str) -> list[Challenge]:
        challenges = []

        assumptions = [
            ("always", "Assumes constant behavior — what about variability?"),
            ("every", "Over-generalization — are there exceptions?"),
            ("just", "Downplays complexity — 'just do X' often hides difficulty"),
            ("simply", "Oversimplification — is it really that simple?"),
            ("obviously", "Not obvious to everyone — state the reasoning"),
        ]

        for word, challenge_text in assumptions:
            if word in solution.lower():
                challenges.append(Challenge(
                    claim=f"Uses '{word}'",
                    challenge=challenge_text,
                    severity="minor",
                    category="assumption",
                ))

        return challenges

    def _check_edge_cases(self, task: str, solution: str) -> list[Challenge]:
        challenges = []

        edge_cases = [
            ("What happens with empty input?", "empty_input"),
            ("What about extremely large input?", "large_input"),
            ("What if the user has no permissions?", "no_permission"),
            ("What about concurrent/parallel access?", "concurrent"),
            ("What if the network fails midway?", "network_failure"),
            ("What about Unicode/special characters?", "unicode"),
            ("What if the input is malicious?", "malicious"),
        ]

        for question, tag in edge_cases:
            if tag not in solution.lower() and question.lower() not in solution.lower():
                challenges.append(Challenge(
                    claim="Edge case coverage",
                    challenge=question,
                    severity="major",
                    category="edge_case",
                ))

        return challenges[:3]  # Limit to top 3

    def _check_security_threats(self, content: str) -> list[Challenge]:
        challenges = []

        threats = [
            ("sql", "SQL injection risk — are queries parameterized?"),
            ("os.system", "Unsafe shell execution — use subprocess with list args"),
            ("pickle", "Insecure deserialization — use JSON instead"),
            ("eval", "Dynamic code execution — is this input-sanitized?"),
            ("password", "Password handling — is this stored securely?"),
            ("http://", "Plain HTTP — should this be HTTPS?"),
        ]

        for pattern, challenge_text in threats:
            if pattern in content.lower():
                challenges.append(Challenge(
                    claim=f"Contains '{pattern}'",
                    challenge=challenge_text,
                    severity="critical",
                    category="security",
                ))

        return challenges

    def _check_performance(self, content: str) -> list[Challenge]:
        challenges = []

        perf_issues = [
            (r"for.*for", "Nested loops — O(n²) complexity. Can this be optimized?"),
            ("while True", "Potential infinite loop — is there an exit condition?"),
            ("sleep\\(", "Sleep-based waiting — consider event-driven approach"),
            (r"from \w+ import \*", "Wildcard imports — bloats namespace and memory"),
        ]

        for pattern, challenge_text in perf_issues:
            import re
            if re.search(pattern, content):
                challenges.append(Challenge(
                    claim=f"Pattern '{pattern}'",
                    challenge=challenge_text,
                    severity="major",
                    category="performance",
                ))

        return challenges

    def _suggest_alternative(self, task: str, solution: str) -> str:
        """Suggest a radically different approach."""
        alternatives = [
            "Instead of building from scratch, can you use an existing library or service?",
            "Could this be solved with a simpler data structure? Consider dict/set over custom class.",
            "Is a configuration-driven approach possible instead of hardcoding?",
            "Could this be split into smaller, independently testable modules?",
            "What if you inverted the dependency? Instead of X depending on Y, make Y notify X.",
        ]

        # Pick a relevant alternative based on context
        if "class " in solution:
            return alternatives[1]  # Simpler data structure
        elif len(solution) > 500:
            return alternatives[3]  # Split into modules
        else:
            return alternatives[0]  # Use existing lib

    def _identify_strengths(self, task: str, solution: str, code: str) -> list[str]:
        strengths = []

        if code:
            if "def " in code or "function" in code:
                strengths.append("Well-structured with clear function boundaries")
            if "try" in code and "except" in code:
                strengths.append("Includes error handling")
            if "test" in code.lower():
                strengths.append("Includes tests")

        if len(solution) > 200:
            strengths.append("Detailed and thorough explanation")
        if "because" in solution.lower():
            strengths.append("Provides reasoning, not just conclusions")

        if not strengths:
            strengths.append("Solution exists (better than nothing)")

        return strengths