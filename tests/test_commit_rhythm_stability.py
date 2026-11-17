"""Tests for iamai.commit_rhythm_stability."""

import math
import statistics

import pytest

from iamai.commit_rhythm_stability import (
    _compute_gaps,
    _percentile,
    _tier_for_score,
    analyze_rhythm,
    rhythm_summary_line,
)


# ────────────────────────────────────────────────────────────────────
# _compute_gaps
# ────────────────────────────────────────────────────────────────────

class TestComputeGaps:
    def test_basic_gaps(self):
        assert _compute_gaps([10, 20, 35]) == [10, 15]

    def test_unsorted_input(self):
        # Should sort internally
        assert _compute_gaps([35, 10, 20]) == [10, 15]

    def test_single_timestamp(self):
        assert _compute_gaps([42]) == []

    def test_empty(self):
        assert _compute_gaps([]) == []

    def test_two_identical(self):
        assert _compute_gaps([5, 5]) == [0]

    def test_large_gaps(self):
        gaps = _compute_gaps([0, 1_000_000, 2_500_000])
        assert gaps == [1_000_000, 1_500_000]


# ────────────────────────────────────────────────────────────────────
# _percentile
# ────────────────────────────────────────────────────────────────────

class TestPercentile:
    def test_median_of_odd(self):
        assert _percentile([1, 2, 3, 4, 5], 50) == 3.0

    def test_p0(self):
        assert _percentile([10, 20, 30], 0) == 10.0

    def test_p100(self):
        assert _percentile([10, 20, 30], 100) == 30.0

    def test_p95_interpolation(self):
        data = list(range(1, 21))  # 1..20
        result = _percentile(data, 95)
        # k = 19 * 0.95 = 18.05; floor=18, ceil=19
        # val = data[18]*(19-18.05) + data[19]*(18.05-18) = 19*0.95 + 20*0.05 = 18.05+1 = 19.05
        assert abs(result - 19.05) < 0.01

    def test_empty(self):
        assert _percentile([], 50) == 0.0

    def test_single_element(self):
        assert _percentile([7], 50) == 7.0


# ────────────────────────────────────────────────────────────────────
# _tier_for_score
# ────────────────────────────────────────────────────────────────────

class TestTierForScore:
    def test_metronomic(self):
        assert _tier_for_score(95) == "metronomic"
        assert _tier_for_score(90) == "metronomic"

    def test_steady(self):
        assert _tier_for_score(70) == "steady"
        assert _tier_for_score(89) == "steady"

    def test_wobbly(self):
        assert _tier_for_score(50) == "wobbly"
        assert _tier_for_score(69) == "wobbly"

    def test_erratic(self):
        assert _tier_for_score(30) == "erratic"
        assert _tier_for_score(49) == "erratic"

    def test_chaotic(self):
        assert _tier_for_score(0) == "chaotic"
        assert _tier_for_score(29) == "chaotic"

    def test_insufficient(self):
        assert _tier_for_score(-1) == "insufficient_data"


# ────────────────────────────────────────────────────────────────────
# analyze_rhythm — insufficient data
# ────────────────────────────────────────────────────────────────────

class TestAnalyzeRhythmEdgeCases:
    def test_empty(self):
        r = analyze_rhythm([])
        assert r["n_commits"] == 0
        assert r["stability_score"] == -1.0
        assert r["tier"] == "insufficient_data"

    def test_single_timestamp(self):
        r = analyze_rhythm([1000])
        assert r["n_commits"] == 1
        assert r["stability_score"] == -1.0

    def test_two_timestamps(self):
        r = analyze_rhythm([1000, 1600])
        assert r["n_gaps"] == 1
        assert r["median_gap_s"] == 600.0
        assert r["mad_gap_s"] == 0.0
        assert r["stability_score"] == 100.0
        assert r["tier"] == "metronomic"


# ────────────────────────────────────────────────────────────────────
# analyze_rhythm — perfect rhythm
# ────────────────────────────────────────────────────────────────────

class TestPerfectRhythm:
    def test_identical_gaps(self):
        # 10 commits, each 600s apart
        ts = [i * 600 for i in range(10)]
        r = analyze_rhythm(ts)
        assert r["n_gaps"] == 9
        assert r["median_gap_s"] == 600.0
        assert r["mad_gap_s"] == 0.0
        assert r["robust_cv"] == 0.0
        assert r["stability_score"] == 100.0
        assert r["tier"] == "metronomic"
        assert r["n_anomalies"] == 0

    def test_near_identical_gaps(self):
        ts = [0, 600, 1201, 1800, 2400, 3001, 3600, 4200, 4801, 5400]
        r = analyze_rhythm(ts)
        gaps = [600, 601, 599, 600, 601, 599, 600, 601, 599]
        assert r["n_gaps"] == 9
        assert r["median_gap_s"] == 600.0
        assert r["mad_gap_s"] == 1.0
        # robust_cv = 1/600 ≈ 0.00167
        assert r["robust_cv"] < 0.01
        assert r["stability_score"] > 98


