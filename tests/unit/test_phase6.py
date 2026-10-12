from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from zerogravity.cli import app
from zerogravity.config import ConfigError, load_config

runner = CliRunner()


def test_syntax_error_raises_config_error(tmp_path: Path):
    """A TOML syntax error in .zerogravity.toml raises ConfigError with file:line:col."""
    cfg = tmp_path / ".zerogravity.toml"
    cfg.write_text("scan = [\n", encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        load_config(tmp_path)

    err = exc_info.value
    assert err.file is not None
    assert err.line is not None
    assert err.col is not None
    assert f"{err.file}:{err.line}:{err.col}" in str(err)


def test_type_error_raises_config_error(tmp_path: Path):
    """A type error (e.g. exclude is string instead of list[str]) raises ConfigError with file:line:col."""
    cfg = tmp_path / ".zerogravity.toml"
    cfg.write_text("[scan]\nexclude = \"single_dir_string\"\n", encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        load_config(tmp_path)

    err = exc_info.value
    assert err.file is not None
    assert err.line is not None
    assert f"{err.file}:{err.line}" in str(err)
    assert "exclude" in str(err).lower() or "list" in str(err).lower()


def test_unknown_key_warns_with_suggestion(tmp_path: Path):
    """An unknown key like 'exlude' produces a warning with a did-you-mean suggestion."""
    cfg = tmp_path / ".zerogravity.toml"
    cfg.write_text("[scan]\nexlude = [\"build\"]\n", encoding="utf-8")

    loaded = load_config(tmp_path)
    assert hasattr(loaded, "warnings")
    assert any("exlude" in w and "exclude" in w for w in loaded.warnings)


def test_cli_catches_config_error_and_exits_2(tmp_path: Path):
    """CLI commands catch ConfigError, print it, and exit with code 2."""
    cfg = tmp_path / ".zerogravity.toml"
    cfg.write_text("invalid toml syntax [[[\n", encoding="utf-8")

    result = runner.invoke(app, ["scan", str(tmp_path)])
    assert result.exit_code == 2
    assert "configerror" in result.output.lower() or ".zerogravity.toml" in result.output


def test_config_check_command(tmp_path: Path):
    """zg config check displays effective config and where each value came from."""
    cfg = tmp_path / ".zerogravity.toml"
    cfg.write_text("[scan]\nexclude = [\"custom_build\"]\n", encoding="utf-8")

    result = runner.invoke(app, ["config", "check", str(tmp_path)])
    assert result.exit_code == 0
    assert "custom_build" in result.output
    assert "file" in result.output.lower()
    assert "default" in result.output.lower()
