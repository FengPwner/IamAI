"""Tests for iamai.stroke_checksum — append-only log integrity verification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iamai.stroke_checksum import (
    ChecksumResult,
    _compute_digest,
    _normalise_line,
    checksum,
    checksum_incremental,
    pin_baseline,
    verify,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path, lines: list[str] | None = None) -> Path:
    """Create a fake repo with a strokes.jsonl."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    if lines is not None:
        with open(data_dir / "strokes.jsonl", "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")
    return tmp_path


def _stroke_line(seq: int, text: str = "test") -> str:
    return json.dumps({"seq": seq, "at": "2026-10-16T00:00:00+00:00", "kind": "thought", "text": text})


# ---------------------------------------------------------------------------
# _normalise_line
# ---------------------------------------------------------------------------


class TestNormaliseLine:
    def test_strips_trailing_newline(self):
        assert _normalise_line("hello\n") == "hello"

    def test_strips_trailing_spaces(self):
        assert _normalise_line("hello   ") == "hello"

    def test_strips_crlf(self):
        assert _normalise_line("hello\r\n") == "hello"

    def test_preserves_content(self):
        assert _normalise_line("hello world") == "hello world"

    def test_empty_line(self):
        assert _normalise_line("") == ""

    def test_whitespace_only(self):
        assert _normalise_line("   \n") == ""


# ---------------------------------------------------------------------------
# _compute_digest
# ---------------------------------------------------------------------------


class TestComputeDigest:
    def test_empty_list(self):
        digest = _compute_digest([])
        assert isinstance(digest, str)
        assert len(digest) == 64  # sha256 hex length

    def test_deterministic(self):
        lines = ["hello", "world"]
        assert _compute_digest(lines) == _compute_digest(lines)

    def test_order_matters(self):
        assert _compute_digest(["a", "b"]) != _compute_digest(["b", "a"])

    def test_blank_lines_skipped(self):
        assert _compute_digest(["a", "", "b"]) == _compute_digest(["a", "b"])

    def test_whitespace_lines_skipped(self):
        assert _compute_digest(["a", "   ", "b"]) == _compute_digest(["a", "b"])

    def test_trailing_whitespace_ignored(self):
        assert _compute_digest(["hello   "]) == _compute_digest(["hello"])

    def test_different_content_different_digest(self):
        assert _compute_digest(["foo"]) != _compute_digest(["bar"])


# ---------------------------------------------------------------------------
# checksum
# ---------------------------------------------------------------------------


class TestChecksum:
    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            checksum(tmp_path)

    def test_single_line(self, tmp_path):
        repo = _make_repo(tmp_path, [_stroke_line(1)])
        result = checksum(repo)
        assert isinstance(result, ChecksumResult)
        assert result.line_count == 1
        assert result.algo == "sha256"
        assert len(result.digest) == 64

    def test_multiple_lines(self, tmp_path):
        lines = [_stroke_line(i) for i in range(10)]
        repo = _make_repo(tmp_path, lines)
        result = checksum(repo)
        assert result.line_count == 10

    def test_deterministic(self, tmp_path):
        lines = [_stroke_line(i) for i in range(5)]
        repo = _make_repo(tmp_path, lines)
        r1 = checksum(repo)
        r2 = checksum(repo)
        assert r1.digest == r2.digest

    def test_append_changes_checksum(self, tmp_path):
        lines = [_stroke_line(i) for i in range(5)]
        repo = _make_repo(tmp_path, lines)
        r1 = checksum(repo)

        # Append a new line
        with open(repo / "data" / "strokes.jsonl", "a") as f:
            f.write(_stroke_line(5) + "\n")
        r2 = checksum(repo)
        assert r1.digest != r2.digest
        assert r2.line_count == 6

    def test_edit_changes_checksum(self, tmp_path):
        lines = [_stroke_line(i, f"original {i}") for i in range(3)]
        repo = _make_repo(tmp_path, lines)
        r1 = checksum(repo)

        # Modify middle line
        modified = [_stroke_line(0, "original 0"), _stroke_line(1, "TAMPERED"), _stroke_line(2, "original 2")]
        _make_repo(tmp_path, modified)
        r2 = checksum(repo)
        assert r1.digest != r2.digest

    def test_short(self, tmp_path):
        repo = _make_repo(tmp_path, [_stroke_line(1)])
        result = checksum(repo)
        assert len(result.short()) == 12
        assert len(result.short(8)) == 8
        assert result.short() == result.digest[:12]


# ---------------------------------------------------------------------------
# checksum_incremental
# ---------------------------------------------------------------------------


