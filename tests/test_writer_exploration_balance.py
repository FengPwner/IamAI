#!/usr/bin/env python3
"""Tests for writer_exploration_balance — explore/exploit tradeoff analysis.

62 tests covering:
- StrokeRecord construction
- _first_seen_map (single stroke, multiple strokes, empty)
- _novelty_half_life (immediate re-touch, delayed, no re-touch, single stroke)
- exploration_ratio (all new, all revisited, mixed, empty, single stroke)
- exploitation_ratio (complement check)
- breadth_index (all unique, all same, mixed, empty)
- depth_index (single file dominant, uniform, single stroke, empty)
- classify_balance (all five classes + boundary values)
- compute_balance (composite scoring, empty input, deepening vs broadening)
- balance_report formatting
- balance_trend (increasing, decreasing, stable, single, empty)
- lookback window effects
- full pipeline integration
"""

import math
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, ".")
from iamai.writer_exploration_balance import (
    BalanceResult,
    BalanceTrend,
    StrokeRecord,
    _first_seen_map,
    _novelty_half_life,
    balance_report,
    balance_trend,
    breadth_index,
    classify_balance,
    compute_balance,
    depth_index,
    exploitation_ratio,
    exploration_ratio,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 11, 1, 12, 0, 0)


def _mkstroke(files, message="", offset_minutes=0):
    """Create a StrokeRecord."""
    return StrokeRecord(
        timestamp=_BASE + timedelta(minutes=offset_minutes),
        files=list(files),
        message=message,
    )


# ---------------------------------------------------------------------------
# StrokeRecord tests
# ---------------------------------------------------------------------------

class TestStrokeRecord(unittest.TestCase):
    def test_construction(self):
        s = _mkstroke(["a.py", "b.py"], "test", 10)
        self.assertEqual(s.files, ["a.py", "b.py"])
        self.assertEqual(s.message, "test")
        self.assertEqual(s.timestamp, _BASE + timedelta(minutes=10))

    def test_default_fields(self):
        s = StrokeRecord(timestamp=_BASE)
        self.assertEqual(s.files, [])
        self.assertEqual(s.message, "")

    def test_files_are_independent(self):
        """Mutating the input list after creation should not affect the record."""
        flist = ["a.py"]
        s = _mkstroke(flist)
        flist.append("b.py")
        self.assertEqual(s.files, ["a.py"])


# ---------------------------------------------------------------------------
# _first_seen_map tests
# ---------------------------------------------------------------------------

class TestFirstSeenMap(unittest.TestCase):
    def test_single_stroke(self):
        strokes = [_mkstroke(["a.py", "b.py"])]
        result = _first_seen_map(strokes)
        self.assertEqual(result, {"a.py": 0, "b.py": 0})

    def test_multiple_strokes(self):
        strokes = [
            _mkstroke(["a.py"]),
            _mkstroke(["b.py"]),
            _mkstroke(["a.py", "c.py"]),
        ]
        result = _first_seen_map(strokes)
        self.assertEqual(result, {"a.py": 0, "b.py": 1, "c.py": 2})

    def test_empty(self):
        self.assertEqual(_first_seen_map([]), {})

    def test_all_same_files(self):
        strokes = [_mkstroke(["a.py"]) for _ in range(5)]
        result = _first_seen_map(strokes)
        self.assertEqual(result, {"a.py": 0})


# ---------------------------------------------------------------------------
# _novelty_half_life tests
# ---------------------------------------------------------------------------

