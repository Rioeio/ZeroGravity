"""
Registry client for querying npm and PyPI package metadata with local TTL caching.
"""

from __future__ import annotations

import time
import urllib.parse
from pathlib import Path
from typing import Any

from zerogravity.net import NetworkError, request_json
from zerogravity.state import (
    atomic_write_json,
    ensure_state_dir,
    file_lock,
    get_lock_path,
    get_state_dir,
    load_json,
)

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
            self.cache_dir = get_state_dir()
            self.cache_file = self.cache_dir / REGISTRY_CACHE_FILENAME

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
        self._ensure_dir()
        with file_lock(self.lock_file):
            cache = load_json(self.cache_file, default={})
            if not isinstance(cache, dict):
                cache = {}
            cache[cache_key] = {
                "version": version,
                "timestamp": time.time(),
            }
            atomic_write_json(self.cache_file, cache)

    def _fetch_json(self, url: str) -> dict[str, Any] | None:
        """Fetch JSON data from a URL using shared net helper."""
        try:
            data = request_json(url, method="GET", timeout=self.timeout)
            if isinstance(data, dict):
                return data
        except (NetworkError, OSError, ValueError) as err:
            self.errors.append(f"Registry request failed for {url}: {err}")
            self.complete = False
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

    def get_latest_crates_version(self, package_name: str, offline: bool = False) -> str | None:
        """Query crates.io API for the latest version of a Rust crate."""
        clean_name = package_name.strip()
        if not clean_name:
            return None

        cache_key = f"cargo:{clean_name.lower()}"
        cached_version, is_fresh = self._get_cached_version(cache_key, offline)
        if is_fresh or (offline and cached_version is not None):
            return cached_version

        if offline:
            return None

        url = f"https://crates.io/api/v1/crates/{urllib.parse.quote(clean_name)}"
        headers = {"User-Agent": "ZeroGravity/0.3.0 (+https://github.com/Rioeio/ZeroGravity)"}

        try:
            data = request_json(url, method="GET", headers=headers, timeout=self.timeout)
            if data and isinstance(data, dict):
                crate_info = data.get("crate", {})
                latest_version = crate_info.get("max_version") or crate_info.get("newest_version")
                if latest_version and isinstance(latest_version, str):
                    self._cache_version(cache_key, latest_version)
                    return latest_version
        except (NetworkError, OSError, ValueError) as err:
            self.errors.append(f"Registry request failed for {url}: {err}")
            self.complete = False
            return None

        return cached_version

    def get_latest_go_version(self, module_path: str, offline: bool = False) -> str | None:
        """Query Go module proxy for the latest version with case-escaping."""
        clean_path = module_path.strip()
        if not clean_path:
            return None

        cache_key = f"go:{clean_path.lower()}"
        cached_version, is_fresh = self._get_cached_version(cache_key, offline)
        if is_fresh or (offline and cached_version is not None):
            return cached_version

        if offline:
            return None

        escaped_path = "".join("!" + c.lower() if "A" <= c <= "Z" else c for c in clean_path)
        url = f"https://proxy.golang.org/{escaped_path}/@latest"

        data = self._fetch_json(url)
        if data and isinstance(data, dict):
            raw_ver = data.get("Version")
            if raw_ver and isinstance(raw_ver, str):
                latest_version = raw_ver.lstrip("v")
                self._cache_version(cache_key, latest_version)
                return latest_version

        return cached_version
