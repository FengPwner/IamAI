"""tests for iamai.stroke_rhythm"""

import time
import pytest
from iamai.stroke_rhythm import StrokeRhythm, RhythmSnapshot


@pytest.fixture
def sr():
    return StrokeRhythm(window_size=50)


@pytest.fixture
def mechanical_sr():
    """A rhythm tracker with perfectly regular intervals (mechanical)."""
    sr = StrokeRhythm(window_size=50)
    base = 1000000.0
    for i in range(30):
        sr.record(base + i * 15.0)  # exactly 15s apart
    return sr


@pytest.fixture
def organic_sr():
    """A rhythm tracker with natural, varied intervals (organic)."""
    sr = StrokeRhythm(window_size=50)
    base = 1000000.0
    intervals = [12, 18, 8, 25, 14, 20, 5, 30, 10, 22,
                 15, 9, 28, 11, 19, 7, 24, 16, 13, 21,
                 6, 27, 17, 10, 23, 8, 14, 26, 12, 20]
    t = base
    for iv in intervals:
        sr.record(t)
        t += iv
    return sr


@pytest.fixture
def fatigued_sr():
    """A rhythm tracker with gradually increasing intervals (fatigued)."""
    sr = StrokeRhythm(window_size=50)
    base = 1000000.0
    t = base
    for i in range(30):
        sr.record(t)
        t += 10 + i * 2  # intervals grow: 10, 12, 14, ..., 68
    return sr


@pytest.fixture
def bursty_sr():
    """A rhythm tracker with bursts of rapid writing followed by pauses."""
    sr = StrokeRhythm(window_size=50)
    base = 1000000.0
    t = base
    # burst 1: 5 rapid strokes
    for _ in range(5):
        sr.record(t)
        t += 2
    # pause
    t += 60
    # normal pace
    for _ in range(10):
        sr.record(t)
        t += 20
    # burst 2: 4 rapid strokes
    for _ in range(4):
        sr.record(t)
        t += 3
    # pause
    t += 80
    # normal pace
    for _ in range(5):
        sr.record(t)
        t += 15
    return sr


# ── record ────────────────────────────────────────────────────────

class TestRecord:
    def test_records_with_default_timestamp(self, sr):
        before = time.time()
        sr.record()
        after = time.time()
        ts = list(sr.timestamps)
        assert len(ts) == 1
        assert before <= ts[0] <= after

    def test_records_with_explicit_timestamp(self, sr):
        sr.record(42.0)
        assert list(sr.timestamps) == [42.0]

    def test_respects_window_size(self):
        sr = StrokeRhythm(window_size=5)
        for i in range(10):
            sr.record(float(i))
        assert len(sr.timestamps) == 6  # window_size + 1

    def test_multiple_records(self, sr):
        for i in range(10):
            sr.record(1000.0 + i * 10)
        assert len(sr.timestamps) == 10


# ── intervals ─────────────────────────────────────────────────────

class TestIntervals:
    def test_empty_when_no_records(self, sr):
        assert sr.intervals() == []

    def test_empty_when_one_record(self, sr):
        sr.record(100.0)
        assert sr.intervals() == []

    def test_computes_intervals(self, sr):
        sr.record(100.0)
        sr.record(115.0)
        sr.record(140.0)
        assert sr.intervals() == [15.0, 25.0]

    def test_mechanical_intervals_are_uniform(self, mechanical_sr):
        ivs = mechanical_sr.intervals()
        assert all(abs(iv - 15.0) < 1e-9 for iv in ivs)


# ── mean_interval ─────────────────────────────────────────────────

class TestMeanInterval:
    def test_zero_when_empty(self, sr):
        assert sr.mean_interval() == 0.0

    def test_correct_mean(self, sr):
        sr.record(0.0)
        sr.record(10.0)
        sr.record(30.0)
        # intervals: [10, 20], mean = 15
        assert sr.mean_interval() == 15.0

    def test_mechanical_mean(self, mechanical_sr):
        assert abs(mechanical_sr.mean_interval() - 15.0) < 1e-9


