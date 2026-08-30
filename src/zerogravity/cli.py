"""
ZeroGravity CLI — Main application entry point.

Provides the `zg` command with subcommands for scanning, auditing,
deduplicating, and checking system status.
"""

from __future__ import annotations

import typer
from rich.console import Console

from zerogravity import __version__
from zerogravity.commands import (
    audit,
    dedup,
    doctor,
    heal,
    init,
    outdated,
    scan,
    security,
    status,
    why,
)

# ── App setup ───────────────────────────────────────────────────────────────
app = typer.Typer(
    name="zg",
    help=(
        "ZeroGravity — Bridge the gap between your project dependencies "
        "and your local operating system."
    ),
    rich_markup_mode="rich",
    no_args_is_help=True,
    add_completion=True,
    pretty_exceptions_enable=True,
    pretty_exceptions_show_locals=False,
)

# ── Register subcommands ────────────────────────────────────────────────────
app.command(name="scan", help="[bold cyan]Scan[/] a project directory for dependency issues.")(scan.scan_command)
app.command(name="audit", help="[bold cyan]Audit[/] your OS environment — binaries, version managers, env vars.")(audit.audit_command)
app.add_typer(dedup.dedup_app, name="dedup", help="[bold cyan]Deduplicate[/] dependency folders across projects.")
app.command(name="status", help="[bold cyan]Status[/] dashboard — system health at a glance.")(status.status_command)
app.command(name="heal", help="[bold cyan]Self-heal[/] runtime environment mismatches.")(heal.heal_command)
app.command(name="init", help="[bold cyan]Initialize[/] .zerogravity.toml configuration file.")(init.init_command)
app.command(name="outdated", help="[bold cyan]Check[/] package registries for available dependency updates.")(outdated.outdated_command)
app.command(name="audit-security", help="[bold cyan]Audit[/] dependencies for known CVEs and security advisories.")(security.security_command)
app.command(name="why", help="[bold cyan]Trace[/] one dependency's resolution, lockfile, versions, and system binary requirements.")(why.why_command)
app.command(name="doctor", help="[bold cyan]Diagnose[/] your project — audit, scan, and offer to heal in one guided flow.")(doctor.doctor_command)


# ── Version callback ────────────────────────────────────────────────────────
def _version_callback(value: bool) -> None:
    if value:
        console = Console()
        console.print(f"[bold cyan]ZeroGravity[/] v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show ZeroGravity version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """
    ZeroGravity — Bridge your code to your machine.
    """
    pass
