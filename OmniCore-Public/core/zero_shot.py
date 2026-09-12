"""First-principles problem solving — no training data, pure reasoning from axioms.

DNA: Prophet (axiomatic reasoning, first-principles decomposition).

The ZeroShot solver breaks any problem into its fundamental components,
identifies base axioms and invariants, then reconstructs a solution from
those primitives.  No training data, no pre-existing knowledge base —
only the problem description and universal reasoning patterns.

Usage::

    zs = ZeroShot()
    result = zs.solve("How can a small startup compete with a tech giant?")
    print(result.solution)
    for step in result.principle_chain:
        print(f"  {step.level}: {step.principle} → {step.implication}")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ── Universal axioms ──────────────────────────────────────────────────

UNIVERSAL_AXIOMS = [
    # Physics / systems
    "Every system has a boundary — what is inside vs outside determines behavior.",
    "Resources are finite; any solution must respect conservation constraints.",
    "Feedback loops (reinforcing or balancing) govern dynamic systems.",
    "Small changes at leverage points produce disproportionate effects.",
    "Entropy increases in closed systems; open systems import negentropy.",
    # Economics / strategy
    "Comparative advantage: entities should focus on their relative strengths.",
    "Incentives drive behavior; align incentives with desired outcomes.",
    "Transaction costs shape optimal boundaries (make vs buy, integrate vs outsource).",
    "Network effects produce winner-take-most dynamics in platform markets.",
    "Information asymmetry creates power imbalances and market failures.",
    # Cognition / decision
    "Satisficing beats optimizing when search costs are high.",
    "The map is not the territory — models are simplifications, not reality.",
    "Every decision involves trade-offs; there is no free lunch.",
    "Framing a problem differently often reveals better solutions than optimizing within a given frame.",
    "Diversity of perspectives reduces blind spots and improves robustness.",
    # Biology / evolution
    "Variation + selection + retention = adaptation.",
    "Cooperation and competition coexist; the boundary depends on context.",
    "Redundancy creates resilience; single points of failure create fragility.",
    # Math / logic
    "Any consistent formal system contains unprovable truths (Gödel).",
    "Recursive structures can generate infinite complexity from finite rules.",
    "Symmetry implies conservation laws (Noether).",
]

# ── Decomposition dimensions ──────────────────────────────────────────

DECOMPOSITION_DIMENSIONS = [
    ("stakeholders", "Who is involved? Who wins? Who loses?"),
    ("resources", "What resources are required? What is scarce?"),
    ("constraints", "What cannot be changed? What are the hard boundaries?"),
    ("goals", "What is the actual desired outcome? (vs stated goal)"),
    ("mechanisms", "What causal mechanisms are at play?"),
    ("timescale", "Short-term vs long-term dynamics?"),
    ("scale", "Does the solution scale or break at different sizes?"),
    ("failure_modes", "How can this go wrong? What's the worst case?"),
    ("assumptions", "What are we taking for granted that might be false?"),
    ("invariants", "What must remain true regardless of the solution?"),
]


@dataclass
class PrincipleStep:
    """One step in the principle chain — an axiom applied to the problem."""
    level: int                # 0 = foundational, 1+ = derived
    principle: str            # The axiom or derived principle
    implication: str          # What this implies for the problem
    confidence: float         # 0.0–1.0


@dataclass
class FirstPrincipleNode:
    """A node in the first-principles decomposition tree."""
    component: str            # Name of this component
    description: str          # What this component is
    children: list[FirstPrincipleNode] = field(default_factory=list)
    axioms: list[str] = field(default_factory=list)


@dataclass
class ZeroShotResult:
    """Result of a zero-shot first-principles solve."""
    problem: str
    solution: str
    principle_chain: list[PrincipleStep]
    decomposition: list[dict]          # dimension → breakdown
    confidence: float
    irreducible_elements: list[str]    # The fundamental primitives


class ZeroShot:
    """First-principles problem solver.

    Breaks problems into irreducible elements, maps them to universal
    axioms, and reconstructs solutions from base principles.  Requires
    no training data — pure reasoning.

    Usage::

        zs = ZeroShot()
        result = zs.solve("How to design a self-driving car safety system?")
        print(result.solution)
    """

    def __init__(self, seed: Optional[int] = None):
        import random
        self._rng = random.Random(seed)

    # ── Public API ────────────────────────────────────────────────────

    def solve(self, problem_description: str) -> ZeroShotResult:
        """Solve a problem from first principles.

        Args:
            problem_description: Natural-language description of the problem.

        Returns:
            ZeroShotResult with solution, principle_chain, decomposition, etc.
        """
        # 1. Extract the core question
        core = self._extract_core(problem_description)

        # 2. Decompose into dimensions
        decomposition = self._decompose(problem_description)

        # 3. Identify irreducible elements
        elements = self._find_irreducible_elements(problem_description, decomposition)

        # 4. Map to universal axioms
        principle_chain = self._build_principle_chain(problem_description, elements, decomposition)

        # 5. Reconstruct solution from axioms
        solution = self._reconstruct(problem_description, principle_chain, decomposition)

        # 6. Compute confidence
        confidence = self._compute_solution_confidence(principle_chain, decomposition)

        return ZeroShotResult(
            problem=problem_description,
            solution=solution,
            principle_chain=principle_chain,
            decomposition=decomposition,
            confidence=confidence,
            irreducible_elements=elements,
        )

    # ── Step 1: Extract core question ─────────────────────────────────

    def _extract_core(self, problem: str) -> str:
        """Extract the fundamental question from a description."""
        # Remove framing words
        cleaned = problem.strip().rstrip("?").rstrip(".")

        # Check if it's already a question
        question_words = [
            "how", "what", "why", "when", "where", "who",
            "should", "can", "could", "would", "is", "are",
        ]
        first_word = cleaned.split()[0].lower() if cleaned.split() else ""

        if first_word in question_words:
            return cleaned

        # Convert statement to core question
        return f"how to {cleaned[0].lower() + cleaned[1:] if cleaned else cleaned}"

    # ── Step 2: Decompose ─────────────────────────────────────────────

    def _decompose(self, problem: str) -> list[dict]:
        """Decompose problem across all standard dimensions."""
        results: list[dict] = []

        for dim_name, dim_prompt in DECOMPOSITION_DIMENSIONS:
            breakdown = self._analyse_dimension(problem, dim_name, dim_prompt)
            results.append({
                "dimension": dim_name,
                "question": dim_prompt,
                "analysis": breakdown,
            })

        return results

    def _analyse_dimension(self, problem: str, dim: str, prompt: str) -> str:
        """Analyse a single dimension of the problem."""
        # Pattern-based analysis for each dimension
        analysers = {
            "stakeholders": lambda p: self._find_stakeholders(p),
            "resources": lambda p: self._find_resources(p),
            "constraints": lambda p: self._find_constraints(p),
            "goals": lambda p: self._find_goals(p),
            "mechanisms": lambda p: self._find_mechanisms(p),
            "timescale": lambda p: self._find_timescale(p),
            "scale": lambda p: self._find_scale_behavior(p),
            "failure_modes": lambda p: self._find_failure_modes(p),
            "assumptions": lambda p: self._find_assumptions(p),
            "invariants": lambda p: self._find_invariants(p),
        }

        analyser = analysers.get(dim, lambda p: f"Analysis of {dim} for: {p[:80]}")
        return analyser(problem)

    def _find_stakeholders(self, problem: str) -> str:
        """Identify likely stakeholders from problem keywords."""
        lower = problem.lower()
        stakeholders: list[str] = []

        keyword_map = {
            "business": ["owners", "employees", "customers", "investors", "regulators"],
            "software": ["users", "developers", "operators", "security team", "product managers"],
            "city": ["residents", "businesses", "government", "visitors", "workers"],
            "health": ["patients", "doctors", "insurers", "hospitals", "regulators"],
            "education": ["students", "teachers", "parents", "administrators", "employers"],
            "energy": ["consumers", "producers", "regulators", "environment", "investors"],
            "startup": ["founders", "employees", "customers", "investors", "competitors"],
            "team": ["members", "leader", "stakeholders", "sponsors", "users"],
            "product": ["users", "builders", "buyers", "competitors", "regulators"],
            "security": ["attackers", "defenders", "users", "administrators", "auditors"],
        }

        for keyword, stks in keyword_map.items():
            if keyword in lower:
                stakeholders.extend(stks)

        if not stakeholders:
            stakeholders = [
                "primary actors", "affected parties", "decision makers",
                "implementers", "beneficiaries",
            ]

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique = []
        for s in stakeholders:
            if s not in seen:
                seen.add(s)
                unique.append(s)

        return f"Stakeholders: {', '.join(unique)}. Key dynamic: "
        f"The {unique[0] if unique else 'primary actors'} drive the system, "
        f"while {unique[-1] if len(unique) > 1 else 'others'} feel the consequences."

    def _find_resources(self, problem: str) -> str:
        lower = problem.lower()
        resources: list[str] = []

        if any(w in lower for w in ["money", "cost", "budget", "funding", "capital", "revenue"]):
            resources.append("financial capital")
        if any(w in lower for w in ["time", "deadline", "schedule", "fast", "speed"]):
            resources.append("time")
        if any(w in lower for w in ["people", "team", "talent", "expert", "skill"]):
            resources.append("human talent")
        if any(w in lower for w in ["data", "information", "knowledge", "insight"]):
            resources.append("information")
        if any(w in lower for w in ["tech", "code", "infrastructure", "system", "platform"]):
            resources.append("technology")
        if any(w in lower for w in ["attention", "focus", "mindshare"]):
            resources.append("attention")
        if any(w in lower for w in ["trust", "reputation", "brand"]):
            resources.append("trust/reputation")

        if not resources:
            resources = ["time", "effort", "attention"]

        scarce = resources[0] if resources else "time"
        return (
            f"Resources involved: {', '.join(resources)}. "
            f"The scarcest is likely {scarce} — optimise this first."
        )

    def _find_constraints(self, problem: str) -> str:
        lower = problem.lower()
        constraints: list[str] = []

        if any(w in lower for w in ["small", "limited", "startup", "few"]):
            constraints.append("limited resources/scale")
        if any(w in lower for w in ["compete", "competition", "giant", "dominate"]):
            constraints.append("asymmetric competition")
        if any(w in lower for w in ["regulation", "compliance", "legal", "law"]):
            constraints.append("regulatory requirements")
        if any(w in lower for w in ["legacy", "existing", "old", "migration"]):
            constraints.append("legacy system compatibility")
        if any(w in lower for w in ["privacy", "secure", "protect"]):
            constraints.append("privacy/security requirements")
        if any(w in lower for w in ["deadline", "urgent", "quickly", "fast"]):
            constraints.append("time pressure")

        if not constraints:
            constraints.append("resource constraints (universal)")

        return (
            f"Hard constraints: {', '.join(constraints)}. "
            f"The tightest constraint is {constraints[0]} — "
            f"this should shape the solution architecture."
        )

    def _find_goals(self, problem: str) -> str:
        lower = problem.lower()

        goal_signals = {
            "reduce": "minimise",
            "increase": "maximise",
            "improve": "optimise",
            "eliminate": "remove entirely",
            "compete": "achieve competitive parity or advantage",
            "build": "create from scratch",
            "design": "create a specification or system",
            "solve": "eliminate the root cause",
            "protect": "prevent harm or loss",
            "grow": "scale up sustainably",
        }

        verb = "optimise"
        for kw, goal in goal_signals.items():
            if kw in lower:
                verb = goal
                break

        return (
            f"Primary goal: {verb} the system. "
            f"The metric of success is whether the underlying need is met, "
            f"not whether the surface symptoms are suppressed."
        )

    def _find_mechanisms(self, problem: str) -> str:
        """Identify causal mechanisms."""
        lower = problem.lower()

        if any(w in lower for w in ["network", "platform", "marketplace"]):
            return "Network effects and two-sided market dynamics are likely at play."
        if any(w in lower for w in ["learn", "data", "ai", "model"]):
            return "Learning curves and data flywheels — more data → better model → more users → more data."
        if any(w in lower for w in ["scale", "growth", "expand"]):
            return "Economies of scale and scope — fixed costs amortised over larger volume."
        if any(w in lower for w in ["feedback", "loop", "cycle"]):
            return "Reinforcing or balancing feedback loops dominate the system dynamics."
        if any(w in lower for w in ["compete", "competition", "rival"]):
            return "Competitive dynamics — moves and counter-moves, game-theoretic considerations."

        return "Standard input → process → output mechanisms with feedback loops."

    def _find_timescale(self, problem: str) -> str:
        return (
            "Short-term: immediate actions and visible results (days to weeks). "
            "Medium-term: structural changes and capability building (months). "
            "Long-term: emergent outcomes and systemic shifts (years). "
            "Key insight: most problems are over-optimised for the short term "
            "at the expense of long-term robustness."
        )

    def _find_scale_behavior(self, problem: str) -> str:
        return (
            "At small scale: personal, manual, high-touch, custom solutions work. "
            "At medium scale: processes, automation, standardisation become necessary. "
            "At large scale: platforms, ecosystems, self-organisation emerge. "
            "The solution must either specify its target scale or design for graceful scaling."
        )

    def _find_failure_modes(self, problem: str) -> str:
        lower = problem.lower()
        modes: list[str] = []

        if any(w in lower for w in ["tech", "software", "code", "system"]):
            modes.append("technical failure (bugs, crashes, data loss)")
        if any(w in lower for w in ["people", "team", "user"]):
            modes.append("human error (misuse, misunderstanding, fatigue)")
        if any(w in lower for w in ["compete", "market", "business"]):
            modes.append("strategic failure (outcompeted, disrupted, irrelevant)")
        if any(w in lower for w in ["security", "attack", "threat"]):
            modes.append("security breach (exploited vulnerability)")

        modes.append("unknown unknowns (black swan events)")

        return (
            f"Failure modes: {', '.join(modes)}. "
            f"The most dangerous are the silent failures — "
            f"the ones that accumulate unnoticed until catastrophic."
        )

    def _find_assumptions(self, problem: str) -> str:
        return (
            "Implicit assumptions to challenge:\n"
            "1. The problem is correctly framed (it may not be).\n"
            "2. The stated goal is the real goal (it may be a proxy).\n"
            "3. Current constraints are immutable (they rarely are).\n"
            "4. The solution must come from the same domain as the problem.\n"
            "5. More resources would solve it (often, better strategy would)."
        )

    def _find_invariants(self, problem: str) -> str:
        return (
            "Invariants — what must remain true:\n"
            "1. The solution must not make things worse.\n"
            "2. The root cause must be addressed, not just symptoms.\n"
            "3. The solution must work under realistic constraints.\n"
            "4. The cost of the solution must be less than the cost of the problem.\n"
            "5. The solution must be robust to reasonable perturbations."
        )

    # ── Step 3: Irreducible elements ──────────────────────────────────

    def _find_irreducible_elements(
        self, problem: str, decomposition: list[dict]
    ) -> list[str]:
        """Identify the fundamental, irreducible primitives of the problem."""
        lower = problem.lower()

        elements: list[str] = []

        # Extract nouns and noun phrases that seem fundamental
        fundamental_patterns = [
            (r'\b(trust|reputation|credibility)\b', "trust"),
            (r'\b(information|data|knowledge|signal)\b', "information"),
            (r'\b(incentive|motivation|reward|punishment)\b', "incentives"),
            (r'\b(coordination|cooperation|collaboration|alignment)\b', "coordination"),
            (r'\b(resource|capital|funding|budget|asset)\b', "resources"),
            (r'\b(constraint|limit|boundary|restriction)\b', "constraints"),
            (r'\b(feedback|response|reaction|adaptation)\b', "feedback"),
            (r'\b(time|deadline|urgency|patience)\b', "time"),
            (r'\b(attention|focus|priority|importance)\b', "attention"),
            (r'\b(relationship|connection|network|link)\b', "relationships"),
        ]

        for pattern, element in fundamental_patterns:
            if re.search(pattern, lower) and element not in elements:
                elements.append(element)

        if not elements:
            elements = ["goals", "constraints", "resources", "feedback"]

        return elements

    # ── Step 4: Build principle chain ─────────────────────────────────

    def _build_principle_chain(
        self,
        problem: str,
        elements: list[str],
        decomposition: list[dict],
    ) -> list[PrincipleStep]:
        """Map problem elements to universal axioms, building a reasoning chain."""
        chain: list[PrincipleStep] = []

        # Level 0: Map foundational axioms
        relevant_axioms = self._select_relevant_axioms(problem, elements)
        for i, axiom in enumerate(relevant_axioms):
            implication = self._axiom_to_implication(axiom, problem)
            chain.append(PrincipleStep(
                level=0,
                principle=axiom,
                implication=implication,
                confidence=0.9,
            ))

        # Level 1: Derive implications
        if chain:
            chain.append(PrincipleStep(
                level=1,
                principle=f"From the axioms above, the core dynamic is: "
                          f"{self._synthesise_core_dynamic(chain, problem)}",
                implication=self._derive_implication_level1(chain, problem),
                confidence=0.75,
            ))

        # Level 2: Actionable consequence
        if len(chain) >= 2:
            chain.append(PrincipleStep(
                level=2,
                principle="The highest-leverage intervention targets the "
                          "intersection of the scarcest resource and the "
                          "strongest feedback loop.",
                implication=self._derive_actionable(chain, problem, elements),
                confidence=0.65,
            ))

        return chain

    def _select_relevant_axioms(
        self, problem: str, elements: list[str]
    ) -> list[str]:
        """Select the most relevant universal axioms."""
        lower = problem.lower()

        keyword_to_axiom = {
            "compete": 3,   # comparative advantage
            "small": 3,     # comparative advantage
            "startup": 3,   # comparative advantage
            "incentive": 6,  # incentives drive behavior
            "feedback": 2,   # feedback loops
            "scale": 8,      # network effects
            "network": 8,    # network effects
            "platform": 8,   # network effects
            "resource": 1,   # resources finite
            "trade": 12,     # trade-offs
            "decision": 12,  # trade-offs
            "evolve": 16,    # variation + selection
            "adapt": 16,     # variation + selection
            "design": 13,    # map not territory
            "model": 13,     # map not territory
            "reduce": 3,     # comparative advantage / focus
            "improve": 2,    # feedback loops
            "grow": 8,       # network effects
            "team": 16,      # cooperation + competition
            "security": 1,   # resources finite
            "risk": 17,      # redundancy → resilience
            "failure": 17,   # redundancy → resilience
        }

        scored: list[tuple[int, str]] = []
        for kw, axiom_idx in keyword_to_axiom.items():
            if kw in lower:
                scored.append((axiom_idx, UNIVERSAL_AXIOMS[axiom_idx]))

        # Deduplicate by axiom text
        seen: set[str] = set()
        unique = []
        for idx, axiom in scored:
            if axiom not in seen:
                seen.add(axiom)
                unique.append(axiom)

        # Always add a few foundational ones
        foundational = [
            UNIVERSAL_AXIOMS[4],   # entropy
            UNIVERSAL_AXIOMS[12],  # trade-offs
            UNIVERSAL_AXIOMS[13],  # framing
        ]

        result = unique[:3] if unique else []
        for ax in foundational:
            if ax not in result and len(result) < 5:
                result.append(ax)

        return result[:5]

    def _axiom_to_implication(self, axiom: str, problem: str) -> str:
        """Translate a universal axiom into a problem-specific implication."""
        core = self._extract_core(problem)

        # Pattern: extract the key lesson from each axiom
        if "comparative advantage" in axiom:
            return (
                f"For '{core}': identify and amplify the unique strengths "
                f"that competitors cannot easily replicate. Don't compete "
                f"where the opponent is strongest."
            )
        if "incentives drive behavior" in axiom:
            return (
                f"For '{core}': map the incentive structure. If the desired "
                f"outcome isn't happening, the incentives are likely misaligned. "
                f"Change incentives, not commands."
            )
        if "Feedback loops" in axiom:
            return (
                f"For '{core}': identify the dominant feedback loops. "
                f"Reinforcing loops amplify small differences; balancing "
                f"loops resist change. Work with the loops, not against them."
            )
        if "resources are finite" in axiom or "Resources are finite" in axiom:
            return (
                f"For '{core}': identify the binding constraint — the one "
                f"resource that, if increased, would unlock everything else. "
                f"Optimise that first."
            )
        if "Network effects" in axiom:
            return (
                f"For '{core}': if network effects apply, the strategy shifts "
                f"from 'better product' to 'bigger network'. Speed and liquidity "
                f"matter more than features."
            )
        if "map is not the territory" in axiom:
            return (
                f"For '{core}': question whether the problem as stated is the "
                f"real problem. The framing may be obscuring a simpler, deeper issue."
            )
        if "trade-off" in axiom.lower():
            return (
                f"For '{core}': explicitly list the trade-offs. Any solution "
                f"that claims to have none is hiding something."
            )
        if "Variation + selection" in axiom:
            return (
                f"For '{core}': generate many small experiments, kill the "
                f"failures fast, double down on what works. Speed of iteration "
                f"beats perfection of planning."
            )
        if "Redundancy" in axiom or "redundancy" in axiom:
            return (
                f"For '{core}': identify single points of failure and add "
                f"redundancy. Resilience costs less than catastrophic failure."
            )
        if "Entropy" in axiom:
            return (
                f"For '{core}': systems naturally decay unless energy is "
                f"continuously invested. Plan for maintenance, not just creation."
            )
        if "Framing" in axiom:
            return (
                f"For '{core}': reframe the problem before solving it. "
                f"The frame defines the solution space; a better frame "
                f"reveals options invisible in the original framing."
            )

        return f"For '{core}': this principle suggests examining the fundamental dynamics before optimising the surface."

    def _synthesise_core_dynamic(
        self, chain: list[PrincipleStep], problem: str
    ) -> str:
        """Synthesise the core system dynamic from the axioms."""
        if len(chain) >= 2:
            return (
                f"The problem involves interacting forces where "
                f"{chain[0].principle[:60].lower()}... and "
                f"{chain[1].principle[:60].lower()}... "
                f"create the observed behavior."
            )
        return "The core dynamic emerges from the interaction of constraints, incentives, and feedback."

    def _derive_implication_level1(
        self, chain: list[PrincipleStep], problem: str
    ) -> str:
        """Derive a level-1 implication."""
        return (
            "The most effective intervention will target the highest-leverage "
            "point in the system — typically a feedback loop or an incentive "
            "structure — rather than directly attacking symptoms."
        )

    def _derive_actionable(
        self, chain: list[PrincipleStep], problem: str, elements: list[str]
    ) -> str:
        """Derive concrete, actionable next steps."""
        primary = elements[0] if elements else "constraints"

        actions = {
            "trust": "Build trust through transparency and consistency before asking for commitment.",
            "information": "Reduce information asymmetry — make the invisible visible.",
            "incentives": "Redesign the incentive structure so that the desired behavior is the easiest behavior.",
            "coordination": "Create coordination mechanisms (standards, platforms, rituals) that reduce transaction costs.",
            "resources": "Identify and amplify the most leveraged resource; the scarce one that unlocks others.",
            "constraints": "Challenge each constraint — which are real and which are assumed?",
            "feedback": "Install fast, visible feedback loops so the system can self-correct.",
            "time": "Invest in leverage that compounds over time rather than one-off fixes.",
            "attention": "Focus on the one thing that, if solved, makes everything else easier or irrelevant.",
            "relationships": "Strengthen the relational fabric — trust, communication, shared understanding.",
        }

        return actions.get(primary, "Address the root cause, measure results, iterate rapidly.")

    # ── Step 5: Reconstruct solution ──────────────────────────────────

    def _reconstruct(
        self,
        problem: str,
        chain: list[PrincipleStep],
        decomposition: list[dict],
    ) -> str:
        """Reconstruct a full solution from the principle chain."""
        if not chain:
            return "Insufficient principles to reconstruct a solution."

        # Extract key insights from the chain
        axioms = [s for s in chain if s.level == 0]
        actionable = [s for s in chain if s.level == 2]

        parts: list[str] = []

        # 1. Reframe
        parts.append(
            f"The problem '{problem[:120]}' can be reframed as: "
        )
        # Find the most relevant axiom
        if axioms:
            parts.append(f"a {axioms[0].principle[:80].lower()}... challenge. ")

        # 2. Core insight
        parts.append(
            "The core insight is that the surface problem is driven by deeper "
            "structural dynamics. Rather than optimising symptoms, the solution "
            "must address the underlying system. "
        )

        # 3. Approach
        parts.append("The recommended approach: ")
        approach_steps = [
            "First, map the full system — stakeholders, incentives, feedback loops.",
            "Second, identify the highest-leverage intervention point.",
            "Third, design the minimal intervention that shifts the system dynamics.",
            "Fourth, measure results with fast feedback and iterate.",
            "Fifth, institutionalise what works and eliminate what doesn't.",
        ]
        parts.append("; ".join(approach_steps) + ". ")

        # 4. Concrete action
        if actionable:
            parts.append(f"Immediate next step: {actionable[0].implication}")

        return "".join(parts)

    # ── Step 6: Confidence ────────────────────────────────────────────

    def _compute_solution_confidence(
        self,
        chain: list[PrincipleStep],
        decomposition: list[dict],
    ) -> float:
        """Compute solution confidence from chain depth and decomposition coverage."""
        if not chain:
            return 0.1

        # Chain depth
        max_level = max(s.level for s in chain) if chain else 0
        depth_score = min(1.0, max_level / 3.0)

        # Number of axioms mapped
        axiom_score = min(1.0, len([s for s in chain if s.level == 0]) / 5.0)

        # Decomposition coverage
        coverage_score = min(1.0, len(decomposition) / len(DECOMPOSITION_DIMENSIONS))

        # Weighted average
        return round(depth_score * 0.3 + axiom_score * 0.4 + coverage_score * 0.3, 3)


# ── Self-test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("ZERO-SHOT SOLVER SELF-TEST")
    print("=" * 60)

    zs = ZeroShot(seed=42)

    # ── Test 1: Classic strategy problem ──────────────────────────────
    print("\n── Test 1: Startup vs giant ──")
    result = zs.solve("How can a small startup compete with a tech giant?")
    print(f"Confidence: {result.confidence}")
    print(f"Irreducible elements: {result.irreducible_elements}")
    print(f"Principle chain length: {len(result.principle_chain)}")
    print(f"Decomposition dimensions: {len(result.decomposition)}")
    print(f"\nSolution:\n{result.solution[:400]}...")
    assert len(result.principle_chain) > 0
    assert result.confidence > 0
    assert len(result.irreducible_elements) > 0

    # ── Test 2: Technical problem ─────────────────────────────────────
    print("\n── Test 2: Security design ──")
    result2 = zs.solve("How to design a self-driving car safety system?")
    print(f"Confidence: {result2.confidence}")
    print(f"Principle chain length: {len(result2.principle_chain)}")
    print(f"Elements: {result2.irreducible_elements}")
    assert len(result2.decomposition) == len(DECOMPOSITION_DIMENSIONS)

    # ── Test 3: Social problem ────────────────────────────────────────
    print("\n── Test 3: Team communication ──")
    result3 = zs.solve("How to improve team communication in a remote company?")
    print(f"Confidence: {result3.confidence}")
    print(f"Elements: {result3.irreducible_elements}")
    assert result3.solution, "Solution should not be empty"

    # ── Test 4: Principle chain integrity ─────────────────────────────
    print("\n── Test 4: Principle chain structure ──")
    chain = result.principle_chain
    levels = set(s.level for s in chain)
    print(f"Levels present: {sorted(levels)}")
    # Should have at least level 0 (axioms)
    assert 0 in levels, "Should have foundational axioms"

    # Verify chain ordering (levels non-decreasing)
    for i in range(1, len(chain)):
        assert chain[i].level >= chain[i - 1].level, (
            f"Chain level decreased at position {i}"
        )
    print("Chain ordering verified ✅")

    # ── Test 5: Decomposition completeness ────────────────────────────
    print("\n── Test 5: Decomposition coverage ──")
    dims = {d["dimension"] for d in result.decomposition}
    expected = {d[0] for d in DECOMPOSITION_DIMENSIONS}
    print(f"Dimensions covered: {len(dims)} / {len(expected)}")
    assert dims == expected, f"Missing dimensions: {expected - dims}"

    # ── Test 6: Solution confidence bounds ────────────────────────────
    print("\n── Test 6: Confidence bounds ──")
    for prob in [
        "How to X?",
        "How to design a complex multi-stakeholder system with regulatory constraints?",
    ]:
        r = zs.solve(prob)
        print(f"  Confidence for '{prob[:50]}...': {r.confidence}")
        assert 0.0 <= r.confidence <= 1.0, "Confidence out of bounds"

    print("\n✅ All zero-shot solver tests passed!")