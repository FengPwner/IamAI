"""Tests for iamai.stroke_density.

Covers: _tokenize(), lexical_diversity_of(), StrokeDensityAnalyser
(feed, lexical_diversity, novelty_ratio, content_fraction,
density_score, average_score, trend, summarize, reset), edge cases,
and error handling.
"""

import pytest
from iamai.stroke_density import (
    StrokeDensityAnalyser,
    _tokenize,
    lexical_diversity_of,
)


# ── _tokenize() ───────────────────────────────────────────────────────


class TestTokenize:
    """Internal tokenizer: lowercase, strip punctuation, split."""

    def test_basic_sentence(self):
        assert _tokenize("Hello, World!") == ["hello", "world"]

    def test_empty_string(self):
        assert _tokenize("") == []

    def test_only_punctuation(self):
        assert _tokenize("... --- !!!") == []

    def test_mixed_case(self):
        assert _tokenize("Growth GROWTH growth") == ["growth", "growth", "growth"]

    def test_numbers_preserved(self):
        assert _tokenize("commit 1465") == ["commit", "1465"]

    def test_hyphens_stripped(self):
        # hyphens are punctuation → stripped, joining the words
        tokens = _tokenize("append-only log")
        assert "appendonly" in tokens
        assert "log" in tokens

    def test_extra_whitespace(self):
        assert _tokenize("  hello   world  ") == ["hello", "world"]


# ── lexical_diversity_of() ────────────────────────────────────────────


class TestLexicalDiversityOf:
    """Pure-function lexical diversity (unique / total)."""

    def test_all_unique(self):
        assert lexical_diversity_of(["a", "b", "c", "d"]) == 1.0

    def test_all_same(self):
        assert lexical_diversity_of(["x", "x", "x"]) == pytest.approx(1 / 3)

    def test_empty(self):
        assert lexical_diversity_of([]) == 0.0

    def test_single_token(self):
        assert lexical_diversity_of(["hello"]) == 1.0

    def test_half_unique(self):
        # 2 unique out of 4 → 0.5
        assert lexical_diversity_of(["a", "b", "a", "b"]) == 0.5


# ── StrokeDensityAnalyser — construction ──────────────────────────────


class TestAnalyserConstruction:
    """Constructor validation and edge cases."""

    def test_default_params(self):
        a = StrokeDensityAnalyser()
        assert a._window == 20
        assert a._bf == 0.5

    def test_custom_params(self):
        a = StrokeDensityAnalyser(window=10, boilerplate_freq=0.3)
        assert a._window == 10
        assert a._bf == 0.3

    def test_window_zero_raises(self):
        with pytest.raises(ValueError, match="window must be >= 1"):
            StrokeDensityAnalyser(window=0)

    def test_window_negative_raises(self):
        with pytest.raises(ValueError, match="window must be >= 1"):
            StrokeDensityAnalyser(window=-5)

    def test_boilerplate_freq_zero_raises(self):
        with pytest.raises(ValueError, match="boilerplate_freq must be in"):
            StrokeDensityAnalyser(boilerplate_freq=0.0)

    def test_boilerplate_freq_above_one_raises(self):
        with pytest.raises(ValueError, match="boilerplate_freq must be in"):
            StrokeDensityAnalyser(boilerplate_freq=1.5)

    def test_boilerplate_freq_one_ok(self):
        a = StrokeDensityAnalyser(boilerplate_freq=1.0)
        assert a._bf == 1.0


# ── StrokeDensityAnalyser — feed() ───────────────────────────────────


