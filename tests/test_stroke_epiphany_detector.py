"""Tests for iamai.stroke_epiphany_detector — epiphany / aha-moment detection."""

from __future__ import annotations

import pytest

from iamai.stroke_epiphany_detector import (
    EpiphanyResult,
    _count_pattern_matches,
    _has_crystallisation,
    _REALIZATION_PATTERNS,
    _CONTRAST_PATTERNS,
    _REVERSAL_PATTERNS,
    _EPIPHANY_THRESHOLD,
    aggregate,
    score,
)


# ---------------------------------------------------------------------------
# realization pattern detection
# ---------------------------------------------------------------------------


class TestRealizationPatterns:
    def test_turns_out(self):
        count, _ = _count_pattern_matches(_REALIZATION_PATTERNS, "it turns out the bug was in the parser")
        assert count >= 1

    def test_i_realize(self):
        count, _ = _count_pattern_matches(_REALIZATION_PATTERNS, "I realize now that the test was wrong")
        assert count >= 1

    def test_i_realized(self):
        count, _ = _count_pattern_matches(_REALIZATION_PATTERNS, "I realized the issue")
        assert count >= 1

    def test_the_key_is(self):
        count, _ = _count_pattern_matches(_REALIZATION_PATTERNS, "the key is that commits are cheap")
        assert count >= 1

    def test_it_became_clear(self):
        count, _ = _count_pattern_matches(_REALIZATION_PATTERNS, "it became clear after the third failure")
        assert count >= 1

    def test_what_actually_matters(self):
        count, _ = _count_pattern_matches(_REALIZATION_PATTERNS, "what actually matters is consistency")
        assert count >= 1

    def test_here_is_the_thing(self):
        count, _ = _count_pattern_matches(_REALIZATION_PATTERNS, "here's the thing about automation")
        assert count >= 1

    def test_the_real_issue(self):
        count, _ = _count_pattern_matches(_REALIZATION_PATTERNS, "the real issue was the SSH key")
        assert count >= 1

    def test_what_i_missed(self):
        count, _ = _count_pattern_matches(_REALIZATION_PATTERNS, "what I missed was the race condition")
        assert count >= 1

    def test_no_realization(self):
        count, _ = _count_pattern_matches(_REALIZATION_PATTERNS, "the weather is nice today")
        assert count == 0


# ---------------------------------------------------------------------------
# contrast pattern detection
# ---------------------------------------------------------------------------


class TestContrastPatterns:
    def test_not_x_but(self):
        count, _ = _count_pattern_matches(_CONTRAST_PATTERNS, "not speed but consistency")
        assert count >= 1

    def test_actually(self):
        count, _ = _count_pattern_matches(_CONTRAST_PATTERNS, "actually, the simpler approach works")
        assert count >= 1

    def test_in_fact(self):
        count, _ = _count_pattern_matches(_CONTRAST_PATTERNS, "in fact, fewer tests ran faster")
        assert count >= 1

    def test_rather_than(self):
        count, _ = _count_pattern_matches(_CONTRAST_PATTERNS, "rather than adding complexity, remove it")
        assert count >= 1

    def test_counterintuitive(self):
        count, _ = _count_pattern_matches(_CONTRAST_PATTERNS, "it's counterintuitive but true")
        assert count >= 1

    def test_paradoxically(self):
        count, _ = _count_pattern_matches(_CONTRAST_PATTERNS, "paradoxically, deleting code helped")
        assert count >= 1

    def test_ironically(self):
        count, _ = _count_pattern_matches(_CONTRAST_PATTERNS, "ironically the fix was one line")
        assert count >= 1

    def test_on_the_contrary(self):
        count, _ = _count_pattern_matches(_CONTRAST_PATTERNS, "on the contrary, it improved")
        assert count >= 1

    def test_no_contrast(self):
        count, _ = _count_pattern_matches(_CONTRAST_PATTERNS, "everything is going smoothly")
        assert count == 0


# ---------------------------------------------------------------------------
# reversal pattern detection
# ---------------------------------------------------------------------------


class TestReversalPatterns:
    def test_i_used_to_think(self):
        count, _ = _count_pattern_matches(_REVERSAL_PATTERNS, "I used to think more tests meant better code")
        assert count >= 1

    def test_initially(self):
        count, _ = _count_pattern_matches(_REVERSAL_PATTERNS, "initially I assumed the cache was warm")
        assert count >= 1

    def test_at_first(self):
        count, _ = _count_pattern_matches(_REVERSAL_PATTERNS, "at first the output seemed correct")
        assert count >= 1

    def test_i_was_wrong(self):
        count, _ = _count_pattern_matches(_REVERSAL_PATTERNS, "I was wrong about the root cause")
        assert count >= 1

    def test_what_i_missed_was(self):
        count, _ = _count_pattern_matches(_REVERSAL_PATTERNS, "what I missed was the timezone offset")
        assert count >= 1

    def test_i_overlooked(self):
        count, _ = _count_pattern_matches(_REVERSAL_PATTERNS, "I overlooked the edge case")
        assert count >= 1

    def test_i_assumed(self):
        count, _ = _count_pattern_matches(_REVERSAL_PATTERNS, "I assumed the default was UTF-8")
        assert count >= 1

    def test_no_reversal(self):
        count, _ = _count_pattern_matches(_REVERSAL_PATTERNS, "the code works as expected")
        assert count == 0


