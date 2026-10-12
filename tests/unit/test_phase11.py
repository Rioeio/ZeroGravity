from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from zerogravity.parsers.base import Ecosystem, ProjectManifest
from zerogravity.resolver.history import ScanHistoryManager
from zerogravity.time import parse_utc_iso, to_utc_iso, utc_now


def test_utc_now_returns_aware_utc() -> None:
    now = utc_now()
    assert now.tzinfo is not None
    assert now.tzinfo == timezone.utc


def test_to_utc_iso_ends_in_z() -> None:
    iso = to_utc_iso()
    assert iso.endswith("Z")
    assert "+00:00" not in iso
    # Also for explicit datetime
    dt = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    assert to_utc_iso(dt) == "2025-01-15T10:30:00Z"


def test_parse_utc_iso_handles_formats() -> None:
    dt1 = parse_utc_iso("2025-01-15T10:30:00Z")
    assert dt1.tzinfo == timezone.utc
    assert dt1.hour == 10

    dt2 = parse_utc_iso("2025-01-15T12:30:00+02:00")
    assert dt2.tzinfo == timezone.utc
    assert dt2.hour == 10  # 12:30 +02:00 == 10:30 UTC

    dt3 = parse_utc_iso("2025-01-15T10:30:00")
    assert dt3.tzinfo == timezone.utc
    assert dt3.hour == 10


def test_history_records_utc_iso_and_respects_timezone_order(tmp_path: Path) -> None:
    mgr = ScanHistoryManager(history_dir=tmp_path)
    # Simulate historical entries with different timezones
    # Earlier event in UTC+5: 2025-01-15T14:00:00+05:00 == 09:00 UTC
    # Later event in UTC-5: 2025-01-15T06:00:00-05:00 == 11:00 UTC
    earlier_str = "2025-01-15T14:00:00+05:00"
    later_str = "2025-01-15T06:00:00-05:00"

    p_early = parse_utc_iso(earlier_str)
    p_late = parse_utc_iso(later_str)
    assert p_early < p_late

    # Saving manifests records timestamps ending in Z
    m = ProjectManifest(project_path=tmp_path, ecosystem=Ecosystem.NODE, dependencies=[])
    mgr.save_manifests([m])
    history_data = mgr.get_history()
    assert len(history_data) >= 1
    for key, entry in history_data.items():
        assert entry["timestamp"].endswith("Z")

    # get_recent_scans compares against cutoff without TypeError
    recent = mgr.get_recent_scans(max_age_days=1)
    assert len(recent) >= 1


def test_no_bare_datetime_now_or_utcnow() -> None:
    src_dir = Path("src/zerogravity")
    bare_now_pattern = re.compile(r"datetime\.now\(\s*\)")
    utcnow_pattern = re.compile(r"datetime\.utcnow")

    violations: list[str] = []
    for py_file in src_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for line_no, line in enumerate(content.splitlines(), 1):
            if bare_now_pattern.search(line):
                violations.append(f"{py_file}:{line_no}: bare datetime.now(): {line}")
            if utcnow_pattern.search(line):
                violations.append(f"{py_file}:{line_no}: deprecated datetime.utcnow(): {line}")

    assert not violations, "Found bare datetime.now() or datetime.utcnow():\n" + "\n".join(violations)


def test_legacy_naive_history_loads_and_prunes(tmp_path: Path) -> None:
    import json
    from datetime import timedelta

    history_file = tmp_path / "scan_history.json"
    p1 = tmp_path / "proj1"
    p2 = tmp_path / "proj2"
    p1.mkdir()
    p2.mkdir()

    legacy_data = {
        str(p1): {
            "project_path": str(p1),
            "project_name": "proj1",
            "ecosystem": "node",
            "engine_constraints": {},
            "dependencies_summary": 1,
            "timestamp": "2020-01-01T12:00:00",
        },
        str(p2): {
            "project_path": str(p2),
            "project_name": "proj2",
            "ecosystem": "node",
            "engine_constraints": {},
            "dependencies_summary": 2,
            "timestamp": (utc_now() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S"),
        },
    }
    history_file.write_text(json.dumps(legacy_data), encoding="utf-8")

    mgr = ScanHistoryManager(history_dir=tmp_path)
    recent = mgr.load_recent_manifests(max_age_days=5)
    assert len(recent) == 1
    assert recent[0].project_path == p2

    mgr.max_entries = 1
    p3 = tmp_path / "proj3"
    p3.mkdir()
    m3 = ProjectManifest(project_path=p3, ecosystem=Ecosystem.NODE, dependencies=[])
    mgr.save_manifests([m3])
    entries = mgr.get_history()
    assert len(entries) == 1
    assert str(p3) in entries