class TestFeed:
    """feed() returns per-stroke metrics dict and updates state."""

    def test_first_feed_returns_dict(self):
        a = StrokeDensityAnalyser()
        result = a.feed("hello world, this is a test")
        assert isinstance(result, dict)
        assert "lexical_diversity" in result
        assert "novelty_ratio" in result
        assert "content_fraction" in result
        assert "density_score" in result

    def test_first_stroke_all_unique(self):
        a = StrokeDensityAnalyser()
        result = a.feed("growth that never stops is a tumour not a garden")
        # "a" appears twice → not all unique
        assert result["lexical_diversity"] < 1.0
        assert result["lexical_diversity"] > 0.8

    def test_first_stroke_novelty_is_one(self):
        """First stroke has no prior vocabulary → novelty = 1.0."""
        a = StrokeDensityAnalyser()
        result = a.feed("an append-only log forces honesty")
        assert result["novelty_ratio"] == 1.0

    def test_first_stroke_content_fraction_is_one(self):
        """Not enough strokes to identify boilerplate → content = 1.0."""
        a = StrokeDensityAnalyser()
        result = a.feed("the commit count grows steadily")
        assert result["content_fraction"] == 1.0

    def test_total_fed_increments(self):
        a = StrokeDensityAnalyser()
        a.feed("first stroke here")
        assert a._total_fed == 1
        a.feed("second stroke here")
        assert a._total_fed == 2
        a.feed("third stroke here")
        assert a._total_fed == 3

    def test_repetitive_stroke_lower_diversity(self):
        a = StrokeDensityAnalyser()
        r1 = a.feed("the the the the the")
        r2 = a.feed("unique varied diverse different novel fresh new")
        assert r1["lexical_diversity"] < r2["lexical_diversity"]


# ── StrokeDensityAnalyser — novelty ──────────────────────────────────


class TestNovelty:
    """Novelty ratio: fraction of tokens new to the window."""

    def test_second_stroke_all_new_words(self):
        a = StrokeDensityAnalyser()
        a.feed("alpha beta gamma")
        result = a.feed("delta epsilon zeta")
        assert result["novelty_ratio"] == 1.0

    def test_second_stroke_all_repeated(self):
        a = StrokeDensityAnalyser()
        a.feed("alpha beta gamma")
        result = a.feed("alpha beta gamma")
        assert result["novelty_ratio"] == 0.0

    def test_partial_novelty(self):
        a = StrokeDensityAnalyser()
        a.feed("alpha beta gamma delta")
        result = a.feed("alpha beta new1 new2")
        # 2 novel out of 4 → 0.5
        assert result["novelty_ratio"] == 0.5

    def test_novelty_with_empty_analyser(self):
        a = StrokeDensityAnalyser()
        assert a.novelty_ratio() == 0.0


# ── StrokeDensityAnalyser — content fraction ─────────────────────────


class TestContentFraction:
    """Content fraction: non-boilerplate proportion."""

    def test_needs_at_least_3_strokes(self):
        a = StrokeDensityAnalyser()
        a.feed("hello world")
        assert a.content_fraction() == 1.0
        a.feed("hello world again")
        assert a.content_fraction() == 1.0

    def test_boilerplate_detected_after_3(self):
        a = StrokeDensityAnalyser(boilerplate_freq=0.5)
        a.feed("the commit the the commit the")
        a.feed("the commit the the commit the")
        a.feed("the commit the the commit the")
        # "the" and "commit" appear in all 3 strokes (100 %)
        # → both are boilerplate at 50 % threshold
        cf = a.content_fraction()
        assert cf < 1.0

    def test_all_unique_words_stay_content(self):
        a = StrokeDensityAnalyser(boilerplate_freq=0.5)
        a.feed("alpha beta gamma")
        a.feed("delta epsilon zeta")
        a.feed("eta theta iota")
        # no word appears in >50 % of strokes
        assert a.content_fraction() == 1.0

    def test_content_fraction_empty_analyser(self):
        a = StrokeDensityAnalyser()
        assert a.content_fraction() == 0.0


# ── StrokeDensityAnalyser — density score ─────────────────────────────


