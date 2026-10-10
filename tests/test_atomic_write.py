"""Tests for snippets/atomic_write.py — readers see old or new, never torn."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from atomic_write import (  # noqa: E402
    AtomicWriter,
    atomic_write_bytes,
    atomic_write_text,
)


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


# ── atomic_write_text ────────────────────────────────────────────────────────


class TestAtomicWriteText:
    def test_basic_write(self, tmp_dir):
        target = tmp_dir / "out.txt"
        atomic_write_text(target, "hello world")
        assert target.read_text() == "hello world"

    def test_overwrite_existing(self, tmp_dir):
        target = tmp_dir / "out.txt"
        target.write_text("old content")
        atomic_write_text(target, "new content")
        assert target.read_text() == "new content"

    def test_creates_parent_dirs(self, tmp_dir):
        target = tmp_dir / "a" / "b" / "c" / "deep.txt"
        atomic_write_text(target, "nested")
        assert target.read_text() == "nested"

    def test_no_temp_file_left(self, tmp_dir):
        target = tmp_dir / "out.txt"
        atomic_write_text(target, "clean")
        leftovers = [f for f in tmp_dir.iterdir() if f.suffix == ".tmp"]
        assert leftovers == [], "temp file should be cleaned up"

    def test_unicode_content(self, tmp_dir):
        target = tmp_dir / "uni.txt"
        text = "你好世界 🌍 café"
        atomic_write_text(target, text)
        assert target.read_text(encoding="utf-8") == text

    def test_empty_string(self, tmp_dir):
        target = tmp_dir / "empty.txt"
        atomic_write_text(target, "")
        assert target.read_text() == ""

    def test_large_content(self, tmp_dir):
        target = tmp_dir / "big.txt"
        data = "x" * (1024 * 1024)  # 1 MB
        atomic_write_text(target, data)
        assert len(target.read_text()) == len(data)

    def test_encoding_latin1(self, tmp_dir):
        target = tmp_dir / "latin.txt"
        text = "café"
        atomic_write_text(target, text, encoding="latin-1")
        assert target.read_bytes() == text.encode("latin-1")


# ── atomic_write_bytes ───────────────────────────────────────────────────────


class TestAtomicWriteBytes:
    def test_basic_bytes(self, tmp_dir):
        target = tmp_dir / "bin.dat"
        atomic_write_bytes(target, b"\x00\x01\x02")
        assert target.read_bytes() == b"\x00\x01\x02"

    def test_empty_bytes(self, tmp_dir):
        target = tmp_dir / "empty.dat"
        atomic_write_bytes(target, b"")
        assert target.read_bytes() == b""

    def test_overwrite_preserves_nothing_on_success(self, tmp_dir):
        target = tmp_dir / "data.bin"
        target.write_bytes(b"old")
        atomic_write_bytes(target, b"new")
        assert target.read_bytes() == b"new"
        leftovers = [f for f in tmp_dir.iterdir() if f.suffix == ".tmp"]
        assert leftovers == []


# ── AtomicWriter context manager ─────────────────────────────────────────────


class TestAtomicWriterContext:
    def test_basic_stream(self, tmp_dir):
        target = tmp_dir / "stream.txt"
        with AtomicWriter(target) as f:
            f.write("line 1\n")
            f.write("line 2\n")
        assert target.read_text() == "line 1\nline 2\n"

    def test_no_temp_on_success(self, tmp_dir):
        target = tmp_dir / "stream.txt"
        with AtomicWriter(target) as f:
            f.write("ok")
        leftovers = [f for f in tmp_dir.iterdir() if f.suffix == ".tmp"]
        assert leftovers == []

    def test_cleanup_on_exception(self, tmp_dir):
        target = tmp_dir / "fail.txt"
        # Pre-populate so we can verify the old file is untouched.
        target.write_text("original")

        with pytest.raises(RuntimeError):
            with AtomicWriter(target) as f:
                f.write("partial")
                raise RuntimeError("simulated failure")

        # Original file should be unchanged.
        assert target.read_text() == "original"
        leftovers = [f for f in tmp_dir.iterdir() if f.suffix == ".tmp"]
        assert leftovers == []

    def test_binary_mode(self, tmp_dir):
        target = tmp_dir / "bin.bin"
        with AtomicWriter(target, mode="wb") as f:
            f.write(b"\xff\xfe")
        assert target.read_bytes() == b"\xff\xfe"

    def test_creates_parent_dirs(self, tmp_dir):
        target = tmp_dir / "x" / "y" / "deep.txt"
        with AtomicWriter(target) as f:
            f.write("nested stream")
        assert target.read_text() == "nested stream"

    def test_overwrite_existing(self, tmp_dir):
        target = tmp_dir / "ow.txt"
        target.write_text("before")
        with AtomicWriter(target) as f:
            f.write("after")
        assert target.read_text() == "after"


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_pathlib_path_accepted(self, tmp_dir):
        target = tmp_dir / "pathlib.txt"
        atomic_write_text(target, "pathlib works")
        assert target.read_text() == "pathlib works"

    def test_string_path_accepted(self, tmp_dir):
        target = str(tmp_dir / "strpath.txt")
        atomic_write_text(target, "string works")
        assert open(target).read() == "string works"

    def test_concurrent_writes_last_wins(self, tmp_dir):
        """Two sequential writes — the second should be what's on disk."""
        target = tmp_dir / "race.txt"
        atomic_write_text(target, "first")
        atomic_write_text(target, "second")
        assert target.read_text() == "second"
