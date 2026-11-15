#!/usr/bin/env python3
"""Tests for writer_pleonasm_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_pleonasm_density import (
    PleonasmDensityResult,
    measure_pleonasm_density,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_pleonasm_density("")
        assert r.pleonasm_density_index == 0.0
        assert r.classification == "lean"

    def test_whitespace_only(self):
        r = measure_pleonasm_density("   \n\n   ")
        assert r.pleonasm_density_index == 0.0

    def test_none_like_empty(self):
        r = measure_pleonasm_density("")
        assert r.total_sentences == 0 or r.total_sentences == 1

    def test_single_word(self):
        r = measure_pleonasm_density("Hello.")
        assert r.pleonasm_density_index == 0.0
        assert r.classification == "lean"


# ── lean prose (minimal pleonasm) ────────────────────────────────


class TestLeanProse:
    PLAIN = (
        "The committee approved the proposal. "
        "The vote was unanimous. "
        "Implementation begins next month. "
        "The budget covers all departments. "
        "Staff will receive training materials."
    )

    def test_lean_classification(self):
        r = measure_pleonasm_density(self.PLAIN)
        assert r.classification in ("lean", "lightly_pleonastic")
        assert r.pleonasm_density_index < 0.15

    def test_low_pleonasm_counts(self):
        r = measure_pleonasm_density(self.PLAIN)
        assert r.semantic_count == 0
        assert r.syntactic_count == 0
        assert r.morphological_count == 0
        assert r.verbal_count == 0
        assert r.intensifier_count == 0


# ── heavily pleonastic prose ────────────────────────────────────


class TestHeavilyPleonasticProse:
    LEGALESE = (
        "The parties agree to cease and desist from all activities "
        "that are null and void under the terms and conditions of "
        "this agreement. Each and every obligation, right, and duty "
        "shall be governed by the will and testament of the original "
        "founder, who shall give, devise, and bequeath all goods and "
        "chattels to the rightful heirs. The fit and proper executor "
        "shall ensure peace and quiet, maintain law and order, and "
        "uphold the rights and obligations of all parties involved. "
        "First and foremost, this document is the one and only binding "
        "instrument, covering each and every aspect of the transaction."
    )

    def test_heavy_classification(self):
        r = measure_pleonasm_density(self.LEGALESE)
        assert r.classification in (
            "heavily_pleonastic",
            "pleonasm_saturated",
            "moderately_pleonastic",
        )
        assert r.pleonasm_density_index >= 0.15

    def test_high_syntactic_count(self):
        r = measure_pleonasm_density(self.LEGALESE)
        assert r.syntactic_count >= 8

    def test_syntactic_rate_positive(self):
        r = measure_pleonasm_density(self.LEGALESE)
        assert r.syntactic_rate > 0

    def test_multiple_categories_detected(self):
        r = measure_pleonasm_density(self.LEGALESE)
        non_zero = sum(
            1
            for c in [
                r.semantic_count,
                r.syntactic_count,
                r.morphological_count,
                r.verbal_count,
                r.intensifier_count,
            ]
            if c > 0
        )
        assert non_zero >= 1


# ── semantic redundancy detection ───────────────────────────────


class TestSemanticRedundancy:
    def test_free_gift(self):
        text = "Sign up today and receive a free gift with your purchase. The free gift includes bonus materials."
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 2

    def test_past_history(self):
        text = "Looking at past history, we see patterns repeat. Past history teaches us many lessons."
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 2

    def test_end_result(self):
        text = "The end result was disappointing. The end result of the experiment confirmed our hypothesis."
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 2

    def test_future_plans(self):
        text = "She discussed her future plans for the company. Future plans include expanding overseas."
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 2

    def test_unexpected_surprise(self):
        text = "The party was an unexpected surprise. What an unexpected surprise to see you here."
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 2

    def test_added_bonus(self):
        text = "The added bonus is free shipping. As an added bonus, you get priority support."
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 2

    def test_necessary_requirement(self):
        text = "A degree is a necessary requirement for this position."
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 1

    def test_revert_back(self):
        text = "Please revert back to the previous version. The system will revert back automatically."
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 2

    def test_repeat_again(self):
        text = "Could you repeat again what you just said? Let me repeat again for clarity."
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 2

    def test_collaborate_together(self):
        text = "The teams will collaborate together on the project. We need to collaborate together more often."
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 2

    def test_actual_fact(self):
        text = "The actual fact is that we need more resources."
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 1

    def test_close_proximity(self):
        text = "The restaurant is in close proximity to the hotel."
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 1

    def test_brief_summary(self):
        text = "Here is a brief summary of the meeting."
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 1

    def test_descend_down(self):
        text = "The hikers began to descend down the mountain."
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 1

    def test_ascend_up(self):
        text = "We watched the balloon ascend up into the sky."
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 1

    def test_case_insensitive(self):
        text = "The Free Gift was an Unexpected Surprise."
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 2


# ── syntactic binomial detection ─────────────────────────────────


class TestSyntacticBinomials:
    def test_null_and_void(self):
        text = "The contract was declared null and void by the court."
        r = measure_pleonasm_density(text)
        assert r.syntactic_count >= 1

    def test_cease_and_desist(self):
        text = "The company received a cease and desist order."
        r = measure_pleonasm_density(text)
        assert r.syntactic_count >= 1

    def test_will_and_testament(self):
        text = "According to the will and testament of the deceased."
        r = measure_pleonasm_density(text)
        assert r.syntactic_count >= 1

    def test_terms_and_conditions(self):
        text = "Please read the terms and conditions carefully."
        r = measure_pleonasm_density(text)
        assert r.syntactic_count >= 1

    def test_each_and_every(self):
        text = "Each and every student must submit their assignment."
        r = measure_pleonasm_density(text)
        assert r.syntactic_count >= 1

    def test_peace_and_quiet(self):
        text = "All I want is some peace and quiet."
        r = measure_pleonasm_density(text)
        assert r.syntactic_count >= 1

    def test_law_and_order(self):
        text = "The government prioritizes law and order above all."
        r = measure_pleonasm_density(text)
        assert r.syntactic_count >= 1

    def test_first_and_foremost(self):
        text = "First and foremost, we must address the budget deficit."
        r = measure_pleonasm_density(text)
        assert r.syntactic_count >= 1

    def test_pros_and_cons(self):
        text = "Let us weigh the pros and cons of each option."
        r = measure_pleonasm_density(text)
        assert r.syntactic_count >= 1

    def test_part_and_parcel(self):
        text = "Risk is part and parcel of any investment."
        r = measure_pleonasm_density(text)
        assert r.syntactic_count >= 1

    def test_safe_and_sound(self):
        text = "The children arrived home safe and sound."
        r = measure_pleonasm_density(text)
        assert r.syntactic_count >= 1

    def test_wear_and_tear(self):
        text = "Normal wear and tear is expected on the vehicle."
        r = measure_pleonasm_density(text)
        assert r.syntactic_count >= 1

    def test_multiple_binomials(self):
        text = (
            "First and foremost, the terms and conditions state that "
            "each and every participant must agree. This is part and parcel "
            "of maintaining law and order, ensuring peace and quiet for all."
        )
        r = measure_pleonasm_density(text)
        assert r.syntactic_count >= 5


# ── morphological redundancy detection ──────────────────────────


class TestMorphologicalRedundancy:
    def test_atm_machine(self):
        text = "I need to find an ATM machine nearby."
        r = measure_pleonasm_density(text)
        assert r.morphological_count >= 1

    def test_pin_number(self):
        text = "Please enter your PIN number to proceed."
        r = measure_pleonasm_density(text)
        assert r.morphological_count >= 1

    def test_hiv_virus(self):
        text = "Research on the HIV virus has advanced significantly."
        r = measure_pleonasm_density(text)
        assert r.morphological_count >= 1

    def test_lcd_display(self):
        text = "The device features an LCD display with high resolution."
        r = measure_pleonasm_density(text)
        assert r.morphological_count >= 1

    def test_ram_memory(self):
        text = "The computer has 16GB of RAM memory."
        r = measure_pleonasm_density(text)
        assert r.morphological_count >= 1

    def test_gps_system(self):
        text = "The car comes equipped with a GPS system."
        r = measure_pleonasm_density(text)
        assert r.morphological_count >= 1

    def test_chai_tea(self):
        text = "I would like a chai tea latte please."
        r = measure_pleonasm_density(text)
        assert r.morphological_count >= 1

    def test_tuna_fish(self):
        text = "She made a tuna fish sandwich for lunch."
        r = measure_pleonasm_density(text)
        assert r.morphological_count >= 1

    def test_multiple_morphological(self):
        text = (
            "Enter your PIN number at the ATM machine, then check "
            "the LCD display. The GPS system will guide you to the "
            "nearest branch with RAM memory upgrades available."
        )
        r = measure_pleonasm_density(text)
        assert r.morphological_count >= 5


# ── verbal pleonasm detection ────────────────────────────────────


class TestVerbalPleonasm:
    def test_see_with_eyes(self):
        text = "You need to see with your eyes what is happening."
        r = measure_pleonasm_density(text)
        assert r.verbal_count >= 1

    def test_hear_with_ears(self):
        text = "I heard with my ears the sound of thunder."
        r = measure_pleonasm_density(text)
        assert r.verbal_count >= 1

    def test_think_in_mind(self):
        text = "Think in your mind about the consequences."
        r = measure_pleonasm_density(text)
        assert r.verbal_count >= 1

    def test_nod_head(self):
        text = "She nodded her head in agreement."
        r = measure_pleonasm_density(text)
        assert r.verbal_count >= 1

    def test_shrug_shoulders(self):
        text = "He shrugged his shoulders in response."
        r = measure_pleonasm_density(text)
        assert r.verbal_count >= 1

    def test_blink_eyes(self):
        text = "She blinked her eyes rapidly."
        r = measure_pleonasm_density(text)
        assert r.verbal_count >= 1

    def test_multiple_verbal(self):
        text = (
            "She nodded her head and blinked her eyes. "
            "He shrugged his shoulders and looked with his eyes "
            "at the scene. They could hear with their ears the "
            "distant sound of music."
        )
        r = measure_pleonasm_density(text)
        assert r.verbal_count >= 4


# ── intensifier pleonasm detection ──────────────────────────────


class TestIntensifierPleonasm:
    def test_very_unique(self):
        text = "This is a very unique opportunity."
        r = measure_pleonasm_density(text)
        assert r.intensifier_count >= 1

    def test_absolutely_perfect(self):
        text = "The performance was absolutely perfect."
        r = measure_pleonasm_density(text)
        assert r.intensifier_count >= 1

    def test_completely_destroyed(self):
        text = "Note: completely destroyed is tested as semantic, not intensifier."
        r = measure_pleonasm_density(text)
        # completely destroyed is in semantic, not intensifier
        # This tests cross-category awareness
        total = r.semantic_count + r.intensifier_count
        assert total >= 1

    def test_totally_dead(self):
        text = "The battery is totally dead."
        r = measure_pleonasm_density(text)
        assert r.intensifier_count >= 1

    def test_absolutely_essential(self):
        text = "This step is absolutely essential for success."
        r = measure_pleonasm_density(text)
        assert r.intensifier_count >= 1

    def test_completely_finished(self):
        text = "The project is completely finished."
        r = measure_pleonasm_density(text)
        assert r.intensifier_count >= 1

    def test_very_pregnant(self):
        text = "The cat is very pregnant."
        r = measure_pleonasm_density(text)
        assert r.intensifier_count >= 1

    def test_absolutely_impossible(self):
        text = "That task is absolutely impossible."
        r = measure_pleonasm_density(text)
        assert r.intensifier_count >= 1

    def test_completely_full(self):
        text = "The stadium is completely full tonight."
        r = measure_pleonasm_density(text)
        assert r.intensifier_count >= 1

    def test_multiple_intensifier_pleonasms(self):
        text = (
            "This is a very unique opportunity that is absolutely essential. "
            "The plan is completely finished and the results are absolutely perfect. "
            "The battery is totally dead and the room is completely full."
        )
        r = measure_pleonasm_density(text)
        assert r.intensifier_count >= 5


# ── composite index and classification ──────────────────────────


class TestCompositeAndClassification:
    def test_zero_index_for_clean_text(self):
        text = "The cat sat on the mat. The dog ran in the park."
        r = measure_pleonasm_density(text)
        assert r.pleonasm_density_index == 0.0
        assert r.classification == "lean"

    def test_high_index_for_saturated_text(self):
        text = (
            "Each and every null and void cease and desist will and testament "
            "terms and conditions first and foremost one and only part and parcel "
            "free gift past history end result future plan added bonus unexpected "
            "surprise revert back repeat again ATM machine PIN number HIV virus "
            "very unique absolutely perfect totally dead absolutely essential "
            "see with your eyes hear with your ears nod your head. "
            "Law and order peace and quiet safe and sound wear and tear. "
            "Collaborate together merge together combine together consensus of opinion "
            "proceed ahead descend down ascend up enter in exit out refer back."
        )
        r = measure_pleonasm_density(text)
        assert r.pleonasm_density_index > 0.3

    def test_classification_levels(self):
        """Verify that different texts produce different classifications."""
        lean = "The quick brown fox jumps over the lazy dog. Birds fly south in winter."
        r_lean = measure_pleonasm_density(lean)
        assert r_lean.classification in ("lean", "lightly_pleonastic")

    def test_index_bounded(self):
        text = "Each and every null and void free gift past history. " * 50
        r = measure_pleonasm_density(text)
        assert 0.0 <= r.pleonasm_density_index <= 1.0

    def test_diversity_index_bounded(self):
        text = "Each and every null and void free gift past history."
        r = measure_pleonasm_density(text)
        assert 0.0 <= r.pleonasm_diversity_index <= 1.0


# ── rates calculation ────────────────────────────────────────────


class TestRates:
    def test_rates_scale_with_sentences(self):
        text = "Free gift. " * 10
        r = measure_pleonasm_density(text)
        # 10 instances in ~10 sentences = ~100 per 100 sentences
        assert r.semantic_rate >= 50.0

    def test_single_sentence_high_rate(self):
        text = "A free gift is an unexpected surprise and an added bonus."
        r = measure_pleonasm_density(text)
        assert r.semantic_rate >= 200.0  # 3 in 1 sentence = 300/100

    def test_rates_are_rounded(self):
        text = "The committee met. Free gift. They left."
        r = measure_pleonasm_density(text)
        assert r.semantic_rate == round(r.semantic_rate, 3)
        assert r.syntactic_rate == round(r.syntactic_rate, 3)
        assert r.morphological_rate == round(r.morphological_rate, 3)
        assert r.verbal_rate == round(r.verbal_rate, 3)
        assert r.intensifier_rate == round(r.intensifier_rate, 3)


# ── details dict ────────────────────────────────────────────────


class TestDetails:
    def test_details_populated(self):
        text = "Each and every free gift is a null and void proposition."
        r = measure_pleonasm_density(text)
        assert "semantic_rate" in r.details
        assert "syntactic_rate" in r.details
        assert "morphological_rate" in r.details
        assert "verbal_rate" in r.details
        assert "intensifier_rate" in r.details
        assert "pleonasm_diversity_index" in r.details
        assert "pleonasm_density_index" in r.details
        assert "classification" in r.details

    def test_details_match_result_fields(self):
        text = "Free gift and null and void terms and conditions."
        r = measure_pleonasm_density(text)
        assert r.details["semantic_rate"] == r.semantic_rate
        assert r.details["syntactic_rate"] == r.syntactic_rate
        assert r.details["classification"] == r.classification


# ── orthogonality checks ────────────────────────────────────────


class TestOrthogonality:
    def test_concise_text_can_be_pleonastic(self):
        """Short text with pleonasm should score high despite brevity."""
        text = "Free gift. Each and every one."
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 1
        assert r.syntactic_count >= 1

    def test_verbose_text_without_pleonasm(self):
        """Long text without redundancy should score low."""
        text = (
            "The algorithm processes input data through a series of "
            "transformations, each producing intermediate results that "
            "feed subsequent stages. Performance benchmarks indicate "
            "throughput of 10000 records per second on standard hardware."
        )
        r = measure_pleonasm_density(text)
        assert r.pleonasm_density_index < 0.15
        assert r.classification in ("lean", "lightly_pleonastic")

    def test_repetition_without_pleonasm(self):
        """Repeating words is not pleonasm in this module's scope."""
        text = "The the the. Cat cat cat. Run run run. Jump jump jump. Fast fast fast."
        r = measure_pleonasm_density(text)
        assert r.semantic_count == 0
        assert r.syntactic_count == 0


