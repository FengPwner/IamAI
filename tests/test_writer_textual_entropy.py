#!/usr/bin/env python3
"""Tests for iamai.writer_textual_entropy — information-theoretic lexical profiling."""

import json
import math
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_textual_entropy import (
    _classify_entropy,
    _empty_result,
    _entropy_gradient,
    _mattr,
    _shannon_entropy,
    _tokenize,
    compute_textual_entropy,
    main,
    textual_entropy_report,
    textual_entropy_summary,
)


# =========================================================================
# _tokenize
# =========================================================================

class TestTokenize:
    def test_basic(self):
        tokens = _tokenize("Hello world hello")
        assert tokens == ["hello", "world", "hello"]

    def test_empty(self):
        assert _tokenize("") == []

    def test_whitespace(self):
        assert _tokenize("   \n\t  ") == []

    def test_punctuation(self):
        tokens = _tokenize("Hello, world! How's it?")
        assert "hello" in tokens
        assert "world" in tokens

    def test_case_fold(self):
        tokens = _tokenize("HELLO Hello hello")
        assert all(t == "hello" for t in tokens)

    def test_numbers_stripped(self):
        tokens = _tokenize("abc 123 def")
        assert "123" not in tokens
        assert "abc" in tokens
        assert "def" in tokens

    def test_unicode(self):
        tokens = _tokenize("café résumé naïve")
        assert len(tokens) == 3

    def test_single_letter(self):
        tokens = _tokenize("I am a test")
        # Single letters that are alpha should be included
        assert "am" in tokens

    def test_contraction(self):
        tokens = _tokenize("don't can't won't")
        # Contractions are kept as units (apostrophe included in token)
        assert "don't" in tokens
        assert "can't" in tokens

    def test_cjk(self):
        tokens = _tokenize("你好世界")
        assert len(tokens) >= 1


# =========================================================================
# _shannon_entropy
# =========================================================================

class TestShannonEntropy:
    def test_empty(self):
        from collections import Counter
        assert _shannon_entropy(Counter()) == 0.0

    def test_single_type(self):
        from collections import Counter
        freq = Counter(["hello"] * 10)
        assert _shannon_entropy(freq) == 0.0

    def test_uniform_2(self):
        from collections import Counter
        freq = Counter(["a", "b"] * 10)
        # Uniform distribution over 2 types: H = 1.0 bit
        assert abs(_shannon_entropy(freq) - 1.0) < 0.01

    def test_uniform_4(self):
        from collections import Counter
        freq = Counter(["a", "b", "c", "d"] * 10)
        # Uniform over 4 types: H = 2.0 bits
        assert abs(_shannon_entropy(freq) - 2.0) < 0.01

    def test_skewed(self):
        from collections import Counter
        freq = Counter(["a"] * 100 + ["b"] * 1)
        H = _shannon_entropy(freq)
        # Skewed distribution: low entropy
        assert 0 < H < 1.0

    def test_higher_with_more_types(self):
        from collections import Counter
        freq_2 = Counter(["a", "b"] * 10)
        freq_4 = Counter(["a", "b", "c", "d"] * 10)
        assert _shannon_entropy(freq_4) > _shannon_entropy(freq_2)


# =========================================================================
# _mattr (moving-average type-token ratio)
# =========================================================================

class TestMATTR:
    def test_empty(self):
        assert _mattr([]) == 0.0

    def test_short_text(self):
        tokens = ["a", "b", "c", "d", "e"]
        # Shorter than window (100), returns global TTR
        assert _mattr(tokens) == 1.0

    def test_all_unique(self):
        tokens = [f"w{i}" for i in range(200)]
        mattr_val = _mattr(tokens)
        assert mattr_val == 1.0

    def test_all_same(self):
        tokens = ["hello"] * 200
        mattr_val = _mattr(tokens)
        # Each window has TTR = 1/100 = 0.01
        assert 0 < mattr_val < 0.02

    def test_mixed(self):
        # 50 unique words repeated 4 times = 200 tokens
        tokens = [f"w{i % 50}" for i in range(200)]
        mattr_val = _mattr(tokens)
        assert 0.3 < mattr_val < 0.7

    def test_window_parameter(self):
        tokens = [f"w{i % 20}" for i in range(100)]
        mattr_small = _mattr(tokens, window=20, step=10)
        assert 0 < mattr_small <= 1.0