class TestNoveltyHalfLife(unittest.TestCase):
    def test_immediate_retouch(self):
        """File re-touched in the very next stroke → gap = 1."""
        strokes = [
            _mkstroke(["a.py"]),
            _mkstroke(["a.py"]),
        ]
        self.assertEqual(_novelty_half_life(strokes), 1.0)

    def test_delayed_retouch(self):
        strokes = [
            _mkstroke(["a.py"]),
            _mkstroke(["b.py"]),
            _mkstroke(["c.py"]),
            _mkstroke(["a.py"]),
        ]
        self.assertEqual(_novelty_half_life(strokes), 3.0)

    def test_no_retouch(self):
        """All unique files → infinity."""
        strokes = [
            _mkstroke(["a.py"]),
            _mkstroke(["b.py"]),
            _mkstroke(["c.py"]),
        ]
        self.assertEqual(_novelty_half_life(strokes), float("inf"))

    def test_single_stroke(self):
        strokes = [_mkstroke(["a.py", "b.py"])]
        self.assertEqual(_novelty_half_life(strokes), float("inf"))

    def test_empty(self):
        self.assertEqual(_novelty_half_life([]), float("inf"))

    def test_multiple_retouches_median(self):
        """Two files with different return gaps → median."""
        strokes = [
            _mkstroke(["a.py", "b.py"]),   # 0: both new
            _mkstroke(["a.py"]),            # 1: a returns (gap=1)
            _mkstroke(["c.py"]),            # 2: new
            _mkstroke(["d.py"]),            # 3: new
            _mkstroke(["b.py"]),            # 4: b returns (gap=4)
        ]
        # gaps: a=1, b=4 → median = (1+4)/2 = 2.5
        self.assertEqual(_novelty_half_life(strokes), 2.5)

    def test_odd_number_of_gaps(self):
        strokes = [
            _mkstroke(["a.py"]),
            _mkstroke(["a.py"]),  # gap=1
            _mkstroke(["b.py"]),
            _mkstroke(["c.py"]),
            _mkstroke(["b.py"]),  # gap=2
            _mkstroke(["c.py"]),  # gap=2
        ]
        # gaps: a=1, b=2, c=2 → sorted [1,2,2] → median=2
        self.assertEqual(_novelty_half_life(strokes), 2.0)


# ---------------------------------------------------------------------------
# exploration_ratio tests
# ---------------------------------------------------------------------------

class TestExplorationRatio(unittest.TestCase):
    def test_all_new(self):
        """Every stroke touches unique files → 100% exploration."""
        strokes = [
            _mkstroke(["a.py"]),
            _mkstroke(["b.py"]),
            _mkstroke(["c.py"]),
        ]
        self.assertEqual(exploration_ratio(strokes, lookback=50), 1.0)

    def test_all_revisited(self):
        """Every stroke re-touches the same file → 0% exploration after first."""
        strokes = [
            _mkstroke(["a.py"]),  # first: explore
            _mkstroke(["a.py"]),  # re-visit
            _mkstroke(["a.py"]),  # re-visit
        ]
        # 1 explore out of 3 total = 0.3333
        self.assertAlmostEqual(exploration_ratio(strokes, lookback=50), 0.3333, places=4)

    def test_mixed(self):
        strokes = [
            _mkstroke(["a.py"]),  # new
            _mkstroke(["b.py"]),  # new
            _mkstroke(["a.py", "c.py"]),  # a=revisit, c=new
        ]
        # 3 new out of 4 total = 0.75
        self.assertAlmostEqual(exploration_ratio(strokes, lookback=50), 0.75, places=4)

    def test_empty(self):
        self.assertEqual(exploration_ratio([]), 0.0)

    def test_single_stroke(self):
        """First stroke is always 100% exploration."""
        strokes = [_mkstroke(["a.py", "b.py", "c.py"])]
        self.assertEqual(exploration_ratio(strokes), 1.0)

    def test_lookback_window_effect(self):
        """Files outside the lookback window count as new again."""
        strokes = [
            _mkstroke(["a.py"]),  # index 0
            _mkstroke(["b.py"]),  # index 1
            _mkstroke(["c.py"]),  # index 2
            _mkstroke(["d.py"]),  # index 3
            _mkstroke(["a.py"]),  # index 4: lookback=2 → only sees indices 2,3 → a is new!
        ]
        # With lookback=2: stroke 4 only sees {c.py, d.py} as recent
        # a.py is NOT in {c.py, d.py} → it's "explored" again
        # All 5 strokes, 5 files total:
        # stroke 0: a=new (1/1)
        # stroke 1: b=new (1/1)
        # stroke 2: c=new (1/1)
        # stroke 3: d=new (1/1)
        # stroke 4: a=new (lookback only sees c,d) (1/1)
        # = 5/5 = 1.0
        self.assertAlmostEqual(exploration_ratio(strokes, lookback=2), 1.0, places=4)

    def test_lookback_catches_revisit(self):
        """With a wider lookback, the revisit is detected."""
        strokes = [
            _mkstroke(["a.py"]),
            _mkstroke(["b.py"]),
            _mkstroke(["c.py"]),
            _mkstroke(["d.py"]),
            _mkstroke(["a.py"]),  # lookback=10 sees all → a is revisit
        ]
        # 4 new + 1 revisit out of 5 = 0.8
        self.assertAlmostEqual(exploration_ratio(strokes, lookback=10), 0.8, places=4)


