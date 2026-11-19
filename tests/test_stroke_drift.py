"""Tests for iamai/stroke_drift.py — topic drift tracker.

Covers: extract_concepts, jaccard_distance, step_drift, window_drift,
drift_velocity, cumulative_drift, _classify_drift_pattern,
drift_health, drift_report, drift_delta, edge cases.

Pure Python, no numpy/scipy.  Written by Qwen during caretaker visit 739,
2026-11-20.
"""

from __future__ import annotations

import pytest

from iamai.stroke_drift import (
    _classify_drift_pattern,
    cumulative_drift,
    drift_delta,
    drift_health,
    drift_report,
    drift_velocity,
    extract_concepts,
    jaccard_distance,
    step_drift,
    window_drift,
)


# ── helpers ──────────────────────────────────────────────────────────────

def _texts(lines):
    return list(lines)


# ── extract_concepts ─────────────────────────────────────────────────────

class TestExtractConcepts:
    def test_basic_extraction(self):
        result = extract_concepts("machine learning algorithms process data")
        assert result == {"machine", "learning", "algorithms", "process", "data"}

    def test_filters_short_words(self):
        result = extract_concepts("the cat sat on a mat")
        assert result == set()

    def test_filters_stopwords(self):
        result = extract_concepts("this would have been very known")
        assert result == set()

    def test_empty_input(self):
        assert extract_concepts("") == set()

    def test_mixed_case(self):
        result = extract_concepts("Machine Learning MACHINE")
        assert result == {"machine", "learning"}

    def test_punctuation_handling(self):
        result = extract_concepts("hello-world, testing! another-thing.")
        assert "hello-world" in result or "hello" not in result  # hyphenated ok
        assert "testing" in result
        assert "another-thing" in result or "another" not in result


# ── jaccard_distance ─────────────────────────────────────────────────────

class TestJaccardDistance:
    def test_identical_sets(self):
        assert jaccard_distance({"a", "b", "c"}, {"a", "b", "c"}) == 0.0

    def test_disjoint_sets(self):
        assert jaccard_distance({"a", "b"}, {"c", "d"}) == 1.0

    def test_partial_overlap(self):
        # intersection=1, union=3 → 1 - 1/3 = 2/3
        result = jaccard_distance({"a", "b"}, {"b", "c"})
        assert abs(result - 2 / 3) < 1e-9

    def test_both_empty(self):
        assert jaccard_distance(set(), set()) == 0.0

    def test_one_empty(self):
        assert jaccard_distance({"a"}, set()) == 1.0

    def test_subset(self):
        result = jaccard_distance({"a", "b", "c"}, {"a"})
        # |intersection|=1, |union|=3 → 1 - 1/3 = 2/3
        assert abs(result - 2 / 3) < 1e-9


# ── step_drift ───────────────────────────────────────────────────────────

class TestStepDrift:
    def test_basic(self):
        sets = [{"a", "b"}, {"b", "c"}, {"c", "d"}]
        result = step_drift(sets)
        assert len(result) == 2
        # Each pair: intersection=1, union=3 → distance=2/3
        assert abs(result[0] - 2 / 3) < 1e-9
        assert abs(result[1] - 2 / 3) < 1e-9

    def test_single_set(self):
        assert step_drift([{"a"}]) == []

    def test_empty(self):
        assert step_drift([]) == []

    def test_identical_consecutive(self):
        sets = [{"a", "b"}, {"a", "b"}]
        result = step_drift(sets)
        assert result == [0.0]

    def test_complete_shift(self):
        sets = [{"a", "b"}, {"c", "d"}]
        result = step_drift(sets)
        assert result == [1.0]


# ── window_drift ─────────────────────────────────────────────────────────

class TestWindowDrift:
    def test_basic_window(self):
        sets = [{"a", "b"}, {"b", "c"}, {"c", "d"}, {"d", "e"}, {"e", "f"}]
        result = window_drift(sets, window=3)
        assert len(result) == 3

    def test_window_equals_length(self):
        sets = [{"a"}, {"b"}, {"c"}]
        result = window_drift(sets, window=3)
        assert len(result) == 1

    def test_window_too_small(self):
        sets = [{"a"}, {"b"}, {"c"}]
        result = window_drift(sets, window=1)
        # window clamped to 2
        assert len(result) == 2

    def test_small_window(self):
        sets = [{"a", "b"}, {"c", "d"}]
        result = window_drift(sets, window=2)
        assert result == [1.0]


