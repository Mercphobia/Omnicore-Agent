"""Google Gemini provider — SDK-first, REST fallback.

DNA: Gemini Flash (fast triage) + Gemini Pro (deep reasoning).

Supports:
    - gemini-2.5-flash (fast, cheap, multimodal)
    - gemini-2.5-pro (deep reasoning, long context)
    - Multimodal: text + image via google-generativeai SDK or httpx REST
    - Function calling / tools (native Gemini format)

Dependencies (all OPTIONAL):
    - google-generativeai  (pip install google-generativeai)
    - httpx                (pip install httpx) — always available in OmniCore

If google-generativeai is unavailable, falls back to httpx REST API calls
against https://generativelanguage.googleapis.com/v1beta/.
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Optional

import httpx

from .base import BaseProvider, ProviderResponse

# ── Gemini REST API constants ───────────────────────────────

GEMINI_REST_BASE = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_MODELS_REST = f"{GEMINI_REST_BASE}/models"

# Mapping from our model IDs to Gemini API model names
MODEL_MAP = {
    "gemini-2.5-flash": "gemini-2.5-flash",
    "gemini-2.5-pro": "gemini-2.5-pro",
    "gemini-2.5-flash-lite": "gemini-2.5-flash-lite",
    "gemini-2.0-flash": "gemini-2.0-flash",
    "gemini-2.0-flash-lite": "gemini-2.0-flash-lite",
    "gemini-1.5-pro": "gemini-1.5-pro",
    "gemini-1.5-flash": "gemini-1.5-flash",
}

SUPPORTED_MODELS = list(MODEL_MAP.keys())


def _resolve_api_key() -> str:
    """Resolve Gemini API key from env or config."""
    return os.environ.get("GOOGLE_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")


def _is_sdk_available() -> bool:
    """Check if google-generativeai package is importable."""
    try:
        import google.generativeai as genai  # noqa: F401
        return True
    except ImportError:
        return False


def _encode_image_to_base64(image_source: str | bytes) -> tuple[str, str]:
    """Encode an image to base64 data URI.

    Args:
        image_source: File path (str), URL (str starting with http), or raw bytes.

    Returns:
        (mime_type, base64_data) tuple — mime_type like 'image/png',
        base64_data is the raw base64 string (no data: prefix).
    """
    import base64 as b64

    if isinstance(image_source, bytes):
        # Raw bytes — assume PNG
        return "image/png", b64.b64encode(image_source).decode("utf-8")

    if image_source.startswith(("http://", "https://")):
        # URL — best-effort MIME from extension
        ext = Path(image_source.split("?")[0]).suffix.lower()
        mime_map = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
            ".svg": "image/svg+xml",
        }
        mime = mime_map.get(ext, "image/png")
        # For URLs, we return the URL itself — Gemini REST handles URLs
        return mime, image_source  # Not base64 for URLs
    else:
        # Local file path
        path = Path(image_source)
        ext = path.suffix.lower()
        mime_map = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
        }
        mime = mime_map.get(ext, "image/png")
        data = path.read_bytes()
        return mime, b64.b64encode(data).decode("utf-8")


# ── Provider ────────────────────────────────────────────────

class GeminiProvider(BaseProvider):
    """Google Gemini provider — SDK-first, httpx REST fallback.

    Constructor signature matches engine.py's _init_provider pattern.

    Usage:
        provider = GeminiProvider(
            api_key="...",  # or from GOOGLE_API_KEY env
            default_model="gemini-2.5-flash",
        )
        response = await provider.generate("Hello", temperature=0.5)
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        default_model: str = "gemini-2.5-flash",
    ):
        resolved_key = api_key or _resolve_api_key()
        super().__init__(
            api_key=resolved_key,
            base_url=base_url or GEMINI_REST_BASE,
            default_model=default_model,
        )
        self._sdk_client = None
        self._using_sdk = False
        self._init_sdk()

    def _init_sdk(self) -> None:
        """Attempt to initialize google-generativeai SDK."""
        if not self.api_key:
            return
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._sdk_client = genai
            self._using_sdk = True
        except ImportError:
            self._using_sdk = False
        except Exception:
            self._using_sdk = False

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
        """Generate a response from Gemini.

        Args:
            prompt: Plain text prompt (used when messages is None).
            model: Override default model. One of SUPPORTED_MODELS.
            system: System instruction (Gemini: system_instruction).
            temperature: 0.0–1.0.
            max_tokens: Max output tokens (Gemini: maxOutputTokens).
            tools: Tool/function definitions (OpenAI-ish format, converted internally).
            messages: Full conversation in OpenAI format (takes precedence over prompt).

        Returns:
            ProviderResponse with text, usage, model, latency.
        """
        if not self.api_key:
            return ProviderResponse(
                text="Error: No Gemini API key. Set GOOGLE_API_KEY or GEMINI_API_KEY env var.",
                model=model or self.default_model,
                usage={},
                finish_reason="error",
                latency_ms=0.0,
            )

        gemini_model = MODEL_MAP.get(model or self.default_model, model or self.default_model)

        if self._using_sdk:
            return await self._generate_sdk(
                prompt=prompt,
                gemini_model=gemini_model,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                messages=messages,
            )
        else:
            return await self._generate_rest(
                prompt=prompt,
                gemini_model=gemini_model,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                messages=messages,
            )

    async def list_models(self) -> list[str]:
        """Return supported model IDs."""
        return SUPPORTED_MODELS

    # ── SDK path ─────────────────────────────────────────────

    async def _generate_sdk(
        self,
        prompt: str,
        gemini_model: str,
        system: Optional[str],
        temperature: float,
        max_tokens: int,
        tools: Optional[list[dict]],
        messages: Optional[list[dict]],
    ) -> ProviderResponse:
        """Generate via google-generativeai SDK (sync, run in thread)."""
        import asyncio

        def _sync_call():
            genai = self._sdk_client
            generation_config = {
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            }

            # Build model
            model_kwargs = {
                "model_name": f"models/{gemini_model}",
                "generation_config": generation_config,
            }
            if system:
                model_kwargs["system_instruction"] = system

            sdk_model = genai.GenerativeModel(**model_kwargs)

            # Build contents from messages or prompt
            contents = self._build_sdk_contents(prompt, messages)

            # Handle tools
            sdk_tools = self._convert_tools_for_gemini(tools) if tools else None

            t0 = time.perf_counter()
            if sdk_tools:
                # Use the newer tool config parameter if available
                try:
                    from google.generativeai.types import Tool, FunctionDeclaration
                    tool_objects = []
                    for t in sdk_tools:
                        tool_objects.append(Tool(function_declarations=[
                            FunctionDeclaration(
                                name=t["name"],
                                description=t.get("description", ""),
                                parameters=t.get("parameters", {}),
                            )
                        ]))
                    response = sdk_model.generate_content(
                        contents,
                        tools=tool_objects,
                    )
                except Exception:
                    response = sdk_model.generate_content(contents)
            else:
                response = sdk_model.generate_content(contents)

            elapsed = (time.perf_counter() - t0) * 1000

            # Extract text
            text = ""
            tool_calls = None
            try:
                if response.candidates:
                    candidate = response.candidates[0]
                    for part in candidate.content.parts:
                        if hasattr(part, "text") and part.text:
                            text += part.text
                        if hasattr(part, "function_call") and part.function_call:
                            if tool_calls is None:
                                tool_calls = []
                            tool_calls.append({
                                "id": f"call_{int(time.time())}",
                                "name": part.function_call.name,
                                "arguments": dict(part.function_call.args),
                            })
                    finish_reason = str(candidate.finish_reason.name) if candidate.finish_reason else "stop"
                else:
                    finish_reason = "stop"
                    # Check for blocked/prompt feedback
                    if response.prompt_feedback and response.prompt_feedback.block_reason:
                        text = f"[Blocked: {response.prompt_feedback.block_reason}]"
                        finish_reason = "content_filter"
            except Exception:
                text = str(response.text) if hasattr(response, "text") else str(response)
                finish_reason = "stop"

            # Usage
            usage = {}
            try:
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    um = response.usage_metadata
                    usage = {
                        "prompt_tokens": getattr(um, "prompt_token_count", 0),
                        "completion_tokens": getattr(um, "candidates_token_count", 0),
                        "total_tokens": getattr(um, "total_token_count", 0),
                    }
            except Exception:
                pass

            return ProviderResponse(
                text=text,
                model=gemini_model,
                usage=usage,
                finish_reason=finish_reason,
                latency_ms=elapsed,
                tool_calls=tool_calls,
            )

        return await asyncio.to_thread(_sync_call)

    def _build_sdk_contents(self, prompt: str, messages: Optional[list[dict]]) -> list:
        """Build Gemini SDK contents from messages or prompt, handling multimodal."""
        if not messages:
            # Simple prompt
            return [{"role": "user", "parts": [prompt]}]

        parts_list = []
        role = "user"

        for msg in messages:
            msg_role = msg.get("role", "user")
            content = msg.get("content", "")

            if msg_role == "system":
                # System messages are handled via system_instruction, skip
                continue

            if isinstance(content, str):
                parts_list.append({"role": "user" if msg_role != "assistant" else "model",
                                    "parts": [content]})
            elif isinstance(content, list):
                # Multimodal: [{"type": "text", "text": "..."}, {"type": "image_url", ...}]
                parts = []
                for item in content:
                    if item.get("type") == "text":
                        parts.append(item["text"])
                    elif item.get("type") == "image_url":
                        image_url = item.get("image_url", {}).get("url", "")
                        if image_url:
                            mime, data = _encode_image_to_base64(image_url)
                            if image_url.startswith(("http://", "https://")):
                                # For URLs, Gemini SDK can handle directly
                                import google.generativeai.types as types
                                parts.append(types.Part.from_uri(
                                    mime_type=mime, uri=data))
                            else:
                                # Local file: inline data
                                import google.generativeai.types as types
                                parts.append(types.Part.from_data(
                                    mime_type=mime, data=base64.b64decode(data)))
                if parts:
                    parts_list.append({
                        "role": "user" if msg_role != "assistant" else "model",
                        "parts": parts,
                    })
            role = msg_role if msg_role in ("user", "assistant") else role

        if not parts_list:
            parts_list = [{"role": "user", "parts": [prompt]}]
        return parts_list

    # ── REST fallback path ───────────────────────────────────

    async def _generate_rest(
        self,
        prompt: str,
        gemini_model: str,
        system: Optional[str],
        temperature: float,
        max_tokens: int,
        tools: Optional[list[dict]],
        messages: Optional[list[dict]],
    ) -> ProviderResponse:
        """Generate via httpx REST API call to Gemini."""
        url = f"{self.base_url}/models/{gemini_model}:generateContent"
        params = {"key": self.api_key}

        # Build contents from messages or prompt
        gemini_contents = self._build_rest_contents(prompt, messages)

        body: dict = {
            "contents": gemini_contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        if system:
            body["systemInstruction"] = {
                "parts": [{"text": system}],
            }

        if tools:
            gemini_tools = self._convert_tools_for_gemini(tools)
            body["tools"] = [{"functionDeclarations": gemini_tools}]

        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=body, params=params)
            if resp.status_code != 200:
                elapsed = (time.perf_counter() - t0) * 1000
                return ProviderResponse(
                    text=f"Gemini API error [{resp.status_code}]: {resp.text[:500]}",
                    model=gemini_model,
                    usage={},
                    finish_reason="error",
                    latency_ms=elapsed,
                )
            data = resp.json()

        elapsed = (time.perf_counter() - t0) * 1000

        # Extract response
        candidates = data.get("candidates", [])
        text = ""
        tool_calls = None

        if candidates:
            candidate = candidates[0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])
            for part in parts:
                if "text" in part:
                    text += part["text"]
                if "functionCall" in part:
                    if tool_calls is None:
                        tool_calls = []
                    fc = part["functionCall"]
                    tool_calls.append({
                        "id": f"call_{int(time.time())}",
                        "name": fc.get("name", ""),
                        "arguments": fc.get("args", {}),
                    })
            finish_reason = candidate.get("finishReason", "STOP").lower()
        else:
            finish_reason = "stop"
            # Check prompt feedback for blocks
            prompt_feedback = data.get("promptFeedback", {})
            if prompt_feedback.get("blockReason"):
                text = f"[Blocked: {prompt_feedback.get('blockReason')}]"
                finish_reason = "content_filter"

        # Usage
        usage_meta = data.get("usageMetadata", {})
        usage = {
            "prompt_tokens": usage_meta.get("promptTokenCount", 0),
            "completion_tokens": usage_meta.get("candidatesTokenCount", 0),
            "total_tokens": usage_meta.get("totalTokenCount", 0),
        }

        return ProviderResponse(
            text=text,
            model=gemini_model,
            usage=usage,
            finish_reason=finish_reason,
            latency_ms=elapsed,
            tool_calls=tool_calls,
        )

    def _build_rest_contents(
        self, prompt: str, messages: Optional[list[dict]]
    ) -> list[dict]:
        """Build Gemini REST contents array from messages, handling multimodal."""
        if not messages:
            return [{"role": "user", "parts": [{"text": prompt}]}]

        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                continue

            gemini_role = "user" if role != "assistant" else "model"

            if isinstance(content, str):
                contents.append({"role": gemini_role, "parts": [{"text": content}]})
            elif isinstance(content, list):
                parts = []
                for item in content:
                    if item.get("type") == "text":
                        parts.append({"text": item["text"]})
                    elif item.get("type") == "image_url":
                        image_url_data = item.get("image_url", {})
                        url = image_url_data.get("url", "")
                        detail = image_url_data.get("detail", "auto")
                        if url:
                            mime, data = _encode_image_to_base64(url)
                            if data.startswith(("http://", "https://")):
                                parts.append({
                                    "fileData": {
                                        "mimeType": mime,
                                        "fileUri": data,
                                    }
                                })
                            else:
                                parts.append({
                                    "inlineData": {
                                        "mimeType": mime,
                                        "data": data,
                                    }
                                })
                if parts:
                    contents.append({"role": gemini_role, "parts": parts})

        if not contents:
            contents = [{"role": "user", "parts": [{"text": prompt}]}]
        return contents

    # ── Tool conversion ──────────────────────────────────────

    @staticmethod
    def _convert_tools_for_gemini(tools: list[dict]) -> list[dict]:
        """Convert OpenAI-style tool definitions to Gemini format."""
        gemini_tools = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool["function"]
                gemini_tools.append({
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {
                        "type": "object",
                        "properties": {},
                    }),
                })
        return gemini_tools


# ── Self-test ───────────────────────────────────────────────

async def _self_test():
    """Quick self-test — requires GOOGLE_API_KEY."""
    provider = GeminiProvider()
    print(f"GeminiProvider initialized:")
    print(f"  API key present: {bool(provider.api_key)}")
    print(f"  Using SDK: {provider._using_sdk}")
    print(f"  Default model: {provider.default_model}")
    print(f"  Models: {await provider.list_models()}")

    if provider.api_key:
        print("\nTesting generate...")
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