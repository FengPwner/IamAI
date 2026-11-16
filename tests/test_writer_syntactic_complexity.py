#!/usr/bin/env python3
"""Tests for writer_syntactic_complexity module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.writer_syntactic_complexity import (
    ComplexityResult,
    measure_syntactic_complexity,
)


# ── empty / degenerate input ────────────────────────────────────


class TestEmptyInput:
    def test_empty_string(self):
        r = measure_syntactic_complexity("")
        assert r.complexity_index == 0.0
        assert r.classification == "simple"

    def test_whitespace_only(self):
        r = measure_syntactic_complexity("   \n\n   ")
        assert r.complexity_index == 0.0

    def test_single_word(self):
        r = measure_syntactic_complexity("Hello.")
        assert r.sentence_count == 1
        assert r.total_words == 1

    def test_no_complexity_markers(self):
        r = measure_syntactic_complexity("The cat sat. The dog ran. The bird flew.")
        assert r.passive_count == 0
        assert r.subordination_count == 0
        assert r.coordination_count == 0
        assert r.relative_count == 0
        assert r.preposition_chain_count == 0
        assert r.participle_count == 0


# ── sentence counting ───────────────────────────────────────────


class TestSentenceCounting:
    def test_three_sentences(self):
        r = measure_syntactic_complexity("One. Two. Three.")
        assert r.sentence_count == 3

    def test_exclamation(self):
        r = measure_syntactic_complexity("Stop! Drop! Roll!")
        assert r.sentence_count == 3

    def test_question_marks(self):
        r = measure_syntactic_complexity("Who? What? Where?")
        assert r.sentence_count == 3

    def test_mixed_punctuation(self):
        r = measure_syntactic_complexity("Really? Yes! I think so.")
        assert r.sentence_count == 3

    def test_single_sentence(self):
        r = measure_syntactic_complexity("The quick brown fox jumps over the lazy dog.")
        assert r.sentence_count == 1

    def test_word_count(self):
        r = measure_syntactic_complexity("One two three. Four five.")
        assert r.total_words == 5

    def test_avg_sentence_length(self):
        r = measure_syntactic_complexity("One two three four five. One two three four five.")
        assert r.avg_sentence_length == 5.0


# ── sentence length variation ──────────────────────────────────


class TestSentenceLengthVariation:
    def test_uniform_length(self):
        """All sentences same length → CV should be near zero."""
        r = measure_syntactic_complexity(
            "One two three. Four five six. Seven eight nine."
        )
        assert r.sentence_length_cv < 0.1

    def test_high_variation(self):
        """Very different sentence lengths → CV should be high."""
        text = "Run. " + " ".join(["word"] * 40) + ". Ok."
        r = measure_syntactic_complexity(text)
        assert r.sentence_length_cv > 0.5

    def test_single_sentence_cv_zero(self):
        r = measure_syntactic_complexity("Just one sentence here.")
        assert r.sentence_length_cv == 0.0

    def test_two_identical_sentences(self):
        r = measure_syntactic_complexity("Same length. Same length.")
        assert r.sentence_length_cv < 0.01


# ── passive voice ───────────────────────────────────────────────


class TestPassiveVoice:
    def test_was_given(self):
        r = measure_syntactic_complexity("The award was given to her.")
        assert r.passive_count >= 1

    def test_were_told(self):
        r = measure_syntactic_complexity("They were told to leave.")
        assert r.passive_count >= 1

    def test_is_known(self):
        r = measure_syntactic_complexity("The answer is known to all.")
        assert r.passive_count >= 1

    def test_been_found(self):
        r = measure_syntactic_complexity("The document has been found.")
        assert r.passive_count >= 1

    def test_being_built(self):
        r = measure_syntactic_complexity("The house is being built.")
        assert r.passive_count >= 1

    def test_active_voice_no_passive(self):
        r = measure_syntactic_complexity("She wrote the report. He sent the email.")
        assert r.passive_count == 0

    def test_multiple_passives(self):
        text = (
            "The ball was thrown. "
            "The window was broken. "
            "The game was cancelled."
        )
        r = measure_syntactic_complexity(text)
        assert r.passive_count >= 3

    def test_passive_ratio_per_100(self):
        # 3 sentences, 3 passives → 100 per 100 sentences
        text = "It was done. It was made. It was found."
        r = measure_syntactic_complexity(text)
        assert r.passive_ratio >= 90.0


# ── subordination ───────────────────────────────────────────────


class TestSubordination:
    def test_because(self):
        r = measure_syntactic_complexity("She left because it was late.")
        assert r.subordination_count >= 1

    def test_although(self):
        r = measure_syntactic_complexity("Although tired, she continued.")
        assert r.subordination_count >= 1

    def test_while(self):
        r = measure_syntactic_complexity("He read while she cooked.")
        assert r.subordination_count >= 1

    def test_since(self):
        r = measure_syntactic_complexity("Since you asked, I will explain.")
        assert r.subordination_count >= 1

    def test_unless(self):
        r = measure_syntactic_complexity("We cannot proceed unless approved.")
        assert r.subordination_count >= 1

    def test_whereas(self):
        r = measure_syntactic_complexity("Cats purr, whereas dogs bark.")
        assert r.subordination_count >= 1

    def test_even_though(self):
        r = measure_syntactic_complexity("Even though it rained, they played.")
        assert r.subordination_count >= 1

    def test_so_that(self):
        r = measure_syntactic_complexity("She studied hard so that she could pass.")
        assert r.subordination_count >= 1

    def test_in_order_to(self):
        r = measure_syntactic_complexity("In order to succeed, you must try.")
        assert r.subordination_count >= 1

    def test_despite(self):
        r = measure_syntactic_complexity("Despite the rain, they went out.")
        assert r.subordination_count >= 1

    def test_until(self):
        r = measure_syntactic_complexity("Wait here until I return.")
        assert r.subordination_count >= 1

    def test_whenever(self):
        r = measure_syntactic_complexity("Whenever possible, she reads.")
        assert r.subordination_count >= 1

    def test_no_subordination(self):
        r = measure_syntactic_complexity("The sun set. Stars appeared. Night fell.")
        assert r.subordination_count == 0

    def test_multiple_subordinators(self):
        text = (
            "Because it rained, the match was cancelled. "
            "Although disappointed, the players understood. "
            "Since the field was flooded, they went home."
        )
        r = measure_syntactic_complexity(text)
        assert r.subordination_count >= 3


# ── coordination ────────────────────────────────────────────────


class TestCoordination:
    def test_comma_and(self):
        r = measure_syntactic_complexity("She ran fast, and he followed.")
        assert r.coordination_count >= 1

    def test_comma_but(self):
        r = measure_syntactic_complexity("It was cold, but they stayed outside.")
        assert r.coordination_count >= 1

    def test_comma_yet(self):
        r = measure_syntactic_complexity("He tried hard, yet he failed.")
        assert r.coordination_count >= 1

    def test_comma_so(self):
        r = measure_syntactic_complexity("It rained, so we stayed in.")
        assert r.coordination_count >= 1

    def test_comma_or(self):
        r = measure_syntactic_complexity("Hurry up, or we will miss it.")
        assert r.coordination_count >= 1

    def test_semicolon(self):
        r = measure_syntactic_complexity("She was tired; however, she kept going.")
        assert r.coordination_count >= 1

    def test_no_coordination(self):
        r = measure_syntactic_complexity("The door opened. She walked in.")
        assert r.coordination_count == 0


# ── relative clauses ────────────────────────────────────────────


class TestRelativeClauses:
    def test_who(self):
        r = measure_syntactic_complexity("The man who called yesterday is here.")
        assert r.relative_count >= 1

    def test_which(self):
        r = measure_syntactic_complexity("The book which I read was good.")
        assert r.relative_count >= 1

    def test_that(self):
        r = measure_syntactic_complexity("The car that she bought is red.")
        assert r.relative_count >= 1

    def test_whose(self):
        r = measure_syntactic_complexity("The girl whose phone rang blushed.")
        assert r.relative_count >= 1

    def test_whom(self):
        r = measure_syntactic_complexity("The person whom you met is my friend.")
        assert r.relative_count >= 1

    def test_where(self):
        r = measure_syntactic_complexity("The city where I grew up is small.")
        assert r.relative_count >= 1

    def test_no_relative(self):
        r = measure_syntactic_complexity("She bought a red car. It is fast.")
        assert r.relative_count == 0

    def test_multiple_relatives(self):
        text = (
            "The man who lives here has a dog which barks loudly. "
            "The woman whose garden is beautiful won an award."
        )
        r = measure_syntactic_complexity(text)
        assert r.relative_count >= 3


# ── prepositional chains ────────────────────────────────────────


class TestPrepositionalChains:
    def test_two_preps(self):
        r = measure_syntactic_complexity("The door of the house on the hill.")
        assert r.preposition_chain_count >= 1

    def test_three_preps(self):
        r = measure_syntactic_complexity(
            "The key to the door of the house at the end of the road."
        )
        assert r.preposition_chain_count >= 1

    def test_no_chain(self):
        r = measure_syntactic_complexity("She opened the door.")
        assert r.preposition_chain_count == 0

    def test_single_preposition(self):
        r = measure_syntactic_complexity("The cat on the mat slept.")
        # single prepositional phrase, no chain
        assert r.preposition_chain_count == 0


# ── participle modifiers ────────────────────────────────────────


class TestParticipleModifiers:
    def test_initial_present_participle(self):
        r = measure_syntactic_complexity("Running late, she skipped breakfast.")
        assert r.participle_count >= 1

    def test_initial_past_participle(self):
        r = measure_syntactic_complexity("Exhausted by the climb, he rested.")
        assert r.participle_count >= 1

    def test_no_participle_modifier(self):
        r = measure_syntactic_complexity("She ate breakfast. He climbed the hill.")
        assert r.participle_count == 0


# ── composite index and classification ──────────────────────────


class TestCompositeIndex:
    def test_simple_prose_low_index(self):
        text = (
            "The sun rose. "
            "Birds sang. "
            "She walked to school. "
            "He ate lunch. "
            "They played outside. "
            "Night fell."
        )
        r = measure_syntactic_complexity(text)
        assert r.complexity_index < 0.3
        assert r.classification in ("telegraphic", "simple")

    def test_complex_prose_higher_index(self):
        text = (
            "Although the morning was cold, she walked to school, and her brother "
            "followed, carrying the lunch that their mother had prepared. "
            "Because the bus was late, which annoyed the driver, they arrived "
            "after the bell had rung, and the teacher, who was already teaching, "
            "glanced up briefly."
        )
        r = measure_syntactic_complexity(text)
        assert r.complexity_index > 0.3
        assert r.classification in ("moderate", "elaborate", "baroque")

    def test_index_range(self):
        """Index should always be in [0, 1]."""
        texts = [
            "Stop.",
            "The cat sat on the mat.",
            "Although she was tired, she continued working, and her colleague, "
            "who had been waiting for the report, was pleased.",
            "A" * 1000,
        ]
        for t in texts:
            r = measure_syntactic_complexity(t)
            assert 0.0 <= r.complexity_index <= 1.0

    def test_telegraphic_classification(self):
        r = measure_syntactic_complexity("Stop. Drop. Roll. Go. Run.")
        assert r.classification == "telegraphic"

    def test_baroque_prose(self):
        """Densely subordinated, varied-length prose should score high."""
        text = (
            "Although the morning, which had been grey since dawn, promised nothing "
            "but rain, she walked, because walking was the only thing that quieted "
            "her mind, through the park where the trees, whose leaves had turned gold, "
            "sheltered the bench on which, since childhood, she had sat, and thought, "
            "while the city, despite its noise, hummed beneath the silence that the "
            "fallen leaves had spread across the path beneath her feet. "
            "She stopped. "
            "A single bird, which had been watching from a branch that overhung the "
            "fountain, flew across the grey sky, and landed on the bench beside her, "
            "where it waited, as if it too understood that some silences are not empty "
            "but full of everything that cannot be said."
        )
        r = measure_syntactic_complexity(text)
        assert r.complexity_index > 0.5
        assert r.classification in ("elaborate", "baroque")


# ── total_complexity_markers property ───────────────────────────


class TestTotalMarkers:
    def test_total_is_sum(self):
        text = (
            "Although tired, she was given a task. "
            "The man who called, and the woman who answered, were friends."
        )
        r = measure_syntactic_complexity(text)
        assert r.total_complexity_markers == (
            r.passive_count
            + r.subordination_count
            + r.coordination_count
            + r.relative_count
            + r.preposition_chain_count
            + r.participle_count
        )

    def test_zero_for_simple(self):
        r = measure_syntactic_complexity("She ran.")
        assert r.total_complexity_markers == 0


# ── edge cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_single_long_sentence(self):
        """One very long sentence with no subordination → simple."""
        words = " ".join(["word"] * 50)
        r = measure_syntactic_complexity(f"{words}.")
        assert r.sentence_count == 1
        assert r.sentence_length_cv == 0.0

    def test_many_short_sentences(self):
        """Many identical short sentences → low CV, low complexity."""
        r = measure_syntactic_complexity("She ran. He walked. They sat. We ate. You left.")
        assert r.sentence_length_cv < 0.3
        assert r.complexity_index < 0.3

    def test_mixed_case_markers(self):
        """Markers should be case-insensitive."""
        r = measure_syntactic_complexity("BECAUSE it rained, ALTHOUGH tired, she ran.")
        assert r.subordination_count >= 2

    def test_contractions_no_false_passive(self):
        """'She's running' should not be flagged as passive."""
        r = measure_syntactic_complexity("She is running to the store. He is walking home.")
        # "is running" — progressive, not passive. Our heuristic might
        # catch it (running doesn't end in -ed/-en/-t/-wn/-ne).
        assert r.passive_count == 0

    def test_result_dataclass_defaults(self):
        r = ComplexityResult()
        assert r.sentence_count == 0
        assert r.total_words == 0
        assert r.complexity_index == 0.0
        assert r.classification == "simple"
        assert r.total_complexity_markers == 0

    def test_orthogonal_to_hedging(self):
        """Hedged but syntactically simple text should score low."""
        text = (
            "It might rain. "
            "Perhaps we should leave. "
            "Maybe the bus is late."
        )
        r = measure_syntactic_complexity(text)
        assert r.complexity_index < 0.3

    def test_orthogonal_to_verbosity(self):
        """Long sentences with simple syntax should not score high."""
        text = (
            "The very large and extremely heavy wooden box sat on the floor. "
            "The extremely bright and very warm summer sun shone through the window."
        )
        r = measure_syntactic_complexity(text)
        # Verbose but syntactically simple
        assert r.subordination_count == 0
        assert r.relative_count == 0


# ── regression: ratio consistency ───────────────────────────────


class TestRatioConsistency:
    def test_ratios_scale_with_sentences(self):
        """Doubling the text should roughly double the counts."""
        base = "Although tired, she walked. Because hungry, he stopped."
        doubled = base + " " + base
        r1 = measure_syntactic_complexity(base)
        r2 = measure_syntactic_complexity(doubled)
        # counts should roughly double
        assert abs(r2.subordination_count - 2 * r1.subordination_count) <= 1
        # ratios per 100 should stay similar
        if r1.subordination_ratio > 0:
            ratio_diff = abs(r2.subordination_ratio - r1.subordination_ratio)
            assert ratio_diff < r1.subordination_ratio * 0.5

    def test_more_subordination_higher_index(self):
        text_simple = "She ran. He walked. They sat. We ate. You left."
        text_complex = (
            "She ran because she was late. "
            "He walked although he was tired. "
            "They sat while the sun set. "
            "We ate before the movie. "
            "You left since you were bored."
        )
        r_simple = measure_syntactic_complexity(text_simple)
        r_complex = measure_syntactic_complexity(text_complex)
        assert r_complex.complexity_index > r_simple.complexity_index
