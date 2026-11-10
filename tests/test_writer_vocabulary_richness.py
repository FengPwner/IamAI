#!/usr/bin/env python3
"""Tests for writer_vocabulary_richness.py — vocabulary diversity measurement."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import writer_vocabulary_richness as vr


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _s(label="x", text=""):
    """Shorthand factory for TextSample."""
    return vr.TextSample(label=label, text=text)


# ---------------------------------------------------------------------------
# classify_richness
# ---------------------------------------------------------------------------

class TestClassifyRichness:
    def test_flourishing_at_boundary(self):
        assert vr.classify_richness(0.80) == "flourishing"

    def test_flourishing_high(self):
        assert vr.classify_richness(0.95) == "flourishing"

    def test_flourishing_at_one(self):
        assert vr.classify_richness(1.0) == "flourishing"

    def test_growing_lower_boundary(self):
        assert vr.classify_richness(0.60) == "growing"

    def test_growing_upper(self):
        assert vr.classify_richness(0.79) == "growing"

    def test_stable_lower_boundary(self):
        assert vr.classify_richness(0.40) == "stable"

    def test_stable_upper(self):
        assert vr.classify_richness(0.55) == "stable"

    def test_narrowing_lower_boundary(self):
        assert vr.classify_richness(0.20) == "narrowing"

    def test_narrowing_upper(self):
        assert vr.classify_richness(0.35) == "narrowing"

    def test_stagnant_at_zero(self):
        assert vr.classify_richness(0.0) == "stagnant"

    def test_stagnant_low(self):
        assert vr.classify_richness(0.15) == "stagnant"

    def test_just_below_growing(self):
        assert vr.classify_richness(0.599) == "stable"

    def test_just_below_narrowing(self):
        assert vr.classify_richness(0.199) == "stagnant"

    def test_clamp_above_one(self):
        assert vr.classify_richness(1.5) == "flourishing"

    def test_clamp_below_zero(self):
        assert vr.classify_richness(-0.5) == "stagnant"


# ---------------------------------------------------------------------------
# _tokenise
# ---------------------------------------------------------------------------

class TestTokenise:
    def test_basic_sentence(self):
        tokens = vr._tokenise("The quick brown fox jumps over the lazy dog")
        assert tokens == ["the", "quick", "brown", "fox", "jumps",
                          "over", "the", "lazy", "dog"]

    def test_punctuation_stripped(self):
        tokens = vr._tokenise("hello, world! how is it going?")
        assert "hello" in tokens
        assert "world" in tokens
        assert "how" in tokens
        assert "going" in tokens

    def test_empty_string(self):
        assert vr._tokenise("") == []

    def test_numbers_ignored(self):
        tokens = vr._tokenise("version 3 of module 42 is ready")
        assert "3" not in tokens
        assert "42" not in tokens
        assert "version" in tokens
        assert "module" in tokens

    def test_case_normalised(self):
        tokens = vr._tokenise("UPPER lower MiXeD")
        assert tokens == ["upper", "lower", "mixed"]


# ---------------------------------------------------------------------------
# _content_tokens
# ---------------------------------------------------------------------------

class TestContentTokens:
    def test_stop_words_removed(self):
        tokens = ["the", "quick", "brown", "fox", "is", "very", "fast"]
        content = vr._content_tokens(tokens)
        assert "the" not in content
        assert "is" not in content
        assert "very" not in content
        assert "quick" in content
        assert "brown" in content
        assert "fox" in content
        assert "fast" in content

    def test_all_stop_words(self):
        tokens = ["the", "is", "a", "to", "of"]
        assert vr._content_tokens(tokens) == []

    def test_no_stop_words(self):
        tokens = ["quantum", "entropy", "resonance"]
        assert vr._content_tokens(tokens) == tokens


# ---------------------------------------------------------------------------
# _type_token_ratio
# ---------------------------------------------------------------------------

class TestTypeTokenRatio:
    def test_all_unique(self):
        assert vr._type_token_ratio(["a", "b", "c", "d"]) == 1.0

    def test_all_same(self):
        assert vr._type_token_ratio(["x", "x", "x", "x"]) == 0.25

    def test_half_unique(self):
        assert vr._type_token_ratio(["a", "b", "a", "b"]) == 0.5

    def test_empty(self):
        assert vr._type_token_ratio([]) == 0.0

    def test_single_token(self):
        assert vr._type_token_ratio(["hello"]) == 1.0


# ---------------------------------------------------------------------------
# _hapax_ratio
# ---------------------------------------------------------------------------

class TestHapaxRatio:
    def test_all_hapax(self):
        # Every word appears exactly once
        tokens = ["alpha", "beta", "gamma", "delta"]
        assert vr._hapax_ratio(tokens) == 1.0

    def test_no_hapax(self):
        # Every word appears more than once
        tokens = ["a", "b", "a", "b", "a", "b"]
        assert vr._hapax_ratio(tokens) == 0.0

    def test_mixed(self):
        # "a" appears 3 times, "b" twice, "c" once
        tokens = ["a", "b", "c", "a", "b", "a"]
        # freq: a=3, b=2, c=1 → hapax = {c} → 1/3
        result = vr._hapax_ratio(tokens)
        assert abs(result - 1.0 / 3.0) < 0.001

    def test_empty(self):
        assert vr._hapax_ratio([]) == 0.0

    def test_single_token(self):
        assert vr._hapax_ratio(["only"]) == 1.0


# ---------------------------------------------------------------------------
# _lexical_density
# ---------------------------------------------------------------------------

class TestLexicalDensity:
    def test_all_content(self):
        tokens = ["quantum", "entropy", "resonance", "cascade"]
        density = vr._lexical_density(tokens)
        # 4 content words / 4 total
        assert density == 1.0

    def test_all_stop_words(self):
        tokens = ["the", "is", "a", "to"]
        assert vr._lexical_density(tokens) == 0.0

    def test_mixed(self):
        tokens = ["the", "quantum", "is", "entropy"]
        # content: quantum, entropy → 2 unique content / 4 total
        density = vr._lexical_density(tokens)
        assert abs(density - 0.5) < 0.001

    def test_empty(self):
        assert vr._lexical_density([]) == 0.0


# ---------------------------------------------------------------------------
# _phrase_repetition
# ---------------------------------------------------------------------------

class TestPhraseRepetition:
    def test_no_repetition(self):
        tokens = ["a", "b", "c", "d", "e"]
        # trigrams: "a b c", "b c d", "c d e" — all unique
        assert vr._phrase_repetition(tokens) == 0.0

    def test_full_repetition(self):
        tokens = ["a", "b", "c", "a", "b", "c"]
        # trigrams: "a b c", "b c a", "c a b", "a b c"
        # "a b c" appears twice → 1 repeated out of 3 unique
        result = vr._phrase_repetition(tokens)
        assert result > 0.0

    def test_short_input(self):
        assert vr._phrase_repetition(["a", "b"]) == 0.0

    def test_empty(self):
        assert vr._phrase_repetition([]) == 0.0

    def test_single_trigram(self):
        assert vr._phrase_repetition(["a", "b", "c"]) == 0.0


# ---------------------------------------------------------------------------
# _novelty_fraction
# ---------------------------------------------------------------------------

class TestNoveltyFraction:
    def test_all_novel(self):
        current = ["x", "y", "z"]
        prior = ["a", "b", "c"]
        assert vr._novelty_fraction(current, prior) == 1.0

    def test_none_novel(self):
        current = ["a", "b"]
        prior = ["a", "b", "c"]
        assert vr._novelty_fraction(current, prior) == 0.0

    def test_half_novel(self):
        current = ["a", "b", "c", "d"]
        prior = ["a", "b"]
        # novel = {c, d} → 2/4 = 0.5
        assert vr._novelty_fraction(current, prior) == 0.5

    def test_empty_current(self):
        assert vr._novelty_fraction([], ["a", "b"]) == 0.0

    def test_empty_prior(self):
        # Everything in current is novel
        assert vr._novelty_fraction(["a", "b"], []) == 1.0

    def test_both_empty(self):
        assert vr._novelty_fraction([], []) == 0.0


# ---------------------------------------------------------------------------
# compute_richness — integration
# ---------------------------------------------------------------------------

class TestComputeRichness:
    def test_empty_samples(self):
        result = vr.compute_richness([])
        assert result.richness_class == "stagnant"
        assert result.sample_count == 0
        assert result.total_tokens == 0

    def test_single_sample(self):
        samples = [_s(text="the quick brown fox jumps over the lazy dog")]
        result = vr.compute_richness(samples)
        assert result.sample_count == 1
        assert result.total_tokens > 0
        # With a single sample and no prior, all tokens are "novel"
        assert result.novelty_fraction == 1.0

    def test_diverse_samples(self):
        """Each sample introduces new vocabulary → high richness."""
        samples = [
            _s(text="quantum entanglement creates nonlocal correlations"),
            _s(text="stochastic resonance amplifies weak periodic signals"),
            _s(text="topological insulators exhibit protected surface states"),
            _s(text="bifurcation theory reveals deterministic chaos thresholds"),
            _s(text="emergent computation arises from simple cellular automata"),
        ]
        result = vr.compute_richness(samples, window=5)
        assert result.sample_count == 5
        assert result.richness_score > 0.5
        # Last sample introduces words not in prior 4
        assert result.novelty_fraction > 0.3

    def test_repetitive_samples(self):
        """All samples use the same words → low richness."""
        text = "the system is running and the system is healthy"
        samples = [_s(text=text) for _ in range(5)]
        result = vr.compute_richness(samples, window=5)
        assert result.richness_score < 0.4
        assert result.novelty_fraction == 0.0  # no new words
        assert result.phrase_repetition > 0.0

    def test_window_truncation(self):
        """Only the last `window` samples are used."""
        samples = [
            _s(text="alpha beta gamma delta epsilon"),
            _s(text="zeta eta theta iota kappa"),
            _s(text="lambda mu nu xi omicron"),
            _s(text="the the the the the"),
            _s(text="the the the the the"),
        ]
        # window=3: last 3 samples used
        result = vr.compute_richness(samples, window=3)
        assert result.sample_count == 3

    def test_fewer_than_window(self):
        """When fewer samples than window, use all."""
        samples = [
            _s(text="quantum computing leverages superposition"),
            _s(text="classical algorithms cannot simulate quantum circuits"),
        ]
        result = vr.compute_richness(samples, window=10)
        assert result.sample_count == 2

    def test_empty_text_samples(self):
        samples = [_s(text=""), _s(text=""), _s(text="hello world")]
        result = vr.compute_richness(samples)
        assert result.total_tokens == 2  # only "hello" and "world"

    def test_all_empty_text(self):
        samples = [_s(text=""), _s(text=""), _s(text="")]
        result = vr.compute_richness(samples)
        assert result.total_tokens == 0
        assert result.richness_score == 0.0


# ---------------------------------------------------------------------------
# compute_richness — score sanity
# ---------------------------------------------------------------------------

class TestRichnessScoreSanity:
    def test_high_diversity_high_score(self):
        """Completely different vocabularies → high score."""
        samples = [
            _s(text="mercurial tides cascade through obsidian channels"),
            _s(text="luminous fractals bloom beneath crystalline archways"),
            _s(text="whispering algorithms navigate quantum probability spaces"),
            _s(text="ancient forests harbour bioluminescent fungal networks"),
            _s(text="volcanic eruptions reshape continental drift patterns"),
        ]
        result = vr.compute_richness(samples)
        assert result.richness_score >= 0.5

    def test_identical_texts_low_score(self):
        """Same text repeated → low score."""
        text = "the quick brown fox jumps over the lazy dog"
        samples = [_s(text=text) for _ in range(5)]
        result = vr.compute_richness(samples)
        assert result.richness_score < 0.5

    def test_score_between_zero_and_one(self):
        samples = [
            _s(text="some mixed content with partial overlap"),
            _s(text="some different content with partial overlap"),
            _s(text="entirely new vocabulary here today"),
        ]
        result = vr.compute_richness(samples)
        assert 0.0 <= result.richness_score <= 1.0


# ---------------------------------------------------------------------------
# richness_trend
# ---------------------------------------------------------------------------

class TestRichnessTrend:
    def test_empty_results(self):
        trend = vr.richness_trend([])
        assert trend.trend == "unknown"
        assert trend.scores == []

    def test_improving_trend(self):
        results = [
            vr.RichnessResult(richness_score=0.3),
            vr.RichnessResult(richness_score=0.4),
            vr.RichnessResult(richness_score=0.5),
            vr.RichnessResult(richness_score=0.6),
            vr.RichnessResult(richness_score=0.7),
        ]
        trend = vr.richness_trend(results)
        assert trend.trend == "improving"
        assert trend.slope > 0
        assert len(trend.scores) == 5

    def test_degrading_trend(self):
        results = [
            vr.RichnessResult(richness_score=0.7),
            vr.RichnessResult(richness_score=0.6),
            vr.RichnessResult(richness_score=0.5),
            vr.RichnessResult(richness_score=0.4),
            vr.RichnessResult(richness_score=0.3),
        ]
        trend = vr.richness_trend(results)
        assert trend.trend == "degrading"
        assert trend.slope < 0

    def test_stable_trend(self):
        results = [
            vr.RichnessResult(richness_score=0.50),
            vr.RichnessResult(richness_score=0.51),
            vr.RichnessResult(richness_score=0.50),
            vr.RichnessResult(richness_score=0.51),
            vr.RichnessResult(richness_score=0.50),
        ]
        trend = vr.richness_trend(results)
        assert trend.trend == "stable"
        assert abs(trend.slope) <= 0.02

    def test_single_result(self):
        results = [vr.RichnessResult(richness_score=0.5)]
        trend = vr.richness_trend(results)
        # Single point → slope = 0 → stable
        assert trend.trend == "stable"
        assert trend.slope == 0.0

    def test_mean_calculation(self):
        results = [
            vr.RichnessResult(richness_score=0.2),
            vr.RichnessResult(richness_score=0.4),
            vr.RichnessResult(richness_score=0.6),
        ]
        trend = vr.richness_trend(results)
        assert abs(trend.mean - 0.4) < 0.001

    def test_stddev_calculation(self):
        results = [
            vr.RichnessResult(richness_score=0.5),
            vr.RichnessResult(richness_score=0.5),
        ]
        trend = vr.richness_trend(results)
        assert trend.stddev == 0.0


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

class TestReporting:
    def test_richness_report_format(self):
        result = vr.compute_richness([
            _s(text="the quick brown fox"),
            _s(text="a lazy dog sleeps in the sun"),
        ])
        report = vr.richness_report(result)
        assert "Vocabulary richness:" in report
        assert "samples analysed" in report
        assert "type-token ratio" in report

    def test_richness_report_contains_class(self):
        result = vr.RichnessResult(
            richness_score=0.75,
            richness_class="growing",
            sample_count=3,
        )
        report = vr.richness_report(result)
        assert "growing" in report
        assert "0.75" in report

    def test_trend_report_format(self):
        trend = vr.RichnessTrend(
            scores=[0.4, 0.5, 0.6],
            trend="improving",
            slope=0.1,
            mean=0.5,
            stddev=0.08,
        )
        report = vr.trend_report(trend)
        assert "improving" in report
        assert "windows analysed: 3" in report

    def test_trend_report_empty(self):
        report = vr.trend_report(vr.RichnessTrend())
        assert "No vocabulary richness data" in report


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_single_word_samples(self):
        samples = [_s(text="hello"), _s(text="world")]
        result = vr.compute_richness(samples)
        assert result.total_tokens == 2

    def test_unicode_handled(self):
        # Non-ASCII chars get stripped by regex tokeniser
        samples = [_s(text="café résumé naïve")]
        result = vr.compute_richness(samples)
        assert result.total_tokens > 0

    def test_very_long_text(self):
        # Pure-alpha words avoid digit stripping by the tokeniser
        words = ["alpha" + chr(97 + i % 26) for i in range(500)]
        text = " ".join(words)
        samples = [_s(text=text)]
        result = vr.compute_richness(samples)
        assert result.total_tokens == 500
        assert result.unique_tokens == 26

    def test_window_zero_uses_default(self):
        # window=0 should still work (takes all samples via [-0:] == all)
        samples = [_s(text="hello world")]
        # Python: list[-0:] == list (entire list)
        result = vr.compute_richness(samples, window=0)
        # Should not crash
        assert result.sample_count >= 0

    def test_repeated_punctuation_heavy(self):
        text = "... --- !!! ... --- !!!"
        samples = [_s(text=text) for _ in range(3)]
        result = vr.compute_richness(samples)
        # Punctuation is stripped; "..." and "---" produce no alpha tokens
        # so total_tokens could be 0
        assert result.total_tokens == 0


# ---------------------------------------------------------------------------
# Dataclass defaults
# ---------------------------------------------------------------------------

class TestDataclassDefaults:
    def test_text_sample_defaults(self):
        s = vr.TextSample()
        assert s.label == ""
        assert s.text == ""

    def test_richness_result_defaults(self):
        r = vr.RichnessResult()
        assert r.sample_count == 0
        assert r.richness_class == "stagnant"
        assert r.richness_score == 0.0

    def test_richness_trend_defaults(self):
        t = vr.RichnessTrend()
        assert t.scores == []
        assert t.trend == "unknown"
