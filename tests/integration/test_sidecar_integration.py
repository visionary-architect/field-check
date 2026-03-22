"""Integration tests for the sidecar IPC protocol.

These tests spawn the sidecar as a subprocess and communicate via
stdin/stdout JSON, mirroring how Tauri interacts with the sidecar.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _spawn_sidecar() -> subprocess.Popen:
    """Spawn the sidecar as a subprocess."""
    return subprocess.Popen(
        [sys.executable, "-m", "field_check.sidecar"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def _send(proc: subprocess.Popen, msg: dict) -> None:
    """Send a JSON command to the sidecar."""
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()


def _read_event(proc: subprocess.Popen, timeout: float = 10.0) -> dict:
    """Read a single JSON event from the sidecar stdout."""
    import threading

    result = [None]
    error = [None]

    def _read():
        try:
            line = proc.stdout.readline()
            if line:
                result[0] = json.loads(line.strip())
        except Exception as exc:
            error[0] = exc

    thread = threading.Thread(target=_read, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        pytest.fail(f"Timeout waiting for sidecar event ({timeout}s)")
    if error[0]:
        raise error[0]
    if result[0] is None:
        pytest.fail("No event received from sidecar")
    return result[0]


def _collect_events(
    proc: subprocess.Popen, until_event: str, timeout: float = 30.0
) -> list[dict]:
    """Collect events from sidecar until a specific event type is seen."""
    events = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        event = _read_event(proc, timeout=max(1.0, remaining))
        events.append(event)
        if event.get("event") == until_event:
            break
    return events


class TestSidecarIntegration:
    """Integration tests that spawn the sidecar as a real subprocess."""

    def test_ready_event_on_startup(self) -> None:
        """Sidecar emits a ready event immediately on startup."""
        proc = _spawn_sidecar()
        try:
            event = _read_event(proc)
            assert event["event"] == "ready"
            assert "version" in event
        finally:
            _send(proc, {"cmd": "shutdown"})
            proc.wait(timeout=5)

    def test_shutdown_command(self) -> None:
        """Sidecar exits cleanly on shutdown command."""
        proc = _spawn_sidecar()
        _read_event(proc)  # consume ready
        _send(proc, {"cmd": "shutdown"})
        rc = proc.wait(timeout=5)
        assert rc == 0

    def test_unknown_command(self) -> None:
        """Unknown command produces an error event."""
        proc = _spawn_sidecar()
        try:
            _read_event(proc)  # consume ready
            _send(proc, {"cmd": "foobar"})
            event = _read_event(proc)
            assert event["event"] == "error"
            assert "foobar" in event["message"]
        finally:
            _send(proc, {"cmd": "shutdown"})
            proc.wait(timeout=5)

    def test_invalid_json(self) -> None:
        """Invalid JSON input produces an error event."""
        proc = _spawn_sidecar()
        try:
            _read_event(proc)  # consume ready
            proc.stdin.write("not valid json\n")
            proc.stdin.flush()
            event = _read_event(proc)
            assert event["event"] == "error"
            assert "Invalid JSON" in event["message"]
        finally:
            _send(proc, {"cmd": "shutdown"})
            proc.wait(timeout=5)

    def test_scan_nonexistent_path(self) -> None:
        """Scanning a nonexistent path emits an error event."""
        proc = _spawn_sidecar()
        try:
            _read_event(proc)  # consume ready
            _send(proc, {"cmd": "scan", "path": "/nonexistent/xyz"})
            event = _read_event(proc)
            assert event["event"] == "error"
            assert "Not a directory" in event["message"]
        finally:
            _send(proc, {"cmd": "shutdown"})
            proc.wait(timeout=5)

    def test_scan_empty_directory(self, tmp_path: Path) -> None:
        """Scanning an empty directory emits a complete event."""
        proc = _spawn_sidecar()
        try:
            _read_event(proc)  # consume ready
            _send(proc, {"cmd": "scan", "path": str(tmp_path)})
            events = _collect_events(proc, "complete", timeout=10)
            complete = [e for e in events if e["event"] == "complete"]
            assert len(complete) == 1
            assert complete[0]["report"]["summary"]["total_files"] == 0
        finally:
            _send(proc, {"cmd": "shutdown"})
            proc.wait(timeout=5)

    def test_scan_with_files(self, tmp_path: Path) -> None:
        """Full scan produces phase events and a complete event with report."""
        for i in range(5):
            (tmp_path / f"file{i}.txt").write_text(
                f"Hello world content number {i}", encoding="utf-8"
            )

        proc = _spawn_sidecar()
        try:
            _read_event(proc)  # consume ready
            _send(proc, {
                "cmd": "scan",
                "path": str(tmp_path),
                "config": {"sampling_rate": 1.0},
            })
            events = _collect_events(proc, "complete", timeout=30)

            event_types = [e["event"] for e in events]
            assert "phase" in event_types
            assert "complete" in event_types

            complete = next(e for e in events if e["event"] == "complete")
            report = complete["report"]
            assert report["summary"]["total_files"] == 5
            assert "type_distribution" in report["summary"]
            assert "duplicates" in report["summary"]
        finally:
            _send(proc, {"cmd": "shutdown"})
            proc.wait(timeout=5)

    def test_cancel_during_scan(self, tmp_path: Path) -> None:
        """Cancel command stops a running scan."""
        # Create enough files to make the scan take a moment
        for i in range(20):
            (tmp_path / f"file{i}.txt").write_text(
                f"content {i}" * 100, encoding="utf-8"
            )

        proc = _spawn_sidecar()
        try:
            _read_event(proc)  # consume ready
            _send(proc, {"cmd": "scan", "path": str(tmp_path)})
            # Wait briefly then cancel
            time.sleep(0.1)
            _send(proc, {"cmd": "cancel"})

            events = _collect_events(proc, "cancelled", timeout=10)
            # Should get either cancelled or complete (if scan finished first)
            event_types = [e["event"] for e in events]
            assert "cancelled" in event_types or "complete" in event_types
        finally:
            _send(proc, {"cmd": "shutdown"})
            proc.wait(timeout=5)

    def test_multiple_scans(self, tmp_path: Path) -> None:
        """Can run multiple scans sequentially."""
        (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")

        proc = _spawn_sidecar()
        try:
            _read_event(proc)  # consume ready

            # First scan
            _send(proc, {"cmd": "scan", "path": str(tmp_path)})
            events1 = _collect_events(proc, "complete", timeout=15)
            assert any(e["event"] == "complete" for e in events1)

            # Second scan
            _send(proc, {"cmd": "scan", "path": str(tmp_path)})
            events2 = _collect_events(proc, "complete", timeout=15)
            assert any(e["event"] == "complete" for e in events2)
        finally:
            _send(proc, {"cmd": "shutdown"})
            proc.wait(timeout=5)
