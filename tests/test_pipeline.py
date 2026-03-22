"""Tests for the scan pipeline orchestration."""

from __future__ import annotations

from pathlib import Path

from field_check.config import FieldCheckConfig
from field_check.pipeline import PHASES, PipelineResult, run_pipeline


def test_empty_directory(tmp_path: Path) -> None:
    """Empty directory returns empty PipelineResult."""
    config = FieldCheckConfig()
    result = run_pipeline(tmp_path, config)

    assert isinstance(result, PipelineResult)
    assert result.empty is True
    assert result.walk is not None
    assert result.inventory is None
    assert result.elapsed_seconds >= 0


def test_pipeline_returns_all_results(tmp_path: Path) -> None:
    """Pipeline populates all result fields for a simple corpus."""
    for i in range(5):
        (tmp_path / f"file{i}.txt").write_text(
            f"Hello world content {i}", encoding="utf-8"
        )
    config = FieldCheckConfig(sampling_rate=1.0)
    result = run_pipeline(tmp_path, config)

    assert result.empty is False
    assert result.walk is not None
    assert result.inventory is not None
    assert result.dedup is not None
    assert result.corruption is not None
    assert result.sample is not None
    assert result.elapsed_seconds > 0


def test_phase_callback_fires(tmp_path: Path) -> None:
    """Phase callback is called for each scan phase."""
    (tmp_path / "test.txt").write_text("content", encoding="utf-8")
    config = FieldCheckConfig(sampling_rate=1.0)

    phases_seen: list[tuple[str, int, int]] = []

    def on_phase(name: str, index: int, total: int) -> None:
        phases_seen.append((name, index, total))

    run_pipeline(tmp_path, config, on_phase=on_phase)

    assert len(phases_seen) == len(PHASES)
    for i, (name, index, total) in enumerate(phases_seen):
        assert name == PHASES[i]
        assert index == i
        assert total == len(PHASES)


def test_progress_callback_fires(tmp_path: Path) -> None:
    """Progress callback is called during scanning phases."""
    for i in range(3):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
    config = FieldCheckConfig(sampling_rate=1.0)

    progress_events: list[tuple[str, int, int]] = []

    def on_progress(phase: str, current: int, total: int) -> None:
        progress_events.append((phase, current, total))

    run_pipeline(tmp_path, config, on_progress=on_progress)

    assert len(progress_events) > 0
    # Walk phase should have fired with file counts
    walk_events = [e for e in progress_events if e[0] == "Scanning files"]
    assert len(walk_events) > 0


def test_empty_dir_no_phase_callback_for_later_phases(
    tmp_path: Path,
) -> None:
    """Empty directory only fires phase 0 (walk), no later phases."""
    config = FieldCheckConfig()

    phases_seen: list[str] = []

    def on_phase(name: str, index: int, total: int) -> None:
        phases_seen.append(name)

    run_pipeline(tmp_path, config, on_phase=on_phase)

    assert phases_seen == ["Scanning files"]


def test_phases_list_has_12_entries() -> None:
    """PHASES list has exactly 12 entries matching the scan stages."""
    assert len(PHASES) == 12
    assert PHASES[0] == "Scanning files"
    assert PHASES[-1] == "Detecting near-duplicates"


def test_pipeline_with_executor_class(tmp_path: Path) -> None:
    """Pipeline accepts and passes executor_class through."""
    from concurrent.futures import ThreadPoolExecutor

    for i in range(3):
        (tmp_path / f"file{i}.txt").write_text(
            f"Hello world content {i}", encoding="utf-8"
        )
    config = FieldCheckConfig(sampling_rate=1.0)
    result = run_pipeline(
        tmp_path, config, executor_class=ThreadPoolExecutor
    )
    assert result.empty is False
    assert result.walk is not None
    assert result.inventory is not None