# ── drift_velocity ──────────────────────────────────────────────────────

class TestDriftVelocity:
    def test_basic(self):
        result = drift_velocity([0.2, 0.4, 0.3, 0.6])
        assert result == [0.2, -0.1, 0.3]

    def test_single(self):
        assert drift_velocity([0.5]) == []

    def test_empty(self):
        assert drift_velocity([]) == []

    def test_constant(self):
        result = drift_velocity([0.3, 0.3, 0.3])
        assert result == [0.0, 0.0]


# ── cumulative_drift ────────────────────────────────────────────────────

class TestCumulativeDrift:
    def test_basic(self):
        assert cumulative_drift([0.5, 0.5, 0.5]) == 0.5

    def test_empty(self):
        assert cumulative_drift([]) == 0.0

    def test_clamped_to_one(self):
        # Even though individual values are ≤ 1, test clamping
        assert cumulative_drift([1.0, 1.0]) == 1.0

    def test_zero_drift(self):
        assert cumulative_drift([0.0, 0.0, 0.0]) == 0.0


# ── _classify_drift_pattern ─────────────────────────────────────────────

class TestClassifyDriftPattern:
    def test_stable(self):
        steps = [0.05, 0.1, 0.08, 0.05]
        vels = drift_velocity(steps)
        result = _classify_drift_pattern(steps, 0.07, vels)
        assert result == "stable"

    def test_gradual(self):
        steps = [0.3, 0.35, 0.4, 0.35, 0.4]
        vels = drift_velocity(steps)
        result = _classify_drift_pattern(steps, 0.36, vels)
        assert result == "gradual"

    def test_pivoting(self):
        steps = [0.2, 0.1, 0.9, 0.2, 0.1]
        vels = drift_velocity(steps)
        result = _classify_drift_pattern(steps, 0.28, vels)
        assert result == "pivoting"

    def test_oscillating(self):
        steps = [0.3, 0.6, 0.2, 0.7, 0.3, 0.6]
        vels = drift_velocity(steps)
        result = _classify_drift_pattern(steps, 0.45, vels)
        assert result in ("oscillating", "wandering")

    def test_empty(self):
        result = _classify_drift_pattern([], 0.0, [])
        assert result == "stable"


# ── drift_health ────────────────────────────────────────────────────────

class TestDriftHealth:
    def test_focused(self):
        assert drift_health("stable", 0.1) == "focused"

    def test_evolving(self):
        assert drift_health("gradual", 0.5) == "evolving"

    def test_scattered(self):
        assert drift_health("wandering", 0.7) == "scattered"

    def test_mixed(self):
        assert drift_health("oscillating", 0.4) == "mixed"

    def test_pivoting_scattered(self):
        assert drift_health("pivoting", 0.6) == "scattered"

    def test_stable_moderate(self):
        # stable but moderate drift → mixed
        assert drift_health("stable", 0.4) == "mixed"


# ── drift_report ────────────────────────────────────────────────────────

