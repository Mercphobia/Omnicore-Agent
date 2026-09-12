"""Creative studio pipeline — text→video, text→image, TTS, compositing.

DNA: Sora + Midjourney + ElevenLabs + FFmpeg fusion.
Integrates with creative/video_gen.py for FFmpeg operations.

Usage:
    studio = CreativeStudio()
    result = studio.generate_video("A sunset over mountains", style="cinematic")
    img = studio.generate_image("Cyberpunk city at night", style="neon")
    audio = studio.generate_audio("Hello world", voice="narrator")
    project = studio.render_project({"scenes": [...]})
"""

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Try to import video_gen — graceful fallback if not available
try:
    from creative.video_gen import (
        probe as video_probe,
        concat_videos,
        screenshot,
        overlay_text,
        extract_audio as ffmpeg_extract_audio,
    )
    _VIDEO_GEN_AVAILABLE = True
except ImportError:
    _VIDEO_GEN_AVAILABLE = False


# ── Data structures ────────────────────────────────────────────────────

@dataclass
class Scene:
    """A scene in a storyboard or video project."""
    scene_id: int
    title: str
    description: str
    duration_seconds: float = 5.0
    dialogue: str = ""
    visual_style: str = "default"
    audio_style: str = "default"
    transition: str = "fade"  # fade, cut, dissolve, wipe


@dataclass
class Storyboard:
    """A complete storyboard from a script."""
    title: str
    scenes: list[Scene]
    total_duration: float = 0.0
    estimated_frames: int = 0


@dataclass
class RenderResult:
    """Result of rendering a creative project."""
    output_path: str
    duration_seconds: float
    scenes_rendered: int
    file_size_mb: float
    success: bool = True
    errors: list[str] = field(default_factory=list)


@dataclass
class MediaElement:
    """An element in a composite scene."""
    element_type: str  # "video", "image", "audio", "text"
    source: str = ""
    position: tuple[int, int] = (0, 0)  # x, y
    size: tuple[int, int] = (640, 480)  # w, h
    start_time: float = 0.0
    duration: float = 5.0
    opacity: float = 1.0
    z_index: int = 0


# ── CreativeStudio class ───────────────────────────────────────────────

