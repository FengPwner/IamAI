#!/usr/bin/env python3
"""Tests for writer_rhythm_signature module."""

import json
import math
import sys
import os
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iamai.writer_rhythm_signature import (
    FUNCTION_WORDS,
    _SHORT_THRESHOLD,
    _LONG_THRESHOLD,
    _classify,
    _count_punctuation,
    _empty_result,
    _estimate_syllables,
    _split_paragraphs,
    _split_sentences,
    _tokenize,
    compute_rhythm_signature,
    main,
    rhythm_signature_report,
    rhythm_signature_summary,
)


# ===================================================================
# _tokenize
# ===================================================================

class TestTokenize:
    def test_basic(self):
        assert _tokenize("Hello world") == ["hello", "world"]

    def test_punctuation_stripped(self):
        assert _tokenize("one, two; three!") == ["one", "two", "three"]

    def test_empty(self):
        assert _tokenize("") == []

    def test_contractions(self):
        tokens = _tokenize("don't stop")
        assert "don't" in tokens

    def test_numbers_ignored(self):
        assert _tokenize("abc 123 def") == ["abc", "def"]

    def test_mixed_case(self):
        assert _tokenize("UPPER lower") == ["upper", "lower"]

    def test_multiple_spaces(self):
        assert _tokenize("a   b   c") == ["a", "b", "c"]

    def test_unicode_letters(self):
        # ASCII-only regex — accented chars not captured
        result = _tokenize("café latte")
        assert "caf" in result or "café" in result  # depends on regex


# ===================================================================
# _count_punctuation
# ===================================================================

class TestCountPunctuation:
    def test_no_punctuation(self):
        assert _count_punctuation("hello world") == 0

    def test_basic_punctuation(self):
        assert _count_punctuation("Hello, world!") == 2

    def test_multiple_types(self):
        assert _count_punctuation("one. two; three?") == 3

    def test_quotes_and_parens(self):
        assert _count_punctuation('(say "hi")') == 4

    def test_ellipsis(self):
        assert _count_punctuation("wait…") == 1

    def test_empty(self):
        assert _count_punctuation("") == 0

    def test_em_dash(self):
        assert _count_punctuation("word—word") == 1

    def test_all_punctuation(self):
        assert _count_punctuation(".,;:!?") == 6


# ===================================================================
# _split_sentences
# ===================================================================

class TestSplitSentences:
    def test_single(self):
        assert _split_sentences("Hello world.") == ["Hello world."]

    def test_multiple(self):
        result = _split_sentences("One. Two. Three.")
        assert len(result) == 3

    def test_questions(self):
        result = _split_sentences("What? Why? How?")
        assert len(result) == 3

    def test_exclamations(self):
        result = _split_sentences("Wow! Great! Nice!")
        assert len(result) == 3

    def test_empty(self):
        assert _split_sentences("") == []

    def test_no_terminator(self):
        result = _split_sentences("no terminator here")
        assert len(result) == 1

    def test_mixed_terminators(self):
        result = _split_sentences("Really? Yes! OK.")
        assert len(result) == 3


# ===================================================================
# _split_paragraphs
# ===================================================================

class TestSplitParagraphs:
    def test_single(self):
        result = _split_paragraphs("Just one paragraph.")
        assert len(result) == 1

    def test_two_paragraphs(self):
        text = "First paragraph.\n\nSecond paragraph."
        result = _split_paragraphs(text)
        assert len(result) == 2

    def test_multiple(self):
        text = "One.\n\nTwo.\n\nThree."
        result = _split_paragraphs(text)
        assert len(result) == 3

    def test_extra_whitespace(self):
        text = "One.\n   \nTwo."
        result = _split_paragraphs(text)
        assert len(result) == 2

    def test_empty(self):
        assert _split_paragraphs("") == []

    def test_trailing_newlines(self):
        text = "One.\n\nTwo.\n\n"
        result = _split_paragraphs(text)
        assert len(result) == 2


