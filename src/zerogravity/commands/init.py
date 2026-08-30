"""
`zg init` command — Initialize .zerogravity.toml configuration file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from zerogravity.config import CONFIG_FILENAME, create_starter_config
from zerogravity.ui.console import print_banner, print_error, print_info, print_success


def init_command(
    path: Optional[str] = typer.Argument(
        None,
        help="Directory to initialize .zerogravity.toml in. Defaults to current directory.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Overwrite existing configuration file if present.",
    ),
) -> None:
    """
    Scaffold a starter .zerogravity.toml configuration file with documented settings.
    """
    print_banner()

    target_dir = Path(path).resolve() if path else Path.cwd().resolve()

    if not target_dir.is_dir():
        print_error(f"Target path is not a directory: {target_dir}")
        raise typer.Exit(code=1)

    try:
        config_path = create_starter_config(target_dir, force=force)
        print_success(f"Created configuration file: {config_path}")
        print_info(f"Customize exclusion patterns, binary maps, and ignore lists in {CONFIG_FILENAME}.")
    except FileExistsError as e:
        print_error(str(e))
        raise typer.Exit(code=1)
    except Exception as e:
        print_error(f"Failed to create configuration file: {e}")
        raise typer.Exit(code=1)
