#!/usr/bin/env python3
"""Tests for writer_gradation_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_gradation_density import (
    GradationDensityResult,
    measure_gradation_density,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_gradation_density("")
        assert r.gradation_density_index == 0.0
        assert r.classification == "flat"

    def test_whitespace_only(self):
        r = measure_gradation_density("   \n\n   ")
        assert r.gradation_density_index == 0.0

    def test_none_like_empty(self):
        r = measure_gradation_density("")
        assert r.total_sentences == 0 or r.total_sentences == 1

    def test_single_word(self):
        r = measure_gradation_density("Hello.")
        assert r.gradation_density_index == 0.0
        assert r.classification == "flat"


# ── flat prose (minimal gradation language) ─────────────────────


class TestFlatProse:
    PLAIN = (
        "The committee approved the proposal. "
        "The vote was unanimous. "
        "Implementation begins next month. "
        "The budget covers all departments. "
        "Staff will receive training materials."
    )

    def test_flat_classification(self):
        r = measure_gradation_density(self.PLAIN)
        assert r.classification in ("flat", "lightly_gradated")
        assert r.gradation_density_index < 0.15

    def test_low_gradation_counts(self):
        r = measure_gradation_density(self.PLAIN)
        assert r.superlative_count == 0
        assert r.intensifier_count == 0
        assert r.diminisher_count == 0
        assert r.equative_count == 0
        assert r.sufficiency_excess_count == 0

    def test_comparative_count_low(self):
        r = measure_gradation_density(self.PLAIN)
        assert r.comparative_count <= 1


# ── heavily gradated prose ──────────────────────────────────────


class TestHeavilyGradatedProse:
    REVIEW = (
        "This is by far the most extraordinary novel I have ever read. "
        "The prose is remarkably elegant, deeply moving, and incredibly precise. "
        "Each chapter is more compelling than the last, building to an utterly devastating climax. "
        "The characters are richer and more complex than in any of her earlier work. "
        "The pacing is somewhat uneven in the middle, but the ending is absolutely perfect. "
        "It is substantially better than her previous book, though not quite as good as her debut. "
        "The dialogue is exceptionally natural, almost painfully realistic. "
        "I would say it is among the greatest novels of the decade."
    )

    def test_high_gradation_index(self):
        r = measure_gradation_density(self.REVIEW)
        assert r.gradation_density_index >= 0.25
        assert r.classification in (
            "moderately_gradated",
            "heavily_gradated",
            "gradation_saturated",
        )

    def test_intensifiers_present(self):
        r = measure_gradation_density(self.REVIEW)
        assert r.intensifier_count >= 4

    def test_superlatives_present(self):
        r = measure_gradation_density(self.REVIEW)
        assert r.superlative_count >= 2

    def test_comparatives_present(self):
        r = measure_gradation_density(self.REVIEW)
        assert r.comparative_count >= 2

    def test_diminishers_present(self):
        r = measure_gradation_density(self.REVIEW)
        assert r.diminisher_count >= 1


# ── comparative-heavy prose ─────────────────────────────────────


class TestComparativeHeavy:
    COMPARISON = (
        "The new model is faster than the old one. "
        "It uses less memory and produces better results. "
        "The larger dataset yields higher accuracy than the smaller sample. "
        "Training is easier than before but harder than with the simplified API. "
        "Performance is stronger overall, though latency is slightly worse than expected."
    )

    def test_comparative_rate_high(self):
        r = measure_gradation_density(self.COMPARISON)
        assert r.comparative_rate >= 50.0

    def test_classification_gradated(self):
        r = measure_gradation_density(self.COMPARISON)
        assert r.classification != "flat"
        assert r.gradation_density_index > 0.10


# ── intensifier-heavy prose ─────────────────────────────────────


class TestIntensifierHeavy:
    INTENSE = (
        "The presentation was extremely well received. "
        "The audience was deeply engaged and thoroughly convinced. "
        "The data was remarkably clear and utterly compelling. "
        "The results were extraordinarily significant and profoundly impactful. "
        "Everyone was absolutely delighted and completely satisfied."
    )

    def test_intensifier_rate_high(self):
        r = measure_gradation_density(self.INTENSE)
        assert r.intensifier_rate >= 100.0

    def test_unique_forms_present(self):
        r = measure_gradation_density(self.INTENSE)
        assert r.unique_gradation_forms >= 5


# ── diminisher-heavy prose ──────────────────────────────────────


class TestDiminisherHeavy:
    SOFT = (
        "The results are somewhat encouraging, though only marginally significant. "
        "Performance improved slightly, but the gains are barely noticeable. "
        "The approach is fairly conventional and rather unremarkable. "
        "It is mildly interesting and moderately useful. "
        "The changes are passably adequate but hardly transformative."
    )

    def test_diminisher_rate_high(self):
        r = measure_gradation_density(self.SOFT)
        assert r.diminisher_rate >= 60.0

    def test_classification_not_flat(self):
        r = measure_gradation_density(self.SOFT)
        assert r.classification != "flat"


# ── equative constructions ──────────────────────────────────────


class TestEquativeConstructions:
    EQUATIVE = (
        "The new algorithm is as fast as the previous version. "
        "Accuracy is equally important as speed in this context. "
        "The results are just as reliable as the benchmark data. "
        "This approach is every bit as effective as the traditional method. "
        "The output quality is on a par with the gold standard."
    )

    def test_equative_rate_present(self):
        r = measure_gradation_density(self.EQUATIVE)
        assert r.equative_count >= 3
        assert r.equative_rate > 0.0


# ── approximative adverbs ───────────────────────────────────────


class TestApproximativeAdverbs:
    APPROX = (
        "The system is almost ready for deployment. "
        "We are nearly finished with the migration. "
        "The results are practically identical to the baseline. "
        "Performance is virtually unchanged from the previous release. "
        "The prototype is essentially complete, roughly meeting all specifications."
    )

    def test_approximative_rate_present(self):
        r = measure_gradation_density(self.APPROX)
        assert r.approximative_count >= 4
        assert r.approximative_rate > 0.0


# ── sufficiency and excess ──────────────────────────────────────


class TestSufficiencyExcess:
    EXCESS = (
        "The model is too complex to deploy on edge devices. "
        "The training data is overly biased toward English text. "
        "Memory usage is disproportionately high for such a small model. "
        "The learning rate is sufficiently low for convergence. "
        "The batch size is not large enough for stable gradients."
    )

    def test_sufficiency_excess_present(self):
        r = measure_gradation_density(self.EXCESS)
        assert r.sufficiency_excess_count >= 2


# ── mixed gradation prose ───────────────────────────────────────


class TestMixedGradation:
    MIXED = (
        "The new design is significantly better than the original. "
        "It is somewhat more intuitive, though not quite as flexible. "
        "The most important improvement is the dramatically faster load time. "
        "Users report it is considerably easier to navigate. "
        "The color scheme is slightly more vibrant but almost identical in tone. "
        "Overall, it is by far the most polished version yet released. "
        "Performance is roughly twice as fast, and memory usage is barely half. "
        "The documentation is reasonably thorough but not entirely comprehensive."
    )

    def test_diverse_gradation(self):
        r = measure_gradation_density(self.MIXED)
        assert r.unique_gradation_forms >= 6
        assert r.gradation_diversity_index > 0.10

    def test_high_composite(self):
        r = measure_gradation_density(self.MIXED)
        assert r.gradation_density_index >= 0.20
        assert r.classification in (
            "moderately_gradated",
            "heavily_gradated",
            "gradation_saturated",
        )


# ── orthogonality checks ────────────────────────────────────────


class TestOrthogonality:
    def test_gradation_without_hedging(self):
        """Confident gradation without hedging."""
        text = (
            "This is absolutely the best solution available. "
            "The results are extremely clear and completely conclusive. "
            "It is undeniably the most effective approach."
        )
        r = measure_gradation_density(text)
        assert r.intensifier_count >= 3
        assert r.superlative_count >= 2
        # hedging words absent
        assert "perhaps" not in text.lower()
        assert "maybe" not in text.lower()

    def test_hedging_without_gradation(self):
        """Hedging language without strong gradation."""
        text = (
            "It seems that the approach may work in some cases. "
            "Perhaps this could be considered a viable option. "
            "It appears that the method might be applicable here."
        )
        r = measure_gradation_density(text)
        assert r.intensifier_count == 0
        assert r.superlative_count == 0

    def test_gradation_without_qualification(self):
        """Gradation without restrictive qualifiers."""
        text = (
            "The system is extremely powerful and remarkably fast. "
            "It delivers extraordinarily reliable results."
        )
        r = measure_gradation_density(text)
        assert r.intensifier_count >= 3
        # no "only", "merely", "just" as qualifiers
        assert "merely" not in text.lower()
        assert "simply" not in text.lower()

    def test_gradation_without_contrast(self):
        """Gradation without explicit contrast."""
        text = (
            "This is an incredibly sophisticated algorithm. "
            "It uses the most advanced techniques available. "
            "The implementation is exceptionally clean."
        )
        r = measure_gradation_density(text)
        assert r.intensifier_count >= 2
        # no contrast markers
        assert "however" not in text.lower()
        assert "although" not in text.lower()


# ── real-world prose samples ────────────────────────────────────


class TestRealWorldProse:
    ACADEMIC = (
        "The results are broadly consistent with prior findings, though "
        "the effect size is considerably smaller than initially hypothesized. "
        "Participants in the treatment group performed significantly better "
        "on the post-test, but the difference was only marginally significant "
        "after controlling for baseline scores. The most striking finding is "
        "the substantially higher retention rate observed in the follow-up "
        "assessment, which is remarkably consistent across all subgroups."
    )

    FICTION = (
        "She was almost beautiful, in an unsettling way. Her eyes were "
        "extraordinarily dark — the darkest he had ever seen — and her "
        "smile was slightly crooked, just enough to be interesting rather "
        "than imperfect. She moved more gracefully than anyone he had "
        "ever watched, and her voice was remarkably low, barely above a "
        "whisper, yet somehow completely audible across the vast room."
    )

    TECHNICAL = (
        "The server processes approximately 10,000 requests per second. "
        "Memory allocation is managed through a fixed-size buffer pool. "
        "Each request is assigned a unique identifier. "
        "The database schema contains twelve tables. "
        "Configuration parameters are loaded from a YAML file."
    )

    def test_academic_moderate_gradation(self):
        r = measure_gradation_density(self.ACADEMIC)
        assert r.classification in (
            "moderately_gradated",
            "heavily_gradated",
            "gradation_saturated",
        )
        assert r.diminisher_count >= 1
        assert r.intensifier_count >= 1

    def test_fiction_high_gradation(self):
        r = measure_gradation_density(self.FICTION)
        assert r.gradation_density_index > 0.15
        assert r.comparative_count >= 1
        assert r.intensifier_count >= 1

    def test_technical_low_gradation(self):
        r = measure_gradation_density(self.TECHNICAL)
        assert r.classification in ("flat", "lightly_gradated")
        assert r.gradation_density_index < 0.20


# ── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_all_caps(self):
        text = "THIS IS THE MOST EXTREMELY INCREDIBLY AMAZING THING EVER."
        r = measure_gradation_density(text)
        assert r.intensifier_count >= 1 or r.superlative_count >= 1

    def test_mixed_case(self):
        text = "This Is The Most Extremely Amazing Thing Ever Created."
        r = measure_gradation_density(text)
        assert r.gradation_density_index > 0.0

    def test_with_numbers(self):
        text = "The model is 3 times faster and roughly 2x more accurate."
        r = measure_gradation_density(text)
        assert r.comparative_count >= 1 or r.approximative_count >= 1

    def test_punctuation_adjacent(self):
        text = "Extremely fast! Incredibly powerful! Absolutely perfect!"
        r = measure_gradation_density(text)
        assert r.intensifier_count >= 2

    def test_newlines_and_tabs(self):
        text = "The best\nresult\tever.\nMore\timpressive\nthan before."
        r = measure_gradation_density(text)
        assert r.comparative_count >= 1 or r.superlative_count >= 1

    def test_repeated_periods(self):
        text = "Almost done... Nearly there... Very close..."
        r = measure_gradation_density(text)
        assert r.total_sentences >= 1
        assert r.approximative_count >= 1 or r.intensifier_count >= 1

    def test_single_sentence_many_gradations(self):
        text = (
            "The extremely complex and remarkably elegant solution is "
            "by far the most sophisticated approach ever devised."
        )
        r = measure_gradation_density(text)
        assert r.total_sentences == 1
        assert r.unique_gradation_forms >= 3


# ── classification boundary checks ──────────────────────────────


class TestClassificationBoundaries:
    def test_flat_boundary(self):
        text = "The cat sat on the mat. The dog ran in the park."
        r = measure_gradation_density(text)
        assert r.classification == "flat"

    def test_result_dataclass_defaults(self):
        r = GradationDensityResult()
        assert r.comparative_rate == 0.0
        assert r.superlative_rate == 0.0
        assert r.intensifier_rate == 0.0
        assert r.diminisher_rate == 0.0
        assert r.equative_rate == 0.0
        assert r.approximative_rate == 0.0
        assert r.sufficiency_excess_rate == 0.0
        assert r.gradation_density_index == 0.0
        assert r.classification == "flat"

    def test_details_populated(self):
        text = "The very best solution is extremely elegant and remarkably fast."
        r = measure_gradation_density(text)
        assert "comparative_rate" in r.details
        assert "superlative_rate" in r.details
        assert "intensifier_rate" in r.details
        assert "diminisher_rate" in r.details
        assert "equative_rate" in r.details
        assert "approximative_rate" in r.details
        assert "sufficiency_excess_rate" in r.details
        assert "gradation_diversity_index" in r.details
        assert "gradation_density_index" in r.details
        assert "classification" in r.details
