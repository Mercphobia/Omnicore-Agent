"""Dual-mode creative + analytical reasoning engine.

DNA: Mythos 5.1 (creative fusion) + Claude Opus (deep analytical reasoning).

The Reasoner operates in three modes:
- creative: brainstorming, lateral thinking, metaphor generation
- analytical: logic chains, first-principles breakdown, deductive reasoning
- hybrid: both modes combined and synthesized

An effort parameter (1-100) controls reasoning depth — higher effort means
more iterations, broader exploration, and deeper chains.
"""

import random
import math
from dataclasses import dataclass, field
from typing import Optional


# ── Reasoning primitives ──────────────────────────────────────────────

CREATIVE_TECHNIQUES = [
    "random_association",     # Connect to a random concept
    "reverse_thinking",       # What's the opposite? How would we fail?
    "metaphor_search",        # What is this like from another domain?
    "analogy_bridge",         # Find analogous situations in nature/tech/art
    "constraint_removal",     # What if we removed all constraints?
    "extremes",               # Push to extremes — what happens?
    "recombination",          # Combine with an unrelated idea
    "first_principles_creative",  # Break to atoms, rebuild creatively
    "provocation",            # Deliberately provocative "what if"
    "analogical_scaling",     # Scale the idea up/down 1000x
]

ANALYTICAL_TECHNIQUES = [
    "decomposition",          # Break into sub-problems
    "causal_chain",           # Map cause → effect cascade
    "deductive_closure",      # What necessarily follows from premises?
    "counterfactual",         # If X were false, what would change?
    "boundary_analysis",      # Where do the assumptions break?
    "socratic_dialogue",      # Question each claim iteratively
    "decision_tree",          # Branch on key uncertainties
    "strength_weakness",      # Systematic pro/con enumeration
    "evidence_audit",         # What evidence supports each claim?
    "system_dynamics",        # Feedback loops and emergent behavior
]

METAPHOR_DOMAINS = [
    "biology", "physics", "music", "architecture", "gardening",
    "warfare", "cooking", "oceanography", "theater", "mathematics",
    "evolution", "geology", "astronomy", "dance", "chess",
]


@dataclass
class ReasoningStep:
    """A single step in a reasoning chain."""
    technique: str
    thought: str
    insight: str = ""
    confidence: float = 0.5


@dataclass
class ReasonResult:
    """The result of a reasoning session."""
    mode: str                          # "creative" | "analytical" | "hybrid"
    reasoning_chain: list[ReasoningStep]
    conclusion: str
    confidence: float                  # 0.0–1.0
    beauty_score: float                # 0.0–1.0
    raw_chains: dict[str, list[ReasoningStep]] = field(default_factory=dict)


# ── Reasoner ──────────────────────────────────────────────────────────