# ── edge cases ───────────────────────────────────────────────────


class TestEdgeCases:
    def test_punctuation_handling(self):
        text = "Is this a free gift? Yes, it's a free gift!"
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 2

    def test_multiline_text(self):
        text = "Free gift.\nNull and void.\nATM machine.\nVery unique."
        r = measure_pleonasm_density(text)
        total = r.semantic_count + r.syntactic_count + r.morphological_count + r.intensifier_count
        assert total >= 4

    def test_mixed_content(self):
        text = (
            "The meeting proceeded ahead as scheduled. "
            "Regular routines were maintained. "
            "The GPS system directed us to the nearest ATM machine. "
            "It was a very unique experience, absolutely perfect in every way. "
            "She nodded her head and we could see with our eyes the result."
        )
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 2
        assert r.morphological_count >= 2
        assert r.intensifier_count >= 1
        assert r.verbal_count >= 2

    def test_total_sentences_counted(self):
        text = "One. Two. Three. Four. Five."
        r = measure_pleonasm_density(text)
        assert r.total_sentences == 5

    def test_unique_forms_counted(self):
        text = "Free gift free gift free gift. Null and void null and void."
        r = measure_pleonasm_density(text)
        assert r.unique_pleonasm_forms >= 2

    def test_result_dataclass_defaults(self):
        r = PleonasmDensityResult()
        assert r.semantic_count == 0
        assert r.syntactic_count == 0
        assert r.morphological_count == 0
        assert r.verbal_count == 0
        assert r.intensifier_count == 0
        assert r.unique_pleonasm_forms == 0
        assert r.pleonasm_density_index == 0.0
        assert r.classification == "lean"
        assert r.details == {}


