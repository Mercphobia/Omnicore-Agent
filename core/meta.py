"""Meta-Cognition Engine — think about thinking, improve reasoning from within.

DNA: cognitive science (metacognition) + Kahneman System 1/2 +
     bias detection (12 known biases) + confidence calibration +
     self-reflection loops.

Meta-cognition is "cognition about cognition" — the ability to observe your own
thought processes, identify patterns of error, and systematically improve how you
reason. This engine turns attention INWARD to examine reasoning chains, detect
biases, and strengthen weak points.

Usage::

    meta = MetaCognition()
    report = meta.reflect("I chose solution A because it worked last time")
    biases = meta.detect_bias("This new framework is definitely better than the old one")
    calibration = meta.calibrate_confidence(0.95, False)  # overconfident!
"""

from __future__ import annotations

import math
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

# ── Data types ──────────────────────────────────────────────────────────


@dataclass
class BiasFinding:
    """A detected cognitive bias in reasoning."""

    bias_name: str
    bias_id: int  # 1-12
    confidence: float  # 0-1 how likely this bias is present
    evidence: str  # quote or pattern that triggered detection
    corrective: str  # what to do about it
    severity: str  # LOW, MEDIUM, HIGH


@dataclass
class ReflectionReport:
    """Full meta-cognitive reflection analysis."""

    summary: str
    reasoning_patterns: list[str]  # deduction, induction, abduction, analogy, authority
    system_mode: str  # System 1 (fast) or System 2 (slow)
    biases_detected: list[BiasFinding]
    assumptions_found: list[str]
    blind_spots: list[str]
    confidence_calibrated: bool
    improvement_suggestions: list[str]
    thinking_score: float  # 0-1 overall reasoning quality


@dataclass
class CalibrationRecord:
    """One confidence calibration data point."""

    prediction: str
    confidence: float  # stated confidence 0-1
    outcome: bool  # was the prediction correct?
    timestamp: float = field(default_factory=time.time)
    delta: float = 0.0  # confidence - accuracy (positive = overconfident)


@dataclass
class PersonaComparison:
    """How different personas would approach the same problem."""

    problem: str
    approaches: dict[str, str]  # persona_name -> approach description
    commonalities: list[str]
    divergences: list[str]
    recommended_synthesis: str


@dataclass
class ThinkingAudit:
    """Full audit trail of a reasoning process."""

    steps: list[dict[str, Any]]
    total_steps: int
    time_estimate_seconds: float
    pattern_counts: dict[str, int]
    bias_interventions: int
    confidence_trajectory: list[float]
    final_verdict: str


# ── The 12 cognitive biases ─────────────────────────────────────────────

