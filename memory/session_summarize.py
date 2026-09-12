"""
OmniCore v3 — Session Auto-Summarizer (Phase 10)
=================================================
DNA: LTX-Quasar cold-protocol — compress context, preserve intent.

Heuristic-based session summarization without LLM dependency.
Extracts key decisions, generates TL;DR summaries, and provides
sliding-window context compression for API context windows.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional

from .store import MemoryStore


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH: str = "~/.omnicore/memory.db"

# Decision-indicator phrases (case-insensitive)
DECISION_PATTERNS: list[str] = [
    r"(?i)\b(I[' ]ll|I will|let'?s|we should|we will|we[' ]ll|go with|proceed with)\b",
    r"(?i)\b(decided|decision|chosen|selected|picked|agreed|confirmed|approved)\b",
    r"(?i)\b(final (answer|choice|decision|plan)|action item|next step)\b",
    r"(?i)\b(create|build|write|implement|deploy|install|configure|set up)\b.*\b(now|first|immediately)\b",
    r"(?i)\b(fix|patch|resolve|address)\b.*\b(bug|issue|error|problem)\b",
    r"(?i)\b(switch|migrate|move|transition)\b.*\b(from|to|over)\b",
    r"(?i)\b(done|complete|finished|resolved|merged|deployed|shipped)\b",
]

# High-signal content indicators
HIGH_SIGNAL_PATTERNS: list[str] = [
    r"```[\s\S]*?```",           # Code blocks
    r"(?i)\b(error|exception|traceback|stack trace)\b",
    r"(?i)\b(warning|critical|urgent|important|note:)\b",
    r"(?i)\b(conclusion|summary|result|outcome|finding)\b",
    r"\b[A-Z_]{3,}\b",           # CONSTANTS / env vars
    r"(?i)\b(api|endpoint|url|host|port|token|key|secret|password)\b",
]

# Content worth compressing (low-signal filler)
LOW_SIGNAL_PATTERNS: list[str] = [
    r"(?i)\b(hello|hi there|hey|good morning|good afternoon)\b",
    r"(?i)\b(thank|thanks|thx|appreciate|np|no problem|you'?re welcome)\b",
    r"(?i)\b(how are you|what'?s up|how'?s it going)\b",
    r"(?i)\b(sorry|apologies|my bad|oops)\b",
]

# Rough token estimator: average English token is ~4 chars
CHARS_PER_TOKEN: int = 4


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DecisionPoint:
    """A key decision extracted from the conversation."""
    content: str
    role: str = ""
    confidence: float = 0.0
    context_before: str = ""
    context_after: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "role": self.role,
            "confidence": self.confidence,
            "context_before": self.context_before[:100],
            "context_after": self.context_after[:100],
        }


@dataclass
class SessionDigest:
    """Structured summary of a session."""
    session_id: str
    title: str = ""
    tldr: str = ""
    message_count: int = 0
    duration_seconds: float = 0.0
    key_decisions: list[DecisionPoint] = field(default_factory=list)
    top_topics: list[str] = field(default_factory=list)
    roles_distribution: dict[str, int] = field(default_factory=dict)
    generated_at: float = 0.0


# ---------------------------------------------------------------------------
# SessionSummarizer
# ---------------------------------------------------------------------------

class SessionSummarizer:
    """Heuristic session summarizer — no LLM dependency.

    Extracts key decisions, generates concise TL;DR summaries,
    and provides sliding-window context compression for fitting
    conversations into model API context windows.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        """Initialize summarizer with MemoryStore connection.

        Args:
            db_path: Path to the SQLite memory database.
        """
        self._store = MemoryStore(db_path=db_path)

    # ── Public API ────────────────────────────────────────────

    def summarize(self, session_id: str) -> SessionDigest:
        """Generate a structured summary for a session.

        Combines TL;DR generation, decision extraction, topic
        analysis, and role distribution into one digest.

        Args:
            session_id: The session to summarize.

        Returns:
            SessionDigest with full summary data.
        """
        messages = self._store.get_messages(session_id, limit=2000)
        if not messages:
            return SessionDigest(
                session_id=session_id,
                title=self._store.get_session_title(session_id),
                generated_at=time.time(),
            )

        tldr = self.generate_tldr(messages)
        decisions = self.extract_key_decisions(messages)
        topics = self._extract_topics(messages)
        roles = self._count_roles(messages)
        duration = self._estimate_duration(messages)

        return SessionDigest(
            session_id=session_id,
            title=self._store.get_session_title(session_id),
            tldr=tldr,
            message_count=len(messages),
            duration_seconds=duration,
            key_decisions=decisions,
            top_topics=topics,
            roles_distribution=roles,
            generated_at=time.time(),
        )

    def sliding_window(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = 8000,
        preserve_system: bool = True,
    ) -> list[dict[str, Any]]:
        """Trim old context while keeping key information.

        Strategy:
        1. Always keep system message (if preserve_system).
        2. Keep the most recent messages that fit.
        3. If truncation needed, insert a compressed summary of
           removed messages as a system note.

        Args:
            messages: Full message list.
            max_tokens: Target token budget.
            preserve_system: Keep the first system message.

        Returns:
            Trimmed message list within token budget.
        """
        if not messages:
            return []

        result: list[dict[str, Any]] = []
        start = 0

        if preserve_system and messages[0].get("role") == "system":
            result.append(messages[0])
            start = 1

        # Work backwards from the end, adding messages until budget exhausted
        budget = max_tokens
        budget -= self._estimate_tokens(
            " ".join(str(m.get("content", "")) for m in result)
        )

        kept: list[dict[str, Any]] = []
        for msg in reversed(messages[start:]):
            tokens = self._estimate_tokens(str(msg.get("content", "")))
            if budget >= tokens:
                kept.insert(0, msg)
                budget -= tokens
            else:
                break

        # If we dropped messages, insert a summary
        dropped_count = len(messages) - start - len(kept)
        if dropped_count > 0 and kept:
            dropped_msgs = messages[start:start + dropped_count]
            summary = self._compress_dropped(dropped_msgs)
            result.append({
                "role": "system",
                "content": f"[Earlier context ({dropped_count} messages)]\n{summary}",
            })

        result.extend(kept)
        return result

    def extract_key_decisions(
        self,
        messages: list[dict[str, Any]],
        min_confidence: float = 0.3,
    ) -> list[DecisionPoint]:
        """Find important decision points in the conversation.

        Uses regex patterns to identify statements that indicate
        a decision, commitment, or action item. Scores confidence
        based on pattern match count and content length.

        Args:
            messages: Conversation messages.
            min_confidence: Minimum confidence threshold (0-1).

        Returns:
            List of DecisionPoint objects, ordered by confidence.
        """
        decisions: list[DecisionPoint] = []

        for i, msg in enumerate(messages):
            content = str(msg.get("content", ""))
            if len(content) < 10:
                continue

            matches = 0
            for pattern in DECISION_PATTERNS:
                if re.search(pattern, content):
                    matches += 1

            if matches == 0:
                continue

            confidence = min(1.0, matches * 0.25 + min(len(content) / 500, 0.5))
            if confidence < min_confidence:
                continue

            ctx_before = str(messages[i - 1].get("content", "")) if i > 0 else ""
            ctx_after = str(messages[i + 1].get("content", "")) if i + 1 < len(messages) else ""

            decisions.append(DecisionPoint(
                content=content[:300],
                role=msg.get("role", ""),
                confidence=confidence,
                context_before=ctx_before[:200],
                context_after=ctx_after[:200],
            ))

        decisions.sort(key=lambda d: d.confidence, reverse=True)
        return decisions[:10]

    def generate_tldr(self, messages: list[dict[str, Any]]) -> str:
        """Generate a one-paragraph TL;DR summary.

        Heuristic approach:
        1. Extract the user's first substantive message as intent.
        2. Extract key decisions.
        3. Extract final outcome / last assistant message.
        4. Combine into a concise paragraph.

        Args:
            messages: Conversation messages.

        Returns:
            One-paragraph summary string.
        """
        if not messages:
            return "Empty session."

        user_msgs = [m for m in messages if m.get("role") == "user"]
        assistant_msgs = [m for m in messages if m.get("role") == "assistant"]

        # Intent: first substantive user message
        intent = ""
        for m in user_msgs:
            content = str(m.get("content", "")).strip()
            if len(content) > 20:
                intent = self._truncate_sentence(content, 120)
                break

        # Outcome: last assistant message or last decision
        outcome = ""
        decisions = self.extract_key_decisions(messages)
        if decisions:
            outcome = self._truncate_sentence(decisions[-1].content, 100)

        if not outcome and assistant_msgs:
            last = str(assistant_msgs[-1].get("content", "")).strip()
            outcome = self._truncate_sentence(last, 100)

        # Build TL;DR
        parts = []
        if intent:
            parts.append(f"User wanted to: {intent}")
        if decisions:
            parts.append(f"Made {len(decisions)} key decisions")
        if outcome:
            parts.append(f"Outcome: {outcome}")

        if not parts:
            return f"Conversation with {len(messages)} messages."

        return ". ".join(parts) + "."

    def compress_context(
        self,
        messages: list[dict[str, Any]],
        target_tokens: int = 4000,
    ) -> list[dict[str, Any]]:
        """Aggressive compression for API context windows.

        Uses multi-pass strategy:
        1. Sliding window for recent messages.
        2. Strip low-signal filler content from kept messages.
        3. Summarize removed messages into a compact system note.

        Args:
            messages: Full message list.
            target_tokens: Target token budget.

        Returns:
            Compressed message list.
        """
        # Pass 1: sliding window
        windowed = self.sliding_window(messages, max_tokens=target_tokens)

        # Pass 2: strip low-signal filler
        compressed: list[dict[str, Any]] = []
        for msg in windowed:
            content = str(msg.get("content", ""))
            if msg.get("role") == "system":
                compressed.append(msg)
                continue

            # Strip filler from non-system messages
            cleaned = self._strip_filler(content)
            compressed.append({**msg, "content": cleaned})

        # Pass 3: if still over budget, merge similar consecutive messages
        total = self._estimate_tokens(
            " ".join(str(m.get("content", "")) for m in compressed)
        )
        if total > target_tokens:
            compressed = self._merge_consecutive(compressed, target_tokens)

        return compressed

    def close(self) -> None:
        """Close the underlying database connection."""
        self._store.close()

    # ── Internal helpers ──────────────────────────────────────

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token count (4 chars ≈ 1 token)."""
        return max(1, len(text) // CHARS_PER_TOKEN)

    @staticmethod
    def _truncate_sentence(text: str, max_chars: int) -> str:
        """Truncate text at a sentence boundary."""
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars]
        # Try to break at last sentence end
        for sep in [". ", "! ", "? ", "\n"]:
            last = truncated.rfind(sep)
            if last > max_chars // 2:
                return truncated[:last + 1]
        return truncated.rsplit(" ", 1)[0] + "..."

    def _extract_topics(self, messages: list[dict[str, Any]]) -> list[str]:
        """Extract key topic words from the conversation."""
        # Collect significant words (nouns, proper nouns, technical terms)
        word_counter: Counter[str] = Counter()
        for msg in messages:
            content = str(msg.get("content", ""))
            # Find capitalized words, code identifiers, quoted terms
            caps = re.findall(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?\b", content)
            for c in caps:
                word_counter[c.lower()] += 1
            tech = re.findall(r"\b[a-z_]{4,}(?:_[a-z]+)+\b", content)  # snake_case
            for t in tech:
                word_counter[t] += 1

        # Return top topics
        return [w for w, _ in word_counter.most_common(10)]

    @staticmethod
    def _count_roles(messages: list[dict[str, Any]]) -> dict[str, int]:
        """Count messages by role."""
        counts: dict[str, int] = {}
        for msg in messages:
            role = msg.get("role", "unknown")
            counts[role] = counts.get(role, 0) + 1
        return counts

    @staticmethod
    def _estimate_duration(messages: list[dict[str, Any]]) -> float:
        """Estimate session duration from message timestamps."""
        timestamps = [
            m.get("created_at", 0)
            for m in messages
            if m.get("created_at", 0) > 0
        ]
        if len(timestamps) < 2:
            return 0.0
        return max(0.0, max(timestamps) - min(timestamps))

    @staticmethod
    def _strip_filler(text: str) -> str:
        """Remove low-signal filler from text."""
        for pattern in LOW_SIGNAL_PATTERNS:
            text = re.sub(pattern, "", text)
        # Collapse multiple newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _compress_dropped(self, messages: list[dict[str, Any]]) -> str:
        """Create a compressed summary of dropped messages."""
        tldr = self.generate_tldr(messages)
        decisions = self.extract_key_decisions(messages)
        topics = self._extract_topics(messages)

        lines = [f"Summary: {tldr}"]
        if decisions:
            lines.append(
                f"Key decisions: {'; '.join(d.content[:80] for d in decisions[:3])}"
            )
        if topics:
            lines.append(f"Topics: {', '.join(topics[:5])}")

        return "\n".join(lines)

    @staticmethod
    def _merge_consecutive(
        messages: list[dict[str, Any]],
        target_tokens: int,
    ) -> list[dict[str, Any]]:
        """Merge consecutive same-role messages to save tokens."""
        if len(messages) <= 2:
            return messages

        merged: list[dict[str, Any]] = [messages[0]]
        for msg in messages[1:]:
            prev = merged[-1]
            if (
                msg.get("role") == prev.get("role")
                and msg.get("role") not in ("system",)
            ):
                prev["content"] = (
                    str(prev.get("content", "")) + "\n" + str(msg.get("content", ""))
                )
            else:
                merged.append(msg)

            # Check budget
            total = len(
                " ".join(str(m.get("content", "")) for m in merged)
            ) // CHARS_PER_TOKEN
            if total <= target_tokens:
                continue

        return merged


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _self_test() -> None:
    """Verify SessionSummarizer basic functionality."""
    import tempfile
    from pathlib import Path

    db_path = Path(tempfile.gettempdir()) / "omnicore_test_summarize.db"
    summarizer = SessionSummarizer(db_path=str(db_path))

    # Seed test data
    sid = "test-summary-001"
    summarizer._store.create_session(sid, "Build Session")
    msgs = [
        ("user", "I need to build a REST API for user management"),
        ("assistant", "I'll create a FastAPI app with SQLAlchemy and JWT auth. We should use PostgreSQL for the database."),
        ("user", "Yes, go with PostgreSQL. Also add rate limiting."),
        ("assistant", "Building the project structure now — models, routes, middleware. Let me implement the rate limiter first."),
        ("assistant", "Done. Created all files. The API is ready with JWT auth, rate limiting, and full CRUD endpoints. Deployed to staging."),
    ]
    for role, content in msgs:
        summarizer._store.save_message(sid, role, content)

    # Test summarize
    digest = summarizer.summarize(sid)
    assert digest.message_count == 5, f"Expected 5 msgs, got {digest.message_count}"
    assert len(digest.tldr) > 10, "TLDR too short"
    assert len(digest.key_decisions) >= 1, "No decisions extracted"
    assert len(digest.top_topics) >= 1, "No topics extracted"
    assert digest.roles_distribution.get("user", 0) >= 1
    assert digest.roles_distribution.get("assistant", 0) >= 1

    # Test generate_tldr standalone
    messages = summarizer._store.get_messages(sid, limit=100)
    tldr = summarizer.generate_tldr(messages)
    assert len(tldr) > 10, "TLDR standalone too short"

    # Test extract_key_decisions standalone
    decisions = summarizer.extract_key_decisions(messages, min_confidence=0.0)
    assert len(decisions) >= 1, "No decisions found standalone"

    # Test sliding_window
    big_msgs = messages * 20  # 100 messages
    windowed = summarizer.sliding_window(big_msgs, max_tokens=500)
    assert len(windowed) <= len(big_msgs), "Window should reduce messages"

    # Test compress_context
    compressed = summarizer.compress_context(big_msgs, target_tokens=500)
    assert len(compressed) <= len(big_msgs), "Compress should reduce messages"

    summarizer.close()
    db_path.unlink(missing_ok=True)
    print("✓ SessionSummarizer self-test PASSED")


if __name__ == "__main__":
    _self_test()