"""OpenAI-compatible provider. Works with OpenAI, OpenRouter, and any
OpenAI-compatible API (Ollama, vLLM, local models)."""

import json
import time
from typing import Optional

import httpx

from .base import BaseProvider, ProviderResponse


class OpenAIProvider(BaseProvider):
    """Thin wrapper around OpenAI-compatible chat completions API."""

    def __init__(self, api_key: str, base_url: str = "", default_model: str = "gpt-4o"):
        base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        super().__init__(api_key, base_url, default_model)

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
        if not self.api_key:
            raise ValueError(
                "No API key configured. Set OMNICORE_API_KEY env var or add api_key to "
                "~/.omnicore/config.yaml. Auto-detected from HERMES_BUATPREM_API_KEY if available."
            )
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Use pre-built messages if provided (full conversation), else build from prompt+system
        if messages:
            msgs = messages
        else:
            msgs = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.append({"role": "user", "content": prompt})

        body = {
            "model": model or self.default_model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = tools

        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        msg = choice["message"]
        tool_calls = None
        if choice.get("finish_reason") == "tool_calls" and msg.get("tool_calls"):
            tool_calls = [
                {"id": tc["id"], "name": tc["function"]["name"],
                 "arguments": json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]}
                for tc in msg["tool_calls"]
            ]

        return ProviderResponse(
            text=msg.get("content") or "",
            model=data.get("model", model or self.default_model),
            usage=data.get("usage", {}),
            finish_reason=choice.get("finish_reason", "stop"),
            latency_ms=(time.perf_counter() - t0) * 1000,
            tool_calls=tool_calls,
        )

    async def list_models(self) -> list[str]:
        url = f"{self.base_url}/models"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return [m["id"] for m in resp.json().get("data", [])]
        return [self.default_model]