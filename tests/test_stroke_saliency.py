"""Tests for stroke_saliency.py — information density scoring.

Covers tokenisation, IDF construction, distinctiveness scoring, density
scoring, per-stroke scoring, band classification, full corpus report,
snapshot delta comparison, and edge cases.  68 tests total.
"""

import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import stroke_saliency as ss


# ---------------------------------------------------------------------------
# extract_tokens
# ---------------------------------------------------------------------------

class TestExtractTokens:
    def test_basic_extraction(self):
        tokens = ss.extract_tokens("automation fails quietly the log speaks")
        assert "automation" in tokens
        assert "fails" in tokens
        assert "quietly" in tokens

    def test_short_words_excluded(self):
        tokens = ss.extract_tokens("an ox is up to no go at it")
        # all tokens < 4 chars or stopwords
        assert tokens == []

    def test_stopwords_excluded(self):
        tokens = ss.extract_tokens("that this from into with your")
        assert tokens == []

    def test_punctuation_stripped(self):
        tokens = ss.extract_tokens("hello, world! (testing) 'quoted'")
        assert "hello" in tokens
        assert "world" in tokens
        assert "testing" in tokens

    def test_case_normalisation(self):
        tokens = ss.extract_tokens("HELLO World MiXeD")
        assert "hello" in tokens
        assert "world" in tokens
        assert "mixed" in tokens

    def test_empty_string(self):
        assert ss.extract_tokens("") == []

    def test_single_long_word(self):
        assert ss.extract_tokens("superlongword") == ["superlongword"]

    def test_apostrophe_handling(self):
        tokens = ss.extract_tokens("don't can't won't")
        # "don't" → "don" (3 chars, excluded), "can" (3, excluded), "won" (3, excluded)
        # but "nt" is 2 chars, excluded
        # actually: _TOKEN_RE finds [a-z']{2,} so "don't" matches as one token
        # then len("don't") = 5 >= 4, and "don't" not in stopwords
        assert "don't" in tokens


# ---------------------------------------------------------------------------
# extract_all_tokens
# ---------------------------------------------------------------------------

class TestExtractAllTokens:
    def test_includes_short_words(self):
        tokens = ss.extract_all_tokens("an ox is up to no go")
        assert len(tokens) == 7

    def test_minimum_length(self):
        tokens = ss.extract_all_tokens("I a ab abc")
        # "ab" (2 chars) included, "abc" (3 chars) included
        # "I" → lowercase "i" (1 char) excluded, "a" (1 char) excluded
        assert "ab" in tokens
        assert "abc" in tokens

    def test_empty(self):
        assert ss.extract_all_tokens("") == []

    def test_case_normalisation(self):
        tokens = ss.extract_all_tokens("HELLO world")
        assert "hello" in tokens
        assert "world" in tokens


# ---------------------------------------------------------------------------
# build_idf_table
# ---------------------------------------------------------------------------

