#!/usr/bin/env python3
"""Tests for iamai.stall_loss_estimator.

Run:
    python3 -m pytest tools/test_stall_loss_estimator.py -v
    python3 tools/test_stall_loss_estimator.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stall_loss_estimator import (  # noqa: E402
    LossReport,
    StallEvent,
    estimate_losses,
)


class TestEstimateLosses(unittest.TestCase):
    """Core algorithm tests."""

    def test_empty_input(self):
        report = estimate_losses([])
        self.assertEqual(report.total_strokes, 0)
        self.assertEqual(report.stall_count, 0)
        self.assertEqual(report.health_score, 1.0)
        self.assertIsNone(report.worst_severity)

    def test_single_timestamp(self):
        report = estimate_losses([1000.0])
        self.assertEqual(report.total_strokes, 1)
        self.assertEqual(report.stall_count, 0)

    def test_no_stalls(self):
        # 100 strokes, 15s apart — perfectly healthy
        ts = [1000 + i * 15 for i in range(100)]
        report = estimate_losses(ts, cadence=15, gap_threshold=1200)
        self.assertEqual(report.stall_count, 0)
        self.assertEqual(report.health_score, 0.0)
        self.assertEqual(report.total_expected_lost, 0)

    def test_single_minor_stall(self):
        # normal strokes, then a 1500s gap (= 100 expected strokes at cadence=15)
        ts = [1000 + i * 15 for i in range(10)]  # 0–135s
        ts.append(ts[-1] + 1500)                  # big gap
        ts.extend([ts[-1] + i * 15 for i in range(1, 11)])  # resume normal
        report = estimate_losses(ts, cadence=15, gap_threshold=1200)
        self.assertEqual(report.stall_count, 1)
        stall = report.stalls[0]
        self.assertEqual(stall.expected_strokes, 100)
        self.assertEqual(stall.loss_severity, "moderate")
        self.assertAlmostEqual(stall.gap_seconds, 1500.0)

    def test_severe_stall(self):
        # 18000s gap = 1200 expected strokes at cadence=15
        ts = [1000, 1000 + 18000]
        report = estimate_losses(ts, cadence=15, gap_threshold=1200)
        self.assertEqual(report.stall_count, 1)
        self.assertEqual(report.stalls[0].loss_severity, "severe")
        self.assertEqual(report.stalls[0].expected_strokes, 1200)

    def test_multiple_stalls(self):
        ts = [0, 15, 30]                         # 3 normal strokes
        ts.append(ts[-1] + 2000)                  # stall 1
        ts.append(ts[-1] + 15)
        ts.append(ts[-1] + 15)
        ts.append(ts[-1] + 3000)                  # stall 2
        ts.append(ts[-1] + 15)
        report = estimate_losses(ts, cadence=15, gap_threshold=1200)
        self.assertEqual(report.stall_count, 2)
        self.assertEqual(report.stalls[0].expected_strokes, 133)  # 2000/15
        self.assertEqual(report.stalls[1].expected_strokes, 200)  # 3000/15
        self.assertEqual(report.total_expected_lost, 333)

    def test_recovery_seconds_normal_resume(self):
        # after gap, strokes resume at normal cadence — recovery should be 0
        ts = [0, 15, 30, 30 + 1500, 30 + 1500 + 15, 30 + 1500 + 30]
        report = estimate_losses(ts, cadence=15, gap_threshold=1200)
        self.assertEqual(report.stall_count, 1)
        self.assertAlmostEqual(report.stalls[0].recovery_seconds, 0.0)

    def test_recovery_seconds_slow_resume(self):
        # after gap, first few strokes are also slow (60s apart > 2*15=30)
        ts = [0, 15, 30]
        ts.append(30 + 2000)       # stall gap
        ts.append(ts[-1] + 60)     # slow recovery stroke 1
        ts.append(ts[-1] + 45)     # slow recovery stroke 2
        ts.append(ts[-1] + 15)     # back to normal
        report = estimate_losses(ts, cadence=15, gap_threshold=1200)
        self.assertEqual(report.stall_count, 1)
        # recovery = 60 + 45 = 105 (both > 2*cadence=30)
        self.assertAlmostEqual(report.stalls[0].recovery_seconds, 105.0)

    def test_gap_threshold_respected(self):
        # 500s gap, threshold=1200 — should not flag
        ts = [0, 15, 30, 30 + 500, 30 + 500 + 15]
        report = estimate_losses(ts, cadence=15, gap_threshold=1200)
        self.assertEqual(report.stall_count, 0)

    def test_custom_cadence(self):
        # cadence=60, gap=300 → expected=5
        ts = [0, 60, 120, 120 + 300, 120 + 300 + 60]
        report = estimate_losses(ts, cadence=60, gap_threshold=200)
        self.assertEqual(report.stall_count, 1)
        self.assertEqual(report.stalls[0].expected_strokes, 5)

    def test_health_score_perfect(self):
        ts = [i * 15 for i in range(1000)]
        report = estimate_losses(ts, cadence=15, gap_threshold=1200)
        self.assertEqual(report.health_score, 0.0)

    def test_health_score_degraded(self):
        # 100 strokes + 1 stall losing 100 expected
        ts = [i * 15 for i in range(100)]
        ts.append(ts[-1] + 1500)
        report = estimate_losses(ts, cadence=15, gap_threshold=1200)
        # lost_ratio = 100 / (101 + 100) ≈ 0.4975
        self.assertGreater(report.health_score, 0.4)
        self.assertLess(report.health_score, 0.6)

    def test_worst_severity_ordering(self):
        # mix of minor and severe → worst should be 'severe'
        ts = [0]
        ts.append(ts[-1] + 500)     # minor (500/15=33 expected)
        ts.append(ts[-1] + 15)
        ts.append(ts[-1] + 20000)   # severe (20000/15=1333 expected)
        ts.append(ts[-1] + 15)
        report = estimate_losses(ts, cadence=15, gap_threshold=1200)
        self.assertEqual(report.worst_severity, "severe")

    def test_stall_event_as_dict(self):
        stall = StallEvent(index=5, gap_seconds=3000.5, expected_strokes=200,
                           recovery_seconds=45.2, cadence=15)
        d = stall.as_dict()
        self.assertEqual(d["index"], 5)
        self.assertEqual(d["gap_seconds"], 3000.5)
        self.assertEqual(d["expected_strokes"], 200)
        self.assertEqual(d["recovery_seconds"], 45.2)
        self.assertEqual(d["loss_severity"], "moderate")

    def test_loss_report_as_dict(self):
        report = LossReport(stalls=[], total_strokes=50, total_gap_seconds=0,
                            total_expected_lost=0)
        d = report.as_dict()
        self.assertEqual(d["stall_count"], 0)
        self.assertEqual(d["total_strokes"], 50)
        self.assertIsNone(d["worst_severity"])
        self.assertEqual(d["health_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
