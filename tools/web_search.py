"""Web search tool. Uses DuckDuckGo (free, no API key)."""


def search_web(query: str, max_results: int = 5) -> str:
    """Search the web. Returns titles + URLs + snippets."""
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return "Web search unavailable. Install: pip install duckduckgo-search"

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        return f"Search failed: {e}"

    if not results:
        return f"No results for '{query}'"

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "No title")
        href = r.get("href", "")
        body = r.get("body", "")[:200]
        lines.append(f"{i}. {title}\n   {href}\n   {body}")

    return "\n\n".join(lines)