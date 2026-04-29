"""
Schedule N posts in advance on Upload-Post servers.

Generates N unique posts and programs each for a future slot.

Usage:
    python scripts/schedule_batch.py 7                               # 7 posts, 10:00+18:00, todas plataformas
    python scripts/schedule_batch.py 14 --start 2h                   # first slot 2h from now
    python scripts/schedule_batch.py 14 --platforms instagram --slots 14,22  # IG extra 14:00+22:00
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console

from src.library import SegmentLibrary

console = Console()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

# Daily slots (local time — CET/Madrid) — default
DEFAULT_DAILY_SLOTS = [(10, 0), (18, 0)]   # 10:00 and 18:00


def compute_slots(
    count: int,
    start_offset_hours: float = 0,
    daily_slots: list[tuple[int, int]] | None = None,
) -> list[datetime]:
    """Return list of N future datetimes at the configured daily slots (Madrid tz)."""
    tz = ZoneInfo("Europe/Madrid")
    now = datetime.now(tz) + timedelta(hours=start_offset_hours)
    slots_def = daily_slots or DEFAULT_DAILY_SLOTS

    slots: list[datetime] = []
    day = now.date()
    while len(slots) < count:
        for hour, minute in slots_def:
            candidate = datetime.combine(day, datetime.min.time()).replace(
                hour=hour, minute=minute, tzinfo=tz
            )
            if candidate > now + timedelta(minutes=10):
                slots.append(candidate)
                if len(slots) >= count:
                    break
        day += timedelta(days=1)
    return slots


def main():
    parser = argparse.ArgumentParser(description="Schedule N future posts via Upload-Post")
    parser.add_argument("count", type=int, help="Number of posts to generate + schedule")
    parser.add_argument("--start", type=str, default="0h", help="Offset from now (e.g. '2h', '30m')")
    parser.add_argument("--platforms", type=str, default=None,
                        help="Comma-separated platforms override (e.g. 'instagram' or 'youtube,x')")
    parser.add_argument("--slots", type=str, default=None,
                        help="Comma-separated daily hours (e.g. '10,18' or '10,14,18,22')")
    args = parser.parse_args()

    platforms_override = [p.strip() for p in args.platforms.split(",")] if args.platforms else None
    daily_slots = None
    if args.slots:
        daily_slots = [(int(h.strip()), 0) for h in args.slots.split(",")]

    # Parse start offset
    offset_hours = 0
    if args.start.endswith("h"):
        offset_hours = float(args.start[:-1])
    elif args.start.endswith("m"):
        offset_hours = float(args.start[:-1]) / 60

    slots = compute_slots(args.count, offset_hours, daily_slots)
    target = ",".join(platforms_override) if platforms_override else "all enabled"
    console.print(f"\n[bold cyan]Scheduling {args.count} posts ({target}):[/bold cyan]")
    for slot in slots:
        console.print(f"  • {slot.strftime('%a %d %b %H:%M %Z')}")

    lib = SegmentLibrary()

    from src.services.uploadpost_publisher import UploadPostPublisher
    publisher = UploadPostPublisher()
    if platforms_override:
        publisher._enabled = set(platforms_override)

    for i, slot in enumerate(slots, 1):
        console.print(f"\n[bold]━━━ Post {i}/{args.count} — {slot.strftime('%d %b %H:%M')} ━━━[/bold]")

        # Generate a fresh post (new segments, new captions each time)
        console.print("[cyan]Generating post...[/cyan]")
        manifest = lib.generate_post()
        post_id = manifest["post_id"]
        console.print(f"  post_id: {post_id}")

        # Schedule it
        manifest_path = Path("data") / "outputs" / post_id / "manifest.json"
        scheduled_date_iso = slot.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")

        console.print(f"[cyan]Scheduling on Upload-Post servers for {slot.strftime('%H:%M')}...[/cyan]")
        results = publisher.publish_post(
            manifest_path,
            scheduled_date=scheduled_date_iso,
            timezone="Europe/Madrid",
        )
        for r in results:
            if r.success:
                console.print(f"  [green]✓[/green] {r.platform}: scheduled (id={r.post_id})")
            else:
                console.print(f"  [red]✗[/red] {r.platform}: {r.error}")

    console.print(f"\n[bold green]✓ Done. {args.count} posts scheduled. Your Mac can now be off.[/bold green]")


if __name__ == "__main__":
    main()
