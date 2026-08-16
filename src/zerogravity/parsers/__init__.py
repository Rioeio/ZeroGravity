"""Parsers package — ecosystem-specific manifest parsers."""

from zerogravity.parsers.registry import ParserRegistry, detect_and_parse

__all__ = ["detect_and_parse", "ParserRegistry"]