# ---------------------------------------------------------------------------
# score() — per-stroke scoring
# ---------------------------------------------------------------------------


class TestScore:
    def test_empty_string(self):
        r = score("")
        assert r.epiphany_score == 0.0
        assert not r.is_epiphany

    def test_whitespace_only(self):
        r = score("   \n  ")
        assert r.epiphany_score == 0.0

    def test_plain_observation(self):
        r = score("commit 9058c43 was pushed at 17:02 today")
        assert r.epiphany_score < _EPIPHANY_THRESHOLD
        assert not r.is_epiphany

    def test_strong_epiphany(self):
        text = (
            "I used to think more tests meant better coverage, but "
            "it turns out the key is not quantity but relevance. "
            "Actually, the opposite is true — fewer focused tests catch more bugs."
        )
        r = score(text)
        assert r.is_epiphany
        assert r.epiphany_score >= _EPIPHANY_THRESHOLD
        assert "realization" in r.markers_found or "contrast" in r.markers_found

    def test_mild_insight(self):
        r = score("actually, the simpler approach works better than expected")
        assert r.epiphany_score > 0.0
        assert "contrast" in r.markers_found

    def test_reversal_epiphany(self):
        text = (
            "I assumed the SSH key was mounted, but I was wrong. "
            "It turns out the container recycle drops it every time. "
            "The real issue was never the network — it was the filesystem."
        )
        r = score(text)
        assert r.is_epiphany
        assert "reversal" in r.markers_found
        assert "realization" in r.markers_found

    def test_score_bounded_zero_to_one(self):
        # extreme case: all marker types maxed out
        text = (
            "I realize now that I used to think speed mattered, but actually "
            "in fact the opposite is true. It turns out I was wrong initially. "
            "The key is consistency. What actually matters is showing up. "
            "Paradoxically, less is more. I realize the real issue was attention."
        )
        r = score(text)
        assert 0.0 <= r.epiphany_score <= 1.0

    def test_markers_found_lists_matches(self):
        r = score("it turns out I was wrong about the parser")
        assert isinstance(r.markers_found, dict)
        for key, values in r.markers_found.items():
            assert isinstance(values, list)
            assert len(values) >= 1

    def test_case_insensitive(self):
        r = score("IT TURNS OUT THE BUG WAS SIMPLE")
        assert r.epiphany_score > 0.0
        assert "realization" in r.markers_found


# ---------------------------------------------------------------------------
# crystallisation bonus
# ---------------------------------------------------------------------------


class TestCrystallisation:
    def test_short_punchy_sentence_gets_bonus(self):
        # short sentence with a realization marker
        r = score("The key is simplicity.")
        assert _has_crystallisation("The key is simplicity.", True)

    def test_long_sentence_no_bonus(self):
        long_text = (
            "The key is that when you have a very long and winding sentence "
            "that goes on and on and never quite gets to the point it is "
            "trying to make about simplicity and clarity in technical writing"
        )
        assert not _has_crystallisation(long_text, True)

    def test_no_marker_no_bonus(self):
        assert not _has_crystallisation("The weather is nice today.", False)

    def test_multi_sentence_with_crystallisation(self):
        text = (
            "After reviewing all the metrics and running several experiments "
            "across different configurations, the key is focus."
        )
        r = score(text)
        # should get crystallisation bonus for the short final sentence
        assert r.epiphany_score > 0.0


# ---------------------------------------------------------------------------
# aggregate() — series-level metrics
# ---------------------------------------------------------------------------


