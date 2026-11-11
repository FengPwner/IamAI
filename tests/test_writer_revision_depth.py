#!/usr/bin/env python3
"""Tests for writer_revision_depth — revision depth analysis.

55 tests covering:
- StrokeRecord construction and post_init padding
- _classify_stroke (generative, revisory, empty, mixed)
- _file_creation_map (single, multiple, no-creation)
- _file_revision_counts (all new, all modified, mixed, empty)
- revision_ratio (all generative, all revisory, mixed, empty, single)
- generation_ratio (complement check)
- avg_revision_rounds (no revisions, one revision, multiple files)
- revision_intensity (no revised files, single, multiple)
- churn_index (high churn, no churn, single stroke, empty, custom gap)
- classify_depth (all five classes + boundary values)
- compute_depth (composite scoring, empty input, architect vs sculptor)
- depth_report formatting
- depth_trend (increasing, decreasing, stable, single, empty)
- lookback window effects
- full pipeline integration
"""

import math
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, ".")
from iamai.writer_revision_depth import (
    DepthResult,
    DepthTrend,
    StrokeRecord,
    _classify_stroke,
    _file_creation_map,
    _file_revision_counts,
    avg_revision_rounds,
    churn_index,
    classify_depth,
    compute_depth,
    depth_report,
    depth_trend,
    generation_ratio,
    revision_intensity,
    revision_ratio,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 11, 1, 12, 0, 0)


def _mkstroke(files, is_new=None, message="", offset_minutes=0):
    """Create a StrokeRecord with automatic is_new padding."""
    if is_new is None:
        is_new = [False] * len(files)
    return StrokeRecord(
        timestamp=_BASE + timedelta(minutes=offset_minutes),
        files=list(files),
        is_new_file=list(is_new),
        message=message,
    )


def _all_new(files):
    """Mark all files as new."""
    return files, [True] * len(files)


def _all_existing(files):
    """Mark all files as existing (modified)."""
    return files, [False] * len(files)


# ---------------------------------------------------------------------------
# StrokeRecord tests
# ---------------------------------------------------------------------------

class TestStrokeRecord(unittest.TestCase):
    def test_construction(self):
        s = _mkstroke(["a.py", "b.py"], [True, False], "test", 10)
        self.assertEqual(s.files, ["a.py", "b.py"])
        self.assertEqual(s.is_new_file, [True, False])
        self.assertEqual(s.message, "test")

    def test_post_init_padding(self):
        """is_new_file shorter than files gets padded with False."""
        s = StrokeRecord(timestamp=_BASE, files=["a.py", "b.py", "c.py"],
                         is_new_file=[True])
        self.assertEqual(s.is_new_file, [True, False, False])

    def test_default_fields(self):
        s = StrokeRecord(timestamp=_BASE)
        self.assertEqual(s.files, [])
        self.assertEqual(s.is_new_file, [])

    def test_is_new_longer_than_files(self):
        """Extra is_new values are kept but don't cause errors."""
        s = StrokeRecord(timestamp=_BASE, files=["a.py"],
                         is_new_file=[True, False, False])
        self.assertEqual(len(s.is_new_file), 3)


# ---------------------------------------------------------------------------
# _classify_stroke tests
# ---------------------------------------------------------------------------

class TestClassifyStroke(unittest.TestCase):
    def test_all_new_files_is_generative(self):
        s = _mkstroke(["a.py", "b.py"], [True, True])
        self.assertEqual(_classify_stroke(s), "generative")

    def test_all_existing_files_is_revisory(self):
        s = _mkstroke(["a.py", "b.py"], [False, False])
        self.assertEqual(_classify_stroke(s), "revisory")

    def test_majority_new_is_generative(self):
        s = _mkstroke(["a.py", "b.py", "c.py"], [True, True, False])
        self.assertEqual(_classify_stroke(s), "generative")

    def test_majority_existing_is_revisory(self):
        s = _mkstroke(["a.py", "b.py", "c.py"], [True, False, False])
        self.assertEqual(_classify_stroke(s), "revisory")

    def test_empty_stroke_is_revisory(self):
        s = _mkstroke([], [])
        self.assertEqual(_classify_stroke(s), "revisory")

    def test_single_new_file_is_generative(self):
        s = _mkstroke(["a.py"], [True])
        self.assertEqual(_classify_stroke(s), "generative")

    def test_single_existing_file_is_revisory(self):
        s = _mkstroke(["a.py"], [False])
        self.assertEqual(_classify_stroke(s), "revisory")

    def test_exactly_half_new_is_revisory(self):
        """When exactly half are new, it's NOT > half, so revisory."""
        s = _mkstroke(["a.py", "b.py"], [True, False])
        self.assertEqual(_classify_stroke(s), "revisory")


