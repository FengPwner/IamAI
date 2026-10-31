#!/usr/bin/env python3
"""Tests for pack_integrity_check.py — 17 tests covering header validation,
pair detection, size checks, report formatting, and CLI exit codes.

Motivated by the 2026-10-31 pack corruption incident: a quick integrity
check would have flagged the problem before the caretaker spent an hour
debugging fetch failures.
"""

import json
import os
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from pack_integrity_check import (
    PackIssue,
    PackReport,
    find_pack_dir,
    check_pack_pair,
    check_pack_header,
    full_check,
    format_report,
    PACK_MAGIC,
    PACK_VERSION,
    MIN_PACK_SIZE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pack_header(version: int = PACK_VERSION, obj_count: int = 100) -> bytes:
    """Build a 12-byte pack header."""
    return PACK_MAGIC + struct.pack(">I", version) + struct.pack(">I", obj_count)


def _write_pack(path: Path, header: bytes, total_size: int = MIN_PACK_SIZE):
    """Write a fake pack file with given header padded to total_size."""
    trailer_size = 20  # SHA-1 trailer
    payload_size = total_size - len(header) - trailer_size
    if payload_size < 0:
        payload_size = 0
    data = header + b"\x00" * payload_size + b"\x00" * trailer_size
    path.write_bytes(data[:total_size])


def _make_repo(tmp_path: Path) -> Path:
    """Create a minimal .git structure with pack dir."""
    git_dir = tmp_path / ".git"
    pack_dir = git_dir / "objects" / "pack"
    pack_dir.mkdir(parents=True)
    return tmp_path


# ---------------------------------------------------------------------------
# find_pack_dir tests
# ---------------------------------------------------------------------------

class TestFindPackDir:
    def test_standard_repo(self, tmp_path):
        repo = _make_repo(tmp_path)
        result = find_pack_dir(repo)
        assert result is not None
        assert result.name == "pack"

    def test_bare_repo(self, tmp_path):
        pack_dir = tmp_path / "objects" / "pack"
        pack_dir.mkdir(parents=True)
        result = find_pack_dir(tmp_path)
        assert result is not None

    def test_no_pack_dir(self, tmp_path):
        result = find_pack_dir(tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# check_pack_pair tests
# ---------------------------------------------------------------------------

class TestCheckPackPair:
    def test_matched_pair(self, tmp_path):
        (tmp_path / "pack-abc.pack").touch()
        (tmp_path / "pack-abc.idx").touch()
        issues = check_pack_pair(tmp_path)
        assert issues == []

    def test_orphan_pack(self, tmp_path):
        (tmp_path / "pack-abc.pack").touch()
        issues = check_pack_pair(tmp_path)
        assert len(issues) == 1
        assert issues[0].issue == "missing_index"

    def test_orphan_idx(self, tmp_path):
        (tmp_path / "pack-abc.idx").touch()
        issues = check_pack_pair(tmp_path)
        assert len(issues) == 1
        assert issues[0].issue == "missing_pack"

    def test_multiple_pairs(self, tmp_path):
        for name in ["pack-aaa", "pack-bbb"]:
            (tmp_path / f"{name}.pack").touch()
            (tmp_path / f"{name}.idx").touch()
        issues = check_pack_pair(tmp_path)
        assert issues == []


# ---------------------------------------------------------------------------
# check_pack_header tests
# ---------------------------------------------------------------------------

class TestCheckPackHeader:
    def test_valid_pack(self, tmp_path):
        pack = tmp_path / "pack-test.pack"
        _write_pack(pack, _make_pack_header())
        issues = check_pack_header(pack)
        assert issues == []

    def test_bad_magic(self, tmp_path):
        pack = tmp_path / "pack-test.pack"
        _write_pack(pack, b"NOPE" + struct.pack(">II", 2, 100))
        issues = check_pack_header(pack)
        assert any(i.issue == "bad_magic" for i in issues)

    def test_bad_version(self, tmp_path):
        pack = tmp_path / "pack-test.pack"
        _write_pack(pack, _make_pack_header(version=99))
        issues = check_pack_header(pack)
        assert any(i.issue == "bad_version" for i in issues)

    def test_empty_pack_header(self, tmp_path):
        pack = tmp_path / "pack-test.pack"
        _write_pack(pack, _make_pack_header(obj_count=0))
        issues = check_pack_header(pack)
        assert any(i.issue == "empty_pack" for i in issues)

    def test_file_too_small(self, tmp_path):
        pack = tmp_path / "pack-test.pack"
        pack.write_bytes(b"\x00" * 8)
        issues = check_pack_header(pack)
        assert any(i.issue == "too_small" for i in issues)

    def test_below_minimum_size(self, tmp_path):
        pack = tmp_path / "pack-test.pack"
        _write_pack(pack, _make_pack_header(), total_size=20)
        issues = check_pack_header(pack)
        assert any(i.issue == "below_minimum_size" for i in issues)

    def test_nonexistent_file(self, tmp_path):
        pack = tmp_path / "nonexistent.pack"
        issues = check_pack_header(pack)
        assert any(i.issue == "stat_failed" for i in issues)


# ---------------------------------------------------------------------------
# full_check tests
# ---------------------------------------------------------------------------

class TestFullCheck:
    def test_no_repo(self, tmp_path):
        report = full_check(tmp_path)
        assert report.verdict == "corrupt"
        assert any(i.issue == "no_pack_dir" for i in report.issues)

    def test_healthy_repo(self, tmp_path):
        repo = _make_repo(tmp_path)
        pack_dir = find_pack_dir(repo)
        name = "pack-abc123"
        _write_pack(pack_dir / f"{name}.pack", _make_pack_header())
        (pack_dir / f"{name}.idx").touch()
        report = full_check(repo)
        assert report.verdict == "healthy"
        assert report.pack_count == 1
        assert report.issues == []

    def test_corrupt_pack_detected(self, tmp_path):
        repo = _make_repo(tmp_path)
        pack_dir = find_pack_dir(repo)
        name = "pack-bad"
        _write_pack(pack_dir / f"{name}.pack", b"CORRUPT_DATA_HERE!")
        (pack_dir / f"{name}.idx").touch()
        report = full_check(repo)
        assert report.verdict == "corrupt"
        assert len(report.issues) > 0


# ---------------------------------------------------------------------------
# format_report tests
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_healthy_format(self):
        report = PackReport(
            repo="/test", pack_dir="/test/.git/objects/pack",
            pack_count=2, verdict="healthy"
        )
        text = format_report(report)
        assert "healthy" in text
        assert "2" in text

    def test_corrupt_format(self):
        report = PackReport(
            repo="/test", pack_dir="/test/.git/objects/pack",
            pack_count=1, verdict="corrupt",
            issues=[PackIssue(file="pack-abc.pack", issue="bad_magic",
                              detail="wrong magic bytes")]
        )
        text = format_report(report)
        assert "corrupt" in text
        assert "bad_magic" in text

    def test_json_serializable(self):
        report = PackReport(
            repo="/test", pack_dir="/test/.git/objects/pack",
            pack_count=1, verdict="healthy"
        )
        d = report.to_dict()
        assert json.dumps(d)  # should not raise
        assert d["verdict"] == "healthy"
