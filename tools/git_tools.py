"""Git operations tool. Safe by default — never force-push to main/master.
DNA: Claude Code (git-native PR workflow).
"""

import subprocess
from pathlib import Path


def git_status(repo_path: str = ".") -> str:
    """Show working tree status."""
    return _run_git(repo_path, ["status", "--short", "--branch"])


def git_diff(repo_path: str = ".", staged: bool = False) -> str:
    """Show working tree diff."""
    args = ["diff"]
    if staged:
        args.append("--staged")
    return _run_git(repo_path, args)


def git_log(repo_path: str = ".", max_count: int = 10) -> str:
    """Show recent commit history."""
    return _run_git(repo_path, [
        "log", f"--max-count={max_count}", "--oneline", "--decorate"
    ])


def git_branch(repo_path: str = ".") -> str:
    """List branches."""
    return _run_git(repo_path, ["branch", "--list"])


def git_commit(repo_path: str, message: str, files: str = ".") -> str:
    """Stage files and commit."""
    # Stage
    _run_git(repo_path, ["add"] + files.split())
    # Commit
    return _run_git(repo_path, ["commit", "-m", message])


def git_push(repo_path: str = ".", remote: str = "origin", 
             branch: str = "") -> str:
    """Push to remote. Blocks force-push to protected branches."""
    if not branch:
        branch = _current_branch(repo_path)
    
    # SAFETY: never force-push to main/master
    if branch in ("main", "master"):
        return "⚠ Cannot push to protected branch. Create a feature branch."

    return _run_git(repo_path, ["push", remote, branch])


def git_create_branch(repo_path: str, branch_name: str) -> str:
    """Create and switch to a new branch."""
    return _run_git(repo_path, ["checkout", "-b", branch_name])


def git_clone(url: str, target_dir: str = "", branch: str = "") -> str:
    """Clone a repository."""
    args = ["clone"]
    if branch:
        args.extend(["-b", branch])
    args.append(url)
    if target_dir:
        args.append(target_dir)
    return _run_git(".", args)


# ── Helpers ────────────────────────────────────────────────

def _run_git(repo_path: str, args: list[str]) -> str:
    """Execute a git command in the given repo."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=repo_path,
        )
        output = result.stdout.strip()
        if result.stderr:
            stderr = result.stderr.strip()
            if stderr:
                output += f"\n[stderr] {stderr}"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "Git command timed out"
    except FileNotFoundError:
        return "Git not found. Install git first."
    except Exception as e:
        return f"Git error: {e}"


def _current_branch(repo_path: str) -> str:
    """Get current branch name."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, cwd=repo_path, timeout=5
    )
    return result.stdout.strip()