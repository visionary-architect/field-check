"""Configuration loader for .field-check.yaml files."""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDES = [".git", "__pycache__", "node_modules", ".venv", ".env"]

CONFIG_FILENAME = ".field-check.yaml"


@dataclass
class FieldCheckConfig:
    """Configuration for a Field Check scan."""

    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDES))


def load_config(scan_path: Path, config_path: Path | None = None) -> FieldCheckConfig:
    """Load configuration from .field-check.yaml.

    Args:
        scan_path: The directory being scanned (used for auto-detection).
        config_path: Explicit path to config file. If None, looks in scan_path.

    Returns:
        Parsed configuration with defaults for missing fields.
    """
    path = Path(config_path) if config_path is not None else Path(scan_path) / CONFIG_FILENAME

    if not path.is_file():
        return FieldCheckConfig()

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to parse %s, using defaults", path)
        return FieldCheckConfig()

    if not isinstance(raw, dict):
        logger.warning("Config file %s is not a YAML mapping, using defaults", path)
        return FieldCheckConfig()

    exclude = raw.get("exclude")
    patterns = [str(p) for p in exclude] if isinstance(exclude, list) else list(DEFAULT_EXCLUDES)

    return FieldCheckConfig(exclude=patterns)


def should_exclude(relative_path: str, patterns: list[str]) -> bool:
    """Check if a path matches any exclusion pattern.

    Args:
        relative_path: Path relative to scan root (forward slashes).
        patterns: List of glob/fnmatch patterns to check against.

    Returns:
        True if the path should be excluded.
    """
    parts = relative_path.replace("\\", "/").split("/")
    for pattern in patterns:
        # Match against full relative path
        if fnmatch.fnmatch(relative_path, pattern):
            return True
        # Match against each path component (for directory names like ".git")
        for part in parts:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False
