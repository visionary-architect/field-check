"""Tests for the configuration loader."""

from __future__ import annotations

from pathlib import Path

from field_check.config import (
    DEFAULT_EXCLUDES,
    FieldCheckConfig,
    load_config,
    should_exclude,
)


def test_load_default_config(tmp_path: Path) -> None:
    """No .field-check.yaml returns defaults."""
    config = load_config(tmp_path)
    assert config.exclude == list(DEFAULT_EXCLUDES)


def test_load_config_from_file(tmp_path: Path) -> None:
    """Parses .field-check.yaml correctly."""
    cfg = tmp_path / ".field-check.yaml"
    cfg.write_text('exclude:\n  - "*.log"\n  - "temp/"\n', encoding="utf-8")
    config = load_config(tmp_path)
    assert "*.log" in config.exclude
    assert "temp/" in config.exclude


def test_load_config_invalid_yaml(tmp_path: Path) -> None:
    """Malformed YAML falls back to defaults."""
    cfg = tmp_path / ".field-check.yaml"
    cfg.write_text("{{{{invalid yaml!!", encoding="utf-8")
    config = load_config(tmp_path)
    assert config.exclude == list(DEFAULT_EXCLUDES)


def test_load_config_missing_fields(tmp_path: Path) -> None:
    """Partial YAML fills in defaults for missing fields."""
    cfg = tmp_path / ".field-check.yaml"
    cfg.write_text("sampling:\n  rate: 0.2\n", encoding="utf-8")
    config = load_config(tmp_path)
    # No exclude key -> defaults
    assert config.exclude == list(DEFAULT_EXCLUDES)


def test_load_config_explicit_path(tmp_path: Path) -> None:
    """Explicit config_path overrides auto-detection."""
    custom = tmp_path / "custom.yaml"
    custom.write_text('exclude:\n  - "custom_pattern"\n', encoding="utf-8")
    config = load_config(tmp_path, config_path=custom)
    assert "custom_pattern" in config.exclude


def test_load_config_not_a_mapping(tmp_path: Path) -> None:
    """YAML that is a list (not a mapping) falls back to defaults."""
    cfg = tmp_path / ".field-check.yaml"
    cfg.write_text("- item1\n- item2\n", encoding="utf-8")
    config = load_config(tmp_path)
    assert config.exclude == list(DEFAULT_EXCLUDES)


def test_should_exclude_glob_pattern() -> None:
    """*.pyc matches foo.pyc."""
    assert should_exclude("foo.pyc", ["*.pyc"]) is True


def test_should_exclude_directory_pattern() -> None:
    """node_modules matches paths containing it."""
    assert should_exclude("node_modules/foo.js", ["node_modules"]) is True


def test_should_exclude_nested_directory() -> None:
    """Pattern matches component in nested path."""
    assert should_exclude("src/__pycache__/foo.pyc", ["__pycache__"]) is True


def test_should_exclude_no_match() -> None:
    """Non-matching pattern returns False."""
    assert should_exclude("readme.md", ["*.pyc", "*.log"]) is False


def test_default_excludes() -> None:
    """.git and __pycache__ are in default excludes."""
    config = FieldCheckConfig()
    assert ".git" in config.exclude
    assert "__pycache__" in config.exclude
