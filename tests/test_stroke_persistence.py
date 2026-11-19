"""Tests for stroke_persistence — idea lifecycle tracking across strokes.

Written by Qwen during caretaker visit 737, 2026-11-20.
"""

from __future__ import annotations

import pytest

from iamai.stroke_persistence import (
    extract_concepts,
    gap_trend,
    persistence_health,
    persistence_report,
    _classify_lifecycle,
    _compute_trace,
)


# =========================================================================
# extract_concepts
# =========================================================================


class TestExtractConcepts:
    """Tests for concept token extraction."""

    def test_basic_extraction(self):
        result = extract_concepts("the quick brown fox jumps")
        assert "quick" in result
        assert "brown" in result

    def test_filters_short_words(self):
        result = extract_concepts("a big cat sat on the mat")
        # "big", "cat", "sat", "mat" are all < 4 chars
        assert result == set()

    def test_filters_stopwords(self):
        result = extract_concepts("this very much more than that")
        # All stopwords
        assert result == set()

    def test_handles_empty_string(self):
        assert extract_concepts("") == set()

    def test_handles_punctuation(self):
        result = extract_concepts("quick, brown! fox? — jumping")
        assert "quick" in result
        assert "brown" in result
        assert "jumping" in result

    def test_case_insensitive(self):
        result = extract_concepts("Quick QUICK quick")
        assert "quick" in result
        assert len(result) == 1

    def test_longer_text(self):
        text = "The architecture of distributed systems requires careful consideration of network partitions"
        result = extract_concepts(text)
        assert "architecture" in result
        assert "distributed" in result
        assert "systems" in result
        assert "requires" in result
        assert "careful" in result
        assert "consideration" in result
        assert "network" in result
        assert "partitions" in result


# =========================================================================
# gap_trend
# =========================================================================


class TestGapTrend:
    """Tests for gap trend classification."""

    def test_increasing(self):
        assert gap_trend([1, 2, 4, 7]) == "increasing"

    def test_decreasing(self):
        assert gap_trend([7, 4, 2, 1]) == "decreasing"

    def test_stable(self):
        assert gap_trend([2, 2, 2]) == "stable"

    def test_empty(self):
        assert gap_trend([]) == "stable"

    def test_single_gap(self):
        assert gap_trend([5]) == "stable"

    def test_mostly_increasing(self):
        assert gap_trend([1, 2, 3, 5, 8]) == "increasing"

    def test_mostly_decreasing(self):
        assert gap_trend([10, 7, 4, 2, 1]) == "decreasing"

    def test_mixed_trend(self):
        # Balanced oscillation — equal up and down diffs
        assert gap_trend([3, 5, 3, 5, 3]) == "stable"


# =========================================================================
# _classify_lifecycle
# =========================================================================


class TestClassifyLifecycle:
    """Tests for concept lifecycle classification."""

    def test_anchored(self):
        # High frequency, no recurrences, span >= 2
        assert _classify_lifecycle(5, 0.9, 0, [1, 1, 1, 1, 1]) == "anchored"

    def test_persistent(self):
        # Wide span, decent frequency
        assert _classify_lifecycle(6, 0.65, 0, [1, 2, 1, 1, 1, 1]) == "persistent"

    def test_recurring(self):
        # Multiple recurrences (gaps > threshold)
        assert _classify_lifecycle(10, 0.3, 3, [1, 4, 1, 5]) == "recurring"

    def test_decaying(self):
        # Gaps are increasing
        assert _classify_lifecycle(10, 0.4, 1, [1, 2, 4, 7]) == "decaying"

    def test_fleeting_short_span(self):
        # Short span
        assert _classify_lifecycle(1, 0.5, 0, [1]) == "fleeting"

    def test_fleeting_single_gap(self):
        # Only one gap, nothing definitive
        assert _classify_lifecycle(2, 0.33, 0, [2]) == "fleeting"

    def test_anchored_beats_persistent(self):
        # Both conditions met, anchored should win
        result = _classify_lifecycle(5, 0.85, 0, [1, 1, 1, 1, 1])
        assert result == "anchored"


# =========================================================================
# _compute_trace
# =========================================================================


