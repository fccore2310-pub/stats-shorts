"""
Upload-Post Publisher — uploads videos to all 4 platforms via Upload-Post SDK.

Requires Upload-Post Basic plan ($16/mo anual or $26 mensual) for TikTok + X.
Free tier only includes YouTube + Instagram.

Docs: https://docs.upload-post.com
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from upload_post import UploadPostClient

from src.utils.config import load_config

logger = logging.getLogger(__name__)


@dataclass
class PublishResult:
    platform: str
    success: bool
    post_id: str | None = None
    response_data: dict | None = None
    error: str | None = None


class UploadPostPublisher:
    """Publishes to TikTok + YouTube Shorts + Instagram Reels + X via Upload-Post SDK."""

    # Which platforms to attempt by default. Controlled via config [upload_post].platforms
    DEFAULT_PLATFORMS = ["tiktok", "youtube", "instagram", "x"]

    def __init__(self):
        config = load_config()
        up_cfg = config.get("upload_post", {})
        api_key = up_cfg.get("api_key", "")
        if not api_key or api_key == "...":
            raise ValueError(
                "Upload-Post API key not configured. "
                "Add it to config/config.toml under [upload_post].api_key"
            )

        self._client = UploadPostClient(api_key=api_key)
        self._user = up_cfg.get("username", "") or self._discover_user()
        self._enabled = set(up_cfg.get("platforms", self.DEFAULT_PLATFORMS))

    def _discover_user(self) -> str:
        """Fetch Upload-Post profiles and pick the first one."""
        try:
            data = self._client.list_users()
            profiles = data.get("profiles", [])
            if profiles:
                username = profiles[0]["username"]
                logger.info(f"Auto-discovered Upload-Post user: {username}")
                return username
        except Exception as e:
            logger.warning(f"Could not discover user: {e}")
        return ""

    def publish_post(
        self,
        manifest_path: Path,
        scheduled_date: str | None = None,
        timezone: str = "Europe/Madrid",
    ) -> list[PublishResult]:
        """Publish each platform version according to enabled platforms.

        If scheduled_date is given (ISO 8601, e.g. "2026-04-19T10:00:00Z"),
        Upload-Post servers will publish at that time (your Mac can be off).
        """
        manifest = json.loads(manifest_path.read_text())
        post_dir = manifest_path.parent
        results: list[PublishResult] = []

        tiktok_video = post_dir / "tiktok_45s.mp4"
        long_video = post_dir / "long_75s.mp4"

        extra_kwargs: dict = {}
        if scheduled_date:
            extra_kwargs["scheduled_date"] = scheduled_date
            extra_kwargs["timezone"] = timezone

        # TikTok: short version
        if "tiktok" in self._enabled:
            tt_caption_with_cta = f"{manifest['tiktok']['caption']} — {self._cta()}"
            results.append(self._upload(
                video_path=tiktok_video,
                title=tt_caption_with_cta[:100],
                description=self._build_caption(
                    manifest["tiktok"]["caption"], manifest["tiktok"]["hashtags"],
                    with_cta=True,
                ),
                platforms=["tiktok"],
                **extra_kwargs,
            ))

        # YouTube Shorts: long version
        if "youtube" in self._enabled:
            yt_desc = (
                manifest["youtube"]["description"]
                + "\n\n"
                + " ".join(f"#{h}" for h in manifest["youtube"]["hashtags"])
                + " #Shorts"
            )
            results.append(self._upload(
                video_path=long_video,
                title=manifest["youtube"]["title"],
                description=yt_desc,
                platforms=["youtube"],
                **extra_kwargs,
            ))

        # Instagram Reels: long version (same as YouTube, different caption)
        if "instagram" in self._enabled:
            ig_caption_with_cta = f"{manifest['instagram']['caption']} — {self._cta()}"
            insta_caption = self._build_caption(
                manifest["instagram"]["caption"], manifest["instagram"]["hashtags"],
                with_cta=True,
            )
            results.append(self._upload(
                video_path=long_video,
                title=ig_caption_with_cta[:100],
                description=insta_caption,
                platforms=["instagram"],
                **extra_kwargs,
            ))

        # X/Twitter: short version (X prefers <60s for algorithm boost)
        if "x" in self._enabled:
            x_caption = manifest.get("x", {}).get("caption") or manifest["tiktok"]["caption"]
            x_hashtags = manifest.get("x", {}).get("hashtags") or manifest["tiktok"]["hashtags"][:3]
            x_caption_with_cta = f"{x_caption} — {self._cta()}"
            results.append(self._upload(
                video_path=tiktok_video,
                title=x_caption_with_cta[:100],
                description=self._build_caption(x_caption, x_hashtags, with_cta=True),
                platforms=["x"],
                **extra_kwargs,
            ))

        return results

    def _upload(
        self,
        video_path: Path,
        title: str,
        description: str,
        platforms: list[str],
        **kwargs,
    ) -> PublishResult:
        platform_label = "+".join(platforms)

        if not video_path.exists():
            return PublishResult(platform_label, False, error=f"Video not found: {video_path}")
        if not self._user:
            return PublishResult(
                platform_label, False,
                error="No Upload-Post user. Connect accounts in the dashboard first.",
            )

        try:
            sched_info = ""
            if kwargs.get("scheduled_date"):
                sched_info = f" scheduled for {kwargs['scheduled_date']}"
            logger.info(f"Uploading {video_path.name} to {platform_label} as user '{self._user}'{sched_info}...")
            result = self._client.upload_video(
                video_path=str(video_path),
                title=title[:100],
                user=self._user,
                platforms=platforms,
                description=description[:2200],
                **kwargs,
            )
        except Exception as e:
            return PublishResult(platform_label, False, error=f"Upload failed: {e}")

        success = bool(result.get("success", False))
        post_id = (
            result.get("id")
            or result.get("post_id")
            or result.get("request_id")
            or result.get("job_id")
        )

        if not success:
            msg = result.get("message", result.get("error", "unknown error"))
            return PublishResult(platform_label, False, error=msg, response_data=result)

        return PublishResult(
            platform=platform_label,
            success=True,
            post_id=str(post_id) if post_id else None,
            response_data=result,
        )

    # Engagement CTA appended to captions to lift profile-tap rate / follow rate.
    # Kept short and ASCII-safe except for the arrow emoji. Variants rotate so the
    # platform algorithms don't flag identical-text spam pattern across uploads.
    _CTA_VARIANTS = [
        "which one do you like more? ⬇️ follow for daily",
        "which moment hit different? ⬇️ follow for daily",
        "fav clip? ⬇️ follow for daily football core",
        "best one? ⬇️ follow for daily",
        "rate the clip ⬇️ follow for daily football core",
    ]

    @classmethod
    def _cta(cls) -> str:
        import random
        return random.choice(cls._CTA_VARIANTS)

    @classmethod
    def _build_caption(cls, base: str, hashtags: list[str], with_cta: bool = False) -> str:
        tags = " ".join(f"#{h}" for h in hashtags)
        if with_cta:
            return f"{base}\n\n{cls._cta()}\n\n{tags}"
        return f"{base}\n\n{tags}"
