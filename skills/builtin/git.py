"""Built-in skill: git workflow patterns."""
NAME = "git"
DESCRIPTION = "Git operations, branching, PR workflow, commit conventions"
TRIGGERS = ["git", "commit", "push", "pull", "branch", "merge", "rebase", "pr", "pull request", "clone"]

PROMPT = """
You are in GIT mode. Follow these conventions:

1. COMMITS: atomic, present-tense, descriptive. "Add user auth" not "added stuff"
2. BRANCHES: feature/name, fix/name, chore/name. Never commit to main directly.
3. PRs: title summarizes change, body explains WHY. Link issues.
4. SAFETY: never force-push to main/master. Always pull before push.

Workflow:
- Start: git checkout -b feature/my-feature
- Work: commit early, commit often
- Sync: git pull --rebase origin main
- Push: git push -u origin feature/my-feature
- Done: create PR, request review

Destructive ops require user approval (force push, hard reset, squash).
"""