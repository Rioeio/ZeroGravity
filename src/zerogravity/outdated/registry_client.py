"""
Registry client for querying npm and PyPI package metadata with local TTL caching.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from zerogravity import __version__

REGISTRY_CACHE_FILENAME = "registry_cache.json"
DEFAULT_TTL_SECONDS = 3600  # 1 hour
DEFAULT_TIMEOUT_SECONDS = 5


class RegistryClient:
    """
    Client for querying package registries with local disk caching and TTL validation.
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
            self.cache_file = self.cache_dir / REGISTRY_CACHE_FILENAME

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

    def _get_cached_version(self, cache_key: str, offline: bool) -> tuple[str | None, bool]:
        """
        Returns (version, is_fresh). If fresh or offline with existing cache, version is returned.
        """
        cache = self._load_cache()
        if cache_key in cache:
            entry = cache[cache_key]
            cached_version = entry.get("version")
            timestamp = entry.get("timestamp", 0)
            is_fresh = (time.time() - timestamp) < self.ttl_seconds
            if is_fresh or offline:
                return cached_version, is_fresh
        return None, False

    def _cache_version(self, cache_key: str, version: str) -> None:
        cache = self._load_cache()
        cache[cache_key] = {
            "version": version,
            "timestamp": time.time(),
        }
        self._save_cache(cache)

    def _fetch_json(self, url: str) -> dict[str, Any] | None:
        """Fetch JSON data from a URL with custom User-Agent and timeout."""
        headers = {
            "User-Agent": f"ZeroGravity/{__version__} (https://github.com/Rioeio/ZeroGravity)",
            "Accept": "application/json",
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                if response.status == 200:
                    raw_data = response.read().decode("utf-8")
                    return json.loads(raw_data)
        except Exception:
            return None
        return None

    def get_latest_npm_version(self, package_name: str, offline: bool = False) -> str | None:
        """
        Query the npm registry for the latest version of a package.
        """
        clean_name = package_name.strip()
        if not clean_name:
            return None

        cache_key = f"npm:{clean_name}"
        cached_version, is_fresh = self._get_cached_version(cache_key, offline)
        if is_fresh or (offline and cached_version is not None):
            return cached_version

        if offline:
            return None

        # Quote name for scoped packages like @scope/pkg
        encoded_name = urllib.parse.quote(clean_name, safe="@")
        url = f"https://registry.npmjs.org/{encoded_name}"

        data = self._fetch_json(url)
        if data and isinstance(data, dict):
            dist_tags = data.get("dist-tags", {})
            latest_version = dist_tags.get("latest")
            if not latest_version:
                # Fallback to top-level version or versions keys
                latest_version = data.get("version")
            if latest_version and isinstance(latest_version, str):
                self._cache_version(cache_key, latest_version)
                return latest_version

        return cached_version

    def get_latest_pypi_version(self, package_name: str, offline: bool = False) -> str | None:
        """
        Query the PyPI JSON API for the latest version of a package.
        """
        clean_name = package_name.strip()
        if not clean_name:
            return None

        cache_key = f"pypi:{clean_name.lower()}"
        cached_version, is_fresh = self._get_cached_version(cache_key, offline)
        if is_fresh or (offline and cached_version is not None):
            return cached_version

        if offline:
            return None

        encoded_name = urllib.parse.quote(clean_name)
        url = f"https://pypi.org/pypi/{encoded_name}/json"

        data = self._fetch_json(url)
        if data and isinstance(data, dict):
            info = data.get("info", {})
            latest_version = info.get("version")
            if latest_version and isinstance(latest_version, str):
                self._cache_version(cache_key, latest_version)
                return latest_version

        return cached_version
