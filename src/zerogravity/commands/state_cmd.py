from __future__ import annotations

import logging
import os
from datetime import datetime

import typer
from rich import box
from rich.table import Table

from zerogravity.state import ensure_state_dir, get_state_dir, load_json
from zerogravity.ui.console import console

logger = logging.getLogger(__name__)

state_app = typer.Typer(
    help="[bold cyan]Manage[/] and inspect ZeroGravity local state files.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


def _format_size(size_bytes: int) -> str:
    """Format byte size into human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


@state_app.command(name="doctor", help="Inspect state files, check health, and list/prune quarantined files.")
def state_doctor(
    prune: bool = typer.Option(
        False,
        "--prune",
        help="Prune/delete all quarantined .corrupt-* files.",
    ),
) -> None:
    """Inspect state directory, report size and entries, and manage corrupt files."""
    state_dir = get_state_dir().resolve()
    ensure_state_dir(state_dir)

    env_var = os.environ.get("ZEROGRAVITY_HOME")
    origin = f"ZEROGRAVITY_HOME={env_var}" if env_var else "default (~/.zerogravity)"

    console.print("[bold cyan]ZeroGravity State Doctor[/bold cyan]")
    console.print(f"Directory: [dim]{state_dir}[/dim] ({origin})\n")

    files_to_check = [
        "scan_history.json",
        "scan_cache.json",
        "registry_cache.json",
        "osv_cache.json",
    ]

    table = Table(title="State Files Health", box=box.ROUNDED)
    table.add_column("State File", style="cyan")
    table.add_column("Size", style="white")
    table.add_column("Entries", style="green")
    table.add_column("Status", style="yellow")

    for fname in files_to_check:
        fpath = state_dir / fname
        if not fpath.exists():
            table.add_row(fname, "0 B", "0", "[dim]missing[/dim]")
            continue

        try:
            size = fpath.stat().st_size
            data = load_json(fpath, default={})
            entries_count = len(data) if isinstance(data, (dict, list)) else 0
            table.add_row(fname, _format_size(size), str(entries_count), "[green]healthy[/green]")
        except (OSError, TypeError, ValueError) as err:
            logger.debug("Failed inspecting state file %s: %s", fpath, err, exc_info=True)
            table.add_row(fname, _format_size(fpath.stat().st_size), "?", "[red]damaged[/red]")

    console.print(table)

    corrupt_files = sorted(state_dir.glob("*.corrupt-*"))
    if corrupt_files:
        corrupt_table = Table(title="\nQuarantined Corrupt Files", box=box.ROUNDED)
        corrupt_table.add_column("File", style="red")
        corrupt_table.add_column("Size", style="white")
        corrupt_table.add_column("Modified", style="dim")

        for cfile in corrupt_files:
            cstat = cfile.stat()
            mod_time = datetime.fromtimestamp(cstat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            corrupt_table.add_row(cfile.name, _format_size(cstat.st_size), mod_time)

        console.print(corrupt_table)

        if prune:
            pruned_count = 0
            for cfile in corrupt_files:
                try:
                    cfile.unlink()
                    pruned_count += 1
                except OSError as err:
                    console.print(f"[red]Failed to prune {cfile.name}: {err}[/red]")
            console.print(f"\n[green]Pruned {pruned_count} quarantined file(s).[/green]")
        else:
            console.print(
                f"\n[yellow]Found {len(corrupt_files)} quarantined file(s). Run 'zg state doctor --prune' to remove them.[/yellow]"
            )
    else:
        console.print("\n[dim]No quarantined files found.[/dim]")
