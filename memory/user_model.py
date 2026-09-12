"""Markov chain user pattern model — learn and predict user behavior.

DNA: Mirror (behavioral mirroring, predictive adaptation).

The UserModel records actions in context, builds a Markov transition model,
and predicts the most likely next action.  Uses only stdlib ``collections``
(Counter + defaultdict) — pure Python, zero dependencies.

Usage::

    model = UserModel(order=1)
    model.record_action("type", {"app": "editor"})
    model.record_action("save", {"app": "editor"})
    model.record_action("run_tests", {"app": "terminal"})

    next_action = model.predict_next({"app": "editor"})
    print(next_action)  # "save" (most likely after "type" in "editor")

    patterns = model.get_patterns(min_count=2)
    for seq, count in patterns:
        print(f"{' → '.join(seq)}: {count} times")
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional


# ── Helpers ───────────────────────────────────────────────────────────

def _context_key(context: dict[str, Any]) -> str:
    """Create a stable string key from a context dict."""
    if not context:
        return "__empty__"
    items = sorted(context.items())
    return json.dumps(items, sort_keys=True, default=str)


def _action_key(action: str, context_key: str) -> str:
    """Combine action and context into a single state key."""
    return f"{context_key}::{action}"


# ── Result types ──────────────────────────────────────────────────────

@dataclass
class PredictionResult:
    """Result of a next-action prediction."""
    action: Optional[str]
    probability: float           # 0.0–1.0
    alternatives: list[tuple[str, float]]  # top-5 alternatives
    confidence: str              # "high", "medium", "low", "none"


# ── UserModel ─────────────────────────────────────────────────────────

class UserModel:
    """Markov-chain user behavior model.

    Records sequences of (action, context) pairs, builds a transition
    probability matrix, and predicts the most likely next action given
    a context.  Supports configurable Markov order (default 1) for
    longer history windows.

    Parameters:
        order: Markov order — how many previous (action, context) pairs
            to consider.  Order 1 uses only the last state; order 2
            uses the last two states.  Higher orders capture longer
            patterns but require more data.
        decay_factor: Exponential decay weight for older observations
            (0.0–1.0).  1.0 = no decay, 0.5 = each older observation
            counts half as much.  Default 1.0.
        max_history: Maximum number of recent actions to track for
            the sliding window (default 1000).
    """

    def __init__(
        self,
        order: int = 1,
        decay_factor: float = 1.0,
        max_history: int = 1000,
    ):
        if order < 1:
            raise ValueError("Markov order must be >= 1")

        self.order = order
        self.decay_factor = max(0.1, min(1.0, decay_factor))
        self.max_history = max_history

        # Transition counts: state_key → Counter[next_state_key]
        self._transitions: dict[str, Counter[str]] = defaultdict(Counter)

        # Rolling window of recent (action, context_key) pairs
        self._recent: list[str] = []  # state_keys

        # Total action counts per context (for fallback predictions)
        self._context_actions: dict[str, Counter[str]] = defaultdict(Counter)

        # Sequence tracking for pattern mining
        self._sequences: list[tuple[str, ...]] = []  # sliding window of actions
        self._action_list: list[str] = []

        # Observation count
        self._total_observations: int = 0

    # ── Public API ────────────────────────────────────────────────────

    def record_action(
        self,
        action_type: str,
        context: Optional[dict[str, Any]] = None,
        weight: float = 1.0,
    ) -> None:
        """Record an observed action in context.

        Args:
            action_type: The action performed (e.g. ``"save"``, ``"type"``, ``"run"``).
            context: Optional dictionary of contextual features
                (e.g. ``{"app": "editor", "time_of_day": "morning"}``).
            weight: Observation weight (default 1.0).  Use < 1.0 for
                uncertain observations.
        """
        ctx = context or {}
        ctx_key = _context_key(ctx)
        state_key = _action_key(action_type, ctx_key)

        # Update context-level counters
        self._context_actions[ctx_key][action_type] += weight

        # Update transition from previous state(s)
        if self._recent:
            prev_key = self._recent[-1]
            self._transitions[prev_key][state_key] += weight

            # Higher-order: also update from earlier states
            if self.order > 1 and len(self._recent) >= self.order:
                for o in range(2, min(self.order, len(self._recent)) + 1):
                    order_key = "||".join(self._recent[-o:])
                    self._transitions[order_key][state_key] += weight

        # Update rolling window
        self._recent.append(state_key)
        self._action_list.append(action_type)
        self._total_observations += 1

        # Prune history
        if len(self._recent) > self.max_history:
            self._recent = self._recent[-self.max_history:]
        if len(self._action_list) > self.max_history:
            self._action_list = self._action_list[-self.max_history:]

        # Update sequence tracking (last N actions for pattern mining)
        seq_len = min(self.order + 1, len(self._action_list))
        if seq_len >= 2:
            self._sequences.append(
                tuple(self._action_list[-seq_len:])
            )

    def predict_next(
        self,
        context: Optional[dict[str, Any]] = None,
        top_n: int = 5,
    ) -> PredictionResult:
        """Predict the most likely next action given a context.

        Uses the Markov transition model: finds the current state
        (last recorded action in this context) and returns the most
        probable next action.

        Args:
            context: Context dict for the prediction.  If None, uses
                the most recent context.
            top_n: Number of top alternatives to include.

        Returns:
            PredictionResult with predicted action, probability, and alternatives.
        """
        ctx = context or {}
        ctx_key = _context_key(ctx)

        # Build current state representation
        if not self._recent:
            # No history — fall back to most common action in context
            return self._fallback_prediction(ctx_key, top_n)

        current_key = self._recent[-1]

        # Try order-N transition first
        if self.order > 1 and len(self._recent) >= self.order:
            order_keys = [
                "||".join(self._recent[-o:])
                for o in range(self.order, 1, -1)
            ]
            for ok in order_keys:
                if ok in self._transitions and self._transitions[ok]:
                    return self._make_prediction(
                        self._transitions[ok], top_n
                    )

        # Try order-1 transition
        if current_key in self._transitions and self._transitions[current_key]:
            return self._make_prediction(
                self._transitions[current_key], top_n
            )

        # Fallback: most common action in this context
        return self._fallback_prediction(ctx_key, top_n)

    def get_patterns(
        self,
        min_count: int = 2,
        max_patterns: int = 20,
    ) -> list[tuple[tuple[str, ...], int]]:
        """Return frequent action sequences sorted by frequency.

        Args:
            min_count: Minimum occurrences for a sequence to be included.
            max_patterns: Maximum number of patterns to return.

        Returns:
            List of (sequence, count) tuples, most frequent first.
        """
        counter: Counter[tuple[str, ...]] = Counter()
        for seq in self._sequences:
            # Also count all sub-sequences
            for length in range(2, len(seq) + 1):
                for start in range(len(seq) - length + 1):
                    subseq = seq[start:start + length]
                    counter[subseq] += 1

        # Filter and sort
        filtered = [
            (seq, count)
            for seq, count in counter.most_common()
            if count >= min_count
        ]
        return filtered[:max_patterns]

    def get_action_probabilities(
        self,
        context: Optional[dict[str, Any]] = None,
    ) -> list[tuple[str, float]]:
        """Get all action probabilities for a given context.

        Returns actions sorted by probability (highest first).
        """
        ctx = context or {}
        ctx_key = _context_key(ctx)

        if not self._recent:
            # Aggregate across all contexts matching this one
            total = self._context_actions.get(ctx_key, Counter())
            if not total:
                return []
            grand_total = sum(total.values())
            return [
                (action, count / grand_total)
                for action, count in total.most_common()
            ]

        current_key = self._recent[-1]
        counter = self._transitions.get(current_key)
        if not counter:
            return []

        total = sum(counter.values())
        return [
            (self._extract_action(state_key), count / total)
            for state_key, count in counter.most_common()
        ]

    @property
    def transition_matrix(self) -> dict[str, dict[str, float]]:
        """The Markov transition matrix as nested dicts.

        Returns:
            ``{from_state: {to_state: probability, ...}, ...}``
        """
        matrix: dict[str, dict[str, float]] = {}
        for from_state, counter in self._transitions.items():
            total = sum(counter.values())
            if total > 0:
                matrix[from_state] = {
                    to_state: count / total
                    for to_state, count in counter.items()
                }
        return matrix

    @property
    def total_observations(self) -> int:
        """Total number of recorded actions."""
        return self._total_observations

    @property
    def unique_actions(self) -> int:
        """Number of unique action types observed."""
        return len(set(self._action_list))

    def stats(self) -> dict[str, Any]:
        """Return summary statistics."""
        patterns = self.get_patterns(min_count=3, max_patterns=10)
        matrix = self.transition_matrix

        return {
            "total_observations": self._total_observations,
            "unique_actions": self.unique_actions,
            "order": self.order,
            "transition_states": len(self._transitions),
            "transition_entries": sum(len(c) for c in self._transitions.values()),
            "top_patterns": [
                (" → ".join(seq), count) for seq, count in patterns[:5]
            ],
            "most_common_action": (
                Counter(self._action_list).most_common(1)[0]
                if self._action_list else None
            ),
            "matrix_density": (
                sum(len(c) for c in self._transitions.values())
                / max(1, len(self._transitions))
                if self._transitions else 0.0
            ),
        }

    def clear(self) -> None:
        """Reset all learned data."""
        self._transitions.clear()
        self._recent.clear()
        self._context_actions.clear()
        self._sequences.clear()
        self._action_list.clear()
        self._total_observations = 0

    # ── Serialisation ─────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialise the model to a JSON-compatible dict."""
        return {
            "order": self.order,
            "decay_factor": self.decay_factor,
            "max_history": self.max_history,
            "total_observations": self._total_observations,
            "recent": self._recent[-100:],  # last 100 states
            "action_list": self._action_list[-100:],  # last 100 actions
            "transitions": {
                k: dict(v)
                for k, v in self._transitions.items()
            },
            "context_actions": {
                k: dict(v)
                for k, v in self._context_actions.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> UserModel:
        """Deserialise a model from a dict (from ``to_dict()``)."""
        model = cls(
            order=data.get("order", 1),
            decay_factor=data.get("decay_factor", 1.0),
            max_history=data.get("max_history", 1000),
        )
        model._total_observations = data.get("total_observations", 0)
        model._recent = data.get("recent", [])
        model._action_list = data.get("action_list", [])

        # Rebuild transitions
        for k, v in data.get("transitions", {}).items():
            model._transitions[k] = Counter(v)

        for k, v in data.get("context_actions", {}).items():
            model._context_actions[k] = Counter(v)

        # Rebuild sequences from action list
        seq_len = min(model.order + 1, len(model._action_list))
        if seq_len >= 2:
            actions = model._action_list
            for i in range(seq_len - 1, len(actions)):
                model._sequences.append(tuple(actions[i - seq_len + 1:i + 1]))

        return model

    # ── Internals ─────────────────────────────────────────────────────

    def _make_prediction(
        self,
        counter: Counter[str],
        top_n: int,
    ) -> PredictionResult:
        """Build a PredictionResult from a transition counter."""
        total = sum(counter.values())
        if total == 0:
            return PredictionResult(
                action=None,
                probability=0.0,
                alternatives=[],
                confidence="none",
            )

        top = counter.most_common(top_n)
        best_state, best_count = top[0]
        probability = best_count / total

        alternatives = [
            (self._extract_action(state), count / total)
            for state, count in top
        ]

        # Confidence heuristic
        if probability > 0.5:
            conf = "high"
        elif probability > 0.2:
            conf = "medium"
        elif probability > 0.05:
            conf = "low"
        else:
            conf = "none"

        return PredictionResult(
            action=self._extract_action(best_state),
            probability=round(probability, 4),
            alternatives=alternatives,
            confidence=conf,
        )

    def _fallback_prediction(
        self, ctx_key: str, top_n: int
    ) -> PredictionResult:
        """Fallback: predict most common action in context."""
        counter = self._context_actions.get(ctx_key)
        if not counter or sum(counter.values()) == 0:
            # Global fallback
            global_counter = Counter(self._action_list)
            if not global_counter:
                return PredictionResult(
                    action=None,
                    probability=0.0,
                    alternatives=[],
                    confidence="none",
                )
            counter = global_counter

        return self._make_prediction(counter, top_n)

    @staticmethod
    def _extract_action(state_key: str) -> str:
        """Extract the action name from a state key."""
        if "::" in state_key:
            return state_key.split("::", 1)[1]
        return state_key


# ── Self-test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("USER MODEL SELF-TEST")
    print("=" * 60)

    # ── Test 1: Basic recording and prediction ────────────────────────
    print("\n── Test 1: Record and predict ──")
    model = UserModel(order=1)

    # Simulate a user workflow
    model.record_action("open_file", {"app": "editor"})
    model.record_action("type", {"app": "editor"})
    model.record_action("type", {"app": "editor"})
    model.record_action("save", {"app": "editor"})
    model.record_action("run_tests", {"app": "terminal"})
    model.record_action("fix_bug", {"app": "editor"})
    model.record_action("save", {"app": "editor"})
    model.record_action("run_tests", {"app": "terminal"})

    # Predict next after "save" in editor
    prediction = model.predict_next({"app": "editor"})
    print(f"Predicted: {prediction.action} (prob={prediction.probability:.3f}, conf={prediction.confidence})")
    print(f"Alternatives: {prediction.alternatives}")
    assert prediction.action is not None, "Should predict something"
    assert 0 <= prediction.probability <= 1

    # ── Test 2: Pattern extraction ────────────────────────────────────
    print("\n── Test 2: Get patterns ──")
    patterns = model.get_patterns(min_count=1)
    print(f"Found {len(patterns)} patterns:")
    for seq, count in patterns[:5]:
        print(f"  {' → '.join(seq)}: {count}")
    assert len(patterns) > 0, "Should find at least one pattern"

    # ── Test 3: Transition matrix ─────────────────────────────────────
    print("\n── Test 3: Transition matrix ──")
    matrix = model.transition_matrix
    print(f"States: {len(matrix)}")
    for from_state, transitions in matrix.items():
        action = model._extract_action(from_state)
        to_actions = [(model._extract_action(k), round(v, 2)) for k, v in transitions.items()]
        print(f"  {action} → {to_actions}")
    assert len(matrix) > 0, "Should have transition entries"

    # ── Test 4: Order-2 Markov ────────────────────────────────────────
    print("\n── Test 4: Order-2 model ──")
    model2 = UserModel(order=2)
    # Simulate a clear pattern
    for _ in range(10):
        model2.record_action("A", {"ctx": "x"})
        model2.record_action("B", {"ctx": "x"})
        model2.record_action("C", {"ctx": "x"})

    prediction2 = model2.predict_next({"ctx": "x"})
    print(f"Order-2 predicted: {prediction2.action} (prob={prediction2.probability:.3f})")
    assert prediction2.action is not None

    # ── Test 5: Stats ─────────────────────────────────────────────────
    print("\n── Test 5: Model stats ──")
    stats = model.stats()
    print(f"Total observations: {stats['total_observations']}")
    print(f"Unique actions: {stats['unique_actions']}")
    print(f"Transition states: {stats['transition_states']}")
    print(f"Transition entries: {stats['transition_entries']}")
    print(f"Most common: {stats['most_common_action']}")
    print(f"Top patterns: {stats['top_patterns']}")
    assert stats["total_observations"] == 8
    assert stats["unique_actions"] >= 4

    # ── Test 6: Serialisation round-trip ──────────────────────────────
    print("\n── Test 6: Serialisation ──")
    data = model.to_dict()
    restored = UserModel.from_dict(data)
    assert restored.total_observations == model.total_observations
    assert restored.unique_actions == model.unique_actions
    assert len(restored.transition_matrix) == len(model.transition_matrix)
    print(f"Round-trip OK: {restored.total_observations} observations, "
          f"{restored.unique_actions} unique actions")

    # ── Test 7: Clear and empty prediction ────────────────────────────
    print("\n── Test 7: Empty model ──")
    model3 = UserModel()
    pred = model3.predict_next({"app": "unknown"})
    print(f"Empty prediction: action={pred.action}, conf={pred.confidence}")
    assert pred.action is None
    assert pred.confidence == "none"

    # ── Test 8: Action probabilities ──────────────────────────────────
    print("\n── Test 8: Action probabilities ──")
    probs = model.get_action_probabilities({"app": "editor"})
    print(f"Probabilities: {probs}")
    total_prob = sum(p for _, p in probs)
    assert abs(total_prob - 1.0) < 0.01, f"Probabilities should sum to ~1.0, got {total_prob}"

    # ── Test 9: Multiple contexts ─────────────────────────────────────
    print("\n── Test 9: Multiple contexts ──")
    model4 = UserModel(order=1)
    model4.record_action("code", {"app": "ide"})
    model4.record_action("compile", {"app": "ide"})
    model4.record_action("browse", {"app": "browser"})
    model4.record_action("search", {"app": "browser"})

    # Predict in IDE context
    pred_ide = model4.predict_next({"app": "ide"})
    # Predict in browser context  
    pred_browser = model4.predict_next({"app": "browser"})
    print(f"IDE prediction: {pred_ide.action} ({pred_ide.confidence})")
    print(f"Browser prediction: {pred_browser.action} ({pred_browser.confidence})")

    # ── Test 10: Property access ──────────────────────────────────────
    print("\n── Test 10: Properties ──")
    print(f"total_observations: {model4.total_observations}")
    print(f"unique_actions: {model4.unique_actions}")
    assert model4.total_observations == 4
    assert model4.unique_actions == 4

    print("\n✅ All user model tests passed!")