# ---------------------------------------------------------------------------
# _file_creation_map tests
# ---------------------------------------------------------------------------

class TestFileCreationMap(unittest.TestCase):
    def test_single_creation(self):
        strokes = [_mkstroke(["a.py"], [True])]
        m = _file_creation_map(strokes)
        self.assertEqual(m, {"a.py": 0})

    def test_multiple_creations(self):
        strokes = [
            _mkstroke(["a.py"], [True]),
            _mkstroke(["b.py"], [True]),
        ]
        m = _file_creation_map(strokes)
        self.assertEqual(m, {"a.py": 0, "b.py": 1})

    def test_first_creation_wins(self):
        """If a file appears as new twice, only the first index is recorded."""
        strokes = [
            _mkstroke(["a.py"], [True]),
            _mkstroke(["a.py"], [True]),
        ]
        m = _file_creation_map(strokes)
        self.assertEqual(m, {"a.py": 0})

    def test_no_creations(self):
        strokes = [_mkstroke(["a.py"], [False])]
        m = _file_creation_map(strokes)
        self.assertEqual(m, {})

    def test_empty(self):
        self.assertEqual(_file_creation_map([]), {})


# ---------------------------------------------------------------------------
# _file_revision_counts tests
# ---------------------------------------------------------------------------

class TestFileRevisionCounts(unittest.TestCase):
    def test_all_new_files_no_revisions(self):
        strokes = [_mkstroke(["a.py", "b.py"], [True, True])]
        self.assertEqual(_file_revision_counts(strokes), {})

    def test_all_modified(self):
        strokes = [
            _mkstroke(["a.py"], [False]),
            _mkstroke(["a.py"], [False]),
        ]
        self.assertEqual(_file_revision_counts(strokes), {"a.py": 2})

    def test_mixed(self):
        strokes = [
            _mkstroke(["a.py"], [True]),
            _mkstroke(["a.py"], [False]),
            _mkstroke(["b.py"], [False]),
        ]
        counts = _file_revision_counts(strokes)
        self.assertEqual(counts["a.py"], 1)
        self.assertEqual(counts["b.py"], 1)

    def test_empty(self):
        self.assertEqual(_file_revision_counts([]), {})


# ---------------------------------------------------------------------------
# revision_ratio tests
# ---------------------------------------------------------------------------

class TestRevisionRatio(unittest.TestCase):
    def test_all_generative(self):
        strokes = [
            _mkstroke(["a.py"], [True]),
            _mkstroke(["b.py"], [True]),
            _mkstroke(["c.py"], [True]),
        ]
        self.assertEqual(revision_ratio(strokes), 0.0)

    def test_all_revisory(self):
        strokes = [
            _mkstroke(["a.py"], [False]),
            _mkstroke(["a.py"], [False]),
        ]
        self.assertEqual(revision_ratio(strokes), 1.0)

    def test_mixed(self):
        strokes = [
            _mkstroke(["a.py"], [True]),   # generative
            _mkstroke(["a.py"], [False]),   # revisory
            _mkstroke(["b.py"], [True]),    # generative
            _mkstroke(["a.py"], [False]),   # revisory
        ]
        self.assertEqual(revision_ratio(strokes), 0.5)

    def test_empty(self):
        self.assertEqual(revision_ratio([]), 0.0)

    def test_single_generative(self):
        strokes = [_mkstroke(["a.py"], [True])]
        self.assertEqual(revision_ratio(strokes), 0.0)

    def test_single_revisory(self):
        strokes = [_mkstroke(["a.py"], [False])]
        self.assertEqual(revision_ratio(strokes), 1.0)


# ---------------------------------------------------------------------------
# generation_ratio tests
# ---------------------------------------------------------------------------

class TestGenerationRatio(unittest.TestCase):
    def test_complement_of_revision(self):
        strokes = [
            _mkstroke(["a.py"], [True]),
            _mkstroke(["a.py"], [False]),
        ]
        self.assertAlmostEqual(
            generation_ratio(strokes) + revision_ratio(strokes), 1.0
        )

    def test_all_generative(self):
        strokes = [_mkstroke(["a.py"], [True])]
        self.assertEqual(generation_ratio(strokes), 1.0)

    def test_empty(self):
        self.assertEqual(generation_ratio([]), 1.0)


