"""Sidecar entry point for Tauri GUI communication.

Long-lived process that reads newline-delimited JSON commands from
stdin and writes newline-delimited JSON events to stdout. All logging
goes to stderr to avoid corrupting the JSON stream.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from pathlib import Path

from field_check import __version__
from field_check.config import FieldCheckConfig
from field_check.pipeline import run_pipeline
from field_check.report.json_report import render_json_report

# Route all logging to stderr so stdout stays clean for JSON IPC
logging.basicConfig(
    stream=sys.stderr,
    level=logging.WARNING,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _emit(event: dict) -> None:
    """Write a JSON event to stdout, newline-terminated and flushed."""
    print(json.dumps(event, default=str), flush=True)


def _build_config(raw: dict) -> FieldCheckConfig:
    """Build a FieldCheckConfig from a JSON dict.

    Args:
        raw: Config dict from the GUI. Keys match FieldCheckConfig fields.

    Returns:
        FieldCheckConfig with values from raw, defaults for missing keys.
    """
    config = FieldCheckConfig()
    if "sampling_rate" in raw:
        config.sampling_rate = max(0.0, min(1.0, float(raw["sampling_rate"])))
        config.sampling_rate_auto = False
    if "exclude" in raw and isinstance(raw["exclude"], list):
        config.exclude = list(config.exclude) + raw["exclude"]
    if "show_pii_samples" in raw:
        config.show_pii_samples = bool(raw["show_pii_samples"])
    if "pii_min_confidence" in raw:
        config.pii_min_confidence = max(
            0.0, min(1.0, float(raw["pii_min_confidence"]))
        )
    if "simhash_threshold" in raw:
        config.simhash_threshold = int(raw["simhash_threshold"])
    if "simhash_bits" in raw:
        config.simhash_bits = int(raw["simhash_bits"])
    return config


def _run_scan(
    scan_path: str,
    config_raw: dict,
    cancel_event: threading.Event,
) -> None:
    """Run a scan and emit events. Called in a background thread.

    Args:
        scan_path: Directory to scan.
        config_raw: Raw config dict from GUI.
        cancel_event: Set by main thread to request cancellation.
    """
    path = Path(scan_path).resolve()
    if not path.is_dir():
        _emit({"event": "error", "message": f"Not a directory: {path}"})
        return

    config = _build_config(config_raw)

    def on_phase(name: str, index: int, total: int) -> None:
        if cancel_event.is_set():
            return
        _emit({
            "event": "phase",
            "name": name,
            "index": index,
            "total": total,
        })

    def on_progress(phase: str, current: int, total: int) -> None:
        if cancel_event.is_set():
            return
        _emit({
            "event": "progress",
            "phase": phase,
            "current": current,
            "total": total,
        })

    try:
        result = run_pipeline(
            path, config, on_phase=on_phase, on_progress=on_progress
        )
    except Exception as exc:
        if cancel_event.is_set():
            _emit({"event": "cancelled"})
        else:
            _emit({"event": "error", "message": str(exc)})
        return

    if cancel_event.is_set():
        _emit({"event": "cancelled"})
        return

    if result.empty:
        _emit({
            "event": "complete",
            "report": {
                "summary": {"total_files": 0},
                "files": [],
            },
        })
        return

    # Build the full JSON report using the existing renderer
    report_json = render_json_report(
        result.inventory,
        result.walk,
        result.elapsed_seconds,
        dedup_result=result.dedup,
        corruption_result=result.corruption,
        sample_result=result.sample,
        text_result=result.text,
        pii_result=result.pii,
        language_result=result.language,
        encoding_result=result.encoding,
        simhash_result=result.simhash,
        mojibake_result=result.mojibake,
        readability_result=result.readability,
    )
    report_data = json.loads(report_json)
    _emit({"event": "complete", "report": report_data})


def main() -> None:
    """Sidecar main loop. Reads commands from stdin, emits events to stdout."""
    _emit({"event": "ready", "version": __version__})

    cancel_event = threading.Event()
    scan_thread: threading.Thread | None = None

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _emit({"event": "error", "message": "Invalid JSON"})
            continue

        cmd = msg.get("cmd")

        if cmd == "scan":
            # Cancel any running scan first
            if scan_thread and scan_thread.is_alive():
                cancel_event.set()
                scan_thread.join(timeout=5)

            cancel_event.clear()
            scan_path = msg.get("path", "")
            config_raw = msg.get("config", {})
            scan_thread = threading.Thread(
                target=_run_scan,
                args=(scan_path, config_raw, cancel_event),
                daemon=True,
            )
            scan_thread.start()

        elif cmd == "cancel":
            cancel_event.set()

        elif cmd == "shutdown":
            cancel_event.set()
            if scan_thread and scan_thread.is_alive():
                scan_thread.join(timeout=5)
            break

        else:
            _emit({
                "event": "error",
                "message": f"Unknown command: {cmd}",
            })


if __name__ == "__main__":
    main()
