#!/usr/bin/env python3
"""Tests for writer_verbosity module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_verbosity import (
    VerbosityResult,
    measure_verbosity,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_verbosity("")
        assert r.verbosity_index == 0.0
        assert r.classification == "lean"

    def test_whitespace_only(self):
        r = measure_verbosity("   \n\n   ")
        assert r.verbosity_index == 0.0

    def test_single_word(self):
        r = measure_verbosity("Hello.")
        assert r.classification == "lean"

    def test_no_filler_plain_sentence(self):
        r = measure_verbosity("The committee approved the budget.")
        assert r.filler_phrase_count == 0
        assert r.redundancy_count == 0
        assert r.pleonasm_count == 0


# ── lean prose ─────────────────────────────────────────────────


class TestLeanProse:
    LEAN = (
        "The engine failed. "
        "Smoke rose from the hood. "
        "Maria pulled over. "
        "She called a tow truck. "
        "The driver arrived in twenty minutes. "
        "He hooked the car to his truck. "
        "They drove to the nearest garage."
    )

    def test_lean_classification(self):
        r = measure_verbosity(self.LEAN)
        assert r.classification in ("lean", "economical")

    def test_low_filler(self):
        r = measure_verbosity(self.LEAN)
        assert r.filler_phrase_count == 0

    def test_low_nominalizations(self):
        r = measure_verbosity(self.LEAN)
        assert r.nominalization_count <= 1

    def test_low_redundancies(self):
        r = measure_verbosity(self.LEAN)
        assert r.redundancy_count == 0

    def test_low_hedges(self):
        r = measure_verbosity(self.LEAN)
        assert r.verbosity_hedge_count == 0


# ── filler phrases ─────────────────────────────────────────────


class TestFillerPhrases:
    def test_in_order_to(self):
        r = measure_verbosity(
            "We rewrote the code in order to fix the bug."
        )
        assert r.filler_phrase_count >= 1

    def test_due_to_the_fact_that(self):
        r = measure_verbosity(
            "The server crashed due to the fact that memory was full."
        )
        assert r.filler_phrase_count >= 1

    def test_it_is_important_to_note_that(self):
        r = measure_verbosity(
            "It is important to note that the API changed."
        )
        assert r.filler_phrase_count >= 1

    def test_for_the_purpose_of(self):
        r = measure_verbosity(
            "We convened for the purpose of discussing the roadmap."
        )
        assert r.filler_phrase_count >= 1

    def test_the_fact_that(self):
        r = measure_verbosity(
            "The fact that the build passed is encouraging."
        )
        assert r.filler_phrase_count >= 1

    def test_multiple_fillers(self):
        text = (
            "In order to complete the project, it is important to note that "
            "we need resources. Due to the fact that budgets are tight, "
            "for the purpose of efficiency, we should consolidate."
        )
        r = measure_verbosity(text)
        assert r.filler_phrase_count >= 4

    def test_no_filler_in_short_form(self):
        r = measure_verbosity("To fix the bug, we rewrote the code.")
        assert r.filler_phrase_count == 0


# ── nominalizations ────────────────────────────────────────────


class TestNominalizations:
    def test_tion_suffix(self):
        r = measure_verbosity(
            "The implementation of the solution requires careful consideration."
        )
        assert r.nominalization_count >= 2

    def test_ment_suffix(self):
        r = measure_verbosity(
            "The development of the agreement took months."
        )
        assert r.nominalization_count >= 1

    def test_ness_suffix(self):
        r = measure_verbosity(
            "The darkness of the situation affected everyone's awareness."
        )
        assert r.nominalization_count >= 1

    def test_short_words_excluded(self):
        # "act", "run", "ion" — short tokens should not be counted
        r = measure_verbosity("The act was done.")
        assert r.nominalization_count == 0

    def test_no_nominalizations(self):
        r = measure_verbosity("We built the system to run fast.")
        assert r.nominalization_count == 0


# ── redundancies ───────────────────────────────────────────────


class TestRedundancies:
    def test_very_unique(self):
        r = measure_verbosity("This is a very unique opportunity.")
        assert r.redundancy_count >= 1

    def test_past_history(self):
        r = measure_verbosity("Looking at the past history of the project.")
        assert r.redundancy_count >= 1

    def test_exact_same(self):
        r = measure_verbosity("We got the exact same result.")
        assert r.redundancy_count >= 1

    def test_future_plans(self):
        r = measure_verbosity("What are your future plans?")
        assert r.redundancy_count >= 1

    def test_close_proximity(self):
        r = measure_verbosity("The two servers are in close proximity.")
        assert r.redundancy_count >= 1

    def test_completely_eliminate(self):
        r = measure_verbosity("We need to completely eliminate the bug.")
        assert r.redundancy_count >= 1

    def test_no_redundancy(self):
        r = measure_verbosity("The server is in the rack.")
        assert r.redundancy_count == 0


# ── pleonasms ──────────────────────────────────────────────────


class TestPleonasms:
    def test_advance_planning(self):
        r = measure_verbosity("Advance planning is essential.")
        assert r.pleonasm_count >= 1

    def test_added_bonus(self):
        r = measure_verbosity("As an added bonus, the tool is free.")
        assert r.pleonasm_count >= 1

    def test_basic_fundamentals(self):
        r = measure_verbosity("Let's review the basic fundamentals.")
        assert r.pleonasm_count >= 1

    def test_revert_back(self):
        r = measure_verbosity("Please revert back to the previous commit.")
        assert r.pleonasm_count >= 1

    def test_return_back(self):
        r = measure_verbosity("Return back to the main screen.")
        assert r.pleonasm_count >= 1

    def test_true_fact(self):
        r = measure_verbosity("It is a true fact that the build passed.")
        assert r.pleonasm_count >= 1

    def test_no_pleonasm(self):
        r = measure_verbosity("The planning phase is complete.")
        assert r.pleonasm_count == 0


# ── verbosity hedges ──────────────────────────────────────────


class TestVerbosityHedges:
    def test_basically(self):
        r = measure_verbosity("Basically, the system works.")
        assert r.verbosity_hedge_count >= 1

    def test_essentially(self):
        r = measure_verbosity("It is essentially a wrapper.")
        assert r.verbosity_hedge_count >= 1

    def test_actually(self):
        r = measure_verbosity("Actually, the fix is simpler.")
        assert r.verbosity_hedge_count >= 1

    def test_in_fact(self):
        r = measure_verbosity("In fact, the tests already cover this.")
        assert r.verbosity_hedge_count >= 1

    def test_sort_of(self):
        r = measure_verbosity("It sort of works in practice.")
        assert r.verbosity_hedge_count >= 1

    def test_kind_of(self):
        r = measure_verbosity("The output is kind of correct.")
        assert r.verbosity_hedge_count >= 1

    def test_to_some_extent(self):
        r = measure_verbosity("To some extent, the model generalizes.")
        assert r.verbosity_hedge_count >= 1

    def test_no_hedges(self):
        r = measure_verbosity("The system processes 500 requests per second.")
        assert r.verbosity_hedge_count == 0


# ── composite and classification ────────────────────────────────


class TestCompositeAndClassification:
    def test_lean_index_range(self):
        text = (
            "The dog ran. The cat slept. Birds flew. "
            "Rain fell. Wind blew. Leaves dropped."
        )
        r = measure_verbosity(text)
        assert 0.0 <= r.verbosity_index < 0.30

    def test_bloated_text(self):
        text = (
            "It is important to note that, due to the fact that the system "
            "is basically a legacy application, for the purpose of maintaining "
            "stability, in order to ensure reliability, it is essential that "
            "we basically implement a comprehensive testing infrastructure. "
            "The implementation of such a solution requires careful consideration. "
            "In fact, the development of the testing framework is absolutely essential. "
            "Basically, for all intents and purposes, the utilization of advanced "
            "methodologies is fundamentally important."
        )
        r = measure_verbosity(text)
        assert r.verbosity_index > 0.30

    def test_index_bounded(self):
        # Even maximally padded text shouldn't exceed 1.0
        text = "In order to " * 50 + "."
        r = measure_verbosity(text)
        assert r.verbosity_index <= 1.0

    def test_classification_values(self):
        valid = {"lean", "economical", "conversational", "verbose", "bloated"}
        r = measure_verbosity("Some text here.")
        assert r.classification in valid


# ── function word ratio ────────────────────────────────────────


class TestFunctionWordRatio:
    def test_high_function_word_ratio(self):
        # Lots of prepositions, articles, auxiliaries
        text = (
            "The cat is on the mat in the room at the end of the hall."
        )
        r = measure_verbosity(text)
        assert r.function_word_ratio > 0.40

    def test_low_function_word_ratio(self):
        # Mostly content words
        text = "Server crashed. Database failed. Network timeout. Restart required."
        r = measure_verbosity(text)
        assert r.function_word_ratio < 0.40

    def test_content_words_positive(self):
        r = measure_verbosity("The quick brown fox jumped.")
        assert r.content_word_count > 0


# ── metadata ────────────────────────────────────────────────────


class TestMetadata:
    def test_sentence_count(self):
        r = measure_verbosity("One. Two. Three.")
        assert r.total_sentences == 3

    def test_word_count(self):
        r = measure_verbosity("The quick brown fox jumped over the lazy dog.")
        assert r.total_words == 9

    def test_details_dict_populated(self):
        r = measure_verbosity("Some text with basically no filler.")
        assert "verbosity_index" in r.details
        assert "classification" in r.details
        assert "function_word_ratio" in r.details


# ── rate calculations ──────────────────────────────────────────


class TestRateCalculations:
    def test_filler_rate_scales_with_sentences(self):
        # One filler in one sentence vs one filler in ten sentences
        short = "In order to proceed, we need approval."
        long = (
            "The server started. The database connected. The cache warmed. "
            "The queue drained. The log rotated. The backup completed. "
            "The monitor pinged. The alert fired. The ticket closed. "
            "In order to proceed, we need approval."
        )
        rs = measure_verbosity(short)
        rl = measure_verbosity(long)
        assert rs.filler_phrase_rate > rl.filler_phrase_rate

    def test_hedge_rate_scales(self):
        text = "Basically, it works. Actually, it scales. Essentially, done."
        r = measure_verbosity(text)
        assert r.verbosity_hedge_rate > 50.0  # 3 hedges in 3 sentences


# ── orthogonality ──────────────────────────────────────────────


class TestOrthogonality:
    def test_verbosity_independent_of_length(self):
        # Short verbose text vs long lean text
        short_verbose = "It is important to note that basically it works."
        long_lean = (
            "The engine roared. Pistons fired. Oil circulated. "
            "Coolant flowed. The gauge climbed. The driver shifted. "
            "Tires gripped. The corner approached. Brakes engaged. "
            "The apex passed. The straight opened. The throttle dropped."
        )
        rs = measure_verbosity(short_verbose)
        rl = measure_verbosity(long_lean)
        assert rs.verbosity_index > rl.verbosity_index

    def test_technical_text_low_verbosity(self):
        # Precise technical language is lean
        text = (
            "The function accepts a UTF-8 byte slice. "
            "It returns a parsed AST or a syntax error. "
            "Errors include line number and column offset."
        )
        r = measure_verbosity(text)
        assert r.classification in ("lean", "economical")


# ── edge cases ─────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_sentence(self):
        r = measure_verbosity("The build passed.")
        assert r.total_sentences >= 1

    def test_no_period(self):
        r = measure_verbosity("The build passed")
        assert r.total_sentences >= 1

    def test_mixed_case_fillers(self):
        r = measure_verbosity("IN ORDER TO proceed, we need approval.")
        assert r.filler_phrase_count >= 1

    def test_newlines_as_sentence_breaks(self):
        text = "Line one.\nLine two.\nLine three."
        r = measure_verbosity(text)
        assert r.total_sentences >= 3

    def test_details_keys_complete(self):
        r = measure_verbosity("Test text.")
        expected_keys = {
            "function_word_ratio",
            "filler_phrase_rate",
            "nominalization_rate",
            "redundancy_rate",
            "pleonasm_rate",
            "verbosity_hedge_rate",
            "verbosity_index",
            "classification",
        }
        assert set(r.details.keys()) == expected_keys
