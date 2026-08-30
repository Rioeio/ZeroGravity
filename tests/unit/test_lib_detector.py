"""Tests for zerogravity.scanner.lib_detector — each detection strategy independently."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from zerogravity.resolver.models import BinaryProbe
from zerogravity.scanner.lib_detector import (
    _try_brew,
    _try_dpkg,
    _try_ldconfig,
    _try_pkg_config,
    _try_rpm,
    _try_which,
    detect_library,
)

# ── Shared fixture metadata ─────────────────────────────────────────────────
_META = {
    "type": "library",
    "pkg_config": "libjpeg",
    "apt": "libjpeg-dev",
    "rpm": "libjpeg-turbo-devel",
    "brew": "jpeg",
}

_META_NO_PC = {
    "type": "library",
    "pkg_config": None,
    "apt": "libbz2-dev",
    "rpm": "bzip2-devel",
    "brew": "bzip2",
}


# ── pkg-config strategy ─────────────────────────────────────────────────────

def test_pkg_config_found():
    """pkg-config --exists succeeds → returns installed probe with version."""
    with patch("zerogravity.scanner.lib_detector.shutil.which", return_value="/usr/bin/pkg-config"), \
         patch("zerogravity.scanner.lib_detector.subprocess.run") as mock_run:
        # First call: --exists (rc=0), second call: --modversion (rc=0, version output)
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=0, stdout="2.1.0"),
        ]
        probe = _try_pkg_config("libjpeg", _META)

    assert probe is not None
    assert probe.installed is True
    assert probe.version == "2.1.0"
    assert probe.path == "pkg-config:libjpeg"


def test_pkg_config_not_found():
    """pkg-config --exists fails (rc≠0) → returns None."""
    with patch("zerogravity.scanner.lib_detector.shutil.which", return_value="/usr/bin/pkg-config"), \
         patch("zerogravity.scanner.lib_detector.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        probe = _try_pkg_config("libjpeg", _META)

    assert probe is None


def test_pkg_config_skipped_when_no_pc_name():
    """If pkg_config is None in metadata, strategy is skipped."""
    probe = _try_pkg_config("libbz2", _META_NO_PC)
    assert probe is None


def test_pkg_config_skipped_when_not_installed():
    """If pkg-config is not on PATH, strategy is skipped."""
    with patch("zerogravity.scanner.lib_detector.shutil.which", return_value=None):
        probe = _try_pkg_config("libjpeg", _META)
    assert probe is None


# ── ldconfig strategy ────────────────────────────────────────────────────────

def test_ldconfig_found():
    """ldconfig -p lists the library → returns installed probe."""
    ldconfig_output = (
        "\tlibjpeg.so.8 (libc6,x86-64) => /usr/lib/x86_64-linux-gnu/libjpeg.so.8\n"
        "\tlibc.so.6 (libc6,x86-64) => /lib/x86_64-linux-gnu/libc.so.6\n"
    )
    with patch("zerogravity.scanner.lib_detector.platform.system", return_value="Linux"), \
         patch("zerogravity.scanner.lib_detector.shutil.which", return_value="/sbin/ldconfig"), \
         patch("zerogravity.scanner.lib_detector.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=ldconfig_output)
        probe = _try_ldconfig("libjpeg", _META)

    assert probe is not None
    assert probe.installed is True
    assert "/usr/lib/x86_64-linux-gnu/libjpeg.so.8" in (probe.path or "")


def test_ldconfig_not_found():
    """ldconfig -p does not list the library → returns None."""
    with patch("zerogravity.scanner.lib_detector.platform.system", return_value="Linux"), \
         patch("zerogravity.scanner.lib_detector.shutil.which", return_value="/sbin/ldconfig"), \
         patch("zerogravity.scanner.lib_detector.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="libc.so.6 => /lib/libc.so.6\n")
        probe = _try_ldconfig("libjpeg", _META)

    assert probe is None


def test_ldconfig_skipped_on_non_linux():
    """ldconfig is skipped on non-Linux platforms."""
    with patch("zerogravity.scanner.lib_detector.platform.system", return_value="Darwin"):
        probe = _try_ldconfig("libjpeg", _META)
    assert probe is None


# ── dpkg strategy ────────────────────────────────────────────────────────────

def test_dpkg_found():
    """dpkg -l shows 'ii' (installed) → returns probe with version."""
    dpkg_output = (
        "Desired=Unknown/Install/...\n"
        "| Status=Not/Inst/...\n"
        "||/ Name            Version       ...\n"
        "+++-===============-=============-...\n"
        "ii  libjpeg-dev     2.1.5-2       amd64 ...\n"
    )
    with patch("zerogravity.scanner.lib_detector.shutil.which", return_value="/usr/bin/dpkg"), \
         patch("zerogravity.scanner.lib_detector.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=dpkg_output)
        probe = _try_dpkg("libjpeg", _META)

    assert probe is not None
    assert probe.installed is True
    assert probe.version == "2.1.5-2"
    assert probe.path == "dpkg:libjpeg-dev"


def test_dpkg_not_found():
    """dpkg -l returns non-zero → returns None."""
    with patch("zerogravity.scanner.lib_detector.shutil.which", return_value="/usr/bin/dpkg"), \
         patch("zerogravity.scanner.lib_detector.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        probe = _try_dpkg("libjpeg", _META)

    assert probe is None


def test_dpkg_skipped_when_no_apt_name():
    """If apt is None in metadata, dpkg strategy is skipped."""
    meta = {**_META, "apt": None}
    probe = _try_dpkg("libjpeg", meta)
    assert probe is None


# ── rpm strategy ─────────────────────────────────────────────────────────────

def test_rpm_found():
    """rpm -q succeeds → returns probe with extracted version."""
    with patch("zerogravity.scanner.lib_detector.shutil.which", return_value="/usr/bin/rpm"), \
         patch("zerogravity.scanner.lib_detector.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="libjpeg-turbo-devel-2.1.4-1.el9.x86_64"
        )
        probe = _try_rpm("libjpeg", _META)

    assert probe is not None
    assert probe.installed is True
    assert probe.version == "2.1.4"


def test_rpm_not_found():
    """rpm -q returns non-zero → returns None."""
    with patch("zerogravity.scanner.lib_detector.shutil.which", return_value="/usr/bin/rpm"), \
         patch("zerogravity.scanner.lib_detector.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        probe = _try_rpm("libjpeg", _META)

    assert probe is None


def test_rpm_skipped_when_no_rpm_name():
    """If rpm is None in metadata, rpm strategy is skipped."""
    meta = {**_META, "rpm": None}
    probe = _try_rpm("libjpeg", meta)
    assert probe is None


# ── brew strategy ────────────────────────────────────────────────────────────

def test_brew_found():
    """brew list succeeds on macOS → returns installed probe."""
    with patch("zerogravity.scanner.lib_detector.platform.system", return_value="Darwin"), \
         patch("zerogravity.scanner.lib_detector.shutil.which", return_value="/usr/local/bin/brew"), \
         patch("zerogravity.scanner.lib_detector.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="/usr/local/Cellar/jpeg/9e/...")
        probe = _try_brew("libjpeg", _META)

    assert probe is not None
    assert probe.installed is True
    assert probe.path == "brew:jpeg"


def test_brew_not_found():
    """brew list returns non-zero → returns None."""
    with patch("zerogravity.scanner.lib_detector.platform.system", return_value="Darwin"), \
         patch("zerogravity.scanner.lib_detector.shutil.which", return_value="/usr/local/bin/brew"), \
         patch("zerogravity.scanner.lib_detector.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        probe = _try_brew("libjpeg", _META)

    assert probe is None


def test_brew_skipped_on_linux():
    """brew is skipped on non-Darwin platforms."""
    with patch("zerogravity.scanner.lib_detector.platform.system", return_value="Linux"):
        probe = _try_brew("libjpeg", _META)
    assert probe is None


# ── shutil.which fallback ────────────────────────────────────────────────────

def test_which_fallback_found():
    """shutil.which finds the name on PATH → returns installed probe."""
    with patch("zerogravity.scanner.lib_detector.shutil.which", return_value="/usr/local/bin/libjpeg"):
        probe = _try_which("libjpeg", _META)
    assert probe is not None
    assert probe.installed is True


def test_which_fallback_not_found():
    """shutil.which returns None → returns None."""
    with patch("zerogravity.scanner.lib_detector.shutil.which", return_value=None):
        probe = _try_which("libjpeg", _META)
    assert probe is None


# ── detect_library (orchestrator) ────────────────────────────────────────────

def test_all_strategies_fail():
    """When every strategy returns None, detect_library returns installed=False."""
    with patch("zerogravity.scanner.lib_detector.DETECTION_STRATEGIES", [
        lambda n, m: None,
        lambda n, m: None,
    ]):
        probe = detect_library("libjpeg", _META)
    assert probe.installed is False
    assert probe.name == "libjpeg"


def test_strategy_order_short_circuits():
    """First successful strategy wins — later strategies are never called."""
    first_probe = BinaryProbe(name="libjpeg", installed=True, path="pkg-config:libjpeg", version="2.1.0")
    second_called = False

    def strategy_one(name: str, meta: dict) -> BinaryProbe:
        return first_probe

    def strategy_two(name: str, meta: dict) -> BinaryProbe | None:
        nonlocal second_called
        second_called = True
        return BinaryProbe(name=name, installed=True, path="ldconfig:libjpeg")

    with patch("zerogravity.scanner.lib_detector.DETECTION_STRATEGIES", [
        strategy_one,
        strategy_two,
    ]):
        probe = detect_library("libjpeg", _META)

    assert probe is first_probe
    assert second_called is False


# ── Schema validation ────────────────────────────────────────────────────────

def test_schema_validation_missing_keys():
    """JSON missing required top-level keys raises SystemDepsSchemaError."""
    from zerogravity.resolver.binary_lookup import SystemDepsSchemaError, _validate_schema

    with pytest.raises(SystemDepsSchemaError, match="missing required top-level keys"):
        _validate_schema({"version": 1})


def test_schema_validation_bad_version():
    """Wrong schema version raises SystemDepsSchemaError."""
    from zerogravity.resolver.binary_lookup import SystemDepsSchemaError, _validate_schema

    with pytest.raises(SystemDepsSchemaError, match="unsupported schema version"):
        _validate_schema({"version": 99, "packages": {}, "library_metadata": {}})


def test_schema_validation_bad_package_value():
    """packages value that isn't a list raises SystemDepsSchemaError."""
    from zerogravity.resolver.binary_lookup import SystemDepsSchemaError, _validate_schema

    with pytest.raises(SystemDepsSchemaError, match="must be a list"):
        _validate_schema({
            "version": 1,
            "packages": {"bad": "not-a-list"},
            "library_metadata": {},
        })


