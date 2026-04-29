"""
Metadata Generator — Claude writes minimalist captions matching the real
football core style (short, signature hashtags, low-key).

Real examples from the niche (for reference, not to copy verbatim):
  - "football core ⚽"
  - "hopecore football video . . . ."
  - "the best of football core 👑"
  - "football core."

No clickbait, no "Most Insane Goals 2025", no SEO-spam. Just the vibe.
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


# Core hashtags (always used) + rotating pool
CORE_HASHTAGS = ["footballcore", "football", "footballtiktok"]

ROTATING_POOL = [
    # Core niche
    "hopecore", "footballedit", "footballshorts", "footballvideo", "skills",
    "funnyfootball", "footballskills",
    # Community
    "soccer", "beautifulgame", "soccerlife",
    # Growth (use sparingly)
    "viralvideo", "fyp", "foryoupage",
]


PROMPT = """You are writing captions for a football core social media account.

REAL examples of captions from top football core accounts (these are the vibe):
  - "football core ⚽"
  - "hopecore football video . . . ."
  - "the best of football core 👑"
  - "football core."
  - "football core ⚽ #footballedit"
  - "wait for the end 🤯"

STYLE RULES for TT/IG/X — VERY IMPORTANT:
- SHORT: 2-6 words maximum. Nothing more.
- Low-key vibe: not clickbait, not SEO-spam.
- 0-2 emojis max (⚽ 👑 🤯 🔥 💫 🎨 are OK).
- The phrase "football core" or a variant should appear in most.

Generate DIFFERENT captions for each platform (duplicate detection penalizes repeats):

TikTok: shortest — pure vibe. Example: "football core ⚽"
Instagram Reels: can be slightly longer, up to 10 words. Example: "football core hits different ⚽"
X/Twitter: very short, punchy, almost like a one-liner. Example: "football core." or "nothing but football core ⚽"

Return ONLY this JSON:
{{
  "tiktok": {{
    "caption": "short caption"
  }},
  "instagram": {{
    "caption": "short caption"
  }},
  "x": {{
    "caption": "short punchy caption"
  }}
}}
"""


# YouTube uses a completely different strategy: SEO-style clickbait wins
# on Shorts. Duplicate titles get suppressed hard, so we rotate seeds + let
# Claude go clickbait. We also generate a keyword-rich description for search.
YT_SEEDS = [
    "Most Insane Football Skills",
    "Incredible Football Moments",
    "Football Goals You Won't Believe",
    "Best Football Tricks",
    "Crazy Football Edit",
    "Unreal Football Plays",
    "Football Scenes That Hit Different",
    "Beautiful Football Moments",
    "Football Skills Compilation",
    "Wild Football Highlights",
    "When Football Gets Emotional",
    "Pure Football Magic",
    "Football at Its Finest",
    "Street Football Gone Wild",
    "Grassroots Football Vibes",
    "Football Core Aesthetic",
    "Beautiful Game Moments",
    "Football Hopecore Edit",
]

YT_PROMPT = """Write a YouTube Shorts title + description for a football compilation video.

TONE — important:
- Engaging but NOT over-the-top clickbait. Avoid cringe phrases like "YOU WON'T BELIEVE", "DEFY PHYSICS", "SHOCK YOU", "BROKE THE INTERNET", "WILL BLOW YOUR MIND".
- More like a confident sports-channel title. "Incredible", "Beautiful", "Wild", "Unreal" are OK; "INSANE" in all caps is not.
- 1-2 emojis at the end max (⚽ 🔥 👑 💫). Avoid 😱 and triple-emoji combos.
- Under 60 characters.
- Year mention (2026) is fine but OPTIONAL — don't force it.

YouTube Shorts algorithm rewards:
- Specific, searchable keywords (football, skills, goals, compilation)
- Natural but hook-y language (what makes a viewer actually tap)
- Uniqueness — DO NOT reuse the same template

