"""
OSV.dev API batch client with local caching and resilient error handling.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from zerogravity import __version__

OSV_BATCH_ENDPOINT = "https://api.osv.dev/v1/querybatch"
OSV_CACHE_FILENAME = "osv_cache.json"
DEFAULT_TTL_SECONDS = 3600  # 1 hour
DEFAULT_TIMEOUT_SECONDS = 5
MAX_BATCH_SIZE = 500


class OSVClient:
    """
    Client for batch querying the OSV.dev vulnerability database.
    """

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
            self.cache_dir = Path.home() / ".zerogravity"
            self.cache_file = self.cache_dir / OSV_CACHE_FILENAME

        self.ttl_seconds = ttl_seconds
        self.timeout = timeout

    def _ensure_dir(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _load_cache(self) -> dict[str, Any]:
        if not self.cache_file.exists():
            return {}
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_cache(self, data: dict[str, Any]) -> None:
        self._ensure_dir()
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def query_batch(
        self,
        queries: list[dict[str, Any]],
        offline: bool = False,
    ) -> list[list[dict[str, Any]]]:
        """
        Query OSV.dev in batches for a list of {'package': {'name': str, 'ecosystem': str}, 'version': str}.

        Returns a list of vulnerability lists corresponding 1:1 to queries.
        """
        if not queries:
            return []

        results: list[list[dict[str, Any]]] = [[] for _ in queries]
        cache = self._load_cache()
        now = time.time()

        queries_to_fetch: list[tuple[int, dict[str, Any]]] = []

        for idx, q in enumerate(queries):
            pkg_name = q.get("package", {}).get("name", "")
            ecosystem = q.get("package", {}).get("ecosystem", "")
            version = q.get("version", "")
            cache_key = f"{ecosystem}:{pkg_name.lower()}:{version}"

            if cache_key in cache:
                entry = cache[cache_key]
                cached_time = entry.get("timestamp", 0)
                if (now - cached_time < self.ttl_seconds) or offline:
                    results[idx] = entry.get("vulns", [])
                    continue

            if not offline:
                queries_to_fetch.append((idx, q))

        if not queries_to_fetch or offline:
            return results

        # Process in chunks of MAX_BATCH_SIZE
        for i in range(0, len(queries_to_fetch), MAX_BATCH_SIZE):
            chunk = queries_to_fetch[i : i + MAX_BATCH_SIZE]
            chunk_queries = [q for _, q in chunk]

            payload = json.dumps({"queries": chunk_queries}).encode("utf-8")
            headers = {
                "User-Agent": f"ZeroGravity/{__version__} (https://github.com/Rioeio/ZeroGravity)",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            req = urllib.request.Request(
                OSV_BATCH_ENDPOINT,
                data=payload,
                headers=headers,
                method="POST",
            )

            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        raw_body = resp.read().decode("utf-8")
                        body_data = json.loads(raw_body)
                        chunk_results = body_data.get("results", [])

                        for (orig_idx, query_obj), res_item in zip(chunk, chunk_results, strict=False):
                            vulns = res_item.get("vulns", []) if isinstance(res_item, dict) else []
                            results[orig_idx] = vulns

                            # Cache response
                            pkg_name = query_obj.get("package", {}).get("name", "")
                            ecosystem = query_obj.get("package", {}).get("ecosystem", "")
                            version = query_obj.get("version", "")
                            cache_key = f"{ecosystem}:{pkg_name.lower()}:{version}"
                            cache[cache_key] = {
                                "vulns": vulns,
                                "timestamp": now,
                            }
            except Exception:
                # Network failures degrade gracefully: keep empty results
                continue

        self._save_cache(cache)
        return results
