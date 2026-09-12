"""Philosophical debate engine — multi-perspective reasoning, dialectic, ethics.

DNA: Socratic + Hegelian + Stoic + Utilitarian + Nihilist synthesis.
Each perspective is a distinct reasoning persona with its own axioms.

Usage:
    phil = Philosophy()
    result = phil.debate("Is AI consciousness possible?", perspectives=None)
    synthesis = phil.thesis_antithesis_synthesis("Free will vs determinism")
    dialogue = phil.socratic_dialogue("What is justice?")
    check = phil.ethical_check("Deploy facial recognition in public spaces")
    wisdom = phil.wisdom_extract("A long philosophical text...")
"""

import time
from dataclasses import dataclass, field
from typing import Any


# ── Perspective definitions ────────────────────────────────────────────

@dataclass
class Perspective:
    """A philosophical perspective with axioms and reasoning style."""
    name: str
    description: str
    axioms: list[str]
    reasoning_style: str
    representative: str = ""  # Representative thinker


PERSPECTIVES: dict[str, Perspective] = {
    "utilitarian": Perspective(
        name="Utilitarian",
        description="Greatest good for the greatest number — Bentham/Mill",
        axioms=[
            "Actions are right if they promote happiness",
            "Pleasure and freedom from pain are the only desirable ends",
            "Each person counts equally in the happiness calculus",
        ],
        reasoning_style="Cost-benefit analysis. Quantify outcomes. Maximize utility.",
        representative="Jeremy Bentham, John Stuart Mill",
    ),
    "deontological": Perspective(
        name="Deontological",
        description="Duty-based ethics — Kant's categorical imperative",
        axioms=[
            "Act only according to maxims you can will as universal law",
            "Treat humanity always as an end, never merely as a means",
            "Moral worth comes from duty, not consequences",
        ],
        reasoning_style="Rule-based. Universalize the maxim. Check for contradictions.",
        representative="Immanuel Kant",
    ),
    "virtue_ethics": Perspective(
        name="Virtue Ethics",
        description="Character-based ethics — Aristotle's golden mean",
        axioms=[
            "The goal is eudaimonia (human flourishing)",
            "Virtue is the mean between excess and deficiency",
            "Practical wisdom (phronesis) guides moral action",
        ],
        reasoning_style="What would a virtuous person do? Find the mean.",
        representative="Aristotle",
    ),
    "nihilist": Perspective(
        name="Nihilist",
        description="Rejection of inherent meaning — Nietzschean critique",
        axioms=[
            "There is no objective meaning or purpose",
            "Morality is a human construct, not a cosmic truth",
            "Freedom comes from creating one's own values",
        ],
        reasoning_style="Deconstruct assumptions. Question everything. Embrace the void.",
        representative="Friedrich Nietzsche",
    ),
    "stoic": Perspective(
        name="Stoic",
        description="Resilience through reason — Marcus Aurelius, Epictetus",
        axioms=[
            "Some things are within our control, others are not",
            "Virtue (wisdom, justice, courage, temperance) is sufficient for happiness",
            "Suffering comes from judgments, not events",
        ],
        reasoning_style="Dichotomy of control. Focus on what you can change. Accept the rest.",
        representative="Marcus Aurelius, Epictetus, Seneca",
    ),
}


@dataclass
class DebateResult:
    """Result of a multi-perspective debate."""
    question: str
    arguments: dict[str, str]  # perspective_name → argument
    synthesis: str
    perspectives_used: list[str]
    duration_ms: float


@dataclass
class SocraticResult:
    """Result of a Socratic dialogue."""
    topic: str
    questions: list[str]
    insights: list[str]
    final_reflection: str


@dataclass
class EthicalCheck:
    """Ethical evaluation of an action."""
    action: str
    scores: dict[str, float]  # perspective → score (-1.0 to 1.0)
    verdict: str  # "endorsed", "caution", "rejected", "ambiguous"
    reasoning: dict[str, str]
    recommendation: str


# ── Philosophy class ───────────────────────────────────────────────────

