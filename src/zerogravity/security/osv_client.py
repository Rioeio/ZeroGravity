"""
OSV.dev API batch client with local caching, pagination, hydration, and resilient error handling.
"""

from __future__ import annotations

import concurrent.futures
import time
from pathlib import Path
from typing import Any

from zerogravity import net
from zerogravity.state import (
    atomic_write_json,
    ensure_state_dir,
    file_lock,
    get_lock_path,
    get_state_dir,
    load_json,
)

OSV_BATCH_ENDPOINT = "https://api.osv.dev/v1/querybatch"
OSV_VULN_ENDPOINT = "https://api.osv.dev/v1/vulns"
OSV_CACHE_FILENAME = "osv_cache.json"
DEFAULT_TTL_SECONDS = 3600  # 1 hour
DEFAULT_TIMEOUT_SECONDS = 5
MAX_BATCH_SIZE = 500
MAX_PAGES = 10
HYDRATION_WORKERS = 8


class OSVClient:
    """Client for batch querying and hydrating records from the OSV.dev vulnerability database."""

    def __init__(
        self,
        cache_file: Path | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if cache_file is not None:
            self.cache_file = Path(cache_file)
            self.cache_dir = self.cache_file.parent
        else:
            self.cache_dir = get_state_dir()
            self.cache_file = self.cache_dir / OSV_CACHE_FILENAME

        self.lock_file = get_lock_path(self.cache_file)
        self.ttl_seconds = ttl_seconds
        self.timeout = timeout
        self.errors: list[str] = []
        self.complete: bool = True

    def _ensure_dir(self) -> None:
        ensure_state_dir(self.cache_dir)

    def _load_cache(self) -> dict[str, Any]:
        data = load_json(self.cache_file, default={})
        return data if isinstance(data, dict) else {}

    def _save_cache(self, data: dict[str, Any]) -> None:
        self._ensure_dir()
        with file_lock(self.lock_file):
            atomic_write_json(self.cache_file, data)

    def _hydrate_vuln(self, vuln_id: str) -> dict[str, Any] | None:
        """Fetch full vulnerability record for a single vulnerability ID."""
        url = f"{OSV_VULN_ENDPOINT}/{vuln_id}"
        try:
            data = net.request_json(url, method="GET", timeout=self.timeout)
            if isinstance(data, dict):
                return data
        except (net.NetworkError, Exception) as err:
            self.errors.append(f"Failed to hydrate {vuln_id}: {err}")
            self.complete = False
        return None

    def query_batch(
        self,
        queries: list[dict[str, Any]],
        offline: bool = False,
        no_cache: bool = False,
    ) -> list[list[dict[str, Any]]]:
        """
        Query OSV.dev in batches, follow pagination tokens, and hydrate full vulnerability records.
        """
        if not queries:
            return []

        results: list[list[dict[str, Any]]] = [[] for _ in queries]
        cache = self._load_cache() if not no_cache else {}
        now = time.time()

        queries_to_fetch: list[tuple[int, dict[str, Any]]] = []

        for idx, q in enumerate(queries):
            pkg_name = q.get("package", {}).get("name", "")
            ecosystem = q.get("package", {}).get("ecosystem", "")
            version = q.get("version", "")
            cache_key = f"{ecosystem}:{pkg_name.lower()}:{version}"

            if not no_cache and cache_key in cache:
                entry = cache[cache_key]
                cached_time = entry.get("timestamp", 0)
                if (now - cached_time < self.ttl_seconds) or offline:
                    results[idx] = entry.get("vulns", [])
                    continue

            if not offline:
                queries_to_fetch.append((idx, q))

        if not queries_to_fetch or offline:
            return results

        vulns_by_orig_idx: dict[int, list[dict[str, Any]]] = {idx: [] for idx, _ in queries_to_fetch}

        # Process queries in chunks of MAX_BATCH_SIZE
        for i in range(0, len(queries_to_fetch), MAX_BATCH_SIZE):
            chunk = queries_to_fetch[i : i + MAX_BATCH_SIZE]
            chunk_queries = [q for _, q in chunk]

            try:
                body_data = net.request_json(
                    OSV_BATCH_ENDPOINT,
                    method="POST",
                    data={"queries": chunk_queries},
                    timeout=self.timeout,
                )
            except (net.NetworkError, Exception) as err:
                self.errors.append(f"OSV batch query failed: {err}")
                self.complete = False
                continue

            if not isinstance(body_data, dict):
                continue

            chunk_results = body_data.get("results", [])
            if len(chunk) != len(chunk_results):
                raise ValueError(
                    f"OSV batch response length mismatch: expected {len(chunk)}, got {len(chunk_results)}"
                )

            # Collect stubs and identify queries needing pagination
            paginated_queries: list[tuple[int, dict[str, Any], str]] = []
            for (orig_idx, query_obj), res_item in zip(chunk, chunk_results):
                if not isinstance(res_item, dict):
                    continue
                vulns = res_item.get("vulns", [])
                if isinstance(vulns, list):
                    vulns_by_orig_idx[orig_idx].extend(vulns)
                token = res_item.get("next_page_token")
                if token and isinstance(token, str):
                    paginated_queries.append((orig_idx, query_obj, token))

            page_round = 0
            while paginated_queries and page_round < MAX_PAGES:
                page_round += 1
                next_batch_queries = [
                    {**q_obj, "page_token": tok}
                    for _, q_obj, tok in paginated_queries
                ]
                try:
                    page_body = net.request_json(
                        OSV_BATCH_ENDPOINT,
                        method="POST",
                        data={"queries": next_batch_queries},
                        timeout=self.timeout,
                    )
                except (net.NetworkError, Exception) as err:
                    self.errors.append(f"OSV paginated query failed: {err}")
                    self.complete = False
                    break

                if not isinstance(page_body, dict):
                    break

                page_results = page_body.get("results", [])
                if len(paginated_queries) != len(page_results):
                    raise ValueError(
                        f"OSV batch response length mismatch: expected {len(paginated_queries)}, got {len(page_results)}"
                    )

                next_paginated_queries: list[tuple[int, dict[str, Any], str]] = []
                for (orig_idx, q_obj, _), res_item in zip(paginated_queries, page_results):
                    if not isinstance(res_item, dict):
                        continue
                    vulns = res_item.get("vulns", [])
                    if isinstance(vulns, list):
                        vulns_by_orig_idx[orig_idx].extend(vulns)
                    token = res_item.get("next_page_token")
                    if token and isinstance(token, str):
                        next_paginated_queries.append((orig_idx, q_obj, token))
                paginated_queries = next_paginated_queries

        # Collect unique vuln IDs needing hydration
        stubs_to_hydrate: dict[str, str] = {}  # vuln_id -> modified
        for vulns in vulns_by_orig_idx.values():
            for v in vulns:
                if isinstance(v, dict) and "id" in v:
                    vid = v["id"]
                    mod = v.get("modified", "")
                    stubs_to_hydrate[vid] = mod

        hydrated_cache = cache.setdefault("__hydrated__", {})
        ids_to_fetch = [
            vid
            for vid, mod in stubs_to_hydrate.items()
            if vid not in hydrated_cache or hydrated_cache[vid].get("modified") != mod
        ]

        if ids_to_fetch:
            with concurrent.futures.ThreadPoolExecutor(max_workers=HYDRATION_WORKERS) as executor:
                future_to_id = {
                    executor.submit(self._hydrate_vuln, vid): vid
                    for vid in ids_to_fetch
                }
                for future in concurrent.futures.as_completed(future_to_id):
                    vid = future_to_id[future]
                    try:
                        record = future.result()
                        if record is not None:
                            hydrated_cache[vid] = {
                                "modified": stubs_to_hydrate.get(vid, ""),
                                "data": record,
                            }
                    except Exception as err:
                        self.errors.append(f"Error hydrating {vid}: {err}")
                        self.complete = False

        # Build final hydrated results and update cache
        for orig_idx, query_obj in queries_to_fetch:
            raw_stubs = vulns_by_orig_idx.get(orig_idx, [])
            hydrated_list: list[dict[str, Any]] = []
            for stub in raw_stubs:
                vid = stub.get("id")
                if vid and vid in hydrated_cache:
                    hydrated_list.append(hydrated_cache[vid]["data"])
                else:
                    hydrated_list.append(stub)

            results[orig_idx] = hydrated_list

            pkg_name = query_obj.get("package", {}).get("name", "")
            ecosystem = query_obj.get("package", {}).get("ecosystem", "")
            version = query_obj.get("version", "")
            cache_key = f"{ecosystem}:{pkg_name.lower()}:{version}"
            cache[cache_key] = {
                "vulns": hydrated_list,
                "timestamp": now,
            }

        if queries_to_fetch and not no_cache:
            self._ensure_dir()
            with file_lock(self.lock_file):
                disk_cache = load_json(self.cache_file, default={})
                if not isinstance(disk_cache, dict):
                    disk_cache = {}
                disk_cache.update(cache)
                atomic_write_json(self.cache_file, disk_cache)
        return results