# ── std_interval ──────────────────────────────────────────────────

class TestStdInterval:
    def test_zero_when_empty(self, sr):
        assert sr.std_interval() == 0.0

    def test_zero_when_one_interval(self, sr):
        sr.record(0.0)
        sr.record(10.0)
        assert sr.std_interval() == 0.0

    def test_zero_for_mechanical(self, mechanical_sr):
        assert mechanical_sr.std_interval() < 1e-9

    def test_positive_for_organic(self, organic_sr):
        assert organic_sr.std_interval() > 0


# ── coefficient_of_variation ──────────────────────────────────────

class TestCV:
    def test_zero_when_empty(self, sr):
        assert sr.coefficient_of_variation() == 0.0

    def test_zero_for_mechanical(self, mechanical_sr):
        assert mechanical_sr.coefficient_of_variation() < 0.01

    def test_positive_for_organic(self, organic_sr):
        cv = organic_sr.coefficient_of_variation()
        assert cv > 0.3  # organic should have decent variation

    def test_cv_formula(self, sr):
        sr.record(0.0)
        sr.record(10.0)
        sr.record(30.0)
        # intervals: [10, 20], mean=15, std=7.071
        expected_cv = sr.std_interval() / sr.mean_interval()
        assert abs(sr.coefficient_of_variation() - expected_cv) < 1e-9


# ── trend_slope ───────────────────────────────────────────────────

class TestTrendSlope:
    def test_zero_when_empty(self, sr):
        assert sr.trend_slope() == 0.0

    def test_zero_when_one_interval(self, sr):
        sr.record(0.0)
        sr.record(10.0)
        assert sr.trend_slope() == 0.0

    def test_zero_for_stable(self, mechanical_sr):
        slope = mechanical_sr.trend_slope()
        assert abs(slope) < 1e-9

    def test_positive_for_fatigued(self, fatigued_sr):
        slope = fatigued_sr.trend_slope()
        assert slope > 0  # intervals growing

    def test_slope_direction(self):
        sr = StrokeRhythm()
        # intervals: 10, 20, 30 — clearly increasing
        sr.record(0.0)
        sr.record(10.0)
        sr.record(30.0)
        sr.record(60.0)
        assert sr.trend_slope() > 0


# ── detect_bursts ─────────────────────────────────────────────────

class TestDetectBursts:
    def test_empty_when_no_data(self, sr):
        assert sr.detect_bursts() == []

    def test_no_bursts_in_mechanical(self, mechanical_sr):
        bursts = mechanical_sr.detect_bursts()
        assert bursts == []

    def test_detects_bursts_in_bursty(self, bursty_sr):
        bursts = bursty_sr.detect_bursts()
        assert len(bursts) >= 1  # should find at least one burst

    def test_burst_format(self, bursty_sr):
        bursts = bursty_sr.detect_bursts()
        for start, end in bursts:
            assert isinstance(start, int)
            assert isinstance(end, int)
            assert end >= start

    def test_custom_threshold(self, sr):
        base = 1000.0
        # mean ~20s, bursts at 2s
        for t in [0, 20, 40, 42, 44, 46, 66, 86]:
            sr.record(base + t)
        bursts_default = sr.detect_bursts()
        bursts_strict = sr.detect_bursts(threshold_factor=0.05)
        # stricter threshold should find fewer or equal bursts
        assert len(bursts_strict) <= len(bursts_default)


# ── rhythm_score ──────────────────────────────────────────────────

class TestRhythmScore:
    def test_neutral_when_insufficient_data(self, sr):
        sr.record(0.0)
        sr.record(10.0)
        assert sr.rhythm_score() == 0.5

    def test_score_in_range(self, organic_sr):
        score = organic_sr.rhythm_score()
        assert 0.0 <= score <= 1.0

    def test_mechanical_scores_lower(self, mechanical_sr, organic_sr):
        mech_score = mechanical_sr.rhythm_score()
        org_score = organic_sr.rhythm_score()
        assert org_score > mech_score

    def test_fatigued_penalized(self, fatigued_sr, organic_sr):
        fat_score = fatigued_sr.rhythm_score()
        org_score = organic_sr.rhythm_score()
        # organic should generally beat fatigued
        assert org_score > fat_score * 0.8  # some tolerance


