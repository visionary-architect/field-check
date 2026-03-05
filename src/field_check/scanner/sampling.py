"""Stratified sampling framework with confidence interval calculation."""

from __future__ import annotations

import logging
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field

from field_check.config import FieldCheckConfig
from field_check.scanner import FileEntry, WalkResult
from field_check.scanner.inventory import InventoryResult

logger = logging.getLogger(__name__)


@dataclass
class ConfidenceInterval:
    """Confidence interval for a sampled proportion."""

    point_estimate: float
    lower: float
    upper: float
    confidence_level: float
    sample_size: int
    population_size: int


@dataclass
class SampleResult:
    """Result of stratified sampling."""

    selected_files: list[FileEntry] = field(default_factory=list)
    per_type_sample: dict[str, list[FileEntry]] = field(default_factory=dict)
    per_type_population: dict[str, int] = field(default_factory=dict)
    total_sample_size: int = 0
    total_population_size: int = 0
    sampling_rate: float = 0.0
    is_census: bool = False


# z-scores for common confidence levels
_Z_SCORES: dict[float, float] = {
    0.90: 1.645,
    0.95: 1.96,
    0.99: 2.576,
}


def select_sample(
    walk_result: WalkResult,
    inventory: InventoryResult,
    config: FieldCheckConfig,
) -> SampleResult:
    """Select a stratified sample from the corpus.

    Stratifies by MIME type, ensuring a minimum number of files per type.

    Args:
        walk_result: Walk results with all discovered files.
        inventory: Inventory with per-file MIME type mapping.
        config: Configuration with sampling_rate and sampling_min_per_type.

    Returns:
        SampleResult with selected files and sampling metadata.
    """
    if not walk_result.files:
        return SampleResult(sampling_rate=config.sampling_rate)

    rate = config.sampling_rate
    min_per_type = config.sampling_min_per_type

    # Group files by MIME type
    files_by_type: defaultdict[str, list[FileEntry]] = defaultdict(list)
    for entry in walk_result.files:
        mime = inventory.file_types.get(entry.path, "application/octet-stream")
        files_by_type[mime].append(entry)

    selected: list[FileEntry] = []
    per_type_sample: dict[str, list[FileEntry]] = {}
    per_type_population: dict[str, int] = {}
    is_census = rate >= 1.0

    for mime, entries in files_by_type.items():
        pop_size = len(entries)
        per_type_population[mime] = pop_size

        if is_census:
            sample = list(entries)
        else:
            target = max(math.ceil(pop_size * rate), min(min_per_type, pop_size))
            target = min(target, pop_size)
            sample = (
                list(entries)
                if target >= pop_size
                else random.sample(entries, target)
            )

        per_type_sample[mime] = sample
        selected.extend(sample)

    return SampleResult(
        selected_files=selected,
        per_type_sample=per_type_sample,
        per_type_population=per_type_population,
        total_sample_size=len(selected),
        total_population_size=len(walk_result.files),
        sampling_rate=rate,
        is_census=is_census or len(selected) >= len(walk_result.files),
    )


def compute_confidence_interval(
    successes: int,
    sample_size: int,
    population_size: int,
    confidence: float = 0.95,
) -> ConfidenceInterval:
    """Compute a confidence interval for a proportion using Wilson score.

    Uses Wilson score interval with finite population correction for
    accurate intervals even with small samples or extreme proportions.

    Args:
        successes: Number of successes in the sample.
        sample_size: Total sample size (n).
        population_size: Total population size (N).
        confidence: Confidence level (default 0.95).

    Returns:
        ConfidenceInterval with point estimate and bounds.
    """
    if sample_size == 0:
        return ConfidenceInterval(
            point_estimate=0.0,
            lower=0.0,
            upper=0.0,
            confidence_level=confidence,
            sample_size=0,
            population_size=population_size,
        )

    # Census: exact values, no uncertainty
    if sample_size >= population_size:
        p = successes / sample_size
        return ConfidenceInterval(
            point_estimate=p,
            lower=p,
            upper=p,
            confidence_level=confidence,
            sample_size=sample_size,
            population_size=population_size,
        )

    z = _Z_SCORES.get(confidence, 1.96)
    n = sample_size
    p_hat = successes / n

    # Wilson score interval
    denominator = 1 + z**2 / n
    center = (p_hat + z**2 / (2 * n)) / denominator
    spread = z * math.sqrt((p_hat * (1 - p_hat) + z**2 / (4 * n)) / n) / denominator

    # Finite population correction
    fpc = math.sqrt((population_size - n) / (population_size - 1))
    adjusted_spread = spread * fpc

    lower = max(0.0, center - adjusted_spread)
    upper = min(1.0, center + adjusted_spread)

    return ConfidenceInterval(
        point_estimate=p_hat,
        lower=lower,
        upper=upper,
        confidence_level=confidence,
        sample_size=sample_size,
        population_size=population_size,
    )


def format_ci(ci: ConfidenceInterval) -> str:
    """Format a confidence interval for display.

    Args:
        ci: The confidence interval to format.

    Returns:
        Formatted string like "50.0% (CI: 45.2% -- 54.8%, n=100)"
        or "50.0% (exact, N=100)" for census data.
    """
    pct = ci.point_estimate * 100

    if ci.sample_size >= ci.population_size:
        return f"{pct:.1f}% (exact, N={ci.population_size})"

    lower_pct = ci.lower * 100
    upper_pct = ci.upper * 100
    return f"{pct:.1f}% (CI: {lower_pct:.1f}% -- {upper_pct:.1f}%, n={ci.sample_size})"
