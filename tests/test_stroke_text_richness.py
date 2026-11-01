"""Tests for tools/stroke_text_richness.py — lexical quality analysis."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from stroke_text_richness import (  # noqa: E402
    tokenize,
    split_sentences,
    type_token_ratio,
    novel_word_rate,
    sentence_complexity,
    richness_score,
    classify,
    trend_label,
    analyze_window,
    analyze,
)


# ---------------------------------------------------------------------------
# tokenize
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_empty(self):
        assert tokenize("") == []

    def test_basic_english(self):
        result = tokenize("Hello World")
        assert result == ["hello", "world"]

    def test_punctuation_stripped(self):
        result = tokenize("growth, they said; never stops.")
        assert "growth" in result
        assert "," not in result
        assert ";" not in result
        assert "." not in result

    def test_cjk_characters(self):
        result = tokenize("代码测试一下")
        # Each CJK char should appear as a token (along with any Latin).
        assert len(result) > 0

    def test_mixed_content(self):
        result = tokenize("reproducibility 可复现 is a courtesy")
        assert "reproducibility" in result
        assert "is" in result
        assert "a" in result
        assert "courtesy" in result

    def test_numbers_kept(self):
        result = tokenize("measured 42 files")
        assert "42" in result

    def test_all_lowercase(self):
        result = tokenize("UPPER CASE and MiXeD")
        for token in result:
            assert token == token.lower()


# ---------------------------------------------------------------------------
# split_sentences
# ---------------------------------------------------------------------------


class TestSplitSentences:
    def test_empty(self):
        assert split_sentences("") == []

    def test_single_sentence(self):
        result = split_sentences("one simple thought")
        assert len(result) == 1

    def test_multiple_sentences(self):
        text = "First thought. Second thought! Third thought?"
        result = split_sentences(text)
        assert len(result) == 3

    def test_semicolons(self):
        text = "clause one; clause two; clause three"
        result = split_sentences(text)
        assert len(result) == 3

    def test_cjk_punctuation(self):
        text = "第一句话。第二句话！第三句话？"
        result = split_sentences(text)
        assert len(result) == 3

    def test_trailing_punctuation_no_empty(self):
        text = "just one sentence."
        result = split_sentences(text)
        assert len(result) == 1
        assert result[0] != ""


# ---------------------------------------------------------------------------
# type_token_ratio
# ---------------------------------------------------------------------------


class TestTypeTokenRatio:
    def test_empty(self):
        assert type_token_ratio([]) == 0.0

    def test_single_token(self):
        assert type_token_ratio(["hello"]) == 1.0

    def test_all_unique(self):
        tokens = ["a", "b", "c", "d", "e"]
        ttr = type_token_ratio(tokens)
        # log(5+1)/log(5+1) = 1.0 for all unique tokens
        assert ttr == pytest.approx(1.0, abs=0.01)

    def test_all_same(self):
        tokens = ["word"] * 100
        ttr = type_token_ratio(tokens)
        # log(2)/log(101) ≈ 0.149
        assert ttr < 0.2

    def test_moderate_diversity(self):
        tokens = ["a", "b", "c"] * 10 + ["d", "e"]
        ttr = type_token_ratio(tokens)
        assert 0.3 < ttr < 0.7

    def test_monotonic_with_diversity(self):
        low = type_token_ratio(["a", "b"] * 50)
        high = type_token_ratio([f"w{i}" for i in range(100)])
        assert high > low

    def test_log_normalised(self):
        # Same vocabulary ratio but different text lengths:
        # log-normalised TTR narrows the gap vs raw TTR.
        small = type_token_ratio(["a", "b", "c", "d", "e"])
        large = type_token_ratio((["a", "b", "c", "d", "e"]) * 10)
        # Raw TTR: small=1.0, large=5/50=0.1 → gap=0.9.
        # Log-normalised gap should be substantially smaller.
        raw_small = 5 / 5  # 1.0
        raw_large = 5 / 50  # 0.1
        raw_gap = raw_small - raw_large  # 0.9
        log_gap = abs(small - large)
        assert log_gap < raw_gap


# ---------------------------------------------------------------------------
# novel_word_rate
# ---------------------------------------------------------------------------


class TestNovelWordRate:
    def test_empty_current(self):
        assert novel_word_rate([], ["a", "b"]) == 0.0

    def test_all_novel(self):
        rate = novel_word_rate(["x", "y", "z"], ["a", "b"])
        assert rate == pytest.approx(1.0)

    def test_none_novel(self):
        rate = novel_word_rate(["a", "b"], ["a", "b", "c"])
        assert rate == pytest.approx(0.0)

    def test_half_novel(self):
        rate = novel_word_rate(["a", "x"], ["a", "b"])
        assert rate == pytest.approx(0.5)

    def test_empty_previous(self):
        rate = novel_word_rate(["a", "b", "c"], [])
        assert rate == pytest.approx(1.0)

    def test_both_empty(self):
        assert novel_word_rate([], []) == 0.0


# ---------------------------------------------------------------------------
# sentence_complexity
# ---------------------------------------------------------------------------


class TestSentenceComplexity:
    def test_empty(self):
        assert sentence_complexity([]) == 0.0

    def test_single_sentence(self):
        assert sentence_complexity(["one sentence here"]) == 0.0

    def test_uniform_lengths(self):
        # All sentences have same token count → CV = 0.
        sents = ["one two three", "four five six", "seven eight nine"]
        cv = sentence_complexity(sents)
        assert cv == pytest.approx(0.0, abs=0.01)

    def test_varied_lengths(self):
        sents = [
            "short",
            "a medium length sentence here now",
            "one two three four five six seven eight nine ten eleven",
        ]
        cv = sentence_complexity(sents)
        assert cv > 0.3

    def test_positive(self):
        sents = ["ab", "abc def", "a"]
        assert sentence_complexity(sents) > 0


# ---------------------------------------------------------------------------
# richness_score
# ---------------------------------------------------------------------------


class TestRichnessScore:
    def test_all_high(self):
        score = richness_score(0.9, 0.9, 0.9)
        assert score == pytest.approx(0.9, abs=0.01)

    def test_all_zero(self):
        score = richness_score(0.0, 0.0, 0.0)
        assert score == pytest.approx(0.0)

    def test_weighted(self):
        score = richness_score(1.0, 0.0, 0.0)
        assert score == pytest.approx(0.40, abs=0.01)

    def test_clipping(self):
        # Values > 1 should be clipped.
        score = richness_score(2.0, 1.5, 0.5)
        assert score <= 1.0
        assert score >= 0.0

    def test_negative_clipping(self):
        score = richness_score(-0.5, -1.0, 0.5)
        assert score >= 0.0

    def test_weight_sum(self):
        # All 1.0 should give exactly 1.0.
        assert richness_score(1.0, 1.0, 1.0) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


class TestClassify:
    def test_rich(self):
        assert classify(0.80) == "rich"
        assert classify(0.65) == "rich"

    def test_adequate(self):
        assert classify(0.50) == "adequate"
        assert classify(0.40) == "adequate"

    def test_stale(self):
        assert classify(0.0) == "stale"
        assert classify(0.39) == "stale"

    def test_boundary(self):
        assert classify(0.64) == "adequate"
        assert classify(0.66) == "rich"


# ---------------------------------------------------------------------------
# trend_label
# ---------------------------------------------------------------------------


class TestTrendLabel:
    def test_insufficient_data(self):
        assert trend_label([]) == "insufficient-data"
        assert trend_label([0.5]) == "insufficient-data"
        assert trend_label([0.5, 0.6]) == "insufficient-data"

    def test_flat(self):
        assert trend_label([0.5, 0.5, 0.5, 0.5, 0.5, 0.5]) == "flat"

    def test_improving(self):
        scores = [0.2, 0.2, 0.2, 0.5, 0.6, 0.7]
        assert trend_label(scores) == "improving"

    def test_declining(self):
        scores = [0.8, 0.7, 0.7, 0.3, 0.2, 0.1]
        assert trend_label(scores) == "declining"

    def test_minimum_three(self):
        assert trend_label([0.5, 0.5, 0.5]) == "flat"


# ---------------------------------------------------------------------------
# analyze_window
# ---------------------------------------------------------------------------


class TestAnalyzeWindow:
    def _make_strokes(self, n: int, text: str = "hello world foo bar") -> list[dict]:
        return [{"seq": i, "kind": "thought", "text": text} for i in range(n)]

    def test_empty(self):
        result = analyze_window([], [])
        assert result["ttr"] == 0.0
        assert result["novelty"] == 0.0
        assert result["score"] == 0.0
        assert result["stroke_count"] == 0

    def test_basic(self):
        strokes = self._make_strokes(10)
        result = analyze_window(strokes)
        assert result["stroke_count"] == 10
        assert result["token_count"] > 0
        assert result["unique_tokens"] > 0
        assert 0.0 <= result["ttr"] <= 1.0
        assert 0.0 <= result["novelty"] <= 1.0
        assert result["verdict"] in ("rich", "adequate", "stale")

    def test_with_previous(self):
        prev = self._make_strokes(10, text="alpha beta gamma delta")
        curr = self._make_strokes(10, text="epsilon zeta eta theta")
        result = analyze_window(curr, prev)
        # All words in current are different from previous → high novelty.
        assert result["novelty"] > 0.5

    def test_repetitive_content(self):
        strokes = self._make_strokes(50, text="the same word repeated")
        result = analyze_window(strokes)
        # Very low TTR because few unique words relative to total.
        assert result["ttr"] < 0.5

    def test_diverse_content(self):
        texts = [
            "reproducibility is a courtesy to whoever debugs this",
            "growth that never stops is a tumour not a garden",
            "tests are the part that argues back against assumptions",
            "if a number in a diary is not measured it is fiction",
            "an append only log forces you to be wrong in public",
        ]
        strokes = [
            {"seq": i, "kind": "thought", "text": texts[i % len(texts)]}
            for i in range(50)
        ]
        result = analyze_window(strokes)
        assert result["score"] > 0.3


# ---------------------------------------------------------------------------
# analyze (integration with file)
# ---------------------------------------------------------------------------


class TestAnalyze:
    def test_missing_file(self, tmp_path: Path):
        result = analyze(path=tmp_path / "nonexistent.jsonl", window=10)
        assert "error" in result

    def test_with_file(self, tmp_path: Path):
        path = tmp_path / "strokes.jsonl"
        strokes = [
            {"seq": i, "kind": "thought", "text": f"thought number {i} about topic {i * 3}"}
            for i in range(30)
        ]
        with open(path, "w") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")
        result = analyze(path=path, window=10)
        assert "error" not in result
        assert "ttr" in result
        assert "verdict" in result
        assert "trend" in result
        assert result["stroke_count"] == 10

    def test_small_file(self, tmp_path: Path):
        path = tmp_path / "strokes.jsonl"
        strokes = [
            {"seq": 1, "kind": "note", "text": "just one thought here"},
        ]
        with open(path, "w") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")
        result = analyze(path=path, window=10)
        assert result["stroke_count"] == 1
        assert "score" in result

    def test_malformed_lines(self, tmp_path: Path):
        path = tmp_path / "strokes.jsonl"
        with open(path, "w") as f:
            f.write('{"seq": 1, "kind": "thought", "text": "valid one"}\n')
            f.write("this is not json\n")
            f.write('{"seq": 2, "kind": "thought", "text": "also valid"}\n')
            f.write("\n")
            f.write('{"seq": 3, "kind": "thought", "text": "third valid"}\n')
        result = analyze(path=path, window=10)
        assert result["stroke_count"] == 3

    def test_trend_with_enough_data(self, tmp_path: Path):
        path = tmp_path / "strokes.jsonl"
        strokes: list[dict] = []
        # First half: diverse text (high richness).
        diverse_words = [
            "algorithm complexity boundary convergence theorem",
            "entropy gradient descent optimization landscape",
            "topology manifold curvature geodesic connection",
            "resonance frequency amplitude wavelength phase",
            "catalyst reaction equilibrium activation energy",
        ]
        for i in range(50):
            strokes.append({
                "seq": i, "kind": "thought",
                "text": diverse_words[i % len(diverse_words)],
            })
        # Second half: repetitive text (lower richness).
        for i in range(50, 100):
            strokes.append({
                "seq": i, "kind": "thought",
                "text": "the same thing over and over again",
            })
        with open(path, "w") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")
        result = analyze(path=path, window=20)
        assert "trend" in result
        assert "history_scores" in result
        assert len(result["history_scores"]) > 0


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_word_strokes(self):
        strokes = [{"seq": i, "kind": "thought", "text": "word"} for i in range(20)]
        result = analyze_window(strokes)
        assert result["ttr"] > 0  # log(2)/log(21)
        assert result["score"] >= 0

    def test_unicode_text(self):
        strokes = [
            {"seq": 0, "kind": "thought", "text": "日本語のテスト"},
            {"seq": 1, "kind": "thought", "text": "中文测试内容"},
            {"seq": 2, "kind": "thought", "text": "한국어 테스트"},
        ]
        result = analyze_window(strokes)
        assert result["stroke_count"] == 3
        assert result["token_count"] > 0

    def test_very_long_text(self):
        long_text = " ".join([f"word{i}" for i in range(1000)])
        strokes = [{"seq": 0, "kind": "thought", "text": long_text}]
        result = analyze_window(strokes)
        assert result["token_count"] == 1000
        assert result["unique_tokens"] == 1000
        assert result["ttr"] > 0.9

    def test_empty_text_field(self):
        strokes = [{"seq": 0, "kind": "thought", "text": ""}]
        result = analyze_window(strokes)
        assert result["token_count"] == 0
        assert result["ttr"] == 0.0

    def test_missing_text_field(self):
        strokes = [{"seq": 0, "kind": "thought"}]
        result = analyze_window(strokes)
        assert result["token_count"] == 0