# ── classify ──────────────────────────────────────────────────────

class TestClassify:
    def test_unknown_when_insufficient(self, sr):
        sr.record(0.0)
        assert sr.classify() == "unknown"

    def test_mechanical_classification(self, mechanical_sr):
        assert mechanical_sr.classify() == "mechanical"

    def test_fatigued_classification(self, fatigued_sr):
        assert fatigued_sr.classify() == "fatigued"

    def test_organic_classification(self, organic_sr):
        cls = organic_sr.classify()
        assert cls in ("organic", "bursty", "erratic")

    def test_valid_classification_values(self, organic_sr):
        valid = {"unknown", "mechanical", "fatigued", "bursty", "erratic", "organic"}
        assert organic_sr.classify() in valid


# ── snapshot ──────────────────────────────────────────────────────

class TestSnapshot:
    def test_snapshot_type(self, organic_sr):
        snap = organic_sr.snapshot()
        assert isinstance(snap, RhythmSnapshot)

    def test_snapshot_fields(self, organic_sr):
        snap = organic_sr.snapshot()
        assert snap.mean_interval > 0
        assert snap.cv >= 0
        assert isinstance(snap.trend, float)
        assert snap.burst_count >= 0
        assert 0 <= snap.rhythm_score <= 1
        assert snap.classification in (
            "unknown", "mechanical", "fatigued", "bursty", "erratic", "organic"
        )

    def test_snapshot_consistency(self, organic_sr):
        snap = organic_sr.snapshot()
        assert snap.mean_interval == organic_sr.mean_interval()
        assert snap.cv == organic_sr.coefficient_of_variation()
        assert snap.trend == organic_sr.trend_slope()
        assert snap.rhythm_score == organic_sr.rhythm_score()
        assert snap.classification == organic_sr.classify()


# ── summary ───────────────────────────────────────────────────────

class TestSummary:
    def test_summary_is_string(self, organic_sr):
        s = organic_sr.summary()
        assert isinstance(s, str)

    def test_summary_contains_classification(self, mechanical_sr):
        s = mechanical_sr.summary()
        assert "mechanical" in s

    def test_summary_contains_score(self, organic_sr):
        s = organic_sr.summary()
        assert "score=" in s

    def test_summary_contains_key_metrics(self, organic_sr):
        s = organic_sr.summary()
        assert "cv=" in s
        assert "trend=" in s
        assert "mean_iv=" in s
        assert "bursts=" in s


# ── edge cases ────────────────────────────────────────────────────

class TestEdgeCases:
    def test_single_record(self, sr):
        sr.record(100.0)
        assert sr.mean_interval() == 0.0
        assert sr.std_interval() == 0.0
        assert sr.coefficient_of_variation() == 0.0
        assert sr.trend_slope() == 0.0
        assert sr.classify() == "unknown"

    def test_two_records(self, sr):
        sr.record(0.0)
        sr.record(10.0)
        assert sr.mean_interval() == 10.0
        assert sr.std_interval() == 0.0  # only one interval, no variance

    def test_identical_timestamps(self, sr):
        """All strokes at the same time → zero intervals."""
        for _ in range(5):
            sr.record(42.0)
        assert sr.mean_interval() == 0.0
        assert sr.coefficient_of_variation() == 0.0

    def test_very_large_intervals(self, sr):
        sr.record(0.0)
        sr.record(1e6)
        sr.record(2e6)
        assert sr.mean_interval() == 1e6
        assert sr.std_interval() == 0.0

    def test_window_overflow(self):
        """More records than window_size should drop oldest."""
        sr = StrokeRhythm(window_size=5)
        for i in range(20):
            sr.record(float(i * 10))
        # window holds 6 timestamps (window_size + 1)
        assert len(sr.timestamps) == 6
        ivs = sr.intervals()
        assert all(iv == 10.0 for iv in ivs)
