"""
Dedup store cleanup and orphan pruning with strict error propagation and permission handling.
"""

from __future__ import annotations

import logging
import os
import shutil
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from zerogravity.dedup.engine import DeduplicationEngine

logger = logging.getLogger(__name__)


def handle_remove_readonly(func: Any, path: str, exc_info: Any) -> None:
    """Clear read-only permissions on failure and retry removal."""
    try:
        os.chmod(path, 0o777)
        func(path)
    except Exception as err:
        logger.debug("Failed removing %s even after chmod: %s", path, err, exc_info=True)
        raise


def cleanup_orphaned_store(engine: DeduplicationEngine) -> dict[str, Any]:
    """
    Remove store packages that have no registered links in the deduplication registry.
    Errors during removal are never swallowed silently.
    """
    from zerogravity.dedup.engine import make_store_writable

    cleaned: list[str] = []
    errors: list[str] = []
    failed: int = 0

    if not engine.store_path.exists():
        return {"cleaned": cleaned, "failed": failed, "errors": errors}

    for child in engine.store_path.iterdir():
        if not child.is_dir():
            continue

        pkg_hash = child.name
        links = engine.registry.get_links_for_package(pkg_hash)
        if not links:
            try:
                make_store_writable(child)
                shutil.rmtree(child, onerror=handle_remove_readonly)
                engine.registry.remove_package(pkg_hash)
                cleaned.append(pkg_hash)
            except (OSError, RuntimeError, shutil.Error) as err:
                failed += 1
                msg = f"Failed to prune orphaned store directory {child.name}: {err}"
                logger.error(msg)
                errors.append(msg)

    return {"cleaned": cleaned, "failed": failed, "errors": errors}
