#!/usr/bin/env python3
"""Tests for content_loop_detector — 34 test cases."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.content_loop_detector import (  # noqa: E402
    LoopReport,
    detect_loop,
    extract_file_labels,
    extract_kind_labels,
    extract_text_prefix_labels,
    load_strokes,
    _score_period,
)


class TestScorePeriod(unittest.TestCase):
    """Low-level period scoring."""

    def test_perfect_period_2(self):
        labels = ["a", "b"] * 10
        match, n, offset = _score_period(labels, 2)
        self.assertEqual(match, 20)
        self.assertEqual(n, 20)

    def test_perfect_period_3(self):
        labels = ["x", "y", "z"] * 8
        match, n, offset = _score_period(labels, 3)
        self.assertEqual(match, 24)

    def test_wrong_period_scores_lower(self):
        labels = ["a", "b", "c"] * 10
        match_2, _, _ = _score_period(labels, 2)
        match_3, _, _ = _score_period(labels, 3)
        self.assertGreater(match_3, match_2)

    def test_too_short_sequence(self):
        match, n, _ = _score_period(["a", "b"], 2)
        # n < period * 2 → returns 0
        self.assertEqual(match, 0)

    def test_single_element_period_rejected(self):
        match, _, _ = _score_period(["a"] * 10, 1)
        self.assertEqual(match, 0)

    def test_offset_alignment(self):
        # Offset sequence: garbage then clean cycle
        labels = ["x", "x", "a", "b", "a", "b", "a", "b"]
        match, n, offset = _score_period(labels, 2)
        # Best cycle should be ["a", "b"] from offset 2
        self.assertIn(offset, [2, 3])


class TestDetectLoopBasic(unittest.TestCase):
    """Core detect_loop functionality."""

    def test_no_loop_in_short_sequence(self):
        report = detect_loop(["a", "b", "c"])
        self.assertFalse(report.has_loop)
        self.assertEqual(report.total_labels, 3)

    def test_no_loop_in_random_data(self):
        import random
        random.seed(42)
        labels = [random.choice("abcdefgh") for _ in range(50)]
        report = detect_loop(labels, min_confidence=0.8)
        self.assertFalse(report.has_loop)

    def test_perfect_binary_cycle(self):
        labels = ["on", "off"] * 25
        report = detect_loop(labels)
        self.assertTrue(report.has_loop)
        self.assertEqual(report.period, 2)
        self.assertAlmostEqual(report.confidence, 1.0)
        self.assertEqual(report.severity, "SEVERE")

    def test_perfect_six_cycle(self):
        kinds = ["thought", "devlog", "garden", "note", "metrics", "snippet"]
        labels = kinds * 20
        report = detect_loop(labels)
        self.assertTrue(report.has_loop)
        self.assertEqual(report.period, 6)
        self.assertAlmostEqual(report.confidence, 1.0)
        self.assertEqual(len(report.cycle), 6)

    def test_noisy_cycle_still_detected(self):
        base = ["a", "b", "c"] * 20
        # Introduce ~5% noise at known positions, using values not in cycle
        noisy = list(base)
        for idx in [5, 17, 29, 41, 53]:
            noisy[idx] = "z"
        report = detect_loop(noisy, min_confidence=0.8)
        self.assertTrue(report.has_loop)
        # detected period should be 3 or a harmonic (6, 9, 12…)
        self.assertEqual(report.period % 3, 0)
        self.assertGreaterEqual(report.confidence, 0.9)

    def test_empty_sequence(self):
        report = detect_loop([])
        self.assertFalse(report.has_loop)
        self.assertEqual(report.total_labels, 0)

    def test_single_label(self):
        report = detect_loop(["only"])
        self.assertFalse(report.has_loop)

    def test_two_identical_labels(self):
        report = detect_loop(["a", "a"])
        self.assertFalse(report.has_loop)  # too short for period >= 2


class TestDetectLoopAdvanced(unittest.TestCase):
    """Advanced scenarios."""

    def test_min_confidence_threshold(self):
        labels = ["a", "b", "a", "b", "x", "x", "a", "b"]
        report_high = detect_loop(labels, min_confidence=0.95)
        report_low = detect_loop(labels, min_confidence=0.5)
        # High threshold might not detect, low should
        self.assertFalse(report_high.has_loop)

    def test_max_period_cap(self):
        # Period-6 cycle where period-3 sub-pattern is detectable
        labels = ["a", "b", "c", "a", "b", "c"] * 10
        report = detect_loop(labels, max_period=3)
        self.assertTrue(report.has_loop)
        self.assertLessEqual(report.period, 3)
        self.assertEqual(report.period, 3)

    def test_explained_count_accuracy(self):
        labels = ["a", "b"] * 10
        report = detect_loop(labels)
        self.assertEqual(report.explained, 20)

    def test_cycle_body_content(self):
        labels = ["x", "y", "z"] * 15
        report = detect_loop(labels)
        self.assertEqual(set(report.cycle), {"x", "y", "z"})
        self.assertEqual(report.period, 3)

    def test_long_cycle(self):
        cycle = list("abcdefghijklmnop")  # period 16
        labels = cycle * 8
        report = detect_loop(labels)
        self.assertTrue(report.has_loop)
        self.assertEqual(report.period, 16)

    def test_partial_sequence(self):
        """Cycle that doesn't divide evenly into sequence length."""
        labels = ["a", "b", "c"] * 7 + ["a", "b"]
        report = detect_loop(labels)
        self.assertTrue(report.has_loop)
        self.assertEqual(report.period, 3)


