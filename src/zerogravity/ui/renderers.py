"""
Rich-powered renderers for ZeroGravity CLI output.

Provides colour-coded, structured rendering for system snapshots,
conflict reports, manifest trees, and deduplication summaries.
"""

from __future__ import annotations

from typing import Any

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from zerogravity.parsers.base import DependencyType, ProjectManifest
from zerogravity.resolver.models import (
    BinaryProbe,
    ResolutionReport,
    SystemSnapshot,
    VersionManagerInfo,
)
from zerogravity.ui.console import console, print_section

# ═══════════════════════════════════════════════════════════════════════════
#  System Snapshot Renderer
# ═══════════════════════════════════════════════════════════════════════════

def render_system_snapshot(snapshot: SystemSnapshot) -> None:
    """
    Render a full system snapshot as a styled Rich table.

    Displays binary status (installed/missing), path, version,
    and colour-coded health indicators.
    """
    print_section("System Binary Audit")

    table = Table(
        title="[zg.accent]Detected System Binaries[/]",
        box=box.ROUNDED,
        show_lines=False,
        header_style="bold #b388ff",
        border_style="#455a64",
        padding=(0, 1),
    )
    table.add_column("Binary", style="zg.package", min_width=12)
    table.add_column("Status", justify="center", min_width=10)
    table.add_column("Version", style="zg.version", min_width=12)
    table.add_column("Path", style="zg.dim", max_width=50, overflow="ellipsis")

    for name, probe in sorted(snapshot.binaries.items()):
        status = _format_binary_status(probe)
        version = probe.version or "—"
        path = probe.path or "—"
        table.add_row(name, status, version, path)

    console.print(table)

    # Platform info panel
    if snapshot.platform:
        platform_text = " │ ".join(
            f"[zg.label]{k}:[/] [zg.value]{v}[/]"
            for k, v in snapshot.platform.items()
        )
        console.print(
            Panel(
                platform_text,
                title="[zg.accent]Platform[/]",
                border_style="#455a64",
                padding=(0, 1),
            )
        )

    # Version managers
    if snapshot.version_managers:
        _render_version_managers(snapshot.version_managers)


def _format_binary_status(probe: BinaryProbe) -> str:
    """Format a binary probe result as a styled status string."""
    if not probe.installed:
        return "[zg.error]● NOT FOUND[/]"
    if probe.error:
        return "[zg.warning]● ERROR[/]"
    return "[zg.ok]● INSTALLED[/]"


def _render_version_managers(managers: dict[str, VersionManagerInfo]) -> None:
    """Render detected version managers."""
    print_section("Version Managers")

    detected = {k: v for k, v in managers.items() if v.detected}
    if not detected:
        console.print("[zg.dim]  No version managers detected.[/]")
        return

    table = Table(
        box=box.SIMPLE_HEAVY,
        header_style="bold #b388ff",
        border_style="#455a64",
    )
    table.add_column("Manager", style="zg.engine")
    table.add_column("Active Version", style="zg.version")
    table.add_column("Installed Versions", style="zg.dim")
    table.add_column("Root", style="zg.path")

    for name, info in detected.items():
        versions_str = ", ".join(info.installed_versions[:5])
        if len(info.installed_versions) > 5:
            versions_str += f" (+{len(info.installed_versions) - 5} more)"
        table.add_row(
            name,
            info.active_version or "—",
            versions_str or "—",
            info.root_path or "—",
        )

    console.print(table)


# ═══════════════════════════════════════════════════════════════════════════
#  Conflict Report Renderer
# ═══════════════════════════════════════════════════════════════════════════

def render_conflict_report(report: ResolutionReport) -> None:
    """
    Render a conflict detection report with colour-coded severity levels,
    remediation suggestions, and a summary dashboard.
    """
    print_section("Conflict Report")

    if not report.issues:
        console.print(
            Panel(
                "[zg.ok]✅ No issues detected. Your environment looks healthy![/]",
                border_style="#00d26a",
                padding=(1, 2),
            )
        )
        return

    # Issues table
    table = Table(
        title="[zg.accent]Detected Issues[/]",
        box=box.ROUNDED,
        show_lines=True,
        header_style="bold #b388ff",
        border_style="#455a64",
        padding=(0, 1),
    )
    table.add_column("Severity", justify="center", min_width=10)
    table.add_column("Category", style="zg.label", min_width=18)
    table.add_column("Message", min_width=40, max_width=60)
    table.add_column("Expected", style="zg.version", min_width=10)
    table.add_column("Actual", style="zg.version", min_width=10)
    table.add_column("Fix", style="zg.info", min_width=20, max_width=35)

    for issue in report.sorted_issues:
        severity_text = Text(
            f"{issue.severity.icon} {issue.severity.value.upper()}",
        )
        severity_text.stylize(issue.severity.color)

        category = issue.category.value.replace("_", " ").title()
        fix = issue.remediation or "—"

        table.add_row(
            severity_text,
            category,
            issue.message,
            issue.expected or "—",
            issue.actual or "—",
            fix,
        )

    console.print(table)

    # Summary panel
    _render_report_summary(report)


