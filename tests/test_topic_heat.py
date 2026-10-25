"""Tests for iamai.topic_heat — topic heat analysis across note windows.

The module tracks which themes are hot (surging), warm (steady),
cooling (fading), or cold (nearly gone) by comparing keyword
frequencies in recent vs baseline filename windows.

Tests cover:

1. Topic extraction from filenames (stop-word filtering, tokenization)
2. Heat classification logic (hot/warm/cooling/cold)
3. Window splitting and density computation
4. Edge cases (empty input, single file, all stop words)
5. Summary and serialization helpers

Each test uses synthetic filename lists to avoid touching the real repo.
"""

from __future__ import annotations

import pytest

from iamai.topic_heat import (
    TopicEntry,
    TopicReport,
    extract_topics,
    topic_heatmap,
    _classify_heat,
    _compute_density,
    _extract_topics_from_filename,
    DEFAULT_STOP_WORDS,
    HOT_RATIO,
    COOLING_RATIO,
    COLD_THRESHOLD,
    MIN_TOTAL_COUNT,
)


# ---------------------------------------------------------------------------
# Token extraction
# ---------------------------------------------------------------------------


class TestExtractTopicsFromFilename:
    """How individual filenames are parsed into topic tokens."""

    def test_simple_filename(self):
        tokens = _extract_topics_from_filename("push-race-recovery.md", DEFAULT_STOP_WORDS)
        assert tokens == ["push", "race", "recovery"]

    def test_stop_words_filtered(self):
        tokens = _extract_topics_from_filename("caretaker-visit-212.md", DEFAULT_STOP_WORDS)
        # "caretaker" and "visit" are stop words; "212" is numeric → stripped
        assert tokens == []

    def test_date_suffix_stripped(self):
        tokens = _extract_topics_from_filename(
            "stall-event-2026-10-18.md", DEFAULT_STOP_WORDS
        )
        assert tokens == ["stall", "event"]

    def test_single_letter_tokens_dropped(self):
        tokens = _extract_topics_from_filename("a-b-c-d-e.md", DEFAULT_STOP_WORDS)
        assert tokens == []

    def test_extension_stripped(self):
        tokens = _extract_topics_from_filename("recovery.txt", DEFAULT_STOP_WORDS)
        assert tokens == ["recovery"]

    def test_mixed_case_normalized(self):
        tokens = _extract_topics_from_filename("Push-Race-Recovery.md", DEFAULT_STOP_WORDS)
        assert tokens == ["push", "race", "recovery"]

    def test_underscores_as_separators(self):
        tokens = _extract_topics_from_filename("stall_forecaster.md", DEFAULT_STOP_WORDS)
        assert tokens == ["stall", "forecaster"]

    def test_real_world_caretaker_visit(self):
        tokens = _extract_topics_from_filename(
            "caretaker-visit-100-2026-10-09.md", DEFAULT_STOP_WORDS
        )
        assert tokens == []

    def test_real_world_stall_note(self):
        tokens = _extract_topics_from_filename(
            "overnight-stall-classified-2026-10-05.md", DEFAULT_STOP_WORDS
        )
        assert tokens == ["overnight", "stall", "classified"]

    def test_custom_stop_words(self):
        custom = frozenset({"stall"})
        tokens = _extract_topics_from_filename("stall-event.md", custom)
        assert tokens == ["event"]


# ---------------------------------------------------------------------------
# extract_topics (list-level helper)
# ---------------------------------------------------------------------------


class TestExtractTopics:
    """Batch extraction over a list of filenames."""

    def test_empty_list(self):
        assert extract_topics([]) == []

    def test_multiple_files(self):
        result = extract_topics([
            "push-race.md",
            "stall-event.md",
            "caretaker-visit-1.md",
        ])
        assert len(result) == 3
        assert result[0] == ["push", "race"]
        assert result[1] == ["stall", "event"]
        assert result[2] == []  # all stop words or numbers


# ---------------------------------------------------------------------------
# Density computation
# ---------------------------------------------------------------------------


class TestComputeDensity:
    """Occurrences per file in a window."""

    def test_normal(self):
        assert _compute_density(5, 10) == 0.5

    def test_zero_window(self):
        assert _compute_density(5, 0) == 0.0

    def test_zero_count(self):
        assert _compute_density(0, 10) == 0.0

    def test_both_zero(self):
        assert _compute_density(0, 0) == 0.0