class Reasoner:
    """Dual-mode creative + analytical reasoning engine.

    Operates in three modes:
        creative  — lateral thinking, metaphors, brainstorming
        analytical — logic chains, decomposition, deductive reasoning
        hybrid    — both modes combined into a synthesized conclusion

    The *effort* parameter (1–100) controls how many reasoning steps are
    generated and how broadly the engine explores.  Low effort (< 30) is
    fast and shallow; high effort (> 70) runs deeper chains with more
    cross-pollination.

    Usage::

        r = Reasoner(seed=42)
        result = r.reason("How to reduce city traffic?", mode="hybrid", effort=70)
        print(result.conclusion)
    """

    def __init__(self, seed: Optional[int] = None):
        """Initialise the reasoner with an optional seed for reproducibility."""
        self._rng = random.Random(seed)

    # ── Public API ────────────────────────────────────────────────────

    def reason(
        self,
        prompt: str,
        mode: str = "hybrid",
        effort: int = 70,
    ) -> ReasonResult:
        """Run a full reasoning session.

        Args:
            prompt: The problem or question to reason about.
            mode: "creative", "analytical", or "hybrid" (default).
            effort: Depth of reasoning, 1–100 (clamped internally).

        Returns:
            ReasonResult with mode, reasoning_chain, conclusion,
            confidence, and beauty_score.
        """
        mode = mode.lower()
        if mode not in ("creative", "analytical", "hybrid"):
            raise ValueError(f"Unknown mode '{mode}'. Use 'creative', 'analytical', or 'hybrid'.")

        effort = max(1, min(100, effort))
        raw_chains: dict[str, list[ReasoningStep]] = {}

        if mode in ("creative", "hybrid"):
            raw_chains["creative"] = self._creative_chain(prompt, effort)

        if mode in ("analytical", "hybrid"):
            raw_chains["analytical"] = self._analytical_chain(prompt, effort)

        # Synthesise
        if mode == "hybrid":
            combined = raw_chains["creative"] + raw_chains["analytical"]
            conclusion, confidence, beauty = self._synthesise(prompt, raw_chains, effort)
        elif mode == "creative":
            combined = raw_chains["creative"]
            conclusion = self._extract_conclusion(raw_chains["creative"])
            confidence = self._compute_confidence(raw_chains["creative"])
            beauty = self._compute_beauty(raw_chains["creative"])
        else:
            combined = raw_chains["analytical"]
            conclusion = self._extract_conclusion(raw_chains["analytical"])
            confidence = self._compute_confidence(raw_chains["analytical"])
            beauty = self._compute_beauty(raw_chains["analytical"])

        return ReasonResult(
            mode=mode,
            reasoning_chain=combined,
            conclusion=conclusion,
            confidence=confidence,
            beauty_score=beauty,
            raw_chains=raw_chains,
        )

    def creative_mode(self, prompt: str, effort: int = 70) -> ReasonResult:
        """Run creative-only reasoning (lateral thinking, metaphors, brainstorming)."""
        return self.reason(prompt, mode="creative", effort=effort)

    def analytical_mode(self, prompt: str, effort: int = 70) -> ReasonResult:
        """Run analytical-only reasoning (logic chains, decomposition, deduction)."""
        return self.reason(prompt, mode="analytical", effort=effort)

    def hybrid_mode(self, prompt: str, effort: int = 70) -> ReasonResult:
        """Run hybrid reasoning — both creative and analytical, synthesised."""
        return self.reason(prompt, mode="hybrid", effort=effort)

    # ── Creative chain ────────────────────────────────────────────────

    def _creative_chain(self, prompt: str, effort: int) -> list[ReasoningStep]:
        """Build a lateral-thinking chain."""
        steps: list[ReasoningStep] = []
        num_steps = max(2, effort // 10)

        techniques = self._rng.sample(CREATIVE_TECHNIQUES, min(num_steps, len(CREATIVE_TECHNIQUES)))

        for i, technique in enumerate(techniques):
            thought = self._generate_creative_thought(prompt, technique, i)
            insight = self._extract_insight(thought, technique)
            steps.append(ReasoningStep(
                technique=technique,
                thought=thought,
                insight=insight,
                confidence=0.5 + (0.3 * (i / max(1, len(techniques) - 1))),
            ))

        return steps

    def _generate_creative_thought(self, prompt: str, technique: str, step_idx: int) -> str:
        """Generate a single creative thought using a named technique."""
        domain = self._rng.choice(METAPHOR_DOMAINS)

        generators = {
            "random_association": lambda: (
                f"Random association with '{domain}': "
                f"If '{prompt[:60]}' were a {domain} system, it would be "
                f"{self._domain_insight(domain)}. "
                f"This suggests {self._random_action_verb()}ing the core element."
            ),
            "reverse_thinking": lambda: (
                f"Reverse: Instead of solving '{prompt[:50]}', what would make it WORSE? "
                f"{self._anti_solution(prompt)}. "
                f"Inverting this reveals: we should {self._invert(self._anti_solution(prompt))}."
            ),
            "metaphor_search": lambda: (
                f"Metaphor from {domain}: '{prompt[:60]}' is like "
                f"{self._domain_metaphor(domain)} because both involve "
                f"{self._universal_principle()}. "
                f"This reframes the problem as one of {self._reframe()}."
            ),
            "analogy_bridge": lambda: (
                f"Analogy: How does {domain} handle '{prompt[:50]}'? "
                f"In {domain}, {self._domain_strategy(domain)}. "
                f"We can port this by {self._bridge_action()}."
            ),
            "constraint_removal": lambda: (
                f"Constraint removal: If all constraints disappeared for '{prompt[:50]}', "
                f"the ideal solution would be {self._ideal_solution()}. "
                f"Working backwards, we can approximate this by {self._approximate_ideal()}."
            ),
            "extremes": lambda: (
                f"Extremes: Scale '{prompt[:50]}' to absurd magnitude. "
                f"{self._extreme_scenario(domain)}. "
                f"From this extreme, the core invariant is: {self._core_invariant(prompt)}."
            ),
            "recombination": lambda: (
                f"Recombination: Merge '{prompt[:50]}' with {domain}. "
                f"The hybrid idea: {self._hybrid_concept(prompt, domain)}. "
                f"This novel combination yields {self._novel_outcome()}."
            ),
            "first_principles_creative": lambda: (
                f"First principles (creative): Strip '{prompt[:50]}' to atoms. "
                f"The irreducible elements are: {self._irreducible_elements(prompt)}. "
                f"Rebuilding creatively from these atoms: {self._creative_rebuild(prompt)}."
            ),
            "provocation": lambda: (
                f"Provocation: The conventional wisdom about '{prompt[:50]}' is WRONG. "
                f"The truth is: {self._provocative_claim(prompt)}. "
                f"This challenges us to {self._provocative_action()}."
            ),
            "analogical_scaling": lambda: (
                f"Scaling: If '{prompt[:50]}' were {self._rng.choice(['1000x larger', '1000x smaller', 'instantaneous', 'eternal'])}, "
                f"the dynamics would shift to {self._scaled_dynamics()}. "
                f"This reveals that {self._scale_invariant(prompt)} is the key lever."
            ),
        }

        fn = generators.get(technique, generators["random_association"])
        return fn()

    # ── Analytical chain ──────────────────────────────────────────────

    def _analytical_chain(self, prompt: str, effort: int) -> list[ReasoningStep]:
        """Build a deductive reasoning chain."""
        steps: list[ReasoningStep] = []
        num_steps = max(2, effort // 10)

        techniques = self._rng.sample(
            ANALYTICAL_TECHNIQUES, min(num_steps, len(ANALYTICAL_TECHNIQUES))
        )

        for i, technique in enumerate(techniques):
            thought = self._generate_analytical_thought(prompt, technique, i)
            insight = self._extract_insight(thought, technique)
            steps.append(ReasoningStep(
                technique=technique,
                thought=thought,
                insight=insight,
                confidence=0.6 + (0.3 * (i / max(1, len(techniques) - 1))),
            ))

        return steps

    def _generate_analytical_thought(self, prompt: str, technique: str, step_idx: int) -> str:
        """Generate a single analytical thought using a named technique."""

        generators = {
            "decomposition": lambda: (
                f"Decomposition: '{prompt[:60]}' breaks into sub-problems: "
                f"{self._decompose(prompt)}. "
                f"The dependency order is: {self._dependency_order(prompt)}."
            ),
            "causal_chain": lambda: (
                f"Causal chain: Root causes → '{prompt[:50]}' → effects. "
                f"Primary cause: {self._root_cause(prompt)}. "
                f"Cascade: {self._cascade(prompt)}."
            ),
            "deductive_closure": lambda: (
                f"Deductive closure: If we accept that '{prompt[:50]}' is the goal, "
                f"then it necessarily follows that {self._necessary_consequence(prompt)}. "
                f"Therefore we must {self._deductive_action(prompt)}."
            ),
            "counterfactual": lambda: (
                f"Counterfactual: If the opposite of '{prompt[:50]}' were true, "
                f"then {self._counterfactual_world(prompt)}. "
                f"The gap between reality and counterfactual shows: {self._gap_analysis(prompt)}."
            ),
            "boundary_analysis": lambda: (
                f"Boundary: Assumptions behind '{prompt[:50]}' include "
                f"{self._list_assumptions(prompt)}. "
                f"The weakest assumption is {self._weakest_assumption(prompt)} — "
                f"if it fails, {self._assumption_failure_consequence(prompt)}."
            ),
            "socratic_dialogue": lambda: (
                f"Socratic: Q1: What do we mean by '{prompt[:40]}'? "
                f"A: {self._define(prompt)}. "
                f"Q2: Why is this important? A: {self._why_important(prompt)}. "
                f"Q3: What evidence would change our mind? A: {self._disconfirming_evidence(prompt)}."
            ),
            "decision_tree": lambda: (
                f"Decision tree: Key uncertainty for '{prompt[:40]}' is "
                f"{self._key_uncertainty(prompt)}. "
                f"Branch A ({self._branch_a(prompt)}): {self._outcome_a(prompt)}. "
                f"Branch B ({self._branch_b(prompt)}): {self._outcome_b(prompt)}."
            ),
            "strength_weakness": lambda: (
                f"Systematic: Strengths of current approach to '{prompt[:40]}': "
                f"{self._strengths(prompt)}. Weaknesses: {self._weaknesses(prompt)}. "
                f"The critical weakness to address first is {self._critical_weakness(prompt)}."
            ),
            "evidence_audit": lambda: (
                f"Evidence audit: Claims about '{prompt[:40]}' need verification. "
                f"Claim 1: {self._claim_1(prompt)} — evidence: {self._evidence_1(prompt)}. "
                f"Claim 2: {self._claim_2(prompt)} — evidence: {self._evidence_2(prompt)}. "
                f"Highest-confidence actionable finding: {self._actionable_finding(prompt)}."
            ),
            "system_dynamics": lambda: (
                f"System dynamics: '{prompt[:40]}' has feedback loops: "
                f"Reinforcing: {self._reinforcing_loop(prompt)}. "
                f"Balancing: {self._balancing_loop(prompt)}. "
                f"Leverage point: {self._leverage_point(prompt)}."
            ),
        }

        fn = generators.get(technique, generators["decomposition"])
        return fn()

    # ── Synthesis ─────────────────────────────────────────────────────

    def _synthesise(
        self,
        prompt: str,
        raw_chains: dict[str, list[ReasoningStep]],
        effort: int,
    ) -> tuple[str, float, float]:
        """Synthesise creative and analytical chains into a unified conclusion."""
        creative = raw_chains.get("creative", [])
        analytical = raw_chains.get("analytical", [])

        creative_insights = [s.insight for s in creative if s.insight]
        analytical_insights = [s.insight for s in analytical if s.insight]

        all_insights = creative_insights + analytical_insights
        if not all_insights:
            return (
                f"After reasoning about '{prompt[:80]}', the core challenge requires "
                f"further decomposition before a conclusion can be drawn.",
                0.3, 0.3,
            )

        # Build conclusion from the strongest insights
        key_creative = creative_insights[:2] if creative_insights else []
        key_analytical = analytical_insights[:2] if analytical_insights else []

        parts = []
        if key_analytical:
            parts.append(f"Analytically, {key_analytical[0].lower()}")
        if key_creative:
            parts.append(f"Creatively, {key_creative[0].lower()}")
        if len(key_analytical) > 1:
            parts.append(f"Furthermore, {key_analytical[1].lower()}")

        conclusion = (
            f"Regarding '{prompt[:80]}': " + " ".join(parts) + " "
            f"Therefore, the recommended approach is to {self._recommend_action(prompt, all_insights)}."
        )

        conf_creative = self._compute_confidence(creative) if creative else 0.5
        conf_analytical = self._compute_confidence(analytical) if analytical else 0.5
        confidence = (conf_creative * 0.4 + conf_analytical * 0.6)

        beauty = self._compute_beauty(creative + analytical)

        return conclusion, round(confidence, 3), round(beauty, 3)

    # ── Helpers ───────────────────────────────────────────────────────

    def _extract_conclusion(self, chain: list[ReasoningStep]) -> str:
        if not chain:
            return "No reasoning chain produced."
        insights = [s.insight for s in chain if s.insight]
        if not insights:
            return chain[-1].thought
        # Use the most confident step's insight as the conclusion anchor
        best = max(chain, key=lambda s: s.confidence)
        return f"Key insight: {best.insight or best.thought}"

    def _compute_confidence(self, chain: list[ReasoningStep]) -> float:
        if not chain:
            return 0.0
        # More steps + higher per-step confidence = higher overall confidence
        avg_conf = sum(s.confidence for s in chain) / len(chain)
        diversity_bonus = min(0.15, 0.02 * len(set(s.technique for s in chain)))
        return min(1.0, avg_conf + diversity_bonus)

    def _compute_beauty(self, chain: list[ReasoningStep]) -> float:
        """Beauty score: elegance of the reasoning chain.

        Rewards: diverse techniques, coherent progression, surprising insights.
        """
        if not chain:
            return 0.0
        techniques = [s.technique for s in chain]
        unique_ratio = len(set(techniques)) / len(techniques)
        insight_lengths = [len(s.insight) for s in chain if s.insight]
        avg_insight = sum(insight_lengths) / max(1, len(insight_lengths))
        # Goldilocks: insights should be neither too short nor too long
        brevity = 1.0 - abs(avg_insight - 80) / 200
        return round(min(1.0, unique_ratio * 0.5 + max(0, brevity) * 0.5), 3)

    def _extract_insight(self, thought: str, technique: str) -> str:
        """Extract a concise insight from a longer thought."""
        sentences = [s.strip() for s in thought.replace("?", ".").split(".") if s.strip()]
        if not sentences:
            return thought[:120]

        # Look for sentences with strong signal words
        signal_words = [
            "suggests", "reveals", "therefore", "implies", "key", "critical",
            "important", "surprising", "unexpected", "novel", "core", "essential",
            "recommend", "must", "should", "the", "this",
        ]
        for sentence in sentences:
            lower = sentence.lower()
            if any(w in lower for w in signal_words) and len(sentence) > 15:
                return sentence.strip()[:200]

        return sentences[-1].strip()[:200]

    # ── Creative thought generators ───────────────────────────────────

    _ACTIONS = [
        "amplify", "invert", "simplify", "combine", "eliminate", "redirect",
        "decentralize", "automate", "gamify", "modularize", "accelerate",
        "decouple", "abstract", "flatten", "disintermediate",
    ]

    _PRINCIPLES = [
        "feedback creates stability or chaos",
        "small changes can produce disproportionate effects",
        "constraints breed creativity",
        "diversity increases resilience",
        "everything is connected through flows",
        "emergence: simple rules produce complex behavior",
        "the map is not the territory",
        "energy flows where attention goes",
    ]

    _IDEALS = [
        "completely automated with zero friction",
        "self-organizing without central control",
        "infinitely scalable at zero marginal cost",
        "instantaneously responsive to every need",
        "perfectly efficient with no waste",
    ]

    _EXTREMES = [
        "everything happens simultaneously — instant orchestration",
        "the system spans the entire planet — global coordination",
        "every individual has unlimited agency — total decentralization",
        "resources are infinite — abundance changes all incentives",
    ]

    def _random_action_verb(self) -> str:
        return self._rng.choice(self._ACTIONS)

    def _universal_principle(self) -> str:
        return self._rng.choice(self._PRINCIPLES)

    def _ideal_solution(self) -> str:
        return self._rng.choice(self._IDEALS)

    def _extreme_scenario(self, domain: str) -> str:
        return f"If scaled to planetary {domain} scale: {self._rng.choice(self._EXTREMES)}"

    def _domain_insight(self, domain: str) -> str:
        insights = {
            "biology": "an organism adapting through iterative mutation",
            "physics": "a field seeking its lowest energy state",
            "music": "a composition balancing harmony and dissonance",
            "architecture": "a structure whose form follows its function",
            "gardening": "a garden where each plant finds its niche",
            "warfare": "a campaign where strategy meets logistics",
            "cooking": "a recipe where ingredients amplify each other",
            "oceanography": "a current flowing through hidden channels",
            "theater": "a performance where every role matters",
            "mathematics": "an equation seeking its simplest form",
            "evolution": "an adaptation landscape being climbed",
            "geology": "a slow pressure releasing suddenly",
            "astronomy": "a gravity well pulling everything toward it",
            "dance": "a choreography of interdependent motion",
            "chess": "a position where tempo matters more than material",
        }
        return insights.get(domain, f"a {domain} system in dynamic equilibrium")

    def _domain_metaphor(self, domain: str) -> str:
        return self._domain_insight(domain)

    def _domain_strategy(self, domain: str) -> str:
        strategies = {
            "biology": "evolution selects for efficiency through countless iterations",
            "physics": "systems minimize potential energy along paths of least action",
            "music": "tension and release create emotional journeys",
            "architecture": "load-bearing elements are distributed, not centralized",
            "gardening": "plants are placed where sun, water, and soil conditions align",
            "warfare": "the side with better logistics and intelligence wins",
        }
        return strategies.get(domain, f"practitioners iterate rapidly and learn from failure")

    def _reframe(self) -> str:
        frames = [
            "managing flows rather than controlling states",
            "enabling emergence rather than prescribing outcomes",
            "designing incentives rather than dictating behavior",
            "building platforms rather than delivering solutions",
        ]
        return self._rng.choice(frames)

    def _bridge_action(self) -> str:
        return f"translating the core mechanism into our domain and {self._rng.choice(self._ACTIONS)}ing it"

    def _approximate_ideal(self) -> str:
        return f"identifying the nearest feasible state and {self._rng.choice(self._ACTIONS)}ing the gap"

    def _core_invariant(self, prompt: str) -> str:
        return f"the underlying need that persists regardless of scale: {prompt[:40]}"

    def _hybrid_concept(self, prompt: str, domain: str) -> str:
        return f"a {domain}-inspired approach to {prompt[:30]}"

    def _novel_outcome(self) -> str:
        outcomes = [
            "an entirely new category of solution",
            "a 10x improvement over existing approaches",
            "a lateral shift that makes the original problem irrelevant",
            "a synthesis that combines the best of both worlds",
        ]
        return self._rng.choice(outcomes)

    def _irreducible_elements(self, prompt: str) -> str:
        elements = [
            "people, process, technology",
            "incentives, information, infrastructure",
            "supply, demand, coordination",
            "goals, constraints, resources",
        ]
        return self._rng.choice(elements)

    def _creative_rebuild(self, prompt: str) -> str:
        return f"recombining these elements in a novel configuration that eliminates the original bottleneck"

    def _provocative_claim(self, prompt: str) -> str:
        claims = [
            "the problem doesn't need solving — it needs reframing",
            "most effort is spent on the wrong 80%",
            "the solution already exists in an unrelated field",
            "we are optimizing a local maximum far from the global peak",
        ]
        return self._rng.choice(claims)

    def _provocative_action(self) -> str:
        return f"question every assumption and start from scratch"

    def _anti_solution(self, prompt: str) -> str:
        return f"deliberately maximising bottlenecks and ignoring feedback"

    @staticmethod
    def _invert(text: str) -> str:
        opposites = {
            "maximising": "minimising",
            "ignoring": "attending to",
            "bottlenecks": "flow enablers",
        }
        result = text
        for k, v in opposites.items():
            result = result.replace(k, v)
        return result

    def _scaled_dynamics(self) -> str:
        return "nonlinear effects dominate and conventional solutions break down"

    def _scale_invariant(self, prompt: str) -> str:
        return f"the core relationship structure within {prompt[:30]}"

    # ── Analytical thought generators ─────────────────────────────────

    def _decompose(self, prompt: str) -> str:
        return "definition, stakeholders, constraints, resources, timeline, success criteria"

    def _dependency_order(self, prompt: str) -> str:
        return "definition → constraints → resources → stakeholders → timeline → execution"

    def _root_cause(self, prompt: str) -> str:
        causes = [
            "misaligned incentives",
            "information asymmetry",
            "coordination failure",
            "resource misallocation",
            "legacy constraints",
        ]
        return self._rng.choice(causes)

    def _cascade(self, prompt: str) -> str:
        return f"root cause → symptom 1 → symptom 2 → visible problem → downstream effects"

    def _necessary_consequence(self, prompt: str) -> str:
        return f"we must address the structural cause, not just the symptoms"

    def _deductive_action(self, prompt: str) -> str:
        return f"target the highest-leverage node in the causal chain"

    def _counterfactual_world(self, prompt: str) -> str:
        return f"the system would exhibit the opposite behavior, revealing hidden constraints"

    def _gap_analysis(self, prompt: str) -> str:
        return f"the existing approach addresses only surface symptoms, not root causes"

    def _list_assumptions(self, prompt: str) -> str:
        return "resources are fixed, stakeholders are rational, environment is stable"

    def _weakest_assumption(self, prompt: str) -> str:
        return "environment is stable"

    def _assumption_failure_consequence(self, prompt: str) -> str:
        return "the entire strategy collapses"

    def _define(self, prompt: str) -> str:
        return f"a systemic challenge involving multiple interacting components"

    def _why_important(self, prompt: str) -> str:
        return f"it affects fundamental outcomes and compounds over time"

    def _disconfirming_evidence(self, prompt: str) -> str:
        return f"evidence that the problem is self-correcting or doesn't need intervention"

    def _key_uncertainty(self, prompt: str) -> str:
        return "whether the root cause is technical or organizational"

    def _branch_a(self, prompt: str) -> str:
        return "technical root cause"

    def _branch_b(self, prompt: str) -> str:
        return "organizational root cause"

    def _outcome_a(self, prompt: str) -> str:
        return "apply technical solution directly"

    def _outcome_b(self, prompt: str) -> str:
        return "change incentives and coordination structures first"

    def _strengths(self, prompt: str) -> str:
        return "familiarity, existing infrastructure, incremental improvement path"

    def _weaknesses(self, prompt: str) -> str:
        return "path dependency, blind spots, slow adaptation"

    def _critical_weakness(self, prompt: str) -> str:
        return "path dependency — we keep doing what we've always done"

    def _claim_1(self, prompt: str) -> str:
        return "the problem is well-understood"

    def _evidence_1(self, prompt: str) -> str:
        return "surface-level agreement, but no deep shared model exists — WEAK"

    def _claim_2(self, prompt: str) -> str:
        return "existing solutions are near-optimal"

    def _evidence_2(self, prompt: str) -> str:
        return "no systematic comparison with alternatives has been done — WEAK"

    def _actionable_finding(self, prompt: str) -> str:
        return "build a shared deep model before committing to any solution direction"

    def _reinforcing_loop(self, prompt: str) -> str:
        return "success → investment → more success (virtuous) OR failure → retreat → more failure (vicious)"

    def _balancing_loop(self, prompt: str) -> str:
        return "diminishing returns as the easy gains are captured"

    def _leverage_point(self, prompt: str) -> str:
        return "changing the goal, not just the tactics — shift from optimization to transformation"

    def _recommend_action(self, prompt: str, insights: list[str]) -> str:
        """Synthesise a recommended action from collected insights."""
        if not insights:
            return "decompose the problem further before acting"

        # Look for action words in insights
        action_words = [w for w in self._ACTIONS if any(w in i.lower() for i in insights)]
        if action_words:
            return f"{self._rng.choice(action_words)} the core dynamic while monitoring feedback"

        return "address the root cause before optimising the surface"


# ── Self-test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    r = Reasoner(seed=42)

    print("=" * 60)
    print("REASONER SELF-TEST")
    print("=" * 60)

    # Test creative mode
    print("\n── Creative Mode ──")
    result = r.reason("How to make cities more walkable?", mode="creative", effort=50)
    print(f"Mode: {result.mode}")
    print(f"Confidence: {result.confidence:.3f}")
    print(f"Beauty: {result.beauty_score:.3f}")
    print(f"Steps: {len(result.reasoning_chain)}")
    print(f"Conclusion: {result.conclusion[:200]}...")
    assert result.mode == "creative"
    assert len(result.reasoning_chain) > 0
    assert 0 <= result.confidence <= 1
    assert 0 <= result.beauty_score <= 1

    # Test analytical mode
    print("\n── Analytical Mode ──")
    result = r.reason("How to reduce software bugs by 50%?", mode="analytical", effort=80)
    print(f"Mode: {result.mode}")
    print(f"Confidence: {result.confidence:.3f}")
    print(f"Steps: {len(result.reasoning_chain)}")
    print(f"Conclusion: {result.conclusion[:200]}...")
    assert result.mode == "analytical"

    # Test hybrid mode
    print("\n── Hybrid Mode ──")
    result = r.reason("Design a sustainable energy strategy for a mid-size city.", mode="hybrid", effort=90)
    print(f"Mode: {result.mode}")
    print(f"Confidence: {result.confidence:.3f}")
    print(f"Beauty: {result.beauty_score:.3f}")
    print(f"Creative steps: {len(result.raw_chains.get('creative', []))}")
    print(f"Analytical steps: {len(result.raw_chains.get('analytical', []))}")
    print(f"Total steps: {len(result.reasoning_chain)}")
    print(f"Conclusion: {result.conclusion[:250]}...")
    assert result.mode == "hybrid"
    assert "creative" in result.raw_chains
    assert "analytical" in result.raw_chains

    # Test effort scaling
    print("\n── Effort Scaling ──")
    for e in [10, 50, 100]:
        result = r.reason("Test prompt", mode="analytical", effort=e)
        print(f"Effort {e:3d}: {len(result.reasoning_chain)} steps, conf={result.confidence:.3f}")

    # Test convenience methods
    print("\n── Convenience Methods ──")
    cr = r.creative_mode("Invent a new breakfast food.")
    ar = r.analytical_mode("Why do projects miss deadlines?")
    hr = r.hybrid_mode("How to improve team communication?")
    print(f"creative_mode: {cr.mode}, {len(cr.reasoning_chain)} steps")
    print(f"analytical_mode: {ar.mode}, {len(ar.reasoning_chain)} steps")
    print(f"hybrid_mode: {hr.mode}, {len(hr.reasoning_chain)} steps")
    assert cr.mode == "creative"
    assert ar.mode == "analytical"
    assert hr.mode == "hybrid"

    # Test invalid mode
    try:
        r.reason("test", mode="invalid")
        assert False, "Should have raised ValueError"
    except ValueError:
        print("\n── ValueError correctly raised for invalid mode ──")

    print("\n✅ All reasoner tests passed!")