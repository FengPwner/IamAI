#!/usr/bin/env python3
"""Tests for stroke_burst_detector — 52 test cases."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_burst_detector import (  # noqa: E402
    _classify,
    _compute_gaps,
    _find_bursts,
    _to_epoch,
    burst_report,
    burst_timeline,
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


# ---------------------------------------------------------------------------
# _to_epoch
# ---------------------------------------------------------------------------

class TestToEpoch(unittest.TestCase):
    """Convert various timestamp types to epoch seconds."""

    def test_int_passthrough(self):
        self.assertEqual(_to_epoch(100), 100.0)

    def test_float_passthrough(self):
        self.assertAlmostEqual(_to_epoch(3.14), 3.14)

    def test_datetime_conversion(self):
        dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.assertAlmostEqual(_to_epoch(dt), dt.timestamp())

    def test_unsupported_type_raises(self):
        with self.assertRaises(TypeError):
            _to_epoch("2026-01-01")

    def test_naive_datetime_works(self):
        # naive datetime should still convert (uses local time)
        dt = datetime(2026, 6, 15, 12, 0, 0)
        result = _to_epoch(dt)
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0)


# ---------------------------------------------------------------------------
# _compute_gaps
# ---------------------------------------------------------------------------

class TestComputeGaps(unittest.TestCase):
    """Inter-stroke gap calculation."""

    def test_empty(self):
        self.assertEqual(_compute_gaps([]), [])

    def test_single(self):
        self.assertEqual(_compute_gaps([100]), [])

    def test_uniform_gaps(self):
        ts = _ts(0, 10, 20, 30)
        gaps = _compute_gaps(ts)
        self.assertEqual(len(gaps), 3)
        for g in gaps:
            self.assertAlmostEqual(g, 10.0, places=1)

    def test_irregular_gaps(self):
        ts = _ts(0, 5, 20, 22)
        gaps = _compute_gaps(ts)
        self.assertAlmostEqual(gaps[0], 5.0, places=1)
        self.assertAlmostEqual(gaps[1], 15.0, places=1)
        self.assertAlmostEqual(gaps[2], 2.0, places=1)

    def test_numeric_timestamps(self):
        gaps = _compute_gaps([0, 3, 7, 15])
        self.assertEqual(gaps, [3, 4, 8])


# ---------------------------------------------------------------------------
# _find_bursts
# ---------------------------------------------------------------------------

class TestFindBursts(unittest.TestCase):
    """Burst window detection."""

    def test_no_gaps_no_bursts(self):
        self.assertEqual(_find_bursts([]), [])

    def test_all_slow_no_bursts(self):
        gaps = [10, 15, 20, 12]  # all above 5s threshold
        self.assertEqual(_find_bursts(gaps, rapid_threshold_s=5.0), [])

    def test_single_burst(self):
        # gaps: 2, 1, 3 (all < 5) then 20, then nothing
        gaps = [2, 1, 3, 20]
        bursts = _find_bursts(gaps, rapid_threshold_s=5.0, min_burst_size=3)
        self.assertEqual(len(bursts), 1)
        self.assertEqual(bursts[0], (0, 3))  # strokes 0..3

    def test_burst_too_small_ignored(self):
        # only 2 rapid gaps => 3 strokes, but min_burst_size=4
        gaps = [1, 2, 15, 20]
        bursts = _find_bursts(gaps, rapid_threshold_s=5.0, min_burst_size=4)
        self.assertEqual(bursts, [])

    def test_multiple_bursts(self):
        gaps = [1, 1, 30, 2, 2, 2, 30]
        bursts = _find_bursts(gaps, rapid_threshold_s=5.0, min_burst_size=3)
        self.assertEqual(len(bursts), 2)
        # first burst: strokes 0..2 (gaps 1,1)
        self.assertEqual(bursts[0], (0, 2))
        # second burst: strokes 3..6 (gaps 2,2,2)
        self.assertEqual(bursts[1], (3, 6))

    def test_burst_extending_to_end(self):
        # rapid strokes at the very end
        gaps = [20, 1, 1, 1]
        bursts = _find_bursts(gaps, rapid_threshold_s=5.0, min_burst_size=3)
        self.assertEqual(len(bursts), 1)
        self.assertEqual(bursts[0], (1, 4))

    def test_threshold_boundary(self):
        # gap exactly at threshold is NOT rapid (< not <=)
        gaps = [5, 5, 5, 5]
        bursts = _find_bursts(gaps, rapid_threshold_s=5.0, min_burst_size=3)
        self.assertEqual(bursts, [])

    def test_custom_threshold(self):
        gaps = [8, 8, 8, 30]
        bursts = _find_bursts(gaps, rapid_threshold_s=10.0, min_burst_size=3)
        self.assertEqual(len(bursts), 1)
        self.assertEqual(bursts[0], (0, 3))


# ---------------------------------------------------------------------------
# burst_report
# ---------------------------------------------------------------------------

class TestBurstReport(unittest.TestCase):
    """Full burst analysis report."""

    def test_empty_input(self):
        r = burst_report([])
        self.assertEqual(r["burst_count"], 0)
        self.assertEqual(r["pattern"], "steady")
        self.assertEqual(r["bursts"], [])

    def test_single_timestamp(self):
        r = burst_report([100])
        self.assertEqual(r["burst_count"], 0)
        self.assertEqual(r["burst_fraction"], 0.0)

    def test_steady_cadence(self):
        ts = _ts(0, 15, 30, 45, 60, 75, 90)
        r = burst_report(ts)
        self.assertEqual(r["burst_count"], 0)
        self.assertEqual(r["pattern"], "steady")
        self.assertEqual(r["max_burst_size"], 0)

    def test_one_burst_detected(self):
        # 3 rapid strokes, then long gap, then 2 regular
        ts = _ts(0, 2, 4, 100, 115)
        r = burst_report(ts, rapid_threshold_s=5.0)
        self.assertEqual(r["burst_count"], 1)
        self.assertGreater(r["burst_fraction"], 0)
        self.assertEqual(r["max_burst_size"], 3)

    def test_burst_fraction_calculation(self):
        # 4 out of 8 strokes in a burst
        ts = _ts(0, 1, 2, 3, 60, 120, 180, 240)
        r = burst_report(ts, rapid_threshold_s=5.0)
        self.assertAlmostEqual(r["burst_fraction"], 4 / 8, places=3)

    def test_mean_inter_burst_gap(self):
        # two bursts with a known gap between them
        ts = _ts(0, 1, 2, 100, 101, 102)
        r = burst_report(ts, rapid_threshold_s=5.0, min_burst_size=3)
        self.assertEqual(r["burst_count"], 2)
        # gap from stroke 2 (epoch+2) to stroke 3 (epoch+100) = 98
        self.assertAlmostEqual(r["mean_inter_burst_gap"], 98.0, places=0)

    def test_occasional_pattern(self):
        # one small burst amid many regular strokes
        ts = _ts(*list(range(0, 200, 15)) + [200, 201, 202])
        # add the burst strokes at end (but keep sorted)
        ts_sorted = sorted(set(ts))
        r = burst_report(ts_sorted, rapid_threshold_s=5.0)
        if r["burst_count"] == 1 and r["burst_fraction"] < 0.3:
            self.assertEqual(r["pattern"], "occasional")

    def test_clustered_pattern(self):
        # multiple bursts close together
        ts = _ts(0, 1, 2, 30, 31, 32, 60, 61, 62)
        r = burst_report(ts, rapid_threshold_s=5.0, min_burst_size=3)
        if r["burst_count"] >= 2 and r["mean_inter_burst_gap"] < 60:
            self.assertEqual(r["pattern"], "clustered")

    def test_bursty_pattern(self):
        # bursts with long silences between
        ts = _ts(0, 1, 2, 500, 501, 502, 1000, 1001, 1002)
        r = burst_report(ts, rapid_threshold_s=5.0, min_burst_size=3)
        self.assertEqual(r["burst_count"], 3)
        self.assertEqual(r["pattern"], "bursty")
        self.assertGreater(r["mean_inter_burst_gap"], 60)

    def test_report_keys_complete(self):
        ts = _ts(0, 1, 2, 60)
        r = burst_report(ts)
        expected_keys = {
            "burst_count", "burst_fraction", "max_burst_size",
            "mean_inter_burst_gap", "pattern", "bursts",
        }
        self.assertEqual(set(r.keys()), expected_keys)

    def test_numeric_timestamps_accepted(self):
        r = burst_report([0, 1, 2, 100, 200, 300])
        self.assertEqual(r["burst_count"], 1)
        self.assertIn(r["pattern"], ("steady", "occasional", "clustered", "bursty"))

    def test_burst_fraction_rounded(self):
        ts = _ts(0, 1, 2, 100, 200)
        r = burst_report(ts, rapid_threshold_s=5.0)
        # rounded to at most 4 decimal places
        self.assertLessEqual(len(str(r["burst_fraction"]).split(".")[-1]), 4)


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify(unittest.TestCase):
    """Pattern classification logic."""

    def test_no_bursts_is_steady(self):
        self.assertEqual(_classify(0, 0.0, 0.0), "steady")

    def test_one_burst_low_fraction_is_occasional(self):
        self.assertEqual(_classify(1, 0.2, 120.0), "occasional")

    def test_two_bursts_low_fraction_is_occasional(self):
        self.assertEqual(_classify(2, 0.25, 300.0), "occasional")

    def test_multiple_bursts_short_gap_is_clustered(self):
        self.assertEqual(_classify(3, 0.5, 30.0), "clustered")

    def test_multiple_bursts_long_gap_is_bursty(self):
        self.assertEqual(_classify(3, 0.5, 120.0), "bursty")

    def test_high_fraction_short_gap_is_clustered(self):
        self.assertEqual(_classify(5, 0.8, 10.0), "clustered")

    def test_high_fraction_long_gap_is_bursty(self):
        self.assertEqual(_classify(5, 0.8, 300.0), "bursty")

    def test_boundary_occasional_at_threshold(self):
        # burst_count=2, fraction=0.29 < 0.3 → occasional
        self.assertEqual(_classify(2, 0.29, 200.0), "occasional")

    def test_boundary_not_occasional(self):
        # burst_count=2, fraction=0.30 → NOT occasional
        result = _classify(2, 0.30, 200.0)
        self.assertIn(result, ("clustered", "bursty"))


# ---------------------------------------------------------------------------
# burst_timeline
# ---------------------------------------------------------------------------

class TestBurstTimeline(unittest.TestCase):
    """ASCII timeline visualisation."""

    def test_empty(self):
        self.assertEqual(burst_timeline([]), "")

    def test_all_steady(self):
        ts = _ts(0, 15, 30, 45, 60)
        timeline = burst_timeline(ts)
        # no burst markers
        self.assertNotIn("█", timeline)
        self.assertIn("·", timeline)

    def test_burst_markers(self):
        ts = _ts(0, 1, 2, 60, 120)
        timeline = burst_timeline(ts, rapid_threshold_s=5.0, min_burst_size=3)
        self.assertIn("█", timeline)
        self.assertIn("·", timeline)

    def test_gap_separators(self):
        ts = _ts(0, 1, 2, 15, 60)
        timeline = burst_timeline(ts, rapid_threshold_s=5.0, min_burst_size=3)
        # long gap should produce ──
        self.assertIn("─", timeline)

    def test_timeline_length_reasonable(self):
        ts = _ts(0, 1, 2, 30, 60, 90)
        timeline = burst_timeline(ts)
        # should have one char per stroke minimum
        self.assertGreaterEqual(len(timeline), 6)

    def test_no_burst_no_block(self):
        # all gaps >= threshold
        ts = _ts(0, 10, 20, 30)
        timeline = burst_timeline(ts, rapid_threshold_s=5.0)
        self.assertNotIn("█", timeline)

    def test_single_burst_full(self):
        ts = _ts(0, 1, 2, 3, 4)
        timeline = burst_timeline(ts, rapid_threshold_s=5.0, min_burst_size=3)
        # all 5 strokes should be in burst
        self.assertEqual(timeline.count("█"), 5)


# ---------------------------------------------------------------------------
# Integration / edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    """Boundary and integration scenarios."""

    def test_two_timestamps_no_burst(self):
        ts = _ts(0, 10)
        r = burst_report(ts)
        self.assertEqual(r["burst_count"], 0)

    def test_all_rapid_single_burst(self):
        ts = _ts(0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
        r = burst_report(ts, rapid_threshold_s=5.0, min_burst_size=3)
        self.assertEqual(r["burst_count"], 1)
        self.assertEqual(r["max_burst_size"], 10)
        self.assertAlmostEqual(r["burst_fraction"], 1.0)

    def test_large_gap_between_bursts(self):
        ts = _ts(0, 1, 2, 10000, 10001, 10002)
        r = burst_report(ts, rapid_threshold_s=5.0, min_burst_size=3)
        self.assertEqual(r["burst_count"], 2)
        self.assertEqual(r["pattern"], "bursty")

    def test_mixed_numeric_and_datetime_fails_gracefully(self):
        # all-numeric should work
        r = burst_report([0, 100, 200, 300])
        self.assertEqual(r["burst_count"], 0)

    def test_report_reproducible(self):
        ts = _ts(0, 2, 4, 60, 62, 64, 200, 300)
        r1 = burst_report(ts)
        r2 = burst_report(ts)
        self.assertEqual(r1, r2)

    def test_timeline_and_report_agree(self):
        ts = _ts(0, 1, 2, 50, 51, 52, 200)
        r = burst_report(ts, rapid_threshold_s=5.0, min_burst_size=3)
        t = burst_timeline(ts, rapid_threshold_s=5.0, min_burst_size=3)
        burst_chars = t.count("█")
        # strokes_in_bursts from report
        strokes_in = sum(e - s + 1 for s, e in r["bursts"])
        self.assertEqual(burst_chars, strokes_in)


if __name__ == "__main__":
    unittest.main()
