"""Context window management. Auto-summarize old messages to stay
within token limits. Sliding window with intelligent truncation.
"""

from typing import Optional


class ContextManager:
    """Manages conversation context to fit within model token limits."""

    def __init__(self, max_messages: int = 50, max_chars: int = 50000):
        self.max_messages = max_messages
        self.max_chars = max_chars

    def trim(self, messages: list[dict], preserve_system: bool = True) -> list[dict]:
        """Trim message list to fit within limits.
        
        Strategy:
        1. Always keep system message
        2. Keep recent messages (sliding window)
        3. Summarize old messages if needed
        """
        if not messages:
            return []

        result = []
        start = 0

        # Preserve system message
        if preserve_system and messages[0].get("role") == "system":
            result.append(messages[0])
            start = 1

        # Get recent messages
        recent = messages[start:][-self.max_messages:]
        
        # Check total size
        total_chars = sum(len(str(m.get("content", ""))) for m in result + recent)
        
        if total_chars <= self.max_chars:
            result.extend(recent)
            return result

        # Need to insert summary of old messages
        old_messages = messages[start:-self.max_messages] if len(messages) > self.max_messages else []
        if old_messages:
            summary = self._summarize_old(old_messages)
            result.append({"role": "system", "content": f"[Earlier conversation summary]\n{summary}"})

        # Add recent messages until we hit the limit
        chars_used = sum(len(str(m.get("content", ""))) for m in result)
        for msg in reversed(recent):
            msg_chars = len(str(msg.get("content", "")))
            if chars_used + msg_chars > self.max_chars:
                break
            result.append(msg)
            chars_used += msg_chars

        return result

    def _summarize_old(self, messages: list[dict]) -> str:
        """Create a brief summary of old conversation."""
        topics = set()
        for msg in messages:
            content = str(msg.get("content", ""))
            # Extract key topics (simple: proper nouns, quoted strings)
            import re
            # Find quoted strings
            quoted = re.findall(r'"([^"]+)"', content)
            topics.update(quoted)
            # Find capitalized phrases
            caps = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', content)
            topics.update(t[:3] for t in caps)

        summary_parts = [f"- Discussed: {', '.join(list(topics)[:10])}"]
        summary_parts.append(f"- {len(messages)} messages summarized")
        return "\n".join(summary_parts)

    def estimate_tokens(self, text: str) -> int:
        """Rough token count (4 chars ≈ 1 token for English)."""
        return len(text) // 4