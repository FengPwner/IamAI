"""Tests for iamai.stroke_dedup module."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from iamai.stroke_dedup import (
    MIN_SEED_LEN,
    duplicate_count,
    duplicate_ratio,
    duplicate_stroke_count,
    duplicate_summary,
    extract_seed,
    find_duplicates,
    health_grade,
    top_duplicates,
)


# ---------------------------------------------------------------------------
# Seed extraction
# ---------------------------------------------------------------------------


class TestExtractSeed:
    def test_strips_measurement_suffix(self):
        text = "hello world -- measured now: 42 things"
        assert extract_seed(text) == "hello world"

    def test_no_measurement_suffix(self):
        text = "just a plain thought"
        assert extract_seed(text) == "just a plain thought"

    def test_lowercased(self):
        text = "Hello WORLD -- measured now: xyz"
        assert extract_seed(text) == "hello world"

    def test_strips_whitespace(self):
        text = "  spaced out  -- measured now: xyz"
        assert extract_seed(text) == "spaced out"

    def test_multiple_markers_uses_first(self):
        text = "first part -- measured now: second -- measured now: third"
        assert extract_seed(text) == "first part"

    def test_empty_string(self):
        assert extract_seed("") == ""

    def test_only_measurement(self):
        text = "-- measured now: nothing before"
        assert extract_seed(text) == ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_strokes(tmp_path: Path, strokes: list[dict]) -> Path:
    """Write a list of stroke dicts to a temporary JSONL file."""
    path = tmp_path / "strokes.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for s in strokes:
            fh.write(json.dumps(s) + "\n")
    return path


def _stroke(seq: int, text: str, kind: str = "thought") -> dict:
    return {
        "seq": seq,
        "at": f"2026-10-06T12:00:{seq:02d}+00:00",
        "kind": kind,
        "text": text,
    }


# ---------------------------------------------------------------------------
# find_duplicates
# ---------------------------------------------------------------------------


class TestFindDuplicates:
    def test_no_duplicates(self, tmp_path):
        strokes = [
            _stroke(1, "unique thought alpha -- measured now: 10 files"),
            _stroke(2, "unique thought beta -- measured now: 20 files"),
            _stroke(3, "unique thought gamma -- measured now: 30 files"),
        ]
        path = _write_strokes(tmp_path, strokes)
        dupes = find_duplicates(path)
        assert dupes == {}

    def test_exact_duplicates(self, tmp_path):
        strokes = [
            _stroke(1, "hello world again -- measured now: 10 files"),
            _stroke(2, "hello world again -- measured now: 20 files"),
            _stroke(3, "different thought here -- measured now: 30 files"),
        ]
        path = _write_strokes(tmp_path, strokes)
        dupes = find_duplicates(path)
        assert "hello world again" in dupes
        assert len(dupes["hello world again"]) == 2

    def test_case_insensitive(self, tmp_path):
        strokes = [
            _stroke(1, "Hello World Again -- measured now: 10"),
            _stroke(2, "hello world again -- measured now: 20"),
        ]
        path = _write_strokes(tmp_path, strokes)
        dupes = find_duplicates(path)
        assert "hello world again" in dupes
        assert len(dupes["hello world again"]) == 2

    def test_short_seeds_ignored(self, tmp_path):
        short = "hi"  # len 2 < MIN_SEED_LEN
        strokes = [
            _stroke(1, f"{short} -- measured now: 1"),
            _stroke(2, f"{short} -- measured now: 2"),
        ]
        path = _write_strokes(tmp_path, strokes)
        dupes = find_duplicates(path)
        assert dupes == {}

    def test_custom_min_seed_len(self, tmp_path):
        strokes = [
            _stroke(1, "hi -- measured now: 1"),
            _stroke(2, "hi -- measured now: 2"),
        ]
        path = _write_strokes(tmp_path, strokes)
        dupes = find_duplicates(path, min_seed_len=2)
        assert "hi" in dupes

    def test_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.jsonl"
        dupes = find_duplicates(path)
        assert dupes == {}

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        dupes = find_duplicates(path)
        assert dupes == {}

    def test_malformed_lines_skipped(self, tmp_path):
        path = tmp_path / "strokes.jsonl"
        path.write_text(
            '{"seq":1,"at":"2026-10-06T12:00:00+00:00","kind":"thought","text":"valid stroke -- measured now: 1"}\n'
            'not json at all\n'
            '{"seq":2,"at":"2026-10-06T12:00:01+00:00","kind":"thought","text":"valid stroke -- measured now: 2"}\n'
        )
        dupes = find_duplicates(path)
        assert "valid stroke" in dupes
        assert len(dupes["valid stroke"]) == 2

    def test_three_way_duplicate(self, tmp_path):
        strokes = [
            _stroke(1, "triple thought -- measured now: 1"),
            _stroke(2, "triple thought -- measured now: 2"),
            _stroke(3, "triple thought -- measured now: 3"),
        ]
        path = _write_strokes(tmp_path, strokes)
        dupes = find_duplicates(path)
        assert len(dupes["triple thought"]) == 3


# ---------------------------------------------------------------------------
# Counts and ratios
# ---------------------------------------------------------------------------


class TestCounts:
    def test_duplicate_count(self, tmp_path):
        strokes = [
            _stroke(1, "alpha thought -- measured now: 1"),
            _stroke(2, "alpha thought -- measured now: 2"),
            _stroke(3, "beta thinking -- measured now: 3"),
            _stroke(4, "beta thinking -- measured now: 4"),
            _stroke(5, "gamma unique -- measured now: 5"),
        ]
        path = _write_strokes(tmp_path, strokes)
        assert duplicate_count(path) == 2

    def test_duplicate_stroke_count(self, tmp_path):
        strokes = [
            _stroke(1, "alpha thought -- measured now: 1"),
            _stroke(2, "alpha thought -- measured now: 2"),
            _stroke(3, "beta thinking -- measured now: 3"),
            _stroke(4, "beta thinking -- measured now: 4"),
            _stroke(5, "gamma unique -- measured now: 5"),
        ]
        path = _write_strokes(tmp_path, strokes)
        assert duplicate_stroke_count(path) == 4  # 2 + 2

    def test_duplicate_ratio_empty(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        assert duplicate_ratio(path) == 0.0

    def test_duplicate_ratio_half(self, tmp_path):
        strokes = [
            _stroke(1, "repeated idea -- measured now: 1"),
            _stroke(2, "repeated idea -- measured now: 2"),
            _stroke(3, "unique other -- measured now: 3"),
            _stroke(4, "unique another -- measured now: 4"),
        ]
        path = _write_strokes(tmp_path, strokes)
        # 2 of 4 strokes are duplicates
        assert abs(duplicate_ratio(path) - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# Top duplicates
# ---------------------------------------------------------------------------


class TestTopDuplicates:
    def test_sorted_by_count(self, tmp_path):
        strokes = [
            _stroke(1, "rare thought -- measured now: 1"),
            _stroke(2, "rare thought -- measured now: 2"),
            _stroke(3, "common thought -- measured now: 3"),
            _stroke(4, "common thought -- measured now: 4"),
            _stroke(5, "common thought -- measured now: 5"),
        ]
        path = _write_strokes(tmp_path, strokes)
        top = top_duplicates(path, limit=10)
        assert top[0] == ("common thought", 3)
        assert top[1] == ("rare thought", 2)

    def test_respects_limit(self, tmp_path):
        strokes = []
        seq = 1
        for i in range(10):
            word = f"thought number {i:02d}"
            strokes.append(_stroke(seq, f"{word} -- measured now: {seq}"))
            seq += 1
            strokes.append(_stroke(seq, f"{word} -- measured now: {seq}"))
            seq += 1
        path = _write_strokes(tmp_path, strokes)
        top = top_duplicates(path, limit=3)
        assert len(top) == 3

    def test_no_duplicates_returns_empty(self, tmp_path):
        strokes = [
            _stroke(1, "one unique thought -- measured now: 1"),
            _stroke(2, "another unique one -- measured now: 2"),
        ]
        path = _write_strokes(tmp_path, strokes)
        assert top_duplicates(path) == []


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class TestSummary:
    def test_no_duplicates(self, tmp_path):
        strokes = [
            _stroke(1, "unique alpha -- measured now: 1"),
            _stroke(2, "unique beta -- measured now: 2"),
        ]
        path = _write_strokes(tmp_path, strokes)
        s = duplicate_summary(path)
        assert "0 duplicate seeds" in s
        assert "2 strokes" in s

    def test_with_duplicates(self, tmp_path):
        strokes = [
            _stroke(1, "repeated idea -- measured now: 1"),
            _stroke(2, "repeated idea -- measured now: 2"),
            _stroke(3, "unique one -- measured now: 3"),
        ]
        path = _write_strokes(tmp_path, strokes)
        s = duplicate_summary(path)
        assert "1 duplicate seeds" in s
        assert "3 strokes" in s


# ---------------------------------------------------------------------------
# Health grade
# ---------------------------------------------------------------------------


class TestHealthGrade:
    def test_grade_a_clean(self, tmp_path):
        # 0% duplication
        strokes = [_stroke(i, f"unique thought {i:04d} -- measured now: {i}") for i in range(100)]
        path = _write_strokes(tmp_path, strokes)
        assert health_grade(path) == "A"

    def test_grade_b_mild(self, tmp_path):
        # ~3% duplication: 3 dupes out of 100
        strokes = [_stroke(i, f"unique thought {i:04d} -- measured now: {i}") for i in range(97)]
        for j in range(3):
            strokes.append(_stroke(97 + j, "this one repeats -- measured now: 999"))
        path = _write_strokes(tmp_path, strokes)
        assert health_grade(path) == "B"

    def test_grade_f_heavy(self, tmp_path):
        # >15% duplication
        strokes = []
        for i in range(80):
            strokes.append(_stroke(i, f"unique thought {i:04d} -- measured now: {i}"))
        for j in range(20):
            strokes.append(_stroke(80 + j, "over and over again -- measured now: 999"))
        path = _write_strokes(tmp_path, strokes)
        assert health_grade(path) == "F"
