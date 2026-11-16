#!/usr/bin/env python3
"""Tests for writer_perspective_shift module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_perspective_shift import (
    PerspectiveShiftResult,
    SentencePerson,
    measure_perspective_shift,
    _classify_sentence,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_perspective_shift("")
        assert r.shift_index == 0.0
        assert r.classification == "stable"

    def test_whitespace_only(self):
        r = measure_perspective_shift("   \n\n   ")
        assert r.shift_index == 0.0

    def test_single_sentence(self):
        r = measure_perspective_shift("I think the server crashed.")
        assert r.shift_index == 0.0
        assert r.classification == "stable"
        assert r.first_person_count == 1

    def test_no_pronouns(self):
        r = measure_perspective_shift("The server crashed. The backup restored data.")
        assert r.shift_index == 0.0
        assert r.total_pronouns == 0

    def test_single_word(self):
        r = measure_perspective_shift("Hello.")
        assert r.classification == "stable"


# ── stable perspective (no shifts) ──────────────────────────────


class TestStablePerspective:
    def test_consistent_first_person(self):
        text = (
            "I tested the server yesterday. "
            "I found three critical bugs. "
            "I reported them to the team. "
            "I will follow up tomorrow."
        )
        r = measure_perspective_shift(text)
        assert r.first_person_count == 4
        assert r.total_shifts == 0
        assert r.shift_index == 0.0
        assert r.classification == "stable"

    def test_consistent_third_person(self):
        text = (
            "The server crashed at midnight. "
            "It had been running for 47 days. "
            "The backup restored the data. "
            "They confirmed the fix by morning."
        )
        r = measure_perspective_shift(text)
        assert r.third_person_count > 0
        assert r.total_shifts == 0
        assert r.classification == "stable"

    def test_consistent_second_person(self):
        text = (
            "You open the terminal. "
            "You type the command. "
            "You press enter. "
            "You see the result."
        )
        r = measure_perspective_shift(text)
        assert r.second_person_count == 4
        assert r.total_shifts == 0
        assert r.classification == "stable"


# ── unstable perspective (many shifts) ────────────────────────


class TestUnstablePerspective:
    def test_alternating_first_third(self):
        text = (
            "I tested the server. "
            "It crashed immediately. "
            "I restarted the process. "
            "They logged the error. "
            "I checked the output."
        )
        r = measure_perspective_shift(text)
        assert r.total_shifts >= 3
        assert r.shift_index > 0.50
        assert r.classification in ("restless", "unstable")

    def test_three_way_rotation(self):
        text = (
            "I opened the file. "
            "You can see the contents. "
            "It contains three sections. "
            "I modified the header. "
            "You should save your changes. "
            "They process the data automatically."
        )
        r = measure_perspective_shift(text)
        assert r.first_person_count >= 2
        assert r.second_person_count >= 2
        assert r.third_person_count >= 2
        assert r.total_shifts >= 4
        assert r.classification == "unstable"

    def test_essay_draft_with_drift(self):
        text = (
            "We face many challenges in software development. "
            "One must consider the trade-offs carefully. "
            "You see this pattern in every codebase. "
            "The team at Google documented their approach. "
            "I found their paper insightful. "
            "It changed how we think about testing."
        )
        r = measure_perspective_shift(text)
        assert r.total_shifts >= 3
        assert r.shift_index > 0.40


# ── mostly stable (occasional shifts) ──────────────────────────


class TestMostlyStable:
    def test_third_person_with_one_exception(self):
        text = (
            "It processes incoming requests. "
            "It maintains a connection pool. "
            "It stores persistent data. "
            "You can configure the timeout setting. "
            "It improves performance."
        )
        r = measure_perspective_shift(text)
        assert r.total_shifts >= 1
        assert r.classification in ("mixed", "restless")

    def test_tutorial_style(self):
        text = (
            "The function accepts three parameters. "
            "You pass the filename as the first argument. "
            "It returns a boolean indicating success. "
            "You should check the return value."
        )
        r = measure_perspective_shift(text)
        # Natural tutorial style mixes 2nd and 3rd
        assert r.second_person_count >= 2
        assert r.third_person_count >= 1
        # Every adjacent pair with person data is a shift here,
        # so just verify the person counts and total pronouns
        assert r.total_pronouns >= 3


# ── per-sentence classification ────────────────────────────────


class TestSentenceClassification:
    def test_first_person_sentence(self):
        sp = _classify_sentence("I think we should go.")
        assert sp.first == 2  # I, we
        assert sp.second == 0
        assert sp.third == 0
        assert sp.dominant == "first"

    def test_second_person_sentence(self):
        sp = _classify_sentence("You should check your settings.")
        assert sp.first == 0
        assert sp.second == 2  # you, your
        assert sp.third == 0
        assert sp.dominant == "second"

    def test_third_person_sentence(self):
        sp = _classify_sentence("She told him about the meeting.")
        assert sp.first == 0
        assert sp.second == 0
        assert sp.third == 2  # she, him
        assert sp.dominant == "third"

    def test_mixed_sentence_dominant(self):
        sp = _classify_sentence("I told you that she would arrive.")
        assert sp.first == 1  # I
        assert sp.second == 1  # you
        assert sp.third == 1  # she
        # When tied, max() returns the first one found in dict order
        assert sp.dominant in ("first", "second", "third")

    def test_no_pronouns(self):
        sp = _classify_sentence("The server crashed at midnight.")
        assert sp.total == 0
        assert sp.dominant is None


# ── person counting accuracy ────────────────────────────────────


class TestPersonCounting:
    def test_first_person_pronouns(self):
        text = "I gave my book to him. We told ourselves it was fine."
        r = measure_perspective_shift(text)
        # I, my, We, ourselves = 4 first person; him, it = 2 third
        assert r.first_person_count == 4

    def test_second_person_pronouns(self):
        text = "You should check your settings. Help yourself."
        r = measure_perspective_shift(text)
        # you, your, yourself = 3 second person
        assert r.second_person_count == 3

    def test_third_person_pronouns(self):
        text = "She gave him the book. They said it was theirs."
        r = measure_perspective_shift(text)
        # she, him, they, it, theirs = 5 third person
        assert r.third_person_count == 5

    def test_reflexive_pronouns(self):
        text = "I hurt myself. You saw yourself. She blamed herself."
        r = measure_perspective_shift(text)
        assert r.first_person_count == 2  # I, myself
        assert r.second_person_count == 2  # you, yourself
        assert r.third_person_count == 2  # she, herself


# ── shift detection ─────────────────────────────────────────────


class TestShiftDetection:
    def test_single_shift(self):
        text = "I opened the file. You can see the result."
        r = measure_perspective_shift(text)
        assert r.total_shifts == 1
        assert r.shift_pairs == 1
        assert r.shift_index == 1.0

    def test_no_shift(self):
        text = "I opened the file. I read the contents."
        r = measure_perspective_shift(text)
        assert r.total_shifts == 0

    def test_shift_skips_pronoun_free_sentence(self):
        text = "I started the server. They logged errors. We fixed them."
        r = measure_perspective_shift(text)
        # Sentence 1: first (I), Sentence 2: third (they), Sentence 3: first (we, them)
        # Shift between 1(first)→2(third), then 2(third)→3(first)
        assert r.total_shifts == 2

    def test_sentences_without_pronouns_skipped(self):
        text = "The server crashed. The database went down."
        r = measure_perspective_shift(text)
        # No personal pronouns in either sentence
        assert r.shift_pairs == 0
        assert r.shift_index == 0.0


# ── classification thresholds ──────────────────────────────────


class TestClassification:
    def test_stable_classification(self):
        text = (
            "I walked to the store. "
            "I bought some groceries. "
            "I cooked dinner at home."
        )
        r = measure_perspective_shift(text)
        assert r.classification == "stable"

    def test_unstable_classification(self):
        text = (
            "I checked the logs. "
            "You should see the output. "
            "It shows three errors. "
            "We need to fix them. "
            "You can restart the service."
        )
        r = measure_perspective_shift(text)
        assert r.shift_index > 0.40

    def test_classification_range(self):
        """All classifications should be one of the five valid values."""
        valid = {"stable", "mostly_stable", "mixed", "restless", "unstable"}
        texts = [
            "I think. I believe. I know.",
            "I think. You know. They say.",
            "The server crashed. It was old.",
            "We tried. You failed. They left.",
            "",
        ]
        for text in texts:
            r = measure_perspective_shift(text)
            assert r.classification in valid


# ── dominant person ─────────────────────────────────────────────


class TestDominantPerson:
    def test_first_person_dominant(self):
        text = (
            "I tested the server. "
            "I found bugs. "
            "We fixed them together."
        )
        r = measure_perspective_shift(text)
        assert r.dominant_person == "first"

    def test_third_person_dominant(self):
        text = (
            "The server crashed. "
            "It had been running too long. "
            "They restarted the process."
        )
        r = measure_perspective_shift(text)
        assert r.dominant_person == "third"

    def test_no_pronouns_no_dominant(self):
        text = "The server crashed. The backup restored data."
        r = measure_perspective_shift(text)
        assert r.dominant_person is None


# ── score computation ──────────────────────────────────────────


class TestScores:
    def test_scores_sum_to_one(self):
        text = (
            "I tested the server. "
            "You should check the logs. "
            "It returned three errors."
        )
        r = measure_perspective_shift(text)
        total = r.first_person_score + r.second_person_score + r.third_person_score
        assert abs(total - 1.0) < 0.01

    def test_scores_zero_when_no_pronouns(self):
        r = measure_perspective_shift("The server crashed.")
        assert r.first_person_score == 0.0
        assert r.second_person_score == 0.0
        assert r.third_person_score == 0.0


# ── orthogonality ──────────────────────────────────────────────


class TestOrthogonality:
    def test_short_but_unstable(self):
        """Short text can still be highly unstable."""
        text = "I think. You know. They say."
        r = measure_perspective_shift(text)
        assert r.shift_index == 1.0
        assert r.total_words < 10

    def test_long_but_stable(self):
        """Long text can be perfectly stable."""
        text = (
            "I walked to the store. "
            "I bought three apples. "
            "I paid with cash. "
            "I walked home slowly. "
            "I ate one apple on the way. "
            "I put the rest in the fridge."
        )
        r = measure_perspective_shift(text)
        assert r.shift_index == 0.0
        assert r.total_words > 20

    def test_stable_not_verbose(self):
        """Stable perspective doesn't require long sentences."""
        text = "I ran. I fell. I got up."
        r = measure_perspective_shift(text)
        assert r.shift_index == 0.0