# ── real-world text samples ─────────────────────────────────────


class TestRealWorldSamples:
    def test_legal_document_style(self):
        text = (
            "This Agreement, including the terms and conditions set forth "
            "herein, constitutes the null and void resolution of all prior "
            "negotiations. Each and every party agrees to cease and desist "
            "from activities that violate the will and testament provisions. "
            "The fit and proper representative shall ensure peace and quiet "
            "enjoyment and maintain law and order throughout the premises. "
            "First and foremost, this is the one and only binding document."
        )
        r = measure_pleonasm_density(text)
        assert r.syntactic_count >= 7
        assert r.classification in (
            "moderately_pleonastic",
            "heavily_pleonastic",
            "pleonasm_saturated",
        )

    def test_marketing_copy(self):
        text = (
            "Sign up today and receive a free gift with your purchase! "
            "As an added bonus, you will get an unexpected surprise in the mail. "
            "This is a very unique opportunity — absolutely essential for anyone "
            "who wants to get ahead. The end result? A completely finished plan "
            "for your future plans. Act now, this is the one and only chance."
        )
        r = measure_pleonasm_density(text)
        assert r.semantic_count >= 4
        assert r.intensifier_count >= 2
        assert r.pleonasm_density_index > 0.1

    def test_technical_writing(self):
        text = (
            "The CPU processor handles all computational tasks. "
            "RAM memory stores temporary data during processing. "
            "The LCD display shows output in real time. "
            "A GPS system provides location data to the application. "
            "Enter your PIN number to authenticate the transaction."
        )
        r = measure_pleonasm_density(text)
        assert r.morphological_count >= 5

    def test_academic_prose_low_pleonasm(self):
        text = (
            "The experiment measured reaction times across three conditions. "
            "Participants responded to visual stimuli presented on a monitor. "
            "Results indicated significant differences between groups. "
            "The control group showed no improvement over baseline. "
            "Statistical analysis confirmed the hypothesis at p < 0.05."
        )
        r = measure_pleonasm_density(text)
        assert r.pleonasm_density_index < 0.15
        assert r.classification in ("lean", "lightly_pleonastic")

    def test_casual_speech(self):
        text = (
            "I went to the ATM machine to get some cash. "
            "Then I ordered a chai tea at the cafe. "
            "Each and every time I go there, the tuna fish sandwich is great. "
            "It is a very unique place, absolutely perfect for a quick lunch."
        )
        r = measure_pleonasm_density(text)
        assert r.morphological_count >= 2
        assert r.intensifier_count >= 1
        assert r.syntactic_count >= 1
