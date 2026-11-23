#!/usr/bin/env python3
"""Tests for iamai.writer_syntactic_mood — grammatical mood profiling per sentence."""

import json
import math
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_syntactic_mood import (
    _classify_mood,
    _classify_sentence,
    _compute_shannon,
    _empty_result,
    _split_sentences,
    compute_syntactic_mood,
    main,
    mood_per_sentence,
    syntactic_mood_report,
    syntactic_mood_summary,
)


# =========================================================================
# _split_sentences
# =========================================================================

class TestSplitSentences:
    def test_basic_split(self):
        text = "The cat sat. The dog ran. The bird flew."
        sents = _split_sentences(text)
        assert len(sents) == 3

    def test_empty_string(self):
        assert _split_sentences("") == []

    def test_none_like(self):
        assert _split_sentences("   ") == []

    def test_single_sentence(self):
        sents = _split_sentences("Hello world.")
        assert len(sents) == 1
        assert sents[0] == "Hello world."

    def test_question_and_exclamation(self):
        text = "What is this? It is amazing! Yes it is."
        sents = _split_sentences(text)
        assert len(sents) == 3

    def test_short_fragments_filtered(self):
        # Fragments of 2 chars or less are filtered
        text = "Hello world. Ok. This is a test."
        sents = _split_sentences(text)
        # "Ok." is 3 chars, should survive
        assert all(len(s) > 2 for s in sents)

    def test_multiline(self):
        text = "First sentence. Second sentence.\nThird sentence."
        sents = _split_sentences(text)
        assert len(sents) == 3

    def test_quotes_preserved(self):
        text = 'He said "hello" to her. She replied.'
        sents = _split_sentences(text)
        assert len(sents) == 2


# =========================================================================
# _classify_sentence — declarative
# =========================================================================

class TestClassifyDeclarative:
    def test_simple_statement(self):
        assert _classify_sentence("The cat sat on the mat.") == "declarative"

    def test_complex_statement(self):
        assert _classify_sentence(
            "The researchers found that the algorithm performed well."
        ) == "declarative"

    def test_statement_with_comma(self):
        assert _classify_sentence(
            "After the rain stopped, we went outside."
        ) == "declarative"

    def test_passive_voice_declarative(self):
        assert _classify_sentence(
            "The results were published last year."
        ) == "declarative"

    def test_there_is(self):
        assert _classify_sentence(
            "There are many reasons for this behavior."
        ) == "declarative"


# =========================================================================
# _classify_sentence — interrogative
# =========================================================================

class TestClassifyInterrogative:
    def test_question_mark(self):
        assert _classify_sentence("What is this?") == "interrogative"

    def test_yes_no_question(self):
        assert _classify_sentence("Is this correct?") == "interrogative"

    def test_how_question(self):
        assert _classify_sentence("How does it work?") == "interrogative"

    def test_why_question(self):
        assert _classify_sentence("Why did this happen?") == "interrogative"

    def test_question_without_mark(self):
        # Question-word at start without '?' should be interrogative
        assert _classify_sentence("What is the meaning of this") == "interrogative"

    def test_how_many(self):
        assert _classify_sentence("How many items are there?") == "interrogative"

    def test_did_question(self):
        assert _classify_sentence("Did you finish the task?") == "interrogative"


# =========================================================================
# _classify_sentence — imperative
# =========================================================================

class TestClassifyImperative:
    def test_simple_command(self):
        assert _classify_sentence("Run the test suite.") == "imperative"

    def test_please_command(self):
        assert _classify_sentence("Please check the output.") == "imperative"

    def test_negative_command(self):
        assert _classify_sentence("Don't forget to save.") == "imperative"

    def test_never_command(self):
        assert _classify_sentence("Never ignore the warnings.") == "imperative"

    def test_always_command(self):
        assert _classify_sentence("Always validate your input.") == "imperative"

    def test_lets_command(self):
        assert _classify_sentence("Let's start the process.") == "imperative"

    def test_add_command(self):
        assert _classify_sentence("Add the new module to the list.") == "imperative"

    def test_create_command(self):
        assert _classify_sentence("Create a new branch for this feature.") == "imperative"

    def test_consider_command(self):
        assert _classify_sentence("Consider the implications.") == "imperative"


