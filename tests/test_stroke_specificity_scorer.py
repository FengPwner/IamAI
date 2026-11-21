"""Tests for iamai.stroke_specificity_scorer — specificity scoring and aggregation."""

from __future__ import annotations

import pytest

from iamai.stroke_specificity_scorer import (
    _count_generic_nouns,
    _count_hedge_words,
    _count_matches,
    _count_proper_nouns,
    _NUMERIC_RE,
    _COMMIT_HASH_RE,
    _URL_RE,
    _CODE_REF_RE,
    aggregate,
    score,
)


# ---------------------------------------------------------------------------
# _count_matches — numeric
# ---------------------------------------------------------------------------


class TestNumericDetection:
    def test_plain_integer(self):
        assert _count_matches(_NUMERIC_RE, "there are 42 files") >= 1

    def test_float(self):
        assert _count_matches(_NUMERIC_RE, "version 3.14 released") >= 1

    def test_percentage(self):
        assert _count_matches(_NUMERIC_RE, "coverage at 85%") >= 1

    def test_byte_size(self):
        assert _count_matches(_NUMERIC_RE, "file is 12 MB") >= 1

    def test_date(self):
        assert _count_matches(_NUMERIC_RE, "dated 2026-11-21") >= 1

    def test_time(self):
        assert _count_matches(_NUMERIC_RE, "at 17:02:30 sharp") >= 1

    def test_comma_separated(self):
        assert _count_matches(_NUMERIC_RE, "total 1,234,567 lines") >= 1

    def test_no_numbers(self):
        assert _count_matches(_NUMERIC_RE, "hello world") == 0

    def test_multiple_numbers(self):
        count = _count_matches(_NUMERIC_RE, "7 files changed, 51 insertions, 43 deletions")
        assert count >= 3


# ---------------------------------------------------------------------------
# _count_matches — commit hashes
# ---------------------------------------------------------------------------


class TestCommitHashDetection:
    def test_short_hash(self):
        assert _count_matches(_COMMIT_HASH_RE, "commit 9058c43 pushed") >= 1

    def test_full_hash(self):
        h = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
        assert _count_matches(_COMMIT_HASH_RE, f"commit {h}") >= 1

    def test_no_hash(self):
        assert _count_matches(_COMMIT_HASH_RE, "hello world") == 0


# ---------------------------------------------------------------------------
# _count_matches — URLs
# ---------------------------------------------------------------------------


class TestURLDetection:
    def test_https_url(self):
        assert _count_matches(_URL_RE, "see https://github.com/FengPwner/IamAI") >= 1

    def test_http_url(self):
        assert _count_matches(_URL_RE, "visit http://example.com/page") >= 1

    def test_no_url(self):
        assert _count_matches(_URL_RE, "no links here") == 0


# ---------------------------------------------------------------------------
# _count_matches — code references
# ---------------------------------------------------------------------------


class TestCodeRefDetection:
    def test_backtick_quoted(self):
        assert _count_matches(_CODE_REF_RE, "run `python3 tools/writer_loop.py`") >= 1

    def test_path_like(self):
        assert _count_matches(_CODE_REF_RE, "check tools/writer_loop.py for details") >= 1

    def test_no_code(self):
        assert _count_matches(_CODE_REF_RE, "hello world again") == 0


# ---------------------------------------------------------------------------
# _count_proper_nouns
# ---------------------------------------------------------------------------


class TestProperNouns:
    def test_proper_noun_detected(self):
        count = _count_proper_nouns("FengPwner pushed to GitHub yesterday")
        assert count >= 1  # FengPwner and/or GitHub

    def test_sentence_start_excluded(self):
        # "Hello" starts the sentence, shouldn't count
        count = _count_proper_nouns("Hello from the garden")
        assert count == 0

    def test_exclusion_list(self):
        # "Python" is always capitalised, not a proper noun signal
        count = _count_proper_nouns("Python is great for scripting")
        assert count == 0

    def test_multiple_proper_nouns(self):
        count = _count_proper_nouns("Alice and Bob reviewed FengPwner's commit")
        assert count >= 2


# ---------------------------------------------------------------------------
# _count_hedge_words
# ---------------------------------------------------------------------------


