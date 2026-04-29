"""
Validator — Claude Vision dictates if a video is a valid football core candidate.

For each candidate:
1. Download a low-res preview
2. Extract ~8 frames spread across the video
3. Ask Claude to judge:
   - Is it football core format? (short clips separated by black screens)
   - Is the content actually football? (not other sports/unrelated)
   - Is there extra garbage? (reaction face overlay, heavy branding, etc.)
4. Returns accept/reject + reason

Cost: ~$0.01 per video validated with Haiku.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import anthropic

from src.utils.config import load_config

logger = logging.getLogger(__name__)


VALIDATION_PROMPT = """You are validating TikTok videos as candidates for a "football core" library.

I'll show you {n_frames} frames from a {duration:.0f}s video.

A VALID football core video must have ALL of these:
1. The content is FOOTBALL/SOCCER (not basketball, rugby, tennis, other sports)
2. It's a COMPILATION of multiple short clips (not a single long scene)
3. Has BLACK SEPARATOR SCREENS between clips (typically with "football core." text)
4. Clips show actual football action (goals, skills, fails, celebrations, tricks)

REJECT videos that:
- Are NOT football (other sports, unrelated content)
- Are a single continuous clip (not a compilation)
- Have NO black separators between clips
- Have large reaction face overlays covering the content
- Are tutorials, talking heads, or text-only content
- Are edited with heavy phonk/velocity edits instead of the clean "football core" format

Return ONLY this JSON:
{{
  "valid": true | false,
  "reason": "short explanation (max 15 words)",
  "confidence": "high" | "medium" | "low"
}}"""


@dataclass
class ValidationResult:
    valid: bool
    reason: str
    confidence: str
    raw_response: str = ""


class Validator:
    """Claude Vision judges if a video is a valid football core candidate."""

    def __init__(self):
        config = load_config()
        claude_cfg = config["claude"]
        self._client = anthropic.Anthropic(api_key=claude_cfg["api_key"])
        self._model = claude_cfg.get("model", "claude-haiku-4-5-20251001")

    def validate(self, video_path: Path, n_frames: int = 8) -> ValidationResult:
        """Download preview, extract frames, ask Claude."""
        duration = self._get_duration(video_path)
        if duration < 10:
            return ValidationResult(False, "Video too short", "high")
        if duration > 180:
            return ValidationResult(False, "Video too long", "high")

        frames = self._extract_frames(video_path, n_frames)
        if len(frames) < 4:
            return ValidationResult(False, "Could not extract frames", "low")

        return self._ask_claude(frames, duration)

    def _ask_claude(
        self, frames: list[tuple[float, Path]], duration: float
    ) -> ValidationResult:
        content: list[dict] = []
        for timestamp, frame_path in frames:
            img_data = base64.standard_b64encode(frame_path.read_bytes()).decode()
            content.append({"type": "text", "text": f"t={timestamp:.1f}s:"})
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": img_data},
            })
        content.append({
            "type": "text",
            "text": VALIDATION_PROMPT.format(n_frames=len(frames), duration=duration),
        })

        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=300,
                messages=[{"role": "user", "content": content}],
            )
            raw = resp.content[0].text.strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                return ValidationResult(
                    valid=bool(data.get("valid", False)),
                    reason=data.get("reason", ""),
                    confidence=data.get("confidence", "low"),
                    raw_response=raw,
                )
        except Exception as e:
            logger.warning(f"Validator failed: {e}")
            return ValidationResult(False, f"Claude error: {e}", "low")

        return ValidationResult(False, "Could not parse response", "low", raw)

    def _extract_frames(self, video_path: Path, n: int) -> list[tuple[float, Path]]:
        duration = self._get_duration(video_path)
        if duration <= 0:
            return []

        tmp_dir = Path(tempfile.mkdtemp(prefix="val_"))
        # Spread frames evenly through the video (avoid first/last 10%)
        interval = (duration * 0.8) / n
        start_offset = duration * 0.1

        frames: list[tuple[float, Path]] = []
        for i in range(n):
            t = start_offset + i * interval
            out_path = tmp_dir / f"f_{i:02d}.jpg"
            cmd = [
                "ffmpeg", "-y", "-v", "quiet",
                "-ss", str(t),
                "-i", str(video_path),
                "-vframes", "1",
                "-vf", "scale=-1:360",
                "-q:v", "5",
                str(out_path),
            ]
            subprocess.run(cmd, timeout=15)
            if out_path.exists() and out_path.stat().st_size > 1000:
                frames.append((t, out_path))

        return frames

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
