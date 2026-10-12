"""
Time and timestamp utilities for ZeroGravity.

Provides timezone-aware UTC datetime helpers and canonical ISO 8601 representations.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


utcnow = utc_now


def to_utc_iso(dt: datetime | None = None) -> str:
    """Return canonical ISO 8601 string with trailing Z in UTC (RFC 3339)."""
    if dt is None:
        dt = utc_now()
    elif dt.tzinfo is None:
        logger.debug("Formatting naive timestamp %s as UTC", dt)
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def parse_utc_iso(s: str) -> datetime:
    """Parse ISO 8601 string accepting Z, offset, or naive (assumed UTC)."""
    s_clean = s.strip()
    if s_clean.endswith("Z"):
        s_clean = s_clean[:-1] + "+00:00"
    dt = datetime.fromisoformat(s_clean)
    if dt.tzinfo is None:
        logger.debug("Parsed naive timestamp %s, assuming UTC", s)
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
