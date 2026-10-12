from __future__ import annotations

from pathlib import Path

from zerogravity.parsers.base import DependencyType
from zerogravity.parsers.python_parser import PythonParser
from zerogravity.resolver.conflict_detector import _check_lockfiles


def test_uv_lock_and_groups_repro(tmp_path: Path):
    """The reproduction project with uv.lock and PEP 735 groups resolves correctly."""
    pyproject_content = """[project]
name = "my-app"
version = "0.1.0"
dependencies = ["requests>=2"]

[dependency-groups]
dev = ["pytest>=8"]
"""
    uv_lock_content = """version = 1
revision = 1

[[package]]
name = "my-app"
version = "0.1.0"
source = { virtual = "." }
dependencies = [
    { name = "requests" },
]

[[package]]
name = "requests"
version = "2.32.3"
source = { registry = "https://pypi.org/simple" }
dependencies = [
    { name = "urllib3" },
]

[[package]]
name = "urllib3"
version = "2.2.1"
source = { registry = "https://pypi.org/simple" }
"""
    (tmp_path / "pyproject.toml").write_text(pyproject_content, encoding="utf-8")
    (tmp_path / "uv.lock").write_text(uv_lock_content, encoding="utf-8")

    manifest = PythonParser().parse(tmp_path)

    # 1. Lockfile present and path set
    assert manifest.lockfile_present is True
    assert manifest.lockfile_path is not None
    assert manifest.lockfile_path.name == "uv.lock"

    # 2. requests resolved to 2.32.3
    req_dep = next((d for d in manifest.dependencies if d.name == "requests"), None)
    assert req_dep is not None
    assert req_dep.resolved_version == "2.32.3"

    # 3. urllib3 transitive dependency present
    url_dep = next((d for d in manifest.dependencies if d.name == "urllib3"), None)
    assert url_dep is not None
    assert url_dep.resolved_version == "2.2.1"
    assert url_dep.metadata.get("transitive") is True

    # 4. pytest is dev dependency
    pyt_dep = next((d for d in manifest.dependencies if d.name == "pytest"), None)
    assert pyt_dep is not None
    assert pyt_dep.dep_type == DependencyType.DEVELOPMENT

    # 5. Project's own entry is workspace_internal
    self_dep = next((d for d in manifest.dependencies if d.name == "my-app"), None)
    if self_dep:
        assert self_dep.metadata.get("workspace_internal") is True

    # 6. No lockfile issue reported
    issues = _check_lockfiles(manifest)
    assert len(issues) == 0


def test_pdm_lock(tmp_path: Path):
    """pdm.lock [[package]] entries resolve direct and transitive packages."""
    pyproject_content = """[project]
name = "pdm-app"
version = "1.0.0"
dependencies = ["flask>=3.0"]
"""
    pdm_lock_content = """version = "4.4.0"

[[package]]
name = "flask"
version = "3.0.2"
dependencies = [
    "werkzeug>=3.0.0",
]

[[package]]
name = "werkzeug"
version = "3.0.1"
"""
    (tmp_path / "pyproject.toml").write_text(pyproject_content, encoding="utf-8")
    (tmp_path / "pdm.lock").write_text(pdm_lock_content, encoding="utf-8")

    manifest = PythonParser().parse(tmp_path)
    assert manifest.lockfile_present is True
    assert manifest.lockfile_path is not None
    assert manifest.lockfile_path.name == "pdm.lock"

    flask_dep = next((d for d in manifest.dependencies if d.name == "flask"), None)
    assert flask_dep is not None
    assert flask_dep.resolved_version == "3.0.2"

    werkzeug_dep = next((d for d in manifest.dependencies if d.name == "werkzeug"), None)
    assert werkzeug_dep is not None
    assert werkzeug_dep.resolved_version == "3.0.1"
    assert werkzeug_dep.metadata.get("transitive") is True


def test_pep735_and_uv_dev_dependencies(tmp_path: Path):
    """PEP 735 include-group and tool.uv dev-dependencies are parsed as DEV dependencies."""
    pyproject_content = """[project]
name = "group-app"
version = "1.0.0"
dependencies = []

[dependency-groups]
test = ["pytest>=8"]
dev = [
    { include-group = "test" },
    "ruff>=0.4.0",
]

[tool.uv]
dev-dependencies = [
    "black>=23.0.0",
]
"""
    (tmp_path / "pyproject.toml").write_text(pyproject_content, encoding="utf-8")

    manifest = PythonParser().parse(tmp_path)
    dep_names = {d.name: d.dep_type for d in manifest.dependencies}

    assert "pytest" in dep_names
    assert dep_names["pytest"] == DependencyType.DEVELOPMENT
    assert "ruff" in dep_names
    assert dep_names["ruff"] == DependencyType.DEVELOPMENT
    assert "black" in dep_names
    assert dep_names["black"] == DependencyType.DEVELOPMENT


def test_setup_cfg_support(tmp_path: Path):
    """setup.cfg install_requires and extras_require are parsed."""
    setup_cfg_content = """[metadata]
name = cfg-app
version = 0.1.0

[options]
install_requires =
    click>=8.0
    requests>=2.28

[options.extras_require]
test =
    pytest>=7.0
    coverage>=6.0
"""
    (tmp_path / "setup.cfg").write_text(setup_cfg_content, encoding="utf-8")

    manifest = PythonParser().parse(tmp_path)
    dep_map = {d.name: d for d in manifest.dependencies}

    assert "click" in dep_map
    assert dep_map["click"].dep_type == DependencyType.PRODUCTION
    assert "requests" in dep_map
    assert dep_map["requests"].dep_type == DependencyType.PRODUCTION

    assert "pytest" in dep_map
    assert dep_map["pytest"].dep_type == DependencyType.OPTIONAL
    assert dep_map["pytest"].metadata.get("optional_group") == "test"
    assert "coverage" in dep_map
    assert dep_map["coverage"].dep_type == DependencyType.OPTIONAL


def test_pep503_normalization(tmp_path: Path):
    """Package name comparisons normalize dashes, underscores, and dots per PEP 503."""
    pyproject_content = """[project]
name = "norm-app"
version = "1.0.0"
dependencies = ["importlib_metadata>=6.0"]
"""
    uv_lock_content = """version = 1

[[package]]
name = "importlib-metadata"
version = "6.8.0"
"""
    (tmp_path / "pyproject.toml").write_text(pyproject_content, encoding="utf-8")
    (tmp_path / "uv.lock").write_text(uv_lock_content, encoding="utf-8")

    manifest = PythonParser().parse(tmp_path)
    dep = next((d for d in manifest.dependencies if "importlib" in d.name), None)
    assert dep is not None
    assert dep.resolved_version == "6.8.0"
