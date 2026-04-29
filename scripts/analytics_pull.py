"""
Pull raw analytics from Upload-Post and store as JSON snapshots.

One snapshot per day — run via launchd at 23:00 local.
Output: data/analytics/snapshots/YYYY-MM-DD.json

This is the *data collection* layer. Analysis lives in analyze.py.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from upload_post import UploadPostClient

from src.utils.config import load_config

SNAPSHOTS = Path(__file__).resolve().parent.parent / "data" / "analytics" / "snapshots"
PLATFORMS = ["instagram", "youtube", "x", "tiktok"]


def pull() -> Path:
    cfg = load_config()
    client = UploadPostClient(api_key=cfg["upload_post"]["api_key"])
    username = cfg["upload_post"]["username"]

    data: dict = {
        "pulled_at": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(),
        "username": username,
        "per_platform": {},
    }

    for p in PLATFORMS:
        try:
            data["per_platform"][p] = client.get_analytics(
                profile_username=username, platforms=[p]
            )
        except Exception as e:
            data["per_platform"][p] = {"error": str(e)}

    # Also save scheduled state
    try:
        data["scheduled"] = client.list_scheduled()
    except Exception as e:
        data["scheduled"] = {"error": str(e)}

    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    today = datetime.now(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d")
    out = SNAPSHOTS / f"{today}.json"
    out.write_text(json.dumps(data, indent=2, default=str))
    print(f"✓ Snapshot saved: {out}")
    return out


if __name__ == "__main__":
    pull()
