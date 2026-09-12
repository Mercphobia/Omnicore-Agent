"""Session Continuity — resume after model switch without losing context.

DNA: Hermes session-continuity skill.

Saves compact state snapshots to memory. On session resume,
auto-restores the last known state so you never ask "where were we?"
"""

import time
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SessionState:
    """Compact session state snapshot."""
    session_id: str
    project: str = ""
    stage: str = ""
    stage_status: str = "in_progress"  # in_progress | done | blocked
    last_action: str = ""
    next_step: str = ""
    last_commit: str = ""
    background_pid: Optional[int] = None
    saved_at: float = field(default_factory=time.time)
    note: str = ""


class SessionContinuity:
    """Save/restore session state for seamless model switches.

    Usage:
        sc = SessionContinuity(memory_store)
        
        # Save state
        sc.save("OmniCore v3", "Phase 10: scheduler", "done",
                last_action="Committed scheduler.py",
                next_step="Build todo.py")
        
        # On resume (next session):
        state = sc.load()
        if state:
            print(f"Resuming: {state.project} — {state.stage} ({state.stage_status})")
    """

    # ── Redis-style memory store adapter ─────────────────────────────
    # ponytail: works with any dict-like store. Pass your MemoryStore 
    # or use the built-in JSON file backend.

    def __init__(self, memory_store=None, 
                 state_file: str = "~/.omnicore/session_state.json"):
        self.memory = memory_store
        self.state_file = Path(state_file).expanduser()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._current: Optional[SessionState] = None
        self._history: list[SessionState] = []

    def save(self, project: str, stage: str, stage_status: str = "in_progress",
             last_action: str = "", next_step: str = "",
             last_commit: str = "", background_pid: int = 0, note: str = ""):
        """Save current session state."""
        state = SessionState(
            session_id=f"session_{int(time.time())}",
            project=project,
            stage=stage,
            stage_status=stage_status,
            last_action=last_action,
            next_step=next_step,
            last_commit=last_commit,
            background_pid=background_pid if background_pid else None,
            note=note,
        )
        self._current = state
        self._history.append(state)

        # Persist to memory if available
        if self.memory:
            self.memory.remember("session_state", self._serialize(state))
        else:
            self.state_file.write_text(self._serialize(state))

    def load(self) -> Optional[SessionState]:
        """Load last session state. Returns None if no state exists."""
        data = ""
        if self.memory:
            data = self.memory.recall("session_state") or ""
        elif self.state_file.exists():
            data = self.state_file.read_text()

        if data:
            try:
                d = json.loads(data)
                state = SessionState(**d)
                self._current = state
                return state
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    def resume_summary(self) -> str:
        """Generate a human-readable resume summary."""
        state = self.load()
        if not state:
            return "No previous session state found. Starting fresh."

        icon = {"done": "✅", "in_progress": "🔄", "blocked": "⛔"}

        lines = [
            f"{icon.get(state.stage_status, '•')} Resuming: {state.project}",
            f"   Stage: {state.stage} ({state.stage_status})",
            f"   Last action: {state.last_action}",
        ]
        if state.next_step:
            lines.append(f"   Next: {state.next_step}")
        if state.last_commit:
            lines.append(f"   Commit: {state.last_commit[:8]}")
        if state.background_pid:
            lines.append(f"   Background: PID {state.background_pid}")
        if state.note:
            lines.append(f"   Note: {state.note}")

        return "\n".join(lines)

    def history(self, limit: int = 10) -> list[SessionState]:
        """Get recent state history."""
        return self._history[-limit:]

    def clear(self):
        """Clear all session state."""
        self._current = None
        self._history = []
        if hasattr(self.memory, 'forget'):
            self.memory.forget("session_state")
        self.state_file.unlink(missing_ok=True)

    def _serialize(self, state: SessionState) -> str:
        d = {
            "session_id": state.session_id,
            "project": state.project,
            "stage": state.stage,
            "stage_status": state.stage_status,
            "last_action": state.last_action,
            "next_step": state.next_step,
            "last_commit": state.last_commit,
            "background_pid": state.background_pid,
            "saved_at": state.saved_at,
            "note": state.note,
        }
        return json.dumps(d)


# ── Self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile

    state_file = Path(tempfile.gettempdir()) / "test_session.json"

    sc = SessionContinuity(state_file=str(state_file))

    # Save
    sc.save(
        project="OmniCore v3",
        stage="Phase 10: scheduler",
        stage_status="done",
        last_action="Committed scheduler.py with cron support",
        next_step="Build todo.py",
        last_commit="abc1234",
        note="All tests passing"
    )

    # Load
    state = sc.load()
    print(f"Loaded: {state.project} — {state.stage} ({state.stage_status})")
    assert state.project == "OmniCore v3"
    assert state.stage_status == "done"

    # Resume summary
    summary = sc.resume_summary()
    print(summary)
    assert "OmniCore v3" in summary
    assert "scheduler" in summary

    # History
    assert len(sc.history()) == 1

    # Clear
    sc.clear()
    assert sc.load() is None

    state_file.unlink(missing_ok=True)
    print("\n✓ SessionContinuity self-tests passed")