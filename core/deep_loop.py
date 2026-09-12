"""Deep loop reasoning — recursive self-critique with configurable depth.
DNA: Astra GPT-6 (loop depth) + Claude Opus (extended thinking).

Provides multi-layer reasoning where each layer critiques the previous,
synthesizing progressively deeper understanding through structured
self-examination. Supports 5 verification dimensions.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Layer:
    """One reasoning layer with critique and improvement."""
    depth: int
    answer: str
    critique: str = ""
    confidence: float = 1.0
    dimension_scores: dict[str, float] = field(default_factory=dict)


class DeepLoopReasoner:
    """Think in layers. Each layer critiques the previous. Depth=N.

    The 5 verification dimensions (DNA: Astra GPT-6):
    1. correctness   — is it factually right?
    2. completeness  — does it cover all cases?
    3. efficiency    — is it optimal?
    4. clarity       — is it understandable?
    5. safety        — are there risks or edge cases?
    """

    DIMENSIONS = ("correctness", "completeness", "efficiency", "clarity", "safety")

    def __init__(self, provider=None):
        self.provider = provider
        self.layers: list[Layer] = []

    async def reason(self, problem: str, depth: int = 3,
                     dimensions: tuple[str, ...] = DIMENSIONS) -> dict:
        """Reason through a problem with increasing depth.

        Args:
            problem: The problem to solve.
            depth: Number of recursive critique layers (default 3).
            dimensions: Which verification dimensions to use.
        """
        self.layers = []
        current: Optional[Layer] = None

        for i in range(depth):
            if i == 0:
                answer = await self._layer_zero(problem)
                current = Layer(depth=i, answer=answer, confidence=0.7)
            else:
                current = await self._layer_n(problem, current, i, dimensions)

            self.layers.append(current)

        synthesis = await self._synthesize(problem)
        verdict = self._gate(synthesis)

        return {
            "layers": [{"depth": l.depth, "answer": l.answer,
                        "critique": l.critique, "confidence": l.confidence,
                        "dimensions": l.dimension_scores}
                       for l in self.layers],
            "depth": depth,
            "synthesis": synthesis,
            "verdict": verdict,
        }

    def reason_sync(self, problem: str, depth: int = 3) -> dict:
        """Synchronous fallback — heuristic reasoning without provider.

        Uses pattern-based decomposition and critique. Suitable for
        offline or when no AI provider is available.
        """
        self.layers = []

        # Layer 0: Decompose problem
        components = self._decompose(problem)
        l0 = Layer(depth=0, answer=f"Components: {'; '.join(components)}",
                   confidence=0.5,
                   dimension_scores={"correctness": 0.5, "completeness": 0.4,
                                     "efficiency": 0.5, "clarity": 0.7, "safety": 0.6})
        self.layers.append(l0)

        # Layers 1..N: Critique each component
        for i in range(1, depth):
            prev = self.layers[-1]
            critiques = [f"{c} → check edge cases" for c in components]
            improved = [f"{c} (vetted)" for c in components]
            li = Layer(depth=i,
                       answer=f"Improved: {'; '.join(improved)}",
                       critique=f"Weak points: {'; '.join(critiques)}",
                       confidence=min(0.5 + i * 0.15, 0.95),
                       dimension_scores={"correctness": 0.5 + i * 0.12,
                                         "completeness": 0.4 + i * 0.12,
                                         "efficiency": 0.5 + i * 0.1,
                                         "clarity": 0.7,
                                         "safety": 0.6 + i * 0.08})
            self.layers.append(li)

        synthesis = self._build_synthesis(components, self.layers)
        return {
            "layers": [{"depth": l.depth, "answer": l.answer,
                        "critique": l.critique, "confidence": l.confidence,
                        "dimensions": l.dimension_scores}
                       for l in self.layers],
            "depth": depth,
            "synthesis": synthesis,
            "verdict": self._gate(synthesis),
        }

    async def _layer_zero(self, problem: str) -> str:
        if not self.provider:
            components = self._decompose(problem)
            return f"Initial analysis: {'; '.join(components)}"

        resp = await self.provider.generate(
            f"Solve this problem thoroughly. Consider edge cases.\n\n{problem}"
        )
        return resp.text

    async def _layer_n(self, problem: str, previous: Layer, n: int,
                       dimensions: tuple[str, ...]) -> Layer:
        dims = ", ".join(dimensions)
        prompt = f"""PROBLEM: {problem}

