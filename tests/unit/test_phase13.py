from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

from zerogravity.net import show_network_notice_once
from zerogravity.outdated.checker import check_outdated_dependencies, is_private_dependency
from zerogravity.outdated.registry_client import RegistryClient
from zerogravity.parsers.base import Dependency, Ecosystem, ProjectManifest


def test_concurrent_network_queries_300_deps(tmp_path: Path) -> None:
    # 300 dependencies fixture
    deps = [
        Dependency(name=f"pkg-{i}", resolved_version="1.0.0", metadata={"transitive": False})
        for i in range(300)
    ]
    manifest = ProjectManifest(project_path=tmp_path, ecosystem=Ecosystem.PYTHON, dependencies=deps)

    active_calls = 0
    max_observed_concurrency = 0
    lock = threading.Lock()

    def mock_fetch(url: str, **kwargs):
        nonlocal active_calls, max_observed_concurrency
        with lock:
            active_calls += 1
            if active_calls > max_observed_concurrency:
                max_observed_concurrency = active_calls
        time.sleep(0.01)
        with lock:
            active_calls -= 1
        return {"info": {"version": "2.0.0"}}

    client = RegistryClient(cache_file=tmp_path / "cache.json")
    with patch("zerogravity.outdated.registry_client.request_json", side_effect=mock_fetch):
        report = check_outdated_dependencies([manifest], offline=False, registry_client=client, max_workers=8)

    assert len(report.packages) == 300
    assert max_observed_concurrency > 1, f"Expected concurrent calls, got max concurrency {max_observed_concurrency}"


def test_unresolved_dependencies_reported_not_queried(tmp_path: Path) -> None:
    # Dependency has only version_spec, no resolved_version
    dep = Dependency(name="unresolved-pkg", version_spec=">=1.0.0", resolved_version=None)
    manifest = ProjectManifest(project_path=tmp_path, ecosystem=Ecosystem.PYTHON, dependencies=[dep])

    with patch("zerogravity.outdated.registry_client.request_json") as mock_req:
        report = check_outdated_dependencies([manifest], offline=False)
        mock_req.assert_not_called()

    assert "unresolved-pkg" in report.unresolved
    assert len(report.packages) == 0


def test_transitive_scoped_by_default(tmp_path: Path) -> None:
    direct_dep = Dependency(name="direct-pkg", resolved_version="1.0.0", metadata={"transitive": False})
    trans_dep = Dependency(name="trans-pkg", resolved_version="1.0.0", metadata={"transitive": True})
    manifest = ProjectManifest(
        project_path=tmp_path,
        ecosystem=Ecosystem.PYTHON,
        dependencies=[direct_dep, trans_dep],
    )

    requested_urls: list[str] = []

    def mock_fetch(url: str, **kwargs):
        requested_urls.append(url)
        return {"info": {"version": "2.0.0"}}

    client = RegistryClient(cache_file=tmp_path / "cache.json")
    with patch("zerogravity.outdated.registry_client.request_json", side_effect=mock_fetch):
        # Default: only direct dependencies
        rep_direct = check_outdated_dependencies([manifest], offline=False, registry_client=client, include_transitive=False)
        assert rep_direct.scanned_dependencies == 1
        assert any("direct-pkg" in u for u in requested_urls)
        assert not any("trans-pkg" in u for u in requested_urls)

        # With include_transitive=True
        requested_urls.clear()
        rep_all = check_outdated_dependencies([manifest], offline=False, registry_client=client, include_transitive=True)
        assert rep_all.scanned_dependencies == 2
        assert any("trans-pkg" in u for u in requested_urls)


def test_crates_io_and_go_proxy_support(tmp_path: Path) -> None:
    client = RegistryClient(cache_file=tmp_path / "cache.json")

    # Crates.io
    with patch("zerogravity.outdated.registry_client.request_json") as mock_req:
        mock_req.return_value = {"crate": {"max_version": "1.0.50"}}
        ver = client.get_latest_crates_version("serde")
        assert ver == "1.0.50"
        url, kwargs = mock_req.call_args[0][0], mock_req.call_args[1]
        assert "crates.io/api/v1/crates/serde" in url
        assert "User-Agent" in kwargs.get("headers", {})

    # Go proxy with case-escaping
    with patch("zerogravity.outdated.registry_client.request_json") as mock_req:
        mock_req.return_value = {"Version": "v1.4.2"}
        ver = client.get_latest_go_version("github.com/Azure/azure-sdk")
        assert ver in ("1.4.2", "v1.4.2")
        url = mock_req.call_args[0][0]
        assert "github.com/!azure/azure-sdk/@latest" in url