# =========================================================================
# _entropy_gradient
# =========================================================================

class TestEntropyGradient:
    def test_short_text(self):
        tokens = ["a", "b", "c"]
        assert _entropy_gradient(tokens) == 0.0

    def test_widening(self):
        # First half: 2 types, second half: 10 types
        first = ["a", "b"] * 10
        second = [f"w{i}" for i in range(20)]
        tokens = first + second
        grad = _entropy_gradient(tokens)
        assert grad > 0  # Positive = widening

    def test_narrowing(self):
        # First half: 10 types, second half: 2 types
        first = [f"w{i}" for i in range(20)]
        second = ["a", "b"] * 10
        tokens = first + second
        grad = _entropy_gradient(tokens)
        assert grad < 0  # Negative = narrowing

    def test_stable(self):
        tokens = [f"w{i % 10}" for i in range(40)]
        grad = _entropy_gradient(tokens)
        assert abs(grad) < 1.0  # Should be near zero


# =========================================================================
# _classify_entropy
# =========================================================================

class TestClassifyEntropy:
    def test_lexical_desert(self):
        assert _classify_entropy(0.10) == "lexical_desert"
        assert _classify_entropy(0.29) == "lexical_desert"

    def test_narrow_band(self):
        assert _classify_entropy(0.30) == "narrow_band"
        assert _classify_entropy(0.49) == "narrow_band"

    def test_balanced(self):
        assert _classify_entropy(0.50) == "balanced"
        assert _classify_entropy(0.69) == "balanced"

    def test_rich_lexicon(self):
        assert _classify_entropy(0.70) == "rich_lexicon"
        assert _classify_entropy(0.84) == "rich_lexicon"

    def test_encyclopedic(self):
        assert _classify_entropy(0.85) == "encyclopedic"
        assert _classify_entropy(1.0) == "encyclopedic"

    def test_zero(self):
        assert _classify_entropy(0.0) == "lexical_desert"


# =========================================================================
# _empty_result
# =========================================================================

class TestEmptyResult:
    def test_keys(self):
        result = _empty_result()
        expected_keys = {
            "total_tokens", "unique_types", "type_token_ratio",
            "hapax_count", "hapax_ratio", "shannon_entropy",
            "max_entropy", "entropy_ratio", "mattr",
            "entropy_gradient", "predictability_index",
            "richness_score", "entropy_label",
        }
        assert set(result.keys()) == expected_keys

    def test_values(self):
        result = _empty_result()
        assert result["total_tokens"] == 0
        assert result["entropy_label"] == "absent"


# =========================================================================
# compute_textual_entropy — core computation
# =========================================================================

