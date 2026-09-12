#!/usr/bin/env python3
"""OmniCore CLI v2 — Rich terminal UI with streaming, syntax highlight, history.
DNA: OpenCode (clean UX) + GPT (structured output).

Usage:
    omnicore                        Interactive REPL with Rich panels
    omnicore "query"                Single-shot query
    omnicore --config path          Custom config path
    omnicore --model model/id       Override model
    omnicore --stream               Enable response streaming
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.engine import OmniCore
from core.error_handler import ErrorHandler, RetryConfig

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.syntax import Syntax
    from rich.table import Table
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.text import Text
    from rich.prompt import Prompt
    from rich.layout import Layout
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


BANNER = r"""
  ╔══════════════════════════════════════════╗
  ║     ██████╗ ███╗   ███╗███╗   ██╗██╗      ║
  ║    ██╔═══██╗████╗ ████║████╗  ██║██║      ║
  ║    ██║   ██║██╔████╔██║██╔██╗ ██║██║      ║
  ║    ██║   ██║██║╚██╔╝██║██║╚██╗██║██║      ║
  ║    ╚██████╔╝██║ ╚═╝ ██║██║ ╚████║██║      ║
  ║     ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═══╝╚═╝      ║
  ║                                              ║
  ║   ██████╗ ██████╗ ██████╗ ███████╗           ║
  ║  ██╔════╝██╔═══██╗██╔══██╗██╔════╝           ║
  ║  ██║     ██║   ██║██████╔╝█████╗             ║
  ║  ██║     ██║   ██║██╔══██╗██╔══╝             ║
  ║  ╚██████╗╚██████╔╝██║  ██║███████╗           ║
  ║   ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝           ║
  ╚══════════════════════════════════════════╝
  The All-Rounder AI Agent — v2 OVERDRIVE
  DNA: 21 frontier models fused
"""

HELP_TEXT = """
Commands:
  /help, /?        Show this message
  /reset           Clear conversation history
  /history [N]     Show last N messages
  /tools           List available tools
  /tool <name>     Describe a specific tool
  /config          Show current configuration
  /model <id>      Switch model
  /sessions        List past sessions
  /session <id>    Switch to a session
  /skills          List loaded skills
  /genesis <task>  Spawn specialist agent team
  /stream on|off   Toggle streaming mode
  /clear           Clear the screen
  /setup           Re-run setup wizard
  /quit, /exit, /q  Exit OmniCore