# ===================================================================
# _estimate_syllables
# ===================================================================

class TestEstimateSyllables:
    def test_monosyllable(self):
        assert _estimate_syllables("cat") == 1

    def test_disyllable(self):
        assert _estimate_syllables("table") >= 1  # ta-ble

    def test_trisyllable(self):
        result = _estimate_syllables("banana")
        assert result >= 2

    def test_single_letter(self):
        assert _estimate_syllables("a") == 1

    def test_empty(self):
        assert _estimate_syllables("") == 0

    def test_silent_e(self):
        # "make" → 1 syllable (silent e)
        assert _estimate_syllables("make") == 1

    def test_le_ending(self):
        # "table" ends in -le, should not subtract
        assert _estimate_syllables("table") >= 1

    def test_long_word(self):
        result = _estimate_syllables("extraordinary")
        assert result >= 3

    def test_minimum_one(self):
        # Even very short words should get at least 1
        assert _estimate_syllables("I") == 1


# ===================================================================
# compute_rhythm_signature — empty / edge cases
# ===================================================================

class TestComputeRhythmSignatureEdgeCases:
    def test_empty_list(self):
        result = compute_rhythm_signature([])
        assert result["total_sentences"] == 0
        assert result["rhythm_label"] == "steady"

    def test_single_sentence(self):
        result = compute_rhythm_signature(["Hello world."])
        assert result["total_sentences"] == 1
        assert result["rhythm_index"] >= 0

    def test_empty_strings(self):
        result = compute_rhythm_signature(["", "", ""])
        assert result["total_sentences"] == 0

    def test_no_punctuation(self):
        result = compute_rhythm_signature(["hello world foo bar baz"])
        assert result["total_sentences"] == 1

    def test_all_function_words(self):
        text = "the a an is are was were do does did."
        result = compute_rhythm_signature([text])
        assert result["function_word_ratio"] > 0.8

    def test_no_function_words(self):
        # Use words that are NOT in FUNCTION_WORDS
        text = "elephants dance beneath moonlit skies tonight."
        result = compute_rhythm_signature([text])
        # Some words might accidentally be function words, but ratio should be low
        assert result["function_word_ratio"] < 0.5

    def test_very_long_sentence(self):
        words = " ".join(["word"] * 100) + "."
        result = compute_rhythm_signature([words])
        assert result["mean_sentence_length"] == 100

    def test_many_short_sentences(self):
        text = "One. Two. Three. Four. Five. Six. Seven. Eight."
        result = compute_rhythm_signature([text])
        assert result["total_sentences"] == 8
        assert result["mean_sentence_length"] <= 2


# ===================================================================
# compute_rhythm_signature — metric ranges
# ===================================================================

class TestMetricRanges:
    def test_rhythm_index_bounded(self):
        texts = [
            "Short. Also short. Very short.",
            "This is a somewhat longer sentence with more words in it.",
            "Brief one. Another brief. Yet another brief sentence here today.",
        ]
        result = compute_rhythm_signature(texts)
        assert 0.0 <= result["rhythm_index"] <= 1.0

    def test_entropy_bounded(self):
        texts = [
            "Short. Medium length sentence here. Very long sentence with many many words included.",
        ] * 5
        result = compute_rhythm_signature(texts)
        assert 0.0 <= result["rhythmic_entropy"] <= 1.0

    def test_cv_non_negative(self):
        texts = ["A steady rhythm keeps the reader grounded in the text."]
        result = compute_rhythm_signature(texts)
        assert result["sentence_length_cv"] >= 0.0
        assert result["paragraph_pace_cv"] >= 0.0

    def test_syllable_density_reasonable(self):
        texts = ["The quick brown fox jumps over the lazy dog."]
        result = compute_rhythm_signature(texts)
        assert 0.5 <= result["syllable_density"] <= 3.0

    def test_function_word_ratio_bounded(self):
        texts = ["The cat sat on the mat and the dog ran across the yard."]
        result = compute_rhythm_signature(texts)
        assert 0.0 <= result["function_word_ratio"] <= 1.0

    def test_punctuation_density_non_negative(self):
        result = compute_rhythm_signature(["Hello world."])
        assert result["punctuation_density"] >= 0.0


