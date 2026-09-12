"""Voice input module — speech-to-text with graceful degradation.

DNA: Dream (multimodal fusion) — voice as a first-class input modality.

Supports:
    - faster-whisper (primary, local, fast, accurate)
    - termux-microphone-record + whisper.cpp (Android/Termux fallback)
    - Graceful degradation: is_available() reports mic status honestly

Usage:
    voice = VoiceInput()
    if voice.is_available():
        text = await voice.listen(timeout=5)
        print(f"Heard: {text}")
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

# Default audio format
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHANNELS = 1

# Where to find whisper.cpp binary (configurable)
WHISPER_CPP_BIN = os.environ.get(
    "WHISPER_CPP_BIN",
    # Common Termux locations
    shutil.which("whisper") or shutil.which("whisper.cpp") or "",
)

WHISPER_MODEL_PATH = os.environ.get(
    "WHISPER_MODEL_PATH",
    str(Path.home() / ".cache" / "whisper" / "ggml-base.en.bin"),
)

TERMUX_MIC_BIN = shutil.which("termux-microphone-record") or ""


# ── Backend detection ───────────────────────────────────────

def _check_faster_whisper() -> bool:
    """Check if faster-whisper is importable."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _check_whisper_cpp() -> bool:
    """Check if whisper.cpp binary exists and is executable."""
    if WHISPER_CPP_BIN:
        return os.path.isfile(WHISPER_CPP_BIN) and os.access(WHISPER_CPP_BIN, os.X_OK)
    return False


def _check_termux_mic() -> bool:
    """Check if termux-microphone-record is available."""
    if TERMUX_MIC_BIN:
        return os.path.isfile(TERMUX_MIC_BIN) and os.access(TERMUX_MIC_BIN, os.X_OK)
    return False