class TestComputeTrace:
    """Tests for individual concept trace computation."""

    def test_single_appearance(self):
        trace = _compute_trace("alpha", [3])
        assert trace["span"] == 0
        assert trace["lifecycle"] == "fleeting"
        assert trace["recurrences"] == 0
        assert trace["fade_curve"] == []

    def test_consecutive_appearances(self):
        trace = _compute_trace("beta", [0, 1, 2, 3, 4])
        assert trace["span"] == 4
        assert trace["frequency"] == 1.0
        assert trace["lifecycle"] == "anchored"

    def test_spread_appearances(self):
        trace = _compute_trace("gamma", [0, 3, 6, 9])
        assert trace["span"] == 9
        assert trace["recurrences"] >= 1
        assert trace["fade_curve"] == [3, 3, 3]

    def test_recurring_concept(self):
        trace = _compute_trace("delta", [0, 1, 5, 6, 10, 11])
        assert trace["recurrences"] >= 2
        assert trace["lifecycle"] == "recurring"

    def test_frequency_calculation(self):
        # 3 appearances over span 6 → 3/7 ≈ 0.4286
        trace = _compute_trace("epsilon", [0, 3, 6])
        assert abs(trace["frequency"] - 3 / 7) < 0.001


# =========================================================================
# persistence_report
# =========================================================================


class TestPersistenceReport:
    """Tests for the full stream persistence report."""

    def test_empty_stream(self):
        report = persistence_report([])
        assert report["total_concepts"] == 0
        assert report["tracked_concepts"] == 0
        assert report["persistence_score"] == 0.0
        assert report["stream_pattern"] == "scattershot"

    def test_single_stroke(self):
        report = persistence_report(["quick brown fox jumps high"])
        assert report["total_concepts"] >= 1
        assert report["tracked_concepts"] == 0  # nothing appears twice
        assert report["persistence_score"] == 0.0

    def test_identical_strokes(self):
        texts = ["alpha beta gamma delta"] * 6
        report = persistence_report(texts)
        assert report["persistence_score"] == 1.0
        assert report["stream_pattern"] == "focused-sprint"
        assert report["tracked_concepts"] >= 4

    def test_boomerang_pattern(self):
        # Concepts that appear, vanish, reappear
        texts = [
            "alpha beta gamma",
            "alpha beta gamma",
            "delta epsilon zeta",
            "delta epsilon zeta",
            "alpha beta gamma",
            "alpha beta gamma",
            "delta epsilon zeta",
            "delta epsilon zeta",
            "alpha beta gamma",
            "alpha beta gamma",
        ]
        report = persistence_report(texts)
        assert report["recurrence_rate"] > 0.0
        assert report["stream_pattern"] == "boomerang"

    def test_deep_dive_pattern(self):
        # Concepts that persist across many consecutive strokes
        base = "architecture distributed systems network partition"
        texts = []
        for i in range(10):
            texts.append(f"{base} consideration stroke number {i}")
        report = persistence_report(texts)
        # High persistence score expected
        assert report["persistence_score"] > 0.3

    def test_scattershot_pattern(self):
        # Each stroke has unique concepts, no overlap
        texts = [
            "alpha bravo charlie",
            "delta echo foxtrot",
            "golf hotel india",
            "juliet kilo lima",
            "mike november oscar",
        ]
        report = persistence_report(texts)
        assert report["tracked_concepts"] == 0
        assert report["stream_pattern"] == "scattershot"

    def test_report_keys(self):
        report = persistence_report(["hello world testing things"])
        expected_keys = {
            "total_concepts", "tracked_concepts", "traces",
            "persistence_score", "recurrence_rate", "anchor_ratio",
            "fade_ratio", "lifecycle_counts", "stream_pattern",
            "top_persistent", "top_recurring",
        }
        assert set(report.keys()) == expected_keys

    def test_min_appearances_parameter(self):
        texts = [
            "alpha beta",
            "alpha beta",
            "alpha beta",
        ]
        # With min_appearances=2, should track
        r2 = persistence_report(texts, min_appearances=2)
        assert r2["tracked_concepts"] >= 2

        # With min_appearances=5, should not track
        r5 = persistence_report(texts, min_appearances=5)
        assert r5["tracked_concepts"] == 0

    def test_top_persistent_sorted_by_span(self):
        texts = [
            "alpha beta gamma delta epsilon",
            "alpha beta gamma",
            "alpha beta gamma",
            "alpha beta gamma",
            "alpha beta gamma delta",
            "alpha beta gamma delta epsilon",
            "alpha beta gamma delta epsilon",
            "alpha beta gamma",
        ]
        report = persistence_report(texts)
        if len(report["top_persistent"]) >= 2:
            spans = [t["span"] for t in report["top_persistent"]]
            assert spans == sorted(spans, reverse=True)

    def test_top_recurring_sorted_by_recurrences(self):
        texts = [
            "alpha beta",
            "alpha beta",
            "gamma delta",
            "gamma delta",
            "alpha beta",
            "alpha beta",
            "gamma delta",
            "gamma delta",
            "alpha beta",
            "gamma delta",
        ]
        report = persistence_report(texts)
        if len(report["top_recurring"]) >= 2:
            recs = [t["recurrences"] for t in report["top_recurring"]]
            assert recs == sorted(recs, reverse=True)

    def test_persistence_score_bounded(self):
        texts = ["alpha beta gamma delta"] * 20
        report = persistence_report(texts)
        assert 0.0 <= report["persistence_score"] <= 1.0

    def test_recurrence_rate_bounded(self):
        texts = [
            "alpha beta",
            "gamma delta",
            "alpha beta",
            "gamma delta",
        ] * 5
        report = persistence_report(texts)
        assert 0.0 <= report["recurrence_rate"] <= 1.0

    def test_anchor_ratio_bounded(self):
        texts = ["alpha beta gamma"] * 10
        report = persistence_report(texts)
        assert 0.0 <= report["anchor_ratio"] <= 1.0

    def test_fade_ratio_bounded(self):
        texts = [
            "alpha beta gamma",
            "alpha beta gamma",
            "alpha",
            "",
            "",
            "",
            "",
            "",
        ]
        report = persistence_report(texts)
        assert 0.0 <= report["fade_ratio"] <= 1.0


