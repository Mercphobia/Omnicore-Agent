"""Mistral AI provider — SDK-first with httpx REST fallback.

DNA: Mistral Large (flagship reasoning), Codestral (code), Nemo (fast).
All models: 128K context window.

Uses the ``mistralai`` SDK if installed, falling back to httpx for the
REST API at https://api.mistral.ai/v1.

Features:
    - Function calling (native tool use)
    - JSON mode (structured output via ``response_format``)
    - 128K context across all current-gen models

API key: set MISTRAL_API_KEY env var.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

import httpx

from .base import BaseProvider, ProviderResponse

# ── Constants ───────────────────────────────────────────────

MISTRAL_BASE_URL = "https://api.mistral.ai/v1"

SUPPORTED_MODELS = [
    "mistral-large-latest",     # Flagship — reasoning, 128K context
    "mistral-medium-latest",    # Balanced performance
    "mistral-small-latest",     # Fast, cost-effective
    "codestral-latest",         # Code-specific model
    "mistral-nemo",             # Lightweight, fast
]

# Aliases for convenience
MODEL_ALIASES: dict[str, str] = {
    "mistral-large":  "mistral-large-latest",
    "mistral-medium": "mistral-medium-latest",
    "mistral-small":  "mistral-small-latest",
    "codestral":      "codestral-latest",
}

CONTEXT_WINDOW = 131_072  # 128K tokens

DEFAULT_MAX_TOKENS: dict[str, int] = {
    "mistral-large-latest":  8192,
    "mistral-medium-latest": 4096,
    "mistral-small-latest":  4096,
    "codestral-latest":      8192,
    "mistral-nemo":          4096,
}

_SDK_AVAILABLE: bool | None = None  # cached check


def _resolve_api_key() -> str:
    """Resolve Mistral API key from environment."""
    return os.environ.get("MISTRAL_API_KEY", "")


def _sdk_available() -> bool:
    """Check if the ``mistralai`` SDK is installed (cached)."""
    global _SDK_AVAILABLE
    if _SDK_AVAILABLE is None:
        try:
            import mistralai  # noqa: F401
            _SDK_AVAILABLE = True
        except ImportError:
            _SDK_AVAILABLE = False
    return _SDK_AVAILABLE


def _resolve_model(name: str) -> str:
    """Resolve a model alias to its canonical ID. Pass-through if unknown."""
    return MODEL_ALIASES.get(name, name)


# ── Provider ────────────────────────────────────────────────

class MistralProvider(BaseProvider):
    """Mistral AI provider — SDK-first, with httpx REST fallback.

    Constructor signature matches BaseProvider pattern.

    Uses the official ``mistralai`` SDK when available, falling back to
    direct httpx REST calls. Both paths produce identical
    ``ProviderResponse`` objects.

    Features:
        - Function calling / tool use (native)
        - JSON mode via ``response_format={"type": "json_object"}``
        - 128K context window
        - Model aliases: ``mistral-large`` → ``mistral-large-latest``
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        default_model: str = "mistral-large-latest",
    ):
        resolved_key = api_key or _resolve_api_key()
        super().__init__(
            api_key=resolved_key,
            base_url=(base_url or MISTRAL_BASE_URL).rstrip("/"),
            default_model=default_model,
        )
        self._sdk_client = None  # lazy init

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
        json_mode: bool = False,
    ) -> ProviderResponse:
        """Generate a response from Mistral.

        Args:
            prompt: Plain text prompt (used when messages is None).
            model: Override default. Aliases like ``mistral-large`` are resolved.
            system: System message.
            temperature: 0.0–2.0.
            max_tokens: Max output tokens.
            tools: Tool/function definitions (OpenAI format).
            messages: Full conversation (OpenAI format).
            json_mode: If True, request structured JSON output via
                       ``response_format={"type": "json_object"}``. The prompt
                       must include the word "JSON" (Mistral requirement).

        Returns:
            ProviderResponse.
        """
        if not self.api_key:
            return ProviderResponse(
                text="Error: No Mistral API key. Set MISTRAL_API_KEY env var.",
                model=model or self.default_model,
                usage={},
                finish_reason="error",
                latency_ms=0.0,
            )

        resolved_model = _resolve_model(model or self.default_model)

        # Try SDK path first, fall back to REST
        if _sdk_available():
            return await self._generate_sdk(
                resolved_model, prompt, system, temperature,
                max_tokens, tools, messages, json_mode,
            )
        else:
            return await self._generate_rest(
                resolved_model, prompt, system, temperature,
                max_tokens, tools, messages, json_mode,
            )

    async def _generate_rest(
        self,
        model: str,
        prompt: str,
        system: Optional[str],
        temperature: float,
        max_tokens: int,
        tools: Optional[list[dict]],
        messages: Optional[list[dict]],
        json_mode: bool,
    ) -> ProviderResponse:
        """Generate via direct REST API call (httpx fallback)."""
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
            "model": model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens or DEFAULT_MAX_TOKENS.get(model, 4096),
        }

        if tools:
            body["tools"] = tools

        # JSON mode — Mistral requires the word "JSON" in the prompt
        if json_mode:
            body["response_format"] = {"type": "json_object"}

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
                text=f"Mistral API error [{e.response.status_code}]: {error_body}",
                model=model,
                usage={},
                finish_reason="error",
                latency_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return ProviderResponse(
                text=f"Mistral API error: {e}",
                model=model,
                usage={},
                finish_reason="error",
                latency_ms=elapsed,
            )

        elapsed = (time.perf_counter() - t0) * 1000
        return self._parse_openai_response(data, model, elapsed)

    async def _generate_sdk(
        self,
        model: str,
        prompt: str,
        system: Optional[str],
        temperature: float,
        max_tokens: int,
        tools: Optional[list[dict]],
        messages: Optional[list[dict]],
        json_mode: bool,
    ) -> ProviderResponse:
        """Generate via the ``mistralai`` SDK."""
        from mistralai import Mistral
        from mistralai.models import (
            SDKError,
            SystemMessage,
            UserMessage,
            AssistantMessage,
            ToolMessage,
        )

        if self._sdk_client is None:
            self._sdk_client = Mistral(api_key=self.api_key)

        sdk = self._sdk_client

        # Convert messages to SDK format
        sdk_messages: list = []
        if messages:
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "system":
                    sdk_messages.append(SystemMessage(content=str(content)))
                elif role == "assistant":
                    sdk_messages.append(AssistantMessage(content=str(content)))
                elif role == "tool":
                    sdk_messages.append(ToolMessage(
                        content=str(content),
                        tool_call_id=msg.get("tool_call_id", ""),
                        name=msg.get("name", ""),
                    ))
                else:
                    sdk_messages.append(UserMessage(content=str(content)))
        else:
            if system:
                sdk_messages.append(SystemMessage(content=system))
            sdk_messages.append(UserMessage(content=prompt))

        # Convert tools to Mistral SDK format
        sdk_tools = None
        if tools:
            sdk_tools = []
            for t in tools:
                if t.get("type") == "function":
                    sdk_tools.append({
                        "type": "function",
                        "function": t["function"],
                    })
                else:
                    sdk_tools.append(t)

        t0 = time.perf_counter()
        try:
            kwargs: dict = {
                "model": model,
                "messages": sdk_messages,
                "temperature": temperature,
                "max_tokens": max_tokens or DEFAULT_MAX_TOKENS.get(model, 4096),
            }
            if sdk_tools:
                kwargs["tools"] = sdk_tools
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            response = sdk.chat.complete(**kwargs)
        except SDKError as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return ProviderResponse(
                text=f"Mistral SDK error: {e}",
                model=model,
                usage={},
                finish_reason="error",
                latency_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return ProviderResponse(
                text=f"Mistral API error: {e}",
                model=model,
                usage={},
                finish_reason="error",
                latency_ms=elapsed,
            )

        elapsed = (time.perf_counter() - t0) * 1000

        if not response or not response.choices:
            return ProviderResponse(
                text="[No response from Mistral]",
                model=model,
                usage={},
                finish_reason="stop",
                latency_ms=elapsed,
            )

        choice = response.choices[0]
        msg = choice.message

        # Tool calls
        tool_calls = None
        if msg.tool_calls:
            tool_calls = []
            for tc in msg.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": (
                        json.loads(tc.function.arguments)
                        if isinstance(tc.function.arguments, str)
                        else tc.function.arguments
                    ),
                })

        usage_dict = {}
        if response.usage:
            usage_dict = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return ProviderResponse(
            text=msg.content or "",
            model=response.model or model,
            usage=usage_dict,
            finish_reason=choice.finish_reason or "stop",
            latency_ms=elapsed,
            tool_calls=tool_calls,
        )

    @staticmethod
    def _parse_openai_response(
        data: dict,
        model: str,
        elapsed_ms: float,
    ) -> ProviderResponse:
        """Parse an OpenAI-compatible chat completion response."""
        choices = data.get("choices", [])
        if not choices:
            return ProviderResponse(
                text="[No response from Mistral]",
                model=data.get("model", model),
                usage=data.get("usage", {}),
                finish_reason="stop",
                latency_ms=elapsed_ms,
            )

        choice = choices[0]
        msg = choice.get("message", {})

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

        return ProviderResponse(
            text=text,
            model=data.get("model", model),
            usage=data.get("usage", {}),
            finish_reason=choice.get("finish_reason", "stop"),
            latency_ms=elapsed_ms,
            tool_calls=tool_calls,
        )

    async def list_models(self) -> list[str]:
        """Return supported model IDs, augmented with live API list."""
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

    # ── Convenience: JSON mode ───────────────────────────────

    async def generate_json(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> ProviderResponse:
        """Generate with JSON output mode.

        Mistral requires the word "JSON" somewhere in the prompt
        when using ``response_format={"type": "json_object"}``.
        """
        # Ensure "JSON" appears in the prompt (Mistral requirement)
        if "json" not in prompt.lower():
            prompt = f"{prompt}\n\nRespond with valid JSON only."

        return await self.generate(
            prompt=prompt,
            model=model,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
        )

    async def generate_code(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> ProviderResponse:
        """Generate code using Codestral.

        Uses codestral-latest by default for code generation tasks.
        """
        code_system = system or (
            "You are an expert software engineer. "
            "Write clean, well-documented, production-ready code. "
            "Include type hints, error handling, and brief comments."
        )
        return await self.generate(
            prompt=prompt,
            model=model or "codestral-latest",
            system=code_system,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # ── Context window info ──────────────────────────────────

    @property
    def context_window(self) -> int:
        """All current-gen Mistral models have 128K context."""
        return CONTEXT_WINDOW

    def get_context_window(self, model: Optional[str] = None) -> int:
        """Return context window size for a model."""
        _ = model
        return CONTEXT_WINDOW


# ── Self-test ───────────────────────────────────────────────

async def _self_test() -> None:
    """Quick self-test — requires MISTRAL_API_KEY."""
    provider = MistralProvider()
    print("MistralProvider initialized:")
    print(f"  API key present: {bool(provider.api_key)}")
    print(f"  SDK available:   {_sdk_available()}")
    print(f"  Default model:   {provider.default_model}")
    print(f"  Context window:  {provider.context_window:,} tokens")
    print(f"  Models:          {await provider.list_models()}")

    if provider.api_key:
        print("\nTesting generate (mistral-small-latest)...")
        try:
            resp = await provider.generate(
                "Say 'OmniCore online' in exactly 3 words.",
                model="mistral-small-latest",
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

        print("\nTesting JSON mode...")
        try:
            resp = await provider.generate_json(
                'Return a JSON object with keys "status" and "provider".',
                model="mistral-small-latest",
                max_tokens=200,
            )
            print(f"  Text:     {resp.text[:200]}")
            print(f"  Latency:  {resp.latency_ms:.0f}ms")
        except Exception as e:
            print(f"  Error: {e}")
    else:
        print("\nSkipping live test — no API key.")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_self_test())