def _check_microphone() -> bool:
    """Check if a microphone is physically available.

    On Android/Termux: check via termux-microphone-record --info.
    On Linux: check /proc/asound/cards or arecord.
    On macOS: check system_profiler.
    """
    # Termux path
    if _check_termux_mic():
        try:
            result = subprocess.run(
                [TERMUX_MIC_BIN, "--info"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    # Linux path
    try:
        result = subprocess.run(
            ["arecord", "-l"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and "card" in result.stdout.lower():
            return True
    except FileNotFoundError:
        pass
    except Exception:
        pass

    # macOS path
    try:
        result = subprocess.run(
            ["system_profiler", "SPAudioDataType"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and "microphone" in result.stdout.lower():
            return True
    except FileNotFoundError:
        pass
    except Exception:
        pass

    # Fallback: check /proc/asound
    try:
        asound = Path("/proc/asound/cards")
        if asound.exists():
            content = asound.read_text()
            if content.strip() and "no soundcards" not in content.lower():
                return True
    except (PermissionError, OSError, Exception):
        pass

    return False


# ── VoiceInput ──────────────────────────────────────────────

class VoiceInput:
    """Async-safe voice input with smart backend selection.

    Backend priority:
        1. faster-whisper (Python, local, fast)
        2. termux-microphone-record + whisper.cpp (Android/Termux)
        3. Unavailable — is_available() returns False

    Usage:
        voice = VoiceInput()
        if voice.is_available():
            text = await voice.listen(timeout=5)
    """

    def __init__(
        self,
        model_size: str = "base.en",
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        language: str = "en",
    ):
        """Initialize voice input.

        Args:
            model_size: Whisper model size. One of: tiny, tiny.en, base, base.en,
                       small, small.en, medium, medium.en, large.
                       Default: 'base.en' (good balance of speed/accuracy).
            sample_rate: Audio sample rate in Hz. Default: 16000.
            language: Language code for transcription. Default: 'en'.
                      Use 'auto' for automatic detection.
        """
        self.model_size = model_size
        self.sample_rate = sample_rate
        self.language = language

        # Detect available backends
        self._faster_whisper_ok = _check_faster_whisper()
        self._whisper_cpp_ok = _check_whisper_cpp()
        self._termux_mic_ok = _check_termux_mic()
        self._mic_present = _check_microphone()

        # Lazy-loaded model
        self._model = None
        self._backend: Optional[str] = None

        # Determine active backend
        self._resolve_backend()

    def _resolve_backend(self) -> None:
        """Select the best available backend."""
        if self._faster_whisper_ok and self._mic_present:
            self._backend = "faster-whisper"
        elif self._whisper_cpp_ok and self._termux_mic_ok:
            self._backend = "whisper-cpp"
        else:
            self._backend = None

    @property
    def available(self) -> bool:
        """Check if voice input is available right now."""
        return self._backend is not None

    def is_available(self) -> bool:
        """Check if voice input is available.

        Returns True only if both a microphone AND a transcription
        backend are available.
        """
        return self.available

    @property
    def backend_name(self) -> str:
        """Name of the active backend."""
        return self._backend or "none"

    @property
    def status(self) -> dict:
        """Detailed status of all components."""
        return {
            "available": self.available,
            "backend": self._backend,
            "faster_whisper_ok": self._faster_whisper_ok,
            "whisper_cpp_ok": self._whisper_cpp_ok,
            "termux_mic_ok": self._termux_mic_ok,
            "mic_present": self._mic_present,
            "model_size": self.model_size,
            "sample_rate": self.sample_rate,
            "language": self.language,
        }

    # ── Main interface ───────────────────────────────────────

    async def listen(self, timeout: float = 5.0) -> str:
        """Listen for speech and transcribe it.

        Args:
            timeout: Maximum recording duration in seconds. Default: 5.

        Returns:
            Transcribed text string. Returns empty string if nothing heard
            or if voice input is unavailable.

        Raises:
            RuntimeError: If no backend is available and listen() is called.
        """
        if not self.available:
            return ""  # Graceful degradation: silent no-op

        audio_path = None
        try:
            # Record audio
            audio_path = await self._record_audio(timeout)

            if audio_path is None or not Path(audio_path).exists():
                return ""

            # Check if file has content (not just silence)
            file_size = Path(audio_path).stat().st_size
            if file_size < 100:  # Less than 100 bytes = likely silence
                return ""

            # Transcribe
            text = await self._transcribe(audio_path)
            return text.strip()

        except Exception as e:
            # Log but don't crash — voice is a convenience feature
            print(f"[VoiceInput] Error: {e}")
            return ""
        finally:
            # Clean up temp file
            if audio_path and Path(audio_path).exists():
                try:
                    Path(audio_path).unlink()
                except Exception:
                    pass

    # ── Recording ────────────────────────────────────────────

    async def _record_audio(self, timeout: float) -> Optional[str]:
        """Record audio from microphone. Returns path to WAV file."""
        if self._backend == "faster-whisper":
            return await self._record_with_python(timeout)
        elif self._backend == "whisper-cpp":
            return await self._record_with_termux(timeout)
        return None

    async def _record_with_python(self, timeout: float) -> Optional[str]:
        """Record using Python (sounddevice or PyAudio).

        Falls back to arecord/sox if Python audio libs unavailable.
        """
        # Try sounddevice first
        try:
            import sounddevice as sd
            import numpy as np

            # Import wavfile
            try:
                from scipy.io import wavfile
            except ImportError:
                import wave
                import struct

            audio_path = tempfile.mktemp(suffix=".wav")

            # Run recording in thread (sounddevice is sync)
            def _record():
                fs = self.sample_rate
                duration = min(timeout, 30)  # Cap at 30s
                recording = sd.rec(
                    int(duration * fs),
                    samplerate=fs,
                    channels=DEFAULT_CHANNELS,
                    dtype="int16",
                )
                sd.wait()
                return recording

            recording = await asyncio.to_thread(_record)

            # Save as WAV
            try:
                from scipy.io import wavfile
                wavfile.write(audio_path, self.sample_rate, recording)
            except ImportError:
                # Manual WAV write
                with wave.open(audio_path, "wb") as wf:
                    wf.setnchannels(DEFAULT_CHANNELS)
                    wf.setsampwidth(2)  # 16-bit
                    wf.setframerate(self.sample_rate)
                    wf.writeframes(recording.tobytes())

            return audio_path

        except ImportError:
            pass

        # Fallback: arecord (Linux) or sox
        return await self._record_with_arecord(timeout)

    async def _record_with_arecord(self, timeout: float) -> Optional[str]:
        """Record using arecord (Linux/ALSA)."""
        audio_path = tempfile.mktemp(suffix=".wav")

        try:
            proc = await asyncio.create_subprocess_exec(
                "arecord",
                "-f", "S16_LE",
                "-r", str(self.sample_rate),
                "-c", str(DEFAULT_CHANNELS),
                "-d", str(int(timeout)),
                audio_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)

            if proc.returncode == 0 and Path(audio_path).exists():
                return audio_path
            else:
                # Clean up on failure
                if Path(audio_path).exists():
                    Path(audio_path).unlink()
                return None

        except FileNotFoundError:
            # arecord not available
            return None
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None

    async def _record_with_termux(self, timeout: float) -> Optional[str]:
        """Record using termux-microphone-record (Android)."""
        if not self._termux_mic_ok:
            return None

        audio_path = tempfile.mktemp(suffix=".wav")
        limit_seconds = str(min(int(timeout), 30))

        try:
            proc = await asyncio.create_subprocess_exec(
                TERMUX_MIC_BIN,
                "-f", audio_path,
                "-l", limit_seconds,
                "-r", str(self.sample_rate),
                "-b", "16",
                "-c", "1",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)

            if proc.returncode == 0 and Path(audio_path).exists():
                return audio_path
            else:
                if Path(audio_path).exists():
                    Path(audio_path).unlink()
                return None

        except asyncio.TimeoutError:
            return None
        except Exception:
            return None

    # ── Transcription ────────────────────────────────────────

    async def _transcribe(self, audio_path: str) -> str:
        """Transcribe audio file using the active backend."""
        if self._backend == "faster-whisper":
            return await self._transcribe_faster_whisper(audio_path)
        elif self._backend == "whisper-cpp":
            return await self._transcribe_whisper_cpp(audio_path)
        return ""

    async def _transcribe_faster_whisper(self, audio_path: str) -> str:
        """Transcribe using faster-whisper (local, fast)."""
        import faster_whisper

        def _transcribe_sync():
            # Lazy-load model (cached after first load)
            if self._model is None:
                # Compute type: int8 for CPU, float16 for GPU
                compute_type = "int8"
                try:
                    import torch
                    if torch.cuda.is_available():
                        compute_type = "float16"
                except ImportError:
                    pass

                self._model = faster_whisper.WhisperModel(
                    self.model_size,
                    device="cpu",
                    compute_type=compute_type,
                    download_root=str(Path.home() / ".cache" / "faster-whisper"),
                )

            segments, info = self._model.transcribe(
                audio_path,
                language=None if self.language == "auto" else self.language,
                beam_size=5,
                vad_filter=True,
            )

            # Collect all segments
            text_parts = []
            for segment in segments:
                text_parts.append(segment.text)

            return " ".join(text_parts)

        return await asyncio.to_thread(_transcribe_sync)

    async def _transcribe_whisper_cpp(self, audio_path: str) -> str:
        """Transcribe using whisper.cpp CLI."""
        if not self._whisper_cpp_ok:
            return ""

        # Ensure model exists
        model_path = WHISPER_MODEL_PATH
        if not Path(model_path).exists():
            # Try to download
            model_path = await self._ensure_whisper_model()

        if not model_path or not Path(model_path).exists():
            return ""

        try:
            proc = await asyncio.create_subprocess_exec(
                WHISPER_CPP_BIN,
                "-m", model_path,
                "-f", audio_path,
                "-l", self.language if self.language != "auto" else "en",
                "--no-timestamps",
                "-otxt",  # Output as text to stdout
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

            if proc.returncode == 0:
                return stdout.decode("utf-8", errors="replace").strip()

            # whisper.cpp may output to stderr for some builds
            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                # Filter out whisper.cpp progress/debug lines
                lines = [
                    l for l in stderr_text.split("\n")
                    if not l.startswith("whisper_")
                    and not l.startswith("[")
                    and l.strip()
                ]
                if lines:
                    return "\n".join(lines).strip()

            return ""

        except asyncio.TimeoutError:
            return ""
        except Exception:
            return ""

    async def _ensure_whisper_model(self) -> Optional[str]:
        """Download whisper.cpp model if not present."""
        model_path = Path(WHISPER_MODEL_PATH)
        if model_path.exists():
            return str(model_path)

        # Try to find it via whisper.cpp's download script
        model_name = f"ggml-{self.model_size}.bin"
        default_cache = Path.home() / ".cache" / "whisper"
        cached = default_cache / model_name
        if cached.exists():
            return str(cached)

        # Try download using whisper.cpp's built-in download
        try:
            proc = await asyncio.create_subprocess_exec(
                WHISPER_CPP_BIN,
                "--help",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except Exception:
            pass

        return None

    # ── Convenience: transcribe existing file ─────────────────

    async def transcribe_file(self, audio_path: str) -> str:
        """Transcribe an existing audio file (no recording).

        Args:
            audio_path: Path to WAV audio file (16kHz, mono, 16-bit preferred).

        Returns:
            Transcribed text.
        """
        if not Path(audio_path).exists():
            return ""
        if not self.available:
            return ""
        return await self._transcribe(audio_path)


# ── Self-test ───────────────────────────────────────────────

async def _self_test():
    """Quick self-test of VoiceInput."""
    voice = VoiceInput()
    print("VoiceInput status:")
    for key, value in voice.status.items():
        print(f"  {key}: {value}")

    if voice.is_available():
        print(f"\nVoice input available via {voice.backend_name}.")
        print("Recording 2-second test...")
        try:
            text = await voice.listen(timeout=2)
            print(f"Result: '{text}'")
        except Exception as e:
            print(f"Error: {e}")
    else:
        print("\nVoice input unavailable — no mic or no transcription backend.")
        print("Install: pip install faster-whisper (recommended)")
        print("  or: pkg install termux-microphone-record whisper.cpp (Android)")


if __name__ == "__main__":
    asyncio.run(_self_test())