"""
`zg outdated` command — Outdated dependency detection and registry comparison.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from zerogravity.config import ConfigError, load_config
from zerogravity.outdated.checker import check_outdated_dependencies
from zerogravity.parsers.registry import detect_and_parse
from zerogravity.ui.console import console, print_banner, print_error, print_info
from zerogravity.ui.renderers import render_outdated_report


def outdated_command(
    paths: Optional[list[str]] = typer.Argument(
        None,
        help="Project directories to check for outdated dependencies. Defaults to current directory.",
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
        help="Run in offline mode without querying online package registries.",
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
    fail_on_outdated: str = typer.Option(
        "none",
        "--fail-on-outdated",
        help="Fail with exit code 1 if outdated dependencies at or above threshold: none, patch, minor, major.",
    ),
    include_transitive: bool = typer.Option(
        False,
        "--include-transitive",
        help="Include transitive dependencies in outdated check (defaults to direct dependencies only).",
    ),
) -> None:
    """
    Check project dependencies against npm and PyPI registries for available updates.
    """
    from zerogravity.commands.scan import _iter_scan_dirs

    project_paths = [Path(p).resolve() for p in paths] if paths else [Path.cwd()]

    for project_path in project_paths:
        if not project_path.is_dir():
            print_error(f"Not a directory: {project_path}")
            raise typer.Exit(code=1)

    print_banner()

    try:
        config = load_config(project_paths[0] if project_paths else None)
    except ConfigError as err:
        print_error(str(err))
        raise typer.Exit(code=2)

    manifests = []
    with console.status("[zg.accent]Parsing project manifests...[/]", spinner="dots"):
        for project_path in project_paths:
            try:
                proj_config = load_config(project_path) if len(project_paths) > 1 else config
            except ConfigError as err:
                print_error(str(err))
                raise typer.Exit(code=2)
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

    effective_offline = offline or not getattr(config, "network_enabled", True)
    with console.status("[zg.accent]Checking package registries for updates...[/]", spinner="dots"):
        report = check_outdated_dependencies(
            manifests,
            offline=effective_offline,
            include_transitive=include_transitive,
            max_workers=getattr(config, "network_max_workers", 8),
        )

    if output_format == "json":
        result = {
            "complete": getattr(report, "complete", True),
            "errors": getattr(report, "errors", []),
            "unresolved": getattr(report, "unresolved", []),
            "private_skipped": getattr(report, "private_skipped", []),
            "summary": report.summary,
            "packages": [
                {
                    "name": p.name,
                    "current_version": p.current_version,
                    "latest_version": p.latest_version,
                    "update_type": p.update_type.value,
                    "ecosystem": p.ecosystem.value,
                    "project_path": str(p.project_path),
                    "project_name": p.project_name,
                }
                for p in report.packages
            ],
        }
        console.print_json(json.dumps(result))
    else:
        render_outdated_report(report)

    # Evaluate fail-on-outdated threshold and exit code contract
    thresh = fail_on_outdated.lower().strip()
    if thresh not in ("none", "patch", "minor", "major"):
        thresh = "none"

    if thresh != "none" and not getattr(report, "complete", True):
        raise typer.Exit(code=2)

    has_findings = False
    if thresh == "patch":
        has_findings = bool(report.major_count or report.minor_count or report.patch_count)
    elif thresh == "minor":
        has_findings = bool(report.major_count or report.minor_count)
    elif thresh == "major":
        has_findings = bool(report.major_count)

    if has_findings:
        raise typer.Exit(code=1)
