"""Slash command system — register, parse, and execute /commands.

DNA: CLI-style command routing with permission model. Designed for chat
interfaces where users (or agents) can trigger special actions with /prefix.

Built-in commands:
    /help          — Show all commands or help for a specific command
    /tools         — List available tools
    /status        — Show system status and health
    /reset         — Reset conversation context
    /blacksmith    — Trigger Blacksmith skill (code generation)
    /ponytail      — Trigger Ponytail skill (design generation)
    /tokenforge    — Trigger Tokenforge (token analysis/generation)

Usage:
    cmds = SlashCommands()
    cmds.register("hello", handler, "Say hello", "everyone")
    result = cmds.parse("/hello world")
    if result:
        output = cmds.execute(result.command, result.args, context)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ── Data structures ─────────────────────────────────────────

@dataclass
class CommandDefinition:
    """A registered slash command."""
    name: str
    handler: Callable
    description: str
    permission: str = "everyone"  # everyone, authenticated, admin
    usage: str = ""
    category: str = "general"


@dataclass
class ParsedCommand:
    """Result of parsing a slash command from text."""
    command: str
    args: list[str]
    raw: str


# ── SlashCommands ───────────────────────────────────────────

class SlashCommands:
    """Register, parse, and execute slash commands.

    Commands are registered with a name, handler callable, description,
    and optional permission level. The parser detects patterns like
    /command arg1 arg2 from any text input.

    Handlers receive (args: list[str], context: dict) and should
    return a string response.
    """

    def __init__(self):
        self._commands: dict[str, CommandDefinition] = {}
        self._aliases: dict[str, str] = {}  # alias → canonical name

        # ── Register built-in commands ─────────────────
        self._register_builtins()

    # ── Registration ──────────────────────────────────────

    def register(
        self,
        command: str,
        handler: Callable,
        description: str = "",
        permission: str = "everyone",
        usage: str = "",
        category: str = "general",
    ) -> None:
        """Register a slash command.

        Args:
            command: Command name (without the / prefix).
            handler: Callable that receives (args: list[str], context: dict)
                     and returns a string.
            description: Short description for /help listing.
            permission: Access level: 'everyone', 'authenticated', 'admin'.
            usage: Usage pattern, e.g. '<name> [--verbose]'.
            category: Group for organization: 'general', 'tools', 'skills', 'admin'.
        """
        cmd = command.lower().lstrip("/")
        self._commands[cmd] = CommandDefinition(
            name=cmd,
            handler=handler,
            description=description,
            permission=permission,
            usage=usage,
            category=category,
        )

    def alias(self, alias: str, target: str) -> None:
        """Register an alias for an existing command.

        Args:
            alias: The alias name (without /).
            target: The canonical command name.
        """
        self._aliases[alias.lower()] = target.lower()

    def unregister(self, command: str) -> bool:
        """Remove a registered command.

        Args:
            command: Command name to remove.

        Returns:
            True if the command was found and removed.
        """
        cmd = command.lower().lstrip("/")
        if cmd in self._commands:
            del self._commands[cmd]
            # Also remove any aliases pointing to it
            self._aliases = {
                k: v for k, v in self._aliases.items() if v != cmd
            }
            return True
        return False

    # ── Parsing ───────────────────────────────────────────

    def parse(self, text: str) -> Optional[ParsedCommand]:
        """Detect and parse a slash command from text.

        Supports: /cmd, /cmd arg1 arg2, /cmd "quoted arg"
        Does NOT match: URLs (https://...), paths (/usr/bin)

        Args:
            text: Raw input text that may contain a command.

        Returns:
            ParsedCommand if text starts with a valid /command,
            None otherwise.
        """
        if not text or not text.strip():
            return None

        stripped = text.strip()

        # Must start with /
        if not stripped.startswith("/"):
            return None

        # Not a URL or path
        if re.match(r"^/(?:/[^\s]|[^\s]+://)", stripped):
            return None

        # Split into command + args, respecting quotes
        parts = self._split_args(stripped)
        if not parts:
            return None

        cmd_name = parts[0][1:].lower()  # Strip leading /
        args = parts[1:]

        # Resolve alias
        cmd_name = self._aliases.get(cmd_name, cmd_name)

        if cmd_name not in self._commands:
            return None

        return ParsedCommand(command=cmd_name, args=args, raw=stripped)

    @staticmethod
    def _split_args(text: str) -> list[str]:
        """Split text into arguments, respecting quotes."""
        import shlex
        try:
            return shlex.split(text)
        except ValueError:
            # Fallback: simple space split
            return text.split()

    def is_command(self, text: str) -> bool:
        """Check if text starts with a recognized /command.

        Args:
            text: Input text to check.

        Returns:
            True if text is a recognized slash command.
        """
        return self.parse(text) is not None

    # ── Execution ─────────────────────────────────────────

    def execute(
        self,
        command: str,
        args: Optional[list[str]] = None,
        context: Optional[dict] = None,
    ) -> str:
        """Execute a slash command.

        Args:
            command: Command name (without / prefix).
            args: List of arguments to pass to handler.
            context: Optional context dict passed to handler
                     (e.g. {'user': ..., 'chat_id': ...}).

        Returns:
            Handler's response string, or an error message.
        """
        args = args or []
        context = context or {}

        cmd_name = command.lower().lstrip("/")
        cmd_name = self._aliases.get(cmd_name, cmd_name)

        cmd_def = self._commands.get(cmd_name)
        if cmd_def is None:
            available = ", ".join(sorted(self._commands.keys()))
            return f"Unknown command: /{cmd_name}. Available: {available}"

        # Permission check
        user_level = context.get("permission", "everyone")
        if not self._check_permission(cmd_def.permission, user_level):
            return (
                f"Permission denied: /{cmd_name} requires '{cmd_def.permission}' "
                f"access (you have '{user_level}')."
            )

        try:
            result = cmd_def.handler(args, context)
            return str(result) if result is not None else ""
        except Exception as e:
            return f"Command /{cmd_name} failed: {type(e).__name__}: {e}"

    @staticmethod
    def _check_permission(required: str, actual: str) -> bool:
        """Check if actual permission level satisfies required."""
        levels = {"everyone": 0, "authenticated": 1, "admin": 2}
        return levels.get(actual, 0) >= levels.get(required, 0)

    # ── Discovery ─────────────────────────────────────────

    def list_all(self) -> list[dict]:
        """List all registered commands with descriptions.

        Returns:
            List of dicts with name, description, permission, usage, category.
        """
        results = []
        for cmd in sorted(self._commands.values(), key=lambda c: c.name):
            results.append({
                "name": cmd.name,
                "description": cmd.description,
                "permission": cmd.permission,
                "usage": cmd.usage,
                "category": cmd.category,
            })
        return results

    def get_command(self, command: str) -> Optional[dict]:
        """Get details for a specific command.

        Args:
            command: Command name.

        Returns:
            Dict with command details or None.
        """
        cmd_name = command.lower().lstrip("/")
        cmd_name = self._aliases.get(cmd_name, cmd_name)
        cmd_def = self._commands.get(cmd_name)
        if cmd_def is None:
            return None
        return {
            "name": cmd_def.name,
            "description": cmd_def.description,
            "permission": cmd_def.permission,
            "usage": cmd_def.usage,
            "category": cmd_def.category,
        }

    def help(self, command: Optional[str] = None) -> str:
        """Get help text for a command or list all commands.

        Args:
            command: Specific command name, or None for overview.

        Returns:
            Formatted help text.
        """
        if command:
            return self._help_for(command)

        # Overview: group by category
        lines = ["**Slash Commands**\n"]
        by_category: dict[str, list[CommandDefinition]] = {}
        for cmd in self._commands.values():
            by_category.setdefault(cmd.category, []).append(cmd)

        for category in sorted(by_category):
            lines.append(f"*{category.title()}*:")
            for cmd in sorted(by_category[category], key=lambda c: c.name):
                alias_hint = ""
                for a, t in self._aliases.items():
                    if t == cmd.name:
                        alias_hint += f" (/{a})"
                        break
                lines.append(f"  **/{cmd.name}**{alias_hint} — {cmd.description}")
            lines.append("")

        lines.append("Type /help <command> for detailed help.")
        return "\n".join(lines)

    def _help_for(self, command: str) -> str:
        """Get detailed help for a specific command."""
        cmd_name = command.lower().lstrip("/")
        cmd_name = self._aliases.get(cmd_name, cmd_name)
        cmd_def = self._commands.get(cmd_name)

        if cmd_def is None:
            return f"No help available for unknown command: /{command}"

        lines = [
            f"**/{cmd_def.name}** — {cmd_def.description}",
            f"Permission: {cmd_def.permission}",
        ]
        if cmd_def.usage:
            lines.append(f"Usage: /{cmd_def.name} {cmd_def.usage}")
        else:
            lines.append(f"Usage: /{cmd_def.name}")

        # List aliases pointing to this command
        aliases = [a for a, t in self._aliases.items() if t == cmd_def.name]
        if aliases:
            aliases_str = ", ".join(f"/{a}" for a in aliases)
            lines.append(f"Aliases: {aliases_str}")

        return "\n".join(lines)

    @property
    def count(self) -> int:
        """Number of registered commands."""
        return len(self._commands)

    # ── Built-in commands ─────────────────────────────────

    def _register_builtins(self) -> None:
        """Register the standard built-in commands."""
        self.register(
            "help",
            self._cmd_help,
            "Show all commands or help for a specific command",
            usage="[command]",
            category="general",
        )
        self.register(
            "tools",
            self._cmd_tools,
            "List available tools",
            usage="[tool_name]",
            category="tools",
        )
        self.register(
            "status",
            self._cmd_status,
            "Show system status and health",
            category="general",
        )
        self.register(
            "reset",
            self._cmd_reset,
            "Reset conversation context",
            permission="authenticated",
            category="general",
        )
        self.register(
            "blacksmith",
            self._cmd_blacksmith,
            "Trigger Blacksmith code generation skill",
            usage="<task description>",
            category="skills",
        )
        self.register(
            "ponytail",
            self._cmd_ponytail,
            "Trigger Ponytail design generation skill",
            usage="<design description>",
            category="skills",
        )
        self.register(
            "tokenforge",
            self._cmd_tokenforge,
            "Trigger Tokenforge token analysis/generation",
            usage="<action> [args]",
            category="skills",
        )

        # Aliases
        self.alias("?", "help")
        self.alias("h", "help")

    # ── Built-in handlers ─────────────────────────────────

    def _cmd_help(self, args: list[str], context: dict) -> str:
        """Handler for /help."""
        if args:
            return self.help(args[0])
        return self.help()

    def _cmd_tools(self, args: list[str], context: dict) -> str:
        """Handler for /tools."""
        # Try to get tool registry from context or engine
        engine = context.get("engine")
        if engine and hasattr(engine, "registry"):
            registry = engine.registry
            tools = registry.list_all()
            lines = [f"**Available Tools** ({len(tools)})\n"]
            for t in tools:
                lines.append(f"  **{t.name}** — {t.description}")
            return "\n".join(lines)

        return (
            "**Available Tools**\n\n"
            "Tool registry not accessible in current context. "
            "Run `/status` to check engine connectivity."
        )

    def _cmd_status(self, args: list[str], context: dict) -> str:
        """Handler for /status."""
        import platform

        lines = [
            "**OmniCore Status**\n",
            f"  **Platform:** {platform.system()} {platform.release()}",
            f"  **Python:** {platform.python_version()}",
            f"  **Commands registered:** {self.count}",
        ]

        engine = context.get("engine")
        if engine:
            model = getattr(engine, "model_name", "unknown")
            lines.append(f"  **Model:** {model}")
            providers = getattr(engine, "providers", None)
            if providers:
                lines.append(f"  **Providers:** {len(providers)} loaded")

        return "\n".join(lines)

    def _cmd_reset(self, args: list[str], context: dict) -> str:
        """Handler for /reset."""
        engine = context.get("engine")
        if engine and hasattr(engine, "reset_conversation"):
            engine.reset_conversation()
            return "Conversation context reset. Fresh start."
        return (
            "Conversation reset requested. If using OmniCore engine, "
            "ensure engine.reset_conversation() is called."
        )

    def _cmd_blacksmith(self, args: list[str], context: dict) -> str:
        """Handler for /blacksmith — delegates to Blacksmith skill."""
        task = " ".join(args) if args else ""
        engine = context.get("engine")
        if engine and hasattr(engine, "run_skill"):
            result = engine.run_skill("blacksmith", task=task)
            return str(result) if result else "Blacksmith returned empty result."
        return (
            "Blacksmith skill invoked. Task: " + (task or "none specified") +
            "\n\nEngine skill runner not connected."
        )

    def _cmd_ponytail(self, args: list[str], context: dict) -> str:
        """Handler for /ponytail — delegates to Ponytail skill."""
        task = " ".join(args) if args else ""
        engine = context.get("engine")
        if engine and hasattr(engine, "run_skill"):
            result = engine.run_skill("ponytail", task=task)
            return str(result) if result else "Ponytail returned empty result."
        return (
            "Ponytail skill invoked. Task: " + (task or "none specified") +
            "\n\nEngine skill runner not connected."
        )

    def _cmd_tokenforge(self, args: list[str], context: dict) -> str:
        """Handler for /tokenforge — delegates to Tokenforge module."""
        action = args[0] if args else "status"
        extra = args[1:] if len(args) > 1 else []

        # Try importing tokenforge directly
        try:
            from core.tokenforge import Tokenforge
            tf = Tokenforge()

            if action == "status":
                return tf.status()
            elif action == "analyze":
                target = " ".join(extra) if extra else ""
                return tf.analyze(target)
            elif action == "generate":
                target = " ".join(extra) if extra else ""
                return tf.generate(target)
            else:
                return f"Unknown tokenforge action: {action}. Use: status, analyze, generate"
        except ImportError:
            return (
                f"Tokenforge action '{action}' requested. "
                "Tokenforge module not importable in current environment."
            )
        except Exception as e:
            return f"Tokenforge error: {type(e).__name__}: {e}"


# ── Self-test ───────────────────────────────────────────────

def _self_test():
    """Quick self-test of SlashCommands."""
    cmds = SlashCommands()

    # Register a custom command
    def echo_handler(args, ctx):
        return f"Echo: {' '.join(args)}"

    cmds.register("echo", echo_handler, "Echo back arguments", usage="<text...>")
    cmds.alias("e", "echo")

    print(f"Commands registered: {cmds.count}")
    print()

    # Test parsing
    tests = [
        "/help",
        "/help status",
        "/tools",
        "/status",
        "/echo hello world",
        "/e test alias",
        "/unknown",
        "https://example.com/path",
        "/usr/bin/python",
        "not a command",
    ]

    for text in tests:
        parsed = cmds.parse(text)
        if parsed:
            result = cmds.execute(parsed.command, parsed.args)
            preview = result[:80].replace("\n", " ")
            print(f"  /{parsed.command} {parsed.args} → {preview}")
        else:
            print(f"  '{text}' → no command detected")

    # Test list_all
    print(f"\nAll commands:")
    for c in cmds.list_all():
        print(f"  /{c['name']} [{c['permission']}] — {c['description']}")

    # Test help
    print(f"\nDetailed help for 'reset':")
    print(cmds.help("reset"))

    # Test permission
    print("\nPermission test (admin-only custom command):")
    cmds.register("admin_test", lambda a, c: "ok", "Admin only", "admin")
    r1 = cmds.execute("admin_test", [], {"permission": "everyone"})
    r2 = cmds.execute("admin_test", [], {"permission": "admin"})
    print(f"  everyone → {r1}")
    print(f"  admin → {r2}")

    print("\nSelf-test complete.")


if __name__ == "__main__":
    _self_test()