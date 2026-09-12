"""WhatsApp Gateway — OmniCore bridge to WhatsApp.

DNA: Baileys webhook + HTTP bridge.

Setup:
    1. Use Baileys (Node.js) or whatsapp-web.js as bridge
    2. Or use Twilio/WhatsApp Business API
    3. This module provides the Python-side handler

Requires: httpx
"""

import json
import time
import asyncio
import threading
import hashlib
import hmac
from typing import Optional, Callable
from urllib.parse import urlencode


class WhatsAppGateway:
    """WhatsApp gateway for OmniCore.

    Supports two modes:
    1. Webhook mode: Receive messages from Baileys/WhatsApp bridge
    2. API mode: Send/receive via WhatsApp Business API (Meta)

    For personal use: Run Baileys bridge (Node.js) → POST to this handler.
    For business: Use Meta WhatsApp Cloud API.
    """

    def __init__(self, mode: str = "webhook", verify_token: str = ""):
        self.mode = mode  # webhook | cloud_api
        self.verify_token = verify_token or "omnicore_verify_token"
        self._agent = None
        self._commands: dict[str, tuple[Callable, str]] = {}
        self._message_handler: Optional[Callable] = None
        self._phone_number_id = ""
        self._access_token = ""

        self._register_builtins()

    # ── Commands ──────────────────────────────────────────────────────

    def _register_builtins(self):
        self.command("ping", lambda args, sender: "pong! 🏓", "Ping")
        self.command("status", self._cmd_status, "OmniCore status")
        self.command("help", self._cmd_help, "Commands list")

    def command(self, name: str, handler: Callable, description: str = ""):
        self._commands[name] = (handler, description)

    def on_message(self, handler: Callable):
        """Register a handler for all incoming messages."""
        self._message_handler = handler

    def _cmd_status(self, args: str, sender: str) -> str:
        return f"""🤖 *OmniCore v3 — WhatsApp Gateway*
  Commands: {len(self._commands)} registered
  Mode: {self.mode}
  Status: Online"""

    def _cmd_help(self, args: str, sender: str) -> str:
        lines = ["*Commands:*"]
        for name, (_, desc) in self._commands.items():
            lines.append(f"  • `/{name}` — {desc}")
        return "\n".join(lines)

    # ── Webhook handler (for Flask/FastAPI integration) ───────────────

    def verify_webhook(self, query_params: dict) -> tuple[int, str]:
        """Verify WhatsApp webhook challenge.

        GET /webhook?hub.mode=subscribe&hub.verify_token=xxx&hub.challenge=yyy
        """
        mode = query_params.get("hub.mode", "")
        token = query_params.get("hub.verify_token", "")
        challenge = query_params.get("hub.challenge", "")

        if mode == "subscribe" and token == self.verify_token:
            return 200, challenge
        return 403, "Verification failed"

    def handle_webhook(self, body: dict) -> dict:
        """Handle incoming WhatsApp webhook event.

        POST /webhook with WhatsApp message payload.
        """
        try:
            # Extract message from WhatsApp webhook format
            entries = body.get("entry", [])
            for entry in entries:
                changes = entry.get("changes", [])
                for change in changes:
                    messages = change.get("value", {}).get("messages", [])
                    for msg in messages:
                        sender = msg.get("from", "unknown")
                        text = msg.get("text", {}).get("body", "")

                        if text:
                            response = self._process_message(text, sender)
                            if response:
                                return {
                                    "messaging_product": "whatsapp",
                                    "to": sender,
                                    "text": {"body": response},
                                }
        except Exception as e:
            pass

        return {"status": "processed"}

    def _process_message(self, text: str, sender: str) -> Optional[str]:
        """Process an incoming message and return response."""
        # Check commands
        if text.startswith("/"):
            parts = text[1:].strip().split(maxsplit=1)
            cmd_name = parts[0].lower() if parts else ""
            args = parts[1] if len(parts) > 1 else ""

            if cmd_name in self._commands:
                handler, _ = self._commands[cmd_name]
                try:
                    return handler(args, sender)
                except Exception as e:
                    return f"Error: {e}"
            return f"Unknown command: /{cmd_name}. Try /help"

        # Pass to message handler
        if self._message_handler:
            return self._message_handler(text, sender)

        return None

    # ── Cloud API mode (Meta WhatsApp Business) ───────────────────────

    def setup_cloud_api(self, phone_number_id: str, access_token: str):
        """Configure WhatsApp Cloud API credentials."""
        self.mode = "cloud_api"
        self._phone_number_id = phone_number_id
        self._access_token = access_token

    async def send_cloud_message(self, to: str, text: str) -> dict:
        """Send message via WhatsApp Cloud API."""
        import httpx

        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

        data = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://graph.facebook.com/v21.0/{self._phone_number_id}/messages",
                headers=headers,
                json=data,
                timeout=30,
            )
            return resp.json() if resp.status_code in (200, 201) else {"error": resp.status_code}

    async def send_template(self, to: str, template_name: str, 
                            language: str = "en") -> dict:
        """Send a WhatsApp message template."""
        import httpx

        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
            },
        }

        headers = {"Authorization": f"Bearer {self._access_token}"}
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://graph.facebook.com/v21.0/{self._phone_number_id}/messages",
                headers=headers,
                json=data,
                timeout=30,
            )
            return resp.json()

    # ── Baileys bridge mode (Node.js WhatsApp web bridge) ─────────────

    def create_baileys_handler(self, webhook_url: str, secret: str = "") -> str:
        """Generate a ready-to-use Baileys handler.

        Returns a Node.js script that bridges WhatsApp to OmniCore.
        """
        return f"""// OmniCore WhatsApp Bridge — Baileys
// npm install @whiskeysockets/baileys pino

const {{ makeWASocket, useMultiFileAuthState, DisconnectReason }} = require('@whiskeysockets/baileys');
const http = require('http');

const OMNICORE_URL = '{webhook_url}';
const SECRET = '{secret}';

async function start() {{
    const {{ state, saveCreds }} = await useMultiFileAuthState('auth_info');
    
    const sock = makeWASocket({{
        auth: state,
        printQRInTerminal: true,
    }});

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('messages.upsert', async ({{ messages }}) => {{
        for (const msg of messages) {{
            if (!msg.message || msg.key.fromMe) continue;
            
            const text = msg.message.conversation || 
                        msg.message.extendedTextMessage?.text || '';
            const sender = msg.key.remoteJid;
            
            if (!text) continue;

            // Forward to OmniCore
            try {{
                const body = JSON.stringify({{
                    from: sender,
                    text: text,
                    timestamp: Date.now(),
                }});
                
                const req = http.request(OMNICORE_URL, {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json',
                        'Content-Length': body.length,
                        'X-Bridge-Secret': SECRET,
                    }},
                }}, (res) => {{
                    let data = '';
                    res.on('data', chunk => data += chunk);
                    res.on('end', () => {{
                        try {{
                            const response = JSON.parse(data);
                            if (response.reply) {{
                                sock.sendMessage(sender, {{ text: response.reply }});
                            }}
                        }} catch (e) {{}}
                    }});
                }});
                
                req.write(body);
                req.end();
            }} catch (e) {{
                console.error('Forward error:', e);
            }}
        }}
    }});

    sock.ev.on('connection.update', (update) => {{
        const {{ connection, lastDisconnect }} = update;
        if (connection === 'close') {{
            const shouldReconnect = lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut;
            if (shouldReconnect) start();
        }}
    }});
}}

start();
console.log('WhatsApp bridge started — scan QR code to connect');
"""

    # ── FastAPI integration ───────────────────────────────────────────

    def mount_to_fastapi(self, app, path: str = "/whatsapp"):
        """Mount WhatsApp webhook handler to a FastAPI app."""
        from fastapi import Request, Query
        from fastapi.responses import PlainTextResponse, JSONResponse

        @app.get(path)
        async def wa_verify(request: Request):
            code, text = self.verify_webhook(dict(request.query_params))
            return PlainTextResponse(text, status_code=code)

        @app.post(path)
        async def wa_webhook(request: Request):
            body = await request.json()
            result = self.handle_webhook(body)
            return JSONResponse(result)


# ── Self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    wa = WhatsAppGateway()

    # Test commands
    assert wa._process_message("/ping", "test_user") == "pong! 🏓"
    print("✓ /ping works")

    assert "Commands" in wa._process_message("/help", "test_user")
    print("✓ /help works")

    assert "Unknown" in wa._process_message("/unknown", "test_user")
    print("✓ unknown command handled")

    # Test webhook verification
    code, text = wa.verify_webhook({
        "hub.mode": "subscribe",
        "hub.verify_token": "omnicore_verify_token",
        "hub.challenge": "test_challenge_123",
    })
    assert text == "test_challenge_123"
    print("✓ Webhook verification works")

    code, _ = wa.verify_webhook({
        "hub.mode": "subscribe",
        "hub.verify_token": "wrong_token",
        "hub.challenge": "test",
    })
    assert code == 403
    print("✓ Webhook rejects bad tokens")

    # Test message handler
    def handler(text, sender):
        return f"Echo: {text}"
    wa.on_message(handler)
    result = wa._process_message("hello world", "user123")
    assert result == "Echo: hello world"
    print("✓ Message handler works")

    print("\n✓ WhatsApp Gateway self-tests passed")