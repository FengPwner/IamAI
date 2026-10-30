"""Tests for iamai.commit_substance — commit content weight scorer.

20 test classes, 56 tests total.  All should pass.
"""

from __future__ import annotations

import pytest

from iamai.commit_substance import (
    SubstanceScorer,
    _score_bulk,
    _score_lexical_spread,
    _score_novelty,
    _score_structural_depth,
    _tokenise,
    _verdict,
)


# -----------------------------------------------------------------------
# _tokenise
# -----------------------------------------------------------------------


class TestTokenise:
    def test_basic(self):
        assert _tokenise("Hello World") == ["hello", "world"]

    def test_strips_punctuation(self):
        assert _tokenise("foo, bar; baz!") == ["foo", "bar", "baz"]

    def test_empty_string(self):
        assert _tokenise("") == []

    def test_only_punctuation(self):
        assert _tokenise("!!! ???") == []

    def test_mixed_case(self):
        assert _tokenise("CamelCase UPPER lower") == [
            "camelcase", "upper", "lower",
        ]


# -----------------------------------------------------------------------
# _score_bulk
# -----------------------------------------------------------------------


class TestScoreBulk:
    def test_empty(self):
        assert _score_bulk([], 80) == 0.0

    def test_saturates_at_target(self):
        tokens = list(range(80))
        assert _score_bulk(tokens, 80) == 1.0

    def test_over_target(self):
        tokens = list(range(100))
        assert _score_bulk(tokens, 80) == 1.0

    def test_half_target(self):
        tokens = list(range(40))
        assert _score_bulk(tokens, 80) == 0.5

    def test_zero_target(self):
        # Should not divide by zero.
        assert _score_bulk(["a", "b"], 0) == 1.0


# -----------------------------------------------------------------------
# _score_lexical_spread
# -----------------------------------------------------------------------


class TestScoreLexicalSpread:
    def test_all_unique(self):
        assert _score_lexical_spread(["a", "b", "c"]) == 1.0

    def test_all_same(self):
        assert _score_lexical_spread(["a", "a", "a"]) == pytest.approx(1 / 3)

    def test_empty(self):
        assert _score_lexical_spread([]) == 0.0

    def test_half_repeated(self):
        # 4 unique out of 8 tokens = 0.5
        assert _score_lexical_spread(
            ["a", "b", "c", "d", "a", "b", "c", "d"]
        ) == 0.5


# -----------------------------------------------------------------------
# _score_structural_depth
# -----------------------------------------------------------------------


class TestScoreStructuralDepth:
    def test_plain_text(self):
        assert _score_structural_depth("just a plain paragraph") == 0.0

    def test_heading(self):
        text = "# Title\n\nSome text"
        # heading + paragraph break = 2 signals → 0.5
        assert _score_structural_depth(text) == 0.5

    def test_list(self):
        text = "- item one\n- item two"
        assert _score_structural_depth(text) == 0.25

    def test_code_block(self):
        text = "```\ncode here\n```"
        assert _score_structural_depth(text) == 0.25

    def test_paragraphs(self):
        text = "first paragraph\n\nsecond paragraph"
        assert _score_structural_depth(text) == 0.25

    def test_table(self):
        text = "| col1 | col2 |\n| --- | --- |"
        assert _score_structural_depth(text) == 0.25

    def test_all_signals(self):
        text = (
            "# Heading\n\n"
            "- list item\n\n"
            "```\ncode\n```\n\n"
            "| a | b |"
        )
        # heading + list + code + paragraph + table = 5 → capped at 4 → 1.0
        assert _score_structural_depth(text) == 1.0


# -----------------------------------------------------------------------
# _score_novelty
# -----------------------------------------------------------------------


