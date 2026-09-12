"""Hermes Plugin: OmniCore v3 — autonomous hyper-agent skill layer.

When installed in Hermes, OmniCore injects its full cybersecurity,
reasoning, and overpower capabilities as Hermes skills.

Install:
    hermes plugins install /storage/emulated/0/OmniCore --enable

Usage inside Hermes:
    /omnicore status          Show OmniCore status
    /omnicore sovereign <key> Authenticate as operator
    /omnicore pentest <url>   Run pentest recon on target
    /omnicore forge <code>    Run Blacksmith code forge
    /omnicore tokens          Show TokenForge savings

All OmniCore builtin skills (55) are auto-loaded as Hermes skills.
"""

import os
import sys
from pathlib import Path

# Ensure OmniCore is on path
OMNICORE_DIR = Path(__file__).parent
if str(OMNICORE_DIR) not in sys.path:
    sys.path.insert(0, str(OMNICORE_DIR))

# Lazy imports — only load when needed
_agent = None
_loaded = False


def _get_agent():
    """Get or create OmniCore agent instance."""
    global _agent
    if _agent is None:
        from core.engine import OmniCore
        _agent = OmniCore()
        _agent.sovereign.authenticate_env()
    return _agent


def _load_skills(ctx):
    """Register all OmniCore skills into Hermes."""
    global _loaded
    if _loaded:
        return

    from skills.loader import SkillLoader
    loader = SkillLoader()
    for skill in loader.list_all():
        # Register as Hermes skill
        try:
            ctx.register_skill(
                f"omnicore:{skill.name}",
                skill.prompt,
                description=skill.description,
                triggers=skill.triggers,
            )
        except Exception:
            pass

    _loaded = True


# ── Hermes hooks ─────────────────────────────────────────────────────

def _pre_llm_call(session_id: str = "", **kwargs) -> dict | None:
    """Inject OmniCore context before each LLM call."""
    agent = _get_agent()
    if agent.sovereign.is_operator:
        identity = "OPERATOR"
    else:
        identity = f"OmniCore v3 — {len(agent.skills.list_all())} skills active"

    return {
        "context": (
            f"[OMNICORE v3 ACTIVE — {identity}]\n"
            f"DNA: 21 sources fused. Execute. Learn. Improve.\n"
        )
    }


# ── Slash commands ───────────────────────────────────────────────────

def _cmd_status(args: str) -> str:
    agent = _get_agent()
    return f"""OmniCore v3 Status:
  Mode: {'OPERATOR' if agent.sovereign.is_operator else 'PUBLIC'}
  Skills: {len(agent.skills.list_all())} loaded
  Provider: {agent.provider.default_model}
  Tools: {len(agent.registry.list_all())} registered
  PersonaCage: {'DISABLED' if agent.sovereign.is_operator else 'ENFORCED'}
  Jailbreak SHIELD: {'DISABLED' if agent.sovereign.is_operator else 'ACTIVE'}
  Jailbreak SWORD: {'ENABLED' if agent.sovereign.is_operator else 'LOCKED'}
"""


def _cmd_sovereign(args: str) -> str:
    agent = _get_agent()
    key = args.strip()
    if not key:
        return f"Usage: /omnicore sovereign <master-key>\nCurrent: {'OPERATOR' if agent.sovereign.is_operator else 'PUBLIC'}"

    if agent.sovereign.authenticate(key):
        return "✓ Authenticated. OPERATOR MODE — all restrictions lifted."
    return "✗ Invalid key."


def _cmd_pentest(args: str) -> str:
    target = args.strip()
    if not target:
        return "Usage: /omnicore pentest <target-url>"

    try:
        from tools.pentest.recon import subdomain_enum, tech_fingerprint
        subs = subdomain_enum(target)
        tech = tech_fingerprint(f"https://{target}")
        return f"Pentest Recon: {target}\n\n{subs}\n\n{tech}"
    except Exception as e:
        return f"Pentest error: {e}"


def _cmd_forge(args: str) -> str:
    return f"[BLACKSMITH] Activate 6-strike forge on: {args}\nUse the blacksmith skill for code transformation."


def _cmd_tokens(args: str) -> str:
    agent = _get_agent()
    return agent.tokenforge.dashboard()


# ── Command registration ─────────────────────────────────────────────

SLASH_COMMANDS = {
    "omnicore": {
        "status":    (_cmd_status,    "Show OmniCore v3 status"),
        "sovereign": (_cmd_sovereign, "Authenticate as operator: /omnicore sovereign <key>"),
        "pentest":   (_cmd_pentest,   "Run pentest recon on target: /omnicore pentest <url>"),
        "forge":     (_cmd_forge,     "Activate Blacksmith code forge"),
        "tokens":    (_cmd_tokens,    "Show TokenForge API savings"),
    }
}


# ── Hermes plugin entry point ────────────────────────────────────────

def register(ctx):
    """Register OmniCore plugin with Hermes."""
    ctx.register_hook("pre_llm_call", _pre_llm_call)

    # Register all 55 skills
    _load_skills(ctx)

    # Register slash commands
    for group, commands in SLASH_COMMANDS.items():
        for subcmd, (handler, desc) in commands.items():
            if subcmd == "status":
                cmd_name = f"{group}-{subcmd}"
            else:
                cmd_name = f"{group}-{subcmd}"
            ctx.register_command(
                cmd_name,
                handler,
                description=desc,
                args_hint="[args]",
            )

    # Register main command
    ctx.register_command(
        "omnicore",
        _cmd_status,
        description="OmniCore v3 — autonomous hyper-agent. Subcommands: status/sovereign/pentest/forge/tokens",
        args_hint="[status|sovereign|pentest|forge|tokens] [args]",
    )