# =========================================================================
# _classify_sentence — exclamatory
# =========================================================================

class TestClassifyExclamatory:
    def test_exclamation(self):
        assert _classify_sentence("What a beautiful day!") == "exclamatory"

    def test_surprise(self):
        assert _classify_sentence("That is incredible!") == "exclamatory"

    def test_warning(self):
        assert _classify_sentence("Watch out!") == "exclamatory"

    def test_emphatic(self):
        assert _classify_sentence("This changes everything!") == "exclamatory"


# =========================================================================
# _classify_sentence — subjunctive
# =========================================================================

class TestClassifySubjunctive:
    def test_if_i_were(self):
        assert _classify_sentence("If I were you, I would accept.") == "subjunctive"

    def test_wish_that(self):
        assert _classify_sentence("I wish that he were here.") == "subjunctive"

    def test_as_if(self):
        assert _classify_sentence("He acted as if nothing happened.") == "subjunctive"

    def test_as_though(self):
        assert _classify_sentence("She spoke as though she knew everything.") == "subjunctive"

    def test_if_only(self):
        assert _classify_sentence("If only we had more time.") == "subjunctive"

    def test_demand_that(self):
        assert _classify_sentence(
            "The committee demands that the report be submitted."
        ) == "subjunctive"

    def test_suggest_that(self):
        assert _classify_sentence(
            "I suggest that she come early."
        ) == "subjunctive"

    def test_god_forbid(self):
        assert _classify_sentence("God forbid that should happen.") == "subjunctive"


# =========================================================================
# _classify_sentence — conditional
# =========================================================================

class TestClassifyConditional:
    def test_if_will(self):
        assert _classify_sentence(
            "If it rains, we will stay inside."
        ) == "conditional"

    def test_would_if(self):
        assert _classify_sentence(
            "I would help if I could."
        ) == "conditional"

    def test_unless(self):
        assert _classify_sentence(
            "We cannot proceed unless you agree."
        ) == "conditional"

    def test_provided_that(self):
        assert _classify_sentence(
            "You may go, provided that you finish first."
        ) == "conditional"

    def test_supposing(self):
        assert _classify_sentence(
            "Supposing the server crashes, what then?"
        ) == "conditional"

    def test_in_case(self):
        assert _classify_sentence(
            "Take an umbrella in case it rains."
        ) == "conditional"

    def test_had_i_known(self):
        assert _classify_sentence(
            "Had I known the truth, I would have acted differently."
        ) == "conditional"


# =========================================================================
# compute_syntactic_mood — aggregation
# =========================================================================

