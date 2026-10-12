"""
Shared HTTP client helper using stdlib urllib with timeouts, retries, and backoff.
"""

from __future__ import annotations

import email.utils
import json
import random
import time
import urllib.error
import urllib.request
from typing import Any

from zerogravity import __version__

DEFAULT_USER_AGENT = f"ZeroGravity/{__version__} (+https://github.com/Rioeio/ZeroGravity)"
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class NetworkError(Exception):
    """Base network error for ZeroGravity HTTP operations."""


class NetworkNotAllowedError(NetworkError):
    """Raised when an unmocked external network connection is attempted in tests."""


class HTTPError(NetworkError):
    """HTTP error with status code."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _parse_retry_after(header_val: str | None) -> float | None:
    """Parse Retry-After header as seconds or HTTP-date."""
    if not header_val:
        return None
    try:
        return max(0.0, float(header_val.strip()))
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(header_val)
        return max(0.0, (dt.timestamp() - time.time()))
    except Exception:
        return None


def request_json(
    url: str,
    method: str = "GET",
    data: Any = None,
    headers: dict[str, str] | None = None,
    timeout: float = 5.0,
    max_retries: int = 3,
    backoff_factor: float = 0.5,
) -> Any:
    """
    Perform an HTTP request with exponential backoff and jitter on 429/5xx, returning JSON.
    """
    req_headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json",
    }
    if headers:
        req_headers.update(headers)

    body_bytes: bytes | None = None
    if data is not None:
        body_bytes = json.dumps(data).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    for attempt in range(1, max_retries + 2):
        req = urllib.request.Request(
            url,
            data=body_bytes,
            headers=req_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw_bytes = resp.read()
                if not raw_bytes:
                    return None
                return json.loads(raw_bytes.decode("utf-8"))
        except urllib.error.HTTPError as err:
            status_code = err.code
            if status_code in RETRY_STATUS_CODES and attempt <= max_retries:
                retry_after = _parse_retry_after(err.headers.get("Retry-After"))
                if retry_after is not None:
                    sleep_time = min(retry_after, 30.0)
                else:
                    sleep_time = backoff_factor * (2 ** (attempt - 1)) + random.uniform(0, 0.25)
                time.sleep(sleep_time)
                continue
            raise HTTPError(f"HTTP {status_code} requesting {url}: {err.reason}", status_code=status_code) from err
        except urllib.error.URLError as err:
            if attempt <= max_retries:
                sleep_time = backoff_factor * (2 ** (attempt - 1)) + random.uniform(0, 0.25)
                time.sleep(sleep_time)
                continue
            raise NetworkError(f"Network error requesting {url}: {err.reason}") from err
        except (TimeoutError, OSError) as err:
            if attempt <= max_retries:
                sleep_time = backoff_factor * (2 ** (attempt - 1)) + random.uniform(0, 0.25)
                time.sleep(sleep_time)
                continue
            raise NetworkError(f"Connection error requesting {url}: {err}") from err
