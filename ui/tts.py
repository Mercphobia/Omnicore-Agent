"""TTS (Text-to-Speech) — Multi-provider speech synthesis with graceful fallback.

DNA: Voice (voice.py) as the STT counterpart — TTS completes the voice loop.

Providers (priority order for auto):
    1. edge-tts (subprocess, free, high quality)
    2. gTTS (subprocess, free, good quality)
    3. pyttsx3 (local, zero-latency, offline)
    4. termux-tts-speak (Android, system TTS engine)

Usage:
    tts = TTS()
    if tts.is_available():
        path = await tts.speak("Hello world", provider="auto")
        print(f"Saved to {path}")
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

# ── Constants ───────────────────────────────────────────────

AUDIO_DIR = Path.home() / ".omnicore" / "audio"
AUDIO_FORMAT = "mp3"

# ── Backend detection ───────────────────────────────────────

def _check_edge_tts() -> bool:
    """Check if edge-tts CLI is available."""
    return shutil.which("edge-tts") is not None


def _check_gtts() -> bool:
    """Check if gtts-cli or gTTS Python module is available."""
    if shutil.which("gtts-cli") is not None:
        return True
    try:
        import gtts  # noqa: F401
        return True
    except ImportError:
        return False


def _check_pyttsx3() -> bool:
    """Check if pyttsx3 is importable."""
    try:
        import pyttsx3  # noqa: F401
        return True
    except ImportError:
        return False


def _check_termux_tts() -> bool:
    """Check if termux-tts-speak is available (Android)."""
    return shutil.which("termux-tts-speak") is not None


# ── TTS ─────────────────────────────────────────────────────

class TTS:
    """Multi-provider text-to-speech with automatic backend selection.

    Backend priority (auto mode):
        1. edge-tts — Microsoft Edge TTS, free, natural quality
        2. gTTS — Google Text-to-Speech, free
        3. pyttsx3 — Local TTS engine, offline, zero latency
        4. termux-tts-speak — Android system TTS

    All backends are tried in order until one succeeds.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        """Initialize TTS engine.

        Args:
            output_dir: Directory to save audio files. Defaults to
                        ~/.omnicore/audio/.
        """
        self.output_dir = Path(output_dir) if output_dir else AUDIO_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Detect available providers
        self._edge_ok = _check_edge_tts()
        self._gtts_ok = _check_gtts()
        self._pyttsx3_ok = _check_pyttsx3()
        self._termux_ok = _check_termux_tts()

        # Ordered list of available provider names
        self._providers: list[str] = []
        if self._edge_ok:
            self._providers.append("edge-tts")
        if self._gtts_ok:
            self._providers.append("gtts")
        if self._pyttsx3_ok:
            self._providers.append("pyttsx3")
        if self._termux_ok:
            self._providers.append("termux-tts-speak")

    # ── Provider detection ─────────────────────────────────

    @property
    def available(self) -> bool:
        """True if at least one TTS provider is available."""
        return len(self._providers) > 0

    def is_available(self) -> bool:
        """Check if any TTS provider works.

        Returns:
            True if at least one provider is detected and ready.
        """
        return self.available

    @property
    def active_providers(self) -> list[str]:
        """List of available provider names."""
        return list(self._providers)

    @property
    def status(self) -> dict:
        """Detailed status of all TTS providers."""
        return {
            "available": self.available,
            "providers": self._providers,
            "edge_tts": self._edge_ok,
            "gtts": self._gtts_ok,
            "pyttsx3": self._pyttsx3_ok,
            "termux_tts_speak": self._termux_ok,
            "output_dir": str(self.output_dir),
        }

    # ── Main interface ─────────────────────────────────────

    async def speak(
        self,
        text: str,
        provider: str = "auto",
        voice: Optional[str] = None,
    ) -> Optional[str]:
        """Convert text to speech and save to file.

        Args:
            text: Text to synthesize. Can be multi-sentence.
            provider: Provider name or 'auto' for automatic selection.
                      Options: 'edge-tts', 'gtts', 'pyttsx3', 'termux-tts-speak'.
            voice: Optional voice name for the provider.
                   edge-tts: 'en-US-AriaNeural' (default), 'en-GB-SoniaNeural', etc.
                   gtts: 'en', 'en-uk', 'en-au', etc. (language code)
                   pyttsx3: system voice index or name

        Returns:
            Absolute path to the generated audio file, or None if synthesis
            failed or no provider is available.

        Raises:
            ValueError: If the specified provider is unknown.
        """
        if not text.strip():
            return None

        if provider == "auto":
            # Try providers in priority order
            for p in self._providers:
                result = await self._speak_with(text, p, voice)
                if result:
                    return result
            return None

        if provider not in ("edge-tts", "gtts", "pyttsx3", "termux-tts-speak"):
            raise ValueError(
                f"Unknown TTS provider: {provider}. "
                f"Options: {self._providers or ['edge-tts', 'gtts', 'pyttsx3', 'termux-tts-speak']}"
            )

        if provider not in self._providers:
            return None  # Provider detected but unavailable

        return await self._speak_with(text, provider, voice)

    # ── Provider implementations ───────────────────────────

    async def _speak_with(
        self,
        text: str,
        provider: str,
        voice: Optional[str] = None,
    ) -> Optional[str]:
        """Route to the correct provider implementation."""
        timestamp = int(time.time() * 1000)

        if provider == "edge-tts":
            return await self._speak_edge_tts(text, voice, timestamp)
        elif provider == "gtts":
            return await self._speak_gtts(text, voice, timestamp)
        elif provider == "pyttsx3":
            return await self._speak_pyttsx3(text, voice, timestamp)
        elif provider == "termux-tts-speak":
            return await self._speak_termux(text, voice, timestamp)
        return None

    async def _speak_edge_tts(
        self, text: str, voice: Optional[str], ts: int
    ) -> Optional[str]:
        """Synthesize using edge-tts CLI."""
        output_path = self.output_dir / f"edge_tts_{ts}.{AUDIO_FORMAT}"
        voice_name = voice or "en-US-AriaNeural"

        try:
            proc = await asyncio.create_subprocess_exec(
                "edge-tts",
                "--voice", voice_name,
                "--text", text,
                "--write-media", str(output_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

            if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                return str(output_path)

            # Clean up failed output
            if output_path.exists():
                output_path.unlink()
            return None

        except asyncio.TimeoutError:
            if output_path.exists():
                output_path.unlink()
            return None
        except FileNotFoundError:
            return None
        except Exception:
            if output_path.exists():
                output_path.unlink()
            return None

    async def _speak_gtts(
        self, text: str, voice: Optional[str], ts: int
    ) -> Optional[str]:
        """Synthesize using gTTS (Google TTS).

        Uses gtts-cli if available, otherwise Python API.
        """
        output_path = self.output_dir / f"gtts_{ts}.{AUDIO_FORMAT}"
        lang = voice or "en"

        # Try gtts-cli first (subprocess, no import needed)
        if shutil.which("gtts-cli"):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "gtts-cli",
                    text,
                    "--lang", lang,
                    "--output", str(output_path),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

                if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    return str(output_path)
            except (asyncio.TimeoutError, FileNotFoundError, Exception):
                pass

        # Fall back to Python gTTS module
        try:
            from gtts import gTTS

            def _synthesize():
                tts = gTTS(text=text, lang=lang, slow=False)
                tts.save(str(output_path))

            await asyncio.to_thread(_synthesize)

            if output_path.exists() and output_path.stat().st_size > 0:
                return str(output_path)
        except ImportError:
            pass
        except Exception:
            pass

        if output_path.exists():
            output_path.unlink()
        return None

    async def _speak_pyttsx3(
        self, text: str, voice: Optional[str], ts: int
    ) -> Optional[str]:
        """Synthesize using pyttsx3 (local TTS)."""
        output_path = self.output_dir / f"pyttsx3_{ts}.wav"

        try:
            import pyttsx3

            def _synthesize():
                engine = pyttsx3.init()
                if voice:
                    # voice can be a name or an index
                    voices = engine.getProperty("voices")
                    if voice.isdigit():
                        idx = int(voice)
                        if 0 <= idx < len(voices):
                            engine.setProperty("voice", voices[idx].id)
                    else:
                        for v in voices:
                            if voice.lower() in v.name.lower() or voice.lower() in v.id.lower():
                                engine.setProperty("voice", v.id)
                                break

                engine.setProperty("rate", 175)
                engine.save_to_file(text, str(output_path))
                engine.runAndWait()
                engine.stop()

            await asyncio.to_thread(_synthesize)

            if output_path.exists() and output_path.stat().st_size > 0:
                return str(output_path)
        except ImportError:
            pass
        except Exception:
            pass

        if output_path.exists():
            output_path.unlink()
        return None

    async def _speak_termux(
        self, text: str, voice: Optional[str], ts: int
    ) -> Optional[str]:
        """Synthesize using termux-tts-speak (Android)."""
        # termux-tts-speak plays audio directly, so we also save a marker,
        # but it doesn't produce a file. We return a fake path as a
        # "spoken" acknowledgment.
        try:
            proc = await asyncio.create_subprocess_exec(
                "termux-tts-speak",
                text,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

            if proc.returncode == 0:
                # Create a marker file so caller knows it was spoken
                marker = self.output_dir / f"spoken_{ts}.txt"
                marker.write_text(f"Spoken via termux-tts-speak: {text[:100]}")
                return str(marker)

            return None

        except FileNotFoundError:
            return None
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None

    # ── Voice listing ──────────────────────────────────────

    def list_voices(self, provider: str = "auto") -> list[str]:
        """List available voices for a provider.

        Args:
            provider: Provider name. 'auto' lists voices for the first
                      available provider.

        Returns:
            List of voice names/identifiers. Empty list if provider
            is unavailable or doesn't support voice enumeration.
        """
        if provider == "auto":
            for p in self._providers:
                voices = self._list_voices_for(p)
                if voices:
                    return voices
            return []

        return self._list_voices_for(provider)

    def _list_voices_for(self, provider: str) -> list[str]:
        """List voices for a specific provider."""
        if provider == "edge-tts":
            return self._list_voices_edge_tts()
        elif provider == "gtts":
            return self._list_voices_gtts()
        elif provider == "pyttsx3":
            return self._list_voices_pyttsx3()
        elif provider == "termux-tts-speak":
            return ["system-default"]  # Termux uses system voice
        return []

    def _list_voices_edge_tts(self) -> list[str]:
        """List edge-tts voices via CLI."""
        if not self._edge_ok:
            return []
        try:
            result = subprocess.run(
                ["edge-tts", "--list-voices"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                voices = []
                for line in result.stdout.split("\n"):
                    if "ShortName" in line or "Name:" in line:
                        # Extract voice name
                        parts = line.strip().split()
                        for part in parts:
                            if "-" in part and "Neural" in part:
                                voices.append(part.strip(",'\""))
                return voices
        except Exception:
            pass
        # Return popular voices as fallback
        return [
            "en-US-AriaNeural", "en-US-GuyNeural", "en-US-JennyNeural",
            "en-GB-SoniaNeural", "en-GB-RyanNeural",
            "en-AU-NatashaNeural", "en-IN-NeerjaNeural",
        ]

    def _list_voices_gtts(self) -> list[str]:
        """List gTTS language codes."""
        return [
            "en", "en-us", "en-uk", "en-au", "en-in", "en-ca",
            "fr", "de", "es", "it", "ja", "ko", "pt", "ru", "zh", "ar",
        ]

    def _list_voices_pyttsx3(self) -> list[str]:
        """List pyttsx3 available voices."""
        if not self._pyttsx3_ok:
            return []
        try:
            import pyttsx3
            engine = pyttsx3.init()
            voices = engine.getProperty("voices")
            engine.stop()
            return [v.name for v in voices]
        except Exception:
            return []

    # ── Convenience: speak in background ───────────────────

    async def speak_async(
        self,
        text: str,
        provider: str = "auto",
        voice: Optional[str] = None,
    ) -> Optional[asyncio.Task]:
        """Speak in background (fire and forget).

        Returns:
            An asyncio.Task, or None if no provider available.
            The task resolves with the audio file path or None.
        """
        if not self.available:
            return None
        return asyncio.create_task(self.speak(text, provider, voice))


# ── Module-level convenience ────────────────────────────────

_default_tts: Optional[TTS] = None


def get_tts() -> TTS:
    """Get or create the singleton TTS instance."""
    global _default_tts
    if _default_tts is None:
        _default_tts = TTS()
    return _default_tts


async def speak(text: str) -> Optional[str]:
    """Quick one-liner: speak text with auto provider."""
    return await get_tts().speak(text)


# ── Self-test ───────────────────────────────────────────────

async def _self_test():
    """Quick self-test of TTS."""
    tts = TTS()
    print("TTS status:")
    for key, value in tts.status.items():
        print(f"  {key}: {value}")

    if not tts.is_available():
        print("\nNo TTS provider available.")
        print("Install one:")
        print("  pip install edge-tts          (recommended)")
        print("  pip install gtts              (Google TTS)")
        print("  pip install pyttsx3           (local TTS)")
        print("  pkg install termux-api        (Android)")
        return

    print(f"\nActive providers: {tts.active_providers}")

    # Show voices for first provider
    voices = tts.list_voices()
    if voices:
        print(f"Voices ({len(voices)} available):")
        for v in voices[:10]:
            print(f"  - {v}")
        if len(voices) > 10:
            print(f"  ... and {len(voices) - 10} more")

    # Test synthesis
    print("\nSynthesizing test phrase...")
    result = await tts.speak("Hello, OmniCore TTS is operational.")
    if result:
        size = Path(result).stat().st_size
        print(f"OK — saved to {result} ({size} bytes)")
    else:
        print("FAIL — all providers failed synthesis")


if __name__ == "__main__":
    asyncio.run(_self_test())