"""
Football core library CLI — manage your segment library.

Commands:
    add URL1 [URL2 URL3 ...]      Download + split + add to library
    hunt [per_account] [max]      Auto-discover + validate + ingest
    stats                         Show library stats
    list                          List all segments
    mix [duration]                Generate a single mix (default 50s)
    post                          Generate BOTH versions (45s TikTok + 75s Shorts/Reels)
    show POST_ID                  Print captions for copy-paste + open video folder
    publish POST_ID               Auto-publish to YouTube + Instagram + X via Upload-Post
    tiktok-post POST_ID           Upload TikTok version via Selenium (warm-up period)
    clear                         Remove everything

Examples:
    python scripts/library.py add https://vm.tiktok.com/ZNR...
    python scripts/library.py hunt            # default: 10 per account, validate up to 20
    python scripts/library.py hunt 5 10       # 5 per account, validate up to 10
    python scripts/library.py mix 45
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from src.library import SegmentLibrary

console = Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(console=console, show_time=False, show_path=False)],
)
logging.getLogger("httpx").setLevel(logging.WARNING)


def cmd_add(urls: list[str]):
    lib = SegmentLibrary()
    for url in urls:
        console.print(f"\n[cyan]Adding:[/cyan] {url}")
        meta = lib.add_source(url)
        if meta.get("status") == "ok":
            console.print(f"  [green]✓[/green] {meta['segment_count']} segments added")
        else:
            console.print(f"  [red]✗[/red] {meta.get('status', 'failed')}")

    cmd_stats()


def cmd_stats():
    lib = SegmentLibrary()
    stats = lib.stats()
    console.print("\n[bold]Library stats:[/bold]")
    console.print(f"  Sources:   {stats['sources']}")
    console.print(f"  Segments:  {stats['segments']}")
    console.print(f"  Duration:  {stats['total_duration_minutes']} min")


def cmd_list():
    lib = SegmentLibrary()
    segments = lib.list_segments()
    if not segments:
        console.print("[yellow]Library is empty[/yellow]")
        return

    from src.utils.video_utils import get_video_info

    table = Table(title=f"Library ({len(segments)} segments)")
    table.add_column("Segment", style="cyan")
    table.add_column("Duration", justify="right")
    table.add_column("Source", style="dim")

    for seg in segments:
        try:
            dur = get_video_info(seg)["duration"]
            source = "_".join(seg.stem.split("_")[:-1])
            table.add_row(seg.name, f"{dur:.1f}s", source)
        except Exception:
            pass

    console.print(table)


def cmd_mix(duration: float = 50, skip_qa: bool = False):
    lib = SegmentLibrary()
    console.print(f"\n[cyan]Generating mix ({duration}s target)...[/cyan]")
    output = lib.generate_mix(target_duration=duration)
    console.print(f"\n[green]✓ Done:[/green] {output}")
    console.print(f"  [dim]open {output}[/dim]")

    if not skip_qa:
        console.print("\n[cyan]Running QA review...[/cyan]")
        from src.services.vision_qa import VisionQA
        qa = VisionQA()
        report = qa.review(output)

        quality_color = {"good": "green", "okay": "yellow", "bad": "red"}.get(
            report.overall_quality, "white"
        )
        console.print(f"\n[bold]Quality:[/bold] [{quality_color}]{report.overall_quality.upper()}[/{quality_color}]")
        console.print(f"[bold]Summary:[/bold] {report.summary}")

        if report.issues:
            console.print(f"\n[bold]Issues found ({len(report.issues)}):[/bold]")
            for issue in report.issues:
                color = "red" if issue.type in ("FROZEN", "CORRUPT", "BLACK") else "yellow"
                console.print(
                    f"  [{color}]• {issue.type}[/{color}] @ {issue.timestamp:.1f}s — {issue.description}"
                )
        else:
            console.print("\n[green]No issues found[/green]")


def cmd_hunt(per_account: int = 10, max_validate: int = 20, min_views: int = 5000):
    lib = SegmentLibrary()
    console.print(f"\n[cyan]Hunting candidates — {per_account}/account, max {max_validate} to validate...[/cyan]")
    stats = lib.hunt(per_account=per_account, max_to_validate=max_validate, min_views=min_views)

    console.print("\n[bold]Hunt results:[/bold]")
    console.print(f"  Candidates found:      {stats['candidates']}")
    console.print(f"  New (not in library):  {stats['new_candidates']}")
    console.print(f"  Validated by Claude:   {stats['validated']}")
    console.print(f"  [green]Accepted:              {stats['accepted']}[/green]")
    console.print(f"  [red]Rejected:              {stats['rejected']}[/red]")
    console.print(f"  [bold green]Added to library:      {stats['added']}[/bold green]")

    if stats["decisions"]:
        console.print("\n[bold]Claude's decisions:[/bold]")
        table = Table()
        table.add_column("Account", style="cyan")
        table.add_column("Views", justify="right")
        table.add_column("Verdict")
        table.add_column("Reason", style="dim")
        for d in stats["decisions"]:
            if d.get("valid") is None:
                verdict = "[yellow]?[/yellow]"
            elif d["valid"]:
                verdict = "[green]✓[/green]"
            else:
                verdict = "[red]✗[/red]"
            table.add_row(
                d.get("account", "?"),
                f"{d.get('views', 0):,}",
                verdict,
                d.get("reason", ""),
            )
        console.print(table)

    cmd_stats()


def cmd_post(skip_qa: bool = False):
    lib = SegmentLibrary()
    console.print("\n[cyan]Generating post (TikTok 45s + Long 75s versions)...[/cyan]")
    manifest = lib.generate_post()

    console.print(f"\n[green]✓ Post ready:[/green] {manifest['post_id']}")
    console.print(f"  TikTok:  {manifest['tiktok']['duration_seconds']}s — {manifest['tiktok']['path']}")
    console.print(f"  Long:    {manifest['long']['duration_seconds']}s — {manifest['long']['path']}")

    if skip_qa:
        return

    from pathlib import Path
    from src.services.vision_qa import VisionQA
    from src.utils.config import project_root

    console.print("\n[cyan]Running Claude Vision QA on TikTok version...[/cyan]")
    video = project_root() / "data" / "outputs" / manifest["post_id"] / "tiktok_45s.mp4"
    qa = VisionQA()
    report = qa.review(video)

    color = {"good": "green", "okay": "yellow", "bad": "red"}.get(report.overall_quality, "white")
    console.print(f"  Quality: [{color}]{report.overall_quality.upper()}[/{color}]  — {report.summary}")
    real_issues = [i for i in report.issues if i.type in ("FROZEN", "CORRUPT")]
    for issue in report.issues:
        c = "red" if issue.type in ("FROZEN", "CORRUPT") else "yellow"
        console.print(f"    [{c}]• {issue.type}[/{c}] @ {issue.timestamp:.1f}s — {issue.description}")
    if report.overall_quality == "bad" or real_issues:
        console.print("\n[red]⚠ Post con issues graves — revisar antes de publicar[/red]")
    elif not report.issues:
        console.print("[green]✓ Sin issues[/green]")


def cmd_show(post_id: str):
    """Display a post's captions formatted for easy copy-paste to Buffer."""
    import json
    import subprocess
    from src.utils.config import project_root

    manifest_path = project_root() / "data" / "outputs" / post_id / "manifest.json"
    if not manifest_path.exists():
        console.print(f"[red]Manifest not found: {manifest_path}[/red]")
        return

    manifest = json.loads(manifest_path.read_text())
    post_dir = manifest_path.parent

    console.print(f"\n[bold cyan]Post {post_id}[/bold cyan]")
    console.print(f"[dim]Folder: {post_dir}[/dim]\n")

    # TikTok
    console.print("[bold magenta]═══ TIKTOK ═══[/bold magenta]")
    console.print(f"[dim]Video: {post_dir / 'tiktok_45s.mp4'}  ({manifest['tiktok']['duration_seconds']}s)[/dim]")
    console.print("[bold]Caption:[/bold]")
    caption = manifest["tiktok"]["caption"] + "\n\n" + " ".join(f"#{h}" for h in manifest["tiktok"]["hashtags"])
    console.print(caption)

    # YouTube
    console.print("\n[bold red]═══ YOUTUBE SHORTS ═══[/bold red]")
    console.print(f"[dim]Video: {post_dir / 'long_75s.mp4'}  ({manifest['long']['duration_seconds']}s)[/dim]")
    console.print(f"[bold]Title:[/bold] {manifest['youtube']['title']}")
    console.print("[bold]Description:[/bold]")
    yt_desc = manifest["youtube"]["description"] + "\n\n" + " ".join(f"#{h}" for h in manifest["youtube"]["hashtags"]) + " #Shorts"
    console.print(yt_desc)

    # Instagram
    console.print("\n[bold yellow]═══ INSTAGRAM REELS ═══[/bold yellow]")
    console.print(f"[dim]Video: {post_dir / 'long_75s.mp4'}  ({manifest['long']['duration_seconds']}s)[/dim]")
    console.print("[bold]Caption:[/bold]")
    ig_caption = manifest["instagram"]["caption"] + "\n\n" + " ".join(f"#{h}" for h in manifest["instagram"]["hashtags"])
    console.print(ig_caption)

    # Open the folder in Finder so videos are easy to drag
    console.print("\n[green]Opening folder in Finder...[/green]")
    subprocess.run(["open", str(post_dir)])


