"""Tests for tools/stroke_vocabulary.py — lexical diversity analysis.

Run:  python3 -m pytest tests/test_stroke_vocabulary.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import stroke_vocabulary as sv  # noqa: E402


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_basic_english(self):
        tokens = sv._tokenize("growth that never stops is a tumour")
        assert "growth" in tokens
        assert "that" in tokens
        assert "never" in tokens
        assert "stops" in tokens
        assert "tumour" in tokens

    def test_strips_measured_now_suffix(self):
        text = "growth is a tumour -- measured now: 100 lines across 50 files"
        tokens = sv._tokenize(text)
        # "measured" and content after separator should be gone
        assert "measured" not in tokens
        assert "lines" not in tokens
        assert "files" not in tokens

    def test_lowercases(self):
        tokens = sv._tokenize("Growth NEVER Stops")
        assert all(t == t.lower() for t in tokens)

    def test_drops_short_tokens(self):
        tokens = sv._tokenize("a I is to be the at")
        # single-char tokens should be dropped; "is", "to", "be", "the", "at" kept
        assert "is" in tokens
        assert "to" in tokens

    def test_chinese_characters(self):
        tokens = sv._tokenize("日志每行只留四十个字")
        assert len(tokens) > 0

    def test_empty_string(self):
        assert sv._tokenize("") == []

    def test_punctuation_stripped(self):
        tokens = sv._tokenize("hello, world! test--ok")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens


# ---------------------------------------------------------------------------
# load_strokes
# ---------------------------------------------------------------------------

class TestLoadStrokes:
    def test_load_from_jsonl(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text(
            '{"seq": 1, "text": "alpha beta gamma"}\n'
            '{"seq": 2, "text": "delta epsilon"}\n'
            '{"seq": 3, "text": "alpha beta gamma"}\n'
        )
        strokes = sv.load_strokes(f)
        assert len(strokes) == 3
        assert strokes[0]["seq"] == 1

    def test_tail_limits(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        lines = [f'{{"seq": {i}, "text": "word{i}"}}' for i in range(50)]
        f.write_text("\n".join(lines) + "\n")
        strokes = sv.load_strokes(f, tail=10)
        assert len(strokes) == 10
        assert strokes[0]["seq"] == 40

    def test_missing_file(self, tmp_path):
        f = tmp_path / "nope.jsonl"
        assert sv.load_strokes(f) == []

    def test_malformed_lines_skipped(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text(
            '{"seq": 1, "text": "good"}\n'
            'broken json\n'
            '{"seq": 3, "text": "also good"}\n'
        )
        strokes = sv.load_strokes(f)
        assert len(strokes) == 2


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_empty_strokes(self):
        result = sv.analyze([])
        assert result["total_strokes"] == 0
        assert result["severity"] == "barren"

    def test_all_unique_words(self):
        strokes = [
            {"text": "alpha bravo charlie delta echo"},
            {"text": "foxtrot golf hotel india juliet"},
            {"text": "kilo lima mike november oscar"},
        ]
        result = sv.analyze(strokes)
        assert result["type_token_ratio"] == 1.0
        assert result["severity"] == "rich"

    def test_all_same_words(self):
        strokes = [{"text": "the the the the the"} for _ in range(20)]
        result = sv.analyze(strokes)
        assert result["unique_words"] == 1
        assert result["type_token_ratio"] < 0.05
        assert result["severity"] == "barren"

    def test_window_limits_scope(self):
        strokes = [
            {"text": "unique alpha bravo"} for _ in range(90)
        ] + [
            {"text": "unique alpha bravo"} for _ in range(10)
        ]
        result_all = sv.analyze(strokes)
        result_win = sv.analyze(strokes, window=10)
        assert result_all["total_strokes"] == 100
        assert result_win["total_strokes"] == 10

    def test_min_words_filter(self):
        strokes = [
            {"text": "ok"},  # 1 word — filtered with min_words=2
            {"text": "alpha bravo charlie"},
            {"text": "si"},  # 1 word — filtered
            {"text": "delta echo foxtrot"},
        ]
        result = sv.analyze(strokes, min_words=2)
        assert result["total_strokes"] == 4  # total before filter
        # but only 2 strokes contributed tokens
        assert result["total_words"] == 6

    def test_hapax_ratio(self):
        # "alpha" appears 3 times, "bravo" once, "charlie" once
        strokes = [
            {"text": "alpha alpha alpha bravo charlie"},
        ]
        result = sv.analyze(strokes)
        # unique words = 3 (alpha, bravo, charlie)
        # hapax = 2 (bravo, charlie — used exactly once)
        assert result["unique_words"] == 3
        assert abs(result["hapax_ratio"] - 2 / 3) < 0.01

    def test_severity_rich(self):
        # 50 unique words in 60 total → TTR ≈ 0.83
        base = "abcdefghijklmnopqrstuvwxyz"
        words = [base[i:i+4]*2 for i in range(50)] + [base[i:i+4]*2 for i in range(10)]
        strokes = [{"text": " ".join(words)}]
        result = sv.analyze(strokes)
        assert result["severity"] == "rich"

    def test_severity_flat(self):
        # 10 unique words repeated 3 times = 30 total → TTR ≈ 0.33
        words = ["alpha", "bravo", "charlie", "delta", "echo",
                 "foxtrot", "golf", "hotel", "india", "juliet"] * 3
        strokes = [{"text": " ".join(words)}]
        result = sv.analyze(strokes)
        assert 0.20 <= result["type_token_ratio"] < 0.40
        assert result["severity"] == "flat"

    def test_severity_barren(self):
        # 3 unique words in 30 total → TTR = 0.10
        words = ["the", "is", "and"] * 10
        strokes = [{"text": " ".join(words)}]
        result = sv.analyze(strokes)
        assert result["severity"] == "barren"

    def test_measured_now_stripped_from_tokens(self):
        strokes = [
            {"text": "growth that never stops -- measured now: 2790 lines across 34 tracked files"},
        ]
        result = sv.analyze(strokes)
        # "lines", "across", "tracked", "files" should NOT be in tokens
        assert result["unique_words"] > 0
        # Check that measured-now suffix words aren't counted
        # by re-tokenizing manually
        tokens = sv._tokenize(strokes[0]["text"])
        assert "lines" not in tokens
        assert "tracked" not in tokens

    def test_json_output_structure(self):
        strokes = [{"text": "alpha bravo"}, {"text": "charlie delta"}]
        result = sv.analyze(strokes)
        assert "total_strokes" in result
        assert "total_words" in result
        assert "unique_words" in result
        assert "type_token_ratio" in result
        assert "mean_length" in result
        assert "hapax_ratio" in result
        assert "severity" in result


# ---------------------------------------------------------------------------
# severity_exit
# ---------------------------------------------------------------------------

class TestSeverityExit:
    def test_rich_returns_0(self):
        assert sv.severity_exit("rich") == 0

    def test_flat_returns_1(self):
        assert sv.severity_exit("flat") == 1

    def test_barren_returns_2(self):
        assert sv.severity_exit("barren") == 2

    def test_unknown_returns_2(self):
        assert sv.severity_exit("wat") == 2


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_contains_all_fields(self):
        result = sv.analyze([{"text": "alpha bravo charlie"}])
        report = sv.format_report(result)
        assert "stroke vocabulary report" in report
        assert "strokes examined" in report
        assert "type-token ratio" in report
        assert "hapax ratio" in report
        assert "severity" in report

    def test_empty_result(self):
        result = sv.analyze([])
        report = sv.format_report(result)
        assert "barren" in report
