"""
`zg status` command — Quick system health dashboard.

Provides a one-glance overview of system health, active dedup links,
and last scan info.
"""

from __future__ import annotations

from zerogravity.ui.console import (
    console,
    print_banner,
    print_section,
)


def status_command() -> None:
    """
    Quick system health dashboard — binaries, dedup stats, and environment health.
    """
    from rich import box
    from rich.panel import Panel
    from rich.table import Table

    from zerogravity.scanner.binary_scanner import run_scan_sync
    from zerogravity.scanner.env_scanner import get_platform_info
    from zerogravity.ui.renderers import _format_bytes

    print_banner()
    print_section("System Health Dashboard")

    # ── Quick binary check ───────────────────────────────────────────────
    key_binaries = ["node", "python", "python3", "git", "docker", "npm"]

    with console.status("[zg.accent]Quick health check...[/]", spinner="dots"):
        binaries = run_scan_sync(binaries=key_binaries)
        platform_info = get_platform_info()

    # Health summary
    installed = sum(1 for b in binaries.values() if b.installed)
    total = len(binaries)
    health_pct = (installed / total * 100) if total > 0 else 0

    if health_pct == 100:
        health_color = "zg.ok"
        health_icon = "✅"
    elif health_pct >= 70:
        health_color = "zg.warning"
        health_icon = "⚠️"
    else:
        health_color = "zg.error"
        health_icon = "❌"

    # Platform panel
    os_info = f"{platform_info.get('os_name', '?')} {platform_info.get('os_version', '')}"
    arch = platform_info.get("architecture", "?")
    py_ver = platform_info.get("python_version", "?")

    console.print(
        Panel(
            f"[zg.label]OS:[/] [zg.value]{os_info}[/]  │  "
            f"[zg.label]Arch:[/] [zg.value]{arch}[/]  │  "
            f"[zg.label]Python:[/] [zg.value]{py_ver}[/]  │  "
            f"[{health_color}]{health_icon} {installed}/{total} binaries detected[/]",
            title="[zg.accent]System[/]",
            border_style="#455a64",
            padding=(0, 1),
        )
    )

    # Binary status grid
    table = Table(
        box=box.SIMPLE,
        show_header=False,
        padding=(0, 2),
    )
    table.add_column("Binary", style="zg.package")
    table.add_column("Status")
    table.add_column("Version", style="zg.version")

    for name, probe in sorted(binaries.items()):
        if probe.installed:
            status_text = "[zg.ok]● OK[/]"
        else:
            status_text = "[zg.error]● MISSING[/]"
        table.add_row(name, status_text, probe.version or "—")

    console.print(table)

    # ── Dedup status ─────────────────────────────────────────────────────
    try:
        from zerogravity.dedup.engine import DeduplicationEngine
        engine = DeduplicationEngine()
        dedup_status = engine.get_status()

        print_section("Deduplication Store")
        console.print(
            f"  [zg.label]Packages:[/] [zg.value]{dedup_status.get('total_packages', 0)}[/]  │  "
            f"[zg.label]Links:[/] [zg.value]{dedup_status.get('total_links', 0)}[/]  │  "
            f"[zg.label]Savings:[/] [zg.ok]{_format_bytes(dedup_status.get('estimated_bytes_saved', 0))}[/]"
        )
    except Exception:
        # Dedup engine not yet initialised — that's fine
        pass

    console.print()