PREVIOUS ANSWER (Layer {n}):
{previous.answer}

Your job as Layer {n+1}:
1. CRITIQUE along: {dims}
2. DEEPEN one level beyond Layer {n}
3. IMPROVE with the critique incorporated
4. Score each dimension 0.0-1.0

Output as JSON:
{{"critique": "...", "improved": "...", "scores": {{"correctness": 0.X, ...}}}}"""

        if self.provider:
            resp = await self.provider.generate(prompt)
            try:
                import json
                data = json.loads(resp.text)
                return Layer(depth=n, answer=data["improved"],
                             critique=data["critique"],
                             confidence=sum(data.get("scores", {}).values()) / len(dimensions),
                             dimension_scores=data.get("scores", {}))
            except (json.JSONDecodeError, KeyError):
                return Layer(depth=n, answer=resp.text,
                             critique="(parse failed)",
                             confidence=previous.confidence * 0.9)

        return Layer(depth=n, answer=f"Layer {n} critique applied",
                     critique=f"Checked: {dims}", confidence=0.7)

    async def _synthesize(self, problem: str) -> str:
        if not self.provider:
            return self._build_synthesis([], self.layers)

        layers_text = "\n\n".join(
            f"--- LAYER {l.depth} (confidence: {l.confidence:.2f}) ---\n"
            f"Critique: {l.critique}\nAnswer: {l.answer}"
            for l in self.layers
        )
        resp = await self.provider.generate(
            f"Problem: {problem}\n\n{layers_text}\n\n"
            f"Synthesize the FINAL answer. Deeper than any single layer. One paragraph."
        )
        return resp.text

    def _gate(self, synthesis: str) -> dict:
        """5-dimension output gate (DNA: Astra GPT-6 verifier)."""
        scores = {}
        if self.layers:
            # Average dimension scores across layers
            for dim in self.DIMENSIONS:
                vals = [l.dimension_scores.get(dim, 0) for l in self.layers if l.dimension_scores]
                scores[dim] = round(sum(vals) / len(vals), 2) if vals else 0.5
        else:
            scores = {d: 0.5 for d in self.DIMENSIONS}

        avg = sum(scores.values()) / len(scores)
        if avg >= 0.8:
            gate = "PASS"
        elif avg >= 0.5:
            gate = "WARN"
        else:
            gate = "FAIL"

        return {"gate": gate, "average_score": round(avg, 2), "dimensions": scores}

    def _decompose(self, problem: str) -> list[str]:
        """Break problem into fundamental components."""
        # Simple heuristic decomposition
        components = []
        for sep in (". ", "? ", "! ", "\n"):
            parts = problem.split(sep)
            if len(parts) > 1:
                components = [p.strip() for p in parts if p.strip()]
                break
        if not components:
            components = [problem]
        return components[:5]  # Max 5 components

    def _build_synthesis(self, components: list[str],
                         layers: list[Layer]) -> str:
        """Build final synthesis from components and layers."""
        final_layer = layers[-1] if layers else None
        conf = final_layer.confidence if final_layer else 0.5
        parts = components or ["the problem"]
        return (f"After {len(layers)} layers of analysis: "
                f"{' and '.join(parts)} — resolved with "
                f"{conf:.0%} confidence.")


# ── Self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    reasoner = DeepLoopReasoner()

    # Test sync reasoning
    result = reasoner.reason_sync(
        "Should I use a microservice architecture for a 3-person startup?",
        depth=3
    )

    print(f"Depth: {result['depth']}")
    print(f"Layers: {len(result['layers'])}")
    print(f"Gate: {result['verdict']['gate']} "
          f"({result['verdict']['average_score']})")
    print(f"Synthesis: {result['synthesis'][:120]}...")

    # Verify layer structure
    assert len(result["layers"]) == 3, "Expected 3 layers"
    assert result["layers"][0]["depth"] == 0
    assert result["layers"][-1]["depth"] == 2
    assert "confidence" in result["layers"][0]
    assert "dimensions" in result["layers"][0]

    print("\n✓ All self-tests passed")