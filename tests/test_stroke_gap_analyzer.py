"""Tests for iamai.stroke_gap_analyzer."""

import pytest

from iamai.stroke_gap_analyzer import (
    GapBucket,
    GapRecord,
    GapSequence,
    StrokeGapAnalyzer,
    gap_report,
)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_default_cadence(self):
        a = StrokeGapAnalyzer()
        assert a.expected_cadence_s == 15.0

    def test_custom_cadence(self):
        a = StrokeGapAnalyzer(expected_cadence_s=30)
        assert a.expected_cadence_s == 30.0

    def test_zero_cadence_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            StrokeGapAnalyzer(expected_cadence_s=0)

    def test_negative_cadence_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            StrokeGapAnalyzer(expected_cadence_s=-5)

    def test_custom_thresholds(self):
        a = StrokeGapAnalyzer(thresholds={"warm": 3.0, "hot": 20.0, "cold": 200.0})
        assert a._thresholds["warm"] == 3.0
        assert a._thresholds["hot"] == 20.0
        assert a._thresholds["cold"] == 200.0

    def test_non_monotonic_thresholds_rejected(self):
        with pytest.raises(ValueError, match="warm < hot < cold"):
            StrokeGapAnalyzer(thresholds={"warm": 10.0, "hot": 5.0, "cold": 100.0})

    def test_partial_thresholds_merge(self):
        a = StrokeGapAnalyzer(thresholds={"warm": 5.0})
        assert a._thresholds["warm"] == 5.0
        assert a._thresholds["hot"] == 10.0  # default


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

