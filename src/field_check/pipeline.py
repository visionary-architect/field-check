"""Scan pipeline orchestration, decoupled from CLI/GUI concerns."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from field_check.config import FieldCheckConfig
from field_check.scanner import WalkResult, walk_directory
from field_check.scanner.corruption import CorruptionResult, check_corruption
from field_check.scanner.dedup import DedupResult, compute_hashes
from field_check.scanner.encoding import EncodingResult, analyze_encodings
from field_check.scanner.inventory import InventoryResult, analyze_inventory
from field_check.scanner.language import LanguageResult, analyze_languages
from field_check.scanner.mojibake import MojibakeResult, detect_mojibake
from field_check.scanner.pii import PIIScanResult, scan_pii
from field_check.scanner.readability import ReadabilityResult, analyze_readability
from field_check.scanner.sampling import (
    SampleResult,
    estimate_design_effect,
    select_sample,
)
from field_check.scanner.simhash import SimHashResult, detect_near_duplicates
from field_check.scanner.text import (
    TextCacheResult,
    TextExtractionResult,
    extract_text_unified,
)

logger = logging.getLogger(__name__)


class ScanCancelledError(Exception):
    """Raised by callbacks to abort the pipeline early."""


# Scan phases in execution order
PHASES = [
    "Scanning files",
    "Analyzing file types",
    "Hashing files",
    "Checking file health",
    "Selecting sample",
    "Extracting text",
    "Scanning for PII",
    "Detecting languages",
    "Analyzing encodings",
    "Checking for encoding damage",
    "Analyzing readability",
    "Detecting near-duplicates",
]

# Callback type aliases
PhaseCallback = Callable[[str, int, int], None]
"""Called on phase transition: (phase_name, phase_index, total_phases)."""

ProgressCallback = Callable[[str, int, int], None]
"""Called on progress within a phase: (phase_name, current, total)."""


@dataclass
class PipelineResult:
    """Result of the full scan pipeline."""

    walk: WalkResult | None = None
    inventory: InventoryResult | None = None
    dedup: DedupResult | None = None
    corruption: CorruptionResult | None = None
    sample: SampleResult | None = None
    text: TextExtractionResult | None = None
    text_cache: TextCacheResult | None = None
    pii: PIIScanResult | None = None
    language: LanguageResult | None = None
    encoding: EncodingResult | None = None
    mojibake: MojibakeResult | None = None
    readability: ReadabilityResult | None = None
    simhash: SimHashResult | None = None
    elapsed_seconds: float = 0.0
    empty: bool = False


def run_pipeline(
    scan_path: Path,
    config: FieldCheckConfig,
    on_phase: PhaseCallback | None = None,
    on_progress: ProgressCallback | None = None,
) -> PipelineResult:
    """Run the full scan pipeline.

    This is the core orchestration function used by both the CLI
    and the sidecar GUI. It is completely decoupled from any display
    framework (no Rich, no stdout).

    Args:
        scan_path: Directory to scan.
        config: Scan configuration.
        on_phase: Called when a new phase starts.
        on_progress: Called with progress updates within a phase.

    Returns:
        PipelineResult with all scan results.
    """
    start = time.monotonic()
    total_phases = len(PHASES)

    def _phase(index: int) -> None:
        if on_phase:
            on_phase(PHASES[index], index, total_phases)

    def _progress(phase_name: str, current: int, total: int) -> None:
        if on_progress:
            on_progress(phase_name, current, total)

    # Phase 1: Walk directory
    _phase(0)

    def _on_walk(count: int) -> None:
        _progress("Scanning files", count, 0)

    walk_result = walk_directory(scan_path, config, progress_callback=_on_walk)

    if not walk_result.files:
        return PipelineResult(
            walk=walk_result,
            elapsed_seconds=time.monotonic() - start,
            empty=True,
        )

    # Phase 2: Inventory
    _phase(1)
    inventory = analyze_inventory(
        walk_result,
        progress_callback=lambda c, t: _progress("Analyzing file types", c, t),
    )

    # Phase 3: Dedup hashing
    _phase(2)
    dedup = compute_hashes(
        walk_result,
        progress_callback=lambda c, t: _progress("Hashing files", c, t),
    )

    # Phase 4: Corruption
    _phase(3)
    corruption = check_corruption(
        walk_result,
        progress_callback=lambda c, t: _progress("Checking file health", c, t),
        file_types=inventory.file_types,
    )

    # Phase 5: Sampling
    _phase(4)
    sample = select_sample(walk_result, inventory, config)
    if not sample.is_census:
        sample.deff = estimate_design_effect(
            sample.selected_files, inventory
        )

    # Phase 6: Text extraction
    _phase(5)
    has_sample = sample.total_sample_size > 0
    text_result: TextExtractionResult | None = None
    text_cache_result: TextCacheResult | None = None
    if has_sample:
        text_result, text_cache_result = extract_text_unified(
            sample,
            inventory,
            progress_callback=lambda c, t: _progress(
                "Extracting text", c, t
            ),
        )

    # Phase 7: PII scan
    _phase(6)
    pii_result: PIIScanResult | None = None
    if has_sample:
        pii_result = scan_pii(
            sample,
            inventory,
            config,
            text_cache=(
                text_cache_result.text_cache if text_cache_result else None
            ),
            progress_callback=lambda c, t: _progress(
                "Scanning for PII", c, t
            ),
        )

    # Phase 8: Language detection
    _phase(7)
    language_result: LanguageResult | None = None
    if text_cache_result and text_cache_result.text_cache:
        language_result = analyze_languages(text_cache_result.text_cache)

    # Phase 9: Encoding analysis
    _phase(8)
    encoding_result: EncodingResult | None = None
    if text_cache_result and text_cache_result.encoding_map:
        encoding_result = analyze_encodings(text_cache_result.encoding_map)

    # Phase 10: Mojibake
    _phase(9)
    mojibake_result: MojibakeResult | None = None
    if text_cache_result and text_cache_result.text_cache:
        mojibake_result = detect_mojibake(text_cache_result.text_cache)

    # Phase 11: Readability
    _phase(10)
    readability_result: ReadabilityResult | None = None
    if text_cache_result and text_cache_result.text_cache:
        readability_result = analyze_readability(text_cache_result.text_cache)

    # Phase 12: SimHash
    _phase(11)
    simhash_result: SimHashResult | None = None
    if text_cache_result and text_cache_result.text_cache:
        simhash_result = detect_near_duplicates(
            text_cache_result.text_cache,
            threshold=config.simhash_threshold,
            bits=config.simhash_bits,
            progress_callback=lambda c, t: _progress(
                "Detecting near-duplicates", c, t
            ),
        )

    return PipelineResult(
        walk=walk_result,
        inventory=inventory,
        dedup=dedup,
        corruption=corruption,
        sample=sample,
        text=text_result,
        text_cache=text_cache_result,
        pii=pii_result,
        language=language_result,
        encoding=encoding_result,
        mojibake=mojibake_result,
        readability=readability_result,
        simhash=simhash_result,
        elapsed_seconds=time.monotonic() - start,
    )
