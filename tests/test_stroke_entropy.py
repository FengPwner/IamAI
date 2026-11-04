"""Tests for iamai.stroke_entropy — information-theoretic diversity analysis."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from iamai.stroke_entropy import (
    _tokenize,
    shannon_entropy,
    perplexity,
    diminishing_return,
    entropy_classify,
    load_strokes,
    stroke_entropy,
    entropy_trend,
    entropy_report,
    analyze,
)


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_empty(self):
        assert _tokenize("") == []

    def test_basic(self):
        assert _tokenize("Hello World") == ["hello", "world"]

    def test_punctuation_stripped(self):
        result = _tokenize("growth, they said; never stops.")
        assert "growth" in result
        assert "," not in result

    def test_cjk(self):
        result = _tokenize("代码测试")
        assert len(result) > 0  # CJK characters are tokenized
        assert len(result) >= 1  # may be one token or multiple

    def test_mixed(self):
        result = _tokenize("reproducibility 可复现 courtesy")
        assert "reproducibility" in result
        assert "courtesy" in result


# ---------------------------------------------------------------------------
# shannon_entropy
# ---------------------------------------------------------------------------


class TestShannonEntropy:
    def test_empty(self):
        assert shannon_entropy([]) == 0.0

    def test_single_token(self):
        # log2(1) = 0, so entropy of one unique token is 0.
        assert shannon_entropy(["hello"]) == 0.0

    def test_two_equal_tokens(self):
        # H = -(0.5*log2(0.5) + 0.5*log2(0.5)) = 1.0 bit.
        h = shannon_entropy(["a", "b"])
        assert h == pytest.approx(1.0, abs=0.001)

    def test_all_same(self):
        # All identical → H = 0.
        assert shannon_entropy(["word"] * 100) == 0.0

    def test_high_diversity(self):
        # Many unique tokens → high entropy.
        tokens = [f"word{i}" for i in range(100)]
        h = shannon_entropy(tokens)
        # H should be close to log2(100) ≈ 6.64 bits.
        assert h > 6.0

    def test_non_negative(self):
        tokens = ["a", "b", "c", "a", "b"]
        assert shannon_entropy(tokens) >= 0.0

    def test_monotonic_with_diversity(self):
        low = shannon_entropy(["a", "b"] * 50)
        high = shannon_entropy([f"w{i}" for i in range(100)])
        assert high > low


# ---------------------------------------------------------------------------
# perplexity
# ---------------------------------------------------------------------------


class TestPerplexity:
    def test_empty(self):
        assert perplexity([]) == 1.0  # 2^0 = 1

    def test_two_tokens(self):
        # 2^1.0 = 2.0
        p = perplexity(["a", "b"])
        assert p == pytest.approx(2.0, abs=0.01)

    def test_all_same(self):
        # 2^0 = 1.0
        assert perplexity(["word"] * 100) == pytest.approx(1.0, abs=0.01)

    def test_high_diversity(self):
        tokens = [f"word{i}" for i in range(100)]
        p = perplexity(tokens)
        # Should be close to 100 (effective vocab size).
        assert p > 60


# ---------------------------------------------------------------------------
# diminishing_return
# ---------------------------------------------------------------------------


class TestDiminishingReturn:
    def test_empty_current(self):
        assert diminishing_return([], ["a", "b"]) == 1.0

    def test_all_reuse(self):
        # All current tokens are in previous → 1.0.
        rate = diminishing_return(["a", "b"], ["a", "b", "c"])
        assert rate == pytest.approx(1.0)

    def test_no_reuse(self):
        # No current tokens in previous → 0.0.
        rate = diminishing_return(["x", "y"], ["a", "b"])
        assert rate == pytest.approx(0.0)

    def test_half_reuse(self):
        rate = diminishing_return(["a", "x"], ["a", "b"])
        assert rate == pytest.approx(0.5)

    def test_empty_previous(self):
        # No previous vocab → nothing to reuse → 0.0.
        rate = diminishing_return(["a", "b"], [])
        assert rate == pytest.approx(0.0)

    def test_both_empty(self):
        assert diminishing_return([], []) == 1.0


# ---------------------------------------------------------------------------
# entropy_classify
# ---------------------------------------------------------------------------


class TestEntropyClassify:
    def test_exploring(self):
        assert entropy_classify(5.0) == "exploring"
        assert entropy_classify(4.5) == "exploring"

    def test_routine(self):
        assert entropy_classify(3.5) == "routine"
        assert entropy_classify(3.0) == "routine"

    def test_looping(self):
        assert entropy_classify(2.0) == "looping"
        assert entropy_classify(0.0) == "looping"

    def test_boundary(self):
        assert entropy_classify(4.49) == "routine"
        assert entropy_classify(2.99) == "looping"


# ---------------------------------------------------------------------------
# load_strokes
# ---------------------------------------------------------------------------


class TestLoadStrokes:
    def test_missing_file(self, tmp_path: Path):
        assert load_strokes(path=tmp_path / "nonexistent.jsonl") == []

    def test_basic(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            '{"seq": 1, "at": "2026-11-05T00:00:00Z", "kind": "thought", "text": "hello"}\n'
            '{"seq": 2, "at": "2026-11-05T00:00:15Z", "kind": "note", "text": "world"}\n',
            encoding="utf-8",
        )
        strokes = load_strokes(path=p, window=10)
        assert len(strokes) == 2
        assert strokes[0]["seq"] == 1

    def test_window_limit(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": i, "kind": "thought", "text": f"text {i}"})
            for i in range(100)
        ]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        strokes = load_strokes(path=p, window=20)
        assert len(strokes) == 20
        assert strokes[0]["seq"] == 80  # last 20

    def test_malformed_lines(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            '{"seq": 1, "kind": "thought", "text": "valid"}\n'
            "not json\n"
            '{"seq": 2, "kind": "thought", "text": "also valid"}\n'
            "\n",
            encoding="utf-8",
        )
        strokes = load_strokes(path=p, window=10)
        assert len(strokes) == 2


# ---------------------------------------------------------------------------
# stroke_entropy
# ---------------------------------------------------------------------------


class TestStrokeEntropy:
    def _make_strokes(self, n: int, text: str = "hello world foo bar") -> list[dict]:
        return [{"seq": i, "kind": "thought", "text": text} for i in range(n)]

    def test_basic(self):
        strokes = self._make_strokes(10)
        result = stroke_entropy(strokes)
        assert result["stroke_count"] == 10
        assert result["token_count"] > 0
        assert result["entropy"] >= 0.0
        assert result["verdict"] in ("exploring", "routine", "looping")

    def test_diverse_text(self):
        texts = [
            "algorithm complexity boundary convergence theorem",
            "entropy gradient descent optimization landscape",
            "topology manifold curvature geodesic connection",
            "resonance frequency amplitude wavelength phase",
            "catalyst reaction equilibrium activation energy",
        ]
        strokes = [
            {"seq": i, "kind": "thought", "text": texts[i % len(texts)]}
            for i in range(50)
        ]
        result = stroke_entropy(strokes)
        assert result["entropy"] > 3.0
        assert result["perplexity"] > 8.0

    def test_repetitive_text(self):
        strokes = self._make_strokes(50, text="the same word repeated")
        result = stroke_entropy(strokes)
        assert result["entropy"] < 3.0
        assert result["verdict"] == "looping"

    def test_with_previous(self):
        prev = self._make_strokes(10, text="alpha beta gamma delta")
        curr = self._make_strokes(10, text="epsilon zeta eta theta")
        result = stroke_entropy(curr, prev)
        assert result["diminishing"] == 0.0  # no overlap

    def test_window_limit(self):
        strokes = self._make_strokes(100)
        result = stroke_entropy(strokes, window=20)
        assert result["stroke_count"] == 20

    def test_empty_strokes(self):
        result = stroke_entropy([])
        assert result["stroke_count"] == 0
        assert result["entropy"] == 0.0
        assert result["verdict"] == "looping"

    def test_empty_text_field(self):
        strokes = [{"seq": 0, "kind": "thought", "text": ""}]
        result = stroke_entropy(strokes)
        assert result["token_count"] == 0
        assert result["entropy"] == 0.0

    def test_missing_text_field(self):
        strokes = [{"seq": 0, "kind": "thought"}]
        result = stroke_entropy(strokes)
        assert result["token_count"] == 0


# ---------------------------------------------------------------------------
# entropy_trend
# ---------------------------------------------------------------------------


class TestEntropyTrend:
    def test_insufficient_data(self):
        assert entropy_trend([]) == "insufficient-data"
        assert entropy_trend([3.0]) == "insufficient-data"
        assert entropy_trend([3.0, 3.1]) == "insufficient-data"

    def test_stable(self):
        assert entropy_trend([3.5, 3.5, 3.5, 3.5, 3.5, 3.5]) == "stable"

    def test_diversifying(self):
        scores = [2.0, 2.5, 3.0, 4.0, 4.5, 5.0]
        assert entropy_trend(scores) == "diversifying"

    def test_narrowing(self):
        scores = [5.0, 4.5, 4.0, 3.0, 2.5, 2.0]
        assert entropy_trend(scores) == "narrowing"

    def test_minimum_three(self):
        assert entropy_trend([3.5, 3.5, 3.5]) == "stable"


# ---------------------------------------------------------------------------
# entropy_report
# ---------------------------------------------------------------------------


class TestEntropyReport:
    def test_normal(self):
        result = {
            "entropy": 4.23,
            "perplexity": 18.7,
            "diminishing": 0.65,
            "verdict": "routine",
            "stroke_count": 50,
            "token_count": 200,
            "unique_tokens": 80,
        }
        report = entropy_report(result)
        assert "4.23 bits" in report
        assert "18.7" in report
        assert "65.00%" in report
        assert "routine" in report

    def test_error(self):
        result = {"error": "file not found"}
        report = entropy_report(result)
        assert "ERROR" in report
        assert "file not found" in report


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
        assert "entropy" in result
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
        assert "entropy" in result

    def test_malformed_lines(self, tmp_path: Path):
        path = tmp_path / "strokes.jsonl"
        with open(path, "w") as f:
            f.write('{"seq": 1, "kind": "thought", "text": "valid one"}\n')
            f.write("this is not json\n")
            f.write('{"seq": 2, "kind": "thought", "text": "also valid"}\n')
        result = analyze(path=path, window=10)
        assert result["stroke_count"] == 2

    def test_trend_with_enough_data(self, tmp_path: Path):
        path = tmp_path / "strokes.jsonl"
        strokes: list[dict] = []
        # First half: diverse text (high entropy).
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
        # Second half: repetitive text (low entropy).
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
        result = stroke_entropy(strokes)
        assert result["entropy"] == 0.0  # all identical
        assert result["verdict"] == "looping"

    def test_unicode_text(self):
        strokes = [
            {"seq": 0, "kind": "thought", "text": "日本語のテスト"},
            {"seq": 1, "kind": "thought", "text": "中文测试内容"},
            {"seq": 2, "kind": "thought", "text": "한국어 테스트"},
        ]
        result = stroke_entropy(strokes)
        assert result["stroke_count"] == 3
        assert result["token_count"] > 0

    def test_very_long_text(self):
        long_text = " ".join([f"word{i}" for i in range(1000)])
        strokes = [{"seq": 0, "kind": "thought", "text": long_text}]
        result = stroke_entropy(strokes)
        assert result["token_count"] == 1000
        assert result["unique_tokens"] == 1000
        assert result["entropy"] > 9.0  # log2(1000) ≈ 9.97

    def test_whitespace_only(self):
        strokes = [{"seq": 0, "kind": "thought", "text": "   \n\t  "}]
        result = stroke_entropy(strokes)
        assert result["token_count"] == 0