class TestDriftReport:
    def test_basic_report(self):
        texts = [
            "alpha beta gamma delta epsilon",
            "alpha beta gamma delta zeta",
            "alpha beta gamma eta theta",
            "alpha beta iota kappa lambda",
            "alpha mu nu xi omicron",
        ]
        report = drift_report(texts)
        assert report["total_strokes"] == 5
        assert len(report["step_drifts"]) == 4
        assert 0.0 <= report["cumulative_drift"] <= 1.0
        assert report["drift_pattern"] in (
            "stable", "gradual", "oscillating", "pivoting", "wandering"
        )
        assert report["drift_health"] in (
            "focused", "evolving", "scattered", "mixed"
        )

    def test_identical_texts(self):
        texts = ["alpha beta gamma delta"] * 5
        report = drift_report(texts)
        assert report["cumulative_drift"] == 0.0
        assert report["drift_pattern"] == "stable"
        assert report["drift_health"] == "focused"

    def test_completely_different(self):
        texts = [
            "alpha beta gamma",
            "delta epsilon zeta",
            "theta iota kappa",
            "lambda mu xi",
        ]
        report = drift_report(texts)
        assert report["cumulative_drift"] == 1.0

    def test_single_text(self):
        report = drift_report(["alpha beta gamma"])
        assert report["total_strokes"] == 1
        assert report["step_drifts"] == []
        assert report["cumulative_drift"] == 0.0

    def test_empty(self):
        report = drift_report([])
        assert report["total_strokes"] == 0
        assert report["drift_pattern"] == "stable"

    def test_window_drifts_present(self):
        texts = [
            "alpha beta gamma",
            "alpha beta delta",
            "alpha beta epsilon",
            "alpha zeta theta",
            "alpha iota kappa",
        ]
        report = drift_report(texts, window=3)
        assert len(report["window_drifts"]) > 0
        assert "mean_window_drift" in report

    def test_velocities_present(self):
        texts = [
            "alpha beta gamma",
            "delta epsilon zeta",
            "theta iota kappa",
        ]
        report = drift_report(texts)
        assert len(report["velocities"]) == 1

    def test_max_min_step(self):
        texts = [
            "alpha beta gamma",
            "alpha beta delta",
            "theta iota kappa",
        ]
        report = drift_report(texts)
        assert report["max_step_drift"] >= report["min_step_drift"]


# ── drift_delta ──────────────────────────────────────────────────────────

class TestDriftDelta:
    def test_basic_delta(self):
        earlier = {
            "cumulative_drift": 0.3,
            "drift_pattern": "stable",
            "drift_health": "focused",
        }
        later = {
            "cumulative_drift": 0.5,
            "drift_pattern": "gradual",
            "drift_health": "evolving",
        }
        delta = drift_delta(earlier, later)
        assert delta["cumulative_drift_change"] == 0.2
        assert delta["pattern_changed"] is True
        assert delta["health_changed"] is True
        assert delta["drift_direction"] == "increasing"

    def test_no_change(self):
        report = {
            "cumulative_drift": 0.3,
            "drift_pattern": "stable",
            "drift_health": "focused",
        }
        delta = drift_delta(report, report)
        assert delta["cumulative_drift_change"] == 0.0
        assert delta["pattern_changed"] is False
        assert delta["drift_direction"] == "steady"

    def test_decreasing_drift(self):
        earlier = {"cumulative_drift": 0.6, "drift_pattern": "gradual", "drift_health": "evolving"}
        later = {"cumulative_drift": 0.3, "drift_pattern": "stable", "drift_health": "focused"}
        delta = drift_delta(earlier, later)
        assert delta["cumulative_drift_change"] == -0.3
        assert delta["drift_direction"] == "decreasing"

    def test_empty_reports(self):
        delta = drift_delta({}, {})
        assert delta["cumulative_drift_change"] == 0.0
        assert delta["drift_direction"] == "steady"


# ── integration: gradual drift scenario ──────────────────────────────────

class TestIntegration:
    def test_gradual_topic_evolution(self):
        """Simulate a natural topic shift over 8 strokes."""
        texts = [
            "python programming language syntax variables functions",
            "python programming language syntax classes methods",
            "python programming classes methods inheritance polymorphism",
            "programming inheritance polymorphism design patterns architecture",
            "software design patterns architecture microservices scalability",
            "microservices scalability deployment containers orchestration",
            "containers orchestration kubernetes deployment pipelines monitoring",
            "monitoring observability alerting metrics dashboards logging",
        ]
        report = drift_report(texts)
        assert report["total_strokes"] == 8
        assert len(report["step_drifts"]) == 7
        assert report["cumulative_drift"] > 0.0
        # Should detect some drift (not stable given the topic evolution)
        assert report["drift_pattern"] != "stable" or report["cumulative_drift"] > 0.2

    def test_stable_topic(self):
        """All strokes about the same topic — high overlap keeps drift low."""
        texts = [
            "python programming language syntax variables functions classes",
            "python programming language syntax variables functions classes",
            "python programming language syntax variables functions classes",
            "python programming language syntax variables functions classes",
            "python programming language syntax variables functions classes",
        ]
        report = drift_report(texts)
        assert report["cumulative_drift"] == 0.0
        assert report["drift_health"] == "focused"
