"""
`zg scan` command — Full project scan.

Parses manifests in the target directory, probes the OS state,
runs conflict detection, and renders a comprehensive report.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from zerogravity.ui.console import console, print_banner, print_error, print_info, print_section

EXCLUDED_DIR_NAMES = {
    "node_modules", "dist", "build", "target", "out",
    "__pycache__", "site-packages", ".git", ".hg", ".svn",
    ".venv", "venv", "env", ".env", ".tox", ".mypy_cache",
    ".pytest_cache", ".next", ".cache", ".nuxt",
}


def _iter_scan_dirs(root: Path):
    """
    Yield root and every subdirectory worth checking for a manifest,
    pruning vendor/build/VCS directories instead of descending into them.
    Skipping node_modules etc. up front (rather than filtering results
    after the fact) keeps --recursive from treating every installed
    package as its own "project".
    """
    yield root
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            children = [c for c in current.iterdir() if c.is_dir()]
        except (PermissionError, OSError):
            continue
        for child in children:
            if child.name in EXCLUDED_DIR_NAMES or child.name.startswith("."):
                continue
            yield child
            stack.append(child)


def scan_command(
    paths: Optional[list[str]] = typer.Argument(
        None,
        help="Project directories to scan. Defaults to current directory.",
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
    heal: bool = typer.Option(
        False,
        "--heal",
        help="Run self-healing after scan.",
    ),
    no_history: bool = typer.Option(
        False,
        "--no-history",
        help="Bypass historical cross-project checks.",
    ),
    recursive: bool = typer.Option(
        False,
        "--recursive",
        "-r",
        help="Search for all subdirectories containing manifest files.",
    ),
) -> None:
    """
    Scan project directories for dependency conflicts, missing binaries,
    and environment mismatches.
    """
    from zerogravity.parsers.registry import detect_and_parse
    from zerogravity.resolver.conflict_detector import detect_conflicts
    from zerogravity.resolver.models import SystemSnapshot
    from zerogravity.scanner.binary_scanner import run_scan_sync
    from zerogravity.scanner.env_scanner import get_platform_info
    from zerogravity.scanner.version_manager import detect_all_managers_sync
    from zerogravity.ui.renderers import (
        render_conflict_report,
        render_project_manifest,
        render_system_snapshot,
    )

    project_paths = [Path(p).resolve() for p in paths] if paths else [Path.cwd()]

    for project_path in project_paths:
        if not project_path.is_dir():
            print_error(f"Not a directory: {project_path}")
            raise typer.Exit(code=1)

    print_banner()

    # ── Step 1: Parse project manifests ──────────────────────────────────
    manifests = []
    with console.status("[zg.accent]Parsing project manifests...[/]", spinner="dots"):
        for project_path in project_paths:
            if recursive:
                for sub_path in _iter_scan_dirs(project_path):
                    sub_manifests = detect_and_parse(sub_path)
                    if sub_manifests:
                        manifests.extend(sub_manifests)
            else:
                project_manifests = detect_and_parse(project_path)
                if project_manifests:
                    manifests.extend(project_manifests)

        # Remove duplicates
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
        report = detect_conflicts(manifests, snapshot, include_history=not no_history)

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

    if heal:
        from zerogravity.commands.heal import heal_command
        # If multiple paths, we just heal the first one or we'd need to change heal command
        heal_command(path=str(project_paths[0]) if project_paths else None, auto_approve=False)
