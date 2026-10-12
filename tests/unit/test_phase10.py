from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from zerogravity.cli import app

runner = CliRunner()


def test_debug_logging_emitted_with_vv(node_project_path: Path) -> None:
    """Verify zg scan -vv emits DEBUG logs showing manifest found, parser selected, cache checked."""
    result = runner.invoke(app, ["scan", str(node_project_path), "-vv", "--offline", "--no-history"])
    assert result.exit_code == 0
    # In CliRunner, stdout/stderr are combined or available
    combined = result.output
    assert "DEBUG" in combined
    assert "manifest" in combined.lower() or "parser" in combined.lower()


def test_malformed_manifest_logs_debug_traceback(tmp_path: Path) -> None:
    """Verify malformed manifest logs a debug traceback instead of vanishing silently."""
    bad_proj = tmp_path / "bad_proj"
    bad_proj.mkdir()
    (bad_proj / "package.json").write_text("{ malformed json", encoding="utf-8")

    result = runner.invoke(app, ["scan", str(bad_proj), "-vv", "--offline", "--no-history"])
    combined = result.output
    assert "DEBUG" in combined
    assert "Failed to parse manifest" in combined or "JSONDecodeError" in combined or "bad_proj" in combined


def test_no_color_emits_zero_ansi_escapes(node_project_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify NO_COLOR=1 and --no-color emit zero ANSI escape codes."""
    monkeypatch.setenv("NO_COLOR", "1")
    result = runner.invoke(app, ["scan", str(node_project_path), "--no-color", "--offline", "--no-history"])
    assert result.exit_code == 0

    ansi_escape_pattern = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    assert not ansi_escape_pattern.search(result.output)


def test_quiet_mode_suppresses_info(node_project_path: Path) -> None:
    """Verify -q suppresses normal informational banners and debug logs."""
    result = runner.invoke(app, ["scan", str(node_project_path), "-q", "--offline", "--no-history"])
    assert result.exit_code == 0
    assert "DEBUG" not in result.output
    assert "INFO" not in result.output
