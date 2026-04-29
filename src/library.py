"""
Segment library — organized storage for football core clips.

Structure:
    data/library/
        sources/          # Original downloaded videos (one per source URL)
            {video_id}.mp4
        segments/         # Individual pre-cut segments (clip + black separator)
            {video_id}_{idx:03d}.mp4
        metadata/         # JSON metadata per segment
            index.json    # Master index of all segments
            {video_id}_{idx}.json
    data/outputs/         # Generated compilations

Flow:
    1. add_source(url) → downloads video, splits into segments, saves to library
    2. generate_mix() → picks random segments from library, concatenates
"""
from __future__ import annotations

import json
import logging
import random
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from src.services.hybrid_splitter import HybridSplitter
from src.utils.video_utils import get_video_info
from src.utils.config import project_root

logger = logging.getLogger(__name__)


class SegmentLibrary:
    """Organized library of pre-cut football core segments."""

    def __init__(self, root: Path | None = None):
        root = root or (project_root() / "data" / "library")
        self.sources_dir = root / "sources"
        self.segments_dir = root / "segments"
        self.metadata_dir = root / "metadata"

        for d in (self.sources_dir, self.segments_dir, self.metadata_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.index_path = self.metadata_dir / "index.json"

    # ── Adding sources ──────────────────────────────────────────────

    def add_source(self, url: str) -> dict:
        """Download a video, split it into segments, save everything to the library.
        Returns metadata about what was added."""
        video_id = self._extract_video_id(url)

        # Skip if already processed
        if self._is_already_added(video_id):
            logger.info(f"Skipping {video_id}: already in library")
            return self._get_source_metadata(video_id)

        # Download to sources/
        video_path = self._download(url, video_id)
        if not video_path:
            return {"url": url, "status": "download_failed"}

        # Split at black separators → save to segments/
        segments = self._split_and_save(video_path, video_id)

        meta = {
            "video_id": video_id,
            "url": url,
            "source_path": str(video_path.relative_to(project_root())),
            "segments": [str(s.relative_to(project_root())) for s in segments],
            "segment_count": len(segments),
            "added_at": datetime.now().isoformat(),
            "status": "ok",
        }

        # Save individual source metadata
        (self.metadata_dir / f"{video_id}.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False)
        )

        # Update master index
        self._update_index(video_id, meta)

        logger.info(f"Added {video_id}: {len(segments)} segments")
        return meta

    # ── Hunt: automated discovery + validation + ingest ─────────────

    def hunt(
        self,
        per_account: int = 10,
        max_to_validate: int = 20,
        min_views: int = 5000,
        accounts: list[str] | None = None,
    ) -> dict:
        """Find football core candidates, validate with Claude, add accepted ones.

        Returns dict with counts: {candidates, validated, accepted, rejected, added}.
        """
        from src.services.hunter import Hunter
        from src.services.validator import Validator

        hunter = Hunter(accounts)
        validator = Validator()

        # Step 1: Find candidates
        logger.info("Hunting candidates from known accounts...")
        candidates = hunter.find_candidates(
            per_account=per_account, min_views=min_views
        )

        # Skip already-added videos
        new_candidates = [c for c in candidates if not self._is_already_added(
            self._extract_video_id(c.url)
        )]
        logger.info(f"New candidates (not in library): {len(new_candidates)}")

        # Limit validation
        to_validate = new_candidates[:max_to_validate]
        stats = {
            "candidates": len(candidates),
            "new_candidates": len(new_candidates),
            "validated": 0,
            "accepted": 0,
            "rejected": 0,
            "added": 0,
            "decisions": [],
        }

        # Step 2: Download preview + validate each
        for candidate in to_validate:
            video_id = self._extract_video_id(candidate.url)
            logger.info(f"Validating {candidate.account}/{video_id} ({candidate.view_count:,} views)...")

            # Download to source path (so if valid, we don't re-download)
            video_path = self._download(candidate.url, video_id)
            if not video_path:
                stats["decisions"].append({
                    "url": candidate.url,
                    "status": "download_failed",
                })
                continue

            # Validate with Claude Vision
            result = validator.validate(video_path)
            stats["validated"] += 1

            decision = {
                "url": candidate.url,
                "account": candidate.account,
                "views": candidate.view_count,
                "valid": result.valid,
                "reason": result.reason,
                "confidence": result.confidence,
            }
            stats["decisions"].append(decision)

            if result.valid and result.confidence in ("high", "medium"):
                stats["accepted"] += 1
                logger.info(f"  ✓ ACCEPTED: {result.reason}")
                # Add to library (this splits + stores segments)
                add_result = self.add_source(candidate.url)
                if add_result.get("status") == "ok":
                    stats["added"] += 1
            else:
                stats["rejected"] += 1
                logger.info(f"  ✗ REJECTED: {result.reason}")
                # Clean up the downloaded source since we're not keeping it
                if video_path.exists():
                    video_path.unlink()

        return stats

    def _download(self, url: str, video_id: str) -> Path | None:
        out_path = self.sources_dir / f"{video_id}.mp4"
        if out_path.exists() and out_path.stat().st_size > 10000:
            return out_path

        cmd = [
            "yt-dlp",
            "-o", str(out_path),
            "--no-warnings",
            url,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode != 0 or not out_path.exists():
            logger.warning(f"Download failed for {url}: {result.stderr[:200]}")
            return None
        return out_path

    def _split_and_save(self, video_path: Path, video_id: str) -> list[Path]:
        """Split video using ffmpeg blackdetect + Claude validation."""
        splitter = HybridSplitter()
        tmp_dir = self.segments_dir / "_tmp" / video_id
        tmp_dir.mkdir(parents=True, exist_ok=True)

        raw_segments = splitter.split(video_path, tmp_dir)

        saved: list[Path] = []
        for i, seg in enumerate(raw_segments):
            try:
                dur = get_video_info(seg)["duration"]
                if not (4.0 <= dur <= 15.0):
                    continue
            except Exception:
                continue

            # Move to segments/ with proper naming
            final_path = self.segments_dir / f"{video_id}_{i:03d}.mp4"
            seg.rename(final_path)
            saved.append(final_path)

            # Save segment metadata
            self._save_segment_metadata(final_path, video_id, i, dur)

        # Cleanup tmp
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

        return saved

    def _save_segment_metadata(self, path: Path, video_id: str, idx: int, duration: float):
        meta = {
            "segment_id": f"{video_id}_{idx:03d}",
            "video_id": video_id,
            "index": idx,
            "duration": round(duration, 2),
            "path": str(path.relative_to(project_root())),
            "added_at": datetime.now().isoformat(),
        }
        (self.metadata_dir / f"segment_{video_id}_{idx:03d}.json").write_text(
            json.dumps(meta, indent=2)
        )

    def _update_index(self, video_id: str, source_meta: dict):
        index = self._load_index()
        index["sources"][video_id] = {
            "url": source_meta["url"],
            "added_at": source_meta["added_at"],
            "segment_count": source_meta["segment_count"],
        }
        index["total_sources"] = len(index["sources"])
        index["total_segments"] = sum(s["segment_count"] for s in index["sources"].values())
        index["updated_at"] = datetime.now().isoformat()
        self.index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False))

    def _load_index(self) -> dict:
        if self.index_path.exists():
            return json.loads(self.index_path.read_text())
        return {"sources": {}, "total_sources": 0, "total_segments": 0}

    def _is_already_added(self, video_id: str) -> bool:
        return (self.metadata_dir / f"{video_id}.json").exists()

    def _get_source_metadata(self, video_id: str) -> dict:
        path = self.metadata_dir / f"{video_id}.json"
        return json.loads(path.read_text()) if path.exists() else {}

    @staticmethod
    def _extract_video_id(url: str) -> str:
        """Extract a stable video ID from various URL formats."""
        import re
        # TikTok: /video/1234567890
        m = re.search(r"/video/(\d+)", url)
        if m:
            return f"tt_{m.group(1)}"
        # TikTok short: vm.tiktok.com/XXXXX
        m = re.search(r"vm\.tiktok\.com/(\w+)", url)
        if m:
            return f"ttvm_{m.group(1)}"
        # YouTube shorts: /shorts/XXXXX
        m = re.search(r"/shorts/([A-Za-z0-9_-]+)", url)
        if m:
            return f"yt_{m.group(1)}"
        # YouTube: watch?v=XXXXX
        m = re.search(r"[?&]v=([A-Za-z0-9_-]+)", url)
        if m:
            return f"yt_{m.group(1)}"
        # Instagram: /reel/XXXXX/
        m = re.search(r"/reel/([A-Za-z0-9_-]+)", url)
        if m:
            return f"ig_{m.group(1)}"
        # Fallback: hash
        import hashlib
        return f"url_{hashlib.md5(url.encode()).hexdigest()[:12]}"

    # ── Listing and mixing ──────────────────────────────────────────

    def list_segments(self) -> list[Path]:
        """Return all segments currently in the library."""
        return sorted(self.segments_dir.glob("*.mp4"))

    def stats(self) -> dict:
        index = self._load_index()
        segments = self.list_segments()
        total_duration = 0.0
        for s in segments:
            try:
                total_duration += get_video_info(s)["duration"]
            except Exception:
                pass
        return {
            "sources": len(index.get("sources", {})),
            "segments": len(segments),
            "total_duration_minutes": round(total_duration / 60, 1),
        }

    def generate_mix(
        self,
        target_duration: float = 50,
        output_path: Path | None = None,
        avoid_consecutive_from_same_source: bool = True,
    ) -> Path:
        """Pick random segments from the library and concatenate into a new video."""
        all_segments = self.list_segments()
        if not all_segments:
            raise ValueError("No segments in library — add some sources first")

        # Shuffle but avoid consecutive segments from same source for variety
        random.shuffle(all_segments)
        if avoid_consecutive_from_same_source:
            all_segments = self._reorder_for_variety(all_segments)

        # Pick segments until we hit target duration
        selected: list[Path] = []
        total = 0.0
        for seg in all_segments:
            try:
                dur = get_video_info(seg)["duration"]
            except Exception:
                continue
            if total + dur > target_duration:
                continue  # Skip, try next
            selected.append(seg)
            total += dur
            if total >= target_duration - 3:
                break

        if not selected:
            raise ValueError("No segments fit the target duration")

        # Generate output
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            project_id = f"{timestamp}_{uuid.uuid4().hex[:6]}"
            output_path = project_root() / "data" / "outputs" / f"{project_id}.mp4"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._concat(selected, output_path)

        # Save manifest
        manifest = {
            "output": str(output_path.relative_to(project_root())),
            "duration_seconds": round(total, 1),
            "segment_count": len(selected),
            "segments_used": [s.name for s in selected],
            "generated_at": datetime.now().isoformat(),
        }
        output_path.with_suffix(".json").write_text(json.dumps(manifest, indent=2))

        logger.info(f"Generated mix: {output_path} ({total:.1f}s, {len(selected)} segments)")
        return output_path

    def generate_long_post(
        self,
        target_duration: float = 600,  # 10 min — unlocks mid-rolls (need ≥8 min)
        aspect: str = "16:9",
        output_dir: Path | None = None,
    ) -> dict:
        """Generate a LONG-FORM YouTube video (~10 min) from the library, keeping
        the original audio of each clip (no external music for this first test).

        Different from generate_post (Shorts): horizontal 16:9 1920x1080 for TV-desktop
        experience + ad-friendly. Also uses the variety reorder but NOT the first-clip
        uniqueness gate (longs are uploaded much more rarely so repeated openings are OK).
        """
        all_segments = self.list_segments()
        if not all_segments:
            raise ValueError("No segments in library")

        random.shuffle(all_segments)
        ordered = self._reorder_for_variety(all_segments)

        # Pick segments up to the target duration
        selected: list[Path] = []
        total = 0.0
        for seg in ordered:
            try:
                dur = get_video_info(seg)["duration"]
            except Exception:
                continue
            if total + dur > target_duration + 60:
                continue
            selected.append(seg)
            total += dur
            if total >= target_duration - 10:
                break

        if total < 480:  # less than 8 min means no mid-rolls — not worth it
            raise ValueError(
                f"Library too small for long: only {total:.0f}s available "
                f"(need ≥480s for ad-eligible long)"
            )

        # Prepare output
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        post_id = f"LONG_{timestamp}_{uuid.uuid4().hex[:6]}"
        if output_dir is None:
            output_dir = project_root() / "data" / "outputs" / post_id
        output_dir.mkdir(parents=True, exist_ok=True)

        long_path = output_dir / "long_video.mp4"

        logger.info(f"Rendering long video ({len(selected)} segments, {total:.1f}s, {aspect})...")
        self._concat_horizontal(selected, long_path) if aspect == "16:9" else self._concat(selected, long_path)

        # Generate title + description tuned for compilation longs
        from src.services.metadata_generator import MetadataGenerator
        meta_gen = MetadataGenerator()
        title, description = meta_gen.generate_long_youtube(duration_min=round(total / 60))

        # YouTube Shorts (<60s) vs long is auto-detected by length + resolution.
        # 16:9 + >60s = standard long. 9:16 + <60s = Shorts. Our target is standard long.

        manifest = {
            "post_id": post_id,
            "type": "long",
            "long": {
                "path": str(long_path.relative_to(project_root())),
                "duration_seconds": round(total, 1),
                "segment_count": len(selected),
                "segments": [s.name for s in selected],
            },
            "youtube": {
                "title": title,
                "description": description,
                "hashtags": ["footballcore", "football", "compilation",
                             "footballedit", "hopecore", "beautifulgame"],
            },
            "generated_at": datetime.now().isoformat(),
        }
        (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

        logger.info(f"Long video ready at {output_dir}")
        logger.info(f"  Duration: {total:.1f}s ({total/60:.1f}min) | Segments: {len(selected)}")
        return manifest

    def _concat_horizontal(self, segments: list[Path], output_path: Path):
        """Two-pass 16:9 concat (ffmpeg filter_complex can't handle 100+ inputs):
        1) Normalize each clip to 1920x1080 with blurred background (parallel-safe).
        2) Concat demuxer (no re-encode — instant)."""
        import tempfile

        tmp_dir = Path(tempfile.mkdtemp(prefix="longnorm_"))
        try:
            normalized: list[Path] = []
            for i, seg in enumerate(segments):
                out = tmp_dir / f"n{i:04d}.mp4"
                # Single-input filter: blur background + center vertical clip on top
                filt = (
                    "split=2[bg][fg];"
                    "[bg]scale=1920:1080:force_original_aspect_ratio=increase,"
                    "crop=1920:1080,boxblur=20:1,setsar=1[bgblur];"
                    "[fg]scale=-1:1080,setsar=1[fgscaled];"
                    "[bgblur][fgscaled]overlay=(W-w)/2:0,fps=30"
                )
                cmd = [
                    "ffmpeg", "-y", "-i", str(seg),
                    "-vf", filt,
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                    "-c:a", "aac", "-ar", "44100", "-b:a", "128k",
                    "-pix_fmt", "yuv420p",
                    str(out),
                ]
                subprocess.run(cmd, check=True, capture_output=True)
                normalized.append(out)
                if (i + 1) % 20 == 0:
                    logger.info(f"  normalized {i+1}/{len(segments)}")

            # Concat demuxer: lossless, instant
            list_file = tmp_dir / "concat.txt"
            list_file.write_text("\n".join(f"file '{p}'" for p in normalized))
            cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(list_file),
                "-c", "copy",
                "-movflags", "+faststart",
                str(output_path),
            ]
            subprocess.run(cmd, check=True, capture_output=True)
        finally:
            # Clean up temp dir
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def generate_post(
        self,
        output_dir: Path | None = None,
    ) -> dict:
        """Generate BOTH versions (45s TikTok + 75s YouTube Shorts/IG Reels) from
        overlapping segments. Returns paths + metadata ready for publishing."""
        all_segments = self.list_segments()
        if not all_segments:
            raise ValueError("No segments in library")

        # Build ordered pool (variety-reordered, shuffled)
        random.shuffle(all_segments)
        ordered = self._reorder_for_variety(all_segments)

        # First-clip uniqueness: avoid reusing the opening segment across recent posts
        # (user feedback: "que no se repita la foto inicial en los vídeos en la misma plataforma").
        # We enforce globally — simpler and strictly stronger than per-platform.
        recent_first_clips = self._load_recent_first_clips()
        for idx, seg in enumerate(ordered):
            if seg.name not in recent_first_clips:
                if idx != 0:
                    ordered = [ordered[idx]] + ordered[:idx] + ordered[idx + 1 :]
                break
        else:
            logger.warning("All segments recently used as first-clip — falling back to shuffled order")

        # Pick enough segments for the 75s version (superset)
        long_segments: list[Path] = []
        long_total = 0.0
        for seg in ordered:
            try:
                dur = get_video_info(seg)["duration"]
            except Exception:
                continue
            if long_total + dur > 78:
                continue
            long_segments.append(seg)
            long_total += dur
            if long_total >= 72:
                break

        # 45s version = first N segments of long version that fit in ~45s
        short_segments: list[Path] = []
        short_total = 0.0
        for seg in long_segments:
            try:
                dur = get_video_info(seg)["duration"]
            except Exception:
                continue
            if short_total + dur > 48:
                break
            short_segments.append(seg)
            short_total += dur

        if len(short_segments) < 3 or len(long_segments) < 4:
            raise ValueError("Not enough segments for both versions")

        # Prepare output paths
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        post_id = f"{timestamp}_{uuid.uuid4().hex[:6]}"
        if output_dir is None:
            output_dir = project_root() / "data" / "outputs" / post_id
        output_dir.mkdir(parents=True, exist_ok=True)

        tiktok_path = output_dir / "tiktok_45s.mp4"
        long_path = output_dir / "long_75s.mp4"

        logger.info(f"Rendering TikTok 45s version ({len(short_segments)} segments)...")
        self._concat(short_segments, tiktok_path)

        logger.info(f"Rendering Long 75s version ({len(long_segments)} segments)...")
        self._concat(long_segments, long_path)

        # Generate unique metadata per platform via Claude
        logger.info("Generating unique captions + hashtags per platform...")
        from src.services.metadata_generator import MetadataGenerator
        meta_gen = MetadataGenerator()
        meta = meta_gen.generate()

        # Manifest
        manifest = {
            "post_id": post_id,
            "tiktok": {
                "path": str(tiktok_path.relative_to(project_root())),
                "duration_seconds": round(short_total, 1),
                "segment_count": len(short_segments),
                "segments": [s.name for s in short_segments],
                "caption": meta.tiktok_caption,
                "hashtags": meta.tiktok_hashtags,
            },
            "long": {
                "path": str(long_path.relative_to(project_root())),
                "duration_seconds": round(long_total, 1),
                "segment_count": len(long_segments),
                "segments": [s.name for s in long_segments],
            },
            "youtube": {
                "title": meta.youtube_title,
                "description": meta.youtube_description,
                "hashtags": meta.youtube_hashtags,
            },
            "instagram": {
                "caption": meta.instagram_caption,
                "hashtags": meta.instagram_hashtags,
            },
            "x": {
                "caption": meta.x_caption,
                "hashtags": meta.x_hashtags,
            },
            "generated_at": datetime.now().isoformat(),
        }
        (output_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2)
        )

        # Remember the first clip so next post avoids reusing it
        if short_segments:
            self._record_first_clip(short_segments[0].name)

        logger.info(f"Post ready at {output_dir}")
        logger.info(f"  TikTok: {short_total:.1f}s | Long: {long_total:.1f}s")
        return manifest

    # ── First-clip diversity state ──────────────────────────────────
    _FIRST_CLIPS_WINDOW = 12  # remember last 12 opening clips

    def _first_clips_state_path(self) -> Path:
        p = project_root() / "data" / "analytics" / "used_first_clips.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _load_recent_first_clips(self) -> list[str]:
        p = self._first_clips_state_path()
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text())
            return data.get("recent", [])[-self._FIRST_CLIPS_WINDOW:]
        except Exception:
            return []

    def _record_first_clip(self, name: str) -> None:
        p = self._first_clips_state_path()
        recent = self._load_recent_first_clips()
        recent.append(name)
        recent = recent[-self._FIRST_CLIPS_WINDOW:]
        try:
            p.write_text(json.dumps({"recent": recent}, indent=2))
        except Exception as e:
            logger.warning(f"Could not persist first-clip state: {e}")

    def _reorder_for_variety(self, segments: list[Path]) -> list[Path]:
        """Shuffle so consecutive segments come from different source videos when possible."""
        def source_of(p: Path) -> str:
            return "_".join(p.stem.split("_")[:-1])

        # Group by source
        by_source: dict[str, list[Path]] = {}
        for s in segments:
            by_source.setdefault(source_of(s), []).append(s)

        # Round-robin pick
        result: list[Path] = []
        while any(by_source.values()):
            for src in list(by_source.keys()):
                if by_source[src]:
                    result.append(by_source[src].pop(0))

        return result

    # Account handle baked into every Short as a subtle top-right watermark.
    # Provides identity throughout the clip (combats the "anonymous aggregator"
    # vibe that's killing our follow conversion on TT/IG).
    WATERMARK_PATH = "data/assets/watermark.png"

    def _watermark_path(self) -> Path:
        return project_root() / self.WATERMARK_PATH

    def _concat(self, segments: list[Path], output_path: Path):
        # Use FFmpeg filter_complex concat — re-encodes but produces clean output
        # This is much more reliable than stream copy when segments come from
        # different source videos with varying codecs/timestamps.

        # Build inputs list — segments first, watermark PNG last
        inputs_args: list[str] = []
        for seg in segments:
            inputs_args.extend(["-i", str(seg)])
        wm_path = self._watermark_path()
        has_watermark = wm_path.exists()
        if has_watermark:
            inputs_args.extend(["-i", str(wm_path)])
            wm_idx = len(segments)  # last input

        # Build concat filter with per-input normalization (forces uniform SAR, fps, size)
        # This prevents "parameters do not match" errors when segments have slightly different SARs
        n = len(segments)
        norm_parts = []
        concat_inputs = []
        for i in range(n):
            # Normalize each input before concat: set SAR 1:1, scale/pad to 1080x1920, fps 30
            norm_parts.append(
                f"[{i}:v:0]scale=1080:1920:force_original_aspect_ratio=decrease,"
                f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}];"
                f"[{i}:a:0]aresample=44100,asetpts=PTS-STARTPTS[a{i}];"
            )
            concat_inputs.append(f"[v{i}][a{i}]")
        filter_complex = "".join(norm_parts) + "".join(concat_inputs)
        if has_watermark:
            # Concat first, then overlay watermark in top-right corner with 30px margins
            filter_complex += (
                f"concat=n={n}:v=1:a=1[concatv][outa];"
                f"[concatv][{wm_idx}:v]overlay=W-w-30:30[outv]"
            )
        else:
            filter_complex += f"concat=n={n}:v=1:a=1[outv][outa]"

        cmd = [
            "ffmpeg", "-y", "-v", "warning",
            *inputs_args,
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg concat failed: {result.stderr[:400]}")
