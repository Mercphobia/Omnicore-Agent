"""Context Weaver — cross-session insight synthesis and pattern detection.

DNA: knowledge graph traversal + temporal reasoning + pattern recognition +
     serendipity engine (hidden connection discovery).

The Context Weaver finds connections that no single session would reveal.
It treats every conversation, every solved problem, every discovered insight
as nodes in a knowledge graph. Its job: traverse the graph, find hidden edges,
and surface the pattern that connects seemingly unrelated things.

Works with MemoryGraph for persistent storage of concepts and connections.

Usage::

    weaver = ContextWeaver(memory_graph)
    threads = weaver.thread_sessions(sessions_list)
    patterns = weaver.temporal_pattern(timeline_events)
    connections = weaver.connect_concepts("neural_networks", "decision_trees")
    insights = weaver.insight_generate()
    score = weaver.relevance_score("old_concept", "current_problem")
    report = weaver.weave_report()
"""

from __future__ import annotations

import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

# ── Data types ──────────────────────────────────────────────────────────


@dataclass
class SessionSummary:
    """Lightweight session representation for cross-session analysis."""

    session_id: str
    timestamp: float  # epoch seconds
    topics: list[str]
    key_concepts: list[str]
    outcomes: list[str]
    tools_used: list[str]
    errors_encountered: list[str]
    sentiment: str = "neutral"  # positive, negative, neutral
    summary: str = ""


@dataclass
class Theme:
    """A thematic thread spanning multiple sessions."""

    name: str
    sessions: list[str]  # session_ids
    strength: float  # 0-1 how strongly this theme recurs
    first_seen: float
    last_seen: float
    evolution: str  # how the theme evolved: ESCALATING, RESOLVED, CYCLICAL, STABLE
    keywords: list[str]


@dataclass
class TemporalPattern:
    """A detected pattern over time."""

    pattern_type: str  # RECURRENCE, ESCALATION, CYCLICAL, REGRESSION, TREND
    description: str
    events: list[str]
    period_days: float  # average period if cyclical, else 0
    confidence: float
    recommendation: str


@dataclass
class ConceptConnection:
    """A hidden connection between two concepts."""

    concept_a: str
    concept_b: str
    connection_type: str  # SEMANTIC, STRUCTURAL, TEMPORAL, SERENDIPITOUS
    shared_abstraction: str  # the deeper concept they share
    path: list[str]  # intermediate concepts along the path
    strength: float  # 0-1
    evidence: str  # what evidence supports this connection


@dataclass
class Insight:
    """A novel insight generated from context weaving."""

    title: str
    description: str
    source_sessions: list[str]
    insight_type: str  # PATTERN, CONNECTION, WARNING, OPPORTUNITY, ABSTRACTION
    confidence: float
    actionable: bool
    action: str  # what to do with this insight


@dataclass
class WeaveReport:
    """Comprehensive cross-session insight report."""

    generated_at: float
    total_sessions_analyzed: int
    themes: list[Theme]
    temporal_patterns: list[TemporalPattern]
    connections: list[ConceptConnection]
    insights: list[Insight]
    concept_graph_summary: str
    recommendations: list[str]
    serendipity_score: float  # 0-1 how many surprising connections found


# ── Core engine ─────────────────────────────────────────────────────────


