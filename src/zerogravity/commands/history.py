from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.table import Table

from zerogravity.resolver.history import ScanHistoryManager
from zerogravity.ui.console import console

history_app = typer.Typer(
    help="[bold cyan]Manage[/] local project scan history.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@history_app.command(name="list", help="List recorded scan history.")
def list_history() -> None:
    """Display all recorded projects in local scan history."""
    mgr = ScanHistoryManager()
    entries = mgr.get_history_entries()
    if not entries:
        console.print("[zg.dim]No scan history recorded.[/]")
        return

    table = Table(title="ZeroGravity Scan History", box=box.ROUNDED)
    table.add_column("Project", style="cyan")
    table.add_column("Path", style="dim")
    table.add_column("Ecosystem", style="green")
    table.add_column("Engine Constraints", style="yellow")
    table.add_column("Timestamp", style="dim")

    for path_str, data in sorted(entries.items(), key=lambda x: str(x[1].get("timestamp", "")), reverse=True):
        p_name = data.get("project_name") or Path(path_str).name
        eco = data.get("ecosystem", "unknown")
        engines = ", ".join(f"{k} {v}" for k, v in data.get("engine_constraints", {}).items()) or "-"
        ts = data.get("timestamp", "-")
        table.add_row(p_name, path_str, eco, engines, ts)

    console.print(table)


@history_app.command(name="clear", help="Clear local scan history.")
def clear_history(
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="Specific project directory path to remove from history.",
    ),
) -> None:
    """Clear scan history entries globally or for a specific project."""
    mgr = ScanHistoryManager()
    mgr.clear_history(path)
    if path:
        console.print(f"[zg.success]Cleared scan history for project:[/] {path}")
    else:
        console.print("[zg.success]Cleared all local scan history.[/]")