# ---------------------------------------------------------------------------
# Heat classification
# ---------------------------------------------------------------------------


class TestClassifyHeat:
    """Mapping density ratios to heat labels."""

    def test_hot_when_baseline_zero_and_enough_recent(self):
        # baseline_density=0, recent_count >= MIN_TOTAL_COUNT → hot
        assert _classify_heat(0.5, 0.0, MIN_TOTAL_COUNT) == "hot"

    def test_warm_when_baseline_zero_and_few_recent(self):
        # baseline_density=0, recent_count < MIN_TOTAL_COUNT → warm
        assert _classify_heat(0.1, 0.0, 1) == "warm"

    def test_hot_high_ratio(self):
        # ratio = 0.8 / 0.2 = 4.0 >= HOT_RATIO (2.0)
        assert _classify_heat(0.8, 0.2, 5) == "hot"

    def test_warm_moderate_ratio(self):
        # ratio = 0.4 / 0.3 ≈ 1.33 — between COOLING and HOT
        assert _classify_heat(0.4, 0.3, 5) == "warm"

    def test_cooling_low_ratio(self):
        # ratio = 0.1 / 0.4 = 0.25 <= COOLING_RATIO (0.5)
        assert _classify_heat(0.1, 0.4, 2) == "cooling"

    def test_cold_very_low_ratio(self):
        # ratio = 0.01 / 0.5 = 0.02 <= COLD_THRESHOLD (0.1)
        assert _classify_heat(0.01, 0.5, 1) == "cold"

    def test_exactly_hot_threshold(self):
        # ratio = 0.6 / 0.3 = 2.0 == HOT_RATIO → hot
        assert _classify_heat(0.6, 0.3, 5) == "hot"

    def test_exactly_cooling_threshold(self):
        # ratio = 0.2 / 0.4 = 0.5 == COOLING_RATIO → cooling (<= check)
        assert _classify_heat(0.2, 0.4, 2) == "cooling"


# ---------------------------------------------------------------------------
# topic_heatmap — main public API
# ---------------------------------------------------------------------------


