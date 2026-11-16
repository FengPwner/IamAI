#!/usr/bin/env python3
"""Tests for writer_discourse_markers module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_discourse_markers import (
    DiscourseMarkerResult,
    measure_discourse_markers,
    _find_word_markers,
    _find_phrase_markers,
    _tokenize,
    _classify,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_discourse_markers("")
        assert r.total_markers == 0
        assert r.classification == "unknown"

    def test_whitespace_only(self):
        r = measure_discourse_markers("   \n\n   ")
        assert r.classification == "unknown"

    def test_no_markers(self):
        r = measure_discourse_markers(
            "The server crashed at midnight. The backup restored data by dawn."
        )
        assert r.total_markers == 0
        assert r.classification == "sparse"

    def test_single_word_no_markers(self):
        r = measure_discourse_markers("Hello.")
        assert r.total_words == 1
        assert r.classification == "sparse"

    def test_punctuation_only(self):
        r = measure_discourse_markers("! @ # $ %")
        assert r.total_markers == 0
        assert r.classification in ("unknown", "sparse")


# ── word marker detection ────────────────────────────────────────


class TestWordMarkerDetection:
    def test_however(self):
        r = measure_discourse_markers("The test passed. However, coverage is low.")
        assert r.total_markers >= 1
        assert "however" in r.marker_counts
        assert r.category_counts.get("adversative", 0) >= 1

    def test_therefore(self):
        r = measure_discourse_markers("The cache is stale. Therefore, we flush it.")
        assert r.total_markers >= 1
        assert "therefore" in r.marker_counts
        assert r.category_counts.get("causal", 0) >= 1

    def test_moreover(self):
        r = measure_discourse_markers("The API is slow. Moreover, it lacks pagination.")
        assert r.total_markers >= 1
        assert "moreover" in r.marker_counts
        assert r.category_counts.get("additive", 0) >= 1

    def test_furthermore(self):
        r = measure_discourse_markers("Furthermore, the logs are rotated weekly.")
        assert r.total_markers >= 1
        assert "furthermore" in r.marker_counts

    def test_consequently(self):
        r = measure_discourse_markers("The disk filled up. Consequently, writes failed.")
        assert r.total_markers >= 1
        assert "consequently" in r.marker_counts

    def test_nevertheless(self):
        r = measure_discourse_markers("Nevertheless, the deployment succeeded.")
        assert r.total_markers >= 1
        assert "nevertheless" in r.marker_counts

    def test_case_insensitive(self):
        r = measure_discourse_markers("HOWEVER it works. Therefore we ship.")
        assert r.total_markers >= 2

    def test_multiple_markers_same_sentence(self):
        r = measure_discourse_markers(
            "However, the fix works and therefore we should merge it."
        )
        assert r.total_markers >= 2


# ── phrase marker detection ─────────────────────────────────────


class TestPhraseMarkerDetection:
    def test_for_example(self):
        r = measure_discourse_markers(
            "We need better tests. For example, the auth module has no coverage."
        )
        assert r.total_markers >= 1
        assert r.category_counts.get("illustrative", 0) >= 1

    def test_in_addition(self):
        r = measure_discourse_markers(
            "The API needs rate limiting. In addition, it needs caching."
        )
        assert r.total_markers >= 1
        assert r.category_counts.get("additive", 0) >= 1

    def test_on_the_other_hand(self):
        r = measure_discourse_markers(
            "Python is readable. On the other hand, Rust is faster."
        )
        assert r.total_markers >= 1
        assert r.category_counts.get("adversative", 0) >= 1

    def test_as_a_result(self):
        r = measure_discourse_markers(
            "The queue backed up. As a result, requests timed out."
        )
        assert r.total_markers >= 1
        assert r.category_counts.get("causal", 0) >= 1

    def test_in_conclusion(self):
        r = measure_discourse_markers(
            "In conclusion, the refactor improved readability by 40%."
        )
        assert r.total_markers >= 1
        assert r.category_counts.get("summative", 0) >= 1

    def test_in_other_words(self):
        r = measure_discourse_markers(
            "The function is pure. In other words, it has no side effects."
        )
        assert r.total_markers >= 1

    def test_to_summarize(self):
        r = measure_discourse_markers(
            "To summarize, we fixed three bugs and added two tests."
        )
        assert r.total_markers >= 1
        assert r.category_counts.get("summative", 0) >= 1

    def test_such_as(self):
        r = measure_discourse_markers(
            "We support several formats such as JSON, YAML, and TOML."
        )
        assert r.total_markers >= 1
        assert r.category_counts.get("illustrative", 0) >= 1

    def test_even_though(self):
        r = measure_discourse_markers(
            "Even though the test is slow, it catches real bugs."
        )
        assert r.total_markers >= 1
        assert r.category_counts.get("adversative", 0) >= 1

    def test_for_instance(self):
        r = measure_discourse_markers(
            "Some databases, for instance PostgreSQL, support JSONB."
        )
        assert r.total_markers >= 1


# ── classification thresholds ────────────────────────────────────


class TestClassification:
    def test_sparse(self):
        # ~200 words, no markers → sparse
        text = " ".join(["word"] * 200)
        r = measure_discourse_markers(text)
        assert r.classification == "sparse"

    def test_lean(self):
        # ~200 words, 1 marker → rate 0.5 → lean
        text = "However " + " ".join(["word"] * 199)
        r = measure_discourse_markers(text)
        assert r.classification == "lean"

    def test_adequate(self):
        # ~200 words, 4 markers → rate 2.0 → adequate
        text = "However moreover therefore consequently " + " ".join(["word"] * 196)
        r = measure_discourse_markers(text)
        assert r.classification == "adequate"

    def test_rich(self):
        # ~100 words, 3 markers → rate 3.0 → rich
        text = "However moreover therefore " + " ".join(["word"] * 97)
        r = measure_discourse_markers(text)
        assert r.classification in ("adequate", "rich")

    def test_over_signposted(self):
        # ~50 words, 4 markers → rate 8.0 → over_signposted
        text = "However moreover therefore consequently furthermore " + " ".join(["word"] * 45)
        r = measure_discourse_markers(text)
        assert r.classification == "over_signposted"

    def test_classify_function_directly(self):
        assert _classify(0.1) == "sparse"
        assert _classify(0.5) == "lean"
        assert _classify(1.5) == "adequate"
        assert _classify(3.0) == "rich"
        assert _classify(5.0) == "over_signposted"


# ── rate calculation ─────────────────────────────────────────────


class TestRateCalculation:
    def test_rate_per_100_words(self):
        # 2 markers in 100 words → rate = 2.0
        words = ["however", "moreover"] + ["word"] * 98
        text = " ".join(words)
        r = measure_discourse_markers(text)
        assert r.total_words == 100
        assert r.total_markers == 2
        assert abs(r.marker_rate - 2.0) < 0.1

    def test_short_text_high_rate(self):
        # 2 markers in 10 words → rate = 20.0
        text = "However therefore word word word word word word word word"
        r = measure_discourse_markers(text)
        assert r.marker_rate > 10.0


# ── category distribution ────────────────────────────────────────


class TestCategoryDistribution:
    def test_all_one_category(self):
        text = "However nevertheless nonetheless conversely whereas"
        text += " word " * 95
        r = measure_discourse_markers(text)
        assert r.category_distribution.get("adversative", 0) > 0.8

    def test_mixed_categories(self):
        text = "However therefore moreover for example in conclusion"
        text += " word " * 95
        r = measure_discourse_markers(text)
        assert len(r.category_counts) >= 3

    def test_distribution_sums_to_one(self):
        text = (
            "However, the data is incomplete. Therefore, we need more samples. "
            "Moreover, the existing samples are biased. For example, the training "
            "set lacks negative cases. In conclusion, we should collect more data."
        )
        r = measure_discourse_markers(text)
        total_dist = sum(r.category_distribution.values())
        assert abs(total_dist - 1.0) < 0.01


# ── top markers ──────────────────────────────────────────────────


class TestTopMarkers:
    def test_top_markers_count(self):
        text = "However however however therefore moreover furthermore consequently"
        text += " word " * 93
        r = measure_discourse_markers(text)
        assert len(r.top_markers) <= 5
        assert r.top_markers[0][0] == "however"
        assert r.top_markers[0][1] == 3

    def test_top_markers_ordered(self):
        text = "Therefore therefore therefore however however moreover"
        text += " word " * 94
        r = measure_discourse_markers(text)
        counts = [count for _, count in r.top_markers]
        assert counts == sorted(counts, reverse=True)


# ── to_dict serialization ───────────────────────────────────────


class TestSerialization:
    def test_to_dict_keys(self):
        r = measure_discourse_markers("However, this works.")
        d = r.to_dict()
        assert "total_markers" in d
        assert "marker_rate" in d
        assert "category_counts" in d
        assert "classification" in d
        assert "top_markers" in d

    def test_to_dict_empty(self):
        r = measure_discourse_markers("")
        d = r.to_dict()
        assert d["classification"] == "unknown"


# ── real-world prose samples ─────────────────────────────────────


class TestRealWorldProse:
    def test_academic_style(self):
        text = (
            "The results demonstrate a significant correlation between sleep "
            "deprivation and cognitive decline in adult populations over the past "
            "decade of controlled studies conducted across multiple research "
            "institutions and clinical settings worldwide. However, the sample size "
            "was small across all reported cohorts and demographic groups. Moreover, "
            "the study did not control for caffeine intake or other dietary "
            "confounders that may influence cognitive performance measurements "
            "taken during the evaluation period. Therefore, further research is "
            "needed to validate these preliminary findings and establish more "
            "robust statistical evidence. In particular, longitudinal studies with "
            "larger populations would provide stronger evidence for the proposed "
            "mechanism underlying the observed correlation. Nevertheless, the "
            "initial findings are suggestive of a real effect that warrants "
            "continued investigation by the broader research community working "
            "on sleep science and cognitive health outcomes in aging populations."
        )
        r = measure_discourse_markers(text)
        assert r.total_markers >= 4
        # 5 markers in ~120+ words → adequate/rich range
        assert r.classification in ("adequate", "rich")

    def test_technical_writing(self):
        text = (
            "The function validates input parameters before processing. First, "
            "it checks that the API key is non-empty. Second, it verifies the "
            "timestamp is within tolerance. Finally, it authenticates the request. "
            "If any check fails, the function raises an appropriate exception."
        )
        r = measure_discourse_markers(text)
        assert r.total_markers >= 3  # first, second, finally

    def test_sparse_prose(self):
        text = (
            "The server crashed. Logs showed a null pointer. We added a guard. "
            "The crash stopped. We deployed to production. Traffic increased. "
            "The server crashed again. We added more guards."
        )
        r = measure_discourse_markers(text)
        assert r.total_markers == 0
        assert r.classification == "sparse"

    def test_over_signposted(self):
        text = (
            "First, we identified the problem. Moreover, we analyzed the root "
            "cause. Furthermore, we proposed three solutions. In addition, we "
            "evaluated trade-offs. However, the timeline was tight. Therefore, "
            "we prioritized the simplest fix. Consequently, we shipped on time. "
            "In conclusion, the project succeeded."
        )
        r = measure_discourse_markers(text)
        assert r.total_markers >= 7
        assert r.classification in ("rich", "over_signposted")