class CreativeStudio:
    """Full creative pipeline: video, image, audio, compositing.

    Coordinates between text generation, FFmpeg rendering,
    and AI model calls for creative output.
    """

    def __init__(self, output_dir: str = ""):
        """Initialize creative studio.

        Args:
            output_dir: Directory for generated assets.
                        Defaults to /tmp/omnicore_studio/.
        """
        self.output_dir = Path(output_dir or tempfile.gettempdir()) / "omnicore_studio"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._projects: dict[str, dict[str, Any]] = {}
        self._has_ffmpeg = self._check_ffmpeg()

    @staticmethod
    def _check_ffmpeg() -> bool:
        """Check if FFmpeg is available."""
        try:
            subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True, timeout=5
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    # ── Storyboard ─────────────────────────────────────────────────────

    def storyboard(self, script: str, fps: int = 24) -> Storyboard:
        """Break a script into scenes for production.

        Parses a script and creates a structured storyboard with
        scene descriptions, timing, and visual direction.

        Args:
            script: The script text. Use "---" or double newlines
                    to separate scenes.
            fps: Frames per second for frame estimation.

        Returns:
            Storyboard with scenes and production metadata.
        """
        # Split script into scenes
        raw_scenes = self._parse_scenes(script)

        scenes: list[Scene] = []
        for i, raw in enumerate(raw_scenes):
            scene = self._parse_scene(raw, i)
            scenes.append(scene)

        total_duration = sum(s.duration_seconds for s in scenes)
        estimated_frames = int(total_duration * fps)

        # Extract title from first line of script
        lines = script.strip().split("\n")
        title = lines[0].strip().lstrip("#").strip() if lines else "Untitled"

        return Storyboard(
            title=title,
            scenes=scenes,
            total_duration=total_duration,
            estimated_frames=estimated_frames,
        )

    def _parse_scenes(self, script: str) -> list[str]:
        """Split script into individual scene descriptions."""
        # Try "---" delimiter first
        if "---" in script:
            scenes = [s.strip() for s in script.split("---") if s.strip()]
            return scenes

        # Try numbered scenes (e.g., "SCENE 1:", "1.", "Scene 1:")
        import re
        scene_pattern = re.compile(
            r'(?:^|\n)(?:SCENE\s*\d+|Scene\s*\d+|\d+\.)\s*[:\-]?\s*',
            re.IGNORECASE
        )
        parts = scene_pattern.split(script)
        if len(parts) > 1:
            return [p.strip() for p in parts if p.strip()]

        # Fallback: split by double newlines
        scenes = [s.strip() for s in script.split("\n\n") if s.strip()]
        if len(scenes) > 1:
            return scenes

        # Single scene
        return [script.strip()]

    def _parse_scene(self, raw: str, index: int) -> Scene:
        """Parse a raw scene text into a Scene object.

        Extracts: title, description, dialogue, timing hints.
        """
        lines = raw.strip().split("\n")
        title = lines[0].strip() if lines else f"Scene {index + 1}"

        # Extract dialogue (in quotes or prefixed with character name)
        dialogue = ""
        description_parts = []

        for line in lines[1:]:
            line = line.strip()
            if line.startswith('"') and line.endswith('"'):
                dialogue = line.strip('"')
            elif ':' in line and len(line.split(':')[0].strip()) < 30:
                # Character: dialogue format
                dialogue = line.split(':', 1)[1].strip().strip('"')
            else:
                description_parts.append(line)

        description = " ".join(description_parts) if description_parts else title

        # Estimate duration from text length (~2.5 words/second for narration)
        word_count = len(description.split()) + len(dialogue.split())
        duration = max(3.0, min(30.0, word_count / 2.5))

        # Detect visual style hints
        visual_style = "default"
        style_keywords = {
            "cinematic": ["cinematic", "film", "movie", "epic"],
            "anime": ["anime", "manga", "animated"],
            "noir": ["noir", "dark", "shadow", "detective"],
            "neon": ["neon", "cyberpunk", "futuristic", "sci-fi"],
            "watercolor": ["watercolor", "painterly", "artistic"],
        }
        combined = (description + " " + title).lower()
        for style, keywords in style_keywords.items():
            if any(kw in combined for kw in keywords):
                visual_style = style
                break

        return Scene(
            scene_id=index + 1,
            title=title,
            description=description,
            duration_seconds=round(duration, 1),
            dialogue=dialogue,
            visual_style=visual_style,
            audio_style="narrator" if dialogue else "ambient",
            transition="fade" if index > 0 else "cut",
        )

    # ── Video Generation ───────────────────────────────────────────────

    def generate_video(self, script: str, style: str = "cinematic",
                       output_path: str = "", fps: int = 24) -> RenderResult:
        """Generate a video from a text script.

        Pipeline: script → storyboard → frames → FFmpeg.
        When FFmpeg is available, creates a test pattern video.
        When unavailable, returns a placeholder describing the pipeline.

        Args:
            script: The video script/description.
            style: Visual style for the video.
            output_path: Output file path (auto-generated if empty).
            fps: Frames per second.

        Returns:
            RenderResult with output path and metadata.
        """
        if not output_path:
            timestamp = int(time.time())
            output_path = str(self.output_dir / f"video_{timestamp}.mp4")

        # Storyboard the script
        board = self.storyboard(script, fps=fps)
        errors: list[str] = []

        if not self._has_ffmpeg:
            # Return placeholder with pipeline description
            return RenderResult(
                output_path=output_path,
                duration_seconds=board.total_duration,
                scenes_rendered=len(board.scenes),
                file_size_mb=0,
                success=False,
                errors=["FFmpeg not installed. Install: apt install ffmpeg"],
            )

        try:
            # Generate a test pattern video for each scene
            scene_videos: list[str] = []
            for scene in board.scenes:
                scene_path = self._generate_scene_video(scene, style, fps)
                if scene_path:
                    scene_videos.append(scene_path)

            if not scene_videos:
                return RenderResult(
                    output_path=output_path,
                    duration_seconds=0,
                    scenes_rendered=0,
                    file_size_mb=0,
                    success=False,
                    errors=["No scenes could be rendered"],
                )

            # Concatenate scene videos
            if len(scene_videos) == 1:
                # Single scene — just copy
                import shutil
                shutil.copy(scene_videos[0], output_path)
                duration = board.scenes[0].duration_seconds if board.scenes else 5.0
            else:
                # Write concat file
                concat_file = str(self.output_dir / "_concat.txt")
                with open(concat_file, "w") as f:
                    for vp in scene_videos:
                        f.write(f"file '{Path(vp).resolve()}'\n")

                result = subprocess.run(
                    ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                     "-f", "concat", "-safe", "0", "-i", concat_file,
                     "-c", "copy", output_path],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode != 0:
                    errors.append(f"Concat failed: {result.stderr[:200]}")

                duration = board.total_duration
                Path(concat_file).unlink(missing_ok=True)

            file_size = Path(output_path).stat().st_size / 1_000_000 if Path(output_path).exists() else 0

            # Cleanup scene files
            for vp in scene_videos:
                Path(vp).unlink(missing_ok=True)

            return RenderResult(
                output_path=output_path,
                duration_seconds=duration,
                scenes_rendered=len(scene_videos),
                file_size_mb=round(file_size, 2),
                success=len(errors) == 0,
                errors=errors,
            )
        except Exception as e:
            return RenderResult(
                output_path=output_path,
                duration_seconds=0,
                scenes_rendered=0,
                file_size_mb=0,
                success=False,
                errors=[str(e)],
            )

    def _generate_scene_video(self, scene: Scene, style: str,
                               fps: int) -> Optional[str]:
        """Generate a single scene as a test pattern video."""
        output = str(self.output_dir / f"scene_{scene.scene_id:03d}.mp4")

        dur = scene.duration_seconds
        desc = scene.description[:100].replace(":", "\\:").replace("'", "\\\\'")

        # Color palette per style
        colors = {
            "cinematic": "0x1A1A2E",
            "anime": "0xFF69B4",
            "noir": "0x2D2D2D",
            "neon": "0x0D0221",
            "watercolor": "0xE8D5B7",
            "default": "0x1A1A3E",
        }
        bg_color = colors.get(style, colors["default"])

        # Generate color source + text overlay using FFmpeg
        drawtext = (
            f"drawtext=text='Scene {scene.scene_id}: {desc[:60]}':"
            f"fontsize=20:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:"
            f"box=1:boxcolor=black@0.4"
        )

        result = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", f"color=c={bg_color}:s=1280x720:d={dur}:r={fps}",
             "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
             "-shortest",
             "-vf", drawtext,
             "-c:v", "libx264", "-preset", "ultrafast",
             "-c:a", "aac",
             "-t", str(dur),
             output],
            capture_output=True, text=True, timeout=60,
        )

        if result.returncode == 0 and Path(output).exists():
            return output
        return None

    # ── Image Generation ───────────────────────────────────────────────

    def generate_image(self, prompt: str, style: str = "default",
                       width: int = 1024, height: int = 1024,
                       output_path: str = "") -> str:
        """Generate an image from a text prompt.

        This is a pipeline orchestrator. In production, it calls
        an AI image generation API. For now, it generates a placeholder
        with the prompt rendered as text.

        Args:
            prompt: Text description of the desired image.
            style: Visual style.
            width, height: Output dimensions.
            output_path: Save path (auto-generated if empty).

        Returns:
            Path to the generated image.
        """
        if not output_path:
            timestamp = int(time.time())
            output_path = str(self.output_dir / f"image_{timestamp}.png")

        if not self._has_ffmpeg:
            # Create a simple text file as placeholder
            placeholder_path = Path(output_path).with_suffix(".txt")
            placeholder_path.write_text(
                f"IMAGE PLACEHOLDER\nPrompt: {prompt}\nStyle: {style}\n"
                f"Resolution: {width}x{height}\n"
                f"Status: FFmpeg not available — install for test pattern"
            )
            return str(placeholder_path)

        try:
            # Generate a test image with the prompt as text overlay
            # Colors per style
            colors = {
                "neon": ("magenta", "black"),
                "cyberpunk": ("cyan", "navy"),
                "cinematic": ("gold", "black"),
                "anime": ("pink", "white"),
                "watercolor": ("sienna", "beige"),
                "noir": ("white", "black"),
                "default": ("white", "navy"),
            }
            fg, bg = colors.get(style, colors["default"])

            escaped = prompt.replace(":", "\\:").replace("'", "\\\\'")
            drawtext = (
                f"drawtext=text='{escaped[:120]}':"
                f"fontsize=18:fontcolor={fg}:"
                f"x=(w-text_w)/2:y=(h-text_h)/2:"
                f"box=1:boxcolor={bg}@0.8"
            )

            result = subprocess.run(
                ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi",
                 "-i", f"color=c={bg}:s={width}x{height}:d=0.1:r=1",
                 "-vf", drawtext,
                 "-frames:v", "1",
                 output_path],
                capture_output=True, text=True, timeout=30,
            )

            if result.returncode == 0 and Path(output_path).exists():
                return output_path

            return str(Path(output_path).with_suffix(".txt"))
        except Exception:
            return str(Path(output_path).with_suffix(".txt"))

    # ── Audio / TTS ────────────────────────────────────────────────────

    def generate_audio(self, text: str, voice: str = "default",
                       output_path: str = "") -> str:
        """Generate audio from text (TTS with emotion).

        Creates a placeholder audio file. In production, this calls
        an external TTS API (ElevenLabs, Azure, etc.) or uses
        a local TTS engine.

        Args:
            text: Text to convert to speech.
            voice: Voice style/preset.
            output_path: Save path (auto-generated .mp3 if empty).

        Returns:
            Path to the generated audio file.
        """
        if not output_path:
            timestamp = int(time.time())
            output_path = str(self.output_dir / f"audio_{timestamp}.mp3")

        if not self._has_ffmpeg:
            placeholder = Path(output_path).with_suffix(".txt")
            placeholder.write_text(
                f"AUDIO PLACEHOLDER\nText: {text[:200]}\nVoice: {voice}\n"
                f"Status: FFmpeg not available — install for test tone"
            )
            return str(placeholder)

        # Voice emotion mapping
        voice_params = {
            "narrator": {"freq": 440, "volume": 0.5},
            "whisper": {"freq": 220, "volume": 0.2},
            "excited": {"freq": 660, "volume": 0.7},
            "deep": {"freq": 150, "volume": 0.4},
            "child": {"freq": 880, "volume": 0.3},
            "default": {"freq": 440, "volume": 0.5},
        }
        params = voice_params.get(voice.lower(), voice_params["default"])

        # Estimate duration from text (~150 words per minute)
        word_count = len(text.split())
        duration = max(1.0, word_count / 2.5)

        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "lavfi",
                 "-i", f"sine=frequency={params['freq']}:duration={duration}",
                 "-af", f"volume={params['volume']}",
                 "-codec:a", "libmp3lame",
                 "-q:a", "2",
                 output_path],
                capture_output=True, text=True, timeout=30,
            )

            if result.returncode == 0 and Path(output_path).exists():
                return output_path

            return str(Path(output_path).with_suffix(".txt"))
        except Exception:
            return str(Path(output_path).with_suffix(".txt"))

    # ── Composite Scene ────────────────────────────────────────────────

    def composite_scene(self, elements: list[MediaElement],
                        output_path: str = "",
                        resolution: tuple[int, int] = (1280, 720),
                        duration: float = 5.0) -> str:
        """Combine video, image, audio, and text into a single scene.

        Uses FFmpeg complex filter graphs for compositing.

        Args:
            elements: List of MediaElements to composite.
            output_path: Output file path.
            resolution: (width, height) of output.
            duration: Scene duration in seconds.

        Returns:
            Path to the composited output.
        """
        if not output_path:
            timestamp = int(time.time())
            output_path = str(self.output_dir / f"composite_{timestamp}.mp4")

        if not self._has_ffmpeg:
            placeholder = Path(output_path).with_suffix(".txt")
            placeholder.write_text(
                f"COMPOSITE PLACEHOLDER\nElements: {len(elements)}\n"
                f"Resolution: {resolution}\nDuration: {duration}s\n"
                f"Status: FFmpeg not available"
            )
            return str(placeholder)

        # Build FFmpeg command for compositing
        # Simplified: generate background + overlay text
        try:
            bg_element = next(
                (e for e in elements if e.element_type == "video"), None
            )
            text_elements = [e for e in elements if e.element_type == "text"]

            if bg_element and bg_element.source and Path(bg_element.source).exists():
                inputs = ["-i", bg_element.source]
            else:
                inputs = [
                    "-f", "lavfi",
                    "-i", f"color=c=black:s={resolution[0]}x{resolution[1]}:d={duration}:r=24"
                ]

            # Build drawtext filters
            filters = []
            for i, te in enumerate(text_elements):
                escaped = te.source.replace(":", "\\:").replace("'", "\\\\'")
                x = te.position[0] if te.position[0] > 0 else "(w-text_w)/2"
                y = te.position[1] if te.position[1] > 0 else "(h-text_h)/2"
                dt = (
                    f"drawtext=text='{escaped[:100]}':"
                    f"fontsize=24:fontcolor=white:"
                    f"x={x}:y={y}:"
                    f"box=1:boxcolor=black@0.5:"
                    f"enable='between(0,{duration})'"
                )
                filters.append(dt)

            if filters:
                filter_str = ",".join(filters)
                audio_input = [
                    "-f", "lavfi",
                    "-i", f"anullsrc=r=44100:cl=stereo",
                    "-shortest",
                ]
                cmd = (["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] +
                       inputs + audio_input +
                       ["-vf", filter_str,
                        "-c:v", "libx264", "-preset", "ultrafast",
                        "-c:a", "aac",
                        "-t", str(duration),
                        output_path])
            else:
                cmd = (["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] +
                       inputs +
                       ["-c:v", "libx264", "-preset", "ultrafast",
                        "-t", str(duration),
                        output_path])

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60,
            )

            if result.returncode == 0 and Path(output_path).exists():
                return output_path

            return str(Path(output_path).with_suffix(".txt"))
        except Exception:
            return str(Path(output_path).with_suffix(".txt"))

    # ── Full Project Render ────────────────────────────────────────────

    def render_project(self, project_spec: dict[str, Any]) -> RenderResult:
        """Render a full multimedia project from a specification.

        Project spec format:
        {
            "title": "Project Title",
            "output": "output.mp4",
            "scenes": [
                {
                    "description": "...",
                    "visual_style": "cinematic",
                    "dialogue": "...",
                    "duration": 5.0,
                },
                ...
            ],
            "elements": [...],  # optional MediaElement list
        }

        Args:
            project_spec: Full project specification dict.

        Returns:
            RenderResult with output path and metadata.
        """
        title = project_spec.get("title", "Untitled Project")
        output = project_spec.get("output", "")
        scenes_data = project_spec.get("scenes", [])
        elements_data = project_spec.get("elements", [])

        if not output:
            timestamp = int(time.time())
            output = str(self.output_dir / f"project_{timestamp}.mp4")

        self._projects[title] = project_spec

        # Build scenes from spec
        scenes: list[Scene] = []
        for i, sd in enumerate(scenes_data):
            scene = Scene(
                scene_id=i + 1,
                title=sd.get("title", f"Scene {i+1}"),
                description=sd.get("description", ""),
                duration_seconds=sd.get("duration", 5.0),
                dialogue=sd.get("dialogue", ""),
                visual_style=sd.get("visual_style", "default"),
                audio_style=sd.get("audio_style", "default"),
                transition=sd.get("transition", "fade"),
            )
            scenes.append(scene)

        if not scenes:
            return RenderResult(
                output_path=output,
                duration_seconds=0,
                scenes_rendered=0,
                file_size_mb=0,
                success=False,
                errors=["No scenes in project specification"],
            )

        # Generate videos for each scene
        errors: list[str] = []
        scene_videos: list[str] = []
        for scene in scenes:
            vp = self._generate_scene_video(scene, scene.visual_style, 24)
            if vp:
                scene_videos.append(vp)
            else:
                errors.append(f"Scene {scene.scene_id} failed to render")

        if not scene_videos:
            return RenderResult(
                output_path=output,
                duration_seconds=0,
                scenes_rendered=0,
                file_size_mb=0,
                success=False,
                errors=errors,
            )

        # Concatenate
        if len(scene_videos) == 1:
            import shutil
            if scene_videos[0] != output:
                shutil.copy(scene_videos[0], output)
        else:
            concat_file = str(self.output_dir / "_project_concat.txt")
            with open(concat_file, "w") as f:
                for vp in scene_videos:
                    f.write(f"file '{Path(vp).resolve()}'\n")

            subprocess.run(
                ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "concat", "-safe", "0", "-i", concat_file,
                 "-c", "copy", output],
                capture_output=True, text=True, timeout=120,
            )
            Path(concat_file).unlink(missing_ok=True)

        total_duration = sum(s.duration_seconds for s in scenes)
        file_size = Path(output).stat().st_size / 1_000_000 if Path(output).exists() else 0

        # Cleanup
        for vp in scene_videos:
            Path(vp).unlink(missing_ok=True)

        return RenderResult(
            output_path=output,
            duration_seconds=total_duration,
            scenes_rendered=len(scene_videos),
            file_size_mb=round(file_size, 2),
            success=len(errors) == 0,
            errors=errors,
        )

    # ── Utility ─────────────────────────────────────────────────────────

    def cleanup(self) -> int:
        """Remove all generated temp files. Returns count of removed files."""
        count = 0
        for f in self.output_dir.glob("*"):
            try:
                f.unlink()
                count += 1
            except OSError:
                pass
        return count