AVOID:
- Generic titles like "football core ⚽"
- All-lowercase minimalist style (that's for TikTok)
- Cringe clickbait stack ("INSANE" + "SHOCK" + "BELIEVE")

Use this SEED idea to inspire a UNIQUE variation (reshape, don't copy):
SEED: "{seed}"

Also generate a 2-3 sentence description with natural keywords
(football, football core, skills, goals, compilation, beautiful game, hopecore,
grassroots, street football) — this feeds YT search.

Return ONLY this JSON:
{{
  "title": "...",
  "description": "2-3 sentences with keywords"
}}
"""


@dataclass
class PostMetadata:
    tiktok_caption: str
    tiktok_hashtags: list[str]
    youtube_title: str
    youtube_description: str
    youtube_hashtags: list[str]
    instagram_caption: str
    instagram_hashtags: list[str]
    x_caption: str
    x_hashtags: list[str]


class MetadataGenerator:
    """Generates minimalist football core captions via Claude."""

    def __init__(self):
        config = load_config()
        claude_cfg = config["claude"]
        self._client = anthropic.Anthropic(api_key=claude_cfg["api_key"])
        self._model = claude_cfg.get("model", "claude-haiku-4-5-20251001")

    def generate(self) -> PostMetadata:
        # Fetch already-used captions across all platforms so we can ask Claude
        # to avoid them. Same pattern we already use for YT titles.
        recent_tt = self._recent_captions("tiktok")
        recent_ig = self._recent_captions("instagram")
        recent_x  = self._recent_captions("x")

        for attempt in range(3):
            avoid_block = ""
            if recent_tt or recent_ig or recent_x:
                avoid_block = "\n\nDO NOT reuse or closely paraphrase any of these already-used captions:\n"
                if recent_tt:
                    avoid_block += "TikTok already used:\n" + "\n".join(f"  - {c}" for c in recent_tt[:10]) + "\n"
                if recent_ig:
                    avoid_block += "Instagram already used:\n" + "\n".join(f"  - {c}" for c in recent_ig[:10]) + "\n"
                if recent_x:
                    avoid_block += "X already used:\n" + "\n".join(f"  - {c}" for c in recent_x[:8]) + "\n"
                avoid_block += "Generate something meaningfully DIFFERENT (different verbs, structure, emojis)."
            try:
                resp = self._client.messages.create(
                    model=self._model,
                    max_tokens=400,
                    messages=[{"role": "user", "content": PROMPT + avoid_block}],
                )
                raw = resp.content[0].text.strip()
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                if match:
                    data = json.loads(match.group())
                    tiktok_caption = data["tiktok"]["caption"].strip()
                    instagram_caption = data["instagram"]["caption"].strip()
                    x_caption = data.get("x", {}).get("caption", "football core.").strip()
                    # Check collisions — if any collide, retry
                    collisions = []
                    if tiktok_caption in recent_tt: collisions.append("tt")
                    if instagram_caption in recent_ig: collisions.append("ig")
                    if x_caption in recent_x: collisions.append("x")
                    if not collisions:
                        break
                    logger.info(f"Caption collision on {collisions} attempt {attempt+1} — retrying")
                else:
                    raise ValueError("No JSON in response")
            except Exception as e:
                logger.warning(f"Caption generation attempt {attempt+1} failed: {e}")
        else:
            # All 3 attempts collided or failed — append unique suffix
            import time
            suffix = f" {random.choice(['⚽','👑','🤯','🔥','💫'])}{random.randint(1,99)}"
            tiktok_caption = locals().get("tiktok_caption", "football core") + suffix
            instagram_caption = locals().get("instagram_caption", "football core") + suffix
            x_caption = locals().get("x_caption", "football core.") + suffix

        # YouTube needs its own clickbait+SEO title (duplicates kill reach)
        youtube_title, youtube_description = self._generate_youtube()

        # Build hashtags: core + 2-3 rotating (keep total short)
        tiktok_tags = CORE_HASHTAGS + random.sample(ROTATING_POOL, 3)
        youtube_tags = CORE_HASHTAGS + random.sample(ROTATING_POOL, 4)
        instagram_tags = CORE_HASHTAGS + random.sample(ROTATING_POOL, 5)
        # X uses FEW hashtags — X's algorithm penalizes hashtag spam
        x_tags = ["footballcore", "football"]

        return PostMetadata(
            tiktok_caption=tiktok_caption,
            tiktok_hashtags=tiktok_tags,
            youtube_title=youtube_title,
            youtube_description=youtube_description,
            youtube_hashtags=youtube_tags,
            instagram_caption=instagram_caption,
            instagram_hashtags=instagram_tags,
            x_caption=x_caption,
            x_hashtags=x_tags,
        )

    def generate_long_youtube(self, duration_min: int = 10) -> tuple[str, str]:
        """Title + description for a long-form compilation video.

        Strategy: advertise duration in title (viewers self-select → better retention),
        position as chill/study/relax content (background-play = max watchtime),
        SEO keywords at start (football core / compilation / skills).
        """
        prompt = f"""Write a YouTube LONG-FORM video title + description for a {duration_min}-minute
football compilation video in the "football core" aesthetic style.

GOAL: maximize CTR + retention for MONETIZATION. This is NOT a Short — it's a
sit-and-watch compilation.

TITLE RULES:
- Mention duration clearly: "{duration_min} Minutes of..." or "{duration_min} Min of..."
- Position as background/chill/study content OR as a compilation vol
- Include "Football Core" or "Football" somewhere (SEO)
- 40-65 characters (not too long on mobile)
- 0-1 emoji max (⚽ 🎧 💫). No fire emojis, no caps-lock shouting
- Good shapes to pick from:
    "{duration_min} Minutes of Football Core to Study / Chill To ⚽"
    "Football Core Compilation Vol. 1 | {duration_min} Min of Pure Aesthetic"
    "The Beautiful Game — {duration_min} Min Football Edit"
    "{duration_min} Min of Hopecore Football to Relax To"
    "Football Core | {duration_min} Minute Aesthetic Compilation"

DESCRIPTION RULES:
- 3-4 sentences
- First sentence restates what it is (SEO keyword density)
- Mention: no talking, raw football, for studying/relaxing/background
- End with: "More football core every day — subscribe for daily Shorts + weekly compilations"
- Include 5-6 hashtags at the end: #footballcore #football #compilation #footballedit #hopecore #beautifulgame

Return ONLY this JSON:
{{
  "title": "...",
  "description": "..."
}}
"""
        for attempt in range(3):
            try:
                resp = self._client.messages.create(
                    model=self._model,
                    max_tokens=500,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = resp.content[0].text.strip()
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                if match:
                    data = json.loads(match.group())
                    title = data.get("title", "").strip()[:95]
                    desc = data.get("description", "").strip()
                    if title and desc:
                        return title, desc
            except Exception as e:
                logger.warning(f"Long YT metadata attempt {attempt+1} failed: {e}")

        # Fallback
        title = f"{duration_min} Minutes of Football Core ⚽"
        desc = (
            f"A {duration_min}-minute football core compilation — raw football footage "
            "with the original sounds from each clip. No talking, no ads-overload — "
            "perfect for studying, relaxing, or background watch. "
            "More football core every day — subscribe for daily Shorts + weekly compilations. "
            "#footballcore #football #compilation #footballedit #hopecore #beautifulgame"
        )
        return title, desc

    def _generate_youtube(self) -> tuple[str, str]:
        """YouTube Shorts title + description using clickbait/SEO style.

        Diversity guarantee: checks already-scheduled+recent YT titles and
        retries with a forbidden-list prompt until we get a novel title.
        Falls back to seed + emoji if Claude keeps collapsing to known titles.
        """
        recent_titles = self._recent_yt_titles()
        # Pick a seed we haven't used as the stem recently
        available_seeds = [s for s in YT_SEEDS if not any(s.lower() in t.lower() for t in recent_titles)]
        seed = random.choice(available_seeds or YT_SEEDS)

        for attempt in range(3):
            avoid_block = ""
            if recent_titles:
                avoid_block = (
                    "\n\nDO NOT USE any of these already-used titles or close variants:\n"
                    + "\n".join(f"  - {t}" for t in recent_titles[:12])
                    + "\nYour title MUST be meaningfully different (different verbs/nouns/structure)."
                )
            try:
                resp = self._client.messages.create(
                    model=self._model,
                    max_tokens=300,
                    messages=[{"role": "user", "content": YT_PROMPT.format(seed=seed) + avoid_block}],
                )
                raw = resp.content[0].text.strip()
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                if match:
                    data = json.loads(match.group())
                    title = data.get("title", "").strip()[:95]
                    desc = data.get("description", "").strip()
                    if title and desc and title not in recent_titles:
                        return title, desc
                    logger.info(f"YT title collision on attempt {attempt+1}: {title!r} — retrying")
                    seed = random.choice(YT_SEEDS)  # rotate seed for next attempt
            except Exception as e:
                logger.warning(f"YT metadata attempt {attempt+1} failed: {e}")

        # Fallback: seed + unique emoji combo forced-unique via timestamp suffix
        from datetime import datetime
        emoji = random.choice(["🔥", "⚽", "😱", "👑", "💫", "🎯", "💥"])
        suffix = random.choice(["", " 2026", " (Part 2)", " — Must Watch"])
        title = f"{seed}{suffix} {emoji}"[:95]
        desc = (
            "The best football core moments — raw skills, beautiful goals, "
            "and hopecore vibes from grassroots and street football. "
            "#Shorts #footballcore #football"
        )
        return title, desc

    def _recent_yt_titles(self) -> list[str]:
        return self._recent_captions("youtube")

    def _recent_captions(self, platform: str) -> list[str]:
        """Fetch captions/titles of scheduled + recently-published posts
        for the given platform so the generator can avoid duplicating them."""
        try:
            from src.services.uploadpost_publisher import UploadPostPublisher
            client = UploadPostPublisher()._client
            captions: list[str] = []
            # Scheduled
            try:
                sched = client.list_scheduled()
                posts = sched.get("scheduled_posts", sched) if isinstance(sched, dict) else sched
                for s in posts or []:
                    if platform in (s.get("platforms") or []):
                        t = s.get("title") or ""
                        # For non-YT platforms the "caption" lives in the description
                        # or platform_content[platform].caption. Grab first line only
                        # (drop hashtags for comparison).
                        pc = (s.get("platform_content") or {}).get(platform, {})
                        cap = pc.get("caption") or pc.get("title") or t
                        cap = cap.split("\n")[0].strip()  # strip hashtag tail
                        if cap: captions.append(cap)
            except Exception:
                pass
            # Published history
            try:
                hist = client.get_history(page=1, limit=20)
                for it in hist.get("history", []):
                    if it.get("platform") == platform:
                        cap = (it.get("post_caption") or it.get("post_title") or "").split("\n")[0].strip()
                        if cap: captions.append(cap)
            except Exception:
                pass
            # De-dupe preserve order
            seen = set()
            out = []
            for c in captions:
                if c not in seen:
                    seen.add(c); out.append(c)
            return out
        except Exception as e:
            logger.warning(f"Could not fetch recent {platform} captions: {e}")
            return []
