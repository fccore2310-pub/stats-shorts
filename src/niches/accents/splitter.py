"""
Splitter for @funny.jokes.23 (accents niche).

Reuses the HybridSplitter pattern from football core (ffmpeg blackdetect +
Claude Vision validation), but with an accent-specific validation prompt so
Claude understands what a real accent-boundary separator looks like here.

Real separator: pure black frame (maybe with a faint country flag/name fading
in or out) that divides one kid's accent imitation from the next.

False positive: a dark scene within the same accent (e.g., shadow on the face).
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


ACCENTS_VALIDATION_PROMPT = """I'm analyzing a TikTok where African kids imitate English accents from different countries. Between each accent there's an INTENTIONAL BLACK TRANSITION (often with the next country's name/flag fading in — e.g. "Sweden 🇸🇪", "Italy 🇮🇹").

For each candidate, I'll show you BEFORE and AFTER the black moment. Mark it as a true ACCENT SEPARATOR if:
- BEFORE shows kid(s) speaking with a country overlay (e.g. "Sweden")
- AFTER shows kid(s) with a DIFFERENT country overlay (e.g. "Italy"), OR a reveal frame ("Beginning", "Ending", a country name)
- OR BEFORE/AFTER clearly differ in overlay text, framing, or subject

Mark as FALSE POSITIVE if:
- Same country overlay visible on both sides
- Same shot continuing (brief dark blink within one accent)
- No visible overlay on either side AND scene is identical

Return ONLY this JSON, no extra text:
{{"separators": {{"0": true, "1": false, "2": true}}}}"""


class AccentsSplitter:
    """Hybrid ffmpeg+Claude splitter tuned for viewer_vibes0-style accent videos."""

    def __init__(
        self,
        min_clip_duration: float = 4.0,
        max_clip_duration: float = 14.0,
        black_min_duration: float = 0.15,
        black_threshold: float = 0.10,
    ):
        cfg = load_config()["claude"]
        self._client = anthropic.Anthropic(api_key=cfg["api_key"])
        self._model = cfg.get("model", "claude-haiku-4-5-20251001")
        self.min_clip_duration = min_clip_duration
        self.max_clip_duration = max_clip_duration
        self.black_min_duration = black_min_duration
        self.black_threshold = black_threshold

    # ── Public API ───────────────────────────────────────────────────

    def split(self, video_path: Path, output_dir: Path) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        total = self._get_duration(video_path)
        if total < self.min_clip_duration:
            return []

        blacks = self._detect_black_moments(video_path)
        blacks = self._merge_adjacent(blacks, gap=1.5)
        logger.info(f"{video_path.name}: {len(blacks)} black candidates (after merge)")

        if not blacks:
            logger.warning(f"{video_path.name}: no blacks found, skipping")
            return []

        verified = self._validate_separators(video_path, blacks)
        logger.info(f"{video_path.name}: Claude verified {len(verified)}/{len(blacks)} as real")

        if not verified:
            verified = blacks  # trust ffmpeg if Claude is unsure

        segments = self._build_segments(verified, total)

        source_id = video_path.stem
        clips: list[Path] = []
        for i, (start, end) in enumerate(segments):
            clip_path = output_dir / f"{source_id}_c{i:02d}.mp4"
            if self._extract(video_path, clip_path, start, end):
                clips.append(clip_path)

        logger.info(f"split {source_id}: {len(clips)} clips")
        return clips

    def split_all(self, sources_dir: Path, segments_dir: Path) -> dict[str, list[Path]]:
        out: dict[str, list[Path]] = {}
        for src in sorted(sources_dir.glob("*.mp4")):
            out[src.stem] = self.split(src, segments_dir)
        return out

    # ── Black detection ──────────────────────────────────────────────

    def _merge_adjacent(
        self, blacks: list[tuple[float, float]], gap: float = 1.5
    ) -> list[tuple[float, float]]:
        """Merge black intervals whose end-to-start gap is < `gap` seconds.
        Prevents multi-flash transitions from being treated as many separators."""
        if not blacks:
            return []
        merged = [blacks[0]]
        for bs, be in blacks[1:]:
            prev_s, prev_e = merged[-1]
            if bs - prev_e < gap:
                merged[-1] = (prev_s, be)
            else:
                merged.append((bs, be))
        return merged

    def _detect_black_moments(self, video_path: Path) -> list[tuple[float, float]]:
        cmd = [
            "ffmpeg", "-v", "info", "-i", str(video_path),
            "-vf", f"blackdetect=d={self.black_min_duration}:pix_th={self.black_threshold}",
            "-an", "-f", "null", "-",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        pattern = re.compile(r"black_start:(\d+\.?\d*)\s+black_end:(\d+\.?\d*)")
        return [(float(m.group(1)), float(m.group(2))) for m in pattern.finditer(r.stderr)]

    # ── Claude validation ────────────────────────────────────────────

    def _validate_separators(
        self, video_path: Path, blacks: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        tmp = Path(tempfile.mkdtemp(prefix="accent_val_"))
        content: list[dict] = []
        for i, (bs, be) in enumerate(blacks):
            before_path = tmp / f"{i:03d}_before.jpg"
            after_path = tmp / f"{i:03d}_after.jpg"
            self._extract_frame(video_path, max(0, bs - 0.3), before_path)
            self._extract_frame(video_path, be + 0.3, after_path)
            if not before_path.exists() or not after_path.exists():
                continue
            b64_before = base64.standard_b64encode(before_path.read_bytes()).decode()
            b64_after = base64.standard_b64encode(after_path.read_bytes()).decode()
            content.append({"type": "text", "text": f"Candidate #{i} (black {bs:.1f}-{be:.1f}s)"})
            content.append({"type": "text", "text": "BEFORE:"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64_before}})
            content.append({"type": "text", "text": "AFTER:"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64_after}})

        content.append({"type": "text", "text": ACCENTS_VALIDATION_PROMPT})

        try:
            resp = self._client.messages.create(
                model=self._model, max_tokens=500,
                messages=[{"role": "user", "content": content}],
            )
            raw = resp.content[0].text.strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                flags = data.get("separators", {})
                return [blacks[i] for i in range(len(blacks)) if flags.get(str(i), False)]
        except Exception as e:
            logger.warning(f"Claude validation failed: {e}")
        return blacks

    # ── Segment building ─────────────────────────────────────────────

    def _build_segments(
        self, separators: list[tuple[float, float]], total: float
    ) -> list[tuple[float, float]]:
        """Each segment = [prev_black_end, current_black_start]
        so we DROP the separator black from the output (we want only the
        accent content, no trailing black screen)."""
        segments: list[tuple[float, float]] = []
        prev_end = 0.0
        for bs, be in separators:
            start = prev_end
            end = bs  # end at the START of the black → drop the black
            dur = end - start
            if self.min_clip_duration <= dur <= self.max_clip_duration:
                segments.append((start, end))
            elif dur > self.max_clip_duration:
                segments.append((start, start + self.max_clip_duration))
            prev_end = be
        # tail segment
        tail_dur = total - prev_end
        if self.min_clip_duration <= tail_dur <= self.max_clip_duration:
            segments.append((prev_end, total))
        return segments

    # ── ffmpeg helpers ───────────────────────────────────────────────

    def _extract(self, video_path: Path, out_path: Path, start: float, end: float) -> bool:
        dur = end - start
        cmd = [
            "ffmpeg", "-y", "-v", "warning",
            "-ss", str(start), "-i", str(video_path), "-t", str(dur),
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,"
                   "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,"
                   "fps=30,format=yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-force_key_frames", "expr:gte(t,n_forced*1)", "-g", "30",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-avoid_negative_ts", "make_zero", "-movflags", "+faststart",
            str(out_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        return r.returncode == 0 and out_path.exists()

    def _extract_frame(self, video_path: Path, ts: float, out_path: Path):
        subprocess.run(
            ["ffmpeg", "-y", "-v", "quiet", "-ss", str(ts), "-i", str(video_path),
             "-vframes", "1", "-vf", "scale=-1:360", "-q:v", "5", str(out_path)],
            timeout=15,
        )

    def _get_duration(self, video_path: Path) -> float:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(video_path)],
            capture_output=True, text=True,
        )
        try:
            return float(r.stdout.strip())
        except ValueError:
            return 0.0


# Back-compat wrappers for scripts/accents.py
def split_all(sources_dir: Path, segments_dir: Path, **kwargs) -> dict[str, list[Path]]:
    return AccentsSplitter(**kwargs).split_all(sources_dir, segments_dir)


def split_source(source_path: Path, out_dir: Path, **kwargs) -> list[Path]:
    return AccentsSplitter(**kwargs).split(source_path, out_dir)
