"""Local Ollama provider — OpenAI-compatible, no auth required.

DNA: Any model pulled locally via Ollama. Runs on-device.

Ollama exposes an OpenAI-compatible API at http://localhost:11434/v1.
No API key required — runs entirely local.

Features:
    - OpenAI-compatible chat completions endpoint
    - list_local_models() — query Ollama for installed models
    - pull_model(name) — pull a new model via Ollama API
    - is_available() — check if Ollama server is running
    - Graceful offline fallback — returns error responses, never crashes
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

import httpx

from .base import BaseProvider, ProviderResponse

# ── Constants ───────────────────────────────────────────────

DEFAULT_OLLAMA_URL = "http://localhost:11434/v1"
DEFAULT_OLLAMA_REST_URL = "http://localhost:11434"  # native Ollama API (non-OpenAI)

# Common local models (for reference — actual list from API)
COMMON_LOCAL_MODELS = [
    "llama3.2",
    "llama3.1",
    "mistral",
    "codellama",
    "phi3",
    "gemma2",
    "qwen2.5",
    "deepseek-r1",
    "mixtral",
]

MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "llama3.2": 131_072,
    "llama3.1": 131_072,
    "mistral": 32_768,
    "codellama": 16_384,
    "phi3": 128_000,
    "gemma2": 8192,
    "qwen2.5": 131_072,
    "deepseek-r1": 131_072,
    "mixtral": 32_768,
}


# ── Provider ────────────────────────────────────────────────

class OllamaProvider(BaseProvider):
    """Local Ollama provider — OpenAI-compatible, no cloud API key.

    Constructor signature matches BaseProvider pattern.

    Talks to a local Ollama server at ``http://localhost:11434/v1``
    (OpenAI-compatible) for chat, and ``http://localhost:11434/api``
    for model management (list, pull).

    No API key is required — pass ``"ollama"`` as a dummy key.
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        default_model: str = "llama3.2",
    ):
        # Ollama doesn't need an API key, but BaseProvider requires one.
        # Use a dummy key if none provided.
        super().__init__(
            api_key=api_key or "ollama",
            base_url=(base_url or DEFAULT_OLLAMA_URL).rstrip("/"),
            default_model=default_model,
        )
        # Native Ollama REST endpoint (non-OpenAI)
        self._rest_url = DEFAULT_OLLAMA_REST_URL

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
        """Generate a response from a local Ollama model.

        Args:
            prompt: Plain text prompt (used when messages is None).
            model: Override default. Any model pulled in Ollama.
            system: System message.
            temperature: 0.0–2.0.
            max_tokens: Max output tokens.
            tools: Tool/function definitions (OpenAI format).
            messages: Full conversation (OpenAI format).

        Returns:
            ProviderResponse. Gracefully returns error text if Ollama is
            unreachable rather than raising an exception.
        """
        resolved_model = model or self.default_model

        # Check availability first
        if not await self.is_available():
            return ProviderResponse(
                text=(
                    "Error: Ollama server not running. "
                    "Start it with: ollama serve"
                ),
                model=resolved_model,
                usage={},
                finish_reason="error",
                latency_ms=0.0,
            )

        url = f"{self.base_url}/chat/completions"
        headers = {
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
            "max_tokens": max_tokens,
        }

        if tools:
            body["tools"] = tools

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError:
            elapsed = (time.perf_counter() - t0) * 1000
            return ProviderResponse(
                text="Error: Cannot connect to Ollama. Is it running? Run: ollama serve",
                model=resolved_model,
                usage={},
                finish_reason="error",
                latency_ms=elapsed,
            )
        except httpx.HTTPStatusError as e:
            elapsed = (time.perf_counter() - t0) * 1000
            error_body = ""
            try:
                error_body = e.response.text[:500]
            except Exception:
                error_body = str(e)
            return ProviderResponse(
                text=f"Ollama API error [{e.response.status_code}]: {error_body}",
                model=resolved_model,
                usage={},
                finish_reason="error",
                latency_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return ProviderResponse(
                text=f"Ollama error: {e}",
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
                text="[No response from Ollama]",
                model=data.get("model", resolved_model),
                usage=data.get("usage", {}),
                finish_reason="stop",
                latency_ms=elapsed,
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
        """Return models available locally in Ollama.

        Queries the Ollama native API (non-OpenAI endpoint) for
        installed models. Falls back to the OpenAI-compatible
        ``/models`` endpoint if the native endpoint is unavailable.
        """
        local = await self.list_local_models()
        if local:
            return local

        # Fallback: OpenAI-compatible /models endpoint
        url = f"{self.base_url}/models"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    return [m["id"] for m in data.get("data", [])]
        except Exception:
            pass

        return [self.default_model]

    # ── Ollama-specific methods ──────────────────────────────

    async def list_local_models(self) -> list[str]:
        """Query Ollama's native API for installed models.

        Uses ``GET /api/tags`` — the Ollama-native endpoint that
        returns all pulled models with metadata.

        Returns:
            List of model names (e.g. ``['llama3.2:latest', 'mistral:7b']``).
            Empty list if Ollama is unreachable.
        """
        url = f"{self._rest_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    return [m["name"] for m in data.get("models", [])]
        except Exception:
            pass
        return []

    async def pull_model(self, name: str) -> dict:
        """Pull a model from Ollama's registry.

        Uses ``POST /api/pull`` — the Ollama-native streaming endpoint.
        Blocks until the pull completes. Reports progress.

        Args:
            name: Model name to pull (e.g. ``llama3.2``, ``mistral:7b``).

        Returns:
            Dict with keys: ``success`` (bool), ``model`` (str),
            ``message`` (str), ``elapsed_ms`` (float).
        """
        url = f"{self._rest_url}/api/pull"
        body = {"name": name, "stream": False}

        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=600) as client:
                resp = await client.post(url, json=body)
                elapsed = (time.perf_counter() - t0) * 1000
                if resp.status_code == 200:
                    return {
                        "success": True,
                        "model": name,
                        "message": f"Model '{name}' pulled successfully.",
                        "elapsed_ms": elapsed,
                    }
                else:
                    return {
                        "success": False,
                        "model": name,
                        "message": f"Pull failed [{resp.status_code}]: {resp.text[:300]}",
                        "elapsed_ms": elapsed,
                    }
        except httpx.ConnectError:
            elapsed = (time.perf_counter() - t0) * 1000
            return {
                "success": False,
                "model": name,
                "message": "Cannot connect to Ollama. Is it running?",
                "elapsed_ms": elapsed,
            }
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return {
                "success": False,
                "model": name,
                "message": f"Pull error: {e}",
                "elapsed_ms": elapsed,
            }

    async def is_available(self) -> bool:
        """Check if the Ollama server is running and reachable.

        Returns:
            True if Ollama responds, False otherwise.
        """
        url = f"{self._rest_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(url)
                return resp.status_code == 200
        except Exception:
            return False

    async def model_info(self, name: str) -> Optional[dict]:
        """Get detailed info about a specific model.

        Uses ``POST /api/show`` — the Ollama-native endpoint.

        Args:
            name: Model name (e.g. ``llama3.2``).

        Returns:
            Dict with model metadata, or None if unavailable.
        """
        url = f"{self._rest_url}/api/show"
        body = {"name": name}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=body)
                if resp.status_code == 200:
                    return resp.json()
        except Exception:
            pass
        return None

    # ── Context window info ──────────────────────────────────

    @property
    def context_window(self) -> int:
        """Best-guess context window for the default model."""
        for prefix, size in MODEL_CONTEXT_WINDOWS.items():
            if self.default_model.startswith(prefix):
                return size
        return 8192  # conservative default

    def get_context_window(self, model: Optional[str] = None) -> int:
        """Return context window size for a model."""
        name = model or self.default_model
        for prefix, size in MODEL_CONTEXT_WINDOWS.items():
            if name.startswith(prefix):
                return size
        return 8192