_BIAS_CATALOG: list[dict[str, Any]] = [
    {
        "id": 1, "name": "Confirmation",
        "triggers": [
            "already know", "proves my point", "as expected", "just as I thought",
            "supports my", "see, I told you", "exactly what I", "obviously",
            "clearly the", "it's obvious that", "surely", "without a doubt",
            "definitely", "absolutely", "no question", "undeniably",
        ],
        "corrective": "Actively search for disconfirming evidence. Ask: 'What would change my mind?'",
        "detection_question": "Am I only seeking evidence that supports my view?",
    },
    {
        "id": 2, "name": "Anchoring",
        "triggers": [
            "first estimate", "starting from", "initial value", "base price",
            "originally", "initially thought", "first number", "starting point",
            "baseline is", "the first thing", "default value",
        ],
        "corrective": "Generate an estimate BEFORE seeing the anchor. Consider multiple reference points.",
        "detection_question": "Am I stuck on the first number/idea I encountered?",
    },
    {
        "id": 3, "name": "Overconfidence",
        "triggers": [
            "100% sure", "absolutely certain", "no way I'm wrong", "guaranteed",
            "I'm totally confident", "zero doubt", "perfectly confident",
            "I'm positive", "I know for a fact", "there's no chance",
            "completely sure", "100 percent", "definitely will",
            "it will definitely", "certainly will",
        ],
        "corrective": "Calibrate: use probability ranges. Say 'I'm 70% sure' and track if you're right 70% of the time.",
        "detection_question": "Is my confidence > my accuracy warrants?",
    },
    {
        "id": 4, "name": "Availability",
        "triggers": [
            "recently", "just saw", "in the news", "everyone's talking about",
            "I keep hearing", "all over", "trending", "viral",
            "just happened", "latest", "breaking", "hot topic",
            "everybody knows", "common knowledge",
        ],
        "corrective": "Seek base rates and statistics, not just recent/vivid examples.",
        "detection_question": "Am I over-weighting recent/vivid examples over base rates?",
    },
    {
        "id": 5, "name": "Framing",
        "triggers": [
            "90% success rate", "10% failure rate", "saved", "lost",
            "gain vs", "loss vs", "win vs", "positive spin",
            "glass half", "net positive", "net negative",
            "from a certain angle", "depending on how you look at it",
        ],
        "corrective": "Reframe: gains vs losses, percentages vs absolutes. Would I decide differently if rephrased?",
        "detection_question": "Would I decide differently if the problem were rephrased?",
    },
    {
        "id": 6, "name": "Sunk Cost",
        "triggers": [
            "already invested", "spent so much time", "put too much into this",
            "might as well finish", "come this far", "too late to stop",
            "can't give up now", "would be a waste", "sunk",
            "already committed", "too deep", "in too deep",
        ],
        "corrective": "Ignore sunk costs; only consider marginal costs and future benefits.",
        "detection_question": "Am I continuing because of past investment, not future value?",
    },
    {
        "id": 7, "name": "Hindsight",
        "triggers": [
            "I knew it all along", "obvious in retrospect", "should have known",
            "hindsight is 20/20", "looking back it was clear", "could have predicted",
            "was bound to happen", "inevitable", "anyone could have seen",
            "so predictable", "in retrospect",
        ],
        "corrective": "Record predictions BEFORE outcomes. Check if you actually predicted it.",
        "detection_question": "Does this seem 'obvious' only after knowing the outcome?",
    },
    {
        "id": 8, "name": "Attribution",
        "triggers": [
            "they're just lazy", "he's so talented", "she's naturally gifted",
            "they don't care", "he's incompetent", "she got lucky",
            "it's their personality", "that's just who they are",
            "they're the kind of person who", "typical of them",
        ],
        "corrective": "Consider situational factors first, before attributing to personality.",
        "detection_question": "Am I blaming personality when the situation explains it?",
    },
    {
        "id": 9, "name": "Representativeness",
        "triggers": [
            "typical", "stereotypical", "sounds like", "reminds me of",
            "classic case of", "textbook", "fits the profile",
            "just like all the others", "same as always",
            "that's exactly what a", "describes most",
        ],
        "corrective": "Start with the base rate, then adjust with specific evidence.",
        "detection_question": "Am I ignoring base rates for vivid stereotypes?",
    },
    {
        "id": 10, "name": "Dunning-Kruger",
        "triggers": [
            "I'm an expert in", "I know this field", "trust me on this",
            "I've been doing this for years", "I'm pretty good at",
            "this is basic", "it's simple really", "anyone could do it",
            "just do X", "easy", "trivial", "piece of cake",
        ],
        "corrective": "Explicitly rate expertise as novice/intermediate/expert. Get external calibration.",
        "detection_question": "Am I overestimating my expertise in an unfamiliar domain?",
    },
    {
        "id": 11, "name": "Survivorship",
        "triggers": [
            "look at all the successes", "successful companies all",
            "the winners do this", "proven track record",
            "every successful", "the best all",
            "survivors share", "top performers",
        ],
        "corrective": "Look for the failures — what happened to them? Count the denominator.",
        "detection_question": "Am I only looking at successes, not failures?",
    },
    {
        "id": 12, "name": "Curse of Knowledge",
        "triggers": [
            "obviously", "as everyone knows", "it goes without saying",
            "clearly", "needless to say", "of course",
            "anyone can see", "it's common sense", "everyone understands",
            "you know what I mean", "you see", "naturally",
        ],
        "corrective": "Explain as if to a smart beginner. Assume the audience knows less than you.",
        "detection_question": "Am I assuming others know what I know?",
    },
]

