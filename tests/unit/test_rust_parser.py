from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from zerogravity.healing.engine import HealingEngine
from zerogravity.parsers.base import DependencyType, Ecosystem
from zerogravity.parsers.registry import ParserRegistry, detect_and_parse
from zerogravity.parsers.rust_parser import RustParser
from zerogravity.resolver.conflict_detector import detect_conflicts
from zerogravity.resolver.models import BinaryProbe, SystemSnapshot


def test_can_parse_with_cargo_toml(rust_project_path: Path):
    parser = RustParser()
    assert parser.can_parse(rust_project_path) is True


def test_can_parse_without_cargo_toml(tmp_path: Path):
    parser = RustParser()
    assert parser.can_parse(tmp_path) is False


def test_ecosystem_property():
    parser = RustParser()
    assert parser.ecosystem == Ecosystem.RUST


def test_parse_direct_dependencies(rust_project_path: Path):
    parser = RustParser()
    manifest = parser.parse(rust_project_path)

    assert manifest.ecosystem == Ecosystem.RUST
    assert manifest.project_name == "rust_project"

    deps = {d.name: d for d in manifest.dependencies if d.source == "Cargo.toml"}

    # Production dependencies
    assert "serde" in deps
    assert deps["serde"].dep_type == DependencyType.PRODUCTION
    assert deps["serde"].version_spec == "1.0.197"
    assert "derive" in deps["serde"].extras

    assert "tokio" in deps
    assert deps["tokio"].dep_type == DependencyType.PRODUCTION
    assert deps["tokio"].version_spec == "1.36.0"
    assert "full" in deps["tokio"].extras

    # Optional dependency
    assert "flate2" in deps
    assert deps["flate2"].dep_type == DependencyType.OPTIONAL
    assert deps["flate2"].version_spec == "1.0.28"
    assert deps["flate2"].metadata.get("optional") is True

    # Dev dependency
    assert "tempfile" in deps
    assert deps["tempfile"].dep_type == DependencyType.DEVELOPMENT
    assert deps["tempfile"].version_spec == "3.10.1"

    # Build dependency
    assert "cc" in deps
    assert deps["cc"].dep_type == DependencyType.BUILD
    assert deps["cc"].version_spec == "1.0.83"


def test_parse_engine_constraints(rust_project_path: Path):
    parser = RustParser()
    manifest = parser.parse(rust_project_path)
    assert manifest.engine_constraints.get("rust") == "1.75.0"


def test_parse_edition_metadata(rust_project_path: Path):
    parser = RustParser()
    manifest = parser.parse(rust_project_path)
    assert manifest.metadata.get("edition") == "2021"


def test_parse_lockfile_detection(rust_project_path: Path):
    parser = RustParser()
    manifest = parser.parse(rust_project_path)
    assert manifest.lockfile_present is True
    assert manifest.lockfile_path == rust_project_path / "Cargo.lock"


def test_parse_resolved_versions(rust_project_path: Path):
    parser = RustParser()
    manifest = parser.parse(rust_project_path)

    direct_deps = {d.name: d for d in manifest.dependencies if d.source == "Cargo.toml"}
    assert direct_deps["serde"].resolved_version == "1.0.197"
    assert direct_deps["tokio"].resolved_version == "1.36.0"
    assert direct_deps["tempfile"].resolved_version == "3.10.1"
    assert direct_deps["cc"].resolved_version == "1.0.83"
    assert direct_deps["flate2"].resolved_version == "1.0.28"


def test_parse_transitive_dependencies(rust_project_path: Path):
    parser = RustParser()
    manifest = parser.parse(rust_project_path)

    transitive_deps = {d.name: d for d in manifest.dependencies if d.metadata.get("transitive") is True}

    # Verify expected transitive crates from Cargo.lock
    assert "serde_derive" in transitive_deps
    assert transitive_deps["serde_derive"].resolved_version == "1.0.197"
    assert transitive_deps["serde_derive"].source == "Cargo.lock"
    assert transitive_deps["serde_derive"].dep_type == DependencyType.PRODUCTION

    assert "proc-macro2" in transitive_deps
    assert transitive_deps["proc-macro2"].resolved_version == "1.0.78"

    assert "quote" in transitive_deps
    assert transitive_deps["quote"].resolved_version == "1.0.35"

    assert "syn" in transitive_deps
    assert transitive_deps["syn"].resolved_version == "2.0.48"

    assert "pin-project-lite" in transitive_deps
    assert transitive_deps["pin-project-lite"].resolved_version == "0.2.13"

    assert "cfg-if" in transitive_deps
    assert transitive_deps["cfg-if"].resolved_version == "1.0.0"

    assert "unicode-ident" in transitive_deps
    assert transitive_deps["unicode-ident"].resolved_version == "1.0.12"

    # Root project name should not be listed as a dependency
    all_dep_names = {d.name for d in manifest.dependencies}
    assert "rust_project" not in all_dep_names