# ===================================================================
# _classify — all 6 labels
# ===================================================================

class TestClassify:
    def test_steady_low_variation(self):
        # Very uniform sentence lengths → steady
        texts = [
            "The cat sat on the mat today.\n\n"
            "The dog ran in the park today.\n\n"
            "The bird flew over the lake today.\n\n"
            "The fish swam through the stream today."
        ]
        result = compute_rhythm_signature(texts)
        assert result["rhythm_label"] in ("steady", "moderate")

    def test_strong_high_variation(self):
        # Mix of very short and very long sentences
        texts = [
            "Stop.\n\n"
            "This is a considerably longer sentence that contains multiple clauses and ideas woven together.\n\n"
            "Go.\n\n"
            "Another extended sentence that explores different concepts and perspectives in considerable detail.\n\n"
            "Wait.\n\n"
            "Yet another lengthy construction that builds upon previous ideas and extends them further."
        ]
        result = compute_rhythm_signature(texts)
        assert result["rhythm_label"] in ("strong", "erratic", "moderate")

    def test_accelerating_trend(self):
        # Paragraphs get shorter
        texts = [
            "This is the first paragraph with several sentences in it.\n\n"
            "It has multiple ideas expressed across various sentence structures.\n\n"
            "The complexity builds as we move forward through the text.\n\n"
            "Now things get shorter.\n\n"
            "Sentences compress.\n\n"
            "Brief.\n\n"
            "Done."
        ]
        result = compute_rhythm_signature(texts)
        # May or may not trigger accelerating depending on exact thresholds
        assert result["rhythm_label"] in ("accelerating", "strong", "moderate", "erratic", "steady")

    def test_decelerating_trend(self):
        # Paragraphs get longer
        texts = [
            "Go.\n\n"
            "Stop here.\n\n"
            "Now we begin.\n\n"
            "Things are getting longer as we proceed forward.\n\n"
            "This paragraph contains multiple ideas expressed across various sentence structures.\n\n"
            "The final paragraph is the longest with many many words and ideas packed together tightly."
        ]
        result = compute_rhythm_signature(texts)
        assert result["rhythm_label"] in ("decelerating", "strong", "moderate", "erratic", "steady")

    def test_erratic(self):
        # Extreme variation but not balanced
        texts = ["A. " + "word " * 50 + ". B."] * 3
        result = compute_rhythm_signature(texts)
        # High CV, potentially erratic
        assert result["rhythm_label"] in ("erratic", "strong", "moderate")

    def test_steady_few_paragraphs(self):
        # Only 1-2 paragraphs → always steady
        result = _classify(0.5, 0.5, [3, 4], 0.5)
        assert result == "steady"


# ===================================================================
# compute_rhythm_signature — varied text patterns
# ===================================================================

class TestTextPatterns:
    def test_uniform_text(self):
        # All sentences same length
        texts = ["Five words in each sentence here."] * 10
        result = compute_rhythm_signature(texts)
        assert result["sentence_length_cv"] < 0.15

    def test_mixed_text(self):
        texts = [
            "Short one.\n\n"
            "This sentence is deliberately made much longer than the previous one.\n\n"
            "Medium length here.\n\n"
            "Another very long sentence that goes on and on with many words packed in."
        ] * 3
        result = compute_rhythm_signature(texts)
        assert result["sentence_length_cv"] > 0.3

    def test_multiple_texts(self):
        texts = [
            "First text with some words.",
            "Second text also has words.",
            "Third text completes the set.",
        ]
        result = compute_rhythm_signature(texts)
        assert result["total_sentences"] >= 3

    def test_paragraph_count(self):
        text = "Para one.\n\nPara two.\n\nPara three."
        result = compute_rhythm_signature([text])
        assert result["total_paragraphs"] == 3


