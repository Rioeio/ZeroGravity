from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from zerogravity.parsers.base import BaseParser, ProjectManifest
from zerogravity.parsers.go_parser import GoParser
from zerogravity.parsers.node_parser import NodeParser
from zerogravity.parsers.python_parser import PythonParser
from zerogravity.parsers.rust_parser import RustParser

logger = logging.getLogger("parser.registry")


class ParserRegistry:
    """
    Registry for project parsers in ZeroGravity.
    Maintains a list of all available parsers and delegates parsing based on project files.
    """

    def __init__(self) -> None:
        """Initialize the registry with standard parsers."""
        self.parsers: list[BaseParser] = [
            NodeParser(),
            PythonParser(),
            RustParser(),
            GoParser(),
        ]

    def detect_parsers(self, path: Path) -> list[BaseParser]:
        """
        Detect which parsers can handle the given directory.

        Args:
            path: The directory path to inspect.

        Returns:
            A list of parsers that support the given project.
        """
        detected: list[BaseParser] = []
        for parser in self.parsers:
            if parser.can_parse(path):
                logger.debug("Selected parser %s for %s", parser.__class__.__name__, path)
                detected.append(parser)
        return detected

    def parse_all(self, path: Path) -> list[ProjectManifest]:
        """
        Run all applicable parsers on the given directory.

        Args:
            path: The directory path to parse.

        Returns:
            A list of resulting ProjectManifests.
        """
        from zerogravity.parsers.base import detect_container_config

        manifests = []
        for parser in self.detect_parsers(path):
            try:
                manifest = parser.parse(path)
                if manifest:
                    if not manifest.container_file:
                        container_file = detect_container_config(manifest.project_path)
                        if not container_file and manifest.workspace_root:
                            container_file = detect_container_config(manifest.workspace_root)
                        manifest.container_file = container_file
                    manifests.append(manifest)
            except (ValueError, OSError, KeyError, TypeError) as err:
                logger.debug("Failed to parse manifest in %s: %s", path, err, exc_info=True)
        return manifests

    def detect_and_parse(
        self,
        path: Path,
        use_cache: bool = True,
        cache_manager: Any = None,
    ) -> list[ProjectManifest]:
        """
        Detect applicable parsers and parse the project directory with caching support.

        Args:
            path: The directory path to inspect and parse.
            use_cache: Whether to check and update the scan-result cache.
            cache_manager: Optional custom ScanCacheManager instance.

        Returns:
            A list of parsed ProjectManifests.
        """
        from zerogravity.scanner.cache import ScanCacheManager

        mgr = cache_manager if cache_manager is not None else ScanCacheManager()

        if use_cache:
            logger.debug("Checking cache for %s", path)
            cached = mgr.get(path)
            if cached is not None:
                logger.debug("Cache hit for %s", path)
                return cached
            logger.debug("Cache miss for %s", path)

        manifests = self.parse_all(path)
        if use_cache and manifests:
            mgr.set(path, manifests)

        return manifests


def detect_and_parse(
    path: Path,
    use_cache: bool = True,
    cache_manager: Any = None,
) -> list[ProjectManifest]:
    """
    Convenience module-level function to detect and parse manifests with cache support.

    Args:
        path: The directory path to inspect and parse.
        use_cache: Whether to use scan-result caching.
        cache_manager: Optional custom ScanCacheManager instance.

    Returns:
        A list of resulting ProjectManifests.
    """
    registry = ParserRegistry()
    return registry.detect_and_parse(path, use_cache=use_cache, cache_manager=cache_manager)
