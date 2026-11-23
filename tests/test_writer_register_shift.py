#!/usr/bin/env python3
"""Tests for writer_register_shift module."""

import json
import sys
import os
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iamai.writer_register_shift import (
    _DEFAULT_SHIFT_THRESHOLD,
    _FORMAL_PATTERNS,
    _INFORMAL_PATTERNS,
    _NOMINALISATION_RE,
    _PASSIVE_RE,
    _classify,
    _empty_result,
    _score_segment,
    _split_segments,
    compute_register_shift,
    main,
    register_shift_report,
    register_shift_summary,
)


# ===================================================================
# _split_segments
# ===================================================================

class TestSplitSegments:
    def test_paragraph_breaks(self):
        text = "First paragraph.\n\nSecond paragraph."
        segs = _split_segments(text)
        assert len(segs) == 2
        assert segs[0] == "First paragraph."
        assert segs[1] == "Second paragraph."

    def test_single_newline_fallback(self):
        text = "Line one.\nLine two.\nLine three."
        segs = _split_segments(text)
        assert len(segs) == 3

    def test_empty_text(self):
        assert _split_segments("") == []

    def test_whitespace_only(self):
        assert _split_segments("   \n  \n   ") == []

    def test_single_paragraph(self):
        text = "Just one paragraph with some words."
        segs = _split_segments(text)
        assert len(segs) == 1

    def test_multiple_blank_lines(self):
        text = "Para one.\n\n\n\nPara two."
        segs = _split_segments(text)
        assert len(segs) == 2

    def test_strips_whitespace(self):
        text = "  Hello world  \n\n  Another one  "
        segs = _split_segments(text)
        assert segs[0] == "Hello world"
        assert segs[1] == "Another one"


# ===================================================================
# _score_segment
# ===================================================================

class TestScoreSegment:
    def test_empty(self):
        assert _score_segment("") == 0.5

    def test_very_short(self):
        assert _score_segment("Hi") == 0.5

    def test_neutral_text(self):
        score = _score_segment("The cat sat on the mat and looked around.")
        assert 0.3 <= score <= 0.7

    def test_informal_text(self):
        score = _score_segment(
            "Yeah I'm gonna grab some stuff, it's totally cool, "
            "no worries, I got this, honestly it's kinda awesome!"
        )
        assert score < 0.4

    def test_formal_text(self):
        score = _score_segment(
            "Furthermore, the implementation shall be established "
            "pursuant to the aforementioned regulations, and "
            "stakeholders must demonstrate compliance therewith."
        )
        assert score > 0.6

    def test_mixed_text(self):
        score = _score_segment(
            "The system was implemented pursuant to regulations. "
            "It's gonna be totally awesome, honestly!"
        )
        # Should be somewhere in the middle
        assert 0.2 <= score <= 0.8

    def test_score_bounded(self):
        # Very informal
        s1 = _score_segment(
            "lol omg gonna wanna gotta yeah nah kinda sorta stuff " * 5
        )
        assert 0.0 <= s1 <= 1.0

        # Very formal
        s2 = _score_segment(
            "furthermore moreover consequently nevertheless hence "
            "pursuant aforementioned herein whereby shall utilize "
            "implement facilitate demonstrate establish " * 5
        )
        assert 0.0 <= s2 <= 1.0


# ===================================================================
# Informal patterns
# ===================================================================

class TestInformalPatterns:
    def test_gonna(self):
        assert any(p.search("I'm gonna go") for p in _INFORMAL_PATTERNS)

    def test_lol(self):
        assert any(p.search("lol that's funny") for p in _INFORMAL_PATTERNS)

    def test_contractions(self):
        assert any(p.search("I don't think so") for p in _INFORMAL_PATTERNS)

    def test_exclamation(self):
        assert any(p.search("Wow!") for p in _INFORMAL_PATTERNS)

    def test_trailing_dots(self):
        assert any(p.search("well...") for p in _INFORMAL_PATTERNS)

    def test_casual_words(self):
        assert any(p.search("that's cool stuff") for p in _INFORMAL_PATTERNS)


# ===================================================================
# Formal patterns
# ===================================================================

