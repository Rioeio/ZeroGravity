from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from zerogravity.cli import app
from zerogravity.commands.scan import _iter_scan_dirs
from zerogravity.config import (
    CONFIG_FILENAME,
    STARTER_CONFIG_TEMPLATE,
    ZeroGravityConfig,
    create_starter_config,
    load_config,
)
from zerogravity.parsers.base import Dependency, DependencyType, Ecosystem, ProjectManifest
from zerogravity.resolver.binary_lookup import lookup_system_deps
from zerogravity.resolver.conflict_detector import detect_conflicts
from zerogravity.resolver.models import IssueCategory, SystemSnapshot

runner = CliRunner()


def test_load_config_defaults(tmp_path: Path):
    """Loading config in an empty directory returns default empty config."""
    config = load_config(tmp_path)
    assert isinstance(config, ZeroGravityConfig)
    assert config.exclude == []
    assert config.binary_map == {}
    assert config.ignore_issues == []
    assert config.ignore_packages == []


def test_load_config_full(tmp_path: Path):
    """Load config parsing [scan], [binary_map], and [ignore] sections."""
    cfg_file = tmp_path / CONFIG_FILENAME
    cfg_file.write_text("""
[scan]
exclude = ["tmp", "build_cache", "ignored_*"]

[binary_map]
pillow = ["libjpeg-turbo"]
my-custom-pkg = ["my_custom_bin"]

[ignore]
issues = ["lockfile_missing", "missing_system_dep"]
packages = ["cryptography"]
""")

    config = load_config(tmp_path)
    assert config.config_path == cfg_file
    assert "tmp" in config.exclude
    assert "build_cache" in config.exclude
    assert "ignored_*" in config.exclude
    assert config.binary_map["pillow"] == ["libjpeg-turbo"]
    assert config.binary_map["my-custom-pkg"] == ["my_custom_bin"]
    assert "lockfile_missing" in config.ignore_issues
    assert "missing_system_dep" in config.ignore_issues
    assert "cryptography" in config.ignore_packages


def test_custom_binary_map_override():
    """Custom binary mapping overrides or augments default lookup table."""
    deps = [
        Dependency(name="pillow", version_spec="*", dep_type=DependencyType.PRODUCTION),
        Dependency(name="custom-pkg", version_spec="*", dep_type=DependencyType.PRODUCTION),
    ]

    custom_map = {
        "pillow": ["libjpeg-turbo"],
        "custom-pkg": ["custom-tool"],
    }

    reqs = lookup_system_deps(deps, custom_map=custom_map)
    req_map = {r.package_name: r.required_binary for r in reqs}
    assert req_map["pillow"] == "libjpeg-turbo"
    assert req_map["custom-pkg"] == "custom-tool"


def test_conflict_detector_filters_ignored_issues(mock_system_snapshot: SystemSnapshot):
    """detect_conflicts filters out issues configured in ignore.issues."""
    manifest = ProjectManifest(
        project_path=Path("/tmp/proj"),
        project_name="proj",
        ecosystem=Ecosystem.NODE,
        dependencies=[],
        engine_constraints={},
        lockfile_present=False,  # would normally produce LOCKFILE_MISSING
    )

    # Without ignore config
    report_unfiltered = detect_conflicts([manifest], mock_system_snapshot, include_history=False, config=ZeroGravityConfig())
    assert any(i.category == IssueCategory.LOCKFILE_MISSING for i in report_unfiltered.issues)

    # With ignore config
    config = ZeroGravityConfig(ignore_issues=["lockfile_missing"])
    report_filtered = detect_conflicts([manifest], mock_system_snapshot, include_history=False, config=config)
    assert not any(i.category == IssueCategory.LOCKFILE_MISSING for i in report_filtered.issues)


def test_conflict_detector_filters_ignored_packages(mock_system_snapshot: SystemSnapshot):
    """detect_conflicts filters out issues related to packages in ignore.packages."""
    dep = Dependency(
        name="cryptography",
        version_spec="*",
        dep_type=DependencyType.PRODUCTION,
    )
    manifest = ProjectManifest(
        project_path=Path("/tmp/proj"),
        project_name="proj",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[dep],
        lockfile_present=True,
    )

    # Without ignore config (missing openssl)
    report_unfiltered = detect_conflicts([manifest], mock_system_snapshot, include_history=False, config=ZeroGravityConfig())
    assert any(i.category == IssueCategory.MISSING_SYSTEM_DEP for i in report_unfiltered.issues)

    # With ignore config
    config = ZeroGravityConfig(ignore_packages=["cryptography"])
    report_filtered = detect_conflicts([manifest], mock_system_snapshot, include_history=False, config=config)
    assert not any(i.category == IssueCategory.MISSING_SYSTEM_DEP for i in report_filtered.issues)


def test_recursive_scan_custom_excludes(tmp_path: Path):
    """_iter_scan_dirs respects extra_excludes with exact names and glob patterns."""
    (tmp_path / "keep_dir").mkdir()
    (tmp_path / "custom_temp").mkdir()
    (tmp_path / "ignored_sub").mkdir()

    dirs = list(_iter_scan_dirs(tmp_path, extra_excludes=["custom_temp", "ignored_*"]))
    dir_names = {d.name for d in dirs}

    assert "keep_dir" in dir_names
    assert "custom_temp" not in dir_names
    assert "ignored_sub" not in dir_names


def test_create_starter_config(tmp_path: Path):
    """create_starter_config generates .zerogravity.toml with starter comments."""
    cfg = create_starter_config(tmp_path)
    assert cfg.is_file()
    content = cfg.read_text(encoding="utf-8")
    assert "[scan]" in content
    assert "[binary_map]" in content
    assert "[ignore]" in content


def test_cli_init_fresh_directory(tmp_path: Path):
    """zg init creates .zerogravity.toml on a fresh directory."""
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0
    assert "Created configuration file" in result.stdout
    assert (tmp_path / CONFIG_FILENAME).is_file()


def test_cli_init_existing_refuses_without_force(tmp_path: Path):
    """zg init refuses to overwrite an existing config without --force."""
    cfg = tmp_path / CONFIG_FILENAME
    cfg.write_text("# custom user content")

    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 1
    assert "already exists" in result.stdout
    assert cfg.read_text() == "# custom user content"


def test_cli_init_existing_overwrites_with_force(tmp_path: Path):
    """zg init --force overwrites an existing config."""
    cfg = tmp_path / CONFIG_FILENAME
    cfg.write_text("# custom user content")

    result = runner.invoke(app, ["init", str(tmp_path), "--force"])
    assert result.exit_code == 0
    assert "Created configuration file" in result.stdout
    assert cfg.read_text() == STARTER_CONFIG_TEMPLATE


def test_cli_scan_loads_config_exclusions(tmp_path: Path):
    """zg scan --recursive skips directories excluded in .zerogravity.toml."""
    (tmp_path / "app1").mkdir()
    (tmp_path / "app1" / "package.json").write_text('{"name": "app1"}')

    (tmp_path / "ignored_app").mkdir()
    (tmp_path / "ignored_app" / "package.json").write_text('{"name": "ignored-app"}')

    (tmp_path / CONFIG_FILENAME).write_text("""
[scan]
exclude = ["ignored_app"]
""")

    result = runner.invoke(app, ["scan", str(tmp_path), "--recursive", "--no-history"])
    assert result.exit_code == 0
    assert "app1" in result.stdout
    assert "ignored-app" not in result.stdout