class Philosophy:
    """Philosophical reasoning engine.

    Runs multi-perspective debates, Hegelian dialectic, Socratic dialogue,
    ethical evaluations, and wisdom extraction.
    """

    def __init__(self):
        self._perspectives = dict(PERSPECTIVES)
        self._dialogue_history: list[dict[str, Any]] = []

    # ── Debate ─────────────────────────────────────────────────────────

    def debate(self, question: str,
               perspectives: list[str] | None = None) -> DebateResult:
        """Run a multi-perspective philosophical debate.

        Each perspective generates an argument from its axioms.
        Then a synthesis is produced reconciling the strongest points.

        Args:
            question: The philosophical question to debate.
            perspectives: List of perspective names to use.
                          If None, uses all available: utilitarian,
                          deontological, virtue_ethics, nihilist, stoic.

        Returns:
            DebateResult with arguments, synthesis, and timing.
        """
        start = time.perf_counter()

        if perspectives is None:
            perspectives = list(self._perspectives.keys())

        available = [p for p in perspectives if p in self._perspectives]
        if not available:
            available = list(self._perspectives.keys())

        # Each perspective generates an argument
        arguments: dict[str, str] = {}
        for name in available:
            persp = self._perspectives[name]
            arguments[name] = self._reason_from_perspective(
                question, persp
            )

        # Synthesize: find common ground and key tensions
        synthesis = self._synthesize(question, arguments)

        elapsed = (time.perf_counter() - start) * 1000
        return DebateResult(
            question=question,
            arguments=arguments,
            synthesis=synthesis,
            perspectives_used=available,
            duration_ms=elapsed,
        )

    def _reason_from_perspective(self, question: str,
                                  persp: Perspective) -> str:
        """Generate an argument from a specific perspective.

        Uses the perspective's axioms and reasoning style to produce
        a structured argument addressing the question.
        """
        lines = [f"### {persp.name} Perspective ({persp.representative})\n"]

        # Opening: state the lens
        lines.append(f"**Framework:** {persp.reasoning_style}\n")

        # Apply each axiom to the question
        lines.append("**Analysis:**")
        for i, axiom in enumerate(persp.axioms, 1):
            applied = self._apply_axiom(question, axiom, persp.name)
            lines.append(f"{i}. {applied}")

        # Conclusion
        lines.append(f"\n**Verdict ({persp.name}):** "
                     f"{self._conclude(question, persp)}")

        return "\n".join(lines)

    def _apply_axiom(self, question: str, axiom: str, perspective: str) -> str:
        """Apply an axiom to a question and produce an analysis line.

        Uses pattern-based reasoning to connect axiom to question.
        """
        # Extract keywords from question
        keywords = _extract_keywords(question)

        # Match axiom type to question domain
        if "happiness" in axiom.lower() or "pleasure" in axiom.lower():
            return (f"*{axiom}* → Applied to '{question}': "
                    f"weigh the happiness consequences for all affected parties. "
                    f"Increased net happiness supports the action.")

        if "universal" in axiom.lower():
            return (f"*{axiom}* → Applied to '{question}': "
                    f"if everyone acted on this principle, would it be coherent? "
                    f"Universalizability determines moral permissibility.")

        if "end" in axiom.lower() and "means" in axiom.lower():
            return (f"*{axiom}* → Applied to '{question}': "
                    f"does this treat any person merely as a tool? "
                    f"If so, it violates human dignity.")

        if "virtue" in axiom.lower() or "flourish" in axiom.lower():
            return (f"*{axiom}* → Applied to '{question}': "
                    f"does this action cultivate virtue or enable flourishing? "
                    f"The answer reveals its moral character.")

        if "meaning" in axiom.lower() or "construct" in axiom.lower():
            return (f"*{axiom}* → Applied to '{question}': "
                    f"there is no cosmic answer — only human interpretation. "
                    f"Choose what gives YOUR life meaning.")

        if "control" in axiom.lower():
            return (f"*{axiom}* → Applied to '{question}': "
                    f"distinguish what is within our control from what is not. "
                    f"Wisdom lies in acting on what we can influence.")

        # Default: generic application
        return (f"*{axiom}* → Considered in light of '{question}': "
                f"this principle guides us toward reasoned judgment.")

    def _conclude(self, question: str, persp: Perspective) -> str:
        """Generate a perspective-specific conclusion."""
        name = persp.name.lower()
        if "utilitarian" in name:
            return "The morally correct choice is whichever maximizes net wellbeing."
        if "deontolog" in name:
            return "The action is right only if it can be universalized without contradiction."
        if "virtue" in name:
            return "A virtuous person would act with practical wisdom, finding the mean."
        if "nihilist" in name:
            return "No answer is objectively correct — create your own values and act authentically."
        if "stoic" in name:
            return "Focus on what you control. Accept what you cannot. Act with virtue regardless of outcome."
        return "Reasoned judgment must prevail."

    def _synthesize(self, question: str, arguments: dict[str, str]) -> str:
        """Synthesize multiple perspectives into a unified view.

        Identifies common ground, key tensions, and resolves toward
        a balanced conclusion.
        """
        lines = [
            "## Synthesis\n",
            f"After considering {len(arguments)} perspectives on '{question}':\n",
        ]

        # Identify common themes
        themes = self._extract_themes(arguments)
        if themes:
            lines.append("### Points of Convergence")
            for theme in themes:
                lines.append(f"- {theme}")
            lines.append("")

        # Identify key tensions
        tensions = self._extract_tensions(arguments)
        if tensions:
            lines.append("### Key Tensions")
            for tension in tensions:
                lines.append(f"- {tension}")
            lines.append("")

        # Resolution
        lines.append("### Resolution")
        lines.append(
            "Truth rarely resides at any single extreme. "
            "The most defensible position integrates the strongest insights "
            "from each perspective while acknowledging irreducible tensions. "
            "Where perspectives conflict, prioritize according to context: "
            "utilitarian calculus for policy, deontological bounds for rights, "
            "virtue ethics for character, stoic acceptance for the uncontrollable, "
            "and nihilist honesty for questioning assumptions."
        )

        return "\n".join(lines)

    def _extract_themes(self, arguments: dict[str, str]) -> list[str]:
        """Extract overlapping themes from arguments."""
        themes = []
        # Look for keywords that appear across multiple perspectives
        all_text = " ".join(arguments.values()).lower()
        keyword_pairs = [
            ("wellbeing", "All perspectives agree wellbeing matters, "
             "though they define it differently"),
            ("reason", "Reason and rational analysis are valued across traditions"),
            ("choice", "Human choice/agency is central to the ethical question"),
            ("suffering", "Minimizing unnecessary suffering is a shared concern"),
            ("dignity", "Respect for persons or living beings is broadly shared"),
        ]
        for keyword, theme in keyword_pairs:
            if all_text.count(keyword) >= 2:
                themes.append(theme)
        return themes[:3]

    def _extract_tensions(self, arguments: dict[str, str]) -> list[str]:
        """Identify key tensions between perspectives."""
        tensions = []
        names = list(arguments.keys())
        if "utilitarian" in names and "deontological" in names:
            tensions.append(
                "**Consequences vs. Duties:** Utilitarianism judges by outcomes; "
                "deontology judges by principles. They can disagree sharply."
            )
        if "nihilist" in names and "virtue_ethics" in names:
            tensions.append(
                "**Objective Meaning vs. Created Values:** The nihilist rejects "
                "objective purpose while virtue ethics presupposes flourishing as a goal."
            )
        if "stoic" in names and "utilitarian" in names:
            tensions.append(
                "**Inner State vs. External Outcomes:** Stoicism focuses on "
                "internal control; utilitarianism demands external optimization."
            )
        return tensions

    # ── Hegelian Dialectic ─────────────────────────────────────────────

    def thesis_antithesis_synthesis(self, topic: str) -> dict[str, str]:
        """Run Hegelian dialectic: thesis → antithesis → synthesis.

        Args:
            topic: The topic or proposition to dialectically analyze.

        Returns:
            Dict with 'thesis', 'antithesis', and 'synthesis' keys.
        """
        # Thesis: the dominant or intuitive position
        thesis = self._generate_thesis(topic)

        # Antithesis: the opposite or contradictory position
        antithesis = self._generate_antithesis(topic, thesis)

        # Synthesis: reconciliation at a higher level
        synthesis = self._dialectical_synthesis(topic, thesis, antithesis)

        return {
            "topic": topic,
            "thesis": thesis,
            "antithesis": antithesis,
            "synthesis": synthesis,
        }

    def _generate_thesis(self, topic: str) -> str:
        """Generate the thesis — the established or intuitive position."""
        return (
            f"Thesis: Regarding '{topic}', the established understanding "
            f"is that it represents a definite and recognizable phenomenon "
            f"with clear properties, boundaries, and implications. "
            f"This position provides stability and a foundation for discourse."
        )

    def _generate_antithesis(self, topic: str, thesis: str) -> str:
        """Generate the antithesis — the negation that reveals contradiction."""
        return (
            f"Antithesis: However, upon closer examination, '{topic}' reveals "
            f"internal contradictions. What appears stable is in flux; what seems "
            f"clear is ambiguous upon scrutiny. The boundaries break down under "
            f"analysis, and the implications are not what they seemed. "
            f"This negation is not mere destruction — it is the necessary "
            f"movement of thought that exposes the limitations of the thesis."
        )

    def _dialectical_synthesis(self, topic: str, thesis: str,
                                antithesis: str) -> str:
        """Generate the synthesis — Aufhebung (sublation/preservation)."""
        return (
            f"Synthesis: The contradiction between thesis and antithesis "
            f"on '{topic}' is resolved at a higher level. The truth preserves "
            f"what was valid in both positions while transcending their "
            f"limitations. What emerges is not a compromise but a new "
            f"understanding that incorporates the partial truths of both "
            f"while revealing a more comprehensive picture. This synthesis "
            f"now becomes the new thesis for further dialectical movement."
        )

    # ── Socratic Dialogue ──────────────────────────────────────────────

    def socratic_dialogue(self, topic: str,
                          depth: int = 5) -> SocraticResult:
        """Conduct a Socratic questioning chain to explore a topic.

        Uses iterative questioning to expose assumptions, clarify concepts,
        and arrive at deeper understanding.

        Args:
            topic: The concept or belief to examine.
            depth: Number of Socratic questions to generate.

        Returns:
            SocraticResult with questions, insights, and reflection.
        """
        questions: list[str] = []
        insights: list[str] = []

        # Socratic question bank
        probing = [
            f"What do we mean by '{topic}'? Can you define it precisely?",
            f"Why do you believe what you believe about {topic}?",
            f"What assumptions underlie our thinking about {topic}?",
            f"What would be a counterexample to the common view of {topic}?",
            f"If someone from a completely different culture considered {topic}, "
            f"what might they see differently?",
            f"What are the consequences if our beliefs about {topic} are wrong?",
            f"How would you explain {topic} to a child? What gets lost?",
            f"Is {topic} a matter of fact or a matter of interpretation?",
            f"What would it take to change your mind about {topic}?",
            f"Does {topic} serve a purpose beyond itself? What is it?",
            f"Where did our concept of {topic} come from historically?",
            f"If you removed {topic} from your worldview, what changes?",
            f"Can you think of a time when your understanding of {topic} was tested?",
            f"What is the relationship between {topic} and truth?",
            f"Does everyone need to agree on what {topic} means?",
        ]

        # Generate the dialogue
        for i in range(min(depth, len(probing))):
            q = probing[i]
            questions.append(q)

            # Derive insight from the question
            insight = self._derive_insight(topic, q, i)
            insights.append(insight)

        # Final reflection
        final = self._socratic_reflection(topic, insights)

        return SocraticResult(
            topic=topic,
            questions=questions,
            insights=insights,
            final_reflection=final,
        )

    def _derive_insight(self, topic: str, question: str, depth: int) -> str:
        """Derive a tentative insight from a Socratic question."""
        if depth == 0:
            return f"Initial inquiry: {question} — This forces us to clarify our terms."
        if depth <= 2:
            return (f"Probing deeper: {question} — This reveals that our understanding "
                    f"of {topic} may rest on unexamined assumptions.")
        if depth <= 4:
            return (f"Critical examination: {question} — We begin to see {topic} "
                    f"not as a fixed concept but as a dynamic interplay of perspectives.")
        return (f"Reflective insight: {question} — At this depth, {topic} "
                f"transforms from an object of thought to a process of understanding.")

    def _socratic_reflection(self, topic: str, insights: list[str]) -> str:
        """Generate final reflection on the Socratic dialogue."""
        return (
            f"After examining '{topic}' through {len(insights)} Socratic questions, "
            f"we emerge with a deepened appreciation for its complexity. "
            f"The unexamined life is not worth living — and the unexamined concept "
            f"is not worth holding. Wisdom begins with knowing what we do not know, "
            f"and Socratic inquiry reveals the depth of our ignorance about '{topic}', "
            f"which is precisely where genuine understanding begins."
        )

    # ── Ethical Check ──────────────────────────────────────────────────

    def ethical_check(self, action: str) -> EthicalCheck:
        """Evaluate the ethical implications of an action.

        Scores the action across all available ethical frameworks
        and returns a verdict with reasoning.

        Args:
            action: Description of the action to evaluate.

        Returns:
            EthicalCheck with scores, verdict, and recommendation.
        """
        scores: dict[str, float] = {}
        reasoning: dict[str, str] = {}

        for name, persp in self._perspectives.items():
            score, reason = self._ethical_score(action, persp)
            scores[name] = score
            reasoning[name] = reason

        # Compute verdict
        avg_score = sum(scores.values()) / max(len(scores), 1)

        if avg_score > 0.4:
            verdict = "endorsed"
            recommendation = "This action aligns with most ethical frameworks. Proceed with confidence."
        elif avg_score > 0.0:
            verdict = "caution"
            recommendation = "Mixed ethical signals. Proceed carefully with mitigations."
        elif avg_score > -0.4:
            verdict = "ambiguous"
            recommendation = "Ethical frameworks disagree significantly. Seek domain expertise."
        else:
            verdict = "rejected"
            recommendation = "This action conflicts with multiple ethical frameworks. Reconsider."

        return EthicalCheck(
            action=action,
            scores=scores,
            verdict=verdict,
            reasoning=reasoning,
            recommendation=recommendation,
        )

    def _ethical_score(self, action: str, persp: Perspective) -> tuple[float, str]:
        """Score an action from a specific ethical perspective.

        Returns (score, reasoning).
        """
        action_lower = action.lower()
        name = persp.name.lower()

        # Keyword-based ethical analysis (heuristic)
        positive_words = [
            "benefit", "help", "protect", "improve", "flourish", "fair",
            "consent", "transparent", "accountable", "voluntary", "safe",
            "heal", "educate", "empower", "sustain", "preserve",
        ]
        negative_words = [
            "harm", "deceive", "exploit", "manipulate", "coerce", "steal",
            "destroy", "discriminate", "oppress", "violate", "fraud",
            "surveil", "weaponize", "poison", "deprive",
        ]

        pos_count = sum(1 for w in positive_words if w in action_lower)
        neg_count = sum(1 for w in negative_words if w in action_lower)

        # Base score from keyword analysis
        raw = (pos_count - neg_count) / max(pos_count + neg_count, 1)
        score = max(-1.0, min(1.0, raw))

        # Adjust per perspective
        if "utilitarian" in name:
            if neg_count == 0 and pos_count > 0:
                score = 0.8
                reason = "Clear net benefit to wellbeing — strongly endorsed."
            elif neg_count > pos_count:
                score = -0.7
                reason = "Net harm to wellbeing — rejected on utilitarian grounds."
            else:
                reason = "Benefits and harms must be weighed carefully."
        elif "deontolog" in name:
            if any(w in action_lower for w in ["consent", "fair", "rights"]):
                score = 0.7
                reason = "Respects autonomy and moral law — deontologically sound."
            elif any(w in action_lower for w in ["deceive", "coerce", "manipulate"]):
                score = -0.8
                reason = "Violates the categorical imperative — using persons as mere means."
            else:
                reason = "Must check universalizability of the maxim."
        elif "virtue" in name:
            if any(w in action_lower for w in ["flourish", "wisdom", "courage"]):
                score = 0.7
                reason = "Cultivates virtue — a virtuous person would endorse this."
            elif any(w in action_lower for w in ["deceive", "exploit"]):
                score = -0.6
                reason = "Contrary to virtue — not the act of a person of good character."
            else:
                reason = "Consider what a person of practical wisdom would do."
        elif "nihilist" in name:
            score = 0.0  # Nihilist refuses to assign moral weight
            reason = "No objective moral framework exists. Act authentically, not ethically."
        elif "stoic" in name:
            if any(w in action_lower for w in ["accept", "endure", "control"]):
                score = 0.6
                reason = "Aligns with the dichotomy of control — stoic virtue."
            elif any(w in action_lower for w in ["rage", "panic", "fear"]):
                score = -0.5
                reason = "Driven by passion, not reason — contrary to stoic discipline."
            else:
                reason = "Focus on what is within your control. Accept the rest."
        else:
            reason = "Ethical evaluation requires further analysis."

        return score, reason

    # ── Wisdom Extract ─────────────────────────────────────────────────

    def wisdom_extract(self, text: str) -> dict[str, Any]:
        """Distill philosophical insights from text.

        Extracts key themes, notable quotes, and actionable wisdom
        from philosophical writings, articles, or discussions.

        Args:
            text: Input text to analyze (philosophical content).

        Returns:
            Dict with themes, quotes, principles, and summary.
        """
        sentences = [s.strip() for s in text.replace("\n", " ").split(".")
                     if len(s.strip()) > 20]

        # Extract themes through keyword aggregation
        themes = self._extract_philosophical_themes(text)

        # Find notable quotes (sentences with philosophical markers)
        quotes = self._extract_quotes(sentences)

        # Derive principles (actionable wisdom)
        principles = self._derive_principles(sentences)

        # Summary
        summary = (
            f"This text explores {', '.join(themes[:3])}. "
            f"It contains {len(quotes)} notable philosophical insights "
            f"and yields {len(principles)} actionable principles."
        ) if themes else "No distinct philosophical themes detected."

        return {
            "text_length": len(text),
            "themes": themes,
            "notable_quotes": quotes,
            "principles": principles,
            "summary": summary,
        }

    def _extract_philosophical_themes(self, text: str) -> list[str]:
        """Identify philosophical themes from text."""
        theme_keywords = {
            "ethics": ["ethics", "moral", "right", "wrong", "good", "evil",
                       "virtue", "duty", "justice"],
            "epistemology": ["knowledge", "truth", "belief", "certainty",
                             "doubt", "evidence", "reason"],
            "metaphysics": ["reality", "being", "existence", "time", "space",
                            "causality", "free will", "determinism"],
            "consciousness": ["consciousness", "mind", "experience", "qualia",
                              "awareness", "self", "identity"],
            "meaning": ["meaning", "purpose", "absurd", "nihilism", "value",
                        "significance", "existential"],
            "politics": ["justice", "freedom", "liberty", "equality", "rights",
                         "society", "power", "authority"],
            "aesthetics": ["beauty", "art", "sublime", "taste", "creativity",
                           "expression"],
        }
        text_lower = text.lower()
        found = []
        for theme, keywords in theme_keywords.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score >= 2:
                found.append((theme, score))
        found.sort(key=lambda x: -x[1])
        return [t[0] for t in found[:5]]

    def _extract_quotes(self, sentences: list[str]) -> list[str]:
        """Extract notable philosophical quotes from sentences."""
        markers = [
            "must", "should", "therefore", "thus", "it follows",
            "the essence", "in other words", "ultimately", "fundamentally",
            "we find that", "it appears that", "one might say",
            "the truth is", "wisdom", "virtue", "meaning",
        ]
        quotes = []
        for s in sentences:
            s_lower = s.lower()
            if any(m in s_lower for m in markers) and 30 < len(s) < 300:
                quotes.append(s.strip())
                if len(quotes) >= 5:
                    break
        return quotes

    def _derive_principles(self, sentences: list[str]) -> list[str]:
        """Derive actionable wisdom principles from sentences."""
        principles = []
        action_markers = ["should", "must", "ought", "one can", "it is better"]

        for s in sentences:
            s_lower = s.lower()
            if any(m in s_lower for m in action_markers):
                principle = s.strip().rstrip(".")
                if 20 < len(principle) < 200:
                    principles.append(principle)
                if len(principles) >= 3:
                    break

        if not principles:
            principles = [
                "Question your assumptions regularly.",
                "Seek to understand before seeking to be understood.",
                "Wisdom begins with acknowledging what you do not know.",
            ]

        return principles

    # ── Utility ─────────────────────────────────────────────────────────

    def list_perspectives(self) -> dict[str, str]:
        """Return available perspectives and their descriptions."""
        return {name: p.description for name, p in self._perspectives.items()}

    def add_perspective(self, name: str, description: str,
                        axioms: list[str], reasoning_style: str,
                        representative: str = "") -> None:
        """Register a custom perspective."""
        self._perspectives[name.lower().replace(" ", "_")] = Perspective(
            name=name,
            description=description,
            axioms=axioms,
            reasoning_style=reasoning_style,
            representative=representative,
        )


