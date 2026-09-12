"""DeepSeek provider — OpenAI-compatible with vision + 1M context.

DNA: DeepSeek-V4 (vision+code) + DeepSeek-R1 (reasoning).

Supports:
    - deepseek-chat       (DeepSeek-V4, 1M context, vision)
    - deepseek-reasoner   (DeepSeek-R1, chain-of-thought, 64K output)
    - Vision: accept image_url in messages (OpenAI-compatible format)
    - Function calling / tools (native)

DeepSeek API is OpenAI-compatible at https://api.deepseek.com/v1.

Usage:
    provider = DeepSeekProvider(
        api_key="sk-...",  # or from DEEPSEEK_API_KEY env
        default_model="deepseek-chat",
    )
    response = await provider.generate("Hello")
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

import httpx

from .base import BaseProvider, ProviderResponse

# ── Constants ───────────────────────────────────────────────

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

SUPPORTED_MODELS = [
    "deepseek-chat",       # DeepSeek-V4 — 1M context, vision, general purpose
    "deepseek-reasoner",   # DeepSeek-R1 — chain-of-thought reasoning
]

# Context window sizes (for reference — handled server-side)
CONTEXT_WINDOWS = {
    "deepseek-chat": 1_048_576,     # 1M tokens
    "deepseek-reasoner": 65_536,    # 64K input + 64K output
}

# Default max output tokens per model
DEFAULT_MAX_TOKENS = {
    "deepseek-chat": 8192,
    "deepseek-reasoner": 8192,      # Can go up to 64K
}


def _resolve_api_key() -> str:
    """Resolve DeepSeek API key from env."""
    return os.environ.get("DEEPSEEK_API_KEY", "")


# ── Provider ────────────────────────────────────────────────

class DeepSeekProvider(BaseProvider):
    """DeepSeek provider — OpenAI-compatible API with vision.

    Constructor signature matches engine.py's _init_provider pattern.

    The DeepSeek API follows the OpenAI chat completions spec, so this
    provider is a thin wrapper similar to OpenAIProvider but with:
    - DeepSeek-specific model IDs
    - Vision support (image_url in messages)
    - 1M context window awareness
    - Different auth header (no "Bearer" prefix required for some setups)
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        default_model: str = "deepseek-chat",
    ):
        resolved_key = api_key or _resolve_api_key()
        super().__init__(
            api_key=resolved_key,
            base_url=base_url or DEEPSEEK_BASE_URL,
            default_model=default_model,
        )

    # ── Core interface ───────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: Optional[list[dict]] = None,
        messages: Optional[list[dict]] = None,
    ) -> ProviderResponse:
        """Generate a response from DeepSeek.

        Args:
            prompt: Plain text prompt (used when messages is None).
            model: Override default. One of 'deepseek-chat' or 'deepseek-reasoner'.
            system: System message.
            temperature: 0.0–2.0. Note: deepseek-reasoner ignores temperature.
            max_tokens: Max output tokens.
            tools: Tool/function definitions (OpenAI format).
            messages: Full conversation (OpenAI format, supports image_url for vision).

        Returns:
            ProviderResponse with text, model, usage, latency, optional tool_calls.
        """
        if not self.api_key:
            return ProviderResponse(
                text="Error: No DeepSeek API key. Set DEEPSEEK_API_KEY env var.",
                model=model or self.default_model,
                usage={},
                finish_reason="error",
                latency_ms=0.0,
            )

        resolved_model = model or self.default_model

        # Validate model
        if resolved_model not in SUPPORTED_MODELS:
            # Still try — DeepSeek may add new models
            pass

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Build messages — support multimodal image_url
        if messages:
            msgs = self._normalize_messages(messages)
        else:
            msgs = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.append({"role": "user", "content": prompt})

        # Build request body
        body: dict = {
            "model": resolved_model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens or DEFAULT_MAX_TOKENS.get(resolved_model, 4096),
        }

        if tools:
            body["tools"] = tools

        # DeepSeek-reasoner: temperature is ignored, but we keep it for compatibility
        # Also: top_p is supported

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=180) as client:  # Longer timeout for reasoning
                resp = await client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            elapsed = (time.perf_counter() - t0) * 1000
            error_body = ""
            try:
                error_body = e.response.text[:500]
            except Exception:
                error_body = str(e)
            return ProviderResponse(
                text=f"DeepSeek API error [{e.response.status_code}]: {error_body}",
                model=resolved_model,
                usage={},
                finish_reason="error",
                latency_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return ProviderResponse(
                text=f"DeepSeek API error: {str(e)}",
                model=resolved_model,
                usage={},
                finish_reason="error",
                latency_ms=elapsed,
            )

        elapsed = (time.perf_counter() - t0) * 1000

        # Extract response
        choices = data.get("choices", [])
        if not choices:
            return ProviderResponse(
                text="[No response from DeepSeek]",
                model=data.get("model", resolved_model),
                usage=data.get("usage", {}),
                finish_reason="stop",
                latency_ms=elapsed,
            )

        choice = choices[0]
        msg = choice.get("message", {})

        # Handle text — deepseek-reasoner may return reasoning_content separately
        text = msg.get("content", "") or ""
        reasoning = msg.get("reasoning_content")  # DeepSeek-R1 CoT

        # If reasoning is available and content is empty, use reasoning as text
        if not text and reasoning:
            text = reasoning

        # Tool calls
        tool_calls = None
        if choice.get("finish_reason") == "tool_calls" and msg.get("tool_calls"):
            tool_calls = []
            for tc in msg["tool_calls"]:
                tool_calls.append({
                    "id": tc.get("id", f"call_{int(time.time())}"),
                    "name": tc["function"]["name"],
                    "arguments": (
                        json.loads(tc["function"]["arguments"])
                        if isinstance(tc["function"]["arguments"], str)
                        else tc["function"]["arguments"]
                    ),
                })

        usage = data.get("usage", {})
        finish_reason = choice.get("finish_reason", "stop")

        return ProviderResponse(
            text=text,
            model=data.get("model", resolved_model),
            usage=usage,
            finish_reason=finish_reason,
            latency_ms=elapsed,
            tool_calls=tool_calls,
        )

    async def list_models(self) -> list[str]:
        """Return supported model IDs.

        Also attempts to fetch live model list from the API.
        """
        models = list(SUPPORTED_MODELS)
        if not self.api_key:
            return models

        url = f"{self.base_url}/models"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    api_models = [m["id"] for m in data.get("data", [])]
                    # Merge: API models + our known models, dedup
                    return list(dict.fromkeys(models + api_models))
        except Exception:
            pass

        return models

    # ── Vision helpers ───────────────────────────────────────

    @staticmethod
    def _normalize_messages(messages: list[dict]) -> list[dict]:
        """Normalize messages for DeepSeek API, handling multimodal content.

        DeepSeek supports image_url in messages in OpenAI-compatible format:
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image"},
                    {"type": "image_url", "image_url": {"url": "https://..."}}
                ]
            }

        Also supports base64 inline images:
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}

        This method passes through compliant messages unchanged and
        ensures text-only messages use string content.
        """
        normalized = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if isinstance(content, str):
                normalized.append({"role": role, "content": content})
            elif isinstance(content, list):
                # Already multimodal format — pass through
                normalized.append({"role": role, "content": content})
            else:
                # Unknown format — stringify
                normalized.append({"role": role, "content": str(content)})

        return normalized

    # ── Extended: reasoning with thinking budget ─────────────

    async def generate_with_reasoning(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        system: Optional[str] = None,
        max_tokens: int = 8192,
    ) -> ProviderResponse:
        """Generate with DeepSeek-R1 reasoning (deepseek-reasoner).

        DeepSeek-R1 returns chain-of-thought reasoning via reasoning_content
        field, then the final answer in content.
        """
        return await self.generate(
            prompt=prompt,
            model=model or "deepseek-reasoner",
            system=system,
            temperature=1.0,  # Reasoner ignores this
            max_tokens=max_tokens,
        )

    # ── Vision convenience ───────────────────────────────────

    async def generate_with_image(
        self,
        prompt: str,
        image_url: str,
        *,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> ProviderResponse:
        """Generate a response with an image input.

        Args:
            prompt: Text prompt about the image.
            image_url: URL or base64 data URI of the image.
            model: Model to use (defaults to deepseek-chat which supports vision).
            system: System message.
            temperature: Sampling temperature.
            max_tokens: Max output tokens.

        Returns:
            ProviderResponse.
        """
        if model is None:
            model = "deepseek-chat"  # Vision only on deepseek-chat

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        })

        return await self.generate(
            prompt="",  # Not used — messages takes precedence
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=messages,
        )

    # ── Context window info ──────────────────────────────────

    @property
    def context_window(self) -> int:
        """Return the context window size for the default model."""
        return CONTEXT_WINDOWS.get(self.default_model, 65_536)

    def get_context_window(self, model: Optional[str] = None) -> int:
        """Return context window size for a specific model."""
        return CONTEXT_WINDOWS.get(model or self.default_model, 65_536)


# ── Self-test ───────────────────────────────────────────────

async def _self_test():
    """Quick self-test — requires DEEPSEEK_API_KEY."""
    provider = DeepSeekProvider()
    print(f"DeepSeekProvider initialized:")
    print(f"  API key present: {bool(provider.api_key)}")
    print(f"  Default model: {provider.default_model}")
    print(f"  Context window: {provider.context_window:,} tokens")
    print(f"  Models: {await provider.list_models()}")

    if provider.api_key:
        print("\nTesting generate (deepseek-chat)...")
        try:
            resp = await provider.generate(
                "Say 'OmniCore v2' in exactly 3 words.",
                temperature=0.0,
                max_tokens=50,
            )
            print(f"  Text: {resp.text}")
            print(f"  Model: {resp.model}")
            print(f"  Latency: {resp.latency_ms:.0f}ms")
            print(f"  Usage: {resp.usage}")
            print(f"  Finish: {resp.finish_reason}")
        except Exception as e:
            print(f"  Error: {e}")
    else:
        print("\nSkipping live test — no API key.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_self_test())