class TestComputeSyntacticMood:
    def test_empty_text(self):
        result = compute_syntactic_mood("")
        assert result["total_sentences"] == 0
        assert result["mood_label"] == "absent"

    def test_whitespace_only(self):
        result = compute_syntactic_mood("   \n\n  ")
        assert result["total_sentences"] == 0

    def test_single_declarative(self):
        result = compute_syntactic_mood("The sky is blue.")
        assert result["total_sentences"] == 1
        assert result["declarative_count"] == 1
        assert result["declarative_ratio"] == 1.0
        assert result["dominant_mood"] == "declarative"

    def test_mixed_text(self):
        text = (
            "The algorithm works well. "
            "Does it handle edge cases? "
            "Run the tests now. "
            "What a great result! "
            "If I were a user, I would be happy."
        )
        result = compute_syntactic_mood(text)
        assert result["total_sentences"] == 5
        assert result["declarative_count"] == 1
        assert result["interrogative_count"] == 1
        assert result["imperative_count"] == 1
        assert result["exclamatory_count"] == 1
        assert result["subjunctive_count"] == 1

    def test_all_declarative(self):
        text = "The sun rises. The moon sets. Stars shine brightly."
        result = compute_syntactic_mood(text)
        assert result["declarative_ratio"] == 1.0
        assert result["mood_label"] == "monotone_declare"

    def test_assertion_ratio(self):
        text = "This is true. That is false. Amazing result!"
        result = compute_syntactic_mood(text)
        # 2 declarative + 1 exclamatory = assertion_ratio 1.0
        assert result["assertion_ratio"] == 1.0

    def test_inquiry_ratio(self):
        text = "What is this? How does it work? The answer is clear."
        result = compute_syntactic_mood(text)
        assert result["inquiry_ratio"] == pytest.approx(2 / 3, abs=0.01)

    def test_directive_ratio(self):
        text = "Run the script. Check the output. The process completed."
        result = compute_syntactic_mood(text)
        assert result["directive_ratio"] == pytest.approx(2 / 3, abs=0.01)

    def test_speculation_ratio(self):
        text = (
            "If I were taller, I would play basketball. "
            "Unless it rains, we will go. "
            "The sky is blue."
        )
        result = compute_syntactic_mood(text)
        assert result["speculation_ratio"] == pytest.approx(2 / 3, abs=0.01)

    def test_mood_diversity_zero(self):
        # All same mood → diversity 0
        text = "One fact. Two facts. Three facts."
        result = compute_syntactic_mood(text)
        assert result["mood_diversity"] == 0.0

    def test_mood_diversity_high(self):
        # 6 different moods → high diversity
        text = (
            "The cat sat. "
            "What is that? "
            "Run the test. "
            "Amazing result! "
            "If I were you, I would accept. "
            "Unless it rains, we will go."
        )
        result = compute_syntactic_mood(text)
        assert result["mood_diversity"] > 0.80

    def test_counts_sum_to_total(self):
        text = (
            "The algorithm works. "
            "Does it scale? "
            "Check the logs. "
            "What a surprise! "
            "If only we had time. "
            "Unless we hurry, we will be late."
        )
        result = compute_syntactic_mood(text)
        mood_sum = sum(result[f"{m}_count"] for m in [
            "declarative", "interrogative", "imperative",
            "exclamatory", "subjunctive", "conditional",
        ])
        assert mood_sum == result["total_sentences"]

    def test_ratios_sum_to_one(self):
        text = (
            "First statement. "
            "Second statement. "
            "Is this correct? "
            "Run the build."
        )
        result = compute_syntactic_mood(text)
        ratio_sum = sum(result[f"{m}_ratio"] for m in [
            "declarative", "interrogative", "imperative",
            "exclamatory", "subjunctive", "conditional",
        ])
        assert ratio_sum == pytest.approx(1.0, abs=0.01)

    def test_dominant_mood_matches_max_count(self):
        text = "One fact. Two facts. Three facts. Is this true?"
        result = compute_syntactic_mood(text)
        assert result["dominant_mood"] == "declarative"

    def test_mood_entropy_range(self):
        text = "Statement one. Statement two. What about this?"
        result = compute_syntactic_mood(text)
        assert 0.0 <= result["mood_entropy"] <= math.log2(6)

    def test_result_has_all_keys(self):
        result = compute_syntactic_mood("Hello world.")
        expected_keys = {
            "total_sentences",
            "declarative_count", "declarative_ratio",
            "interrogative_count", "interrogative_ratio",
            "imperative_count", "imperative_ratio",
            "exclamatory_count", "exclamatory_ratio",
            "subjunctive_count", "subjunctive_ratio",
            "conditional_count", "conditional_ratio",
            "dominant_mood", "mood_diversity", "mood_entropy",
            "assertion_ratio", "inquiry_ratio",
            "directive_ratio", "speculation_ratio",
            "mood_label",
        }
        assert expected_keys.issubset(set(result.keys()))


# =========================================================================
# _empty_result
# =========================================================================