class TestFormalPatterns:
    def test_furthermore(self):
        assert any(p.search("Furthermore, we note") for p in _FORMAL_PATTERNS)

    def test_pursuant(self):
        assert any(p.search("pursuant to the agreement") for p in _FORMAL_PATTERNS)

    def test_shall(self):
        assert any(p.search("shall be implemented") for p in _FORMAL_PATTERNS)

    def test_utilize(self):
        assert any(p.search("utilize the resources") for p in _FORMAL_PATTERNS)

    def test_in_accordance(self):
        assert any(
            p.search("in accordance with policy") for p in _FORMAL_PATTERNS
        )

    def test_stakeholder(self):
        assert any(p.search("all stakeholder groups agree") for p in _FORMAL_PATTERNS)


# ===================================================================
# Passive voice
# ===================================================================

class TestPassiveVoice:
    def test_is_written(self):
        assert _PASSIVE_RE.search("The report is written clearly.")

    def test_was_established(self):
        assert _PASSIVE_RE.search("The rule was established in 1990.")

    def test_has_been_demonstrated(self):
        assert _PASSIVE_RE.search("It has been demonstrated that...")

    def test_active_voice_no_match(self):
        assert not _PASSIVE_RE.search("She writes the report.")

    def test_be_seen(self):
        # "seen" ends in -en
        assert _PASSIVE_RE.search("It can be seen from the data.")


# ===================================================================
# Nominalisation
# ===================================================================

class TestNominalisation:
    def test_tion(self):
        assert _NOMINALISATION_RE.search("implementation")

    def test_ment(self):
        assert _NOMINALISATION_RE.search("establishment")

    def test_ness(self):
        assert _NOMINALISATION_RE.search("awareness")

    def test_ity(self):
        assert _NOMINALISATION_RE.search("capability")

    def test_no_match(self):
        assert not _NOMINALISATION_RE.search("cat dog run fast")


# ===================================================================
# _classify
# ===================================================================

class TestClassify:
    def test_consistent(self):
        scores = [0.5, 0.51, 0.49, 0.50, 0.52]
        label = _classify(scores, 0.5, 0.01, 0.0, 0.02, 0.30)
        assert label == "consistent"

    def test_mostly_stable(self):
        scores = [0.5, 0.55, 0.48, 0.52, 0.50, 0.53, 0.47]
        label = _classify(scores, 0.5, 0.10, 0.0, 0.10, 0.30)
        assert label == "mostly_stable"

    def test_volatile_high_shift_rate(self):
        # Balanced mean across halves but big adjacent jumps
        scores = [0.2, 0.8, 0.1, 0.8, 0.1, 0.2]
        shifts = [abs(scores[i] - scores[i-1]) for i in range(1, len(scores))]
        shift_rate = sum(1 for s in shifts if s > 0.30) / len(shifts)
        label = _classify(scores, 0.37, 0.35, shift_rate, max(shifts), 0.30)
        assert label == "volatile"

    def test_formalising(self):
        # First half informal, second half formal
        scores = [0.2, 0.25, 0.3, 0.25, 0.7, 0.75, 0.8, 0.85]
        shifts = [abs(scores[i] - scores[i-1]) for i in range(1, len(scores))]
        shift_rate = sum(1 for s in shifts if s > 0.30) / len(shifts)
        label = _classify(scores, 0.5, 0.28, shift_rate, max(shifts), 0.30)
        assert label == "formalising"

    def test_informalising(self):
        # First half formal, second half informal
        scores = [0.8, 0.85, 0.75, 0.80, 0.3, 0.25, 0.2, 0.15]
        shifts = [abs(scores[i] - scores[i-1]) for i in range(1, len(scores))]
        shift_rate = sum(1 for s in shifts if s > 0.30) / len(shifts)
        label = _classify(scores, 0.5, 0.30, shift_rate, max(shifts), 0.30)
        assert label == "informalising"

    def test_mixed(self):
        scores = [0.4, 0.6, 0.35, 0.65, 0.5, 0.55]
        shifts = [abs(scores[i] - scores[i-1]) for i in range(1, len(scores))]
        shift_rate = sum(1 for s in shifts if s > 0.30) / len(shifts)
        label = _classify(scores, 0.5, 0.12, shift_rate, max(shifts), 0.30)
        assert label in ("mixed", "mostly_stable")

    def test_empty(self):
        assert _classify([], 0.5, 0.0, 0.0, 0.0, 0.30) == "consistent"


# ===================================================================
# _empty_result
# ===================================================================

class TestEmptyResult:
    def test_structure(self):
        result = _empty_result()
        assert result["total_segments"] == 0
        assert result["mean_formality"] == 0.5
        assert result["formality_std"] == 0.0
        assert result["shift_count"] == 0
        assert result["register_label"] == "consistent"
        assert result["segment_scores"] == []


