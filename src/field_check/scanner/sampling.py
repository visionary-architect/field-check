"""Stratified sampling framework with confidence interval calculation."""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field

from field_check.config import FieldCheckConfig
from field_check.scanner import FileEntry, WalkResult
from field_check.scanner.inventory import InventoryResult

logger = logging.getLogger(__name__)

# Below this threshold, sample everything (census). Small enough
# that full content analysis is fast.
_AUTO_CENSUS_THRESHOLD = 3000

# Target sample size for all corpora above census threshold.
# 3,000 gives ~1.8% margin of error at 95% confidence.
_AUTO_TARGET_SAMPLE = _AUTO_CENSUS_THRESHOLD


def compute_auto_sampling_rate(population_size: int) -> float:
    """Compute an optimal sampling rate based on corpus size.

    Targets a fixed sample size of 3,000 for consistent ~1.8%
    margin of error at 95% confidence. For small corpora (<=3,000),
    returns 1.0 (full census) for a seamless transition.

    Args:
        population_size: Total number of files in the corpus.

    Returns:
        Sampling rate between 0.0 and 1.0.
    """
    if population_size <= 0:
        return 1.0

    if population_size <= _AUTO_CENSUS_THRESHOLD:
        return 1.0

    return _AUTO_TARGET_SAMPLE / population_size


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
    deff: float = 1.0


# z-scores for common confidence levels
_Z_SCORES: dict[float, float] = {
    0.90: 1.645,
    0.95: 1.96,
    0.99: 2.576,
}


def _sample_by_directory(
    entries: list[FileEntry],
    target: int,
    rng: object | None = None,
) -> list[FileEntry]:
    """Sample files proportionally across directories.

    Groups files by parent directory, allocates the sample budget
    proportionally to each directory's share, then randomly selects
    within each directory. Ensures at least 1 file per directory
    when possible.

    Args:
        entries: Files to sample from (all same MIME type).
        target: Number of files to select.
        rng: Random instance for reproducible sampling (default: module RNG).

    Returns:
        Selected files drawn proportionally from directories.
    """
    import random
    from pathlib import PurePath

    rng = rng or random

    # Group by parent directory
    by_dir: dict[str, list[FileEntry]] = defaultdict(list)
    for entry in entries:
        parent = str(PurePath(entry.path).parent)
        by_dir[parent].append(entry)

    if len(by_dir) <= 1:
        # Single directory: simple random sample
        return rng.sample(entries, target)

    total = len(entries)
    selected: list[FileEntry] = []
    remaining = target

    # Proportional allocation with minimum 1 per directory
    # Sort by directory path for deterministic allocation order
    allocations: list[tuple[str, int]] = []
    for dir_path, dir_files in sorted(by_dir.items()):
        alloc = max(1, round(len(dir_files) / total * target))
        alloc = min(alloc, len(dir_files), max(remaining, 0))
        allocations.append((dir_path, alloc))
        remaining -= alloc

    # Distribute any remaining budget to largest directories
    if remaining > 0:
        for dir_path, dir_files in sorted(
            by_dir.items(),
            key=lambda x: len(x[1]),
            reverse=True,
        ):
            current = dict(allocations).get(dir_path, 0)
            extra = min(remaining, len(dir_files) - current)
            if extra > 0:
                allocations = [(d, a + extra) if d == dir_path else (d, a) for d, a in allocations]
                remaining -= extra
            if remaining <= 0:
                break

    # Sample within each directory
    for dir_path, alloc in allocations:
        dir_files = by_dir[dir_path]
        n = min(alloc, len(dir_files))
        if n >= len(dir_files):
            selected.extend(dir_files)
        else:
            selected.extend(rng.sample(dir_files, n))

    return selected[:target]


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

    population = len(walk_result.files)
    if config.sampling_rate_auto:
        rate = compute_auto_sampling_rate(population)
        logger.info(
            "Auto sampling: %d files → rate %.2f (target ~%d samples)",
            population,
            rate,
            min(population, _AUTO_TARGET_SAMPLE),
        )
    else:
        rate = config.sampling_rate
    min_per_type = config.sampling_min_per_type

    # Create a local RNG instance for reproducibility (avoids mutating global state)
    import random

    rng: random.Random | None = None
    if config.seed is not None:
        rng = random.Random(config.seed)

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
                else _sample_by_directory(entries, target, rng=rng)
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


def estimate_design_effect(
    files: list[FileEntry],
    inventory: InventoryResult,
) -> float:
    """Estimate the design effect (DEFF) from directory clustering.

    Uses one-way ANOVA decomposition to estimate intraclass correlation
    (ICC/rho), then computes DEFF = 1 + rho * (m - 1) where m is the
    average cluster (directory) size.

    Args:
        files: Sampled files.
        inventory: Inventory with per-file MIME types.

    Returns:
        DEFF >= 1.0. Returns 1.0 if no clustering detected.
    """
    if len(files) < 2:
        return 1.0

    # Group files by parent directory
    from pathlib import PurePath

    groups: dict[str, list[float]] = defaultdict(list)
    for f in files:
        parent = str(PurePath(f.path).parent)
        # Log-transform sizes to reduce outlier influence (file sizes are
        # right-skewed/lognormal). math.log1p handles zero-byte files safely.
        groups[parent].append(math.log1p(f.size))

    k = len(groups)  # number of clusters
    if k <= 1 or k == len(files):
        # Single directory or every file in its own directory: no clustering
        return 1.0

    n = len(files)
    m = n / k  # average cluster size

    # One-way ANOVA: compute MSB and MSW from log-transformed file sizes
    all_values = [v for members in groups.values() for v in members]
    grand_mean = sum(all_values) / n

    ssb = 0.0  # between-group sum of squares
    ssw = 0.0  # within-group sum of squares
    for members in groups.values():
        group_mean = sum(members) / len(members)
        ssb += len(members) * (group_mean - grand_mean) ** 2
        ssw += sum((x - group_mean) ** 2 for x in members)

    msb = ssb / (k - 1) if k > 1 else 0.0
    msw = ssw / (n - k) if n > k else 0.0

    # ICC (rho) estimation
    if msb + (m - 1) * msw == 0:
        return 1.0
    rho = (msb - msw) / (msb + (m - 1) * msw)
    rho = max(0.0, rho)  # ICC can't be negative for DEFF purposes

    deff = 1.0 + rho * (m - 1)
    return max(1.0, deff)


def compute_confidence_interval_adjusted(
    successes: int,
    sample_size: int,
    population_size: int,
    deff: float = 1.0,
    confidence: float = 0.95,
) -> ConfidenceInterval:
    """Compute CI with design effect adjustment for clustered samples.

    Widens the confidence interval by sqrt(DEFF) to account for
    within-cluster correlation (files from the same directory tend
    to be similar).

    Args:
        successes: Number of successes in the sample.
        sample_size: Total sample size (n).
        population_size: Total population size (N).
        deff: Design effect (>= 1.0).
        confidence: Confidence level (default 0.95).

    Returns:
        ConfidenceInterval with adjusted bounds.
    """
    ci = compute_confidence_interval(successes, sample_size, population_size, confidence)

    if deff <= 1.0 or ci.sample_size >= ci.population_size:
        return ci

    # Widen the interval by sqrt(DEFF)
    center = (ci.lower + ci.upper) / 2
    half_width = (ci.upper - ci.lower) / 2
    adjusted_half = half_width * math.sqrt(deff)

    return ConfidenceInterval(
        point_estimate=ci.point_estimate,
        lower=max(0.0, center - adjusted_half),
        upper=min(1.0, center + adjusted_half),
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