class TestLoopReport(unittest.TestCase):
    """LoopReport dataclass behaviour."""

    def test_frozen(self):
        report = LoopReport(
            has_loop=True, period=3, confidence=0.9,
            cycle=("a", "b", "c"), total_labels=30, explained=27,
        )
        with self.assertRaises(AttributeError):
            report.period = 5  # type: ignore

    def test_severity_none(self):
        r = LoopReport(False, 0, 0.3, (), 10, 3)
        self.assertEqual(r.severity, "NONE")

    def test_severity_mild(self):
        r = LoopReport(True, 2, 0.7, ("a", "b"), 10, 7)
        self.assertEqual(r.severity, "MILD")

    def test_severity_moderate(self):
        r = LoopReport(True, 3, 0.85, ("a", "b", "c"), 30, 25)
        self.assertEqual(r.severity, "MODERATE")

    def test_severity_severe(self):
        r = LoopReport(True, 2, 0.98, ("a", "b"), 100, 98)
        self.assertEqual(r.severity, "SEVERE")

    def test_summary_no_loop(self):
        r = LoopReport(False, 0, 0.0, (), 50, 0)
        self.assertIn("no loop", r.summary())

    def test_summary_with_loop(self):
        r = LoopReport(True, 3, 0.95, ("x", "y", "z"), 30, 28)
        s = r.summary()
        self.assertIn("period=3", s)
        self.assertIn("SEVERE", s)


class TestLabelExtractors(unittest.TestCase):
    """Label extraction from stroke dicts."""

    def test_kind_labels(self):
        strokes = [
            {"kind": "thought", "text": "hello"},
            {"kind": "devlog", "text": "world"},
            {"kind": "garden", "text": "foo"},
        ]
        self.assertEqual(extract_kind_labels(strokes), ["thought", "devlog", "garden"])

    def test_file_labels(self):
        strokes = [
            {"path": "data/strokes.jsonl"},
            {"path": "docs/DEVLOG.md"},
        ]
        self.assertEqual(extract_file_labels(strokes), ["data/strokes.jsonl", "docs/DEVLOG.md"])

    def test_text_prefix_labels(self):
        strokes = [
            {"text": "automation is a fire hose -- measured now: 123"},
            {"text": "short text"},
        ]
        labels = extract_text_prefix_labels(strokes, max_len=20)
        self.assertEqual(labels[0], "automation is a fire")
        self.assertEqual(labels[1], "short text")

    def test_missing_fields(self):
        strokes = [{}, {"kind": "note"}]
        kinds = extract_kind_labels(strokes)
        self.assertEqual(kinds, ["unknown", "note"])


class TestLoadStrokes(unittest.TestCase):
    """File loading edge cases."""

    def test_load_from_tempfile(self):
        data = [
            {"seq": 1, "kind": "thought", "text": "a"},
            {"seq": 2, "kind": "devlog", "text": "b"},
            {"seq": 3, "kind": "garden", "text": "c"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for d in data:
                f.write(json.dumps(d) + "\n")
            tmp = f.name
        try:
            loaded = load_strokes(tmp)
            self.assertEqual(len(loaded), 3)
            self.assertEqual(loaded[0]["seq"], 1)
        finally:
            os.unlink(tmp)

    def test_load_tail(self):
        data = [{"seq": i} for i in range(20)]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for d in data:
                f.write(json.dumps(d) + "\n")
            tmp = f.name
        try:
            loaded = load_strokes(tmp, tail=5)
            self.assertEqual(len(loaded), 5)
            self.assertEqual(loaded[0]["seq"], 15)
        finally:
            os.unlink(tmp)

    def test_load_nonexistent(self):
        loaded = load_strokes("/tmp/nonexistent_strokes_12345.jsonl")
        self.assertEqual(loaded, [])

    def test_load_skips_bad_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"seq": 1}\n')
            f.write('NOT JSON\n')
            f.write('{"seq": 3}\n')
            tmp = f.name
        try:
            loaded = load_strokes(tmp)
            self.assertEqual(len(loaded), 2)
        finally:
            os.unlink(tmp)


class TestIntegration(unittest.TestCase):
    """End-to-end with realistic data."""

    def test_iamai_writer_pattern(self):
        """Simulate the exact pattern from this repo's writer state."""
        kinds = ["thought", "devlog", "garden", "note", "metrics", "snippet"]
        labels = kinds * 50  # 300 strokes
        report = detect_loop(labels)
        self.assertTrue(report.has_loop)
        self.assertEqual(report.period, 6)
        self.assertAlmostEqual(report.confidence, 1.0)
        self.assertEqual(report.severity, "SEVERE")

    def test_realistic_with_noise(self):
        """Real writer data with occasional gaps and kind variations."""
        import random
        random.seed(7)
        kinds = ["thought", "devlog", "garden", "note", "metrics", "snippet"]
        labels = []
        for _ in range(200):
            if random.random() < 0.05:  # 5% chance of random kind
                labels.append(random.choice(["thought", "note", "devlog"]))
            else:
                labels.append(kinds[len(labels) % 6])
        report = detect_loop(labels, min_confidence=0.8)
        self.assertTrue(report.has_loop)
        self.assertEqual(report.period, 6)


if __name__ == "__main__":
    unittest.main()