# ---------------------------------------------------------------------------
# exploitation_ratio tests
# ---------------------------------------------------------------------------

class TestExploitationRatio(unittest.TestCase):
    def test_complement(self):
        """exploitation_ratio should always be 1 - exploration_ratio."""
        strokes = [
            _mkstroke(["a.py"]),
            _mkstroke(["b.py"]),
            _mkstroke(["a.py"]),
        ]
        exp = exploration_ratio(strokes, lookback=50)
        exploit = exploitation_ratio(strokes, lookback=50)
        self.assertAlmostEqual(exp + exploit, 1.0, places=4)

    def test_all_revisited(self):
        strokes = [_mkstroke(["a.py"])] * 5
        # First is new (1/5 = 0.2 explore), rest are revisits
        self.assertAlmostEqual(exploitation_ratio(strokes, lookback=50), 0.8, places=4)


# ---------------------------------------------------------------------------
# breadth_index tests
# ---------------------------------------------------------------------------

class TestBreadthIndex(unittest.TestCase):
    def test_all_unique(self):
        """Each file touched once → breadth = 1.0."""
        strokes = [
            _mkstroke(["a.py"]),
            _mkstroke(["b.py"]),
            _mkstroke(["c.py"]),
        ]
        self.assertEqual(breadth_index(strokes), 1.0)

    def test_all_same(self):
        """One file touched many times → breadth = 1/N."""
        strokes = [_mkstroke(["a.py"]) for _ in range(5)]
        self.assertAlmostEqual(breadth_index(strokes), 1.0 / 5, places=4)

    def test_mixed(self):
        strokes = [
            _mkstroke(["a.py", "b.py"]),
            _mkstroke(["a.py", "c.py"]),
        ]
        # 3 distinct / 4 total = 0.75
        self.assertAlmostEqual(breadth_index(strokes), 0.75, places=4)

    def test_empty(self):
        self.assertEqual(breadth_index([]), 0.0)

    def test_empty_strokes(self):
        strokes = [_mkstroke([]), _mkstroke([])]
        self.assertEqual(breadth_index(strokes), 0.0)


# ---------------------------------------------------------------------------
# depth_index tests
# ---------------------------------------------------------------------------

class TestDepthIndex(unittest.TestCase):
    def test_single_file_dominant(self):
        strokes = [
            _mkstroke(["a.py"]),
            _mkstroke(["a.py"]),
            _mkstroke(["a.py"]),
            _mkstroke(["b.py"]),
        ]
        # a: 3, b: 1 → max=3, total=4 → 0.75
        self.assertAlmostEqual(depth_index(strokes), 0.75, places=4)

    def test_uniform(self):
        strokes = [
            _mkstroke(["a.py"]),
            _mkstroke(["b.py"]),
            _mkstroke(["c.py"]),
        ]
        # all have count 1 → max=1, total=3 → 0.3333
        self.assertAlmostEqual(depth_index(strokes), 0.3333, places=4)

    def test_single_stroke(self):
        strokes = [_mkstroke(["a.py"])]
        self.assertEqual(depth_index(strokes), 1.0)

    def test_empty(self):
        self.assertEqual(depth_index([]), 0.0)


# ---------------------------------------------------------------------------
# classify_balance tests
# ---------------------------------------------------------------------------

class TestClassifyBalance(unittest.TestCase):
    def test_deepening(self):
        self.assertEqual(classify_balance(0.0), "deepening")
        self.assertEqual(classify_balance(0.10), "deepening")
        self.assertEqual(classify_balance(0.19), "deepening")

    def test_balanced_low(self):
        self.assertEqual(classify_balance(0.20), "balanced-low")
        self.assertEqual(classify_balance(0.30), "balanced-low")
        self.assertEqual(classify_balance(0.39), "balanced-low")

    def test_balanced(self):
        self.assertEqual(classify_balance(0.40), "balanced")
        self.assertEqual(classify_balance(0.50), "balanced")
        self.assertEqual(classify_balance(0.59), "balanced")

    def test_balanced_high(self):
        self.assertEqual(classify_balance(0.60), "balanced-high")
        self.assertEqual(classify_balance(0.70), "balanced-high")
        self.assertEqual(classify_balance(0.79), "balanced-high")

    def test_broadening(self):
        self.assertEqual(classify_balance(0.80), "broadening")
        self.assertEqual(classify_balance(0.90), "broadening")
        self.assertEqual(classify_balance(1.0), "broadening")

    def test_boundary_values(self):
        self.assertEqual(classify_balance(0.199), "deepening")
        self.assertEqual(classify_balance(0.20), "balanced-low")
        self.assertEqual(classify_balance(0.399), "balanced-low")
        self.assertEqual(classify_balance(0.40), "balanced")
        self.assertEqual(classify_balance(0.599), "balanced")
        self.assertEqual(classify_balance(0.60), "balanced-high")
        self.assertEqual(classify_balance(0.799), "balanced-high")
        self.assertEqual(classify_balance(0.80), "broadening")


