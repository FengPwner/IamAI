"""Tests for iamai.text_similarity — shared text comparison utilities.

Visit 810: this module provides five complementary text similarity metrics
plus a composite score, intended as shared infrastructure for all analysis
modules that compare text content (stroke_dedup, content_loop_detector,
template_loop_detector, etc.).

Test areas:
    1. token_jaccard            — token-set Jaccard similarity
    2. ngram_overlap            — directional n-gram containment
    3. word_frequency_cosine    — cosine of frequency vectors
    4. lcs_ratio                — character-level LCS ratio
    5. structural_similarity    — sentence-opener Jaccard
    6. composite_similarity     — weighted blend + rounding
    7. pairwise_similarity      — NxN matrix computation
    8. edge cases               — empty input, single word, identical texts
    9. metric properties        — symmetry, reflexivity, bounds
   10. helper functions         — tokenise, ngrams, sentence_openers
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.text_similarity import (
    _lcs_length,
    _ngrams,
    _sentence_openers,
    _token_set,
    _tokenise,
    composite_similarity,
    lcs_ratio,
    ngram_overlap,
    pairwise_similarity,
    structural_similarity,
    token_jaccard,
    word_frequency_cosine,
)


# -----------------------------------------------------------------------
# 1. token_jaccard
# -----------------------------------------------------------------------

class TestTokenJaccard:
    def test_identical_texts(self):
        assert token_jaccard("hello world", "hello world") == 1.0

    def test_completely_different(self):
        assert token_jaccard("hello world", "foo bar baz") == 0.0

    def test_partial_overlap(self):
        # tokens: {the, quick, brown, fox} vs {the, quick, brown, dog}
        # intersection = 3, union = 5 → 0.6
        assert token_jaccard("the quick brown fox", "the quick brown dog") == pytest.approx(0.6)

    def test_empty_both(self):
        assert token_jaccard("", "") == 1.0

    def test_one_empty(self):
        assert token_jaccard("hello", "") == 0.0
        assert token_jaccard("", "hello") == 0.0

    def test_case_insensitive(self):
        assert token_jaccard("Hello World", "hello world") == 1.0

    def test_repeated_words_collapsed(self):
        # token set: {"the", "cat"} for both
        assert token_jaccard("the cat the cat", "the cat") == 1.0

    def test_superset(self):
        # {a, b} vs {a, b, c, d} → 2/4 = 0.5
        assert token_jaccard("a b", "a b c d") == pytest.approx(0.5)

    def test_punctuation_ignored(self):
        assert token_jaccard("hello, world!", "hello world") == 1.0


# -----------------------------------------------------------------------
# 2. ngram_overlap
# -----------------------------------------------------------------------

class TestNgramOverlap:
    def test_identical_texts(self):
        assert ngram_overlap("a b c d", "a b c d", n=2) == 1.0

    def test_no_overlap(self):
        assert ngram_overlap("a b c", "x y z", n=2) == 0.0

    def test_partial_overlap(self):
        # a: [("the","quick"), ("quick","brown"), ("brown","fox")] = 3 bigrams
        # b: [("the","quick"), ("quick","brown"), ("brown","dog")] = 3 bigrams
        # shared: 2 out of 3 from a → 2/3
        result = ngram_overlap("the quick brown fox", "the quick brown dog", n=2)
        assert result == pytest.approx(2 / 3)

    def test_directional(self):
        # a is shorter, all of a's bigrams in b → 1.0
        assert ngram_overlap("a b", "a b c d", n=2) == 1.0
        # b has bigrams not in a → < 1.0
        assert ngram_overlap("a b c d", "a b", n=2) < 1.0

    def test_empty_source(self):
        # empty a → no n-grams to check → 1.0
        assert ngram_overlap("", "hello world", n=2) == 1.0

    def test_empty_target(self):
        # a has n-grams but b has none → 0.0
        assert ngram_overlap("hello world foo", "", n=2) == 0.0

    def test_trigrams(self):
        a = "the quick brown fox jumps"
        b = "the quick brown fox leaps"
        # trigrams of a: (the,quick,brown), (quick,brown,fox), (brown,fox,jumps)
        # trigrams of b: (the,quick,brown), (quick,brown,fox), (brown,fox,leaps)
        # 2 out of 3 from a in b
        assert ngram_overlap(a, b, n=3) == pytest.approx(2 / 3)

    def test_single_word_no_bigrams(self):
        assert ngram_overlap("hello", "hello", n=2) == 1.0  # no bigrams → 1.0

    def test_case_insensitive(self):
        assert ngram_overlap("The Quick", "the quick brown", n=2) == 1.0


# -----------------------------------------------------------------------
# 3. word_frequency_cosine
# -----------------------------------------------------------------------

class TestWordFrequencyCosine:
    def test_identical_texts(self):
        assert word_frequency_cosine("a b c", "a b c") == pytest.approx(1.0)

    def test_completely_different(self):
        assert word_frequency_cosine("a b c", "x y z") == 0.0

    def test_same_words_different_frequency(self):
        # a: {"the":2, "cat":1}  b: {"the":1, "cat":2}
        # cos = (2*1 + 1*2) / (sqrt(4+1) * sqrt(1+4)) = 4/5 = 0.8
        result = word_frequency_cosine("the the cat", "the cat cat")
        assert result == pytest.approx(0.8)

    def test_empty_both(self):
        assert word_frequency_cosine("", "") == 0.0

    def test_one_empty(self):
        assert word_frequency_cosine("hello", "") == 0.0

    def test_proportional_frequencies(self):
        # Same distribution, different magnitudes → cosine = 1.0
        assert word_frequency_cosine("a a b b", "a b") == pytest.approx(1.0)

    def test_bounds(self):
        result = word_frequency_cosine("hello world foo", "hello world bar")
        assert 0.0 <= result <= 1.0


# -----------------------------------------------------------------------
# 4. lcs_ratio
# -----------------------------------------------------------------------

class TestLcsRatio:
    def test_identical_strings(self):
        assert lcs_ratio("abcdef", "abcdef") == pytest.approx(1.0)

    def test_completely_different(self):
        assert lcs_ratio("abc", "xyz") == 0.0

    def test_subsequence(self):
        # "ace" is a subsequence of "abcde" → LCS=3, min_len=3 → 1.0
        assert lcs_ratio("ace", "abcde") == pytest.approx(1.0)

    def test_partial_overlap(self):
        # "abcd" vs "abef" → LCS = "ab" = 2, min_len = 4 → 0.5
        assert lcs_ratio("abcd", "abef") == pytest.approx(0.5)

    def test_empty_both(self):
        assert lcs_ratio("", "") == 1.0

    def test_one_empty(self):
        assert lcs_ratio("abc", "") == 0.0

    def test_truncation_for_long_input(self):
        # Inputs > 2000 chars should still work without blowing up
        a = "x" * 3000
        b = "x" * 3000
        result = lcs_ratio(a, b)
        assert result == pytest.approx(1.0)

    def test_symmetry(self):
        assert lcs_ratio("abc", "bcd") == pytest.approx(lcs_ratio("bcd", "abc"))


# -----------------------------------------------------------------------
# 5. structural_similarity
# -----------------------------------------------------------------------

class TestStructuralSimilarity:
    def test_identical_openers(self):
        a = "The cat sat. The dog ran. The bird flew."
        b = "The fish swam. The horse galloped. The snake slithered."
        # Both have openers: {"the cat"/"the dog"/"the bird"} vs {"the fish"/"the horse"/"the snake"}
        # Actually with prefix_words=2: {"the cat", "the dog", "the bird"} vs {"the fish", "the horse", "the snake"}
        # intersection=0, union=6 → 0.0
        # Wait, let me re-think. prefix_words=2 means first 2 tokens.
        # "The cat sat." → ["the", "cat"] → "the cat"
        # "The dog ran." → ["the", "dog"] → "the dog"
        # etc. All different → Jaccard = 0/6 = 0.0
        result = structural_similarity(a, b, prefix_words=2)
        assert result == pytest.approx(0.0)

    def test_same_openers(self):
        a = "The cat sat. The cat ran. The cat slept."
        b = "The cat jumped. The cat played. The cat ate."
        # Both have opener set: {"the cat"} → Jaccard = 1/1 = 1.0
        result = structural_similarity(a, b, prefix_words=2)
        assert result == pytest.approx(1.0)

    def test_empty_both(self):
        assert structural_similarity("", "") == 1.0

    def test_one_empty(self):
        assert structural_similarity("Hello world.", "") == 0.0

    def test_single_word_prefix(self):
        a = "The cat sat. The dog ran."
        b = "The bird flew. The fish swam."
        # prefix_words=1: {"the"} vs {"the"} → 1.0
        result = structural_similarity(a, b, prefix_words=1)
        assert result == pytest.approx(1.0)

    def test_no_sentences(self):
        # No sentence-ending punctuation → treated as one fragment
        # _SENTENCE_RE still finds it as one sentence
        result = structural_similarity("hello world", "hello world")
        assert result == pytest.approx(1.0)


# -----------------------------------------------------------------------
# 6. composite_similarity
# -----------------------------------------------------------------------

class TestCompositeSimilarity:
    def test_identical_texts(self):
        result = composite_similarity("hello world foo bar", "hello world foo bar")
        assert result["composite"] == pytest.approx(1.0)
        assert result["jaccard"] == pytest.approx(1.0)

    def test_completely_different(self):
        result = composite_similarity("hello world", "xyz abc")
        assert result["composite"] < 0.3

    def test_returns_all_keys(self):
        result = composite_similarity("a b c", "a b d")
        expected_keys = {"jaccard", "ngram", "cosine", "lcs", "structural", "composite"}
        assert set(result.keys()) == expected_keys

    def test_custom_weights(self):
        # Only weight jaccard → composite equals jaccard score
        result = composite_similarity(
            "hello world", "hello foo",
            weights={"jaccard": 1.0, "ngram": 0.0, "cosine": 0.0, "lcs": 0.0, "structural": 0.0},
        )
        assert result["composite"] == result["jaccard"]

    def test_zero_weights(self):
        result = composite_similarity(
            "hello", "world",
            weights={"jaccard": 0.0, "ngram": 0.0, "cosine": 0.0, "lcs": 0.0, "structural": 0.0},
        )
        assert result["composite"] == 0.0

    def test_rounding(self):
        result = composite_similarity("a b c d e", "a b c x y")
        for key in ("jaccard", "ngram", "cosine", "lcs", "structural", "composite"):
            # Check that values are rounded to 4 decimal places
            s = str(result[key])
            if "." in s:
                decimals = len(s.split(".")[1])
                assert decimals <= 4


# -----------------------------------------------------------------------
# 7. pairwise_similarity
# -----------------------------------------------------------------------

class TestPairwiseSimilarity:
    def test_single_text(self):
        matrix = pairwise_similarity(["hello world"])
        assert matrix == [[1.0]]

    def test_two_texts(self):
        texts = ["hello world", "hello world"]
        matrix = pairwise_similarity(texts, metric="jaccard")
        assert matrix[0][0] == 1.0
        assert matrix[1][1] == 1.0
        assert matrix[0][1] == 1.0
        assert matrix[1][0] == 1.0

    def test_symmetry_jaccard(self):
        texts = ["a b c", "b c d", "x y z"]
        matrix = pairwise_similarity(texts, metric="jaccard")
        for i in range(3):
            for j in range(3):
                assert matrix[i][j] == pytest.approx(matrix[j][i])

    def test_diagonal_is_one(self):
        texts = ["hello", "world", "foo bar"]
        matrix = pairwise_similarity(texts, metric="cosine")
        for i in range(3):
            assert matrix[i][i] == 1.0

    def test_unknown_metric_raises(self):
        with pytest.raises(ValueError, match="Unknown metric"):
            pairwise_similarity(["a"], metric="bogus")

    def test_empty_list(self):
        matrix = pairwise_similarity([])
        assert matrix == []


# -----------------------------------------------------------------------
# 8. edge cases
# -----------------------------------------------------------------------

class TestEdgeCases:
    def test_single_word(self):
        assert token_jaccard("hello", "hello") == 1.0
        assert token_jaccard("hello", "world") == 0.0

    def test_numbers_as_tokens(self):
        assert token_jaccard("test 123", "test 456") == pytest.approx(1 / 3)

    def test_very_long_texts(self):
        a = " ".join(f"word{i}" for i in range(500))
        b = " ".join(f"word{i}" for i in range(250, 750))
        result = token_jaccard(a, b)
        # intersection = 250 (words 250-499), union = 750
        assert result == pytest.approx(250 / 750)

    def test_unicode_handling(self):
        # Non-ASCII chars stripped by alphanumeric-only regex
        assert token_jaccard("café résumé", "café résumé") == 1.0

    def test_whitespace_only(self):
        assert token_jaccard("   ", "   ") == 1.0  # both empty token sets


# -----------------------------------------------------------------------
# 9. metric properties
# -----------------------------------------------------------------------

class TestMetricProperties:
    """Verify basic mathematical properties of the similarity functions."""

    PAIRS = [
        ("the quick brown fox", "the quick brown fox"),
        ("hello world", "goodbye universe"),
        ("a b c d e f", "a b c x y z"),
        ("tests are the specification that runs", "tests verify behaviour"),
    ]

    @pytest.mark.parametrize("a,b", PAIRS)
    def test_reflexivity(self, a, b):
        assert token_jaccard(a, a) == 1.0
        assert word_frequency_cosine(a, a) == pytest.approx(1.0)

    @pytest.mark.parametrize("a,b", PAIRS)
    def test_symmetry_jaccard(self, a, b):
        assert token_jaccard(a, b) == pytest.approx(token_jaccard(b, a))

    @pytest.mark.parametrize("a,b", PAIRS)
    def test_symmetry_cosine(self, a, b):
        assert word_frequency_cosine(a, b) == pytest.approx(word_frequency_cosine(b, a))

    @pytest.mark.parametrize("a,b", PAIRS)
    def test_bounds_jaccard(self, a, b):
        v = token_jaccard(a, b)
        assert 0.0 <= v <= 1.0

    @pytest.mark.parametrize("a,b", PAIRS)
    def test_bounds_cosine(self, a, b):
        v = word_frequency_cosine(a, b)
        assert 0.0 <= v <= 1.0

    @pytest.mark.parametrize("a,b", PAIRS)
    def test_bounds_lcs(self, a, b):
        v = lcs_ratio(a, b)
        assert 0.0 <= v <= 1.0


# -----------------------------------------------------------------------
# 10. helper functions
# -----------------------------------------------------------------------

class TestHelpers:
    def test_tokenise_basic(self):
        assert _tokenise("Hello, World! 123") == ["hello", "world", "123"]

    def test_tokenise_empty(self):
        assert _tokenise("") == []

    def test_token_set_deduplication(self):
        assert _token_set("the the cat") == {"the", "cat"}

    def test_ngrams_basic(self):
        tokens = ["a", "b", "c", "d"]
        assert _ngrams(tokens, 2) == [("a", "b"), ("b", "c"), ("c", "d")]

    def test_ngrams_empty(self):
        assert _ngrams([], 2) == []

    def test_ngrams_too_short(self):
        assert _ngrams(["a"], 2) == []

    def test_lcs_length_basic(self):
        assert _lcs_length("abcde", "ace") == 3

    def test_lcs_length_empty(self):
        assert _lcs_length("", "abc") == 0

    def test_sentence_openers_basic(self):
        text = "The cat sat. The dog ran. A bird flew."
        openers = _sentence_openers(text, prefix_words=2)
        assert openers == ["the cat", "the dog", "a bird"]

    def test_sentence_openers_single_word(self):
        openers = _sentence_openers("Hello. World.", prefix_words=1)
        assert openers == ["hello", "world"]
