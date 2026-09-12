"""
Swarm intelligence — multi-agent coordination with multiprocessing.

DNA: Hydra (swarm) + Muse Spark (orchestration) + GPT-5.5 (structured merge).

The Swarm class spawns isolated agent nodes (each in its own process),
runs gossip-based broadcast, multi-agent proposal/debate, and merges
solutions into consensus.  Mesh health is continuously monitored.

Usage::

    swarm = Swarm(node_count=5, agent_factory=my_agent_builder)
    solutions = swarm.propose("Design a rate limiter")
    consensus = swarm.merge_solutions(solutions)
"""

from __future__ import annotations

import json
import logging
import multiprocessing as mp
import random
import signal
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from queue import Empty, Queue
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Sentinel to stop worker nodes
_STOP = "__SWARM_STOP__"


# ── Data types ──────────────────────────────────────────────────────────

@dataclass
class NodeInfo:
    """Metadata about a swarm node."""
    node_id: str
    pid: int
    status: str = "alive"            # alive | dead | busy
    last_heartbeat: float = 0.0
    tasks_completed: int = 0
    role: str = "worker"


@dataclass
class Proposal:
    """A solution proposal from a node."""
    node_id: str
    content: Any
    confidence: float = 0.0
    reasoning: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DebateRound:
    """One round of debate with votes."""
    topic: str
    proposals: list[Proposal] = field(default_factory=list)
    votes: dict[str, str] = field(default_factory=dict)  # node_id → voted_for
    winner: Optional[Proposal] = None


# ── Worker process ──────────────────────────────────────────────────────