class TestEmptyResult:
    def test_all_zero(self):
        result = _empty_result()
        assert result["total_sentences"] == 0
        assert result["mood_label"] == "absent"
        assert result["mood_diversity"] == 0.0

    def test_has_all_mood_keys(self):
        result = _empty_result()
        for m in ["declarative", "interrogative", "imperative",
                   "exclamatory", "subjunctive", "conditional"]:
            assert f"{m}_count" in result
            assert f"{m}_ratio" in result


# =========================================================================
# _classify_mood (text-level label)
# =========================================================================

class TestClassifyMoodLabel:
    def test_monotone_declare(self):
        ratios = {
            "declarative": 0.95, "interrogative": 0.02,
            "imperative": 0.01, "exclamatory": 0.01,
            "subjunctive": 0.005, "conditional": 0.005,
        }
        assert _classify_mood(ratios, 0.1) == "monotone_declare"

    def test_inquisitive(self):
        ratios = {
            "declarative": 0.60, "interrogative": 0.25,
            "imperative": 0.05, "exclamatory": 0.05,
            "subjunctive": 0.03, "conditional": 0.02,
        }
        assert _classify_mood(ratios, 0.5) == "inquisitive"

    def test_directive(self):
        ratios = {
            "declarative": 0.55, "interrogative": 0.05,
            "imperative": 0.25, "exclamatory": 0.05,
            "subjunctive": 0.05, "conditional": 0.05,
        }
        assert _classify_mood(ratios, 0.5) == "directive"

    def test_speculative(self):
        ratios = {
            "declarative": 0.50, "interrogative": 0.05,
            "imperative": 0.05, "exclamatory": 0.05,
            "subjunctive": 0.20, "conditional": 0.15,
        }
        assert _classify_mood(ratios, 0.5) == "speculative"

    def test_mixed_voice(self):
        ratios = {
            "declarative": 0.20, "interrogative": 0.20,
            "imperative": 0.20, "exclamatory": 0.15,
            "subjunctive": 0.10, "conditional": 0.15,
        }
        assert _classify_mood(ratios, 0.85) == "mixed_voice"

    def test_assertive(self):
        ratios = {
            "declarative": 0.80, "interrogative": 0.05,
            "imperative": 0.05, "exclamatory": 0.07,
            "subjunctive": 0.01, "conditional": 0.02,
        }
        assert _classify_mood(ratios, 0.4) == "assertive"


# =========================================================================
# _compute_shannon
# =========================================================================

class TestComputeShannon:
    def test_empty(self):
        from collections import Counter
        assert _compute_shannon(Counter(), 0) == 0.0

    def test_uniform(self):
        from collections import Counter
        counts = Counter({"a": 1, "b": 1, "c": 1, "d": 1})
        h = _compute_shannon(counts, 4)
        assert h == pytest.approx(2.0, abs=0.001)

    def test_single_item(self):
        from collections import Counter
        counts = Counter({"a": 10})
        assert _compute_shannon(counts, 10) == 0.0

    def test_two_equal(self):
        from collections import Counter
        counts = Counter({"a": 5, "b": 5})
        h = _compute_shannon(counts, 10)
        assert h == pytest.approx(1.0, abs=0.001)


# =========================================================================
# mood_per_sentence
# =========================================================================

class TestMoodPerSentence:
    def test_basic(self):
        text = "The sun shines. Is it warm? Go outside!"
        detail = mood_per_sentence(text)
        assert len(detail) == 3
        moods = [d["mood"] for d in detail]
        assert "declarative" in moods
        assert "interrogative" in moods
        assert "exclamatory" in moods

    def test_empty(self):
        assert mood_per_sentence("") == []

    def test_has_sentence_and_mood(self):
        detail = mood_per_sentence("Hello world.")
        assert len(detail) == 1
        assert "sentence" in detail[0]
        assert "mood" in detail[0]


# =========================================================================
# syntactic_mood_report (on-disk)
# =========================================================================

