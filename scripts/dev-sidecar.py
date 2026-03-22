"""Create a dev-mode sidecar wrapper for Tauri development.

Creates a script in src-tauri/binaries/ that runs the Python sidecar
directly (without PyInstaller) for fast iteration during development.

Usage:
    python scripts/dev-sidecar.py
"""

from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BINARIES_DIR = ROOT / "src-tauri" / "binaries"


def get_target_triple() -> str:
    """Get the Rust target triple for the current platform."""
    try:
        result = subprocess.run(
            ["rustc", "--print", "host-tuple"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "x86_64-pc-windows-msvc"


def create_wrapper() -> None:
    """Create a dev wrapper script matching the sidecar naming convention."""
    triple = get_target_triple()
    BINARIES_DIR.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        # Windows batch file
        wrapper = BINARIES_DIR / f"scanner-{triple}.exe.cmd"
        # Use a .cmd that Tauri can find. Note: Tauri looks for .exe,
        # so we create a .exe batch file (rename trick).
        wrapper = BINARIES_DIR / f"scanner-{triple}.exe"
        # Actually write a Python launcher script
        launcher = BINARIES_DIR / f"scanner-{triple}.bat"
        python_path = sys.executable.replace("\\", "/")
        sidecar_module = "field_check.sidecar"
        launcher.write_text(
            f'@echo off\n"{python_path}" -m {sidecar_module}\n',
            encoding="utf-8",
        )
        print(f"Created dev wrapper: {launcher}")
        print(
            "NOTE: For Tauri dev mode on Windows, you may need to "
            "run the sidecar manually or build with PyInstaller."
        )
    else:
        # Unix shell script
        wrapper = BINARIES_DIR / f"scanner-{triple}"
        python_path = sys.executable
        wrapper.write_text(
            f'#!/bin/sh\nexec "{python_path}" -m field_check.sidecar "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
        print(f"Created dev wrapper: {wrapper}")

    print("Dev sidecar wrapper ready for Tauri dev mode.")


if __name__ == "__main__":
    create_wrapper()