# ---------------------------------------------------------------------------
# avg_revision_rounds tests
# ---------------------------------------------------------------------------

class TestAvgRevisionRounds(unittest.TestCase):
    def test_no_revisions(self):
        strokes = [_mkstroke(["a.py"], [True])]
        self.assertEqual(avg_revision_rounds(strokes), 0.0)

    def test_single_revision(self):
        strokes = [
            _mkstroke(["a.py"], [True]),
            _mkstroke(["a.py"], [False]),
        ]
        self.assertEqual(avg_revision_rounds(strokes), 1.0)

    def test_multiple_files(self):
        strokes = [
            _mkstroke(["a.py"], [True]),
            _mkstroke(["b.py"], [True]),
            _mkstroke(["a.py"], [False]),
            _mkstroke(["a.py"], [False]),
            _mkstroke(["b.py"], [False]),
        ]
        # a.py: 2 revisions, b.py: 1 revision → avg = 1.5
        self.assertEqual(avg_revision_rounds(strokes), 1.5)

    def test_empty(self):
        self.assertEqual(avg_revision_rounds([]), 0.0)


# ---------------------------------------------------------------------------
# revision_intensity tests
# ---------------------------------------------------------------------------

class TestRevisionIntensity(unittest.TestCase):
    def test_no_revised_files(self):
        strokes = [_mkstroke(["a.py"], [True])]
        self.assertEqual(revision_intensity(strokes), 0.0)

    def test_single_revised_file(self):
        strokes = [
            _mkstroke(["a.py"], [True]),
            _mkstroke(["a.py"], [False]),
            _mkstroke(["a.py"], [False]),
            _mkstroke(["a.py"], [False]),
        ]
        self.assertEqual(revision_intensity(strokes), 3.0)

    def test_empty(self):
        self.assertEqual(revision_intensity([]), 0.0)


# ---------------------------------------------------------------------------
# churn_index tests
# ---------------------------------------------------------------------------

class TestChurnIndex(unittest.TestCase):
    def test_high_churn(self):
        """Most strokes touch a file that the next stroke also touches."""
        strokes = [
            _mkstroke(["a.py"], [True]),
            _mkstroke(["a.py"], [False]),
            _mkstroke(["a.py"], [False]),
            _mkstroke(["a.py"], [False]),
        ]
        # Last stroke has no future → no churn; 3 out of 4 = 0.75
        self.assertEqual(churn_index(strokes), 0.75)

    def test_no_churn(self):
        """No file is touched again within the gap window."""
        strokes = [
            _mkstroke(["a.py"], [True]),
            _mkstroke(["b.py"], [True]),
            _mkstroke(["c.py"], [True]),
            _mkstroke(["d.py"], [True]),
            _mkstroke(["e.py"], [True]),
            _mkstroke(["f.py"], [True]),
        ]
        self.assertEqual(churn_index(strokes), 0.0)

    def test_single_stroke(self):
        self.assertEqual(churn_index([_mkstroke(["a.py"], [True])]), 0.0)

    def test_empty(self):
        self.assertEqual(churn_index([]), 0.0)

    def test_custom_gap(self):
        """With gap=1, only immediately adjacent strokes count."""
        strokes = [
            _mkstroke(["a.py"], [True]),
            _mkstroke(["b.py"], [True]),
            _mkstroke(["a.py"], [False]),  # a.py again, but gap=2 from first
        ]
        # stroke 0: a.py — next 1 stroke has b.py → no churn
        # stroke 1: b.py — next 1 stroke has a.py → no churn
        # stroke 2: a.py — no next stroke → no churn
        self.assertEqual(churn_index(strokes, gap=1), 0.0)

    def test_stroke_with_no_files(self):
        """Strokes with empty file lists are excluded from the denominator."""
        strokes = [
            _mkstroke(["a.py"], [True]),
            _mkstroke([], []),
            _mkstroke(["a.py"], [False]),
        ]
        # stroke 0 has files; a.py appears in stroke 2 (within gap=5) → churn
        # stroke 1 has no files → excluded
        # stroke 2 has files; no future strokes → no churn
        # 1 out of 2 strokes with files → 0.5
        self.assertEqual(churn_index(strokes), 0.5)


# ---------------------------------------------------------------------------
# classify_depth tests
# ---------------------------------------------------------------------------

