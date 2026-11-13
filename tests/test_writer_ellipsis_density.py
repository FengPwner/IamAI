#!/usr/bin/env python3
"""Tests for writer_ellipsis_density — comprehensive test suite."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_ellipsis_density import (  # noqa: E402
    STOP_WORDS,
    WriterEllipsisDensity,
    _content_words,
    _split_sentences,
    _tokenize,
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

    def test_ellipsis_in_text(self):
        result = _split_sentences("She waited… He arrived… They left.")
        self.assertTrue(len(result) >= 1)

    def test_newlines(self):
        result = _split_sentences("First sentence.\nSecond sentence.")
        self.assertEqual(len(result), 2)


class TestTokenize(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(_tokenize("Hello world"), ["hello", "world"])

    def test_contractions(self):
        self.assertEqual(_tokenize("don't stop"), ["don't", "stop"])

    def test_punctuation_stripped(self):
        result = _tokenize("She said, 'hello!'")
        self.assertIn("she", result)
        self.assertIn("said", result)
        self.assertIn("hello", result)

    def test_empty(self):
        self.assertEqual(_tokenize(""), [])

    def test_numbers_ignored(self):
        result = _tokenize("42 cats ran")
        self.assertEqual(result, ["cats", "ran"])

    def test_unicode_ellipsis(self):
        result = _tokenize("waiting…")
        self.assertEqual(result, ["waiting"])


class TestContentWords(unittest.TestCase):
    def test_filters_stopwords(self):
        tokens = ["the", "cat", "in", "the", "hat"]
        self.assertEqual(_content_words(tokens), ["cat", "hat"])

    def test_filters_short_tokens(self):
        tokens = ["a", "i", "oh", "hello"]
        self.assertEqual(_content_words(tokens), ["hello"])

    def test_empty(self):
        self.assertEqual(_content_words([]), [])

    def test_all_stopwords(self):
        tokens = ["the", "in", "on", "at"]
        self.assertEqual(_content_words(tokens), [])


# ── Syntactic Ellipsis Rate ──────────────────────────────────────────


class TestSyntacticEllipsisRate(unittest.TestCase):
    def setUp(self):
        self.wed = WriterEllipsisDensity()

    def test_empty_text(self):
        self.assertEqual(self.wed.syntactic_ellipsis_rate(""), 0.0)

    def test_whitespace_only(self):
        self.assertEqual(self.wed.syntactic_ellipsis_rate("   "), 0.0)

    def test_all_explicit_subjects(self):
        text = "She walked home. He opened the door. They sat down."
        rate = self.wed.syntactic_ellipsis_rate(text)
        self.assertEqual(rate, 0.0)

    def test_dropped_subjects(self):
        text = "Went to the store. Bought some milk. Came home tired."
        rate = self.wed.syntactic_ellipsis_rate(text)
        self.assertGreater(rate, 0.5)

    def test_mixed_subjects(self):
        text = "She walked to the park. Sat on the bench. Watched the children play."
        rate = self.wed.syntactic_ellipsis_rate(text)
        self.assertGreater(rate, 0.0)
        self.assertLessEqual(rate, 1.0)

    def test_fragments(self):
        text = "A cold wind. The empty street. Silence."
        rate = self.wed.syntactic_ellipsis_rate(text)
        self.assertGreater(rate, 0.5)

    def test_single_explicit_sentence(self):
        text = "The cat sat on the mat."
        self.assertEqual(self.wed.syntactic_ellipsis_rate(text), 0.0)

    def test_single_fragment(self):
        text = "Silence."
        rate = self.wed.syntactic_ellipsis_rate(text)
        self.assertGreater(rate, 0.0)

    def test_verb_initial_sentences(self):
        text = "Running through the rain. Jumping over puddles. Dancing in the dark."
        rate = self.wed.syntactic_ellipsis_rate(text)
        self.assertEqual(rate, 1.0)


# ── Punctuation Gap Rate ─────────────────────────────────────────────


class TestPunctuationGapRate(unittest.TestCase):
    def setUp(self):
        self.wed = WriterEllipsisDensity()

    def test_empty_text(self):
        self.assertEqual(self.wed.punctuation_gap_rate(""), 0.0)

    def test_no_gaps(self):
        text = "She walked home. He opened the door. They ate dinner."
        self.assertEqual(self.wed.punctuation_gap_rate(text), 0.0)

    def test_ellipsis_unicode(self):
        text = "She waited… He arrived… They left."
        rate = self.wed.punctuation_gap_rate(text)
        self.assertGreater(rate, 0.0)

    def test_ellipsis_dots(self):
        text = "She waited.. He arrived.. They left."
        rate = self.wed.punctuation_gap_rate(text)
        self.assertGreater(rate, 0.0)

    def test_em_dashes(self):
        text = "The door — old and creaking — opened slowly."
        rate = self.wed.punctuation_gap_rate(text)
        self.assertGreater(rate, 0.0)

    def test_double_hyphen(self):
        text = "The door -- old and creaking -- opened slowly."
        rate = self.wed.punctuation_gap_rate(text)
        self.assertGreater(rate, 0.0)

    def test_mixed_gaps(self):
        text = "She waited… The door — always sticky — wouldn't open. Silence."
        rate = self.wed.punctuation_gap_rate(text)
        self.assertGreater(rate, 0.5)

    def test_single_sentence_one_gap(self):
        text = "She paused — then continued."
        rate = self.wed.punctuation_gap_rate(text)
        self.assertGreater(rate, 0.0)

    def test_many_gaps(self):
        text = "This… that… the other… always something…"
        rate = self.wed.punctuation_gap_rate(text)
        self.assertGreater(rate, 0.0)


# ── Vague Reference Rate ────────────────────────────────────────────


class TestVagueReferenceRate(unittest.TestCase):
    def setUp(self):
        self.wed = WriterEllipsisDensity()

    def test_empty_text(self):
        self.assertEqual(self.wed.vague_reference_rate(""), 0.0)

    def test_no_vague_references(self):
        text = "The cat sat on the mat. The dog ran in the park."
        self.assertEqual(self.wed.vague_reference_rate(text), 0.0)

    def test_something(self):
        text = "Something moved in the shadows."
        rate = self.wed.vague_reference_rate(text)
        self.assertGreater(rate, 0.0)

    def test_someone(self):
        text = "Someone knocked at the door."
        rate = self.wed.vague_reference_rate(text)
        self.assertGreater(rate, 0.0)

    def test_everything(self):
        text = "Everything changed after that day."
        rate = self.wed.vague_reference_rate(text)
        self.assertGreater(rate, 0.0)

    def test_nothing(self):
        text = "Nothing mattered anymore."
        rate = self.wed.vague_reference_rate(text)
        self.assertGreater(rate, 0.0)

    def test_multiple_vague(self):
        text = "Something was wrong. Someone had taken everything. Nobody knew anything."
        rate = self.wed.vague_reference_rate(text)
        self.assertGreater(rate, 1.0)

    def test_whatever(self):
        text = "Whatever happens, happens."
        rate = self.wed.vague_reference_rate(text)
        self.assertGreater(rate, 0.0)

    def test_stuff(self):
        text = "The stuff on the table was old."
        rate = self.wed.vague_reference_rate(text)
        self.assertGreater(rate, 0.0)

    def test_things(self):
        text = "Things were different now."
        rate = self.wed.vague_reference_rate(text)
        self.assertGreater(rate, 0.0)

    def test_anywhere(self):
        text = "She couldn't find it anywhere."
        rate = self.wed.vague_reference_rate(text)
        self.assertGreater(rate, 0.0)


# ── Trailing Off Rate ────────────────────────────────────────────────


class TestTrailingOffRate(unittest.TestCase):
    def setUp(self):
        self.wed = WriterEllipsisDensity()

    def test_empty_text(self):
        self.assertEqual(self.wed.trailing_off_rate(""), 0.0)

    def test_no_trailing(self):
        text = "She walked home. He opened the door. They sat down."
        self.assertEqual(self.wed.trailing_off_rate(text), 0.0)

    def test_ellipsis_trailing(self):
        text = "She walked home… He opened the door… They sat down…"
        rate = self.wed.trailing_off_rate(text)
        self.assertGreater(rate, 0.0)

    def test_dash_trailing(self):
        text = "She walked home— He opened the door— They sat down—"
        rate = self.wed.trailing_off_rate(text)
        self.assertGreater(rate, 0.0)

    def test_mixed_trailing(self):
        text = "She walked home. He opened the door… They sat down."
        rate = self.wed.trailing_off_rate(text)
        self.assertGreater(rate, 0.0)
        self.assertLess(rate, 1.0)

    def test_all_trailing(self):
        text = "Waiting… Always waiting… The clock ticking…"
        rate = self.wed.trailing_off_rate(text)
        self.assertEqual(rate, 1.0)

    def test_period_ending(self):
        text = "The experiment concluded successfully."
        self.assertEqual(self.wed.trailing_off_rate(text), 0.0)

    def test_double_dot_trailing(self):
        text = "She paused.. then continued.."
        rate = self.wed.trailing_off_rate(text)
        self.assertGreater(rate, 0.0)


# ── Inference Load ───────────────────────────────────────────────────


class TestInferenceLoad(unittest.TestCase):
    def setUp(self):
        self.wed = WriterEllipsisDensity()

    def test_empty_text(self):
        self.assertEqual(self.wed.inference_load(""), 0.0)

    def test_no_inference(self):
        text = "The cat sat on the mat. The dog ran in the park."
        rate = self.wed.inference_load(text)
        self.assertEqual(rate, 0.0)

    def test_you_know(self):
        text = "You know what I mean. The thing happened."
        rate = self.wed.inference_load(text)
        self.assertGreater(rate, 0.0)

    def test_of_course(self):
        text = "Of course, it was obvious. The answer was clear."
        rate = self.wed.inference_load(text)
        self.assertGreater(rate, 0.0)

    def test_needless_to_say(self):
        text = "Needless to say, the plan failed."
        rate = self.wed.inference_load(text)
        self.assertGreater(rate, 0.0)

    def test_rhetorical_questions(self):
        text = "Why bother? What's the point? Who cares?"
        rate = self.wed.inference_load(text)
        self.assertGreater(rate, 0.0)

    def test_parenthetical(self):
        text = "The plan (which everyone knew would fail) proceeded anyway."
        rate = self.wed.inference_load(text)
        self.assertGreater(rate, 0.0)

    def test_obviously(self):
        text = "Obviously, the results were significant."
        rate = self.wed.inference_load(text)
        self.assertGreater(rate, 0.0)

    def test_naturally(self):
        text = "Naturally, she agreed to the proposal."
        rate = self.wed.inference_load(text)
        self.assertGreater(rate, 0.0)

    def test_mixed_inference(self):
        text = "Of course, you know how it goes. Why bother asking? The answer (obviously) was no."
        rate = self.wed.inference_load(text)
        self.assertGreater(rate, 1.0)

    def test_as_they_say(self):
        text = "As they say, time heals all wounds."
        rate = self.wed.inference_load(text)
        self.assertGreater(rate, 0.0)

    def test_single_question(self):
        text = "The cat sat on the mat. Why?"
        rate = self.wed.inference_load(text)
        self.assertGreater(rate, 0.0)
        self.assertLessEqual(rate, 1.0)


# ── Composite ────────────────────────────────────────────────────────


class TestComposite(unittest.TestCase):
    def setUp(self):
        self.wed = WriterEllipsisDensity()

    def test_empty_measure(self):
        result = self.wed.measure("")
        self.assertEqual(result["ellipsis_density_index"], 0.0)
        self.assertEqual(result["classification"], "fully_explicit")

    def test_whitespace_measure(self):
        result = self.wed.measure("   \n   ")
        self.assertEqual(result["ellipsis_density_index"], 0.0)
        self.assertEqual(result["classification"], "fully_explicit")

    def test_explicit_text(self):
        text = """
        The researcher opened the laboratory notebook and reviewed
        the experimental results from Tuesday. The temperature had
        reached forty-two degrees Celsius before the reaction stopped.
        Three samples were contaminated during the transfer process.
        The team scheduled a meeting for Thursday to discuss the
        contamination issue.
        """
        result = self.wed.measure(text)
        self.assertLess(result["ellipsis_density_index"], 0.25)
        self.assertIn(result["classification"], [
            "fully_explicit", "minimally_elliptical"
        ])

    def test_elliptical_text(self):
        text = """
        Went to the window again. The same view — grey sky, wet
        street, the cat on the wall. Something had changed though.
        Couldn't say what. Maybe the light. Maybe nothing at all…

        Of course, it was never about the view. You know how it
        goes — you look out and you're really looking in. Somewhere
        in the distance, a bell. Then silence.

        If only things were simpler. Imagine a world where…
        """
        result = self.wed.measure(text)
        self.assertGreater(result["ellipsis_density_index"], 0.15)
        self.assertIn(result["classification"], [
            "minimally_elliptical", "moderately_elliptical",
            "richly_elliptical", "radically_elliptical"
        ])

    def test_measure_returns_all_keys(self):
        text = "She walked home. Something was different."
        result = self.wed.measure(text)
        expected_keys = {
            "syntactic_ellipsis_rate",
            "punctuation_gap_rate",
            "vague_reference_rate",
            "trailing_off_rate",
            "inference_load",
            "ellipsis_density_index",
            "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_all_values_rounded(self):
        text = "Something happened… Maybe nothing. You know how it goes."
        result = self.wed.measure(text)
        for key in [
            "syntactic_ellipsis_rate",
            "punctuation_gap_rate",
            "vague_reference_rate",
            "trailing_off_rate",
            "inference_load",
            "ellipsis_density_index",
        ]:
            value = result[key]
            # Check that value is rounded to 4 decimal places
            self.assertEqual(value, round(value, 4))

    def test_index_bounds(self):
        """Index should be between 0 and 1 for any text."""
        texts = [
            "Simple text.",
            "…",
            "Something — everything — nothing…",
            "Went there. Did that. Came back.",
            "The committee approved the revised budget proposal for fiscal year 2027.",
        ]
        for text in texts:
            result = self.wed.measure(text)
            self.assertGreaterEqual(result["ellipsis_density_index"], 0.0)
            self.assertLessEqual(result["ellipsis_density_index"], 1.0)


# ── Classification ───────────────────────────────────────────────────


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.wed = WriterEllipsisDensity()

    def test_fully_explicit(self):
        self.assertEqual(self.wed.classify(0.0), "fully_explicit")
        self.assertEqual(self.wed.classify(0.05), "fully_explicit")
        self.assertEqual(self.wed.classify(0.09), "fully_explicit")

    def test_minimally_elliptical(self):
        self.assertEqual(self.wed.classify(0.10), "minimally_elliptical")
        self.assertEqual(self.wed.classify(0.20), "minimally_elliptical")
        self.assertEqual(self.wed.classify(0.24), "minimally_elliptical")

    def test_moderately_elliptical(self):
        self.assertEqual(self.wed.classify(0.25), "moderately_elliptical")
        self.assertEqual(self.wed.classify(0.35), "moderately_elliptical")
        self.assertEqual(self.wed.classify(0.44), "moderately_elliptical")

    def test_richly_elliptical(self):
        self.assertEqual(self.wed.classify(0.45), "richly_elliptical")
        self.assertEqual(self.wed.classify(0.55), "richly_elliptical")
        self.assertEqual(self.wed.classify(0.64), "richly_elliptical")

    def test_radically_elliptical(self):
        self.assertEqual(self.wed.classify(0.65), "radically_elliptical")
        self.assertEqual(self.wed.classify(0.80), "radically_elliptical")
        self.assertEqual(self.wed.classify(1.0), "radically_elliptical")

    def test_boundary_values(self):
        # Test exact boundary values
        self.assertEqual(self.wed.classify(0.099), "fully_explicit")
        self.assertEqual(self.wed.classify(0.1), "minimally_elliptical")
        self.assertEqual(self.wed.classify(0.249), "minimally_elliptical")
        self.assertEqual(self.wed.classify(0.25), "moderately_elliptical")
        self.assertEqual(self.wed.classify(0.449), "moderately_elliptical")
        self.assertEqual(self.wed.classify(0.45), "richly_elliptical")
        self.assertEqual(self.wed.classify(0.649), "richly_elliptical")
        self.assertEqual(self.wed.classify(0.65), "radically_elliptical")


# ── Compute Ellipsis Density Index ──────────────────────────────────


class TestComputeIndex(unittest.TestCase):
    def setUp(self):
        self.wed = WriterEllipsisDensity()

    def test_all_zeros(self):
        index = self.wed.compute_ellipsis_density_index(0, 0, 0, 0, 0)
        self.assertEqual(index, 0.0)

    def test_all_ones(self):
        # Max values (before capping in normalization)
        index = self.wed.compute_ellipsis_density_index(1.0, 3.0, 2.0, 1.0, 3.0)
        self.assertLessEqual(index, 1.0)
        self.assertGreater(index, 0.5)

    def test_weights_sum(self):
        # When all normalized to 1.0, index should be 1.0
        index = self.wed.compute_ellipsis_density_index(1.0, 3.0, 2.0, 1.0, 3.0)
        self.assertAlmostEqual(index, 1.0, places=2)

    def test_partial_values(self):
        index = self.wed.compute_ellipsis_density_index(0.5, 1.5, 1.0, 0.5, 1.5)
        self.assertGreater(index, 0.0)
        self.assertLess(index, 1.0)

    def test_only_syntactic(self):
        index = self.wed.compute_ellipsis_density_index(1.0, 0, 0, 0, 0)
        self.assertAlmostEqual(index, 0.25, places=2)

    def test_only_punctuation(self):
        index = self.wed.compute_ellipsis_density_index(0, 3.0, 0, 0, 0)
        self.assertAlmostEqual(index, 0.20, places=2)

    def test_only_vague(self):
        index = self.wed.compute_ellipsis_density_index(0, 0, 2.0, 0, 0)
        self.assertAlmostEqual(index, 0.15, places=2)

    def test_only_trailing(self):
        index = self.wed.compute_ellipsis_density_index(0, 0, 0, 1.0, 0)
        self.assertAlmostEqual(index, 0.20, places=2)

    def test_only_inference(self):
        index = self.wed.compute_ellipsis_density_index(0, 0, 0, 0, 3.0)
        self.assertAlmostEqual(index, 0.20, places=2)

    def test_capping(self):
        # Values exceeding normalization caps should be capped
        index_capped = self.wed.compute_ellipsis_density_index(2.0, 10.0, 5.0, 2.0, 10.0)
        index_max = self.wed.compute_ellipsis_density_index(1.0, 3.0, 2.0, 1.0, 3.0)
        self.assertAlmostEqual(index_capped, index_max, places=4)


# ── Integration Tests ────────────────────────────────────────────────


class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.wed = WriterEllipsisDensity()

    def test_hemingway_style(self):
        """Hemingway-style prose should be moderately elliptical."""
        text = """
        He sat at the table and looked at the empty plate. The
        waiter came. Nothing to say. The rain outside — steady,
        grey, endless. Something about the way the light fell
        across the floor. Maybe it was the hour. Maybe it was
        nothing.
        """
        result = self.wed.measure(text)
        self.assertGreater(result["ellipsis_density_index"], 0.10)

    def test_technical_documentation(self):
        """Technical docs should be minimally elliptical."""
        text = """
        The function accepts two parameters: a string representing
        the file path and an integer specifying the buffer size.
        The function returns a dictionary containing the parsed
        results. If the file does not exist, the function raises
        a FileNotFoundError exception.
        """
        result = self.wed.measure(text)
        self.assertLess(result["ellipsis_density_index"], 0.25)

    def test_poetry_fragment(self):
        """Poetry fragments should be highly elliptical."""
        text = """
        Petals on the wet bough. A sparrow — gone.
        Something in the wind. The silence after rain…
        Waiting. Always waiting. If only…
        """
        result = self.wed.measure(text)
        self.assertGreater(result["ellipsis_density_index"], 0.15)

    def test_dialog(self):
        """Dialog tends toward moderate ellipsis."""
        text = """
        You know what I mean. Of course you do. Something's
        wrong — can't you see it? Obviously not. Everything's
        fine. Sure. Why not?
        """
        result = self.wed.measure(text)
        self.assertGreater(result["ellipsis_density_index"], 0.10)

    def test_single_word(self):
        """Single word should still work without error."""
        result = self.wed.measure("Silence.")
        self.assertIn("ellipsis_density_index", result)
        self.assertGreaterEqual(result["ellipsis_density_index"], 0.0)

    def test_very_long_text(self):
        """Should handle long texts without error."""
        sentences = [
            "The researcher examined the data carefully.",
            "Something seemed wrong with the results.",
            "The experiment — always problematic — had failed again.",
            "Why did this keep happening?",
            "Of course, the answer was obvious.",
        ] * 50
        text = " ".join(sentences)
        result = self.wed.measure(text)
        self.assertIn("ellipsis_density_index", result)
        self.assertGreaterEqual(result["ellipsis_density_index"], 0.0)
        self.assertLessEqual(result["ellipsis_density_index"], 1.0)


# ── Edge Cases ───────────────────────────────────────────────────────


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.wed = WriterEllipsisDensity()

    def test_only_punctuation(self):
        result = self.wed.measure("… — . ! ?")
        self.assertIn("ellipsis_density_index", result)

    def test_repeated_ellipsis(self):
        text = "… … … …"
        result = self.wed.measure(text)
        self.assertGreater(result["punctuation_gap_rate"], 0.0)

    def test_unicode_and_ascii(self):
        text = "She paused… He paused.. They both paused…"
        result = self.wed.measure(text)
        self.assertGreater(result["punctuation_gap_rate"], 0.0)

    def test_no_sentences_after_split(self):
        result = self.wed.measure("   \t\n  ")
        self.assertEqual(result["ellipsis_density_index"], 0.0)

    def test_all_vague_words(self):
        text = "Something somewhere somehow someone something."
        result = self.wed.measure(text)
        self.assertGreater(result["vague_reference_rate"], 0.0)

    def test_parenthetical_heavy(self):
        text = "The plan (which everyone doubted) proceeded (as expected) on schedule (naturally)."
        result = self.wed.measure(text)
        self.assertGreater(result["inference_load"], 0.0)

    def test_multiple_questions(self):
        text = "Why? How? When? Where? Who? What?"
        result = self.wed.measure(text)
        self.assertGreater(result["inference_load"], 0.0)

    def test_mixed_explicit_implicit(self):
        text = """
        The committee approved the budget. Something was missing.
        The chairman — always cautious — tabled the motion.
        Obviously, the decision was final. Why argue?
        """
        result = self.wed.measure(text)
        # Should be somewhere in the middle
        self.assertGreater(result["ellipsis_density_index"], 0.0)
        self.assertLessEqual(result["ellipsis_density_index"], 1.0)


if __name__ == "__main__":
    unittest.main()
