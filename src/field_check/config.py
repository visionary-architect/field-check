"""Configuration loader for .field-check.yaml files."""

from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDES = [".git", "__pycache__", "node_modules", ".venv", ".env"]

CONFIG_FILENAME = ".field-check.yaml"


@dataclass
class FieldCheckConfig:
    """Configuration for a Field Check scan."""

    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    sampling_rate: float = 0.10
    sampling_min_per_type: int = 30
    pii_custom_patterns: list[dict[str, str]] = field(default_factory=list)
    show_pii_samples: bool = False
    simhash_threshold: int = 5
    pii_critical: float = 0.05
    duplicate_critical: float = 0.10
    corrupt_critical: float = 0.01


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
        import yaml

        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to parse %s, using defaults", path)
        return FieldCheckConfig()

    if not isinstance(raw, dict):
        logger.warning("Config file %s is not a YAML mapping, using defaults", path)
        return FieldCheckConfig()

    exclude = raw.get("exclude")
    if isinstance(exclude, list):
        patterns = list(DEFAULT_EXCLUDES) + [str(p) for p in exclude]
    else:
        patterns = list(DEFAULT_EXCLUDES)

    # Parse sampling config
    sampling = raw.get("sampling", {})
    sampling_rate = 0.10
    sampling_min_per_type = 30
    if isinstance(sampling, dict):
        rate = sampling.get("rate")
        if isinstance(rate, (int, float)):
            sampling_rate = float(max(0.0, min(1.0, rate)))
        min_per = sampling.get("min_per_type")
        if isinstance(min_per, int) and min_per >= 0:
            sampling_min_per_type = min_per

    # Parse PII config
    pii_custom_patterns: list[dict[str, str]] = []
    pii_section = raw.get("pii", {})
    if isinstance(pii_section, dict):
        custom = pii_section.get("custom_patterns", [])
        if isinstance(custom, list):
            for entry in custom:
                if (
                    isinstance(entry, dict)
                    and isinstance(entry.get("name"), str)
                    and isinstance(entry.get("pattern"), str)
                ):
                    try:
                        re.compile(entry["pattern"])
                        pii_custom_patterns.append(
                            {"name": entry["name"], "pattern": entry["pattern"]}
                        )
                    except re.error:
                        logger.warning(
                            "Invalid PII regex pattern '%s', skipping",
                            entry["pattern"],
                        )

    # Parse SimHash config
    simhash_threshold = 5
    simhash_section = raw.get("simhash", {})
    if isinstance(simhash_section, dict):
        thresh = simhash_section.get("threshold")
        if isinstance(thresh, int):
            simhash_threshold = max(0, min(64, thresh))

    # Parse thresholds config
    pii_critical = 0.05
    duplicate_critical = 0.10
    corrupt_critical = 0.01
    thresholds_section = raw.get("thresholds", {})
    if isinstance(thresholds_section, dict):
        pii_t = thresholds_section.get("pii_critical")
        if isinstance(pii_t, (int, float)):
            pii_critical = max(0.0, min(1.0, float(pii_t)))
        dup_t = thresholds_section.get("duplicate_critical")
        if isinstance(dup_t, (int, float)):
            duplicate_critical = max(0.0, min(1.0, float(dup_t)))
        cor_t = thresholds_section.get("corrupt_critical")
        if isinstance(cor_t, (int, float)):
            corrupt_critical = max(0.0, min(1.0, float(cor_t)))

    return FieldCheckConfig(
        exclude=patterns,
        sampling_rate=sampling_rate,
        sampling_min_per_type=sampling_min_per_type,
        pii_custom_patterns=pii_custom_patterns,
        simhash_threshold=simhash_threshold,
        pii_critical=pii_critical,
        duplicate_critical=duplicate_critical,
        corrupt_critical=corrupt_critical,
    )


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