def test_parse_target_specific_dependencies(tmp_path: Path):
    cargo_toml = tmp_path / "Cargo.toml"
    cargo_toml.write_text(
        """
[package]
name = "target_app"
version = "0.1.0"
edition = "2021"

[dependencies]
log = "0.4"

[target.'cfg(windows)'.dependencies]
winapi = "0.3"

[target.'cfg(unix)'.dependencies]
libc = { version = "0.2", optional = true }

[target.'cfg(unix)'.dev-dependencies]
nix = "0.26"
"""
    )
    parser = RustParser()
    manifest = parser.parse(tmp_path)
    deps = {d.name: d for d in manifest.dependencies}

    assert "log" in deps
    assert "winapi" in deps
    assert deps["winapi"].metadata.get("target") == "cfg(windows)"
    assert deps["winapi"].dep_type == DependencyType.PRODUCTION

    assert "libc" in deps
    assert deps["libc"].metadata.get("target") == "cfg(unix)"
    assert deps["libc"].dep_type == DependencyType.OPTIONAL

    assert "nix" in deps
    assert deps["nix"].metadata.get("target") == "cfg(unix)"
    assert deps["nix"].dep_type == DependencyType.DEVELOPMENT


def test_parse_malformed_cargo_toml(tmp_path: Path):
    cargo = tmp_path / "Cargo.toml"
    cargo.write_text("[package\nname = invalid")
    parser = RustParser()
    with pytest.raises(ValueError):
        parser.parse(tmp_path)


def test_parse_missing_cargo_toml(tmp_path: Path):
    parser = RustParser()
    with pytest.raises(FileNotFoundError):
        parser.parse(tmp_path)


def test_parse_workspace(tmp_path: Path):
    # Workspace root
    (tmp_path / "Cargo.toml").write_text(
        """
[workspace]
members = [
    "crates/core",
    "crates/cli",
]

[workspace.package]
rust-version = "1.74.0"
edition = "2021"
"""
    )
    crates_dir = tmp_path / "crates"
    core_dir = crates_dir / "core"
    cli_dir = crates_dir / "cli"
    core_dir.mkdir(parents=True)
    cli_dir.mkdir(parents=True)

    (core_dir / "Cargo.toml").write_text(
        """
[package]
name = "my-core"
version = "0.1.0"
edition = "2021"

[dependencies]
serde = "1.0"
"""
    )
    (cli_dir / "Cargo.toml").write_text(
        """
[package]
name = "my-cli"
version = "0.1.0"
edition = "2021"

[dependencies]
my-core = { path = "../core" }
clap = "4.0"
"""
    )

    parser = RustParser()

    # Test root
    root_manifest = parser.parse(tmp_path)
    assert root_manifest.is_workspace_root is True
    assert len(root_manifest.workspace_members) == 2
    assert root_manifest.engine_constraints.get("rust") == "1.74.0"

    # Test member
    cli_manifest = parser.parse(cli_dir)
    assert cli_manifest.is_workspace_member is True
    assert cli_manifest.workspace_root == tmp_path
    cli_deps = {d.name: d for d in cli_manifest.dependencies}
    assert cli_deps["my-core"].metadata.get("workspace_internal") is True


def test_registry_integration(rust_project_path: Path):
    registry = ParserRegistry()
    parsers = registry.detect_parsers(rust_project_path)
    assert any(isinstance(p, RustParser) for p in parsers)

    manifests = detect_and_parse(rust_project_path, use_cache=False)
    assert len(manifests) == 1
    assert manifests[0].ecosystem == Ecosystem.RUST
    assert manifests[0].project_name == "rust_project"


def test_healing_engine_triggered_by_rust_manifest(rust_project_path: Path):
    """
    Verify that an Ecosystem.RUST manifest with rust-version constraint
    produces a missing binary issue when rustc is missing / mismatched,
    which triggers the HealingEngine rustup remediation branch.
    """
    manifests = detect_and_parse(rust_project_path, use_cache=False)
    assert len(manifests) == 1
    manifest = manifests[0]

    # 1. Snapshot where rust is missing
    snapshot_missing = SystemSnapshot(
        binaries={
            "rust": BinaryProbe(name="rust", installed=False),
        }
    )
    report_missing = detect_conflicts([manifest], snapshot_missing, include_history=False)
    rust_issues = [i for i in report_missing.issues if i.affected_binary == "rust"]
    assert len(rust_issues) > 0
    assert rust_issues[0].expected == "1.75.0"

    # Test HealingEngine generates rustup remediation plan
    healing = HealingEngine()
    with patch("shutil.which", return_value="/usr/bin/rustup"):
        plans = healing.plan_remediations(report_missing, snapshot_missing)

    rust_plans = [p for p in plans if p.manager_name == "rustup"]
    assert len(rust_plans) == 1
    assert rust_plans[0].command == ["rustup", "override", "set", "1.75.0"]
    assert "Set Rust 1.75.0 via rustup override" in rust_plans[0].description

    # 2. Snapshot where rust version is older than constraint (e.g. 1.70.0 vs 1.75.0)
    snapshot_older = SystemSnapshot(
        binaries={
            "rust": BinaryProbe(name="rust", installed=True, version="1.70.0", path="/usr/bin/rustc"),
        }
    )
    report_older = detect_conflicts([manifest], snapshot_older, include_history=False)
    rust_issues_older = [i for i in report_older.issues if i.affected_binary == "rust"]
    assert len(rust_issues_older) > 0

    with patch("shutil.which", return_value="/usr/bin/rustup"):
        plans_older = healing.plan_remediations(report_older, snapshot_older)

    rust_plans_older = [p for p in plans_older if p.manager_name == "rustup"]
    assert len(rust_plans_older) == 1
    assert rust_plans_older[0].command == ["rustup", "override", "set", "1.75.0"]
