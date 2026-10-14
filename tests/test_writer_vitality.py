"""Tests for iamai.writer_vitality — rolling health score for AI writers."""

from __future__ import annotations

import pytest

from iamai.writer_vitality import (
    WriterVitality,
    _composite,
    _freshness_score,
    _stall_score,
    _trend_label,
)


# ---------------------------------------------------------------------------
# _freshness_score
# ---------------------------------------------------------------------------

class TestFreshnessScore:
    def test_zero_seconds_is_perfect(self):
        assert _freshness_score(0) == 1.0

    def test_ceiling_is_zero(self):
        assert _freshness_score(300) == 0.0

    def test_beyond_ceiling_clamped(self):
        assert _freshness_score(600) == 0.0

    def test_midpoint(self):
        score = _freshness_score(150)
        assert 0.49 < score < 0.51

    def test_negative_treated_as_zero(self):
        assert _freshness_score(-10) == 1.0

    def test_monotonic_decrease(self):
        prev = _freshness_score(0)
        for t in [30, 60, 120, 200, 299]:
            cur = _freshness_score(t)
            assert cur < prev
            prev = cur


# ---------------------------------------------------------------------------
# _stall_score
# ---------------------------------------------------------------------------

class TestStallScore:
    def test_zero_stalls_is_perfect(self):
        assert _stall_score(0) == 1.0

    def test_one_stall(self):
        assert _stall_score(1) == 0.75

    def test_four_stalls_is_zero(self):
        assert _stall_score(4) == 0.0

    def test_beyond_four_clamped(self):
        assert _stall_score(10) == 0.0

    def test_negative_treated_as_zero(self):
        assert _stall_score(-1) == 1.0

    def test_two_stalls(self):
        assert _stall_score(2) == 0.5


# ---------------------------------------------------------------------------
# _composite
# ---------------------------------------------------------------------------

class TestComposite:
    def test_perfect_inputs(self):
        assert _composite(0, 1.0, 0) == 1.0

    def test_worst_inputs(self):
        assert _composite(999, 0.0, 10) == 0.0

    def test_mixed_inputs(self):
        score = _composite(60, 0.8, 1)
        # freshness ~0.8, cadence 0.8, stall 0.75
        # 0.4*0.8 + 0.35*0.8 + 0.25*0.75 = 0.32 + 0.28 + 0.1875 = 0.7875
        assert 0.78 < score < 0.80

    def test_clamped_above(self):
        # Shouldn't exceed 1.0 even with contrived inputs
        assert _composite(0, 1.0, 0) <= 1.0

    def test_clamped_below(self):
        assert _composite(9999, -1.0, 100) >= 0.0

    def test_cadence_clamped(self):
        # cadence_pct > 1.0 shouldn't inflate score
        assert _composite(0, 2.0, 0) <= 1.0

    def test_returns_float(self):
        assert isinstance(_composite(10, 0.9, 0), float)


# ---------------------------------------------------------------------------
# _trend_label
# ---------------------------------------------------------------------------

class TestTrendLabel:
    def test_insufficient_data_empty(self):
        assert _trend_label([]) == "insufficient_data"

    def test_insufficient_data_two(self):
        assert _trend_label([0.5, 0.6]) == "insufficient_data"

    def test_improving(self):
        scores = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
        assert _trend_label(scores) == "improving"

    def test_declining(self):
        scores = [0.9, 0.8, 0.7, 0.5, 0.3, 0.1]
        assert _trend_label(scores) == "declining"

    def test_flat(self):
        scores = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
        assert _trend_label(scores) == "flat"

    def test_nearly_flat(self):
        scores = [0.50, 0.51, 0.50, 0.51, 0.50]
        assert _trend_label(scores) == "flat"

    def test_uses_last_ten(self):
        # First 20 declining, last 10 improving → should be improving
        scores = [1.0 - i * 0.04 for i in range(20)]  # declining
        scores += [0.2 + i * 0.05 for i in range(10)]  # improving
        assert _trend_label(scores) == "improving"


# ---------------------------------------------------------------------------
# WriterVitality — recording
# ---------------------------------------------------------------------------