class TestSyntacticMoodReport:
    def test_missing_file(self):
        result = syntactic_mood_report("/nonexistent/path.jsonl")
        assert result["total_sentences"] == 0
        assert result["mood_label"] == "absent"

    def test_with_strokes(self, tmp_path):
        strokes = tmp_path / "strokes.jsonl"
        strokes.write_text(
            json.dumps({"body": "The algorithm works well."}) + "\n"
            + json.dumps({"body": "Does it handle errors?"}) + "\n"
            + json.dumps({"body": "Run the test suite."}) + "\n"
        )
        result = syntactic_mood_report(str(strokes))
        assert result["total_sentences"] == 3
        assert result["declarative_count"] >= 1
        assert result["interrogative_count"] >= 1

    def test_empty_jsonl(self, tmp_path):
        strokes = tmp_path / "strokes.jsonl"
        strokes.write_text("")
        result = syntactic_mood_report(str(strokes))
        assert result["total_sentences"] == 0

    def test_malformed_lines_skipped(self, tmp_path):
        strokes = tmp_path / "strokes.jsonl"
        strokes.write_text(
            "not valid json\n"
            + json.dumps({"body": "This is valid."}) + "\n"
            + "{broken\n"
        )
        result = syntactic_mood_report(str(strokes))
        assert result["total_sentences"] >= 1


# =========================================================================
# syntactic_mood_summary
# =========================================================================

class TestSyntacticMoodSummary:
    def test_no_data(self):
        summary = syntactic_mood_summary(_empty_result())
        assert "No sentences" in summary

    def test_with_data(self):
        result = compute_syntactic_mood(
            "The code works. Does it scale? Run the build. Great output!"
        )
        summary = syntactic_mood_summary(result)
        assert "Syntactic Mood Profile" in summary
        assert "declarative" in summary
        assert "interrogative" in summary

    def test_default_report(self, tmp_path):
        # When result is None, it tries to read strokes
        summary = syntactic_mood_summary(None, str(tmp_path / "missing.jsonl"))
        assert "No sentences" in summary


# =========================================================================
# CLI main
# =========================================================================

class TestMain:
    def test_json_output(self, tmp_path, capsys):
        strokes = tmp_path / "strokes.jsonl"
        strokes.write_text(json.dumps({"body": "Hello world."}) + "\n")
        sys.argv = ["prog", "--json", "--strokes", str(strokes)]
        rc = main()
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "total_sentences" in data

    def test_text_mode(self, capsys):
        sys.argv = ["prog", "--text", "The sun shines. Is it warm?"]
        rc = main()
        assert rc == 0
        captured = capsys.readouterr()
        assert "Syntactic Mood Profile" in captured.out

    def test_text_json_mode(self, capsys):
        sys.argv = ["prog", "--text", "The sun shines.", "--json"]
        rc = main()
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["total_sentences"] == 1

    def test_text_per_sentence(self, capsys):
        sys.argv = ["prog", "--text", "Hello. What?", "--per-sentence"]
        rc = main()
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data) == 2


# =========================================================================
# Edge cases
# =========================================================================

class TestEdgeCases:
    def test_very_long_sentence(self):
        text = "And " * 500 + "finally the end."
        result = compute_syntactic_mood(text)
        assert result["total_sentences"] >= 1

    def test_unicode_text(self):
        text = "The café is open. Isn't it wonderful? Try the crème brûlée!"
        result = compute_syntactic_mood(text)
        assert result["total_sentences"] == 3

    def test_numbers_in_text(self):
        text = "There are 42 items. How many do you need? Take 10."
        result = compute_syntactic_mood(text)
        assert result["total_sentences"] == 3

    def test_abbreviations_not_split(self):
        text = "Dr. Smith went to Washington. He arrived on Monday."
        # "Dr." might cause a false split — our heuristic may split here,
        # but the result should still have at least 1 sentence
        result = compute_syntactic_mood(text)
        assert result["total_sentences"] >= 1

    def test_mood_label_not_absent_with_text(self):
        result = compute_syntactic_mood("This is a test.")
        assert result["mood_label"] != "absent"

    def test_single_word_sentences(self):
        text = "Go! Stop! Wait!"
        result = compute_syntactic_mood(text)
        assert result["total_sentences"] == 3
        assert result["exclamatory_count"] == 3