class TestTopicHeatmap:
    """End-to-end tests for topic_heatmap."""

    def test_empty_input(self):
        report = topic_heatmap([])
        assert report.topics == {}
        assert report.recent_window_size == 0
        assert report.baseline_window_size == 0

    def test_all_stop_words(self):
        """If all tokens are stop words, no topics are tracked."""
        report = topic_heatmap([
            "caretaker-visit-1.md",
            "caretaker-visit-2.md",
            "caretaker-visit-3.md",
            "caretaker-visit-4.md",
        ], recent_count=2)
        assert report.topics == {}

    def test_hot_topic(self):
        """A topic that surges in recent window should be hot."""
        # baseline: 10 files, "stall" appears in 1 → density 0.1
        # recent:   5 files, "stall" appears in 4 → density 0.8
        # ratio = 8.0 → hot
        baseline = [f"stall-event-{i}.md" for i in range(1)]
        baseline += [f"other-note-{i}.md" for i in range(9)]
        recent = [f"stall-event-{i}.md" for i in range(4)]
        recent += [f"other-note-{i}.md" for i in range(1)]
        filenames = baseline + recent
        report = topic_heatmap(filenames, recent_count=5, min_total_count=2)
        assert "stall" in report.topics
        assert report.topics["stall"].heat == "hot"

    def test_cooling_topic(self):
        """A topic that fades in recent window should be cooling or cold."""
        # baseline: 10 files, "push" appears in 8 → density 0.8
        # recent:   5 files, "push" appears in 1 → density 0.2
        # ratio = 0.25 → cooling
        baseline = [f"push-race-{i}.md" for i in range(8)]
        baseline += [f"other-note-{i}.md" for i in range(2)]
        recent = [f"push-race-{i}.md" for i in range(1)]
        recent += [f"other-note-{i}.md" for i in range(4)]
        filenames = baseline + recent
        report = topic_heatmap(filenames, recent_count=5, min_total_count=2)
        assert "push" in report.topics
        assert report.topics["push"].heat in ("cooling", "cold")

    def test_warm_topic(self):
        """A topic steady across both windows should be warm."""
        # baseline: 10 files, "recovery" in 3 → density 0.3
        # recent:   5 files, "recovery" in 2 → density 0.4
        # ratio ≈ 1.33 → warm
        baseline = [f"recovery-note-{i}.md" for i in range(3)]
        baseline += [f"other-note-{i}.md" for i in range(7)]
        recent = [f"recovery-note-{i}.md" for i in range(2)]
        recent += [f"other-note-{i}.md" for i in range(3)]
        filenames = baseline + recent
        report = topic_heatmap(filenames, recent_count=5, min_total_count=2)
        assert "recovery" in report.topics
        assert report.topics["recovery"].heat == "warm"

    def test_min_total_count_filter(self):
        """Topics below min_total_count are excluded."""
        filenames = ["stall-once.md"] + [f"other-{i}.md" for i in range(5)]
        report = topic_heatmap(filenames, recent_count=3, min_total_count=2)
        # "stall" appears once total, "once" appears once → both excluded
        assert "stall" not in report.topics

    def test_window_sizes(self):
        """Verify window sizes are computed correctly."""
        filenames = [f"note-{i}.md" for i in range(15)]
        report = topic_heatmap(filenames, recent_count=5)
        assert report.recent_window_size == 5
        assert report.baseline_window_size == 10

    def test_recent_larger_than_total(self):
        """When recent_count > len(filenames), baseline is empty."""
        filenames = ["stall-event-1.md", "stall-event-2.md"]
        report = topic_heatmap(filenames, recent_count=10)
        assert report.baseline_window_size == 0
        assert report.recent_window_size == 2

    def test_multiple_topics_tracked(self):
        """Several topics can be tracked simultaneously."""
        filenames = (
            [f"push-race-{i}.md" for i in range(4)] +
            [f"stall-event-{i}.md" for i in range(3)] +
            [f"recovery-note-{i}.md" for i in range(2)] +
            [f"other-{i}.md" for i in range(6)]
        )
        report = topic_heatmap(filenames, recent_count=5, min_total_count=2)
        # push (4), stall (3), recovery (2), race (4), event (3), note (2)
        # all should appear
        assert "push" in report.topics
        assert "stall" in report.topics
        assert "race" in report.topics
        assert "event" in report.topics


# ---------------------------------------------------------------------------
# TopicReport helpers
# ---------------------------------------------------------------------------


class TestTopicReport:
    """Summary, hot_topics, and serialization."""

    def _make_report(self):
        topics = {
            "stall": TopicEntry("stall", "hot", 8, 2, 0.8, 0.1),
            "push": TopicEntry("push", "cooling", 1, 6, 0.1, 0.6),
            "recovery": TopicEntry("recovery", "warm", 3, 3, 0.3, 0.3),
            "race": TopicEntry("race", "cold", 0, 5, 0.0, 0.5),
        }
        return TopicReport(topics=topics, recent_window_size=10, baseline_window_size=10)

    def test_summary_format(self):
        report = self._make_report()
        s = report.summary()
        assert "4 topics tracked" in s
        assert "1 hot" in s
        assert "1 warm" in s
        assert "1 cooling" in s
        assert "1 cold" in s

    def test_summary_empty(self):
        report = TopicReport(topics={}, recent_window_size=0, baseline_window_size=0)
        assert report.summary() == "no topics tracked"

    def test_hot_topics_sorted(self):
        report = self._make_report()
        hot = report.hot_topics()
        # hot first, then warm, cooling, cold
        assert hot[0] == "stall"
        assert hot[-1] == "race"

    def test_as_dict(self):
        report = self._make_report()
        d = report.as_dict()
        assert "topics" in d
        assert "summary" in d
        assert d["recent_window_size"] == 10
        assert d["topics"]["stall"]["heat"] == "hot"

    def test_topic_entry_as_dict(self):
        entry = TopicEntry("stall", "hot", 8, 2, 0.8, 0.1)
        d = entry.as_dict()
        assert d["topic"] == "stall"
        assert d["heat"] == "hot"
        assert d["recent_count"] == 8
        assert d["baseline_density"] == 0.1
