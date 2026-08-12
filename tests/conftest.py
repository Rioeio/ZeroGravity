from __future__ import annotations

import pytest
from pathlib import Path
from zerogravity.resolver.models import BinaryProbe, SystemSnapshot


@pytest.fixture
def fixtures_path() -> Path:
    return Path(__file__).parent / "test_fixtures"


@pytest.fixture
def node_project_path(fixtures_path: Path) -> Path:
    return fixtures_path / "node_project"


@pytest.fixture
def python_project_path(fixtures_path: Path) -> Path:
    return fixtures_path / "python_project"


@pytest.fixture
def tmp_project_dir(tmp_path: Path) -> Path:
    pkg = tmp_path / "package.json"
    pkg.write_text('{"name": "tmp-project"}')
    return tmp_path


@pytest.fixture
def mock_binary_probe() -> BinaryProbe:
    return BinaryProbe(
        name="node", installed=True, path="/usr/bin/node",
        version="20.11.0", error=None,
    )


@pytest.fixture
def mock_system_snapshot() -> SystemSnapshot:
    binaries = {
        "node": BinaryProbe(
            name="node", installed=True, path="/usr/bin/node",
            version="20.11.0", error=None,
        ),
        "python3": BinaryProbe(
            name="python3", installed=True, path="/usr/bin/python3",
            version="3.11.5", error=None,
        ),
        "git": BinaryProbe(
            name="git", installed=True, path="/usr/bin/git",
            version="2.42.0", error=None,
        ),
        "npm": BinaryProbe(
            name="npm", installed=True, path="/usr/bin/npm",
            version="10.2.4", error=None,
        ),
    }
    return SystemSnapshot(binaries=binaries)
