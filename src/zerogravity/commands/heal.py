from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.panel import Panel
from rich.table import Table

from zerogravity.ui.console import console, print_banner, print_section, print_error, print_info
from zerogravity.healing.engine import HealingEngine


def heal_command(
    path: Optional[str] = typer.Argument(
        None,
        help="Project directory to heal. Defaults to current directory.",
    ),
    auto_approve: bool = typer.Option(
        False,
        "--auto-approve",
        "-y",
        help="Automatically approve and execute remediation plans.",
    ),
) -> None:
    """
    Scan project and self-heal runtime environment mismatches.
    """
    from zerogravity.parsers.registry import detect_and_parse
    from zerogravity.scanner.binary_scanner import run_scan_sync
    from zerogravity.scanner.env_scanner import get_platform_info
    from zerogravity.scanner.version_manager import detect_all_managers_sync
    from zerogravity.resolver.models import SystemSnapshot
    from zerogravity.resolver.conflict_detector import detect_conflicts
    from zerogravity.ui.renderers import render_conflict_report

    project_path = Path(path).resolve() if path else Path.cwd()

    if not project_path.is_dir():
        print_error(f"Not a directory: {project_path}")
        raise typer.Exit(code=1)

    print_banner()

    with console.status("[zg.accent]Scanning environment...[/]", spinner="dots"):
        manifests = detect_and_parse(project_path)
        binaries = run_scan_sync()
        platform_info = get_platform_info()
        version_managers = detect_all_managers_sync()

    snapshot = SystemSnapshot(
        binaries=binaries,
        platform=platform_info,
        version_managers=version_managers,
    )

    with console.status("[zg.accent]Analyzing conflicts...[/]", spinner="dots"):
        report = detect_conflicts(manifests, snapshot)

    render_conflict_report(report)

    engine = HealingEngine()
    plans = engine.plan_remediations(report, snapshot)

    if not plans:
        print_info("No remediations could be planned.")
        return

    print_section("Remediation Plans")
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Manager", style="cyan")
    table.add_column("Command", style="green")
    table.add_column("Description")

    for plan in plans:
        table.add_row(plan.manager_name, " ".join(plan.command), plan.description)

    console.print(Panel(table, title="Proposed Actions", border_style="blue"))

    success_count = 0
    for plan in plans:
        if engine.execute_plan(plan, snapshot, auto_approve=auto_approve):
            console.print(f"[green]✓ Success:[/] {' '.join(plan.command)}")
            success_count += 1
        else:
            console.print(f"[red]✗ Failed:[/] {' '.join(plan.command)}")

    console.print(f"\n[bold]Heal Complete.[/] {success_count}/{len(plans)} actions succeeded.")
