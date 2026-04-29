"""
Autonomous analysis routine — Claude's eyes on the pipeline.

What it does each run:
1. Load today's snapshot (pulling a fresh one if missing).
2. Diff vs yesterday and 7 days ago.
3. Compute per-platform deltas + top/bottom posts.
4. Append a timestamped entry to data/analytics/agent_journal.md
   so the next Claude session can read "what past-me observed".
5. Update data/analytics/state.json with the latest numbers
   (fast lookup for CLAUDE.md pre-flight read).

Usage:
    python3 scripts/analyze.py            # full cycle
    python3 scripts/analyze.py --pull     # force fresh snapshot
    python3 scripts/analyze.py --report   # print markdown summary to stdout
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
ANALYTICS = ROOT / "data" / "analytics"
SNAPSHOTS = ANALYTICS / "snapshots"
JOURNAL = ANALYTICS / "agent_journal.md"
PLAYBOOK = ANALYTICS / "playbook.md"
STATE = ANALYTICS / "state.json"


def _load_snapshot(date_str: str) -> dict | None:
    p = SNAPSHOTS / f"{date_str}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _today_str() -> str:
    return datetime.now(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d")


HEADLINE_KEYS = (
    "followers", "reach", "views", "impressions", "profileViews",
    "likes", "comments", "shares", "saves",
)


def _extract_headline_numbers(snap: dict) -> dict:
    """Pull a small, comparable set of metrics from whatever the API returned."""
    out: dict = {}
    for platform, payload in snap.get("per_platform", {}).items():
        if not isinstance(payload, dict):
            out[platform] = {"error": "unknown"}
            continue
        if "error" in payload:
            out[platform] = {"error": payload["error"]}
            continue
        # Upload-Post nests data under the platform key: {"instagram": {...}}
        inner = payload.get(platform, payload)
        if isinstance(inner, dict) and inner.get("success") is False:
            out[platform] = {"error": inner.get("message", "not connected")}
            continue
        headline = {k: inner[k] for k in HEADLINE_KEYS if k in inner and isinstance(inner[k], (int, float))}
        out[platform] = headline
    return out


def _delta(cur: dict, prev: dict | None) -> dict:
    if not prev:
        return {}
    d: dict = {}
    for plat, cur_vals in cur.items():
        if not isinstance(cur_vals, dict):
            continue
        prev_vals = prev.get(plat, {}) if isinstance(prev.get(plat), dict) else {}
        plat_delta = {}
        for k, v in cur_vals.items():
            if isinstance(v, (int, float)) and isinstance(prev_vals.get(k), (int, float)):
                plat_delta[k] = v - prev_vals[k]
        if plat_delta:
            d[plat] = plat_delta
    return d


def build_report() -> str:
    today = _today_str()
    snap = _load_snapshot(today)
    if not snap:
        # Try pulling
        from scripts.analytics_pull import pull
        pull()
        snap = _load_snapshot(today)
    if not snap:
        return f"# {today}\nNo snapshot available."

    today_nums = _extract_headline_numbers(snap)

    yesterday = (datetime.now(ZoneInfo("Europe/Madrid")) - timedelta(days=1)).strftime("%Y-%m-%d")
    week_ago = (datetime.now(ZoneInfo("Europe/Madrid")) - timedelta(days=7)).strftime("%Y-%m-%d")
    y_snap = _load_snapshot(yesterday)
    w_snap = _load_snapshot(week_ago)
    y_nums = _extract_headline_numbers(y_snap) if y_snap else None
    w_nums = _extract_headline_numbers(w_snap) if w_snap else None

    d_day = _delta(today_nums, y_nums)
    d_week = _delta(today_nums, w_nums)

    lines = [f"# Analytics report — {today}", ""]
    for plat in ("instagram", "youtube", "x", "tiktok"):
        vals = today_nums.get(plat, {})
        lines.append(f"## {plat}")
        if "error" in vals:
            lines.append(f"- error: `{vals['error']}`")
            lines.append("")
            continue
        if not vals:
            lines.append("- (no data)")
            lines.append("")
            continue
        for k, v in vals.items():
            dd = d_day.get(plat, {}).get(k)
            dw = d_week.get(plat, {}).get(k)
            suffix = []
            if dd is not None:
                suffix.append(f"Δ1d={dd:+g}")
            if dw is not None:
                suffix.append(f"Δ7d={dw:+g}")
            suffix_s = f"  ({', '.join(suffix)})" if suffix else ""
            lines.append(f"- {k}: {v}{suffix_s}")
        lines.append("")

    # Scheduled state
    sched = snap.get("scheduled")
    if isinstance(sched, dict) and "results" in sched:
        n = len(sched.get("results") or [])
        lines.append(f"**Scheduled upcoming:** {n} posts")
        lines.append("")

    return "\n".join(lines)


def _append_journal(report: str):
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    if not JOURNAL.exists():
        JOURNAL.write_text(
            "# Agent journal\n\n"
            "_Persistent memory for Claude across sessions. Each entry is "
            "timestamped. Future-me: read the last 2-3 entries before acting, "
            "update hypotheses in playbook.md when a pattern becomes clear._\n\n"
        )
    sep = "\n\n---\n\n"
    JOURNAL.write_text(JOURNAL.read_text() + sep + report.strip() + "\n")


def _write_state(report_text: str):
    today = _today_str()
    snap = _load_snapshot(today) or {}
    state = {
        "last_analysis": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(),
        "last_snapshot_date": today,
        "headline": _extract_headline_numbers(snap),
        "report_preview": report_text[:2000],
    }
    STATE.write_text(json.dumps(state, indent=2, default=str))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pull", action="store_true", help="Force a fresh snapshot first")
    ap.add_argument("--report", action="store_true", help="Only print report, no journal write")
    args = ap.parse_args()

    if args.pull:
        from scripts.analytics_pull import pull
        pull()

    report = build_report()
    print(report)

    if not args.report:
        _append_journal(report)
        _write_state(report)
        print(f"\n✓ Journal updated: {JOURNAL}")
        print(f"✓ State updated:   {STATE}")


if __name__ == "__main__":
    main()