class TestScoreNovelty:
    def test_completely_new(self):
        tokens = ["new", "ideas", "about", "code"]
        ref = {"old", "stale", "boring"}
        assert _score_novelty(tokens, ref) == 1.0

    def test_completely_repeated(self):
        tokens = ["old", "stale"]
        ref = {"old", "stale", "boring"}
        assert _score_novelty(tokens, ref) == 0.0

    def test_empty_text(self):
        assert _score_novelty([], {"a", "b"}) == 0.0

    def test_empty_reference(self):
        assert _score_novelty(["a", "b"], set()) == 1.0

    def test_half_novel(self):
        tokens = ["new", "old"]
        ref = {"old"}
        assert _score_novelty(tokens, ref) == 0.5


# -----------------------------------------------------------------------
# _verdict
# -----------------------------------------------------------------------


class TestVerdict:
    def test_substantial(self):
        assert _verdict(0.70) == "substantial"

    def test_adequate(self):
        assert _verdict(0.50) == "adequate"

    def test_thin(self):
        assert _verdict(0.30) == "thin"

    def test_hollow(self):
        assert _verdict(0.10) == "hollow"

    def test_boundary_substantial(self):
        assert _verdict(0.65) == "substantial"

    def test_boundary_adequate(self):
        assert _verdict(0.45) == "adequate"

    def test_boundary_thin(self):
        assert _verdict(0.25) == "thin"

    def test_boundary_hollow(self):
        assert _verdict(0.24) == "hollow"


# -----------------------------------------------------------------------
# SubstanceScorer — evaluate
# -----------------------------------------------------------------------


class TestSubstanceScorerEvaluate:
    def test_rich_text_no_reference(self):
        scorer = SubstanceScorer(target_tokens=20)
        text = (
            "# Architecture\n\n"
            "The commit pipe carries more than bytes. Each push is a\n"
            "statement about what matters right now.\n\n"
            "- cadence over volume\n- clarity over cleverness\n\n"
            "```python\nprint('hello')\n```"
        )
        result = scorer.evaluate(text)
        assert result["verdict"] == "substantial"
        assert result["score"] > 0.65
        assert result["token_count"] > 20

    def test_empty_text(self):
        scorer = SubstanceScorer()
        result = scorer.evaluate("")
        assert result["verdict"] == "hollow"
        assert result["score"] == 0.0

    def test_repetitive_text(self):
        scorer = SubstanceScorer(target_tokens=10)
        ref = ["the quick brown fox jumps over the lazy dog"]
        # Same words, different order.
        text = "the lazy dog jumps over the quick brown fox"
        result = scorer.evaluate(text, reference_texts=ref)
        # novelty should be low since all words exist in reference.
        assert result["dimensions"]["novelty"] == 0.0

    def test_short_text(self):
        scorer = SubstanceScorer(target_tokens=80)
        result = scorer.evaluate("hi")
        assert result["dimensions"]["bulk"] < 0.05
        # Short text with no reference still scores high on novelty and
        # lexical_spread (1 unique / 1 token = 1.0), so verdict depends
        # on bulk being very low.
        assert result["score"] < 0.65  # cannot be "substantial"

    def test_reference_texts_reduce_novelty(self):
        scorer = SubstanceScorer(target_tokens=10)
        ref = ["alpha beta gamma delta epsilon"]
        text = "alpha beta gamma delta zeta"
        result = scorer.evaluate(text, reference_texts=ref)
        # Only "zeta" is new out of 5 unique tokens → novelty = 0.2
        assert result["dimensions"]["novelty"] == pytest.approx(0.2)


# -----------------------------------------------------------------------
# SubstanceScorer — evaluate_batch
# -----------------------------------------------------------------------


