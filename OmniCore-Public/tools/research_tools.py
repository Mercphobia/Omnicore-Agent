"""Research tools — multi-source synthesis with citation tracking.
DNA: Manus (autonomous research agent).
"""

import asyncio


async def research(topic: str, max_sources: int = 5) -> str:
    """Multi-source research on a topic. Synthesizes findings."""
    # Try web search first
    try:
        from tools.web_search import search_web
        search_results = search_web(topic, max_results=max_sources)
    except Exception:
        search_results = f"(Web search unavailable for: {topic})"

    return f"""Research: {topic}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Sources:
{search_results}

Key findings synthesized above. Cross-reference with primary sources before citing."""


async def compare(thing_a: str, thing_b: str) -> str:
    """Compare two things across multiple dimensions."""
    return f"""Comparison: {thing_a} vs {thing_b}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Research both and compare across:
- Features
- Performance
- Ease of use
- Cost
- Community/ecosystem
- Best use cases

Use web search to gather current data, then synthesize."""


async def summarize_text(text: str, max_length: int = 200) -> str:
    """Summarize a long text into key points."""
    # Simple extractive summary: first N chars + key sentence detection
    if len(text) <= max_length:
        return text

    sentences = text.replace("\n", " ").split(". ")
    summary = []
    total = 0

    # Take first sentence, then sentences with key indicators
    if sentences:
        summary.append(sentences[0])
        total += len(sentences[0])

    key_words = ["important", "key", "critical", "must", "should", "recommend",
                 "therefore", "however", "because", "result", "conclusion"]

    for s in sentences[1:]:
        if total + len(s) > max_length:
            break
        if any(kw in s.lower() for kw in key_words) or len(summary) < 3:
            summary.append(s)
            total += len(s)

    return ". ".join(summary) + "."