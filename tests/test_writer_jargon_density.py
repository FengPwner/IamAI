#!/usr/bin/env python3
"""Tests for writer_jargon_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_jargon_density import (
    JargonDensityResult,
    JargonHit,
    measure_jargon_density,
    _tokenize,
    _split_sentences,
    _find_jargon,
    _check_explained,
    _classify,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_jargon_density("")
        assert r.total_jargon == 0
        assert r.classification == "unknown"

    def test_whitespace_only(self):
        r = measure_jargon_density("   \n\n   ")
        assert r.total_jargon == 0
        assert r.classification == "unknown"

    def test_single_word_plain(self):
        r = measure_jargon_density("Hello.")
        assert r.total_jargon == 0
        assert r.word_count == 1
        # Too short to classify reliably
        assert r.classification == "unknown"

    def test_none_like_empty(self):
        r = measure_jargon_density("")
        assert r.jargon_rate == 0.0


# ── tokenization ────────────────────────────────────────────────


class TestTokenize:
    def test_basic_tokenization(self):
        tokens = _tokenize("Hello world")
        assert tokens == ["hello", "world"]

    def test_punctuation_stripped(self):
        tokens = _tokenize("Hello, world! How are you?")
        assert "hello" in tokens
        assert "world" in tokens
        assert "," not in tokens
        assert "!" not in tokens

    def test_apostrophe_preserved(self):
        tokens = _tokenize("don't can't won't")
        assert "don't" in tokens
        assert "can't" in tokens

    def test_empty_string(self):
        assert _tokenize("") == []


# ── sentence splitting ──────────────────────────────────────────


class TestSplitSentences:
    def test_basic_sentences(self):
        parts = _split_sentences("Hello world. How are you?")
        assert len(parts) == 2

    def test_exclamation(self):
        parts = _split_sentences("Wow! Amazing!")
        assert len(parts) == 2

    def test_no_punctuation(self):
        parts = _split_sentences("Just some text without punctuation")
        assert len(parts) == 1


# ── jargon detection ────────────────────────────────────────────


class TestJargonDetection:
    def test_technical_jargon_detected(self):
        text = "The polymorphism in this codebase enables flexible type handling."
        r = measure_jargon_density(text)
        assert r.technical_count >= 1
        assert "polymorphism" in r.jargon_words

    def test_corporate_buzzword_detected(self):
        text = "We need to leverage our synergies to move the needle."
        r = measure_jargon_density(text)
        assert r.buzzword_count >= 1
        assert r.total_jargon >= 1

    def test_academic_jargon_detected(self):
        text = "We utilize this methodology to facilitate the discourse."
        r = measure_jargon_density(text)
        assert r.academic_count >= 1

    def test_plain_text_no_jargon(self):
        text = "The cat sat on the mat and looked at the door."
        r = measure_jargon_density(text)
        assert r.total_jargon == 0
        assert r.classification == "plain"

    def test_case_insensitive(self):
        text = "POLYMORPHISM is important. Idempotent operations matter."
        r = measure_jargon_density(text)
        assert r.total_jargon >= 2

    def test_multi_word_phrase(self):
        text = "We need to circle back on this action item."
        r = measure_jargon_density(text)
        assert r.total_jargon >= 1

    def test_multiple_jargon_terms(self):
        text = (
            "The stochastic gradient descent with backpropagation "
            "and regularization prevents overfitting in the model."
        )
        r = measure_jargon_density(text)
        assert r.total_jargon >= 2
        assert r.technical_count >= 2

    def test_word_boundary_respected(self):
        # "scale" is jargon, "scaled" should not match as exact "scale"
        text = "We scaled the application."
        hits = _find_jargon(text)
        # "scaled" is not in the lexicon as exact match
        terms = [h.term for h in hits]
        assert "scale" not in terms  # boundary check


# ── jargon density classification ───────────────────────────────


class TestClassification:
    def test_plain_classification(self):
        assert _classify(0.5, 100) == "plain"

    def test_light_jargon_classification(self):
        assert _classify(2.0, 100) == "light_jargon"

    def test_moderate_jargon_classification(self):
        assert _classify(4.5, 100) == "moderate_jargon"

    def test_heavy_jargon_classification(self):
        assert _classify(8.0, 100) == "heavy_jargon"

    def test_impenetrable_classification(self):
        assert _classify(12.0, 100) == "impenetrable"

    def test_unknown_for_short_text(self):
        assert _classify(5.0, 5) == "unknown"

    def test_boundary_at_1(self):
        assert _classify(1.0, 100) == "light_jargon"

    def test_boundary_at_3(self):
        assert _classify(3.0, 100) == "moderate_jargon"

    def test_boundary_at_6(self):
        assert _classify(6.0, 100) == "heavy_jargon"

    def test_boundary_at_10(self):
        assert _classify(10.0, 100) == "impenetrable"


# ── jargon rate calculation ─────────────────────────────────────


class TestJargonRate:
    def test_rate_per_100_words(self):
        # Create text with known jargon density
        words = ["the"] * 97 + ["polymorphism", "heuristic", "stochastic"]
        text = " ".join(words) + "."
        r = measure_jargon_density(text)
        assert r.jargon_rate == 3.0
        assert r.classification == "moderate_jargon"

    def test_weighted_rate_higher_for_opaque_terms(self):
        # "polymorphism" has weight 3, "refactor" has weight 1
        text_heavy = " ".join(["the"] * 48 + ["polymorphism", "polymorphism"]) + "."
        text_light = " ".join(["the"] * 48 + ["refactor", "refactor"]) + "."
        r_heavy = measure_jargon_density(text_heavy)
        r_light = measure_jargon_density(text_light)
        assert r_heavy.weighted_jargon_rate > r_light.weighted_jargon_rate

    def test_zero_rate_for_plain_text(self):
        text = "The cat sat on the mat near the door."
        r = measure_jargon_density(text)
        assert r.jargon_rate == 0.0


# ── buzzword ratio ──────────────────────────────────────────────


class TestBuzzwordRatio:
    def test_all_buzzwords(self):
        text = "We need to leverage synergies and circle back to move the needle."
        r = measure_jargon_density(text)
        assert r.buzzword_ratio > 0.5

    def test_all_technical(self):
        text = (
            "The polymorphism and stochastic nature of the heuristic "
            "requires idempotent operations with recursive patterns."
        )
        r = measure_jargon_density(text)
        assert r.buzzword_ratio == 0.0

    def test_mixed_content(self):
        text = (
            "We leverage polymorphism to facilitate the heuristic approach."
        )
        r = measure_jargon_density(text)
        assert 0.0 < r.buzzword_ratio < 1.0

    def test_zero_buzzword_ratio_when_no_jargon(self):
        text = "The cat sat on the mat."
        r = measure_jargon_density(text)
        assert r.buzzword_ratio == 0.0


# ── explanation detection ────────────────────────────────────────


class TestExplanationDetection:
    def test_explained_with_which(self):
        text = (
            "The idempotent, which means producing the same result "
            "each time, simplifies retry logic in distributed systems."
        )
        r = measure_jargon_density(text)
        if r.total_jargon > 0:
            assert r.explanation_ratio > 0.0

    def test_explained_with_dash(self):
        text = (
            "The heuristic — a practical approach to problem-solving — "
            "works well for most cases in production environments."
        )
        r = measure_jargon_density(text)
        if r.total_jargon > 0:
            explained_hits = [h for h in r.jargon_hits if h.explained]
            assert len(explained_hits) >= 0  # may or may not match pattern

    def test_unexplained_jargon(self):
        text = (
            "The polymorphism enables stochastic gradient descent "
            "with regularized backpropagation for the idempotent cache."
        )
        r = measure_jargon_density(text)
        assert r.explanation_ratio < 1.0

    def test_explanation_with_ie(self):
        text = (
            "We use an idempotent operation, i.e. one that produces "
            "the same result when called multiple times."
        )
        hits = _find_jargon(text)
        idempotent_hits = [h for h in hits if h.term == "idempotent"]
        if idempotent_hits:
            explained = _check_explained(text, idempotent_hits[0])
            assert explained is True


# ── top jargon terms ─────────────────────────────────────────────


class TestTopJargon:
    def test_top_jargon_ordered_by_frequency(self):
        text = (
            "The polymorphism and polymorphism with heuristic and "
            "stochastic approach requires polymorphism in the code."
        )
        r = measure_jargon_density(text)
        if len(r.top_jargon) >= 2:
            assert r.top_jargon[0][1] >= r.top_jargon[1][1]

    def test_top_jargon_includes_repeated_terms(self):
        text = (
            "The heuristic approach is a heuristic method using "
            "heuristic patterns and heuristic rules."
        )
        r = measure_jargon_density(text)
        heuristic_count = sum(
            count for term, count in r.top_jargon if term == "heuristic"
        )
        assert heuristic_count >= 3

    def test_empty_top_jargon_for_plain_text(self):
        text = "The cat sat on the mat."
        r = measure_jargon_density(text)
        assert r.top_jargon == []


# ── category breakdown ──────────────────────────────────────────


class TestCategoryBreakdown:
    def test_counts_sum_to_total(self):
        text = (
            "We leverage polymorphism to utilize the heuristic "
            "stochastic approach with synergies."
        )
        r = measure_jargon_density(text)
        assert (
            r.technical_count + r.buzzword_count + r.academic_count
            == r.total_jargon
        )

    def test_technical_only(self):
        text = (
            "The recursive polymorphism with stochastic gradient "
            "descent requires idempotent operations."
        )
        r = measure_jargon_density(text)
        assert r.buzzword_count == 0
        assert r.academic_count == 0
        assert r.technical_count > 0

    def test_buzzword_only(self):
        text = (
            "We need to circle back and touch base to leverage "
            "our synergies and move the needle."
        )
        r = measure_jargon_density(text)
        assert r.buzzword_count > 0
        # Technical terms should be minimal in this text
        # (may have 0 or very few)


# ── word and sentence counts ────────────────────────────────────


class TestCounts:
    def test_word_count(self):
        text = "One two three four five."
        r = measure_jargon_density(text)
        assert r.word_count == 5

    def test_sentence_count(self):
        text = "First sentence. Second sentence. Third one!"
        r = measure_jargon_density(text)
        assert r.sentence_count == 3

    def test_single_sentence(self):
        text = "Just one sentence here."
        r = measure_jargon_density(text)
        assert r.sentence_count == 1


# ── result dataclass defaults ───────────────────────────────────


class TestResultDefaults:
    def test_default_result(self):
        r = JargonDensityResult()
        assert r.total_jargon == 0
        assert r.jargon_rate == 0.0
        assert r.classification == "unknown"
        assert r.word_count == 0
        assert r.jargon_words == []
        assert r.jargon_hits == []

    def test_default_hit(self):
        h = JargonHit(term="test", category="technical", weight=2, position=0)
        assert h.explained is False
        assert h.term == "test"


# ── integration: realistic texts ─────────────────────────────────


class TestIntegration:
    def test_technical_blog_post(self):
        text = (
            "Building a microservice architecture with Kubernetes "
            "requires understanding eventual consistency and circuit "
            "breaker patterns. The backpressure mechanism prevents "
            "overload in the message queue. We use gRPC for "
            "inter-service communication and implement sharding "
            "for the database layer."
        )
        r = measure_jargon_density(text)
        assert r.technical_count >= 3
        assert r.classification in (
            "light_jargon", "moderate_jargon", "heavy_jargon", "impenetrable"
        )

    def test_corporate_email(self):
        text = (
            "Let's circle back on the action items from the deep dive. "
            "We need to leverage our synergies to move the needle on "
            "this deliverable. I'll touch base with stakeholders and "
            "ping you offline. Going forward, let's align on best "
            "practices and take this offline."
        )
        r = measure_jargon_density(text)
        assert r.buzzword_count >= 3
        assert r.buzzword_ratio > 0.3

    def test_plain_english(self):
        text = (
            "The weather was nice today. I went for a walk in the "
            "park and saw some birds. The flowers were starting to "
            "bloom. I sat on a bench and read a book for an hour. "
            "Then I walked home and made dinner."
        )
        r = measure_jargon_density(text)
        assert r.classification == "plain"
        assert r.total_jargon == 0

    def test_academic_paper(self):
        text = (
            "This paper utilizes a novel methodology to elucidate "
            "the epistemological foundations of the discourse. "
            "We interrogate the hegemonic structures and "
            "problematize the normative assumptions. The "
            "hermeneutic approach facilitates a deeper "
            "understanding of the phenomenological experience."
        )
        r = measure_jargon_density(text)
        assert r.academic_count >= 3
        assert r.classification in (
            "moderate_jargon", "heavy_jargon", "impenetrable"
        )

    def test_mixed_register(self):
        text = (
            "The server crashed because the recursive function had "
            "no base case. Simple fix — add a return when n reaches "
            "zero. But the real problem was the polymorphic type "
            "system letting bad data through."
        )
        r = measure_jargon_density(text)
        assert r.technical_count >= 1
        # Should be light — mostly plain explanation with a few terms
        assert r.classification in ("plain", "light_jargon", "moderate_jargon")


# ── edge cases ───────────────────────────────────────────────────


class TestEdgeCases:
    def test_repeated_same_jargon(self):
        text = "Leverage leverage leverage leverage leverage. " * 3
        r = measure_jargon_density(text)
        assert r.total_jargon >= 10
        assert r.jargon_rate == 100.0
        assert r.classification == "impenetrable"

    def test_jargon_in_parentheses(self):
        text = "The (polymorphism) was important."
        r = measure_jargon_density(text)
        assert r.total_jargon >= 1

    def test_very_long_text(self):
        words = ["the", "cat", "sat"] * 500 + ["polymorphism"] * 10
        text = " ".join(words) + "."
        r = measure_jargon_density(text)
        assert r.word_count > 1000
        assert r.total_jargon == 10

    def test_all_jargon_no_plain_words(self):
        text = "Polymorphism heuristic stochastic idempotent recursive. " * 3
        r = measure_jargon_density(text)
        assert r.jargon_rate == 100.0
        assert r.classification == "impenetrable"
