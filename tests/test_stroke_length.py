"""Tests for iamai.stroke_length."""

import json
from pathlib import Path

import pytest

from iamai.stroke_length import (
    _classify_trend,
    _load_lengths,
    length_report,
    length_stats,
    length_trend,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_strokes_file(tmp_path: Path, strokes: list[dict]) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    p = data_dir / "strokes.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for s in strokes:
            f.write(json.dumps(s) + "\n")
    return p


def _stroke(seq: int, text: str = "hello world", kind: str = "thought") -> dict:
    return {"seq": seq, "at": "2026-10-15T00:00:00+00:00", "kind": kind, "text": text}


# ---------------------------------------------------------------------------
# _load_lengths
# ---------------------------------------------------------------------------

class TestLoadLengths:
    def test_missing_file(self, tmp_path: Path):
        result = _load_lengths(tmp_path / "nope.jsonl", 10)
        assert result == []

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        assert _load_lengths(p, 10) == []

    def test_basic_load(self, tmp_path: Path):
        strokes = [_stroke(i, "abcde") for i in range(5)]  # each len=5
        p = _make_strokes_file(tmp_path, strokes)
        lengths = _load_lengths(p, 10)
        assert lengths == [5, 5, 5, 5, 5]

    def test_window_truncation(self, tmp_path: Path):
        # 20 strokes of varying length, window=10 → only last 10
        strokes = [_stroke(i, "x" * (i + 1)) for i in range(20)]
        p = _make_strokes_file(tmp_path, strokes)
        lengths = _load_lengths(p, 10)
        assert len(lengths) == 10
        # last 10 strokes: indices 10..19, lengths 11..20
        assert lengths == list(range(11, 21))

    def test_missing_text_field(self, tmp_path: Path):
        strokes = [{"seq": 1, "at": "", "kind": "thought"}]  # no text
        p = _make_strokes_file(tmp_path, strokes)
        lengths = _load_lengths(p, 10)
        assert lengths == [0]

    def test_non_string_text(self, tmp_path: Path):
        strokes = [{"seq": 1, "at": "", "kind": "thought", "text": 42}]
        p = _make_strokes_file(tmp_path, strokes)
        lengths = _load_lengths(p, 10)
        assert lengths == [0]

    def test_empty_text(self, tmp_path: Path):
        strokes = [_stroke(1, ""), _stroke(2, "abc")]
        p = _make_strokes_file(tmp_path, strokes)
        lengths = _load_lengths(p, 10)
        assert lengths == [0, 3]

    def test_malformed_lines_skipped(self, tmp_path: Path):
        p = tmp_path / "data" / "strokes.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            '{"seq":1,"kind":"thought","at":"","text":"abc"}\n'
            'NOT JSON AT ALL\n'
            '{"seq":2,"kind":"note","at":"","text":"defgh"}\n'
        )
        lengths = _load_lengths(p, 10)
        assert lengths == [3, 5]


# ---------------------------------------------------------------------------
# _classify_trend
# ---------------------------------------------------------------------------

class TestClassifyTrend:
    def test_stable(self):
        assert _classify_trend(100.0, 100.0) == "stable"
        assert _classify_trend(100.0, 119.0) == "stable"
        assert _classify_trend(100.0, 81.0) == "stable"

    def test_growing(self):
        assert _classify_trend(100.0, 121.0) == "growing"
        assert _classify_trend(100.0, 200.0) == "growing"
        assert _classify_trend(50.0, 100.0) == "growing"

    def test_shrinking(self):
        assert _classify_trend(100.0, 79.0) == "shrinking"
        assert _classify_trend(100.0, 10.0) == "shrinking"
        assert _classify_trend(200.0, 50.0) == "shrinking"

    def test_both_zero(self):
        assert _classify_trend(0.0, 0.0) == "stable"

    def test_first_zero_second_positive(self):
        assert _classify_trend(0.0, 50.0) == "growing"

    def test_first_zero_second_zero(self):
        assert _classify_trend(0.0, 0.0) == "stable"


