"""
Knowledge graph memory — persistent concept graph with traversal and clustering.

DNA: Gemini Flash (fast triage) + Claude Opus (deep reasoning).

MemoryGraph stores concepts as nodes with properties, connects them via
typed edges, supports multi-hop traversal, cross-session link discovery,
concept clustering, and Graphviz DOT export for visualization.

Uses networkx if available; falls back to a pure-Python dict graph.

Usage::

    mg = MemoryGraph()
    mg.add_concept("neural_network", {"type": "algorithm", "complexity": "high"})
    mg.link_concepts("neural_network", "deep_learning", "is_subclass_of")
    related = mg.query_related("neural_network", depth=2)
    mg.export_graphviz("memory.dot")
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Optional networkx ───────────────────────────────────────────────────

_nx_available = False
_nx: Any = None
try:
    import networkx as _nx
    _nx_available = True
except ImportError:
    pass


# ── Data types ──────────────────────────────────────────────────────────

@dataclass
class Concept:
    """A node in the knowledge graph."""
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    session_id: str = ""
    embedding: Optional[list[float]] = None      # optional vector embedding
    node_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class Edge:
    """A directed, typed edge between two concepts."""
    source: str          # concept name
    target: str          # concept name
    relation: str        # e.g., "is_a", "depends_on", "similar_to"
    weight: float = 1.0
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class TraversalResult:
    """Result of a graph traversal query."""
    concept: str
    path: list[str]              # names along the path
    relations: list[str]         # relations along each edge
    depth: int
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ClusterInfo:
    """A detected cluster of related concepts."""
    cluster_id: int
    concepts: list[str]
    density: float               # internal edge density
    central_concept: str
    size: int


# ── Pure-Python graph backend ───────────────────────────────────────────

class _DictGraph:
    """Pure-Python adjacency-list graph — fallback when networkx is absent."""

    def __init__(self) -> None:
        self._nodes: dict[str, Concept] = {}
        self._adj: dict[str, dict[str, list[Edge]]] = defaultdict(lambda: defaultdict(list))
        # _adj[source][target] = [Edge, ...]

    def add_node(self, concept: Concept) -> None:
        self._nodes[concept.name] = concept
        if concept.name not in self._adj:
            self._adj[concept.name] = defaultdict(list)

    def has_node(self, name: str) -> bool:
        return name in self._nodes

    def add_edge(self, edge: Edge) -> None:
        self._adj[edge.source][edge.target].append(edge)
        # Ensure target exists in adj dict
        if edge.target not in self._adj:
            self._adj[edge.target] = defaultdict(list)

    def neighbors(self, name: str) -> list[str]:
        return list(self._adj.get(name, {}).keys())

    def get_edges(self, source: str, target: str) -> list[Edge]:
        return self._adj.get(source, {}).get(target, [])

    def all_edges(self) -> list[Edge]:
        edges: list[Edge] = []
        for src, targets in self._adj.items():
            for tgt, edge_list in targets.items():
                edges.extend(edge_list)
        return edges

    def nodes(self) -> list[str]:
        return list(self._nodes.keys())

    def node_count(self) -> int:
        return len(self._nodes)

    def edge_count(self) -> int:
        return sum(
            len(edges) for targets in self._adj.values() for edges in targets.values()
        )

    def get_node(self, name: str) -> Optional[Concept]:
        return self._nodes.get(name)


# ── MemoryGraph ─────────────────────────────────────────────────────────

class MemoryGraph:
    """Knowledge graph for persistent concept memory.

    Stores concepts, links them with typed relations, traverses the graph,
    discovers cross-session connections, clusters related concepts, and
    exports to Graphviz DOT format.
    """

    def __init__(
        self,
        storage_path: Optional[str | Path] = None,
        use_networkx: bool = True,
    ):
        self._storage_path = Path(storage_path) if storage_path else None
        self._use_nx = use_networkx and _nx_available

        if self._use_nx:
            self._nx_graph = _nx.DiGraph()
            self._nodes: dict[str, Concept] = {}
        else:
            self._graph = _DictGraph()
            self._nodes = {}

        self._edges: list[Edge] = []
        self._session_id = uuid.uuid4().hex[:8]
        self._cluster_counter = 0

        # Load persisted graph if available
        if self._storage_path and self._storage_path.exists():
            self._load()

    # ── Add / Link ─────────────────────────────────────────────────

    def add_concept(
        self, name: str, properties: Optional[dict[str, Any]] = None,
        embedding: Optional[list[float]] = None,
    ) -> Concept:
        """Add a concept node to the graph.

        Args:
            name: Unique concept name.
            properties: Optional key-value metadata.
            embedding: Optional vector embedding for similarity search.

        Returns:
            The created Concept.
        """
        concept = Concept(
            name=name,
            properties=properties or {},
            session_id=self._session_id,
            embedding=embedding,
        )
        self._nodes[name] = concept

        if self._use_nx:
            self._nx_graph.add_node(name, concept=concept)
        else:
            self._graph.add_node(concept)

        logger.debug("Added concept: %s", name)
        return concept

    def link_concepts(
        self, a: str, b: str, relation: str = "related_to",
        weight: float = 1.0, properties: Optional[dict[str, Any]] = None,
    ) -> Edge:
        """Create a typed edge between two concepts.

        Auto-creates nodes if they don't exist.

        Args:
            a: Source concept name.
            b: Target concept name.
            relation: The relationship type (e.g., "is_a", "depends_on").
            weight: Edge weight (1.0 default).
            properties: Optional edge metadata.

        Returns:
            The created Edge.
        """
        # Ensure nodes exist
        if a not in self._nodes:
            self.add_concept(a)
        if b not in self._nodes:
            self.add_concept(b)

        edge = Edge(
            source=a, target=b, relation=relation,
            weight=weight, properties=properties or {},
        )
        self._edges.append(edge)

        if self._use_nx:
            self._nx_graph.add_edge(a, b, edge=edge)
        else:
            self._graph.add_edge(edge)

        logger.debug("Linked: %s --[%s]--> %s", a, relation, b)
        return edge

    # ── Traversal / Query ──────────────────────────────────────────

    def query_related(self, concept: str, depth: int = 1) -> list[TraversalResult]:
        """Find concepts related to the given one up to N hops.

        BFS traversal through the graph.

        Args:
            concept: Starting concept name.
            depth: Maximum number of hops (≥1).

        Returns:
            List of TraversalResult objects, ordered by depth.
        """
        if concept not in self._nodes:
            return []

        results: list[TraversalResult] = []
        visited = {concept}
        queue: deque[tuple[str, list[str], list[str], int]] = deque()
        queue.append((concept, [], [], 0))

        while queue:
            current, path, rels, d = queue.popleft()
            if d > depth:
                continue

            if d > 0:
                results.append(TraversalResult(
                    concept=current,
                    path=path,
                    relations=rels,
                    depth=d,
                    properties=self._nodes.get(current, Concept(current)).properties,
                ))

            if d < depth:
                neighbors = self._get_neighbors(current)
                for neighbor in neighbors:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        edges = self._get_edges_between(current, neighbor)
                        edge_rel = edges[0].relation if edges else "unknown"
                        queue.append((
                            neighbor,
                            path + [neighbor],
                            rels + [edge_rel],
                            d + 1,
                        ))

        # Update access times
        for r in results:
            if r.concept in self._nodes:
                self._nodes[r.concept].last_accessed = time.time()

        return results

    def _get_neighbors(self, name: str) -> list[str]:
        """Get outgoing + incoming neighbor names."""
        if self._use_nx:
            return list(self._nx_graph.successors(name)) + list(self._nx_graph.predecessors(name))
        return self._graph.neighbors(name)

    def _get_edges_between(self, a: str, b: str) -> list[Edge]:
        """Get all edges between two nodes (either direction)."""
        edges: list[Edge] = []
        if self._use_nx:
            if self._nx_graph.has_edge(a, b):
                edges.append(self._nx_graph[a][b]["edge"])
            if self._nx_graph.has_edge(b, a):
                edges.append(self._nx_graph[b][a]["edge"])
        else:
            edges.extend(self._graph.get_edges(a, b))
            edges.extend(self._graph.get_edges(b, a))
        return edges

    # ── Cross-session linking ──────────────────────────────────────

    def cross_session_link(self, session_a: str, session_b: str) -> list[Edge]:
        """Find and create connections between concepts from two sessions.

        Links concepts that share keywords in their names or properties.

        Args:
            session_a: First session ID.
            session_b: Second session ID.

        Returns:
            List of newly created edges.
        """
        nodes_a = [
            n for n in self._nodes.values()
            if n.session_id == session_a or session_a in n.session_id
        ]
        nodes_b = [
            n for n in self._nodes.values()
            if n.session_id == session_b or session_b in n.session_id
        ]

        new_edges: list[Edge] = []
        for na in nodes_a:
            for nb in nodes_b:
                score = self._concept_similarity(na, nb)
                if score > 0.3:
                    edge = self.link_concepts(
                        na.name, nb.name,
                        relation="cross_session_link",
                        weight=score,
                        properties={"sessions": [session_a, session_b], "similarity": score},
                    )
                    new_edges.append(edge)

        return new_edges

    @staticmethod
    def _concept_similarity(a: Concept, b: Concept) -> float:
        """Compute similarity between two concepts (0–1)."""
        if a.name == b.name:
            return 1.0

        # Jaccard of name tokens
        tokens_a = set(a.name.lower().replace("_", " ").split())
        tokens_b = set(b.name.lower().replace("_", " ").split())
        if not tokens_a or not tokens_b:
            return 0.0
        name_sim = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)

        # Property overlap
        keys_a = set(a.properties.keys())
        keys_b = set(b.properties.keys())
        prop_sim = len(keys_a & keys_b) / max(1, len(keys_a | keys_b))

        # Cosine of embeddings if available
        embed_sim = 0.0
        if a.embedding and b.embedding and len(a.embedding) == len(b.embedding):
            dot = sum(x * y for x, y in zip(a.embedding, b.embedding))
            norm_a = math.sqrt(sum(x * x for x in a.embedding))
            norm_b = math.sqrt(sum(x * x for x in b.embedding))
            if norm_a > 0 and norm_b > 0:
                embed_sim = dot / (norm_a * norm_b)

        return 0.4 * name_sim + 0.3 * prop_sim + 0.3 * embed_sim

    # ── Clustering ─────────────────────────────────────────────────

    def concept_cluster(self, min_cluster_size: int = 2) -> list[ClusterInfo]:
        """Find clusters of related concepts using connected components.

        Args:
            min_cluster_size: Minimum number of concepts to form a cluster.

        Returns:
            List of ClusterInfo objects.
        """
        # Build undirected adjacency
        adj: dict[str, set[str]] = defaultdict(set)
        if self._use_nx:
            undirected = self._nx_graph.to_undirected()
            for comp in _nx.connected_components(undirected):
                component = list(comp)
                if len(component) >= min_cluster_size:
                    self._cluster_counter += 1
                    central = self._find_central(component)
                    density = self._compute_density(component)
                    adj.clear()
        else:
            # Build adjacency from edges
            for edge in self._edges:
                adj[edge.source].add(edge.target)
                adj[edge.target].add(edge.source)

            # DFS to find connected components
            visited: set[str] = set()
            components: list[list[str]] = []
            for node in self._nodes:
                if node not in visited:
                    stack = [node]
                    comp: list[str] = []
                    while stack:
                        n = stack.pop()
                        if n not in visited:
                            visited.add(n)
                            comp.append(n)
                            stack.extend(adj.get(n, set()) - visited)
                    if len(comp) >= min_cluster_size:
                        components.append(comp)

            clusters: list[ClusterInfo] = []
            for comp in components:
                if len(comp) >= min_cluster_size:
                    self._cluster_counter += 1
                    central = self._find_central(comp)
                    density = self._compute_density(comp)
                    clusters.append(ClusterInfo(
                        cluster_id=self._cluster_counter,
                        concepts=comp,
                        density=density,
                        central_concept=central,
                        size=len(comp),
                    ))
            return clusters

    def _find_central(self, component: list[str]) -> str:
        """Find the most connected node in a component (degree centrality)."""
        degrees: dict[str, int] = defaultdict(int)
        for edge in self._edges:
            if edge.source in component and edge.target in component:
                degrees[edge.source] += 1
                degrees[edge.target] += 1
        if not degrees:
            return component[0] if component else ""
        return max(degrees, key=degrees.get)

    def _compute_density(self, component: list[str]) -> float:
        """Compute internal edge density of a component."""
        comp_set = set(component)
        n = len(component)
        if n < 2:
            return 1.0
        internal_edges = sum(
            1 for e in self._edges
            if e.source in comp_set and e.target in comp_set
        )
        max_edges = n * (n - 1)  # directed
        return internal_edges / max_edges if max_edges > 0 else 0.0

    # ── Export ─────────────────────────────────────────────────────

    def export_graphviz(self, path: str | Path, max_nodes: int = 200) -> str:
        """Export the graph as a Graphviz DOT file for visualization.

        Args:
            path: Output file path (.dot extension recommended).
            max_nodes: Maximum nodes to include.

        Returns:
            The DOT content as a string.
        """
        all_nodes = list(self._nodes.keys())[:max_nodes]
        node_set = set(all_nodes)

        lines = ["digraph MemoryGraph {", "  rankdir=LR;", '  node [shape=box, style=filled, fillcolor="#f0f0f0"];']
        lines.append(f'  label="OmniCore Knowledge Graph ({len(all_nodes)} nodes)";')
        lines.append("  fontsize=20;")

        # Nodes
        for name in all_nodes:
            concept = self._nodes.get(name)
            label = name.replace("_", "\\n")
            if concept and concept.properties:
                label += f"\\n{json.dumps(concept.properties)[:60]}"
            lines.append(f'  "{name}" [label="{label}"];')

        # Edges
        edge_count = 0
        for edge in self._edges:
            if edge.source in node_set and edge.target in node_set:
                edge_count += 1
                lines.append(
                    f'  "{edge.source}" -> "{edge.target}" '
                    f'[label="{edge.relation}", weight={edge.weight}];'
                )
                if edge_count > 500:
                    break

        lines.append("}")
        dot_content = "\n".join(lines)

        # Write to file
        out_path = Path(path)
        out_path.write_text(dot_content, encoding="utf-8")
        logger.info("Exported graphviz to %s (%d nodes, %d edges)", out_path, len(all_nodes), edge_count)

        return dot_content

    # ── Persistence ────────────────────────────────────────────────

    def _load(self) -> None:
        """Load graph from JSON storage."""
        if not self._storage_path:
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            for nd in data.get("nodes", []):
                self.add_concept(
                    nd["name"],
                    properties=nd.get("properties", {}),
                    embedding=nd.get("embedding"),
                )
            for ed in data.get("edges", []):
                self.link_concepts(
                    ed["source"], ed["target"],
                    relation=ed.get("relation", "related_to"),
                    weight=ed.get("weight", 1.0),
                    properties=ed.get("properties", {}),
                )
            logger.info("Loaded %d nodes, %d edges from %s", len(data.get("nodes", [])), len(data.get("edges", [])), self._storage_path)
        except Exception as exc:
            logger.warning("Failed to load graph: %s", exc)

    def save(self, path: Optional[str | Path] = None) -> None:
        """Persist graph to JSON."""
        target = Path(path) if path else self._storage_path
        if not target:
            return
        data = {
            "nodes": [
                {
                    "name": c.name,
                    "properties": c.properties,
                    "embedding": c.embedding,
                    "session_id": c.session_id,
                    "node_id": c.node_id,
                }
                for c in self._nodes.values()
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "relation": e.relation,
                    "weight": e.weight,
                    "properties": e.properties,
                }
                for e in self._edges
            ],
        }
        target.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    # ── Properties ─────────────────────────────────────────────────

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    @property
    def stats(self) -> dict[str, Any]:
        """Quick stats summary."""
        clusters = self.concept_cluster(min_cluster_size=2)
        return {
            "nodes": self.node_count,
            "edges": self.edge_count,
            "clusters": len(clusters),
            "density": round(
                self.edge_count / max(1, self.node_count * (self.node_count - 1)), 4
            ),
            "avg_degree": round(self.edge_count / max(1, self.node_count), 2),
        }


# ── Self-test ───────────────────────────────────────────────────────────

def _self_test() -> None:
    """Verify MemoryGraph core operations."""
    import tempfile

    mg = MemoryGraph()

    # add_concept
    c1 = mg.add_concept("python", {"type": "language", "paradigm": "multi"})
    c2 = mg.add_concept("fastapi", {"type": "framework", "language": "python"})
    assert mg.node_count == 2
    print(f"  add_concept: {mg.node_count} nodes")

    # link_concepts
    e = mg.link_concepts("python", "fastapi", "has_framework", weight=0.9)
    assert mg.edge_count == 1
    print(f"  link_concepts: {mg.edge_count} edges, relation={e.relation}")

    # query_related
    related = mg.query_related("python", depth=2)
    assert len(related) > 0
    print(f"  query_related(depth=2): {len(related)} results, first={related[0].concept}")

    # cross_session_link
    mg.add_concept("react", {"type": "framework", "session": "b"})
    links = mg.cross_session_link(mg._session_id, "b")
    print(f"  cross_session_link: {len(links)} links created")

    # concept_cluster
    clusters = mg.concept_cluster(min_cluster_size=2)
    print(f"  concept_cluster: {len(clusters)} clusters")

    # export_graphviz
    dot_path = Path(tempfile.gettempdir()) / "test_memory_graph.dot"
    dot = mg.export_graphviz(dot_path, max_nodes=10)
    assert "digraph" in dot
    print(f"  export_graphviz: {len(dot)} chars of DOT")

    # stats
    print(f"  stats: {mg.stats}")

    print("  memory_graph: ALL TESTS PASSED")


if __name__ == "__main__":
    _self_test()