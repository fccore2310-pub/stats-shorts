"""
Build an accents compilation post: select N clips, concatenate, write manifest.
"""
from __future__ import annotations

import json
import logging
import random
import secrets
import subprocess
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


BLACK_BETWEEN = 0.3  # seconds of pure black between clips (niche signature)


def _make_black_clip(duration: float, out_path: Path) -> bool:
    """Make a silent black 1080x1920@30fps clip of the given duration."""
    cmd = [
        "ffmpeg", "-y", "-v", "quiet",
        "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:r=30:d={duration}",
        "-f", "lavfi", "-i", f"anullsrc=cl=stereo:r=44100",
        "-t", f"{duration}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0 and out_path.exists()


def _concat_clips(clips: list[Path], out_path: Path) -> bool:
    """Concatenate clips with a 0.3s black separator between each (niche look)."""
    tmp_black = out_path.parent / "_black.mp4"
    if not tmp_black.exists():
        if not _make_black_clip(BLACK_BETWEEN, tmp_black):
            return False

    # Interleave: [clip1, black, clip2, black, ..., clipN]
    interleaved: list[Path] = []
    for i, c in enumerate(clips):
        interleaved.append(c)
        if i < len(clips) - 1:
            interleaved.append(tmp_black)

    list_file = out_path.with_suffix(".txt")
    list_file.write_text("\n".join(f"file '{c.resolve()}'" for c in interleaved))
    cmd = [
        "ffmpeg", "-y", "-v", "quiet",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(out_path),
    ]
    r = subprocess.run(cmd)
    list_file.unlink(missing_ok=True)
    if r.returncode != 0 or not out_path.exists():
        # Fallback: re-encode (handles minor incompatibilities in fps/sar/audio)
        inputs = []
        for c in interleaved:
            inputs += ["-i", str(c)]
        n = len(interleaved)
        filter_complex = "".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
        cmd2 = [
            "ffmpeg", "-y", "-v", "quiet",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(out_path),
        ]
        r2 = subprocess.run(cmd2)
        ok = r2.returncode == 0 and out_path.exists()
    else:
        ok = True
    tmp_black.unlink(missing_ok=True)
    return ok


def _probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def generate_post(
    segments_dir: Path,
    outputs_dir: Path,
    clips_per_post: int = 5,
    target_total: float = 55.0,
    exclude_used: set[str] | None = None,
) -> dict:
    exclude_used = exclude_used or set()
    all_clips = [c for c in sorted(segments_dir.glob("*.mp4")) if c.name not in exclude_used]
    if len(all_clips) < clips_per_post:
        raise ValueError(
            f"Not enough clips: {len(all_clips)} < {clips_per_post}. "
            f"Ingest more sources first."
        )

    # Group clips by source_id so we can pick at most 1 per source (no repeats
    # of the same kid/scene in a single compilation).
    def _source_of(clip: Path) -> str:
        # filenames: "{source_id}_c{NN}.mp4"
        return clip.stem.rsplit("_c", 1)[0]

    by_source: dict[str, list[Path]] = {}
    for c in all_clips:
        by_source.setdefault(_source_of(c), []).append(c)

    source_ids = list(by_source.keys())
    random.shuffle(source_ids)

    # Prefer 1 clip per source first. If we run out of sources and still need
    # more clips to hit target duration, take a 2nd pick from random sources.
    picked: list[Path] = []
    total = 0.0
    used_sources: set[str] = set()

    for sid in source_ids:
        if len(picked) >= clips_per_post:
            break
        choice = random.choice(by_source[sid])
        d = _probe_duration(choice)
        if total + d > target_total + 5:
            continue
        picked.append(choice)
        used_sources.add(sid)
        total += d

    # Second pass if under target (allow 2nd clip per source but different file)
    if total < target_total * 0.85:
        random.shuffle(source_ids)
        for sid in source_ids:
            if len(picked) >= clips_per_post:
                break
            remaining = [c for c in by_source[sid] if c not in picked]
            if not remaining:
                continue
            choice = random.choice(remaining)
            d = _probe_duration(choice)
            if total + d > target_total + 5:
                continue
            picked.append(choice)
            total += d

    if len(picked) < 3:
        raise RuntimeError(f"Could not pick enough clips (got {len(picked)})")

    post_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(3)
    post_dir = outputs_dir / post_id
    post_dir.mkdir(parents=True, exist_ok=True)
    out_video = post_dir / "video.mp4"

    if not _concat_clips(picked, out_video):
        raise RuntimeError("Concat failed")

    manifest = {
        "post_id": post_id,
        "created_at": datetime.now().isoformat(),
        "niche": "accents",
        "clips": [str(c.relative_to(segments_dir.parent.parent.parent)) for c in picked],
        "clip_names": [c.name for c in picked],
        "duration": _probe_duration(out_video),
        "video_path": str(out_video.relative_to(outputs_dir.parent.parent.parent)),
    }
    (post_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    logger.info(f"Generated post {post_id}: {len(picked)} clips, {manifest['duration']:.1f}s")
    return manifest