# ────────────────────────────────────────────────────────────────────
# analyze_rhythm — irregular rhythm
# ────────────────────────────────────────────────────────────────────

class TestIrregularRhythm:
    def test_wobbly(self):
        # Gaps vary enough that MAD > 0 but not wildly
        ts = [0]
        for g in [80, 150, 90, 200, 110, 170, 120, 190, 85]:
            ts.append(ts[-1] + g)
        r = analyze_rhythm(ts)
        assert r["n_gaps"] == 9
        # Median is 120; abs_devs from 120: [40,30,30,80,10,50,0,70,35]
        # sorted: [0,10,30,30,35,40,50,70,80] → MAD=35
        # robust_cv = 35/120 ≈ 0.292 → score ≈ 70.8
        assert r["stability_score"] < 80
        assert r["stability_score"] >= 50

    def test_erratic_with_one_big_gap(self):
        # Normal ~600s gaps with slight noise, then one huge gap
        ts = [0, 605, 1195, 1800, 2390, 3005, 3610, 4200, 14200]
        r = analyze_rhythm(ts)
        assert r["max_gap_s"] == 10000.0
        # The 10000s gap should be anomalous (MAD > 0 due to noise)
        assert r["n_anomalies"] >= 1

    def test_chaotic_rhythm(self):
        # Gaps vary wildly: 10, 5000, 20, 8000, 15, 12000, 30
        ts = [0]
        for g in [10, 5000, 20, 8000, 15, 12000, 30]:
            ts.append(ts[-1] + g)
        r = analyze_rhythm(ts)
        # Median should be around 20-30, but max is 12000
        assert r["max_gap_s"] == 12000.0
        assert r["stability_score"] < 50  # erratic or chaotic


# ────────────────────────────────────────────────────────────────────
# analyze_rhythm — anomaly detection
# ────────────────────────────────────────────────────────────────────

class TestAnomalyDetection:
    def test_no_anomalies_in_stable_data(self):
        ts = [i * 600 for i in range(20)]
        r = analyze_rhythm(ts)
        assert r["n_anomalies"] == 0

    def test_detects_outlier_gap(self):
        # Normal gaps with slight noise, plus one 7200s outlier
        normal_gaps = [580, 620, 595, 610, 590, 605, 585, 615, 600,
                       595, 610, 580, 620, 590, 605, 585, 615, 600]
        ts = [0]
        for g in normal_gaps:
            ts.append(ts[-1] + g)
        ts.append(ts[-1] + 7200)  # outlier
        # Add a few more normal gaps after the outlier
        for g in [600, 610, 590]:
            ts.append(ts[-1] + g)
        r = analyze_rhythm(ts)
        assert r["n_anomalies"] >= 1
        anomalous_values = [a["gap_s"] for a in r["anomalous_gaps"]]
        assert 7200 in anomalous_values

    def test_custom_anomaly_sigma(self):
        ts = [0, 600, 1200, 1800, 2400, 5400]  # last gap is 3000s
        r_strict = analyze_rhythm(ts, anomaly_sigma=2.0)
        r_loose = analyze_rhythm(ts, anomaly_sigma=5.0)
        # Strict should find at least as many anomalies
        assert r_strict["n_anomalies"] >= r_loose["n_anomalies"]

    def test_anomaly_ratio_to_median(self):
        # Gaps with slight noise so MAD > 0, plus one large outlier
        ts = [0, 590, 1210, 1800, 2410, 3000, 3605, 13605]
        # last gap = 10000
        r = analyze_rhythm(ts)
        if r["anomalous_gaps"]:
            for a in r["anomalous_gaps"]:
                assert a["ratio_to_median"] > 1.0


# ────────────────────────────────────────────────────────────────────
# analyze_rhythm — metric correctness
# ────────────────────────────────────────────────────────────────────