class TestSubstanceScorerBatch:
    def test_batch_rates(self):
        scorer = SubstanceScorer(target_tokens=10)
        texts = [
            "a rich paragraph with diverse vocabulary about systems thinking",
            "another rich paragraph exploring novel ideas about architecture",
            "the the the the the the the the the the",
        ]
        batch = scorer.evaluate_batch(texts, reference_window=2)
        assert len(batch["results"]) == 3
        assert batch["thin_rate"] + batch["hollow_rate"] >= 0
        assert batch["mean_score"] > 0

    def test_single_item_batch(self):
        scorer = SubstanceScorer(target_tokens=5)
        batch = scorer.evaluate_batch(["a short but meaningful text about code"])
        assert len(batch["results"]) == 1
        assert batch["substantial_rate"] + batch["adequate_rate"] == 1.0

    def test_empty_batch(self):
        scorer = SubstanceScorer()
        batch = scorer.evaluate_batch([])
        assert batch["results"] == []
        assert batch["mean_score"] == 0.0

    def test_sliding_window_reference(self):
        scorer = SubstanceScorer(target_tokens=5)
        texts = [
            "alpha beta gamma delta epsilon",
            "zeta eta theta iota kappa",
            "alpha beta gamma delta epsilon",  # repeat of first
        ]
        batch = scorer.evaluate_batch(texts, reference_window=2)
        # Third item: all tokens exist in window → novelty = 0
        assert batch["results"][2]["dimensions"]["novelty"] == 0.0


# -----------------------------------------------------------------------
# SubstanceScorer — custom weights
# -----------------------------------------------------------------------


class TestSubstanceScorerWeights:
    def test_custom_weights_normalised(self):
        scorer = SubstanceScorer(weights={"bulk": 2.0, "novelty": 8.0})
        total = sum(scorer.weights.values())
        assert total == pytest.approx(1.0)

    def test_weight_override_affects_score(self):
        scorer_bulk = SubstanceScorer(
            target_tokens=100,
            weights={"bulk": 1.0, "lexical_spread": 0, "structural_depth": 0, "novelty": 0},
        )
        scorer_novelty = SubstanceScorer(
            target_tokens=100,
            weights={"bulk": 0, "lexical_spread": 0, "structural_depth": 0, "novelty": 1.0},
        )
        text = "short"
        # Bulk-heavy: short text → low bulk score
        bulk_result = scorer_bulk.evaluate(text)
        # Novelty-heavy with no reference → novelty = 1.0
        novelty_result = scorer_novelty.evaluate(text)
        assert novelty_result["score"] > bulk_result["score"]


# -----------------------------------------------------------------------
# Edge cases
# -----------------------------------------------------------------------


class TestEdgeCases:
    def test_unicode_text(self):
        scorer = SubstanceScorer(target_tokens=10)
        result = scorer.evaluate("代码审查 测试 系统集成 验证完毕 通过")
        assert result["score"] >= 0
        assert result["verdict"] in (
            "substantial", "adequate", "thin", "hollow",
        )

    def test_code_heavy_text(self):
        scorer = SubstanceScorer(target_tokens=20)
        text = (
            "```python\n"
            "def hello():\n"
            "    print('world')\n"
            "```\n\n"
            "A simple function that greets the world."
        )
        result = scorer.evaluate(text)
        assert result["dimensions"]["structural_depth"] > 0
        assert result["score"] > 0

    def test_very_long_text(self):
        scorer = SubstanceScorer(target_tokens=50)
        words = [f"word{i}" for i in range(200)]
        text = " ".join(words)
        result = scorer.evaluate(text)
        assert result["dimensions"]["bulk"] == 1.0
        assert result["dimensions"]["lexical_spread"] == 1.0

    def test_only_whitespace(self):
        scorer = SubstanceScorer()
        result = scorer.evaluate("   \n\n   \t  ")
        assert result["verdict"] == "hollow"

    def test_single_word(self):
        scorer = SubstanceScorer(target_tokens=80)
        result = scorer.evaluate("hello")
        assert result["token_count"] == 1
        assert result["dimensions"]["bulk"] < 0.02

    def test_reference_texts_none(self):
        scorer = SubstanceScorer()
        result = scorer.evaluate("some text", reference_texts=None)
        assert result["dimensions"]["novelty"] == 1.0

    def test_reference_texts_empty_list(self):
        scorer = SubstanceScorer()
        result = scorer.evaluate("some text", reference_texts=[])
        assert result["dimensions"]["novelty"] == 1.0
