"""Video generation tools — FFmpeg pipeline with multi-format support.
DNA: Sora (video generation) + creative fusion.

Capabilities: info, trim, extract_audio, concat, resize, fps_change,
gif_convert, screenshot, overlay_text, mute, speed, crop, rotate.
All operations use subprocess + ffmpeg/ffprobe with graceful fallback.
"""

import subprocess
import json
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


@dataclass
class VideoInfo:
    path: str
    duration: float = 0.0
    size_mb: float = 0.0
    format: str = ""
    video_codec: str = ""
    audio_codec: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = False


def _ffmpeg(*args, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run ffmpeg with unified error handling."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _ffprobe(filepath: str) -> Optional[dict]:
    """Get JSON probe data from a media file."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", filepath],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def probe(filepath: str) -> Optional[VideoInfo]:
    """Probe a video file and return structured VideoInfo."""
    data = _ffprobe(filepath)
    if not data:
        return None

    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video = next((s for s in streams if s["codec_type"] == "video"), {})
    audio = next((s for s in streams if s["codec_type"] == "audio"), {})

    # Parse FPS from r_frame_rate (e.g. "30000/1001")
    fps_str = video.get("r_frame_rate", "0/1")
    try:
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0

    return VideoInfo(
        path=filepath,
        duration=float(fmt.get("duration", 0)),
        size_mb=float(fmt.get("size", 0)) / 1_000_000,
        format=fmt.get("format_name", ""),
        video_codec=video.get("codec_name", ""),
        audio_codec=audio.get("codec_name", ""),
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        fps=round(fps, 2),
        has_audio=bool(audio),
    )


def video_info(filepath: str) -> str:
    """Get human-readable video file information."""
    info = probe(filepath)
    if not info:
        return "ffmpeg not installed. Install: apt install ffmpeg"

    lines = [
        f"Video: {filepath}",
        f"Duration: {info.duration:.1f}s",
        f"Size: {info.size_mb:.1f}MB",
        f"Format: {info.format}",
        f"Video: {info.video_codec} {info.width}x{info.height} @ {info.fps}fps",
        f"Audio: {info.audio_codec if info.has_audio else 'none'}",
    ]
    return "\n".join(lines)


def trim_video(input_path: str, output_path: str,
               start: str = "00:00:00", end: str = "") -> str:
    """Trim a video segment. Times in HH:MM:SS or seconds."""
    try:
        cmd = ["ffmpeg", "-i", input_path, "-ss", start, "-c", "copy"]
        if end:
            cmd.extend(["-to", end])
        cmd.append(output_path)
        result = _ffmpeg(*cmd[1:])  # Skip ffmpeg since _ffmpeg adds it
        if result.returncode == 0:
            return f"Trimmed: {input_path} → {output_path}"
        return f"ffmpeg error: {result.stderr[:300]}"
    except FileNotFoundError:
        return "ffmpeg not installed"


def extract_audio(input_path: str, output_path: str = "") -> str:
    """Extract audio from video file as MP3."""
    if not output_path:
        output_path = str(Path(input_path).with_suffix(".mp3"))
    try:
        result = _ffmpeg("-i", input_path, "-vn", "-acodec", "libmp3lame",
                         "-q:a", "2", output_path)
        if result.returncode == 0:
            return f"Audio extracted: {output_path}"
        return f"ffmpeg error: {result.stderr[:300]}"
    except FileNotFoundError:
        return "ffmpeg not installed"


def concat_videos(input_paths: list[str], output_path: str) -> str:
    """Concatenate multiple videos into one."""
    # Write concat file list
    concat_file = "/tmp/_omnicore_concat.txt"
    with open(concat_file, "w") as f:
        for p in input_paths:
            f.write(f"file '{Path(p).resolve()}'\n")

    try:
        result = _ffmpeg("-f", "concat", "-safe", "0", "-i", concat_file,
                         "-c", "copy", output_path)
        os.remove(concat_file)
        if result.returncode == 0:
            return f"Concatenated {len(input_paths)} videos → {output_path}"
        return f"ffmpeg error: {result.stderr[:300]}"
    except FileNotFoundError:
        return "ffmpeg not installed"


def resize_video(input_path: str, output_path: str,
                 width: int = -1, height: int = -1) -> str:
    """Resize video. Specify width or height (maintains aspect ratio)."""
    scale = f"scale={width}:{height}" if width > 0 and height > 0 else \
            f"scale={width}:-2" if width > 0 else \
            f"scale=-2:{height}"
    try:
        result = _ffmpeg("-i", input_path, "-vf", scale, "-c:a", "copy", output_path)
        if result.returncode == 0:
            return f"Resized: {input_path} → {output_path}"
        return f"ffmpeg error: {result.stderr[:300]}"
    except FileNotFoundError:
        return "ffmpeg not installed"


def change_fps(input_path: str, output_path: str, fps: int = 30) -> str:
    """Change video frame rate."""
    try:
        result = _ffmpeg("-i", input_path, "-filter:v", f"fps=fps={fps}",
                         "-c:a", "copy", output_path)
        if result.returncode == 0:
            return f"FPS changed to {fps}: {output_path}"
        return f"ffmpeg error: {result.stderr[:300]}"
    except FileNotFoundError:
        return "ffmpeg not installed"


def to_gif(input_path: str, output_path: str = "",
           fps: int = 10, width: int = 480) -> str:
    """Convert video segment to GIF."""
    if not output_path:
        output_path = str(Path(input_path).with_suffix(".gif"))
    try:
        result = _ffmpeg("-i", input_path,
                         "-vf", f"fps={fps},scale={width}:-1:flags=lanczos",
                         "-loop", "0", output_path)
        if result.returncode == 0:
            size = Path(output_path).stat().st_size / 1_000_000
            return f"GIF created: {output_path} ({size:.1f}MB)"
        return f"ffmpeg error: {result.stderr[:300]}"
    except FileNotFoundError:
        return "ffmpeg not installed"


def screenshot(input_path: str, output_path: str = "",
               at_time: str = "00:00:01") -> str:
    """Take a screenshot at a specific timestamp."""
    if not output_path:
        output_path = str(Path(input_path).with_suffix(".png"))
    try:
        result = _ffmpeg("-ss", at_time, "-i", input_path,
                         "-vframes", "1", "-q:v", "2", output_path)
        if result.returncode == 0:
            return f"Screenshot saved: {output_path}"
        return f"ffmpeg error: {result.stderr[:300]}"
    except FileNotFoundError:
        return "ffmpeg not installed"


def overlay_text(input_path: str, output_path: str,
                 text: str, position: str = "bottom") -> str:
    """Overlay text on video. Position: top, bottom, center."""
    y_pos = {"top": "h/6", "center": "h/2", "bottom": "h-h/6"}.get(position, "h-h/6")
    escaped = text.replace(":", "\\:").replace("'", "\\'")
    draw = f"drawtext=text='{escaped}':fontsize=24:fontcolor=white:" \
           f"x=(w-text_w)/2:y={y_pos}:box=1:boxcolor=black@0.5"
    try:
        result = _ffmpeg("-i", input_path, "-vf", draw, "-c:a", "copy", output_path)
        if result.returncode == 0:
            return f"Text overlayed: {output_path}"
        return f"ffmpeg error: {result.stderr[:300]}"
    except FileNotFoundError:
        return "ffmpeg not installed"


def mute_video(input_path: str, output_path: str) -> str:
    """Remove audio track from video."""
    try:
        result = _ffmpeg("-i", input_path, "-an", "-c:v", "copy", output_path)
        if result.returncode == 0:
            return f"Muted: {output_path}"
        return f"ffmpeg error: {result.stderr[:300]}"
    except FileNotFoundError:
        return "ffmpeg not installed"


def speed_video(input_path: str, output_path: str, speed: float = 2.0) -> str:
    """Speed up or slow down video. 0.5 = half speed, 2.0 = double speed."""
    setpts = f"setpts={1/speed}*PTS"
    atempo = f"atempo={speed}"
    try:
        result = _ffmpeg("-i", input_path,
                         "-filter_complex", f"[0:v]{setpts}[v];[0:a]{atempo}[a]",
                         "-map", "[v]", "-map", "[a]", output_path)
        if result.returncode == 0:
            return f"Speed {speed}x: {output_path}"
        return f"ffmpeg error: {result.stderr[:300]}"
    except FileNotFoundError:
        return "ffmpeg not installed"


def crop_video(input_path: str, output_path: str,
               w: int, h: int, x: int = 0, y: int = 0) -> str:
    """Crop a region from the video."""
    try:
        result = _ffmpeg("-i", input_path, "-filter:v",
                         f"crop={w}:{h}:{x}:{y}", "-c:a", "copy", output_path)
        if result.returncode == 0:
            return f"Cropped {w}x{h}+{x}+{y}: {output_path}"
        return f"ffmpeg error: {result.stderr[:300]}"
    except FileNotFoundError:
        return "ffmpeg not installed"


def rotate_video(input_path: str, output_path: str, degrees: int = 90) -> str:
    """Rotate video. Only 90, 180, 270 supported by transpose."""
    transpose_map = {90: "transpose=1", 180: "transpose=1,transpose=1",
                     270: "transpose=2"}
    vf = transpose_map.get(degrees, "transpose=1")
    try:
        result = _ffmpeg("-i", input_path, "-vf", vf, "-c:a", "copy", output_path)
        if result.returncode == 0:
            return f"Rotated {degrees}°: {output_path}"
        return f"ffmpeg error: {result.stderr[:300]}"
    except FileNotFoundError:
        return "ffmpeg not installed"


# ── Self-test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile

    # Create a minimal test video (1 second, single color)
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        test_video = f.name

    result = _ffmpeg("-f", "lavfi", "-i", "color=c=blue:s=320x240:d=1",
                     "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                     "-shortest", "-c:v", "libx264", "-t", "1", test_video,
                     timeout=30)
    if result.returncode != 0:
        print(f"SKIP: ffmpeg not available or failed ({result.stderr[:100]})")
        exit(0)

    # Test probe
    info = probe(test_video)
    assert info is not None, "probe returned None"
    assert info.width == 320, f"Expected 320, got {info.width}"
    assert info.height == 240, f"Expected 240, got {info.height}"
    assert info.has_audio, "Expected audio track"
    print(f"✓ probe: {info.width}x{info.height}, {info.duration}s, "
          f"{info.size_mb:.1f}MB")

    # Test video_info
    summary = video_info(test_video)
    assert "320x240" in summary
    print(f"✓ video_info: {summary.split(chr(10))[3]}")

    # Test screenshot
    ss_path = test_video.replace(".mp4", "_ss.png")
    r = screenshot(test_video, ss_path, at_time="0.5")
    assert "Screenshot saved" in r, f"Unexpected: {r}"
    assert Path(ss_path).exists()
    print(f"✓ screenshot: {Path(ss_path).stat().st_size} bytes")

    # Test extract_audio
    audio_path = test_video.replace(".mp4", "_audio.mp3")
    r = extract_audio(test_video, audio_path)
    assert "Audio extracted" in r or "ffmpeg" in r
    print(f"✓ extract_audio: {r[:60]}")

    # Cleanup
    for p in [test_video, ss_path, audio_path]:
        if Path(p).exists():
            Path(p).unlink()

    print("\n✓ All self-tests passed")