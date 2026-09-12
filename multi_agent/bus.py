"""Inter-agent communication bus. Workers publish messages, orchestrator subscribes.
DNA: Astra (hyper-agentic coordination) + CrewAI (shared context).
"""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Message:
    sender: str
    content: str
    msg_type: str = "info"        # info | status | result | error | request
    timestamp: float = field(default_factory=time.time)
    reply_to: str = ""            # worker_id to reply to
    metadata: dict = field(default_factory=dict)


class MessageBus:
    """Publish-subscribe message bus for inter-agent communication."""

    def __init__(self, history_limit: int = 200):
        self.subscribers: dict[str, list[Callable]] = defaultdict(list)
        self.history: list[Message] = []
        self.history_limit = history_limit
        self._lock = asyncio.Lock()

    async def publish(self, message: Message) -> None:
        """Publish a message to all subscribers of its type."""
        async with self._lock:
            self.history.append(message)
            # Trim history
            if len(self.history) > self.history_limit:
                self.history = self.history[-self.history_limit:]

        # Notify all subscribers (type-specific + wildcard)
        callbacks = self.subscribers.get(message.msg_type, []) + self.subscribers.get("*", [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(message)
                else:
                    callback(message)
            except Exception:
                pass  # Subscriber errors shouldn't crash the bus

    def subscribe(self, msg_type: str, callback: Callable) -> None:
        """Subscribe to messages of a given type. Use '*' for all."""
        self.subscribers[msg_type].append(callback)

    def unsubscribe(self, msg_type: str, callback: Callable) -> None:
        """Remove a subscription."""
        if callback in self.subscribers[msg_type]:
            self.subscribers[msg_type].remove(callback)

    async def request(self, target: str, content: str, timeout: float = 30.0) -> Optional[Message]:
        """Send a request and wait for a reply. Returns the reply or None on timeout."""
        reply_event = asyncio.Event()
        reply_message: Optional[Message] = None

        async def _on_reply(msg: Message):
            nonlocal reply_message
            if msg.reply_to == target or msg.sender == target:
                reply_message = msg
                reply_event.set()

        self.subscribe("result", _on_reply)
        self.subscribe("error", _on_reply)

        await self.publish(Message(
            sender="_orchestrator",
            content=content,
            msg_type="request",
            reply_to=target,
        ))

        try:
            await asyncio.wait_for(reply_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass

        self.unsubscribe("result", _on_reply)
        self.unsubscribe("error", _on_reply)
        return reply_message

    def get_history(self, msg_type: Optional[str] = None, limit: int = 50) -> list[Message]:
        """Get recent message history, optionally filtered by type."""
        if msg_type:
            return [m for m in self.history if m.msg_type == msg_type][-limit:]
        return self.history[-limit:]

    def get_context(self) -> str:
        """Build a shared context string from all messages for worker injection."""
        lines = []
        for msg in self.history[-50:]:
            lines.append(f"[{msg.sender}] [{msg.msg_type}] {msg.content[:200]}")
        return "\n".join(lines)

    def clear(self) -> None:
        """Clear message history."""
        self.history.clear()


class SharedContext:
    """Mutable shared state that workers can read and write to.
    Useful for accumulating results, tracking progress, sharing discoveries.
    """

    def __init__(self):
        self._data: dict = {}
        self._lock = asyncio.Lock()

    async def set(self, key: str, value) -> None:
        async with self._lock:
            self._data[key] = value

    async def get(self, key: str, default=None):
        async with self._lock:
            return self._data.get(key, default)

    async def append(self, key: str, value) -> None:
        """Append to a list stored at key."""
        async with self._lock:
            if key not in self._data:
                self._data[key] = []
            self._data[key].append(value)

    async def merge(self, updates: dict) -> None:
        """Merge a dict into shared state."""
        async with self._lock:
            self._data.update(updates)

    async def snapshot(self) -> dict:
        """Return a copy of the current state."""
        async with self._lock:
            return dict(self._data)