def cmd_publish(post_id: str, platforms: list[str] | None = None):
    """Publish to enabled platforms via Upload-Post (cloud, no browser needed)."""
    from src.utils.config import project_root

    manifest_path = project_root() / "data" / "outputs" / post_id / "manifest.json"
    if not manifest_path.exists():
        console.print(f"[red]Manifest not found: {manifest_path}[/red]")
        console.print("Run [cyan]post[/cyan] first to generate a post.")
        return

    target = ", ".join(platforms) if platforms else "all enabled platforms"
    console.print(f"\n[cyan]Publishing {post_id} via Upload-Post ({target})...[/cyan]")
    try:
        from src.services.uploadpost_publisher import UploadPostPublisher
        publisher = UploadPostPublisher()
        if platforms:
            publisher._enabled = set(platforms)
        results = publisher.publish_post(manifest_path)
        for r in results:
            if r.success:
                pid = f" (id={r.post_id})" if r.post_id else ""
                console.print(f"  [green]✓[/green] {r.platform}: uploaded{pid}")
            else:
                console.print(f"  [red]✗[/red] {r.platform}: {r.error}")
    except ValueError as e:
        console.print(f"[red]Upload-Post: {e}[/red]")


def cmd_tiktok_post(post_id: str):
    """Upload tiktok_45s.mp4 to TikTok using Selenium (warm-up period)."""
    from src.utils.config import project_root

    manifest_path = project_root() / "data" / "outputs" / post_id / "manifest.json"
    if not manifest_path.exists():
        console.print(f"[red]Manifest not found: {manifest_path}[/red]")
        console.print("Run [cyan]post[/cyan] first to generate a post.")
        return

    console.print(f"\n[cyan]Uploading {post_id} to TikTok via Selenium...[/cyan]")
    try:
        from src.services.tiktok_selenium_publisher import TikTokSeleniumPublisher
        publisher = TikTokSeleniumPublisher()
        ok = publisher.publish_post(manifest_path)
        if ok:
            console.print("  [green]✓[/green] TikTok: uploaded")
        else:
            console.print("  [red]✗[/red] TikTok: upload failed — check the browser window")
    except ImportError:
        console.print("[red]Faltan dependencias. Ejecuta:[/red]")
        console.print("  pip install selenium undetected-chromedriver")


