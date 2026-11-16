#!/usr/bin/env python3
"""Tests for writer_pronoun_density module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_pronoun_density import (
    PronounDensityResult,
    measure_pronoun_density,
    _tokenize,
    _find_pronouns,
    _categorize,
    _count_special,
    _frequency_list,
    _person_balance_entropy,
    _classify,
    _dominant_person,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_pronoun_density("")
        assert r.total_pronouns == 0
        assert r.classification == "unknown"

    def test_whitespace_only(self):
        r = measure_pronoun_density("   \n\n   ")
        assert r.classification == "unknown"

    def test_single_word_no_pronoun(self):
        r = measure_pronoun_density("Hello.")
        assert r.total_pronouns == 0
        assert r.total_words == 1

    def test_single_pronoun(self):
        r = measure_pronoun_density("I.")
        assert r.total_pronouns == 1
        assert r.first_person_count == 1

    def test_numbers_only(self):
        r = measure_pronoun_density("123 456 789")
        assert r.total_pronouns == 0
        assert r.classification == "unknown"


# ── tokenization ────────────────────────────────────────────────


class TestTokenization:
    def test_simple_words(self):
        tokens = _tokenize("The cat sat on the mat")
        assert tokens == ["the", "cat", "sat", "on", "the", "mat"]

    def test_contractions(self):
        tokens = _tokenize("I'm happy and they're coming")
        assert "i" in tokens
        assert "they" in tokens

    def test_case_insensitive(self):
        tokens = _tokenize("I ME My")
        assert tokens == ["i", "me", "my"]

    def test_punctuation_stripped(self):
        tokens = _tokenize("Hello, world! How's it?")
        assert "hello" in tokens
        assert "world" in tokens

    def test_empty_input(self):
        tokens = _tokenize("")
        assert tokens == []


# ── pronoun finding ─────────────────────────────────────────────


class TestFindPronouns:
    def test_first_person(self):
        tokens = _tokenize("I told him about myself")
        pronouns = _find_pronouns(tokens)
        assert "i" in pronouns
        assert "him" in pronouns
        assert "myself" in pronouns

    def test_second_person(self):
        tokens = _tokenize("You should see yourself")
        pronouns = _find_pronouns(tokens)
        assert "you" in pronouns
        assert "yourself" in pronouns

    def test_third_person(self):
        tokens = _tokenize("She gave it to them")
        pronouns = _find_pronouns(tokens)
        assert "she" in pronouns
        assert "it" in pronouns
        assert "them" in pronouns

    def test_no_pronouns(self):
        tokens = _tokenize("The quick brown fox jumps")
        pronouns = _find_pronouns(tokens)
        assert pronouns == []


# ── categorization ──────────────────────────────────────────────


class TestCategorize:
    def test_mixed_persons(self):
        pronouns = ["i", "you", "he", "we", "they"]
        counts = _categorize(pronouns)
        assert counts["first"] == 2  # i, we
        assert counts["second"] == 1  # you
        assert counts["third"] == 2  # he, they

    def test_all_first(self):
        pronouns = ["i", "me", "my", "we", "us"]
        counts = _categorize(pronouns)
        assert counts["first"] == 5
        assert counts["second"] == 0
        assert counts["third"] == 0

    def test_empty(self):
        counts = _categorize([])
        assert counts == {"first": 0, "second": 0, "third": 0}


# ── special counts ──────────────────────────────────────────────


class TestCountSpecial:
    def test_possessive(self):
        pronouns = ["my", "your", "his", "her", "i", "you"]
        poss, refl = _count_special(pronouns)
        assert poss == 4  # my, your, his, her
        assert refl == 0

    def test_reflexive(self):
        pronouns = ["myself", "yourself", "himself", "i", "you"]
        poss, refl = _count_special(pronouns)
        assert refl == 3
        # myself is also possessive? No — "myself" is reflexive, not possessive
        assert poss == 0

    def test_mixed(self):
        pronouns = ["my", "myself", "their", "themselves"]
        poss, refl = _count_special(pronouns)
        assert poss == 2  # my, their
        assert refl == 2  # myself, themselves


# ── frequency list ──────────────────────────────────────────────


class TestFrequencyList:
    def test_basic(self):
        pronouns = ["i", "i", "i", "you", "you", "he"]
        top = _frequency_list(pronouns, top_n=3)
        assert top[0] == ("i", 3)
        assert top[1] == ("you", 2)
        assert top[2] == ("he", 1)

    def test_top_n_limit(self):
        pronouns = ["i", "me", "my", "you", "he", "she"]
        top = _frequency_list(pronouns, top_n=2)
        assert len(top) == 2

    def test_empty(self):
        top = _frequency_list([])
        assert top == []


# ── person balance entropy ─────────────────────────────────────


class TestPersonBalance:
    def test_all_one_person(self):
        balance = _person_balance_entropy(1.0, 0.0, 0.0)
        assert balance == 0.0

    def test_perfectly_balanced(self):
        balance = _person_balance_entropy(1 / 3, 1 / 3, 1 / 3)
        assert abs(balance - 1.0) < 0.001

    def test_two_persons(self):
        balance = _person_balance_entropy(0.5, 0.5, 0.0)
        assert 0 < balance < 1.0

    def test_all_zero(self):
        balance = _person_balance_entropy(0.0, 0.0, 0.0)
        assert balance == 0.0


# ── classification ──────────────────────────────────────────────


class TestClassify:
    def test_unknown_when_zero(self):
        assert _classify(0.0, 0) == "unknown"

    def test_sparse(self):
        assert _classify(2.0, 5) == "sparse"

    def test_lean(self):
        assert _classify(4.5, 10) == "lean"

    def test_balanced(self):
        assert _classify(7.0, 20) == "balanced"

    def test_pronoun_heavy(self):
        assert _classify(12.0, 30) == "pronoun_heavy"

    def test_deictic(self):
        assert _classify(16.0, 40) == "deictic"


# ── dominant person ─────────────────────────────────────────────


class TestDominantPerson:
    def test_first_dominant(self):
        assert _dominant_person(10, 2, 3) == "first"

    def test_second_dominant(self):
        assert _dominant_person(2, 10, 3) == "second"

    def test_third_dominant(self):
        assert _dominant_person(2, 3, 10) == "third"

    def test_none_when_all_zero(self):
        assert _dominant_person(0, 0, 0) == "none"


# ── integration: first-person prose ─────────────────────────────


class TestFirstPersonProse:
    def test_diary_style(self):
        text = (
            "I woke up early. I made coffee. I sat by the window and "
            "watched the rain. My thoughts drifted to yesterday. I "
            "wondered if I should call her. I decided to wait."
        )
        r = measure_pronoun_density(text)
        assert r.dominant_person == "first"
        assert r.first_person_ratio > 0.7
        assert r.total_pronouns >= 6
        assert r.classification != "unknown"

    def test_first_person_high_density(self):
        # Very pronoun-heavy first person
        text = "I me my I me my I me my I"
        r = measure_pronoun_density(text)
        assert r.pronoun_rate >= 80
        assert r.classification == "deictic"


# ── integration: second-person prose ────────────────────────────


class TestSecondPersonProse:
    def test_instructional(self):
        text = (
            "You open the file. You type the command. You press enter. "
            "Your screen updates. You check the output. You save your work."
        )
        r = measure_pronoun_density(text)
        assert r.dominant_person == "second"
        assert r.second_person_ratio > 0.5


# ── integration: third-person prose ─────────────────────────────


class TestThirdPersonProse:
    def test_narrative(self):
        text = (
            "She walked to the station. He waited by the platform. "
            "They exchanged glances. It was awkward. She looked away. "
            "He checked his watch."
        )
        r = measure_pronoun_density(text)
        assert r.dominant_person == "third"
        assert r.third_person_ratio > 0.5


# ── integration: balanced prose ─────────────────────────────────


class TestBalancedProse:
    def test_mixed(self):
        text = (
            "I think you should know that she told him the truth. "
            "We all agreed it was the right thing. They understood."
        )
        r = measure_pronoun_density(text)
        assert r.person_balance > 0.3  # some diversity
        assert r.total_pronouns >= 5


# ── integration: formal/technical (sparse pronouns) ─────────────


class TestSparsePronouns:
    def test_technical_writing(self):
        text = (
            "The server processes incoming requests. Each request is "
            "validated against a schema. Invalid requests return HTTP "
            "400 errors. Valid requests proceed to the handler stage. "
            "The handler queries the database and returns results."
        )
        r = measure_pronoun_density(text)
        # Technical writing should have very few pronouns
        assert r.total_pronouns <= 2
        assert r.classification in ("sparse", "lean", "unknown")


# ── contraction handling ────────────────────────────────────────


class TestContractions:
    def test_im_counts_as_first_person(self):
        text = "I'm going to the store"
        r = measure_pronoun_density(text)
        assert r.first_person_count >= 1

    def test_theyre_counts_as_third_person(self):
        text = "They're coming over later today"
        r = measure_pronoun_density(text)
        assert r.third_person_count >= 1

    def test_youre_counts_as_second_person(self):
        text = "You're going to love this place"
        r = measure_pronoun_density(text)
        assert r.second_person_count >= 1


# ── result structure ────────────────────────────────────────────


class TestResultStructure:
    def test_has_all_fields(self):
        r = measure_pronoun_density("I saw her at the park yesterday.")
        assert hasattr(r, "total_pronouns")
        assert hasattr(r, "total_words")
        assert hasattr(r, "pronoun_rate")
        assert hasattr(r, "first_person_count")
        assert hasattr(r, "second_person_count")
        assert hasattr(r, "third_person_count")
        assert hasattr(r, "possessive_count")
        assert hasattr(r, "reflexive_count")
        assert hasattr(r, "first_person_ratio")
        assert hasattr(r, "second_person_ratio")
        assert hasattr(r, "third_person_ratio")
        assert hasattr(r, "possessive_ratio")
        assert hasattr(r, "reflexive_ratio")
        assert hasattr(r, "person_balance")
        assert hasattr(r, "dominant_person")
        assert hasattr(r, "category_counts")
        assert hasattr(r, "top_pronouns")
        assert hasattr(r, "classification")

    def test_top_pronouns_format(self):
        r = measure_pronoun_density("I told him she told me he told us")
        assert isinstance(r.top_pronouns, list)
        for item in r.top_pronouns:
            assert isinstance(item, tuple)
            assert len(item) == 2
            assert isinstance(item[0], str)
            assert isinstance(item[1], int)

    def test_category_counts_format(self):
        r = measure_pronoun_density("I saw you and he left")
        assert isinstance(r.category_counts, dict)
        assert "first" in r.category_counts
        assert "second" in r.category_counts
        assert "third" in r.category_counts


# ── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_repeated_pronoun(self):
        text = "I I I I I"
        r = measure_pronoun_density(text)
        assert r.total_pronouns == 5
        assert r.first_person_ratio == 1.0
        assert r.person_balance == 0.0

    def test_pronoun_in_quoted_speech(self):
        text = 'She said "I think you should come"'
        r = measure_pronoun_density(text)
        assert r.total_pronouns >= 3  # she, i, you

    def test_long_text(self):
        text = "The cat sat. " * 500 + "I watched. " * 50
        r = measure_pronoun_density(text)
        assert r.total_words > 1000
        assert r.classification in ("sparse", "lean", "unknown")

    def test_ratios_sum_approximately_one(self):
        text = "I told you that he and she went with them to our house"
        r = measure_pronoun_density(text)
        ratio_sum = r.first_person_ratio + r.second_person_ratio + r.third_person_ratio
        assert abs(ratio_sum - 1.0) < 0.01
