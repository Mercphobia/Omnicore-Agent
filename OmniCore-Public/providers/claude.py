"""Anthropic Claude provider. Extended thinking, nuanced judgment.
DNA: Claude Opus (deep reasoning).

Note: Claude API uses a different format than OpenAI.
This provider adapts Claude's Messages API to our standard interface.
"""

import time
import json
from typing import Optional

import httpx

from .base import BaseProvider, ProviderResponse


class ClaudeProvider(BaseProvider):
    """Anthropic Claude Messages API provider."""

    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(self, api_key: str, default_model: str = "claude-sonnet-4-20250514"):
        super().__init__(api_key, "https://api.anthropic.com/v1", default_model)

    async def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        system: Optional[str] = None,
        messages: Optional[list[dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: Optional[list[dict]] = None,
    ) -> ProviderResponse:
        url = f"{self.base_url}/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }

        # Convert OpenAI-style messages to Claude format
        claude_messages = []
        claude_system = system or ""

        if messages:
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                
                if role == "system":
                    claude_system += ("\n" + content) if claude_system else content
                elif role in ("user", "assistant"):
                    claude_messages.append({"role": role, "content": content})
                elif role == "tool":
                    # Claude expects tool results in user messages
                    claude_messages.append({
                        "role": "user",
                        "content": f"[Tool result]\n{content}"
                    })
        else:
            claude_messages = [{"role": "user", "content": prompt}]

        body = {
            "model": model or self.default_model,
            "messages": claude_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        
        if claude_system:
            body["system"] = claude_system

        # Claude uses 'tools' not 'functions' — convert if needed
        if tools:
            claude_tools = []
            for t in tools:
                if t.get("type") == "function":
                    claude_tools.append({
                        "name": t["function"]["name"],
                        "description": t["function"].get("description", ""),
                        "input_schema": t["function"].get("parameters", {"type": "object", "properties": {}}),
                    })
            if claude_tools:
                body["tools"] = claude_tools

        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # Extract response
        content_blocks = data.get("content", [])
        text_parts = []
        tool_calls = None

        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                if tool_calls is None:
                    tool_calls = []
                tool_calls.append({
                    "id": block.get("id", f"toolu_{int(time.time())}"),
                    "name": block.get("name", ""),
                    "arguments": block.get("input", {}),
                })

        usage = data.get("usage", {})
        return ProviderResponse(
            text="\n".join(text_parts),
            model=data.get("model", model or self.default_model),
            usage={
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            },
            finish_reason=data.get("stop_reason", "stop"),
            latency_ms=(time.perf_counter() - t0) * 1000,
            tool_calls=tool_calls,
        )

    async def list_models(self) -> list[str]:
        return [self.default_model]

    # ── Extended Thinking (Claude-specific) ──────────────────

    async def generate_with_thinking(
        self,
        prompt: str,
        *,
        thinking_budget: int = 4000,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ) -> ProviderResponse:
        """Generate with Claude's extended thinking mode.
        
        Args:
            thinking_budget: Tokens allocated for internal reasoning
        """
        url = f"{self.base_url}/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }

        body = {
            "model": model or self.default_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "thinking": {
                "type": "enabled",
                "budget_tokens": thinking_budget,
            },
        }
        if system:
            body["system"] = system

        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # Extract text (skip thinking blocks)
        text_parts = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))

        usage = data.get("usage", {})
        return ProviderResponse(
            text="\n".join(text_parts),
            model=data.get("model", model or self.default_model),
            usage={
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            },
            finish_reason=data.get("stop_reason", "stop"),
            latency_ms=(time.perf_counter() - t0) * 1000,
        )