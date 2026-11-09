"""Tests for iamai.writer_output_quality_index — 40 test cases."""

import math
import pytest
from datetime import datetime, timedelta, timezone

from iamai.writer_output_quality_index import (
    OQIReport,
    compute_oqi,
    grade_oqi,
    _score_cadence,
    _score_diversity,
    _score_freshness,
    _score_loop_freedom,
    _score_volume,
    _parse_at,
    _text_hash,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_stroke(kind="thought", text="hello world", at=None):
    """Build a minimal stroke dict."""
    if at is None:
        at = "2026-11-09T00:00:00+00:00"
    return {"kind": kind, "text": text, "at": at}


def _make_series(n, kinds=None, gap=15, base_text="stroke {i}"):
    """Generate n strokes spaced `gap` seconds apart."""
    base = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)
    strokes = []
    for i in range(n):
        kind = kinds[i % len(kinds)] if kinds else "thought"
        at = (base + timedelta(seconds=i * gap)).isoformat()
        strokes.append(_make_stroke(kind=kind, text=base_text.format(i=i), at=at))
    return strokes


# ---------------------------------------------------------------------------
# Empty / edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_strokes(self):
        r = compute_oqi([])
        assert r.score == 0.0
        assert r.grade == "D"
        assert r.stroke_count == 0

    def test_single_stroke(self):
        r = compute_oqi([_make_stroke()])
        assert r.score >= 0.0
        assert r.grade in ("A", "B", "C", "D")

    def test_two_strokes(self):
        strokes = _make_series(2)
        r = compute_oqi(strokes)
        assert isinstance(r, OQIReport)

    def test_strokes_outside_window(self):
        old = "2020-01-01T00:00:00+00:00"
        strokes = [_make_stroke(at=old), _make_stroke(at=old)]
        r = compute_oqi(strokes, window=60)
        # All strokes are within the window from newest - 60s
        assert r.score >= 0.0

    def test_bad_timestamp(self):
        strokes = [{"kind": "note", "text": "x", "at": "not-a-date"}]
        r = compute_oqi(strokes)
        assert r.score >= 0.0

    def test_zero_target_gap(self):
        r = compute_oqi(_make_series(5), target_gap=0)
        assert r.dimensions["cadence"] == 0.0


# ---------------------------------------------------------------------------
# Cadence scoring
# ---------------------------------------------------------------------------

class TestCadence:
    def test_perfect_cadence(self):
        gaps = [15.0, 15.0, 15.0]
        assert _score_cadence(gaps, 15.0) == 1.0

    def test_half_speed(self):
        gaps = [30.0, 30.0, 30.0]
        score = _score_cadence(gaps, 15.0)
        assert 0.0 <= score <= 0.05  # deviation = 1.0 → score = 0

    def test_double_speed(self):
        gaps = [7.5, 7.5, 7.5]
        score = _score_cadence(gaps, 15.0)
        assert score == 0.5

    def test_empty_gaps(self):
        assert _score_cadence([], 15.0) == 0.0

    def test_slightly_off(self):
        gaps = [16.0, 16.0, 16.0]
        score = _score_cadence(gaps, 15.0)
        assert 0.9 < score < 1.0


# ---------------------------------------------------------------------------
# Diversity scoring
# ---------------------------------------------------------------------------

class TestDiversity:
    def test_all_kinds(self):
        kinds = ["devlog", "garden", "note", "thought", "metrics", "snippet"]
        assert _score_diversity(kinds) == 1.0

    def test_half_kinds(self):
        kinds = ["devlog", "garden", "note"]
        assert _score_diversity(kinds) == 0.5

    def test_no_kinds(self):
        assert _score_diversity([]) == 0.0

    def test_unknown_kinds_only(self):
        kinds = ["unknown", "other"]
        assert _score_diversity(kinds) == 0.0

    def test_duplicates_still_count(self):
        kinds = ["devlog"] * 10 + ["garden"]
        score = _score_diversity(kinds)
        assert score == pytest.approx(2 / 6)


# ---------------------------------------------------------------------------
# Freshness scoring
# ---------------------------------------------------------------------------

class TestFreshness:
    def test_all_unique(self):
        hashes = ["a", "b", "c", "d"]
        assert _score_freshness(hashes) == 1.0

    def test_all_same(self):
        hashes = ["x"] * 10
        assert _score_freshness(hashes) == 0.1

    def test_empty(self):
        assert _score_freshness([]) == 0.0

    def test_half_unique(self):
        hashes = ["a", "b", "a", "b"]
        assert _score_freshness(hashes) == 0.5