# ===================================================================
# compute_register_shift
# ===================================================================

class TestComputeRegisterShift:
    def test_empty_input(self):
        result = compute_register_shift([])
        assert result["total_segments"] == 0
        assert result["register_label"] == "consistent"

    def test_single_text(self):
        result = compute_register_shift([
            "This is a simple text with some words in it."
        ])
        assert result["total_segments"] >= 1
        assert 0.0 <= result["mean_formality"] <= 1.0
        assert result["shift_count"] == 0

    def test_uniform_formal(self):
        texts = [
            "Furthermore, the implementation shall be established.\n\n"
            "Moreover, stakeholders must demonstrate compliance.\n\n"
            "Consequently, the entity shall utilise all resources."
        ]
        result = compute_register_shift(texts)
        assert result["mean_formality"] > 0.5
        assert result["formality_std"] < 0.20

    def test_uniform_informal(self):
        texts = [
            "Yeah I'm gonna grab some stuff!\n\n"
            "It's totally cool, no worries!\n\n"
            "Honestly, it's kinda awesome, lol!"
        ]
        result = compute_register_shift(texts)
        assert result["mean_formality"] < 0.5
        assert result["formality_std"] < 0.20

    def test_mixed_register(self):
        texts = [
            "Yeah I'm gonna grab some stuff, it's totally cool!\n\n"
            "Furthermore, the implementation shall be established "
            "pursuant to the aforementioned regulations.\n\n"
            "lol omg that's awesome, wanna come along?\n\n"
            "Moreover, stakeholders must demonstrate compliance "
            "in accordance with the established protocols."
        ]
        result = compute_register_shift(texts)
        assert result["formality_std"] > 0.10
        assert result["shift_count"] >= 1

    def test_shift_rate_bounded(self):
        texts = ["Hello world.\n\nAnother paragraph.\n\nThird one here."]
        result = compute_register_shift(texts)
        assert 0.0 <= result["shift_rate"] <= 1.0

    def test_max_shift_non_negative(self):
        texts = ["First para.\n\nSecond para.\n\nThird para."]
        result = compute_register_shift(texts)
        assert result["max_shift"] >= 0.0

    def test_shift_direction_stable(self):
        texts = [
            "The cat sat on the mat.\n\n"
            "The dog ran in the park.\n\n"
            "The bird flew over the tree.\n\n"
            "The fish swam in the pond."
        ]
        result = compute_register_shift(texts)
        assert result["shift_direction"] in ("stable", "formalising", "informalising")

    def test_custom_threshold(self):
        texts = [
            "Informal stuff here, gonna be cool!\n\n"
            "Formal implementation shall be established."
        ]
        # With a very high threshold, no shifts detected
        result_high = compute_register_shift(texts, shift_threshold=0.99)
        # With default threshold, shift should be detected
        result_default = compute_register_shift(texts)
        assert result_high["shift_count"] <= result_default["shift_count"]

    def test_segment_scores_present(self):
        texts = ["Para one.\n\nPara two.\n\nPara three."]
        result = compute_register_shift(texts)
        assert len(result["segment_scores"]) == result["total_segments"]
        for s in result["segment_scores"]:
            assert 0.0 <= s <= 1.0

    def test_multiple_texts(self):
        texts = [
            "First text, paragraph one.\n\nFirst text, paragraph two.",
            "Second text, paragraph one.\n\nSecond text, paragraph two.",
        ]
        result = compute_register_shift(texts)
        assert result["total_segments"] >= 4

    def test_formality_range(self):
        texts = [
            "lol gonna wanna stuff!\n\n"
            "Furthermore, the implementation shall be established."
        ]
        result = compute_register_shift(texts)
        assert result["formality_range"] >= 0.0
        assert result["formality_range"] <= 1.0

    def test_all_fields_present(self):
        result = compute_register_shift(["Hello world."])
        expected_keys = {
            "total_segments", "mean_formality", "formality_std",
            "formality_range", "shift_count", "shift_rate",
            "max_shift", "shift_direction", "register_label",
            "segment_scores",
        }
        assert expected_keys.issubset(result.keys())


# ===================================================================
# register_shift_report / summary
# ===================================================================

