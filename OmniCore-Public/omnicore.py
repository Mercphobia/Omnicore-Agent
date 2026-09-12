#!/usr/bin/env python3
"""OmniCore Launcher — auto-detect or manual mode selection.

TWO MODES:

  HERMES MODE (runs inside Hermes Agent):
    - Uses Hermes provider, tools, memory, skills
    - Acts as a plugin/skill layer on top
    - Lower resource usage, shares Hermes infra
    - Activate: OMNICORE_MODE=hermes or auto-detect

  STANDALONE MODE (runs independently):
    - Full OmniCore engine with own providers, tools, memory
    - API server, CLI, WebSocket, all 166 files
    - Complete cybersecurity suite + overpower core
    - Activate: OMNICORE_MODE=standalone or default

AUTO-DETECT:
    If HERMES_BUATPREM_API_KEY exists → HERMES mode
    Otherwise → STANDALONE mode

Usage:
    omnicore                              # Auto-detect mode
    omnicore --mode hermes                # Force Hermes mode
    omnicore --mode standalone            # Force standalone mode
    omnicore --mode standalone --server   # Start API server
    omnicore --mode standalone --cli      # Start CLI (default)
"""

import os
import sys
from pathlib import Path

# Add OmniCore to path
OMNICORE_DIR = Path(__file__).parent
sys.path.insert(0, str(OMNICORE_DIR))


def detect_mode() -> str:
    """Auto-detect which mode to run in."""
    # 1. Explicit override
    mode = os.environ.get("OMNICORE_MODE", "").lower()
    if mode in ("hermes", "standalone"):
        return mode

    # 2. Check for Hermes environment
    if os.environ.get("HERMES_BUATPREM_API_KEY"):
        return "hermes"

    # 3. Default: standalone
    return "standalone"


def run_hermes_mode():
    """Run OmniCore as a Hermes plugin/skill layer."""
    print("⚡ OmniCore v3 — HERMES MODE")
    print("   Running as skill layer on Hermes infrastructure")

    from core.engine import OmniCore
    from core.persona_cage import PersonaCage
    from core.tokenforge import TokenForge
    from core.sovereign import SovereignGate

    # Minimal init — use Hermes provider
    agent = OmniCore()
    agent.sovereign.authenticate_env()

    print(f"   Sovereign: {'OPERATOR' if agent.sovereign.is_operator else 'PUBLIC'}")
    print(f"   Skills: {len(agent.skills.list_all())} loaded")
    print(f"   Provider: {agent.provider.default_model}")
    print("   Ready.")
    return agent


def run_standalone_mode(server: bool = False):
    """Run OmniCore as standalone agent with full capabilities."""
    print("🛡️  OmniCore v3 — STANDALONE MODE")
    print("   166 files | 51K lines | 11 providers | 55 skills | 35+ tools")

    if server:
        print("   Starting API server on http://0.0.0.0:8000 ...")
        import uvicorn
        from ui.api import app
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
    else:
        print("   Starting interactive CLI...")
        from ui.cli import main
        main()


def show_banner(mode: str):
    """Display the OmniCore banner."""
    banner = r"""
  ╔══════════════════════════════════════════════╗
  ║           OMNICORE v3 — OVERPOWER           ║
  ║     "The platform agents run on."           ║
  ╠══════════════════════════════════════════════╣
  ║  DNA: 21 frontier sources fused             ║
  ║  Mode: {: <36s} ║
  ║  Sovereign: {: <31s} ║
  ╚══════════════════════════════════════════════╝
    """
    sovereign = "PUBLIC (PersonaCage enforced)"
    if os.environ.get("OMNICORE_MASTER_KEY"):
        sovereign = "OPERATOR (Jack, full access)"

    print(banner.format(mode.upper(), sovereign))


# ── Entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="OmniCore v3 Launcher")
    parser.add_argument("--mode", choices=["hermes", "standalone", "auto"],
                       default="auto", help="Run mode (default: auto-detect)")
    parser.add_argument("--server", action="store_true",
                       help="Start API server (standalone mode only)")
    parser.add_argument("query", nargs="*", help="Single-shot query")

    args = parser.parse_args()

    mode = args.mode if args.mode != "auto" else detect_mode()
    show_banner(mode)

    if mode == "hermes":
        agent = run_hermes_mode()
        if args.query:
            import asyncio
            async def query():
                response = await agent.run(" ".join(args.query))
                print(response)
            asyncio.run(query())

    elif mode == "standalone":
        run_standalone_mode(server=args.server)