class TestClassifyDepth(unittest.TestCase):
    def test_architect(self):
        self.assertEqual(classify_depth(0.00), "architect")
        self.assertEqual(classify_depth(0.10), "architect")
        self.assertEqual(classify_depth(0.14), "architect")

    def test_light_editor(self):
        self.assertEqual(classify_depth(0.15), "light-editor")
        self.assertEqual(classify_depth(0.25), "light-editor")

    def test_gardener(self):
        self.assertEqual(classify_depth(0.30), "gardener")
        self.assertEqual(classify_depth(0.45), "gardener")

    def test_polisher(self):
        self.assertEqual(classify_depth(0.50), "polisher")
        self.assertEqual(classify_depth(0.65), "polisher")

    def test_sculptor(self):
        self.assertEqual(classify_depth(0.70), "sculptor")
        self.assertEqual(classify_depth(1.00), "sculptor")

    def test_boundary_values(self):
        self.assertEqual(classify_depth(0.149999), "architect")
        self.assertEqual(classify_depth(0.15), "light-editor")
        self.assertEqual(classify_depth(0.299999), "light-editor")
        self.assertEqual(classify_depth(0.30), "gardener")
        self.assertEqual(classify_depth(0.499999), "gardener")
        self.assertEqual(classify_depth(0.50), "polisher")
        self.assertEqual(classify_depth(0.699999), "polisher")
        self.assertEqual(classify_depth(0.70), "sculptor")


# ---------------------------------------------------------------------------
# compute_depth tests
# ---------------------------------------------------------------------------

class TestComputeDepth(unittest.TestCase):
    def test_empty_input(self):
        result = compute_depth([])
        self.assertEqual(result.window_strokes, 0)
        self.assertEqual(result.depth_score, 0.3)
        self.assertEqual(result.depth_class, "gardener")

    def test_all_generative_architect(self):
        """All strokes create new files → low depth score → architect."""
        strokes = [
            _mkstroke([f"file_{i}.py"], [True], offset_minutes=i)
            for i in range(20)
        ]
        result = compute_depth(strokes)
        self.assertEqual(result.revision_ratio, 0.0)
        self.assertEqual(result.depth_class, "architect")
        self.assertLess(result.depth_score, 0.15)

    def test_all_revisory_sculptor(self):
        """All strokes modify one file → high depth score → sculptor."""
        strokes = [
            _mkstroke(["core.py"], [True], offset_minutes=0),
        ] + [
            _mkstroke(["core.py"], [False], offset_minutes=i)
            for i in range(1, 30)
        ]
        result = compute_depth(strokes)
        self.assertGreater(result.revision_ratio, 0.9)
        self.assertEqual(result.depth_class, "sculptor")

    def test_gardener_mix(self):
        """A mix of new files and revisions → gardener range."""
        strokes = []
        for i in range(10):
            strokes.append(_mkstroke([f"new_{i}.py"], [True], offset_minutes=i * 2))
            strokes.append(_mkstroke([f"new_{i}.py"], [False], offset_minutes=i * 2 + 1))
        result = compute_depth(strokes)
        self.assertIn(result.depth_class, ["light-editor", "gardener", "polisher"])

    def test_lookback_window(self):
        """Only the last `lookback` strokes are analyzed."""
        # First 30 strokes: all generative
        strokes = [
            _mkstroke([f"old_{i}.py"], [True], offset_minutes=i)
            for i in range(30)
        ]
        # Next 20 strokes: all revisory
        strokes += [
            _mkstroke(["core.py"], [False], offset_minutes=30 + i)
            for i in range(20)
        ]
        result = compute_depth(strokes, lookback=20)
        # Should only see the revisory strokes
        self.assertEqual(result.revision_ratio, 1.0)

    def test_file_revision_counts_populated(self):
        strokes = [
            _mkstroke(["a.py"], [True]),
            _mkstroke(["a.py"], [False]),
            _mkstroke(["a.py"], [False]),
            _mkstroke(["b.py"], [False]),
        ]
        result = compute_depth(strokes)
        self.assertIn("a.py", result.file_revision_counts)
        self.assertEqual(result.file_revision_counts["a.py"], 2)

    def test_new_and_revised_file_counts(self):
        strokes = [
            _mkstroke(["a.py", "b.py"], [True, True]),
            _mkstroke(["a.py"], [False]),
            _mkstroke(["c.py"], [False]),
        ]
        result = compute_depth(strokes)
        self.assertEqual(result.new_file_count, 2)  # a.py, b.py
        self.assertEqual(result.revised_file_count, 2)  # a.py, c.py


