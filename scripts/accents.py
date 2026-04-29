"""
CLI for the accents niche (@funny.jokes.23).

Usage:
    python3 scripts/accents.py split        # Split all sources into clips
    python3 scripts/accents.py stats        # Show library stats
    python3 scripts/accents.py post         # Generate one compilation post
    python3 scripts/accents.py publish POST_ID       # Publish now (all enabled platforms)
    python3 scripts/accents.py schedule N   # Generate + schedule N posts on Upload-Post
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tomli
from rich.console import Console
from rich.table import Table

from src.niches.accents.compiler import generate_post
from src.niches.accents.metadata import AccentsMetadataGenerator
from src.niches.accents.splitter import split_all

console = Console()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "niches" / "accents.toml"


def _load_niche_config() -> dict:
    return tomli.loads(CONFIG_PATH.read_text())


def cmd_split():
    cfg = _load_niche_config()
    sources = ROOT / cfg["sources_dir"]
    segments = ROOT / cfg["segments_dir"]
    result = split_all(
        sources, segments,
        min_clip_duration=cfg["min_clip_duration"],
        max_clip_duration=cfg["max_clip_duration"],
    )
    total = sum(len(v) for v in result.values())
    console.print(f"[green]✓[/green] Split {len(result)} sources into {total} clips")


def cmd_stats():
    cfg = _load_niche_config()
    sources = ROOT / cfg["sources_dir"]
    segments = ROOT / cfg["segments_dir"]
    outputs = ROOT / cfg["outputs_dir"]

    n_src = len(list(sources.glob("*.mp4")))
    n_seg = len(list(segments.glob("*.mp4")))
    n_out = len([p for p in outputs.iterdir() if p.is_dir()]) if outputs.exists() else 0

    t = Table(title="Accents niche — library stats")
    t.add_column("Metric")
    t.add_column("Count", justify="right")
    t.add_row("Sources (originals)", str(n_src))
    t.add_row("Segments (clips)", str(n_seg))
    t.add_row("Posts generated", str(n_out))
    console.print(t)


def cmd_post():
    cfg = _load_niche_config()
    segments = ROOT / cfg["segments_dir"]
    outputs = ROOT / cfg["outputs_dir"]

    if len(list(segments.glob("*.mp4"))) < cfg["clips_per_post"]:
        console.print(f"[red]✗[/red] Not enough clips. Run: python3 scripts/accents.py split")
        sys.exit(1)

    manifest = generate_post(
        segments, outputs,
        clips_per_post=cfg["clips_per_post"],
        target_total=cfg["target_total_duration"],
    )
    console.print(f"[cyan]Generating captions...[/cyan]")
    md = AccentsMetadataGenerator().generate()
    manifest["metadata"] = md.to_dict()
    post_dir = outputs / manifest["post_id"]
    (post_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    console.print(f"[green]✓[/green] Post generated: {manifest['post_id']}")
    console.print(f"  duration: {manifest['duration']:.1f}s — {len(manifest['clips'])} clips")
    console.print(f"  IG caption: [yellow]{md.instagram_caption}[/yellow]")
    console.print(f"  TT caption: [yellow]{md.tiktok_caption}[/yellow]")
    console.print(f"  video: {post_dir / 'video.mp4'}")


def cmd_publish(post_id: str, platforms_override: list[str] | None = None):
    cfg = _load_niche_config()
    outputs = ROOT / cfg["outputs_dir"]
    post_dir = outputs / post_id
    manifest_path = post_dir / "manifest.json"
    if not manifest_path.exists():
        console.print(f"[red]✗[/red] Post not found: {post_id}")
        sys.exit(1)

    from src.services.uploadpost_publisher import UploadPostPublisher
    publisher = UploadPostPublisher()
    # Override profile to the niche's Upload-Post username
    publisher._username = cfg["upload_post_username"]
    platforms = platforms_override or cfg["platforms"]
    publisher._enabled = set(platforms)

    # The publisher expects a manifest with "video_path"; we have it relative to ROOT
    console.print(f"[cyan]Publishing {post_id} to {', '.join(platforms)} "
                  f"as @{cfg['handle']}...[/cyan]")
    results = publisher.publish_post(manifest_path)
    for r in results:
        if r.success:
            console.print(f"  [green]✓[/green] {r.platform}: posted (id={r.post_id})")
        else:
            console.print(f"  [red]✗[/red] {r.platform}: {r.error}")


def cmd_schedule(count: int, start_offset_hours: float = 0.0):
    cfg = _load_niche_config()
    outputs = ROOT / cfg["outputs_dir"]
    tz = ZoneInfo("Europe/Madrid")

    # Compute slots
    slot_defs = [tuple(s) for s in cfg["daily_slots"]]
    now = datetime.now(tz) + timedelta(hours=start_offset_hours)
    slots: list[datetime] = []
    day = now.date()
    while len(slots) < count:
        for hour, minute in slot_defs:
            candidate = datetime.combine(day, datetime.min.time()).replace(
                hour=hour, minute=minute, tzinfo=tz
            )
            if candidate > now + timedelta(minutes=10):
                slots.append(candidate)
                if len(slots) >= count:
                    break
        day += timedelta(days=1)

    console.print(f"\n[bold cyan]Scheduling {count} posts as @{cfg['handle']} "
                  f"({', '.join(cfg['platforms'])}):[/bold cyan]")
    for slot in slots:
        console.print(f"  • {slot.strftime('%a %d %b %H:%M %Z')}")

    from src.services.uploadpost_publisher import UploadPostPublisher
    publisher = UploadPostPublisher()
    publisher._username = cfg["upload_post_username"]
    publisher._enabled = set(cfg["platforms"])

    for i, slot in enumerate(slots, 1):
        console.print(f"\n[bold]━━━ Post {i}/{count} — {slot.strftime('%d %b %H:%M')} ━━━[/bold]")
        manifest = generate_post(
            ROOT / cfg["segments_dir"], outputs,
            clips_per_post=cfg["clips_per_post"],
            target_total=cfg["target_total_duration"],
        )
        md = AccentsMetadataGenerator().generate()
        manifest["metadata"] = md.to_dict()
        post_dir = outputs / manifest["post_id"]
        (post_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        console.print(f"  post_id: {manifest['post_id']} — IG: [yellow]{md.instagram_caption}[/yellow]")

        scheduled_iso = slot.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
        results = publisher.publish_post(
            post_dir / "manifest.json",
            scheduled_date=scheduled_iso,
            timezone="Europe/Madrid",
        )
        for r in results:
            status = "[green]✓[/green]" if r.success else "[red]✗[/red]"
            detail = f"id={r.post_id}" if r.success else r.error
            console.print(f"  {status} {r.platform}: {detail}")

    console.print(f"\n[bold green]✓ Done. {count} posts scheduled.[/bold green]")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("split")
    sub.add_parser("stats")
    sub.add_parser("post")

    pub = sub.add_parser("publish")
    pub.add_argument("post_id")
    pub.add_argument("platforms", nargs="*", default=None)

    sch = sub.add_parser("schedule")
    sch.add_argument("count", type=int)
    sch.add_argument("--start", type=str, default="0h")

    args = ap.parse_args()
    if args.cmd == "split":
        cmd_split()
    elif args.cmd == "stats":
        cmd_stats()
    elif args.cmd == "post":
        cmd_post()
    elif args.cmd == "publish":
        cmd_publish(args.post_id, args.platforms or None)
    elif args.cmd == "schedule":
        offset = float(args.start[:-1]) if args.start.endswith("h") else float(args.start[:-1]) / 60
        cmd_schedule(args.count, offset)


if __name__ == "__main__":
    main()
