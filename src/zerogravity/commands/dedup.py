"""
`zg dedup` command group — Dependency deduplication.

Provides subcommands to scan, optimize, restore, and check status
of deduplicated dependency folders.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from zerogravity.ui.console import (
    console,
    print_banner,
    print_success,
    print_error,
    print_warning,
    print_info,
    print_section,
)


dedup_app = typer.Typer(
    name="dedup",
    help="Smart dependency deduplication with virtualised symlinking.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@dedup_app.command("scan")
def dedup_scan(
    paths: list[str] = typer.Argument(
        ...,
        help="Project directories to scan for duplicate dependencies.",
    ),
    target_dirs: Optional[list[str]] = typer.Option(
        None,
        "--target",
        "-t",
        help="Specific directory names to check (default: node_modules, .venv, vendor).",
    ),
) -> None:
    """
    Scan multiple project directories for duplicate dependency folders.
    """
    from zerogravity.dedup.engine import DeduplicationEngine
    from zerogravity.ui.renderers import render_dedup_report

    print_banner()

    project_paths = [Path(p).resolve() for p in paths]

    # Validate paths
    for p in project_paths:
        if not p.is_dir():
            print_error(f"Not a directory: {p}")
            raise typer.Exit(code=1)

    with console.status("[zg.accent]Scanning for duplicates...[/]", spinner="dots"):
        engine = DeduplicationEngine()
        report = engine.scan_for_duplicates(
            project_paths,
            target_dirs=target_dirs,
        )

    render_dedup_report({
        "groups": [
            {
                "hash": g.hash,
                "paths": [str(p) for p in g.paths],
                "size_bytes": g.size_bytes,
                "potential_savings": g.potential_savings,
            }
            for g in report.groups
        ],
        "total_waste_bytes": report.total_waste_bytes,
        "total_directories": report.total_directories,
    })


@dedup_app.command("optimize")
def dedup_optimize(
    path: str = typer.Argument(
        ...,
        help="Path to the dependency folder to deduplicate.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Show what would be done without making changes.",
    ),
) -> None:
    """
    Deduplicate a specific dependency folder by moving it to the
    central store and creating an OS-level link.
    """
    from zerogravity.dedup.engine import DeduplicationEngine

    dep_path = Path(path).resolve()

    if not dep_path.is_dir():
        print_error(f"Not a directory: {dep_path}")
        raise typer.Exit(code=1)

    engine = DeduplicationEngine()

    if dry_run:
        print_info(f"[DRY RUN] Would optimize: {dep_path}")
        hash_val = engine._generate_content_hash(dep_path)
        print_info(f"Content hash: {hash_val[:16]}...")
        existing = engine.registry.package_exists(hash_val)
        if existing:
            print_info("Package already in store — would only create link (instant)")
        else:
            print_info("Package not in store — would copy to store, then create link")
        return

    with console.status("[zg.accent]Optimizing...[/]", spinner="dots"):
        result = engine.optimize(dep_path)

    if result.status == "success":
        from zerogravity.ui.renderers import _format_bytes
        print_success(f"Optimized: {dep_path}")
        print_info(f"Hash: {result.hash[:16]}...")
        print_info(f"Saved: {_format_bytes(result.bytes_saved)}")
        print_info(f"Store: {result.store_path}")
    elif result.status == "skipped":
        print_warning(f"Skipped: {result.error_message}")
    else:
        print_error(f"Failed: {result.error_message}")
        raise typer.Exit(code=1)


@dedup_app.command("restore")
def dedup_restore(
    path: str = typer.Argument(
        ...,
        help="Path to a linked dependency folder to restore.",
    ),
) -> None:
    """
    Restore a deduplicated folder back to a real directory (undo optimization).
    """
    from zerogravity.dedup.engine import DeduplicationEngine

    dep_path = Path(path).resolve()
    engine = DeduplicationEngine()

    with console.status("[zg.accent]Restoring...[/]", spinner="dots"):
        result = engine.restore(dep_path)

    if result.status == "success":
        print_success(f"Restored: {dep_path}")
    else:
        print_error(f"Failed: {result.error_message}")
        raise typer.Exit(code=1)


@dedup_app.command("status")
def dedup_status() -> None:
    """
    Show deduplication engine status — packages in store, active links, and savings.
    """
    from zerogravity.dedup.engine import DeduplicationEngine
    from zerogravity.ui.renderers import render_dedup_status

    print_banner()

    engine = DeduplicationEngine()
    status = engine.get_status()
    render_dedup_status(status)