class ContextWeaver:
    """Find hidden connections across sessions, concepts, and time.

    Parameters:
        memory_graph: Optional MemoryGraph for persistent concept storage.
        session_window_days: How many days back to consider for analysis.
        min_theme_strength: Minimum strength threshold for theme detection.
    """

    def __init__(
        self,
        memory_graph: Any = None,
        session_window_days: float = 90.0,
        min_theme_strength: float = 0.3,
    ) -> None:
        self.memory_graph = memory_graph
        self.session_window_days = session_window_days
        self.min_theme_strength = min_theme_strength

        # Internal state
        self._sessions: list[SessionSummary] = []
        self._concept_index: dict[str, list[str]] = defaultdict(list)  # concept -> session_ids
        self._insights: list[Insight] = []
        self._connections: list[ConceptConnection] = []

    # ── Public API ──────────────────────────────────────────────────

    def thread_sessions(
        self, sessions: Sequence[SessionSummary]
    ) -> list[Theme]:
        """Find thematic threads that span multiple sessions.

        Args:
            sessions: Sequence of SessionSummary objects to analyze.

        Returns:
            List of Theme objects representing recurrent themes.
        """
        self._sessions = list(sessions)
        self._rebuild_concept_index()

        themes: list[Theme] = []
        all_keywords: Counter[str] = Counter()

        for session in sessions:
            all_keywords.update(session.topics)
            all_keywords.update(session.key_concepts)

        # Themes emerge from recurring keywords across sessions
        now = time.time()
        for keyword, count in all_keywords.items():
            if count < 2:
                continue

            # Find sessions mentioning this keyword
            session_ids = self._concept_index.get(keyword, [])
            if len(session_ids) < 2:
                continue

            # Calculate theme strength: how concentrated is this keyword?
            total_sessions = len(sessions)
            strength = count / max(total_sessions, 1)

            if strength < self.min_theme_strength:
                continue

            # Determine evolution
            timestamps = [
                s.timestamp
                for s in sessions
                if s.session_id in session_ids
            ]
            evolution = self._classify_evolution(keyword, session_ids)

            themes.append(
                Theme(
                    name=keyword,
                    sessions=list(session_ids),
                    strength=round(strength, 3),
                    first_seen=min(timestamps) if timestamps else now,
                    last_seen=max(timestamps) if timestamps else now,
                    evolution=evolution,
                    keywords=[keyword],
                )
            )

        # Merge related themes (shared sessions)
        themes = self._merge_related_themes(themes)

        return sorted(themes, key=lambda t: t.strength, reverse=True)

    def temporal_pattern(
        self, timeline: Sequence[dict[str, Any]]
    ) -> list[TemporalPattern]:
        """Detect patterns in a timeline of events.

        Args:
            timeline: Sequence of dicts with keys: 'timestamp', 'event', 'type'.

        Returns:
            List of TemporalPattern objects.
        """
        if not timeline:
            return []

        patterns: list[TemporalPattern] = []
        sorted_events = sorted(timeline, key=lambda e: e.get("timestamp", 0.0))

        # Recurrence detection: same event type appearing multiple times
        type_counts: Counter[str] = Counter()
        for event in sorted_events:
            type_counts[event.get("type", event.get("event", "unknown"))] += 1

        for event_type, count in type_counts.items():
            if count >= 3:
                matching = [
                    e.get("event", "")
                    for e in sorted_events
                    if (e.get("type") == event_type or e.get("event") == event_type)
                    or event_type in str(e.get("event", ""))
                ]
                pattern_type = "CYCLICAL" if count >= 5 else "RECURRENCE"
                period = self._estimate_period(
                    [
                        e["timestamp"]
                        for e in sorted_events
                        if e.get("type") == event_type
                    ]
                )

                patterns.append(
                    TemporalPattern(
                        pattern_type=pattern_type,
                        description=f"'{event_type}' appears {count} times across timeline",
                        events=matching[:10],
                        period_days=round(period, 1),
                        confidence=min(0.5 + count * 0.1, 0.95),
                        recommendation=self._pattern_recommendation(pattern_type, event_type),
                    )
                )

        # Escalation detection: severity/urgency increasing over time
        if len(sorted_events) >= 3:
            severities = [
                e.get("severity", e.get("priority", e.get("urgency", 0)))
                for e in sorted_events
            ]
            numeric_severities = []
            for s in severities:
                if isinstance(s, (int, float)):
                    numeric_severities.append(s)
                elif isinstance(s, str) and s.upper() in ("HIGH", "CRITICAL", "SEVERE"):
                    numeric_severities.append(3)
                elif isinstance(s, str) and s.upper() in ("MEDIUM", "MODERATE"):
                    numeric_severities.append(2)
                elif isinstance(s, str) and s.upper() in ("LOW", "MINOR"):
                    numeric_severities.append(1)
                else:
                    numeric_severities.append(0)

            if len(numeric_severities) >= 3:
                first_half = numeric_severities[: len(numeric_severities) // 2]
                second_half = numeric_severities[len(numeric_severities) // 2 :]
                if statistics.mean(second_half) > statistics.mean(first_half) * 1.5:
                    patterns.append(
                        TemporalPattern(
                            pattern_type="ESCALATION",
                            description="Severity of events is increasing over time.",
                            events=[e.get("event", "") for e in sorted_events[-5:]],
                            period_days=0.0,
                            confidence=0.7,
                            recommendation="Escalating pattern — root cause not being addressed. Intervene now.",
                        )
                    )

        # Regression detection: previously resolved issues reappearing
        resolved_set: set[str] = set()
        for event in sorted_events:
            evt = event.get("event", "")
            status = event.get("status", "")
            if status in ("resolved", "fixed", "closed"):
                resolved_set.add(evt)
            elif evt in resolved_set and status not in ("resolved", "fixed", "closed"):
                patterns.append(
                    TemporalPattern(
                        pattern_type="REGRESSION",
                        description=f"Previously resolved issue reappeared: '{evt}'",
                        events=[evt],
                        period_days=0.0,
                        confidence=0.8,
                        recommendation=f"Check what changed around '{evt}' — something reintroduced the bug.",
                    )
                )
                resolved_set.discard(evt)  # re-arm for future detection

        return patterns

    def connect_concepts(
        self, concept_a: str, concept_b: str, max_depth: int = 4
    ) -> Optional[ConceptConnection]:
        """Find hidden connections between two concepts.

        Uses the memory graph (if available) or the internal concept index
        to find paths connecting two seemingly unrelated concepts.

        Args:
            concept_a: First concept name.
            concept_b: Second concept name.
            max_depth: Maximum traversal depth for path finding.

        Returns:
            ConceptConnection if a path exists, None otherwise.
        """
        # Short-circuit: direct match
        if concept_a.lower() == concept_b.lower():
            return ConceptConnection(
                concept_a=concept_a,
                concept_b=concept_b,
                connection_type="SEMANTIC",
                shared_abstraction="Identical concepts",
                path=[concept_a],
                strength=1.0,
                evidence="Exact match.",
            )

        # Try memory graph traversal
        if self.memory_graph is not None:
            path = self._graph_path(concept_a, concept_b, max_depth)
            if path:
                return self._build_connection(concept_a, concept_b, path, "memory_graph")

        # Try internal concept index co-occurrence
        sessions_a = set(self._concept_index.get(concept_a.lower(), []))
        sessions_b = set(self._concept_index.get(concept_b.lower(), []))
        shared = sessions_a & sessions_b

        if shared:
            return ConceptConnection(
                concept_a=concept_a,
                concept_b=concept_b,
                connection_type="TEMPORAL",
                shared_abstraction=f"Both discussed in same sessions: {shared}",
                path=[concept_a, concept_b],
                strength=min(len(shared) / max(len(self._sessions), 1) * 3, 1.0),
                evidence=f"Co-occurrence in {len(shared)} session(s).",
            )

        # Serendipitous: find shared abstraction via keyword overlap
        if concept_a in self._concept_index and concept_b in self._concept_index:
            related_a = self._find_related(concept_a)
            related_b = self._find_related(concept_b)
            shared_abstractions = related_a & related_b

            if shared_abstractions:
                abstraction = next(iter(shared_abstractions))
                return ConceptConnection(
                    concept_a=concept_a,
                    concept_b=concept_b,
                    connection_type="SERENDIPITOUS",
                    shared_abstraction=abstraction,
                    path=[concept_a, abstraction, concept_b],
                    strength=0.4,
                    evidence=f"Both relate to abstract concept: {abstraction}",
                )

        return None

    def insight_generate(self) -> list[Insight]:
        """Generate novel insights from accumulated context.

        Returns:
            List of Insight objects, potentially action-guiding.
        """
        insights: list[Insight] = []

        if not self._sessions:
            return insights

        # Insight type 1: Most reinforced concept across sessions
        concept_weights: Counter[str] = Counter()
        for session in self._sessions:
            for concept in session.key_concepts:
                concept_weights[concept] += 1
            for topic in session.topics:
                concept_weights[topic] += 0.5

        if concept_weights:
            top_concept, top_count = concept_weights.most_common(1)[0]
            insights.append(
                Insight(
                    title=f"Core concern: '{top_concept}'",
                    description=(
                        f"'{top_concept}' appears across {top_count:.0f} session(s) — "
                        f"it is the most reinforced concept. This may indicate a core "
                        f"problem that needs fundamental resolution rather than patch fixes."
                    ),
                    source_sessions=self._concept_index.get(top_concept, []),
                    insight_type="PATTERN",
                    confidence=min(0.5 + top_count * 0.1, 0.9),
                    actionable=True,
                    action=f"Investigate root cause of '{top_concept}' recurring pattern.",
                )
            )

        # Insight type 2: Error clusters
        error_counts: Counter[str] = Counter()
        for session in self._sessions:
            error_counts.update(session.errors_encountered)

        if error_counts:
            top_error, error_count = error_counts.most_common(1)[0]
            if error_count >= 2:
                insights.append(
                    Insight(
                        title=f"Recurring error: '{top_error}'",
                        description=(
                            f"Error '{top_error}' appears in {error_count} session(s). "
                            f"This is not a one-off — it's a systemic issue."
                        ),
                        source_sessions=[
                            s.session_id
                            for s in self._sessions
                            if top_error in s.errors_encountered
                        ],
                        insight_type="WARNING",
                        confidence=min(0.6 + error_count * 0.1, 0.9),
                        actionable=True,
                        action=f"Root-cause analysis for recurring error: '{top_error}'.",
                    )
                )

        # Insight type 3: Sentiment trend
        sentiments = [s.sentiment for s in self._sessions if s.sentiment != "neutral"]
        if len(sentiments) >= 3:
            neg_count = sentiments.count("negative")
            pos_count = sentiments.count("positive")
            if neg_count > pos_count:
                insights.append(
                    Insight(
                        title="Negative sentiment trend",
                        description=(
                            f"More negative ({neg_count}) than positive ({pos_count}) "
                            f"session sentiments. Consider underlying cause."
                        ),
                        source_sessions=[s.session_id for s in self._sessions],
                        insight_type="WARNING",
                        confidence=0.6,
                        actionable=True,
                        action="Review sessions with negative sentiment for systemic issues.",
                    )
                )

        # Insight type 4: Cross-session abstraction
        all_keywords: set[str] = set()
        for session in self._sessions:
            all_keywords.update(k.lower() for k in session.key_concepts)
            all_keywords.update(t.lower() for t in session.topics)

        if len(all_keywords) >= 5:
            insights.append(
                Insight(
                    title="Cross-session knowledge synthesis",
                    description=(
                        f"Across {len(self._sessions)} sessions, {len(all_keywords)} "
                        f"unique concepts were discussed. Key domains include: "
                        f"{', '.join(sorted(all_keywords)[:10])}."
                    ),
                    source_sessions=[s.session_id for s in self._sessions],
                    insight_type="ABSTRACTION",
                    confidence=0.8,
                    actionable=False,
                    action="",
                )
            )

        self._insights = insights
        return insights

    def relevance_score(self, concept: str, current_context: str) -> float:
        """Calculate how relevant an old concept is to the current problem.

        Uses semantic overlap and temporal decay to score relevance.

        Args:
            concept: The old concept to evaluate.
            current_context: Description of the current problem/session.

        Returns:
            Relevance score 0-1 (higher = more relevant).
        """
        concept_lower = concept.lower()
        context_lower = current_context.lower()
        context_words = set(context_lower.split())

        # Direct match bonus
        if concept_lower in context_lower:
            return 0.9

        # Keyword overlap
        concept_words = set(concept_lower.split())
        overlap = concept_words & context_words
        semantic_score = len(overlap) / max(len(concept_words), 1)

        # Temporal decay: older concepts lose relevance
        if concept_lower in self._concept_index:
            session_ids = self._concept_index[concept_lower]
            timestamps = [
                s.timestamp
                for s in self._sessions
                if s.session_id in session_ids
            ]
            if timestamps:
                age_days = (time.time() - max(timestamps)) / 86400.0
                temporal_score = max(0.0, 1.0 - age_days / self.session_window_days)
            else:
                temporal_score = 0.3
        else:
            temporal_score = 0.2  # never seen this concept

        # Combine scores
        score = 0.4 * semantic_score + 0.3 * temporal_score + 0.3 * (0.5 if overlap else 0.0)
        return round(min(score, 1.0), 4)

    def weave_report(self) -> WeaveReport:
        """Generate a comprehensive cross-session insight report.

        Returns:
            WeaveReport with themes, patterns, connections, and recommendations.
        """
        themes = self.thread_sessions(self._sessions)

        # Build fake timeline from sessions for temporal pattern detection
        timeline = [
            {
                "timestamp": s.timestamp,
                "event": topic,
                "type": s.sentiment if s.sentiment != "neutral" else "info",
            }
            for s in self._sessions
            for topic in s.topics
        ]
        temporal_patterns = self.temporal_pattern(timeline)

        insights = self.insight_generate()

        # Compute serendipity score: how many connections are surprising?
        total_connections = len(self._connections)
        surprising = sum(
            1 for c in self._connections if c.connection_type == "SERENDIPITOUS"
        )
        serendipity = surprising / max(total_connections, 1)

        # Recommendations
        recommendations: list[str] = []
        for insight in insights:
            if insight.actionable and insight.action:
                recommendations.append(insight.action)
        for tp in temporal_patterns:
            if tp.confidence > 0.6:
                recommendations.append(tp.recommendation)

        concept_summary = (
            f"{len(self._concept_index)} unique concepts tracked across "
            f"{len(self._sessions)} sessions."
        )

        return WeaveReport(
            generated_at=time.time(),
            total_sessions_analyzed=len(self._sessions),
            themes=themes,
            temporal_patterns=temporal_patterns,
            connections=list(self._connections),
            insights=insights,
            concept_graph_summary=concept_summary,
            recommendations=recommendations[:10],
            serendipity_score=round(serendipity, 3),
        )

    def add_session(self, session: SessionSummary) -> None:
        """Add a session to the weaver for future analysis.

        Args:
            session: A SessionSummary to index and track.
        """
        self._sessions.append(session)
        for concept in session.key_concepts:
            self._concept_index[concept.lower()].append(session.session_id)
        for topic in session.topics:
            self._concept_index[topic.lower()].append(session.session_id)

    # ── Internal helpers ────────────────────────────────────────────

    def _rebuild_concept_index(self) -> None:
        """Rebuild the concept-to-sessions index from all stored sessions."""
        self._concept_index.clear()
        for session in self._sessions:
            for concept in session.key_concepts:
                self._concept_index[concept.lower()].append(session.session_id)
            for topic in session.topics:
                self._concept_index[topic.lower()].append(session.session_id)

    def _classify_evolution(self, keyword: str, session_ids: list[str]) -> str:
        """Classify how a theme has evolved over time."""
        if len(session_ids) <= 2:
            return "STABLE"

        sessions_for_keyword = sorted(
            [s for s in self._sessions if s.session_id in session_ids],
            key=lambda s: s.timestamp,
        )

        if len(sessions_for_keyword) < 3:
            return "STABLE"

        # Check sentiment trend
        sentiments = [s.sentiment for s in sessions_for_keyword]
        if sentiments.count("negative") > sentiments.count("positive"):
            return "ESCALATING"

        if sentiments[-1] == "positive" and sentiments[0] == "negative":
            return "RESOLVED"

        # Check for cyclical: alternating positive/negative
        if len(sentiments) >= 4:
            alternations = sum(
                1
                for i in range(1, len(sentiments))
                if sentiments[i] != sentiments[i - 1] and sentiments[i] != "neutral"
            )
            if alternations >= 3:
                return "CYCLICAL"

        return "STABLE"

    def _merge_related_themes(self, themes: list[Theme]) -> list[Theme]:
        """Merge themes that share most of their sessions (likely same theme)."""
        if len(themes) < 2:
            return themes

        merged: list[Theme] = []
        used: set[int] = set()

        for i, t1 in enumerate(themes):
            if i in used:
                continue
            s1 = set(t1.sessions)

            for j, t2 in enumerate(themes):
                if j <= i or j in used:
                    continue
                s2 = set(t2.sessions)
                shared = s1 & s2
                if len(shared) >= len(s1) * 0.7 and len(shared) >= len(s2) * 0.7:
                    # Merge t2 into t1
                    s1 |= s2
                    t1.keywords.extend(t2.keywords)
                    t1.strength = max(t1.strength, t2.strength)
                    t1.last_seen = max(t1.last_seen, t2.last_seen)
                    t1.first_seen = min(t1.first_seen, t2.first_seen)
                    t1.name = f"{t1.name}+{t2.name}" if t1.name != t2.name else t1.name
                    used.add(j)

            t1.sessions = list(s1)
            t1.keywords = list(dict.fromkeys(t1.keywords))  # dedup
            merged.append(t1)
            used.add(i)

        return merged

    def _estimate_period(self, timestamps: list[float]) -> float:
        """Estimate the average period (in days) between timestamps."""
        if len(timestamps) < 2:
            return 0.0

        sorted_ts = sorted(timestamps)
        gaps = [
            (sorted_ts[i + 1] - sorted_ts[i]) / 86400.0
            for i in range(len(sorted_ts) - 1)
        ]

        return statistics.mean(gaps) if gaps else 0.0

    def _pattern_recommendation(self, pattern_type: str, context: str) -> str:
        """Generate a recommendation based on pattern type."""
        recs = {
            "RECURRENCE": f"'{context}' keeps recurring — automate the fix or address the root cause.",
            "ESCALATION": f"'{context}' is getting worse — immediate intervention recommended.",
            "CYCLICAL": f"'{context}' is cyclical — look for periodic triggers (scheduled jobs, releases, billing cycles).",
            "REGRESSION": f"'{context}' regressed — check recent changes for reintroduction of old issue.",
            "TREND": f"'{context}' shows a trend — extrapolate and act before it becomes critical.",
        }
        return recs.get(pattern_type, f"Investigate pattern: '{context}'.")

    def _graph_path(self, concept_a: str, concept_b: str, max_depth: int) -> list[str]:
        """Find a path in the memory graph between two concepts."""
        mg = self.memory_graph
        if mg is None:
            return []

        try:
            # Try BFS traversal via query_related
            visited: set[str] = set()
            queue = [(concept_a, [concept_a])]

            while queue:
                current, path = queue.pop(0)
                if len(path) > max_depth:
                    continue
                if current.lower() == concept_b.lower():
                    return path

                if current in visited:
                    continue
                visited.add(current)

                try:
                    related = mg.query_related(current, depth=1)
                    for r in related:
                        name = r.concept if hasattr(r, "concept") else str(r)
                        if name not in visited:
                            queue.append((name, path + [name]))
                except Exception:
                    pass  # query_related may not be available

        except Exception:
            pass

        return []

    def _build_connection(
        self, concept_a: str, concept_b: str, path: list[str], source: str
    ) -> ConceptConnection:
        """Build a ConceptConnection from a discovered path."""
        path_len = len(path) - 1  # edges
        strength = 1.0 / max(path_len, 1)

        if path_len == 1:
            conn_type = "SEMANTIC"
        elif path_len <= 3:
            conn_type = "STRUCTURAL"
        elif source == "memory_graph":
            conn_type = "TEMPORAL"
        else:
            conn_type = "SERENDIPITOUS"

        return ConceptConnection(
            concept_a=concept_a,
            concept_b=concept_b,
            connection_type=conn_type,
            shared_abstraction=f"Connected via {path_len} hop(s)",
            path=path,
            strength=round(strength, 3),
            evidence=f"Path found through {source}: {' → '.join(path)}",
        )

    def _find_related(self, concept: str) -> set[str]:
        """Find concepts related to the given concept by co-occurrence."""
        sessions = set(self._concept_index.get(concept.lower(), []))
        if not sessions:
            return set()

        related: set[str] = set()
        for kw, kw_sessions in self._concept_index.items():
            if kw == concept.lower():
                continue
            if sessions & set(kw_sessions):
                related.add(kw)

        return related


# Import statistics (needed at top but used in helper)
import statistics  # noqa: E402

# ── Self-test ────────────────────────────────────────────────────────────

def _self_test() -> None:
    """Verify ContextWeaver with synthetic session data."""
    now = time.time()
    day = 86400.0

    sessions = [
        SessionSummary(
            session_id="s1",
            timestamp=now - 10 * day,
            topics=["authentication", "login"],
            key_concepts=["oauth", "token_refresh", "session_mgmt"],
            outcomes=["implemented oauth"],
            tools_used=["curl", "jwt_tool"],
            errors_encountered=["token_expired", "invalid_grant"],
            sentiment="negative",
        ),
        SessionSummary(
            session_id="s2",
            timestamp=now - 7 * day,
            topics=["database", "performance"],
            key_concepts=["query_optimization", "indexing", "connection_pool"],
            outcomes=["reduced query time 80%"],
            tools_used=["pg_stat", "explain_analyze"],
            errors_encountered=["timeout"],
            sentiment="positive",
        ),
        SessionSummary(
            session_id="s3",
            timestamp=now - 4 * day,
            topics=["authentication", "security"],
            key_concepts=["oauth", "token_refresh", "rate_limiting"],
            outcomes=["fixed token refresh"],
            tools_used=["curl", "burp"],
            errors_encountered=["token_expired", "rate_limit_hit"],
            sentiment="positive",
        ),
        SessionSummary(
            session_id="s4",
            timestamp=now - 1 * day,
            topics=["database", "authentication"],
            key_concepts=["connection_pool", "session_mgmt", "query_optimization"],
            outcomes=["stabilized auth flow"],
            tools_used=["pg_stat", "jwt_tool"],
            errors_encountered=["timeout", "token_expired"],
            sentiment="negative",
        ),
    ]

    weaver = ContextWeaver(session_window_days=30)

    # Test threading
    themes = weaver.thread_sessions(sessions)
    assert len(themes) > 0, "Should find at least one theme"
    auth_themes = [t for t in themes if "auth" in t.name.lower() or "token" in t.name.lower()]
    assert len(auth_themes) > 0, "Should find authentication-related theme"

    # Test temporal pattern
    timeline = [
        {"timestamp": now - 5 * day, "event": "timeout_error", "type": "error"},
        {"timestamp": now - 4 * day, "event": "timeout_error", "type": "error"},
        {"timestamp": now - 3 * day, "event": "timeout_error", "type": "error"},
        {"timestamp": now - 2 * day, "event": "deploy_fix", "type": "deploy"},
        {"timestamp": now - 1 * day, "event": "timeout_error", "type": "error"},
    ]
    patterns = weaver.temporal_pattern(timeline)
    assert len(patterns) > 0

    # Test concept connection
    conn = weaver.connect_concepts("oauth", "token_refresh")
    assert conn is not None, "oauth and token_refresh should be connected"
    assert conn.strength > 0

    # Test insight generation
    insights = weaver.insight_generate()
    assert len(insights) > 0

    # Test relevance score
    score = weaver.relevance_score("oauth", "We need to fix the oauth login authentication flow")
    assert score > 0.5, f"oauth should be relevant to login authentication, got {score}"

    score2 = weaver.relevance_score("machine_learning", "We need to fix the login authentication flow")
    assert score2 < 0.5, "machine_learning should be less relevant"

    # Test weave report
    report = weaver.weave_report()
    assert report.total_sessions_analyzed == len(sessions)
    assert 0 <= report.serendipity_score <= 1

    # Test add_session
    new_session = SessionSummary(
        session_id="s5",
        timestamp=now,
        topics=["new_feature"],
        key_concepts=["api_design", "rate_limiting"],
        outcomes=["designed API"],
        tools_used=["curl"],
        errors_encountered=[],
        sentiment="positive",
    )
    weaver.add_session(new_session)
    assert len(weaver._sessions) == 5

    # Test edge: empty
    empty_weaver = ContextWeaver()
    empty_patterns = empty_weaver.temporal_pattern([])
    assert empty_patterns == []

    print("ContextWeaver: all self-tests passed ✓")


if __name__ == "__main__":
    _self_test()