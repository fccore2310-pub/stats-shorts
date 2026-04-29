"""
Caption generator for accents niche (@funny.jokes.23).

Voice: conversational, asking viewer to pick a favorite → drives comments.
Hook is the first 2 words — must make you stop scrolling.
"""
from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass

import anthropic

from src.utils.config import load_config

logger = logging.getLogger(__name__)

CORE_HASHTAGS = ["accents", "funny", "funnyjokes"]
ROTATING_POOL = [
    "africa", "kids", "english", "learnenglish", "accentchallenge",
    "viral", "fyp", "foryoupage", "comedy", "funnykids",
    "africankids", "language", "languages", "british", "american",
    "spanishaccent", "italianaccent", "frenchaccent", "germanaccent",
]

PROMPT = """You write captions for a TikTok/Reels account where African kids imitate English accents from different countries (Sweden, USA, UK, Italy, France, Spain, etc.).

REAL vibes from top accounts in this niche:
  - "which one won? 👀"
  - "spanish english was UNREAL 💀"
  - "rank them 1-5"
  - "the german one got me"
  - "which accent is your favorite?"
  - "wait for Italy 🇮🇹😭"
  - "they ATE this 🔥"

Rules:
- Conversational, asking viewer to reply → drives comments = reach.
- 3-8 words. NEVER clickbait, NEVER "you won't believe".
- One emoji max, sometimes a country flag if relevant.
- Gen-Z voice: "ate", "unreal", "no bc", "SOS", "💀".
- Lowercase preferred, unless emphasizing a country/name.

The clips in this post feature these countries (in order): {countries}

Return ONLY valid JSON, no other text:
{{
  "instagram_caption": "...",
  "tiktok_caption": "...",
  "instagram_hashtags": ["tag1", "tag2", ...],
  "tiktok_hashtags": ["tag1", ...]
}}

Keep hashtags to 5-8 per platform, all lowercase, no # symbol."""


@dataclass
class AccentPostMetadata:
    instagram_caption: str
    tiktok_caption: str
    instagram_hashtags: list[str]
    tiktok_hashtags: list[str]

    def to_dict(self) -> dict:
        return {
            "instagram": {"caption": self.instagram_caption, "hashtags": self.instagram_hashtags},
            "tiktok": {"caption": self.tiktok_caption, "hashtags": self.tiktok_hashtags},
        }


class AccentsMetadataGenerator:
    def __init__(self):
        cfg = load_config()["claude"]
        self._client = anthropic.Anthropic(api_key=cfg["api_key"])
        self._model = cfg.get("model", "claude-haiku-4-5-20251001")

    def generate(self, countries: list[str] | None = None) -> AccentPostMetadata:
        countries = countries or ["random"]
        countries_str = ", ".join(countries)

        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=500,
                messages=[{"role": "user", "content": PROMPT.format(countries=countries_str)}],
            )
            raw = resp.content[0].text.strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                return self._finalize(data)
        except Exception as e:
            logger.warning(f"Claude caption failed: {e}")

        return self._fallback(countries)

    def _finalize(self, d: dict) -> AccentPostMetadata:
        pool = random.sample(ROTATING_POOL, k=min(4, len(ROTATING_POOL)))
        ig_tags = list(dict.fromkeys(CORE_HASHTAGS + d.get("instagram_hashtags", []) + pool))[:8]
        tt_tags = list(dict.fromkeys(CORE_HASHTAGS + d.get("tiktok_hashtags", []) + pool))[:8]
        return AccentPostMetadata(
            instagram_caption=d.get("instagram_caption", "which accent won? 👀"),
            tiktok_caption=d.get("tiktok_caption", "rank them 1-5"),
            instagram_hashtags=ig_tags,
            tiktok_hashtags=tt_tags,
        )

    def _fallback(self, countries: list[str]) -> AccentPostMetadata:
        pool = random.sample(ROTATING_POOL, k=4)
        return AccentPostMetadata(
            instagram_caption="which one won? 👀",
            tiktok_caption="rank them 1-5",
            instagram_hashtags=CORE_HASHTAGS + pool,
            tiktok_hashtags=CORE_HASHTAGS + pool,
        )
