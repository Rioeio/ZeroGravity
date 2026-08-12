"""
Global Rich Console instance and ZeroGravity theme configuration.

Provides a centralised, consistently-styled console used by all
UI renderers across the CLI.
"""

from __future__ import annotations

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


# ── Global console singleton ────────────────────────────────────────────────
console = Console(theme=ZG_THEME, highlight=False)


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
    console.print(f"[zg.error]❌ {message}[/]")


def print_info(message: str) -> None:
    """Print an informational message."""
    console.print(f"[zg.info]ℹ️  {message}[/]")
