"""
Global Rich Console instance and ZeroGravity theme configuration.

Provides a centralised, consistently-styled console used by all
UI renderers across the CLI.
"""

from __future__ import annotations

import logging
import os
import sys

from rich.console import Console
from rich.theme import Theme

# ── ZeroGravity colour palette ──────────────────────────────────────────────
ZG_THEME = Theme({
    # Status colours
    "zg.ok":       "#00d26a",      # Vivid green  — synced / healthy
    "zg.info":     "#00d4ff",      # Cyan         — informational
    "zg.warning":  "#ffb627",      # Amber        — optimisation available
    "zg.error":    "#ff4d4d",      # Red          — broken dependency
    "zg.critical": "bold #ff0033", # Bold red     — critical failure

    # Structural colours
    "zg.header":   "bold #b388ff",  # Lavender     — section headers
    "zg.dim":      "dim #9e9e9e",   # Muted grey   — secondary text
    "zg.accent":   "bold #00e5ff",  # Electric cyan — emphasis / highlights
    "zg.path":     "underline #81d4fa", # Light blue — file paths
    "zg.version":  "bold #e0e0e0",  # White-ish    — version strings
    "zg.label":    "#b0bec5",       # Blue grey    — field labels
    "zg.value":    "#ffffff",       # White        — field values

    # Engine identifiers
    "zg.engine":   "bold #ffab40",  # Orange       — engine names
    "zg.package":  "#ce93d8",       # Light purple — package names
})


# ── Global console singletons ───────────────────────────────────────────────
console = Console(theme=ZG_THEME, highlight=False)
error_console = Console(stderr=True, theme=ZG_THEME, highlight=False)

_cli_verbose: int = 0
_cli_quiet: bool = False
_cli_no_color: bool = False
_zg_log_handler: logging.Handler | None = None


def configure_environment(
    verbose: int = 0,
    quiet: bool = False,
    no_color: bool = False,
    is_global_callback: bool = False,
) -> None:
    """Configure global console and structured logging based on CLI flags and environment."""
    global _cli_verbose, _cli_quiet, _cli_no_color, _zg_log_handler

    if is_global_callback:
        _cli_verbose = verbose
        _cli_quiet = quiet
        _cli_no_color = no_color
    else:
        verbose = max(verbose, _cli_verbose)
        quiet = quiet or _cli_quiet
        no_color = no_color or _cli_no_color

    env_no_color = bool(os.environ.get("NO_COLOR", ""))
    env_force_color = bool(os.environ.get("FORCE_COLOR", "")) and os.environ.get("FORCE_COLOR") != "0"

    disable_color = False
    if no_color:
        disable_color = True
    elif env_force_color:
        disable_color = False
    elif env_no_color:
        disable_color = True

    console.no_color = disable_color
    error_console.no_color = disable_color
    console.quiet = quiet

    if quiet:
        log_level = logging.ERROR
    elif verbose >= 2:
        log_level = logging.DEBUG
    elif verbose == 1:
        log_level = logging.INFO
    else:
        log_level = logging.WARNING

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    if _zg_log_handler is not None:
        _zg_log_handler.setLevel(log_level)
    else:
        handler = _DynamicStreamHandler()
        handler.setLevel(log_level)
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
        _zg_log_handler = handler


class _DynamicStreamHandler(logging.StreamHandler):
    """StreamHandler that dynamically resolves sys.stderr on each emit."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            sys.stderr.write(msg + self.terminator)
            sys.stderr.flush()
        except (RecursionError, SystemExit, KeyboardInterrupt):
            raise
        except (OSError, RuntimeError, ValueError):
            self.handleError(record)


# ── ASCII Banner ────────────────────────────────────────────────────────────
BANNER_ART = r"""
[bold #00e5ff] ______              _____                 _ _
|__  /___ _ __ ___  / ____|_ __ __ ___   _(_) |_ _   _
  / // _ \ '__/ _ \| |  __| '__/ _` \ \ / / | __| | | |
 / /|  __/ | | (_) | |_|_ | | | (_| |\ V /| | |_| |_| |
/____\___|_|  \___/ \_____|_|  \__,_| \_/ |_|\__|\__, |
                                                   |___/[/]
[dim]Bridge your code to your machine.[/dim]
"""


def print_banner() -> None:
    """Print the ZeroGravity ASCII art banner."""
    console.print(BANNER_ART)


def print_section(title: str) -> None:
    """Print a styled section header."""
    console.print()
    console.print(f"[zg.header]━━━ {title} ━━━[/]")
    console.print()


def print_success(message: str) -> None:
    """Print a success message."""
    console.print(f"[zg.ok]✅ {message}[/]")


def print_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"[zg.warning]⚠️  {message}[/]")


def print_error(message: str) -> None:
    """Print an error message."""
    if console.quiet:
        error_console.print(f"[zg.error]❌ {message}[/]")
    else:
        console.print(f"[zg.error]❌ {message}[/]")


def print_info(message: str) -> None:
    """Print an informational message."""
    console.print(f"[zg.info]ℹ️  {message}[/]")
