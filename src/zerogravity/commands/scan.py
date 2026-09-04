"""
`zg scan` command — Full project scan.

Parses manifests in the target directory, probes the OS state,
runs conflict detection, and renders a comprehensive report.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Optional

import typer

from zerogravity.config import load_config
from zerogravity.ui.console import console, print_banner, print_error, print_info, print_section

EXCLUDED_DIR_NAMES = {
    "node_modules", "dist", "build", "target", "out",
    "__pycache__", "site-packages", ".git", ".hg", ".svn",
    ".venv", "venv", "env", ".env", ".tox", ".mypy_cache",
    ".pytest_cache", ".next", ".cache", ".nuxt",
}


def _iter_scan_dirs(root: Path, extra_excludes: list[str] | None = None):
    """
    Yield root and every subdirectory worth checking for a manifest,
    pruning vendor/build/VCS directories and user-configured exclusions
    instead of descending into them.
    """
    custom_excludes = set(extra_excludes or [])
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
            if child.name in custom_excludes:
                continue
            rel_str = child.relative_to(root).as_posix()
            if any(fnmatch.fnmatch(rel_str, pat) or fnmatch.fnmatch(child.name, pat) for pat in custom_excludes):
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
        help="Output format: table (default), json, sarif, or junit.",
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
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Bypass scan-result cache and force full re-parsing.",
    ),
    offline: bool = typer.Option(
        False,
        "--offline",
        help="Run in offline mode without querying online package registries.",
    ),
    check_host_anyway: bool = typer.Option(
        False,
        "--check-host-anyway",
        help="Check host system binaries even for containerized/devcontainer projects.",
    ),
) -> None:
    """
    Scan project directories for dependency conflicts, missing binaries,
    and environment mismatches.
    """
    from zerogravity.formatters.junit import format_junit
    from zerogravity.formatters.sarif import format_sarif
    from zerogravity.outdated.checker import check_outdated_dependencies
    from zerogravity.parsers.registry import detect_and_parse
    from zerogravity.resolver.conflict_detector import detect_conflicts
    from zerogravity.resolver.models import SystemSnapshot
    from zerogravity.scanner.binary_scanner import compute_scoped_binaries, run_scan_sync
    from zerogravity.scanner.env_scanner import get_platform_info
    from zerogravity.scanner.version_manager import detect_all_managers_sync
    from zerogravity.security.scanner import scan_vulnerabilities
    from zerogravity.ui.renderers import (
        render_conflict_report,
        render_outdated_summary,
        render_project_manifest,
        render_security_summary,
        render_system_snapshot,
    )

    project_paths = [Path(p).resolve() for p in paths] if paths else [Path.cwd()]

    for project_path in project_paths:
        if not project_path.is_dir():
            print_error(f"Not a directory: {project_path}")
            raise typer.Exit(code=1)

    if output_format == "table":
        print_banner()

    # Load configuration
    config = load_config(project_paths[0] if project_paths else None)

    # ── Step 1: Parse project manifests ──────────────────────────────────
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

        # Remove duplicates
        seen = set()
        unique_manifests = []
        for m in manifests:
            if m.project_path not in seen:
                seen.add(m.project_path)
                unique_manifests.append(m)
        manifests = unique_manifests

    if not manifests:
        if output_format == "table":
            paths_str = ", ".join(str(p) for p in project_paths)
            print_info(f"No supported manifest files found in {paths_str}")
            print_info("Supported: package.json, requirements.txt, pyproject.toml")
    elif output_format == "table":
        print_section("Project Manifests")
        for manifest in manifests:
            render_project_manifest(manifest)

    # ── Step 2: Probe OS state ───────────────────────────────────────────
    with console.status("[zg.accent]Scanning system binaries...[/]", spinner="dots"):
        scoped_binaries = compute_scoped_binaries(
            manifests,
            custom_map=config.binary_map if config else None,
        )
        binaries = run_scan_sync(binaries=scoped_binaries)
        platform_info = get_platform_info()
        version_managers = detect_all_managers_sync()

    snapshot = SystemSnapshot(
        binaries=binaries,
        platform=platform_info,
        version_managers=version_managers,
    )

    if verbose and output_format == "table":
        render_system_snapshot(snapshot)

    # ── Step 3: Run conflict detection ───────────────────────────────────
    with console.status("[zg.accent]Analyzing conflicts...[/]", spinner="dots"):
        report = detect_conflicts(
            manifests,
            snapshot,
            include_history=not no_history,
            config=config,
            check_host_anyway=check_host_anyway,
        )

    if output_format == "table":
        render_conflict_report(report)

    # ── Step 4: Check outdated dependencies ──────────────────────────────
    outdated_report = None
    if manifests:
        with console.status("[zg.accent]Checking package registries for updates...[/]", spinner="dots"):
            outdated_report = check_outdated_dependencies(manifests, offline=offline)
        if output_format == "table":
            render_outdated_summary(outdated_report)

    # ── Step 5: Check security vulnerabilities ───────────────────────────
    security_report = None
    if manifests:
        with console.status("[zg.accent]Querying OSV.dev vulnerability database...[/]", spinner="dots"):
            security_report = scan_vulnerabilities(manifests, offline=offline)
        if output_format == "table":
            render_security_summary(security_report)

    # ── Step 6: Output formatting ────────────────────────────────────────
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
            "outdated": outdated_report.summary if outdated_report else {},
            "vulnerabilities": security_report.summary if security_report else {},
        }
        console.print_json(json.dumps(result))
    elif output_format == "sarif":
        sarif_doc = format_sarif(report, security_report=security_report, manifests=manifests)
        console.print_json(sarif_doc)
    elif output_format == "junit":
        junit_doc = format_junit(report, security_report=security_report, manifests=manifests)
        console.print(junit_doc, soft_wrap=True, highlight=False)

    if heal:
        from zerogravity.commands.heal import heal_command
        heal_command(path=str(project_paths[0]) if project_paths else None, auto_approve=False)
