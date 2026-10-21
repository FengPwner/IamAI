"""Tests for iamai.stroke_half_life — topic recurrence interval tracker."""

import pytest

from iamai.stroke_half_life import (
    TopicHalfLife,
    classify_topic,
    trend_from_gaps,
)


# ---------------------------------------------------------------------------
# TopicHalfLife construction
# ---------------------------------------------------------------------------


class TestTopicHalfLifeInit:
    def test_defaults(self):
        thl = TopicHalfLife()
        assert thl.hot_threshold == 120.0
        assert thl.cold_threshold == 1800.0
        assert thl.window_s == 3600.0

    def test_custom_thresholds(self):
        thl = TopicHalfLife(hot_threshold=60, cold_threshold=600, window_s=7200)
        assert thl.hot_threshold == 60
        assert thl.cold_threshold == 600
        assert thl.window_s == 7200


# ---------------------------------------------------------------------------
# observe / observe_many
# ---------------------------------------------------------------------------


class TestObserve:
    def test_single_observe(self):
        thl = TopicHalfLife()
        thl.observe("thought", 1000)
        assert thl.count("thought") == 1

    def test_multiple_observe(self):
        thl = TopicHalfLife()
        thl.observe("thought", 1000)
        thl.observe("thought", 1060)
        thl.observe("thought", 1120)
        assert thl.count("thought") == 3

    def test_observe_many(self):
        thl = TopicHalfLife()
        events = [
            ("thought", 1000),
            ("devlog", 1030),
            ("thought", 1060),
            ("garden", 1090),
        ]
        thl.observe_many(events)
        assert thl.count("thought") == 2
        assert thl.count("devlog") == 1
        assert thl.count("garden") == 1

    def test_unknown_topic_count_zero(self):
        thl = TopicHalfLife()
        assert thl.count("nonexistent") == 0


# ---------------------------------------------------------------------------
# topics property
# ---------------------------------------------------------------------------


class TestTopics:
    def test_empty(self):
        thl = TopicHalfLife()
        assert thl.topics == []

    def test_sorted_by_last_seen(self):
        thl = TopicHalfLife()
        thl.observe("old_topic", 100)
        thl.observe("new_topic", 200)
        thl.observe("mid_topic", 150)
        assert thl.topics == ["new_topic", "mid_topic", "old_topic"]


# ---------------------------------------------------------------------------
# gap
# ---------------------------------------------------------------------------


class TestGap:
    def test_no_occurrences(self):
        thl = TopicHalfLife()
        assert thl.gap("missing") is None

    def test_single_occurrence(self):
        thl = TopicHalfLife()
        thl.observe("thought", 1000)
        assert thl.gap("thought") is None

    def test_two_occurrences(self):
        thl = TopicHalfLife()
        thl.observe("thought", 1000)
        thl.observe("thought", 1060)
        assert thl.gap("thought") == 60.0

    def test_three_occurrences_avg(self):
        thl = TopicHalfLife()
        thl.observe("thought", 1000)
        thl.observe("thought", 1060)
        thl.observe("thought", 1180)
        # gaps: 60, 120 → avg 90
        assert thl.gap("thought") == 90.0

    def test_unsorted_timestamps_still_correct(self):
        """Timestamps arriving out of order should still produce correct gaps."""
        thl = TopicHalfLife()
        thl.observe("thought", 1060)
        thl.observe("thought", 1000)
        thl.observe("thought", 1180)
        # sorted: 1000, 1060, 1180 → gaps: 60, 120 → avg 90
        assert thl.gap("thought") == 90.0


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