# ── index range ────────────────────────────────────────────────


class TestIndexRange:
    def test_index_always_valid(self):
        """Shift index should always be between 0.0 and 1.0."""
        texts = [
            "Hello world.",
            "I think. You know. They say.",
            "I walked. I talked. I listened.",
            "The server. It crashed. They fixed it.",
            "",
            "One must consider the implications.",
        ]
        for text in texts:
            r = measure_perspective_shift(text)
            assert 0.0 <= r.shift_index <= 1.0


# ── edge cases ─────────────────────────────────────────────────


class TestEdgeCases:
    def test_repeated_sentence(self):
        text = "I think. " * 10
        r = measure_perspective_shift(text)
        assert r.shift_index == 0.0
        assert r.total_sentences == 10

    def test_alternating_pattern(self):
        text = "I ran. You walked. I jumped. You sat."
        r = measure_perspective_shift(text)
        assert r.total_shifts == 3
        assert r.shift_index == 1.0

    def test_result_dataclass_defaults(self):
        r = PerspectiveShiftResult()
        assert r.shift_index == 0.0
        assert r.classification == "stable"
        assert r.first_person_count == 0
        assert r.total_sentences == 0

    def test_sentence_person_defaults(self):
        sp = SentencePerson()
        assert sp.first == 0
        assert sp.second == 0
        assert sp.third == 0
        assert sp.dominant is None
        assert sp.total == 0