# ---------------------------------------------------------------------------
# Loop freedom scoring
# ---------------------------------------------------------------------------

class TestLoopFreedom:
    def test_no_loop(self):
        labels = ["a", "b", "c", "d", "e", "f", "g", "h"]
        score = _score_loop_freedom(labels)
        assert score == 1.0

    def test_strong_loop(self):
        # Perfect period-2 cycle: a, b, a, b, ...
        labels = ["a", "b"] * 20
        score = _score_loop_freedom(labels)
        assert score < 0.5

    def test_short_sequence(self):
        assert _score_loop_freedom(["a", "b"]) == 1.0

    def test_empty(self):
        assert _score_loop_freedom([]) == 1.0

    def test_mild_repetition(self):
        # Mostly random with some repetition
        labels = ["a", "b", "c", "a", "b", "d", "c", "a", "b", "e"]
        score = _score_loop_freedom(labels)
        assert score >= 0.3


# ---------------------------------------------------------------------------
# Volume scoring
# ---------------------------------------------------------------------------

class TestVolume:
    def test_exact_expected(self):
        assert _score_volume(120, 120) == 1.0

    def test_over_expected(self):
        assert _score_volume(200, 120) == 1.0

    def test_half_expected(self):
        assert _score_volume(60, 120) == 0.5

    def test_zero_expected(self):
        assert _score_volume(5, 0) == 1.0

    def test_zero_both(self):
        assert _score_volume(0, 0) == 0.0


# ---------------------------------------------------------------------------
# Grade mapping
# ---------------------------------------------------------------------------

class TestGrading:
    def test_grade_a(self):
        assert grade_oqi(0.85) == "A"
        assert grade_oqi(1.0) == "A"

    def test_grade_b(self):
        assert grade_oqi(0.65) == "B"
        assert grade_oqi(0.84) == "B"

    def test_grade_c(self):
        assert grade_oqi(0.45) == "C"
        assert grade_oqi(0.64) == "C"

    def test_grade_d(self):
        assert grade_oqi(0.0) == "D"
        assert grade_oqi(0.44) == "D"


# ---------------------------------------------------------------------------
# Integration: full compute_oqi
# ---------------------------------------------------------------------------

class TestComputeOQI:
    def test_healthy_writer(self):
        import random
        random.seed(42)
        pool = ["devlog", "garden", "note", "thought", "metrics", "snippet"]
        kinds = [random.choice(pool) for _ in range(120)]
        strokes = _make_series(120, kinds=kinds, gap=15)
        r = compute_oqi(strokes, target_gap=15, window=1800)
        assert r.score >= 0.3
        assert r.dimensions["diversity"] == 1.0
        assert r.dimensions["freshness"] == 1.0

    def test_stalled_writer(self):
        # Only 2 strokes in 30 min window → low volume
        strokes = _make_series(2, gap=1500)
        r = compute_oqi(strokes, target_gap=15, window=1800)
        assert r.dimensions["volume"] < 0.1

    def test_looping_writer(self):
        # Repeating 2-kind cycle
        strokes = _make_series(
            120, kinds=["thought", "thought"], gap=15,
            base_text="same text every time"
        )
        r = compute_oqi(strokes, target_gap=15, window=1800)
        # Freshness is low (all same text) and loop freedom may be affected
        assert r.dimensions["freshness"] < 0.1

    def test_custom_weights(self):
        strokes = _make_series(
            60,
            kinds=["devlog", "garden", "note", "thought", "metrics", "snippet"],
            gap=15,
        )
        r = compute_oqi(strokes, weights={"cadence": 5.0, "volume": 0.1})
        assert isinstance(r.score, float)

    def test_report_str(self):
        r = compute_oqi(_make_series(10))
        s = str(r)
        assert "OQI" in s
        assert "[" in s

    def test_window_filters_old(self):
        # 60 strokes at 15s gap = 900s; with 300s window, only ~20 fit
        strokes = _make_series(60, gap=15)
        r = compute_oqi(strokes, window=300, target_gap=15)
        # Volume should be capped since the window is small
        assert r.dimensions["volume"] <= 1.0

    def test_dataclass_frozen(self):
        r = compute_oqi(_make_series(5))
        with pytest.raises(AttributeError):
            r.score = 999

    def test_score_bounded(self):
        strokes = _make_series(50, gap=15)
        r = compute_oqi(strokes)
        assert 0.0 <= r.score <= 1.0