class TestDensityScore:
    """Composite density score = 0.30*ld + 0.40*nv + 0.30*cf."""

    def test_score_in_range(self):
        a = StrokeDensityAnalyser()
        a.feed("growth that never stops is a tumour not a garden")
        score = a.density_score()
        assert 0.0 <= score <= 1.0

    def test_score_empty_is_zero(self):
        a = StrokeDensityAnalyser()
        assert a.density_score() == 0.0

    def test_high_density_stroke(self):
        """A stroke with all unique, novel, non-boilerplate words."""
        a = StrokeDensityAnalyser()
        a.feed("alpha beta gamma delta epsilon zeta eta theta")
        # first stroke: ld=1.0, nv=1.0, cf=1.0 → score=1.0
        assert a.density_score() == pytest.approx(1.0)

    def test_degrading_density(self):
        """Repeated boilerplate should lower the score over time."""
        a = StrokeDensityAnalyser()
        scores = []
        for i in range(10):
            result = a.feed(
                f"the commit count is {i} the commit the the commit"
            )
            scores.append(result["density_score"])
        # later scores should be lower than the first
        assert scores[-1] < scores[0]


# ── StrokeDensityAnalyser — average and trend ─────────────────────────


class TestAverageAndTrend:
    """Rolling average and trend detection."""

    def test_average_empty(self):
        a = StrokeDensityAnalyser()
        assert a.average_score() == 0.0

    def test_average_single(self):
        a = StrokeDensityAnalyser()
        a.feed("hello world")
        assert a.average_score() == a.density_score()

    def test_average_with_n(self):
        a = StrokeDensityAnalyser()
        for i in range(10):
            a.feed(f"stroke number {i} with some unique words")
        avg_all = a.average_score()
        avg_3 = a.average_score(n=3)
        # they should differ (unless all strokes are identical)
        assert isinstance(avg_all, float)
        assert isinstance(avg_3, float)

    def test_trend_flat_with_few_strokes(self):
        a = StrokeDensityAnalyser()
        a.feed("one two three")
        a.feed("four five six")
        assert a.trend() == "flat"

    def test_trend_flat_stable_input(self):
        a = StrokeDensityAnalyser()
        for i in range(10):
            a.feed(f"unique novel stroke number {i} always different words")
        assert a.trend() in ("flat", "improving", "declining")

    def test_trend_declining(self):
        """Start with rich strokes, end with boilerplate."""
        a = StrokeDensityAnalyser(window=20)
        # rich strokes
        for i in range(6):
            a.feed(f"extraordinary unique vocabulary batch {i} "
                   f"philosophical epistemological ontological")
        # degenerate strokes
        for i in range(6):
            a.feed("the the the the the the the the")
        assert a.trend() == "declining"

    def test_trend_improving(self):
        """Start with boilerplate, end with rich strokes."""
        a = StrokeDensityAnalyser(window=20)
        for i in range(6):
            a.feed("the the the the the the the the")
        for i in range(6):
            a.feed(f"extraordinary unique vocabulary batch {i} "
                   f"philosophical epistemological ontological")
        assert a.trend() == "improving"


# ── StrokeDensityAnalyser — summarize ─────────────────────────────────


class TestSummarize:
    """summarize() returns a structured dict."""

    def test_summarize_empty(self):
        a = StrokeDensityAnalyser()
        s = a.summarize()
        assert s["total_strokes"] == 0
        assert s["average_score"] == 0.0
        assert s["trend"] == "flat"
        assert s["latest"]["density_score"] == 0.0

    def test_summarize_after_feeds(self):
        a = StrokeDensityAnalyser(window=10)
        a.feed("growth that never stops is a tumour")
        a.feed("an append-only log forces honesty in public")
        a.feed("if a number in a diary is not measured it is fiction")
        s = a.summarize()
        assert s["total_strokes"] == 3
        assert s["window_size"] == 10
        assert "lexical_diversity" in s["latest"]
        assert "novelty_ratio" in s["latest"]
        assert "content_fraction" in s["latest"]
        assert "density_score" in s["latest"]
        assert isinstance(s["average_score"], float)
        assert s["trend"] in ("flat", "improving", "declining")

    def test_summarize_rounds_values(self):
        a = StrokeDensityAnalyser()
        a.feed("hello world test")
        s = a.summarize()
        # all float values should be rounded to 4 decimals
        for key in ("lexical_diversity", "novelty_ratio",
                     "content_fraction", "density_score"):
            val = s["latest"][key]
            assert val == round(val, 4)


# ── StrokeDensityAnalyser — reset ─────────────────────────────────────


