#!/usr/bin/env python3
"""Tests for writer_stamina — 40 test cases."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from statistics import mean

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_stamina import (  # noqa: E402
    StaminaReport,
    _compute_score,
    _find_decay_onset,
    _max_consecutive_true,
    _rolling_mean,
    classify_decay,
    compute_stamina,
    load_intervals_from_jsonl,
)


# ---------------------------------------------------------------------------
# compute_stamina — empty / edge
# ---------------------------------------------------------------------------

class TestComputeStaminaEdge(unittest.TestCase):
    """Edge cases for the main entry point."""

    def test_empty_intervals(self):
        r = compute_stamina([])
        self.assertEqual(r.total_strokes, 0)
        self.assertEqual(r.stamina_score, 0)
        self.assertEqual(r.decay_profile, "none")

    def test_single_interval(self):
        r = compute_stamina([15.0])
        self.assertEqual(r.total_strokes, 1)
        self.assertIsNotNone(r.stamina_score)
        self.assertGreaterEqual(r.stamina_score, 0)

    def test_two_intervals(self):
        r = compute_stamina([15.0, 15.0])
        self.assertEqual(r.total_strokes, 2)

    def test_all_identical_intervals(self):
        intervals = [15.0] * 100
        r = compute_stamina(intervals, target_gap=15)
        self.assertEqual(r.decay_profile, "none")
        self.assertGreaterEqual(r.stamina_score, 40)


# ---------------------------------------------------------------------------
# compute_stamina — sustain and decay
# ---------------------------------------------------------------------------

class TestComputeStaminaSustain(unittest.TestCase):
    """Sustain duration and decay detection."""

    def test_steady_cadence_no_decay(self):
        intervals = [15.0 + (i % 3 - 1) * 0.5 for i in range(200)]
        r = compute_stamina(intervals, target_gap=15)
        self.assertIsNone(r.decay_onset)
        self.assertEqual(r.sustain_strokes, 200)

    def test_decay_detected_after_slow_start(self):
        good = [15.0] * 50
        bad = [45.0] * 30  # 3× target, well above threshold
        intervals = good + bad
        r = compute_stamina(intervals, target_gap=15, min_decay_run=5)
        self.assertIsNotNone(r.decay_onset)
        # Rolling mean delays onset detection; allow generous margin
        self.assertLessEqual(r.decay_onset, 75)

    def test_sustain_seconds_positive(self):
        intervals = [15.0] * 30
        r = compute_stamina(intervals, target_gap=15)
        self.assertGreater(r.sustain_s, 0)

    def test_peak_run_matches_steady_section(self):
        intervals = [15.0] * 80 + [60.0] * 10 + [15.0] * 20
        r = compute_stamina(intervals, target_gap=15, min_decay_run=5)
        self.assertGreaterEqual(r.peak_run, 80)

    def test_efficiency_bounded(self):
        r = compute_stamina([15.0, 30.0, 15.0, 45.0], target_gap=15)
        self.assertGreaterEqual(r.efficiency, 0.0)
        self.assertLessEqual(r.efficiency, 1.0)


# ---------------------------------------------------------------------------
# classify_decay
# ---------------------------------------------------------------------------

class TestClassifyDecay(unittest.TestCase):
    """Decay profile classification."""

    def test_none_when_no_onset(self):
        self.assertEqual(classify_decay([15.0] * 20, None, 15, 2.0), "none")

    def test_cliff_decay(self):
        cadence = [15.0] * 10 + [15.0, 16.0, 50.0, 55.0, 60.0] + [45.0] * 5
        result = classify_decay(cadence, 10, 15, 2.0)
        self.assertEqual(result, "cliff")

    def test_gradual_decay(self):
        # Monotonically increasing cadence
        cadence = [15.0] * 10 + [20.0 + i * 2.0 for i in range(20)]
        result = classify_decay(cadence, 10, 15, 2.0)
        self.assertEqual(result, "gradual")

    def test_oscillating_decay(self):
        # Alternating good/bad
        bad = 45.0
        good = 15.0
        after = [good, bad, good, bad, good, bad, good, bad, good, bad]
        cadence = [15.0] * 5 + after
        result = classify_decay(cadence, 5, 15, 2.0)
        self.assertEqual(result, "oscillating")

    def test_short_after_onset_returns_none(self):
        cadence = [15.0] * 10 + [45.0, 45.0]
        result = classify_decay(cadence, 10, 15, 2.0)
        self.assertEqual(result, "none")


# ---------------------------------------------------------------------------
# _rolling_mean
# ---------------------------------------------------------------------------

class TestRollingMean(unittest.TestCase):
    """Rolling mean computation."""

    def test_empty(self):
        self.assertEqual(_rolling_mean([], 5), [])

    def test_single_value(self):
        self.assertEqual(_rolling_mean([10.0], 5), [10.0])

    def test_window_larger_than_data(self):
        result = _rolling_mean([10.0, 20.0, 30.0], 10)
        self.assertAlmostEqual(result[0], 10.0)
        self.assertAlmostEqual(result[1], 15.0)
        self.assertAlmostEqual(result[2], 20.0)

    def test_exact_window(self):
        result = _rolling_mean([1.0, 2.0, 3.0, 4.0, 5.0], 3)
        self.assertAlmostEqual(result[2], 2.0)   # (1+2+3)/3
        self.assertAlmostEqual(result[3], 3.0)   # (2+3+4)/3
        self.assertAlmostEqual(result[4], 4.0)   # (3+4+5)/3

    def test_constant_values(self):
        result = _rolling_mean([7.0] * 10, 5)
        for v in result:
            self.assertAlmostEqual(v, 7.0)


# ---------------------------------------------------------------------------
# _max_consecutive_true
# ---------------------------------------------------------------------------

class TestMaxConsecutiveTrue(unittest.TestCase):
    """Longest run of True values."""

    def test_empty(self):
        self.assertEqual(_max_consecutive_true([]), 0)

    def test_all_true(self):
        self.assertEqual(_max_consecutive_true([True] * 10), 10)

    def test_all_false(self):
        self.assertEqual(_max_consecutive_true([False] * 10), 0)

    def test_mixed(self):
        flags = [True, True, False, True, True, True, False, True]
        self.assertEqual(_max_consecutive_true(flags), 3)

    def test_single_true(self):
        self.assertEqual(_max_consecutive_true([True]), 1)


# ---------------------------------------------------------------------------
# _find_decay_onset
# ---------------------------------------------------------------------------

class TestFindDecayOnset(unittest.TestCase):
    """Decay onset detection."""

    def test_no_decay(self):
        self.assertIsNone(_find_decay_onset([True] * 50, 5))

    def test_decay_found(self):
        flags = [True] * 20 + [False] * 10 + [True] * 5
        result = _find_decay_onset(flags, 5)
        self.assertEqual(result, 20)

    def test_short_bad_run_not_detected(self):
        flags = [True] * 20 + [False] * 3 + [True] * 10
        result = _find_decay_onset(flags, 5)
        self.assertIsNone(result)

    def test_all_bad(self):
        flags = [False] * 20
        result = _find_decay_onset(flags, 5)
        self.assertEqual(result, 0)

    def test_exact_min_run(self):
        flags = [True] * 10 + [False] * 5
        result = _find_decay_onset(flags, 5)
        self.assertEqual(result, 10)


# ---------------------------------------------------------------------------
# _compute_score
# ---------------------------------------------------------------------------

class TestComputeScore(unittest.TestCase):
    """Stamina score computation."""

    def test_perfect_session(self):
        # 3 hours, 500 peak run, 100% efficiency, no decay
        score = _compute_score(10800, 720, 720, 500, 1.0, "none")
        self.assertEqual(score, 100)

    def test_zero_session(self):
        score = _compute_score(0, 0, 0, 0, 0.0, "cliff")
        self.assertEqual(score, 2)  # cliff still gets 2 pts

    def test_bounded_0_100(self):
        score = _compute_score(999999, 9999, 9999, 9999, 1.0, "none")
        self.assertLessEqual(score, 100)
        self.assertGreaterEqual(score, 0)

    def test_gradual_beats_cliff(self):
        base = (3600, 200, 300, 100, 0.8)
        gradual = _compute_score(*base, "gradual")
        cliff = _compute_score(*base, "cliff")
        self.assertGreater(gradual, cliff)


# ---------------------------------------------------------------------------
# StaminaReport
# ---------------------------------------------------------------------------

class TestStaminaReport(unittest.TestCase):
    """StaminaReport data class."""

    def test_summary_no_strokes(self):
        r = StaminaReport(
            total_strokes=0, target_gap_s=15, sustain_s=0,
            sustain_strokes=0, peak_run=0, decay_onset=None,
            decay_profile="none", stamina_score=0, efficiency=0,
            mean_cadence_s=0, median_cadence_s=0,
        )
        self.assertIn("no strokes", r.summary())

    def test_summary_with_data(self):
        r = StaminaReport(
            total_strokes=100, target_gap_s=15, sustain_s=1500,
            sustain_strokes=100, peak_run=80, decay_onset=None,
            decay_profile="none", stamina_score=75, efficiency=0.9,
            mean_cadence_s=15.2, median_cadence_s=15.0,
        )
        s = r.summary()
        self.assertIn("75/100", s)
        self.assertIn("none", s)

    def test_frozen(self):
        r = StaminaReport(
            total_strokes=10, target_gap_s=15, sustain_s=150,
            sustain_strokes=10, peak_run=10, decay_onset=None,
            decay_profile="none", stamina_score=80, efficiency=1.0,
            mean_cadence_s=15.0, median_cadence_s=15.0,
        )
        with self.assertRaises(AttributeError):
            r.stamina_score = 99


# ---------------------------------------------------------------------------
# load_intervals_from_jsonl
# ---------------------------------------------------------------------------

class TestLoadIntervalsFromJsonl(unittest.TestCase):
    """Loading intervals from JSONL files."""

    def test_missing_file(self):
        result = load_intervals_from_jsonl("/tmp/nonexistent_strokes.jsonl")
        self.assertEqual(result, [])

    def test_valid_jsonl(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for i in range(10):
                f.write(json.dumps({"at": 1000000.0 + i * 15.0}) + "\n")
            f.flush()
            result = load_intervals_from_jsonl(f.name)
        os.unlink(f.name)
        self.assertEqual(len(result), 9)
        for v in result:
            self.assertAlmostEqual(v, 15.0)

    def test_max_strokes_limit(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for i in range(100):
                f.write(json.dumps({"at": 1000000.0 + i * 15.0}) + "\n")
            f.flush()
            result = load_intervals_from_jsonl(f.name, max_strokes=20)
        os.unlink(f.name)
        self.assertLessEqual(len(result), 20)

    def test_malformed_lines_skipped(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write("not json\n")
            f.write(json.dumps({"at": 1000.0}) + "\n")
            f.write("also bad\n")
            f.write(json.dumps({"at": 1015.0}) + "\n")
            f.flush()
            result = load_intervals_from_jsonl(f.name)
        os.unlink(f.name)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0], 15.0)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.flush()
            result = load_intervals_from_jsonl(f.name)
        os.unlink(f.name)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# Integration: full pipeline
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):
    """End-to-end stamina analysis."""

    def test_healthy_session(self):
        """Steady 15s cadence for 200 strokes → high score."""
        intervals = [15.0 + (i % 5 - 2) * 0.3 for i in range(200)]
        r = compute_stamina(intervals, target_gap=15)
        self.assertGreater(r.stamina_score, 40)
        self.assertEqual(r.decay_profile, "none")

    def test_degrading_session(self):
        """Starts good, cadence gradually increases → lower score."""
        intervals = []
        for i in range(200):
            if i < 50:
                intervals.append(15.0)
            else:
                intervals.append(15.0 + (i - 50) * 0.5)
        r = compute_stamina(intervals, target_gap=15, min_decay_run=5)
        self.assertLess(r.stamina_score, 60)

    def test_recovery_session(self):
        """Bad start, then recovers → moderate score."""
        bad = [45.0] * 10
        good = [15.0] * 100
        r = compute_stamina(bad + good, target_gap=15, min_decay_run=5)
        self.assertIsNotNone(r.decay_onset)
        # Sustained good section after decay → decent efficiency
        self.assertGreater(r.efficiency, 0.5)


if __name__ == "__main__":
    unittest.main()