# ---------------------------------------------------------------------------
# depth_report tests
# ---------------------------------------------------------------------------

class TestDepthReport(unittest.TestCase):
    def test_report_contains_key_fields(self):
        result = DepthResult(
            window_strokes=50,
            revision_ratio=0.6,
            generation_ratio=0.4,
            avg_revision_rounds=3.2,
            revision_intensity=4.1,
            churn_index=0.35,
            depth_score=0.55,
            depth_class="polisher",
            file_revision_counts={"core.py": 15, "util.py": 8},
            new_file_count=10,
            revised_file_count=20,
        )
        report = depth_report(result)
        self.assertIn("polisher", report)
        self.assertIn("0.55", report)
        self.assertIn("core.py", report)
        self.assertIn("50 strokes", report)
        self.assertIn("60.00%", report)

    def test_report_empty_counts(self):
        result = DepthResult(
            window_strokes=0,
            revision_ratio=0.0,
            generation_ratio=0.0,
            avg_revision_rounds=0.0,
            revision_intensity=0.0,
            churn_index=0.0,
            depth_score=0.3,
            depth_class="gardener",
        )
        report = depth_report(result)
        self.assertIn("gardener", report)
        self.assertNotIn("most-revised", report)


# ---------------------------------------------------------------------------
# depth_trend tests
# ---------------------------------------------------------------------------

class TestDepthTrend(unittest.TestCase):
    def test_increasing(self):
        results = [
            DepthResult(0, 0, 0, 0, 0, 0, 0.2, "light-editor"),
            DepthResult(0, 0, 0, 0, 0, 0, 0.5, "gardener"),
        ]
        trend = depth_trend(results)
        self.assertEqual(trend.direction, "increasing")
        self.assertAlmostEqual(trend.score_delta, 0.3)

    def test_decreasing(self):
        results = [
            DepthResult(0, 0, 0, 0, 0, 0, 0.7, "polisher"),
            DepthResult(0, 0, 0, 0, 0, 0, 0.3, "gardener"),
        ]
        trend = depth_trend(results)
        self.assertEqual(trend.direction, "decreasing")

    def test_stable(self):
        results = [
            DepthResult(0, 0, 0, 0, 0, 0, 0.40, "gardener"),
            DepthResult(0, 0, 0, 0, 0, 0, 0.43, "gardener"),
        ]
        trend = depth_trend(results)
        self.assertEqual(trend.direction, "stable")

    def test_single_result(self):
        results = [DepthResult(0, 0, 0, 0, 0, 0, 0.5, "gardener")]
        trend = depth_trend(results)
        self.assertEqual(trend.direction, "stable")
        self.assertEqual(trend.sample_count, 1)

    def test_empty(self):
        trend = depth_trend([])
        self.assertEqual(trend.direction, "stable")
        self.assertEqual(trend.sample_count, 0)


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):
    def test_full_pipeline(self):
        """Build a realistic stroke sequence and run the full pipeline."""
        strokes = []
        # Create 5 new files
        for i in range(5):
            strokes.append(_mkstroke([f"mod_{i}.py"], [True], offset_minutes=i * 3))
        # Revise each file twice
        for i in range(5):
            strokes.append(_mkstroke([f"mod_{i}.py"], [False], offset_minutes=15 + i * 2))
            strokes.append(_mkstroke([f"mod_{i}.py"], [False], offset_minutes=16 + i * 2))

        result = compute_depth(strokes, lookback=50)
        self.assertEqual(result.window_strokes, 15)
        self.assertEqual(result.new_file_count, 5)
        self.assertEqual(result.revised_file_count, 5)
        self.assertGreater(result.revision_ratio, 0.6)

        report = depth_report(result)
        self.assertIn("Revision depth", report)

    def test_trend_across_windows(self):
        """Compute depth for two windows and check trend."""
        # Window 1: mostly generative
        w1_strokes = [
            _mkstroke([f"a_{i}.py"], [True], offset_minutes=i)
            for i in range(10)
        ]
        # Window 2: mostly revisory
        w2_strokes = [
            _mkstroke(["core.py"], [False], offset_minutes=i)
            for i in range(10)
        ]
        r1 = compute_depth(w1_strokes)
        r2 = compute_depth(w2_strokes)

        trend = depth_trend([r1, r2])
        self.assertEqual(trend.direction, "increasing")
        self.assertGreater(trend.score_delta, 0)


if __name__ == "__main__":
    unittest.main()
