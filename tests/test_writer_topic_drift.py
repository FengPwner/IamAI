#!/usr/bin/env python3
"""Tests for writer_topic_drift — topic focus and drift analysis.

58 tests covering:
- StrokeRecord construction and topic extraction
- StrokeRecord.dominant_topic (single area, multi-area, empty, tie-break)
- _classify_file (matching prefixes, longest match, no match → other)
- _shannon_entropy (single topic, uniform, empty, two topics)
- _jaccard (identical, disjoint, partial, empty)
- topic_entropy (single-area strokes, multi-area, empty)
- concentration_index (all same area, spread, empty)
- transition_rate (all same, all different, alternating, single, empty)
- topic_stability (stable areas, changing areas, not enough data, empty)
- classify_focus (all five classes + boundary values)
- compute_drift (composite scoring, empty input, focused vs scattered)
- drift_report formatting
- drift_trend (increasing, decreasing, stable, single, empty)
- full pipeline integration
"""

import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, ".")
from iamai.writer_topic_drift import (
    DriftResult,
    DriftTrend,
    StrokeRecord,
    _classify_file,
    _jaccard,
    _shannon_entropy,
    classify_focus,
    compute_drift,
    concentration_index,
    drift_report,
    drift_trend,
    topic_entropy,
    topic_stability,
    transition_rate,
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


def _mkstroke_seq(n, files_per_stroke, topic_cycle=None):
    """Create n strokes cycling through file sets.

    If topic_cycle is given, strokes cycle through the provided list of
    file-lists; otherwise each stroke gets files_per_stroke.
    """
    strokes = []
    for i in range(n):
        if topic_cycle:
            files = topic_cycle[i % len(topic_cycle)]
        else:
            files = files_per_stroke
        strokes.append(_mkstroke(files, offset_minutes=i))
    return strokes


# ---------------------------------------------------------------------------
# StrokeRecord tests
# ---------------------------------------------------------------------------

class TestStrokeRecord(unittest.TestCase):
    """Tests for StrokeRecord dataclass."""

    def test_topics_single_area(self):
        s = _mkstroke(["iamai/caretaker_log.py", "iamai/caretaker_briefing.py"])
        self.assertEqual(s.topics(), {"caretaker"})

    def test_topics_multi_area(self):
        s = _mkstroke(["iamai/cadence_jitter.py", "tests/test_cadence_jitter.py"])
        self.assertEqual(s.topics(), {"cadence", "testing"})

    def test_topics_empty(self):
        s = _mkstroke([])
        self.assertEqual(s.topics(), set())

    def test_dominant_topic_single(self):
        s = _mkstroke(["iamai/writer_heartbeat.py"])
        self.assertEqual(s.dominant_topic(), "writer-self")

    def test_dominant_topic_multi_picks_majority(self):
        s = _mkstroke([
            "iamai/cadence_drift.py",
            "iamai/cadence_jitter.py",
            "tests/test_cadence_drift.py",
        ])
        # cadence: 2, testing: 1
        self.assertEqual(s.dominant_topic(), "cadence")

    def test_dominant_topic_empty(self):
        s = _mkstroke([])
        self.assertEqual(s.dominant_topic(), "other")

    def test_custom_prefix_map(self):
        custom = {"src/models/": "models", "src/": "code", "tests/": "tests"}
        s = StrokeRecord(
            timestamp=_BASE,
            files=["src/models/resnet.py", "src/utils.py", "tests/test_resnet.py"],
        )
        topics = s.topics(prefix_map=custom)
        self.assertIn("models", topics)  # longest match
        self.assertIn("code", topics)
        self.assertIn("tests", topics)


# ---------------------------------------------------------------------------
# _classify_file tests
# ---------------------------------------------------------------------------

class TestClassifyFile(unittest.TestCase):
    """Tests for the _classify_file helper."""

    def test_caretaker_prefix(self):
        self.assertEqual(_classify_file("iamai/caretaker_log.py"), "caretaker")

    def test_cadence_prefix(self):
        self.assertEqual(_classify_file("iamai/cadence_drift.py"), "cadence")

    def test_writer_prefix(self):
        self.assertEqual(_classify_file("iamai/writer_heartbeat.py"), "writer-self")

    def test_batch_prefix(self):
        self.assertEqual(_classify_file("iamai/batch_effectiveness.py"), "batch")

    def test_commit_analysis_prefix(self):
        self.assertEqual(_classify_file("iamai/commit_echo.py"), "commit-analysis")

    def test_tests_prefix(self):
        self.assertEqual(_classify_file("tests/test_batch.py"), "testing")

    def test_docs_prefix(self):
        self.assertEqual(_classify_file("docs/DEVLOG.md"), "documentation")

    def test_notes_prefix(self):
        self.assertEqual(_classify_file("notes/cadence.md"), "reflection")

    def test_tools_prefix(self):
        self.assertEqual(_classify_file("tools/run_both.sh"), "tooling")

    def test_no_match_is_other(self):
        self.assertEqual(_classify_file("README.md"), "other")

    def test_longest_match_wins(self):
        custom = {"iamai/caretaker_": "caretaker-sub", "iamai/": "iamai-general"}
        self.assertEqual(_classify_file("iamai/caretaker_log.py", custom), "caretaker-sub")

    def test_shorter_prefix_fallback(self):
        custom = {"iamai/caretaker_": "caretaker-sub", "iamai/": "iamai-general"}
        self.assertEqual(_classify_file("iamai/batch.py", custom), "iamai-general")


# ---------------------------------------------------------------------------
# _shannon_entropy tests
# ---------------------------------------------------------------------------

class TestShannonEntropy(unittest.TestCase):
    """Tests for the Shannon entropy helper."""

    def test_single_topic(self):
        from collections import Counter
        self.assertAlmostEqual(_shannon_entropy(Counter({"a": 10})), 0.0)

    def test_uniform_two(self):
        from collections import Counter
        # Two topics equally split → 1.0 bit
        self.assertAlmostEqual(_shannon_entropy(Counter({"a": 5, "b": 5})), 1.0)

    def test_uniform_four(self):
        from collections import Counter
        # Four topics equally split → 2.0 bits
        c = Counter({"a": 5, "b": 5, "c": 5, "d": 5})
        self.assertAlmostEqual(_shannon_entropy(c), 2.0)

    def test_empty(self):
        from collections import Counter
        self.assertEqual(_shannon_entropy(Counter()), 0.0)

    def test_skewed(self):
        from collections import Counter
        # Heavily skewed → low entropy
        c = Counter({"a": 100, "b": 1})
        entropy = _shannon_entropy(c)
        self.assertLess(entropy, 0.1)


# ---------------------------------------------------------------------------
# _jaccard tests
# ---------------------------------------------------------------------------

class TestJaccard(unittest.TestCase):
    """Tests for the Jaccard similarity helper."""

    def test_identical(self):
        self.assertEqual(_jaccard({"a", "b"}, {"a", "b"}), 1.0)

    def test_disjoint(self):
        self.assertEqual(_jaccard({"a", "b"}, {"c", "d"}), 0.0)

    def test_partial(self):
        self.assertAlmostEqual(_jaccard({"a", "b", "c"}, {"b", "c", "d"}), 0.5)

    def test_both_empty(self):
        self.assertEqual(_jaccard(set(), set()), 1.0)

    def test_one_empty(self):
        self.assertEqual(_jaccard({"a"}, set()), 0.0)

    def test_subset(self):
        self.assertAlmostEqual(_jaccard({"a", "b"}, {"a", "b", "c"}), 2 / 3)


# ---------------------------------------------------------------------------
# topic_entropy tests
# ---------------------------------------------------------------------------

class TestTopicEntropy(unittest.TestCase):
    """Tests for the topic_entropy metric."""

    def test_single_area(self):
        strokes = [_mkstroke(["iamai/caretaker_log.py"]) for _ in range(10)]
        ent, dist = topic_entropy(strokes)
        self.assertAlmostEqual(ent, 0.0)
        self.assertEqual(len(dist), 1)
        self.assertIn("caretaker", dist)

    def test_two_areas_balanced(self):
        strokes = []
        for i in range(10):
            if i < 5:
                strokes.append(_mkstroke(["iamai/caretaker_log.py"]))
            else:
                strokes.append(_mkstroke(["tests/test_batch.py"]))
        ent, dist = topic_entropy(strokes)
        self.assertAlmostEqual(ent, 1.0)
        self.assertEqual(len(dist), 2)

    def test_empty_strokes(self):
        ent, dist = topic_entropy([])
        self.assertEqual(ent, 0.0)
        self.assertEqual(dist, {})

    def test_empty_files(self):
        strokes = [_mkstroke([]) for _ in range(5)]
        ent, dist = topic_entropy(strokes)
        self.assertEqual(ent, 0.0)


# ---------------------------------------------------------------------------
# concentration_index tests
# ---------------------------------------------------------------------------

class TestConcentrationIndex(unittest.TestCase):
    """Tests for the concentration_index metric."""

    def test_all_same_area(self):
        strokes = [_mkstroke(["iamai/cadet.py"]) for _ in range(10)]
        # All "other" since cadet doesn't match any prefix
        ci = concentration_index(strokes)
        self.assertAlmostEqual(ci, 1.0)

    def test_perfectly_spread(self):
        strokes = [
            _mkstroke(["iamai/caretaker_log.py"]),
            _mkstroke(["tests/test_batch.py"]),
            _mkstroke(["docs/DEVLOG.md"]),
            _mkstroke(["notes/cadence.md"]),
        ]
        ci = concentration_index(strokes)
        self.assertAlmostEqual(ci, 0.25)

    def test_empty(self):
        ci = concentration_index([])
        self.assertEqual(ci, 0.0)


# ---------------------------------------------------------------------------
# transition_rate tests
# ---------------------------------------------------------------------------

class TestTransitionRate(unittest.TestCase):
    """Tests for the transition_rate metric."""

    def test_all_same_topic(self):
        strokes = [_mkstroke(["iamai/caretaker_log.py"]) for _ in range(10)]
        tr = transition_rate(strokes)
        self.assertAlmostEqual(tr, 0.0)

    def test_all_different(self):
        strokes = [
            _mkstroke(["iamai/caretaker_log.py"]),
            _mkstroke(["tests/test_batch.py"]),
            _mkstroke(["docs/DEVLOG.md"]),
            _mkstroke(["notes/cadence.md"]),
            _mkstroke(["iamai/cadence_drift.py"]),
        ]
        tr = transition_rate(strokes)
        self.assertAlmostEqual(tr, 1.0)

    def test_alternating(self):
        strokes = []
        for i in range(10):
            if i % 2 == 0:
                strokes.append(_mkstroke(["iamai/caretaker_log.py"]))
            else:
                strokes.append(_mkstroke(["tests/test_batch.py"]))
        tr = transition_rate(strokes)
        self.assertAlmostEqual(tr, 1.0)

    def test_single_stroke(self):
        tr = transition_rate([_mkstroke(["iamai/caretaker_log.py"])])
        self.assertEqual(tr, 0.0)

    def test_empty(self):
        tr = transition_rate([])
        self.assertEqual(tr, 0.0)

    def test_half_switch(self):
        # 10 strokes, 5 transitions
        strokes = []
        for i in range(10):
            if i < 5:
                strokes.append(_mkstroke(["iamai/caretaker_log.py"]))
            elif i < 7:
                strokes.append(_mkstroke(["tests/test_batch.py"]))
            else:
                strokes.append(_mkstroke(["iamai/caretaker_log.py"]))
        # transitions at indices 5 and 7 → 2 transitions / 9 comparisons
        tr = transition_rate(strokes)
        self.assertAlmostEqual(tr, 2 / 9, places=3)


# ---------------------------------------------------------------------------
# topic_stability tests
# ---------------------------------------------------------------------------

class TestTopicStability(unittest.TestCase):
    """Tests for the topic_stability metric."""

    def test_stable_areas(self):
        files = ["iamai/caretaker_log.py", "tests/test_caretaker.py"]
        strokes = [_mkstroke(files, offset_minutes=i) for i in range(20)]
        stab = topic_stability(strokes, window_size=5)
        self.assertAlmostEqual(stab, 1.0)

    def test_changing_areas(self):
        # Each block of 5 strokes uses a distinct set of areas
        # Block 1: caretaker only, Block 2: testing only,
        # Block 3: docs only, Block 4: notes only
        strokes = []
        blocks = [
            ["iamai/caretaker_log.py"],
            ["tests/test_batch.py"],
            ["docs/DEVLOG.md"],
            ["notes/cadence.md"],
        ]
        for block_idx, files in enumerate(blocks):
            for j in range(5):
                strokes.append(_mkstroke(files, offset_minutes=block_idx * 5 + j))
        stab = topic_stability(strokes, window_size=5)
        # Each window has a single distinct area → no overlap → 0.0
        self.assertAlmostEqual(stab, 0.0)

    def test_not_enough_data(self):
        strokes = [_mkstroke(["iamai/caretaker_log.py"]) for _ in range(3)]
        stab = topic_stability(strokes, window_size=5)
        # Falls back to half-split; all same area → 1.0
        self.assertAlmostEqual(stab, 1.0)

    def test_empty(self):
        stab = topic_stability([], window_size=5)
        self.assertAlmostEqual(stab, 1.0)

    def test_single_stroke(self):
        strokes = [_mkstroke(["iamai/caretaker_log.py"])]
        stab = topic_stability(strokes, window_size=5)
        self.assertAlmostEqual(stab, 1.0)


# ---------------------------------------------------------------------------
# classify_focus tests
# ---------------------------------------------------------------------------

class TestClassifyFocus(unittest.TestCase):
    """Tests for the focus classification."""

    def test_focused(self):
        self.assertEqual(classify_focus(0.0), "focused")
        self.assertEqual(classify_focus(0.10), "focused")
        self.assertEqual(classify_focus(0.24), "focused")

    def test_exploring(self):
        self.assertEqual(classify_focus(0.25), "exploring")
        self.assertEqual(classify_focus(0.35), "exploring")
        self.assertEqual(classify_focus(0.44), "exploring")

    def test_drifting(self):
        self.assertEqual(classify_focus(0.45), "drifting")
        self.assertEqual(classify_focus(0.55), "drifting")
        self.assertEqual(classify_focus(0.64), "drifting")

    def test_scattered(self):
        self.assertEqual(classify_focus(0.65), "scattered")
        self.assertEqual(classify_focus(0.75), "scattered")
        self.assertEqual(classify_focus(0.84), "scattered")

    def test_oscillating(self):
        self.assertEqual(classify_focus(0.85), "oscillating")
        self.assertEqual(classify_focus(0.95), "oscillating")
        self.assertEqual(classify_focus(1.0), "oscillating")

    def test_boundary_values(self):
        # Exact boundaries
        self.assertEqual(classify_focus(0.25), "exploring")
        self.assertEqual(classify_focus(0.45), "drifting")
        self.assertEqual(classify_focus(0.65), "scattered")
        self.assertEqual(classify_focus(0.85), "oscillating")


# ---------------------------------------------------------------------------
# compute_drift tests
# ---------------------------------------------------------------------------

class TestComputeDrift(unittest.TestCase):
    """Tests for the composite drift computation."""

    def test_empty_input(self):
        result = compute_drift([])
        self.assertEqual(result.window_strokes, 0)
        self.assertEqual(result.drift_score, 0.0)
        self.assertEqual(result.focus_class, "focused")

    def test_focused_work(self):
        # All strokes touch caretaker files
        strokes = [_mkstroke(
            ["iamai/caretaker_log.py", "iamai/caretaker_briefing.py"],
            offset_minutes=i,
        ) for i in range(50)]
        result = compute_drift(strokes)
        self.assertEqual(result.focus_class, "focused")
        self.assertLess(result.drift_score, 0.25)
        self.assertAlmostEqual(result.topic_entropy, 0.0)
        self.assertAlmostEqual(result.concentration_index, 1.0)
        self.assertAlmostEqual(result.transition_rate, 0.0)

    def test_scattered_work(self):
        # Every stroke touches a completely different area
        areas = [
            ["iamai/caretaker_log.py"],
            ["tests/test_batch.py"],
            ["docs/DEVLOG.md"],
            ["notes/cadence.md"],
            ["iamai/cadence_drift.py"],
            ["tools/run_both.sh"],
            ["iamai/writer_heartbeat.py"],
            ["iamai/batch_effectiveness.py"],
        ]
        strokes = [_mkstroke(areas[i % len(areas)], offset_minutes=i) for i in range(80)]
        result = compute_drift(strokes)
        self.assertIn(result.focus_class, ("scattered", "oscillating", "drifting"))
        self.assertGreater(result.drift_score, 0.40)
        self.assertGreater(result.topic_entropy, 1.5)

    def test_exploring_work(self):
        # Two related areas, alternating
        strokes = []
        for i in range(50):
            if i % 2 == 0:
                strokes.append(_mkstroke(["iamai/cadence_drift.py"]))
            else:
                strokes.append(_mkstroke(["tests/test_cadence_drift.py"]))
        result = compute_drift(strokes)
        # Should be exploring: moderate entropy, high transitions, 2 areas
        self.assertIn(result.focus_class, ("exploring", "drifting"))

    def test_window_size_truncation(self):
        # 100 strokes but window_size=20 → only last 20 used
        strokes = [_mkstroke(["iamai/caretaker_log.py"], offset_minutes=i) for i in range(100)]
        result = compute_drift(strokes, window_size=20)
        self.assertEqual(result.window_strokes, 20)

    def test_area_distribution_populated(self):
        strokes = [_mkstroke(["iamai/caretaker_log.py"]) for _ in range(10)]
        result = compute_drift(strokes)
        self.assertIn("caretaker", result.area_distribution)


# ---------------------------------------------------------------------------
# drift_report tests
# ---------------------------------------------------------------------------

class TestDriftReport(unittest.TestCase):
    """Tests for the drift report formatter."""

    def test_basic_report(self):
        result = DriftResult(
            window_strokes=50,
            topic_entropy=1.5,
            concentration_index=0.45,
            transition_rate=0.30,
            topic_stability=0.65,
            drift_score=0.35,
            focus_class="exploring",
            area_distribution={"caretaker": 0.45, "testing": 0.35, "documentation": 0.20},
        )
        report = drift_report(result)
        self.assertIn("exploring", report)
        self.assertIn("50 strokes", report)
        self.assertIn("caretaker", report)
        self.assertIn("testing", report)

    def test_empty_distribution(self):
        result = DriftResult(
            window_strokes=0,
            topic_entropy=0.0,
            concentration_index=0.0,
            transition_rate=0.0,
            topic_stability=1.0,
            drift_score=0.0,
            focus_class="focused",
        )
        report = drift_report(result)
        self.assertIn("focused", report)
        self.assertNotIn("area distribution:", report)


# ---------------------------------------------------------------------------
# drift_trend tests
# ---------------------------------------------------------------------------

class TestDriftTrend(unittest.TestCase):
    """Tests for the drift trend analysis."""

    def _mkresult(self, score):
        return DriftResult(
            window_strokes=50,
            topic_entropy=1.0,
            concentration_index=0.5,
            transition_rate=0.3,
            topic_stability=0.7,
            drift_score=score,
            focus_class=classify_focus(score),
        )

    def test_increasing(self):
        results = [self._mkresult(0.2), self._mkresult(0.3), self._mkresult(0.5)]
        trend = drift_trend(results)
        self.assertEqual(trend.direction, "increasing")
        self.assertAlmostEqual(trend.score_delta, 0.3)

    def test_decreasing(self):
        results = [self._mkresult(0.7), self._mkresult(0.5), self._mkresult(0.3)]
        trend = drift_trend(results)
        self.assertEqual(trend.direction, "decreasing")
        self.assertAlmostEqual(trend.score_delta, -0.4)

    def test_stable(self):
        results = [self._mkresult(0.4), self._mkresult(0.42), self._mkresult(0.44)]
        trend = drift_trend(results)
        self.assertEqual(trend.direction, "stable")

    def test_single(self):
        trend = drift_trend([self._mkresult(0.5)])
        self.assertEqual(trend.direction, "stable")
        self.assertEqual(trend.sample_count, 1)

    def test_empty(self):
        trend = drift_trend([])
        self.assertEqual(trend.direction, "stable")
        self.assertEqual(trend.sample_count, 0)
        self.assertEqual(trend.score_delta, 0.0)


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):
    """End-to-end pipeline test."""

    def test_full_pipeline(self):
        """Simulate a realistic writing session and verify drift output."""
        strokes = []
        # Phase 1: focused on caretaker (20 strokes)
        for i in range(20):
            strokes.append(_mkstroke(
                ["iamai/caretaker_log.py", "iamai/caretaker_briefing.py",
                 "tests/test_caretaker_log.py"],
                offset_minutes=i,
            ))
        # Phase 2: shift to cadence (20 strokes)
        for i in range(20, 40):
            strokes.append(_mkstroke(
                ["iamai/cadence_drift.py", "iamai/cadence_jitter.py",
                 "tests/test_cadence_drift.py"],
                offset_minutes=i,
            ))
        # Phase 3: exploring docs + notes (10 strokes)
        for i in range(40, 50):
            if i % 2 == 0:
                strokes.append(_mkstroke(["docs/DEVLOG.md", "docs/GARDEN.md"], offset_minutes=i))
            else:
                strokes.append(_mkstroke(["notes/cadence.md", "notes/reading.md"], offset_minutes=i))

        result = compute_drift(strokes)
        self.assertEqual(result.window_strokes, 50)
        self.assertGreater(result.topic_entropy, 0.5)  # Multiple areas
        self.assertIn(result.focus_class, (
            "focused", "exploring", "drifting", "scattered", "oscillating"
        ))

        # Report should be non-empty
        report = drift_report(result)
        self.assertIn("drift score:", report)
        self.assertIn("topic entropy:", report)

        # Trend from first half (focused) vs second half (mixed)
        r1 = compute_drift(strokes[:25])
        r2 = compute_drift(strokes[25:])
        trend = drift_trend([r1, r2])
        self.assertEqual(trend.sample_count, 2)
        # Second window should have higher drift (more diverse)
        self.assertGreater(r2.drift_score, r1.drift_score)


if __name__ == "__main__":
    unittest.main()