class TestHedgeWords:
    def test_hedge_detected(self):
        assert _count_hedge_words("maybe this is somewhat better") >= 2

    def test_no_hedge(self):
        assert _count_hedge_words("commit 9058c43 added 7 files") == 0

    def test_multiple_hedges(self):
        count = _count_hedge_words("probably roughly maybe approximately correct")
        assert count >= 3


# ---------------------------------------------------------------------------
# _count_generic_nouns
# ---------------------------------------------------------------------------


class TestGenericNouns:
    def test_generic_detected(self):
        assert _count_generic_nouns("there are things and stuff to fix") >= 2

    def test_no_generic(self):
        assert _count_generic_nouns("the writer produces strokes every 15 seconds") == 0

    def test_multiple_generics(self):
        count = _count_generic_nouns("some issues with aspects of the situation")
        assert count >= 2


# ---------------------------------------------------------------------------
# score() — single stroke
# ---------------------------------------------------------------------------


class TestScore:
    def test_highly_specific(self):
        text = "commit 9058c43 pushed 7 files (51 insertions, 43 deletions) to main at 17:02:30"
        result = score(text)
        assert result["specificity_score"] >= 0.30
        assert result["band"] in ("precise", "adequate")
        assert result["indicators"]["numeric_refs"] >= 4
        assert result["indicators"]["citation_like"] >= 1

    def test_vague_stroke(self):
        text = "things are maybe getting somewhat better probably"
        result = score(text)
        assert result["specificity_score"] < 0.30
        assert result["band"] in ("vague", "hand_wavy")
        assert result["indicators"]["hedge_words"] >= 2
        assert result["indicators"]["generic_nouns"] >= 1

    def test_empty_string(self):
        result = score("")
        assert result["specificity_score"] == 0.0
        assert result["band"] == "hand_wavy"

    def test_whitespace_only(self):
        result = score("   \n  ")
        assert result["specificity_score"] == 0.0
        assert result["band"] == "hand_wavy"

    def test_code_reference_boosts_score(self):
        text = "run `tools/run_both.sh --status` to check writer pid and batch pid"
        result = score(text)
        assert result["indicators"]["code_refs"] >= 1

    def test_score_bounded(self):
        # Even with many indicators, score should not exceed 1.0
        text = " ".join([f"commit {i:07x} added {i} files" for i in range(50)])
        result = score(text)
        assert 0.0 <= result["specificity_score"] <= 1.0

    def test_score_non_negative(self):
        # Even with many hedge words, score should not go below 0
        text = "maybe somewhat roughly possibly presumably basically essentially practically"
        result = score(text)
        assert result["specificity_score"] >= 0.0

    def test_band_matches_threshold(self):
        text = "commit 9058c43 added 7 files with 51 insertions to docs/DEVLOG.md at 17:02"
        result = score(text)
        s = result["specificity_score"]
        band = result["band"]
        if s >= 0.55:
            assert band == "precise"
        elif s >= 0.30:
            assert band == "adequate"
        elif s >= 0.15:
            assert band == "vague"
        else:
            assert band == "hand_wavy"

    def test_indicators_dict_keys(self):
        result = score("hello world")
        expected_keys = {
            "numeric_refs",
            "proper_nouns",
            "code_refs",
            "citation_like",
            "hedge_words",
            "generic_nouns",
        }
        assert set(result["indicators"].keys()) == expected_keys

    def test_mixed_content(self):
        text = "Alice reviewed 3 commits on GitHub and found issues with the batch committer"
        result = score(text)
        assert result["indicators"]["numeric_refs"] >= 1
        assert result["indicators"]["proper_nouns"] >= 1
        assert result["specificity_score"] > 0.0


# ---------------------------------------------------------------------------
# aggregate() — series of scored strokes
# ---------------------------------------------------------------------------


