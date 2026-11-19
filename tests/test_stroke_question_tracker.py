"""Tests for iamai/stroke_question_tracker.py — question tracking.

Run:  python3 -m pytest tests/test_stroke_question_tracker.py -v

Written by Qwen during caretaker visit 733, 2026-11-19.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.stroke_question_tracker import (  # noqa: E402
    EvolutionReport,
    QuestionRecord,
    StreamQuestionReport,
    StrokeQuestionReport,
    WindowQuestionReport,
    analyse_stroke,
    analyse_stream,
    analyse_windows,
    classify_question,
    split_sentences,
    tokenise,
    _classify_style,
    _is_question,
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

    def test_empty_string(self):
        assert split_sentences("") == []

    def test_whitespace_only(self):
        assert split_sentences("   \n  ") == []

    def test_mixed_punctuation(self):
        result = split_sentences("Wow! Really? Yes.")
        assert len(result) == 3

    def test_no_ending_punctuation(self):
        result = split_sentences("no punctuation here")
        assert len(result) == 1
        assert result[0] == "no punctuation here"


# ---------------------------------------------------------------------------
# tokenise
# ---------------------------------------------------------------------------


class TestTokenise:
    def test_basic(self):
        assert tokenise("Hello, World!") == ["hello", "world"]

    def test_apostrophe(self):
        assert tokenise("don't stop") == ["don't", "stop"]

    def test_empty(self):
        assert tokenise("") == []

    def test_numbers_stripped(self):
        result = tokenise("version 3.2 is out")
        assert "version" in result
        assert "is" in result
        assert "out" in result


# ---------------------------------------------------------------------------
# _is_question
# ---------------------------------------------------------------------------


class TestIsQuestion:
    def test_question(self):
        assert _is_question("What is this?") is True

    def test_statement(self):
        assert _is_question("This is a statement.") is False

    def test_exclamation(self):
        assert _is_question("Wow!") is False

    def test_trailing_whitespace(self):
        assert _is_question("Really?  ") is True

    def test_empty(self):
        assert _is_question("") is False


# ---------------------------------------------------------------------------
# classify_question
# ---------------------------------------------------------------------------


class TestClassifyQuestion:
    def test_hypothetical_what_if(self):
        assert classify_question("What if we removed the lock?") == "hypothetical"

    def test_hypothetical_suppose(self):
        assert classify_question("Suppose the network fails?") == "hypothetical"

    def test_hypothetical_imagine(self):
        assert classify_question("Imagine a world without tests?") == "hypothetical"

    def test_hypothetical_assume(self):
        assert classify_question("Assume the worst case?") == "hypothetical"

    def test_hypothetical_would_happen(self):
        assert classify_question("What would happen if we scale up?") == "hypothetical"

    def test_hypothetical_could_we(self):
        assert classify_question("How could we make this faster?") == "hypothetical"

    def test_rhetorical_who_cares(self):
        assert classify_question("Who cares?") == "rhetorical"

    def test_rhetorical_why_bother(self):
        assert classify_question("Why bother?") == "rhetorical"

    def test_rhetorical_so_what(self):
        assert classify_question("So what?") == "rhetorical"

    def test_rhetorical_really(self):
        assert classify_question("Is this really necessary?") == "rhetorical"

    def test_rhetorical_seriously(self):
        assert classify_question("Seriously?") == "rhetorical"

    def test_rhetorical_obviously(self):
        assert classify_question("Is this obviously correct?") == "rhetorical"

    def test_tag_isnt_it(self):
        assert classify_question("It's fast, isn't it?") == "tag"

    def test_tag_right(self):
        assert classify_question("That works, right?") == "tag"

    def test_tag_dont_you_think(self):
        assert classify_question("This is better, don't you think?") == "tag"

    def test_tag_doesnt_it(self):
        assert classify_question("That compiles, doesn't it?") == "tag"

    def test_genuine_default(self):
        assert classify_question("What does the buffer contain?") == "genuine"

    def test_genuine_how(self):
        assert classify_question("How does the garbage collector work?") == "genuine"

    def test_genuine_why(self):
        assert classify_question("Why does the test fail on CI?") == "genuine"

    def test_genuine_when(self):
        assert classify_question("When does the cache expire?") == "genuine"


# ---------------------------------------------------------------------------
# analyse_stroke
# ---------------------------------------------------------------------------


class TestAnalyseStroke:
    def test_no_questions(self):
        text = "This is a statement. Another statement. Final one."
        rpt = analyse_stroke(text, stroke_index=0)
        assert rpt.stroke_index == 0
        assert rpt.sentence_count == 3
        assert rpt.question_count == 0
        assert rpt.question_rate == 0.0
        assert rpt.questions == []
        assert rpt.dominant_type == "none"

    def test_all_questions(self):
        text = "What is this? Why does it matter? How does it work?"
        rpt = analyse_stroke(text, stroke_index=5)
        assert rpt.sentence_count == 3
        assert rpt.question_count == 3
        assert rpt.question_rate == 1.0
        assert len(rpt.questions) == 3
        assert all(q.stroke_index == 5 for q in rpt.questions)

    def test_mixed(self):
        text = "Here is a fact. But why? Another fact. And how?"
        rpt = analyse_stroke(text)
        assert rpt.sentence_count == 4
        assert rpt.question_count == 2
        assert rpt.question_rate == 0.5

    def test_empty_stroke(self):
        rpt = analyse_stroke("")
        assert rpt.sentence_count == 0
        assert rpt.question_count == 0
        assert rpt.dominant_type == "none"

    def test_single_question(self):
        text = "What happens next?"
        rpt = analyse_stroke(text, stroke_index=10)
        assert rpt.sentence_count == 1
        assert rpt.question_count == 1
        assert rpt.question_rate == 1.0
        assert rpt.questions[0].qtype == "genuine"
        assert rpt.questions[0].word_count > 0

    def test_dominant_type(self):
        # Two hypothetical + one genuine → dominant = hypothetical.
        text = (
            "What if we scale up? Suppose the cache misses? "
            "When does it expire?"
        )
        rpt = analyse_stroke(text)
        assert rpt.dominant_type == "hypothetical"

    def test_question_records(self):
        text = "Really? What does it do?"
        rpt = analyse_stroke(text, stroke_index=42)
        assert len(rpt.questions) == 2
        assert rpt.questions[0].text == "Really?"
        assert rpt.questions[0].qtype == "rhetorical"
        assert rpt.questions[0].stroke_index == 42
        assert rpt.questions[1].text == "What does it do?"
        assert rpt.questions[1].qtype == "genuine"


# ---------------------------------------------------------------------------
# analyse_stream
# ---------------------------------------------------------------------------


class TestAnalyseStream:
    def test_empty_stream(self):
        rpt = analyse_stream([])
        assert rpt.total_strokes == 0
        assert rpt.total_questions == 0
        assert rpt.style == "declarative"

    def test_no_questions_at_all(self):
        strokes = [
            "This is a statement.",
            "Another statement here.",
            "Yet more declarations.",
        ]
        rpt = analyse_stream(strokes)
        assert rpt.total_strokes == 3
        assert rpt.total_questions == 0
        assert rpt.question_rate == 0.0
        assert rpt.question_density == 0.0
        assert rpt.style == "declarative"

    def test_all_questions(self):
        strokes = [
            "What is this?",
            "Why does it matter?",
            "How does it work?",
        ]
        rpt = analyse_stream(strokes)
        assert rpt.total_strokes == 3
        assert rpt.total_questions == 3
        assert rpt.question_rate == 1.0
        assert rpt.question_density == 1.0

    def test_question_density_partial(self):
        strokes = [
            "What is this?",       # has question
            "This is a fact.",      # no question
            "Why does it matter?",  # has question
            "Another fact.",        # no question
        ]
        rpt = analyse_stream(strokes)
        assert rpt.question_density == 0.5

    def test_type_distribution(self):
        strokes = [
            "Really? So what?",           # 2 rhetorical
            "What if we removed locks?",   # 1 hypothetical
            "How does the cache work?",    # 1 genuine
        ]
        rpt = analyse_stream(strokes)
        assert rpt.total_questions == 4
        assert "rhetorical" in rpt.type_distribution
        assert rpt.type_distribution["rhetorical"] == 0.5
        assert rpt.type_distribution["hypothetical"] == 0.25
        assert rpt.type_distribution["genuine"] == 0.25

    def test_style_exploratory(self):
        # High question rate with mostly genuine/hypothetical.
        strokes = [
            "What does this do? How does it work? When does it fail?",
            "Why does the cache miss? What would happen if we scale?",
            "How could we improve this? Where does the data go?",
        ]
        rpt = analyse_stream(strokes)
        assert rpt.style == "exploratory"

    def test_style_rhetorical(self):
        # Moderate rate with mostly rhetorical.
        strokes = [
            "Who cares? So what? Really?",
            "Why bother? Seriously?",
            "It works, right? Obviously correct?",
        ]
        rpt = analyse_stream(strokes)
        assert rpt.style in ("rhetorical", "mixed")

    def test_style_declarative(self):
        strokes = [
            "This is a statement.",
            "The function returns a value.",
            "Tests pass on CI.",
        ]
        rpt = analyse_stream(strokes)
        assert rpt.style == "declarative"

    def test_stroke_reports_populated(self):
        strokes = ["What?", "Statement.", "Why?"]
        rpt = analyse_stream(strokes)
        assert len(rpt.stroke_reports) == 3
        assert rpt.stroke_reports[0].question_count == 1
        assert rpt.stroke_reports[1].question_count == 0
        assert rpt.stroke_reports[2].question_count == 1


# ---------------------------------------------------------------------------
# _classify_style
# ---------------------------------------------------------------------------


class TestClassifyStyle:
    def test_declarative_low_rate(self):
        assert _classify_style(0.01, {}) == "declarative"
        assert _classify_style(0.03, {"genuine": 1.0}) == "declarative"

    def test_rhetorical(self):
        assert _classify_style(0.20, {"rhetorical": 0.7, "genuine": 0.3}) == "rhetorical"

    def test_exploratory(self):
        assert _classify_style(
            0.30, {"genuine": 0.5, "hypothetical": 0.3, "rhetorical": 0.2}
        ) == "exploratory"

    def test_mixed(self):
        assert _classify_style(
            0.10, {"genuine": 0.4, "rhetorical": 0.3, "tag": 0.3}
        ) == "mixed"

    def test_zero_rate(self):
        assert _classify_style(0.0, {}) == "declarative"


# ---------------------------------------------------------------------------
# analyse_windows
# ---------------------------------------------------------------------------


class TestAnalyseWindows:
    def test_empty_input(self):
        rpt = analyse_windows([])
        assert rpt.windows == []
        assert rpt.trend == "stable"
        assert rpt.rate_delta == 0.0

    def test_single_window(self):
        strokes = [f"Question {i}?" for i in range(5)]
        rpt = analyse_windows(strokes, window_size=10, step=5)
        assert len(rpt.windows) >= 1

    def test_stable_trend(self):
        # Uniform questioning → stable.
        strokes = []
        for i in range(100):
            if i % 2 == 0:
                strokes.append(f"What is item {i}?")
            else:
                strokes.append(f"Item {i} is a thing.")
        rpt = analyse_windows(strokes, window_size=30, step=15)
        assert rpt.trend == "stable"

    def test_deepening_trend(self):
        # Start declarative, end exploratory.
        strokes = []
        # First half: all declarative.
        for i in range(50):
            strokes.append(f"Statement number {i}.")
        # Second half: all questions.
        for i in range(50):
            strokes.append(f"What about item {i}?")
        rpt = analyse_windows(strokes, window_size=30, step=15)
        assert rpt.trend == "deepening"
        assert rpt.rate_delta > 0

    def test_closing_trend(self):
        # Start exploratory, end declarative.
        strokes = []
        # First half: all questions.
        for i in range(50):
            strokes.append(f"What is item {i}?")
        # Second half: all declarative.
        for i in range(50):
            strokes.append(f"Item {i} is finalized.")
        rpt = analyse_windows(strokes, window_size=30, step=15)
        assert rpt.trend == "closing"
        assert rpt.rate_delta < 0

    def test_window_fields(self):
        strokes = [f"Q{i}?" for i in range(20)]
        rpt = analyse_windows(strokes, window_size=10, step=5)
        for w in rpt.windows:
            assert isinstance(w.window_index, int)
            assert isinstance(w.start_stroke, int)
            assert isinstance(w.end_stroke, int)
            assert 0.0 <= w.question_rate <= 1.0
            assert 0.0 <= w.question_density <= 1.0
            assert w.end_stroke >= w.start_stroke

    def test_window_dominant_type(self):
        strokes = ["Really?", "So what?", "Who cares?"] * 10
        rpt = analyse_windows(strokes, window_size=10, step=5)
        for w in rpt.windows:
            if w.question_rate > 0:
                assert w.dominant_type in (
                    "rhetorical", "genuine", "hypothetical", "tag", "other"
                )

    def test_small_input(self):
        strokes = ["Hello?", "World."]
        rpt = analyse_windows(strokes, window_size=50, step=25)
        # Too small for a window of 50 with step 25 → may produce 0 or 1 windows.
        assert len(rpt.windows) <= 1

    def test_rate_delta_computed(self):
        strokes = []
        for i in range(40):
            strokes.append(f"Statement {i}.")
        for i in range(40):
            strokes.append(f"What about {i}?")
        rpt = analyse_windows(strokes, window_size=20, step=10)
        if len(rpt.windows) >= 2:
            assert rpt.rate_delta != 0.0


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class TestDataClasses:
    def test_question_record(self):
        q = QuestionRecord(
            text="What?", stroke_index=5, qtype="genuine", word_count=1
        )
        assert q.text == "What?"
        assert q.stroke_index == 5
        assert q.qtype == "genuine"
        assert q.word_count == 1

    def test_stroke_question_report_defaults(self):
        rpt = StrokeQuestionReport(stroke_index=0)
        assert rpt.sentence_count == 0
        assert rpt.question_count == 0
        assert rpt.question_rate == 0.0
        assert rpt.questions == []
        assert rpt.dominant_type == "none"

    def test_stream_question_report_defaults(self):
        rpt = StreamQuestionReport()
        assert rpt.total_strokes == 0
        assert rpt.total_questions == 0
        assert rpt.style == "declarative"

    def test_window_question_report(self):
        w = WindowQuestionReport(
            window_index=0,
            start_stroke=0,
            end_stroke=10,
            question_rate=0.3,
        )
        assert w.window_index == 0
        assert w.question_rate == 0.3

    def test_evolution_report_defaults(self):
        rpt = EvolutionReport()
        assert rpt.windows == []
        assert rpt.trend == "stable"
        assert rpt.rate_delta == 0.0


# ---------------------------------------------------------------------------
# Integration / edge cases
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_question_in_code_comment(self):
        """Even code comments with ? should be detected."""
        text = "# What does this function return? It returns None."
        rpt = analyse_stroke(text)
        assert rpt.question_count == 1
        assert rpt.questions[0].qtype == "genuine"

    def test_multiple_question_marks(self):
        """Multiple ? in one sentence still counts as one sentence."""
        text = "What?? Really?? Yes."
        rpt = analyse_stroke(text)
        # split_sentences may split on each ? boundary.
        assert rpt.question_count >= 1

    def test_long_stream_consistency(self):
        """Verify consistent behaviour over 200 strokes."""
        strokes = []
        for i in range(200):
            if i % 3 == 0:
                strokes.append(f"What is item {i}? Why does it exist?")
            elif i % 3 == 1:
                strokes.append(f"Item {i} is a thing. It works well.")
            else:
                strokes.append(
                    f"Consider item {i}. What if we changed it? "
                    f"It is important, isn't it?"
                )
        rpt = analyse_stream(strokes)
        assert rpt.total_strokes == 200
        assert rpt.total_questions > 0
        assert 0.0 < rpt.question_rate < 1.0
        assert 0.0 < rpt.question_density < 1.0

    def test_tag_question_full_sentence(self):
        text = (
            "The algorithm runs in O(n log n) time, isn't it? "
            "The results look good, right?"
        )
        rpt = analyse_stroke(text)
        assert rpt.question_count == 2
        assert all(q.qtype == "tag" for q in rpt.questions)

    def test_hypothetical_variants(self):
        strokes = [
            "What if we used a hash map?",
            "Suppose the input is empty?",
            "Imagine a lock-free queue?",
            "Assume the worst case scenario?",
        ]
        rpt = analyse_stream(strokes)
        assert rpt.total_questions == 4
        assert rpt.type_distribution.get("hypothetical", 0) == 1.0

    def test_window_with_only_declarative(self):
        strokes = [f"Fact number {i}." for i in range(30)]
        rpt = analyse_windows(strokes, window_size=10, step=5)
        for w in rpt.windows:
            assert w.question_rate == 0.0
            assert w.dominant_type == "none"

    def test_all_tag_questions(self):
        strokes = [
            "It works, right?",
            "That's correct, isn't it?",
            "We're done, aren't we?",
        ]
        rpt = analyse_stream(strokes)
        assert rpt.type_distribution.get("tag", 0) == 1.0