_BIAS_LOOKUP: dict[str, dict[str, Any]] = {b["name"].lower(): b for b in _BIAS_CATALOG}
_BIAS_BY_ID: dict[int, dict[str, Any]] = {b["id"]: b for b in _BIAS_CATALOG}


def _compile_trigger_patterns(bias: dict[str, Any]) -> list[str]:
    """Flatten triggers for substring matching."""
    return [t.lower() for t in bias["triggers"]]


# ── Reasoning pattern detection ─────────────────────────────────────────

_REASONING_SIGNALS = {
    "deduction": [
        "if.*then", "therefore", "must be", "necessarily", "it follows that",
        "implies", "consequently", "hence", "ergo", "thus",
    ],
    "induction": [
        "all observed", "in general", "tends to", "usually", "typically",
        "most of the time", "pattern suggests", "based on past",
        "the data shows", "statistically",
    ],
    "abduction": [
        "best explanation", "most likely", "probably because",
        "the simplest explanation", "could explain", "might be due to",
        "plausibly", "working hypothesis", "seems like",
    ],
    "analogy": [
        "like", "similar to", "just as", "comparable to",
        "in the same way", "equivalent to", "analogous",
        "reminds me of", "parallel to", "mirrors",
    ],
    "authority": [
        "according to", "studies show", "experts say",
        "research indicates", "as stated by", "the literature",
        "per", "as documented", "cited by",
    ],
}


# ── Core engine ─────────────────────────────────────────────────────────