class TestComputeTextualEntropy:
    def test_empty(self):
        result = compute_textual_entropy("")
        assert result["total_tokens"] == 0
        assert result["entropy_label"] == "absent"

    def test_whitespace_only(self):
        result = compute_textual_entropy("   \n\t  ")
        assert result["total_tokens"] == 0

    def test_single_word(self):
        result = compute_textual_entropy("hello")
        assert result["total_tokens"] == 1
        assert result["unique_types"] == 1
        assert result["type_token_ratio"] == 1.0

    def test_repeated_word(self):
        result = compute_textual_entropy("hello hello hello hello hello")
        assert result["total_tokens"] == 5
        assert result["unique_types"] == 1
        assert result["type_token_ratio"] == 0.2
        assert result["shannon_entropy"] == 0.0
        assert result["entropy_label"] == "lexical_desert"

    def test_all_unique(self):
        text = "alpha beta gamma delta epsilon zeta eta theta"
        result = compute_textual_entropy(text)
        assert result["unique_types"] == 8
        assert result["type_token_ratio"] == 1.0
        assert result["hapax_ratio"] == 1.0
        assert result["entropy_ratio"] == 1.0

    def test_mixed_text(self):
        text = "The quick brown fox jumps over the lazy dog. " * 5
        result = compute_textual_entropy(text)
        assert result["total_tokens"] > 0
        assert 0 < result["type_token_ratio"] < 1
        assert 0 < result["shannon_entropy"] < result["max_entropy"]

    def test_ttr_calculation(self):
        text = "a b c a b a"
        result = compute_textual_entropy(text)
        # 6 tokens, 3 unique: TTR = 0.5
        assert result["total_tokens"] == 6
        assert result["unique_types"] == 3
        assert abs(result["type_token_ratio"] - 0.5) < 0.01

    def test_hapax_count(self):
        text = "a a a b b c d"
        result = compute_textual_entropy(text)
        # c and d appear once each
        assert result["hapax_count"] == 2

    def test_hapax_ratio(self):
        text = "a a a b b c d"
        result = compute_textual_entropy(text)
        # 4 unique types, 2 hapax: ratio = 0.5
        assert abs(result["hapax_ratio"] - 0.5) < 0.01

    def test_entropy_ratio_bounded(self):
        text = "This is a test sentence with some words in it."
        result = compute_textual_entropy(text)
        assert 0 <= result["entropy_ratio"] <= 1.0

    def test_predictability_complement(self):
        text = "alpha beta gamma delta"
        result = compute_textual_entropy(text)
        # predictability = 1 - entropy_ratio
        expected = 1.0 - result["entropy_ratio"]
        assert abs(result["predictability_index"] - expected) < 0.001

    def test_richness_score_bounded(self):
        text = "The cat sat on the mat."
        result = compute_textual_entropy(text)
        assert 0 <= result["richness_score"] <= 1.0

    def test_gradient_positive(self):
        # Text that widens vocabulary: first half repetitive, second half diverse
        # Need balanced token counts so the split doesn't skew
        # Use purely alphabetic words to avoid digit-stripping issues
        diverse_words = [
            "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
            "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi",
            "rho", "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega",
            "red", "blue", "green", "yellow", "purple", "orange", "cyan", "magenta",
            "north", "south", "east", "west", "up", "down", "left", "right",
            "fire", "water", "earth", "wind", "ice", "storm", "light", "dark",
            "sun", "moon", "star", "comet", "planet", "galaxy", "void", "space",
            "tree", "leaf", "root", "branch", "seed", "flower", "fruit", "bark",
            "stone", "sand", "clay", "iron", "gold", "silver", "copper", "bronze",
        ]
        first = "the the the the " * 20  # 80 tokens, 1 type
        second = " ".join(diverse_words)  # 80 tokens, 80 types
        text = first + " " + second
        result = compute_textual_entropy(text)
        # Gradient should be positive (widening)
        assert result["entropy_gradient"] > 0

    def test_unicode_text(self):
        text = "café résumé naïve café"
        result = compute_textual_entropy(text)
        assert result["total_tokens"] > 0

    def test_long_text(self):
        words = [f"word{i % 100}" for i in range(1000)]
        text = " ".join(words)
        result = compute_textual_entropy(text)
        assert result["total_tokens"] == 1000
        assert result["mattr"] > 0

    def test_field_completeness(self):
        result = compute_textual_entropy("Hello world")
        expected_keys = {
            "total_tokens", "unique_types", "type_token_ratio",
            "hapax_count", "hapax_ratio", "shannon_entropy",
            "max_entropy", "entropy_ratio", "mattr",
            "entropy_gradient", "predictability_index",
            "richness_score", "entropy_label",
        }
        assert set(result.keys()) == expected_keys

    def test_non_negative_values(self):
        text = "A simple test sentence for checking values."
        result = compute_textual_entropy(text)
        for key in ["total_tokens", "unique_types", "hapax_count",
                     "shannon_entropy", "max_entropy"]:
            assert result[key] >= 0

    def test_telegraphic_style(self):
        # Very concise, high content word ratio
        text = "Run fast jump high climb wall dodge arrow"
        result = compute_textual_entropy(text)
        assert result["type_token_ratio"] > 0.8

    def test_conversational_style(self):
        # Lots of function words, repetition
        text = "Well I think that maybe we should probably just go ahead and do it"
        result = compute_textual_entropy(text)
        assert result["total_tokens"] > 5


# =========================================================================
# On-disk integration
# =========================================================================

