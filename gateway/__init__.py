"""Gateway package — external service connectors (Telegram, Discord, etc.).

DNA: Hermes pattern — gateways bridge OmniCore to the outside world via
polling, webhooks, or bidirectional streams.
"""

from __future__ import annotations

# Lazy import: httpx may not be installed, so defer telegram import
# to avoid breaking the entire package on init.
_telegram_available = False


def __getattr__(name: str):
    """Lazy-load TelegramGateway on first access."""
    if name == "TelegramGateway":
        from gateway.telegram import TelegramGateway

        globals()["TelegramGateway"] = TelegramGateway
        return TelegramGateway
    raise AttributeError(f"module 'gateway' has no attribute {name!r}")


__all__ = ["TelegramGateway"]