def test_privacy_guard_skips_private_registries(tmp_path: Path) -> None:
    # 1. Private npm package via .npmrc or internal host
    npm_internal = Dependency(
        name="@mycorp/secret-lib",
        resolved_version="1.0.0",
        metadata={"resolved": "https://npm.corp.internal/secret-lib/-1.0.0.tgz"},
    )
    npm_manifest = ProjectManifest(project_path=tmp_path, ecosystem=Ecosystem.NODE, dependencies=[npm_internal])
    assert is_private_dependency(npm_internal, npm_manifest) is True

    # 2. Private python source
    py_internal = Dependency(
        name="internal-utils",
        resolved_version="0.5.0",
        metadata={"source": {"type": "git", "git": "https://github.com/mycorp/utils"}},
    )
    py_manifest = ProjectManifest(project_path=tmp_path, ecosystem=Ecosystem.PYTHON, dependencies=[py_internal])
    assert is_private_dependency(py_internal, py_manifest) is True

    # 3. Private Go module via GOPRIVATE
    go_internal = Dependency(
        name="corp.internal/tools/logger",
        resolved_version="v0.1.0",
    )
    go_manifest = ProjectManifest(project_path=tmp_path, ecosystem=Ecosystem.GO, dependencies=[go_internal])
    with patch.dict(os.environ, {"GOPRIVATE": "corp.internal/*"}):
        assert is_private_dependency(go_internal, go_manifest) is True

    # Check outdated skips private dependencies and records them
    with patch("zerogravity.outdated.registry_client.request_json") as mock_req:
        report = check_outdated_dependencies([npm_manifest, py_manifest], offline=False)
        mock_req.assert_not_called()
    assert len(report.packages) == 0
    assert len(report.private_skipped) >= 2


def test_one_time_network_notice(tmp_path: Path) -> None:
    # Notice shown once per state directory
    captured_messages: list[str] = []

    def mock_print(msg: str):
        captured_messages.append(msg)

    first_shown = show_network_notice_once(state_dir=tmp_path, printer=mock_print)
    assert first_shown is True
    assert len(captured_messages) == 1
    assert "public registries" in captured_messages[0].lower()

    # Second call does not print
    captured_messages.clear()
    second_shown = show_network_notice_once(state_dir=tmp_path, printer=mock_print)
    assert second_shown is False
    assert len(captured_messages) == 0


def test_network_config_disabled(tmp_path: Path) -> None:
    # When network.enabled is false in config, network requests are skipped without error
    (tmp_path / ".zerogravity.toml").write_text("[network]\nenabled = false\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        '{"name": "test-pkg", "version": "1.0.0", "dependencies": {"lodash": "4.17.21"}}',
        encoding="utf-8",
    )
    (tmp_path / "package-lock.json").write_text(
        '{"name": "test-pkg", "version": "1.0.0", "lockfileVersion": 3, "packages": {"node_modules/lodash": {"version": "4.17.21"}}}',
        encoding="utf-8",
    )
    from zerogravity.config import load_config
    cfg = load_config(tmp_path)
    assert cfg.network_enabled is False

    from typer.testing import CliRunner

    from zerogravity.cli import app

    runner = CliRunner()
    with patch("zerogravity.outdated.registry_client.request_json") as mock_req:
        result = runner.invoke(app, ["outdated", str(tmp_path)])
        assert result.exit_code == 0
        mock_req.assert_not_called()


def test_cli_include_transitive_flag(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name": "test-pkg", "version": "1.0.0", "dependencies": {"direct-lib": "1.0.0"}}',
        encoding="utf-8",
    )
    (tmp_path / "package-lock.json").write_text(
        '{"name": "test-pkg", "version": "1.0.0", "lockfileVersion": 3, "packages": {'
        '"node_modules/direct-lib": {"version": "1.0.0"},'
        '"node_modules/trans-lib": {"version": "1.0.0"}'
        '}}',
        encoding="utf-8",
    )
    from typer.testing import CliRunner

    from zerogravity.cli import app

    runner = CliRunner()
    # Default direct only
    with patch("zerogravity.outdated.registry_client.request_json") as mock_req:
        mock_req.return_value = {"dist-tags": {"latest": "1.0.0"}}
        res = runner.invoke(app, ["outdated", str(tmp_path), "--format", "json"])
        assert res.exit_code == 0
        calls = [c[0][0] for c in mock_req.call_args_list]
        assert any("direct-lib" in u for u in calls)
        assert not any("trans-lib" in u for u in calls)

    # With --include-transitive
    with patch("zerogravity.outdated.registry_client.request_json") as mock_req:
        mock_req.return_value = {"dist-tags": {"latest": "1.0.0"}}
        res = runner.invoke(app, ["outdated", str(tmp_path), "--include-transitive", "--format", "json"])
        assert res.exit_code == 0
        calls = [c[0][0] for c in mock_req.call_args_list]
        assert any("trans-lib" in u for u in calls)