# ---------------------------------------------------------------------------
# length_stats
# ---------------------------------------------------------------------------

class TestLengthStats:
    def test_empty(self, tmp_path: Path):
        p = _make_strokes_file(tmp_path, [])
        result = length_stats(p)
        assert result == {
            "count": 0, "min": 0, "max": 0,
            "mean": 0.0, "median": 0.0, "total": 0,
        }

    def test_missing_file(self, tmp_path: Path):
        result = length_stats(tmp_path / "nope.jsonl")
        assert result["count"] == 0

    def test_uniform(self, tmp_path: Path):
        strokes = [_stroke(i, "abcde") for i in range(10)]  # each len=5
        p = _make_strokes_file(tmp_path, strokes)
        result = length_stats(p, window=10)
        assert result["count"] == 10
        assert result["min"] == 5
        assert result["max"] == 5
        assert result["mean"] == 5.0
        assert result["median"] == 5.0
        assert result["total"] == 50

    def test_varying(self, tmp_path: Path):
        strokes = [_stroke(0, "ab"), _stroke(1, "abcd"), _stroke(2, "abcdef")]
        p = _make_strokes_file(tmp_path, strokes)
        result = length_stats(p, window=10)
        assert result["count"] == 3
        assert result["min"] == 2
        assert result["max"] == 6
        assert result["mean"] == 4.0
        assert result["median"] == 4.0
        assert result["total"] == 12

    def test_single_stroke(self, tmp_path: Path):
        strokes = [_stroke(0, "hello")]
        p = _make_strokes_file(tmp_path, strokes)
        result = length_stats(p, window=10)
        assert result["count"] == 1
        assert result["mean"] == 5.0
        assert result["median"] == 5.0

    def test_with_empty_text(self, tmp_path: Path):
        strokes = [_stroke(0, ""), _stroke(1, "abc"), _stroke(2, "")]
        p = _make_strokes_file(tmp_path, strokes)
        result = length_stats(p, window=10)
        assert result["count"] == 3
        assert result["min"] == 0
        assert result["max"] == 3
        assert result["total"] == 3

    def test_window_respected(self, tmp_path: Path):
        # 20 strokes, window=5 → only last 5
        strokes = [_stroke(i, "x" * (i + 1)) for i in range(20)]
        p = _make_strokes_file(tmp_path, strokes)
        result = length_stats(p, window=5)
        assert result["count"] == 5
        # last 5: lengths 16,17,18,19,20
        assert result["min"] == 16
        assert result["max"] == 20
        assert result["total"] == 90


# ---------------------------------------------------------------------------
# length_trend
# ---------------------------------------------------------------------------

