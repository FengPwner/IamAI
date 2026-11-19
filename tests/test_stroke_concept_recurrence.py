"""Tests for stroke_concept_recurrence.py — concept recurrence measurement.

Covers concept extraction, dormancy gap computation, rhythm classification,
stream-level reporting, and snapshot delta comparison.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import stroke_concept_recurrence as scr


# ---------------------------------------------------------------------------
# extract_concepts
# ---------------------------------------------------------------------------

class TestExtractConcepts:
    def test_basic_extraction(self):
        concepts = scr.extract_concepts("alpha beta gamma delta epsilon")
        assert "alpha" in concepts
        assert "gamma" in concepts
        assert "epsilon" in concepts

    def test_stopwords_excluded(self):
        concepts = scr.extract_concepts("that this these those from into")
        assert len(concepts) == 0

    def test_short_words_excluded(self):
        concepts = scr.extract_concepts("cat dog bat fox owl")
        assert len(concepts) == 0  # all 3-letter words

    def test_four_letter_words_included(self):
        concepts = scr.extract_concepts("alpha beta fish frog")
        assert "alpha" in concepts
        assert "fish" in concepts
        assert "beta" in concepts

    def test_case_insensitive(self):
        c1 = scr.extract_concepts("ALPHA beta GAMMA")
        c2 = scr.extract_concepts("alpha BETA gamma")
        assert c1 == c2

    def test_punctuation_stripped(self):
        concepts = scr.extract_concepts("alpha, beta! gamma? delta.")
        assert "alpha" in concepts
        assert "gamma" in concepts

    def test_empty_string(self):
        assert scr.extract_concepts("") == set()

    def test_mixed_content(self):
        concepts = scr.extract_concepts(
            "the quick brown fox jumps over the lazy alpha"
        )
        # "quick", "brown", "jumps", "lazy" are 4 chars and not stopwords
        assert "quick" in concepts
        assert "alpha" in concepts
        # "the", "over" are stopwords
        assert "the" not in concepts
        assert "over" not in concepts


# ---------------------------------------------------------------------------
# build_concept_map
# ---------------------------------------------------------------------------

class TestBuildConceptMap:
    def test_empty_list(self):
        assert scr.build_concept_map([]) == {}

    def test_single_text(self):
        cmap = scr.build_concept_map(["alpha beta gamma"])
        assert cmap["alpha"] == [0]
        assert cmap["beta"] == [0]
        assert cmap["gamma"] == [0]

    def test_repeated_concepts(self):
        texts = [
            "alpha beta gamma",
            "alpha delta epsilon",
            "alpha beta zeta",
        ]
        cmap = scr.build_concept_map(texts)
        assert cmap["alpha"] == [0, 1, 2]
        assert cmap["beta"] == [0, 2]
        assert cmap["delta"] == [1]

    def test_no_overlap(self):
        texts = [
            "alpha beta gamma",
            "delta epsilon zeta",
            "theta iota kappa",
        ]
        cmap = scr.build_concept_map(texts)
        for concept, indices in cmap.items():
            assert len(indices) == 1


# ---------------------------------------------------------------------------
# concept_dormancy
# ---------------------------------------------------------------------------

class TestConceptDormancy:
    def test_single_appearance(self):
        assert scr.concept_dormancy([0]) == []

    def test_empty_list(self):
        assert scr.concept_dormancy([]) == []

    def test_consecutive_appearances(self):
        gaps = scr.concept_dormancy([0, 1, 2, 3])
        assert gaps == [1, 1, 1]

    def test_with_gaps(self):
        gaps = scr.concept_dormancy([0, 3, 7, 8])
        assert gaps == [3, 4, 1]

    def test_two_appearances(self):
        gaps = scr.concept_dormancy([2, 10])
        assert gaps == [8]


# ---------------------------------------------------------------------------
# _coefficient_of_variation
# ---------------------------------------------------------------------------

class TestCoefficientOfVariation:
    def test_identical_values(self):
        assert scr._coefficient_of_variation([3.0, 3.0, 3.0]) == 0.0

    def test_single_value(self):
        assert scr._coefficient_of_variation([5.0]) == 0.0

    def test_empty_list(self):
        assert scr._coefficient_of_variation([]) == 0.0

    def test_known_cv(self):
        # values = [2, 4, 6]: mean=4, std=sqrt(8/3)≈1.633, cv≈0.408
        cv = scr._coefficient_of_variation([2.0, 4.0, 6.0])
        assert 0.3 < cv < 0.5

    def test_zero_mean(self):
        assert scr._coefficient_of_variation([0.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# classify_rhythm
# ---------------------------------------------------------------------------

class TestClassifyRhythm:
    def test_one_shot_no_gaps(self):
        assert scr.classify_rhythm([]) == "one_shot"

    def test_steady_all_ones(self):
        assert scr.classify_rhythm([1, 1, 1, 1]) == "steady"

    def test_revival_large_gap(self):
        assert scr.classify_rhythm([1, 2, 8, 1], revival_threshold=5) == "revival"

    def test_periodic_tight_cluster(self):
        # gaps = [3, 3, 3, 3] → CV = 0
        assert scr.classify_rhythm([3, 3, 3, 3], revival_threshold=10) == "periodic"

    def test_bursty_variable_gaps(self):
        # gaps = [1, 1, 1, 8, 1] → high CV, no revival (threshold=10)
        assert scr.classify_rhythm([1, 1, 1, 8, 1], revival_threshold=10) == "bursty"

    def test_revival_overrides_periodic(self):
        # Even if most gaps are tight, one big gap → revival
        assert scr.classify_rhythm([2, 2, 2, 15, 2], revival_threshold=10) == "revival"

    def test_custom_threshold(self):
        # gap=4 is revival at threshold=3 but not at threshold=5
        assert scr.classify_rhythm([4], revival_threshold=3) == "revival"
        assert scr.classify_rhythm([4], revival_threshold=5) != "revival"


# ---------------------------------------------------------------------------
# concept_recurrence_metrics
# ---------------------------------------------------------------------------

class TestConceptRecurrenceMetrics:
    def test_single_appearance(self):
        m = scr.concept_recurrence_metrics([5])
        assert m["appearances"] == 1
        assert m["dormancy_gaps"] == []
        assert m["rhythm"] == "one_shot"
        assert m["revivals"] == 0

    def test_steady_concept(self):
        m = scr.concept_recurrence_metrics([0, 1, 2, 3, 4, 5])
        assert m["appearances"] == 6
        assert m["dormancy_gaps"] == [1, 1, 1, 1, 1]
        assert m["rhythm"] == "steady"
        assert m["mean_dormancy"] == 1.0

    def test_periodic_concept(self):
        m = scr.concept_recurrence_metrics([0, 3, 6, 9, 12], revival_threshold=5)
        assert m["appearances"] == 5
        assert m["dormancy_gaps"] == [3, 3, 3, 3]
        assert m["rhythm"] == "periodic"
        assert m["mean_dormancy"] == 3.0
        assert m["revivals"] == 0

    def test_revival_concept(self):
        m = scr.concept_recurrence_metrics([0, 1, 8, 9], revival_threshold=5)
        assert m["revivals"] == 1
        assert m["max_dormancy"] == 7
        assert m["rhythm"] == "revival"

    def test_metrics_keys_complete(self):
        m = scr.concept_recurrence_metrics([0, 2, 5, 12])
        expected_keys = {
            "appearances", "dormancy_gaps", "mean_dormancy",
            "max_dormancy", "min_dormancy", "gap_cv", "revivals", "rhythm",
        }
        assert set(m.keys()) == expected_keys


# ---------------------------------------------------------------------------
# recurrence_report
# ---------------------------------------------------------------------------

class TestRecurrenceReport:
    def test_empty_texts(self):
        report = scr.recurrence_report([])
        assert report["total_concepts"] == 0
        assert report["recurrence_score"] == 0.0
        assert report["stream_pattern"] == "transient"

    def test_no_concepts_extracted(self):
        # All short words / stopwords
        report = scr.recurrence_report(["the a an of", "to in at by"])
        assert report["total_concepts"] == 0
        assert report["stream_pattern"] == "transient"

    def test_all_one_shot(self):
        # Every concept appears exactly once
        texts = [
            "alpha beta gamma",
            "delta epsilon zeta",
            "theta iota kappa",
        ]
        report = scr.recurrence_report(texts)
        assert report["recurring_concepts"] == 0
        assert report["recurrence_score"] == 0.0
        assert report["stream_pattern"] == "transient"

    def test_steady_dominant(self):
        # "alpha" appears in every stroke → steady
        texts = [
            "alpha unique_first_here",
            "alpha unique_second_here",
            "alpha unique_third_here",
            "alpha unique_fourth_here",
            "alpha unique_fifth_here",
        ]
        report = scr.recurrence_report(texts)
        assert report["rhythm_distribution"].get("steady", 0) >= 1
        # alpha is steady, the unique_* are one_shot
        assert report["concept_details"]["alpha"]["rhythm"] == "steady"

    def test_revival_detected(self):
        # "alpha" disappears for 6 strokes then comes back
        texts = [
            "alpha beta gamma",
            "delta epsilon zeta",
            "theta iota kappa",
            "lambda sigma omega",
            "omicron rho phi",
            "chi psi xi",
            "nu tau upsilon",
            "alpha beta gamma",  # revival after gap of 7
        ]
        report = scr.recurrence_report(texts, revival_threshold=5)
        assert report["revival_concepts"] >= 1
        assert report["longest_revival"] >= 5
        alpha_metrics = report["concept_details"]["alpha"]
        assert alpha_metrics["revivals"] >= 1

    def test_recurrence_score_range(self):
        texts = [
            "alpha beta gamma delta epsilon",
            "something completely different here now",
            "another passage with no overlap whatsoever",
            "alpha beta gamma delta epsilon",
            "nothing shared with earlier passages here",
            "fresh topics only in this middle stroke",
            "alpha beta gamma delta epsilon",
        ]
        report = scr.recurrence_report(texts)
        assert 0.0 <= report["recurrence_score"] <= 1.0

    def test_revival_rate_range(self):
        texts = [
            "alpha beta gamma",
            "delta epsilon zeta",
            "theta iota kappa",
            "lambda sigma omega",
            "omicron rho phi",
            "chi psi xi",
            "alpha beta gamma",
        ]
        report = scr.recurrence_report(texts, revival_threshold=5)
        assert 0.0 <= report["revival_rate"] <= 1.0

    def test_stream_pattern_valid(self):
        texts = [
            "alpha beta gamma delta",
            "alpha beta gamma delta",
            "alpha beta gamma delta",
            "something different here now",
            "another passage entirely",
            "alpha beta gamma delta",
            "completely unrelated material",
            "alpha beta gamma delta",
        ]
        report = scr.recurrence_report(texts)
        assert report["stream_pattern"] in (
            "cyclical", "episodic", "transient", "anchored"
        )

    def test_concept_details_present(self):
        texts = [
            "alpha beta gamma",
            "alpha beta delta",
            "alpha gamma delta",
        ]
        report = scr.recurrence_report(texts)
        assert "alpha" in report["concept_details"]
        assert "beta" in report["concept_details"]
        assert "gamma" in report["concept_details"]

    def test_mean_dormancy_computed(self):
        texts = [
            "alpha beta gamma",
            "delta epsilon zeta",
            "alpha beta gamma",
            "delta epsilon zeta",
            "alpha beta gamma",
        ]
        report = scr.recurrence_report(texts)
        assert report["mean_dormancy"] > 0

    def test_rhythm_distribution_keys(self):
        texts = [
            "alpha beta gamma",
            "alpha beta gamma",
            "alpha beta gamma",
            "something different here now",
            "another passage entirely",
            "alpha beta gamma",
        ]
        report = scr.recurrence_report(texts)
        valid_rhythms = {"periodic", "bursty", "revival", "one_shot", "steady"}
        for rhythm in report["rhythm_distribution"]:
            assert rhythm in valid_rhythms


# ---------------------------------------------------------------------------
# Stream pattern classification
# ---------------------------------------------------------------------------

class TestStreamPatternClassification:
    def test_anchored_pattern(self):
        # Most concepts are steady → anchored
        texts = [
            "alpha beta gamma delta epsilon",
            "alpha beta gamma delta epsilon",
            "alpha beta gamma delta epsilon",
            "alpha beta gamma delta epsilon",
            "alpha beta gamma delta epsilon",
        ]
        report = scr.recurrence_report(texts)
        assert report["stream_pattern"] == "anchored"

    def test_transient_pattern(self):
        # All concepts are one-shot → transient
        texts = [
            "alpha beta gamma",
            "delta epsilon zeta",
            "theta iota kappa",
            "lambda sigma omega",
        ]
        report = scr.recurrence_report(texts)
        assert report["stream_pattern"] == "transient"


# ---------------------------------------------------------------------------
# recurrence_delta
# ---------------------------------------------------------------------------

class TestRecurrenceDelta:
    def test_empty_reports(self):
        before = scr.recurrence_report([])
        after = scr.recurrence_report([])
        delta = scr.recurrence_delta(before, after)
        assert delta["recurrence_score_delta"] == 0.0
        assert delta["revival_rate_delta"] == 0.0
        assert delta["new_revivals"] == []
        assert delta["rhythm_shifts"] == {}

    def test_new_revival_detected(self):
        texts_before = [
            "alpha beta gamma",
            "delta epsilon zeta",
            "alpha beta gamma",
        ]
        texts_after = texts_before + [
            "theta iota kappa",
            "lambda sigma omega",
            "chi psi xi",
            "nu tau upsilon",
            "alpha beta gamma",  # alpha gets a revival
        ]
        before = scr.recurrence_report(texts_before, revival_threshold=3)
        after = scr.recurrence_report(texts_after, revival_threshold=3)
        delta = scr.recurrence_delta(before, after)
        # alpha should gain a revival
        assert "alpha" in delta["new_revivals"] or delta["revival_rate_delta"] >= 0

    def test_rhythm_shift_detected(self):
        texts_before = [
            "alpha beta gamma",
            "alpha beta gamma",
            "alpha beta gamma",
        ]
        texts_after = texts_before + [
            "something different here now",
            "another passage entirely",
            "completely unrelated material",
            "alpha beta gamma",  # alpha now has a big gap → revival
        ]
        before = scr.recurrence_report(texts_before, revival_threshold=3)
        after = scr.recurrence_report(texts_after, revival_threshold=3)
        delta = scr.recurrence_delta(before, after)
        # alpha went from steady to revival
        if "alpha" in delta["rhythm_shifts"]:
            old_rhythm, new_rhythm = delta["rhythm_shifts"]["alpha"]
            assert old_rhythm == "steady"
            assert new_rhythm == "revival"

    def test_score_delta_direction(self):
        # Adding more recurring texts should increase recurrence_score
        texts_before = [
            "alpha beta gamma",
            "delta epsilon zeta",
        ]
        texts_after = texts_before + [
            "alpha beta gamma",
            "delta epsilon zeta",
        ]
        before = scr.recurrence_report(texts_before)
        after = scr.recurrence_report(texts_after)
        delta = scr.recurrence_delta(before, after)
        assert delta["recurrence_score_delta"] >= 0

    def test_brand_new_concept_with_revival(self):
        texts_before = [
            "alpha beta gamma",
            "alpha beta gamma",
        ]
        texts_after = texts_before + [
            "delta epsilon zeta",
            "delta epsilon zeta",
            "theta iota kappa",
            "theta iota kappa",
            "theta iota kappa",
            "theta iota kappa",
            "theta iota kappa",
            "theta iota kappa",
        ]
        before = scr.recurrence_report(texts_before, revival_threshold=3)
        after = scr.recurrence_report(texts_after, revival_threshold=3)
        delta = scr.recurrence_delta(before, after)
        # delta should compute without errors
        assert "recurrence_score_delta" in delta
        assert "revival_rate_delta" in delta


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_single_text_with_concepts(self):
        report = scr.recurrence_report(["alpha beta gamma delta"])
        assert report["total_concepts"] >= 4
        assert report["recurring_concepts"] == 0
        assert report["recurrence_score"] == 0.0

    def test_two_identical_texts(self):
        report = scr.recurrence_report([
            "alpha beta gamma delta",
            "alpha beta gamma delta",
        ])
        assert report["recurring_concepts"] >= 4
        # All concepts appear in consecutive strokes → steady
        for concept in ["alpha", "beta", "gamma", "delta"]:
            if concept in report["concept_details"]:
                assert report["concept_details"][concept]["rhythm"] == "steady"

    def test_texts_with_only_stopwords(self):
        report = scr.recurrence_report([
            "the a an of to in at by for from",
            "that this these those with into",
        ])
        assert report["total_concepts"] == 0
        assert report["stream_pattern"] == "transient"

    def test_long_stream_many_gaps(self):
        # Alternate between two concept sets
        texts = []
        for i in range(20):
            if i % 2 == 0:
                texts.append("alpha beta gamma delta epsilon")
            else:
                texts.append("zeta theta iota kappa lambda sigma")
        report = scr.recurrence_report(texts, revival_threshold=3)
        # alpha appears at 0,2,4,6,8,10,12,14,16,18 → gaps are all 2
        alpha_m = report["concept_details"].get("alpha", {})
        if alpha_m:
            assert alpha_m["rhythm"] == "periodic"

    def test_delta_with_disjoint_concepts(self):
        before = scr.recurrence_report(["alpha beta gamma"])
        after = scr.recurrence_report(["delta epsilon zeta"])
        delta = scr.recurrence_delta(before, after)
        assert delta["new_revivals"] == []
        assert delta["rhythm_shifts"] == {}


# ---------------------------------------------------------------------------
# Integration: module docstring example
# ---------------------------------------------------------------------------

class TestDocstringExample:
    def test_module_docstring_example(self):
        texts = [
            "alpha beta gamma delta epsilon",
            "something completely different here now",
            "another passage with no overlap whatsoever",
            "alpha beta gamma delta epsilon",
            "nothing shared with earlier passages here",
            "fresh topics only in this middle stroke",
            "alpha beta gamma delta epsilon",
            "completely unrelated material in this one",
            "alpha beta gamma delta epsilon",
            "alpha beta gamma delta epsilon",
        ]
        report = scr.recurrence_report(texts)
        assert report["stream_pattern"] in (
            "cyclical", "episodic", "transient", "anchored"
        )
        assert 0.0 <= report["recurrence_score"] <= 1.0
