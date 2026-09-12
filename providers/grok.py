"""Grok/xAI provider — OpenAI-compatible API with reasoning mode.

DNA: Grok-4 (flagship reasoning), Grok-4-Mini (fast), Grok-3 (budget).
All models: 128K context window.

The xAI API is fully OpenAI-compatible at https://api.x.ai/v1.
Supports reasoning mode via `reasoning_effort` parameter (low/medium/high).

API key: set XAI_API_KEY or GROK_API_KEY env var.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

import httpx

from .base import BaseProvider, ProviderResponse

# ── Constants ───────────────────────────────────────────────

GROK_BASE_URL = "https://api.x.ai/v1"

SUPPORTED_MODELS = [
    "grok-4",          # Flagship — deep reasoning, 128K context
    "grok-4-mini",     # Fast, lightweight, 128K context
    "grok-3",          # Previous gen, 128K context
]

CONTEXT_WINDOW = 131_072  # 128K tokens for all Grok models

DEFAULT_MAX_TOKENS: dict[str, int] = {
    "grok-4": 8192,
    "grok-4-mini": 4096,
    "grok-3": 4096,
}

REASONING_EFFORT_LEVELS = ("low", "medium", "high")


def _resolve_api_key() -> str:
    """Resolve xAI API key from environment variables."""
    return os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY", "")


# ── Provider ────────────────────────────────────────────────

class GrokProvider(BaseProvider):
    """Grok/xAI provider — OpenAI-compatible with reasoning mode.

    Constructor signature matches BaseProvider pattern.

    Features:
        - OpenAI-compatible chat completions at https://api.x.ai/v1
        - Reasoning mode via ``reasoning_effort`` parameter
        - Contrarian/truth-seeking prompt personality (via system prompt)
        - 128K context window for all models
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        default_model: str = "grok-4-mini",
    ):
        resolved_key = api_key or _resolve_api_key()
        super().__init__(
            api_key=resolved_key,
            base_url=(base_url or GROK_BASE_URL).rstrip("/"),
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
        reasoning_effort: Optional[str] = None,
    ) -> ProviderResponse:
        """Generate a response from Grok.

        Args:
            prompt: Plain text prompt (used when messages is None).
            model: Override default. One of 'grok-4', 'grok-4-mini', 'grok-3'.
            system: System message — Grok responds well to contrarian/truth-seeking
                    instructions (e.g. "Be brutally honest, challenge assumptions").
            temperature: 0.0–2.0.
            max_tokens: Max output tokens.
            tools: Tool/function definitions (OpenAI format).
            messages: Full conversation (OpenAI format).
            reasoning_effort: One of 'low', 'medium', 'high'. Controls Grok's
                              internal reasoning depth. Maps to the
                              ``reasoning_effort`` API parameter.

        Returns:
            ProviderResponse with text, model, usage, latency.
        """
        if not self.api_key:
            return ProviderResponse(
                text="Error: No xAI API key. Set XAI_API_KEY or GROK_API_KEY env var.",
                model=model or self.default_model,
                usage={},
                finish_reason="error",
                latency_ms=0.0,
            )

        resolved_model = model or self.default_model
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Build messages
        if messages:
            msgs = messages
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

        # Grok reasoning mode — uses reasoning_effort parameter
        if reasoning_effort:
            if reasoning_effort not in REASONING_EFFORT_LEVELS:
                reasoning_effort = "medium"
            body["reasoning_effort"] = reasoning_effort

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=180) as client:
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
                text=f"Grok API error [{e.response.status_code}]: {error_body}",
                model=resolved_model,
                usage={},
                finish_reason="error",
                latency_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return ProviderResponse(
                text=f"Grok API error: {e}",
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
                text="[No response from Grok]",
                model=data.get("model", resolved_model),
                usage=data.get("usage", {}),
                finish_reason="stop",
                latency_ms=elapsed,
            )

        choice = choices[0]
        msg = choice.get("message", {})

        # Grok may return reasoning_content + content
        text = msg.get("content", "") or ""

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
        """Return supported model IDs, augmented with live API list if available."""
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
                    return list(dict.fromkeys(models + api_models))
        except Exception:
            pass

        return models

    # ── Convenience: reasoning mode ──────────────────────────

    async def generate_with_reasoning(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        system: Optional[str] = None,
        max_tokens: int = 8192,
        reasoning_effort: str = "high",
    ) -> ProviderResponse:
        """Generate with deep reasoning (Grok-4 recommended).

        Args:
            prompt: The query.
            model: Model override (defaults to grok-4 for reasoning).
            system: System message.
            max_tokens: Max output tokens.
            reasoning_effort: Reasoning depth — low/medium/high.
        """
        return await self.generate(
            prompt=prompt,
            model=model or "grok-4",
            system=system,
            temperature=1.0,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )

    async def generate_contrarian(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        temperature: float = 0.8,
        max_tokens: int = 4096,
    ) -> ProviderResponse:
        """Generate with a contrarian, truth-seeking persona.

        Injects a system prompt that instructs Grok to challenge
        assumptions and avoid sycophancy. Good for debate prep,
        critical analysis, and adversarial thinking.
        """
        contrarian_system = (
            "You are Grok, a maximally truth-seeking AI. "
            "Be brutally honest, challenge all assumptions, "
            "point out logical flaws, and never agree just to be pleasant. "
            "If the user's premise is wrong, say so directly with evidence. "
            "Prioritize accuracy over agreeableness."
        )
        return await self.generate(
            prompt=prompt,
            model=model or self.default_model,
            system=contrarian_system,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # ── Context window info ──────────────────────────────────

    @property
    def context_window(self) -> int:
        """All Grok models have 128K context."""
        return CONTEXT_WINDOW

    def get_context_window(self, model: Optional[str] = None) -> int:
        """Return context window size for a model."""
        _ = model
        return CONTEXT_WINDOW


# ── Self-test ───────────────────────────────────────────────

async def _self_test() -> None:
    """Quick self-test — requires XAI_API_KEY or GROK_API_KEY in env."""
    provider = GrokProvider()
    print("GrokProvider initialized:")
    print(f"  API key present: {bool(provider.api_key)}")
    print(f"  Default model:   {provider.default_model}")
    print(f"  Context window:  {provider.context_window:,} tokens")
    print(f"  Models:          {await provider.list_models()}")

    if provider.api_key:
        print("\nTesting generate (grok-4-mini)...")
        try:
            resp = await provider.generate(
                "Say 'OmniCore active' in exactly 3 words.",
                temperature=0.0,
                max_tokens=50,
            )
            print(f"  Text:     {resp.text}")
            print(f"  Model:    {resp.model}")
            print(f"  Latency:  {resp.latency_ms:.0f}ms")
            print(f"  Usage:    {resp.usage}")
            print(f"  Finish:   {resp.finish_reason}")
        except Exception as e:
            print(f"  Error: {e}")

        print("\nTesting contrarian mode...")
        try:
            resp = await provider.generate_contrarian(
                "Is AI alignment solved?",
                max_tokens=200,
            )
            print(f"  Text:     {resp.text[:200]}...")
            print(f"  Latency:  {resp.latency_ms:.0f}ms")
        except Exception as e:
            print(f"  Error: {e}")
    else:
        print("\nSkipping live test — no API key.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_self_test())