class TestMetricCorrectness:
    def test_known_values(self):
        ts = [0, 100, 250, 400, 600]
        gaps = [100, 150, 150, 200]
        r = analyze_rhythm(ts)
        assert r["gaps"] == gaps
        assert r["median_gap_s"] == statistics.median(gaps)
        assert r["mean_gap_s"] == statistics.mean(gaps)
        assert r["max_gap_s"] == 200.0
        assert r["min_gap_s"] == 100.0
        assert r["n_commits"] == 5
        assert r["n_gaps"] == 4

    def test_cv_calculation(self):
        ts = [0, 100, 250, 400, 600]
        gaps = [100, 150, 150, 200]
        r = analyze_rhythm(ts)
        expected_cv = statistics.stdev(gaps) / statistics.mean(gaps)
        assert abs(r["cv"] - round(expected_cv, 4)) < 0.001

    def test_mad_calculation(self):
        ts = [0, 100, 250, 400, 600]
        gaps = [100, 150, 150, 200]
        median_g = statistics.median(gaps)
        abs_devs = sorted([abs(g - median_g) for g in gaps])
        expected_mad = statistics.median(abs_devs)
        r = analyze_rhythm(ts)
        assert r["mad_gap_s"] == expected_mad

    def test_score_clamped_to_zero(self):
        # Construct data where robust_cv > 1.0
        # gaps: [1, 1, 1, 1, 1, 1, 1, 1000]
        ts = [0]
        for g in [1, 1, 1, 1, 1, 1, 1, 1000]:
            ts.append(ts[-1] + g)
        r = analyze_rhythm(ts)
        assert r["stability_score"] >= 0.0
        assert r["stability_score"] <= 100.0

    def test_unsorted_input_produces_same_result(self):
        ts_sorted = [0, 600, 1200, 1800, 2400, 3000]
        ts_shuffled = [1800, 0, 3000, 600, 2400, 1200]
        r1 = analyze_rhythm(ts_sorted)
        r2 = analyze_rhythm(ts_shuffled)
        # Same gaps, same metrics
        assert r1["gaps"] == r2["gaps"]
        assert r1["stability_score"] == r2["stability_score"]
        assert r1["tier"] == r2["tier"]


# ────────────────────────────────────────────────────────────────────
# rhythm_summary_line
# ────────────────────────────────────────────────────────────────────

class TestRhythmSummaryLine:
    def test_insufficient_data(self):
        r = analyze_rhythm([42])
        line = rhythm_summary_line(r)
        assert "insufficient data" in line
        assert "1 commits" in line

    def test_normal_summary(self):
        ts = [i * 600 for i in range(10)]
        r = analyze_rhythm(ts)
        line = rhythm_summary_line(r)
        assert "metronomic" in line
        assert "score 100" in line
        assert "600s" in line

    def test_summary_with_anomalies(self):
        # Noise + big outlier ensures MAD > 0 so anomalies are detected
        ts = [0, 595, 1205, 1800, 2410, 3005, 3600, 13600, 14210, 14800]
        r = analyze_rhythm(ts)
        line = rhythm_summary_line(r)
        assert "anomalies" in line or "anomal" in line.lower()

    def test_summary_contains_tier(self):
        ts = [0, 10, 5010, 5020, 10020, 15030, 15040, 20040]
        r = analyze_rhythm(ts)
        line = rhythm_summary_line(r)
        assert r["tier"] in line


# ────────────────────────────────────────────────────────────────────
# Boundary and stress tests
# ────────────────────────────────────────────────────────────────────

class TestBoundary:
    def test_two_timestamps_zero_gap(self):
        r = analyze_rhythm([100, 100])
        assert r["median_gap_s"] == 0.0
        assert r["stability_score"] == 100.0 or r["robust_cv"] == 0.0

    def test_negative_timestamps(self):
        # Timestamps can be relative; negative is fine
        r = analyze_rhythm([-600, -300, 0, 300])
        assert r["n_gaps"] == 3
        assert r["median_gap_s"] == 300.0

    def test_float_timestamps(self):
        ts = [0.0, 600.5, 1201.3, 1800.1]
        r = analyze_rhythm(ts)
        assert r["n_gaps"] == 3
        assert all(isinstance(g, float) for g in r["gaps"])

    def test_large_dataset(self):
        # 1000 commits at ~600s with small noise
        import random
        random.seed(42)
        ts = [0]
        for _ in range(999):
            ts.append(ts[-1] + 600 + random.randint(-5, 5))
        r = analyze_rhythm(ts)
        assert r["n_gaps"] == 999
        assert r["stability_score"] > 95  # very stable
        assert r["tier"] == "metronomic"

    def test_all_zero_gaps(self):
        r = analyze_rhythm([100, 100, 100, 100])
        assert r["median_gap_s"] == 0.0
        assert r["mad_gap_s"] == 0.0
        assert r["robust_cv"] == 0.0