def _node_worker(
    node_id: str,
    agent_factory_data: bytes,
    input_queue: mp.Queue,
    output_queue: mp.Queue,
    heartbeat_queue: mp.Queue,
) -> None:
    """Entry point for a swarm node subprocess.

    Deserializes the agent factory, then loops: receive task → execute → return result.
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    try:
        agent_fn = _deserialize_callable(agent_factory_data)
        agent = agent_fn(node_id)
    except Exception as exc:
        logger.error("Node %s: failed to initialise agent: %s", node_id, exc)
        agent = None

    last_beat = time.time()

    while True:
        # Heartbeat
        now = time.time()
        if now - last_beat > 5.0:
            try:
                heartbeat_queue.put_nowait({"node_id": node_id, "time": now, "status": "alive"})
                last_beat = now
            except Exception:
                pass

        # Process input
        try:
            msg = input_queue.get(timeout=1.0)
        except Empty:
            continue

        if msg == _STOP:
            break

        task = msg.get("task", "")
        task_type = msg.get("type", "execute")
        task_id = msg.get("task_id", str(uuid.uuid4()))

        try:
            if task_type == "broadcast":
                result = {"node_id": node_id, "ack": True, "message": task}
            elif task_type == "propose":
                result = _run_proposal(agent, node_id, task)
            elif task_type == "debate":
                result = _run_debate(agent, node_id, task)
            elif task_type == "health":
                result = {"node_id": node_id, "status": "alive", "pid": mp.current_process().pid}
            elif agent is not None and hasattr(agent, "execute"):
                result = agent.execute(task)
            else:
                result = {"node_id": node_id, "result": f"Received: {task}", "confidence": 0.5}
        except Exception as exc:
            result = {
                "node_id": node_id,
                "error": str(exc),
                "confidence": 0.0,
            }

        result["task_id"] = task_id
        try:
            output_queue.put_nowait(result)
        except Exception:
            pass

    logger.debug("Node %s shutting down", node_id)


def _run_proposal(agent: Any, node_id: str, task: str) -> dict[str, Any]:
    """Have a node agent propose a solution."""
    if agent is not None and hasattr(agent, "propose"):
        return agent.propose(task)
    # Fallback: basic proposal
    return {
        "node_id": node_id,
        "solution": f"Node {node_id} proposes: approach via {_random_approach()}",
        "confidence": random.uniform(0.5, 0.95),
        "reasoning": "Heuristic-based fallback proposal",
    }


def _run_debate(agent: Any, node_id: str, topic: str) -> dict[str, Any]:
    """Have a node agent participate in a debate."""
    if agent is not None and hasattr(agent, "debate"):
        return agent.debate(topic)
    return {
        "node_id": node_id,
        "argument": f"Node {node_id} argues: {_random_stance()}",
        "vote_for": node_id,  # default: vote for self
    }


def _random_approach() -> str:
    return random.choice([
        "divide-and-conquer decomposition",
        "iterative refinement",
        "constraint satisfaction",
        "heuristic search",
        "neural/symbolic hybrid",
        "ensemble of weak methods",
    ])


def _random_stance() -> str:
    return random.choice([
        "The most efficient path is incremental delivery",
        "We should optimize for correctness first, speed second",
        "Simplicity is the highest priority",
        "A composable pipeline is the right architecture",
    ])


def _serialize_callable(fn: Callable) -> bytes:
    """Serialize a callable for cross-process transport (pickle)."""
    import pickle
    return pickle.dumps(fn)


def _deserialize_callable(data: bytes) -> Callable:
    import pickle
    return pickle.loads(data)


# ── Swarm class ─────────────────────────────────────────────────────────

class Swarm:
    """Multi-agent swarm with gossip protocol and consensus merging.

    Spawns isolated worker processes and coordinates them through
    propose → debate → merge cycles.
    """

    def __init__(
        self,
        node_count: int = 5,
        agent_factory: Optional[Callable[[str], Any]] = None,
        method: str = "spawn",
    ):
        self._node_count = max(1, node_count)
        self._method = method
        self._nodes: dict[str, NodeInfo] = {}
        self._processes: dict[str, mp.Process] = {}
        self._input_queues: dict[str, mp.Queue] = {}
        self._output_queues: dict[str, mp.Queue] = {}
        self._heartbeat_queue: mp.Queue = mp.Queue()
        self._lock = threading.Lock()
        self._running = False

        # Agent factory
        if agent_factory is None:
            agent_factory = _default_agent_factory
        self._agent_factory = agent_factory
        self._serialized_factory = _serialize_callable(agent_factory)

        # Health monitor thread
        self._health_thread: Optional[threading.Thread] = None

    # ── Node management ────────────────────────────────────────────

    def create_node(self, node_id: Optional[str] = None) -> NodeInfo:
        """Spawn a new agent node in its own process.

        Args:
            node_id: Optional identifier. Auto-generated if omitted.

        Returns:
            NodeInfo for the created node.
        """
        if node_id is None:
            node_id = f"node-{uuid.uuid4().hex[:8]}"

        with self._lock:
            if node_id in self._nodes:
                raise ValueError(f"Node {node_id} already exists")

            input_q: mp.Queue = mp.Queue()
            output_q: mp.Queue = mp.Queue()

            ctx = mp.get_context(self._method)
            proc = ctx.Process(
                target=_node_worker,
                args=(node_id, self._serialized_factory, input_q, output_q, self._heartbeat_queue),
                name=f"swarm-{node_id}",
                daemon=True,
            )
            proc.start()

            info = NodeInfo(
                node_id=node_id,
                pid=proc.pid or 0,
                status="alive",
                last_heartbeat=time.time(),
            )

            self._nodes[node_id] = info
            self._processes[node_id] = proc
            self._input_queues[node_id] = input_q
            self._output_queues[node_id] = output_q

        logger.info("Created node %s (pid=%d)", node_id, proc.pid)
        return info

    def _ensure_nodes(self) -> None:
        """Create nodes if none exist yet."""
        if not self._nodes:
            for i in range(self._node_count):
                self.create_node(f"node-{i:04d}")

    # ── Broadcast ──────────────────────────────────────────────────

    def broadcast(self, message: str) -> dict[str, Any]:
        """Send a message to all nodes via gossip protocol and collect acks.

        Args:
            message: The message to broadcast.

        Returns:
            Dict mapping node_id → acknowledgment.
        """
        self._ensure_nodes()
        task_id = str(uuid.uuid4())

        for node_id in list(self._nodes.keys()):
            try:
                self._input_queues[node_id].put_nowait({
                    "task": message,
                    "type": "broadcast",
                    "task_id": task_id,
                })
            except Exception:
                pass

        # Collect acknowledgments
        acks: dict[str, Any] = {}
        deadline = time.time() + 5.0
        while time.time() < deadline and len(acks) < len(self._nodes):
            for node_id in list(self._nodes.keys()):
                if node_id in acks:
                    continue
                try:
                    result = self._output_queues[node_id].get(timeout=0.5)
                    if result.get("task_id") == task_id:
                        acks[node_id] = result
                except Empty:
                    pass

        return acks

    # ── Propose ────────────────────────────────────────────────────

    def propose(self, task: str) -> list[Proposal]:
        """Have N nodes propose solutions to a task.

        Args:
            task: The task description for nodes to solve.

        Returns:
            List of Proposal objects, one from each responding node.
        """
        self._ensure_nodes()
        task_id = str(uuid.uuid4())

        for node_id in list(self._nodes.keys()):
            try:
                self._input_queues[node_id].put_nowait({
                    "task": task,
                    "type": "propose",
                    "task_id": task_id,
                })
            except Exception:
                pass

        proposals = self._collect_results(task_id, timeout=30.0)
        return [
            Proposal(
                node_id=r["node_id"],
                content=r.get("solution", r.get("result")),
                confidence=r.get("confidence", 0.5),
                reasoning=r.get("reasoning", ""),
                metadata=r,
            )
            for r in proposals
            if "error" not in r
        ]

    # ── Debate ─────────────────────────────────────────────────────

    def debate(self, topic: str, rounds: int = 1) -> list[DebateRound]:
        """Run multi-agent debate with voting.

        Each round: nodes submit arguments, then vote on the best.

        Args:
            topic: The debate topic.
            rounds: Number of debate rounds.

        Returns:
            List of DebateRound results.
        """
        self._ensure_nodes()
        history: list[DebateRound] = []

        for rnd in range(rounds):
            task_id = str(uuid.uuid4())
            for node_id in list(self._nodes.keys()):
                try:
                    self._input_queues[node_id].put_nowait({
                        "task": topic,
                        "type": "debate",
                        "task_id": task_id,
                    })
                except Exception:
                    pass

            results = self._collect_results(task_id, timeout=15.0)
            dr = DebateRound(topic=topic)

            for r in results:
                if "error" in r:
                    continue
                dr.proposals.append(Proposal(
                    node_id=r["node_id"],
                    content=r.get("argument", ""),
                    confidence=r.get("confidence", 0.5),
                ))
                vote = r.get("vote_for", r["node_id"])
                dr.votes[r["node_id"]] = vote

            # Determine winner by vote count
            if dr.votes:
                tally = Counter(dr.votes.values())
                winner_id = tally.most_common(1)[0][0]
                for p in dr.proposals:
                    if p.node_id == winner_id:
                        dr.winner = p
                        break
                # Also inject winning argument into nodes for next round context
                topic = f"{topic}\nWinning argument: {dr.winner.content if dr.winner else 'none'}"

            history.append(dr)

        return history

    # ── Merge ──────────────────────────────────────────────────────

    def merge_solutions(self, solutions: list[Proposal]) -> dict[str, Any]:
        """Merge N proposals into a consensus solution.

        Uses weighted voting based on confidence scores and deduplication
        of overlapping content.

        Args:
            solutions: List of proposals to merge.

        Returns:
            Merged consensus dict with 'solution', 'confidence', 'contributors'.
        """
        if not solutions:
            return {"solution": None, "confidence": 0.0, "contributors": []}

        if len(solutions) == 1:
            s = solutions[0]
            return {
                "solution": s.content,
                "confidence": s.confidence,
                "contributors": [s.node_id],
                "reasoning": s.reasoning,
            }

        # Weighted merge: group similar proposals
        clusters = self._cluster_proposals(solutions)

        # Select best cluster by aggregate confidence
        best_cluster = max(clusters, key=lambda c: sum(s.confidence for s in c))

        # Merge content from best cluster
        merged_content = self._synthesize_merge([s.content for s in best_cluster])
        avg_confidence = sum(s.confidence for s in best_cluster) / len(best_cluster)

        return {
            "solution": merged_content,
            "confidence": avg_confidence,
            "contributors": [s.node_id for s in best_cluster],
            "all_proposals": [s.content for s in solutions],
            "reasoning": "\n".join(s.reasoning for s in best_cluster if s.reasoning),
        }

    @staticmethod
    def _cluster_proposals(proposals: list[Proposal]) -> list[list[Proposal]]:
        """Rough cluster proposals by content overlap."""
        clusters: list[list[Proposal]] = []
        for p in proposals:
            placed = False
            for cluster in clusters:
                rep = cluster[0]
                if Swarm._content_similarity(p.content, rep.content) > 0.3:
                    cluster.append(p)
                    placed = True
                    break
            if not placed:
                clusters.append([p])
        return clusters

    @staticmethod
    def _content_similarity(a: Any, b: Any) -> float:
        """Simple Jaccard-like similarity for content strings."""
        sa = set(str(a).lower().split())
        sb = set(str(b).lower().split())
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    @staticmethod
    def _synthesize_merge(contents: list[Any]) -> str:
        """Combine multiple solution texts into one."""
        if not contents:
            return ""
        if len(contents) == 1:
            return str(contents[0])
        # Merge by taking the longest as base and appending unique points
        contents_str = [str(c) for c in contents]
        base = max(contents_str, key=len)
        extras = []
        base_words = set(base.lower().split())
        for c in contents_str:
            if c == base:
                continue
            c_words = set(c.lower().split())
            unique = c_words - base_words
            if unique:
                extras.append(f"Additionally: {', '.join(sorted(unique)[:5])}")
        if extras:
            return base + "\n\n" + "\n".join(extras)
        return base

    # ── Health ─────────────────────────────────────────────────────

    def mesh_health(self) -> dict[str, NodeInfo]:
        """Check all nodes' health status.

        Returns:
            Dict mapping node_id → NodeInfo with current status.
        """
        # Process heartbeat queue
        while True:
            try:
                beat = self._heartbeat_queue.get_nowait()
                nid = beat["node_id"]
                if nid in self._nodes:
                    self._nodes[nid].last_heartbeat = beat["time"]
                    self._nodes[nid].status = beat.get("status", "alive")
            except Empty:
                break

        # Mark dead nodes
        now = time.time()
        for nid, info in self._nodes.items():
            if now - info.last_heartbeat > 30.0:
                info.status = "dead"
            # Also check process aliveness
            proc = self._processes.get(nid)
            if proc and not proc.is_alive():
                info.status = "dead"

        return dict(self._nodes)

    def _collect_results(self, task_id: str, timeout: float) -> list[dict[str, Any]]:
        """Gather results from output queues for a given task_id."""
        results: list[dict[str, Any]] = []
        deadline = time.time() + timeout
        while time.time() < deadline and len(results) < len(self._nodes):
            for node_id in list(self._nodes.keys()):
                if any(r.get("node_id") == node_id for r in results):
                    continue
                try:
                    result = self._output_queues[node_id].get(timeout=0.3)
                    if result.get("task_id") == task_id:
                        results.append(result)
                except Empty:
                    pass
        return results

    # ── Lifecycle ──────────────────────────────────────────────────

    def start_health_monitor(self, interval: float = 10.0) -> None:
        """Begin periodic health checks in a background thread."""

        def _monitor() -> None:
            while self._running:
                self.mesh_health()
                time.sleep(interval)

        self._running = True
        self._health_thread = threading.Thread(target=_monitor, daemon=True)
        self._health_thread.start()

    def shutdown(self) -> None:
        """Stop all nodes and clean up."""
        self._running = False

        # Send stop signal
        for node_id, q in self._input_queues.items():
            try:
                q.put_nowait(_STOP)
            except Exception:
                pass

        # Join processes
        for node_id, proc in self._processes.items():
            proc.join(timeout=5.0)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=2.0)

        self._nodes.clear()
        self._processes.clear()
        self._input_queues.clear()
        self._output_queues.clear()

    def __enter__(self) -> "Swarm":
        return self

    def __exit__(self, *_: Any) -> None:
        self.shutdown()


# ── Default swarm agent ─────────────────────────────────────────────────

def _default_agent_factory(node_id: str) -> _SwarmAgent:
    """Module-level factory — must be picklable for multiprocessing."""
    return _SwarmAgent(node_id)


class _SwarmAgent:
    """Minimal agent used when no agent_factory is provided."""

    def __init__(self, node_id: str):
        self.node_id = node_id

    def propose(self, task: str) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "solution": f"Agent {self.node_id}: {task} → {_random_approach()}",
            "confidence": random.uniform(0.6, 0.9),
            "reasoning": f"Heuristic from {self.node_id}",
        }

    def debate(self, topic: str) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "argument": f"Agent {self.node_id} argues: {_random_stance()}",
            "vote_for": self.node_id,
        }

    def execute(self, task: str) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "result": f"Executed: {task}",
            "confidence": 0.7,
        }


# ── Self-test ───────────────────────────────────────────────────────────

def _self_test() -> None:
    """Verify Swarm core operations."""
    print("  swarm: Starting tests (may take a few seconds)...")

    with Swarm(node_count=3) as swarm:
        swarm._ensure_nodes()  # pre-create nodes
        assert len(swarm._nodes) == 3, "Should have 3 nodes"

        # broadcast
        acks = swarm.broadcast("hello swarm")
        print(f"  broadcast: {len(acks)} acks received")

        # propose
        proposals = swarm.propose("Sort a list efficiently")
        assert len(proposals) > 0, "Should get proposals"
        print(f"  propose: {len(proposals)} proposals")

        # merge
        merged = swarm.merge_solutions(proposals)
        assert merged["solution"] is not None
        print(f"  merge: confidence={merged['confidence']:.2f}")

        # health
        health = swarm.mesh_health()
        assert len(health) == 3
        print(f"  mesh_health: {sum(1 for n in health.values() if n.status == 'alive')} alive")

    print("  swarm: ALL TESTS PASSED")


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    _self_test()