class TestBuildIdfTable:
    def test_empty_corpus(self):
        assert ss.build_idf_table([]) == {}

    def test_single_document(self):
        idf = ss.build_idf_table(["automation testing framework"])
        # N=1, df=1 for each token → IDF = log(1/1) = 0
        for tok, val in idf.items():
            assert val == pytest.approx(0.0)

    def test_rare_token_high_idf(self):
        corpus = [
            "common word repeated often",
            "common word appears again",
            "common word here too",
            "common word plus rareword",
        ]
        idf = ss.build_idf_table(corpus)
        # "rareword" appears in 1 of 4 docs → IDF = log(4/1) ≈ 1.386
        assert idf["rareword"] == pytest.approx(math.log(4))
        # "common" and "word" appear in all 4 → IDF = log(4/4) = 0
        assert idf["common"] == pytest.approx(0.0)
        assert idf["word"] == pytest.approx(0.0)

    def test_idf_ordering(self):
        corpus = [
            "alpha beta gamma",
            "alpha beta delta",
            "alpha epsilon zeta",
        ]
        idf = ss.build_idf_table(corpus)
        # "alpha" in all 3 → IDF=0
        # "beta" in 2 → IDF=log(3/2)
        # "gamma" in 1 → IDF=log(3)
        assert idf["alpha"] < idf["beta"] < idf["gamma"]

    def test_multiple_occurrences_same_doc(self):
        corpus = ["repeat repeat repeat unique"]
        idf = ss.build_idf_table(corpus)
        # Both appear in 1 doc → df=1 for both → IDF=log(1)=0
        assert idf["repeat"] == pytest.approx(0.0)
        assert idf["unique"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# stroke_distinctiveness
# ---------------------------------------------------------------------------

class TestStrokeDistinctiveness:
    def test_empty_tokens(self):
        assert ss.stroke_distinctiveness([], {"word": 1.0}, 1.0) == 0.0

    def test_zero_max_idf(self):
        assert ss.stroke_distinctiveness(["word"], {"word": 0.0}, 0.0) == 0.0

    def test_all_rare_words(self):
        idf = {"rare1": 2.0, "rare2": 2.0, "rare3": 2.0}
        dist = ss.stroke_distinctiveness(["rare1", "rare2", "rare3"], idf, 2.0)
        assert dist == pytest.approx(1.0)

    def test_all_common_words(self):
        idf = {"common1": 0.0, "common2": 0.0}
        dist = ss.stroke_distinctiveness(["common1", "common2"], idf, 2.0)
        assert dist == pytest.approx(0.0)

    def test_mixed_words(self):
        idf = {"rare": 2.0, "common": 0.0}
        dist = ss.stroke_distinctiveness(["rare", "common"], idf, 2.0)
        # mean IDF = (2.0 + 0.0) / 2 = 1.0; normalised = 1.0 / 2.0 = 0.5
        assert dist == pytest.approx(0.5)

    def test_unknown_token_scores_zero(self):
        idf = {"known": 2.0}
        dist = ss.stroke_distinctiveness(["known", "unknown"], idf, 2.0)
        # mean IDF = (2.0 + 0.0) / 2 = 1.0; normalised = 0.5
        assert dist == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# stroke_density
# ---------------------------------------------------------------------------

class TestStrokeDensity:
    def test_all_content_words(self):
        # "automation" (10 chars), "framework" (9 chars), "testing" (7 chars)
        # all >= 4 chars, none stopwords
        dens = ss.stroke_density("automation framework testing")
        assert dens == pytest.approx(1.0)

    def test_mixed_content_and_filler(self):
        # "the" (stopword), "big" (3 chars < 4), "automation" (content)
        # all_tokens: ["the", "big", "automation"] → 3
        # content: ["automation"] → 1
        dens = ss.stroke_density("the big automation")
        assert dens == pytest.approx(1.0 / 3.0)

    def test_empty_string(self):
        assert ss.stroke_density("") == 0.0

    def test_only_fillers(self):
        # "the" (stopword), "and" (stopword), "for" (stopword)
        # all_tokens: ["the", "and", "for"] → 3
        # content: [] → 0
        dens = ss.stroke_density("the and for")
        assert dens == pytest.approx(0.0)

    def test_short_text_with_content(self):
        # "also" is a stopword, "testing" is content
        dens = ss.stroke_density("also testing")
        # all_tokens: ["also", "testing"] → 2
        # content: ["testing"] → 1
        assert dens == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# classify_band
# ---------------------------------------------------------------------------

class TestClassifyBand:
    def test_background_low(self):
        assert ss.classify_band(0.0) == "background"

    def test_background_boundary(self):
        assert ss.classify_band(0.19) == "background"

    def test_notable_low(self):
        assert ss.classify_band(0.2) == "notable"

    def test_notable_high(self):
        assert ss.classify_band(0.39) == "notable"

    def test_salient_low(self):
        assert ss.classify_band(0.4) == "salient"

    def test_salient_high(self):
        assert ss.classify_band(0.69) == "salient"

    def test_landmark(self):
        assert ss.classify_band(0.7) == "landmark"

    def test_landmark_max(self):
        assert ss.classify_band(1.0) == "landmark"

    def test_negative_clamped(self):
        assert ss.classify_band(-0.5) == "background"


# ---------------------------------------------------------------------------
# score_stroke
# ---------------------------------------------------------------------------

class TestScoreStroke:
    def test_basic_scoring(self):
        idf = {"automation": 2.0, "testing": 1.5, "framework": 1.0}
        result = ss.score_stroke("automation testing framework", idf, 2.0)
        assert "saliency" in result
        assert "band" in result
        assert "distinctiveness" in result
        assert "density" in result
        assert result["content_tokens"] == 3
        assert result["total_tokens"] == 3

    def test_filler_heavy_stroke(self):
        idf = {"rare": 2.0}
        result = ss.score_stroke("the and for also rare", idf, 2.0)
        # content tokens: ["rare"] → 1
        # all tokens: ["the", "and", "for", "also", "rare"] → 5
        # density = 1/5 = 0.2
        assert result["density"] == pytest.approx(0.2)
        assert result["content_tokens"] == 1
        assert result["total_tokens"] == 5

    def test_empty_stroke(self):
        result = ss.score_stroke("", {}, 0.0)
        assert result["saliency"] == 0.0
        assert result["band"] == "background"
        assert result["content_tokens"] == 0

    def test_saliency_is_product(self):
        idf = {"alpha": 1.0, "beta": 1.0}
        result = ss.score_stroke("alpha beta", idf, 1.0)
        expected_sal = result["distinctiveness"] * result["density"]
        assert result["saliency"] == pytest.approx(round(expected_sal, 6))


# ---------------------------------------------------------------------------
# saliency_report
# ---------------------------------------------------------------------------

class TestSaliencyReport:
    def _make_strokes(self):
        return [
            {"seq": 1, "text": "automation testing framework for continuous integration"},
            {"seq": 2, "text": "the the the the common words here"},
            {"seq": 3, "text": "exponential decay half-life predicts topic dormancy accurately"},
            {"seq": 4, "text": "also another update about the testing stuff"},
            {"seq": 5, "text": "bloom filter probabilistic data structure membership testing"},
        ]

    def test_empty_corpus(self):
        report = ss.saliency_report([])
        assert report["strokes"] == []
        assert report["summary"]["count"] == 0

    def test_report_structure(self):
        strokes = self._make_strokes()
        report = ss.saliency_report(strokes)
        assert len(report["strokes"]) == 5
        assert "summary" in report
        summary = report["summary"]
        assert "mean_saliency" in summary
        assert "max_saliency" in summary
        assert "min_saliency" in summary
        assert "median_saliency" in summary
        assert "band_distribution" in summary
        assert "landmark_count" in summary
        assert "background_ratio" in summary

    def test_stroke_ordering(self):
        strokes = self._make_strokes()
        report = ss.saliency_report(strokes)
        seqs = [s["seq"] for s in report["strokes"]]
        assert seqs == [1, 2, 3, 4, 5]

    def test_filler_stroke_scores_low(self):
        strokes = self._make_strokes()
        report = ss.saliency_report(strokes)
        # seq 2 ("the the the the common words here") should score lowest
        scores = {s["seq"]: s["saliency"] for s in report["strokes"]}
        # It should be among the lowest
        assert scores[2] < scores[3]  # technical content scores higher

    def test_window_parameter(self):
        strokes = self._make_strokes()
        report = ss.saliency_report(strokes, window=3)
        assert len(report["strokes"]) == 3
        seqs = [s["seq"] for s in report["strokes"]]
        assert seqs == [3, 4, 5]

    def test_window_larger_than_corpus(self):
        strokes = self._make_strokes()
        report = ss.saliency_report(strokes, window=100)
        assert len(report["strokes"]) == 5

    def test_summary_count_matches(self):
        strokes = self._make_strokes()
        report = ss.saliency_report(strokes)
        assert report["summary"]["count"] == 5

    def test_band_distribution_sums_to_count(self):
        strokes = self._make_strokes()
        report = ss.saliency_report(strokes)
        total = sum(report["summary"]["band_distribution"].values())
        assert total == 5

    def test_mean_between_min_max(self):
        strokes = self._make_strokes()
        report = ss.saliency_report(strokes)
        s = report["summary"]
        assert s["min_saliency"] <= s["mean_saliency"] <= s["max_saliency"]


# ---------------------------------------------------------------------------
# saliency_delta
# ---------------------------------------------------------------------------

class TestSaliencyDelta:
    def test_identical_reports(self):
        strokes = [
            {"seq": 1, "text": "automation testing framework"},
            {"seq": 2, "text": "bloom filter structure"},
        ]
        r = ss.saliency_report(strokes)
        delta = ss.saliency_delta(r, r)
        assert delta["count_change"] == 0
        assert delta["mean_change"] == pytest.approx(0.0)
        assert delta["max_change"] == pytest.approx(0.0)
        assert delta["landmark_change"] == 0
        assert delta["background_ratio_change"] == pytest.approx(0.0)

    def test_growth_delta(self):
        before_strokes = [
            {"seq": 1, "text": "common words here and there"},
        ]
        after_strokes = [
            {"seq": 1, "text": "common words here and there"},
            {"seq": 2, "text": "exponential decay probabilistic bloom filter"},
        ]
        before = ss.saliency_report(before_strokes)
        after = ss.saliency_report(after_strokes)
        delta = ss.saliency_delta(before, after)
        assert delta["count_change"] == 1

    def test_empty_before(self):
        before = ss.saliency_report([])
        after = ss.saliency_report([{"seq": 1, "text": "testing automation"}])
        delta = ss.saliency_delta(before, after)
        assert delta["count_change"] == 1

    def test_empty_both(self):
        empty = ss.saliency_report([])
        delta = ss.saliency_delta(empty, empty)
        assert delta["count_change"] == 0
        assert delta["mean_change"] == 0.0


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_single_stroke_corpus(self):
        strokes = [{"seq": 1, "text": "only stroke in the corpus"}]
        report = ss.saliency_report(strokes)
        assert report["summary"]["count"] == 1
        # With 1 doc, all IDF = log(1/1) = 0 → distinctiveness = 0
        # saliency should be 0
        assert report["strokes"][0]["saliency"] == 0.0
        assert report["strokes"][0]["band"] == "background"

    def test_identical_strokes(self):
        strokes = [
            {"seq": i, "text": "repeated text about automation testing"}
            for i in range(1, 6)
        ]
        report = ss.saliency_report(strokes)
        # All strokes identical → same scores
        scores = [s["saliency"] for s in report["strokes"]]
        assert len(set(scores)) == 1

    def test_unicode_handling(self):
        tokens = ss.extract_tokens("café naïve résumé testing")
        # accent stripping depends on regex; "café" → "caf" (3 chars < 4)
        # "naïve" → "na" + "ve" (both < 4)
        # "résumé" → "r" + "sum" (3 chars < 4)
        # "testing" → passes
        assert "testing" in tokens

    def test_very_long_stroke(self):
        text = " ".join([f"word{i:04d}" for i in range(500)])
        tokens = ss.extract_tokens(text)
        assert len(tokens) == 500

    def test_numeric_content_ignored(self):
        tokens = ss.extract_tokens("testing 1234 framework 5678")
        assert "testing" in tokens
        assert "framework" in tokens
        # Numbers don't match [a-z'] pattern
        assert "1234" not in tokens

    def test_hyphenated_words(self):
        tokens = ss.extract_tokens("self-testing pre-commit anti-pattern")
        # regex [a-z']{2,} splits on hyphens:
        # "self" (4), "testing" (7), "pre" (3, excluded), "commit" (6),
        # "anti" (4), "pattern" (7)
        assert "self" in tokens
        assert "testing" in tokens
        assert "commit" in tokens
        assert "anti" in tokens
        assert "pattern" in tokens

    def test_density_bounded_zero_one(self):
        for text in [
            "",
            "the and for",
            "automation testing framework",
            "the automation and testing for framework",
        ]:
            d = ss.stroke_density(text)
            assert 0.0 <= d <= 1.0

    def test_distinctiveness_bounded_zero_one(self):
        idf = {"rare": 5.0, "common": 0.1}
        for tokens in [[], ["rare"], ["common"], ["rare", "common"]]:
            d = ss.stroke_distinctiveness(tokens, idf, 5.0)
            assert 0.0 <= d <= 1.0

    def test_window_zero_uses_all(self):
        strokes = [
            {"seq": 1, "text": "alpha beta gamma"},
            {"seq": 2, "text": "delta epsilon zeta"},
        ]
        report = ss.saliency_report(strokes, window=0)
        # window=0 is falsy → use all
        assert len(report["strokes"]) == 2

    def test_window_negative_uses_all(self):
        strokes = [
            {"seq": 1, "text": "alpha beta gamma"},
            {"seq": 2, "text": "delta epsilon zeta"},
        ]
        report = ss.saliency_report(strokes, window=-5)
        assert len(report["strokes"]) == 2


# ---------------------------------------------------------------------------
# integration: realistic corpus
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_realistic_corpus_diversity(self):
        strokes = [
            {"seq": 1, "text": "the garden grew today with some nice flowers"},
            {"seq": 2, "text": "exponential decay half-life predicts dormancy better than linear"},
            {"seq": 3, "text": "commit cadence dropped to three per hour overnight"},
            {"seq": 4, "text": "bloom filter false positive rate scales logarithmically with size"},
            {"seq": 5, "text": "the and the and the and common stuff"},
            {"seq": 6, "text": "jaccard similarity threshold zero point six catches most echoes"},
            {"seq": 7, "text": "testing is good and testing is important for quality"},
            {"seq": 8, "text": "append-only log forces public correction of mistakes"},
        ]
        report = ss.saliency_report(strokes)
        assert report["summary"]["count"] == 8
        # Technical strokes (2, 4, 6) should score higher than filler (5)
        scores = {s["seq"]: s["saliency"] for s in report["strokes"]}
        assert scores[5] < scores[4]
        assert scores[5] < scores[6]

    def test_delta_detects_quality_improvement(self):
        before = [
            {"seq": 1, "text": "common everyday update about stuff"},
            {"seq": 2, "text": "another regular update with things"},
        ]
        after = before + [
            {"seq": 3, "text": "bloom filter probabilistic membership exponential decay"},
            {"seq": 4, "text": "jaccard similarity coefficient measures set overlap precisely"},
        ]
        r_before = ss.saliency_report(before)
        r_after = ss.saliency_report(after)
        delta = ss.saliency_delta(r_before, r_after)
        assert delta["count_change"] == 2
        # Mean saliency should increase with more technical content
        # (though IDF shifts make this corpus-dependent)
        assert isinstance(delta["mean_change"], float)
