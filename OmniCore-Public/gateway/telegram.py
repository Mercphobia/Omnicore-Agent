"""Telegram bot gateway — polling-based bridge to Telegram Bot API.

DNA: Async-first, httpx-powered, supports text/code blocks/long message
splitting. Designed as a drop-in connector for OmniCore's agent engine.

Usage:
    gw = TelegramGateway()
    gw.register_command("start", handle_start)
    await gw.start_bot("YOUR_BOT_TOKEN")
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable, Optional

import httpx

# ── Constants ───────────────────────────────────────────────

TELEGRAM_API_BASE = "https://api.telegram.org/bot"
MAX_MESSAGE_LENGTH = 4096  # Telegram's max message length
POLLING_TIMEOUT = 30  # Long polling timeout in seconds
RETRY_DELAY = 5  # Seconds to wait after a connection error

logger = logging.getLogger("omnicore.gateway.telegram")


# ── TelegramGateway ─────────────────────────────────────────

class TelegramGateway:
    """Async Telegram bot gateway using httpx.

    Connects OmniCore to Telegram via the Bot API with long polling.
    Supports text messages, code blocks (```), and automatic splitting
    of messages that exceed Telegram's 4096-character limit.

    Commands are registered with register_command() and dispatched
    when users send /command messages.

    Lifecycle:
        gw = TelegramGateway()
        gw.register_command("start", lambda chat_id, args, ctx: "Hello!")
        await gw.start_bot(token)
        # ... bot runs until stop_bot() or signal
        await gw.stop_bot()
    """

    def __init__(self, base_url: str = TELEGRAM_API_BASE):
        """Initialize the Telegram gateway.

        Args:
            base_url: Base URL for Telegram Bot API.
                      Default: https://api.telegram.org/bot
        """
        self.base_url = base_url.rstrip("/")
        self._token: str = ""
        self._client: Optional[httpx.AsyncClient] = None
        self._running: bool = False
        self._poll_task: Optional[asyncio.Task] = None

        # Command registry: {name: handler}
        self._commands: dict[str, Callable] = {}

        # Message handler (non-command messages)
        self._message_handler: Optional[Callable] = None

        # Statistics
        self._messages_processed: int = 0
        self._errors: int = 0
        self._start_time: float = 0.0

    # ── Properties ────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        """True if the bot is actively polling."""
        return self._running

    @property
    def stats(self) -> dict:
        """Runtime statistics."""
        import time
        return {
            "running": self._running,
            "messages_processed": self._messages_processed,
            "errors": self._errors,
            "commands_registered": len(self._commands),
            "uptime_seconds": time.time() - self._start_time if self._start_time else 0,
        }

    # ── Bot lifecycle ─────────────────────────────────────

    async def start_bot(self, token: str) -> None:
        """Start the bot and begin polling for updates.

        Args:
            token: Telegram Bot API token from @BotFather.

        Raises:
            RuntimeError: If the bot is already running.
            ConnectionError: If the token is invalid or API unreachable.
        """
        if self._running:
            raise RuntimeError("Bot is already running. Call stop_bot() first.")

        self._token = token

        # Create httpx client
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=5),
        )

        # Validate token
        me = await self._api_call("getMe")
        if not me.get("ok"):
            await self._client.aclose()
            self._client = None
            raise ConnectionError(
                f"Invalid token or API unreachable: {me.get('description', 'unknown error')}"
            )

        bot_info = me.get("result", {})
        bot_name = bot_info.get("first_name", "Unknown")
        bot_username = bot_info.get("username", "unknown")
        logger.info(f"Bot connected: @{bot_username} ({bot_name})")

        self._running = True
        self._start_time = __import__("time").time()
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop_bot(self) -> None:
        """Stop the bot and clean up resources."""
        self._running = False

        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

        if self._client:
            await self._client.aclose()
            self._client = None

        logger.info("Bot stopped.")

    # ── Command registration ──────────────────────────────

    def register_command(self, command: str, handler: Callable) -> None:
        """Register a bot command handler.

        Args:
            command: Command name without the '/' prefix.
            handler: Async or sync callable(chat_id, args, context) -> str.
                     Context contains: message, from_user, chat, date.
        """
        self._commands[command.lower()] = handler

    def set_message_handler(self, handler: Callable) -> None:
        """Set handler for non-command messages.

        Args:
            handler: Callable(chat_id, text, context) -> str.
        """
        self._message_handler = handler

    def list_commands(self) -> list[str]:
        """List all registered bot commands."""
        return sorted(self._commands.keys())

    # ── Polling loop ──────────────────────────────────────

    async def _poll_loop(self) -> None:
        """Main polling loop using long-polling getUpdates."""
        offset = 0

        while self._running:
            try:
                updates = await self._api_call(
                    "getUpdates",
                    offset=offset,
                    timeout=POLLING_TIMEOUT,
                    allowed_updates=["message", "edited_message"],
                )

                if updates.get("ok"):
                    for update in updates.get("result", []):
                        offset = max(offset, update["update_id"] + 1)

                        # Handle message
                        if "message" in update:
                            asyncio.create_task(
                                self._handle_update(update["message"])
                            )
                        elif "edited_message" in update:
                            asyncio.create_task(
                                self._handle_update(update["edited_message"])
                            )

            except asyncio.CancelledError:
                break
            except httpx.ReadTimeout:
                # Long polling timeout — normal, retry
                continue
            except httpx.ConnectError as e:
                logger.warning(f"Connection error: {e}. Retrying in {RETRY_DELAY}s...")
                self._errors += 1
                await asyncio.sleep(RETRY_DELAY)
            except Exception as e:
                logger.error(f"Poll error: {type(e).__name__}: {e}")
                self._errors += 1
                await asyncio.sleep(RETRY_DELAY)

    # ── Message handling ──────────────────────────────────

    async def _handle_update(self, message: dict) -> None:
        """Process an incoming Telegram message."""
        try:
            chat_id = message.get("chat", {}).get("id")
            text = message.get("text", "").strip()
            from_user = message.get("from", {})
            message_id = message.get("message_id")

            if not chat_id or not text:
                return

            context = {
                "message": message,
                "from_user": from_user,
                "chat": message.get("chat", {}),
                "date": message.get("date"),
                "message_id": message_id,
            }

            # Check for command
            if text.startswith("/"):
                response = await self._dispatch_command(chat_id, text, context)
            else:
                response = await self._dispatch_message(chat_id, text, context)

            if response:
                await self.send_response(chat_id, response)

            self._messages_processed += 1

        except Exception as e:
            logger.error(f"Handle error: {type(e).__name__}: {e}")
            self._errors += 1

    async def _dispatch_command(
        self, chat_id: int, text: str, context: dict
    ) -> Optional[str]:
        """Route a /command to its registered handler."""
        # Parse command and args
        parts = text.split(maxsplit=1)
        cmd = parts[0][1:].lower()  # Strip leading /
        cmd = cmd.split("@")[0]  # Strip bot username mention
        args_str = parts[1] if len(parts) > 1 else ""

        handler = self._commands.get(cmd)
        if handler is None:
            return (
                f"Unknown command: /{cmd}\n"
                f"Available commands: {', '.join(f'/{c}' for c in self.list_commands())}"
            )

        try:
            result = handler(chat_id, args_str, context)
            if asyncio.iscoroutine(result):
                result = await result
            return str(result) if result is not None else None
        except Exception as e:
            logger.error(f"Command /{cmd} error: {type(e).__name__}: {e}")
            return f"Error executing /{cmd}: {type(e).__name__}: {e}"

    async def _dispatch_message(
        self, chat_id: int, text: str, context: dict
    ) -> Optional[str]:
        """Route a non-command message."""
        if self._message_handler:
            try:
                result = self._message_handler(chat_id, text, context)
                if asyncio.iscoroutine(result):
                    result = await result
                return str(result) if result is not None else None
            except Exception as e:
                logger.error(f"Message handler error: {type(e).__name__}: {e}")
                return None
        return None

    # ── Sending responses ─────────────────────────────────

    async def send_response(
        self,
        chat_id: int,
        text: str,
        parse_mode: str = "Markdown",
        reply_to_message_id: Optional[int] = None,
    ) -> list[dict]:
        """Send a text response to a chat.

        Automatically splits long messages (>4096 chars) into multiple
        messages. Code blocks (```) are properly handled across splits.

        Args:
            chat_id: Target chat ID.
            text: Response text. Supports Markdown formatting.
            parse_mode: 'Markdown', 'HTML', or None for plain text.
            reply_to_message_id: Optional message ID to reply to.

        Returns:
            List of API response dicts, one per sent message.
        """
        if not self._client or not self._running:
            return []

        results = []
        chunks = self._split_message(text)

        for i, chunk in enumerate(chunks):
            # Ensure unclosed code blocks don't break formatting
            chunk = self._fix_code_blocks(chunk, i > 0, i < len(chunks) - 1)

            params: dict[str, Any] = {
                "chat_id": chat_id,
                "text": chunk,
            }

            if parse_mode and parse_mode.lower() != "none":
                params["parse_mode"] = parse_mode

            if reply_to_message_id and i == 0:
                params["reply_to_message_id"] = reply_to_message_id

            result = await self._api_call("sendMessage", **params)
            results.append(result)

            # Small delay between chunks to preserve order
            if i < len(chunks) - 1:
                await asyncio.sleep(0.3)

        return results

    async def send_code(
        self, chat_id: int, code: str, language: str = ""
    ) -> list[dict]:
        """Send a code block to a chat.

        Args:
            chat_id: Target chat ID.
            code: Source code to send.
            language: Optional language for syntax highlighting.

        Returns:
            List of API response dicts.
        """
        text = f"```{language}\n{code}\n```"
        return await self.send_response(chat_id, text)

    # ── Message splitting ─────────────────────────────────

    @staticmethod
    def _split_message(text: str) -> list[str]:
        """Split a long message into Telegram-compatible chunks.

        Splits at newlines where possible, respecting code blocks.
        Each chunk is at most MAX_MESSAGE_LENGTH characters.

        Args:
            text: Full message text.

        Returns:
            List of message chunks.
        """
        if len(text) <= MAX_MESSAGE_LENGTH:
            return [text]

        chunks = []
        current = ""
        in_code_block = False

        for line in text.split("\n"):
            # Track code block state
            if line.strip().startswith("```"):
                in_code_block = not in_code_block

            # If adding this line exceeds the limit
            if len(current) + len(line) + 1 > MAX_MESSAGE_LENGTH:
                if current:
                    # Close open code block before splitting
                    if in_code_block:
                        current += "\n```"
                        in_code_block = False
                    chunks.append(current)

                # Start new chunk
                current = line
                # Reopen code block if needed
                if line.strip().startswith("```"):
                    in_code_block = not in_code_block
            else:
                if current:
                    current += "\n" + line
                else:
                    current = line

        if current:
            chunks.append(current)

        return chunks

    @staticmethod
    def _fix_code_blocks(text: str, is_continuation: bool, is_not_last: bool) -> str:
        """Ensure code blocks are properly closed/open across splits."""
        # Count opening and closing ```
        opens = len(re.findall(r"```\w*\n", text))
        closes = len(re.findall(r"\n```", text))
        # Also count standalone ``` at very start/end
        if text.startswith("```"):
            opens += 1
        if text.endswith("```"):
            closes += 1

        # If more opens than closes, close the block
        if opens > closes:
            text += "\n```"

        return text

    # ── API communication ─────────────────────────────────

    async def _api_call(self, method: str, **params) -> dict:
        """Make an API call to Telegram Bot API.

        Args:
            method: API method name (e.g. 'sendMessage', 'getUpdates').
            **params: Method parameters.

        Returns:
            Parsed JSON response dict.
        """
        if not self._client:
            return {"ok": False, "description": "Client not initialized"}

        url = f"{self.base_url}/{self._token}/{method}"

        try:
            response = await self._client.post(url, json=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"API HTTP {e.response.status_code}: {e.response.text[:200]}")
            return {
                "ok": False,
                "description": f"HTTP {e.response.status_code}",
                "error_code": e.response.status_code,
            }
        except httpx.RequestError as e:
            logger.error(f"API request error: {e}")
            return {"ok": False, "description": str(e)}

    # ── Utility: set bot commands menu ────────────────────

    async def set_bot_commands(self) -> dict:
        """Register all commands with Telegram's bot menu.

        Returns:
            API response dict.
        """
        commands = [
            {"command": cmd, "description": self._commands[cmd].__doc__ or cmd}
            for cmd in sorted(self._commands)
        ]
        return await self._api_call("setMyCommands", commands=commands)

    # ── Convenience: quick start for testing ──────────────

    @classmethod
    async def quick_start(
        cls,
        token: str,
        message_handler: Optional[Callable] = None,
    ) -> TelegramGateway:
        """Create and start a basic bot in one call.

        Args:
            token: Bot token.
            message_handler: Function(chat_id, text, context) -> str
                             Called for every non-command message.

        Returns:
            Running TelegramGateway instance.
        """
        gw = cls()

        # Default /start and /help commands
        def cmd_start(chat_id, args, ctx):
            username = ctx.get("from_user", {}).get("first_name", "there")
            return (
                f"Hello {username}! 👋\n\n"
                f"I'm OmniCore, your AI agent.\n"
                f"Type /help to see what I can do."
            )

        def cmd_help(chat_id, args, ctx):
            cmds = gw.list_commands()
            return "**Available commands:**\n" + "\n".join(
                f"/{c}" for c in cmds
            )

        gw.register_command("start", cmd_start)
        gw.register_command("help", cmd_help)

        if message_handler:
            gw.set_message_handler(message_handler)

        await gw.start_bot(token)
        return gw


# ── Self-test ───────────────────────────────────────────────

async def _self_test():
    """Quick self-test (requires a bot token)."""
    import os

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("TELEGRAM_BOT_TOKEN not set. Skipping live test.")
        print("\nTesting utility methods...")

        gw = TelegramGateway()

        # Test message splitting
        long_text = "Line " + "X\nLine ".join(str(i) for i in range(2000))
        chunks = gw._split_message(long_text)
        print(f"Message split into {len(chunks)} chunks")
        print(f"  Chunk 1: {len(chunks[0])} chars")
        if len(chunks) > 1:
            print(f"  Chunk 2: {len(chunks[1])} chars")

        # Test code block splitting
        code_text = "```python\n" + "print('hello')\n" * 200 + "```"
        code_chunks = gw._split_message(code_text)
        print(f"\nCode block split into {len(code_chunks)} chunks")

        # Test command registration
        gw.register_command("ping", lambda cid, a, ctx: "pong")
        gw.register_command("echo", lambda cid, a, ctx: a)
        print(f"\nCommands: {gw.list_commands()}")

        print("\nAll utility tests passed.")
        print("\nTo test live: TELEGRAM_BOT_TOKEN=xxx python -m gateway.telegram")
        return

    print(f"Starting bot with token: {token[:8]}...")

    gw = TelegramGateway()

    def handle_message(chat_id, text, ctx):
        return f"You said: {text}"

    gw.register_command("ping", lambda cid, a, ctx: "🏓 pong!")
    gw.set_message_handler(handle_message)

    await gw.start_bot(token)
    print("Bot is running. Press Ctrl+C to stop.")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        await gw.stop_bot()
        print("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(_self_test())