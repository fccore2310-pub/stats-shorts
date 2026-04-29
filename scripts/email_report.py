"""
Email stats report — pulls fresh analytics and emails a concise summary
optimized for mobile reading (plain text, short, scannable).

Runs via launchd (scripts/launchd/com.fccore.email.plist) every 6 hours.

Requires Gmail SMTP app password in config.toml:
    [email]
    sender   = "fc.core.23.10@gmail.com"
    password = "xxxx xxxx xxxx xxxx"   # Gmail app password (16 chars, spaces OK)
    to       = "marcospastorabajo@gmail.com"
"""
from __future__ import annotations

import json
import logging
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tomli

from scripts.analytics_pull import pull
from src.utils.config import load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = ROOT / "data" / "analytics" / "snapshots"
TZ = ZoneInfo("Europe/Madrid")


HEADLINE = ("followers", "views", "impressions", "likes", "profileViews", "shares", "saves")


def _flatten(snap: dict) -> dict[str, dict]:
    """Flatten per_platform payloads ({instagram:{instagram:{...}}}) to numbers."""
    out: dict[str, dict] = {}
    for platform, payload in snap.get("per_platform", {}).items():
        if "error" in payload:
            out[platform] = {"error": payload["error"]}
            continue
        inner = payload.get(platform, payload)
        if inner.get("success") is False:
            out[platform] = {"error": inner.get("message", "not connected")}
            continue
        out[platform] = {k: inner[k] for k in HEADLINE if isinstance(inner.get(k), (int, float))}
    return out


def _load_snapshot(date_str: str) -> dict | None:
    p = SNAPSHOTS / f"{date_str}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _fmt_delta(curr, prev) -> str:
    if prev is None or curr is None:
        return ""
    d = curr - prev
    if d == 0:
        return " (—)"
    sign = "+" if d > 0 else ""
    # Comma-separate thousands
    return f" ({sign}{d:,.0f})" if abs(d) >= 1000 else f" ({sign}{d:.0f})"


def build_report() -> tuple[str, str]:
    """Return (subject, body_plaintext)."""
    now = datetime.now(TZ)
    today_str = now.strftime("%Y-%m-%d")

    curr_snap = _load_snapshot(today_str) or {}
    curr = _flatten(curr_snap)

    # Compare to yesterday's snapshot (note: both are EOD cumulative so delta
    # reflects ~24h, but if we're mid-day the delta is partial. Label clearly.)
    from datetime import timedelta
    yday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    prev_snap = _load_snapshot(yday)
    prev = _flatten(prev_snap) if prev_snap else {}

    lines: list[str] = []
    lines.append(f"🗓  {now.strftime('%a %d %b %H:%M')} Madrid")
    lines.append("")

    order = [("📸 Instagram", "instagram"), ("▶️  YouTube", "youtube"),
             ("🎵 TikTok", "tiktok"), ("𝕏 X", "x")]
    for label, key in order:
        c = curr.get(key, {})
        if "error" in c:
            lines.append(f"{label}: ⚠️  {c['error'][:50]}")
            lines.append("")
            continue
        p = prev.get(key, {})
        lines.append(f"{label}")
        for k in ("followers", "views", "impressions", "likes"):
            if k in c:
                v = c[k]
                delta = _fmt_delta(v, p.get(k))
                lines.append(f"  {k:13} {v:>8,.0f}{delta}")
        if key == "instagram" and "profileViews" in c:
            v = c["profileViews"]
            lines.append(f"  profileViews  {v:>8,.0f}{_fmt_delta(v, p.get('profileViews'))}")
        lines.append("")

    # Scheduled state (queue depth)
    sched = curr_snap.get("scheduled", {})
    if isinstance(sched, dict):
        posts = sched.get("scheduled_posts", [])
        fc = [s for s in posts if s.get("profile_username") == "FCCore-23"]
        lines.append(f"📅 Cola: {len(fc)} slots programados")

    # Highlights — detect notable changes
    highlights: list[str] = []
    for key in ("instagram", "youtube", "tiktok"):
        c = curr.get(key, {})
        p = prev.get(key, {})
        if not c or "error" in c:
            continue
        df = c.get("followers", 0) - p.get("followers", 0)
        dv = c.get("views", c.get("impressions", 0)) - p.get("views", p.get("impressions", 0))
        if df >= 20:
            highlights.append(f"🚀 {key}: +{df} followers")
        if dv >= 5000:
            highlights.append(f"📈 {key}: +{dv:,.0f} views")
    if highlights:
        lines.append("")
        lines.append("━━━ DESTACADO ━━━")
        lines.extend(highlights)

    # YT monetization countdown
    yt_followers = curr.get("youtube", {}).get("followers", 0)
    if yt_followers:
        to_500 = max(0, 500 - yt_followers)
        lines.append("")
        lines.append(f"🎯 YT → 500 subs: faltan {to_500}")

    body = "\n".join(lines)
    subject = f"FC Core — {now.strftime('%d/%m %H:%M')}"
    return subject, body


def send_email(subject: str, body: str) -> bool:
    cfg = load_config()
    email_cfg = cfg.get("email") or {}
    sender = email_cfg.get("sender")
    password = (email_cfg.get("password") or "").replace(" ", "")
    to = email_cfg.get("to")
    if not (sender and password and to):
        logger.error("Missing email config. Add [email] block to config.toml")
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as s:
            s.login(sender, password)
            s.send_message(msg)
        logger.info(f"Email sent to {to}: {subject!r}")
        return True
    except Exception as e:
        logger.error(f"Email failed: {e}")
        return False


def main():
    try:
        pull()
    except Exception as e:
        logger.warning(f"Pull failed (continuing with latest cached snapshot): {e}")
    subject, body = build_report()
    ok = send_email(subject, body)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