def test_schema_validation_bad_metadata_type():
    """library_metadata entry with invalid type raises SystemDepsSchemaError."""
    from zerogravity.resolver.binary_lookup import SystemDepsSchemaError, _validate_schema

    with pytest.raises(SystemDepsSchemaError, match="must be one of"):
        _validate_schema({
            "version": 1,
            "packages": {},
            "library_metadata": {
                "libfoo": {
                    "type": "invalid",
                    "pkg_config": "foo",
                    "apt": "libfoo-dev",
                    "rpm": "libfoo-devel",
                    "brew": "foo",
                },
            },
        })


def test_schema_validation_missing_meta_keys():
    """library_metadata entry missing required keys raises SystemDepsSchemaError."""
    from zerogravity.resolver.binary_lookup import SystemDepsSchemaError, _validate_schema

    with pytest.raises(SystemDepsSchemaError, match="missing required keys"):
        _validate_schema({
            "version": 1,
            "packages": {},
            "library_metadata": {
                "libfoo": {"type": "library"},
            },
        })


# ── Dedup / custom_map override behaviour ────────────────────────────────────

def test_custom_map_overrides_json_data():
    """custom_map takes precedence over the JSON-loaded SYSTEM_DEPENDENCY_MAP
    — confirming the dedup/override behaviour is preserved after externalisation."""
    from zerogravity.parsers.base import Dependency, DependencyType
    from zerogravity.resolver.binary_lookup import SYSTEM_DEPENDENCY_MAP, lookup_system_deps

    # 'cryptography' is in the JSON data file mapping to ["openssl"]
    assert "cryptography" in SYSTEM_DEPENDENCY_MAP
    assert "openssl" in SYSTEM_DEPENDENCY_MAP["cryptography"]

    dep = Dependency(name="cryptography", version_spec=">=41.0.0", dep_type=DependencyType.PRODUCTION, source="test")
    # Override: custom_map says cryptography needs ["my-custom-ssl"] instead
    reqs = lookup_system_deps([dep], custom_map={"cryptography": ["my-custom-ssl"]})
    assert len(reqs) == 1
    assert reqs[0].required_binary == "my-custom-ssl"


def test_json_data_used_when_no_custom_map():
    """Without custom_map, lookup_system_deps uses the JSON-loaded data."""
    from zerogravity.parsers.base import Dependency, DependencyType
    from zerogravity.resolver.binary_lookup import lookup_system_deps

    dep = Dependency(name="cryptography", version_spec=">=41.0.0", dep_type=DependencyType.PRODUCTION, source="test")
    reqs = lookup_system_deps([dep])
    binaries = [r.required_binary for r in reqs]
    assert "openssl" in binaries
