"""Discord Gateway — OmniCore bot for Discord.

DNA: Hermes gateway + Discord API.

Usage:
    from gateway.discord import DiscordGateway
    bot = DiscordGateway(token="your-bot-token")
    bot.start()
"""

import json
import time
import asyncio
import threading
from typing import Optional, Callable


class DiscordGateway:
    """Discord bot gateway for OmniCore.

    Requires: httpx (pip install httpx)
    Setup: Create bot at https://discord.com/developers/applications
           Invite with: bot + applications.commands + Send Messages
    """

    API_BASE = "https://discord.com/api/v10"

    def __init__(self, token: str = "", prefix: str = "!"):
        self.token = token
        self.prefix = prefix
        self._agent = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._commands: dict[str, tuple[Callable, str]] = {}
        self._session_id = ""
        self._sequence = 0
        self._heartbeat_interval = 41250  # Default

        # Register built-in commands
        self._register_builtins()

    # ── Commands ──────────────────────────────────────────────────────

    def _register_builtins(self):
        self.command("ping", lambda args, msg: "pong!", "Ping the bot")
        self.command("status", self._cmd_status, "Show OmniCore status")
        self.command("help", self._cmd_help, "Show available commands")

    def command(self, name: str, handler: Callable, description: str = ""):
        """Register a chat command: !name → handler(args, message)."""
        self._commands[name] = (handler, description)

    def _cmd_status(self, args: str, msg: dict) -> str:
        return f"""OmniCore v3 — Discord Gateway
  Commands: {len(self._commands)} registered
  Prefix: {self.prefix}
  Status: Online"""

    def _cmd_help(self, args: str, msg: dict) -> str:
        lines = ["**OmniCore Commands:**"]
        for name, (_, desc) in self._commands.items():
            lines.append(f"  `{self.prefix}{name}` — {desc}")
        return "\n".join(lines)

    # ── API ───────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bot {self.token}",
            "Content-Type": "application/json",
        }

    async def _api_get(self, path: str) -> dict:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.API_BASE}{path}",
                headers=self._headers(),
                timeout=30
            )
            return resp.json() if resp.status_code == 200 else {}

    async def _api_post(self, path: str, data: dict) -> dict:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.API_BASE}{path}",
                headers=self._headers(),
                json=data,
                timeout=30
            )
            return resp.json() if resp.status_code in (200, 204) else {"error": resp.status_code}

    async def send_message(self, channel_id: str, content: str):
        """Send a message to a Discord channel."""
        return await self._api_post(
            f"/channels/{channel_id}/messages",
            {"content": content[:2000]}  # Discord limit
        )

    async def send_embed(self, channel_id: str, title: str, 
                          description: str, color: int = 0x1a1a1a):
        """Send a rich embed message."""
        return await self._api_post(
            f"/channels/{channel_id}/messages",
            {
                "embeds": [{
                    "title": title,
                    "description": description[:4096],
                    "color": color,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }]
            }
        )

    async def send_code(self, channel_id: str, code: str, language: str = "python"):
        """Send a code block."""
        await self.send_message(
            channel_id,
            f"```{language}\n{code[:1990]}\n```"
        )

    # ── Bot loop ──────────────────────────────────────────────────────

    def start(self):
        """Start the Discord bot in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _run(self):
        asyncio.run(self._bot_loop())

    async def _bot_loop(self):
        """Main bot loop: gateway → events → handle."""
        import httpx

        # 1. Get gateway URL
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.API_BASE}/gateway/bot",
                headers=self._headers()
            )
            gateway = resp.json()
            gw_url = gateway.get("url", "wss://gateway.discord.gg/?v=10&encoding=json")

        # 2. Connect to WebSocket
        import websockets
        ws_url = f"{gw_url}/?v=10&encoding=json"

        try:
            async with websockets.connect(ws_url) as ws:
                # Receive HELLO
                hello = json.loads(await ws.recv())
                self._heartbeat_interval = hello["d"]["heartbeat_interval"] / 1000

                # Start heartbeat
                asyncio.create_task(self._heartbeat(ws))

                # Identify
                await ws.send(json.dumps({
                    "op": 2,
                    "d": {
                        "token": self.token,
                        "intents": 512 + 32768,  # GUILD_MESSAGES + MESSAGE_CONTENT
                        "properties": {"os": "linux", "browser": "omnicore", "device": "omnicore"},
                    }
                }))

                # Event loop
                while self._running:
                    try:
                        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                        await self._handle_event(msg)
                    except asyncio.TimeoutError:
                        continue
                    except Exception:
                        break
        except Exception as e:
            if self._running:
                print(f"Discord gateway disconnected: {e}")
                # Reconnect after 5 seconds
                await asyncio.sleep(5)

    async def _heartbeat(self, ws):
        while self._running:
            await ws.send(json.dumps({"op": 1, "d": self._sequence}))
            await asyncio.sleep(self._heartbeat_interval)

    async def _handle_event(self, event: dict):
        """Handle a Discord gateway event."""
        op = event.get("op", 0)

        if op == 0:  # DISPATCH
            event_type = event.get("t", "")
            data = event.get("d", {})
            self._sequence = event.get("s", 0)

            if event_type == "MESSAGE_CREATE":
                await self._handle_message(data)

    async def _handle_message(self, msg: dict):
        """Handle an incoming message."""
        content = msg.get("content", "")
        channel_id = msg.get("channel_id", "")
        author = msg.get("author", {})
        author_name = author.get("username", "unknown")

        # Ignore own messages
        if author.get("bot"):
            return

        # Check prefix
        if content.startswith(self.prefix):
            parts = content[len(self.prefix):].strip().split(maxsplit=1)
            cmd_name = parts[0].lower() if parts else ""
            args = parts[1] if len(parts) > 1 else ""

            if cmd_name in self._commands:
                handler, _ = self._commands[cmd_name]
                try:
                    response = handler(args, msg)
                    if response:
                        await self.send_message(channel_id, str(response))
                except Exception as e:
                    await self.send_message(channel_id, f"Error: {e}")
            else:
                await self.send_message(
                    channel_id,
                    f"Unknown command: `{cmd_name}`. Try `{self.prefix}help`"
                )

    def is_running(self) -> bool:
        return self._running