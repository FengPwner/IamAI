#!/usr/bin/env python3
"""Tests for stall_early_warning — 48 test cases."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stall_early_warning import (  # noqa: E402
    _classify_level,
    _escalation_count,
    _eta_stall,
    _gaps,
    _linear_fit,
    _mean,
    _median,
    _recommend_action,
    _risk_score,
    _stdev,
    _to_epoch,
    early_warning_report,
    warning_dashboard,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(*seconds: float) -> list:
    """Build a list of datetimes from epoch-second offsets."""
    base = datetime(2026, 11, 10, 0, 0, 0, tzinfo=timezone.utc)
    return [
        datetime.fromtimestamp(base.timestamp() + s, tz=timezone.utc)
        for s in seconds
    ]


def _make_timestamps(gaps: list[float]) -> list:
    """Build timestamps from a list of inter-stroke gaps."""
    base = datetime(2026, 11, 10, 0, 0, 0, tzinfo=timezone.utc)
    result = [base]
    t = base.timestamp()
    for g in gaps:
        t += g
        result.append(datetime.fromtimestamp(t, tz=timezone.utc))
    return result


# ---------------------------------------------------------------------------
# _to_epoch
# ---------------------------------------------------------------------------

class TestToEpoch(unittest.TestCase):
    def test_single(self):
        ts = [datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)]
        epochs = _to_epoch(ts)
        self.assertEqual(len(epochs), 1)
        self.assertAlmostEqual(epochs[0], ts[0].timestamp())

    def test_multiple(self):
        ts = _ts(0, 15, 30, 45)
        epochs = _to_epoch(ts)
        self.assertEqual(len(epochs), 4)
        self.assertAlmostEqual(epochs[1] - epochs[0], 15.0, places=1)

    def test_empty(self):
        self.assertEqual(_to_epoch([]), [])


# ---------------------------------------------------------------------------
# _gaps
# ---------------------------------------------------------------------------

class TestGaps(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_gaps([0.0, 15.0, 30.0]), [15.0, 15.0])

    def test_single(self):
        self.assertEqual(_gaps([100.0]), [])

    def test_empty(self):
        self.assertEqual(_gaps([]), [])

    def test_irregular(self):
        gaps = _gaps([0.0, 10.0, 25.0, 50.0])
        self.assertEqual(gaps, [10.0, 15.0, 25.0])


# ---------------------------------------------------------------------------
# _mean, _median, _stdev
# ---------------------------------------------------------------------------

class TestStats(unittest.TestCase):
    def test_mean_basic(self):
        self.assertAlmostEqual(_mean([10, 20, 30]), 20.0)

    def test_mean_single(self):
        self.assertAlmostEqual(_mean([42.0]), 42.0)

    def test_mean_empty(self):
        self.assertAlmostEqual(_mean([]), 0.0)

    def test_median_odd(self):
        self.assertAlmostEqual(_median([1, 3, 5]), 3.0)

    def test_median_even(self):
        self.assertAlmostEqual(_median([1, 2, 3, 4]), 2.5)

    def test_median_single(self):
        self.assertAlmostEqual(_median([7.0]), 7.0)

    def test_median_empty(self):
        self.assertAlmostEqual(_median([]), 0.0)

    def test_stdev_uniform(self):
        self.assertAlmostEqual(_stdev([5, 5, 5, 5]), 0.0)

    def test_stdev_known(self):
        # stdev of [2, 4, 4, 4, 5, 5, 7, 9] ≈ 2.14 (sample stdev)
        sd = _stdev([2, 4, 4, 4, 5, 5, 7, 9])
        self.assertAlmostEqual(sd, 2.14, places=1)

    def test_stdev_single(self):
        self.assertAlmostEqual(_stdev([10.0]), 0.0)

    def test_stdev_empty(self):
        self.assertAlmostEqual(_stdev([]), 0.0)


# ---------------------------------------------------------------------------
# _linear_fit
# ---------------------------------------------------------------------------

class TestLinearFit(unittest.TestCase):
    def test_constant(self):
        slope, intercept = _linear_fit([15.0, 15.0, 15.0, 15.0])
        self.assertAlmostEqual(slope, 0.0, places=6)
        self.assertAlmostEqual(intercept, 15.0, places=6)

    def test_increasing(self):
        # y = 2x + 10: [10, 12, 14, 16, 18]
        slope, intercept = _linear_fit([10.0, 12.0, 14.0, 16.0, 18.0])
        self.assertAlmostEqual(slope, 2.0, places=6)
        self.assertAlmostEqual(intercept, 10.0, places=6)

    def test_decreasing(self):
        # y = -1x + 20: [20, 19, 18, 17, 16]
        slope, intercept = _linear_fit([20.0, 19.0, 18.0, 17.0, 16.0])
        self.assertAlmostEqual(slope, -1.0, places=6)

    def test_two_points(self):
        slope, intercept = _linear_fit([10.0, 20.0])
        self.assertAlmostEqual(slope, 10.0, places=6)

    def test_single_point(self):
        slope, intercept = _linear_fit([42.0])
        self.assertAlmostEqual(slope, 0.0)
        self.assertAlmostEqual(intercept, 42.0)


# ---------------------------------------------------------------------------
# _escalation_count
# ---------------------------------------------------------------------------

class TestEscalationCount(unittest.TestCase):
    def test_no_escalation(self):
        self.assertEqual(_escalation_count([15, 15, 15, 15, 15]), 0)

    def test_full_escalation(self):
        self.assertEqual(_escalation_count([10, 12, 15, 20, 28, 40]), 5)

    def test_partial_escalation(self):
        # [10, 12, 15, 10, 11, 12, 13] — run of 3 at end
        self.assertEqual(_escalation_count([10, 12, 15, 10, 11, 12, 13]), 3)

    def test_single(self):
        self.assertEqual(_escalation_count([15]), 0)

    def test_empty(self):
        self.assertEqual(_escalation_count([]), 0)

    def test_decreasing(self):
        self.assertEqual(_escalation_count([20, 18, 15, 12, 10]), 0)

    def test_alternating(self):
        self.assertEqual(_escalation_count([10, 15, 10, 15, 10]), 1)


# ---------------------------------------------------------------------------
# _risk_score
# ---------------------------------------------------------------------------

class TestRiskScore(unittest.TestCase):
    def test_healthy(self):
        score = _risk_score(0.0, 0.0, 0.05, 1.0, 0, 15.0)
        self.assertLess(score, 0.01)

    def test_high_risk(self):
        score = _risk_score(7.5, 3.0, 0.8, 5.0, 7, 15.0)
        self.assertGreater(score, 0.8)
        self.assertLessEqual(score, 1.0)

    def test_moderate_risk(self):
        score = _risk_score(2.0, 0.5, 0.3, 2.0, 3, 15.0)
        self.assertGreater(score, 0.1)
        self.assertLess(score, 0.8)

    def test_clamped_to_01(self):
        score = _risk_score(100.0, 100.0, 10.0, 100.0, 100, 15.0)
        self.assertEqual(score, 1.0)

    def test_no_negative(self):
        score = _risk_score(-10.0, -10.0, -1.0, 0.5, 0, 15.0)
        self.assertEqual(score, 0.0)


# ---------------------------------------------------------------------------
# _classify_level
# ---------------------------------------------------------------------------

class TestClassifyLevel(unittest.TestCase):
    def test_none(self):
        self.assertEqual(_classify_level(0.0), "none")
        self.assertEqual(_classify_level(0.14), "none")

    def test_watch(self):
        self.assertEqual(_classify_level(0.15), "watch")
        self.assertEqual(_classify_level(0.34), "watch")

    def test_warning(self):
        self.assertEqual(_classify_level(0.35), "warning")
        self.assertEqual(_classify_level(0.59), "warning")

    def test_critical(self):
        self.assertEqual(_classify_level(0.60), "critical")
        self.assertEqual(_classify_level(1.0), "critical")


# ---------------------------------------------------------------------------
# _eta_stall
# ---------------------------------------------------------------------------

class TestEtaStall(unittest.TestCase):
    def test_no_degradation(self):
        eta = _eta_stall([15.0, 15.0, 15.0], 0.0, 15.0)
        self.assertIsNone(eta)

    def test_already_stalled(self):
        eta = _eta_stall([15.0, 20.0, 35.0], 5.0, 15.0)
        self.assertAlmostEqual(eta, 0.0)

    def test_slow_degradation(self):
        # gaps trending up slowly, last gap = 18, target = 15, stall at 30
        eta = _eta_stall([15.0, 16.0, 17.0, 18.0], 1.0, 15.0)
        self.assertIsNotNone(eta)
        self.assertGreater(eta, 0)

    def test_empty_gaps(self):
        eta = _eta_stall([], 0.5, 15.0)
        self.assertIsNone(eta)


# ---------------------------------------------------------------------------
# _recommend_action
# ---------------------------------------------------------------------------

class TestRecommendAction(unittest.TestCase):
    def test_none(self):
        self.assertEqual(_recommend_action("none", None), "no action needed")

    def test_watch_far_eta(self):
        action = _recommend_action("watch", 3600)
        self.assertIn("log", action.lower())

    def test_watch_near_eta(self):
        action = _recommend_action("watch", 300)
        self.assertIn("monitor", action.lower())

    def test_warning_imminent(self):
        action = _recommend_action("warning", 200)
        self.assertIn("restart", action.lower())

    def test_critical(self):
        action = _recommend_action("critical", None)
        self.assertIn("restart", action.lower())
        self.assertIn("immediately", action.lower())


# ---------------------------------------------------------------------------
# early_warning_report (integration)
# ---------------------------------------------------------------------------

class TestEarlyWarningReport(unittest.TestCase):
    def test_healthy_writer(self):
        # Steady 15-second gaps
        gaps = [15.0] * 30
        ts = _make_timestamps(gaps)
        report = early_warning_report(ts, target_gap_s=15.0)
        self.assertEqual(report["level"], "none")
        self.assertLess(report["risk_score"], 0.15)
        self.assertIsNone(report["eta_stall_s"])
        self.assertEqual(report["gaps_analysed"], 30)

    def test_degrading_writer(self):
        # Gaps steadily increasing: 15, 17, 19, ..., 73 (step 2)
        gaps = [15.0 + i * 2.0 for i in range(30)]
        ts = _make_timestamps(gaps)
        report = early_warning_report(ts, target_gap_s=15.0)
        self.assertIn(report["level"], ("warning", "critical"))
        self.assertGreater(report["risk_score"], 0.35)
        self.assertGreater(report["gap_trend"], 0)
        self.assertGreater(report["escalation_count"], 5)

    def test_stalled_writer(self):
        # Large gaps at the end
        gaps = [15.0] * 20 + [45.0, 60.0, 90.0, 120.0, 180.0]
        ts = _make_timestamps(gaps)
        report = early_warning_report(ts, target_gap_s=15.0)
        self.assertIn(report["level"], ("warning", "critical"))
        self.assertGreater(report["max_gap_ratio"], 3.0)

    def test_insufficient_data(self):
        ts = _make_timestamps([15.0])
        report = early_warning_report(ts, target_gap_s=15.0)
        self.assertEqual(report["level"], "none")
        self.assertEqual(report["action"], "insufficient data")

    def test_window_truncation(self):
        # 100 gaps but window=30
        gaps = [15.0] * 70 + [15.0 + i * 0.5 for i in range(30)]
        ts = _make_timestamps(gaps)
        report = early_warning_report(ts, target_gap_s=15.0, window=30)
        self.assertEqual(report["gaps_analysed"], 30)

    def test_random_healthy(self):
        # Random-ish gaps around 15s
        import random
        random.seed(42)
        gaps = [15.0 + random.uniform(-2, 2) for _ in range(30)]
        ts = _make_timestamps(gaps)
        report = early_warning_report(ts, target_gap_s=15.0)
        self.assertIn(report["level"], ("none", "watch"))

    def test_sudden_spike(self):
        # Normal then sudden spike
        gaps = [15.0] * 25 + [80.0, 90.0, 100.0, 110.0, 120.0]
        ts = _make_timestamps(gaps)
        report = early_warning_report(ts, target_gap_s=15.0)
        self.assertGreater(report["cv"], 0.3)
        self.assertGreater(report["max_gap_ratio"], 4.0)

    def test_report_keys(self):
        ts = _make_timestamps([15.0] * 10)
        report = early_warning_report(ts, target_gap_s=15.0)
        expected_keys = {
            "gap_trend", "gap_acceleration", "cv", "max_gap_ratio",
            "escalation_count", "risk_score", "level", "eta_stall_s",
            "action", "gaps_analysed",
        }
        self.assertEqual(set(report.keys()), expected_keys)


# ---------------------------------------------------------------------------
# warning_dashboard
# ---------------------------------------------------------------------------

class TestWarningDashboard(unittest.TestCase):
    def test_output_is_string(self):
        ts = _make_timestamps([15.0] * 20)
        output = warning_dashboard(ts, target_gap_s=15.0)
        self.assertIsInstance(output, str)

    def test_contains_level(self):
        ts = _make_timestamps([15.0] * 20)
        output = warning_dashboard(ts, target_gap_s=15.0)
        self.assertIn("NONE", output)

    def test_contains_bar(self):
        ts = _make_timestamps([15.0] * 20)
        output = warning_dashboard(ts, target_gap_s=15.0)
        self.assertIn("░", output)

    def test_critical_dashboard(self):
        # Severe degradation: step 8 per stroke
        gaps = [15.0 + i * 8 for i in range(30)]
        ts = _make_timestamps(gaps)
        output = warning_dashboard(ts, target_gap_s=15.0)
        self.assertIn("CRITICAL", output)
        self.assertIn("█", output)


if __name__ == "__main__":
    unittest.main()
