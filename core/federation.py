"""Cross-instance federation — peer discovery, knowledge sync, Raft-like consensus.

DNA: Swarm intelligence + distributed consensus. Enables multiple OmniCore
instances to discover each other, share knowledge graphs, and achieve
consensus on shared state.

Uses httpx for HTTP-based sync between instances.
"""

import hashlib
import json
import socket
import struct
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import urljoin


try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]


# ── Data structures ────────────────────────────────────────────────────

@dataclass
class NodeInfo:
    """Information about a federation peer node."""
    node_id: str
    host: str
    port: int = 9090
    version: str = "3.0.0"
    capabilities: list[str] = field(default_factory=list)
    last_seen: float = 0.0
    is_leader: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Proposal:
    """A consensus proposal."""
    proposal_id: str
    term: int = 0
    value: Any = None
    votes: dict[str, bool] = field(default_factory=dict)  # node_id → vote


@dataclass
class SyncResult:
    """Result of a knowledge sync operation."""
    peer_url: str
    pulled_count: int = 0
    pushed_count: int = 0
    conflicts: int = 0
    duration_ms: float = 0.0
    success: bool = True
    error: str = ""


# ── Federation class ───────────────────────────────────────────────────

class Federation:
    """Cross-instance federation manager.

    Handles peer discovery, knowledge graph sync, gossip protocol,
    and Raft-like consensus resolution.

    Usage:
        fed = Federation(node_id="node-1", port=9090)
        fed.announce({"host": "10.0.0.1", "capabilities": ["search", "code"]})
        result = fed.sync_knowledge("http://peer:9090")
        fed.gossip({"type": "alert", "message": "cluster rebalancing"})
    """

    def __init__(self, node_id: str = "", port: int = 9090):
        """Initialize federation.

        Args:
            node_id: Unique identifier for this node (auto-generated if empty).
            port: Port for federation HTTP endpoint.
        """
        self.node_id = node_id or _generate_node_id()
        self.port = port
        self._peers: dict[str, NodeInfo] = {}
        self._knowledge: dict[str, Any] = {}
        self._term: int = 0
        self._leader_id: str = ""
        self._http_client: Any = None
        if httpx:
            self._http_client = httpx.Client(timeout=10.0)

    # ── Peer Discovery ─────────────────────────────────────────────────

    def peer_discovery(self, multicast_group: str = "224.0.0.251",
                       discovery_port: int = 9091,
                       timeout: float = 3.0) -> list[NodeInfo]:
        """Auto-discover peers on local network via UDP multicast.

        Sends a discovery probe and collects responses from peers.

        Args:
            multicast_group: Multicast address (default: mDNS-like).
            discovery_port: Port for discovery messages.
            timeout: How long to wait for responses.

        Returns:
            List of discovered NodeInfo objects.
        """
        discovered: list[NodeInfo] = []
        sock = None

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(timeout)

            # Bind to listen for responses
            sock.bind(("0.0.0.0", discovery_port))

            # Send discovery probe
            probe = json.dumps({
                "type": "discovery",
                "node_id": self.node_id,
                "port": self.port,
                "version": "3.0.0",
                "timestamp": time.time(),
            }).encode()
            sock.sendto(probe, (multicast_group, discovery_port))

            # Collect responses
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        break
                    sock.settimeout(remaining)
                    data, addr = sock.recvfrom(4096)
                    info = json.loads(data)
                    if info.get("node_id") != self.node_id:
                        node = NodeInfo(
                            node_id=info.get("node_id", "unknown"),
                            host=addr[0],
                            port=info.get("port", 9090),
                            version=info.get("version", "3.0.0"),
                            last_seen=time.time(),
                        )
                        discovered.append(node)
                        self._peers[node.node_id] = node
                except socket.timeout:
                    break
        except OSError as e:
            # Multicast may not be supported on all networks
            pass
        finally:
            if sock:
                sock.close()

        return discovered

    # ── Announce ───────────────────────────────────────────────────────

    def announce(self, node_info: dict[str, Any]) -> dict[str, Any]:
        """Broadcast presence to all known peers.

        Sends an HTTP POST to /federation/announce on each peer.

        Args:
            node_info: Dictionary with host, port, capabilities, metadata.

        Returns:
            Dict with accepted and rejected counts.
        """
        if not self._http_client:
            return {"accepted": 0, "rejected": 0, "error": "httpx not installed"}

        info = {
            "node_id": self.node_id,
            "host": node_info.get("host", ""),
            "port": self.port,
            "version": "3.0.0",
            "capabilities": node_info.get("capabilities", []),
            "metadata": node_info.get("metadata", {}),
            "timestamp": time.time(),
        }

        accepted = 0
        rejected = 0
        for peer in list(self._peers.values()):
            try:
                url = f"http://{peer.host}:{peer.port}/federation/announce"
                resp = self._http_client.post(url, json=info, timeout=5.0)
                if resp.status_code == 200:
                    accepted += 1
                    peer.last_seen = time.time()
                else:
                    rejected += 1
            except Exception:
                rejected += 1

        return {"accepted": accepted, "rejected": rejected}

    # ── Knowledge Sync ─────────────────────────────────────────────────

    def sync_knowledge(self, peer_url: str) -> SyncResult:
        """Pull and push knowledge graph with a peer.

        Two-way sync: pull peer's knowledge, push our knowledge.

        Args:
            peer_url: Base URL of the peer (e.g., "http://10.0.0.2:9090").

        Returns:
            SyncResult with pull/push counts and conflicts.
        """
        start = time.perf_counter()
        result = SyncResult(peer_url=peer_url)

        if not self._http_client:
            result.success = False
            result.error = "httpx not installed"
            return result

        try:
            # Pull: GET peer's knowledge
            pull_url = urljoin(peer_url, "/federation/knowledge")
            resp = self._http_client.get(pull_url, timeout=10.0)

            if resp.status_code == 200:
                peer_knowledge = resp.json()
                for key, value in peer_knowledge.items():
                    if key in self._knowledge and self._knowledge[key] != value:
                        merged = self.conflict_resolution(self._knowledge[key], value)
                        self._knowledge[key] = merged
                        result.conflicts += 1
                    elif key not in self._knowledge:
                        self._knowledge[key] = value
                        result.pulled_count += 1

            # Push: POST our knowledge
            push_url = urljoin(peer_url, "/federation/knowledge")
            push_resp = self._http_client.post(
                push_url,
                json=self._knowledge,
                timeout=10.0,
            )
            if push_resp.status_code == 200:
                push_result = push_resp.json()
                result.pushed_count = push_result.get("accepted", 0)

            result.success = True
        except Exception as e:
            result.success = False
            result.error = str(e)

        result.duration_ms = (time.perf_counter() - start) * 1000
        return result

    def get_knowledge(self) -> dict[str, Any]:
        """Return the local knowledge graph."""
        return dict(self._knowledge)

    def set_knowledge(self, key: str, value: Any) -> None:
        """Set a knowledge entry."""
        self._knowledge[key] = value

    def delete_knowledge(self, key: str) -> bool:
        """Delete a knowledge entry. Returns True if key existed."""
        return self._knowledge.pop(key, None) is not None

    # ── Gossip Protocol ─────────────────────────────────────────────────

    def gossip(self, message: dict[str, Any],
               target_peers: Optional[list[str]] = None) -> dict[str, int]:
        """Propagate a message to all connected peers (or specific targets).

        Epidemic/gossip protocol: each peer forwards to N random peers.

        Args:
            message: Dictionary payload to propagate.
            target_peers: Optional list of specific node IDs to send to.
                          If None, sends to all known peers.

        Returns:
            Dict with 'sent' and 'failed' counts.
        """
        if not self._http_client:
            return {"sent": 0, "failed": 0, "error": "httpx not installed"}

        payload = {
            "type": "gossip",
            "origin": self.node_id,
            "message": message,
            "timestamp": time.time(),
            "ttl": 5,  # Hop limit
        }

        if target_peers:
            targets = [
                self._peers[nid] for nid in target_peers
                if nid in self._peers
            ]
        else:
            # Send to all known peers
            targets = list(self._peers.values())

        sent = 0
        failed = 0
        for peer in targets:
            try:
                url = f"http://{peer.host}:{peer.port}/federation/gossip"
                resp = self._http_client.post(url, json=payload, timeout=5.0)
                if resp.status_code == 200:
                    sent += 1
                else:
                    failed += 1
            except Exception:
                failed += 1

        return {"sent": sent, "failed": failed}

    def handle_gossip(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle incoming gossip message. Forward if TTL > 0."""
        ttl = payload.get("ttl", 0) - 1
        if ttl > 0:
            payload["ttl"] = ttl
            self.gossip(payload["message"])
        return {"received": True, "forwarded": ttl > 0}

    # ── Consensus (Raft-like) ──────────────────────────────────────────

    def consensus_resolve(self, proposals: list[dict[str, Any]]) -> dict[str, Any]:
        """Resolve multiple proposals using Raft-like consensus.

        Simple majority-wins consensus. Each proposal is voted on by
        known peers.

        Args:
            proposals: List of proposals, each with at least 'id' and 'value'.

        Returns:
            Dict with winning proposal, vote counts, and term.
        """
        self._term += 1
        term = self._term

        if not proposals:
            return {"winner": None, "term": term, "votes": {}, "status": "no_proposals"}

        # If only one proposal, auto-win
        if len(proposals) == 1:
            prop = proposals[0]
            return {
                "winner": prop.get("value"),
                "proposal_id": prop.get("id", "single"),
                "term": term,
                "votes": {self.node_id: True},
                "status": "unanimous",
            }

        # Collect votes from peers (simulated — in production this contacts peers)
        voted: dict[str, str] = {}  # node_id → proposal_id
        for i, prop in enumerate(proposals):
            prop_id = prop.get("id", f"prop-{i}")
            voted[self.node_id] = prop_id  # Self-vote for first proposal initially

        # Use peer votes if available (add our self-vote for each peer)
        peer_votes = {}
        if self._http_client:
            for peer in list(self._peers.values()):
                try:
                    url = f"http://{peer.host}:{peer.port}/federation/vote"
                    resp = self._http_client.post(
                        url,
                        json={"proposals": proposals, "term": term},
                        timeout=3.0,
                    )
                    if resp.status_code == 200:
                        vote_data = resp.json()
                        peer_votes[peer.node_id] = vote_data.get("vote", "")
                except Exception:
                    pass

        # Count votes
        vote_count: dict[str, int] = {}
        for pid in peer_votes.values():
            if pid:
                vote_count[pid] = vote_count.get(pid, 0) + 1

        # Self-vote for best proposal (hash-based deterministic)
        if not vote_count:
            # No peer votes — pick by proposal hash (deterministic tiebreaker)
            best_idx = 0
            best_hash = ""
            for i, prop in enumerate(proposals):
                h = hashlib.sha256(
                    json.dumps(prop, sort_keys=True).encode()
                ).hexdigest()
                if h > best_hash:
                    best_hash = h
                    best_idx = i
            winner = proposals[best_idx]
            return {
                "winner": winner.get("value"),
                "proposal_id": winner.get("id", f"prop-{best_idx}"),
                "term": term,
                "votes": {self.node_id: winner.get("id", "")},
                "status": "local_consensus",
            }

        # Find majority winner
        total_votes = len(vote_count) + 1  # +1 for self
        majority = total_votes // 2 + 1

        for pid, count in vote_count.items():
            if count >= majority:
                winning_prop = next(
                    (p for p in proposals if p.get("id") == pid), None
                )
                if winning_prop:
                    return {
                        "winner": winning_prop.get("value"),
                        "proposal_id": pid,
                        "term": term,
                        "votes": vote_count,
                        "status": "majority",
                    }

        # No majority — return plurality winner with status
        best_pid = max(vote_count, key=vote_count.get)
        winning_prop = next(
            (p for p in proposals if p.get("id") == best_pid), proposals[0]
        )
        return {
            "winner": winning_prop.get("value"),
            "proposal_id": best_pid,
            "term": term,
            "votes": vote_count,
            "status": "plurality",
        }

    # ── Conflict Resolution ────────────────────────────────────────────

    def conflict_resolution(self, local: Any, remote: Any) -> Any:
        """Merge conflicting data between local and remote values.

        Strategy:
        - Dicts: deep-merge with remote winning on key conflicts.
        - Lists: concatenate with deduplication.
        - Scalars: LWW (Last-Writer-Wins) — remote wins.
        - Strings: take the longer one (more data is better).

        Args:
            local: Local value.
            remote: Remote value from peer.

        Returns:
            Merged value.
        """
        if local is None:
            return remote
        if remote is None:
            return local

        # Both dicts: deep merge
        if isinstance(local, dict) and isinstance(remote, dict):
            merged = dict(local)
            for key, value in remote.items():
                if key in merged:
                    merged[key] = self.conflict_resolution(merged[key], value)
                else:
                    merged[key] = value
            return merged

        # Both lists: concat + dedup
        if isinstance(local, list) and isinstance(remote, list):
            seen: set[str] = set()
            result = []
            for item in local + remote:
                # Use JSON repr for dedup of complex items
                key = json.dumps(item, sort_keys=True, default=str)
                if key not in seen:
                    seen.add(key)
                    result.append(item)
            return result

        # Both strings: take longer (more information)
        if isinstance(local, str) and isinstance(remote, str):
            return remote if len(remote) >= len(local) else local

        # Both numeric: max
        if isinstance(local, (int, float)) and isinstance(remote, (int, float)):
            return remote if remote >= local else local

        # Type mismatch or other: remote wins (last-writer-wins)
        return remote

    # ── Peer management ────────────────────────────────────────────────

    def get_peers(self) -> list[NodeInfo]:
        """Return list of all known peers."""
        return list(self._peers.values())

    def add_peer(self, host: str, port: int = 9090,
                 node_id: str = "") -> NodeInfo:
        """Manually add a peer."""
        nid = node_id or _generate_node_id()
        node = NodeInfo(
            node_id=nid,
            host=host,
            port=port,
            last_seen=time.time(),
        )
        self._peers[nid] = node
        return node

    def remove_peer(self, node_id: str) -> bool:
        """Remove a peer. Returns True if it was removed."""
        return self._peers.pop(node_id, None) is not None

    def health_check(self) -> dict[str, Any]:
        """Return federation health status."""
        online = 0
        for peer in list(self._peers.values()):
            try:
                if self._http_client:
                    url = f"http://{peer.host}:{peer.port}/federation/ping"
                    resp = self._http_client.get(url, timeout=2.0)
                    if resp.status_code == 200:
                        online += 1
                        peer.last_seen = time.time()
            except Exception:
                pass

        return {
            "node_id": self.node_id,
            "peers_total": len(self._peers),
            "peers_online": online,
            "knowledge_entries": len(self._knowledge),
            "term": self._term,
            "is_leader": self._leader_id == self.node_id,
        }


# ── Helpers ────────────────────────────────────────────────────────────

def _generate_node_id() -> str:
    """Generate a unique node ID."""
    raw = f"{socket.gethostname()}-{time.time()}-{os.urandom(4).hex()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


import os  # noqa: E402 — needed in _generate_node_id


# ── Self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Federation Self-Test ===\n")

    fed = Federation(node_id="test-node-1", port=9090)

    # Test add_peer
    peer = fed.add_peer("127.0.0.1", 9091, "peer-1")
    print(f"✓ add_peer: {peer.node_id} @ {peer.host}:{peer.port}")

    # Test conflict_resolution
    print("\n--- conflict_resolution ---")
    # Dict merge
    local = {"a": 1, "b": {"x": 1}}
    remote = {"b": {"y": 2}, "c": 3}
    merged = fed.conflict_resolution(local, remote)
    assert merged == {"a": 1, "b": {"x": 1, "y": 2}, "c": 3}, f"Dict merge failed: {merged}"
    print(f"  ✓ dict merge: {merged}")

    # List merge
    l = [1, 2, 3]
    r = [3, 4, 5]
    merged_list = fed.conflict_resolution(l, r)
    assert merged_list == [1, 2, 3, 4, 5], f"List merge failed: {merged_list}"
    print(f"  ✓ list merge: {merged_list}")

    # String LWW
    assert fed.conflict_resolution("short", "longer string") == "longer string"
    print("  ✓ string LWW: longer wins")

    # Numeric
    assert fed.conflict_resolution(5, 10) == 10
    print("  ✓ numeric: larger wins")

    # Test consensus
    print("\n--- consensus_resolve ---")
    proposals = [
        {"id": "prop-1", "value": "option_a"},
        {"id": "prop-2", "value": "option_b"},
        {"id": "prop-3", "value": "option_a"},  # ties with prop-1
    ]
    result = fed.consensus_resolve(proposals)
    assert result["winner"] is not None, "No winner"
    assert result["term"] > 0, "Term not incremented"
    assert result["status"] in ("local_consensus", "majority", "plurality"), \
        f"Bad status: {result['status']}"
    print(f"  ✓ consensus: {result['status']} → winner={result['winner']} term={result['term']}")

    # Single proposal
    single = [{"id": "only", "value": "solo"}]
    r2 = fed.consensus_resolve(single)
    assert r2["winner"] == "solo"
    assert r2["status"] == "unanimous"
    print(f"  ✓ single proposal: unanimous")

    # Empty proposals
    r3 = fed.consensus_resolve([])
    assert r3["winner"] is None
    assert r3["status"] == "no_proposals"
    print(f"  ✓ empty proposals: {r3['status']}")

    # Test knowledge sync helpers
    print("\n--- knowledge ---")
    fed.set_knowledge("key1", "value1")
    fed.set_knowledge("key2", {"nested": True})
    assert fed.get_knowledge()["key1"] == "value1"
    assert fed.delete_knowledge("key1")
    assert fed.delete_knowledge("nonexistent") is False
    print(f"  ✓ knowledge get/set/delete OK")

    # Test health_check
    health = fed.health_check()
    assert health["node_id"] == "test-node-1"
    assert health["peers_total"] == 1
    print(f"  ✓ health: {health['peers_total']} peers, "
          f"{health['knowledge_entries']} entries")

    # Test remove_peer
    assert fed.remove_peer("peer-1")
    assert not fed.remove_peer("peer-1")
    print(f"  ✓ remove_peer OK")

    # Test gossip (no real peers, should return 0 sent)
    gossip_result = fed.gossip({"msg": "hello"})
    print(f"  ✓ gossip: {gossip_result}")

    # Test peer_discovery (multicast may be unavailable, verify graceful failure)
    discovered = fed.peer_discovery(timeout=0.5)
    assert isinstance(discovered, list), f"Expected list, got {type(discovered)}"
    print(f"  ✓ peer_discovery: {len(discovered)} peers discovered (graceful)")

    print("\n✓ All self-tests passed")