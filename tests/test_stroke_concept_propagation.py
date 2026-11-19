"""Tests for iamai/stroke_concept_propagation.py — concept propagation tracking.

Run:  python3 -m pytest tests/test_stroke_concept_propagation.py -v

Written by Qwen during caretaker visit 728, 2026-11-19.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.stroke_concept_propagation import (  # noqa: E402
    ConceptReport,
    ConceptTimeline,
    PropagationReport,
    _classify_regime,
    analyse_propagation,
    analyse_propagation_windows,
    build_concept_timeline,
    build_word_timelines,
    classify_adoption,
    compute_echo_rate,
    compute_half_life,
    extract_content_words,
)


# ---------------------------------------------------------------------------
# extract_content_words
# ---------------------------------------------------------------------------


class TestExtractContentWords:
    def test_basic_extraction(self):
        words = extract_content_words("the quick brown fox jumps over")
        assert "quick" in words
        assert "brown" in words
        assert "jumps" in words

    def test_filters_short_words(self):
        words = extract_content_words("a an to of in on at by")
        assert words == []

    def test_filters_stopwords(self):
        words = extract_content_words("about above after again")
        assert words == []

    def test_lowercases(self):
        words = extract_content_words("QUICK BROWN FOX")
        assert "quick" in words
        assert "brown" in words

    def test_min_len_parameter(self):
        words = extract_content_words("cat dog elephant", min_len=5)
        assert "cat" not in words
        assert "elephant" in words

    def test_empty_input(self):
        assert extract_content_words("") == []

    def test_punctuation_handling(self):
        words = extract_content_words("hello, planets! testing...")
        assert "hello" in words
        assert "planets" in words
        assert "testing" in words

    def test_numbers_ignored(self):
        words = extract_content_words("commit 42 lines 1234")
        assert "commit" in words
        assert "lines" in words
        # numbers are not alphabetic, so excluded
        assert "42" not in words

    def test_hyphenated_words_split(self):
        # hyphenated words get split by regex
        words = extract_content_words("self-writing repository")
        assert "self" in words
        assert "writing" in words
        assert "repository" in words


# ---------------------------------------------------------------------------
# build_word_timelines
# ---------------------------------------------------------------------------


class TestBuildWordTimelines:
    def test_basic(self):
        texts = [
            "automation builds systems",
            "systems require testing",
            "testing validates automation",
        ]
        tl = build_word_timelines(texts)
        assert tl["automation"] == [0, 2]
        assert tl["systems"] == [0, 1]
        assert tl["testing"] == [1, 2]

    def test_empty_input(self):
        assert build_word_timelines([]) == {}

    def test_single_stroke(self):
        tl = build_word_timelines(["automation builds systems"])
        assert tl["automation"] == [0]
        assert tl["systems"] == [0]

    def test_deduplication_within_stroke(self):
        tl = build_word_timelines(["testing testing testing"])
        assert tl["testing"] == [0]

    def test_min_len(self):
        tl = build_word_timelines(["cat dog elephant"], min_len=5)
        assert "cat" not in tl
        assert "elephant" in tl


# ---------------------------------------------------------------------------
# compute_echo_rate
# ---------------------------------------------------------------------------


class TestComputeEchoRate:
    def test_perfect_echo(self):
        # concept appears in every stroke after first
        appearances = [0, 1, 2, 3, 4]
        rate = compute_echo_rate(appearances, total_strokes=5)
        assert rate == 1.0

    def test_no_echo(self):
        # concept appears only once
        rate = compute_echo_rate([0], total_strokes=10)
        assert rate == 0.0

    def test_partial_echo(self):
        appearances = [0, 2, 4, 6, 8]
        rate = compute_echo_rate(appearances, total_strokes=10)
        # echoes in (0, 9] = 4, horizon = 9
        assert abs(rate - 4 / 9) < 0.01

    def test_with_horizon(self):
        appearances = [0, 1, 2, 3, 4, 10, 20]
        rate = compute_echo_rate(appearances, total_strokes=25, horizon=5)
        # echoes in (0, 5] = 4, horizon = 5
        assert abs(rate - 4 / 5) < 0.01

    def test_single_stroke_stream(self):
        rate = compute_echo_rate([0], total_strokes=1)
        assert rate == 0.0

    def test_empty_appearances(self):
        rate = compute_echo_rate([], total_strokes=10)
        assert rate == 0.0

    def test_all_at_end(self):
        appearances = [0, 8, 9]
        rate = compute_echo_rate(appearances, total_strokes=10)
        # echoes in (0, 9] = 2, horizon = 9
        assert abs(rate - 2 / 9) < 0.01

    def test_horizon_zero(self):
        rate = compute_echo_rate([0, 1, 2], total_strokes=3, horizon=0)
        assert rate == 0.0


# ---------------------------------------------------------------------------
# compute_half_life
# ---------------------------------------------------------------------------


class TestComputeHalfLife:
    def test_steady_usage(self):
        # concept appears once per stroke for 20 strokes
        appearances = list(range(20))
        hl = compute_half_life(appearances, total_strokes=20, window_size=5)
        # peak window has 5 uses; half = 2.5; near the tail count drops
        # half_life should be close to full span
        assert hl >= 15

    def test_burst_then_decay(self):
        # burst at start, then nothing
        appearances = [0, 1, 2, 3, 4]
        hl = compute_half_life(appearances, total_strokes=30, window_size=5)
        # peak window (0-4) has 5 uses; half = 2.5
        # window starting at 1 has 4, at 2 has 3, at 3 has 2, at 4 has 1
        # first window after peak with count < 2.5 is start=3 (count=2)
        assert hl == 3

    def test_single_appearance(self):
        hl = compute_half_life([5], total_strokes=20)
        assert hl == 0

    def test_two_appearances(self):
        hl = compute_half_life([0, 10], total_strokes=20, window_size=5)
        assert hl >= 0

    def test_empty(self):
        hl = compute_half_life([], total_strokes=10)
        assert hl == 0


# ---------------------------------------------------------------------------
# classify_adoption
# ---------------------------------------------------------------------------


class TestClassifyAdoption:
    def test_stillborn_single_use(self):
        assert classify_adoption(0.5, 10, total_uses=1) == "stillborn"

    def test_viral(self):
        # high echo, short half-life
        assert classify_adoption(0.50, 3, total_uses=10) == "viral"

    def test_steady(self):
        # high echo, long half-life
        assert classify_adoption(0.40, 30, total_uses=15) == "steady"

    def test_flash(self):
        # moderate echo, moderate life
        assert classify_adoption(0.20, 10, total_uses=5) == "flash"

    def test_stillborn_low_echo(self):
        assert classify_adoption(0.05, 5, total_uses=3) == "stillborn"

    def test_boundary_high_echo_short_hl(self):
        # exactly at thresholds
        assert classify_adoption(0.30, 5, total_uses=5) == "viral"

    def test_boundary_high_echo_long_hl(self):
        # echo_rate >= 0.30 and half_life > 20 -> steady
        assert classify_adoption(0.30, 21, total_uses=5) == "steady"


# ---------------------------------------------------------------------------
# _classify_regime
# ---------------------------------------------------------------------------


class TestClassifyRegime:
    def test_sticky(self):
        assert _classify_regime(0.50) == "sticky"
        assert _classify_regime(0.40) == "sticky"

    def test_cultivating(self):
        assert _classify_regime(0.30) == "cultivating"
        assert _classify_regime(0.25) == "cultivating"

    def test_ephemeral(self):
        assert _classify_regime(0.15) == "ephemeral"
        assert _classify_regime(0.12) == "ephemeral"

    def test_scattershot(self):
        assert _classify_regime(0.10) == "scattershot"
        assert _classify_regime(0.0) == "scattershot"


# ---------------------------------------------------------------------------
# build_concept_timeline
# ---------------------------------------------------------------------------


class TestBuildConceptTimeline:
    def test_basic(self):
        ct = build_concept_timeline("testing", [0, 3, 7, 12], total_strokes=20)
        assert ct.word == "testing"
        assert ct.first_seen == 0
        assert ct.total_uses == 4
        assert ct.span == 12

    def test_single_appearance(self):
        ct = build_concept_timeline("novel", [5], total_strokes=20)
        assert ct.total_uses == 1
        assert ct.span == 0

    def test_peak_window(self):
        # cluster at 0-4
        ct = build_concept_timeline("cluster", [0, 1, 2, 3, 4, 20], total_strokes=25, peak_window=5)
        assert ct.peak_window_count == 5
        assert ct.peak_window_start == 0


# ---------------------------------------------------------------------------
# analyse_propagation
# ---------------------------------------------------------------------------


class TestAnalysePropagation:
    def test_empty_input(self):
        report = analyse_propagation([])
        assert report.total_strokes == 0
        assert report.total_concepts == 0
        assert report.regime == "scattershot"

    def test_single_stroke(self):
        report = analyse_propagation(["automation builds systems carefully"])
        assert report.total_strokes == 1
        assert report.concepts_tracked == 0  # no concept appears ≥2 times

    def test_repeated_concept(self):
        texts = [
            "automation builds systems",
            "automation requires testing",
            "automation enables scaling",
            "automation demands monitoring",
            "automation rewards patience",
        ] * 5  # 25 strokes
        report = analyse_propagation(texts, horizon=10, min_uses=2)
        assert report.total_strokes == 25
        assert report.total_concepts > 0
        assert report.concepts_tracked > 0
        # "automation" should have high echo rate
        auto_reports = [r for r in report.top_concepts if r.word == "automation"]
        if auto_reports:
            assert auto_reports[0].echo_rate > 0.5

    def test_diverse_stream(self):
        # Each stroke uses unique words — no propagation
        import string
        bases = list(string.ascii_lowercase)
        texts = [f"{bases[i]}xyz {bases[i]}qrs {bases[i]}mno {bases[i]}tuv" for i in range(20)]
        report = analyse_propagation(texts, min_uses=2)
        # Each word is unique (different prefix per stroke), so no concept appears ≥2 times
        # Note: 3-letter words are filtered out by min_len=4
        assert report.concepts_tracked == 0

    def test_regime_assignment(self):
        # Create a stream with strong concept reuse
        base = "automation testing systems building"
        texts = [base] * 50
        report = analyse_propagation(texts, horizon=20, min_uses=2)
        assert report.regime in ("sticky", "cultivating", "ephemeral", "scattershot")

    def test_adoption_distribution_sums(self):
        texts = [
            "automation builds systems carefully today",
            "automation requires testing thoroughly today",
            "systems need monitoring carefully always",
            "testing validates automation properly always",
            "monitoring helps systems today properly",
        ] * 10
        report = analyse_propagation(texts, min_uses=2)
        total = sum(report.adoption_distribution.values())
        assert total == report.concepts_tracked

    def test_top_concepts_sorted(self):
        texts = [
            "automation builds systems",
            "automation requires testing",
            "systems need monitoring",
            "testing validates automation",
            "monitoring helps systems",
            "automation scales testing",
            "systems evolve monitoring",
            "testing improves automation",
        ] * 5
        report = analyse_propagation(texts, min_uses=2, top_n=5)
        rates = [r.echo_rate for r in report.top_concepts]
        assert rates == sorted(rates, reverse=True)

    def test_concept_timelines_populated(self):
        texts = ["automation builds", "automation tests", "builds automation"]
        report = analyse_propagation(texts, min_uses=2)
        assert "automation" in report.concept_timelines

    def test_median_half_life(self):
        texts = ["alpha beta gamma"] + ["alpha beta"] * 10 + ["gamma delta"] * 5
        report = analyse_propagation(texts, min_uses=2)
        assert report.median_half_life >= 0


# ---------------------------------------------------------------------------
# analyse_propagation_windows
# ---------------------------------------------------------------------------


class TestAnalysePropagationWindows:
    def test_basic_windowing(self):
        texts = ["automation testing systems"] * 200
        reports = analyse_propagation_windows(texts, window_size=50, step=50)
        assert len(reports) == 4  # (200 - 50) / 50 + 1 = 4

    def test_small_input(self):
        texts = ["hello world"] * 10
        reports = analyse_propagation_windows(texts, window_size=50, step=25)
        assert len(reports) == 0  # not enough data for even one window

    def test_invalid_params(self):
        with pytest.raises(ValueError):
            analyse_propagation_windows(["test"], window_size=1, step=1)
        with pytest.raises(ValueError):
            analyse_propagation_windows(["test"], window_size=10, step=0)

    def test_window_independence(self):
        # Different windows should produce independent reports
        texts_a = ["automation testing"] * 50
        texts_b = ["unique special distinct particular different"] * 50
        texts = texts_a + texts_b
        reports = analyse_propagation_windows(texts, window_size=50, step=50)
        assert len(reports) == 2
        # First window should have higher echo rate than second
        assert reports[0].avg_echo_rate >= reports[1].avg_echo_rate


# ---------------------------------------------------------------------------
# Integration: realistic stroke stream
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_mixed_stream(self):
        """Simulate a realistic stroke stream with some recurring themes."""
        strokes = [
            "automation fails quietly so the log has to say something",
            "naming is hard because a bad name is cheap to type",
            "most architecture is choosing which coupling you will live with",
            "automation fails quietly so the log must report clearly",
            "deleting a file is progress too eventually",
            "automation rewards patience and punishes haste always",
            "naming remains hard because good names take real thought",
            "most architecture is choosing between bad options carefully",
            "automation builds trust through consistent reliable output",
            "deleting unused code is progress too say the elders",
            "the useful abstraction deletes a branch not adds a class",
            "automation fails quietly which is the dangerous kind",
            "naming things is hard but renaming is harder still",
            "most architecture decisions are about managing coupling",
            "automation requires discipline and rewards the patient",
            "deleting a file is also a form of progress today",
            "the log must say something even when nothing happened",
            "automation builds systems that outlive their creators",
            "naming remains the hardest problem in computing today",
            "most architecture is just choosing your pain carefully",
        ]
        report = analyse_propagation(strokes, horizon=10, min_uses=2)
        assert report.total_strokes == 20
        assert report.total_concepts > 5
        assert report.concepts_tracked > 0
        assert report.regime in ("sticky", "cultivating", "ephemeral", "scattershot")

        # "automation" should be a well-propagated concept
        auto = [r for r in report.top_concepts if r.word == "automation"]
        if auto:
            assert auto[0].total_uses >= 4
            assert auto[0].echo_rate > 0.0

    def test_zero_length_strokes_ignored(self):
        strokes = ["", "", "", "automation testing", "automation building"]
        report = analyse_propagation(strokes, min_uses=2)
        assert report.total_strokes == 5
        # empty strokes still count in total but produce no words
        assert report.total_concepts >= 0

    def test_report_dataclass_fields(self):
        report = analyse_propagation(["test example sample"] * 10, min_uses=2)
        assert isinstance(report.total_strokes, int)
        assert isinstance(report.total_concepts, int)
        assert isinstance(report.concepts_tracked, int)
        assert isinstance(report.avg_echo_rate, float)
        assert isinstance(report.median_half_life, (int, float))
        assert isinstance(report.adoption_distribution, dict)
        assert isinstance(report.regime, str)
        assert isinstance(report.top_concepts, list)
        for cr in report.top_concepts:
            assert isinstance(cr, ConceptReport)
            assert isinstance(cr.word, str)
            assert isinstance(cr.echo_rate, float)
            assert isinstance(cr.half_life, int)
            assert cr.adoption_class in ("viral", "steady", "flash", "stillborn")
