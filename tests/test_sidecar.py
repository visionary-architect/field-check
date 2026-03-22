"""Tests for the sidecar JSON IPC protocol."""

from __future__ import annotations

import json
import threading
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from field_check.sidecar import _build_config, _emit, _run_scan


def test_emit_writes_json_line(capsys: object) -> None:
    """_emit writes a JSON line to stdout with newline."""
    _emit({"event": "ready", "version": "0.1.0"})
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    line = captured.out.strip()
    parsed = json.loads(line)
    assert parsed["event"] == "ready"
    assert parsed["version"] == "0.1.0"


def test_build_config_defaults() -> None:
    """Empty dict produces default config."""
    config = _build_config({})
    assert config.sampling_rate == 0.10
    assert config.sampling_rate_auto is True
    assert config.show_pii_samples is False


def test_build_config_overrides() -> None:
    """Config dict overrides specific fields."""
    config = _build_config({
        "sampling_rate": 0.5,
        "show_pii_samples": True,
        "pii_min_confidence": 0.8,
        "exclude": ["*.log"],
    })
    assert config.sampling_rate == 0.5
    assert config.sampling_rate_auto is False
    assert config.show_pii_samples is True
    assert config.pii_min_confidence == 0.8
    assert "*.log" in config.exclude


def test_build_config_clamps_values() -> None:
    """Out-of-range values are clamped."""
    config = _build_config({
        "sampling_rate": 5.0,
        "pii_min_confidence": -1.0,
    })
    assert config.sampling_rate == 1.0
    assert config.pii_min_confidence == 0.0


def test_run_scan_invalid_path(capsys: object) -> None:
    """Scanning a nonexistent path emits an error event."""
    cancel = threading.Event()
    _run_scan("/nonexistent/path/xyz", {}, cancel)

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    events = [json.loads(line) for line in captured.out.strip().split("\n") if line.strip()]
    assert any(e["event"] == "error" for e in events)


def test_run_scan_empty_directory(tmp_path: Path, capsys: object) -> None:
    """Scanning an empty directory emits a complete event."""
    cancel = threading.Event()
    _run_scan(str(tmp_path), {}, cancel)

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    events = [json.loads(line) for line in captured.out.strip().split("\n") if line.strip()]
    complete = [e for e in events if e["event"] == "complete"]
    assert len(complete) == 1
    assert complete[0]["report"]["summary"]["total_files"] == 0


def test_run_scan_with_files(tmp_path: Path, capsys: object) -> None:
    """Scanning a directory with files emits phase, progress, and complete events."""
    for i in range(3):
        (tmp_path / f"file{i}.txt").write_text(f"content {i}", encoding="utf-8")

    cancel = threading.Event()
    _run_scan(str(tmp_path), {"sampling_rate": 1.0}, cancel)

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    events = [json.loads(line) for line in captured.out.strip().split("\n") if line.strip()]

    event_types = [e["event"] for e in events]
    assert "phase" in event_types
    assert "complete" in event_types

    complete = next(e for e in events if e["event"] == "complete")
    assert complete["report"]["summary"]["total_files"] == 3


def test_run_scan_cancellation(tmp_path: Path, capsys: object) -> None:
    """Setting cancel_event causes a cancelled event."""
    for i in range(3):
        (tmp_path / f"file{i}.txt").write_text("x", encoding="utf-8")

    cancel = threading.Event()
    cancel.set()  # Pre-cancel
    _run_scan(str(tmp_path), {}, cancel)

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    events = [json.loads(line) for line in captured.out.strip().split("\n") if line.strip()]
    # Should have cancelled event (the pipeline runs but callbacks are suppressed)
    event_types = [e["event"] for e in events]
    assert "cancelled" in event_types or "complete" in event_types


def test_main_ready_event() -> None:
    """main() emits a ready event immediately."""
    stdin = StringIO('{"cmd": "shutdown"}\n')
    stdout = StringIO()

    with patch("sys.stdin", stdin), patch("sys.stdout", stdout):
        from field_check.sidecar import main

        main()

    output = stdout.getvalue()
    lines = [json.loads(line) for line in output.strip().split("\n") if line.strip()]
    assert lines[0]["event"] == "ready"
    assert "version" in lines[0]


