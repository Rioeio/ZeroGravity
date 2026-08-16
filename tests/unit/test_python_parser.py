from __future__ import annotations

from pathlib import Path

from zerogravity.parsers.base import DependencyType
from zerogravity.parsers.python_parser import PythonParser


def test_can_parse_with_requirements(python_project_path: Path):
    parser = PythonParser()
    assert parser.can_parse(python_project_path) is True


def test_can_parse_with_pyproject(python_project_path: Path):
    parser = PythonParser()
    assert parser.can_parse(python_project_path) is True


def test_parse_requirements_pinned(python_project_path: Path):
    parser = PythonParser()
    manifest = parser.parse(python_project_path)
    pinned_requests = [
        d for d in manifest.dependencies
        if d.source == "requirements.txt" and d.name == "requests" and not d.extras
    ]
    assert len(pinned_requests) > 0
    assert pinned_requests[0].version_spec == "==2.31.0"


def test_parse_requirements_range(python_project_path: Path):
    parser = PythonParser()
    manifest = parser.parse(python_project_path)
    deps = {d.name: d for d in manifest.dependencies if d.source == "requirements.txt"}
    assert deps["flask"].version_spec == ">=2.3.0,<3.0.0"


def test_parse_requirements_extras(python_project_path: Path):
    parser = PythonParser()
    manifest = parser.parse(python_project_path)
    # The extras version of requests should have "security" in extras
    extras_deps = [
        d for d in manifest.dependencies
        if d.source == "requirements.txt" and d.name == "requests" and d.extras
    ]
    assert len(extras_deps) > 0
    assert "security" in extras_deps[0].extras


def test_parse_requirements_vcs(python_project_path: Path):
    parser = PythonParser()
    manifest = parser.parse(python_project_path)
    deps = {d.name: d for d in manifest.dependencies if d.source == "requirements.txt"}
    assert "custom-lib" in deps


def test_parse_requirements_comments(python_project_path: Path):
    parser = PythonParser()
    manifest = parser.parse(python_project_path)
    deps = [d for d in manifest.dependencies if d.source == "requirements.txt"]
    assert not any(d.name.startswith("#") for d in deps)


def test_parse_pyproject_dependencies(python_project_path: Path):
    parser = PythonParser()
    manifest = parser.parse(python_project_path)
    deps = {d.name: d for d in manifest.dependencies if d.source == "pyproject.toml"}
    assert "fastapi" in deps


def test_parse_pyproject_requires_python(python_project_path: Path):
    parser = PythonParser()
    manifest = parser.parse(python_project_path)
    assert manifest.engine_constraints["python"] == ">=3.10"


def test_parse_pyproject_optional_deps(python_project_path: Path):
    parser = PythonParser()
    manifest = parser.parse(python_project_path)
    deps = {
        d.name: d for d in manifest.dependencies
        if d.source == "pyproject.toml" and d.dep_type == DependencyType.OPTIONAL
    }
    assert "pytest" in deps