def _render_report_summary(report: ResolutionReport) -> None:
    """Render a summary panel with issue counts."""
    summary = report.summary
    parts = []
    if summary["critical"] > 0:
        parts.append(f"[zg.critical]🔴 {summary['critical']} Critical[/]")
    if summary["errors"] > 0:
        parts.append(f"[zg.error]❌ {summary['errors']} Errors[/]")
    if summary["warnings"] > 0:
        parts.append(f"[zg.warning]⚠️  {summary['warnings']} Warnings[/]")
    if summary["ok"] > 0:
        parts.append(f"[zg.ok]✅ {summary['ok']} OK[/]")

    summary_text = "   ".join(parts)
    console.print()
    console.print(
        Panel(
            summary_text,
            title="[zg.accent]Summary[/]",
            subtitle=f"[zg.dim]{summary['total']} total issues across {report.scanned_projects} projects[/]",
            border_style="#455a64",
            padding=(0, 2),
        )
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Project Manifest Renderer
# ═══════════════════════════════════════════════════════════════════════════

def render_project_manifest(manifest: ProjectManifest) -> None:
    """
    Render a project manifest as a dependency tree with type annotations.
    """
    project_label = (
        f"[zg.accent]{manifest.project_name or manifest.project_path.name}[/] "
        f"[zg.dim]({manifest.ecosystem.value})[/]"
    )
    tree = Tree(project_label, guide_style="zg.dim")

    # Engine constraints
    if manifest.engine_constraints:
        engines_branch = tree.add("[zg.engine]⚙ Engine Constraints[/]")
        for engine, spec in manifest.engine_constraints.items():
            engines_branch.add(f"[zg.label]{engine}[/] [zg.version]{spec}[/]")

    # Dependencies by type
    dep_groups = {
        DependencyType.PRODUCTION: ("📦 Production", "zg.ok"),
        DependencyType.DEVELOPMENT: ("🔧 Development", "zg.info"),
        DependencyType.PEER: ("🔗 Peer", "zg.warning"),
        DependencyType.OPTIONAL: ("📎 Optional", "zg.dim"),
    }

    for dep_type, (label, style) in dep_groups.items():
        deps = [d for d in manifest.dependencies if d.dep_type == dep_type]
        if deps:
            branch = tree.add(f"[{style}]{label} ({len(deps)})[/]")
            for dep in sorted(deps, key=lambda d: d.name):
                version = dep.resolved_version or dep.version_spec or "any"
                extras = f"[{', '.join(dep.extras)}]" if dep.extras else ""
                branch.add(
                    f"[zg.package]{dep.name}{extras}[/] "
                    f"[zg.dim]@ {version}[/]"
                )

    # Lockfile status
    lock_status = (
        "[zg.ok]✅ Lockfile present[/]"
        if manifest.lockfile_present
        else "[zg.warning]⚠️  No lockfile[/]"
    )
    tree.add(lock_status)

    console.print(tree)


# ═══════════════════════════════════════════════════════════════════════════
#  Deduplication Report Renderer
# ═══════════════════════════════════════════════════════════════════════════

def render_dedup_report(report: dict[str, Any]) -> None:
    """
    Render a deduplication scan report showing duplicate groups
    and potential savings.
    """
    print_section("Deduplication Report")

    groups = report.get("groups", [])
    if not groups:
        console.print(
            Panel(
                "[zg.ok]✅ No duplicates found across scanned projects.[/]",
                border_style="#00d26a",
                padding=(1, 2),
            )
        )
        return

    table = Table(
        title="[zg.accent]Duplicate Dependencies[/]",
        box=box.ROUNDED,
        header_style="bold #b388ff",
        border_style="#455a64",
    )
    table.add_column("Hash", style="zg.dim", max_width=12)
    table.add_column("Copies", justify="center", style="zg.warning")
    table.add_column("Size (each)", justify="right", style="zg.version")
    table.add_column("Potential Savings", justify="right", style="zg.ok")
    table.add_column("Locations", style="zg.path")

    for group in groups:
        hash_short = group.get("hash", "")[:10] + "…"
        copies = str(len(group.get("paths", [])))
        size = _format_bytes(group.get("size_bytes", 0))
        savings = _format_bytes(group.get("potential_savings", 0))
        locations = "\n".join(str(p) for p in group.get("paths", [])[:3])
        if len(group.get("paths", [])) > 3:
            locations += f"\n(+{len(group['paths']) - 3} more)"
        table.add_row(hash_short, copies, size, savings, locations)

    console.print(table)

    # Total savings panel
    total_waste = report.get("total_waste_bytes", 0)
    total_dirs = report.get("total_directories", 0)
    console.print(
        Panel(
            f"[zg.accent]Total recoverable space:[/] [zg.ok]{_format_bytes(total_waste)}[/] "
            f"across [zg.version]{total_dirs}[/] directories",
            border_style="#455a64",
            padding=(0, 2),
        )
    )


def render_dedup_status(status: dict[str, Any]) -> None:
    """Render deduplication engine status dashboard."""
    print_section("Deduplication Status")

    table = Table(box=box.SIMPLE, header_style="bold #b388ff")
    table.add_column("Metric", style="zg.label")
    table.add_column("Value", style="zg.value", justify="right")

    table.add_row("Packages in Store", str(status.get("total_packages", 0)))
    table.add_row("Active Links", str(status.get("total_links", 0)))
    table.add_row("Store Size", _format_bytes(status.get("total_bytes_stored", 0)))
    table.add_row(
        "Estimated Savings",
        f"[zg.ok]{_format_bytes(status.get('estimated_bytes_saved', 0))}[/]",
    )

    console.print(table)


# ═══════════════════════════════════════════════════════════════════════════
#  Utilities
# ═══════════════════════════════════════════════════════════════════════════

def _format_bytes(num_bytes: int) -> str:
    """Format byte count into human-readable string (KB, MB, GB)."""
    if num_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    size = float(num_bytes)
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    return f"{size:.1f} {units[unit_index]}"