class TestWriterVitalityRecord:
    def test_record_returns_score(self):
        vit = WriterVitality()
        s = vit.record(freshness_s=10, cadence_pct=0.9, stalls=0)
        assert isinstance(s, float)
        assert 0.0 <= s <= 1.0

    def test_record_updates_score(self):
        vit = WriterVitality()
        assert vit.score() is None
        vit.record(freshness_s=10, cadence_pct=0.9, stalls=0)
        assert vit.score() is not None

    def test_multiple_records(self):
        vit = WriterVitality()
        for i in range(5):
            vit.record(freshness_s=10 + i * 5, cadence_pct=0.9, stalls=0)
        assert vit.readings() == 5
        assert len(vit.history()) == 5

    def test_history_ring_buffer(self):
        vit = WriterVitality(history=10)
        for i in range(20):
            vit.record(freshness_s=float(i), cadence_pct=0.9, stalls=0)
        assert vit.readings() == 10
        assert len(vit.history()) == 10


# ---------------------------------------------------------------------------
# WriterVitality — queries
# ---------------------------------------------------------------------------

class TestWriterVitalityQueries:
    def test_score_none_initially(self):
        vit = WriterVitality()
        assert vit.score() is None

    def test_score_latest(self):
        vit = WriterVitality()
        vit.record(freshness_s=10, cadence_pct=0.9, stalls=0)
        s1 = vit.score()
        vit.record(freshness_s=200, cadence_pct=0.5, stalls=2)
        s2 = vit.score()
        assert s2 < s1  # worse inputs → lower score

    def test_trend_improving(self):
        vit = WriterVitality()
        for i in range(6):
            vit.record(
                freshness_s=max(0, 200 - i * 30),
                cadence_pct=0.5 + i * 0.08,
                stalls=max(0, 3 - i),
            )
        assert vit.trend() == "improving"

    def test_trend_declining(self):
        vit = WriterVitality()
        for i in range(6):
            vit.record(
                freshness_s=i * 50,
                cadence_pct=max(0, 0.95 - i * 0.15),
                stalls=i,
            )
        assert vit.trend() == "declining"

    def test_trend_insufficient_data(self):
        vit = WriterVitality()
        vit.record(freshness_s=10, cadence_pct=0.9, stalls=0)
        assert vit.trend() == "insufficient_data"

    def test_history_ordered(self):
        vit = WriterVitality()
        vit.record(freshness_s=10, cadence_pct=0.9, stalls=0)
        vit.record(freshness_s=200, cadence_pct=0.5, stalls=2)
        h = vit.history()
        assert h[0] > h[1]  # first reading better than second


# ---------------------------------------------------------------------------
# WriterVitality — summary
# ---------------------------------------------------------------------------

class TestWriterVitalitySummary:
    def test_no_readings(self):
        vit = WriterVitality()
        assert vit.summary() == "no readings yet"

    def test_single_reading(self):
        vit = WriterVitality()
        vit.record(freshness_s=10, cadence_pct=0.9, stalls=0)
        s = vit.summary()
        assert "vitality" in s
        assert "1 readings" in s

    def test_multiple_readings(self):
        vit = WriterVitality()
        for i in range(5):
            vit.record(freshness_s=10 + i * 10, cadence_pct=0.9, stalls=0)
        s = vit.summary()
        assert "5 readings" in s
        assert "range" in s
        assert "avg" in s


# ---------------------------------------------------------------------------
# WriterVitality — repr
# ---------------------------------------------------------------------------

class TestWriterVitalityRepr:
    def test_repr_no_readings(self):
        vit = WriterVitality()
        r = repr(vit)
        assert "readings=0" in r
        assert "score=None" in r

    def test_repr_with_readings(self):
        vit = WriterVitality()
        vit.record(freshness_s=10, cadence_pct=0.9, stalls=0)
        r = repr(vit)
        assert "readings=1" in r
        assert "score=" in r


# ---------------------------------------------------------------------------
# WriterVitality — edge cases
# ---------------------------------------------------------------------------

class TestWriterVitalityEdgeCases:
    def test_history_minimum_five(self):
        vit = WriterVitality(history=1)  # below minimum
        for i in range(6):
            vit.record(freshness_s=float(i), cadence_pct=0.9, stalls=0)
        assert vit.readings() == 5  # min enforced

    def test_history_maximum_sixty(self):
        vit = WriterVitality(history=100)  # above maximum
        for i in range(65):
            vit.record(freshness_s=float(i), cadence_pct=0.9, stalls=0)
        assert vit.readings() == 60  # max enforced

    def test_identical_readings_flat(self):
        vit = WriterVitality()
        for _ in range(5):
            vit.record(freshness_s=50, cadence_pct=0.8, stalls=1)
        assert vit.trend() == "flat"
