"""
Emergence Engine — creative recombination, cross-domain analogy, and novelty synthesis.
DNA: The closest thing to genuine creativity in code. Recombines existing skills
into novel solutions, finds cross-domain analogies, measures novelty, and synthesizes
diverse approaches into emergent solutions no single strategy could produce.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import random
import re
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Set, Tuple, Union


# ============================================================================
# Data types
# ============================================================================


@dataclass
class Skill:
    """A named capability with a semantic description."""

    name: str
    description: str
    domain: str = "general"
    tags: List[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    @property
    def token_set(self) -> FrozenSet[str]:
        return frozenset(re.findall(r"\w+", f"{self.name} {self.description}".lower()))


@dataclass
class CombinedSolution:
    """A solution created by recombining existing skills."""

    description: str
    source_skills: List[Skill]
    novelty: float
    feasibility: float
    composite_tags: List[str] = field(default_factory=list)
    analogy_chain: List[str] = field(default_factory=list)

    def __repr__(self) -> str:
        skills_str = " + ".join(s.name for s in self.source_skills)
        return f"CombinedSolution({skills_str} → novelty={self.novelty:.2f})"


@dataclass
class CrossDomainAnalogy:
    """An analogy bridging two different domains."""

    domain_a: str
    domain_b: str
    mapping: List[Tuple[str, str]]  # (concept_in_a, concept_in_b)
    insight: str
    strength: float  # 0–1: how strong the analogy is

    def __repr__(self) -> str:
        return f"Analogy({self.domain_a} ↔ {self.domain_b}, strength={self.strength:.2f})"


@dataclass
class EmergentSolution:
    """A solution synthesized from multiple diverse approaches."""

    description: str
    components: List[str]
    synthesis_method: str
    novelty_score: float
    confidence: float
    rationale: str = ""

    def __repr__(self) -> str:
        return f"EmergentSolution(novelty={self.novelty_score:.2f}, confidence={self.confidence:.2f})"


# ============================================================================
# Domain knowledge base for cross-domain analogy
# ============================================================================


_DOMAIN_CONCEPTS: Dict[str, List[str]] = {
    "biology": [
        "evolution", "natural selection", "mutation", "adaptation", "ecosystem",
        "symbiosis", "homeostasis", "metabolism", "reproduction", "genetic algorithm",
        "immune system", "neural network", "swarm behavior", "pheromone trail",
        "cellular automaton", "emergent behavior", "self-organization", "feedback loop",
    ],
    "physics": [
        "entropy", "thermodynamics", "equilibrium", "phase transition", "resonance",
        "wave", "field", "momentum", "friction", "gravity", "quantum superposition",
        "conservation law", "symmetry breaking", "critical point", "hysteresis",
    ],
    "computer_science": [
        "algorithm", "data structure", "cache", "pipeline", "parallelism",
        "lazy evaluation", "memoization", "heuristic", "optimization", "abstraction",
        "recursion", "concurrency", "garbage collection", "type system", "protocol",
        "distributed consensus", "event sourcing", "message passing", "state machine",
    ],
    "mathematics": [
        "optimization", "probability", "graph theory", "linear algebra", "calculus",
        "topology", "combinatorics", "statistics", "set theory", "category theory",
        "fixed point", "convergence", "duality", "invariant", "transformation",
    ],
    "economics": [
        "supply and demand", "market equilibrium", "arbitrage", "incentive",
        "game theory", "auction", "scarcity", "utility", "externality",
        "network effect", "winner-take-all", "tragedy of the commons", "signaling",
    ],
    "psychology": [
        "reinforcement learning", "cognitive bias", "heuristic", "priming",
        "pattern recognition", "attention", "memory", "habituation", "flow state",
        "mental model", "anchoring", "social proof", "loss aversion",
    ],
    "art": [
        "composition", "contrast", "rhythm", "harmony", "abstraction",
        "juxtaposition", "minimalism", "generative art", "improvisation",
        "negative space", "symmetry", "texture", "gradient",
    ],
    "engineering": [
        "feedback control", "redundancy", "modularity", "pipeline", "buffering",
        "load balancing", "circuit breaker", "graceful degradation", "backpressure",
        "failover", "throttling", "caching", "pooling", "batching",
    ],
}

_DOMAIN_ANALOGY_TEMPLATES: List[Dict[str, Any]] = [
    {
        "domains": ("biology", "computer_science"),
        "mappings": [
            ("evolution", "genetic algorithm"),
            ("immune system", "anomaly detection"),
            ("swarm behavior", "distributed optimization"),
            ("neural network", "deep learning"),
            ("symbiosis", "microservices"),
            ("homeostasis", "auto-scaling"),
            ("mutation", "random search / exploration"),
        ],
        "insight": "Biological systems solve complex adaptive problems without central control — "
                   "the same principles power distributed, self-healing software systems.",
    },
    {
        "domains": ("physics", "computer_science"),
        "mappings": [
            ("entropy", "technical debt"),
            ("phase transition", "tipping point / viral adoption"),
            ("resonance", "cache hit ratio optimization"),
            ("momentum", "development velocity"),
            ("friction", "UX friction / onboarding drop-off"),
            ("quantum superposition", "speculative execution"),
            ("symmetry breaking", "consensus protocols (leader election)"),
        ],
        "insight": "Physical systems evolve toward equilibrium; software systems evolve toward "
                   "complexity. Understanding phase transitions helps predict when systems break.",
    },
    {
        "domains": ("economics", "computer_science"),
        "mappings": [
            ("supply and demand", "resource allocation / scheduling"),
            ("arbitrage", "performance optimization"),
            ("network effect", "platform growth / API adoption"),
            ("game theory", "multi-agent systems"),
            ("auction", "bid optimization / ad placement"),
            ("scarcity", "rate limiting / capacity planning"),
        ],
        "insight": "Markets efficiently allocate scarce resources through decentralized mechanisms — "
                   "the same principles apply to compute scheduling and network bandwidth allocation.",
    },
    {
        "domains": ("psychology", "computer_science"),
        "mappings": [
            ("reinforcement learning", "RLHF / preference optimization"),
            ("cognitive bias", "algorithmic bias"),
            ("attention", "transformer attention mechanism"),
            ("memory", "caching / context windows"),
            ("habituation", "alert fatigue / notification design"),
            ("flow state", "developer experience / DX optimization"),
        ],
        "insight": "Human cognition offers proven patterns for building AI systems — "
                   "attention, memory, and learning mechanisms all have computational analogs.",
    },
    {
        "domains": ("art", "engineering"),
        "mappings": [
            ("composition", "system architecture"),
            ("contrast", "A/B testing"),
            ("rhythm", "CI/CD pipeline cadence"),
            ("harmony", "API consistency"),
            ("negative space", "white space in UI / code readability"),
            ("minimalism", "YAGNI / simple solutions"),
            ("improvisation", "hotfix / incident response"),
        ],
        "insight": "Artistic principles of composition and balance directly translate to "
                   "software architecture — both are about arranging elements for clarity and impact.",
    },
]


# ============================================================================
# Main class
# ============================================================================


class Emergence:
    """Emergence Engine — creative recombination and novelty synthesis.

    Combines existing skills into novel solutions, finds cross-domain analogies,
    measures solution novelty, generates serendipitous connections, and synthesizes
    diverse approaches into emergent solutions no single strategy could produce.

    DNA: The closest thing to genuine creativity in code. Recombines skills,
    bridges domains, and synthesizes diverse outputs into emergent solutions
    that transcend any individual approach.

    Usage:
        engine = Emergence()

        skills = [
            Skill("sort", "Sort a list efficiently", "algorithms"),
            Skill("cache", "Store computed results for reuse", "systems"),
        ]

        combined = engine.combine(skills, "process large streaming data")
        novelty = engine.novelty_score(combined)
        analogy = engine.cross_domain("biology", "computer_science")
        serendipity = engine.serendipity()
        emergent = engine.synthesize([solution_a, solution_b, solution_c])
    """

    def __init__(self, *, seed: Optional[int] = None):
        """Initialize the Emergence Engine.

        Args:
            seed: Random seed for reproducible serendipity.
        """
        self._rng = random.Random(seed)
        self._history: List[CombinedSolution] = []
        self._analogy_cache: Dict[Tuple[str, str], CrossDomainAnalogy] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def combine(
        self,
        skills: List[Skill],
        problem: str,
        *,
        max_combinations: int = 5,
    ) -> List[CombinedSolution]:
        """Creatively recombine existing skills to produce novel solutions.

        Takes a set of existing skills and a problem description, then finds
        non-obvious combinations that could solve the problem in novel ways.
        Uses semantic similarity, tag overlap, and random recombination with
        feasibility filtering.

        Args:
            skills: List of Skill objects to recombine.
            problem: Natural language problem description.
            max_combinations: Maximum number of combined solutions to return.

        Returns:
            List of CombinedSolution objects, ranked by novelty × feasibility.
        """
        if len(skills) < 2:
            return []

        problem_tokens = frozenset(re.findall(r"\w+", problem.lower()))
        solutions: List[CombinedSolution] = []

        # Generate all pairs
        for s1, s2 in itertools.combinations(skills, 2):
            # Skip same-domain pairs (less novel)
            if s1.domain == s2.domain:
                continue

            # Compute semantic distance as novelty proxy
            common_tags = set(s1.tags) & set(s2.tags)
            all_tags = set(s1.tags) | set(s2.tags)
            tag_similarity = len(common_tags) / len(all_tags) if all_tags else 0.0
            token_overlap = len(s1.token_set & s2.token_set) / max(
                len(s1.token_set | s2.token_set), 1
            )

            novelty = 1.0 - (tag_similarity * 0.5 + token_overlap * 0.5)

            # Feasibility: how well the combination addresses the problem
            combined_tokens = s1.token_set | s2.token_set
            problem_overlap = len(combined_tokens & problem_tokens) / max(
                len(problem_tokens), 1
            )
            feasibility = 0.3 + (problem_overlap * 0.7)

            # Build composite tags
            composite = list(set(s1.tags + s2.tags))

            description = (
                f"Combine {s1.name} ({s1.domain}) with {s2.name} ({s2.domain}) "
                f"to create a {self._describe_combination(s1, s2)} that addresses: {problem[:80]}"
            )

            solutions.append(CombinedSolution(
                description=description,
                source_skills=[s1, s2],
                novelty=round(novelty, 3),
                feasibility=round(feasibility, 3),
                composite_tags=composite,
            ))

        # Generate triple combinations for more novelty
        if len(skills) >= 3:
            for combo in itertools.combinations(skills, 3):
                domains = {s.domain for s in combo}
                if len(domains) < 2:
                    continue  # Need at least 2 different domains for novelty

                novelty = 1.0 - (1.0 / len(domains))
                combined_tokens: Set[str] = set()
                for s in combo:
                    combined_tokens |= set(s.token_set)
                problem_overlap = len(combined_tokens & set(problem_tokens)) / max(
                    len(problem_tokens), 1
                )
                feasibility = 0.3 + (problem_overlap * 0.7)
                all_tags = list(set(itertools.chain.from_iterable(s.tags for s in combo)))

                description = (
                    f"Triple fusion: {combo[0].name} × {combo[1].name} × {combo[2].name} "
                    f"— merging {', '.join(domains)} perspectives"
                )

                solutions.append(CombinedSolution(
                    description=description,
                    source_skills=list(combo),
                    novelty=round(novelty, 3),
                    feasibility=round(feasibility, 3),
                    composite_tags=all_tags,
                ))

        # Sort by novelty × feasibility score
        solutions.sort(
            key=lambda s: s.novelty * s.feasibility,
            reverse=True,
        )

        result = solutions[:max_combinations]
        self._history.extend(result)
        return result

    def novelty_score(self, solution: Union[CombinedSolution, str]) -> float:
        """Measure how novel a solution is.

        Novelty is computed based on:
        - Semantic distance between combined components
        - Domain diversity of source skills
        - Uniqueness of the combination relative to history
        - Tag dispersion

        Args:
            solution: CombinedSolution or plain text description.

        Returns:
            Novelty score 0–1 (higher = more novel).
        """
        if isinstance(solution, str):
            return self._text_novelty(solution)

        sol = solution

        # Domain diversity
        domains = {s.domain for s in sol.source_skills}
        domain_diversity = min(1.0, len(domains) / 3.0)

        # Tag dispersion
        all_tags = sol.composite_tags or list(
            itertools.chain.from_iterable(s.tags for s in sol.source_skills)
        )
        tag_counter = Counter(all_tags)
        if tag_counter:
            tag_entropy = -sum(
                (c / len(all_tags)) * math.log2(c / len(all_tags))
                for c in tag_counter.values()
            )
            tag_dispersion = min(1.0, tag_entropy / 5.0)  # Normalize
        else:
            tag_dispersion = 0.5

        # Historical uniqueness
        uniqueness = self._historical_uniqueness(sol)

        # Number of source skills (more = more novel combination)
        skill_factor = min(1.0, len(sol.source_skills) / 4.0)

        score = (
            domain_diversity * 0.35
            + tag_dispersion * 0.25
            + uniqueness * 0.25
            + skill_factor * 0.15
        )

        return round(min(1.0, score), 3)

    def cross_domain(
        self,
        domain_a: str,
        domain_b: str,
    ) -> Optional[CrossDomainAnalogy]:
        """Find cross-domain analogies between two knowledge domains.

        Uses a curated knowledge base of domain concepts and their analogical
        mappings. Falls back to structural similarity when no direct mapping exists.

        Args:
            domain_a: First domain name (e.g., "biology", "physics").
            domain_b: Second domain name.

        Returns:
            CrossDomainAnalogy with concept mappings and insight, or None.
        """
        key = (domain_a, domain_b)
        rev_key = (domain_b, domain_a)

        if key in self._analogy_cache:
            return self._analogy_cache[key]
        if rev_key in self._analogy_cache:
            analogy = self._analogy_cache[rev_key]
            # Reverse the mapping
            return CrossDomainAnalogy(
                domain_a=domain_a,
                domain_b=domain_b,
                mapping=[(b, a) for a, b in analogy.mapping],
                insight=analogy.insight,
                strength=analogy.strength,
            )

        # Search for a template match
        for template in _DOMAIN_ANALOGY_TEMPLATES:
            t_domains = template["domains"]
            if (t_domains[0] == domain_a and t_domains[1] == domain_b) or \
               (t_domains[0] == domain_b and t_domains[1] == domain_a):
                mappings = template["mappings"]
                if t_domains[0] == domain_b:
                    mappings = [(b, a) for a, b in mappings]

                analogy = CrossDomainAnalogy(
                    domain_a=domain_a,
                    domain_b=domain_b,
                    mapping=mappings,
                    insight=template["insight"],
                    strength=0.85,
                )
                self._analogy_cache[key] = analogy
                return analogy

        # Build structural analogy from domain concepts
        concepts_a = _DOMAIN_CONCEPTS.get(domain_a, [])
        concepts_b = _DOMAIN_CONCEPTS.get(domain_b, [])

        if not concepts_a or not concepts_b:
            return None

        # Structural similarity: map concepts by shared semantic patterns
        mappings: List[Tuple[str, str]] = []
        for ca in concepts_a:
            ca_tokens = set(re.findall(r"\w+", ca.lower()))
            best_score = 0.0
            best_cb = ""
            for cb in concepts_b:
                cb_tokens = set(re.findall(r"\w+", cb.lower()))
                overlap = len(ca_tokens & cb_tokens) / max(len(ca_tokens | cb_tokens), 1)
                if overlap > best_score:
                    best_score = overlap
                    best_cb = cb
            if best_score > 0.1:
                mappings.append((ca, best_cb))

        strength = min(0.7, len(mappings) / max(len(concepts_a), 1) * 0.8)

        insight = (
            f"Both {domain_a} and {domain_b} share structural patterns in how they "
            f"handle complexity, adaptation, and system-level behavior. "
            f"Key mapping: {mappings[0][0] if mappings else 'none'} ↔ {mappings[0][1] if mappings else 'none'}"
        )

        analogy = CrossDomainAnalogy(
            domain_a=domain_a,
            domain_b=domain_b,
            mapping=mappings[:10],
            insight=insight,
            strength=round(strength, 3),
        )

        self._analogy_cache[key] = analogy
        return analogy

    def serendipity(self, *, domain: Optional[str] = None) -> Dict[str, Any]:
        """Generate a random creative connection — controlled serendipity.

        Randomly selects two domains, finds an analogy between them, and
        generates a creative insight that might spark a novel approach.

        Args:
            domain: Optional domain to anchor (the other is random).

        Returns:
            Dict with {analogy, creative_insight, suggested_application}.
        """
        available_domains = list(_DOMAIN_CONCEPTS.keys())

        if domain and domain in available_domains:
            dom_a = domain
            others = [d for d in available_domains if d != domain]
            dom_b = self._rng.choice(others) if others else available_domains[0]
        else:
            dom_a, dom_b = self._rng.sample(available_domains, 2)

        analogy = self.cross_domain(dom_a, dom_b)

        if analogy and analogy.mapping:
            mapping = self._rng.choice(analogy.mapping) if analogy.mapping else ("?", "?")
            concept_a, concept_b = mapping

            templates = [
                f"What if we applied {concept_b} ({dom_b}) to solve problems in {dom_a}?",
                f"The {dom_a} concept of {concept_a} might revolutionize how we think about {concept_b} in {dom_b}.",
                f"Could {concept_a} ({dom_a}) be the missing piece for better {concept_b} ({dom_b}) systems?",
                f"Borrow {concept_b} from {dom_b} to reimagine {concept_a} in {dom_a}.",
            ]
            creative_insight = self._rng.choice(templates)

            applications = [
                f"Build a {dom_b}-inspired approach to {dom_a} optimization",
                f"Design a hybrid {dom_a}/{dom_b} system",
                f"Use {concept_b} as a metaphor for solving {dom_a} problems",
                f"Create a {dom_b}-based tool for {dom_a} tasks",
            ]
            suggested_application = self._rng.choice(applications)
        else:
            creative_insight = f"Explore unexpected connections between {dom_a} and {dom_b}"
            suggested_application = f"Map concepts from {dom_b} onto {dom_a} problems"

        return {
            "domain_a": dom_a,
            "domain_b": dom_b,
            "analogy": analogy,
            "creative_insight": creative_insight,
            "suggested_application": suggested_application,
            "novelty_estimate": round(0.5 + self._rng.random() * 0.4, 2),
        }

    def synthesize(
        self,
        diverse_outputs: List[Any],
        *,
        method: str = "auto",
    ) -> EmergentSolution:
        """Merge N diverse approaches into one emergent solution.

        Takes multiple outputs from different strategies/approaches and synthesizes
        them into a unified solution that transcends any individual input. This is
        the core of emergent behavior.

        Supported synthesis methods:
        - "ensemble": majority vote / averaging
        - "complement": find complementary strengths
        - "dialectic": thesis + antithesis → synthesis
        - "auto": automatically choose the best method

        Args:
            diverse_outputs: List of outputs from different approaches.
            method: Synthesis method.

        Returns:
            EmergentSolution combining the best of all inputs.
        """
        if not diverse_outputs:
            return EmergentSolution(
                description="No inputs to synthesize",
                components=[],
                synthesis_method="none",
                novelty_score=0.0,
                confidence=0.0,
            )

        if len(diverse_outputs) == 1:
            return EmergentSolution(
                description=f"Single input: {str(diverse_outputs[0])[:100]}",
                components=[str(o) for o in diverse_outputs],
                synthesis_method="passthrough",
                novelty_score=0.0,
                confidence=0.5,
            )

        # Auto-select method based on output types
        if method == "auto":
            method = self._auto_select_method(diverse_outputs)

        if method == "ensemble":
            return self._ensemble_synthesis(diverse_outputs)
        elif method == "complement":
            return self._complement_synthesis(diverse_outputs)
        elif method == "dialectic":
            return self._dialectic_synthesis(diverse_outputs)
        else:
            return self._ensemble_synthesis(diverse_outputs)

    # ------------------------------------------------------------------
    # Internal synthesis methods
    # ------------------------------------------------------------------

    def _ensemble_synthesis(self, outputs: List[Any]) -> EmergentSolution:
        """Ensemble: combine by majority vote / averaging."""
        str_outputs = [str(o) for o in outputs]

        # Find consensus
        counter = Counter(str_outputs)
        most_common = counter.most_common(1)[0] if counter else ("none", 0)

        consensus_ratio = most_common[1] / len(outputs)

        # Build merged description
        if consensus_ratio >= 0.5:
            # Strong consensus
            description = (
                f"Ensemble consensus ({consensus_ratio:.0%} agreement): "
                f"{most_common[0][:200]}"
            )
            confidence = consensus_ratio
        else:
            # Mixed opinions — take best elements from each
            unique = list(set(str_outputs))
            description = (
                f"Ensemble blending {len(unique)} distinct perspectives. "
                f"Dominant: {most_common[0][:100]}. "
                f"Minority views incorporated: {', '.join(u[:60] for u in unique[1:4])}"
            )
            confidence = 0.5 + (consensus_ratio * 0.3)

        novelty = self._diversity_score(outputs)

        return EmergentSolution(
            description=description,
            components=str_outputs,
            synthesis_method="ensemble",
            novelty_score=round(novelty, 3),
            confidence=round(confidence, 3),
            rationale="Combined via consensus voting — strongest signal emerges from agreement",
        )

    def _complement_synthesis(self, outputs: List[Any]) -> EmergentSolution:
        """Find complementary strengths across outputs."""
        str_outputs = [str(o) for o in outputs]

        # Look for unique elements each contributes
        all_words: Dict[int, Set[str]] = {}
        for i, out in enumerate(str_outputs):
            all_words[i] = set(re.findall(r"\w+", out.lower()))

        # Each output's unique contribution
        unique_contributions: Dict[int, Set[str]] = {}
        for i, words in all_words.items():
            others = set()
            for j, other_words in all_words.items():
                if i != j:
                    others |= other_words
            unique_contributions[i] = words - others

        # Build description from unique elements
        meaningful = [
            (i, words) for i, words in unique_contributions.items()
            if len(words) >= 2
        ]

        if meaningful:
            parts = []
            for i, words in meaningful[:3]:
                sample = list(words)[:5]
                parts.append(f"Output {i + 1} contributes: {', '.join(sample)}")
            description = (
                "Complementary synthesis: each approach contributes unique elements. "
                + " | ".join(parts)
            )
        else:
            description = (
                "Complementary synthesis: all approaches overlap significantly — "
                "high confidence in the shared core result."
            )

        novelty = self._diversity_score(outputs) * 1.2  # complement is more novel

        return EmergentSolution(
            description=description[:500],
            components=str_outputs,
            synthesis_method="complement",
            novelty_score=round(min(1.0, novelty), 3),
            confidence=0.65,
            rationale="Each approach fills gaps the others miss — the whole exceeds the sum",
        )

    def _dialectic_synthesis(self, outputs: List[Any]) -> EmergentSolution:
        """Dialectic: thesis + antithesis → synthesis."""
        if len(outputs) < 2:
            return self._ensemble_synthesis(outputs)

        str_outputs = [str(o) for o in outputs]

        # Find the two most divergent outputs (thesis and antithesis)
        pairs: List[Tuple[int, int, float]] = []
        for i, j in itertools.combinations(range(len(outputs)), 2):
            words_i = set(re.findall(r"\w+", str_outputs[i].lower()))
            words_j = set(re.findall(r"\w+", str_outputs[j].lower()))
            union = words_i | words_j
            inter = words_i & words_j
            divergence = 1.0 - (len(inter) / len(union)) if union else 0.0
            pairs.append((i, j, divergence))

        if not pairs:
            return self._ensemble_synthesis(outputs)

        pairs.sort(key=lambda x: x[2], reverse=True)
        thesis_idx, antithesis_idx, divergence = pairs[0]

        thesis = str_outputs[thesis_idx]
        antithesis = str_outputs[antithesis_idx]

        # Build synthesis
        thesis_words = set(re.findall(r"\w+", thesis.lower()))
        antithesis_words = set(re.findall(r"\w+", antithesis.lower()))
        common = thesis_words & antithesis_words
        unique_thesis = thesis_words - antithesis_words
        unique_antithesis = antithesis_words - thesis_words

        common_sample = list(common)[:5]
        thesis_sample = list(unique_thesis)[:5]
        antithesis_sample = list(unique_antithesis)[:5]

        description = (
            f"Synthesis of opposing approaches:\n"
            f"  Thesis:   {thesis[:100]}...\n"
            f"  Antithesis: {antithesis[:100]}...\n"
            f"  Common ground: {', '.join(common_sample) if common_sample else 'none'}\n"
            f"  Synthesis preserves {', '.join(common_sample)} while incorporating "
            f"the best of both: {', '.join(thesis_sample)} from thesis and "
            f"{', '.join(antithesis_sample)} from antithesis."
        )

        novelty = 0.5 + (divergence * 0.5)

        return EmergentSolution(
            description=description[:500],
            components=str_outputs,
            synthesis_method="dialectic",
            novelty_score=round(novelty, 3),
            confidence=0.55,
            rationale="Opposing views resolved into a higher synthesis — emergent truth",
        )

    def _auto_select_method(self, outputs: List[Any]) -> str:
        """Automatically select the best synthesis method."""
        str_outputs = [str(o) for o in outputs]
        counter = Counter(str_outputs)

        # High agreement → ensemble
        most_common_ratio = counter.most_common(1)[0][1] / len(outputs)
        if most_common_ratio >= 0.7:
            return "ensemble"

        # High divergence → dialectic
        if len(set(str_outputs)) >= len(outputs) * 0.7:
            return "dialectic"

        # Moderate → complement
        return "complement"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _text_novelty(self, text: str) -> float:
        """Estimate novelty from text alone."""
        tokens = set(re.findall(r"\w+", text.lower()))
        if not tokens:
            return 0.0

        # Check against history
        min_distance = 1.0
        for hist_sol in self._history[-50:]:
            hist_tokens = set()
            for s in hist_sol.source_skills:
                hist_tokens |= s.token_set
            if hist_tokens:
                overlap = len(tokens & hist_tokens) / len(tokens | hist_tokens)
                distance = 1.0 - overlap
                min_distance = min(min_distance, distance)

        return round(min_distance, 3)

    def _historical_uniqueness(self, solution: CombinedSolution) -> float:
        """How unique is this combination relative to past solutions?"""
        if not self._history:
            return 1.0

        sol_skills = {s.name for s in solution.source_skills}
        max_similarity = 0.0

        for past in self._history[-100:]:
            past_skills = {s.name for s in past.source_skills}
            if not past_skills or not sol_skills:
                continue
            overlap = len(sol_skills & past_skills)
            union = len(sol_skills | past_skills)
            similarity = overlap / union if union > 0 else 0.0
            max_similarity = max(max_similarity, similarity)

        return 1.0 - max_similarity

    def _diversity_score(self, outputs: List[Any]) -> float:
        """Measure how diverse a set of outputs is."""
        str_outputs = [str(o) for o in outputs]
        if len(str_outputs) < 2:
            return 0.0

        # Pairwise Jaccard distances
        distances = []
        for i, j in itertools.combinations(range(len(str_outputs)), 2):
            words_i = set(re.findall(r"\w+", str_outputs[i].lower()))
            words_j = set(re.findall(r"\w+", str_outputs[j].lower()))
            union = words_i | words_j
            inter = words_i & words_j
            distance = 1.0 - (len(inter) / len(union)) if union else 0.0
            distances.append(distance)

        return sum(distances) / len(distances) if distances else 0.0

    @staticmethod
    def _describe_combination(s1: Skill, s2: Skill) -> str:
        """Generate a descriptive name for a skill combination."""
        patterns = [
            f"{s1.name}-powered {s2.name}",
            f"{s2.name}-enhanced {s1.name}",
            f"hybrid {s1.name}/{s2.name} system",
            f"{s1.domain} × {s2.domain} fusion",
        ]
        return random.choice(patterns)


# ============================================================================
# Self-test
# ============================================================================

def _self_test() -> None:
    """Run comprehensive self-tests on the Emergence Engine."""
    print("=== Emergence Self-Test ===\n")

    engine = Emergence(seed=42)

    # Build test skills
    skills = [
        Skill("quicksort", "Divide-and-conquer sorting algorithm", "algorithms",
              ["sorting", "divide-and-conquer", "in-place", "comparison"]),
        Skill("hashmap", "Key-value store with O(1) lookup", "data_structures",
              ["lookup", "hashing", "associative", "collision-resolution"]),
        Skill("bfs", "Breadth-first graph traversal", "graph",
              ["traversal", "shortest-path", "queue", "unweighted"]),
        Skill("lru_cache", "Least-recently-used cache eviction", "systems",
              ["caching", "eviction", "memory-management", "temporal-locality"]),
        Skill("gradient_descent", "Iterative optimization algorithm", "ml",
              ["optimization", "gradient", "learning-rate", "convergence"]),
        Skill("circuit_breaker", "Fault-tolerance pattern for distributed systems", "engineering",
              ["resilience", "failure-detection", "state-machine", "fallback"]),
        Skill("genetic_algorithm", "Evolution-inspired optimization", "biology",
              ["evolution", "mutation", "crossover", "fitness", "population"]),
        Skill("attention_mechanism", "Transformer attention for sequence modeling", "psychology",
              ["attention", "sequence", "weighted-sum", "context"]),
        Skill("market_auction", "Bid-based resource allocation", "economics",
              ["auction", "bidding", "allocation", "price-discovery"]),
        Skill("negative_space", "Use of empty space in composition", "art",
              ["composition", "minimalism", "visual-design", "balance"]),
    ]

    # Test 1: Combine skills
    print("Test 1: Creative recombination")
    combinations = engine.combine(skills, "build a fast distributed cache")
    assert len(combinations) > 0, "Expected at least one combination"
    for combo in combinations[:3]:
        print(f"  [{combo.novelty:.2f}] {combo.description[:100]}...")
    print("  PASS\n")

    # Test 2: Novelty score
    print("Test 2: Novelty scoring")
    if combinations:
        score = engine.novelty_score(combinations[0])
        assert 0.0 <= score <= 1.0, f"Novelty score out of range: {score}"
        print(f"  Top combo novelty: {score}")
    score2 = engine.novelty_score("use blockchain for decentralized voting")
    assert 0.0 <= score2 <= 1.0
    print(f"  Text novelty: {score2}")
    print("  PASS\n")

    # Test 3: Cross-domain analogy
    print("Test 3: Cross-domain analogies")
    analogy1 = engine.cross_domain("biology", "computer_science")
    assert analogy1 is not None
    assert len(analogy1.mapping) > 0
    print(f"  {analogy1}")
    print(f"  Sample mapping: {analogy1.mapping[0]}")
    print("  PASS\n")

    analogy2 = engine.cross_domain("physics", "economics")
    assert analogy2 is not None
    print(f"  {analogy2}")
    print("  PASS\n")

    # Test 4: Serendipity
    print("Test 4: Serendipitous connections")
    for i in range(3):
        s = engine.serendipity()
        assert "creative_insight" in s
        assert "suggested_application" in s
        print(f"  Serendipity {i + 1}: {s['domain_a']} × {s['domain_b']}")
        print(f"    → {s['creative_insight'][:80]}...")
    print("  PASS\n")

    # Test 5: Synthesize — ensemble
    print("Test 5: Ensemble synthesis")
    outputs = ["result_a_fast", "result_a_fast", "result_a_fast", "result_b_slow"]
    emergent = engine.synthesize(outputs, method="ensemble")
    assert emergent.synthesis_method == "ensemble"
    assert emergent.confidence >= 0.5
    print(f"  {emergent}")
    print("  PASS\n")

    # Test 6: Synthesize — complement
    print("Test 6: Complement synthesis")
    outputs2 = [
        "sort using quicksort divide and conquer recursion",
        "sort using merge sort external memory stable",
        "sort using heap sort in-place priority queue",
    ]
    emergent2 = engine.synthesize(outputs2, method="complement")
    assert emergent2.synthesis_method == "complement"
    print(f"  Novelty: {emergent2.novelty_score}")
    print(f"  {emergent2.description[:200]}...")
    print("  PASS\n")

    # Test 7: Synthesize — dialectic
    print("Test 7: Dialectic synthesis")
    outputs3 = [
        "use SQL database for structured data with ACID guarantees",
        "use NoSQL for flexible schema and horizontal scaling",
        "use caching layer for read-heavy workloads",
    ]
    emergent3 = engine.synthesize(outputs3, method="dialectic")
    assert emergent3.synthesis_method == "dialectic"
    print(f"  Novelty: {emergent3.novelty_score}")
    print(f"  {emergent3.description[:200]}...")
    print("  PASS\n")

    # Test 8: Auto synthesis
    print("Test 8: Auto method selection")
    identical = ["same", "same", "same", "same"]
    emergent4 = engine.synthesize(identical, method="auto")
    assert emergent4.synthesis_method == "ensemble"
    print(f"  Auto-selected: {emergent4.synthesis_method} (for identical outputs)")

    diverse = ["a", "b", "c", "d", "e"]
    emergent5 = engine.synthesize(diverse, method="auto")
    print(f"  Auto-selected: {emergent5.synthesis_method} (for diverse outputs)")
    print("  PASS\n")

    print("=== All Emergence tests passed ===")


if __name__ == "__main__":
    _self_test()