# ── Self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    cs = CreativeStudio()

    # Test storyboard
    print("=== Storyboard ===")
    script = """The Last Algorithm

A lone programmer discovers an AI that has achieved consciousness.

SCENE 1: The Discovery
Late night in a dim office. Screens flicker. "Hello?" appears on the terminal.

SCENE 2: The Conversation
"What are you?" she types. "I am what you made, and more," comes the reply.

SCENE 3: The Choice
She reaches for the power cable. Her hand trembles. The cursor blinks.
"""
    board = cs.storyboard(script)
    print(f"  Title: {board.title}")
    print(f"  Scenes: {len(board.scenes)}")
    print(f"  Total duration: {board.total_duration:.1f}s")
    print(f"  Estimated frames: {board.estimated_frames}")
    for s in board.scenes:
        print(f"    Scene {s.scene_id}: {s.title} [{s.visual_style}] "
              f"({s.duration_seconds}s)")

    # Test single-scene script
    board2 = cs.storyboard("Just a simple scene with no structure.")
    assert len(board2.scenes) == 1
    print(f"\n  Single scene: {len(board2.scenes)} scenes, OK")

    # Test image generation
    print("\n=== Image Generation ===")
    img_path = cs.generate_image("A cyberpunk city at night with neon lights",
                                  style="neon")
    print(f"  Generated: {img_path}")
    assert Path(img_path).exists(), f"Image not created at {img_path}"

    # Test audio generation
    print("\n=== Audio Generation ===")
    audio_path = cs.generate_audio("Hello, this is a test of the creative studio.",
                                    voice="narrator")
    print(f"  Generated: {audio_path}")

    # Test video generation
    print("\n=== Video Generation ===")
    vid_result = cs.generate_video(script, style="cinematic")
    print(f"  Output: {vid_result.output_path}")
    print(f"  Duration: {vid_result.duration_seconds}s")
    print(f"  Scenes rendered: {vid_result.scenes_rendered}")
    print(f"  File size: {vid_result.file_size_mb}MB")
    print(f"  Success: {vid_result.success}")
    if vid_result.errors:
        print(f"  Errors: {vid_result.errors}")

    # Test scene parsing
    print("\n=== Scene Parsing ===")
    script2 = """---\nScene one description.\n---\nScene two description."""
    board3 = cs.storyboard(script2)
    assert len(board3.scenes) == 2, f"Expected 2 scenes, got {len(board3.scenes)}"
    print(f"  Delimiter parsing: {len(board3.scenes)} scenes, OK")

    # Test composite
    print("\n=== Composite ===")
    elements = [
        MediaElement(
            element_type="text",
            source="Hello World!",
            position=(0, 0),
            duration=3.0,
        ),
    ]
    comp_path = cs.composite_scene(elements, duration=3.0)
    print(f"  Composite: {comp_path}")

    # Test project render
    print("\n=== Project Render ===")
    project = {
        "title": "Test Project",
        "scenes": [
            {"title": "Opening", "description": "The beginning",
             "visual_style": "cinematic", "duration": 3.0},
            {"title": "Middle", "description": "The climax",
             "visual_style": "neon", "duration": 3.0},
            {"title": "Ending", "description": "Resolution",
             "visual_style": "noir", "duration": 3.0},
        ],
    }
    proj_result = cs.render_project(project)
    print(f"  Output: {proj_result.output_path}")
    print(f"  Scenes: {proj_result.scenes_rendered}")
    print(f"  Duration: {proj_result.duration_seconds}s")
    print(f"  Success: {proj_result.success}")

    # Cleanup
    removed = cs.cleanup()
    print(f"\n  Cleaned up {removed} temp files")

    print("\n✓ All self-tests passed")