class TestReportAndSummary:
    def test_report_returns_dict(self, tmp_path, monkeypatch):
        # Create a fake strokes file
        strokes_file = tmp_path / "strokes.jsonl"
        strokes_file.write_text(
            '{"text": "Hello world."}\n'
            '{"text": "Another stroke."}\n'
        )
        # Monkeypatch the STROKES_FILE
        import iamai.writer_register_shift as mod
        monkeypatch.setattr(mod, "STROKES_FILE", strokes_file)
        result = register_shift_report(n=10)
        assert "strokes_analysed" in result
        assert result["strokes_analysed"] == 2

    def test_report_missing_file(self, tmp_path, monkeypatch):
        import iamai.writer_register_shift as mod
        monkeypatch.setattr(mod, "STROKES_FILE", tmp_path / "nonexistent.jsonl")
        result = register_shift_report()
        assert result["total_segments"] == 0

    def test_summary_format(self):
        metrics = compute_register_shift(["Hello world.\n\nAnother para."])
        summary = register_shift_summary(metrics)
        assert "Segments analysed" in summary
        assert "Mean formality" in summary
        assert "Register label" in summary
        # Should have 9 lines
        lines = summary.strip().split("\n")
        assert len(lines) == 9


# ===================================================================
# CLI (main)
# ===================================================================

class TestMain:
    def test_main_default(self, tmp_path, monkeypatch, capsys):
        strokes_file = tmp_path / "strokes.jsonl"
        strokes_file.write_text('{"text": "Hello world."}\n')
        import iamai.writer_register_shift as mod
        monkeypatch.setattr(mod, "STROKES_FILE", strokes_file)
        ret = main(["-n", "5"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "Segments analysed" in captured.out

    def test_main_json(self, tmp_path, monkeypatch, capsys):
        strokes_file = tmp_path / "strokes.jsonl"
        strokes_file.write_text('{"text": "Hello world."}\n')
        import iamai.writer_register_shift as mod
        monkeypatch.setattr(mod, "STROKES_FILE", strokes_file)
        ret = main(["-n", "5", "--json"])
        assert ret == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "mean_formality" in data


# ===================================================================
# Edge cases
# ===================================================================

class TestEdgeCases:
    def test_unicode_text(self):
        texts = [
            "Héllo wörld, this is a test with ünïcödé characters.\n\n"
            "Another paragraph with émojis 🎉 and spëcial chars."
        ]
        result = compute_register_shift(texts)
        assert result["total_segments"] >= 2

    def test_very_long_text(self):
        para = "This is a moderately formal sentence about implementation. " * 20
        texts = [para]
        result = compute_register_shift(texts)
        assert result["total_segments"] >= 1

    def test_single_word_paragraphs(self):
        texts = ["Hello\n\nWorld\n\nTest\n\nMore"]
        result = compute_register_shift(texts)
        assert result["total_segments"] >= 1

    def test_json_decode_error_skipped(self, tmp_path, monkeypatch):
        import iamai.writer_register_shift as mod
        strokes_file = tmp_path / "strokes.jsonl"
        strokes_file.write_text(
            '{"text": "Valid stroke."}\n'
            'INVALID JSON LINE\n'
            '{"text": "Another valid stroke."}\n'
        )
        monkeypatch.setattr(mod, "STROKES_FILE", strokes_file)
        result = register_shift_report(n=10)
        assert result["strokes_analysed"] == 2

    def test_empty_text_field_skipped(self, tmp_path, monkeypatch):
        import iamai.writer_register_shift as mod
        strokes_file = tmp_path / "strokes.jsonl"
        strokes_file.write_text(
            '{"text": ""}\n'
            '{"text": "Valid stroke."}\n'
            '{"other": "no text field"}\n'
        )
        monkeypatch.setattr(mod, "STROKES_FILE", strokes_file)
        result = register_shift_report(n=10)
        assert result["strokes_analysed"] == 1

    def test_repeated_identical_segments(self):
        texts = ["Same thing.\n\nSame thing.\n\nSame thing.\n\nSame thing."]
        result = compute_register_shift(texts)
        assert result["formality_std"] < 0.05
        assert result["register_label"] in ("consistent", "mostly_stable")

    def test_alternating_register(self):
        texts = [
            "lol gonna grab stuff!\n\n"
            "Furthermore, implementation shall proceed.\n\n"
            "omg that's totally cool!\n\n"
            "Pursuant to the aforementioned regulations.\n\n"
            "wanna come hang out?\n\n"
            "Stakeholders must demonstrate compliance."
        ]
        result = compute_register_shift(texts)
        assert result["formality_std"] > 0.15
        assert result["shift_count"] >= 2