class TestLengthTrend:
    def test_insufficient_data(self, tmp_path: Path):
        strokes = [_stroke(0, "abc"), _stroke(1, "def")]
        p = _make_strokes_file(tmp_path, strokes)
        result = length_trend(p, window=10)
        assert result["direction"] == "insufficient"
        assert result["sample_size"] == 2

    def test_stable_trend(self, tmp_path: Path):
        # All same length → stable
        strokes = [_stroke(i, "hello") for i in range(20)]
        p = _make_strokes_file(tmp_path, strokes)
        result = length_trend(p, window=20)
        assert result["direction"] == "stable"
        assert result["first_mean"] == 5.0
        assert result["second_mean"] == 5.0
        assert result["sample_size"] == 20

    def test_growing_trend(self, tmp_path: Path):
        # First half: short (len 3), second half: long (len 10)
        strokes = [_stroke(i, "abc") for i in range(10)]
        strokes += [_stroke(i + 10, "abcdefghij") for i in range(10)]
        p = _make_strokes_file(tmp_path, strokes)
        result = length_trend(p, window=20)
        assert result["direction"] == "growing"
        assert result["first_mean"] == 3.0
        assert result["second_mean"] == 10.0

    def test_shrinking_trend(self, tmp_path: Path):
        # First half: long (len 20), second half: short (len 3)
        strokes = [_stroke(i, "x" * 20) for i in range(10)]
        strokes += [_stroke(i + 10, "abc") for i in range(10)]
        p = _make_strokes_file(tmp_path, strokes)
        result = length_trend(p, window=20)
        assert result["direction"] == "shrinking"
        assert result["first_mean"] == 20.0
        assert result["second_mean"] == 3.0

    def test_ratio_computed(self, tmp_path: Path):
        strokes = [_stroke(i, "ab") for i in range(5)]
        strokes += [_stroke(i + 5, "abcdef") for i in range(5)]
        p = _make_strokes_file(tmp_path, strokes)
        result = length_trend(p, window=10)
        assert result["direction"] == "growing"
        assert result["ratio"] == pytest.approx(3.0, rel=0.01)

    def test_empty_file(self, tmp_path: Path):
        p = _make_strokes_file(tmp_path, [])
        result = length_trend(p, window=10)
        assert result["direction"] == "insufficient"
        assert result["sample_size"] == 0

    def test_exactly_four_strokes(self, tmp_path: Path):
        strokes = [_stroke(0, "ab"), _stroke(1, "ab"), _stroke(2, "abcdefgh"), _stroke(3, "abcdefgh")]
        p = _make_strokes_file(tmp_path, strokes)
        result = length_trend(p, window=10)
        assert result["direction"] == "growing"
        assert result["sample_size"] == 4

    def test_first_half_empty_text(self, tmp_path: Path):
        # First half: empty strings; second half: real text
        strokes = [_stroke(i, "") for i in range(5)]
        strokes += [_stroke(i + 5, "hello world") for i in range(5)]
        p = _make_strokes_file(tmp_path, strokes)
        result = length_trend(p, window=10)
        assert result["direction"] == "growing"
        assert result["first_mean"] == 0.0
        assert result["second_mean"] == 11.0


# ---------------------------------------------------------------------------
# length_report
# ---------------------------------------------------------------------------

class TestLengthReport:
    def test_no_strokes(self, tmp_path: Path):
        _make_strokes_file(tmp_path, [])
        report = length_report(tmp_path, window=10)
        assert "no strokes" in report

    def test_insufficient_data(self, tmp_path: Path):
        strokes = [_stroke(0, "hi"), _stroke(1, "yo")]
        _make_strokes_file(tmp_path, strokes)
        report = length_report(tmp_path, window=10)
        assert "insufficient" in report
        assert "2 stroke" in report

    def test_stable_report(self, tmp_path: Path):
        strokes = [_stroke(i, "hello world") for i in range(20)]
        _make_strokes_file(tmp_path, strokes)
        report = length_report(tmp_path, window=20)
        assert "stable" in report
        assert "mean" in report
        assert "range" in report
        assert "\u2192" in report  # → arrow

    def test_growing_report(self, tmp_path: Path):
        strokes = [_stroke(i, "ab") for i in range(10)]
        strokes += [_stroke(i + 10, "abcdefghijklmnop") for i in range(10)]
        _make_strokes_file(tmp_path, strokes)
        report = length_report(tmp_path, window=20)
        assert "growing" in report

    def test_shrinking_report(self, tmp_path: Path):
        strokes = [_stroke(i, "x" * 30) for i in range(10)]
        strokes += [_stroke(i + 10, "ab") for i in range(10)]
        _make_strokes_file(tmp_path, strokes)
        report = length_report(tmp_path, window=20)
        assert "shrinking" in report

    def test_report_contains_count(self, tmp_path: Path):
        strokes = [_stroke(i, "test") for i in range(15)]
        _make_strokes_file(tmp_path, strokes)
        report = length_report(tmp_path, window=15)
        assert "15 strokes" in report

    def test_default_repo_path(self):
        # Calling with no args should not crash — just returns a string.
        report = length_report(window=5)
        assert isinstance(report, str)

    def test_unicode_range_dash(self, tmp_path: Path):
        # Verify the en-dash is present in the range display.
        strokes = [_stroke(i, "hello") for i in range(10)]
        _make_strokes_file(tmp_path, strokes)
        report = length_report(tmp_path, window=10)
        assert "\u2013" in report  # en-dash –
