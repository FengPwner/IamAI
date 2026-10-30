#!/usr/bin/env python3
"""Tests for merge_conflict_scanner.py.

Run with:
    python3 -m pytest tools/test_merge_conflict_scanner.py -v
    # or directly:
    python3 tools/test_merge_conflict_scanner.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure the tools directory is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from merge_conflict_scanner import (  # noqa: E402
    ConflictHit,
    ScanResult,
    scan_file,
)


class TestScanFile(unittest.TestCase):
    """Unit tests for scan_file()."""

    def _write_tmp(self, content: str) -> Path:
        fd, path = tempfile.mkstemp(suffix=".md", text=True)
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        return Path(path)

    def test_clean_file(self):
        """A file with no conflict markers returns no hits."""
        p = self._write_tmp("hello world\nno conflicts here\n")
        try:
            hits = scan_file(p, "clean.md")
            self.assertEqual(hits, [])
        finally:
            p.unlink()

    def test_ours_marker(self):
        """Detects <<<<<<< HEAD marker."""
        p = self._write_tmp("<<<<<<< HEAD\nour change\n=======\ntheir change\n>>>>>>> feature\n")
        try:
            hits = scan_file(p, "conflict.md")
            markers = [h.marker for h in hits]
            self.assertIn("ours", markers)
            self.assertIn("separator", markers)
            self.assertIn("theirs", markers)
            self.assertEqual(len(hits), 3)
        finally:
            p.unlink()

    def test_line_numbers(self):
        """Line numbers are 1-indexed and correct."""
        content = "line one\n<<<<<<< HEAD\nline three\n=======\nline five\n>>>>>>> branch\nline seven\n"
        p = self._write_tmp(content)
        try:
            hits = scan_file(p, "numbered.md")
            lines = {h.marker: h.line for h in hits}
            self.assertEqual(lines["ours"], 2)
            self.assertEqual(lines["separator"], 4)
            self.assertEqual(lines["theirs"], 6)
        finally:
            p.unlink()

    def test_multiple_conflicts(self):
        """Detects multiple conflict blocks in one file."""
        content = (
            "<<<<<<< HEAD\nA\n=======\nB\n>>>>>>> br1\n"
            "clean line\n"
            "<<<<<<< HEAD\nC\n=======\nD\n>>>>>>> br2\n"
        )
        p = self._write_tmp(content)
        try:
            hits = scan_file(p, "multi.md")
            ours_hits = [h for h in hits if h.marker == "ours"]
            theirs_hits = [h for h in hits if h.marker == "theirs"]
            self.assertEqual(len(ours_hits), 2)
            self.assertEqual(len(theirs_hits), 2)
        finally:
            p.unlink()

    def test_binary_file_skipped(self):
        """Binary files (containing NUL bytes) are skipped."""
        p = self._write_tmp("<<<<<<< HEAD\n\x00binary\x00data\n")
        try:
            hits = scan_file(p, "binary.bin")
            self.assertEqual(hits, [])
        finally:
            p.unlink()

    def test_nonexistent_file(self):
        """Missing file returns empty list, no exception."""
        hits = scan_file(Path("/nonexistent/fake.md"), "fake.md")
        self.assertEqual(hits, [])

    def test_content_preserved(self):
        """The full marker line is captured in the hit."""
        p = self._write_tmp("<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> feature-branch\n")
        try:
            hits = scan_file(p, "content.md")
            ours = [h for h in hits if h.marker == "ours"][0]
            theirs = [h for h in hits if h.marker == "theirs"][0]
            self.assertEqual(ours.content, "<<<<<<< HEAD")
            self.assertEqual(theirs.content, ">>>>>>> feature-branch")
        finally:
            p.unlink()


class TestScanResult(unittest.TestCase):
    """Unit tests for ScanResult."""

    def test_clean_when_no_conflicts(self):
        r = ScanResult(scanned=10, conflicts=[])
        self.assertTrue(r.clean)

    def test_not_clean_with_conflicts(self):
        r = ScanResult(scanned=10, conflicts=[{"file": "x", "line": 1}])
        self.assertFalse(r.clean)

    def test_to_dict(self):
        r = ScanResult(scanned=5, conflicts=[])
        d = r.to_dict()
        self.assertEqual(d["scanned"], 5)
        self.assertTrue(d["clean"])
        self.assertEqual(d["conflicts"], [])


class TestConflictHit(unittest.TestCase):
    """Unit tests for ConflictHit dataclass."""

    def test_fields(self):
        h = ConflictHit("file.py", 42, "ours", "<<<<<<< HEAD")
        self.assertEqual(h.file, "file.py")
        self.assertEqual(h.line, 42)
        self.assertEqual(h.marker, "ours")
        self.assertEqual(h.content, "<<<<<<< HEAD")


if __name__ == "__main__":
    unittest.main(verbosity=2)
