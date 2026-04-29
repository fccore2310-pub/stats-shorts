"""
Hybrid Splitter — uses ffmpeg for PRECISE timestamps, Claude Vision for VALIDATION.

Strategy:
1. ffmpeg blackdetect finds exact timestamps of black frames (millisecond precision)
2. Claude Vision verifies which black frames are true clip separators
3. We cut at the END of each verified separator, so each segment includes:
   - Full clip content
   - Trailing black screen with "football core." text
   - Trailing separator sound
4. Result: perfect cuts, sound preserved, no false transitions
"""
from __future__ import annotations

import base64
import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path

import anthropic

from src.utils.config import load_config

logger = logging.getLogger(__name__)

VALIDATION_PROMPT = """I'm analyzing a TikTok football compilation. I found these moments where the video goes black. For each, tell me if it's a real CLIP SEPARATOR (intentional black screen between clips) or a FALSE POSITIVE (dark frame within a clip, brief fade, etc.).

I'll show you 2 frames per candidate: BEFORE the black moment and AFTER. A TRUE separator has completely different scenes before/after (different players, location, angle). A false positive has the same scene continuing.

Return ONLY this JSON. For each candidate index (0, 1, 2...), mark if it's a true separator:

{{"separators": {{"0": true, "1": false, "2": true}}}}"""