# ── Self-test ───────────────────────────────────────────────

async def _self_test() -> None:
    """Quick self-test — no API key needed, but Ollama must be running."""
    provider = OllamaProvider()
    print("OllamaProvider initialized:")
    print(f"  Base URL:        {provider.base_url}")
    print(f"  Default model:   {provider.default_model}")
    print(f"  Context window:  {provider.context_window:,} tokens")

    print("\nChecking availability...")
    available = await provider.is_available()
    print(f"  Ollama running:  {available}")

    if available:
        print("\nListing local models...")
        models = await provider.list_local_models()
        print(f"  Local models:    {models}")

        if models:
            test_model = models[0]
            print(f"\nTesting generate ({test_model})...")
            try:
                resp = await provider.generate(
                    "Say 'OmniCore local' in exactly 3 words.",
                    model=test_model,
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

            print(f"\nModel info for {test_model}...")
            info = await provider.model_info(test_model)
            if info:
                details = info.get("details", {})
                print(f"  Family:         {details.get('family', 'unknown')}")
                print(f"  Parameter size: {details.get('parameter_size', 'unknown')}")
                print(f"  Format:         {details.get('format', 'unknown')}")
            else:
                print("  No info available.")
        else:
            print("\nNo models pulled. Use provider.pull_model('llama3.2') to pull one.")
            print("Testing pull_model info...")
            print("  (skipping actual pull — takes too long for a self-test)")
    else:
        print("\nOllama not running. Start with: ollama serve")
        print("Install: curl -fsSL https://ollama.com/install.sh | sh")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_self_test())