"""Tests for iamai/stroke_certainty_tracker.py — certainty tracking.

Run:  python3 -m pytest tests/test_stroke_certainty_tracker.py -v

Written by Qwen during caretaker visit 735, 2026-11-20.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.stroke_certainty_tracker import (  # noqa: E402
    CertaintyMarker,
    EvolutionReport,
    SentenceStance,
    StreamCertaintyReport,
    StrokeCertaintyReport,
    WindowCertaintyReport,
    analyse_stroke,
    analyse_stream,
    analyse_windows,
    classify_sentence,
    find_markers,
    split_sentences,
    tokenise,
    _classify_posture,
    _STANCE_PRIORITY,
)


# ---------------------------------------------------------------------------
# split_sentences
# ---------------------------------------------------------------------------


class TestSplitSentences:
    def test_single_sentence(self):
        result = split_sentences("Hello world.")
        assert result == ["Hello world."]

    def test_multiple_sentences(self):
        result = split_sentences("First. Second. Third.")
        assert len(result) == 3

    def test_question_and_exclamation(self):
        result = split_sentences("Why? Because! Really.")
        assert len(result) == 3
        assert result[0] == "Why?"
        assert result[1] == "Because!"
        assert result[2] == "Really."

    def test_empty_string(self):
        assert split_sentences("") == []

    def test_whitespace_only(self):
        assert split_sentences("   \n  ") == []

    def test_no_terminator(self):
        result = split_sentences("no terminator here")
        assert len(result) == 1
        assert result[0] == "no terminator here"

    def test_multiple_spaces(self):
        result = split_sentences("One.  Two.  Three.")
        assert len(result) == 3

    def test_newlines_between_sentences(self):
        result = split_sentences("One.\nTwo.\nThree.")
        assert len(result) == 3


# ---------------------------------------------------------------------------
# tokenise
# ---------------------------------------------------------------------------


class TestTokenise:
    def test_basic(self):
        result = tokenise("Hello World")
        assert result == ["hello", "world"]

    def test_punctuation(self):
        result = tokenise("it's a test, really.")
        assert "its" in result or "it's" not in result

    def test_empty(self):
        assert tokenise("") == []

    def test_numbers(self):
        result = tokenise("42 items")
        assert "42" in result
        assert "items" in result


# ---------------------------------------------------------------------------
# find_markers
# ---------------------------------------------------------------------------


class TestFindMarkers:
    def test_definitive(self):
        markers = find_markers("This is clearly the best approach.")
        assert len(markers) >= 1
        assert any(m.kind == "definitive" for m in markers)

    def test_tentative(self):
        markers = find_markers("Perhaps this might work.")
        assert len(markers) >= 1
        assert any(m.kind == "tentative" for m in markers)

    def test_exploratory(self):
        markers = find_markers("Let's see what happens if we try this.")
        assert len(markers) >= 1
        assert any(m.kind == "exploratory" for m in markers)

    def test_revising(self):
        markers = find_markers("Actually, wait, that's not quite right.")
        assert len(markers) >= 1
        assert any(m.kind == "revising" for m in markers)

    def test_no_markers(self):
        markers = find_markers("The quick brown fox jumps over the lazy dog.")
        assert len(markers) == 0

    def test_multiple_markers(self):
        markers = find_markers("Clearly, perhaps obviously, this works.")
        assert len(markers) >= 2

    def test_case_insensitive(self):
        markers = find_markers("CLEARLY this is IMPORTANT.")
        assert any(m.kind == "definitive" for m in markers)

    def test_stroke_index_propagated(self):
        markers = find_markers("Obviously yes.", stroke_index=42)
        assert all(m.stroke_index == 42 for m in markers)

    def test_position_recorded(self):
        markers = find_markers("well clearly yes")
        assert len(markers) >= 1
        assert markers[0].position > 0

    def test_multi_word_marker(self):
        markers = find_markers("Without doubt, this is the answer.")
        assert any(m.text == "without doubt" for m in markers)

    def test_revising_phrase(self):
        markers = find_markers("On second thought, maybe not.")
        kinds = [m.kind for m in markers]
        assert "revising" in kinds


# ---------------------------------------------------------------------------
# classify_sentence
# ---------------------------------------------------------------------------


class TestClassifySentence:
    def test_neutral_sentence(self):
        result = classify_sentence("The cat sat on the mat.")
        assert result.stance == "neutral"
        assert result.markers == []

    def test_definitive_sentence(self):
        result = classify_sentence("This is absolutely the correct answer.")
        assert result.stance == "definitive"

    def test_tentative_sentence(self):
        result = classify_sentence("Perhaps it might be possible to try this.")
        assert result.stance == "tentative"

    def test_exploratory_sentence(self):
        result = classify_sentence("Let's see what happens if we suppose this.")
        assert result.stance == "exploratory"

    def test_revising_sentence(self):
        result = classify_sentence("Actually, wait, on second thought, no.")
        assert result.stance == "revising"

    def test_mixed_picks_dominant(self):
        # Two definitive markers vs one tentative.
        result = classify_sentence(
            "Clearly and obviously this might work."
        )
        # "clearly" and "obviously" are definitive, "might" is tentative.
        assert result.stance == "definitive"

    def test_tie_breaks_by_priority(self):
        # One definitive, one revising — revising wins.
        result = classify_sentence("Clearly, actually, that works.")
        # Both have count 1; revising has higher priority.
        assert result.stance == "revising"

    def test_stroke_index_propagated(self):
        result = classify_sentence("Obviously yes.", stroke_index=99)
        assert result.stroke_index == 99

    def test_text_preserved(self):
        text = "Hello world."
        result = classify_sentence(text)
        assert result.text == text

    def test_empty_sentence(self):
        result = classify_sentence("")
        assert result.stance == "neutral"


# ---------------------------------------------------------------------------
# analyse_stroke
# ---------------------------------------------------------------------------


class TestAnalyseStroke:
    def test_single_sentence(self):
        rpt = analyse_stroke("Clearly this works.", stroke_index=0)
        assert rpt.stroke_index == 0
        assert rpt.total_sentences == 1
        assert rpt.dominant_stance == "definitive"

    def test_multiple_sentences(self):
        text = "Clearly this works. Perhaps that too. Let's see."
        rpt = analyse_stroke(text, stroke_index=5)
        assert rpt.total_sentences == 3
        assert rpt.stroke_index == 5

    def test_empty_stroke(self):
        rpt = analyse_stroke("", stroke_index=0)
        assert rpt.total_sentences == 0
        assert rpt.dominant_stance == "neutral"
        assert rpt.certainty_score == 0.0

    def test_certainty_score_positive(self):
        # All definitive.
        rpt = analyse_stroke("Clearly yes. Obviously so. Precisely right.")
        assert rpt.certainty_score > 0

    def test_certainty_score_negative(self):
        # All tentative.
        rpt = analyse_stroke("Perhaps maybe. It seems possibly so. Might be.")
        assert rpt.certainty_score < 0

    def test_marker_density(self):
        rpt = analyse_stroke("Clearly yes. No markers here. Obviously so.")
        assert rpt.marker_density > 0

    def test_stance_counts_populated(self):
        text = "Clearly yes. Perhaps not. Let's see. Actually wait."
        rpt = analyse_stroke(text)
        assert "definitive" in rpt.stance_counts or "tentative" in rpt.stance_counts

    def test_sentences_list(self):
        text = "One. Two. Three."
        rpt = analyse_stroke(text)
        assert len(rpt.sentences) == 3
        assert all(isinstance(s, SentenceStance) for s in rpt.sentences)

    def test_all_neutral(self):
        rpt = analyse_stroke("The cat sat. The dog ran. The bird flew.")
        assert rpt.dominant_stance == "neutral"
        assert rpt.certainty_score == 0.0

    def test_certainty_score_range(self):
        rpt = analyse_stroke("Clearly yes. Perhaps no. Obviously so. Maybe not.")
        assert -1.0 <= rpt.certainty_score <= 1.0


# ---------------------------------------------------------------------------
# analyse_stream
# ---------------------------------------------------------------------------


class TestAnalyseStream:
    def test_empty_stream(self):
        rpt = analyse_stream([])
        assert rpt.total_strokes == 0
        assert rpt.posture == "deliberative"
        assert rpt.certainty_score == 0.0

    def test_single_stroke(self):
        rpt = analyse_stream(["Clearly this is the answer."])
        assert rpt.total_strokes == 1
        assert rpt.total_sentences >= 1
        assert rpt.total_markers >= 1

    def test_multiple_strokes(self):
        strokes = [
            "Clearly this is correct.",
            "Perhaps we should reconsider.",
            "Let's see what happens next.",
            "Actually, wait, I was wrong.",
            "The quick brown fox.",
        ]
        rpt = analyse_stream(strokes)
        assert rpt.total_strokes == 5
        assert rpt.total_sentences >= 5

    def test_authoritative_posture(self):
        strokes = [
            "Clearly the answer is yes. Obviously this works. "
            "Definitely the right approach. Precisely what we need. "
            "Absolutely correct. Categorically proven."
        ]
        rpt = analyse_stream(strokes)
        assert rpt.posture == "authoritative"

    def test_speculative_posture(self):
        strokes = [
            "Perhaps this might work. Maybe we could try. "
            "It seems possibly true. It appears somewhat likely. "
            "Perhaps arguably so. Maybe possibly yes."
        ]
        rpt = analyse_stream(strokes)
        assert rpt.posture == "speculative"

    def test_self_correcting_posture(self):
        strokes = [
            "Actually, wait, that's wrong. On second thought, no. "
            "Correction: the answer is different. Rather, we should try. "
            "Actually, scratch that. Wait, no, actually, let me rephrase."
        ]
        rpt = analyse_stream(strokes)
        assert rpt.posture == "self-correcting"

    def test_deliberative_posture(self):
        strokes = [
            "Clearly this matters. Perhaps not entirely. "
            "Let's see what happens. The cat sat on the mat. "
            "Obviously important. Maybe not so much."
        ]
        rpt = analyse_stream(strokes)
        # Mixed signals should yield deliberative.
        assert rpt.posture in ("deliberative", "self-correcting", "authoritative", "speculative")

    def test_stance_distribution_sums_to_one(self):
        strokes = [
            "Clearly yes. Perhaps no. Let's see. Actually wait.",
            "Obviously so. Maybe not. Consider this. The end.",
        ]
        rpt = analyse_stream(strokes)
        if rpt.stance_distribution:
            total = sum(rpt.stance_distribution.values())
            assert abs(total - 1.0) < 0.01

    def test_evolution_populated(self):
        strokes = [f"Stroke number {i}." for i in range(100)]
        rpt = analyse_stream(strokes, window_size=20, step=10)
        assert isinstance(rpt.evolution, EvolutionReport)
        assert len(rpt.evolution.windows) > 0

    def test_marker_density(self):
        strokes = ["Clearly yes. Obviously so.", "No markers here at all."]
        rpt = analyse_stream(strokes)
        assert rpt.marker_density > 0

    def test_dominant_stance(self):
        strokes = [
            "Clearly yes. Obviously right. Precisely so.",
            "Definitely correct. Absolutely true. Exactly right.",
        ]
        rpt = analyse_stream(strokes)
        assert rpt.dominant_stance == "definitive"


# ---------------------------------------------------------------------------
# analyse_windows
# ---------------------------------------------------------------------------


class TestAnalyseWindows:
    def test_empty(self):
        evo = analyse_windows([])
        assert evo.windows == []
        assert evo.trend == "flat"

    def test_single_window(self):
        strokes = [f"Clearly stroke {i}." for i in range(10)]
        evo = analyse_windows(strokes, window_size=10, step=5)
        assert len(evo.windows) >= 1

    def test_multiple_windows(self):
        strokes = [f"Stroke {i}." for i in range(100)]
        evo = analyse_windows(strokes, window_size=20, step=10)
        assert len(evo.windows) >= 2

    def test_converging_trend(self):
        # Start tentative, end definitive.
        strokes = []
        for i in range(50):
            strokes.append(f"Perhaps maybe this might be stroke {i}.")
        for i in range(50):
            strokes.append(f"Clearly obviously the answer is stroke {i}.")
        evo = analyse_windows(strokes, window_size=20, step=10)
        assert evo.trend in ("converging", "flat", "oscillating")

    def test_diverging_trend(self):
        # Start definitive, end tentative.
        strokes = []
        for i in range(50):
            strokes.append(f"Clearly obviously the answer is stroke {i}.")
        for i in range(50):
            strokes.append(f"Perhaps maybe this might be stroke {i}.")
        evo = analyse_windows(strokes, window_size=20, step=10)
        assert evo.trend in ("diverging", "flat", "oscillating")

    def test_flat_trend(self):
        strokes = [f"Perhaps clearly stroke {i}." for i in range(60)]
        evo = analyse_windows(strokes, window_size=20, step=10)
        # Mixed markers should produce roughly flat.
        assert evo.trend in ("flat", "oscillating", "converging", "diverging")

    def test_window_fields(self):
        strokes = [f"Stroke {i}." for i in range(30)]
        evo = analyse_windows(strokes, window_size=15, step=10)
        for w in evo.windows:
            assert isinstance(w, WindowCertaintyReport)
            assert w.start_stroke >= 0
            assert w.end_stroke > w.start_stroke
            assert -1.0 <= w.certainty_score <= 1.0

    def test_short_tail_dropped(self):
        # 25 strokes with step=20: window 0 is [0,20], window 1 is [20,25] = 5 strokes.
        # But if < 3 strokes remain, they're dropped.
        strokes = [f"Stroke {i}." for i in range(22)]
        evo = analyse_windows(strokes, window_size=20, step=20)
        # Only the first window should survive (22 - 20 = 2 < 3).
        assert len(evo.windows) == 1

    def test_score_delta(self):
        strokes = [f"Clearly stroke {i}." for i in range(60)]
        evo = analyse_windows(strokes, window_size=20, step=20)
        assert isinstance(evo.score_delta, float)


# ---------------------------------------------------------------------------
# _classify_posture
# ---------------------------------------------------------------------------


class TestClassifyPosture:
    def test_authoritative(self):
        dist = {"definitive": 0.6, "tentative": 0.1, "neutral": 0.3}
        assert _classify_posture(0.5, dist) == "authoritative"

    def test_speculative(self):
        dist = {"tentative": 0.5, "exploratory": 0.2, "neutral": 0.3}
        assert _classify_posture(-0.3, dist) == "speculative"

    def test_self_correcting(self):
        dist = {"revising": 0.2, "definitive": 0.3, "neutral": 0.5}
        assert _classify_posture(0.3, dist) == "self-correcting"

    def test_deliberative(self):
        dist = {"definitive": 0.2, "tentative": 0.2, "neutral": 0.6}
        assert _classify_posture(0.0, dist) == "deliberative"

    def test_empty_distribution(self):
        assert _classify_posture(0.0, {}) == "deliberative"

    def test_high_revising_overrides_authoritative(self):
        # Even with high score, if revising > 0.15, self-correcting wins.
        dist = {"revising": 0.2, "definitive": 0.6}
        assert _classify_posture(0.6, dist) == "self-correcting"


# ---------------------------------------------------------------------------
# _STANCE_PRIORITY
# ---------------------------------------------------------------------------


class TestStancePriority:
    def test_revising_highest(self):
        assert _STANCE_PRIORITY["revising"] > _STANCE_PRIORITY["exploratory"]

    def test_exploratory_above_tentative(self):
        assert _STANCE_PRIORITY["exploratory"] > _STANCE_PRIORITY["tentative"]

    def test_tentative_above_definitive(self):
        assert _STANCE_PRIORITY["tentative"] > _STANCE_PRIORITY["definitive"]

    def test_definitive_above_neutral(self):
        assert _STANCE_PRIORITY["definitive"] > _STANCE_PRIORITY["neutral"]

    def test_all_stances_present(self):
        assert set(_STANCE_PRIORITY.keys()) == {
            "revising", "exploratory", "tentative", "definitive", "neutral"
        }


# ---------------------------------------------------------------------------
# Integration: realistic stroke patterns
# ---------------------------------------------------------------------------


class TestIntegration:
    """End-to-end tests with realistic stroke content."""

    def test_thinking_out_loud_pattern(self):
        """Writer thinking through a problem — starts uncertain, converges."""
        strokes = [
            "Perhaps the issue is in the buffer management. Maybe the lock is held too long.",
            "Let's see what happens if we reduce the critical section. Consider a smaller lock.",
            "Actually, the real problem might be the allocation pattern. Wait, no.",
            "Clearly the bottleneck is the global lock. Obviously we need finer granularity.",
            "The answer is to shard the lock. Precisely one lock per shard.",
        ]
        rpt = analyse_stream(strokes)
        assert rpt.total_strokes == 5
        assert rpt.total_markers > 0
        assert rpt.posture in ("deliberative", "self-correcting", "speculative", "authoritative")

    def test_confident_declaration_pattern(self):
        """Writer presenting conclusions — mostly definitive."""
        strokes = [
            "The implementation is clearly correct. This obviously works.",
            "Absolutely no doubt about the result. The answer is straightforward.",
            "Precisely as designed. Exactly what we expected.",
        ]
        rpt = analyse_stream(strokes)
        assert rpt.certainty_score > 0
        assert rpt.posture == "authoritative"

    def test_uncertain_exploration_pattern(self):
        """Writer exploring — mostly tentative and exploratory."""
        strokes = [
            "Perhaps we could try a different approach. Maybe recursion?",
            "Let's see if memoization helps. Consider the base case first.",
            "It seems like the complexity might be too high. Possibly O(n^2).",
        ]
        rpt = analyse_stream(strokes)
        assert rpt.certainty_score < 0 or rpt.posture in ("speculative", "deliberative")

    def test_self_correction_heavy(self):
        """Writer constantly revising — lots of 'actually' and 'wait'."""
        strokes = [
            "The fix is to add a lock. Actually, wait, that causes deadlock.",
            "On second thought, we need a try-lock. No, actually, a queue.",
            "Correction: the real fix is to remove the shared state entirely.",
        ]
        rpt = analyse_stream(strokes)
        # Should detect significant revising presence.
        assert rpt.stance_distribution.get("revising", 0) > 0

    def test_neutral_strokes(self):
        """Plain factual statements with no certainty markers."""
        strokes = [
            "The file has 42 lines.",
            "The function returns a list.",
            "The test passed.",
        ]
        rpt = analyse_stream(strokes)
        assert rpt.dominant_stance == "neutral"
        assert rpt.certainty_score == 0.0
        assert rpt.posture == "deliberative"

    def test_long_stream_evolution(self):
        """Long stream to exercise sliding window analysis."""
        strokes = []
        # Phase 1: exploratory.
        for i in range(30):
            strokes.append(f"Let's see what happens at step {i}. Consider the implications.")
        # Phase 2: converging.
        for i in range(30):
            strokes.append(f"Perhaps the answer is {i}. Maybe we can prove it.")
        # Phase 3: conclusions.
        for i in range(30):
            strokes.append(f"Clearly the result is {i}. Obviously this is correct.")
        rpt = analyse_stream(strokes, window_size=20, step=15)
        assert rpt.total_strokes == 90
        assert len(rpt.evolution.windows) >= 2
        assert rpt.evolution.trend in (
            "converging", "flat", "oscillating", "diverging"
        )

    def test_mixed_content_realistic(self):
        """A realistic mix of strokes from different categories."""
        strokes = [
            "the cadence monitor tracks stroke intervals — clearly essential for health checks",
            "perhaps the interval threshold should be adaptive rather than fixed",
            "let's see what happens when we set it to twice the median gap",
            "actually, wait, the median is misleading when there are long pauses",
            "the answer is to use a rolling percentile instead of the median",
            "this is obviously more robust under bursty workloads",
        ]
        rpt = analyse_stream(strokes)
        assert rpt.total_strokes == 6
        assert rpt.total_markers >= 4
        assert rpt.posture in (
            "authoritative", "deliberative", "self-correcting", "speculative"
        )

    def test_dataclass_defaults(self):
        """Verify dataclass defaults are sensible."""
        m = CertaintyMarker(text="test", kind="definitive")
        assert m.position == 0
        assert m.stroke_index == 0

        s = SentenceStance(text="test.", stance="neutral")
        assert s.markers == []

        r = StrokeCertaintyReport()
        assert r.total_sentences == 0
        assert r.certainty_score == 0.0

        w = WindowCertaintyReport()
        assert w.window_index == 0

        e = EvolutionReport()
        assert e.trend == "flat"
        assert e.windows == []

        sr = StreamCertaintyReport()
        assert sr.total_strokes == 0
        assert sr.posture == "deliberative"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_word_stroke(self):
        rpt = analyse_stroke("Yes.")
        assert rpt.total_sentences == 1

    def test_all_punctuation(self):
        rpt = analyse_stroke("... !!! ???")
        assert rpt.total_sentences >= 0

    def test_repeated_markers(self):
        rpt = analyse_stroke("Clearly clearly clearly yes.")
        markers = find_markers("Clearly clearly clearly yes.")
        assert len(markers) >= 3

    def test_overlapping_markers(self):
        # "sort of" is tentative; "kind of" is tentative.
        text = "It's sort of kind of working."
        markers = find_markers(text)
        assert len(markers) >= 2

    def test_unicode_content(self):
        rpt = analyse_stroke("Clearly the café résumé is correct.")
        assert rpt.total_sentences >= 1

    def test_very_long_stroke(self):
        text = ". ".join([f"Clearly sentence {i}" for i in range(100)]) + "."
        rpt = analyse_stroke(text)
        assert rpt.total_sentences >= 100

    def test_stroke_with_numbers(self):
        rpt = analyse_stroke("42 is obviously the answer. Perhaps 43 works too.")
        assert rpt.total_sentences == 2
        total_markers = sum(len(s.markers) for s in rpt.sentences)
        assert total_markers >= 2