class HybridSplitter:
    """Precise splitting using ffmpeg black detection + Claude validation."""

    def __init__(
        self,
        min_clip_duration: float = 2.5,
        max_clip_duration: float = 15.0,
        black_min_duration: float = 0.2,
        black_threshold: float = 0.10,
    ):
        config = load_config()
        claude_cfg = config["claude"]
        self._client = anthropic.Anthropic(api_key=claude_cfg["api_key"])
        self._model = claude_cfg.get("model", "claude-haiku-4-5-20251001")
        self.min_clip_duration = min_clip_duration
        self.max_clip_duration = max_clip_duration
        self.black_min_duration = black_min_duration
        self.black_threshold = black_threshold

    def split(self, video_path: Path, output_dir: Path) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        total_duration = self._get_duration(video_path)
        if total_duration < self.min_clip_duration:
            return []

        # Step 1: Find ALL black moments with ffmpeg (precise)
        blacks = self._detect_black_moments(video_path)
        logger.info(f"Found {len(blacks)} black moments in {video_path.name}")

        if not blacks:
            # Video has no black separators — try time-based split
            logger.info(f"No black moments, splitting uniformly")
            return self._split_uniform(video_path, output_dir, total_duration)

        # Step 2: Ask Claude to validate which blacks are real separators
        verified = self._validate_separators(video_path, blacks)
        logger.info(f"Claude verified {len(verified)}/{len(blacks)} as real separators")

        if not verified:
            # Claude rejected all — fall back to using them all anyway
            verified = blacks

        # Step 3: Cut at the END of each verified separator
        # Each segment: [previous_end, this_black_end]
        # First segment: [0, first_black_end]
        segments = self._build_segments(verified, total_duration)

        # Step 4: Extract clips
        clips: list[Path] = []
        for i, (start, end) in enumerate(segments):
            clip_path = output_dir / f"clip_{i:03d}.mp4"
            if self._extract(video_path, clip_path, start, end):
                clips.append(clip_path)

        logger.info(f"Split {video_path.name}: {len(clips)} clips")
        return clips

    # ── Step 1: Precise black detection ─────────────────────────────

    def _detect_black_moments(self, video_path: Path) -> list[tuple[float, float]]:
        """Returns (black_start, black_end) tuples with millisecond precision."""
        cmd = [
            "ffmpeg", "-v", "info",
            "-i", str(video_path),
            "-vf", f"blackdetect=d={self.black_min_duration}:pix_th={self.black_threshold}",
            "-an", "-f", "null", "-",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)

        blacks: list[tuple[float, float]] = []
        pattern = re.compile(
            r"black_start:(\d+\.?\d*)\s+black_end:(\d+\.?\d*)"
        )
        for m in pattern.finditer(result.stderr):
            start = float(m.group(1))
            end = float(m.group(2))
            blacks.append((start, end))

        return blacks

    # ── Step 2: Claude validates separators ─────────────────────────

    def _validate_separators(
        self, video_path: Path, blacks: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        """For each black moment, extract before/after frames and ask Claude."""
        tmp_dir = Path(tempfile.mkdtemp(prefix="validate_"))

        # Extract before/after frames
        content: list[dict] = []
        for i, (black_start, black_end) in enumerate(blacks):
            # Frame 0.2s BEFORE the black starts
            before_time = max(0, black_start - 0.3)
            # Frame 0.2s AFTER the black ends
            after_time = black_end + 0.3

            before_path = tmp_dir / f"{i:03d}_before.jpg"
            after_path = tmp_dir / f"{i:03d}_after.jpg"

            self._extract_frame(video_path, before_time, before_path)
            self._extract_frame(video_path, after_time, after_path)

            if not before_path.exists() or not after_path.exists():
                continue

            before_b64 = base64.standard_b64encode(before_path.read_bytes()).decode()
            after_b64 = base64.standard_b64encode(after_path.read_bytes()).decode()

            content.append({"type": "text", "text": f"Candidate #{i} (black at {black_start:.1f}s-{black_end:.1f}s)"})
            content.append({"type": "text", "text": "BEFORE:"})
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": before_b64},
            })
            content.append({"type": "text", "text": "AFTER:"})
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": after_b64},
            })

        content.append({"type": "text", "text": VALIDATION_PROMPT})

        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=500,
                messages=[{"role": "user", "content": content}],
            )
            raw = resp.content[0].text.strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                sep_flags = data.get("separators", {})
                verified = []
                for i, (bs, be) in enumerate(blacks):
                    if sep_flags.get(str(i), False):
                        verified.append((bs, be))
                return verified
        except Exception as e:
            logger.warning(f"Claude validation failed: {e}")

        return blacks  # Fallback: trust all

    # ── Step 3: Build segments ──────────────────────────────────────

    def _build_segments(
        self, separators: list[tuple[float, float]], total_duration: float
    ) -> list[tuple[float, float]]:
        """Each segment ends at the END of a separator (black_end).
        Segment boundaries: [0, black_1_end], [black_1_end, black_2_end], ..."""
        segments: list[tuple[float, float]] = []
        prev_end = 0.0

        for black_start, black_end in separators:
            # Segment from prev_end to current black_end
            # This way each segment includes its trailing separator
            duration = black_end - prev_end
            if self.min_clip_duration <= duration <= self.max_clip_duration:
                segments.append((prev_end, black_end))
            elif duration > self.max_clip_duration:
                # Clip too long — cut at max duration (losing trailing separator)
                segments.append((prev_end, prev_end + self.max_clip_duration))
            # If too short, just skip and continue
            prev_end = black_end

        # Last segment from last black_end to end of video (no trailing separator)
        # We still include it but only if it's long enough to be useful
        final_duration = total_duration - prev_end
        if self.min_clip_duration <= final_duration <= self.max_clip_duration:
            segments.append((prev_end, total_duration))

        return segments

    # ── Step 4: Extract with normalization ──────────────────────────

    def _extract(self, video_path: Path, out_path: Path, start: float, end: float) -> bool:
        duration = end - start
        cmd = [
            "ffmpeg", "-y", "-v", "warning",
            "-ss", str(start),
            "-i", str(video_path),
            "-t", str(duration),
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,"
                   "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,"
                   "fps=30,format=yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-force_key_frames", "expr:gte(t,n_forced*1)",
            "-g", "30",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart",
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if result.returncode != 0:
            logger.warning(f"Extract failed: {result.stderr[:200]}")
        return result.returncode == 0 and out_path.exists()

    # ── Helpers ─────────────────────────────────────────────────────

    def _extract_frame(self, video_path: Path, timestamp: float, out_path: Path):
        cmd = [
            "ffmpeg", "-y", "-v", "quiet",
            "-ss", str(timestamp),
            "-i", str(video_path),
            "-vframes", "1",
            "-vf", "scale=-1:360",
            "-q:v", "5",
            str(out_path),
        ]
        subprocess.run(cmd, timeout=15)

    def _split_uniform(
        self, video_path: Path, output_dir: Path, total_duration: float
    ) -> list[Path]:
        """Fallback: split uniformly into ~6s segments when no black detected."""
        segment_duration = 6.0
        segments = []
        t = 0.0
        while t + self.min_clip_duration < total_duration:
            end = min(t + segment_duration, total_duration)
            segments.append((t, end))
            t = end

        clips = []
        for i, (s, e) in enumerate(segments):
            clip_path = output_dir / f"clip_{i:03d}.mp4"
            if self._extract(video_path, clip_path, s, e):
                clips.append(clip_path)
        return clips

    def _get_duration(self, video_path: Path) -> float:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return float(result.stdout.strip())
        except ValueError:
            return 0.0
