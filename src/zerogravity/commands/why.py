"""
`zg why` command — Trace dependency resolution and system binary requirements.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich import box
from rich.table import Table

from zerogravity.config import load_config
from zerogravity.parsers.registry import detect_and_parse
from zerogravity.resolver.binary_lookup import lookup_system_deps
from zerogravity.ui.console import console, print_error


def why_command(
    package: str = typer.Argument(
        ...,
        help="Package name to trace.",
    ),
    path: Optional[str] = typer.Argument(
        None,
        help="Project directory to inspect. Defaults to current directory.",
    ),
    output_format: str = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format: table (default) or json.",
    ),
) -> None:
    """
    Trace one dependency's full resolution — direct or transitive,
    which lockfile resolved it, its declared vs. resolved version,
    and any system binaries it requires per the dependency map.
    """
    project_path = Path(path).resolve() if path else Path.cwd()

    if not project_path.is_dir():
        print_error(f"Not a directory: {project_path}")
        raise typer.Exit(code=1)

    config = load_config(project_path)
    manifests = detect_and_parse(project_path)

    if not manifests:
        print_error(f"No supported manifest files found in {project_path}")
        raise typer.Exit(code=1)

    target_pkg = package.strip().lower()
    matches = []

    for manifest in manifests:
        for dep in manifest.dependencies:
            if dep.name.lower() == target_pkg:
                sys_deps = lookup_system_deps([dep], custom_map=config.binary_map if config else None)
                matches.append((manifest, dep, sys_deps))

    if not matches:
        if output_format == "json":
            console.print(
                json.dumps(
                    {
                        "package": package,
                        "found": False,
                        "message": f"Package '{package}' not found in project dependencies.",
                    },
                    indent=2,
                )
            )
        else:
            console.print(
                f"[zg.warning]Package '{package}' not found in project dependencies for {project_path.name}.[/]"
            )
        return

    if output_format == "json":
        traces = []
        for manifest, dep, sys_deps in matches:
            is_transitive = bool(dep.metadata.get("transitive"))
            lockfile_name = (
                manifest.lockfile_path.name
                if manifest.lockfile_path and (is_transitive or dep.resolved_version)
                else (dep.source if dep.source.endswith((".lock", ".json", ".sum")) else None)
            )
            traces.append({
                "package": dep.name,
                "project_name": manifest.project_name or manifest.project_path.name,
                "project_path": str(manifest.project_path),
                "ecosystem": manifest.ecosystem.value,
                "dependency_type": "transitive" if is_transitive else "direct",
                "role": dep.dep_type.value,
                "declared_version": dep.version_spec if not is_transitive else None,
                "resolved_version": dep.resolved_version,
                "lockfile": lockfile_name,
                "source": dep.source,
                "system_binaries": [r.required_binary for r in sys_deps],
            })
        console.print(json.dumps({"package": package, "found": True, "traces": traces}, indent=2))
        return

    for manifest, dep, sys_deps in matches:
        is_transitive = bool(dep.metadata.get("transitive"))
        dep_type_str = "Transitive" if is_transitive else f"Direct ({dep.dep_type.value})"

        if manifest.lockfile_path and (is_transitive or dep.resolved_version):
            lockfile_str = manifest.lockfile_path.name
        elif dep.source and any(dep.source.endswith(ext) for ext in (".lock", ".json", ".sum")):
            lockfile_str = dep.source
        elif manifest.lockfile_present and manifest.lockfile_path:
            lockfile_str = manifest.lockfile_path.name
        else:
            lockfile_str = "None (no lockfile)"

        declared_str = dep.version_spec if not is_transitive else "— (transitive)"
        resolved_str = dep.resolved_version or "— (unresolved)"

        if sys_deps:
            sys_binaries_str = ", ".join(r.required_binary for r in sys_deps)
        else:
            sys_binaries_str = "None"

        table = Table(
            title=f"[zg.accent]Dependency Trace: [bold]{dep.name}[/][/]",
            box=box.ROUNDED,
            show_header=False,
            border_style="#455a64",
            padding=(0, 1),
        )
        table.add_column("Property", style="zg.label", min_width=20)
        table.add_column("Value", style="zg.value")

        table.add_row("Package", f"[zg.package]{dep.name}[/]")
        table.add_row("Project", f"{manifest.project_name or manifest.project_path.name} [zg.dim]({manifest.project_path})[/]")
        table.add_row("Ecosystem", f"[zg.engine]{manifest.ecosystem.value.upper()}[/]")
        table.add_row("Dependency Type", f"[zg.ok]{dep_type_str}[/]" if not is_transitive else f"[zg.dim]{dep_type_str}[/]")
        table.add_row("Declared Version", f"[zg.version]{declared_str}[/]")
        table.add_row("Resolved Version", f"[zg.version]{resolved_str}[/]")
        table.add_row("Lockfile", f"[zg.path]{lockfile_str}[/]")
        table.add_row("System Binaries", f"[zg.info]{sys_binaries_str}[/]")

        if dep.extras:
            table.add_row("Extras / Features", ", ".join(dep.extras))
        if dep.metadata.get("workspace_internal"):
            table.add_row("Workspace Internal", "Yes (local workspace member/path)")

        console.print(table)