class TestClassify:
    def test_dormant_no_data(self):
        thl = TopicHalfLife()
        assert thl.classify("missing") == "dormant"

    def test_dormant_single(self):
        thl = TopicHalfLife()
        thl.observe("thought", 1000)
        assert thl.classify("thought") == "dormant"

    def test_hot(self):
        thl = TopicHalfLife()
        thl.observe("thought", 1000)
        thl.observe("thought", 1030)  # gap 30s < 120s threshold
        assert thl.classify("thought") == "hot"

    def test_warm(self):
        thl = TopicHalfLife()
        thl.observe("thought", 1000)
        thl.observe("thought", 1500)  # gap 500s, between 120 and 1800
        assert thl.classify("thought") == "warm"

    def test_cold(self):
        thl = TopicHalfLife()
        thl.observe("thought", 1000)
        thl.observe("thought", 5000)  # gap 4000s > 1800 threshold
        assert thl.classify("thought") == "cold"

    def test_custom_thresholds(self):
        thl = TopicHalfLife(hot_threshold=30, cold_threshold=100)
        thl.observe("x", 0)
        thl.observe("x", 50)  # gap 50 > 30 hot, < 100 cold → warm
        assert thl.classify("x") == "warm"

    def test_boundary_hot_exact(self):
        """Gap exactly at hot_threshold is NOT hot (must be strictly less)."""
        thl = TopicHalfLife(hot_threshold=60)
        thl.observe("x", 0)
        thl.observe("x", 60)  # gap == threshold → warm
        assert thl.classify("x") == "warm"

    def test_boundary_cold_exact(self):
        """Gap exactly at cold_threshold is warm, not cold."""
        thl = TopicHalfLife(cold_threshold=300)
        thl.observe("x", 0)
        thl.observe("x", 300)  # gap == cold_threshold → warm
        assert thl.classify("x") == "warm"


# ---------------------------------------------------------------------------
# trend
# ---------------------------------------------------------------------------


class TestTrend:
    def test_steady_insufficient_data(self):
        thl = TopicHalfLife()
        assert thl.trend("missing") == "steady"
        thl.observe("x", 1000)
        assert thl.trend("x") == "steady"
        thl.observe("x", 1060)
        assert thl.trend("x") == "steady"  # only 1 gap, need ≥ 2

    def test_steady_equal_gaps(self):
        thl = TopicHalfLife()
        thl.observe("x", 0)
        thl.observe("x", 60)
        thl.observe("x", 120)
        # gaps: 60, 60 → last/avg = 1.0
        assert thl.trend("x") == "steady"

    def test_heating(self):
        thl = TopicHalfLife()
        thl.observe("x", 0)
        thl.observe("x", 100)  # gap 100
        thl.observe("x", 150)  # gap 50
        # avg=75, last=50, ratio=0.667 < 0.7 → heating
        assert thl.trend("x") == "heating"

    def test_cooling(self):
        thl = TopicHalfLife()
        thl.observe("x", 0)
        thl.observe("x", 60)   # gap 60
        thl.observe("x", 200)  # gap 140
        # avg=100, last=140, ratio=1.4 > 1.3 → cooling
        assert thl.trend("x") == "cooling"

    def test_boundary_0_7_is_steady(self):
        """Ratio exactly at 0.7 is NOT heating (must be strictly less)."""
        thl = TopicHalfLife()
        thl.observe("x", 0)
        thl.observe("x", 100)  # gap 100
        thl.observe("x", 170)  # gap 70 → ratio 0.7
        assert thl.trend("x") == "steady"

    def test_boundary_1_3_is_steady(self):
        """Ratio exactly at 1.3 is NOT cooling (must be strictly greater)."""
        thl = TopicHalfLife()
        thl.observe("x", 0)
        thl.observe("x", 100)  # gap 100
        thl.observe("x", 230)  # gap 130 → ratio 1.3
        assert thl.trend("x") == "steady"


# ---------------------------------------------------------------------------
# summary / report
# ---------------------------------------------------------------------------


