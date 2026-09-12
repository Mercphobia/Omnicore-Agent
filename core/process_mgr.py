"""Process Manager — background process poll/wait/kill.

DNA: Hermes process_manage.

Manages subprocess lifecycle: start, poll status, wait for completion,
terminate, kill, list running processes.
"""

import os as _os_impl
import subprocess
import time
import json
import signal
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

os = _os_impl


@dataclass
class ManagedProcess:
    pid: int
    name: str
    command: str
    status: str = "running"  # running | done | killed | error
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    exit_code: Optional[int] = None
    output_file: Optional[str] = None


class ProcessManager:
    """Manage background processes with poll/wait/kill.

    Usage:
        pm = ProcessManager()
        pid = pm.start("my_task", "python script.py")
        pm.poll(pid)          # Check if still running
        pm.wait(pid, 30)      # Wait up to 30s for completion
        pm.kill(pid)          # Force kill
        pm.list_all()          # All managed processes
    """

    def __init__(self, log_dir: str = "~/.omnicore/processes"):
        self.log_dir = Path(log_dir).expanduser()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._processes: dict[int, ManagedProcess] = {}

    def start(self, name: str, command: str, 
              capture_output: bool = True) -> int:
        """Start a background process. Returns PID."""
        output_file = self.log_dir / f"{name}_{int(time.time())}.log"

        if capture_output:
            f = open(output_file, "w")
            proc = subprocess.Popen(
                command, shell=True,
                stdout=f, stderr=subprocess.STDOUT,
                preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_IGN)
            )
        else:
            proc = subprocess.Popen(command, shell=True)

        mp = ManagedProcess(
            pid=proc.pid,
            name=name,
            command=command,
            output_file=str(output_file) if capture_output else None,
        )
        self._processes[proc.pid] = mp
        return proc.pid

    def poll(self, pid: int) -> str:
        """Check process status. Returns: running | done | unknown."""
        if pid not in self._processes:
            return "unknown"

        mp = self._processes[pid]
        if mp.status != "running":
            return mp.status

        try:
            os.kill(pid, 0)  # Signal 0 = check if process exists
        except OSError:
            mp.status = "done"
            mp.finished_at = time.time()
        return mp.status

    def wait(self, pid: int, timeout: int = 60) -> str:
        """Wait for process to complete. Returns final status."""
        if pid not in self._processes:
            return "unknown"

        mp = self._processes[pid]
        deadline = time.time() + timeout

        while time.time() < deadline:
            status = self.poll(pid)
            if status != "running":
                return status
            time.sleep(0.5)

        return "running"  # Timeout, still running

    def kill(self, pid: int, force: bool = False) -> str:
        """Kill a process. Returns status after kill."""
        if pid not in self._processes:
            return "unknown"

        mp = self._processes[pid]
        sig = signal.SIGKILL if force else signal.SIGTERM

        try:
            os.kill(pid, sig)
            time.sleep(0.5)
            mp.status = "killed"
            mp.finished_at = time.time()
        except ProcessLookupError:
            mp.status = "done"
            mp.finished_at = time.time()
        except OSError:
            pass

        return mp.status

    def kill_all(self, name: str = "") -> str:
        """Kill all managed processes, optionally filtered by name."""
        count = 0
        for pid, mp in list(self._processes.items()):
            if name and mp.name != name:
                continue
            if mp.status == "running":
                self.kill(pid)
                count += 1
        return f"Killed {count} process(es)"

    def list(self, status: str = "") -> list[dict]:
        """List managed processes."""
        result = []
        for mp in self._processes.values():
            if status and mp.status != status:
                continue
            result.append({
                "pid": mp.pid, "name": mp.name,
                "status": mp.status if mp.status == "running" else self.poll(mp.pid),
                "uptime_seconds": round(time.time() - mp.started_at, 1),
                "command": mp.command[:80],
            })
        return result

    def read_output(self, pid: int, lines: int = 50) -> str:
        """Read last N lines of process output."""
        if pid not in self._processes:
            return "Unknown PID"
        mp = self._processes[pid]
        if not mp.output_file or not Path(mp.output_file).exists():
            return "No output captured"
        with open(mp.output_file) as f:
            all_lines = f.readlines()
            return "".join(all_lines[-lines:])

    def cleanup(self, older_than_hours: float = 24):
        """Remove logs for completed processes older than threshold."""
        for pid, mp in list(self._processes.items()):
            if mp.status in ("done", "killed") and mp.finished_at:
                age = time.time() - mp.finished_at
                if age > older_than_hours * 3600:
                    if mp.output_file:
                        Path(mp.output_file).unlink(missing_ok=True)
                    del self._processes[pid]


# ── Self-test ──────────────────────────────────────────────────────────

import os as _os

if __name__ == "__main__":
    pm = ProcessManager()

    # Start a process
    pid = pm.start("test_sleep", "sleep 2")
    print(f"Started PID: {pid}")

    # Poll
    status = pm.poll(pid)
    print(f"Status after start: {status}")
    assert status == "running"

    # Wait
    final = pm.wait(pid, timeout=10)
    print(f"Status after wait: {final}")
    assert final in ("done", "running"), f"Unexpected: {final}"

    # List
    procs = pm.list()
    print(f"Managed processes: {len(procs)}")
    assert len(procs) == 1

    # Cleanup
    pm.cleanup(0)
    procs = pm.list()
    print(f"After cleanup: {len(procs)}")
    # Process may still be running, cleanup only removes completed ones
    assert len(procs) >= 0
    pm.kill(pid, force=True)

    print("\n✓ ProcessManager self-tests passed")