class TestAggregate:
    def test_empty_input(self):
        report = aggregate([])
        assert report["mean_specificity"] == 0.0
        assert report["specificity_trend"] == 0.0
        assert report["precise_ratio"] == 0.0

    def test_single_stroke(self):
        results = [score("commit 9058c43 added 7 files")]
        report = aggregate(results)
        assert report["mean_specificity"] == results[0]["specificity_score"]
        assert report["specificity_trend"] == 0.0  # can't compute trend with 1 point

    def test_trend_positive(self):
        # Series going from vague to specific
        texts = [
            "things are somewhat okay",
            "the writer pushed some commits",
            "commit 9058c43 added 7 files to docs/DEVLOG.md at 17:02",
            "commit a1b2c3d pushed 12 files (51 insertions) to main branch at 17:02:30",
        ]
        results = [score(t) for t in texts]
        report = aggregate(results)
        assert report["specificity_trend"] > 0

    def test_trend_negative(self):
        # Series going from specific to vague
        texts = [
            "commit 9058c43 added 7 files to docs/DEVLOG.md at 17:02:30",
            "commit a1b2c3d pushed 12 files to main",
            "the writer pushed some commits",
            "things are somewhat okay maybe",
        ]
        results = [score(t) for t in texts]
        report = aggregate(results)
        assert report["specificity_trend"] < 0

    def test_band_distribution_sums(self):
        texts = [
            "commit 9058c43 added 7 files to docs/DEVLOG.md at 17:02:30",
            "things are maybe getting better",
            "Alice reviewed commits on GitHub",
            "stuff happened probably",
        ]
        results = [score(t) for t in texts]
        report = aggregate(results)
        total_bands = sum(report["band_distribution"].values())
        assert total_bands == len(results)

    def test_precise_ratio(self):
        results = [
            score("commit 9058c43 added 7 files to docs/DEVLOG.md at 17:02:30"),
            score("things are maybe somewhat better"),
        ]
        report = aggregate(results)
        assert 0.0 <= report["precise_ratio"] <= 1.0

    def test_min_max_specificity(self):
        texts = [
            "commit 9058c43 added 7 files to docs/DEVLOG.md at 17:02:30",
            "things are maybe somewhat better probably",
            "Alice reviewed 3 commits on GitHub",
        ]
        results = [score(t) for t in texts]
        report = aggregate(results)
        scores = [r["specificity_score"] for r in results]
        assert report["min_specificity"] == min(scores)
        assert report["max_specificity"] == max(scores)

    def test_median_specificity(self):
        texts = [
            "commit 9058c43 added 7 files",
            "things happened",
            "Alice reviewed commits on GitHub at 17:02",
        ]
        results = [score(t) for t in texts]
        report = aggregate(results)
        scores = sorted(r["specificity_score"] for r in results)
        assert report["median_specificity"] == scores[1]  # middle of 3

    def test_all_bands_present(self):
        report = aggregate([])
        expected_bands = {"precise", "adequate", "vague", "hand_wavy"}
        assert set(report["band_distribution"].keys()) == expected_bands


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_very_short_stroke(self):
        result = score("hi")
        assert 0.0 <= result["specificity_score"] <= 1.0

    def test_stroke_with_only_numbers(self):
        result = score("42 100 3.14 2026-11-21")
        assert result["indicators"]["numeric_refs"] >= 3

    def test_unicode_text(self):
        result = score("提交 commit 9058c43 添加了 7 个文件到 docs/DEVLOG.md")
        assert result["indicators"]["citation_like"] >= 1
        assert result["indicators"]["numeric_refs"] >= 1

    def test_repeated_hedge_words(self):
        text = "maybe maybe maybe maybe maybe"
        result = score(text)
        assert result["indicators"]["hedge_words"] >= 4
        assert result["specificity_score"] < 0.20

    def test_long_specific_stroke(self):
        text = (
            "caretaker visit 768 added stroke_specificity_scorer with 35 tests "
            "at 2026-11-21 17:05 CST, covering numeric detection, proper noun "
            "heuristics, hedge word counting, and aggregation with linear trend. "
            "commit a1b2c3d4 pushed 3 files to iamai/stroke_specificity_scorer.py "
            "and tests/test_stroke_specificity_scorer.py"
        )
        result = score(text)
        assert result["specificity_score"] >= 0.30
        assert result["band"] in ("precise", "adequate")

    def test_score_returns_all_keys(self):
        result = score("hello world")
        assert "specificity_score" in result
        assert "indicators" in result
        assert "band" in result

    def test_aggregate_returns_all_keys(self):
        report = aggregate([score("hello")])
        expected = {
            "mean_specificity",
            "specificity_trend",
            "precise_ratio",
            "band_distribution",
            "median_specificity",
            "min_specificity",
            "max_specificity",
        }
        assert set(report.keys()) == expected
