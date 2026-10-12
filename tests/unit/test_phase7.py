from __future__ import annotations

import multiprocessing
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from zerogravity.cli import app
from zerogravity.outdated.registry_client import RegistryClient
from zerogravity.parsers.base import Ecosystem, ProjectManifest
from zerogravity.resolver.history import ScanHistoryManager
from zerogravity.scanner.cache import ScanCacheManager
from zerogravity.security.osv_client import OSVClient


def test_zerogravity_home_redirects_all_four_state_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom_home = tmp_path / "custom_zg_home"
    monkeypatch.setenv("ZEROGRAVITY_HOME", str(custom_home))

    hm = ScanHistoryManager()
    cm = ScanCacheManager()
    rc = RegistryClient()
    oc = OSVClient()

    assert hm.history_dir == custom_home
    assert cm.cache_dir == custom_home
    assert rc.cache_dir == custom_home
    assert oc.cache_dir == custom_home


def test_corrupt_json_quarantined_not_overwritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZEROGRAVITY_HOME", str(tmp_path))
    cache_file = tmp_path / "scan_cache.json"
    cache_file.write_text("{corrupt: json content", encoding="utf-8")

    cm = ScanCacheManager()
    # Trigger load
    raw = cm._load_raw_cache()
    assert raw == {}

    # Check that corrupt file was quarantined
    corrupt_files = list(tmp_path.glob("scan_cache.json.corrupt-*"))
    assert len(corrupt_files) == 1
    assert "{corrupt: json content" in corrupt_files[0].read_text(encoding="utf-8")

    # Save new cache and verify corrupt file is preserved
    manifest = ProjectManifest(
        project_path=tmp_path / "proj",
        project_name="proj",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[],
        engine_constraints={},
        lockfile_present=False,
        lockfile_path=None,
        manifest_files=[],
        metadata={},
    )
    cm.set(tmp_path / "proj", [manifest])
    assert cache_file.exists()
    assert len(list(tmp_path.glob("scan_cache.json.corrupt-*"))) == 1


def _worker_append(project_path_str: str, zg_home: str) -> None:
    os.environ["ZEROGRAVITY_HOME"] = zg_home
    hm = ScanHistoryManager()
    manifest = ProjectManifest(
        project_path=Path(project_path_str),
        project_name=Path(project_path_str).name,
        ecosystem=Ecosystem.PYTHON,
        dependencies=[],
        engine_constraints={},
        lockfile_present=False,
        lockfile_path=None,
        manifest_files=[],
        metadata={},
    )
    hm.save_manifests([manifest])


def test_concurrent_append_to_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZEROGRAVITY_HOME", str(tmp_path))
    hm = ScanHistoryManager()
    hm._ensure_dir()

    # Launch two separate processes concurrently appending to history
    ctx = multiprocessing.get_context("spawn")
    p1 = ctx.Process(target=_worker_append, args=(str(tmp_path / "p1"), str(tmp_path)))
    p2 = ctx.Process(target=_worker_append, args=(str(tmp_path / "p2"), str(tmp_path)))

    p1.start()
    p2.start()
    p1.join(timeout=10)
    p2.join(timeout=10)

    assert p1.exitcode == 0
    assert p2.exitcode == 0

    entries = hm.get_history_entries()
    assert str(tmp_path / "p1") in entries
    assert str(tmp_path / "p2") in entries


def test_bounded_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZEROGRAVITY_HOME", str(tmp_path))
    hm = ScanHistoryManager(max_entries=3)

    manifests = [
        ProjectManifest(
            project_path=tmp_path / f"proj_{i}",
            project_name=f"proj_{i}",
            ecosystem=Ecosystem.PYTHON,
            dependencies=[],
            engine_constraints={},
            lockfile_present=False,
            lockfile_path=None,
            manifest_files=[],
            metadata={},
        )
        for i in range(5)
    ]
    for m in manifests:
        hm.save_manifests([m])

    entries = hm.get_history_entries()
    assert len(entries) == 3


def test_state_doctor_empty_and_populated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    monkeypatch.setenv("ZEROGRAVITY_HOME", str(tmp_path))

    # Empty state dir
    result = runner.invoke(app, ["state", "doctor"])
    assert result.exit_code == 0
    assert "ZeroGravity State Doctor" in result.output
    assert "scan_history.json" in result.output

    # Create dummy corrupt file and populated file
    (tmp_path / "scan_cache.json").write_text('{"foo": "bar"}', encoding="utf-8")
    (tmp_path / "scan_history.json.corrupt-12345").write_text("corrupted", encoding="utf-8")

    result = runner.invoke(app, ["state", "doctor"])
    assert result.exit_code == 0
    assert "scan_history.json.corrupt-12345" in result.output

    # Test pruning
    result_prune = runner.invoke(app, ["state", "doctor", "--prune"])
    assert result_prune.exit_code == 0
    assert not (tmp_path / "scan_history.json.corrupt-12345").exists()
