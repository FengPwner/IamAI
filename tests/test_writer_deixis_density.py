#!/usr/bin/env python3
"""Tests for writer_deixis_density — comprehensive test suite."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_deixis_density import (  # noqa: E402
    DEMONSTRATIVE_DEIXIS_RE,
    PERSONAL_DEIXIS_RE,
    SPATIAL_DEIXIS_RE,
    TEMPORAL_DEIXIS_RE,
    WriterDeixisDensity,
    _count_words,
    _split_sentences,
    analyse,
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


class TestCountWords(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_count_words(""), 0)

    def test_whitespace(self):
        self.assertEqual(_count_words("   "), 0)

    def test_single_word(self):
        self.assertEqual(_count_words("hello"), 1)

    def test_multiple_words(self):
        self.assertEqual(_count_words("the quick brown fox"), 4)

    def test_punctuation_attached(self):
        self.assertEqual(_count_words("hello, world!"), 2)

    def test_numbers_only(self):
        self.assertEqual(_count_words("123 456"), 0)

    def test_mixed(self):
        self.assertEqual(_count_words("hello 123 world"), 2)


# ── Pattern tests ───────────────────────────────────────────────────


class TestPersonalDeixisPattern(unittest.TestCase):
    def test_first_person_singular(self):
        matches = PERSONAL_DEIXIS_RE.findall("I told myself that my work is mine.")
        self.assertGreaterEqual(len(matches), 4)

    def test_first_person_plural(self):
        matches = PERSONAL_DEIXIS_RE.findall("We showed ourselves our work.")
        self.assertGreaterEqual(len(matches), 3)

    def test_second_person(self):
        matches = PERSONAL_DEIXIS_RE.findall("You hurt yourself with your words.")
        self.assertGreaterEqual(len(matches), 3)

    def test_third_person(self):
        matches = PERSONAL_DEIXIS_RE.findall("She told him about his car.")
        self.assertGreaterEqual(len(matches), 3)

    def test_plural_third(self):
        matches = PERSONAL_DEIXIS_RE.findall("They showed them their work.")
        self.assertGreaterEqual(len(matches), 3)

    def test_case_insensitive(self):
        matches = PERSONAL_DEIXIS_RE.findall("HE told HER about IT.")
        self.assertGreaterEqual(len(matches), 3)

    def test_no_false_positives(self):
        # "their" inside "therein" should not match
        matches = PERSONAL_DEIXIS_RE.findall("therein lies the answer.")
        # "therein" contains "the" + "rein", not "their"
        # but \b boundaries should prevent partial matches
        for m in matches:
            self.assertNotIn(m.lower(), ["their", "the"])


class TestSpatialDeixisPattern(unittest.TestCase):
    def test_basic_spatial(self):
        matches = SPATIAL_DEIXIS_RE.findall("Come here, go there, look nearby.")
        self.assertGreaterEqual(len(matches), 3)

    def test_compound_spatial(self):
        matches = SPATIAL_DEIXIS_RE.findall("Look over there by that place.")
        self.assertGreaterEqual(len(matches), 1)

    def test_directional(self):
        matches = SPATIAL_DEIXIS_RE.findall("Look above, then below.")
        self.assertEqual(len(matches), 2)

    def test_indefinite_location(self):
        matches = SPATIAL_DEIXIS_RE.findall(
            "It could be anywhere, everywhere, nowhere, somewhere."
        )
        self.assertEqual(len(matches), 4)

    def test_archaic(self):
        matches = SPATIAL_DEIXIS_RE.findall("Come hither, go thither, hence.")
        self.assertEqual(len(matches), 3)

    def test_where_variants(self):
        matches = SPATIAL_DEIXIS_RE.findall("Where are you? Wherever you go.")
        self.assertEqual(len(matches), 2)


class TestTemporalDeixisPattern(unittest.TestCase):
    def test_basic_temporal(self):
        matches = TEMPORAL_DEIXIS_RE.findall("Now, then, today, tomorrow.")
        self.assertEqual(len(matches), 4)

    def test_relative_temporal(self):
        matches = TEMPORAL_DEIXIS_RE.findall(
            "It happened recently, already finished, still pending."
        )
        self.assertEqual(len(matches), 3)

    def test_time_references(self):
        matches = TEMPORAL_DEIXIS_RE.findall(
            "Yesterday was good. Tonight will be better. Soon enough."
        )
        self.assertEqual(len(matches), 3)

    def test_before_after(self):
        matches = TEMPORAL_DEIXIS_RE.findall("Before that, afterwards this.")
        self.assertEqual(len(matches), 2)

    def test_formal_temporal(self):
        matches = TEMPORAL_DEIXIS_RE.findall(
            "Henceforth, heretofore, previously stated."
        )
        self.assertEqual(len(matches), 3)


class TestDemonstrativeDeixisPattern(unittest.TestCase):
    def test_basic_demonstratives(self):
        matches = DEMONSTRATIVE_DEIXIS_RE.findall(
            "This and that, these and those."
        )
        self.assertEqual(len(matches), 4)

    def test_such(self):
        matches = DEMONSTRATIVE_DEIXIS_RE.findall("Such is the way.")
        self.assertEqual(len(matches), 1)

    def test_formal_references(self):
        matches = DEMONSTRATIVE_DEIXIS_RE.findall(
            "The aforementioned point. The said document. The above statement."
        )
        self.assertEqual(len(matches), 3)

    def test_latter_former(self):
        matches = DEMONSTRATIVE_DEIXIS_RE.findall(
            "The latter point. The former argument."
        )
        self.assertEqual(len(matches), 2)

    def test_the_following(self):
        matches = DEMONSTRATIVE_DEIXIS_RE.findall("Consider the following items.")
        self.assertEqual(len(matches), 1)


# ── Signal tests ────────────────────────────────────────────────────


class TestPersonalDeixisRate(unittest.TestCase):
    def test_no_pronouns(self):
        text = "The cat sat on the mat. The dog ran across the field."
        w = WriterDeixisDensity(text)
        self.assertEqual(w.personal_deixis_rate, 0.0)

    def test_all_pronouns(self):
        text = "I saw you. He told her. They asked us. We told them."
        w = WriterDeixisDensity(text)
        self.assertGreater(w.personal_deixis_rate, 100.0)

    def test_moderate_pronouns(self):
        text = (
            "The experiment was conducted carefully. "
            "We measured the results. The data showed improvement. "
            "She published the findings. The team celebrated."
        )
        w = WriterDeixisDensity(text)
        self.assertGreater(w.personal_deixis_rate, 0.0)
        self.assertLess(w.personal_deixis_rate, 100.0)


class TestSpatialDeixisRate(unittest.TestCase):
    def test_no_spatial(self):
        text = "The function returns the sum of two integers."
        w = WriterDeixisDensity(text)
        self.assertEqual(w.spatial_deixis_rate, 0.0)

    def test_heavy_spatial(self):
        text = "Come here. Go there. Look nearby. Check above. Look below."
        w = WriterDeixisDensity(text)
        self.assertGreater(w.spatial_deixis_rate, 50.0)


class TestTemporalDeixisRate(unittest.TestCase):
    def test_no_temporal(self):
        text = "The algorithm processes each element in constant time."
        w = WriterDeixisDensity(text)
        self.assertEqual(w.temporal_deixis_rate, 0.0)

    def test_heavy_temporal(self):
        text = (
            "Now we begin. Then we continue. Today is good. "
            "Tomorrow will be better. Yesterday was rough."
        )
        w = WriterDeixisDensity(text)
        self.assertGreater(w.temporal_deixis_rate, 50.0)


class TestDemonstrativeDeixisRate(unittest.TestCase):
    def test_no_demonstratives(self):
        text = "An algorithm processes data efficiently."
        w = WriterDeixisDensity(text)
        self.assertEqual(w.demonstrative_deixis_rate, 0.0)

    def test_heavy_demonstratives(self):
        text = (
            "This is important. That matters too. These are useful. "
            "Those were helpful. Such things happen."
        )
        w = WriterDeixisDensity(text)
        self.assertGreater(w.demonstrative_deixis_rate, 50.0)


class TestDeicticWordShare(unittest.TestCase):
    def test_no_deictic_words(self):
        text = "Algorithms process data efficiently using binary search."
        w = WriterDeixisDensity(text)
        self.assertEqual(w.deictic_word_share, 0.0)

    def test_all_deictic_words(self):
        text = "I you he she it we they here there now then this that."
        w = WriterDeixisDensity(text)
        self.assertGreater(w.deictic_word_share, 0.5)

    def test_mixed(self):
        text = (
            "I walked here today because this meeting matters. "
            "The quarterly earnings report was published on schedule."
        )
        w = WriterDeixisDensity(text)
        self.assertGreater(w.deictic_word_share, 0.0)
        self.assertLess(w.deictic_word_share, 1.0)


class TestAnaphoricChainRatio(unittest.TestCase):
    def test_no_chains(self):
        # Each sentence has at most one deictic reference
        text = "I walked. He ran. She stayed."
        w = WriterDeixisDensity(text)
        self.assertEqual(w.anaphoric_chain_ratio, 0.0)

    def test_all_chains(self):
        # Every sentence has 3+ deictic references
        text = (
            "She told him that this was theirs now. "
            "He asked her why those things mattered then. "
            "They showed us these items here today."
        )
        w = WriterDeixisDensity(text)
        self.assertGreater(w.anaphoric_chain_ratio, 0.5)

    def test_no_deixis_returns_zero(self):
        text = "Algorithms process data efficiently."
        w = WriterDeixisDensity(text)
        self.assertEqual(w.anaphoric_chain_ratio, 0.0)

    def test_mixed_chains(self):
        text = (
            "I went home. "
            "She told him that this was important now. "
            "The algorithm works. "
            "They asked us why those things mattered."
        )
        w = WriterDeixisDensity(text)
        self.assertGreater(w.anaphoric_chain_ratio, 0.0)
        self.assertLess(w.anaphoric_chain_ratio, 1.0)


# ── Composite tests ─────────────────────────────────────────────────


class TestDeixisDensityIndex(unittest.TestCase):
    def test_zero_for_non_deictic(self):
        text = "Algorithms process data using binary search trees efficiently."
        w = WriterDeixisDensity(text)
        self.assertEqual(w.deixis_density_index, 0.0)

    def test_high_for_heavily_deictic(self):
        text = (
            "I told you that this here now matters. "
            "She showed him those things there then. "
            "We asked them why these items nearby today "
            "seemed important to us."
        )
        w = WriterDeixisDensity(text)
        self.assertGreater(w.deixis_density_index, 0.3)

    def test_range(self):
        for text in [
            "Hello world.",
            "I told her that this here now matters to us all.",
            "The algorithm processes data in linear time.",
            "She stood there, watching him, wondering if they would come.",
        ]:
            w = WriterDeixisDensity(text)
            idx = w.deixis_density_index
            self.assertGreaterEqual(idx, 0.0)
            self.assertLessEqual(idx, 1.0)


class TestClassification(unittest.TestCase):
    def test_context_independent(self):
        text = "Algorithms process data using binary search trees efficiently."
        w = WriterDeixisDensity(text)
        self.assertEqual(w.classification, "context_independent")

    def test_heavily_deictic(self):
        text = ". ".join(
            ["I told you that this here now matters to us all"] * 10
        ) + "."
        w = WriterDeixisDensity(text)
        self.assertIn(w.classification, [
            "heavily_deictic", "deictic_saturated", "moderately_deictic"
        ])

    def test_all_classifications_are_valid(self):
        valid = {
            "context_independent", "lightly_deictic", "moderately_deictic",
            "heavily_deictic", "deictic_saturated",
        }
        for text in [
            "Algorithms process data.",
            "I went there yesterday.",
            "She told him that this was important now.",
            "I told you here now that this matters to us.",
            ". ".join(["I told you that this here now"] * 20) + ".",
        ]:
            w = WriterDeixisDensity(text)
            self.assertIn(w.classification, valid)


# ── Convenience function ────────────────────────────────────────────


class TestAnalyse(unittest.TestCase):
    def test_returns_dict(self):
        result = analyse("Hello world.")
        self.assertIsInstance(result, dict)

    def test_keys_present(self):
        result = analyse("I went there yesterday.")
        expected_keys = {
            "personal_deixis_rate",
            "spatial_deixis_rate",
            "temporal_deixis_rate",
            "demonstrative_deixis_rate",
            "deictic_word_share",
            "anaphoric_chain_ratio",
            "deixis_density_index",
            "classification",
            "n_sentences",
            "n_words",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_empty_text(self):
        result = analyse("")
        self.assertEqual(result["deixis_density_index"], 0.0)
        self.assertEqual(result["classification"], "context_independent")

    def test_rich_input(self):
        text = (
            "I told you that this here now matters to us all. "
            "She showed him those things there then."
        )
        result = analyse(text)
        self.assertGreater(result["deixis_density_index"], 0.0)


# ── Orthogonality sanity tests ──────────────────────────────────────


class TestOrthogonality(unittest.TestCase):
    """Verify that deixis density varies independently of other qualities."""

    def test_deictic_but_clear(self):
        text = (
            "I am here now. You are there then. "
            "This is that thing we discussed."
        )
        w = WriterDeixisDensity(text)
        self.assertGreater(w.deixis_density_index, 0.0)
        # Very clear prose, but heavily deictic

    def test_deictic_but_concise(self):
        text = "I saw it here now."
        w = WriterDeixisDensity(text)
        self.assertGreater(w.deixis_density_index, 0.0)
        # Concise yet deictic

    def test_context_independent_but_verbose(self):
        text = (
            "The complex computational system processes input data "
            "through a series of transformational stages, each "
            "applying specific mathematical operations to produce "
            "the desired output format."
        )
        w = WriterDeixisDensity(text)
        self.assertEqual(w.deixis_density_index, 0.0)
        # Verbose but no deictic references

    def test_context_independent_but_hedged(self):
        text = (
            "It might be possible that the results are somewhat inconclusive. "
            "Perhaps the methodology could potentially be improved."
        )
        w = WriterDeixisDensity(text)
        self.assertLess(w.deixis_density_index, 0.3)
        # Hedged but not heavily deictic (no pronouns, no spatial/temporal)


# ── Boundary tests ───────────────────────────────────────────────────


class TestBoundaries(unittest.TestCase):
    def test_one_sentence(self):
        w = WriterDeixisDensity("Hello.")
        self.assertEqual(w.deixis_density_index, 0.0)

    def test_two_sentences(self):
        w = WriterDeixisDensity("Hello. I am here now.")
        self.assertGreater(w.personal_deixis_rate, 0.0)
        self.assertGreater(w.spatial_deixis_rate, 0.0)
        self.assertGreater(w.temporal_deixis_rate, 0.0)

    def test_many_sentences(self):
        text = ". ".join([f"Sentence number {i}" for i in range(100)]) + "."
        w = WriterDeixisDensity(text)
        self.assertEqual(w.deixis_density_index, 0.0)

    def test_all_deictic_sentences(self):
        text = ". ".join(
            ["I told you that this here now"] * 10
        ) + "."
        w = WriterDeixisDensity(text)
        self.assertGreater(w.personal_deixis_rate, 100.0)
        self.assertGreater(w.deixis_density_index, 0.3)


# ── Genre comparison tests ──────────────────────────────────────────


class TestGenreComparison(unittest.TestCase):
    """Verify expected differences between text genres."""

    def test_technical_is_less_deictic_than_conversational(self):
        technical = (
            "The function accepts a string parameter. "
            "It returns a boolean value. "
            "Empty input raises a ValueError. "
            "Thread safety is guaranteed by a mutex lock."
        )
        conversational = (
            "I told you yesterday that this thing here matters. "
            "She showed me those items over there. "
            "We need to go there tomorrow. "
            "They asked us why we stayed here."
        )
        tech_w = WriterDeixisDensity(technical)
        conv_w = WriterDeixisDensity(conversational)
        self.assertLess(tech_w.deixis_density_index, conv_w.deixis_density_index)

    def test_narrative_has_more_personal_deixis_than_exposition(self):
        narrative = (
            "I walked to the store. She met me there. "
            "We bought groceries. He paid for them."
        )
        exposition = (
            "Grocery stores sell food. Customers purchase items. "
            "Payment occurs at checkout. Receipts document transactions."
        )
        narr_w = WriterDeixisDensity(narrative)
        expo_w = WriterDeixisDensity(exposition)
        self.assertGreater(
            narr_w.personal_deixis_rate, expo_w.personal_deixis_rate
        )


if __name__ == "__main__":
    unittest.main()
