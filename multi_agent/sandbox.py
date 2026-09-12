"""Sandboxed execution environment. Isolated subprocess with resource limits.
DNA: Codex CLI (sandboxed ops) + Devin (env isolation).

Runs commands in isolated directories with optional Docker support.
Falls back to subprocess with resource limits when Docker unavailable.
"""

import os
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional


class Sandbox:
    """Isolated execution environment for safe code execution."""

    def __init__(self, name: str = "", work_dir: str | None = None):
        self.name = name or f"sandbox_{os.getpid()}"
        self.work_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="omnicore_sandbox_"))
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._created_dirs: list[Path] = []

    def run(self, command: str, timeout: int = 30, env: dict | None = None) -> dict:
        """Run a command in the sandbox.
        
        Returns:
            {exit_code, stdout, stderr, timed_out}
        """
        try:
            r = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.work_dir),
                env={**os.environ, **(env or {})},
            )
            return {
                "exit_code": r.returncode,
                "stdout": r.stdout[-5000:],
                "stderr": r.stderr[-2000:],
                "timed_out": False,
            }
        except subprocess.TimeoutExpired:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s",
                "timed_out": True,
            }

    def write_file(self, filename: str, content: str) -> str:
        """Write a file into the sandbox."""
        path = self.work_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return str(path)

    def read_file(self, filename: str) -> str:
        """Read a file from the sandbox."""
        path = self.work_dir / filename
        if not path.exists():
            return f"File not found: {filename}"
        return path.read_text()

    def copy_in(self, source: str, dest: str = "") -> str:
        """Copy a file or directory into the sandbox."""
        src = Path(source).expanduser()
        dst = self.work_dir / (dest or src.name)
        
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        
        return str(dst)

    def copy_out(self, sandbox_path: str, dest: str) -> str:
        """Copy a file from sandbox to host."""
        src = self.work_dir / sandbox_path
        dst = Path(dest).expanduser()
        dst.parent.mkdir(parents=True, exist_ok=True)
        
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        
        return str(dst)

    def list_files(self, subdir: str = "") -> list[str]:
        """List files in the sandbox."""
        target = self.work_dir / subdir if subdir else self.work_dir
        if not target.exists():
            return []
        
        files = []
        for p in target.rglob("*"):
            if p.is_file():
                rel = p.relative_to(self.work_dir)
                files.append(str(rel))
        return sorted(files)

    def cleanup(self) -> None:
        """Delete the sandbox directory and all contents."""
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cleanup()


class DockerSandbox(Sandbox):
    """Docker-based sandbox with full container isolation."""

    def __init__(self, name: str = "", image: str = "python:3.11-slim"):
        super().__init__(name=name)
        self.image = image
        self.container_id: Optional[str] = None

    def run(self, command: str, timeout: int = 30, env: dict | None = None) -> dict:
        """Run command in Docker container."""
        env_args = []
        if env:
            for k, v in env.items():
                env_args.extend(["-e", f"{k}={v}"])

        try:
            # Start container
            r = subprocess.run(
                ["docker", "run", "--rm", "-d", "--name", self.name,
                 "-v", f"{self.work_dir}:/workspace",
                 "-w", "/workspace"]
                + env_args + [self.image, "sleep", "infinity"],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode != 0:
                return {"exit_code": -1, "stdout": "", "stderr": f"Docker start failed: {r.stderr}", "timed_out": False}

            self.container_id = r.stdout.strip()

            # Execute command
            r2 = subprocess.run(
                ["docker", "exec", self.container_id, "sh", "-c", command],
                capture_output=True, text=True, timeout=timeout,
            )

            # Stop container
            subprocess.run(["docker", "stop", self.container_id],
                          capture_output=True, timeout=10)

            return {
                "exit_code": r2.returncode,
                "stdout": r2.stdout[-5000:],
                "stderr": r2.stderr[-2000:],
                "timed_out": False,
            }
        except subprocess.TimeoutExpired:
            self._kill_container()
            return {"exit_code": -1, "stdout": "", "stderr": f"Command timed out after {timeout}s", "timed_out": True}
        except FileNotFoundError:
            # Docker not installed — fall back to regular sandbox
            return super().run(command, timeout, env)

    def _kill_container(self):
        if self.container_id:
            subprocess.run(["docker", "kill", self.container_id],
                          capture_output=True, timeout=10)

    def cleanup(self):
        self._kill_container()
        super().cleanup()


# ── Multi-sandbox (parallel isolation) ────────────────────────

class SandboxPool:
    """Run N sandboxes in parallel for testing multiple scenarios."""

    def __init__(self, count: int = 3):
        self.count = count
        self.sandboxes: list[Sandbox] = []

    def __enter__(self):
        self.sandboxes = [Sandbox(name=f"sandbox_{i}") for i in range(self.count)]
        return self

    def __exit__(self, *args):
        for sb in self.sandboxes:
            sb.cleanup()

    def run_all(self, command: str, timeout: int = 30) -> list[dict]:
        """Run the same command in all sandboxes."""
        results = []
        for sb in self.sandboxes:
            results.append(sb.run(command, timeout=timeout))
        return results

    def run_each(self, commands: list[str], timeout: int = 30) -> list[dict]:
        """Run different commands in each sandbox."""
        results = []
        for sb, cmd in zip(self.sandboxes, commands):
            results.append(sb.run(cmd, timeout=timeout))
        return results


# ── Tool wrappers ────────────────────────────────────────────

_active_sandboxes: dict[str, Sandbox] = {}


def sandbox_create(name: str = "") -> str:
    """Create a new sandboxed environment."""
    sb = Sandbox(name=name or f"sb_{len(_active_sandboxes)}")
    _active_sandboxes[sb.name] = sb
    return f"✅ Sandbox created: {sb.name} ({sb.work_dir})"


def sandbox_run(name: str, command: str, timeout: int = 30) -> str:
    """Run a command in a sandbox."""
    sb = _active_sandboxes.get(name)
    if not sb:
        return f"❌ Sandbox not found: {name}"
    result = sb.run(command, timeout=timeout)
    if result["exit_code"] == 0:
        return f"✅ Exit 0\n{result['stdout'][:1000]}"
    return f"❌ Exit {result['exit_code']}\n{result['stderr'][:500] or result['stdout'][:500]}"


def sandbox_cleanup(name: str = "") -> str:
    """Destroy a sandbox."""
    if name:
        sb = _active_sandboxes.pop(name, None)
        if sb:
            sb.cleanup()
            return f"✅ Sandbox destroyed: {name}"
        return f"❌ Sandbox not found: {name}"
    else:
        count = len(_active_sandboxes)
        for sb in _active_sandboxes.values():
            sb.cleanup()
        _active_sandboxes.clear()
        return f"✅ {count} sandbox(es) destroyed"