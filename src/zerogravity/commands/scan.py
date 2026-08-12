"""
`zg scan` command — Full project scan.

Parses manifests in the target directory, probes the OS state,
runs conflict detection, and renders a comprehensive report.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer

from zerogravity.ui.console import console, print_banner, print_section, print_error, print_info


def scan_command(
    path: Optional[str] = typer.Argument(
        None,
        help="Project directory to scan. Defaults to current directory.",
    ),
    output_format: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format: table (default) or json.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed output including all OK checks.",
    ),
) -> None:
    """
    Scan a project directory for dependency conflicts, missing binaries,
    and environment mismatches.
    """
    from zerogravity.parsers.registry import detect_and_parse
    from zerogravity.scanner.binary_scanner import run_scan_sync
    from zerogravity.scanner.env_scanner import get_platform_info
    from zerogravity.scanner.version_manager import detect_all_managers_sync
    from zerogravity.resolver.models import SystemSnapshot
    from zerogravity.resolver.conflict_detector import detect_conflicts
    from zerogravity.ui.renderers import (
        render_system_snapshot,
        render_conflict_report,
        render_project_manifest,
    )

    project_path = Path(path).resolve() if path else Path.cwd()

    if not project_path.is_dir():
        print_error(f"Not a directory: {project_path}")
        raise typer.Exit(code=1)

    print_banner()

    # ── Step 1: Parse project manifests ──────────────────────────────────
    with console.status("[zg.accent]Parsing project manifests...[/]", spinner="dots"):
        manifests = detect_and_parse(project_path)

    if not manifests:
        print_info(f"No supported manifest files found in {project_path}")
        print_info("Supported: package.json, requirements.txt, pyproject.toml")
    else:
        print_section("Project Manifests")
        for manifest in manifests:
            render_project_manifest(manifest)

    # ── Step 2: Probe OS state ───────────────────────────────────────────
    with console.status("[zg.accent]Scanning system binaries...[/]", spinner="dots"):
        binaries = run_scan_sync()
        platform_info = get_platform_info()
        version_managers = detect_all_managers_sync()

    snapshot = SystemSnapshot(
        binaries=binaries,
        platform=platform_info,
        version_managers=version_managers,
    )

    if verbose:
        render_system_snapshot(snapshot)

    # ── Step 3: Run conflict detection ───────────────────────────────────
    with console.status("[zg.accent]Analyzing conflicts...[/]", spinner="dots"):
        report = detect_conflicts(manifests, snapshot)

    render_conflict_report(report)

    # ── Step 4: JSON output mode ─────────────────────────────────────────
    if output_format == "json":
        import json
        result = {
            "manifests": [
                {
                    "project": str(m.project_path),
                    "ecosystem": m.ecosystem.value,
                    "dependencies": len(m.dependencies),
                    "engine_constraints": m.engine_constraints,
                }
                for m in manifests
            ],
            "issues": [
                {
                    "severity": i.severity.value,
                    "category": i.category.value,
                    "message": i.message,
                    "expected": i.expected,
                    "actual": i.actual,
                    "remediation": i.remediation,
                }
                for i in report.issues
            ],
            "summary": report.summary,
        }
        console.print_json(json.dumps(result))