class MetaCognition:
    """Think about thinking — detect biases, calibrate confidence, improve reasoning.

    Parameters:
        track_history: Whether to maintain a full calibration history.
        min_confidence_for_warning: Threshold below which to flag low confidence.
    """

    def __init__(
        self,
        track_history: bool = True,
        min_confidence_for_warning: float = 0.5,
    ) -> None:
        self.track_history = track_history
        self.min_confidence_for_warning = min_confidence_for_warning

        # Internal state
        self._calibration_history: list[CalibrationRecord] = []
        self._reflection_log: list[ReflectionReport] = []
        self._thinking_steps: list[dict[str, Any]] = []
        self._bias_intervention_count: int = 0

    # ── Public API ──────────────────────────────────────────────────

    def reflect(self, reasoning_trace: str) -> ReflectionReport:
        """Analyze a reasoning trace for patterns, biases, and blind spots.

        Args:
            reasoning_trace: The reasoning text to analyze (chain of thought).

        Returns:
            ReflectionReport with full meta-cognitive analysis.
        """
        trace_lower = reasoning_trace.lower()

        # Detect reasoning patterns
        patterns = self._detect_reasoning_patterns(trace_lower)

        # Detect biases
        biases = self.detect_bias(reasoning_trace)

        # Detect system mode
        system_mode = self._classify_system_mode(reasoning_trace, patterns)

        # Find assumptions
        assumptions = self._extract_assumptions(reasoning_trace)

        # Find blind spots
        blind_spots = self._identify_blind_spots(reasoning_trace, biases, patterns)

        # Generate improvement suggestions
        improvements = self.improve_reasoning()

        # Calculate thinking score
        score = self._calculate_thinking_score(biases, patterns, blind_spots)

        report = ReflectionReport(
            summary=self._generate_summary(biases, patterns, system_mode, score),
            reasoning_patterns=patterns,
            system_mode=system_mode,
            biases_detected=sorted(biases, key=lambda b: b.severity, reverse=True),
            assumptions_found=assumptions,
            blind_spots=blind_spots,
            confidence_calibrated=len(self._calibration_history) > 0,
            improvement_suggestions=improvements,
            thinking_score=round(score, 3),
        )

        self._reflection_log.append(report)
        return report

    def detect_bias(self, decision: str) -> list[BiasFinding]:
        """Identify cognitive biases present in a decision or statement.

        Scans against the 12 known cognitive biases using trigger phrase
        matching and pattern heuristics.

        Args:
            decision: The decision text or reasoning to scan.

        Returns:
            List of BiasFinding objects, sorted by confidence descending.
        """
        findings: list[BiasFinding] = []
        decision_lower = decision.lower()
        words = set(decision_lower.split())

        for bias in _BIAS_CATALOG:
            triggers = _compile_trigger_patterns(bias)
            matches = [t for t in triggers if t in decision_lower]

            if not matches:
                continue

            # Calculate confidence based on match density and specificity
            match_ratio = len(matches) / len(triggers)
            # Longer triggers = higher specificity
            specificity = sum(len(t) for t in matches) / (sum(len(t) for t in triggers) + 1e-10)
            confidence = min(0.5 + (match_ratio * 0.3) + (specificity * 0.2), 0.95)

            # Severity based on number of matches
            severity = "LOW"
            if len(matches) >= 3:
                severity = "HIGH"
            elif len(matches) >= 2:
                severity = "MEDIUM"

            findings.append(
                BiasFinding(
                    bias_name=bias["name"],
                    bias_id=bias["id"],
                    confidence=round(confidence, 3),
                    evidence=f"Matched triggers: {', '.join(matches[:3])}",
                    corrective=bias["corrective"],
                    severity=severity,
                )
            )

        # Additional heuristic checks
        findings.extend(self._heuristic_bias_checks(decision, decision_lower, words))

        return sorted(findings, key=lambda f: (f.confidence, f.severity == "HIGH"), reverse=True)

    def calibrate_confidence(
        self, prediction: str, outcome: bool, stated_confidence: Optional[float] = None
    ) -> CalibrationRecord:
        """Adjust confidence calibration based on prediction outcome.

        Args:
            prediction: What was predicted.
            outcome: Whether the prediction was correct.
            stated_confidence: The confidence level stated (0-1). If None,
                              inferred from language in prediction.

        Returns:
            CalibrationRecord with delta and calibration assessment.
        """
        if stated_confidence is None:
            stated_confidence = self._infer_confidence(prediction)

        delta = stated_confidence - (1.0 if outcome else 0.0)

        record = CalibrationRecord(
            prediction=prediction[:300],
            confidence=stated_confidence,
            outcome=outcome,
            delta=round(delta, 4),
        )

        if self.track_history:
            self._calibration_history.append(record)

        return record

    def thinking_report(self) -> ThinkingAudit:
        """Produce a comprehensive audit trail of the reasoning process.

        Returns:
            ThinkingAudit with step-by-step analysis.
        """
        steps = list(self._thinking_steps)

        confidence_traj = [c.confidence for c in self._calibration_history[-20:]]

        # Count pattern types across all reflections
        pattern_counts: dict[str, int] = Counter()
        for report in self._reflection_log:
            for p in report.reasoning_patterns:
                pattern_counts[p] += 1

        total_time = sum(
            step.get("duration_ms", 500) for step in steps
        ) / 1000.0

        return ThinkingAudit(
            steps=steps,
            total_steps=len(steps),
            time_estimate_seconds=round(total_time, 2),
            pattern_counts=dict(pattern_counts),
            bias_interventions=self._bias_intervention_count,
            confidence_trajectory=confidence_traj,
            final_verdict=self._synthesize_verdict(),
        )

    def improve_reasoning(self) -> list[str]:
        """Suggest concrete improvements to the reasoning process.

        Returns:
            List of actionable improvement suggestions.
        """
        suggestions: list[str] = []

        if self._reflection_log:
            last = self._reflection_log[-1]

            if last.system_mode == "System 1":
                suggestions.append(
                    "Slow down: switch from System 1 (fast/intuitive) to System 2 "
                    "(slow/deliberate) for important decisions."
                )

            high_biases = [b for b in last.biases_detected if b.severity == "HIGH"]
            for b in high_biases[:3]:
                suggestions.append(f"Address {b.bias_name} bias: {b.corrective}")

            if not last.reasoning_patterns:
                suggestions.append(
                    "Make your reasoning explicit: articulate whether you're using "
                    "deduction, induction, abduction, analogy, or authority."
                )

            if last.thinking_score < 0.5:
                suggestions.append(
                    "Low reasoning quality detected. Consider: (1) listing assumptions, "
                    "(2) seeking disconfirming evidence, (3) consulting an outside view."
                )

        # Calibration-based suggestions
        if len(self._calibration_history) >= 5:
            recent = self._calibration_history[-5:]
            avg_delta = statistics.mean(r.delta for r in recent)
            if avg_delta > 0.15:
                suggestions.append(
                    f"You're overconfident by {avg_delta:.0%} on average. "
                    "Reduce stated confidence by this margin."
                )
            elif avg_delta < -0.15:
                suggestions.append(
                    "You're underconfident. Your predictions are more accurate "
                    "than you think — raise stated confidence slightly."
                )

        if not suggestions:
            suggestions.append(
                "Continue tracking reasoning patterns. Consider keeping a decision "
                "journal to improve calibration over time."
            )

        return suggestions

    def compare_personas(self, problem: str, personas: Optional[dict[str, str]] = None) -> PersonaComparison:
        """Analyze how different personas would approach the same problem.

        Args:
            problem: The problem description.
            personas: Dict of persona_name -> persona_description. If None,
                     uses a default set of cognitive archetypes.

        Returns:
            PersonaComparison with approaches and synthesis.
        """
        if personas is None:
            personas = {
                "Analyst": "Data-driven, systematic, thorough, risk-averse",
                "Innovator": "Creative, lateral thinking, rule-breaking, high risk tolerance",
                "Pragmatist": "Practical, cost-conscious, incremental, 'good enough'",
                "Perfectionist": "Zero-defect, exhaustive, every edge case, high standards",
                "Skeptic": "Questioning, adversarial, stress-testing, worst-case focus",
                "Optimist": "Opportunity-focused, best-case scenario, growth mindset",
            }

        approaches: dict[str, str] = {}
        for name, desc in personas.items():
            approaches[name] = self._simulate_persona_approach(name, desc, problem)

        commonalities = self._extract_commonalities(approaches)
        divergences = self._extract_divergences(approaches)
        synthesis = self._synthesize_approaches(problem, approaches, commonalities)

        return PersonaComparison(
            problem=problem,
            approaches=approaches,
            commonalities=commonalities,
            divergences=divergences,
            recommended_synthesis=synthesis,
        )

    def record_thinking_step(self, step_description: str, pattern: str = "", duration_ms: float = 0.0) -> None:
        """Record a single step in the reasoning chain (for audit trail).

        Args:
            step_description: What was thought/decided.
            pattern: Reasoning pattern used (deduction, induction, etc.).
            duration_ms: Time spent on this step.
        """
        self._thinking_steps.append({
            "step": len(self._thinking_steps) + 1,
            "description": step_description,
            "pattern": pattern,
            "duration_ms": duration_ms,
            "timestamp": time.time(),
        })

    # ── Internal helpers ────────────────────────────────────────────

    def _detect_reasoning_patterns(self, text: str) -> list[str]:
        """Detect which reasoning patterns are present in text."""
        found = []
        for pattern, signals in _REASONING_SIGNALS.items():
            for sig in signals:
                if sig in text:
                    found.append(pattern)
                    break
        return found

    def _classify_system_mode(self, text: str, patterns: list[str]) -> str:
        """Classify as System 1 (fast/intuitive) or System 2 (slow/deliberate)."""
        word_count = len(text.split())
        has_explicit_patterns = len(patterns) >= 2
        has_caveats = any(
            w in text.lower()
            for w in ["however", "but", "although", "on the other hand", "depends"]
        )

        # Short + confident + no hedging = System 1
        if word_count < 50 and not has_explicit_patterns and not has_caveats:
            return "System 1"
        # Long + explicit patterns + hedging = System 2
        if word_count > 80 and (has_explicit_patterns or has_caveats):
            return "System 2"

        return "System 1 (likely)" if word_count < 80 else "System 2 (likely)"

    def _extract_assumptions(self, text: str) -> list[str]:
        """Extract unstated assumptions from text."""
        assumptions: list[str] = []
        lines = text.split(".")

        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Heuristic: absolute statements often hide assumptions
            if any(w in line.lower() for w in ["always", "never", "every", "all", "must", "obviously"]):
                assumptions.append(f"Potentially unstated assumption in: '{line[:120]}...'")
            if any(w in line.lower() for w in ["will", "going to", "definitely"]):
                assumptions.append(f"Future prediction without stated uncertainty: '{line[:120]}...'")

        return assumptions[:10]

    def _identify_blind_spots(
        self, text: str, biases: list[BiasFinding], patterns: list[str]
    ) -> list[str]:
        """Identify reasoning blind spots."""
        blind_spots: list[str] = []

        bias_names = {b.bias_name for b in biases}

        if "Confirmation" in bias_names:
            blind_spots.append("Not considering contradictory evidence — seeking only confirmation.")

        if not patterns:
            blind_spots.append("No explicit reasoning pattern detected — may be relying on intuition alone.")

        if "Overconfidence" in bias_names:
            blind_spots.append("Overestimating certainty — missing nuance and edge cases.")

        if "Curse of Knowledge" in bias_names:
            blind_spots.append("Assuming shared knowledge — may miss what others don't know.")

        if not blind_spots:
            blind_spots.append("No major blind spots detected from text analysis.")

        return blind_spots

    def _calculate_thinking_score(
        self, biases: list[BiasFinding], patterns: list[str], blind_spots: list[str]
    ) -> float:
        """Score reasoning quality 0-1."""
        score = 0.7  # baseline

        # Deduct for biases
        high_biases = len([b for b in biases if b.severity == "HIGH"])
        med_biases = len([b for b in biases if b.severity == "MEDIUM"])
        score -= high_biases * 0.15
        score -= med_biases * 0.05

        # Bonus for explicit reasoning patterns
        score += len(patterns) * 0.05

        # Deduct for blind spots
        genuine_blind = [b for b in blind_spots if "No major" not in b]
        score -= len(genuine_blind) * 0.05

        return max(0.0, min(1.0, score))

    def _generate_summary(
        self, biases: list[BiasFinding], patterns: list[str], system_mode: str, score: float
    ) -> str:
        """Generate a concise summary of the meta-cognitive analysis."""
        parts = [f"Thinking score: {score:.2f}/1.0"]

        if patterns:
            parts.append(f"Patterns: {', '.join(patterns)}")
        else:
            parts.append("No explicit reasoning patterns detected.")

        parts.append(f"Mode: {system_mode}")

        high_biases = [b.bias_name for b in biases if b.severity == "HIGH"]
        if high_biases:
            parts.append(f"High-severity biases: {', '.join(high_biases)}")

        return ". ".join(parts)

    def _heuristic_bias_checks(
        self, text: str, text_lower: str, words: set[str]
    ) -> list[BiasFinding]:
        """Additional heuristic bias checks beyond trigger matching."""
        findings: list[BiasFinding] = []

        # Overconfidence: check for 100% certainty language
        certainty_words = {
            "certainly", "definitely", "absolutely", "guaranteed", "surely",
            "undoubtedly", "unquestionably", "infallible", "foolproof",
        }
        certainty_matches = words & certainty_words
        if len(certainty_matches) >= 2:
            findings.append(
                BiasFinding(
                    bias_name="Overconfidence",
                    bias_id=3,
                    confidence=0.75,
                    evidence=f"High-certainty language: {', '.join(sorted(certainty_matches)[:4])}",
                    corrective=_BIAS_BY_ID[3]["corrective"],
                    severity="MEDIUM",
                )
            )

        # Confirmation: check for dismissive language toward alternatives
        dismissive = {"clearly", "obviously", "no question", "without doubt"}
        if len(words & dismissive) >= 2:
            findings.append(
                BiasFinding(
                    bias_name="Confirmation",
                    bias_id=1,
                    confidence=0.65,
                    evidence="Dismissive language toward alternatives without evidence.",
                    corrective=_BIAS_BY_ID[1]["corrective"],
                    severity="MEDIUM",
                )
            )

        # Length-based Dunning-Kruger check
        if len(words) < 20 and any(
            w in words for w in {"expert", "master", "guru", "authority"}
        ):
            findings.append(
                BiasFinding(
                    bias_name="Dunning-Kruger",
                    bias_id=10,
                    confidence=0.55,
                    evidence="Short statement claiming expertise without demonstration.",
                    corrective=_BIAS_BY_ID[10]["corrective"],
                    severity="LOW",
                )
            )

        return findings

    def _infer_confidence(self, text: str) -> float:
        """Infer stated confidence from language in prediction text."""
        text_lower = text.lower()

        # Explicit percentage
        import re
        pct_match = re.search(r"(\d+)\s*%", text)
        if pct_match:
            return float(pct_match.group(1)) / 100.0

        # Confidence mapping
        if any(w in text_lower for w in ["certain", "definitely", "definitely will", "guaranteed", "absolutely"]):
            return 0.95
        if any(w in text_lower for w in ["very likely", "almost certainly", "highly probable"]):
            return 0.85
        if any(w in text_lower for w in ["likely", "probably", "i think so", "most likely"]):
            return 0.70
        if any(w in text_lower for w in ["maybe", "possibly", "might", "could go either way"]):
            return 0.50
        if any(w in text_lower for w in ["unlikely", "probably not", "doubtful"]):
            return 0.30

        return 0.60  # default moderate confidence

    def _simulate_persona_approach(self, name: str, desc: str, problem: str) -> str:
        """Simulate how a given persona would approach the problem."""
        desc_lower = desc.lower()

        approach_parts = [f"As a {name} ({desc}):"]

        if "data-driven" in desc_lower or "systematic" in desc_lower:
            approach_parts.append(
                f"I would collect all available data about '{problem[:60]}...', "
                "build a quantitative model, and evaluate options against metrics."
            )
        elif "creative" in desc_lower or "lateral" in desc_lower:
            approach_parts.append(
                f"I would reframe '{problem[:60]}...' from multiple angles, "
                "brainstorm unconventional solutions, and prototype rapidly."
            )
        elif "practical" in desc_lower or "cost-conscious" in desc_lower:
            approach_parts.append(
                f"I'd find the simplest solution to '{problem[:60]}...', "
                "weigh cost vs benefit, and implement incrementally."
            )
        elif "perfectionist" in desc_lower or "zero-defect" in desc_lower:
            approach_parts.append(
                f"I would exhaustively enumerate all edge cases for '{problem[:60]}...', "
                "build comprehensive tests, and iterate until flawless."
            )
        elif "skeptic" in desc_lower or "adversarial" in desc_lower:
            approach_parts.append(
                f"I would stress-test every assumption about '{problem[:60]}...', "
                "find the weakest links, and verify each claim independently."
            )
        elif "optimist" in desc_lower or "growth" in desc_lower:
            approach_parts.append(
                f"I would identify the upside potential in '{problem[:60]}...', "
                "envision the best outcome, and work backwards to make it happen."
            )
        else:
            approach_parts.append(
                f"I would approach '{problem[:60]}...' by first understanding the "
                "context, then applying my characteristic methods."
            )

        return " ".join(approach_parts)

    def _extract_commonalities(self, approaches: dict[str, str]) -> list[str]:
        """Find common themes across persona approaches."""
        all_text = " ".join(approaches.values()).lower()
        commonalities: list[str] = []

        if "understand" in all_text:
            commonalities.append("All personas start by understanding the problem context.")
        if "solution" in all_text:
            commonalities.append("All personas converge on finding a solution, differing only in method.")
        if "test" in all_text or "verify" in all_text or "validate" in all_text:
            commonalities.append("All personas include some form of verification or testing.")

        return commonalities if commonalities else ["All personas engage with the problem from their characteristic angle."]

    def _extract_divergences(self, approaches: dict[str, str]) -> list[str]:
        """Find key divergences between persona approaches."""
        divergences: list[str] = []

        names = list(approaches.keys())
        if len(names) >= 2:
            divergences.append(
                f"{names[0]} emphasizes depth while {names[-1]} emphasizes breadth "
                "in problem-solving strategy."
            )

        speed_related = any("rapidly" in v.lower() or "fast" in v.lower() for v in approaches.values())
        thorough_related = any("exhaustively" in v.lower() or "comprehensive" in v.lower() for v in approaches.values())
        if speed_related and thorough_related:
            divergences.append("Speed vs thoroughness is the primary axis of divergence.")

        return divergences

    def _synthesize_approaches(
        self, problem: str, approaches: dict[str, str], commonalities: list[str]
    ) -> str:
        """Synthesize the best of all persona approaches."""
        return (
            f"For '{problem[:80]}...': Begin with the Skeptic's stress-test of assumptions, "
            f"then apply the Analyst's systematic data collection, inject the Innovator's "
            f"creative reframing, implement the Pragmatist's incremental approach, and "
            f"validate with the Perfectionist's thoroughness — while maintaining the "
            f"Optimist's focus on the best possible outcome."
        )

    def _synthesize_verdict(self) -> str:
        """Synthesize overall verdict from reflection history."""
        if not self._reflection_log:
            return "No reflection data available."

        avg_score = statistics.mean(r.thinking_score for r in self._reflection_log)
        total_biases = sum(len(r.biases_detected) for r in self._reflection_log)

        if avg_score >= 0.8:
            return f"Strong reasoning ({avg_score:.2f}/1.0). {total_biases} biases flagged across sessions."
        elif avg_score >= 0.6:
            return f"Moderate reasoning ({avg_score:.2f}/1.0). {total_biases} biases detected — room to tighten logic."
        else:
            return f"Weak reasoning ({avg_score:.2f}/1.0). {total_biases} biases found — significant improvement needed."