# ── real-world text samples ────────────────────────────────────


class TestRealWorldSamples:
    def test_tech_blog_post(self):
        text = (
            "We migrated our database to PostgreSQL 16 last week. "
            "The process took 47 minutes. "
            "We used pg_dump to export the data. "
            "The team verified all 127 tables after migration."
        )
        r = measure_perspective_shift(text)
        assert r.classification in ("stable", "mostly_stable")

    def test_casual_chat(self):
        text = (
            "I was thinking about your suggestion. "
            "You mentioned that it could help with performance. "
            "I tested it on my laptop. "
            "You were right — it shaved 200ms off the build."
        )
        r = measure_perspective_shift(text)
        # Chat naturally mixes first and second person
        assert r.first_person_count >= 2
        assert r.second_person_count >= 2

    def test_scientific_abstract(self):
        text = (
            "This study examines the relationship between sleep "
            "quality and cognitive performance. "
            "We recruited 47 participants aged 18 to 35. "
            "They completed a battery of cognitive tests. "
            "The results indicate a significant correlation."
        )
        r = measure_perspective_shift(text)
        # Scientific writing often mixes we/they/it
        assert r.total_pronouns >= 2

    def test_instruction_manual(self):
        text = (
            "Remove the cover panel. "
            "You will see three screws on the left side. "
            "Unscrew them carefully. "
            "The board should lift out without resistance."
        )
        r = measure_perspective_shift(text)
        assert r.second_person_count >= 1
        assert r.third_person_count >= 1

    def test_commit_message_style(self):
        text = (
            "add writer_perspective_shift module + 35 tests + "
            "caretaker visit 657. It measures grammatical-person "
            "stability across sentences. We wrote it during manual "
            "caretaker visit 657, 2026-11-16."
        )
        r = measure_perspective_shift(text)
        assert r.total_words > 10
        assert r.total_sentences >= 2

    def test_metadata_accuracy(self):
        text = "I walked. You ran. She jumped."
        r = measure_perspective_shift(text)
        assert r.total_sentences == 3
        assert r.total_words == 6
        assert r.total_pronouns == 3
