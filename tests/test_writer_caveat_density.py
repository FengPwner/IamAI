#!/usr/bin/env python3
"""Tests for writer_caveat_density — comprehensive test suite."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_caveat_density import (  # noqa: E402
    LIABILITY_DISCLAIMER_PATTERNS,
    PROFESSIONAL_ADVICE_PATTERNS,
    RESULT_QUALIFIER_PATTERNS,
    SCOPE_LIMITATION_PATTERNS,
    TEMPORAL_RESTRICTION_PATTERNS,
    WARRANTY_LIMITATION_PATTERNS,
    WriterCaveatDensity,
    _count_matching,
    _split_sentences,
)


# ── Helpers ──────────────────────────────────────────────────────────


class TestSplitSentences(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(_split_sentences(""), [])

    def test_whitespace_only(self):
        self.assertEqual(_split_sentences("   \n  "), [])

    def test_single_sentence(self):
        self.assertEqual(_split_sentences("She walked home."), ["She walked home."])

    def test_multiple_sentences(self):
        result = _split_sentences("He ran. She walked. They stayed.")
        self.assertEqual(len(result), 3)

    def test_question_marks(self):
        result = _split_sentences("Why? How? Where?")
        self.assertEqual(len(result), 3)

    def test_exclamation_marks(self):
        result = _split_sentences("Stop! Wait! Go!")
        self.assertEqual(len(result), 3)

    def test_mixed_punctuation(self):
        result = _split_sentences("Hello. What? Yes! No.")
        self.assertEqual(len(result), 4)

    def test_newlines(self):
        result = _split_sentences("First sentence.\nSecond sentence.")
        self.assertEqual(len(result), 2)

    def test_strips_whitespace(self):
        result = _split_sentences("  Hello world.  ")
        self.assertEqual(result, ["Hello world."])


class TestCountMatching(unittest.TestCase):
    def test_empty_sentences(self):
        self.assertEqual(_count_matching([], LIABILITY_DISCLAIMER_PATTERNS), 0)

    def test_no_matches(self):
        sentences = ["The cat sat on the mat.", "She walked home quietly."]
        self.assertEqual(_count_matching(sentences, LIABILITY_DISCLAIMER_PATTERNS), 0)

    def test_all_match(self):
        sentences = [
            "The product is provided as is.",
            "We are not liable for damages.",
        ]
        count = _count_matching(sentences, LIABILITY_DISCLAIMER_PATTERNS)
        self.assertGreater(count, 0)

    def test_partial_match(self):
        sentences = [
            "Not liable for any damages.",
            "The cat sat on the mat.",
            "Use at your own risk.",
            "She walked home.",
        ]
        count = _count_matching(sentences, LIABILITY_DISCLAIMER_PATTERNS)
        self.assertGreaterEqual(count, 2)


# ── Liability Disclaimer Patterns ────────────────────────────────────


class TestLiabilityDisclaimerPatterns(unittest.TestCase):
    def test_not_liable_for(self):
        self.assertTrue(
            any(p.search("We are not liable for any damages.") for p in LIABILITY_DISCLAIMER_PATTERNS)
        )

    def test_not_responsible_for(self):
        self.assertTrue(
            any(p.search("We are not responsible for losses.") for p in LIABILITY_DISCLAIMER_PATTERNS)
        )

    def test_not_accountable_for(self):
        self.assertTrue(
            any(p.search("Not accountable for user actions.") for p in LIABILITY_DISCLAIMER_PATTERNS)
        )

    def test_at_your_own_risk(self):
        self.assertTrue(
            any(p.search("Use this software at your own risk.") for p in LIABILITY_DISCLAIMER_PATTERNS)
        )

    def test_as_is(self):
        self.assertTrue(
            any(p.search("The product is provided as is.") for p in LIABILITY_DISCLAIMER_PATTERNS)
        )

    def test_as_is_hyphenated(self):
        self.assertTrue(
            any(p.search("Provided as-is to users.") for p in LIABILITY_DISCLAIMER_PATTERNS)
        )

    def test_no_warranty(self):
        self.assertTrue(
            any(p.search("There is no warranty for this product.") for p in LIABILITY_DISCLAIMER_PATTERNS)
        )

    def test_without_guarantee(self):
        self.assertTrue(
            any(p.search("Sold without guarantee of fitness.") for p in LIABILITY_DISCLAIMER_PATTERNS)
        )

    def test_disclaims_liability(self):
        self.assertTrue(
            any(p.search("The author disclaims all liability.") for p in LIABILITY_DISCLAIMER_PATTERNS)
        )

    def test_hold_harmless(self):
        self.assertTrue(
            any(p.search("You agree to hold harmless the company.") for p in LIABILITY_DISCLAIMER_PATTERNS)
        )

    def test_no_obligation(self):
        self.assertTrue(
            any(p.search("We have no obligation to support this.") for p in LIABILITY_DISCLAIMER_PATTERNS)
        )

    def test_shall_not_be_liable(self):
        self.assertTrue(
            any(p.search("The company shall not be liable for indirect damages.") for p in LIABILITY_DISCLAIMER_PATTERNS)
        )

    def test_under_no_circumstances(self):
        self.assertTrue(
            any(p.search("Under no circumstances shall we be liable.") for p in LIABILITY_DISCLAIMER_PATTERNS)
        )

    def test_indemnify(self):
        self.assertTrue(
            any(p.search("You shall indemnify the provider.") for p in LIABILITY_DISCLAIMER_PATTERNS)
        )

    def test_case_insensitive(self):
        self.assertTrue(
            any(p.search("NOT LIABLE FOR DAMAGES.") for p in LIABILITY_DISCLAIMER_PATTERNS)
        )

    def test_no_false_positive_narrative(self):
        self.assertFalse(
            any(p.search("The sun set over the mountains.") for p in LIABILITY_DISCLAIMER_PATTERNS)
        )

    def test_no_false_positive_casual(self):
        self.assertFalse(
            any(p.search("She walked to the store yesterday.") for p in LIABILITY_DISCLAIMER_PATTERNS)
        )


# ── Result Qualifier Patterns ────────────────────────────────────────


class TestResultQualifierPatterns(unittest.TestCase):
    def test_results_may_vary(self):
        self.assertTrue(
            any(p.search("Results may vary from person to person.") for p in RESULT_QUALIFIER_PATTERNS)
        )

    def test_your_results_may_vary(self):
        self.assertTrue(
            any(p.search("Your results may vary.") for p in RESULT_QUALIFIER_PATTERNS)
        )

    def test_your_mileage_may_vary(self):
        self.assertTrue(
            any(p.search("Your mileage may vary.") for p in RESULT_QUALIFIER_PATTERNS)
        )

    def test_ymmv(self):
        self.assertTrue(
            any(p.search("The tool works well, YMMV.") for p in RESULT_QUALIFIER_PATTERNS)
        )

    def test_individual_results(self):
        self.assertTrue(
            any(p.search("Individual results will differ.") for p in RESULT_QUALIFIER_PATTERNS)
        )

    def test_not_guaranteed(self):
        self.assertTrue(
            any(p.search("Success is not guaranteed.") for p in RESULT_QUALIFIER_PATTERNS)
        )

    def test_no_guarantee(self):
        self.assertTrue(
            any(p.search("There is no guarantee of profit.") for p in RESULT_QUALIFIER_PATTERNS)
        )

    def test_past_performance(self):
        self.assertTrue(
            any(p.search("Past performance does not predict future results.") for p in RESULT_QUALIFIER_PATTERNS)
        )

    def test_may_not_work_for_everyone(self):
        self.assertTrue(
            any(p.search("This approach may not work for everyone.") for p in RESULT_QUALIFIER_PATTERNS)
        )

    def test_no_assurance(self):
        self.assertTrue(
            any(p.search("We provide no assurance of success.") for p in RESULT_QUALIFIER_PATTERNS)
        )

    def test_does_not_ensure(self):
        self.assertTrue(
            any(p.search("Using this method does not ensure success.") for p in RESULT_QUALIFIER_PATTERNS)
        )

    def test_actual_results_may_differ(self):
        self.assertTrue(
            any(p.search("Actual results may differ from projections.") for p in RESULT_QUALIFIER_PATTERNS)
        )

    def test_outcomes_may_vary(self):
        self.assertTrue(
            any(p.search("Outcomes may vary by region.") for p in RESULT_QUALIFIER_PATTERNS)
        )

    def test_no_false_positive_narrative(self):
        self.assertFalse(
            any(p.search("The results were impressive.") for p in RESULT_QUALIFIER_PATTERNS)
        )


# ── Professional Advice Patterns ─────────────────────────────────────


class TestProfessionalAdvicePatterns(unittest.TestCase):
    def test_not_medical_advice(self):
        self.assertTrue(
            any(p.search("This is not medical advice.") for p in PROFESSIONAL_ADVICE_PATTERNS)
        )

    def test_not_legal_advice(self):
        self.assertTrue(
            any(p.search("This is not legal advice.") for p in PROFESSIONAL_ADVICE_PATTERNS)
        )

    def test_not_financial_advice(self):
        self.assertTrue(
            any(p.search("This is not financial advice.") for p in PROFESSIONAL_ADVICE_PATTERNS)
        )

    def test_consult_a_doctor(self):
        self.assertTrue(
            any(p.search("Consult a doctor before starting.") for p in PROFESSIONAL_ADVICE_PATTERNS)
        )

    def test_consult_your_physician(self):
        self.assertTrue(
            any(p.search("Consult your physician first.") for p in PROFESSIONAL_ADVICE_PATTERNS)
        )

    def test_consult_a_lawyer(self):
        self.assertTrue(
            any(p.search("Consult a lawyer for legal questions.") for p in PROFESSIONAL_ADVICE_PATTERNS)
        )

    def test_seek_professional_advice(self):
        self.assertTrue(
            any(p.search("Seek professional advice before proceeding.") for p in PROFESSIONAL_ADVICE_PATTERNS)
        )

    def test_seek_medical_help(self):
        self.assertTrue(
            any(p.search("Seek medical help if symptoms persist.") for p in PROFESSIONAL_ADVICE_PATTERNS)
        )

    def test_not_a_substitute_for(self):
        self.assertTrue(
            any(p.search("This is not a substitute for professional care.") for p in PROFESSIONAL_ADVICE_PATTERNS)
        )

    def test_talk_to_your_doctor(self):
        self.assertTrue(
            any(p.search("Talk to your doctor about this.") for p in PROFESSIONAL_ADVICE_PATTERNS)
        )

    def test_always_consult(self):
        self.assertTrue(
            any(p.search("Always consult a professional before deciding.") for p in PROFESSIONAL_ADVICE_PATTERNS)
        )

    def test_before_starting_program(self):
        self.assertTrue(
            any(p.search("Before starting any exercise program, check with your doctor.") for p in PROFESSIONAL_ADVICE_PATTERNS)
        )

    def test_does_not_constitute_advice(self):
        self.assertTrue(
            any(p.search("This does not constitute investment advice.") for p in PROFESSIONAL_ADVICE_PATTERNS)
        )

    def test_no_false_positive(self):
        self.assertFalse(
            any(p.search("She gave good advice to her friend.") for p in PROFESSIONAL_ADVICE_PATTERNS)
        )


# ── Warranty Limitation Patterns ─────────────────────────────────────


class TestWarrantyLimitationPatterns(unittest.TestCase):
    def test_subject_to_change(self):
        self.assertTrue(
            any(p.search("Prices are subject to change.") for p in WARRANTY_LIMITATION_PATTERNS)
        )

    def test_without_notice(self):
        self.assertTrue(
            any(p.search("Features may change without notice.") for p in WARRANTY_LIMITATION_PATTERNS)
        )

    def test_without_prior_notice(self):
        self.assertTrue(
            any(p.search("Terms may change without prior notice.") for p in WARRANTY_LIMITATION_PATTERNS)
        )

    def test_no_warranty_expressed_or_implied(self):
        self.assertTrue(
            any(p.search("There is no warranty expressed or implied.") for p in WARRANTY_LIMITATION_PATTERNS)
        )

    def test_may_be_discontinued(self):
        self.assertTrue(
            any(p.search("This service may be discontinued.") for p in WARRANTY_LIMITATION_PATTERNS)
        )

    def test_may_be_withdrawn(self):
        self.assertTrue(
            any(p.search("The offer may be withdrawn at any time.") for p in WARRANTY_LIMITATION_PATTERNS)
        )

    def test_not_obligated_to_maintain(self):
        self.assertTrue(
            any(p.search("We are not obligated to maintain this service.") for p in WARRANTY_LIMITATION_PATTERNS)
        )

    def test_not_obligated_to_support(self):
        self.assertTrue(
            any(p.search("Not obligated to support older versions.") for p in WARRANTY_LIMITATION_PATTERNS)
        )

    def test_provided_as_is(self):
        self.assertTrue(
            any(p.search("The software is provided as-is.") for p in WARRANTY_LIMITATION_PATTERNS)
        )

    def test_provided_without_warranties(self):
        self.assertTrue(
            any(p.search("Provided without any warranties.") for p in WARRANTY_LIMITATION_PATTERNS)
        )

    def test_expressly_disclaims(self):
        self.assertTrue(
            any(p.search("The company expressly disclaims all warranties.") for p in WARRANTY_LIMITATION_PATTERNS)
        )

    def test_no_false_positive(self):
        self.assertFalse(
            any(p.search("The weather may change tomorrow.") for p in WARRANTY_LIMITATION_PATTERNS)
        )


# ── Temporal Restriction Patterns ────────────────────────────────────


class TestTemporalRestrictionPatterns(unittest.TestCase):
    def test_as_of_date(self):
        self.assertTrue(
            any(p.search("Information is accurate as of January 2026.") for p in TEMPORAL_RESTRICTION_PATTERNS)
        )

    def test_as_of_the_date(self):
        self.assertTrue(
            any(p.search("Valid as of the date of purchase.") for p in TEMPORAL_RESTRICTION_PATTERNS)
        )

    def test_at_the_time_of_writing(self):
        self.assertTrue(
            any(p.search("At the time of writing, this was accurate.") for p in TEMPORAL_RESTRICTION_PATTERNS)
        )

    def test_at_the_time_of_publication(self):
        self.assertTrue(
            any(p.search("At the time of publication, prices were stable.") for p in TEMPORAL_RESTRICTION_PATTERNS)
        )

    def test_current_as_of(self):
        self.assertTrue(
            any(p.search("Data is current as of November 2026.") for p in TEMPORAL_RESTRICTION_PATTERNS)
        )

    def test_valid_until(self):
        self.assertTrue(
            any(p.search("This coupon is valid until December 31.") for p in TEMPORAL_RESTRICTION_PATTERNS)
        )

    def test_valid_through(self):
        self.assertTrue(
            any(p.search("Offer valid through the end of the month.") for p in TEMPORAL_RESTRICTION_PATTERNS)
        )

    def test_may_expire(self):
        self.assertTrue(
            any(p.search("These discounts may expire soon.") for p in TEMPORAL_RESTRICTION_PATTERNS)
        )

    def test_limited_time(self):
        self.assertTrue(
            any(p.search("This is a limited-time offer.") for p in TEMPORAL_RESTRICTION_PATTERNS)
        )

    def test_prices_subject_to_change(self):
        self.assertTrue(
            any(p.search("Prices are subject to change.") for p in TEMPORAL_RESTRICTION_PATTERNS)
        )

    def test_effective_date(self):
        self.assertTrue(
            any(p.search("Effective date of this policy is January 1.") for p in TEMPORAL_RESTRICTION_PATTERNS)
        )

    def test_no_false_positive(self):
        self.assertFalse(
            any(p.search("She arrived at the station as of usual.") for p in TEMPORAL_RESTRICTION_PATTERNS)
        )


# ── Scope Limitation Patterns ────────────────────────────────────────


class TestScopeLimitationPatterns(unittest.TestCase):
    def test_for_informational_purposes_only(self):
        self.assertTrue(
            any(p.search("This is for informational purposes only.") for p in SCOPE_LIMITATION_PATTERNS)
        )

    def test_for_educational_purposes(self):
        self.assertTrue(
            any(p.search("This guide is for educational purposes.") for p in SCOPE_LIMITATION_PATTERNS)
        )

    def test_for_entertainment_purposes(self):
        self.assertTrue(
            any(p.search("This content is for entertainment purposes only.") for p in SCOPE_LIMITATION_PATTERNS)
        )

    def test_not_exhaustive(self):
        self.assertTrue(
            any(p.search("This list is not exhaustive.") for p in SCOPE_LIMITATION_PATTERNS)
        )

    def test_not_comprehensive(self):
        self.assertTrue(
            any(p.search("This overview is not comprehensive.") for p in SCOPE_LIMITATION_PATTERNS)
        )

    def test_does_not_cover(self):
        self.assertTrue(
            any(p.search("This guide does not cover advanced topics.") for p in SCOPE_LIMITATION_PATTERNS)
        )

    def test_does_not_address(self):
        self.assertTrue(
            any(p.search("This article does not address edge cases.") for p in SCOPE_LIMITATION_PATTERNS)
        )

    def test_limited_to(self):
        self.assertTrue(
            any(p.search("Support is limited to business hours.") for p in SCOPE_LIMITATION_PATTERNS)
        )

    def test_applies_only_to(self):
        self.assertTrue(
            any(p.search("This policy applies only to premium users.") for p in SCOPE_LIMITATION_PATTERNS)
        )

    def test_in_certain_jurisdictions(self):
        self.assertTrue(
            any(p.search("This feature is available in certain jurisdictions.") for p in SCOPE_LIMITATION_PATTERNS)
        )

    def test_may_not_be_available(self):
        self.assertTrue(
            any(p.search("This service may not be available in all regions.") for p in SCOPE_LIMITATION_PATTERNS)
        )

    def test_not_a_complete_list(self):
        self.assertTrue(
            any(p.search("This is not a complete list of features.") for p in SCOPE_LIMITATION_PATTERNS)
        )

    def test_including_but_not_limited_to(self):
        self.assertTrue(
            any(p.search("Risks include but are not limited to data loss.") for p in SCOPE_LIMITATION_PATTERNS)
        )

    def test_no_false_positive(self):
        self.assertFalse(
            any(p.search("She walked to the store.") for p in SCOPE_LIMITATION_PATTERNS)
        )


# ── WriterCaveatDensity class ────────────────────────────────────────


class TestWriterCaveatDensity(unittest.TestCase):
    def setUp(self):
        self.wcd = WriterCaveatDensity()

    # ── Empty / edge cases ──

    def test_empty_text(self):
        result = self.wcd.measure("")
        self.assertEqual(result["caveat_density_index"], 0.0)
        self.assertEqual(result["classification"], "unencumbered")

    def test_whitespace_only(self):
        result = self.wcd.measure("   \n  ")
        self.assertEqual(result["caveat_density_index"], 0.0)

    def test_single_non_caveat_sentence(self):
        result = self.wcd.measure("The cat sat on the mat.")
        self.assertEqual(result["caveat_density_index"], 0.0)
        self.assertEqual(result["classification"], "unencumbered")

    # ── Liability disclaimer rate ──

    def test_liability_rate_all_caveats(self):
        text = "Not liable for damages. At your own risk. No warranty."
        rate = self.wcd.measure_liability_disclaimer_rate(text)
        self.assertGreater(rate, 0.5)

    def test_liability_rate_no_caveats(self):
        text = "The weather is nice. She walked home. He read a book."
        rate = self.wcd.measure_liability_disclaimer_rate(text)
        self.assertEqual(rate, 0.0)

    def test_liability_rate_mixed(self):
        text = "Not liable for damages. The weather is nice. Use at your own risk."
        rate = self.wcd.measure_liability_disclaimer_rate(text)
        self.assertGreater(rate, 0.3)
        self.assertLess(rate, 1.0)

    # ── Result qualifier rate ──

    def test_result_rate_all_caveats(self):
        text = "Results may vary. Not guaranteed. Past performance is no indicator."
        rate = self.wcd.measure_result_qualifier_rate(text)
        self.assertGreater(rate, 0.5)

    def test_result_rate_no_caveats(self):
        text = "She won the race. He finished first. They celebrated."
        rate = self.wcd.measure_result_qualifier_rate(text)
        self.assertEqual(rate, 0.0)

    # ── Professional advice rate ──

    def test_professional_rate_all_caveats(self):
        text = "Not medical advice. Consult a doctor. Seek professional help."
        rate = self.wcd.measure_professional_advice_rate(text)
        self.assertGreater(rate, 0.5)

    def test_professional_rate_no_caveats(self):
        text = "She cooked dinner. He washed dishes. They watched TV."
        rate = self.wcd.measure_professional_advice_rate(text)
        self.assertEqual(rate, 0.0)

    # ── Warranty limitation rate ──

    def test_warranty_rate_all_caveats(self):
        text = "Subject to change. Without notice. May be discontinued."
        rate = self.wcd.measure_warranty_limitation_rate(text)
        self.assertGreater(rate, 0.5)

    def test_warranty_rate_no_caveats(self):
        text = "The store opens at nine. She bought groceries. He paid cash."
        rate = self.wcd.measure_warranty_limitation_rate(text)
        self.assertEqual(rate, 0.0)

    # ── Temporal restriction rate ──

    def test_temporal_rate_all_caveats(self):
        text = "Current as of January. At the time of writing. Valid until March."
        rate = self.wcd.measure_temporal_restriction_rate(text)
        self.assertGreater(rate, 0.5)

    def test_temporal_rate_no_caveats(self):
        text = "She went to the park. He read a novel. They had lunch."
        rate = self.wcd.measure_temporal_restriction_rate(text)
        self.assertEqual(rate, 0.0)

    # ── Scope limitation rate ──

    def test_scope_rate_all_caveats(self):
        text = "For informational purposes only. Not exhaustive. Does not cover all cases."
        rate = self.wcd.measure_scope_limitation_rate(text)
        self.assertGreater(rate, 0.5)

    def test_scope_rate_no_caveats(self):
        text = "The garden bloomed in spring. Roses lined the path."
        rate = self.wcd.measure_scope_limitation_rate(text)
        self.assertEqual(rate, 0.0)

    # ── Composite index ──

    def test_composite_index_all_zeros(self):
        index = self.wcd.compute_caveat_density_index(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(index, 0.0)

    def test_composite_index_all_ones(self):
        index = self.wcd.compute_caveat_density_index(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
        self.assertEqual(index, 1.0)

    def test_composite_index_capped_at_one(self):
        index = self.wcd.compute_caveat_density_index(2.0, 2.0, 2.0, 2.0, 2.0, 2.0)
        self.assertLessEqual(index, 1.0)

    def test_composite_index_partial(self):
        index = self.wcd.compute_caveat_density_index(0.5, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(index, 0.125, places=3)

    def test_composite_index_weights(self):
        # liability=0.25 weight, result=0.20 weight
        index_liability = self.wcd.compute_caveat_density_index(1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        index_result = self.wcd.compute_caveat_density_index(0.0, 1.0, 0.0, 0.0, 0.0, 0.0)
        self.assertGreater(index_liability, index_result)

    # ── Classification ──

    def test_classify_unencumbered(self):
        self.assertEqual(self.wcd.classify(0.0), "unencumbered")
        self.assertEqual(self.wcd.classify(0.01), "unencumbered")
        self.assertEqual(self.wcd.classify(0.029), "unencumbered")

    def test_classify_lightly_caveated(self):
        self.assertEqual(self.wcd.classify(0.03), "lightly_caveated")
        self.assertEqual(self.wcd.classify(0.05), "lightly_caveated")
        self.assertEqual(self.wcd.classify(0.099), "lightly_caveated")

    def test_classify_moderately_caveated(self):
        self.assertEqual(self.wcd.classify(0.10), "moderately_caveated")
        self.assertEqual(self.wcd.classify(0.15), "moderately_caveated")
        self.assertEqual(self.wcd.classify(0.249), "moderately_caveated")

    def test_classify_heavily_caveated(self):
        self.assertEqual(self.wcd.classify(0.25), "heavily_caveated")
        self.assertEqual(self.wcd.classify(0.35), "heavily_caveated")
        self.assertEqual(self.wcd.classify(0.449), "heavily_caveated")

    def test_classify_legally_saturated(self):
        self.assertEqual(self.wcd.classify(0.45), "legally_saturated")
        self.assertEqual(self.wcd.classify(0.60), "legally_saturated")
        self.assertEqual(self.wcd.classify(1.0), "legally_saturated")

    # ── Full measure integration ──

    def test_measure_legal_text(self):
        text = (
            "This product is provided as-is without warranty. "
            "The company shall not be liable for damages. "
            "Results may vary depending on your setup. "
            "This is not legal advice. "
            "Consult a lawyer before proceeding. "
            "Features are subject to change without notice. "
            "Information is current as of January 2026. "
            "This guide is for informational purposes only. "
            "The list is not exhaustive. "
            "This does not cover all scenarios."
        )
        result = self.wcd.measure(text)
        self.assertIn("caveat_density_index", result)
        self.assertIn("classification", result)
        self.assertGreater(result["caveat_density_index"], 0.10)
        self.assertIn(
            result["classification"],
            ["moderately_caveated", "heavily_caveated", "legally_saturated"],
        )

    def test_measure_narrative_text(self):
        text = (
            "The morning sun cast long shadows across the garden. "
            "She knelt beside the rose bushes, examining the new growth. "
            "A cardinal landed on the fence, tilted its head, and flew away. "
            "The soil was dark and rich after last night's rain. "
            "She worked slowly, methodically, pulling weeds by the root. "
            "By noon the garden looked transformed."
        )
        result = self.wcd.measure(text)
        self.assertEqual(result["caveat_density_index"], 0.0)
        self.assertEqual(result["classification"], "unencumbered")

    def test_measure_mixed_text(self):
        text = (
            "This tool improves performance significantly. "
            "Results may vary depending on your hardware. "
            "The algorithm processes data in linear time. "
            "Not guaranteed to work on all platforms. "
            "She tested it on three different systems."
        )
        result = self.wcd.measure(text)
        self.assertGreater(result["caveat_density_index"], 0.0)
        self.assertLess(result["caveat_density_index"], 0.5)

    def test_measure_returns_all_keys(self):
        result = self.wcd.measure("Hello world.")
        expected_keys = {
            "liability_disclaimer_rate",
            "result_qualifier_rate",
            "professional_advice_rate",
            "warranty_limitation_rate",
            "temporal_restriction_rate",
            "scope_limitation_rate",
            "caveat_density_index",
            "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_measure_values_are_rounded(self):
        text = "Results may vary. Not liable for damages. Consult a doctor."
        result = self.wcd.measure(text)
        for key, value in result.items():
            if key != "classification":
                # Check that value has at most 4 decimal places
                self.assertEqual(value, round(value, 4))

    # ── Orthogonality smoke tests ──

    def test_hedging_text_low_caveat(self):
        """Hedging language (perhaps, possibly, may) should not trigger caveat patterns."""
        text = (
            "Perhaps the results are accurate. "
            "It is possible that the method works. "
            "The data might suggest a correlation. "
            "We may have found a solution."
        )
        result = self.wcd.measure(text)
        self.assertLess(result["caveat_density_index"], 0.10)

    def test_qualifier_text_low_caveat(self):
        """Intensity qualifiers (very, extremely) should not trigger caveat patterns."""
        text = (
            "The method is very effective. "
            "Results are extremely consistent. "
            "The approach is quite reliable. "
            "Performance is remarkably stable."
        )
        result = self.wcd.measure(text)
        self.assertLess(result["caveat_density_index"], 0.10)

    def test_imperative_text_low_caveat(self):
        """Imperatives (do this, run that) should not trigger caveat patterns."""
        text = (
            "Run the tests first. "
            "Check the output carefully. "
            "Make sure to save your work. "
            "Don't forget to commit your changes."
        )
        result = self.wcd.measure(text)
        self.assertLess(result["caveat_density_index"], 0.10)


# ── Boundary and edge cases ──────────────────────────────────────────


class TestBoundaryCases(unittest.TestCase):
    def setUp(self):
        self.wcd = WriterCaveatDensity()

    def test_single_word(self):
        result = self.wcd.measure("Hello.")
        self.assertEqual(result["caveat_density_index"], 0.0)

    def test_repeated_caveats(self):
        text = "Results may vary. " * 50
        result = self.wcd.measure(text)
        self.assertGreater(result["caveat_density_index"], 0.0)

    def test_very_long_text(self):
        caveats = [
            "Not liable for damages.",
            "Results may vary.",
            "Consult a doctor.",
            "Subject to change.",
            "For informational purposes only.",
            "The sun rose in the east.",
        ] * 20
        text = " ".join(caveats)
        result = self.wcd.measure(text)
        self.assertIn("classification", result)
        self.assertGreater(result["caveat_density_index"], 0.0)

    def test_mixed_languages(self):
        text = "这是免责声明。Not liable for damages. 结果可能不同。"
        result = self.wcd.measure(text)
        # Should still detect the English caveat
        self.assertGreater(result["liability_disclaimer_rate"], 0.0)

    def test_newlines_and_formatting(self):
        text = "Not liable for damages.\nResults may vary.\n\nConsult a doctor."
        result = self.wcd.measure(text)
        self.assertGreater(result["caveat_density_index"], 0.0)

    def test_case_sensitivity(self):
        text_lower = "results may vary. not liable for damages."
        text_upper = "RESULTS MAY VARY. NOT LIABLE FOR DAMAGES."
        r_lower = self.wcd.measure(text_lower)
        r_upper = self.wcd.measure(text_upper)
        self.assertEqual(r_lower["caveat_density_index"], r_upper["caveat_density_index"])


if __name__ == "__main__":
    unittest.main()