# ── Self-test ────────────────────────────────────────────────────────────

def _self_test() -> None:
    """Verify MetaCognition with representative inputs."""
    meta = MetaCognition()

    # Test reflection
    report = meta.reflect(
        "I'm absolutely certain this approach will work. It's obvious that "
        "the new method is better — everyone knows that. I've been doing this "
        "for years so trust me on this. Looking back it was bound to succeed."
    )
    assert report.system_mode in ("System 1", "System 2", "System 1 (likely)", "System 2 (likely)")
    assert len(report.biases_detected) > 0, "Should detect biases in overconfident text"
    assert 0 <= report.thinking_score <= 1

    # Test bias detection
    biases = meta.detect_bias(
        "This new framework is definitely better than the old one. "
        "I'm 100% sure about this. All the successful companies use it."
    )

    bias_names = {b.bias_name for b in biases}
    assert len(biases) > 0
    assert any(b.bias_name == "Overconfidence" for b in biases), "Should detect overconfidence"

    # Test calibration
    cal = meta.calibrate_confidence(
        "I'm 90% sure the test will pass.",
        outcome=True,
        stated_confidence=0.9,
    )
    assert cal.outcome is True
    assert abs(cal.delta - (-0.1)) < 0.01  # 0.9 - 1.0 = -0.1

    cal2 = meta.calibrate_confidence(
        "I'm definitely right about this.",
        outcome=False,
    )
    assert cal2.outcome is False
    assert cal2.confidence > 0.8  # "definitely" maps to high confidence

    # Test thinking report
    audit = meta.thinking_report()
    assert audit.total_steps >= 0

    # Test improvement suggestions
    improvements = meta.improve_reasoning()
    assert len(improvements) > 0

    # Test persona comparison
    comparison = meta.compare_personas("Should we rewrite the entire codebase?")
    assert len(comparison.approaches) == 6
    assert comparison.recommended_synthesis

    # Test record thinking step
    meta.record_thinking_step("Consider option A", "deduction", 250.0)
    meta.record_thinking_step("Compare with option B", "analogy", 300.0)
    audit2 = meta.thinking_report()
    assert audit2.total_steps >= 2

    # Test edge: empty input
    empty_report = meta.reflect("")
    assert empty_report.thinking_score >= 0

    print("MetaCognition: all self-tests passed ✓")


if __name__ == "__main__":
    _self_test()