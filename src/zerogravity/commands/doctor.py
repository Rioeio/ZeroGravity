"""
`zg doctor` command — Guided diagnostic flow.

Runs audit → scan → conflict detection as one narrative,
then offers to run heal if actionable issues are found.
Composes over the existing detection and healing logic
without introducing any new detection rules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.panel import Panel
from rich.table import Table

from zerogravity.healing.engine import HealingEngine
from zerogravity.ui.console import console, print_banner, print_error, print_info, print_section


def doctor_command(
    path: Optional[str] = typer.Argument(
        None,
        help="Project directory to diagnose. Defaults to current directory.",
    ),
    auto_approve: bool = typer.Option(
        False,
        "--auto-approve",
        "-y",
        help="Automatically approve and execute remediation plans.",
    ),
) -> None:
    """
    Run a full diagnostic: audit your system, scan a project for issues,
    and offer to heal any problems — all in one guided flow.
    """
    from zerogravity.config import load_config
    from zerogravity.parsers.registry import detect_and_parse
    from zerogravity.resolver.conflict_detector import detect_conflicts
    from zerogravity.resolver.models import SystemSnapshot
    from zerogravity.scanner.binary_scanner import run_scan_sync
    from zerogravity.scanner.env_scanner import get_platform_info
    from zerogravity.scanner.version_manager import detect_all_managers_sync
    from zerogravity.ui.renderers import render_system_snapshot

    project_path = Path(path).resolve() if path else Path.cwd()

    if not project_path.is_dir():
        print_error(f"Not a directory: {project_path}")
        raise typer.Exit(code=1)

    print_banner()
    console.print("[zg.accent]Running full diagnostic...[/]\n")

    # ── Step 1: Audit — probe system environment ────────────────────────
    print_section("Step 1/3 — System Audit")

    with console.status("[zg.accent]Probing system binaries & version managers...[/]", spinner="dots"):
        binaries = run_scan_sync()
        platform_info = get_platform_info()
        version_managers = detect_all_managers_sync()

    snapshot = SystemSnapshot(
        binaries=binaries,
        platform=platform_info,
        version_managers=version_managers,
    )

    render_system_snapshot(snapshot)

    installed_count = sum(1 for b in binaries.values() if b.installed)
    total_count = len(binaries)
    console.print(
        f"\n[zg.info]Audit complete:[/] {installed_count}/{total_count} binaries detected."
    )

    # ── Step 2: Scan — parse manifests and detect conflicts ─────────────
    print_section("Step 2/3 — Project Scan")

    config = load_config(project_path)

    with console.status("[zg.accent]Parsing project manifests...[/]", spinner="dots"):
        manifests = detect_and_parse(project_path)

    if not manifests:
        print_info(f"No supported manifest files found in {project_path.name}")
        print_info("Nothing to diagnose. You're all clear!")
        return

    dep_count = sum(len(m.dependencies) for m in manifests)
    ecosystems = {m.ecosystem.value for m in manifests}
    console.print(
        f"[zg.info]Found {len(manifests)} manifest(s) "
        f"({', '.join(e.upper() for e in sorted(ecosystems))}) "
        f"with {dep_count} total dependencies.[/]"
    )

    with console.status("[zg.accent]Analyzing conflicts...[/]", spinner="dots"):
        report = detect_conflicts(manifests, snapshot, config=config)

    # ── Build a narrative summary of findings ───────────────────────────
    critical_issues = [i for i in report.issues if i.severity.priority >= 3]  # ERROR + CRITICAL
    warning_issues = [i for i in report.issues if i.severity.priority == 2]  # WARNING
    info_issues = [i for i in report.issues if i.severity.priority <= 1]  # OK + INFO

    if critical_issues or warning_issues:
        print_section("Findings")

        findings_table = Table(
            box=box.ROUNDED,
            show_header=True,
            header_style="bold #b388ff",
            border_style="#455a64",
        )
        findings_table.add_column("Severity", style="bold", min_width=10)
        findings_table.add_column("Issue", min_width=40)
        findings_table.add_column("Remediation", style="zg.dim", min_width=30)

        for issue in report.sorted_issues:
            if issue.severity.priority <= 1:
                continue
            sev_text = f"[{issue.severity.color}]{issue.severity.icon} {issue.severity.value.upper()}[/]"
            findings_table.add_row(sev_text, issue.message, issue.remediation or "—")

        console.print(findings_table)
    else:
        console.print("\n[zg.ok]✅ No issues found — your project looks healthy![/]")

    summary_parts = []
    if report.critical_count:
        summary_parts.append(f"[zg.critical]{report.critical_count} critical[/]")
    if report.error_count:
        summary_parts.append(f"[zg.error]{report.error_count} error(s)[/]")
    if report.warning_count:
        summary_parts.append(f"[zg.warning]{report.warning_count} warning(s)[/]")
    if info_issues:
        summary_parts.append(f"[zg.info]{len(info_issues)} info[/]")

    console.print(
        f"\n[zg.info]Scan complete:[/] {', '.join(summary_parts) if summary_parts else '[zg.ok]clean[/]'}."
    )

    # ── Step 3: Heal offer ──────────────────────────────────────────────
    print_section("Step 3/3 — Heal")

    engine = HealingEngine()
    plans = engine.plan_remediations(report, snapshot)

    if not plans:
        if critical_issues or warning_issues:
            print_info(
                "Issues were found but no automatic remediation is available. "
                "Follow the remediation hints above."
            )
        else:
            console.print("[zg.ok]✅ Nothing to heal — your environment is in good shape![/]")
        return

    # Show proposed actions
    plan_table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
        border_style="#455a64",
    )
    plan_table.add_column("Manager", style="cyan", min_width=10)
    plan_table.add_column("Command", style="green", min_width=30)
    plan_table.add_column("Description")

    for plan in plans:
        plan_table.add_row(plan.manager_name, " ".join(plan.command), plan.description)

    console.print(
        Panel(
            plan_table,
            title="[bold]Proposed Remediation Actions[/]",
            border_style="blue",
        )
    )

    console.print(
        f"\n[zg.accent]ZeroGravity can automatically fix "
        f"{len(plans)} issue(s) listed above.[/]"
    )

    # Execute
    success_count = 0
    for plan in plans:
        if engine.execute_plan(plan, snapshot, auto_approve=auto_approve):
            console.print(f"[green]✓ Success:[/] {' '.join(plan.command)}")
            success_count += 1
        else:
            console.print(f"[red]✗ Skipped/Failed:[/] {' '.join(plan.command)}")

    console.print(
        f"\n[bold]Doctor complete.[/] {success_count}/{len(plans)} actions succeeded."
    )
