#!/usr/bin/env python3
"""Tests for writer_nominalization_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_nominalization_density import (
    NominalizationDensityResult,
    NominalizationHit,
    measure_nominalization_density,
    _is_nominalization,
    _classify_suffix,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_nominalization_density("")
        assert r.classification == "unknown"
        assert r.nominalization_count == 0

    def test_whitespace_only(self):
        r = measure_nominalization_density("   \n\n   ")
        assert r.classification == "unknown"

    def test_no_words(self):
        r = measure_nominalization_density("!@#$%^&*()")
        assert r.classification == "unknown"

    def test_single_word_not_nominalization(self):
        r = measure_nominalization_density("Hello.")
        assert r.nominalization_count == 0

    def test_single_word_nominalization(self):
        r = measure_nominalization_density("Implementation.")
        assert r.nominalization_count == 1
        assert r.total_words == 1


# ── _is_nominalization function ────────────────────────────────


class TestIsNominalization:
    def test_tion_suffix(self):
        assert _is_nominalization("implementation") is True

    def test_sion_suffix(self):
        assert _is_nominalization("observation") is True

    def test_ment_suffix(self):
        assert _is_nominalization("development") is True

    def test_ness_suffix(self):
        assert _is_nominalization("happiness") is True

    def test_ity_suffix(self):
        assert _is_nominalization("clarity") is True

    def test_ence_suffix(self):
        assert _is_nominalization("independence") is True

    def test_ance_suffix(self):
        assert _is_nominalization("disturbance") is True

    def test_ism_suffix(self):
        assert _is_nominalization("determinism") is True

    def test_ist_suffix(self):
        assert _is_nominalization("determinist") is True

    def test_not_nominalization_plain_word(self):
        assert _is_nominalization("server") is False

    def test_not_nominalization_verb(self):
        assert _is_nominalization("running") is False

    def test_not_nominalization_adjective(self):
        assert _is_nominalization("quick") is False

    def test_too_short(self):
        assert _is_nominalization("it") is False

    def test_case_insensitive(self):
        assert _is_nominalization("Implementation") is True
        assert _is_nominalization("IMPLEMENTATION") is True


# ── exception list ──────────────────────────────────────────────


class TestExceptions:
    def test_nation_not_nominalization(self):
        assert _is_nominalization("nation") is False

    def test_action_not_nominalization(self):
        assert _is_nominalization("action") is False

    def test_station_not_nominalization(self):
        assert _is_nominalization("station") is False

    def test_moment_not_nominalization(self):
        assert _is_nominalization("moment") is False

    def test_cement_not_nominalization(self):
        assert _is_nominalization("cement") is False

    def test_pavement_not_nominalization(self):
        assert _is_nominalization("pavement") is False

    def test_city_not_nominalization(self):
        assert _is_nominalization("city") is False

    def test_witness_not_nominalization(self):
        assert _is_nominalization("witness") is False

    def test_mission_not_nominalization(self):
        assert _is_nominalization("mission") is False

    def test_passion_not_nominalization(self):
        assert _is_nominalization("passion") is False

    def test_artist_not_nominalization(self):
        assert _is_nominalization("artist") is False

    def test_tourist_not_nominalization(self):
        assert _is_nominalization("tourist") is False

    def test_baptism_not_nominalization(self):
        assert _is_nominalization("baptism") is False

    def test_hence_not_nominalization(self):
        assert _is_nominalization("hence") is False

    def test_fence_not_nominalization(self):
        assert _is_nominalization("fence") is False

    def test_dance_not_nominalization(self):
        assert _is_nominalization("dance") is False


# ── suffix classification ───────────────────────────────────────


class TestSuffixClassification:
    def test_tion(self):
        assert _classify_suffix("implementation") == "tion"

    def test_sion(self):
        assert _classify_suffix("expression") == "sion"

    def test_ment(self):
        assert _classify_suffix("development") == "ment"

    def test_ness(self):
        assert _classify_suffix("happiness") == "ness"

    def test_ity(self):
        assert _classify_suffix("clarity") == "ity"

    def test_ence(self):
        assert _classify_suffix("independence") == "ence"

    def test_ance(self):
        assert _classify_suffix("acceptance") == "ance"

    def test_ism(self):
        assert _classify_suffix("determinism") == "ism"

    def test_ist(self):
        assert _classify_suffix("determinist") == "ist"

    def test_no_suffix(self):
        assert _classify_suffix("server") == "none"


# ── nominalization rate ─────────────────────────────────────────


class TestNominalizationRate:
    def test_no_nominalizations(self):
        text = "The cat sat on the mat. The dog ran in the park."
        r = measure_nominalization_density(text)
        assert r.nominalization_count == 0
        assert r.nominalization_rate == 0.0

    def test_all_nominalizations(self):
        text = "Implementation observation development happiness clarity."
        r = measure_nominalization_density(text)
        assert r.nominalization_count == 5
        assert r.nominalization_rate == 100.0

    def test_mixed_text_rate(self):
        # 2 nominalizations in 10 words = 20 per 100
        text = (
            "The implementation of the new observation system "
            "was completed on time."
        )
        r = measure_nominalization_density(text)
        assert r.nominalization_count == 2
        assert r.nominalization_rate > 0

    def test_rate_calculation(self):
        # 1 nominalization in 10 words = 10 per 100
        text = "The server implementation was deployed at midnight last night again."
        r = measure_nominalization_density(text)
        assert r.nominalization_count == 1
        assert r.total_words == 10
        assert r.nominalization_rate == 10.0


# ── noun ratio ──────────────────────────────────────────────────


class TestNounRatio:
    def test_no_nouns(self):
        # All stop words / verbs
        text = "is are was were have has had do does did."
        r = measure_nominalization_density(text)
        assert r.nominalization_noun_ratio == 0.0

    def test_all_nominalizations_among_nouns(self):
        text = "Implementation observation development."
        r = measure_nominalization_density(text)
        # All words are nominalizations (and likely nouns)
        assert r.nominalization_noun_ratio > 0.5

    def test_mixed_nouns_and_nominalizations(self):
        text = (
            "The server crash showed a pattern of failure "
            "in the implementation."
        )
        r = measure_nominalization_density(text)
        assert r.nominalization_noun_ratio > 0
        assert r.nominalization_noun_ratio < 1.0


# ── suffix breakdown ────────────────────────────────────────────


class TestSuffixBreakdown:
    def test_multiple_suffixes(self):
        text = (
            "The implementation of the observation system "
            "showed development in clarity and resistance."
        )
        r = measure_nominalization_density(text)
        assert "tion" in r.suffix_breakdown or "sion" in r.suffix_breakdown
        assert r.nominalization_count >= 3

    def test_dominant_suffix(self):
        # Three -tion words, one -ment
        text = (
            "Implementation observation optimization development."
        )
        r = measure_nominalization_density(text)
        assert r.dominant_suffix == "tion"

    def test_no_nominalizations_dominant(self):
        text = "The cat sat on the mat."
        r = measure_nominalization_density(text)
        assert r.dominant_suffix == "none"


# ── density index ───────────────────────────────────────────────


class TestDensityIndex:
    def test_concrete_text_low_index(self):
        text = (
            "The dog chased the cat across the yard. "
            "The cat climbed the tree. The dog barked below."
        )
        r = measure_nominalization_density(text)
        assert r.density_index < 0.10

    def test_bureaucratic_text_high_index(self):
        text = (
            "The implementation of the optimization of the "
            "observation system requires the development of "
            "a clarification of the authorization mechanism "
            "and the establishment of a reconciliation process."
        )
        r = measure_nominalization_density(text)
        assert r.density_index > 0.30

    def test_index_range(self):
        text = "Implementation observation development happiness clarity."
        r = measure_nominalization_density(text)
        assert 0.0 <= r.density_index <= 1.0


# ── classification ──────────────────────────────────────────────


class TestClassification:
    def test_concrete(self):
        text = (
            "She ran to the store and bought bread. "
            "He cooked dinner and ate quickly."
        )
        r = measure_nominalization_density(text)
        assert r.classification in ("concrete", "lean")

    def test_bureaucratic(self):
        text = (
            "The implementation of the optimization of the "
            "observation system requires the development of "
            "a clarification of the authorization mechanism "
            "and the establishment of a reconciliation process."
        )
        r = measure_nominalization_density(text)
        assert r.classification in ("dense", "bureaucratic")

    def test_unknown_for_empty(self):
        r = measure_nominalization_density("")
        assert r.classification == "unknown"


# ── hits list ───────────────────────────────────────────────────


class TestHits:
    def test_hits_populated(self):
        text = "The implementation was an improvement."
        r = measure_nominalization_density(text)
        assert len(r.hits) >= 1
        assert all(isinstance(h, NominalizationHit) for h in r.hits)

    def test_hit_has_word(self):
        text = "Implementation of the system."
        r = measure_nominalization_density(text)
        words = [h.word for h in r.hits]
        assert "implementation" in words

    def test_hit_has_suffix(self):
        text = "Implementation of the system."
        r = measure_nominalization_density(text)
        suffixes = [h.suffix for h in r.hits]
        assert "tion" in suffixes

    def test_hit_has_position(self):
        text = "The quick implementation arrived."
        r = measure_nominalization_density(text)
        positions = [h.position for h in r.hits]
        assert 2 in positions  # "implementation" is word index 2


# ── real-world prose samples ────────────────────────────────────


class TestRealWorldProse:
    def test_hemingway_style(self):
        """Hemingway-esque prose should be concrete."""
        text = (
            "He sat at the table and drank his beer. "
            "The sun was hot. The road was dusty. "
            "He walked home slowly."
        )
        r = measure_nominalization_density(text)
        assert r.classification in ("concrete", "lean")

    def test_academic_style(self):
        """Academic prose should be moderate to dense."""
        text = (
            "The implementation of the investigation into the "
            "phenomenon of globalization requires a comprehensive "
            "understanding of the interconnection between economic "
            "development and cultural transformation."
        )
        r = measure_nominalization_density(text)
        assert r.nominalization_count >= 3
        assert r.classification in ("moderate", "dense", "bureaucratic")

    def test_technical_documentation(self):
        """Technical docs often have moderate nominalization."""
        text = (
            "The configuration requires the installation of "
            "the dependency before execution. Authorization "
            "is handled through token validation."
        )
        r = measure_nominalization_density(text)
        assert r.nominalization_count >= 2


# ── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_repeated_nominalization(self):
        text = "Implementation implementation implementation."
        r = measure_nominalization_density(text)
        assert r.nominalization_count == 3

    def test_nominalization_with_punctuation(self):
        text = "The implementation, the observation, and the development."
        r = measure_nominalization_density(text)
        assert r.nominalization_count == 3

    def test_mixed_case(self):
        text = "Implementation OBSERVATION Development."
        r = measure_nominalization_density(text)
        assert r.nominalization_count == 3

    def test_long_text(self):
        words = ["The server crashed."] * 100
        words.insert(50, "The implementation failed.")
        text = " ".join(words)
        r = measure_nominalization_density(text)
        assert r.nominalization_count == 1
        assert r.total_words > 100

    def test_single_sentence(self):
        text = "The decision was final."
        r = measure_nominalization_density(text)
        # "decision" ends in -sion but it's an exception
        # "final" is not a nominalization
        assert r.nominalization_count == 0
