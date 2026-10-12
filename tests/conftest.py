import socket
from pathlib import Path
from typing import Any, Generator

import pytest

from zerogravity.net import NetworkNotAllowedError
from zerogravity.resolver.models import BinaryProbe, SystemSnapshot


@pytest.fixture(autouse=True)
def isolate_zerogravity_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Hermetically isolate ZEROGRAVITY_HOME, HOME, and USERPROFILE to tmp_path."""
    zg_home = tmp_path / "hermetic_zg_home"
    zg_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ZEROGRAVITY_HOME", str(zg_home))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return zg_home


@pytest.fixture(autouse=True)
def network_guard(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Guard against unmocked external network calls in unit tests."""
    if request.node.get_closest_marker("integration"):
        yield
        return

    orig_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        host: Any = None
        if isinstance(address, tuple) and len(address) >= 1:
            host = address[0]
        elif isinstance(address, str):
            host = address

        if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0", 0, None):
            return orig_connect(self, address)

        raise NetworkNotAllowedError(
            f"Network connection to {address} blocked. "
            "Mock external network calls or mark test with @pytest.mark.integration."
        )

    socket.socket.connect = guarded_connect  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = orig_connect  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def reset_library_detection_cache():
    """Ensure each test runs with a clean library detection cache."""
    from zerogravity.scanner.lib_detector import clear_detection_cache

    clear_detection_cache()
    yield
    clear_detection_cache()


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
def rust_project_path(fixtures_path: Path) -> Path:
    return fixtures_path / "rust_project"


@pytest.fixture
def go_project_path(fixtures_path: Path) -> Path:
    return fixtures_path / "go_project"


@pytest.fixture
def node_workspace_path(fixtures_path: Path) -> Path:
    return fixtures_path / "node_workspace"


@pytest.fixture
def python_workspace_path(fixtures_path: Path) -> Path:
    return fixtures_path / "python_workspace"


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