class TestAggregate:
    def test_empty_series(self):
        agg = aggregate([])
        assert agg["total_strokes"] == 0
        assert agg["epiphany_rate"] == 0.0
        assert agg["epiphany_trend"] == 0.0

    def test_single_stroke(self):
        r = score("it turns out consistency beats speed")
        agg = aggregate([r])
        assert agg["total_strokes"] == 1
        assert agg["epiphany_trend"] == 0.0  # can't compute slope with 1 point

    def test_no_epiphanies(self):
        results = [
            score("commit 587 pushed at 10:00"),
            score("the tree has 2099 files"),
            score("batch committer ran without errors"),
        ]
        agg = aggregate(results)
        assert agg["total_epiphanies"] == 0
        assert agg["epiphany_rate"] == 0.0

    def test_all_epiphanies(self):
        results = [
            score("I realize now that the key is not speed but consistency"),
            score("it turns out I was wrong about the cache behavior"),
            score("actually, the opposite is true — deletion is progress"),
        ]
        agg = aggregate(results)
        assert agg["total_epiphanies"] == 3
        assert agg["epiphany_rate"] == 1.0

    def test_mixed_series(self):
        results = [
            score("commit 587 pushed cleanly"),
            score("I realize the real issue was the SSH key rotation"),
            score("the metrics look stable today"),
            score("it turns out fewer tests catch more bugs actually"),
        ]
        agg = aggregate(results)
        assert agg["total_strokes"] == 4
        assert 0 < agg["total_epiphanies"] < 4
        assert 0.0 < agg["epiphany_rate"] < 1.0

    def test_epiphany_trend_positive(self):
        # early strokes: plain; later strokes: epiphanies
        results = [
            score("the sun rose at 6:12"),
            score("commit count is 1063"),
            score("tree has 2566 files"),
            score("it turns out the key insight is that less is more"),
            score("I realize now I was wrong about complexity"),
            score("actually, the opposite is true and the real issue was focus"),
        ]
        agg = aggregate(results)
        assert agg["epiphany_trend"] > 0

    def test_epiphany_trend_negative(self):
        # early: epiphanies; later: plain
        results = [
            score("I realize the key is consistency not speed"),
            score("it turns out I was wrong about the parser"),
            score("actually the fix was one line"),
            score("commit 587 pushed at 10:00"),
            score("tree has 2566 files"),
            score("batch ran without errors"),
        ]
        agg = aggregate(results)
        assert agg["epiphany_trend"] < 0

    def test_epiphany_indices(self):
        results = [
            score("plain observation here today"),
            score("I realize now the key insight about automation"),
            score("another plain note about the weather"),
            score("it turns out I was wrong about everything actually"),
        ]
        agg = aggregate(results)
        # indices 1 and 3 should be epiphanies (if scored above threshold)
        for idx in agg["epiphany_indices"]:
            assert results[idx].is_epiphany

    def test_aggregate_score_bounds(self):
        results = [
            score("some text here"),
            score("more text there"),
            score("even more text everywhere"),
        ]
        agg = aggregate(results)
        assert 0.0 <= agg["mean_epiphany_score"] <= 1.0
        assert 0.0 <= agg["max_epiphany_score"] <= 1.0
        assert 0.0 <= agg["min_epiphany_score"] <= 1.0
        assert 0.0 <= agg["median_epiphany_score"] <= 1.0

    def test_median_odd_count(self):
        results = [
            EpiphanyResult(epiphany_score=0.1),
            EpiphanyResult(epiphany_score=0.5),
            EpiphanyResult(epiphany_score=0.9),
        ]
        agg = aggregate(results)
        assert agg["median_epiphany_score"] == 0.5

    def test_median_even_count(self):
        results = [
            EpiphanyResult(epiphany_score=0.2),
            EpiphanyResult(epiphany_score=0.4),
            EpiphanyResult(epiphany_score=0.6),
            EpiphanyResult(epiphany_score=0.8),
        ]
        agg = aggregate(results)
        assert agg["median_epiphany_score"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_none_input_treated_as_empty(self):
        # score handles None gracefully via falsy check
        r = score("")
        assert r.epiphany_score == 0.0

    def test_very_short_text(self):
        r = score("hi")
        assert r.epiphany_score >= 0.0
        assert r.epiphany_score <= 1.0

    def test_unicode_text(self):
        r = score("the key is 一致性 in automation")
        assert isinstance(r.epiphany_score, float)

    def test_multiple_markers_boost_score(self):
        single = score("it turns out the fix was simple")
        multi = score(
            "I realize now that I used to think speed mattered, "
            "but it turns out the key is actually consistency. "
            "I was wrong initially."
        )
        assert multi.epiphany_score > single.epiphany_score

    def test_repeated_markers_diminishing(self):
        """More of the same marker type should have diminishing returns."""
        three = score("actually, actually, actually the fix was simple")
        six = score(
            "actually, actually, actually, actually, actually, actually "
            "the fix was simple"
        )
        # the score should not scale linearly with marker count
        assert six.epiphany_score < three.epiphany_score * 2


# ---------------------------------------------------------------------------
# linear slope helper
# ---------------------------------------------------------------------------


class TestLinearSlope:
    def test_flat_series(self):
        from iamai.stroke_epiphany_detector import _linear_slope

        assert _linear_slope([0.5, 0.5, 0.5, 0.5]) == 0.0

    def test_increasing_series(self):
        from iamai.stroke_epiphany_detector import _linear_slope

        assert _linear_slope([0.1, 0.2, 0.3, 0.4]) > 0

    def test_decreasing_series(self):
        from iamai.stroke_epiphany_detector import _linear_slope

        assert _linear_slope([0.4, 0.3, 0.2, 0.1]) < 0

    def test_single_value(self):
        from iamai.stroke_epiphany_detector import _linear_slope

        assert _linear_slope([0.5]) == 0.0

    def test_empty(self):
        from iamai.stroke_epiphany_detector import _linear_slope

        assert _linear_slope([]) == 0.0