class TestOnDiskIntegration:
    def test_strokes_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"body": "Hello world this is a test"}) + "\n")
            f.write(json.dumps({"body": "Another stroke with some words"}) + "\n")
            path = f.name

        try:
            result = textual_entropy_report(path)
            assert result["total_tokens"] > 0
        finally:
            os.unlink(path)

    def test_missing_file(self):
        result = textual_entropy_report("/nonexistent/path.jsonl")
        assert result["total_tokens"] == 0
        assert result["entropy_label"] == "absent"

    def test_malformed_jsonl(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("not valid json\n")
            f.write(json.dumps({"body": "valid entry"}) + "\n")
            f.write("{broken\n")
            path = f.name

        try:
            result = textual_entropy_report(path)
            assert result["total_tokens"] > 0
        finally:
            os.unlink(path)

    def test_empty_text_fields(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"body": ""}) + "\n")
            f.write(json.dumps({"body": "   "}) + "\n")
            path = f.name

        try:
            result = textual_entropy_report(path)
            # Whitespace-only should still tokenize to something
            assert result["total_tokens"] >= 0
        finally:
            os.unlink(path)

    def test_body_fallback(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"text": "fallback text here"}) + "\n")
            f.write(json.dumps({"content": "content field works"}) + "\n")
            path = f.name

        try:
            result = textual_entropy_report(path)
            assert result["total_tokens"] > 0
        finally:
            os.unlink(path)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            result = textual_entropy_report(path)
            assert result["total_tokens"] == 0
        finally:
            os.unlink(path)


# =========================================================================
# Summary formatting
# =========================================================================

class TestSummary:
    def test_lines(self):
        result = compute_textual_entropy("Hello world hello world")
        summary = textual_entropy_summary(result)
        lines = summary.split("\n")
        assert len(lines) >= 10

    def test_key_fields(self):
        result = compute_textual_entropy("Test sentence for summary")
        summary = textual_entropy_summary(result)
        assert "Tokens:" in summary
        assert "Shannon" in summary
        assert "Label:" in summary

    def test_empty_summary(self):
        result = _empty_result()
        summary = textual_entropy_summary(result)
        assert "No text available" in summary

    def test_gradient_direction(self):
        result = compute_textual_entropy("a b c " * 20)
        summary = textual_entropy_summary(result)
        assert "stable" in summary or "widening" in summary or "narrowing" in summary


# =========================================================================
# CLI
# =========================================================================

class TestCLI:
    def test_exit_code(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"body": "test"}) + "\n")
            path = f.name

        try:
            sys.argv = ["writer_textual_entropy", "--strokes", path]
            ret = main()
            assert ret == 0
        finally:
            os.unlink(path)

    def test_json_output(self, capsys):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"body": "test data"}) + "\n")
            path = f.name

        try:
            sys.argv = ["writer_textual_entropy", "--json", "--strokes", path]
            main()
            captured = capsys.readouterr()
            data = json.loads(captured.out)
            assert "total_tokens" in data
        finally:
            os.unlink(path)

    def test_text_output(self, capsys):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"body": "test data"}) + "\n")
            path = f.name

        try:
            sys.argv = ["writer_textual_entropy", "--strokes", path]
            main()
            captured = capsys.readouterr()
            assert "Textual Entropy" in captured.out
        finally:
            os.unlink(path)


# =========================================================================
# Edge cases
# =========================================================================

class TestEdgeCases:
    def test_single_sentence(self):
        result = compute_textual_entropy("Just one sentence here.")
        assert result["total_tokens"] > 0

    def test_numbers_only(self):
        result = compute_textual_entropy("123 456 789")
        assert result["total_tokens"] == 0

    def test_mixed_scripts(self):
        result = compute_textual_entropy("Hello 你好 world 世界")
        assert result["total_tokens"] > 0

    def test_very_long_text(self):
        words = [f"w{i % 200}" for i in range(5000)]
        text = " ".join(words)
        result = compute_textual_entropy(text)
        assert result["total_tokens"] == 5000
        assert result["mattr"] > 0

    def test_all_hapax(self):
        text = "alpha beta gamma delta epsilon zeta"
        result = compute_textual_entropy(text)
        assert result["hapax_ratio"] == 1.0

    def test_no_hapax(self):
        text = "a a b b c c d d"
        result = compute_textual_entropy(text)
        assert result["hapax_count"] == 0
        assert result["hapax_ratio"] == 0.0

    def test_richness_monotonic_with_diversity(self):
        low = compute_textual_entropy("a a a a b b b b")
        high = compute_textual_entropy("a b c d e f g h")
        assert high["richness_score"] > low["richness_score"]

    def test_entropy_ratio_monotonic(self):
        low = compute_textual_entropy("a a a a a b")
        high = compute_textual_entropy("a b c d e f")
        assert high["entropy_ratio"] > low["entropy_ratio"]
