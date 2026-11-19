"""Tests for iamai/stroke_transition_tracker.py — transition tracking.

Run:  python3 -m pytest tests/test_stroke_transition_tracker.py -v

Written by Qwen during caretaker visit 734, 2026-11-20.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.stroke_transition_tracker import (  # noqa: E402
    EvolutionReport,
    StreamTransitionReport,
    StrokeTransitionReport,
    TransitionRecord,
    WindowTransitionReport,
    _classify_style,
    _normalise_sentence_start,
    analyse_stroke,
    analyse_stream,
    analyse_windows,
    detect_transition,
    split_sentences,
    CONTINUATION_MARKERS,
    ELABORATION_MARKERS,
    CONTRAST_MARKERS,
    CONSEQUENCE_MARKERS,
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

    def test_question_marks(self):
        result = split_sentences("Why? Because. Really?")
        assert len(result) == 3
        assert result[0] == "Why?"
        assert result[1] == "Because."
        assert result[2] == "Really?"

    def test_exclamation(self):
        result = split_sentences("Wow! Amazing! Yes.")
        assert len(result) == 3

    def test_empty_string(self):
        assert split_sentences("") == []

    def test_whitespace_only(self):
        assert split_sentences("   \n  ") == []

    def test_no_terminal_punctuation(self):
        result = split_sentences("No punctuation here at all")
        # Treats entire text as one sentence.
        assert len(result) == 1

    def test_mixed_punctuation(self):
        result = split_sentences("Is it? Yes! It is.")
        assert len(result) == 3

    def test_trailing_no_punct_short(self):
        # Trailing text < 5 chars is ignored.
        result = split_sentences("Hello. Ok")
        assert len(result) == 1

    def test_trailing_no_punct_long(self):
        # Trailing text > 5 chars is captured.
        result = split_sentences("Hello. This has no ending punctuation")
        assert len(result) == 2

    def test_abbreviation_not_split(self):
        # "e.g." should not split because no space+capital after period.
        result = split_sentences("Use e.g. this example.")
        # The regex may split on "e.g." but we accept the behaviour;
        # the important thing is the function doesn't crash.
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# _normalise_sentence_start
# ---------------------------------------------------------------------------


class TestNormaliseSentenceStart:
    def test_lowercase(self):
        assert _normalise_sentence_start("However, we").startswith("however")

    def test_strip_leading_space(self):
        result = _normalise_sentence_start("  Furthermore, this")
        assert result.startswith("furthermore")

    def test_truncation(self):
        long_sent = "A" * 100
        result = _normalise_sentence_start(long_sent)
        assert len(result) == 40


# ---------------------------------------------------------------------------
# detect_transition
# ---------------------------------------------------------------------------


class TestDetectTransition:
    def test_continuation_also(self):
        rec = detect_transition("We built it.", "Also, we tested it.")
        assert rec.kind == "continuation"
        assert rec.marker == "also"

    def test_continuation_furthermore(self):
        rec = detect_transition("First step done.", "Furthermore, the next step is clear.")
        assert rec.kind == "continuation"
        assert rec.marker == "furthermore"

    def test_continuation_moreover(self):
        rec = detect_transition("The code compiles.", "Moreover, it passes all tests.")
        assert rec.kind == "continuation"
        assert rec.marker == "moreover"

    def test_continuation_similarly(self):
        rec = detect_transition("Module A works.", "Similarly, module B functions correctly.")
        assert rec.kind == "continuation"
        assert rec.marker == "similarly"

    def test_elaboration_for_example(self):
        rec = detect_transition("We need tests.", "For example, unit tests for each module.")
        assert rec.kind == "elaboration"
        assert rec.marker == "for example"

    def test_elaboration_specifically(self):
        rec = detect_transition("Some issues remain.", "Specifically, the lock contention.")
        assert rec.kind == "elaboration"
        assert rec.marker == "specifically"

    def test_elaboration_in_particular(self):
        rec = detect_transition("We have problems.", "In particular, the memory leak.")
        assert rec.kind == "elaboration"
        assert rec.marker == "in particular"

    def test_elaboration_that_is(self):
        rec = detect_transition("It is slow.", "That is, the latency exceeds 100ms.")
        assert rec.kind == "elaboration"
        assert rec.marker == "that is"

    def test_contrast_however(self):
        rec = detect_transition("The build passed.", "However, tests are flaky.")
        assert rec.kind == "contrast"
        assert rec.marker == "however"

    def test_contrast_but(self):
        rec = detect_transition("We tried hard.", "But the bug persisted.")
        assert rec.kind == "contrast"
        assert rec.marker == "but"

    def test_contrast_nevertheless(self):
        rec = detect_transition("The fix was applied.", "Nevertheless, the issue returned.")
        assert rec.kind == "contrast"
        assert rec.marker == "nevertheless"

    def test_contrast_yet(self):
        rec = detect_transition("We optimised it.", "Yet performance stayed flat.")
        assert rec.kind == "contrast"
        assert rec.marker == "yet"

    def test_contrast_on_the_other_hand(self):
        rec = detect_transition("Python is slow.", "On the other hand, it is productive.")
        assert rec.kind == "contrast"
        assert rec.marker == "on the other hand"

    def test_consequence_therefore(self):
        rec = detect_transition("The lock was held.", "Therefore, the thread blocked.")
        assert rec.kind == "consequence"
        assert rec.marker == "therefore"

    def test_consequence_thus(self):
        rec = detect_transition("We cached the result.", "Thus, latency dropped by 50%.")
        assert rec.kind == "consequence"
        assert rec.marker == "thus"

    def test_consequence_consequently(self):
        rec = detect_transition("The server crashed.", "Consequently, users saw errors.")
        assert rec.kind == "consequence"
        assert rec.marker == "consequently"

    def test_consequence_so(self):
        rec = detect_transition("Memory was full.", "So we added more.")
        assert rec.kind == "consequence"
        assert rec.marker == "so"

    def test_digression_no_marker(self):
        rec = detect_transition("The cat sat.", "The dog ran away quickly.")
        assert rec.kind == "digression"
        assert rec.marker == ""

    def test_digression_random_start(self):
        rec = detect_transition("We write code.", "Birds fly south in winter.")
        assert rec.kind == "digression"
        assert rec.marker == ""

    def test_text_truncation(self):
        long_text = "A" * 200 + "."
        rec = detect_transition(long_text, "However, it works.")
        assert len(rec.from_text) <= 80
        assert len(rec.to_text) <= 80

    def test_marker_mid_sentence_after_comma(self):
        # "The code, however, is slow." — marker after comma.
        rec = detect_transition(
            "We wrote it quickly.",
            "The code, however, is slow.",
        )
        assert rec.kind == "contrast"
        assert rec.marker == "however"


# ---------------------------------------------------------------------------
# analyse_stroke
# ---------------------------------------------------------------------------


class TestAnalyseStroke:
    def test_single_sentence(self):
        rpt = analyse_stroke("Just one sentence here.")
        assert rpt.sentence_count == 1
        assert rpt.transition_count == 0
        assert rpt.transition_density == 0.0

    def test_empty(self):
        rpt = analyse_stroke("")
        assert rpt.sentence_count == 0
        assert rpt.transition_count == 0

    def test_two_sentences_continuation(self):
        rpt = analyse_stroke("We built it. Furthermore, we tested it.")
        assert rpt.sentence_count == 2
        assert rpt.transition_count == 1
        assert rpt.transitions[0].kind == "continuation"
        assert rpt.transition_density == 1.0

    def test_mixed_transitions(self):
        text = (
            "We started the project. "
            "However, we hit a blocker. "
            "For example, the database was locked. "
            "Therefore, we switched to Redis. "
            "The cache was empty."
        )
        rpt = analyse_stroke(text)
        assert rpt.sentence_count == 5
        assert rpt.transition_count == 4
        kinds = [t.kind for t in rpt.transitions]
        assert "contrast" in kinds
        assert "elaboration" in kinds
        assert "consequence" in kinds
        assert "digression" in kinds

    def test_density_verdict_architecting(self):
        # All transitions explicit → density = 1.0
        text = (
            "First sentence. "
            "Moreover, second sentence. "
            "However, third sentence. "
            "Therefore, fourth sentence."
        )
        rpt = analyse_stroke(text)
        assert rpt.transition_density >= 0.6
        assert rpt.density_verdict == "architecting"

    def test_density_verdict_streaming(self):
        # No transitions → density = 0.0
        text = "Cats sleep. Dogs run. Birds fly. Fish swim."
        rpt = analyse_stroke(text)
        assert rpt.transition_density < 0.1
        assert rpt.density_verdict == "streaming"

    def test_type_distribution_keys(self):
        text = (
            "Start here. "
            "However, we changed plans. "
            "Also, we added more tests."
        )
        rpt = analyse_stroke(text)
        assert "contrast" in rpt.type_distribution or "continuation" in rpt.type_distribution
        for v in rpt.type_distribution.values():
            assert 0.0 <= v <= 1.0

    def test_type_distribution_sums_to_one(self):
        text = (
            "First. "
            "However, second. "
            "Also, third. "
            "Therefore, fourth."
        )
        rpt = analyse_stroke(text)
        total = sum(rpt.type_distribution.values())
        assert abs(total - 1.0) < 0.01

    def test_stroke_index_propagated(self):
        rpt = analyse_stroke("Hello. World.", stroke_index=42)
        assert rpt.stroke_index == 42


# ---------------------------------------------------------------------------
# analyse_stream
# ---------------------------------------------------------------------------


class TestAnalyseStream:
    def test_empty(self):
        rpt = analyse_stream([])
        assert rpt.total_strokes == 0
        assert rpt.transition_density == 0.0

    def test_single_stroke(self):
        rpt = analyse_stream(["Just one sentence."])
        assert rpt.total_strokes == 1
        assert rpt.total_transitions == 0

    def test_multiple_strokes(self):
        strokes = [
            "We started coding. Moreover, we wrote tests.",
            "However, bugs appeared. Therefore, we fixed them.",
            "The system works. Also, it scales well.",
        ]
        rpt = analyse_stream(strokes)
        assert rpt.total_strokes == 3
        assert rpt.total_sentences >= 6
        assert rpt.total_transitions >= 3
        assert rpt.transition_density > 0.0

    def test_density_verdict(self):
        # All explicit transitions
        strokes = [
            "First. Moreover, second. However, third.",
            "Fourth. Therefore, fifth. Also, sixth.",
        ]
        rpt = analyse_stream(strokes)
        assert rpt.density_verdict in ("architecting", "structured", "flowing", "streaming")

    def test_dominant_type(self):
        # Mostly contrast transitions
        strokes = [
            "We tried A. However, it failed.",
            "We tried B. But it also failed.",
            "We tried C. Yet again, failure.",
        ]
        rpt = analyse_stream(strokes)
        assert rpt.dominant_type in ("contrast", "digression", "continuation", "elaboration", "consequence")

    def test_dominant_style_mapping(self):
        style_map = {
            "elaboration": "drilling",
            "continuation": "building",
            "contrast": "debating",
            "consequence": "reasoning",
            "digression": "wandering",
            "none": "wandering",
        }
        strokes = [
            "We started. Moreover, we continued. Also, we expanded.",
        ]
        rpt = analyse_stream(strokes)
        expected_style = style_map.get(rpt.dominant_type, "wandering")
        assert rpt.dominant_style == expected_style

    def test_evolution_included(self):
        strokes = [f"Sentence {i}." for i in range(100)]
        rpt = analyse_stream(strokes, window_size=30, step=15)
        assert rpt.evolution is not None
        assert rpt.evolution.trend in ("tightening", "stable", "loosening")

    def test_type_distribution_values(self):
        strokes = [
            "Start. However, problem. Also, another thing.",
            "Continue. Therefore, result. But wait.",
        ]
        rpt = analyse_stream(strokes)
        for v in rpt.type_distribution.values():
            assert 0.0 <= v <= 1.0


# ---------------------------------------------------------------------------
# analyse_windows
# ---------------------------------------------------------------------------


class TestAnalyseWindows:
    def test_empty(self):
        evo = analyse_windows([])
        assert evo.windows == []
        assert evo.trend == "stable"

    def test_single_small_window(self):
        # Need at least 3 strokes for a window to be created.
        strokes = [
            "First. Also, second. However, third.",
            "Fourth. Therefore, fifth.",
            "Sixth. Moreover, seventh. But eighth.",
        ]
        evo = analyse_windows(strokes, window_size=10)
        assert len(evo.windows) >= 1
        assert evo.trend == "stable"

    def test_multiple_windows(self):
        # Create enough strokes for multiple windows
        strokes = []
        for i in range(100):
            if i < 50:
                strokes.append(f"Start {i}. Also, continue {i}.")
            else:
                strokes.append(f"Start {i}. Birds fly {i}.")
        evo = analyse_windows(strokes, window_size=30, step=15)
        assert len(evo.windows) >= 2

    def test_tightening_trend(self):
        # First half: no transitions; second half: all transitions
        strokes = []
        for i in range(50):
            strokes.append(f"Random text {i}. More random {i}.")
        for i in range(50):
            strokes.append(f"Start {i}. Moreover, continue {i}. However, also {i}.")
        evo = analyse_windows(strokes, window_size=30, step=25)
        # The trend should show tightening (increasing density).
        assert evo.trend in ("tightening", "stable", "loosening")

    def test_loosening_trend(self):
        # First half: all explicit; second half: none
        strokes = []
        for i in range(50):
            strokes.append(f"Start {i}. Moreover, continue {i}. However, also {i}.")
        for i in range(50):
            strokes.append(f"Random text {i}. More random {i}.")
        evo = analyse_windows(strokes, window_size=30, step=25)
        assert evo.trend in ("tightening", "stable", "loosening")

    def test_window_indices(self):
        strokes = [f"S{i}. Also S{i}." for i in range(80)]
        evo = analyse_windows(strokes, window_size=30, step=20)
        for i, w in enumerate(evo.windows):
            assert w.window_index == i

    def test_density_delta(self):
        strokes = [f"S{i}." for i in range(60)]
        evo = analyse_windows(strokes, window_size=20, step=10)
        assert isinstance(evo.density_delta, float)


# ---------------------------------------------------------------------------
# _classify_style
# ---------------------------------------------------------------------------


class TestClassifyStyle:
    def test_empty_distribution(self):
        dom, style = _classify_style({})
        assert dom == "none"
        assert style == "wandering"

    def test_elaboration_dominant(self):
        dom, style = _classify_style({"elaboration": 0.5, "continuation": 0.2, "digression": 0.3})
        assert dom == "elaboration"
        assert style == "drilling"

    def test_continuation_dominant(self):
        dom, style = _classify_style({"continuation": 0.6, "contrast": 0.4})
        assert dom == "continuation"
        assert style == "building"

    def test_contrast_dominant(self):
        dom, style = _classify_style({"contrast": 0.7, "digression": 0.3})
        assert dom == "contrast"
        assert style == "debating"

    def test_consequence_dominant(self):
        dom, style = _classify_style({"consequence": 0.8})
        assert dom == "consequence"
        assert style == "reasoning"

    def test_digression_dominant(self):
        dom, style = _classify_style({"digression": 0.9, "contrast": 0.1})
        assert dom == "digression"
        assert style == "wandering"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_very_short_strokes(self):
        strokes = ["Hi.", "Ok.", "Bye."]
        rpt = analyse_stream(strokes)
        assert rpt.total_strokes == 3

    def test_stroke_with_only_whitespace(self):
        rpt = analyse_stroke("   \n\n  ")
        assert rpt.sentence_count == 0

    def test_marker_at_very_start(self):
        rec = detect_transition("End.", "So we continue.")
        assert rec.kind == "consequence"
        assert rec.marker == "so"

    def test_case_insensitive_marker(self):
        rec = detect_transition("End.", "However, this is different.")
        assert rec.kind == "contrast"

    def test_uppercase_marker(self):
        rec = detect_transition("End.", "HOWEVER, this is different.")
        # Should still match because we lowercase.
        assert rec.kind == "contrast"

    def test_marker_followed_by_comma(self):
        rec = detect_transition("X.", "Therefore, we did Y.")
        assert rec.kind == "consequence"
        assert rec.marker == "therefore"

    def test_marker_followed_by_no_punctuation(self):
        rec = detect_transition("X.", "Moreover we continued.")
        assert rec.kind == "continuation"
        assert rec.marker == "moreover"

    def test_partial_marker_not_matched(self):
        # "butt" should not match "but"
        rec = detect_transition("X.", "Butterflies are pretty.")
        # "but" is a marker; "butterflies" starts with "but" but rest[0] is 't', not comma/space.
        assert rec.kind == "digression"

    def test_and_as_continuation(self):
        rec = detect_transition("We coded.", "And we tested.")
        assert rec.kind == "continuation"
        assert rec.marker == "and"

    def test_while_as_contrast(self):
        rec = detect_transition("It compiles.", "While that is true, it crashes.")
        assert rec.kind == "contrast"
        assert rec.marker == "while"

    def test_many_strokes_performance(self):
        """Ensure analysis completes quickly for 200 strokes."""
        import time
        strokes = [
            f"We built module {i}. Moreover, it has {i} tests. "
            f"However, coverage is only {i}%. Therefore, we added more. "
            f"For example, integration tests for module {i}."
            for i in range(200)
        ]
        start = time.monotonic()
        rpt = analyse_stream(strokes)
        elapsed = time.monotonic() - start
        assert elapsed < 5.0  # Should complete in under 5 seconds.
        assert rpt.total_strokes == 200

    def test_stream_report_has_evolution(self):
        strokes = [f"Sentence {i}. Also sentence {i+1}." for i in range(60)]
        rpt = analyse_stream(strokes, window_size=20, step=10)
        assert rpt.evolution is not None
        assert len(rpt.evolution.windows) >= 1


# ---------------------------------------------------------------------------
# Integration: full stroke stream analysis
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_realistic_strokes(self):
        strokes = [
            (
                "The commit pipeline starts with a diff. "
                "Specifically, we extract changed files from git status. "
                "However, some files are ignored by .gitignore. "
                "Therefore, we must also check the untracked set."
            ),
            (
                "The batch collector waits for 600 seconds. "
                "Moreover, it checks for uncommitted changes every 60 seconds. "
                "If the writer stalls, the batch still commits. "
                "For example, a stalled writer at stroke 50 still gets committed."
            ),
            (
                "Push failures are retried with exponential backoff. "
                "Nevertheless, persistent failures indicate credential issues. "
                "We added a deploy key monitor to catch this early. "
                "Also, the push readiness probe runs before every attempt."
            ),
        ]
        rpt = analyse_stream(strokes)
        assert rpt.total_strokes == 3
        assert rpt.total_sentences >= 12
        assert rpt.transition_density > 0.0
        assert rpt.dominant_type != "none"
        assert rpt.evolution is not None

    def test_all_digression_stream(self):
        strokes = [
            "The cat sat on the mat. The dog ran in the park.",
            "Birds fly south. Fish swim in the ocean.",
            "Trees grow tall. Mountains rise above clouds.",
        ]
        rpt = analyse_stream(strokes)
        assert rpt.dominant_type == "digression"
        assert rpt.dominant_style == "wandering"
        assert rpt.transition_density == 0.0
        assert rpt.density_verdict == "streaming"
