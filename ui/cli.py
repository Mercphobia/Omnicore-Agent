#!/usr/bin/env python3
"""OmniCore CLI v3 — Rich terminal UI with full command palette.
DNA: OpenCode (clean UX) + GPT (structured) + LTX-Quasar (cold execution).

Usage:
    omnicore                        Interactive REPL
    omnicore "query"                Single-shot
    omnicore --server               Start API server
    omnicore --dashboard            Open web dashboard
"""

import asyncio
import sys
import os
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.engine import OmniCore

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.syntax import Syntax
    from rich.table import Table
    from rich.prompt import Prompt
    from rich.layout import Layout
    from rich.live import Live
    RICH = True
except ImportError:
    RICH = False

BANNER = """
  ╔══════════════════════════════════════════════╗
  ║          OMNICORE v3 — OVERPOWER             ║
  ║     "The platform agents run on."            ║
  ╠══════════════════════════════════════════════╣
  ║  DNA: 31 sources fused | 356 files | 114K   ║
  ║  Providers: 11 | Skills: 56 | Tools: 35+     ║
  ║  Modules: 10 SUPERWEAPON | 4 Gateways        ║
  ╚══════════════════════════════════════════════╝
"""

HELP_TEXT = """
Commands:
  /help, /?          Show this
  /status            Show agent status (mode, provider, skills, tools)
  /sovereign [key]   Authenticate as operator (or show status)
  /reset             Clear conversation
  /history [N]       Show last N messages  
  /tools             List all tools
  /tool <name>       Describe a tool
  /skills            List loaded skills
  /config            Show configuration
  /model <id>        Switch model
  /todo [add|list|done]  Task management
  /scheduler [list|add]  Cron job management
  /benchmark         Run benchmark suite
  /tokenforge        Show API savings dashboard
  /blacksmith <code>  Forge code (6-strike)
  /pentest <target>  Run pentest recon
  /dashboard         Open web dashboard (port 8000)
  /server            Start API server on :8000
  /stream on|off     Toggle streaming
  /clear             Clear screen
  /quit, /exit, /q   Exit
"""

