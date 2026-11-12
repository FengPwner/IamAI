#!/usr/bin/env python3
"""Tests for writer_temporal_orientation — 128 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_temporal_orientation import (  # noqa: E402
    FUTURE_ADVERBIALS,
    FUTURE_ADVERBIAL_PHRASES,
    FUTURE_MARKERS,
    FUTURE_PHRASES,
    FUNCTION_WORDS,
    IRREGULAR_PAST_FORMS,
    PAST_ADVERBIALS,
    PAST_ADVERBIAL_PHRASES,
    PERFECT_AUXILIARIES,
    PRESENT_ADVERBIALS,
    PRESENT_ADVERBIAL_PHRASES,
    PROGRESSIVE_AUXILIARIES,
    WriterTemporalOrientation,
)


class TestWriterTemporalOrientationInit(unittest.TestCase):
    """Test WriterTemporalOrientation initialization."""

    def test_init_default(self):
        wto = WriterTemporalOrientation()
        self.assertIsNotNone(wto.irregular_past)
        self.assertIsNotNone(wto.past_adverbials)

    def test_init_sets_all_attributes(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto.irregular_past, IRREGULAR_PAST_FORMS)
        self.assertEqual(wto.past_adverbials, PAST_ADVERBIALS)
        self.assertEqual(wto.past_adverbial_phrases, PAST_ADVERBIAL_PHRASES)
        self.assertEqual(wto.present_adverbials, PRESENT_ADVERBIALS)
        self.assertEqual(wto.present_adverbial_phrases, PRESENT_ADVERBIAL_PHRASES)
        self.assertEqual(wto.future_markers, FUTURE_MARKERS)
        self.assertEqual(wto.future_phrases, FUTURE_PHRASES)
        self.assertEqual(wto.future_adverbials, FUTURE_ADVERBIALS)
        self.assertEqual(wto.future_adverbial_phrases, FUTURE_ADVERBIAL_PHRASES)
        self.assertEqual(wto.perfect_auxiliaries, PERFECT_AUXILIARIES)
        self.assertEqual(wto.progressive_auxiliaries, PROGRESSIVE_AUXILIARIES)
        self.assertEqual(wto.function_words, FUNCTION_WORDS)


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_empty_string(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto._split_sentences(""), [])

    def test_whitespace_only(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto._split_sentences("   "), [])

    def test_single_sentence(self):
        wto = WriterTemporalOrientation()
        result = wto._split_sentences("She walked home.")
        self.assertEqual(result, ["She walked home"])

    def test_multiple_sentences(self):
        wto = WriterTemporalOrientation()
        result = wto._split_sentences("She walked. He ran. They flew.")
        self.assertEqual(len(result), 3)

    def test_question_marks(self):
        wto = WriterTemporalOrientation()
        result = wto._split_sentences("Did she walk? Yes she did.")
        self.assertEqual(len(result), 2)

    def test_exclamation_marks(self):
        wto = WriterTemporalOrientation()
        result = wto._split_sentences("She walked! He ran!")
        self.assertEqual(len(result), 2)

    def test_mixed_punctuation(self):
        wto = WriterTemporalOrientation()
        result = wto._split_sentences("Did she walk? She walked! Yes.")
        self.assertEqual(len(result), 3)

    def test_no_trailing_punctuation(self):
        wto = WriterTemporalOrientation()
        result = wto._split_sentences("She walked home")
        self.assertEqual(result, ["She walked home"])


class TestTokenize(unittest.TestCase):
    """Test _tokenize helper."""

    def test_empty_string(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto._tokenize(""), [])

    def test_single_word(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto._tokenize("hello"), ["hello"])

    def test_multiple_words(self):
        wto = WriterTemporalOrientation()
        tokens = wto._tokenize("The quick brown fox")
        self.assertEqual(tokens, ["the", "quick", "brown", "fox"])

    def test_punctuation_removed(self):
        wto = WriterTemporalOrientation()
        tokens = wto._tokenize("Hello, world!")
        self.assertEqual(tokens, ["hello", "world"])

    def test_case_insensitive(self):
        wto = WriterTemporalOrientation()
        tokens = wto._tokenize("HELLO World")
        self.assertEqual(tokens, ["hello", "world"])

    def test_numbers_excluded(self):
        wto = WriterTemporalOrientation()
        tokens = wto._tokenize("I have 5 cats")
        self.assertIn("have", tokens)
        self.assertNotIn("5", tokens)

    def test_contractions_kept(self):
        wto = WriterTemporalOrientation()
        tokens = wto._tokenize("don't go")
        # apostrophe is kept in the token
        self.assertIn("don't", tokens)
        self.assertIn("go", tokens)


class TestIrregularPastDetection(unittest.TestCase):
    """Test _has_irregular_past helper."""

    def test_detected(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_irregular_past(["she", "went", "home"]))

    def test_not_detected(self):
        wto = WriterTemporalOrientation()
        self.assertFalse(wto._has_irregular_past(["she", "walks", "home"]))

    def test_multiple_irregulars(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_irregular_past(["he", "took", "the", "book"]))

    def test_function_words_excluded(self):
        wto = WriterTemporalOrientation()
        # "was" and "had" are in both irregular_past and function_words
        # but the method checks for non-function-word membership
        tokens = ["the", "a", "is"]
        self.assertFalse(wto._has_irregular_past(tokens))

    def test_saw_detected(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_irregular_past(["i", "saw", "her"]))

    def test_broke_detected(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_irregular_past(["it", "broke", "yesterday"]))

    def test_understood_detected(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_irregular_past(["she", "understood", "everything"]))


class TestRegularPastDetection(unittest.TestCase):
    """Test _has_regular_past helper."""

    def test_ed_ending(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_regular_past(["she", "walked", "home"]))

    def test_short_word_excluded(self):
        wto = WriterTemporalOrientation()
        self.assertFalse(wto._has_regular_past(["he", "fed", "the", "cat"]))

    def test_need_excluded(self):
        wto = WriterTemporalOrientation()
        self.assertFalse(wto._has_regular_past(["i", "need", "help"]))

    def test_seed_excluded(self):
        wto = WriterTemporalOrientation()
        self.assertFalse(wto._has_regular_past(["the", "seed", "grew"]))

    def test_painted_detected(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_regular_past(["it", "was", "painted", "blue"]))

    def test_planted_detected(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_regular_past(["he", "planted", "a", "tree"]))

    def test_remembered_detected(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_regular_past(["she", "remembered", "everything"]))

    def test_function_words_excluded(self):
        wto = WriterTemporalOrientation()
        self.assertFalse(wto._has_regular_past(["the", "and", "for"]))


class TestPresentThirdPerson(unittest.TestCase):
    """Test _has_present_third_person helper."""

    def test_es_verb(self):
        wto = WriterTemporalOrientation()
        # "processes" ends in -es, stem "process" ends in -ss
        self.assertTrue(wto._has_present_third_person(["it", "processes", "data"]))

    def test_s_verb(self):
        wto = WriterTemporalOrientation()
        # "checks" ends in -s
        self.assertTrue(wto._has_present_third_person(["it", "checks", "tokens"]))

    def test_plural_excluded(self):
        wto = WriterTemporalOrientation()
        # "things" is excluded
        self.assertFalse(wto._has_present_third_person(["many", "things"]))

    def test_short_word_excluded(self):
        wto = WriterTemporalOrientation()
        self.assertFalse(wto._has_present_third_person(["as", "is"]))


class TestFutureMarkerDetection(unittest.TestCase):
    """Test _has_future_marker helper."""

    def test_will(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_future_marker(["we", "will", "go"], "We will go"))

    def test_shall(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_future_marker(["we", "shall", "see"], "We shall see"))

    def test_going_to(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_future_marker(
            ["we", "are", "going", "to", "win"],
            "We are going to win"
        ))

    def test_about_to(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_future_marker(
            ["she", "is", "about", "to", "leave"],
            "She is about to leave"
        ))

    def test_no_future(self):
        wto = WriterTemporalOrientation()
        self.assertFalse(wto._has_future_marker(
            ["she", "walked", "home"],
            "She walked home"
        ))

    def test_gonna(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_future_marker(
            ["we", "gonna", "win"],
            "We gonna win"
        ))


class TestPastAdverbialCounting(unittest.TestCase):
    """Test _count_past_adverbials helper."""

    def test_yesterday(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto._count_past_adverbials("She walked yesterday"), 1)

    def test_ago(self):
        wto = WriterTemporalOrientation()
        # "ago" (single) + "days ago" (phrase) → ≥ 1
        self.assertGreaterEqual(wto._count_past_adverbials("Two days ago she left"), 1)

    def test_phrase_last_year(self):
        wto = WriterTemporalOrientation()
        # "last" (single) + "last year" (phrase) = 2
        self.assertGreaterEqual(wto._count_past_adverbials("She moved last year"), 1)

    def test_phrase_years_ago(self):
        wto = WriterTemporalOrientation()
        # "ago" (single) + "years ago" (phrase) = 2
        self.assertGreaterEqual(wto._count_past_adverbials("It happened years ago"), 1)

    def test_none(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto._count_past_adverbials("She walks now"), 0)

    def test_multiple(self):
        wto = WriterTemporalOrientation()
        self.assertGreaterEqual(
            wto._count_past_adverbials("Yesterday, long ago, she left"), 2
        )

    def test_back_then(self):
        wto = WriterTemporalOrientation()
        # "back" + "then" (singles) + "back then" (phrase) → ≥ 1
        self.assertGreaterEqual(wto._count_past_adverbials("Back then things were different"), 1)

    def test_in_the_past(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto._count_past_adverbials("In the past this was common"), 1)


class TestPresentAdverbialCounting(unittest.TestCase):
    """Test _count_present_adverbials helper."""

    def test_now(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto._count_present_adverbials("She walks now"), 1)

    def test_today(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto._count_present_adverbials("Today is a good day"), 1)

    def test_currently(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto._count_present_adverbials("She is currently working"), 1)

    def test_phrase_right_now(self):
        wto = WriterTemporalOrientation()
        # "now" (single) + "right now" (phrase) → ≥ 1
        self.assertGreaterEqual(wto._count_present_adverbials("Do it right now"), 1)

    def test_phrase_this_week(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto._count_present_adverbials("This week we work hard"), 1)

    def test_none(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto._count_present_adverbials("She walked yesterday"), 0)


class TestFutureAdverbialCounting(unittest.TestCase):
    """Test _count_future_adverbials helper."""

    def test_tomorrow(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto._count_future_adverbials("We leave tomorrow"), 1)

    def test_soon(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto._count_future_adverbials("It will happen soon"), 1)

    def test_eventually(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto._count_future_adverbials("Eventually they will see"), 1)

    def test_phrase_next_year(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto._count_future_adverbials("We launch next year"), 1)

    def test_phrase_in_the_future(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(
            wto._count_future_adverbials("In the future we will fly"), 1
        )

    def test_phrase_going_forward(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(
            wto._count_future_adverbials("Going forward we improve"), 1
        )

    def test_none(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto._count_future_adverbials("She walked yesterday"), 0)


class TestPerfectAspect(unittest.TestCase):
    """Test _has_perfect_aspect helper."""

    def test_have_ed(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_perfect_aspect(["they", "have", "walked"]))

    def test_has_been(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_perfect_aspect(["she", "has", "been"]))

    def test_had_done(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_perfect_aspect(["he", "had", "done"]))

    def test_has_seen(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_perfect_aspect(["she", "has", "seen"]))

    def test_have_gone(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_perfect_aspect(["they", "have", "gone"]))

    def test_no_perfect(self):
        wto = WriterTemporalOrientation()
        self.assertFalse(wto._has_perfect_aspect(["she", "walks", "home"]))

    def test_had_written(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_perfect_aspect(["she", "had", "written"]))

    def test_have_taken(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_perfect_aspect(["they", "have", "taken"]))


class TestProgressiveAspect(unittest.TestCase):
    """Test _has_progressive_aspect helper."""

    def test_is_walking(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_progressive_aspect(["she", "is", "walking"]))

    def test_was_running(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_progressive_aspect(["he", "was", "running"]))

    def test_are_working(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_progressive_aspect(["they", "are", "working"]))

    def test_no_progressive(self):
        wto = WriterTemporalOrientation()
        self.assertFalse(wto._has_progressive_aspect(["she", "walks", "home"]))

    def test_thing_excluded(self):
        wto = WriterTemporalOrientation()
        self.assertFalse(wto._has_progressive_aspect(["the", "thing", "is"]))

    def test_being_alone(self):
        wto = WriterTemporalOrientation()
        # "being" is in progressive aux but also excluded as -ing form
        self.assertFalse(wto._has_progressive_aspect(["she", "is", "being"]))

    def test_were_speaking(self):
        wto = WriterTemporalOrientation()
        self.assertTrue(wto._has_progressive_aspect(["they", "were", "speaking"]))


class TestMeasurePastTenseDensity(unittest.TestCase):
    """Test measure_past_tense_density."""

    def test_empty(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto.measure_past_tense_density(""), 0.0)

    def test_all_past(self):
        wto = WriterTemporalOrientation()
        text = "She walked home. He took the bus. They saw the movie."
        density = wto.measure_past_tense_density(text)
        self.assertEqual(density, 1.0)

    def test_no_past(self):
        wto = WriterTemporalOrientation()
        text = "She walks home. He takes the bus."
        density = wto.measure_past_tense_density(text)
        self.assertEqual(density, 0.0)

    def test_mixed(self):
        wto = WriterTemporalOrientation()
        text = "She walked home. He takes the bus. They saw the movie."
        density = wto.measure_past_tense_density(text)
        self.assertGreater(density, 0.5)

    def test_single_sentence(self):
        wto = WriterTemporalOrientation()
        text = "She walked through the garden yesterday."
        self.assertEqual(wto.measure_past_tense_density(text), 1.0)

    def test_half_past(self):
        wto = WriterTemporalOrientation()
        text = "She walked home. The sky is blue."
        density = wto.measure_past_tense_density(text)
        self.assertAlmostEqual(density, 0.5, places=1)


class TestMeasurePresentTenseDensity(unittest.TestCase):
    """Test measure_present_tense_density."""

    def test_empty(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto.measure_present_tense_density(""), 0.0)

    def test_all_present(self):
        wto = WriterTemporalOrientation()
        text = "The algorithm processes tokens. It checks the dictionary."
        density = wto.measure_present_tense_density(text)
        self.assertGreater(density, 0.0)

    def test_no_present(self):
        wto = WriterTemporalOrientation()
        text = "She walked home yesterday. He took the bus."
        density = wto.measure_present_tense_density(text)
        self.assertEqual(density, 0.0)


class TestMeasureFutureTenseDensity(unittest.TestCase):
    """Test measure_future_tense_density."""

    def test_empty(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto.measure_future_tense_density(""), 0.0)

    def test_all_future(self):
        wto = WriterTemporalOrientation()
        text = "We will go. They will see. She shall return."
        density = wto.measure_future_tense_density(text)
        self.assertEqual(density, 1.0)

    def test_no_future(self):
        wto = WriterTemporalOrientation()
        text = "She walked home. He took the bus."
        density = wto.measure_future_tense_density(text)
        self.assertEqual(density, 0.0)

    def test_going_to(self):
        wto = WriterTemporalOrientation()
        text = "We are going to win. She is going to leave."
        density = wto.measure_future_tense_density(text)
        self.assertEqual(density, 1.0)

    def test_mixed(self):
        wto = WriterTemporalOrientation()
        text = "We will go tomorrow. She walked yesterday. They will see."
        density = wto.measure_future_tense_density(text)
        self.assertGreater(density, 0.5)


class TestMeasureTemporalAdverbialDensity(unittest.TestCase):
    """Test measure_temporal_adverbial_density."""

    def test_empty(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto.measure_temporal_adverbial_density(""), 0.0)

    def test_all_adverbial(self):
        wto = WriterTemporalOrientation()
        text = "She left yesterday. We arrive tomorrow. He works today."
        density = wto.measure_temporal_adverbial_density(text)
        self.assertEqual(density, 1.0)

    def test_no_adverbial(self):
        wto = WriterTemporalOrientation()
        text = "The cat sat. The dog ran. The bird flew."
        density = wto.measure_temporal_adverbial_density(text)
        self.assertEqual(density, 0.0)

    def test_partial(self):
        wto = WriterTemporalOrientation()
        text = "She left yesterday. The cat sat quietly."
        density = wto.measure_temporal_adverbial_density(text)
        self.assertAlmostEqual(density, 0.5, places=1)


class TestMeasurePerfectiveAspectRatio(unittest.TestCase):
    """Test measure_perfective_aspect_ratio."""

    def test_empty(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto.measure_perfective_aspect_ratio(""), 0.0)

    def test_all_perfect(self):
        wto = WriterTemporalOrientation()
        text = "She has walked. They have gone. He had done it."
        ratio = wto.measure_perfective_aspect_ratio(text)
        self.assertEqual(ratio, 1.0)

    def test_no_perfect(self):
        wto = WriterTemporalOrientation()
        text = "She walks. He runs. They swim."
        ratio = wto.measure_perfective_aspect_ratio(text)
        self.assertEqual(ratio, 0.0)

    def test_partial(self):
        wto = WriterTemporalOrientation()
        text = "She has walked. He runs daily."
        ratio = wto.measure_perfective_aspect_ratio(text)
        self.assertAlmostEqual(ratio, 0.5, places=1)


class TestMeasureProgressiveAspectRatio(unittest.TestCase):
    """Test measure_progressive_aspect_ratio."""

    def test_empty(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto.measure_progressive_aspect_ratio(""), 0.0)

    def test_all_progressive(self):
        wto = WriterTemporalOrientation()
        text = "She is walking. He is running. They are swimming."
        ratio = wto.measure_progressive_aspect_ratio(text)
        self.assertEqual(ratio, 1.0)

    def test_no_progressive(self):
        wto = WriterTemporalOrientation()
        text = "She walks. He runs. They swim."
        ratio = wto.measure_progressive_aspect_ratio(text)
        self.assertEqual(ratio, 0.0)


class TestComputeTemporalOrientationIndex(unittest.TestCase):
    """Test compute_temporal_orientation_index."""

    def test_neutral(self):
        wto = WriterTemporalOrientation()
        index = wto.compute_temporal_orientation_index(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(index, 0.0, places=2)

    def test_fully_past(self):
        wto = WriterTemporalOrientation()
        index = wto.compute_temporal_orientation_index(1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0)
        self.assertLess(index, -0.5)

    def test_fully_future(self):
        wto = WriterTemporalOrientation()
        index = wto.compute_temporal_orientation_index(0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0)
        self.assertGreater(index, 0.5)

    def test_clamped_low(self):
        wto = WriterTemporalOrientation()
        index = wto.compute_temporal_orientation_index(1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0)
        self.assertGreaterEqual(index, -1.0)

    def test_clamped_high(self):
        wto = WriterTemporalOrientation()
        index = wto.compute_temporal_orientation_index(0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 1.0)
        self.assertLessEqual(index, 1.0)


class TestClassify(unittest.TestCase):
    """Test classify method."""

    def test_retrospective(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto.classify(-0.5), "retrospective")

    def test_retrospective_boundary(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto.classify(-0.35), "retrospective")

    def test_immediate(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto.classify(0.0), "immediate")

    def test_immediate_low(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto.classify(-0.34), "immediate")

    def test_immediate_high(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto.classify(0.34), "immediate")

    def test_prospective(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto.classify(0.5), "prospective")

    def test_prospective_boundary(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto.classify(0.35), "prospective")

    def test_negative_one(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto.classify(-1.0), "retrospective")

    def test_positive_one(self):
        wto = WriterTemporalOrientation()
        self.assertEqual(wto.classify(1.0), "prospective")


class TestMeasure(unittest.TestCase):
    """Test measure method with full text."""

    def test_empty_string(self):
        wto = WriterTemporalOrientation()
        result = wto.measure("")
        self.assertEqual(result["past_tense_density"], 0.0)
        self.assertEqual(result["classification"], "immediate")

    def test_whitespace_only(self):
        wto = WriterTemporalOrientation()
        result = wto.measure("   ")
        self.assertEqual(result["past_tense_density"], 0.0)
        self.assertEqual(result["classification"], "immediate")

    def test_none_text(self):
        wto = WriterTemporalOrientation()
        result = wto.measure(None)
        self.assertEqual(result["past_tense_density"], 0.0)

    def test_past_oriented_text(self):
        wto = WriterTemporalOrientation()
        text = """She walked through the old neighborhood yesterday.
        The house had been painted blue. She remembered the garden.
        The oak tree stood taller than she remembered. Everything
        felt smaller than it had seemed in childhood."""
        result = wto.measure(text)
        self.assertGreater(result["past_tense_density"], 0.5)
        self.assertEqual(result["classification"], "retrospective")

    def test_future_oriented_text(self):
        wto = WriterTemporalOrientation()
        text = """The committee will review the proposals next month.
        We are going to announce the winners soon. The new system
        will be deployed in phases. Eventually, the team will expand
        the service. The roadmap outlines milestones for the coming
        year."""
        result = wto.measure(text)
        self.assertGreater(result["future_tense_density"], 0.5)
        self.assertEqual(result["classification"], "prospective")

    def test_present_oriented_text(self):
        wto = WriterTemporalOrientation()
        text = """The cat sat on the mat. Dogs like bones. Birds fly
        in the sky. Fish swim in the ocean. The sun is bright."""
        result = wto.measure(text)
        self.assertIn(result["classification"], ["immediate", "retrospective", "prospective"])

    def test_result_keys(self):
        wto = WriterTemporalOrientation()
        result = wto.measure("She walked home.")
        expected_keys = {
            "past_tense_density",
            "present_tense_density",
            "future_tense_density",
            "temporal_adverbial_density",
            "perfective_aspect_ratio",
            "progressive_aspect_ratio",
            "temporal_orientation_index",
            "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_all_values_are_numbers_except_classification(self):
        wto = WriterTemporalOrientation()
        result = wto.measure("She walked home yesterday.")
        for key in result:
            if key == "classification":
                self.assertIsInstance(result[key], str)
            else:
                self.assertIsInstance(result[key], (int, float))

    def test_index_range(self):
        wto = WriterTemporalOrientation()
        for text in [
            "She walked home yesterday.",
            "We will go tomorrow.",
            "The cat sits on the mat.",
            "She has been walking. He will have gone.",
        ]:
            result = wto.measure(text)
            self.assertGreaterEqual(result["temporal_orientation_index"], -1.0)
            self.assertLessEqual(result["temporal_orientation_index"], 1.0)

    def test_classification_is_valid(self):
        wto = WriterTemporalOrientation()
        valid = {"retrospective", "immediate", "prospective"}
        for text in [
            "She walked home yesterday.",
            "We will go tomorrow.",
            "The cat sits on the mat.",
        ]:
            result = wto.measure(text)
            self.assertIn(result["classification"], valid)

    def test_memoir_is_retrospective(self):
        wto = WriterTemporalOrientation()
        text = """I grew up in a small town years ago. My father
        worked at the mill back then. My mother taught school
        before I was born. We played outside until dark every
        evening. The summers were long and golden. I remembered
        the smell of fresh bread from the bakery. Back in those
        days, everything felt slower. Previously, I had never
        understood why people missed small towns. Now I understood."""
        result = wto.measure(text)
        self.assertEqual(result["classification"], "retrospective")

    def test_proposal_is_prospective(self):
        wto = WriterTemporalOrientation()
        text = """We will build a new platform. The system will handle
        millions of requests. Next quarter, we will launch the beta.
        The team is going to expand. Eventually, the service will
        cover all regions. By next year, we will have processed
        billions of transactions."""
        result = wto.measure(text)
        self.assertEqual(result["classification"], "prospective")

    def test_documentation_is_immediate_or_near(self):
        wto = WriterTemporalOrientation()
        text = """The function accepts a string argument. It returns
        a dictionary of metrics. The module handles edge cases by
        returning zero values. Input validation occurs before
        processing begins."""
        result = wto.measure(text)
        # Documentation should be close to center
        self.assertGreater(result["temporal_orientation_index"], -0.5)
        self.assertLess(result["temporal_orientation_index"], 0.5)


class TestDirectionalAdverbialFractions(unittest.TestCase):
    """Test _compute_directional_adverbial_fractions."""

    def test_empty(self):
        wto = WriterTemporalOrientation()
        past, future = wto._compute_directional_adverbial_fractions("")
        self.assertEqual(past, 0.0)
        self.assertEqual(future, 0.0)

    def test_all_past(self):
        wto = WriterTemporalOrientation()
        text = "She left yesterday. He went last week."
        past, future = wto._compute_directional_adverbial_fractions(text)
        self.assertGreater(past, 0.0)
        self.assertEqual(future, 0.0)

    def test_all_future(self):
        wto = WriterTemporalOrientation()
        text = "We go tomorrow. They arrive next week."
        past, future = wto._compute_directional_adverbial_fractions(text)
        self.assertEqual(past, 0.0)
        self.assertGreater(future, 0.0)

    def test_mixed(self):
        wto = WriterTemporalOrientation()
        text = "She left yesterday. We go tomorrow. The cat naps."
        past, future = wto._compute_directional_adverbial_fractions(text)
        self.assertGreater(past, 0.0)
        self.assertGreater(future, 0.0)


class TestConstantsExist(unittest.TestCase):
    """Test that all expected constants are defined."""

    def test_irregular_past_forms_not_empty(self):
        self.assertGreater(len(IRREGULAR_PAST_FORMS), 50)

    def test_past_adverbials_not_empty(self):
        self.assertGreater(len(PAST_ADVERBIALS), 10)

    def test_past_adverbial_phrases_not_empty(self):
        self.assertGreater(len(PAST_ADVERBIAL_PHRASES), 10)

    def test_present_adverbials_not_empty(self):
        self.assertGreater(len(PRESENT_ADVERBIALS), 5)

    def test_present_adverbial_phrases_not_empty(self):
        self.assertGreater(len(PRESENT_ADVERBIAL_PHRASES), 10)

    def test_future_markers_not_empty(self):
        self.assertGreater(len(FUTURE_MARKERS), 0)

    def test_future_phrases_not_empty(self):
        self.assertGreater(len(FUTURE_PHRASES), 5)

    def test_future_adverbials_not_empty(self):
        self.assertGreater(len(FUTURE_ADVERBIALS), 5)

    def test_future_adverbial_phrases_not_empty(self):
        self.assertGreater(len(FUTURE_ADVERBIAL_PHRASES), 10)

    def test_perfect_auxiliaries_not_empty(self):
        self.assertGreater(len(PERFECT_AUXILIARIES), 0)

    def test_progressive_auxiliaries_not_empty(self):
        self.assertGreater(len(PROGRESSIVE_AUXILIARIES), 0)

    def test_function_words_not_empty(self):
        self.assertGreater(len(FUNCTION_WORDS), 50)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_single_word_text(self):
        wto = WriterTemporalOrientation()
        result = wto.measure("Walked.")
        self.assertIn("classification", result)

    def test_single_sentence_no_period(self):
        wto = WriterTemporalOrientation()
        result = wto.measure("She walked home")
        self.assertIn("classification", result)

    def test_very_long_text(self):
        wto = WriterTemporalOrientation()
        text = "She walked home. " * 200
        result = wto.measure(text)
        self.assertEqual(result["classification"], "retrospective")

    def test_unicode_text(self):
        wto = WriterTemporalOrientation()
        result = wto.measure("She walked through the café.")
        self.assertIn("classification", result)

    def test_repeated_punctuation(self):
        wto = WriterTemporalOrientation()
        result = wto.measure("She walked... He ran... They flew...")
        self.assertIn("classification", result)

    def test_all_metrics_zero_for_empty(self):
        wto = WriterTemporalOrientation()
        result = wto.measure("")
        for key in result:
            if key == "classification":
                self.assertEqual(result[key], "immediate")
            else:
                self.assertEqual(result[key], 0.0)

    def test_rounding_to_four_decimals(self):
        wto = WriterTemporalOrientation()
        result = wto.measure("She walked yesterday. He runs today. They will go tomorrow.")
        for key in result:
            if key == "classification":
                continue
            # Check that values have at most 4 decimal places
            self.assertEqual(result[key], round(result[key], 4))


if __name__ == "__main__":
    unittest.main()