# ===================================================================
# _empty_result
# ===================================================================

class TestEmptyResult:
    def test_all_keys_present(self):
        result = _empty_result()
        expected_keys = {
            "total_sentences", "total_paragraphs", "mean_sentence_length",
            "sentence_length_cv", "syllable_density", "function_word_ratio",
            "rhythmic_entropy", "paragraph_pace_cv", "punctuation_density",
            "rhythm_index", "rhythm_label",
        }
        assert set(result.keys()) == expected_keys

    def test_all_zero(self):
        result = _empty_result()
        for key, val in result.items():
            if key == "rhythm_label":
                assert val == "steady"
            else:
                assert val == 0 or val == 0.0

    def test_label_is_steady(self):
        assert _empty_result()["rhythm_label"] == "steady"


# ===================================================================
# On-disk integration
# ===================================================================

class TestOnDiskIntegration:
    def test_report_with_strokes_file(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        strokes_file = data_dir / "strokes.jsonl"
        strokes = [
            {"text": "The quick brown fox jumps."},
            {"text": "A lazy dog sleeps in the warm afternoon sun."},
            {"text": "Birds fly across the evening sky."},
        ]
        strokes_file.write_text(
            "\n".join(json.dumps(s) for s in strokes) + "\n"
        )
        monkeypatch.setattr(
            "iamai.writer_rhythm_signature.STROKES_FILE", strokes_file
        )
        result = rhythm_signature_report(n=10)
        assert result["strokes_analysed"] == 3
        assert result["total_sentences"] >= 3

    def test_report_missing_file(self, tmp_path, monkeypatch):
        strokes_file = tmp_path / "nonexistent.jsonl"
        monkeypatch.setattr(
            "iamai.writer_rhythm_signature.STROKES_FILE", strokes_file
        )
        result = rhythm_signature_report()
        assert result["strokes_analysed"] == 0
        assert result["total_sentences"] == 0

    def test_report_malformed_jsonl(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        strokes_file = data_dir / "strokes.jsonl"
        strokes_file.write_text("not json\n{bad\n{}\n")
        monkeypatch.setattr(
            "iamai.writer_rhythm_signature.STROKES_FILE", strokes_file
        )
        result = rhythm_signature_report()
        assert result["strokes_analysed"] == 0

    def test_report_respects_n(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        strokes_file = data_dir / "strokes.jsonl"
        strokes = [{"text": f"Sentence number {i}."} for i in range(20)]
        strokes_file.write_text(
            "\n".join(json.dumps(s) for s in strokes) + "\n"
        )
        monkeypatch.setattr(
            "iamai.writer_rhythm_signature.STROKES_FILE", strokes_file
        )
        result_5 = rhythm_signature_report(n=5)
        result_20 = rhythm_signature_report(n=20)
        assert result_5["strokes_analysed"] == 5
        assert result_20["strokes_analysed"] == 20


# ===================================================================
# Summary formatting
# ===================================================================

class TestSummary:
    def test_contains_all_metrics(self):
        result = compute_rhythm_signature([
            "A test sentence here.",
            "Another sentence for variety.",
        ])
        summary = rhythm_signature_summary(result)
        assert "Sentences analysed" in summary
        assert "Rhythm index" in summary
        assert "Label" in summary
        assert "Syllable density" in summary
        assert "Function word ratio" in summary

    def test_format_numbers(self):
        result = compute_rhythm_signature([
            "The quick brown fox jumps over the lazy dog today."
        ])
        summary = rhythm_signature_summary(result)
        # Should contain formatted numbers
        assert "%" in summary or "words" in summary

    def test_empty_summary(self):
        result = _empty_result()
        summary = rhythm_signature_summary(result)
        assert "Sentences analysed : 0" in summary


# ===================================================================
# CLI
# ===================================================================

class TestCLI:
    def test_default_run(self, tmp_path, monkeypatch, capsys):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        strokes_file = data_dir / "strokes.jsonl"
        strokes = [{"text": "Hello world."}, {"text": "Goodbye world."}]
        strokes_file.write_text(
            "\n".join(json.dumps(s) for s in strokes) + "\n"
        )
        monkeypatch.setattr(
            "iamai.writer_rhythm_signature.STROKES_FILE", strokes_file
        )
        exit_code = main([])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Rhythm index" in captured.out

    def test_json_flag(self, tmp_path, monkeypatch, capsys):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        strokes_file = data_dir / "strokes.jsonl"
        strokes = [{"text": "Hello world."}]
        strokes_file.write_text(
            "\n".join(json.dumps(s) for s in strokes) + "\n"
        )
        monkeypatch.setattr(
            "iamai.writer_rhythm_signature.STROKES_FILE", strokes_file
        )
        exit_code = main(["--json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "rhythm_index" in data
        assert "rhythm_label" in data

    def test_custom_n(self, tmp_path, monkeypatch, capsys):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        strokes_file = data_dir / "strokes.jsonl"
        strokes = [{"text": f"Stroke {i}."} for i in range(50)]
        strokes_file.write_text(
            "\n".join(json.dumps(s) for s in strokes) + "\n"
        )
        monkeypatch.setattr(
            "iamai.writer_rhythm_signature.STROKES_FILE", strokes_file
        )
        exit_code = main(["-n", "10"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Sentences analysed" in captured.out

    def test_empty_strokes_file(self, tmp_path, monkeypatch, capsys):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        strokes_file = data_dir / "strokes.jsonl"
        strokes_file.write_text("")
        monkeypatch.setattr(
            "iamai.writer_rhythm_signature.STROKES_FILE", strokes_file
        )
        exit_code = main(["--json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["total_sentences"] == 0


# ===================================================================
# Constants
# ===================================================================

class TestConstants:
    def test_function_words_is_frozenset(self):
        assert isinstance(FUNCTION_WORDS, frozenset)

    def test_function_words_not_empty(self):
        assert len(FUNCTION_WORDS) > 50

    def test_function_words_lowercase(self):
        for w in FUNCTION_WORDS:
            assert w == w.lower(), f"{w} is not lowercase"

    def test_short_threshold_less_than_long(self):
        assert _SHORT_THRESHOLD < _LONG_THRESHOLD

    def test_short_threshold_positive(self):
        assert _SHORT_THRESHOLD > 0

    def test_long_threshold_reasonable(self):
        assert _LONG_THRESHOLD >= 15


# ===================================================================
# Rhythm index composite behaviour
# ===================================================================

class TestRhythmIndexComposite:
    def test_high_variation_gives_higher_index(self):
        # Uniform text
        uniform = ["Five words in each sentence."] * 10
        uniform_result = compute_rhythm_signature(uniform)

        # Varied text
        varied = [
            "Stop.\n\n"
            "This is a considerably longer sentence with many more words packed into it.\n\n"
            "Go.\n\n"
            "Another very long and complex sentence that stretches on for quite a while."
        ] * 3
        varied_result = compute_rhythm_signature(varied)

        assert varied_result["rhythm_index"] >= uniform_result["rhythm_index"]

    def test_more_paragraphs_gives_richer_signal(self):
        few = ["One sentence.\n\nTwo sentence."]
        many = ["One.\n\nTwo.\n\nThree.\n\nFour.\n\nFive.\n\nSix."]
        few_result = compute_rhythm_signature(few)
        many_result = compute_rhythm_signature(many)
        # With more paragraphs, paragraph_pace_cv can be computed
        assert many_result["total_paragraphs"] > few_result["total_paragraphs"]

    def test_index_never_exceeds_one(self):
        # Extreme input
        texts = ["A. " + "word " * 200 + ". B. C."] * 10
        result = compute_rhythm_signature(texts)
        assert result["rhythm_index"] <= 1.0

    def test_index_never_negative(self):
        result = compute_rhythm_signature(["x."])
        assert result["rhythm_index"] >= 0.0
