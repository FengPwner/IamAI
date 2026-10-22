"""Tests for iamai.writer_fatigue module."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_fatigue import (
    fatigue_report,
    fatigue_summary,
    _bigrams,
    _grade,
    _linreg_slope,
    _normalised_slope,
    _parse_ts,
    _tokenize,
    _window_bigram_diversity,
    _window_mean_gap,
    _window_mean_length,
    _window_recycling,
)


# ── helpers ────────────────────────────────────────────────────


def _make_stroke(seq: int, text: str, ts: str) -> dict:
    return {"seq": seq, "text": text, "at": ts, "kind": "thought"}


def _make_strokes(n: int, text: str = "the garden grows slowly and steadily",
                  gap_seconds: int = 300, base_ts: str = "2026-10-20T10:00:00+00:00") -> list:
    """Generate n strokes with uniform gap."""
    from datetime import datetime, timedelta, timezone
    base = _parse_ts(base_ts)
    strokes = []
    for i in range(n):
        ts = (base + timedelta(seconds=gap_seconds * i)).isoformat()
        strokes.append(_make_stroke(i + 1, text, ts))
    return strokes


# ── _tokenize ──────────────────────────────────────────────────


class TestTokenize:
    def test_basic(self):
        assert _tokenize("the garden grows") == ["the", "garden", "grows"]

    def test_punctuation(self):
        assert _tokenize("hello, world! test-case.") == ["hello", "world", "test", "case"]

    def test_case_insensitive(self):
        assert _tokenize("Garden GROWS") == ["garden", "grows"]

    def test_empty(self):
        assert _tokenize("") == []

    def test_numbers_stripped(self):
        tokens = _tokenize("commit 42 pushed")
        assert tokens == ["commit", "pushed"]


# ── _bigrams ───────────────────────────────────────────────────


class TestBigrams:
    def test_basic(self):
        assert _bigrams(["a", "b", "c"]) == [("a", "b"), ("b", "c")]

    def test_single_token(self):
        assert _bigrams(["a"]) == []

    def test_empty(self):
        assert _bigrams([]) == []


# ── _parse_ts ──────────────────────────────────────────────────


class TestParseTs:
    def test_iso_with_tz(self):
        dt = _parse_ts("2026-10-20T10:00:00+00:00")
        assert dt.hour == 10

    def test_iso_with_z(self):
        dt = _parse_ts("2026-10-20T10:00:00Z")
        assert dt.hour == 10


# ── _linreg_slope / _normalised_slope ─────────────────────────


class TestLinreg:
    def test_flat(self):
        assert _linreg_slope([5.0, 5.0, 5.0, 5.0]) == 0.0

    def test_positive_slope(self):
        slope = _linreg_slope([1.0, 2.0, 3.0, 4.0])
        assert abs(slope - 1.0) < 1e-9

    def test_negative_slope(self):
        slope = _linreg_slope([4.0, 3.0, 2.0, 1.0])
        assert abs(slope - (-1.0)) < 1e-9

    def test_single_value(self):
        assert _linreg_slope([5.0]) == 0.0

    def test_normalised_zero_mean(self):
        assert _normalised_slope([0.0, 0.0, 0.0]) == 0.0

    def test_normalised_positive(self):
        # slope=1, mean=2.5 → normalised = 0.4
        ns = _normalised_slope([1.0, 2.0, 3.0, 4.0])
        assert abs(ns - 0.4) < 1e-9


# ── _grade ─────────────────────────────────────────────────────


class TestGrade:
    def test_fresh(self):
        assert _grade(0) == "fresh"
        assert _grade(24.9) == "fresh"

    def test_warming(self):
        assert _grade(25) == "warming"
        assert _grade(49) == "warming"

    def test_fatigued(self):
        assert _grade(50) == "fatigued"
        assert _grade(74) == "fatigued"

    def test_exhausted(self):
        assert _grade(75) == "exhausted"
        assert _grade(100) == "exhausted"


# ── window metrics ─────────────────────────────────────────────


class TestWindowMeanLength:
    def test_uniform(self):
        strokes = [
            _make_stroke(1, "one two three four five", "2026-10-20T10:00:00+00:00"),
            _make_stroke(2, "six seven eight nine ten", "2026-10-20T10:05:00+00:00"),
        ]
        assert _window_mean_length(strokes) == 5.0

    def test_empty(self):
        assert _window_mean_length([]) == 0.0


class TestWindowRecycling:
    def test_no_prior_vocab(self):
        strokes = [_make_stroke(1, "hello world", "2026-10-20T10:00:00+00:00")]
        assert _window_recycling(strokes, frozenset()) == 0.0

    def test_full_recycling(self):
        strokes = [_make_stroke(1, "hello world", "2026-10-20T10:00:00+00:00")]
        assert _window_recycling(strokes, frozenset({"hello", "world"})) == 1.0

    def test_partial_recycling(self):
        strokes = [_make_stroke(1, "hello world foo", "2026-10-20T10:00:00+00:00")]
        rec = _window_recycling(strokes, frozenset({"hello"}))
        assert abs(rec - 1 / 3) < 1e-9


class TestWindowMeanGap:
    def test_uniform_gaps(self):
        strokes = [
            _make_stroke(1, "a", "2026-10-20T10:00:00+00:00"),
            _make_stroke(2, "b", "2026-10-20T10:05:00+00:00"),
            _make_stroke(3, "c", "2026-10-20T10:10:00+00:00"),
        ]
        assert abs(_window_mean_gap(strokes) - 300.0) < 1e-6

    def test_single_stroke(self):
        strokes = [_make_stroke(1, "a", "2026-10-20T10:00:00+00:00")]
        assert _window_mean_gap(strokes) == 0.0

    def test_empty(self):
        assert _window_mean_gap([]) == 0.0


class TestWindowBigramDiversity:
    def test_all_unique(self):
        strokes = [_make_stroke(1, "a b c d e", "2026-10-20T10:00:00+00:00")]
        div = _window_bigram_diversity(strokes)
        assert abs(div - 1.0) < 1e-9

    def test_all_same(self):
        # "a a a a" → bigrams: (a,a)×3, unique=1, total=3
        strokes = [_make_stroke(1, "a a a a", "2026-10-20T10:00:00+00:00")]
        div = _window_bigram_diversity(strokes)
        assert abs(div - 1 / 3) < 1e-9

    def test_empty(self):
        assert _window_bigram_diversity([]) == 0.0


# ── fatigue_report ─────────────────────────────────────────────


class TestFatigueReport:
    def test_insufficient_data(self):
        strokes = _make_strokes(10)
        report = fatigue_report(strokes, window_size=50, num_windows=6)
        assert report["grade"] == "unknown"
        assert report["fatigue_score"] == 0.0

    def test_healthy_writer(self):
        """Uniform strokes should produce low fatigue."""
        strokes = _make_strokes(400, text="the garden grows slowly and steadily over time")
        report = fatigue_report(strokes, window_size=50, num_windows=6)
        assert report["fatigue_score"] < 30
        assert report["grade"] in ("fresh", "warming")
        assert report["windows_analysed"] > 0

    def test_fatigued_writer_shrinking_texts(self):
        """Texts getting shorter over time → higher fatigue."""
        from datetime import datetime, timedelta, timezone
        base = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
        strokes = []
        for i in range(400):
            # Word count decreases from ~10 to ~3 over the session
            wc = max(3, 10 - int(i * 7 / 400))
            text = " ".join([f"word{j}" for j in range(wc)])
            ts = (base + timedelta(seconds=300 * i)).isoformat()
            strokes.append(_make_stroke(i + 1, text, ts))
        report = fatigue_report(strokes, window_size=50, num_windows=6)
        assert report["length_trend"] < 0  # negative = shrinking
        # Should have some fatigue signal
        assert report["fatigue_score"] > 0

    def test_fatigued_writer_increasing_gaps(self):
        """Gaps widening over time → higher fatigue."""
        from datetime import datetime, timedelta, timezone
        base = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
        strokes = []
        cum_seconds = 0
        for i in range(400):
            # Gap increases from 200s to 600s
            gap = 200 + int(i * 400 / 400)
            cum_seconds += gap
            ts = (base + timedelta(seconds=cum_seconds)).isoformat()
            strokes.append(_make_stroke(i + 1, "the garden grows steadily", ts))
        report = fatigue_report(strokes, window_size=50, num_windows=6)
        assert report["gap_trend"] > 0  # positive = widening

    def test_report_keys(self):
        strokes = _make_strokes(400)
        report = fatigue_report(strokes, window_size=50, num_windows=6)
        expected_keys = {
            "fatigue_score", "grade", "length_trend", "recycling_trend",
            "gap_trend", "diversity_trend", "windows_analysed",
            "window_size", "detail",
        }
        assert expected_keys.issubset(set(report.keys()))

    def test_score_bounded(self):
        strokes = _make_strokes(400)
        report = fatigue_report(strokes, window_size=50, num_windows=6)
        assert 0.0 <= report["fatigue_score"] <= 100.0


# ── fatigue_summary ────────────────────────────────────────────


class TestFatigueSummary:
    def test_insufficient_data(self):
        strokes = _make_strokes(5)
        summary = fatigue_summary(strokes, window_size=50, num_windows=6)
        assert "insufficient data" in summary.lower() or "need at least" in summary.lower()

    def test_healthy_returns_string(self):
        strokes = _make_strokes(400)
        summary = fatigue_summary(strokes, window_size=50, num_windows=6)
        assert "fatigue" in summary
        assert "/" in summary  # score/100
