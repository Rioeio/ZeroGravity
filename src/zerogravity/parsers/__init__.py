"""Parsers package — ecosystem-specific manifest parsers."""

from zerogravity.parsers.registry import detect_and_parse, ParserRegistry

__all__ = ["detect_and_parse", "ParserRegistry"]