class TestIngestion:
    def test_ingest_basic(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        n = a.ingest([100, 110, 120, 130])
        assert n == 3
        assert a.total_gaps == 3

    def test_ingest_unsorted(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([130, 100, 120, 110])
        assert a.total_gaps == 3
        vals = a.gap_values()
        assert vals == [10.0, 10.0, 10.0]

    def test_ingest_duplicates_dropped(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([100, 100, 110, 110])
        assert a.total_gaps == 1

    def test_ingest_empty(self):
        a = StrokeGapAnalyzer()
        assert a.ingest([]) == 0
        assert a.total_gaps == 0

    def test_ingest_single_timestamp(self):
        a = StrokeGapAnalyzer()
        assert a.ingest([1000]) == 0
        assert a.total_gaps == 0

    def test_add_single(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([100])
        rec = a.add(110)
        assert rec is not None
        assert rec.gap_s == 10.0
        assert rec.bucket is GapBucket.MICRO

    def test_add_duplicate_returns_none(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([100, 110])
        rec = a.add(110)
        assert rec is None

    def test_incremental_ingest(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([100, 110, 120])
        assert a.total_gaps == 2
        a.ingest([130, 140])
        assert a.total_gaps == 4


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassification:
    def test_micro_gap(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([100, 110])  # 1.0x
        assert a.records[0].bucket is GapBucket.MICRO

    def test_micro_gap_boundary(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([100, 119])  # 1.9x — just under warm threshold
        assert a.records[0].bucket is GapBucket.MICRO

    def test_warm_gap(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([100, 120])  # 2.0x
        assert a.records[0].bucket is GapBucket.WARM

    def test_warm_gap_upper(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([100, 199])  # 9.9x — just under hot
        assert a.records[0].bucket is GapBucket.WARM

    def test_hot_gap(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([100, 200])  # 10x
        assert a.records[0].bucket is GapBucket.HOT

    def test_hot_gap_upper(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([100, 1099])  # 99.9x — just under cold
        assert a.records[0].bucket is GapBucket.HOT

    def test_cold_gap(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([100, 1100])  # 100x
        assert a.records[0].bucket is GapBucket.COLD

    def test_massive_gap(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([100, 100100])  # 10000x
        assert a.records[0].bucket is GapBucket.COLD

    def test_ratio_computed(self):
        a = StrokeGapAnalyzer(expected_cadence_s=15)
        a.ingest([0, 45])
        assert abs(a.records[0].ratio - 3.0) < 0.001


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

class TestQueries:
    def _make_analyzer(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        # micro, micro, warm, hot, cold
        a.ingest([100, 110, 120, 140, 240, 1240])
        return a

    def test_gaps_in_micro(self):
        a = self._make_analyzer()
        micros = a.gaps_in(GapBucket.MICRO)
        assert len(micros) == 2

    def test_gaps_in_warm(self):
        a = self._make_analyzer()
        warms = a.gaps_in(GapBucket.WARM)
        assert len(warms) == 1

    def test_gaps_in_hot(self):
        a = self._make_analyzer()
        hots = a.gaps_in(GapBucket.HOT)
        assert len(hots) == 1

    def test_gaps_in_cold(self):
        a = self._make_analyzer()
        colds = a.gaps_in(GapBucket.COLD)
        assert len(colds) == 1

    def test_gap_values(self):
        a = self._make_analyzer()
        vals = a.gap_values()
        assert vals == [10.0, 10.0, 20.0, 100.0, 1000.0]


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

class TestSummary:
    def test_empty_summary(self):
        a = StrokeGapAnalyzer()
        s = a.summary()
        assert s["total_gaps"] == 0
        assert s["mean_gap_s"] == 0.0
        assert s["longest_sequence"] is None

    def test_summary_counts(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([100, 110, 120, 140, 240, 1240])
        s = a.summary()
        assert s["total_gaps"] == 5
        assert s["micro"] == 2
        assert s["warm"] == 1
        assert s["hot"] == 1
        assert s["cold"] == 1

    def test_summary_mean(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([0, 10, 20, 30])  # all 10s gaps
        s = a.summary()
        assert s["mean_gap_s"] == 10.0

    def test_summary_median(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([0, 10, 30, 40])  # gaps: 10, 20, 10
        s = a.summary()
        assert s["median_gap_s"] == 10.0

    def test_summary_max(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([0, 10, 1010])  # gaps: 10, 1000
        s = a.summary()
        assert s["max_gap_s"] == 1000.0

    def test_summary_p95(self):
        a = StrokeGapAnalyzer(expected_cadence_s=1)
        timestamps = list(range(100))  # 99 gaps of 1s each
        a.ingest(timestamps)
        s = a.summary()
        assert s["p95_gap_s"] == 1.0

    def test_summary_dominant_bucket(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        # 5 micro gaps, 1 cold gap
        a.ingest([0, 10, 20, 30, 40, 50, 1050])
        s = a.summary()
        assert s["dominant_bucket"] is GapBucket.MICRO

    def test_summary_has_longest_sequence(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        # 4 consecutive micro gaps
        a.ingest([0, 10, 20, 30, 40])
        s = a.summary()
        seq = s["longest_sequence"]
        assert seq is not None
        assert seq.bucket is GapBucket.MICRO
        assert seq.length == 4


# ---------------------------------------------------------------------------
# Sequences
# ---------------------------------------------------------------------------

class TestSequences:
    def test_no_sequences_empty(self):
        a = StrokeGapAnalyzer()
        assert a.sequences() == []

    def test_single_run(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([0, 10, 20, 30])
        seqs = a.sequences(min_length=2)
        assert len(seqs) == 1
        assert seqs[0].bucket is GapBucket.MICRO
        assert seqs[0].length == 3

    def test_mixed_runs(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        # micro micro | warm warm warm | cold
        a.ingest([0, 10, 20, 40, 60, 80, 1080])
        seqs = a.sequences(min_length=2)
        assert len(seqs) == 2
        assert seqs[0].bucket is GapBucket.MICRO
        assert seqs[0].length == 2
        assert seqs[1].bucket is GapBucket.WARM
        assert seqs[1].length == 3

    def test_min_length_filter(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([0, 10, 20])  # 2 micro gaps
        assert len(a.sequences(min_length=3)) == 0
        assert len(a.sequences(min_length=2)) == 1

    def test_sequence_total_s(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([0, 10, 20, 30])  # gaps: 10, 10, 10
        seqs = a.sequences(min_length=2)
        assert seqs[0].total_s == 30.0

    def test_sequence_mean_gap_s(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([0, 10, 20, 30])
        seqs = a.sequences(min_length=2)
        assert seqs[0].mean_gap_s == 10.0

    def test_sequence_end_index(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([0, 10, 20, 30])
        seqs = a.sequences(min_length=2)
        assert seqs[0].start_index == 0
        assert seqs[0].end_index == 2


# ---------------------------------------------------------------------------
# Health Score
# ---------------------------------------------------------------------------

class TestHealthScore:
    def test_perfect_health(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([0, 10, 20, 30, 40])
        assert a.health_score() == 1.0

    def test_all_cold(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([0, 1000, 2000, 3000])  # all 100x
        assert a.health_score() == 0.0

    def test_mixed_health(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        # 3 micro (1.0 each) + 1 warm (0.6) = 3.6 / 4 = 0.9
        a.ingest([0, 10, 20, 30, 50])
        score = a.health_score()
        assert abs(score - 0.9) < 0.001

    def test_empty_health(self):
        a = StrokeGapAnalyzer()
        assert a.health_score() == 1.0

    def test_health_range(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([0, 10, 20, 200, 1200])
        score = a.health_score()
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Gap Report
# ---------------------------------------------------------------------------

class TestGapReport:
    def test_empty_report(self):
        a = StrokeGapAnalyzer()
        report = gap_report(a.summary())
        assert "No gaps" in report

    def test_report_contains_buckets(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([0, 10, 20, 40, 240, 2240])
        report = gap_report(a.summary())
        assert "micro" in report
        assert "warm" in report
        assert "hot" in report or "cold" in report

    def test_report_contains_stats(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([0, 10, 20, 30])
        report = gap_report(a.summary())
        assert "mean gap" in report
        assert "median gap" in report
        assert "p95 gap" in report
        assert "max gap" in report

    def test_report_contains_sequence(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([0, 10, 20, 30, 40])
        report = gap_report(a.summary())
        assert "longest sequence" in report

    def test_report_total_gaps(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([0, 10, 20])
        report = gap_report(a.summary())
        assert "2 gaps" in report


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_very_small_cadence(self):
        a = StrokeGapAnalyzer(expected_cadence_s=0.001)
        a.ingest([0, 0.001, 0.002])
        assert a.total_gaps == 2
        assert all(r.bucket is GapBucket.MICRO for r in a.records)

    def test_large_timestamps(self):
        a = StrokeGapAnalyzer(expected_cadence_s=15)
        base = 1700000000.0
        a.ingest([base, base + 15, base + 30])
        assert a.total_gaps == 2

    def test_float_precision(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([0.0, 10.0000001, 20.0000002])
        assert a.total_gaps == 2
        # Should still be micro despite tiny floating-point drift
        assert all(r.bucket is GapBucket.MICRO for r in a.records)

    def test_records_are_frozen(self):
        a = StrokeGapAnalyzer(expected_cadence_s=10)
        a.ingest([0, 10])
        rec = a.records[0]
        with pytest.raises(AttributeError):
            rec.gap_s = 999  # type: ignore[misc]

    def test_gap_bucket_is_string_enum(self):
        assert GapBucket.MICRO.value == "micro"
        assert isinstance(GapBucket.MICRO, str)
