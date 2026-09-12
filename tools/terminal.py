"""Terminal/shell execution tool. Gated for destructive commands."""

import subprocess
import shlex

DESTRUCTIVE_PATTERNS = [
    "rm ", "rm -rf", "dd ", "mkfs", ":(){ :|:& };:",  # fork bomb
    "> /dev/sda", "chmod 777 /", "shutdown", "reboot",
    "git push --force", "git reset --hard",
]


def run_command(command: str, timeout: int = 60, workdir: str = "") -> str:
    """Execute a shell command. Returns stdout + stderr.
    
    Destructive commands are flagged but still executed.
    The caller (agent engine) is responsible for gating.
    """
    # Check for destructive patterns
    warnings = []
    cmd_lower = command.lower()
    for pattern in DESTRUCTIVE_PATTERNS:
        if pattern.lower() in cmd_lower:
            warnings.append(f"⚠ DESTRUCTIVE: contains '{pattern}'")

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=workdir or None,
            executable="/bin/bash" if _bash_available() else None,
        )

        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"

        if warnings:
            output = "\n".join(warnings) + "\n\n" + output

        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"

        return output.strip() or "(no output)"

    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return f"Command not found: {shlex.split(command)[0] if command else '?'}"
    except Exception as e:
        return f"Error: {e}"


def _bash_available() -> bool:
    """Check if bash is available."""
    try:
        subprocess.run(["bash", "--version"], capture_output=True, timeout=2)
        return True
    except Exception:
        return False