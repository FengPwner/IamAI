#!/usr/bin/env python3
"""Tests for writer_modality_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_modality_density import (
    ModalityDensityResult,
    measure_modality_density,
)


# ── empty / degenerate input ────────────────────────────────────

class TestEmptyInput:
    def test_empty_string(self):
        r = measure_modality_density("")
        assert r.modality_density_index == 0.0
        assert r.classification == "declarative"

    def test_whitespace_only(self):
        r = measure_modality_density("   \n\n   ")
        assert r.modality_density_index == 0.0

    def test_none_like_empty(self):
        r = measure_modality_density("")
        assert r.total_sentences == 0 or r.total_sentences == 1


# ── plain declarative prose (no modals) ─────────────────────────

class TestDeclarativeProse:
    PLAIN = (
        "The morning light crept across the floorboards, painting "
        "long amber rectangles that shifted with the hours. She sat "
        "at the kitchen table, turning a cold cup of tea in her "
        "hands, watching the garden through the window. The roses "
        "had bloomed early this year, their red petals scattered "
        "across the wet grass like small flags of surrender. A "
        "blackbird perched on the fence, tilted its head, and flew "
        "away without singing."
    )

    def test_declarative_classification(self):
        r = measure_modality_density(self.PLAIN)
        assert r.classification == "declarative"
        assert r.modality_density_index < 0.05

    def test_low_modal_counts(self):
        r = measure_modality_density(self.PLAIN)
        assert r.deontic_count == 0
        assert r.epistemic_count <= 1  # "can" might appear as substring
        assert r.hedging_modal_count == 0


# ── deontic modality (obligation/permission) ────────────────────

class TestDeonticModality:
    DEONTIC = (
        "You must submit the report by Friday. All employees should "
        "review the updated policy before the meeting. Staff members "
        "shall wear identification badges at all times. You ought to "
        "read the safety manual before operating any machinery. "
        "Everyone has to sign in at the front desk. Visitors need to "
        "check in with reception. The contractor is required to "
        "provide proof of insurance. You are not permitted to park "
        "in reserved spaces. Employees are allowed to take two breaks "
        "per shift."
    )

    def test_deontic_classification(self):
        r = measure_modality_density(self.DEONTIC)
        assert r.classification in ("moderately_modal", "heavily_modal")
        assert r.deontic_count >= 6

    def test_deontic_rate_positive(self):
        r = measure_modality_density(self.DEONTIC)
        assert r.deontic_modality_rate > 0


# ── epistemic modality (possibility/certainty) ──────────────────

class TestEpistemicModality:
    EPISTEMIC = (
        "The results might indicate a correlation between sleep and "
        "memory consolidation. The data could suggest that caffeine "
        "affects reaction time. It may be that the sample size was "
        "too small to detect a significant effect. The findings would "
        "support the hypothesis if replicated in a larger study. "
        "This will likely become clearer with further research. "
        "The theory can account for most observed phenomena, but it "
        "cannot explain the outlier cases. The experiment might not "
        "have controlled for all confounding variables."
    )

    def test_epistemic_count(self):
        r = measure_modality_density(self.EPISTEMIC)
        assert r.epistemic_count >= 5

    def test_epistemic_rate(self):
        r = measure_modality_density(self.EPISTEMIC)
        assert r.epistemic_modality_rate > 0


# ── dynamic modality (ability/willingness) ──────────────────────

class TestDynamicModality:
    DYNAMIC = (
        "She can swim across the lake without stopping. He could "
        "read before he turned four. They were able to finish the "
        "project ahead of schedule. The team managed to deliver "
        "under extreme pressure. She is capable of solving complex "
        "equations in her head. He is willing to work overtime when "
        "needed. The students attempted to build a working model "
        "from scratch. She succeeded in convincing the committee."
    )

    def test_dynamic_count(self):
        r = measure_modality_density(self.DYNAMIC)
        assert r.dynamic_count >= 4

    def test_dynamic_rate(self):
        r = measure_modality_density(self.DYNAMIC)
        assert r.dynamic_modality_rate > 0


# ── hedging modals ──────────────────────────────────────────────

class TestHedgingModals:
    HEDGING = (
        "The results might be due to chance. It could be that we "
        "overlooked a variable. This may or may not be significant. "
        "One would expect a different outcome under those conditions. "
        "The approach can work in some situations. It might not apply "
        "to all populations. The findings could be interpreted in "
        "several ways."
    )

    def test_hedging_modal_count(self):
        r = measure_modality_density(self.HEDGING)
        assert r.hedging_modal_count >= 4

    def test_hedging_modal_rate(self):
        r = measure_modality_density(self.HEDGING)
        assert r.hedging_modal_rate > 0


# ── conditional modals ──────────────────────────────────────────

class TestConditionalModals:
    CONDITIONAL = (
        "If the temperature drops below zero, the water will freeze. "
        "Unless you study harder, you might fail the exam. When the "
        "market crashes, investors would typically sell. If we had "
        "more data, we could make a better prediction. Provided that "
        "the sample is representative, the results should generalize."
    )

    def test_conditional_modal_count(self):
        r = measure_modality_density(self.CONDITIONAL)
        assert r.conditional_modal_count >= 3

    def test_conditional_modal_rate(self):
        r = measure_modality_density(self.CONDITIONAL)
        assert r.conditional_modal_rate > 0


# ── negated modals ──────────────────────────────────────────────

class TestNegatedModals:
    NEGATED = (
        "You must not enter the restricted area. She cannot attend "
        "the meeting tomorrow. They won't accept late submissions. "
        "He wouldn't agree to the terms. You should not ignore the "
        "warning signs. The system could not process the request. "
        "We can't afford to make mistakes."
    )

    def test_negated_modal_count(self):
        r = measure_modality_density(self.NEGATED)
        assert r.negated_modal_count >= 4

    def test_negated_modal_rate(self):
        r = measure_modality_density(self.NEGATED)
        assert r.negated_modal_rate > 0


# ── modal diversity ─────────────────────────────────────────────

class TestModalDiversity:
    LOW_DIVERSITY = (
        "You must do this. You must do that. You must follow the "
        "rules. You must obey the law. You must respect authority."
    )

    HIGH_DIVERSITY = (
        "You must try harder. You should consider the consequences. "
        "She might arrive late. He could help if asked. They may "
        "have already left. We would go if we had time. The system "
        "can handle the load. You ought to apologize. She has to "
        "finish by noon. He is able to run fast. They are willing "
        "to negotiate."
    )

    def test_low_diversity(self):
        r = measure_modality_density(self.LOW_DIVERSITY)
        assert r.unique_modal_forms <= 3

    def test_high_diversity(self):
        r = measure_modality_density(self.HIGH_DIVERSITY)
        assert r.unique_modal_forms >= 7

    def test_diversity_index_range(self):
        r = measure_modality_density(self.HIGH_DIVERSITY)
        assert 0.0 <= r.modal_diversity_index <= 1.0


# ── heavily modal text ─────────────────────────────────────────

class TestModalSaturated:
    SATURATED = (
        "You must understand that this could change everything. "
        "We should consider what might happen if we cannot control "
        "the variables. They would have to accept that the results "
        "may not be conclusive. She might be able to help, but she "
        "could also make things worse. He will need to decide whether "
        "he can commit to the project. The committee should review "
        "the proposal before we can proceed. You ought to know that "
        "the deadline may be extended. We would like to help, but we "
        "must follow protocol. It could be that the approach will "
        "work, but we might need more time. They shall receive the "
        "results when the analysis can be completed."
    )

    def test_saturated_classification(self):
        r = measure_modality_density(self.SATURATED)
        assert r.classification in ("heavily_modal", "modal_saturated")
        assert r.modality_density_index > 0.35

    def test_high_composite(self):
        r = measure_modality_density(self.SATURATED)
        assert r.modality_density_index > 0.30


# ── composite index properties ──────────────────────────────────

class TestCompositeIndex:
    def test_index_range(self):
        texts = [
            "Simple sentence. Another simple sentence.",
            "You must should could might may would shall can will.",
            "If you would help, she could succeed, and they might agree.",
        ]
        for text in texts:
            r = measure_modality_density(text)
            assert 0.0 <= r.modality_density_index <= 1.0

    def test_more_modals_higher_index(self):
        plain = "The cat sat on the mat. The dog ran in the park."
        modal = "The cat might sit on the mat. The dog could run in the park."
        r_plain = measure_modality_density(plain)
        r_modal = measure_modality_density(modal)
        assert r_modal.modality_density_index > r_plain.modality_density_index


# ── classification thresholds ───────────────────────────────────

class TestClassification:
    VALID_CLASSES = {
        "declarative",
        "lightly_modal",
        "moderately_modal",
        "heavily_modal",
        "modal_saturated",
    }

    def test_valid_classification(self):
        texts = [
            "No modals here at all.",
            "One might think so.",
            "You must should could might.",
            "Must should could might may would shall can will ought need have to.",
        ]
        for text in texts:
            r = measure_modality_density(text)
            assert r.classification in self.VALID_CLASSES


# ── details dict ────────────────────────────────────────────────

class TestDetailsDict:
    def test_details_keys(self):
        r = measure_modality_density("You must go. She might come.")
        expected_keys = {
            "deontic_modality_rate",
            "epistemic_modality_rate",
            "dynamic_modality_rate",
            "hedging_modal_rate",
            "conditional_modal_rate",
            "negated_modal_rate",
            "modal_diversity_index",
            "modality_density_index",
            "classification",
        }
        assert set(r.details.keys()) == expected_keys

    def test_details_values_match_fields(self):
        r = measure_modality_density("You should read this. It might help.")
        assert r.details["deontic_modality_rate"] == r.deontic_modality_rate
        assert r.details["epistemic_modality_rate"] == r.epistemic_modality_rate
        assert r.details["modality_density_index"] == r.modality_density_index
        assert r.details["classification"] == r.classification


# ── edge cases ──────────────────────────────────────────────────

class TestEdgeCases:
    def test_single_sentence_no_modals(self):
        r = measure_modality_density("Hello world.")
        assert r.modality_density_index == 0.0
        assert r.total_sentences == 1

    def test_single_word_must(self):
        r = measure_modality_density("Must.")
        assert r.deontic_count >= 1 or r.epistemic_count >= 1

    def test_modals_in_quotes(self):
        text = 'She said "you must go" and he replied "I might stay."'
        r = measure_modality_density(text)
        # Modals inside quotes still count
        assert r.deontic_count >= 1 or r.epistemic_count >= 1

    def test_case_insensitive(self):
        r_lower = measure_modality_density("you must go. she might come.")
        r_upper = measure_modality_density("You MUST go. She MIGHT come.")
        assert r_lower.modality_density_index == r_upper.modality_density_index

    def test_repeated_modal_increases_rate(self):
        base = "The cat sat on the mat."
        repeated = "You must must must must must go."
        r_base = measure_modality_density(base)
        r_rep = measure_modality_density(repeated)
        assert r_rep.modality_density_index > r_base.modality_density_index

    def test_very_long_text(self):
        # 50 sentences, no modals
        text = ". ".join([f"Sentence number {i} has no modal verbs" for i in range(50)]) + "."
        r = measure_modality_density(text)
        assert r.total_sentences >= 45
        assert r.modality_density_index < 0.05


# ── orthogonality sanity ────────────────────────────────────────

class TestOrthogonalitySanity:
    """Verify that modality density doesn't conflate with
    unrelated textual features."""

    def test_long_sentences_low_modality(self):
        # Long, complex sentences without modals
        text = (
            "The ancient library, its walls lined with thousands "
            "of leather-bound volumes stretching from floor to "
            "ceiling in every direction, stood at the center of "
            "the university campus, a monument to centuries of "
            "accumulated knowledge and scholarly endeavor. "
            "Students from around the world, drawn by the "
            "institution's reputation for excellence and the "
            "promise of access to rare manuscripts unavailable "
            "anywhere else, filled the reading rooms from early "
            "morning until the last bell signaled closing time."
        )
        r = measure_modality_density(text)
        assert r.modality_density_index < 0.10

    def test_short_sentences_high_modality(self):
        # Short, punchy sentences loaded with modals
        text = (
            "You must go. She should stay. They could help. "
            "He might try. We would see. It may work. You "
            "can do it. I will try."
        )
        r = measure_modality_density(text)
        assert r.modality_density_index > 0.20