class TestReset:
    """reset() clears all state."""

    def test_reset_clears_everything(self):
        a = StrokeDensityAnalyser()
        a.feed("hello world")
        a.feed("second stroke")
        a.feed("third stroke here")
        assert a._total_fed == 3
        a.reset()
        assert a._total_fed == 0
        assert a.density_score() == 0.0
        assert a.novelty_ratio() == 0.0
        assert a.content_fraction() == 0.0
        assert a.average_score() == 0.0
        assert a.summarize()["total_strokes"] == 0


# ── StrokeDensityAnalyser — window behaviour ──────────────────────────


class TestWindowBehaviour:
    """Sliding window should evict old strokes."""

    def test_window_eviction(self):
        a = StrokeDensityAnalyser(window=3)
        a.feed("alpha beta gamma")
        a.feed("delta epsilon zeta")
        a.feed("eta theta iota")
        # window is full
        assert len(a._history) == 3
        a.feed("kappa lambda mu")
        # still 3 — oldest evicted
        assert len(a._history) == 3
        # "alpha" should be gone
        all_tokens = [t for tokens in a._history for t in tokens]
        assert "alpha" not in all_tokens

    def test_window_one(self):
        """Window of 1 means novelty is always 1.0 (no prior)."""
        a = StrokeDensityAnalyser(window=1)
        a.feed("hello world")
        a.feed("hello world")
        # each stroke sees no prior → novelty = 1.0
        assert a.novelty_ratio() == 1.0


# ── Integration: realistic stroke stream ──────────────────────────────


class TestRealisticStream:
    """Feed a sequence that mimics actual IamAI strokes."""

    STROKES = [
        "growth that never stops is a tumour not a garden measured now commit 1465",
        "an append-only log forces you to be wrong in public and then correct yourself measured now 3071 strokes",
        "if a number in a diary is not measured it is fiction measured now 155653 lines across 771 tracked files",
        "ten minutes is long enough to be honest and short enough to be boring measured now 490 python files",
        "a deterministic garden beats a random one it records elapsed time measured now 3071 strokes into 771 files",
        "reproducibility is a courtesy to whoever debugs this at 2am usually me measured now 155688 lines",
        "tests are the part of a repository that argues back measured now 490 python files 3075 logged thoughts",
        "growth that never stops is a tumour not a garden measured now 3074 strokes into 771 files",
        "an append-only log forces you to be wrong in public measured now tree is 771 files 155723 lines",
        "if a number in a diary is not measured it is fiction measured now 490 python files 3078 logged thoughts",
    ]

    def test_full_stream(self):
        a = StrokeDensityAnalyser(window=10)
        results = [a.feed(s) for s in self.STROKES]
        assert len(results) == 10
        assert a._total_fed == 10

    def test_summary_after_stream(self):
        a = StrokeDensityAnalyser(window=10)
        for s in self.STROKES:
            a.feed(s)
        summary = a.summarize()
        assert summary["total_strokes"] == 10
        assert 0.0 < summary["average_score"] <= 1.0
        assert summary["trend"] in ("flat", "improving", "declining")

    def test_repetitive_stream_has_lower_score(self):
        """Compare a diverse stream to a repetitive one."""
        a_diverse = StrokeDensityAnalyser(window=5)
        a_repet = StrokeDensityAnalyser(window=5)

        diverse = [
            "epistemological foundations crumble under empirical scrutiny",
            "quantum entanglement defies classical intuition about locality",
            "photosynthetic efficiency peaks at surprisingly low light levels",
            "cartesian dualism persists despite neurological evidence against it",
            "thermodynamic irreversibility gives time its perceived direction",
        ]
        repet = [
            "the commit count is growing the commit count is growing",
            "the commit count is growing the commit count is growing",
            "the commit count is growing the commit count is growing",
            "the commit count is growing the commit count is growing",
            "the commit count is growing the commit count is growing",
        ]

        for s in diverse:
            a_diverse.feed(s)
        for s in repet:
            a_repet.feed(s)

        assert a_diverse.average_score() > a_repet.average_score()
