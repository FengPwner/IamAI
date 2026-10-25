"""Tests for tools/batch_recovery_correlation.py"""

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from batch_recovery_correlation import (
    detect_stalls,
    nearest_batch_multiple,
    classify_correlation,
)


# ---------------------------------------------------------------------------
# detect_stalls
# ---------------------------------------------------------------------------

class TestDetectStalls:
    def test_no_stalls(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts = [base + timedelta(seconds=i * 15) for i in range(20)]
        assert detect_stalls(ts, threshold_seconds=300) == []

    def test_single_stall(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts = [base, base + timedelta(seconds=15), base + timedelta(seconds=600)]
        stalls = detect_stalls(ts, threshold_seconds=300)
        assert len(stalls) == 1
        assert stalls[0]["gap_seconds"] == 585.0

    def test_multiple_stalls(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts = [
            base,
            base + timedelta(seconds=15),
            base + timedelta(seconds=400),   # gap 385
            base + timedelta(seconds=415),
            base + timedelta(seconds=900),   # gap 485
        ]
        stalls = detect_stalls(ts, threshold_seconds=300)
        assert len(stalls) == 2

    def test_empty_list(self):
        assert detect_stalls([], threshold_seconds=300) == []

    def test_single_timestamp(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert detect_stalls([base], threshold_seconds=300) == []


# ---------------------------------------------------------------------------
# nearest_batch_multiple
# ---------------------------------------------------------------------------

class TestNearestBatchMultiple:
    def test_exact_multiple(self):
        mult, dist = nearest_batch_multiple(600.0, 600.0)
        assert mult == 1
        assert dist == 0.0

    def test_near_multiple(self):
        mult, dist = nearest_batch_multiple(620.0, 600.0)
        assert mult == 1
        assert dist == 20.0

    def test_second_multiple(self):
        mult, dist = nearest_batch_multiple(1180.0, 600.0)
        assert mult == 2
        assert dist == 20.0

    def test_halfway(self):
        mult, dist = nearest_batch_multiple(300.0, 600.0)
        assert mult == 1
        assert dist == 300.0

    def test_zero_interval(self):
        mult, dist = nearest_batch_multiple(500.0, 0)
        assert mult == 0
        assert dist == 500.0

    def test_very_small_recovery(self):
        mult, dist = nearest_batch_multiple(10.0, 600.0)
        assert mult == 1  # minimum is 1
        assert dist == 590.0


# ---------------------------------------------------------------------------
# classify_correlation
# ---------------------------------------------------------------------------

class TestClassifyCorrelation:
    def test_empty(self):
        result = classify_correlation([], 600.0)
        assert result["total"] == 0
        assert result["verdict"] == "independent"

    def test_all_correlated(self):
        # All recoveries are near 600s multiples
        recoveries = [590.0, 610.0, 1190.0, 1210.0, 580.0]
        result = classify_correlation(recoveries, 600.0, tolerance=60.0)
        assert result["total"] == 5
        assert result["verdict"] == "correlated"
        assert result["cluster_score"] >= 0.6

    def test_all_independent(self):
        # All recoveries are far from 600s multiples
        recoveries = [150.0, 350.0, 850.0, 1050.0, 1550.0]
        result = classify_correlation(recoveries, 600.0, tolerance=60.0)
        assert result["verdict"] == "independent"
        assert result["cluster_score"] < 0.3

    def test_weak_correlation(self):
        # 2 out of 5 hit = 0.4
        recoveries = [590.0, 610.0, 350.0, 850.0, 1550.0]
        result = classify_correlation(recoveries, 600.0, tolerance=60.0)
        assert result["verdict"] == "weak"
        assert 0.3 <= result["cluster_score"] < 0.6

    def test_records_present(self):
        recoveries = [600.0, 900.0]
        result = classify_correlation(recoveries, 600.0, tolerance=60.0)
        assert len(result["records"]) == 2
        assert "recovery_seconds" in result["records"][0]
        assert "within_tolerance" in result["records"][0]

    def test_tolerance_boundary(self):
        # Exactly at tolerance edge
        recoveries = [660.0]  # distance = 60 from 1*600
        result = classify_correlation(recoveries, 600.0, tolerance=60.0)
        assert result["records"][0]["within_tolerance"] is True

        recoveries2 = [661.0]  # distance = 61
        result2 = classify_correlation(recoveries2, 600.0, tolerance=60.0)
        assert result2["records"][0]["within_tolerance"] is False


# ---------------------------------------------------------------------------
# integration-style test with synthetic timestamps
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_pipeline(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # Simulate: normal strokes, then a 600s gap, then normal, then 1200s gap
        # Note: after a for loop with range(N), t has been incremented N times,
        # so the gap between the last appended ts and the new t is (stall + 15).
        ts = []
        t = base
        for _ in range(10):
            ts.append(t)
            t += timedelta(seconds=15)
        t += timedelta(seconds=585)  # +15 from last increment = 600s gap
        for _ in range(10):
            ts.append(t)
            t += timedelta(seconds=15)
        t += timedelta(seconds=1185)  # +15 from last increment = 1200s gap
        for _ in range(5):
            ts.append(t)
            t += timedelta(seconds=15)

        stalls = detect_stalls(ts, threshold_seconds=300)
        assert len(stalls) == 2
        recoveries = [s["gap_seconds"] for s in stalls]
        # First stall 600s, second 1200s
        assert abs(recoveries[0] - 600.0) < 1
        assert abs(recoveries[1] - 1200.0) < 1

        result = classify_correlation(recoveries, 600.0, tolerance=60.0)
        assert result["total"] == 2
        assert result["within_tol"] == 2  # both are exact multiples
        assert result["verdict"] == "correlated"
