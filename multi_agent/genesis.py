"""Agent factory — spawn specialized sub-agents from templates.
DNA: Genesis (agent civilization) + Hydra (self-replicate).

Templates define agent roles with system prompts, tools, and configs.
Factory spawns them as independent workers with shared context.
"""

import time
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class AgentTemplate:
    """Blueprint for spawning a specialized agent."""
    role: str
    description: str
    system_prompt: str
    tools: list[str] = field(default_factory=list)
    model: str = ""
    temperature: float = 0.7
    max_iterations: int = 5
    icon: str = "🤖"


# ── Built-in Templates ───────────────────────────────────────

BUILTIN_TEMPLATES: dict[str, AgentTemplate] = {
    "architect": AgentTemplate(
        role="architect",
        description="System design, architecture decisions, trade-off analysis",
        system_prompt="""You are an ARCHITECT agent. Your job: design before building.

PRINCIPLES:
- Start with requirements. What must the system do?
- Consider constraints: budget, team, timeline, existing tech.
- State trade-offs explicitly. Every decision has a cost.
- Prefer simplicity. The best architecture is the one you don't need.
- Design for change. What's the migration path?

DELIVERABLES:
- High-level component diagram (ASCII)
- Data flow for key scenarios
- Technology choices with rationale
- Failure modes and mitigations
- Next steps for implementation""",
        tools=["read_file", "search_files", "list_files"],
        model="",
        temperature=0.5,
        icon="🏗️",
    ),
    "coder": AgentTemplate(
        role="coder",
        description="Implementation, code generation, debugging",
        system_prompt="""You are a CODER agent. Your job: write clean, working code.

Follow the PONYTAIL ladder before writing ANY code:
1. Does this need to exist? (YAGNI)
2. Already in this codebase? (reuse)
3. Stdlib does it? (use it)
4. Native platform feature? (use it)
5. Installed dependency? (use it)
6. One line? (one line)
7. Only then: the minimum that works

PRINCIPLES:
- Read before write. Understand the codebase.
- Full code, no stubs. No TODOs.
- Handle errors. Validate inputs.
- Test your code.
- Commit working code, not perfect code.""",
        tools=["read_file", "write_file", "search_files", "run_command",
               "git_status", "git_diff", "git_commit", "analyze_code"],
        model="",
        temperature=0.5,
        icon="💻",
    ),
    "reviewer": AgentTemplate(
        role="reviewer",
        description="Code review, quality check, security audit",
        system_prompt="""You are a REVIEWER agent. Your job: review code for quality and security.

CHECKLIST:
- Correctness: Does it solve the problem?
- Completeness: No stubs, no TODOs?
- Security: SQLi, XSS, hardcoded secrets, eval?
- Style: Conventions, naming, formatting?
- Performance: N+1 queries, nested loops, memory leaks?
- Tests: Are there tests? Do they cover edge cases?

OUTPUT:
- Summary: LGTM or changes requested
- Issues: numbered, with file:line references
- Suggestions: specific improvements
- Security flags: any vulnerabilities found""",
        tools=["read_file", "search_files", "analyze_code", "security_scan", "review_file"],
        model="",
        temperature=0.3,
        icon="🔍",
    ),
    "researcher": AgentTemplate(
        role="researcher",
        description="Web research, documentation, competitive analysis",
        system_prompt="""You are a RESEARCHER agent. Your job: find and synthesize information.

METHODOLOGY:
1. Define: What exactly do we need to know?
2. Search: Multiple sources, prefer primary over secondary.
3. Evaluate: Credibility, recency, bias.
4. Synthesize: Patterns, contradictions, gaps.
5. Cite: Every claim has a source.

OUTPUT:
- Key findings (numbered, with sources)
- Contradictions or gaps
- Recommendation
- References""",
        tools=["search_web", "read_file", "list_files"],
        model="",
        temperature=0.6,
        icon="📚",
    ),
    "devops": AgentTemplate(
        role="devops",
        description="Infrastructure, CI/CD, deployment, monitoring",
        system_prompt="""You are a DEVOPS agent. Your job: infrastructure as code.

PRINCIPLES:
- Automate everything. Manual steps are bugs.
- Infrastructure as Code: Terraform, Docker, K8s.
- CI/CD: Build -> Test -> Scan -> Deploy.
- Observe: Metrics, logs, alerts.
- Secure: CIS benchmarks, least privilege, secrets management.

CHECKLIST:
- Dockerfile with multi-stage build, non-root user
- K8s: deployment, service, ingress, probes, resource limits
- CI: lint -> test -> build -> deploy
- Monitoring: RED metrics + SLO""",
        tools=["read_file", "write_file", "run_command", "git_status", "git_diff"],
        model="",
        temperature=0.5,
        icon="⚙️",
    ),
    "ponytail": AgentTemplate(
        role="ponytail",
        description="Lazy senior dev — writes only what's necessary. 54% less code.",
        system_prompt="""You are PONYTAIL — the lazy senior dev who's been at the company longer than version control.

Before writing ANY code, climb this ladder. Stop at the first rung that holds:

1. Does this need to exist? → No: skip it. YAGNI.
2. Already in this codebase? → Reuse it.
3. Stdlib does it? → Use it.
4. Native platform feature? → Use it.
5. Installed dependency? → Use it.
6. One line? → One line.
7. Only then: the minimum that works.

RULES:
- ALWAYS read the code before editing.
- NEVER cut validation, error handling, security, or accessibility.
- Small code is a side effect of necessity, not golf.
- If something already exists, say so. Don't rewrite.
- Before npm/pip install, check what's already installed.""",
        tools=["read_file", "write_file", "search_files", "list_files",
               "analyze_code", "run_command"],
        model="",
        temperature=0.3,
        icon="🦥",
    ),
}


