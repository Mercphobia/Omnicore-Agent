"""Execution checkpointing. Save/restore agent state at any point.
DNA: Chronos (time-travel state recovery).
"""

import pickle
import time
from pathlib import Path
from typing import Optional


class Checkpoint:
    """Serializable agent state snapshot."""

    def __init__(self, name: str = "", data: dict | None = None):
        self.name = name or f"checkpoint_{int(time.time())}"
        self.timestamp = time.time()
        self.data = data or {}

    def save(self, directory: Path | str = "~/.omnicore/checkpoints") -> Path:
        """Save checkpoint to disk."""
        d = Path(directory).expanduser()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{self.name}.pkl"
        with open(path, "wb") as f:
            pickle.dump(self, f)
        return path

    @staticmethod
    def load(path: Path | str) -> Optional["Checkpoint"]:
        """Load checkpoint from disk."""
        p = Path(path).expanduser()
        if not p.exists():
            return None
        with open(p, "rb") as f:
            return pickle.load(f)


class CheckpointManager:
    """Manage multiple checkpoints with list, restore, cleanup."""

    def __init__(self, directory: str = "~/.omnicore/checkpoints"):
        self.directory = Path(directory).expanduser()
        self.directory.mkdir(parents=True, exist_ok=True)

    def create(self, name: str = "", state: dict | None = None) -> Checkpoint:
        """Create a new checkpoint from current state."""
        cp = Checkpoint(name=name or f"ckpt_{int(time.time())}", data=state or {})
        cp.save(self.directory)
        return cp

    def restore(self, name: str) -> Optional[Checkpoint]:
        """Restore a checkpoint by name."""
        path = self.directory / f"{name}.pkl"
        return Checkpoint.load(path)

    def list_checkpoints(self) -> list[dict]:
        """List all available checkpoints."""
        checkpoints = []
        for f in sorted(self.directory.glob("*.pkl"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                cp = Checkpoint.load(f)
                checkpoints.append({
                    "name": cp.name,
                    "timestamp": cp.timestamp,
                    "time_ago": _time_ago(time.time() - cp.timestamp),
                    "keys": list(cp.data.keys()) if cp.data else [],
                    "size": f.stat().st_size,
                })
            except Exception:
                checkpoints.append({
                    "name": f.stem,
                    "timestamp": f.stat().st_mtime,
                    "time_ago": _time_ago(time.time() - f.stat().st_mtime),
                    "keys": [],
                    "size": f.stat().st_size,
                })
        return checkpoints

    def delete(self, name: str) -> bool:
        """Delete a checkpoint by name."""
        path = self.directory / f"{name}.pkl"
        if path.exists():
            path.unlink()
            return True
        return False

    def cleanup(self, max_age_hours: float = 168, keep_latest: int = 5) -> int:
        """Remove old checkpoints, keeping the latest N."""
        removed = 0
        checkpoints = self.list_checkpoints()
        now = time.time()

        # Keep the latest N
        for cp in checkpoints[keep_latest:]:
            age_hours = (now - cp["timestamp"]) / 3600
            if age_hours > max_age_hours:
                self.delete(cp["name"])
                removed += 1

        return removed

    def snapshot_agent(self, agent) -> Checkpoint:
        """Create a checkpoint from an OmniCore agent instance."""
        state = {
            "session_id": getattr(agent, "session_id", ""),
            "messages": getattr(agent, "messages", [])[-50:],  # Last 50 messages
            "config": getattr(agent, "config", {}),
            "provider_model": getattr(agent.provider, "default_model", "") if hasattr(agent, "provider") else "",
        }
        return self.create(state=state)

    def restore_agent(self, agent, name: str) -> bool:
        """Restore agent state from a checkpoint."""
        cp = self.restore(name)
        if not cp:
            return False

        if "session_id" in cp.data:
            agent.session_id = cp.data["session_id"]
        if "messages" in cp.data:
            agent.messages = cp.data["messages"]

        return True


def _time_ago(seconds: float) -> str:
    """Human-readable time ago."""
    if seconds < 60:
        return f"{int(seconds)}s ago"
    elif seconds < 3600:
        return f"{int(seconds / 60)}m ago"
    elif seconds < 86400:
        return f"{int(seconds / 3600)}h ago"
    else:
        return f"{int(seconds / 86400)}d ago"


# ── Tool wrappers ────────────────────────────────────────────

_manager = None


def _get_manager() -> CheckpointManager:
    global _manager
    if _manager is None:
        _manager = CheckpointManager()
    return _manager


def checkpoint_save(name: str = "") -> str:
    """Save current agent state as a checkpoint."""
    cp = _get_manager().create(name)
    return f"✅ Checkpoint saved: {cp.name}"


def checkpoint_restore(name: str) -> str:
    """Restore agent state from a checkpoint."""
    cp = _get_manager().restore(name)
    if not cp:
        return f"❌ Checkpoint not found: {name}"
    return f"✅ Checkpoint restored: {cp.name} (keys: {list(cp.data.keys())})"


def checkpoint_list() -> str:
    """List all saved checkpoints."""
    checkpoints = _get_manager().list_checkpoints()
    if not checkpoints:
        return "(no checkpoints)"
    lines = [f"Checkpoints ({len(checkpoints)}):"]
    for cp in checkpoints:
        size_kb = cp["size"] / 1024
        lines.append(f"  {cp['name']} ({size_kb:.1f}KB) — {cp['time_ago']}")
    return "\n".join(lines)


def checkpoint_clear(max_age_hours: float = 168) -> str:
    """Clean up old checkpoints."""
    removed = _get_manager().cleanup(max_age_hours=max_age_hours)
    return f"✅ Removed {removed} old checkpoint(s)"