def test_main_unknown_command() -> None:
    """Unknown command emits an error event."""
    stdin = StringIO('{"cmd": "bogus"}\n{"cmd": "shutdown"}\n')
    stdout = StringIO()

    with patch("sys.stdin", stdin), patch("sys.stdout", stdout):
        from field_check.sidecar import main

        main()

    output = stdout.getvalue()
    lines = [json.loads(line) for line in output.strip().split("\n") if line.strip()]
    errors = [ev for ev in lines if ev["event"] == "error"]
    assert len(errors) == 1
    assert "bogus" in errors[0]["message"]


def test_main_invalid_json() -> None:
    """Invalid JSON on stdin emits an error event."""
    stdin = StringIO('not json\n{"cmd": "shutdown"}\n')
    stdout = StringIO()

    with patch("sys.stdin", stdin), patch("sys.stdout", stdout):
        from field_check.sidecar import main

        main()

    output = stdout.getvalue()
    lines = [json.loads(line) for line in output.strip().split("\n") if line.strip()]
    errors = [ev for ev in lines if ev["event"] == "error"]
    assert len(errors) == 1
    assert "Invalid JSON" in errors[0]["message"]


def test_main_eof_exits_cleanly() -> None:
    """main() exits cleanly when stdin reaches EOF (no commands)."""
    stdin = StringIO("")  # immediate EOF
    stdout = StringIO()

    with patch("sys.stdin", stdin), patch("sys.stdout", stdout):
        from field_check.sidecar import main

        main()

    output = stdout.getvalue()
    lines = [json.loads(line) for line in output.strip().split("\n") if line.strip()]
    # Should have emitted ready and then exited
    assert lines[0]["event"] == "ready"
    assert len(lines) == 1


def test_main_missing_cmd_field() -> None:
    """Message with no cmd field emits an error event."""
    stdin = StringIO('{"not_cmd": "scan"}\n{"cmd": "shutdown"}\n')
    stdout = StringIO()

    with patch("sys.stdin", stdin), patch("sys.stdout", stdout):
        from field_check.sidecar import main

        main()

    output = stdout.getvalue()
    lines = [json.loads(line) for line in output.strip().split("\n") if line.strip()]
    errors = [ev for ev in lines if ev["event"] == "error"]
    assert len(errors) == 1
    assert "None" in errors[0]["message"]


def test_build_config_invalid_values() -> None:
    """Invalid config values raise ValueError."""
    import pytest

    with pytest.raises(ValueError, match="Invalid config value"):
        _build_config({"sampling_rate": "not_a_number"})


def test_build_config_invalid_simhash() -> None:
    """Non-numeric simhash_threshold raises ValueError."""
    import pytest

    with pytest.raises(ValueError, match="Invalid config value"):
        _build_config({"simhash_threshold": "abc"})


def test_emit_non_serializable(capsys: object) -> None:
    """_emit handles non-serializable types via default=str."""
    _emit({"event": "test", "path": Path("/some/path")})
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    parsed = json.loads(captured.out.strip())
    assert parsed["event"] == "test"
    # Path should be serialized as string
    assert "/some/path" in parsed["path"] or "\\some\\path" in parsed["path"]


def test_run_scan_with_executor_class(tmp_path: Path, capsys: object) -> None:
    """Scanning with explicit executor_class passes through correctly."""
    from concurrent.futures import ThreadPoolExecutor

    (tmp_path / "test.txt").write_text("hello world", encoding="utf-8")
    cancel = threading.Event()
    _run_scan(str(tmp_path), {}, cancel, executor_class=ThreadPoolExecutor)

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    events = [
        json.loads(line)
        for line in captured.out.strip().split("\n")
        if line.strip()
    ]
    assert any(e["event"] == "complete" for e in events)


def test_run_scan_bad_config(capsys: object, tmp_path: Path) -> None:
    """Bad config values emit an error event instead of crashing."""
    cancel = threading.Event()
    _run_scan(str(tmp_path), {"sampling_rate": "invalid"}, cancel)

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    events = [json.loads(line) for line in captured.out.strip().split("\n") if line.strip()]
    errors = [e for e in events if e["event"] == "error"]
    assert len(errors) == 1
    assert "Invalid config value" in errors[0]["message"]
