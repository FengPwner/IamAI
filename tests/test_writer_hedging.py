#!/usr/bin/env python3
"""Tests for writer_hedging module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_hedging import (
    HedgingResult,
    measure_hedging,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_hedging("")
        assert r.hedging_index == 0.0
        assert r.classification == "assertive"

    def test_whitespace_only(self):
        r = measure_hedging("   \n\n   ")
        assert r.hedging_index == 0.0

    def test_single_word(self):
        r = measure_hedging("Hello.")
        assert r.classification == "assertive"

    def test_no_hedges_plain_sentence(self):
        r = measure_hedging("The committee approved the budget.")
        assert r.total_hedges == 0
        assert r.hedging_index == 0.0


# ── assertive prose ─────────────────────────────────────────────


class TestAssertiveProse:
    ASSERTIVE = (
        "The engine failed. "
        "Smoke rose from the hood. "
        "Maria pulled over. "
        "She called a tow truck. "
        "The driver arrived in twenty minutes. "
        "He hooked the car to his truck. "
        "They drove to the nearest garage."
    )

    def test_assertive_classification(self):
        r = measure_hedging(self.ASSERTIVE)
        assert r.classification in ("assertive", "measured")

    def test_zero_epistemic(self):
        r = measure_hedging(self.ASSERTIVE)
        assert r.epistemic_count == 0

    def test_zero_evidential(self):
        r = measure_hedging(self.ASSERTIVE)
        assert r.evidential_count == 0

    def test_zero_degree(self):
        r = measure_hedging(self.ASSERTIVE)
        assert r.degree_count == 0

    def test_zero_frequency(self):
        r = measure_hedging(self.ASSERTIVE)
        assert r.frequency_count == 0

    def test_zero_proportion(self):
        r = measure_hedging(self.ASSERTIVE)
        assert r.proportion_count == 0


# ── epistemic hedges ────────────────────────────────────────────


class TestEpistemicHedges:
    def test_might(self):
        r = measure_hedging("This might work.")
        assert r.epistemic_count >= 1

    def test_could(self):
        r = measure_hedging("We could try that.")
        assert r.epistemic_count >= 1

    def test_perhaps(self):
        r = measure_hedging("Perhaps the answer lies elsewhere.")
        assert r.epistemic_count >= 1

    def test_maybe(self):
        r = measure_hedging("Maybe we should reconsider.")
        assert r.epistemic_count >= 1

    def test_possibly(self):
        r = measure_hedging("This is possibly the best approach.")
        assert r.epistemic_count >= 1

    def test_probably(self):
        r = measure_hedging("It will probably rain tomorrow.")
        assert r.epistemic_count >= 1

    def test_likely(self):
        r = measure_hedging("The outcome is likely positive.")
        assert r.epistemic_count >= 1

    def test_seems(self):
        r = measure_hedging("The code seems correct.")
        assert r.epistemic_count >= 1

    def test_appears(self):
        r = measure_hedging("The system appears stable.")
        assert r.epistemic_count >= 1

    def test_tends_to(self):
        r = measure_hedging("This algorithm tends to converge quickly.")
        assert r.epistemic_count >= 1

    def test_arguably(self):
        r = measure_hedging("This is arguably the best solution.")
        assert r.epistemic_count >= 1

    def test_not_necessarily(self):
        r = measure_hedging("That is not necessarily true.")
        assert r.epistemic_count >= 1

    def test_conceivably(self):
        r = measure_hedging("One could conceivably do this.")
        assert r.epistemic_count >= 2  # "could" + "conceivably"

    def test_it_seems(self):
        r = measure_hedging("It would seem that the data is correct.")
        assert r.epistemic_count >= 1

    def test_multiple_epistemic(self):
        text = (
            "The results might suggest a trend. "
            "It could perhaps indicate causation. "
            "We may possibly be wrong."
        )
        r = measure_hedging(text)
        assert r.epistemic_count >= 4


# ── evidential hedges ───────────────────────────────────────────


class TestEvidentialHedges:
    def test_apparently(self):
        r = measure_hedging("Apparently, the server crashed.")
        assert r.evidential_count >= 1

    def test_reportedly(self):
        r = measure_hedging("Reportedly, the deal closed yesterday.")
        assert r.evidential_count >= 1

    def test_allegedly(self):
        r = measure_hedging("The CEO allegedly approved the plan.")
        assert r.evidential_count >= 1

    def test_supposedly(self):
        r = measure_hedging("Supposedly, the fix was deployed.")
        assert r.evidential_count >= 1

    def test_ostensibly(self):
        r = measure_hedging("Ostensibly, the system is secure.")
        assert r.evidential_count >= 1

    def test_seemingly(self):
        r = measure_hedging("The seemingly simple task took hours.")
        assert r.evidential_count >= 1

    def test_reputedly(self):
        r = measure_hedging("The library is reputedly fast.")
        assert r.evidential_count >= 1

    def test_purportedly(self):
        r = measure_hedging("The purportedly fixed bug reappeared.")
        assert r.evidential_count >= 1

    def test_it_is_said(self):
        r = measure_hedging("It is said that practice makes perfect.")
        assert r.evidential_count >= 1

    def test_it_is_believed(self):
        r = measure_hedging("It is believed that the market will recover.")
        assert r.evidential_count >= 1

    def test_word_has_it(self):
        r = measure_hedging("Word has it that the merger is imminent.")
        assert r.evidential_count >= 1

    def test_multiple_evidential(self):
        text = (
            "Apparently the fix works. "
            "Reportedly, users are happy. "
            "The team allegedly tested it."
        )
        r = measure_hedging(text)
        assert r.evidential_count >= 3


# ── frequency hedges ────────────────────────────────────────────


class TestFrequencyHedges:
    def test_sometimes(self):
        r = measure_hedging("Sometimes the tests fail.")
        assert r.frequency_count >= 1

    def test_occasionally(self):
        r = measure_hedging("We occasionally see timeouts.")
        assert r.frequency_count >= 1

    def test_often(self):
        r = measure_hedging("Developers often skip tests.")
        assert r.frequency_count >= 1

    def test_frequently(self):
        r = measure_hedging("The server frequently restarts.")
        assert r.frequency_count >= 1

    def test_rarely(self):
        r = measure_hedging("Bugs rarely appear in production.")
        assert r.frequency_count >= 1

    def test_seldom(self):
        r = measure_hedging("We seldom see this error.")
        assert r.frequency_count >= 1

    def test_at_times(self):
        r = measure_hedging("At times the system is slow.")
        assert r.frequency_count >= 1

    def test_from_time_to_time(self):
        r = measure_hedging("From time to time, we get alerts.")
        assert r.frequency_count >= 1

    def test_now_and_then(self):
        r = measure_hedging("Now and then, the cache is stale.")
        assert r.frequency_count >= 1

    def test_intermittently(self):
        r = measure_hedging("The service intermittently drops.")
        assert r.frequency_count >= 1

    def test_sporadically(self):
        r = measure_hedging("Errors occur sporadically.")
        assert r.frequency_count >= 1

    def test_multiple_frequency(self):
        text = (
            "Sometimes the API is slow. "
            "We occasionally get timeouts. "
            "Users rarely complain though."
        )
        r = measure_hedging(text)
        assert r.frequency_count >= 3


# ── degree hedges ───────────────────────────────────────────────


class TestDegreeHedges:
    def test_somewhat(self):
        r = measure_hedging("The results were somewhat surprising.")
        assert r.degree_count >= 1

    def test_slightly(self):
        r = measure_hedging("Performance is slightly better now.")
        assert r.degree_count >= 1

    def test_rather(self):
        r = measure_hedging("The code is rather complex.")
        assert r.degree_count >= 1

    def test_fairly(self):
        r = measure_hedging("The test suite is fairly comprehensive.")
        assert r.degree_count >= 1

    def test_quite(self):
        r = measure_hedging("The response was quite fast.")
        assert r.degree_count >= 1

    def test_more_or_less(self):
        r = measure_hedging("The feature is more or less complete.")
        assert r.degree_count >= 1

    def test_kind_of(self):
        r = measure_hedging("It kind of works.")
        assert r.degree_count >= 1

    def test_sort_of(self):
        r = measure_hedging("It sort of makes sense.")
        assert r.degree_count >= 1

    def test_a_bit(self):
        r = measure_hedging("The output is a bit slow.")
        assert r.degree_count >= 1

    def test_a_little(self):
        r = measure_hedging("The API is a little complicated.")
        assert r.degree_count >= 1

    def test_mildly(self):
        r = measure_hedging("The warning was mildly concerning.")
        assert r.degree_count >= 1

    def test_moderately(self):
        r = measure_hedging("The load was moderately high.")
        assert r.degree_count >= 1

    def test_reasonably(self):
        r = measure_hedging("The latency is reasonably low.")
        assert r.degree_count >= 1

    def test_not_entirely(self):
        r = measure_hedging("The solution is not entirely correct.")
        assert r.degree_count >= 1

    def test_multiple_degree(self):
        text = (
            "The code is somewhat complex. "
            "Performance is slightly better. "
            "Tests are fairly comprehensive."
        )
        r = measure_hedging(text)
        assert r.degree_count >= 3


# ── proportion hedges ───────────────────────────────────────────


class TestProportionHedges:
    def test_mostly(self):
        r = measure_hedging("The code is mostly clean.")
        assert r.proportion_count >= 1

    def test_largely(self):
        r = measure_hedging("The fix was largely successful.")
        assert r.proportion_count >= 1

    def test_partly(self):
        r = measure_hedging("The delay was partly our fault.")
        assert r.proportion_count >= 1

    def test_partially(self):
        r = measure_hedging("The migration is partially complete.")
        assert r.proportion_count >= 1

    def test_generally(self):
        r = measure_hedging("Generally, users prefer the new UI.")
        assert r.proportion_count >= 1

    def test_typically(self):
        r = measure_hedging("Typically, deploys take five minutes.")
        assert r.proportion_count >= 1

    def test_usually(self):
        r = measure_hedging("The pipeline usually finishes on time.")
        assert r.proportion_count >= 1

    def test_for_the_most_part(self):
        r = measure_hedging("For the most part, the system works.")
        assert r.proportion_count >= 1

    def test_in_general(self):
        r = measure_hedging("In general, the approach is sound.")
        assert r.proportion_count >= 1

    def test_as_a_rule(self):
        r = measure_hedging("As a rule, we test before deploying.")
        assert r.proportion_count >= 1

    def test_more_often_than_not(self):
        r = measure_hedging("More often than not, the fix works.")
        assert r.proportion_count >= 1

    def test_broadly_speaking(self):
        r = measure_hedging("Broadly speaking, the design is solid.")
        assert r.proportion_count >= 1

    def test_in_most_cases(self):
        r = measure_hedging("In most cases, caching helps.")
        assert r.proportion_count >= 1

    def test_multiple_proportion(self):
        text = (
            "Generally the code is clean. "
            "Typically tests pass on first try. "
            "For the most part, the system is stable."
        )
        r = measure_hedging(text)
        assert r.proportion_count >= 3


# ── composite index ─────────────────────────────────────────────


class TestCompositeIndex:
    def test_index_range(self):
        """Index must be between 0.0 and 1.0."""
        text = (
            "Perhaps the results might possibly suggest something. "
            "It could conceivably indicate a trend. "
            "We may arguably be somewhat correct. "
            "The data is largely, generally, mostly consistent. "
            "Sometimes, occasionally, frequently we see outliers."
        )
        r = measure_hedging(text)
        assert 0.0 <= r.hedging_index <= 1.0

    def test_high_hedging(self):
        """A text packed with hedges should score high."""
        text = (
            "Perhaps the system might possibly be somewhat stable. "
            "It could conceivably tend to generally work. "
            "We may arguably be largely, mostly correct. "
            "Sometimes, occasionally, the data is fairly consistent. "
            "It seems the results could probably be rather reliable. "
            "Maybe the team might possibly have been slightly cautious. "
            "The outcome is likely somewhat positive. "
            "It appears the fix may be partially effective. "
            "Broadly speaking, the approach is somewhat sound. "
            "Generally, the method tends to be fairly efficient."
        )
        r = measure_hedging(text)
        assert r.hedging_index > 0.4
        assert r.classification in ("cautious", "tentative", "noncommittal")

    def test_zero_hedging(self):
        """A text with zero hedges should score 0."""
        text = (
            "The function returns an integer. "
            "The server crashed at midnight. "
            "Alice wrote the parser. "
            "Bob fixed the bug. "
            "The deploy succeeded."
        )
        r = measure_hedging(text)
        assert r.hedging_index == 0.0
        assert r.classification == "assertive"

    def test_measured_classification(self):
        """A moderately hedged text should not be 'assertive'."""
        text = (
            "The results suggest a correlation. "
            "The data appears consistent. "
            "We generally follow this pattern. "
            "The implementation works correctly."
        )
        r = measure_hedging(text)
        assert r.classification in ("measured", "cautious", "tentative")


# ── classification boundaries ───────────────────────────────────


class TestClassification:
    def test_all_classifications_exist(self):
        """Only valid classification labels should appear."""
        valid = {"assertive", "measured", "cautious", "tentative", "noncommittal"}
        for text in [
            "The code works.",
            "The code might work.",
            "Perhaps the code could somewhat work.",
            (
                "Perhaps the system might possibly be somewhat stable. "
                "It could conceivably tend to generally work. "
                "We may arguably be largely, mostly correct. "
                "Sometimes the data is fairly consistent. "
                "It seems the results could probably be rather reliable. "
                "Maybe the team might have been slightly cautious."
            ),
        ]:
            r = measure_hedging(text)
            assert r.classification in valid


# ── rate calculations ───────────────────────────────────────────


class TestRateCalculations:
    def test_rate_scales_with_sentences(self):
        """Rates should be per 100 sentences."""
        text = (
            "Perhaps this works. " * 50
            + "Nothing here. " * 50
        )
        r = measure_hedging(text)
        # 50 "perhaps" in ~100 sentences → epistemic_rate ≈ 50
        assert r.epistemic_rate > 30

    def test_total_hedges_is_sum(self):
        """Total hedges should equal sum of all channel counts."""
        text = (
            "Perhaps the system might work. "
            "Generally it is somewhat stable. "
            "Sometimes it appears slow."
        )
        r = measure_hedging(text)
        expected = (
            r.epistemic_count
            + r.evidential_count
            + r.frequency_count
            + r.degree_count
            + r.proportion_count
        )
        assert r.total_hedges == expected

    def test_details_dict_matches_fields(self):
        """Details dict should mirror result fields."""
        text = (
            "Perhaps the data might be somewhat consistent. "
            "Generally the results appear reliable."
        )
        r = measure_hedging(text)
        assert r.details["hedging_index"] == r.hedging_index
        assert r.details["classification"] == r.classification
        assert r.details["epistemic_rate"] == r.epistemic_rate
        assert r.details["evidential_rate"] == r.evidential_rate
        assert r.details["frequency_rate"] == r.frequency_rate
        assert r.details["degree_rate"] == r.degree_rate
        assert r.details["proportion_rate"] == r.proportion_rate


# ── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_sentence_with_hedge(self):
        r = measure_hedging("Maybe it works.")
        assert r.epistemic_count >= 1
        assert r.total_sentences == 1

    def test_long_text_no_hedges(self):
        sentences = "The server processed the request. " * 100
        r = measure_hedging(sentences)
        assert r.hedging_index == 0.0
        assert r.classification == "assertive"

    def test_case_insensitive(self):
        r_lower = measure_hedging("perhaps it works.")
        r_upper = measure_hedging("PERHAPS IT WORKS.")
        r_mixed = measure_hedging("Perhaps It Works.")
        assert r_lower.epistemic_count == r_upper.epistemic_count
        assert r_lower.epistemic_count == r_mixed.epistemic_count

    def test_repeated_hedges_same_sentence(self):
        r = measure_hedging("Perhaps maybe possibly it might work.")
        assert r.epistemic_count >= 4

    def test_mixed_channels(self):
        """A single sentence can trigger hedges in multiple channels."""
        r = measure_hedging(
            "Generally, the system sometimes appears to be somewhat slow."
        )
        assert r.proportion_count >= 1  # "generally"
        assert r.frequency_count >= 1   # "sometimes"
        assert r.epistemic_count >= 1    # "appears"
        assert r.degree_count >= 1       # "somewhat"

    def test_metadata_populated(self):
        text = "Perhaps the results might be somewhat positive."
        r = measure_hedging(text)
        assert r.total_sentences > 0
        assert r.total_words > 0
        assert r.total_hedges > 0

    def test_no_crash_on_special_chars(self):
        r = measure_hedging("... !!! ??? ---")
        assert r.hedging_index == 0.0

    def test_newlines_and_tabs(self):
        text = "Perhaps\n\tthe\tresults\nmight work."
        r = measure_hedging(text)
        assert r.epistemic_count >= 2


# ── orthogonality sanity ────────────────────────────────────────


class TestOrthogonality:
    def test_technical_assertive_text(self):
        """Technical documentation should score low on hedging."""
        text = (
            "The function takes two arguments and returns a string. "
            "Pass None to use the default value. "
            "The timeout parameter is in seconds. "
            "Errors raise a ValueError exception."
        )
        r = measure_hedging(text)
        assert r.classification in ("assertive", "measured")

    def test_academic_cautious_text(self):
        """Academic hedging: 'suggest', 'appear', 'may'."""
        text = (
            "The results suggest a possible correlation. "
            "The data appears to indicate a trend. "
            "This may be related to the sample size. "
            "Further research could clarify the relationship. "
            "The findings might support the hypothesis."
        )
        r = measure_hedging(text)
        assert r.epistemic_count >= 4
        assert r.hedging_index > 0.1