class TestSummary:
    def test_empty(self):
        thl = TopicHalfLife()
        assert thl.summary() == {}

    def test_structure(self):
        thl = TopicHalfLife()
        thl.observe("thought", 0)
        thl.observe("thought", 60)
        thl.observe("devlog", 10)
        s = thl.summary()
        assert "thought" in s
        assert "devlog" in s
        assert s["thought"]["count"] == 2
        assert s["thought"]["avg_gap_s"] == 60.0
        assert s["thought"]["classify"] == "hot"
        assert s["devlog"]["classify"] == "dormant"

    def test_report_not_empty(self):
        thl = TopicHalfLife()
        thl.observe("thought", 0)
        thl.observe("thought", 60)
        report = thl.report()
        assert "thought" in report
        assert "hot" in report


# ---------------------------------------------------------------------------
# from_strokes classmethod
# ---------------------------------------------------------------------------


class TestFromStrokes:
    def test_basic(self):
        strokes = [
            {"kind": "thought", "at": "2026-10-21T10:00:00"},
            {"kind": "devlog",  "at": "2026-10-21T10:00:30"},
            {"kind": "thought", "at": "2026-10-21T10:01:00"},
            {"kind": "thought", "at": "2026-10-21T10:02:00"},
        ]
        thl = TopicHalfLife.from_strokes(strokes)
        assert thl.count("thought") == 3
        assert thl.count("devlog") == 1
        # thought gaps: 60s, 60s → avg 60s → hot
        assert thl.classify("thought") == "hot"

    def test_skips_missing_keys(self):
        strokes = [
            {"kind": "thought", "at": "2026-10-21T10:00:00"},
            {"at": "2026-10-21T10:00:30"},         # no kind
            {"kind": "devlog"},                      # no at
        ]
        thl = TopicHalfLife.from_strokes(strokes)
        assert thl.count("thought") == 1
        assert thl.count("devlog") == 0

    def test_skips_bad_timestamps(self):
        strokes = [
            {"kind": "thought", "at": "2026-10-21T10:00:00"},
            {"kind": "thought", "at": "not-a-date"},
        ]
        thl = TopicHalfLife.from_strokes(strokes)
        assert thl.count("thought") == 1

    def test_custom_keys(self):
        strokes = [
            {"topic": "A", "time": "2026-01-01T00:00:00"},
            {"topic": "A", "time": "2026-01-01T00:05:00"},
        ]
        thl = TopicHalfLife.from_strokes(
            strokes, topic_key="topic", ts_key="time"
        )
        assert thl.count("A") == 2

    def test_custom_thresholds_passed(self):
        strokes = [
            {"kind": "x", "at": "2026-01-01T00:00:00"},
            {"kind": "x", "at": "2026-01-01T00:01:00"},
        ]
        # Default hot_threshold=120, gap=60 → hot
        thl_default = TopicHalfLife.from_strokes(strokes)
        assert thl_default.classify("x") == "hot"
        # With hot_threshold=30, gap=60 > 30 → warm (if < cold_threshold)
        thl_custom = TopicHalfLife.from_strokes(strokes, hot_threshold=30)
        assert thl_custom.classify("x") == "warm"


# ---------------------------------------------------------------------------
# Standalone helpers
# ---------------------------------------------------------------------------


class TestClassifyTopic:
    def test_none(self):
        assert classify_topic(None) == "dormant"

    def test_hot(self):
        assert classify_topic(50) == "hot"

    def test_warm(self):
        assert classify_topic(500) == "warm"

    def test_cold(self):
        assert classify_topic(5000) == "cold"

    def test_custom(self):
        assert classify_topic(80, hot_threshold=100, cold_threshold=200) == "hot"


class TestTrendFromGaps:
    def test_empty(self):
        assert trend_from_gaps([]) == "steady"

    def test_single(self):
        assert trend_from_gaps([60]) == "steady"

    def test_steady(self):
        assert trend_from_gaps([60, 60, 60]) == "steady"

    def test_heating(self):
        assert trend_from_gaps([100, 100, 30]) == "heating"

    def test_cooling(self):
        assert trend_from_gaps([60, 60, 200]) == "cooling"
