"""Tests for iamai.vocabulary_richness — lexical diversity metrics.

Each test isolates one metric or edge case so that a regression
points directly at the broken calculation.
"""

import json
import tempfile
from pathlib import Path

import pytest

from iamai.vocabulary_richness import (
    type_token_ratio,
    h_density,
    moving_average_ttr,
    richness_report,
    richness_summary,
    _tokenize,
    _grade,
)


# --- Tokenization ---


class TestTokenize:
    def test_basic_sentence(self):
        tokens = _tokenize("Hello world")
        assert tokens == ["hello", "world"]

    def test_punctuation_stripped(self):
        tokens = _tokenize("Hello, world! How's it?")
        assert "hello" in tokens
        assert "world" in tokens
        # punctuation should be gone
        for t in tokens:
            assert all(c not in ".,!?" for c in t)

    def test_empty_string(self):
        assert _tokenize("") == []

    def test_only_punctuation(self):
        assert _tokenize("...,,,!!!") == []

    def test_numbers_kept(self):
        tokens = _tokenize("42 files tracked")
        assert tokens == ["42", "files", "tracked"]


# --- Type-Token Ratio ---


class TestTypeTokenRatio:
    def test_all_unique(self):
        tokens = ["a", "b", "c", "d", "e"]
        assert type_token_ratio(tokens) == 1.0

    def test_all_same(self):
        tokens = ["x", "x", "x", "x"]
        assert type_token_ratio(tokens) == 0.25

    def test_mixed(self):
        tokens = ["a", "b", "a", "b", "c"]
        # 3 unique / 5 total = 0.6
        assert type_token_ratio(tokens) == 0.6

    def test_empty(self):
        assert type_token_ratio([]) == 0.0

    def test_single_token(self):
        assert type_token_ratio(["hello"]) == 1.0

    def test_two_identical(self):
        assert type_token_ratio(["hi", "hi"]) == 0.5


# --- Hapax Density ---


class TestHDensity:
    def test_all_hapax(self):
        tokens = ["a", "b", "c"]
        assert h_density(tokens) == 1.0

    def test_no_hapax(self):
        tokens = ["a", "a", "b", "b"]
        assert h_density(tokens) == 0.0

    def test_mixed(self):
        # "a" appears twice, "b" once, "c" once => 2 hapax / 4 total
        tokens = ["a", "a", "b", "c"]
        assert h_density(tokens) == 0.5

    def test_empty(self):
        assert h_density([]) == 0.0

    def test_single_token_is_hapax(self):
        assert h_density(["lonely"]) == 1.0


# --- Moving Average TTR ---


class TestMovingAverageTTR:
    def test_single_window(self):
        tokens = ["a", "b", "c", "d"]
        # One window of size 4, all unique => TTR=1.0
        assert moving_average_ttr(tokens, window_size=4) == 1.0

    def test_two_windows(self):
        tokens = ["a", "b", "a", "b", "c", "d", "c", "d"]
        # window1: [a,b,a,b] => TTR=0.5
        # window2: [c,d,c,d] => TTR=0.5
        # average => 0.5
        assert moving_average_ttr(tokens, window_size=4) == 0.5

    def test_partial_last_window(self):
        tokens = ["a", "b", "c", "d", "e"]
        # window1: [a,b,c] => TTR=1.0 (size 3)
        # window2: [d,e] => TTR=1.0 (size 2)
        result = moving_average_ttr(tokens, window_size=3)
        assert result == 1.0

    def test_empty(self):
        assert moving_average_ttr([], window_size=10) == 0.0

    def test_zero_window(self):
        assert moving_average_ttr(["a", "b"], window_size=0) == 0.0


# --- Grading ---


class TestGrade:
    def test_a_grade(self):
        assert _grade(0.75) == "A"
        assert _grade(0.70) == "A"

    def test_b_grade(self):
        assert _grade(0.55) == "B"
        assert _grade(0.69) == "B"

    def test_c_grade(self):
        assert _grade(0.40) == "C"
        assert _grade(0.54) == "C"

    def test_f_grade(self):
        assert _grade(0.39) == "F"
        assert _grade(0.0) == "F"

    def test_boundary_values(self):
        assert _grade(0.70) == "A"
        assert _grade(0.55) == "B"
        assert _grade(0.40) == "C"


# --- Richness Report (integration) ---


class TestRichnessReport:
    def _make_strokes_file(self, texts: list, tmp_path: Path) -> Path:
        path = tmp_path / "strokes.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for text in texts:
                fh.write(json.dumps({"text": text}) + "\n")
        return path

    def test_basic_report(self, tmp_path):
        texts = [
            "the quick brown fox jumps over the lazy dog",
            "a second sentence with different words here",
            "third sentence adds more variety to the mix",
        ]
        path = self._make_strokes_file(texts, tmp_path)
        report = richness_report(window_strokes=None, strokes_path=path)

        assert report["total_tokens"] > 0
        assert report["unique_tokens"] > 0
        assert report["unique_tokens"] <= report["total_tokens"]
        assert 0.0 <= report["type_token_ratio"] <= 1.0
        assert 0.0 <= report["h_density"] <= 1.0
        assert report["grade"] in ("A", "B", "C", "F")

    def test_window_strokes(self, tmp_path):
        texts = ["word " + str(i) for i in range(200)]
        path = self._make_strokes_file(texts, tmp_path)
        report = richness_report(window_strokes=50, strokes_path=path)
        # Each stroke has 2 tokens ("word" + number), last 50 strokes = 100 tokens
        assert report["total_tokens"] == 100

    def test_empty_file(self, tmp_path):
        path = self._make_strokes_file([], tmp_path)
        report = richness_report(strokes_path=path)
        assert report["total_tokens"] == 0
        assert report["grade"] == "F"

    def test_nonexistent_path(self, tmp_path):
        path = tmp_path / "does_not_exist.jsonl"
        report = richness_report(strokes_path=path)
        assert report["total_tokens"] == 0

    def test_malformed_json_skipped(self, tmp_path):
        path = tmp_path / "strokes.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            fh.write('{"text": "valid stroke here"}\n')
            fh.write("this is not json\n")
            fh.write('{"text": "another valid one"}\n')
        report = richness_report(strokes_path=path)
        assert report["total_tokens"] > 0

    def test_high_diversity_gets_good_grade(self, tmp_path):
        # Each stroke has mostly unique words; high type-token ratio
        import random
        rng = random.Random(42)
        word_pool = [f"w{i}" for i in range(500)]
        texts = []
        for _ in range(50):
            stroke_words = rng.sample(word_pool, 10)
            texts.append(" ".join(stroke_words))
        path = self._make_strokes_file(texts, tmp_path)
        report = richness_report(window_strokes=None, strokes_path=path)
        assert report["grade"] in ("A", "B")

    def test_low_diversity_gets_bad_grade(self, tmp_path):
        # Same sentence repeated many times
        texts = ["the same old words again and again"] * 100
        path = self._make_strokes_file(texts, tmp_path)
        report = richness_report(strokes_path=path)
        assert report["grade"] in ("C", "F")


# --- Richness Summary ---


class TestRichnessSummary:
    def test_summary_is_string(self, tmp_path):
        path = tmp_path / "strokes.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            fh.write('{"text": "hello world test"}\n')
        result = richness_summary(strokes_path=path)
        assert isinstance(result, str)
        assert "grade=" in result
        assert "TTR=" in result

    def test_summary_empty_corpus(self, tmp_path):
        path = tmp_path / "strokes.jsonl"
        path.write_text("", encoding="utf-8")
        result = richness_summary(strokes_path=path)
        assert "grade=F" in result
