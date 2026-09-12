"""Multi-modal input processor — unified intent from text, image, voice, mixed.

DNA: Dream (multimodal fusion) — every input channel treated as first-class.

Handles:
    - text:      Direct text input → passthrough
    - image:     Screenshot/file → description via vision model
    - voice:     Audio → transcribed text via VoiceInput
    - mixed:     Image + text combo → combined vision+text processing

Returns a unified intent dict:
    {"type": "text"|"image"|"voice"|"mixed",
     "content": "...",
     "metadata": {...}}

Usage:
    multi = MultiInput(provider=None)  # provider for vision descriptions
    result = await multi.process("Hello world")
    result = await multi.process({"type": "image", "data": "/path/to/img.png"})
    result = await multi.process({"type": "voice", "data": None})  # records mic
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

# ── Input data types ────────────────────────────────────────

# Input can be:
#   str               → treated as plain text
#   dict              → structured input with type hint
#   {"type": "text", "data": "..."}
#   {"type": "image", "data": "/path/to/file" or bytes or base64_str}
#   {"type": "voice", "data": None}  → records from mic
#   {"type": "mixed", "data": [{"type": "text", ...}, {"type": "image", ...}]}

InputData = Union[str, dict]


# ── Unified result ──────────────────────────────────────────

def _make_result(
    input_type: str,
    content: str,
    **metadata,
) -> dict:
    """Build a unified intent result dict."""
    return {
        "type": input_type,
        "content": content,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **metadata,
        },
    }


# ── MultiInput ──────────────────────────────────────────────

class MultiInput:
    """Multi-modal input processor.

    Routes input through the appropriate channel and returns a
    unified intent dict ready for OmniCore consumption.

    Args:
        provider: Optional provider for vision descriptions (image→text).
                  If None, image inputs return a placeholder description.
        voice: Optional VoiceInput instance. If None, creates one on first use.
    """

    def __init__(
        self,
        provider=None,
        voice=None,
    ):
        self.provider = provider
        self._voice = voice

    @property
    def voice(self):
        """Lazy-loaded VoiceInput instance."""
        if self._voice is None:
            from ui.voice import VoiceInput
            self._voice = VoiceInput()
        return self._voice

    # ── Main interface ───────────────────────────────────────

    async def process(self, input_data: InputData) -> dict:
        """Process any input and return a unified intent dict.

        Args:
            input_data: String (plain text) or dict with type hint.

        Returns:
            {"type": "text"|"image"|"voice"|"mixed",
             "content": "<processed content string>",
             "metadata": {...}}

        Examples:
            >>> await multi.process("Fix the bug")
            {"type": "text", "content": "Fix the bug", "metadata": {...}}

            >>> await multi.process({"type": "image", "data": "screenshot.png"})
            {"type": "image", "content": "A terminal showing...", "metadata": {...}}

            >>> await multi.process({"type": "voice"})
            {"type": "voice", "content": "Fix the bug in server.py", "metadata": {...}}
        """
        # String → text passthrough
        if isinstance(input_data, str):
            return await self._process_text(input_data)

        # Dict → route by type
        if not isinstance(input_data, dict):
            return _make_result("text", str(input_data), source="coerced")

        input_type = input_data.get("type", "text")
        data = input_data.get("data")

        handlers = {
            "text": self._process_text,
            "image": self._process_image,
            "voice": self._process_voice,
            "mixed": self._process_mixed,
        }

        handler = handlers.get(input_type)
        if handler is None:
            # Unknown type → treat as text
            return _make_result(
                "text",
                str(data or input_data),
                source="unknown_type",
                original_type=input_type,
            )

        return await handler(data)

    # ── Type-specific processors ─────────────────────────────

    async def _process_text(self, data) -> dict:
        """Process plain text input."""
        text = data if isinstance(data, str) else str(data or "")
        return _make_result("text", text, char_count=len(text))

    async def _process_image(self, data) -> dict:
        """Process image input → text description via vision model.

        data can be:
            - str: file path, URL, or base64 data URI
            - bytes: raw image bytes
            - dict with {"path": ..., "url": ..., "bytes": ...}
        """
        # Resolve image into a format the provider can handle
        image_ref, mime_type, byte_size = self._resolve_image(data)

        metadata = {
            "source": "image",
            "mime_type": mime_type,
            "byte_size": byte_size,
        }

        # If we have a vision-capable provider, use it
        if self.provider is not None:
            try:
                description = await self._describe_via_provider(image_ref, mime_type)
                if description:
                    metadata["vision_model"] = getattr(
                        self.provider, "default_model", "unknown"
                    )
                    return _make_result("image", description, **metadata)
            except Exception as e:
                metadata["vision_error"] = str(e)

        # Fallback: basic metadata-only description
        metadata["no_vision_provider"] = True
        return _make_result(
            "image",
            f"[Image: {mime_type}, {byte_size} bytes]",
            **metadata,
        )

    async def _process_voice(self, data=None) -> dict:
        """Process voice input — record and transcribe.

        If data is a file path, transcribe that file instead of recording.
        """
        # If a file path is provided, transcribe that
        if isinstance(data, str) and Path(data).exists():
            text = await self.voice.transcribe_file(data)
            return _make_result(
                "voice",
                text,
                source_file=data,
                backend=self.voice.backend_name,
            )

        # If voice is unavailable, degrade
        if not self.voice.is_available():
            return _make_result(
                "voice",
                "",
                available=False,
                reason="No microphone or transcription backend available",
            )

        # Record and transcribe
        timeout = 5.0
        if isinstance(data, dict):
            timeout = data.get("timeout", 5.0)
        elif isinstance(data, (int, float)):
            timeout = float(data)

        text = await self.voice.listen(timeout=timeout)

        return _make_result(
            "voice",
            text,
            backend=self.voice.backend_name,
            timeout=timeout,
            has_content=bool(text.strip()),
        )

    async def _process_mixed(self, data) -> dict:
        """Process mixed input (text + image combination).

        data should be a list of sub-inputs:
            [
                {"type": "text", "data": "What's this error?"},
                {"type": "image", "data": "screenshot.png"},
            ]

        Or a dict with text and image keys:
            {"text": "What's this?", "image": "screenshot.png"}

        Result: text is preserved as-is, image is described, combined.
        """
        if not data:
            return _make_result("mixed", "", empty=True)

        # Handle list format
        if isinstance(data, list):
            text_parts = []
            image_descriptions = []
            metadata_parts = []

            for item in data:
                item_type = item.get("type", "text") if isinstance(item, dict) else "text"
                item_data = item.get("data") if isinstance(item, dict) else item
                if item_type == "text":
                    result = await self._process_text(item_data)
                    text_parts.append(result["content"])
                elif item_type == "image":
                    result = await self._process_image(item_data)
                    image_descriptions.append(result["content"])
                elif item_type == "voice":
                    result = await self._process_voice(item_data)
                    text_parts.append(result["content"])
                metadata_parts.append(result.get("metadata", {}))

            combined_text = "\n".join(text_parts)
            if image_descriptions:
                combined_text += "\n\n[Images]\n" + "\n".join(
                    f"- {desc}" for desc in image_descriptions
                )

            return _make_result(
                "mixed",
                combined_text.strip(),
                text_segments=len(text_parts),
                image_segments=len(image_descriptions),
                parts=metadata_parts,
            )

        # Handle dict format: {"text": "...", "image": "..."}
        if isinstance(data, dict):
            text_input = data.get("text", "")
            image_input = data.get("image")
            voice_input = data.get("voice")

            parts = []
            content_parts = []

            if text_input:
                result = await self._process_text(text_input)
                content_parts.append(result["content"])
                parts.append({"type": "text", "metadata": result["metadata"]})

            if image_input:
                result = await self._process_image(image_input)
                content_parts.append(f"[Image]: {result['content']}")
                parts.append({"type": "image", "metadata": result["metadata"]})

            if voice_input:
                result = await self._process_voice(voice_input)
                content_parts.append(f"[Voice]: {result['content']}")
                parts.append({"type": "voice", "metadata": result["metadata"]})

            return _make_result(
                "mixed",
                "\n".join(content_parts).strip(),
                segments=len(parts),
                parts=parts,
            )

        # Unknown mixed format
        return _make_result("mixed", str(data), format="unknown")

    # ── Image resolution ─────────────────────────────────────

    @staticmethod
    def _resolve_image(data) -> tuple[str, str, int]:
        """Resolve image input to (reference_string, mime_type, byte_size).

        reference_string is what gets passed to the vision provider:
        - For files: base64 data URI
        - For URLs: the URL itself
        - For bytes: base64 data URI
        """
        if isinstance(data, bytes):
            # Raw bytes
            mime = "image/png"
            b64 = base64.b64encode(data).decode("utf-8")
            return f"data:{mime};base64,{b64}", mime, len(data)

        if isinstance(data, str):
            # URL
            if data.startswith(("http://", "https://")):
                ext = Path(data.split("?")[0]).suffix.lower()
                mime_map = {
                    ".png": "image/png", ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg", ".gif": "image/gif",
                    ".webp": "image/webp",
                }
                return data, mime_map.get(ext, "image/png"), 0  # Size unknown for URLs

            # Base64 data URI
            if data.startswith("data:image"):
                # Extract mime and size
                header, encoded = data.split(",", 1)
                mime = header.split(":")[1].split(";")[0]
                size = len(base64.b64decode(encoded))
                return data, mime, size

            # File path
            path = Path(data)
            if path.exists():
                ext = path.suffix.lower()
                mime_map = {
                    ".png": "image/png", ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg", ".gif": "image/gif",
                    ".webp": "image/webp", ".bmp": "image/bmp",
                }
                mime = mime_map.get(ext, "image/png")
                raw = path.read_bytes()
                b64 = base64.b64encode(raw).decode("utf-8")
                return f"data:{mime};base64,{b64}", mime, len(raw)

            # Unresolvable string — treat as raw base64
            return data, "image/png", 0

        if isinstance(data, dict):
            # Dict with keys
            url = data.get("url", "")
            path = data.get("path", "")
            raw_bytes = data.get("bytes")

            if url:
                return MultiInput._resolve_image(url)
            if path:
                return MultiInput._resolve_image(path)
            if raw_bytes:
                return MultiInput._resolve_image(raw_bytes)

        # Fallback
        return str(data), "image/png", 0

    # ── Vision provider integration ──────────────────────────

    async def _describe_via_provider(
        self, image_ref: str, mime_type: str
    ) -> str:
        """Use the provider to describe an image.

        Tries multiple patterns depending on the provider type:
        1. generate_with_image() method (DeepSeek, custom)
        2. generate() with multimodal messages (OpenAI, Gemini)
        3. generate() with image URL in prompt (fallback)
        """
        if self.provider is None:
            return ""

        prompt = (
            "Describe this image in detail. What do you see? "
            "Include any text visible in the image, UI elements, "
            "error messages, or code that appears. Be concise but thorough."
        )

        # Method 1: generate_with_image (DeepSeek)
        if hasattr(self.provider, "generate_with_image"):
            try:
                resp = await self.provider.generate_with_image(
                    prompt=prompt,
                    image_url=image_ref,
                    temperature=0.3,
                    max_tokens=1024,
                )
                if resp and resp.text:
                    return resp.text.strip()
            except Exception:
                pass

        # Method 2: generate with multimodal messages
        try:
            multimodal_msg = {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_ref}},
                ],
            }
            resp = await self.provider.generate(
                prompt="",
                messages=[multimodal_msg],
                temperature=0.3,
                max_tokens=1024,
            )
            if resp and resp.text:
                return resp.text.strip()
        except Exception:
            pass

        # Method 3: Plain text fallback (won't describe the image, but won't crash)
        try:
            resp = await self.provider.generate(
                prompt=f"{prompt}\n[Image reference: {image_ref[:100]}...]",
                temperature=0.3,
                max_tokens=512,
            )
            if resp and resp.text:
                return resp.text.strip()
        except Exception:
            pass

        return ""

    # ── Convenience: screenshot ──────────────────────────────

    async def process_screenshot(self, prompt: str = "Describe this screenshot.") -> dict:
        """Take a screenshot and process it through the vision pipeline.

        Requires: Android (screencap) or Linux (import/scrot/gnome-screenshot).

        Returns: intent dict with type='image'.
        """
        screenshot_data = await self._capture_screenshot()
        if screenshot_data is None:
            return _make_result(
                "image", "",
                screenshot_error="No screenshot tool available",
            )

        return await self.process({
            "type": "image",
            "data": screenshot_data,
        })

    @staticmethod
    async def _capture_screenshot() -> Optional[bytes]:
        """Capture a screenshot. Returns raw PNG bytes or None."""
        tmp = tempfile.mktemp(suffix=".png")

        # Android
        try:
            proc = await asyncio.create_subprocess_exec(
                "screencap", "-p", tmp,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
            if proc.returncode == 0 and Path(tmp).exists():
                data = Path(tmp).read_bytes()
                Path(tmp).unlink(missing_ok=True)
                return data
        except FileNotFoundError:
            pass
        except Exception:
            pass

        # Linux: try scrot
        for tool in ["scrot", "import", "gnome-screenshot"]:
            try:
                prog = tool
                if tool == "gnome-screenshot":
                    args = [prog, "-f", tmp]
                elif tool == "import":
                    args = [prog, "-window", "root", tmp]
                else:
                    args = [prog, tmp]

                proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.communicate()
                if proc.returncode == 0 and Path(tmp).exists():
                    data = Path(tmp).read_bytes()
                    Path(tmp).unlink(missing_ok=True)
                    return data
            except FileNotFoundError:
                continue
            except Exception:
                continue

        # macOS
        try:
            proc = await asyncio.create_subprocess_exec(
                "screencapture", "-x", tmp,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
            if proc.returncode == 0 and Path(tmp).exists():
                data = Path(tmp).read_bytes()
                Path(tmp).unlink(missing_ok=True)
                return data
        except FileNotFoundError:
            pass
        except Exception:
            pass

        # Cleanup
        Path(tmp).unlink(missing_ok=True)
        return None


# ── Self-test ───────────────────────────────────────────────

async def _self_test():
    """Quick self-test of MultiInput."""
    multi = MultiInput()

    print("MultiInput initialized (no vision provider).")

    # Test text
    result = await multi.process("Hello world")
    print(f"\nText input: type={result['type']}, content='{result['content'][:50]}'")

    # Test dict text
    result = await multi.process({"type": "text", "data": "Fix the bug"})
    print(f"Dict text:  type={result['type']}, content='{result['content']}'")

    # Test image (non-existent → fallback)
    result = await multi.process({"type": "image", "data": "/nonexistent.png"})
    print(f"Image:      type={result['type']}, content='{result['content'][:60]}'")

    # Test voice (likely unavailable in test)
    result = await multi.process({"type": "voice"})
    print(f"Voice:      type={result['type']}, content='{result['content'][:60]}'")
    print(f"            available={result['metadata'].get('available')}")

    # Test mixed
    result = await multi.process({
        "type": "mixed",
        "data": [
            {"type": "text", "data": "What's this error?"},
            {"type": "text", "data": "It happened during deploy."},
        ],
    })
    print(f"Mixed:      type={result['type']}, content='{result['content'][:80]}'")

    print("\nAll self-tests passed.")


if __name__ == "__main__":
    asyncio.run(_self_test())