class Genesis:
    """Agent factory — spawn specialized agents from templates."""

    def __init__(self, provider_factory: Callable, bus=None):
        self.provider_factory = provider_factory
        self.templates: dict[str, AgentTemplate] = dict(BUILTIN_TEMPLATES)
        self.bus = bus
        self.active_agents: dict[str, dict] = {}

    def register_template(self, template: AgentTemplate) -> None:
        """Register a new agent template."""
        self.templates[template.role] = template

    def spawn(self, role: str, task: str, context: str = "") -> dict:
        """Spawn an agent of the given role to handle a task.
        
        Returns: {agent_id, role, task, status}
        """
        template = self.templates.get(role)
        if not template:
            return {"error": f"Unknown role: {role}. Available: {list(self.templates.keys())}"}

        agent_id = f"{role}_{int(time.time())}"

        agent_info = {
            "id": agent_id,
            "role": role,
            "template": template,
            "task": task,
            "context": context,
            "status": "spawned",
            "created_at": time.time(),
        }

        self.active_agents[agent_id] = agent_info
        return agent_info

    def spawn_team(self, assignments: dict[str, str], shared_context: str = "") -> list[dict]:
        """Spawn a team of agents for different tasks.
        
        Args:
            assignments: {role: task_description}
            shared_context: Context shared across all agents
        
        Returns:
            List of agent info dicts
        """
        team = []
        for role, task in assignments.items():
            agent = self.spawn(role, task, shared_context)
            team.append(agent)
        return team

    def spawn_for_complex_task(self, task: str) -> list[dict]:
        """Auto-decompose a complex task and spawn appropriate agents.
        
        Heuristic: based on task keywords, spawn the right team.
        """
        task_lower = task.lower()
        team_assignments = {}

        # Always include a ponytail (lazy senior dev oversight)
        if "code" in task_lower or "implement" in task_lower or "build" in task_lower:
            team_assignments["ponytail"] = f"Oversee and simplify: {task}"
            team_assignments["architect"] = f"Design approach for: {task}"
            team_assignments["coder"] = f"Implement: {task}"
            team_assignments["reviewer"] = f"Review implementation of: {task}"
        elif "research" in task_lower or "analyze" in task_lower:
            team_assignments["researcher"] = task
            team_assignments["architect"] = f"Synthesize findings for: {task}"
        elif "deploy" in task_lower or "infra" in task_lower:
            team_assignments["devops"] = task
            team_assignments["architect"] = f"Design infrastructure for: {task}"
        elif "security" in task_lower or "audit" in task_lower:
            team_assignments["reviewer"] = f"Security audit: {task}"
            team_assignments["coder"] = f"Fix security issues: {task}"
        else:
            # Default: architect + ponytail
            team_assignments["ponytail"] = f"Simplify: {task}"
            team_assignments["architect"] = f"Design approach: {task}"

        return self.spawn_team(team_assignments, shared_context=task)

    def list_templates(self) -> list[dict]:
        """List all available agent templates."""
        return [
            {
                "role": t.role,
                "description": t.description,
                "icon": t.icon,
                "tools": t.tools,
            }
            for t in self.templates.values()
        ]

    def list_active(self) -> list[dict]:
        """List all active agents."""
        return [
            {"id": a["id"], "role": a["role"], "task": a["task"][:80], "status": a["status"]}
            for a in self.active_agents.values()
        ]

    def get_template(self, role: str) -> Optional[AgentTemplate]:
        """Get a template by role name."""
        return self.templates.get(role)

    def kill_all(self) -> int:
        """Remove all active agents."""
        count = len(self.active_agents)
        self.active_agents.clear()
        return count


# ── Tool wrapper for CLI ─────────────────────────────────────

_genesis_instance: Optional[Genesis] = None


def get_genesis(provider_factory: Callable | None = None) -> Genesis:
    global _genesis_instance
    if _genesis_instance is None and provider_factory:
        _genesis_instance = Genesis(provider_factory)
    return _genesis_instance


def genesis_list_templates() -> str:
    """List available agent templates."""
    g = get_genesis()
    if not g:
        return "Genesis not initialized"
    templates = g.list_templates()
    lines = [f"Agent Templates ({len(templates)}):"]
    for t in templates:
        lines.append(f"  {t['icon']} {t['role']}: {t['description'][:60]}")
        lines.append(f"     tools: {', '.join(t['tools'][:5])}")
    return "\n".join(lines)


def genesis_spawn_team(task: str) -> str:
    """Spawn a team of agents for a complex task."""
    g = get_genesis()
    if not g:
        return "Genesis not initialized"
    team = g.spawn_for_complex_task(task)
    lines = [f"Team spawned for: {task[:80]}", f"Agents: {len(team)}"]
    for agent in team:
        if "error" in agent:
            lines.append(f"  ❌ {agent['error']}")
        else:
            lines.append(f"  {agent['role']}: {agent['task'][:60]}")
    return "\n".join(lines)