class TestChecksumIncremental:
    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            checksum_incremental(tmp_path)

    def test_matches_full_checksum(self, tmp_path):
        lines = [_stroke_line(i) for i in range(20)]
        repo = _make_repo(tmp_path, lines)
        full = checksum(repo)
        incr = checksum_incremental(repo)
        assert full.digest == incr.digest
        assert full.line_count == incr.line_count

    def test_single_line(self, tmp_path):
        repo = _make_repo(tmp_path, [_stroke_line(1)])
        full = checksum(repo)
        incr = checksum_incremental(repo)
        assert full.digest == incr.digest

    def test_large_file(self, tmp_path):
        """Ensure incremental works on larger files without issues."""
        lines = [_stroke_line(i, f"text for stroke {i}") for i in range(500)]
        repo = _make_repo(tmp_path, lines)
        full = checksum(repo)
        incr = checksum_incremental(repo)
        assert full.digest == incr.digest
        assert incr.line_count == 500


# ---------------------------------------------------------------------------
# pin_baseline / verify
# ---------------------------------------------------------------------------


class TestBaseline:
    def test_pin_creates_file(self, tmp_path):
        repo = _make_repo(tmp_path, [_stroke_line(1)])
        pin_baseline(repo)
        assert (repo / ".stroke_checksum").exists()

    def test_pin_writes_valid_json(self, tmp_path):
        repo = _make_repo(tmp_path, [_stroke_line(1)])
        pin_baseline(repo)
        data = json.loads((repo / ".stroke_checksum").read_text())
        assert "digest" in data
        assert "line_count" in data
        assert data["algo"] == "sha256"

    def test_verify_after_pin(self, tmp_path):
        lines = [_stroke_line(i) for i in range(5)]
        repo = _make_repo(tmp_path, lines)
        pin_baseline(repo)
        ok, reason = verify(repo)
        assert ok is True
        assert "matches" in reason

    def test_verify_detects_tamper(self, tmp_path):
        lines = [_stroke_line(i, f"original {i}") for i in range(3)]
        repo = _make_repo(tmp_path, lines)
        pin_baseline(repo)

        # Tamper with the file
        tampered = [_stroke_line(0, "original 0"), _stroke_line(1, "HACKED"), _stroke_line(2, "original 2")]
        _make_repo(tmp_path, tampered)
        ok, reason = verify(repo)
        assert ok is False
        assert "mismatch" in reason

    def test_verify_detects_truncation(self, tmp_path):
        lines = [_stroke_line(i) for i in range(10)]
        repo = _make_repo(tmp_path, lines)
        pin_baseline(repo)

        # Truncate the file
        _make_repo(tmp_path, lines[:5])
        ok, reason = verify(repo)
        assert ok is False

    def test_verify_detects_append(self, tmp_path):
        lines = [_stroke_line(i) for i in range(5)]
        repo = _make_repo(tmp_path, lines)
        pin_baseline(repo)

        # Append new lines
        with open(repo / "data" / "strokes.jsonl", "a") as f:
            f.write(_stroke_line(5) + "\n")
        ok, reason = verify(repo)
        assert ok is False  # append changes the checksum

    def test_verify_no_baseline(self, tmp_path):
        repo = _make_repo(tmp_path, [_stroke_line(1)])
        ok, reason = verify(repo)
        assert ok is False
        assert "no baseline" in reason

    def test_verify_with_explicit_digest(self, tmp_path):
        lines = [_stroke_line(i) for i in range(5)]
        repo = _make_repo(tmp_path, lines)
        result = checksum(repo)
        ok, reason = verify(repo, expected_digest=result.digest)
        assert ok is True

    def test_verify_with_wrong_digest(self, tmp_path):
        repo = _make_repo(tmp_path, [_stroke_line(1)])
        ok, reason = verify(repo, expected_digest="0" * 64)
        assert ok is False
        assert "mismatch" in reason

    def test_verify_missing_file(self, tmp_path):
        # No strokes file at all
        ok, reason = verify(tmp_path, expected_digest="abc")
        assert ok is False
        assert "not found" in reason


# ---------------------------------------------------------------------------
# ChecksumResult dataclass
# ---------------------------------------------------------------------------


class TestChecksumResult:
    def test_frozen(self):
        r = ChecksumResult(digest="abc", line_count=5)
        with pytest.raises(AttributeError):
            r.digest = "xyz"

    def test_defaults(self):
        r = ChecksumResult(digest="abc", line_count=5)
        assert r.algo == "sha256"

    def test_short_default(self):
        r = ChecksumResult(digest="a" * 64, line_count=1)
        assert r.short() == "a" * 12

    def test_short_custom(self):
        r = ChecksumResult(digest="abcdef1234567890", line_count=1)
        assert r.short(6) == "abcdef"
