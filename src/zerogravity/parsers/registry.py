from __future__ import annotations

from pathlib import Path

from zerogravity.parsers.base import BaseParser, ProjectManifest
from zerogravity.parsers.node_parser import NodeParser
from zerogravity.parsers.python_parser import PythonParser


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
        ]

    def detect_parsers(self, path: Path) -> list[BaseParser]:
        """
        Detect which parsers can handle the given directory.

        Args:
            path: The directory path to inspect.

        Returns:
            A list of parsers that support the given project.
        """
        return [parser for parser in self.parsers if parser.can_parse(path)]

    def parse_all(self, path: Path) -> list[ProjectManifest]:
        """
        Run all applicable parsers on the given directory.

        Args:
            path: The directory path to parse.

        Returns:
            A list of resulting ProjectManifests.
        """
        manifests = []
        for parser in self.detect_parsers(path):
            manifest = parser.parse(path)
            if manifest:
                manifests.append(manifest)
        return manifests

    def detect_and_parse(self, path: Path) -> list[ProjectManifest]:
        """
        Detect applicable parsers and parse the project directory.

        Args:
            path: The directory path to inspect and parse.

        Returns:
            A list of parsed ProjectManifests.
        """
        return self.parse_all(path)


def detect_and_parse(path: Path) -> list[ProjectManifest]:
    """
    Convenience module-level function to detect and parse manifests.

    Args:
        path: The directory path to inspect and parse.

    Returns:
        A list of resulting ProjectManifests.
    """
    registry = ParserRegistry()
    return registry.detect_and_parse(path)