def cmd_clear():
    import shutil
    from src.utils.config import project_root

    lib_dir = project_root() / "data" / "library"
    if lib_dir.exists():
        shutil.rmtree(lib_dir)
    console.print("[green]Library cleared[/green]")


def main():
    if len(sys.argv) < 2:
        console.print(__doc__)
        return

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "add":
        if not args:
            console.print("[red]Error: provide at least one URL[/red]")
            return
        cmd_add(args)
    elif cmd == "hunt":
        per_account = int(args[0]) if len(args) > 0 else 10
        max_validate = int(args[1]) if len(args) > 1 else 20
        cmd_hunt(per_account, max_validate)
    elif cmd == "stats":
        cmd_stats()
    elif cmd == "list":
        cmd_list()
    elif cmd == "mix":
        duration = float(args[0]) if args else 50
        cmd_mix(duration)
    elif cmd == "post":
        cmd_post()
    elif cmd == "show":
        if not args:
            console.print("[red]Usage: show POST_ID[/red]")
            return
        cmd_show(args[0])
    elif cmd == "publish":
        if not args:
            console.print("[red]Usage: publish POST_ID [platform1 platform2 ...][/red]")
            return
        platforms = args[1:] if len(args) > 1 else None
        cmd_publish(args[0], platforms=platforms)
    elif cmd == "tiktok-post":
        if not args:
            console.print("[red]Usage: tiktok-post POST_ID[/red]")
            return
        cmd_tiktok_post(args[0])
    elif cmd == "clear":
        cmd_clear()
    else:
        console.print(f"[red]Unknown command: {cmd}[/red]")
        console.print(__doc__)


if __name__ == "__main__":
    main()