class OmniCoreCLI:
    """v3 CLI with full command palette, operator mode, and Rich UI."""

    def __init__(self, config_path: Path | None = None):
        self.agent = OmniCore(config_path=config_path)
        self.streaming = False
        self.console = Console() if RICH else None

    def _status_line(self) -> str:
        a = self.agent
        mode = "OPERATOR" if a.sovereign.is_operator else "PUBLIC"
        style = "green" if a.sovereign.is_operator else "yellow"
        return f"[{style}]{mode}[/{style}] | {a.provider.default_model} | {len(a.skills.list_all())} skills | {len(a.registry.list_all())} tools"

    async def run_interactive(self):
        self._print(BANNER)
        self._print(f"  {self._status_line()}")
        self._print("  Type /help for commands, /quit to exit\n")

        while True:
            try:
                user_input = Prompt.ask("▸") if RICH else input("▸ ").strip()
            except (KeyboardInterrupt, EOFError):
                self._print("\nExiting.")
                break

            if not user_input:
                continue
            if user_input.startswith("/"):
                result = await self._handle_command(user_input)
                if result == "quit":
                    break
                continue

            t0 = time.perf_counter()
            try:
                response = await self.agent.run(user_input)
                elapsed = (time.perf_counter() - t0) * 1000
                if RICH:
                    self.console.print(Panel(Markdown(response), title="OmniCore", subtitle=f"{elapsed:.0f}ms", border_style="cyan"))
                else:
                    print(f"\n{response}\n[{elapsed:.0f}ms]")
            except Exception as e:
                self._print(f"❌ Error: {e}")

    async def run_single(self, query: str):
        response = await self.agent.run(query)
        if RICH:
            self.console.print(Markdown(response))
        else:
            print(response)

    # ── Commands ──────────────────────────────────────────────────────

    async def _handle_command(self, cmd_line: str):
        parts = cmd_line[1:].lower().split()
        cmd, args = parts[0], parts[1:] if len(parts) > 1 else []
        handlers = {
            "help": self._cmd_help, "?": self._cmd_help,
            "status": self._cmd_status, "sovereign": self._cmd_sovereign,
            "reset": self._cmd_reset, "history": self._cmd_history,
            "tools": self._cmd_tools, "tool": self._cmd_tool,
            "skills": self._cmd_skills, "config": self._cmd_config,
            "model": self._cmd_model, "todo": self._cmd_todo,
            "scheduler": self._cmd_scheduler, "benchmark": self._cmd_benchmark,
            "tokenforge": self._cmd_tokenforge, "blacksmith": self._cmd_blacksmith,
            "pentest": self._cmd_pentest, "dashboard": self._cmd_dashboard,
            "server": self._cmd_server, "stream": self._cmd_stream,
            "clear": self._cmd_clear, "quit": lambda _: "quit",
            "exit": lambda _: "quit", "q": lambda _: "quit",
        }
        h = handlers.get(cmd)
        if h:
            return await h(args) if asyncio.iscoroutinefunction(h) else h(args)
        self._print(f"Unknown: /{cmd}. Type /help")
        return None

    async def _cmd_help(self, _): self._print(HELP_TEXT)
    
    async def _cmd_status(self, _):
        a = self.agent
        mode = "🔓 OPERATOR (full access)" if a.sovereign.is_operator else "🔒 PUBLIC (PersonaCage enforced)"
        self._print(f"  Mode: {mode}")
        self._print(f"  Provider: {a.provider.default_model}")
        self._print(f"  Skills: {len(a.skills.list_all())} loaded")
        self._print(f"  Tools: {len(a.registry.list_all())} registered")
        self._print(f"  Session: {a.session_id}")
        self._print(f"  PersonaCage: {'DISABLED' if a.sovereign.is_operator else 'ENFORCED'}")
        self._print(f"  Jailbreak SHIELD: {'DISABLED' if a.sovereign.is_operator else 'ACTIVE'}")
        self._print(f"  TokenForge budget: {'UNLIMITED' if a.sovereign.is_operator else f'${a.tokenforge.budget_per_task:.2f}/task'}")

    async def _cmd_sovereign(self, args):
        if not args:
            self._print(f"  Mode: {'OPERATOR' if self.agent.sovereign.is_operator else 'PUBLIC'}")
            self._print("  Usage: /sovereign <master-key>")
            return
        if self.agent.sovereign.authenticate(args[0]):
            self._print("  ✓ OPERATOR MODE — all restrictions lifted. PersonaCage: OFF. SWORD: ON.")
        else:
            self._print("  ✗ Invalid key.")

    async def _cmd_reset(self, _): self.agent.reset(); self._print("  ✓ Reset.")

    async def _cmd_history(self, args):
        n = int(args[0]) if args and args[0].isdigit() else 10
        for i, msg in enumerate(self.agent.history[-n:], 1):
            role = msg.get("role", "?")
            content = str(msg.get("content", ""))[:200]
            icon = {"user":"👤","assistant":"🤖","tool":"🔧"}.get(role,"  ")
            self._print(f"  {i}. {icon} [{role}] {content}")

    async def _cmd_tools(self, _):
        tools = self.agent.registry.list_all()
        if RICH:
            t = Table(title="Tools"); t.add_column("Name"); t.add_column("Description"); t.add_column("Lock")
            for x in tools: t.add_row(x.name, x.description[:80], "🔒" if x.requires_approval else "")
            self.console.print(t)
        else:
            for x in tools: self._print(f"  {x.name}: {x.description[:80]}")

    async def _cmd_tool(self, args):
        if not args: self._print("Usage: /tool <name>"); return
        t = self.agent.registry.get(args[0])
        if t: self._print(f"  {t.name}: {t.description}\n  Params: {t.parameters}\n  Approval: {t.requires_approval}")
        else: self._print(f"  Not found: {args[0]}")

    async def _cmd_skills(self, _):
        skills = self.agent.skills.list_all()
        for s in skills: self._print(f"  {s.name}: {s.description[:80]}")

    async def _cmd_config(self, _):
        c = self.agent.config
        self._print(f"  Provider: {c.get('provider',{}).get('default','?')}")
        self._print(f"  Model: {self.agent.provider.default_model}")
        self._print(f"  Budget: ${c.get('agent',{}).get('budget_per_task',0.10):.2f}/task")

    async def _cmd_model(self, args):
        if not args: self._print(f"  Current: {self.agent.provider.default_model}"); return
        self._print(f"  Model override: {args[0]} (next request)")

    async def _cmd_todo(self, args):
        try:
            from core.todo import TodoList
            todo = TodoList()
            if not args: self._print(todo.dashboard()); return
            sub = args[0]
            if sub == "add":
                todo.add(" ".join(args[1:]) if len(args)>1 else "Untitled")
                self._print("  ✓ Added")
            elif sub == "list": self._print(todo.dashboard())
            elif sub == "done" and len(args)>1: todo.done(args[1]); self._print("  ✓ Done")
            else: self._print("  Usage: /todo [add|list|done]")
        except Exception as e: self._print(f"  Error: {e}")

    async def _cmd_scheduler(self, args):
        try:
            from core.scheduler import Scheduler
            s = Scheduler()
            self._print(f"  Jobs: {len(s.list_jobs())}")
            for j in s.list_jobs(): self._print(f"    {j['name']} [{j['schedule']}] next: {j.get('next_run','?')}")
        except Exception as e: self._print(f"  Error: {e}")

    async def _cmd_benchmark(self, _):
        try:
            from tools.benchmark_suite import BenchmarkSuite
            b = BenchmarkSuite()
            results = b.run_builtins()
            if RICH:
                t = Table(title="Benchmark Results"); t.add_column("Task"); t.add_column("Ops/sec"); t.add_column("Time")
                for r in results: t.add_row(r['task'], f"{r.get('ops_per_sec',0):.0f}", f"{r.get('total_time_ms',0):.1f}ms")
                self.console.print(t)
            else:
                for r in results: self._print(f"  {r['task']}: {r.get('ops_per_sec',0):.0f} ops/sec")
            self._print(f"  Mean: {sum(r.get('ops_per_sec',0) for r in results)/len(results):.0f} ops/sec")
        except Exception as e: self._print(f"  Error: {e}")

    async def _cmd_tokenforge(self, _):
        self._print(self.agent.tokenforge.dashboard())

    async def _cmd_blacksmith(self, args):
        self._print("  ⚒ BLACKSMITH 6-STRIKE FORGE")
        self._print("  1. MELT → 2. PURIFY → 3. ALLOY → 4. HAMMER → 5. QUENCH → 6. SHARPEN")
        self._print("  Activate with: /blacksmith forge|armory|cataclysm")

    async def _cmd_pentest(self, args):
        if not args: self._print("Usage: /pentest <target-domain>"); return
        self._print(f"  🔍 Recon: {args[0]}...")
        try:
            from tools.pentest.recon import subdomain_enum, tech_fingerprint
            subs = subdomain_enum(args[0])
            tech = tech_fingerprint(f"https://{args[0]}")
            self._print(subs)
            self._print(tech)
        except Exception as e: self._print(f"  Error: {e}")

    async def _cmd_dashboard(self, _):
        import webbrowser
        webbrowser.open("http://localhost:8000")
        self._print("  Opening dashboard at http://localhost:8000 ...")

    async def _cmd_server(self, _):
        self._print("  Starting API server on http://0.0.0.0:8000 ...")
        import uvicorn
        from ui.api import app
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

    async def _cmd_stream(self, args):
        if args and args[0] in ("on","1"): self.streaming = True; self._print("Streaming: ON")
        elif args and args[0] in ("off","0"): self.streaming = False; self._print("Streaming: OFF")
        else: self._print(f"Streaming: {'ON' if self.streaming else 'OFF'}")

    async def _cmd_clear(self, _):
        if RICH: self.console.clear()
        else: print("\033[2J\033[H", end="")

    def _print(self, text):
        if RICH: self.console.print(text)
        else: print(text)


# ── Entry point ──────────────────────────────────────────────────────

async def main():
    import argparse
    p = argparse.ArgumentParser(description="OmniCore v3 — Autonomous Hyper-Agent")
    p.add_argument("query", nargs="?", help="Single query")
    p.add_argument("--config", type=Path, help="Config path")
    p.add_argument("--model", help="Model override")
    p.add_argument("--stream", action="store_true", help="Streaming")
    p.add_argument("--server", action="store_true", help="Start API server")
    p.add_argument("--version", action="store_true", help="Show version")
    args = p.parse_args()

    if args.version:
        print("OmniCore v3.1.0 — 356 files | 114K lines | 10 SUPERWEAPON | 11 providers")
        return

    if args.server:
        import uvicorn
        from ui.api import app
        print("OmniCore API: http://0.0.0.0:8000 | Docs: http://0.0.0.0:8000/docs")
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
        return

    cli = OmniCoreCLI(config_path=args.config)
    if args.stream: cli.streaming = True
    if args.query: await cli.run_single(args.query)
    else: await cli.run_interactive()

if __name__ == "__main__":
    asyncio.run(main())