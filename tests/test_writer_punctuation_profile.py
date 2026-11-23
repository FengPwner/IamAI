"""Tests for iamai.writer_punctuation_profile — punctuation-based style analysis.

Visit 817: this module analyses how punctuation usage patterns reveal
writing style (formal, conversational, telegraphic, structured, fragmented).

Test areas:
     1. _count_sentences           — sentence counting
     2. _count_words               — word counting
     3. _safe_div                  — safe division helper
     4. analyse_text (empty)       — empty input handling
     5. analyse_text (basic)       — basic metric computation
     6. formality_index            — formal vs informal scoring
     7. fragmentation_index        — fragmentation detection
     8. _classify_style            — style label classification
     9. profile_report             — on-disk integration
    10. profile_summary            — human-readable output
    11. _cli                       — exit codes, --json flag
    12. edge cases                 — degenerate inputs
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_punctuation_profile import (
    _classify_style,
    _cli,
    _count_sentences,
    _count_words,
    _empty_report,
    _safe_div,
    analyse_text,
    profile_report,
    profile_summary,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _stroke(text: str = "Hello, world.", seq: int = 0, kind: str = "thought") -> dict:
    return {"seq": seq, "at": "2026-01-01T00:00:00+00:00", "kind": kind, "text": text}


def _write_strokes(tmp_path: Path, strokes: list[dict]) -> Path:
    p = tmp_path / "strokes.jsonl"
    with open(p, "w") as f:
        for s in strokes:
            f.write(json.dumps(s) + "\n")
    return p


# -----------------------------------------------------------------------
# 1. _count_sentences
# -----------------------------------------------------------------------


class TestCountSentences:
    def test_single_sentence(self):
        assert _count_sentences("Hello world.") == 1

    def test_multiple_sentences(self):
        assert _count_sentences("First. Second. Third.") == 3

    def test_questions_and_exclamations(self):
        assert _count_sentences("Really? Yes! Done.") == 3

    def test_no_punctuation_returns_one(self):
        assert _count_sentences("no punctuation here") == 1

    def test_empty_string_returns_one(self):
        assert _count_sentences("") == 1

    def test_multiple_dots_counted(self):
        # "Really?! Yes." has two terminal marks
        assert _count_sentences("Really?! Yes.") == 2


# -----------------------------------------------------------------------
# 2. _count_words
# -----------------------------------------------------------------------


class TestCountWords:
    def test_basic_words(self):
        assert _count_words("hello world") == 2

    def test_words_with_punctuation(self):
        assert _count_words("hello, world!") == 2

    def test_empty_string(self):
        assert _count_words("") == 0

    def test_numbers_count(self):
        assert _count_words("test 123 values") == 3

    def test_contraction(self):
        # "don't" has two word parts: "don" and "t"
        count = _count_words("don't stop")
        assert count >= 2


# -----------------------------------------------------------------------
# 3. _safe_div
# -----------------------------------------------------------------------


class TestSafeDiv:
    def test_normal_division(self):
        assert _safe_div(10.0, 5.0) == 2.0

    def test_zero_denominator_returns_default(self):
        assert _safe_div(10.0, 0.0) == 0.0

    def test_custom_default(self):
        assert _safe_div(10.0, 0.0, 99.0) == 99.0

    def test_zero_numerator(self):
        assert _safe_div(0.0, 5.0) == 0.0


# -----------------------------------------------------------------------
# 4. analyse_text — empty input
# -----------------------------------------------------------------------


class TestAnalyseTextEmpty:
    def test_empty_list(self):
        result = analyse_text([])
        assert result["total_strokes"] == 0
        assert result["style_label"] == "empty"

    def test_all_empty_strings(self):
        result = analyse_text(["", "", ""])
        assert result["total_words"] == 0
        assert result["style_label"] == "empty"


# -----------------------------------------------------------------------
# 5. analyse_text — basic metrics
# -----------------------------------------------------------------------


class TestAnalyseTextBasic:
    def test_simple_text(self):
        texts = ["Hello, world. How are you? I am fine!"]
        result = analyse_text(texts)
        assert result["total_strokes"] == 1
        assert result["total_words"] > 0
        assert result["total_sentences"] == 3  # period, question, exclamation
        assert result["comma_ratio"] > 0
        assert result["question_ratio"] > 0
        assert result["exclamation_ratio"] > 0

    def test_semicolons_detected(self):
        texts = ["First clause; second clause; third clause."]
        result = analyse_text(texts)
        assert result["semicolon_ratio"] > 0

    def test_colons_detected(self):
        texts = ["Here it is: the answer. Next: more."]
        result = analyse_text(texts)
        assert result["colon_ratio"] > 0

    def test_dashes_detected(self):
        texts = ["This — that — the other thing."]
        result = analyse_text(texts)
        assert result["dash_ratio"] > 0

    def test_parentheticals_detected(self):
        texts = ["This (important) thing (also key) matters."]
        result = analyse_text(texts)
        assert result["parenthetical_ratio"] > 0

    def test_ellipsis_detected(self):
        texts = ["Well... maybe... perhaps..."]
        result = analyse_text(texts)
        assert result["ellipsis_ratio"] > 0

    def test_punctuation_density_positive(self):
        texts = ["Hello, world. This is a test."]
        result = analyse_text(texts)
        assert result["punctuation_density"] > 0


# -----------------------------------------------------------------------
# 6. formality_index
# -----------------------------------------------------------------------


class TestFormalityIndex:
    def test_formal_text_high_score(self):
        # Many semicolons and colons, no exclamations
        texts = [
            "First point; second point; third. "
            "Moreover: the data shows this; furthermore: it persists. "
            "Consider: one aspect; another aspect; final aspect."
        ]
        result = analyse_text(texts)
        assert result["formality_index"] > 0.5

    def test_informal_text_low_score(self):
        # Many exclamations, no semicolons or colons
        texts = [
            "Wow! Amazing! Incredible! So cool! "
            "Can't believe it! Unbelievable! Fantastic! Great!"
        ]
        result = analyse_text(texts)
        assert result["formality_index"] < 0.5

    def test_mixed_text_moderate_score(self):
        texts = [
            "Point one; point two. Here: the thing! "
            "Wow! Look at that; and this."
        ]
        result = analyse_text(texts)
        assert 0.0 <= result["formality_index"] <= 1.0


# -----------------------------------------------------------------------
# 7. fragmentation_index
# -----------------------------------------------------------------------


class TestFragmentationIndex:
    def test_fragmented_text_high_score(self):
        texts = [
            "This — that — the other — more stuff — and more. "
            "Then... well... maybe... perhaps... I don't know..."
        ]
        result = analyse_text(texts)
        assert result["fragmentation_index"] > 0.1

    def test_clean_text_low_score(self):
        texts = [
            "The quick brown fox jumps over the lazy dog. "
            "Simple sentences are easy to read. Facts are clear."
        ]
        result = analyse_text(texts)
        assert result["fragmentation_index"] < 0.3

    def test_fragmentation_bounded(self):
        # Even extreme fragmentation should be capped at 1.0
        texts = [" — — — — — — — — — — ."]
        result = analyse_text(texts)
        assert result["fragmentation_index"] <= 1.0


# -----------------------------------------------------------------------
# 8. _classify_style
# -----------------------------------------------------------------------


class TestClassifyStyle:
    def test_telegraphic(self):
        assert _classify_style(2.0, 0.5, 0.1, 0.0, 0.0, 0.0) == "telegraphic"

    def test_structured(self):
        assert _classify_style(10.0, 0.7, 0.1, 0.0, 0.2, 0.2) == "structured"

    def test_fragmented(self):
        assert _classify_style(10.0, 0.3, 0.7, 0.0, 0.0, 0.0) == "fragmented"

    def test_formal(self):
        # formality > 0.65 AND question_ratio < 0.08 → formal
        assert _classify_style(10.0, 0.8, 0.1, 0.02, 0.05, 0.05) == "formal"

    def test_conversational(self):
        assert _classify_style(8.0, 0.4, 0.1, 0.15, 0.02, 0.02) == "conversational"

    def test_balanced(self):
        # formality ≥ 0.65 AND question_ratio ≥ 0.1 avoids both "formal" and "conversational"
        assert _classify_style(8.0, 0.70, 0.1, 0.12, 0.05, 0.05) == "balanced"

    def test_telegraphic_takes_priority(self):
        # Even if other signals suggest structured, low density → telegraphic
        assert _classify_style(1.0, 0.9, 0.0, 0.0, 0.5, 0.5) == "telegraphic"


# -----------------------------------------------------------------------
# 9. profile_report — on-disk integration
# -----------------------------------------------------------------------


class TestProfileReport:
    def test_basic_report(self, tmp_path: Path) -> None:
        strokes = [
            _stroke("Hello, world. This is a test.", seq=i)
            for i in range(20)
        ]
        path = _write_strokes(tmp_path, strokes)
        result = profile_report(n=20, strokes_path=path)
        assert result["total_strokes"] == 20
        assert result["style_label"] != "empty"
        assert result["punctuation_density"] > 0

    def test_report_with_mixed_styles(self, tmp_path: Path) -> None:
        strokes = []
        for i in range(30):
            if i % 3 == 0:
                strokes.append(_stroke(f"Formal statement; with structure: point {i}.", seq=i))
            elif i % 3 == 1:
                strokes.append(_stroke(f"Really? Is that so! Wow!", seq=i))
            else:
                strokes.append(_stroke(f"Thinking... about stuff... maybe...", seq=i))
        path = _write_strokes(tmp_path, strokes)
        result = profile_report(n=30, strokes_path=path)
        assert result["total_strokes"] == 30
        assert result["semicolon_ratio"] > 0
        assert result["question_ratio"] > 0
        assert result["ellipsis_ratio"] > 0


# -----------------------------------------------------------------------
# 10. profile_summary
# -----------------------------------------------------------------------


class TestProfileSummary:
    def test_empty_report(self):
        result = _empty_report()
        summary = profile_summary(result)
        assert "No strokes" in summary

    def test_normal_report(self, tmp_path: Path) -> None:
        strokes = [_stroke("Hello, world. Test sentence.", seq=0)] * 10
        path = _write_strokes(tmp_path, strokes)
        report = profile_report(n=10, strokes_path=path)
        summary = profile_summary(report)
        assert "writer_punctuation_profile" in summary
        assert "style=" in summary
        assert "punctuation density" in summary

    def test_summary_with_questions(self, tmp_path: Path) -> None:
        strokes = [_stroke("Is this right? What about this?", seq=0)] * 10
        path = _write_strokes(tmp_path, strokes)
        report = profile_report(n=10, strokes_path=path)
        summary = profile_summary(report)
        assert "questions" in summary

    def test_summary_ends_with_period(self, tmp_path: Path) -> None:
        strokes = [_stroke("Test.", seq=0)] * 5
        path = _write_strokes(tmp_path, strokes)
        report = profile_report(n=5, strokes_path=path)
        summary = profile_summary(report)
        assert summary.endswith(".")


# -----------------------------------------------------------------------
# 11. _cli
# -----------------------------------------------------------------------


class TestCLI:
    def test_normal_output(self, tmp_path: Path, capsys) -> None:
        strokes = [_stroke("Hello, world.", seq=0)] * 10
        path = _write_strokes(tmp_path, strokes)
        with patch(
            "iamai.writer_punctuation_profile.DEFAULT_STROKES_PATH", path
        ):
            exit_code = _cli(["-n", "10"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "writer_punctuation_profile" in captured.out

    def test_json_output(self, tmp_path: Path, capsys) -> None:
        strokes = [_stroke("Hello, world.", seq=0)] * 10
        path = _write_strokes(tmp_path, strokes)
        with patch(
            "iamai.writer_punctuation_profile.DEFAULT_STROKES_PATH", path
        ):
            exit_code = _cli(["-n", "10", "--json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "style_label" in data
        assert "punctuation_density" in data

    def test_default_n(self, tmp_path: Path, capsys) -> None:
        strokes = [_stroke("Test.", seq=i) for i in range(50)]
        path = _write_strokes(tmp_path, strokes)
        with patch(
            "iamai.writer_punctuation_profile.DEFAULT_STROKES_PATH", path
        ):
            exit_code = _cli([])
        assert exit_code == 0


# -----------------------------------------------------------------------
# 12. Edge cases
# -----------------------------------------------------------------------


class TestEdgeCases:
    def test_single_stroke(self):
        result = analyse_text(["One sentence."])
        assert result["total_strokes"] == 1
        assert result["total_sentences"] == 1

    def test_no_punctuation_at_all(self):
        result = analyse_text(["no punctuation here at all just words"])
        assert result["punctuation_density"] == 0.0
        assert result["style_label"] == "telegraphic"

    def test_only_punctuation(self):
        result = analyse_text(["...!!!???"])
        assert result["total_strokes"] == 1
        assert result["punctuation_density"] > 0

    def test_very_long_text(self):
        text = "This is a sentence. " * 1000
        result = analyse_text([text])
        assert result["total_words"] > 1000
        assert result["style_label"] != "empty"

    def test_many_strokes(self):
        texts = [f"Sentence number {i}. With a comma, here." for i in range(500)]
        result = analyse_text(texts)
        assert result["total_strokes"] == 500

    def test_unicode_ellipsis(self):
        result = analyse_text(["Thinking… about stuff…"])
        assert result["ellipsis_ratio"] > 0

    def test_em_dash_unicode(self):
        result = analyse_text(["This — that — the other."])
        assert result["dash_ratio"] > 0

    def test_all_fields_present_in_result(self):
        result = analyse_text(["Test sentence."])
        expected_keys = {
            "total_strokes", "total_words", "total_sentences",
            "punctuation_density", "comma_ratio", "semicolon_ratio",
            "colon_ratio", "dash_ratio", "question_ratio",
            "exclamation_ratio", "parenthetical_ratio", "ellipsis_ratio",
            "formality_index", "fragmentation_index", "style_label",
        }
        assert set(result.keys()) == expected_keys

    def test_empty_report_fields(self):
        result = _empty_report()
        assert result["total_strokes"] == 0
        assert result["style_label"] == "empty"
        assert result["formality_index"] == 0.0
        assert result["fragmentation_index"] == 0.0

    def test_deterministic_output(self):
        texts = ["Hello, world. How are you? Fine; thanks."]
        r1 = analyse_text(texts)
        r2 = analyse_text(texts)
        assert r1 == r2
