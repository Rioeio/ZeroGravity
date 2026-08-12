"""
`zg audit` command — OS environment audit.

Probes all system binaries, environment variables, and version managers
without requiring a project directory.
"""

from __future__ import annotations

import typer

from zerogravity.ui.console import console, print_banner


def audit_command(
    output_format: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """
    Audit your system environment — show all detected binaries,
    version managers, and relevant environment variables.
    """
    from zerogravity.scanner.binary_scanner import run_scan_sync
    from zerogravity.scanner.env_scanner import (
        scan_environment,
        get_platform_info,
        scan_path_directories,
    )
    from zerogravity.scanner.version_manager import detect_all_managers_sync
    from zerogravity.resolver.models import SystemSnapshot
    from zerogravity.ui.renderers import render_system_snapshot
    from zerogravity.ui.console import print_section

    print_banner()

    # ── Probe binaries ───────────────────────────────────────────────────
    with console.status("[zg.accent]Probing system binaries...[/]", spinner="dots"):
        binaries = run_scan_sync()

    # ── Scan environment ─────────────────────────────────────────────────
    with console.status("[zg.accent]Scanning environment...[/]", spinner="dots"):
        env_vars = scan_environment()
        platform_info = get_platform_info()
        version_managers = detect_all_managers_sync()

    snapshot = SystemSnapshot(
        binaries=binaries,
        env_vars=env_vars,
        platform=platform_info,
        version_managers=version_managers,
    )

    # ── Render ───────────────────────────────────────────────────────────
    render_system_snapshot(snapshot)

    # ── Environment variables panel ──────────────────────────────────────
    if env_vars:
        print_section("Environment Variables")
        from rich.table import Table
        from rich import box

        env_table = Table(
            box=box.SIMPLE,
            header_style="bold #b388ff",
            border_style="#455a64",
        )
        env_table.add_column("Variable", style="zg.label", min_width=18)
        env_table.add_column("Value", style="zg.dim", max_width=70, overflow="ellipsis")

        for var, val in sorted(env_vars.items()):
            env_table.add_row(var, val)

        console.print(env_table)

    # ── PATH directories ─────────────────────────────────────────────────
    with console.status("[zg.accent]Validating PATH directories...[/]", spinner="dots"):
        path_dirs = scan_path_directories()

    print_section("PATH Directories")
    valid_count = len(path_dirs)
    console.print(f"[zg.dim]  {valid_count} valid directories in PATH[/]")

    # ── JSON output ──────────────────────────────────────────────────────
    if output_format == "json":
        import json
        result = {
            "binaries": {
                name: {
                    "installed": p.installed,
                    "version": p.version,
                    "path": p.path,
                    "error": p.error,
                }
                for name, p in binaries.items()
            },
            "platform": platform_info,
            "env_vars": env_vars,
            "version_managers": {
                name: {
                    "detected": vm.detected,
                    "active_version": vm.active_version,
                    "installed_versions": vm.installed_versions,
                }
                for name, vm in version_managers.items()
            },
        }
        console.print_json(json.dumps(result))
