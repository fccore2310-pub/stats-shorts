"""
Hunter — finds football core video candidates from TikTok accounts.

Lists videos from a curated set of accounts that post football core content,
filters by duration (compilations are typically 30-90s), and returns candidates
for the Validator to judge.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# Known accounts that post football core-style content
KNOWN_ACCOUNTS = [
    "football.1.hub",
    "hopecore.video",
    "footballcoremedia",
    "thefootballcore_",
    "football.coree",
    "hopecorefootball",
    "football.hopecore",
]


@dataclass
class Candidate:
    url: str
    video_id: str
    account: str
    duration: float
    view_count: int
    title: str


class Hunter:
    """Finds candidate videos from known TikTok accounts."""

    def __init__(self, accounts: list[str] | None = None):
        self.accounts = accounts or KNOWN_ACCOUNTS

    def find_candidates(
        self,
        per_account: int = 10,
        min_duration: float = 25,
        max_duration: float = 120,
        min_views: int = 0,
    ) -> list[Candidate]:
        """List recent videos from all accounts and filter viable candidates."""
        candidates: list[Candidate] = []

        for account in self.accounts:
            try:
                account_candidates = self._list_account(
                    account, per_account, min_duration, max_duration, min_views
                )
                candidates.extend(account_candidates)
                logger.info(f"@{account}: {len(account_candidates)} candidates")
            except Exception as e:
                logger.warning(f"Failed to list @{account}: {e}")

        # Sort by view count (popular first)
        candidates.sort(key=lambda c: c.view_count, reverse=True)
        logger.info(f"Total candidates: {len(candidates)}")
        return candidates

    def _list_account(
        self,
        account: str,
        limit: int,
        min_dur: float,
        max_dur: float,
        min_views: int,
    ) -> list[Candidate]:
        cmd = [
            "yt-dlp",
            "--cookies-from-browser", "chrome",
            "--flat-playlist", "--dump-json",
            "--playlist-items", f"1-{limit}",
            f"https://www.tiktok.com/@{account}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return []

        candidates = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            duration = data.get("duration") or 0
            view_count = data.get("view_count") or 0

            if duration < min_dur or duration > max_dur:
                continue
            if view_count < min_views:
                continue

            video_id = data.get("id", "")
            candidates.append(Candidate(
                url=f"https://www.tiktok.com/@{account}/video/{video_id}",
                video_id=video_id,
                account=account,
                duration=duration,
                view_count=view_count,
                title=data.get("title", ""),
            ))

        return candidates