# ---------------------------------------------------------------------------
# compute_balance tests
# ---------------------------------------------------------------------------

class TestComputeBalance(unittest.TestCase):
    def test_empty(self):
        result = compute_balance([])
        self.assertEqual(result.window_strokes, 0)
        self.assertEqual(result.balance_score, 0.5)
        self.assertEqual(result.balance_class, "balanced")

    def test_broadening_scenario(self):
        """All unique files → high exploration → broadening."""
        strokes = [_mkstroke([f"file_{i}.py"]) for i in range(20)]
        result = compute_balance(strokes, lookback=50)
        self.assertGreater(result.exploration_ratio, 0.9)
        self.assertIn(result.balance_class, ["broadening", "balanced-high"])

    def test_deepening_scenario(self):
        """Same file over and over → high exploitation → deepening."""
        strokes = [_mkstroke(["core.py"]) for _ in range(20)]
        result = compute_balance(strokes, lookback=50)
        self.assertLess(result.exploration_ratio, 0.2)
        self.assertEqual(result.balance_class, "deepening")

    def test_balanced_scenario(self):
        """Mix of new and revisited files."""
        strokes = []
        for i in range(20):
            if i % 3 == 0:
                strokes.append(_mkstroke([f"new_{i}.py", "shared.py"]))
            else:
                strokes.append(_mkstroke(["shared.py", f"new_{i}.py"]))
        result = compute_balance(strokes, lookback=50)
        self.assertGreater(result.exploration_ratio, 0.0)
        self.assertLess(result.exploration_ratio, 1.0)

    def test_window_truncation(self):
        """With more strokes than lookback, only the last `lookback` are used."""
        strokes = [_mkstroke(["old.py"])] * 100
        strokes.extend([_mkstroke([f"new_{i}.py"]) for i in range(10)])
        result = compute_balance(strokes, lookback=20)
        self.assertEqual(result.window_strokes, 20)

    def test_result_fields(self):
        strokes = [
            _mkstroke(["a.py"]),
            _mkstroke(["a.py", "b.py"]),
            _mkstroke(["c.py"]),
        ]
        result = compute_balance(strokes, lookback=50)
        self.assertEqual(result.window_strokes, 3)
        self.assertIsInstance(result.exploration_ratio, float)
        self.assertIsInstance(result.exploitation_ratio, float)
        self.assertIsInstance(result.breadth_index, float)
        self.assertIsInstance(result.depth_index, float)
        self.assertIsInstance(result.balance_score, float)
        self.assertIn(result.balance_class, [
            "deepening", "balanced-low", "balanced", "balanced-high", "broadening"
        ])
        self.assertIsInstance(result.file_touch_counts, dict)


# ---------------------------------------------------------------------------
# balance_report tests
# ---------------------------------------------------------------------------

class TestBalanceReport(unittest.TestCase):
    def test_basic_format(self):
        result = BalanceResult(
            window_strokes=10,
            exploration_ratio=0.6,
            exploitation_ratio=0.4,
            novelty_half_life=3.5,
            breadth_index=0.7,
            depth_index=0.15,
            balance_score=0.55,
            balance_class="balanced",
            file_touch_counts={"a.py": 5, "b.py": 3},
        )
        report = balance_report(result)
        self.assertIn("Exploration balance (10 strokes)", report)
        self.assertIn("balanced", report)
        self.assertIn("0.55", report)
        self.assertIn("60.00%", report)
        self.assertIn("3.5", report)
        self.assertIn("a.py", report)

    def test_infinite_half_life(self):
        result = BalanceResult(
            window_strokes=5,
            exploration_ratio=1.0,
            exploitation_ratio=0.0,
            novelty_half_life=float("inf"),
            breadth_index=1.0,
            depth_index=0.2,
            balance_score=0.8,
            balance_class="broadening",
            file_touch_counts={},
        )
        report = balance_report(result)
        self.assertIn("inf (no re-touches)", report)

    def test_empty_counts(self):
        result = BalanceResult(
            window_strokes=0,
            exploration_ratio=0.0,
            exploitation_ratio=0.0,
            novelty_half_life=float("inf"),
            breadth_index=0.0,
            depth_index=0.0,
            balance_score=0.5,
            balance_class="balanced",
            file_touch_counts={},
        )
        report = balance_report(result)
        self.assertNotIn("top files:", report)