# =========================================================================
# persistence_health
# =========================================================================


class TestPersistenceHealth:
    """Tests for the quick health check function."""

    def test_healthy_deep_dive(self):
        report = {"stream_pattern": "deep-dive", "persistence_score": 0.7}
        assert persistence_health(report) == "healthy"

    def test_shallow_scattershot(self):
        report = {"stream_pattern": "scattershot", "persistence_score": 0.1}
        assert persistence_health(report) == "shallow"

    def test_mixed_boomerang(self):
        report = {"stream_pattern": "boomerang", "persistence_score": 0.3}
        assert persistence_health(report) == "mixed"

    def test_healthy_focused_sprint(self):
        report = {"stream_pattern": "focused-sprint", "persistence_score": 0.4}
        assert persistence_health(report) == "healthy"

    def test_mixed_default(self):
        report = {"stream_pattern": "unknown", "persistence_score": 0.5}
        assert persistence_health(report) == "mixed"

    def test_missing_keys(self):
        report = {}
        assert persistence_health(report) == "shallow"


# =========================================================================
# Edge cases and robustness
# =========================================================================


class TestEdgeCases:
    """Edge cases and robustness tests."""

    def test_all_empty_strokes(self):
        texts = ["", "", "", ""]
        report = persistence_report(texts)
        assert report["total_concepts"] == 0
        assert report["stream_pattern"] == "scattershot"

    def test_one_concept_throughout(self):
        texts = ["alpha"] * 10
        # "alpha" is only 5 chars but let's check it's tracked
        report = persistence_report(texts)
        assert report["tracked_concepts"] >= 1
        assert report["persistence_score"] == 1.0

    def test_very_long_stream(self):
        texts = [f"concept_{i % 5} stroke_{i}" for i in range(100)]
        report = persistence_report(texts)
        assert report["tracked_concepts"] > 0
        assert 0.0 <= report["persistence_score"] <= 1.0

    def test_concepts_with_hyphens(self):
        result = extract_concepts("well-known self-driving state-of-the-art")
        # hyphenated words should be extracted if long enough
        assert len(result) > 0

    def test_unicode_handling(self):
        # Non-ASCII characters in text shouldn't break extraction
        result = extract_concepts("café résumé naïve über algorithm")
        # Only ASCII words matching the regex will be found
        assert "algorithm" in result

    def test_traces_contain_required_fields(self):
        texts = ["alpha beta gamma"] * 5
        report = persistence_report(texts)
        for trace in report["traces"]:
            assert "concept" in trace
            assert "appearances" in trace
            assert "first_seen" in trace
            assert "last_seen" in trace
            assert "span" in trace
            assert "frequency" in trace
            assert "recurrences" in trace
            assert "fade_curve" in trace
            assert "lifecycle" in trace

    def test_lifecycle_counts_sum_to_tracked(self):
        texts = [
            "alpha beta gamma delta",
            "alpha beta gamma",
            "alpha beta",
            "alpha beta gamma delta",
            "alpha beta gamma",
            "alpha",
            "alpha beta gamma delta",
        ]
        report = persistence_report(texts)
        total_from_counts = sum(report["lifecycle_counts"].values())
        assert total_from_counts == report["tracked_concepts"]

    def test_gap_threshold_parameter(self):
        texts = [
            "alpha beta",
            "alpha beta",
            "gamma delta",
            "alpha beta",
            "alpha beta",
        ]
        # With default gap_threshold=2, gap of 2 is not a recurrence
        r_default = persistence_report(texts)
        # With gap_threshold=1, gap of 2 IS a recurrence
        r_strict = persistence_report(texts, gap_threshold=1)
        assert r_strict["recurrence_rate"] >= r_default["recurrence_rate"]
