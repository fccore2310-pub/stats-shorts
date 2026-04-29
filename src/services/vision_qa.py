"""
Vision QA — Claude reviews generated compilation videos and reports issues.

Extracts frames from the output video and checks for:
- Frozen frames (same image persisting too long)
- Black/empty frames in the middle of the video
- Abrupt bad cuts
- Any visible issue (text overlap, corruption, etc.)
"""
from __future__ import annotations

import base64
import json
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from src.utils.config import load_config

logger = logging.getLogger(__name__)

QA_PROMPT = """You are reviewing a "football core" TikTok compilation. Frames sampled every {interval}s.

CRITICAL CONTEXT — this is the "football core" aesthetic:
- Black frames with text like "football core." / "fc.core." appear BETWEEN clips. This is the INTENTIONAL SIGNATURE style of the niche. DO NOT flag them as issues no matter how many appear.
- Clips are often football shots that look visually similar (same stadium, grass field, players). Two consecutive similar-looking frames is NORMAL — only flag FROZEN if the SAME EXACT shot is literally frozen/static.
- Slow-motion or slow camera pans are common — they are NOT frozen frames.
- Variety of indoor/outdoor footage is a FEATURE, not a bug.

Only flag REAL issues:

1. FROZEN: the SAME EXACT image (pixel-identical, no motion at all) persists for 4+ seconds. A similar-looking-but-different shot is NOT frozen.
2. CORRUPT: visual artifacts, glitches, garbled pixels, codec damage.
3. DUPLICATE: the exact same clip appears twice in the compilation.

DO NOT flag:
- Black separator frames with "football core." text (those are intentional)
- Different shots that happen to show similar scenes (different stadiums, different games)
- Natural slow camera work
- Transitions between indoor and outdoor football footage

Return ONLY this JSON, no other text:
{{
  "overall_quality": "good" | "okay" | "bad",
  "issues": [
    {{"type": "FROZEN", "timestamp": 15.0, "description": "..."}}
  ],
  "summary": "One sentence overview"
}}

If there are no REAL issues (only intentional style elements), return overall_quality: "good" with empty issues array.

Video duration: {duration:.0f}s. Be specific with timestamps."""


@dataclass
class QAIssue:
    type: str
    timestamp: float
    description: str


@dataclass
class QAReport:
    overall_quality: str = "unknown"
    issues: list[QAIssue] = field(default_factory=list)
    summary: str = ""
    raw_response: str = ""

    @property
    def passed(self) -> bool:
        return self.overall_quality in ("good", "okay") and not any(
            i.type in ("FROZEN", "CORRUPT") for i in self.issues
        )


class VisionQA:
    """Review compilation videos with Claude Vision."""

    def __init__(self, frame_interval: float = 2.0):
        config = load_config()
        claude_cfg = config["claude"]
        self._client = anthropic.Anthropic(api_key=claude_cfg["api_key"])
        self._model = claude_cfg.get("model", "claude-haiku-4-5-20251001")
        self.frame_interval = frame_interval

    def review(self, video_path: Path) -> QAReport:
        duration = self._get_duration(video_path)
        if duration < 5:
            return QAReport(overall_quality="bad", summary="Video too short")

        frames = self._extract_frames(video_path, self.frame_interval)
        if len(frames) < 3:
            return QAReport(overall_quality="bad", summary="Could not extract frames")

        report = self._ask_claude(frames, duration)
        logger.info(
            f"QA: {report.overall_quality} — {len(report.issues)} issues — {report.summary}"
        )
        return report

    def _ask_claude(self, frames: list[tuple[float, Path]], duration: float) -> QAReport:
        content: list[dict] = []
        for timestamp, frame_path in frames:
            img_data = base64.standard_b64encode(frame_path.read_bytes()).decode("utf-8")
            content.append({"type": "text", "text": f"t={timestamp:.1f}s:"})
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": img_data,
                },
            })

        content.append({
            "type": "text",
            "text": QA_PROMPT.format(interval=self.frame_interval, duration=duration),
        })

        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=800,
                messages=[{"role": "user", "content": content}],
            )
            raw = resp.content[0].text.strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                issues = []
                for i in data.get("issues", []):
                    ts_raw = str(i.get("timestamp", 0))
                    # Handle range format like "16.0-24.0" — take the start
                    if "-" in ts_raw:
                        ts_raw = ts_raw.split("-")[0]
                    try:
                        ts = float(ts_raw)
                    except ValueError:
                        ts = 0.0
                    issues.append(QAIssue(
                        type=i.get("type", "UNKNOWN"),
                        timestamp=ts,
                        description=i.get("description", ""),
                    ))
                return QAReport(
                    overall_quality=data.get("overall_quality", "unknown"),
                    issues=issues,
                    summary=data.get("summary", ""),
                    raw_response=raw,
                )
        except Exception as e:
            logger.warning(f"Claude QA failed: {e}")
            return QAReport(raw_response=str(e))

        return QAReport(raw_response="Could not parse response")

    def _extract_frames(self, video_path: Path, interval: float) -> list[tuple[float, Path]]:
        tmp_dir = Path(tempfile.mkdtemp(prefix="qa_"))
        cmd = [
            "ffmpeg", "-y", "-v", "quiet",
            "-i", str(video_path),
            "-vf", f"fps=1/{interval},scale=-1:360",
            "-q:v", "5",
            str(tmp_dir / "f_%03d.jpg"),
        ]
        subprocess.run(cmd, timeout=60)

        frames = []
        for f in sorted(tmp_dir.glob("f_*.jpg")):
            idx = int(f.stem.split("_")[1]) - 1
            timestamp = idx * interval
            frames.append((timestamp, f))

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
