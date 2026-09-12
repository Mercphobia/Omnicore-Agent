"""
OmniCore v3 — Session Search Engine (Phase 10)
==============================================
DNA: LTX-Quasar cold-protocol — find anything, instantly.

Full-text search across all session history backed by the existing
MemoryStore SQLite backend. Supports keyword + context matching,
recent activity, tool-specific queries, and result export.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .store import MemoryStore


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH: str = "~/.omnicore/memory.db"
DEFAULT_LIMIT: int = 20
MAX_SNIPPET_LEN: int = 300
SCORE_EXACT_MATCH: int = 100
SCORE_PARTIAL_MATCH: int = 50
SCORE_CONTEXT_BONUS: int = 25
SCORE_RECENCY_DECAY: float = 0.95  # per day


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """A single search hit with context and scoring."""
    session_id: str
    session_title: str = ""
    role: str = ""
    snippet: str = ""
    matched_on: str = ""
    score: float = 0.0
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "session_title": self.session_title,
            "role": self.role,
            "snippet": self.snippet,
            "matched_on": self.matched_on,
            "score": self.score,
            "timestamp": self.timestamp,
        }


@dataclass
class SessionSummary:
    """Lightweight session metadata for listing."""
    session_id: str
    title: str
    message_count: int = 0
    tool_names: list[str] = field(default_factory=list)
    first_seen: float = 0.0
    last_seen: float = 0.0
    key_topics: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SessionSearch
# ---------------------------------------------------------------------------

class SessionSearch:
    """Full-text search engine across all OmniCore session history.

    Backed by the existing MemoryStore SQLite backend. Provides
    keyword search, semantic (context-aware) matching, recent
    activity queries, tool-specific filtering, and structured export.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        """Initialize search engine with a MemoryStore connection.

        Args:
            db_path: Path to the SQLite memory database.
        """
        self._store = MemoryStore(db_path=db_path)
        self._db_path = db_path

    # ── Public API ────────────────────────────────────────────

    def search(
        self,
        query: str,
        limit: int = DEFAULT_LIMIT,
        session_id: Optional[str] = None,
    ) -> list[SearchResult]:
        """Full-text search across all session conversations.

        Splits the query into tokens, scores each message for
        relevance (exact match > partial > context), and returns
        ranked results with snippets.

        Args:
            query: Search query string.
            limit: Maximum results to return.
            session_id: Optional session filter.

        Returns:
            Ranked list of SearchResult objects.
        """
        if not query.strip():
            return []

        tokens = self._tokenize(query)
        if not tokens:
            return []

        # Fetch candidate messages via SQL LIKE
        candidates = self._fetch_candidates(tokens, session_id, limit * 3)

        # Score and rank
        scored: list[SearchResult] = []
        for c in candidates:
            score = self._score_message(c, tokens, query)
            if score > 0:
                snippet = self._build_snippet(c["content"], tokens)
                scored.append(SearchResult(
                    session_id=c["session_id"],
                    session_title=self._store.get_session_title(c["session_id"]),
                    role=c["role"],
                    snippet=snippet,
                    matched_on=self._matched_tokens(c["content"], tokens),
                    score=score,
                    timestamp=c.get("created_at", 0.0),
                ))

        # Sort by score descending, then recency
        scored.sort(key=lambda r: (r.score, r.timestamp), reverse=True)
        return scored[:limit]

    def semantic_search(self, query: str, limit: int = DEFAULT_LIMIT) -> list[SearchResult]:
        """Keyword + context-aware search using surrounding message
        context to boost relevance.

        Strategy:
        1. Run keyword search to get primary hits.
        2. For each hit, fetch adjacent messages in the same session.
        3. Boost score if adjacent messages contain related terms.

        Args:
            query: Search query string.
            limit: Maximum results to return.

        Returns:
            Context-boosted ranked results.
        """
        primary = self.search(query, limit=limit * 2)
        if not primary:
            return []

        tokens = self._tokenize(query)
        boosted: list[SearchResult] = []

        for result in primary:
            # Fetch context window around the hit
            context_msgs = self._get_context_window(
                result.session_id, window=3
            )
            # Check for related terms in surrounding messages
            context_text = " ".join(m.get("content", "") for m in context_msgs)
            context_hits = sum(
                1 for t in tokens if t.lower() in context_text.lower()
            )
            if context_hits >= 2:
                result.score += SCORE_CONTEXT_BONUS * context_hits
            boosted.append(result)

        boosted.sort(key=lambda r: (r.score, r.timestamp), reverse=True)
        return boosted[:limit]

    def recent_sessions(self, days: int = 7, limit: int = DEFAULT_LIMIT) -> list[SessionSummary]:
        """List sessions active within the last N days.

        Args:
            days: Look-back window in days.
            limit: Maximum sessions to return.

        Returns:
            List of SessionSummary objects, most recent first.
        """
        cutoff = time.time() - (days * 86400)
        all_sessions = self._store.list_sessions(limit=200)

        summaries: list[SessionSummary] = []
        for s in all_sessions:
            if s["updated_at"] < cutoff:
                continue
            sid = s["id"]
            msgs = self._store.get_messages(sid, limit=1000)
            tools = self._extract_tool_names(msgs)
            topics = self._extract_topics(msgs)
            summaries.append(SessionSummary(
                session_id=sid,
                title=s.get("title", ""),
                message_count=len(msgs),
                tool_names=tools,
                first_seen=s["created_at"],
                last_seen=s["updated_at"],
                key_topics=topics,
            ))

        summaries.sort(key=lambda s: s.last_seen, reverse=True)
        return summaries[:limit]

    def search_by_tool(
        self,
        tool_name: str,
        limit: int = DEFAULT_LIMIT,
    ) -> list[SearchResult]:
        """Find sessions that used a specific tool.

        Searches for tool invocation patterns in conversation content,
        e.g., 'tool: browser', 'using terminal', 'called search_files'.

        Args:
            tool_name: Name of the tool to search for.
            limit: Maximum results.

        Returns:
            Ranked SearchResult list.
        """
        # Build tool-specific query patterns
        patterns = [
            tool_name,
            f"tool:{tool_name}",
            f"<tool>{tool_name}</tool>",
            f"using {tool_name}",
        ]
        query = " OR ".join(patterns)
        return self.search(query, limit=limit)

    def export_results(
        self,
        query: str,
        output_format: str = "json",
        output_path: Optional[str] = None,
    ) -> str:
        """Run search and export results to the requested format.

        Args:
            query: Search query.
            output_format: 'json' or 'csv'.
            output_path: Optional file path to write to. If None,
                         returns the serialized string.

        Returns:
            Serialized result string (JSON or CSV).
        """
        results = self.search(query, limit=200)

        if output_format == "csv":
            return self._export_csv(results, output_path)
        return self._export_json(results, output_path)

    def close(self) -> None:
        """Close the underlying database connection."""
        self._store.close()

    # ── Internal helpers ──────────────────────────────────────

    @staticmethod
    def _tokenize(query: str) -> list[str]:
        """Split query into meaningful search tokens."""
        # Split on whitespace and punctuation, keep words >= 2 chars
        raw = re.findall(r"[A-Za-z0-9_./\-]{2,}", query)
        # Deduplicate while preserving order for multi-term queries
        seen: set[str] = set()
        tokens: list[str] = []
        for t in raw:
            if t.lower() not in seen:
                seen.add(t.lower())
                tokens.append(t)
        return tokens

    def _fetch_candidates(
        self,
        tokens: list[str],
        session_id: Optional[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        """Query database for messages matching any token."""
        import sqlite3

        conn = self._store.conn
        # Build OR-chain of LIKE clauses
        conditions = " OR ".join(["content LIKE ?" for _ in tokens])
        params = [f"%{t}%" for t in tokens]

        if session_id:
            sql = (
                "SELECT session_id, role, content, created_at "
                "FROM conversations WHERE session_id = ? AND ({conditions}) "
                "ORDER BY id DESC LIMIT ?"
            ).format(conditions=conditions)
            all_params = [session_id] + params + [limit]
        else:
            sql = (
                "SELECT session_id, role, content, created_at "
                "FROM conversations WHERE ({conditions}) "
                "ORDER BY id DESC LIMIT ?"
            ).format(conditions=conditions)
            all_params = params + [limit]

        rows = conn.execute(sql, all_params).fetchall()
        return [dict(r) for r in rows]

    def _score_message(
        self,
        msg: dict[str, Any],
        tokens: list[str],
        raw_query: str,
    ) -> float:
        """Score a candidate message for relevance."""
        content = msg.get("content", "")
        content_lower = content.lower()
        score = 0.0

        for token in tokens:
            token_lower = token.lower()
            count = content_lower.count(token_lower)
            if count > 0:
                # Exact word match scores higher
                if re.search(rf"\b{re.escape(token)}\b", content, re.IGNORECASE):
                    score += SCORE_EXACT_MATCH * count
                else:
                    score += SCORE_PARTIAL_MATCH * count

        # Bonus for full phrase match
        if raw_query.lower() in content_lower:
            score += SCORE_EXACT_MATCH * 2

        # Recency bonus
        ts = msg.get("created_at", 0.0)
        if ts > 0:
            days_ago = (time.time() - ts) / 86400
            score *= max(0.2, SCORE_RECENCY_DECAY ** days_ago)

        return score

    @staticmethod
    def _matched_tokens(content: str, tokens: list[str]) -> str:
        """Return comma-separated list of tokens that matched."""
        content_lower = content.lower()
        matched = [t for t in tokens if t.lower() in content_lower]
        return ", ".join(matched[:5])

    @staticmethod
    def _build_snippet(content: str, tokens: list[str], window: int = 40) -> str:
        """Extract a relevant snippet around the first token match."""
        if len(content) <= MAX_SNIPPET_LEN:
            return content

        content_lower = content.lower()
        best_pos = -1
        for token in tokens:
            pos = content_lower.find(token.lower())
            if pos != -1:
                best_pos = pos
                break

        if best_pos == -1:
            return content[:MAX_SNIPPET_LEN] + "..."

        start = max(0, best_pos - window)
        end = min(len(content), best_pos + len(tokens[0]) + window)
        snippet = content[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."
        return snippet

    def _get_context_window(
        self,
        session_id: str,
        window: int = 3,
    ) -> list[dict[str, Any]]:
        """Get messages surrounding context for a session."""
        msgs = self._store.get_messages(session_id, limit=window * 2 + 1)
        return msgs[-window * 2:]

    @staticmethod
    def _extract_tool_names(messages: list[dict[str, Any]]) -> list[str]:
        """Extract tool names mentioned in messages."""
        tool_pattern = re.compile(
            r'(?:tool|using|called|invoked?|ran)\s+[`"\']?(\w+)[`"\']?',
            re.IGNORECASE,
        )
        tools: set[str] = set()
        for msg in messages:
            content = str(msg.get("content", ""))
            for match in tool_pattern.finditer(content):
                tools.add(match.group(1).lower())
        return sorted(tools)[:20]

    @staticmethod
    def _extract_topics(messages: list[dict[str, Any]]) -> list[str]:
        """Extract key topic words from messages."""
        # Simple: find capitalized phrases and quoted strings
        topics: set[str] = set()
        for msg in messages:
            content = str(msg.get("content", ""))
            quoted = re.findall(r'"([^"]+)"', content)
            topics.update(q.lower() for q in quoted)
            caps = re.findall(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?\b", content)
            topics.update(c.lower() for c in caps[:5])
        return sorted(topics)[:15]

    # ── Export helpers ────────────────────────────────────────

    @staticmethod
    def _export_json(
        results: list[SearchResult],
        output_path: Optional[str],
    ) -> str:
        """Serialize results to JSON."""
        data = {
            "count": len(results),
            "exported_at": time.time(),
            "results": [r.to_dict() for r in results],
        }
        serialized = json.dumps(data, indent=2, ensure_ascii=False)
        if output_path:
            Path(output_path).write_text(serialized, encoding="utf-8")
        return serialized

    @staticmethod
    def _export_csv(
        results: list[SearchResult],
        output_path: Optional[str],
    ) -> str:
        """Serialize results to CSV."""
        import csv
        import io

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "session_id", "session_title", "role", "snippet",
            "matched_on", "score", "timestamp",
        ])
        for r in results:
            writer.writerow([
                r.session_id, r.session_title, r.role,
                r.snippet.replace('"', '""'), r.matched_on,
                r.score, r.timestamp,
            ])
        serialized = buf.getvalue()
        if output_path:
            Path(output_path).write_text(serialized, encoding="utf-8")
        return serialized


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _self_test() -> None:
    """Verify SessionSearch basic functionality."""
    import tempfile

    db_path = Path(tempfile.gettempdir()) / "omnicore_test_search.db"
    searcher = SessionSearch(db_path=str(db_path))

    # Seed test data
    sid = "test-session-001"
    searcher._store.create_session(sid, "Test Session")
    searcher._store.save_message(sid, "user", "scan the target network for open ports")
    searcher._store.save_message(sid, "assistant", "Running nmap scan on port 22 and 443 using terminal")
    searcher._store.save_message(sid, "user", "what did the search_files tool find?")
    searcher._store.save_message(sid, "assistant", "Found 3 config files with search_files pattern *.conf")

    # Test search
    results = searcher.search("nmap", limit=5)
    assert len(results) >= 1, f"Expected >=1 result, got {len(results)}"
    assert any("nmap" in r.snippet.lower() for r in results), "nmap not in results"

    # Test search_by_tool
    tool_results = searcher.search_by_tool("search_files")
    assert len(tool_results) >= 1, "search_files tool not found"

    # Test export
    json_out = searcher.export_results("port", output_format="json")
    data = json.loads(json_out)
    assert data["count"] >= 1, "Export count mismatch"

    csv_out = searcher.export_results("terminal", output_format="csv")
    assert "session_id" in csv_out, "CSV header missing"

    # Test recent_sessions
    recent = searcher.recent_sessions(days=365)
    assert any(s.session_id == sid for s in recent), "Test session not in recent"

    searcher.close()
    db_path.unlink(missing_ok=True)
    print("✓ SessionSearch self-test PASSED")


if __name__ == "__main__":
    _self_test()