from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.table import Table

from zerogravity.config import CONFIG_FILENAME, ConfigError, load_config
from zerogravity.ui.console import console, print_error

config_app = typer.Typer(
    help="[bold cyan]Inspect[/] and validate ZeroGravity project configuration.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@config_app.command(name="check", help="Check and display effective merged configuration and precedence.")
def config_check(
    path: Optional[str] = typer.Argument(
        None,
        help="Project path or configuration file to check.",
    ),
) -> None:
    """Validate .zerogravity.toml and display effective merged configuration."""
    target_path = Path(path).resolve() if path else Path.cwd()
    if target_path.is_file() and target_path.name != CONFIG_FILENAME:
        target_path = target_path.parent

    try:
        cfg = load_config(target_path)
    except ConfigError as err:
        print_error(str(err))
        raise typer.Exit(code=2)

    has_file = cfg.config_path is not None and cfg.config_path.is_file()
    file_source = f"file ({cfg.config_path.name})" if (has_file and cfg.config_path is not None) else "default"

    table = Table(title="ZeroGravity Effective Configuration", box=box.ROUNDED)
    table.add_column("Setting", style="cyan")
    table.add_column("Effective Value", style="white")
    table.add_column("Precedence / Source", style="yellow")

    ex_source = file_source if (has_file and cfg.exclude) else "default"
    table.add_row("scan.exclude", str(cfg.exclude) if cfg.exclude else "[]", ex_source)

    bm_source = file_source if (has_file and cfg.binary_map) else "default"
    table.add_row("binary_map", str(cfg.binary_map) if cfg.binary_map else "{}", bm_source)

    iss_source = file_source if (has_file and cfg.ignore_issues) else "default"
    table.add_row("ignore.issues", str(cfg.ignore_issues) if cfg.ignore_issues else "[]", iss_source)

    pkg_source = file_source if (has_file and cfg.ignore_packages) else "default"
    table.add_row("ignore.packages", str(cfg.ignore_packages) if cfg.ignore_packages else "[]", pkg_source)

    hist_source = file_source if (has_file and cfg.history_max_entries != 1000) else "default"
    table.add_row("history.max_entries", str(cfg.history_max_entries), hist_source)

    heal_source = file_source if (has_file and cfg.healing_prefer) else "default"
    table.add_row("healing.prefer", str(cfg.healing_prefer) if cfg.healing_prefer else "[]", heal_source)

    net_source = file_source if (has_file and (not cfg.network_enabled or cfg.network_max_workers != 8 or cfg.network_timeout != 5)) else "default"
    table.add_row("network.enabled", str(cfg.network_enabled), net_source)
    table.add_row("network.max_workers", str(cfg.network_max_workers), net_source)
    table.add_row("network.timeout", str(cfg.network_timeout), net_source)

    console.print(table)
    if has_file:
        console.print(f"[zg.ok]Configuration file:[/] {cfg.config_path}")
    else:
        console.print("[zg.dim]No configuration file found; using default settings.[/]")