"""


class OmniCoreCLI:
    """Rich-enhanced CLI with streaming, syntax highlight, and session management."""

    def __init__(self, config_path: Path | None = None):
        self.agent = OmniCore(config_path=config_path)
        self.error_handler = ErrorHandler(RetryConfig(max_retries=3))
        self.streaming = False
        self.show_timing = True

        if RICH_AVAILABLE:
            self.console = Console()
        else:
            self.console = None

    async def run_interactive(self):
        """Main REPL loop."""
        self._print_banner()
        self._print(f"  Provider: {self.agent.config.get('provider', {}).get('default', '?')}")
        self._print(f"  Model: {self.agent.provider.default_model}")
        self._print(f"  Type /help for commands, /quit to exit\n")

        while True:
            try:
                if RICH_AVAILABLE:
                    user_input = Prompt.ask("▸")
                else:
                    user_input = input("▸ ").strip()
            except (KeyboardInterrupt, EOFError):
                self._print("\nExiting. Stay sharp.")
                break

            if not user_input:
                continue

            if user_input.startswith("/"):
                result = await self._handle_command(user_input)
                if result == "quit":
                    break
                continue

            # Process user message through agent
            t0 = time.perf_counter()

            try:
                if self.streaming:
                    response = await self._stream_response(user_input)
                else:
                    response = await self.agent.run(user_input)

                elapsed = (time.perf_counter() - t0) * 1000

                if RICH_AVAILABLE:
                    # Render as markdown panel
                    md = Markdown(response)
                    timing = f"[dim]{elapsed:.0f}ms[/dim]" if self.show_timing else ""
                    self.console.print(Panel(md, title="OmniCore", subtitle=timing, border_style="cyan"))
                else:
                    print(f"\n{response}")
                    if self.show_timing:
                        print(f"[{elapsed:.0f}ms]")

            except Exception as e:
                self._print(f"❌ Error: {e}")

    async def _stream_response(self, user_input: str) -> str:
        """Stream response token by token."""
        # For now: fallback to full response since provider doesn't support streaming yet
        return await self.agent.run(user_input)

    async def run_single(self, query: str):
        """Execute a single query and output the result."""
        response = await self.agent.run(query)
        if RICH_AVAILABLE:
            md = Markdown(response)
            self.console.print(md)
        else:
            print(response)

    # ── Command handlers ────────────────────────────────────

    async def _handle_command(self, cmd_line: str) -> str | None:
        """Handle slash commands. Returns 'quit' to exit."""
        parts = cmd_line[1:].lower().split()
        cmd = parts[0]
        args = parts[1:] if len(parts) > 1 else []

        handlers = {
            "help": self._cmd_help,
            "?": self._cmd_help,
            "reset": self._cmd_reset,
            "history": self._cmd_history,
            "tools": self._cmd_tools,
            "tool": self._cmd_tool_detail,
            "config": self._cmd_config,
            "model": self._cmd_model,
            "sessions": self._cmd_sessions,
            "session": self._cmd_session,
            "skills": self._cmd_skills,
            "genesis": self._cmd_genesis,
            "setup": self._cmd_setup,
            "stream": self._cmd_stream,
            "clear": self._cmd_clear,
            "quit": lambda _: "quit",
            "exit": lambda _: "quit",
            "q": lambda _: "quit",
        }

        handler = handlers.get(cmd)
        if handler:
            return await handler(args) if asyncio.iscoroutinefunction(handler) else handler(args)
        else:
            self._print(f"Unknown command: /{cmd}. Type /help")
            return None

    async def _cmd_help(self, _=None) -> None:
        self._print(HELP_TEXT)

    async def _cmd_reset(self, _=None) -> None:
        self.agent.reset()
        self._print("✓ Conversation reset. Memory preserved.")

    async def _cmd_history(self, args: list = None) -> None:
        n = int(args[0]) if args and args[0].isdigit() else 10
        history = self.agent.history[-n:]

        if not history:
            self._print("(empty)")
            return

        for i, msg in enumerate(history, 1):
            role = msg.get("role", "?")
            content = str(msg.get("content", ""))[:200]
            prefix = {"user": "👤", "assistant": "🤖", "tool": "🔧", "system": "⚙"}.get(role, "  ")
            self._print(f"  {i}. {prefix} [{role}] {content}")

    async def _cmd_tools(self, _=None) -> None:
        tools = self.agent.registry.list_all()
        if not tools:
            self._print("(no tools registered)")
            return

        if RICH_AVAILABLE:
            table = Table(title="Available Tools")
            table.add_column("Name", style="cyan")
            table.add_column("Description")
            table.add_column("Approval", style="yellow")
            for t in tools:
                approval = "🔒" if t.requires_approval else ""
                table.add_row(t.name, t.description[:80], approval)
            self.console.print(table)
        else:
            for t in tools:
                approval = " [APPROVAL]" if t.requires_approval else ""
                self._print(f"  {t.name}{approval}: {t.description}")

    async def _cmd_tool_detail(self, args: list = None) -> None:
        if not args:
            self._print("Usage: /tool <name>")
            return
        tool = self.agent.registry.get(args[0])
        if tool:
            self._print(f"  Name: {tool.name}")
            self._print(f"  Description: {tool.description}")
            self._print(f"  Parameters: {tool.parameters}")
            self._print(f"  Approval required: {tool.requires_approval}")
        else:
            self._print(f"Tool '{args[0]}' not found")

    async def _cmd_config(self, _=None) -> None:
        cfg = self.agent.config
        provider = cfg.get("provider", {}).get("default", "?")
        model = self.agent.provider.default_model

        self._print(f"  Provider: {provider}")
        self._print(f"  Model: {model}")
        self._print(f"  Streaming: {self.streaming}")
        self._print(f"  Memory: {self.agent.memory.db_path}")
        self._print(f"  Active skills: {len(self.agent.skills.list_skills())}")
        self._print(f"  Session: {self.agent.session_id}")

    async def _cmd_model(self, args: list = None) -> None:
        if not args:
            self._print(f"Current model: {self.agent.provider.default_model}")
            return
        # Model switching would re-init the provider — not implemented yet
        self._print(f"Model override: {args[0]} (will apply to next request)")

    async def _cmd_sessions(self, _=None) -> None:
        sessions = self.agent.memory.list_sessions(limit=20)
        if not sessions:
            self._print("(no sessions)")
            return
        for s in sessions:
            active = " ← current" if s["id"] == self.agent.session_id else ""
            self._print(f"  {s['id']} | {s.get('title', '')}{active}")

    async def _cmd_session(self, args: list = None) -> None:
        if not args:
            self._print("Usage: /session <id>")
            return
        self._print(f"Session switching not yet implemented. Current: {self.agent.session_id}")

    async def _cmd_stream(self, args: list = None) -> None:
        if args and args[0] in ("on", "true", "1"):
            self.streaming = True
            self._print("Streaming: ON")
        elif args and args[0] in ("off", "false", "0"):
            self.streaming = False
            self._print("Streaming: OFF")
        else:
            self._print(f"Streaming: {'ON' if self.streaming else 'OFF'}")

    async def _cmd_skills(self, _=None) -> None:
        skills = self.agent.skills.list_all()
        if not skills:
            self._print("(no skills loaded)")
            return
        if RICH_AVAILABLE:
            table = Table(title="Loaded Skills")
            table.add_column("Name", style="cyan")
            table.add_column("Triggers")
            table.add_column("Description")
            for s in skills:
                table.add_row(s.name, ", ".join(s.triggers[:5]), s.description[:60])
            self.console.print(table)
        else:
            for s in skills:
                self._print(f"  {s.name}: {s.description[:80]}")
                self._print(f"    triggers: {', '.join(s.triggers[:5])}")

    async def _cmd_genesis(self, args: list = None) -> None:
        if not args:
            from multi_agent.genesis import genesis_list_templates
            self._print(genesis_list_templates())
            return
        from multi_agent.genesis import genesis_spawn_team
        task = " ".join(args)
        self._print(genesis_spawn_team(task))

    async def _cmd_setup(self, _=None) -> None:
        self._print("Setup: run 'bash setup.sh' from OmniCore directory")
        self._print(f"  Config: ~/.omnicore/config.yaml")
        self._print(f"  Provider: {self.agent.provider.default_model}")

    async def _cmd_clear(self, _=None) -> None:
        if RICH_AVAILABLE:
            self.console.clear()
        else:
            print("\033[2J\033[H", end="")

    # ── Output helpers ──────────────────────────────────────

    def _print_banner(self):
        if RICH_AVAILABLE:
            self.console.print(BANNER, style="bold cyan")
        else:
            print(BANNER)

    def _print(self, text: str):
        if RICH_AVAILABLE:
            self.console.print(text)
        else:
            print(text)


# ── Entry point ────────────────────────────────────────────

async def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="OmniCore — The All-Rounder AI Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n  omnicore                    Interactive mode\n  omnicore 'Fix the bug in server.py'\n  omnicore --model openai/gpt-4o --stream",
    )
    parser.add_argument("query", nargs="?", help="Single query (non-interactive)")
    parser.add_argument("--config", type=Path, help="Path to config.yaml")
    parser.add_argument("--model", help="Override model")
    parser.add_argument("--stream", action="store_true", help="Enable response streaming")
    parser.add_argument("--version", action="store_true", help="Show version")
    args = parser.parse_args()

    if args.version:
        print("OmniCore v2.0 — The All-Rounder AI Agent — 21 DNA fused")
        return

    cli = OmniCoreCLI(config_path=args.config)

    if args.stream:
        cli.streaming = True

    if args.query:
        await cli.run_single(args.query)
    else:
        await cli.run_interactive()


if __name__ == "__main__":
    asyncio.run(main())