# ---------------------------------------------------------------------------
# balance_trend tests
# ---------------------------------------------------------------------------

class TestBalanceTrend(unittest.TestCase):
    def test_increasing(self):
        results = [
            BalanceResult(10, 0.3, 0.7, 5.0, 0.4, 0.3, 0.30, "balanced-low"),
            BalanceResult(10, 0.5, 0.5, 3.0, 0.6, 0.2, 0.50, "balanced"),
            BalanceResult(10, 0.7, 0.3, 2.0, 0.8, 0.1, 0.70, "balanced-high"),
        ]
        trend = balance_trend(results)
        self.assertEqual(trend.direction, "increasing")
        self.assertAlmostEqual(trend.score_delta, 0.40, places=4)

    def test_decreasing(self):
        results = [
            BalanceResult(10, 0.7, 0.3, 2.0, 0.8, 0.1, 0.70, "balanced-high"),
            BalanceResult(10, 0.5, 0.5, 3.0, 0.6, 0.2, 0.50, "balanced"),
            BalanceResult(10, 0.3, 0.7, 5.0, 0.4, 0.3, 0.30, "balanced-low"),
        ]
        trend = balance_trend(results)
        self.assertEqual(trend.direction, "decreasing")
        self.assertAlmostEqual(trend.score_delta, -0.40, places=4)

    def test_stable(self):
        results = [
            BalanceResult(10, 0.5, 0.5, 3.0, 0.6, 0.2, 0.50, "balanced"),
            BalanceResult(10, 0.5, 0.5, 3.0, 0.6, 0.2, 0.52, "balanced"),
        ]
        trend = balance_trend(results)
        self.assertEqual(trend.direction, "stable")
        self.assertAlmostEqual(trend.score_delta, 0.02, places=4)

    def test_single(self):
        results = [
            BalanceResult(10, 0.5, 0.5, 3.0, 0.6, 0.2, 0.50, "balanced"),
        ]
        trend = balance_trend(results)
        self.assertEqual(trend.direction, "stable")

    def test_empty(self):
        trend = balance_trend([])
        self.assertEqual(trend.direction, "stable")
        self.assertEqual(trend.sample_count, 0)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):
    def test_full_pipeline_broadening(self):
        """Simulate a writer that always touches new files."""
        strokes = [
            _mkstroke([f"mod_{i}.py", f"tests/test_{i}.py"],
                      message=f"add module {i}", offset_minutes=i)
            for i in range(30)
        ]
        result = compute_balance(strokes, lookback=50)
        self.assertEqual(result.exploration_ratio, 1.0)
        self.assertEqual(result.breadth_index, 1.0)
        self.assertGreater(result.balance_score, 0.7)

    def test_full_pipeline_deepening(self):
        """Simulate a writer that always re-touches the same files."""
        core_files = ["core.py", "tests/test_core.py", "docs/API.md"]
        strokes = [
            _mkstroke(core_files, message=f"refine core #{i}", offset_minutes=i)
            for i in range(30)
        ]
        result = compute_balance(strokes, lookback=50)
        # First stroke is explore (3 files), rest are exploit (87 files)
        self.assertLess(result.exploration_ratio, 0.05)
        self.assertAlmostEqual(result.depth_index, 1.0 / 3, places=2)

    def test_trend_from_windows(self):
        """Multiple windows show a shift from broadening to deepening."""
        # Phase 1: broadening — all new files
        phase1 = [_mkstroke([f"new_{i}.py"]) for i in range(20)]
        r1 = compute_balance(phase1, lookback=50)

        # Phase 2: deepening — same files repeatedly
        phase2 = [_mkstroke(["core.py"]) for _ in range(20)]
        r2 = compute_balance(phase1 + phase2, lookback=50)

        trend = balance_trend([r1, r2])
        self.assertEqual(trend.direction, "decreasing")


if __name__ == "__main__":
    unittest.main()