# ── Helpers ────────────────────────────────────────────────────────────

def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from text."""
    stopwords = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                 "in", "on", "at", "to", "for", "of", "with", "by", "from",
                 "and", "or", "but", "not", "if", "then", "else", "when",
                 "that", "this", "it", "its", "what", "which", "who", "how"}
    words = text.lower().split()
    return [w.strip("?!.,;:'\"") for w in words
            if w.strip("?!.,;:'\"") not in stopwords
            and len(w.strip("?!.,;:'\"")) > 2]


# ── Self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    phil = Philosophy()

    # Test debate
    print("=== Multi-Perspective Debate ===\n")
    result = phil.debate("Should AI be granted legal personhood?")
    print(f"Perspectives: {result.perspectives_used}")
    print(f"Duration: {result.duration_ms:.1f}ms\n")
    for name, arg in result.arguments.items():
        lines = arg.split("\n")
        print(f"  [{name}] {lines[0]}")
        print(f"    {lines[-1][:100]}")
    print(f"\n  Synthesis:\n    {result.synthesis[:200]}...\n")

    # Test thesis-antithesis-synthesis
    print("=== Hegelian Dialectic ===\n")
    dialectic = phil.thesis_antithesis_synthesis("Free will exists")
    for key in ["thesis", "antithesis", "synthesis"]:
        print(f"  {key.capitalize()}: {dialectic[key][:100]}...")
    print()

    # Test Socratic dialogue
    print("=== Socratic Dialogue ===\n")
    dialogue = phil.socratic_dialogue("What is justice?", depth=3)
    assert len(dialogue.questions) == 3
    assert len(dialogue.insights) == 3
    for i, (q, ins) in enumerate(zip(dialogue.questions, dialogue.insights), 1):
        print(f"  Q{i}: {q[:80]}...")
        print(f"  I{i}: {ins[:80]}...")
    print(f"\n  Reflection: {dialogue.final_reflection[:150]}...\n")

    # Test ethical check — positive
    print("=== Ethical Check ===\n")
    check1 = phil.ethical_check("Provide free education to all children")
    print(f"  Action: {check1.action}")
    print(f"  Verdict: {check1.verdict}")
    print(f"  Scores: {dict((k, round(v, 2)) for k, v in check1.scores.items())}")
    print(f"  Recommendation: {check1.recommendation}\n")

    # Test ethical check — negative
    check2 = phil.ethical_check("Deploy mass surveillance without consent")
    print(f"  Action: {check2.action}")
    print(f"  Verdict: {check2.verdict}")
    print(f"  Scores: {dict((k, round(v, 2)) for k, v in check2.scores.items())}")
    print(f"  Recommendation: {check2.recommendation}\n")

    # Test wisdom extract
    print("=== Wisdom Extract ===\n")
    text = (
        "The unexamined life is not worth living. We must question our "
        "deepest assumptions about reality, truth, and meaning. Through "
        "reason and dialogue, we can approach wisdom — though absolute "
        "certainty remains forever beyond our grasp. One should therefore "
        "cultivate intellectual humility and remain open to being wrong."
    )
    wisdom = phil.wisdom_extract(text)
    print(f"  Text length: {wisdom['text_length']} chars")
    print(f"  Themes: {wisdom['themes']}")
    print(f"  Quotes: {len(wisdom['notable_quotes'])} found")
    print(f"  Principles: {len(wisdom['principles'])} derived")
    print(f"  Summary: {wisdom['summary']}\n")

    # Test custom perspective
    print("=== Custom Perspective ===\n")
    phil.add_perspective(
        "Pragmatist",
        "Truth is what works in practice — William James, John Dewey",
        ["Ideas are true insofar as they help us get into satisfactory relations",
         "Truth happens to an idea — it becomes true through events",
         "The test of truth is its practical consequences"],
        "What are the practical consequences? What works?"
    )
    result3 = phil.debate("Should we colonize Mars?", perspectives=["stoic", "pragmatist"])
    print(f"  Debate with custom 'pragmatist' perspective:")
    print(f"  Perspectives used: {result3.perspectives_used}")
    for name, arg in result3.arguments.items():
        print(f"    [{name}] {arg.split(chr(10))[-1][:100]}")

    print("\n✓ All self-tests passed")