from __future__ import annotations

import json
import subprocess
from pathlib import Path


def get_video_metadata(path: Path) -> dict:
    """Get video metadata using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr}")
    return json.loads(result.stdout)


def get_video_info(path: Path) -> dict:
    """Extract key video info: duration, width, height, fps."""
    meta = get_video_metadata(path)

    video_stream = None
    for stream in meta.get("streams", []):
        if stream.get("codec_type") == "video":
            video_stream = stream
            break

    if not video_stream:
        raise ValueError(f"No video stream found in {path}")

    # Parse fps from r_frame_rate (e.g. "30/1")
    fps_str = video_stream.get("r_frame_rate", "30/1")
    if "/" in fps_str:
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 30.0
    else:
        fps = float(fps_str)

    duration = float(meta.get("format", {}).get("duration", 0))
    if duration == 0:
        duration = float(video_stream.get("duration", 0))

    return {
        "duration": duration,
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "fps": fps,
        "file_size": int(meta.get("format", {}).get("size", 0)),
        "codec": video_stream.get("codec_name", "unknown"),
    }
