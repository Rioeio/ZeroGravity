from __future__ import annotations

import socket
import urllib.request
from pathlib import Path

import pytest

from zerogravity.state import get_state_dir


def test_network_guard_blocks_unmocked_network() -> None:
    from zerogravity.net import NetworkNotAllowedError

    with pytest.raises(NetworkNotAllowedError):
        urllib.request.urlopen("http://example.com", timeout=1)


def test_network_guard_allows_localhost() -> None:
    from zerogravity.net import NetworkNotAllowedError

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Attempt connection to 127.0.0.1 on an arbitrary unused port
        # Must not raise NetworkNotAllowedError (will raise OSError / ConnectionRefusedError)
        s.connect(("127.0.0.1", 59999))
    except NetworkNotAllowedError:
        pytest.fail("NetworkNotAllowedError raised for localhost connection!")
    except OSError:
        # Expected: connection refused
        pass
    finally:
        s.close()


@pytest.mark.integration
def test_network_guard_allows_integration_marker() -> None:
    from zerogravity.net import NetworkNotAllowedError

    try:
        # Should not raise NetworkNotAllowedError (may raise OSError/timeout)
        urllib.request.urlopen("http://example.com", timeout=0.1)
    except NetworkNotAllowedError:
        pytest.fail("NetworkNotAllowedError raised on integration-marked test!")
    except Exception:
        pass


def test_hermetic_env_isolates_zerogravity_home(tmp_path: Path) -> None:
    # Verify that get_state_dir() points to inside a tmp_path / isolated directory,
    # NOT the user's real ~/.zerogravity
    state_dir = get_state_dir()
    real_home_zg = Path.home() / ".zerogravity"
    assert state_dir != real_home_zg
    assert "hermetic" in str(state_dir) or "pytest" in str(state_dir) or "tmp" in str(state_dir).lower()
