from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from zerogravity.parsers.base import Dependency, DependencyType, Ecosystem, ProjectManifest
from zerogravity.security.models import VulnerabilitySeverity
from zerogravity.security.osv_client import OSVClient
from zerogravity.security.scanner import _parse_severity, scan_vulnerabilities

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "data" / "osv"


def test_cvss_vector_scoring():
    """Verify CVSS v3.1 calculation and severity thresholds, v4 unknown, unrecognized unknown."""
    # 1. Critical vector
    crit_vuln = {
        "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
    }
    sev, _ = _parse_severity(crit_vuln)
    assert sev == VulnerabilitySeverity.CRITICAL

    # 2. Medium vector (must NOT be CRITICAL)
    med_vuln = {
        "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:L/AC:H/PR:H/UI:R/S:U/C:H/I:H/A:H"}],
    }
    sev, _ = _parse_severity(med_vuln)
    assert sev == VulnerabilitySeverity.MEDIUM

    # 3. CVSS v4 vector without usable severity -> UNKNOWN
    v4_vuln = {
        "severity": [{"type": "CVSS_V4", "score": "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N"}],
    }
    sev, _ = _parse_severity(v4_vuln)
    assert sev == VulnerabilitySeverity.UNKNOWN

    # 4. Unrecognized severity string -> UNKNOWN
    bad_str_vuln = {
        "database_specific": {"severity": "SUPER_CRITICAL_CUSTOM"},
    }
    sev, _ = _parse_severity(bad_str_vuln)
    assert sev == VulnerabilitySeverity.UNKNOWN


def test_osv_hydrates_real_shape_records(tmp_path: Path):
    """OSV querybatch stub response is hydrated with GET /v1/vulns/{id}."""
    stub_data = json.loads((FIXTURES_DIR / "querybatch_stub.json").read_text(encoding="utf-8"))
    full_data = json.loads((FIXTURES_DIR / "vuln_ghsa_p6mc.json").read_text(encoding="utf-8"))

    client = OSVClient(cache_file=tmp_path / "osv_cache.json")

    manifest = ProjectManifest(
        project_path=tmp_path / "app",
        project_name="app",
        ecosystem=Ecosystem.NODE,
        dependencies=[
            Dependency(
                name="lodash",
                version_spec="4.17.15",
                resolved_version="4.17.15",
                dep_type=DependencyType.PRODUCTION,
            ),
        ],
    )

    def fake_request_json(url, *args, **kwargs):
        if "querybatch" in url:
            return stub_data
        if "GHSA-p6mc-m468-83gw" in url:
            return full_data
        raise ValueError(f"Unexpected url: {url}")

    with patch("zerogravity.net.request_json", side_effect=fake_request_json):
        report = scan_vulnerabilities([manifest], osv_client=client)

    assert report.total_vulnerabilities == 1
    adv = report.advisories[0]
    assert adv.id == "GHSA-p6mc-m468-83gw"
    assert adv.cve_id == "CVE-2020-8203"
    assert "Prototype Pollution" in adv.summary
    assert adv.severity == VulnerabilitySeverity.HIGH


def test_osv_pagination(tmp_path: Path):
    """OSV client follows next_page_token and hydrates all returned advisories."""
    page1 = json.loads((FIXTURES_DIR / "page1_response.json").read_text(encoding="utf-8"))
    page2 = json.loads((FIXTURES_DIR / "page2_response.json").read_text(encoding="utf-8"))

    client = OSVClient(cache_file=tmp_path / "osv_cache.json")

    def fake_request_json(url, *args, **kwargs):
        data = kwargs.get("data") or {}
        queries = data.get("queries", [])
        if "querybatch" in url:
            if queries and queries[0].get("page_token") == "token-page-2":
                return page2
            return page1
        if "VULN-PAGE-1" in url:
            return {"id": "VULN-PAGE-1", "summary": "Page 1 vuln"}
        if "VULN-PAGE-2" in url:
            return {"id": "VULN-PAGE-2", "summary": "Page 2 vuln"}
        raise ValueError(f"Unexpected url: {url}")

    queries = [{"package": {"name": "foo", "ecosystem": "npm"}, "version": "1.0.0"}]
    with patch("zerogravity.net.request_json", side_effect=fake_request_json):
        results = client.query_batch(queries)

    assert len(results) == 1
    assert len(results[0]) == 2
    vuln_ids = [v["id"] for v in results[0]]
    assert "VULN-PAGE-1" in vuln_ids
    assert "VULN-PAGE-2" in vuln_ids


def test_net_http_retry_429_then_200():
    """Shared net helper retries 429 with Retry-After and returns 200 response."""
    from zerogravity.net import request_json

    calls = 0

    class DummyResponse:
        def __init__(self, body: bytes):
            self.status = 200
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    import io
    import urllib.error

    def fake_urlopen(req, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            headers = {"Retry-After": "0.01"}
            hdrs_mock = MagicMock()
            hdrs_mock.get.side_effect = lambda k, default=None: headers.get(k, default)
            raise urllib.error.HTTPError("http://example.com", 429, "Too Many Requests", hdrs_mock, io.BytesIO(b""))
        return DummyResponse(b'{"success": true}')

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        with patch("time.sleep") as mock_sleep:
            res = request_json("http://example.com")
            assert res == {"success": True}
            assert calls == 2
            mock_sleep.assert_called()


def test_range_only_dependency_not_queried_at_floor(tmp_path: Path):
    """A dependency with only a range spec is unresolved and never queried at the range floor."""
    client = OSVClient(cache_file=tmp_path / "osv_cache.json")

    manifest = ProjectManifest(
        project_path=tmp_path / "app",
        project_name="app",
        ecosystem=Ecosystem.PYTHON,
        dependencies=[
            Dependency(
                name="requests",
                version_spec=">=2.0.0",
                resolved_version=None,
                dep_type=DependencyType.PRODUCTION,
            ),
        ],
    )

    with patch.object(client, "query_batch") as mock_query_batch:
        report = scan_vulnerabilities([manifest], osv_client=client)
        mock_query_batch.assert_not_called()
        assert report.scanned_packages == 0
