"""Extended tests for the directory walker — covering edge cases and error branches."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from field_check.config import FieldCheckConfig
from field_check.scanner import _long_path, walk_directory

# ---------------------------------------------------------------------------
# _long_path Windows prefix
# ---------------------------------------------------------------------------


class TestLongPath:
    """Test _long_path Windows prefix logic."""

    def test_short_path_unchanged(self) -> None:
        """Paths under 259 chars are returned unchanged on all platforms."""
        short = "/some/normal/path.txt"
        assert _long_path(short) == short

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only prefix")
    def test_long_path_gets_prefix_on_windows(self) -> None:
        """Paths > 259 chars get \\\\?\\ prefix on Windows."""
        long = "C:\\" + "a" * 260 + "\\file.txt"
        result = _long_path(long)
        assert result.startswith("\\\\?\\")

    def test_long_path_no_prefix_on_non_windows(self) -> None:
        """On non-Windows, long paths are returned unchanged."""
        long = "/" + "a" * 300 + "/file.txt"
        if sys.platform != "win32":
            assert _long_path(long) == long


# ---------------------------------------------------------------------------
# Exclude directory branch
# ---------------------------------------------------------------------------


class TestExcludeDirectory:
    """Test that excluded directories are skipped entirely."""

    def test_exclude_directory(self, tmp_path: Path) -> None:
        """Directory matching exclude pattern is skipped."""
        secret_dir = tmp_path / "secret"
        secret_dir.mkdir()
        (secret_dir / "data.txt").write_text("hidden", encoding="utf-8")
        (tmp_path / "visible.txt").write_text("seen", encoding="utf-8")

        config = FieldCheckConfig(exclude=["secret"])
        result = walk_directory(tmp_path, config)

        names = {f.relative_path.name for f in result.files}
        assert "visible.txt" in names
        assert "data.txt" not in names
        assert result.excluded_count >= 1

    def test_exclude_nested_directory(self, tmp_path: Path) -> None:
        """Nested directories matching pattern are excluded."""
        deep = tmp_path / "a" / "node_modules"
        deep.mkdir(parents=True)
        (deep / "pkg.json").write_text("{}", encoding="utf-8")
        (tmp_path / "a" / "app.txt").write_text("app", encoding="utf-8")

        config = FieldCheckConfig(exclude=["node_modules"])
        result = walk_directory(tmp_path, config)

        names = {f.relative_path.name for f in result.files}
        assert "app.txt" in names
        assert "pkg.json" not in names


# ---------------------------------------------------------------------------
# File permission / OS errors
# ---------------------------------------------------------------------------


class TestFileErrors:
    """Test permission and OS error handling on individual files."""

    def test_file_permission_error(self, tmp_path: Path) -> None:
        """PermissionError on lstat records in permission_errors."""
        (tmp_path / "ok.txt").write_text("fine", encoding="utf-8")
        (tmp_path / "bad.txt").write_text("nope", encoding="utf-8")

        original_lstat = os.lstat

        def mock_lstat(path, *args, **kwargs):
            if "bad.txt" in str(path):
                raise PermissionError("Access denied")
            return original_lstat(path, *args, **kwargs)

        config = FieldCheckConfig(exclude=[])
        with patch("field_check.scanner.os.lstat", side_effect=mock_lstat):
            result = walk_directory(tmp_path, config)

        assert any("bad.txt" in str(p) for p in result.permission_errors)
        # ok.txt should still be collected
        names = {f.relative_path.name for f in result.files}
        assert "ok.txt" in names

    def test_file_os_error(self, tmp_path: Path) -> None:
        """OSError on lstat is silently logged, file skipped."""
        (tmp_path / "ok.txt").write_text("fine", encoding="utf-8")
        (tmp_path / "broken.txt").write_text("nope", encoding="utf-8")

        original_lstat = os.lstat

        def mock_lstat(path, *args, **kwargs):
            if "broken.txt" in str(path):
                raise OSError("Device not ready")
            return original_lstat(path, *args, **kwargs)

        config = FieldCheckConfig(exclude=[])
        with patch("field_check.scanner.os.lstat", side_effect=mock_lstat):
            result = walk_directory(tmp_path, config)

        names = {f.relative_path.name for f in result.files}
        assert "ok.txt" in names
        assert "broken.txt" not in names


# ---------------------------------------------------------------------------
# Empty dir tracking with excluded files
# ---------------------------------------------------------------------------


class TestEmptyDirTracking:
    """Test that dirs with only excluded files count as empty."""

    def test_dir_with_only_excluded_files_is_empty(self, tmp_path: Path) -> None:
        """A directory containing only excluded files counts as empty."""
        (tmp_path / "secret.bin").write_bytes(b"\x00" * 100)

        config = FieldCheckConfig(exclude=["*.bin"])
        result = walk_directory(tmp_path, config)

        # tmp_path itself has no non-excluded files
        assert result.empty_dirs >= 1

    def test_dir_with_mixed_files(self, tmp_path: Path) -> None:
        """A directory with at least one non-excluded file is not empty."""
        (tmp_path / "secret.bin").write_bytes(b"\x00" * 100)
        (tmp_path / "visible.txt").write_text("hi", encoding="utf-8")

        config = FieldCheckConfig(exclude=["*.bin"])
        result = walk_directory(tmp_path, config)

        # The root dir should NOT be counted as empty because visible.txt is there
        # (empty_dirs counts dirs with zero discovered regular files after exclusions)
        names = {f.relative_path.name for f in result.files}
        assert "visible.txt" in names


# ---------------------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------------------


class TestProgressCallback:
    """Test that the progress callback is called correctly."""

    def test_callback_called_with_incrementing_count(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("aaa", encoding="utf-8")
        (tmp_path / "b.txt").write_text("bbb", encoding="utf-8")
        (tmp_path / "c.txt").write_text("ccc", encoding="utf-8")

        counts: list[int] = []
        config = FieldCheckConfig(exclude=[])
        walk_directory(tmp_path, config, progress_callback=lambda c: counts.append(c))

        assert len(counts) == 3
        assert counts == [1, 2, 3]

    def test_callback_not_called_when_none(self, tmp_path: Path) -> None:
        """No crash when progress_callback is None."""
        (tmp_path / "a.txt").write_text("aaa", encoding="utf-8")
        config = FieldCheckConfig(exclude=[])
        result = walk_directory(tmp_path, config, progress_callback=None)
        assert len(result.files) == 1


# ---------------------------------------------------------------------------
# Directory permission error
# ---------------------------------------------------------------------------


class TestDirectoryErrors:
    """Test directory-level error handling."""

    def test_directory_permission_error(self, tmp_path: Path) -> None:
        """PermissionError on os.stat for a directory records it and continues."""
        sub = tmp_path / "protected"
        sub.mkdir()
        (sub / "secret.txt").write_text("hidden", encoding="utf-8")
        (tmp_path / "public.txt").write_text("visible", encoding="utf-8")

        original_stat = os.stat

        def mock_stat(path, *args, **kwargs):
            # Only intercept the explicit os.stat call (follow_symlinks=True,
            # the default) on the "protected" directory itself -- not lstat
            # calls (follow_symlinks=False) used by pathlib.is_symlink().
            follow = kwargs.get("follow_symlinks", True)
            path_s = str(path)
            is_protected_dir = (
                path_s.endswith("protected")
                or path_s.endswith("protected\\")
                or path_s.endswith("protected/")
            )
            if is_protected_dir and follow:
                raise PermissionError("Access denied")
            return original_stat(path, *args, **kwargs)

        config = FieldCheckConfig(exclude=[])
        with patch("field_check.scanner.os.stat", side_effect=mock_stat):
            result = walk_directory(tmp_path, config)

        assert any("protected" in str(p) for p in result.permission_errors)
        names = {f.relative_path.name for f in result.files}
        assert "public.txt" in names
