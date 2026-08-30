"""
`zg audit-security` command — OSV.dev vulnerability auditing for project dependencies.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from zerogravity.config import load_config
from zerogravity.parsers.registry import detect_and_parse
from zerogravity.security.scanner import scan_vulnerabilities
from zerogravity.ui.console import console, print_banner, print_error, print_info
from zerogravity.ui.renderers import render_security_report


def security_command(
    paths: Optional[list[str]] = typer.Argument(
        None,
        help="Project directories to audit for security vulnerabilities. Defaults to current directory.",
    ),
    output_format: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format: table (default) or json.",
    ),
    offline: bool = typer.Option(
        False,
        "--offline",
        help="Run in offline mode without querying online OSV database.",
    ),
    recursive: bool = typer.Option(
        False,
        "--recursive",
        "-r",
        help="Search for all subdirectories containing manifest files.",
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Bypass scan-result cache and force full re-parsing.",
    ),
) -> None:
    """
    Audit project dependencies for known security vulnerabilities using OSV.dev database.
    """
    from zerogravity.commands.scan import _iter_scan_dirs

    project_paths = [Path(p).resolve() for p in paths] if paths else [Path.cwd()]

    for project_path in project_paths:
        if not project_path.is_dir():
            print_error(f"Not a directory: {project_path}")
            raise typer.Exit(code=1)

    print_banner()

    config = load_config(project_paths[0] if project_paths else None)

    manifests = []
    with console.status("[zg.accent]Parsing project manifests...[/]", spinner="dots"):
        for project_path in project_paths:
            proj_config = load_config(project_path) if len(project_paths) > 1 else config
            if recursive:
                for sub_path in _iter_scan_dirs(project_path, extra_excludes=proj_config.exclude):
                    sub_manifests = detect_and_parse(sub_path, use_cache=not no_cache)
                    if sub_manifests:
                        manifests.extend(sub_manifests)
            else:
                project_manifests = detect_and_parse(project_path, use_cache=not no_cache)
                if project_manifests:
                    manifests.extend(project_manifests)

        # Deduplicate manifests
        seen = set()
        unique_manifests = []
        for m in manifests:
            if m.project_path not in seen:
                seen.add(m.project_path)
                unique_manifests.append(m)
        manifests = unique_manifests

    if not manifests:
        paths_str = ", ".join(str(p) for p in project_paths)
        print_info(f"No supported manifest files found in {paths_str}")
        return

    with console.status("[zg.accent]Querying OSV.dev vulnerability database...[/]", spinner="dots"):
        report = scan_vulnerabilities(manifests, offline=offline)

    if output_format == "json":
        result = {
            "summary": report.summary,
            "advisories": [
                {
                    "id": a.id,
                    "cve_id": a.cve_id,
                    "package": a.package_name,
                    "installed_version": a.installed_version,
                    "severity": a.severity.value,
                    "summary": a.summary,
                    "ecosystem": a.ecosystem.value,
                    "project_path": str(a.project_path),
                    "project_name": a.project_name,
                }
                for a in report.advisories
            ],
        }
        console.print_json(json.dumps(result))
    else:
        render_security_report(report)
