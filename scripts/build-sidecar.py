"""Build the Python scanner sidecar binary for Tauri.

Compiles the sidecar entry point with PyInstaller and copies the
resulting binary to src-tauri/binaries/ with the correct target
triple naming convention.

Usage:
    python scripts/build-sidecar.py
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIDECAR_ENTRY = ROOT / "src" / "field_check" / "sidecar.py"
TEMPLATES_DIR = ROOT / "src" / "field_check" / "templates"
BINARIES_DIR = ROOT / "src-tauri" / "binaries"
DIST_DIR = ROOT / "dist"


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
        # Fallback: construct from platform info
        system = platform.system().lower()
        machine = platform.machine().lower()

        if system == "windows":
            arch = "x86_64" if machine in ("amd64", "x86_64") else machine
            return f"{arch}-pc-windows-msvc"
        elif system == "darwin":
            arch = "aarch64" if machine == "arm64" else "x86_64"
            return f"{arch}-apple-darwin"
        else:
            arch = "x86_64" if machine in ("amd64", "x86_64") else machine
            return f"{arch}-unknown-linux-gnu"


def build() -> None:
    """Build the sidecar binary with PyInstaller."""
    triple = get_target_triple()
    binary_name = f"scanner-{triple}"
    print(f"Building sidecar for: {triple}")
    print(f"Binary name: {binary_name}")

    # Build with PyInstaller
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        binary_name,
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(ROOT / "build" / "pyinstaller"),
        "--specpath",
        str(ROOT / "build"),
        # Include templates for HTML report export
        "--add-data",
        f"{TEMPLATES_DIR}{':' if sys.platform != 'win32' else ';'}field_check/templates",
        # Exclude unnecessary packages
        "--exclude-module",
        "tkinter",
        "--exclude-module",
        "boto3",
        "--exclude-module",
        "google.cloud",
        "--exclude-module",
        "azure",
        # Console mode required for stdin/stdout IPC
        "--console",
        str(SIDECAR_ENTRY),
    ]

    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

    # Copy to src-tauri/binaries/
    BINARIES_DIR.mkdir(parents=True, exist_ok=True)

    ext = ".exe" if sys.platform == "win32" else ""
    src = DIST_DIR / f"{binary_name}{ext}"
    dst = BINARIES_DIR / f"{binary_name}{ext}"

    if not src.exists():
        print(f"ERROR: Built binary not found at {src}")
        sys.exit(1)

    shutil.copy2(src, dst)
    print(f"Copied {src} -> {dst}")
    print("Sidecar build complete!")


if __name__ == "__main__":
    build()
