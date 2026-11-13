#!/usr/bin/env python3
"""Tests for writer_negation_density — comprehensive test suite."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_negation_density import (  # noqa: E402
    CONTRACTED_NEGATION_RE,
    EXPLICIT_NEGATION_RE,
    LITOTES_RE,
    NEGATIVE_PREFIX_RE,
    NEGATIVE_VERB_RE,
    WriterNegationDensity,
    _sentence_has_negation,
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


class TestSentenceHasNegation(unittest.TestCase):
    def test_plain_sentence(self):
        self.assertFalse(_sentence_has_negation("The cat sat on the mat."))

    def test_explicit_not(self):
        self.assertTrue(_sentence_has_negation("I do not agree."))

    def test_explicit_never(self):
        self.assertTrue(_sentence_has_negation("She never arrived."))

    def test_explicit_no(self):
        self.assertTrue(_sentence_has_negation("There is no evidence."))

    def test_explicit_neither(self):
        self.assertTrue(_sentence_has_negation("Neither option works."))

    def test_explicit_none(self):
        self.assertTrue(_sentence_has_negation("None of them came."))

    def test_explicit_nothing(self):
        self.assertTrue(_sentence_has_negation("Nothing happened."))

    def test_explicit_nobody(self):
        self.assertTrue(_sentence_has_negation("Nobody answered."))

    def test_explicit_nowhere(self):
        self.assertTrue(_sentence_has_negation("There is nowhere to go."))

    def test_contracted_dont(self):
        self.assertTrue(_sentence_has_negation("I don't think so."))

    def test_contracted_cant(self):
        self.assertTrue(_sentence_has_negation("She can't come."))

    def test_contracted_wont(self):
        self.assertTrue(_sentence_has_negation("They won't agree."))

    def test_contracted_isnt(self):
        self.assertTrue(_sentence_has_negation("It isn't fair."))

    def test_contracted_doesnt(self):
        self.assertTrue(_sentence_has_negation("He doesn't know."))

    def test_negative_prefix_impossible(self):
        self.assertTrue(_sentence_has_negation("It is impossible."))

    def test_negative_prefix_unfair(self):
        self.assertTrue(_sentence_has_negation("That is unfair."))

    def test_negative_prefix_disagree(self):
        self.assertTrue(_sentence_has_negation("I disagree with that."))

    def test_negative_prefix_nonexistent(self):
        self.assertTrue(_sentence_has_negation("The problem is nonexistent."))

    def test_negative_verb_deny(self):
        self.assertTrue(_sentence_has_negation("She denied the accusation."))

    def test_negative_verb_refuse(self):
        self.assertTrue(_sentence_has_negation("He refused the offer."))

    def test_negative_verb_avoid(self):
        self.assertTrue(_sentence_has_negation("They avoided the topic."))

    def test_negative_verb_reject(self):
        self.assertTrue(_sentence_has_negation("The board rejected the proposal."))

    def test_no_false_positive_note(self):
        # "note" contains "not" as substring but shouldn't match word boundary
        self.assertFalse(_sentence_has_negation("Please note the deadline."))

    def test_no_false_positive_know(self):
        self.assertFalse(_sentence_has_negation("I know the answer."))


# ── Pattern-level tests ─────────────────────────────────────────────


class TestExplicitNegationRE(unittest.TestCase):
    def test_matches_not(self):
        self.assertTrue(EXPLICIT_NEGATION_RE.search("I do not agree"))

    def test_matches_never(self):
        self.assertTrue(EXPLICIT_NEGATION_RE.search("She never came"))

    def test_matches_no(self):
        self.assertTrue(EXPLICIT_NEGATION_RE.search("No way"))

    def test_matches_neither(self):
        self.assertTrue(EXPLICIT_NEGATION_RE.search("Neither works"))

    def test_matches_nor(self):
        self.assertTrue(EXPLICIT_NEGATION_RE.search("Nor did he"))

    def test_matches_none(self):
        self.assertTrue(EXPLICIT_NEGATION_RE.search("None left"))

    def test_matches_nothing(self):
        self.assertTrue(EXPLICIT_NEGATION_RE.search("Nothing here"))

    def test_matches_nobody(self):
        self.assertTrue(EXPLICIT_NEGATION_RE.search("Nobody came"))

    def test_matches_nowhere(self):
        self.assertTrue(EXPLICIT_NEGATION_RE.search("Nowhere to go"))

    def test_no_partial_match(self):
        self.assertIsNone(EXPLICIT_NEGATION_RE.search("notable effort"))


class TestContractedNegationRE(unittest.TestCase):
    def test_dont(self):
        self.assertTrue(CONTRACTED_NEGATION_RE.search("don't"))

    def test_cant(self):
        self.assertTrue(CONTRACTED_NEGATION_RE.search("can't"))

    def test_wont(self):
        self.assertTrue(CONTRACTED_NEGATION_RE.search("won't"))

    def test_isnt(self):
        self.assertTrue(CONTRACTED_NEGATION_RE.search("isn't"))

    def test_arent(self):
        self.assertTrue(CONTRACTED_NEGATION_RE.search("aren't"))

    def test_wasnt(self):
        self.assertTrue(CONTRACTED_NEGATION_RE.search("wasn't"))

    def test_werent(self):
        self.assertTrue(CONTRACTED_NEGATION_RE.search("weren't"))

    def test_doesnt(self):
        self.assertTrue(CONTRACTED_NEGATION_RE.search("doesn't"))

    def test_didnt(self):
        self.assertTrue(CONTRACTED_NEGATION_RE.search("didn't"))

    def test_wouldnt(self):
        self.assertTrue(CONTRACTED_NEGATION_RE.search("wouldn't"))

    def test_couldnt(self):
        self.assertTrue(CONTRACTED_NEGATION_RE.search("couldn't"))

    def test_shouldnt(self):
        self.assertTrue(CONTRACTED_NEGATION_RE.search("shouldn't"))

    def test_havent(self):
        self.assertTrue(CONTRACTED_NEGATION_RE.search("haven't"))

    def test_hasnt(self):
        self.assertTrue(CONTRACTED_NEGATION_RE.search("hasn't"))

    def test_hadnt(self):
        self.assertTrue(CONTRACTED_NEGATION_RE.search("hadn't"))

    def test_neednt(self):
        self.assertTrue(CONTRACTED_NEGATION_RE.search("needn't"))

    def test_case_insensitive(self):
        self.assertTrue(CONTRACTED_NEGATION_RE.search("Can't"))

    def test_no_false_positive_cantankerous(self):
        self.assertIsNone(CONTRACTED_NEGATION_RE.search("cantankerous"))


class TestNegativePrefixRE(unittest.TestCase):
    def test_unhappy(self):
        self.assertTrue(NEGATIVE_PREFIX_RE.search("unhappy"))

    def test_impossible(self):
        self.assertTrue(NEGATIVE_PREFIX_RE.search("impossible"))

    def test_irregular(self):
        self.assertTrue(NEGATIVE_PREFIX_RE.search("irregular"))

    def test_illegal(self):
        self.assertTrue(NEGATIVE_PREFIX_RE.search("illegal"))

    def test_nonsense(self):
        self.assertTrue(NEGATIVE_PREFIX_RE.search("nonsense"))

    def test_disagree(self):
        self.assertTrue(NEGATIVE_PREFIX_RE.search("disagree"))

    def test_devalue(self):
        self.assertTrue(NEGATIVE_PREFIX_RE.search("devalue"))

    def test_antibiotic(self):
        self.assertTrue(NEGATIVE_PREFIX_RE.search("antibiotic"))

    def test_counterproductive(self):
        self.assertTrue(NEGATIVE_PREFIX_RE.search("counterproductive"))

    def test_misunderstand(self):
        self.assertTrue(NEGATIVE_PREFIX_RE.search("misunderstand"))

    def test_short_word_excluded(self):
        # Words shorter than 3 chars after prefix are excluded
        self.assertIsNone(NEGATIVE_PREFIX_RE.search("undo"))


class TestNegativeVerbRE(unittest.TestCase):
    def test_deny(self):
        self.assertTrue(NEGATIVE_VERB_RE.search("deny the claim"))

    def test_denies(self):
        self.assertTrue(NEGATIVE_VERB_RE.search("she denies it"))

    def test_denied(self):
        self.assertTrue(NEGATIVE_VERB_RE.search("he denied it"))

    def test_refuse(self):
        self.assertTrue(NEGATIVE_VERB_RE.search("refuse the offer"))

    def test_reject(self):
        self.assertTrue(NEGATIVE_VERB_RE.search("reject the proposal"))

    def test_decline(self):
        self.assertTrue(NEGATIVE_VERB_RE.search("decline the invitation"))

    def test_avoid(self):
        self.assertTrue(NEGATIVE_VERB_RE.search("avoid the issue"))

    def test_prevent(self):
        self.assertTrue(NEGATIVE_VERB_RE.search("prevent the error"))

    def test_prohibit(self):
        self.assertTrue(NEGATIVE_VERB_RE.search("prohibit smoking"))

    def test_forbid(self):
        self.assertTrue(NEGATIVE_VERB_RE.search("forbid entry"))

    def test_exclude(self):
        self.assertTrue(NEGATIVE_VERB_RE.search("exclude this option"))

    def test_negate(self):
        self.assertTrue(NEGATIVE_VERB_RE.search("negate the effect"))

    def test_oppose(self):
        self.assertTrue(NEGATIVE_VERB_RE.search("oppose the plan"))

    def test_case_insensitive(self):
        self.assertTrue(NEGATIVE_VERB_RE.search("Deny everything"))


class TestLitotesRE(unittest.TestCase):
    def test_not_bad(self):
        self.assertTrue(LITOTES_RE.search("not bad at all"))

    def test_not_uncommon(self):
        self.assertTrue(LITOTES_RE.search("not uncommon to see"))

    def test_not_unlike(self):
        self.assertTrue(LITOTES_RE.search("not unlike her mother"))

    def test_not_infrequent(self):
        self.assertTrue(LITOTES_RE.search("not infrequent occurrence"))

    def test_not_insignificant(self):
        self.assertTrue(LITOTES_RE.search("not insignificant amount"))

    def test_not_unreasonable(self):
        self.assertTrue(LITOTES_RE.search("not unreasonable request"))

    def test_not_impossible(self):
        self.assertTrue(LITOTES_RE.search("not impossible to achieve"))

    def test_not_unusual(self):
        self.assertTrue(LITOTES_RE.search("not unusual behavior"))

    def test_not_unlikely(self):
        self.assertTrue(LITOTES_RE.search("not unlikely outcome"))

    def test_positive_statement_no_match(self):
        self.assertIsNone(LITOTES_RE.search("this is very good"))


# ── Class-level tests ───────────────────────────────────────────────


class TestWriterNegationDensityEmpty(unittest.TestCase):
    def test_empty_text(self):
        w = WriterNegationDensity("")
        self.assertEqual(w.n_sentences, 0)

    def test_whitespace_text(self):
        w = WriterNegationDensity("   \n  ")
        self.assertEqual(w.n_sentences, 0)

    @property
    def _instance(self):
        return WriterNegationDensity("")

    # Helper to access n_sentences from empty instances
    def setUp(self):
        pass


class TestWriterNegationDensityBasic(unittest.TestCase):
    def setUp(self):
        self.text = (
            "The sky is blue. The grass is green. "
            "The sun is bright. Birds are singing. "
            "It is a beautiful day."
        )
        self.w = WriterNegationDensity(self.text)

    def test_n_sentences(self):
        self.assertEqual(self.w.n_sentences, 5)

    def test_explicit_negation_rate_zero(self):
        self.assertEqual(self.w.explicit_negation_rate, 0.0)

    def test_contracted_negation_rate_zero(self):
        self.assertEqual(self.w.contracted_negation_rate, 0.0)

    def test_negative_prefix_rate_zero(self):
        self.assertEqual(self.w.negative_prefix_rate, 0.0)

    def test_negative_verb_rate_zero(self):
        self.assertEqual(self.w.negative_verb_rate, 0.0)

    def test_litotes_rate_zero(self):
        self.assertEqual(self.w.litotes_rate, 0.0)

    def test_negation_scope_ratio_zero(self):
        self.assertEqual(self.w.negation_scope_ratio, 0.0)

    def test_negation_density_index_zero(self):
        self.assertEqual(self.w.negation_density_index, 0.0)

    def test_classification_affirmative(self):
        self.assertEqual(self.w.classification, "affirmative")


class TestWriterNegationDensityExplicit(unittest.TestCase):
    def setUp(self):
        self.text = (
            "I do not agree with that. She never came to the party. "
            "There is no evidence for this claim. Neither option works well. "
            "Nothing happened yesterday. Nobody answered the phone. "
            "There is nowhere to hide. None of them showed up."
        )
        self.w = WriterNegationDensity(self.text)

    def test_n_sentences(self):
        self.assertEqual(self.w.n_sentences, 8)

    def test_explicit_negation_rate_positive(self):
        self.assertGreater(self.w.explicit_negation_rate, 0.0)

    def test_explicit_negation_rate_value(self):
        # 8 explicit negators in 8 sentences = 100 per 100 sentences
        self.assertAlmostEqual(self.w.explicit_negation_rate, 100.0, places=1)

    def test_classification_not_affirmative(self):
        self.assertNotEqual(self.w.classification, "affirmative")


class TestWriterNegationDensityContracted(unittest.TestCase):
    def setUp(self):
        self.text = (
            "I don't think so. She can't come to the party. "
            "They won't agree to the terms. It isn't fair at all. "
            "He doesn't know the answer."
        )
        self.w = WriterNegationDensity(self.text)

    def test_contracted_negation_rate_positive(self):
        self.assertGreater(self.w.contracted_negation_rate, 0.0)

    def test_contracted_negation_rate_value(self):
        # 5 contractions in 5 sentences = 100 per 100 sentences
        self.assertAlmostEqual(self.w.contracted_negation_rate, 100.0, places=1)


class TestWriterNegationDensityPrefix(unittest.TestCase):
    def setUp(self):
        self.text = (
            "The impossible task was unfair. His irregular behavior "
            "was illegal. The nonsense argument was disagreeable. "
            "She misunderstood the counterproductive policy."
        )
        self.w = WriterNegationDensity(self.text)

    def test_negative_prefix_rate_positive(self):
        self.assertGreater(self.w.negative_prefix_rate, 0.0)


class TestWriterNegationDensityVerbs(unittest.TestCase):
    def setUp(self):
        self.text = (
            "She denied the accusation. He refused the offer. "
            "They rejected the proposal. She declined the invitation. "
            "He avoided the topic. The law prohibits smoking."
        )
        self.w = WriterNegationDensity(self.text)

    def test_negative_verb_rate_positive(self):
        self.assertGreater(self.w.negative_verb_rate, 0.0)

    def test_negative_verb_rate_value(self):
        # 6 negative verbs in 6 sentences = 100 per 100
        self.assertAlmostEqual(self.w.negative_verb_rate, 100.0, places=1)


class TestWriterNegationDensityLitotes(unittest.TestCase):
    def setUp(self):
        self.text = (
            "The result was not bad. It was not uncommon to see this. "
            "She was not unlike her mother. The cost was not insignificant. "
            "It was not unreasonable to ask. The task was not impossible."
        )
        self.w = WriterNegationDensity(self.text)

    def test_litotes_rate_positive(self):
        self.assertGreater(self.w.litotes_rate, 0.0)

    def test_litotes_rate_value(self):
        # 6 litotes in 6 sentences = 100 per 100
        self.assertAlmostEqual(self.w.litotes_rate, 100.0, places=1)


class TestWriterNegationDensityScope(unittest.TestCase):
    def test_stacked_negation(self):
        text = (
            "It is not impossible that this is not unrelated. "
            "She does not deny that nothing is wrong. "
            "The impossible task was not unfair."
        )
        w = WriterNegationDensity(text)
        # All three sentences have 2+ negators
        self.assertGreater(w.negation_scope_ratio, 0.0)

    def test_single_negation_no_scope(self):
        text = (
            "I do not agree. She never came. Nobody answered."
        )
        w = WriterNegationDensity(text)
        # Each sentence has only 1 negator, so scope ratio should be 0
        self.assertEqual(w.negation_scope_ratio, 0.0)


class TestWriterNegationDensityComposite(unittest.TestCase):
    def test_heavily_negated_text(self):
        text = (
            "I don't think it's not impossible. She never denies nothing. "
            "It is not unfair to say nothing is impossible. Nobody can't "
            "refuse the unfair and impossible task. The irregular and "
            "illegal action was not unreasonable. She couldn't avoid "
            "the nonsensical and counterproductive outcome."
        )
        w = WriterNegationDensity(text)
        self.assertGreater(w.negation_density_index, 0.2)
        self.assertIn(w.classification, [
            "moderately_negated", "heavily_negated", "negation_saturated"
        ])

    def test_affirmative_text(self):
        text = (
            "The sun rises in the east. Birds sing in the morning. "
            "Flowers bloom in spring. Children play in the garden. "
            "The river flows to the sea. Mountains touch the sky."
        )
        w = WriterNegationDensity(text)
        self.assertLess(w.negation_density_index, 0.08)
        self.assertEqual(w.classification, "affirmative")


class TestWriterNegationDensityAsDict(unittest.TestCase):
    def test_as_dict_keys(self):
        w = WriterNegationDensity("Hello world.")
        d = w.as_dict()
        expected_keys = {
            "explicit_negation_rate",
            "contracted_negation_rate",
            "negative_prefix_rate",
            "negative_verb_rate",
            "litotes_rate",
            "negation_scope_ratio",
            "negation_density_index",
            "classification",
            "n_sentences",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    def test_as_dict_values_types(self):
        w = WriterNegationDensity("I don't think it is impossible.")
        d = w.as_dict()
        self.assertIsInstance(d["explicit_negation_rate"], float)
        self.assertIsInstance(d["contracted_negation_rate"], float)
        self.assertIsInstance(d["negative_prefix_rate"], float)
        self.assertIsInstance(d["negative_verb_rate"], float)
        self.assertIsInstance(d["litotes_rate"], float)
        self.assertIsInstance(d["negation_scope_ratio"], float)
        self.assertIsInstance(d["negation_density_index"], float)
        self.assertIsInstance(d["classification"], str)
        self.assertIsInstance(d["n_sentences"], int)


class TestAnalyseConvenience(unittest.TestCase):
    def test_returns_dict(self):
        result = analyse("The sky is blue.")
        self.assertIsInstance(result, dict)

    def test_matches_class(self):
        text = "She doesn't deny the impossible task."
        d1 = analyse(text)
        d2 = WriterNegationDensity(text).as_dict()
        self.assertEqual(d1, d2)

    def test_empty_text(self):
        result = analyse("")
        self.assertEqual(result["n_sentences"], 0)
        self.assertEqual(result["negation_density_index"], 0.0)


class TestWriterNegationDensityNProperty(unittest.TestCase):
    """Test the n_sentences property accessor."""

    def test_n_sentences_property(self):
        w = WriterNegationDensity("Hello. World. Test.")
        self.assertEqual(w.n_sentences, 3)

    def test_empty_n_sentences(self):
        w = WriterNegationDensity("")
        self.assertEqual(w.n_sentences, 0)


class TestClassificationThresholds(unittest.TestCase):
    def test_affirmative_threshold(self):
        # Index < 0.08
        w = WriterNegationDensity("Hello world. The sky is blue.")
        self.assertEqual(w.classification, "affirmative")

    def test_classification_monotonic(self):
        # More negation → higher classification
        light = WriterNegationDensity(
            "The sky is blue. I do not agree. The grass is green."
        )
        heavy = WriterNegationDensity(
            "I don't think it's not impossible. She never denies nothing. "
            "Nobody can't refuse the unfair task. The irregular action "
            "was not unreasonable. She couldn't avoid the impossible outcome."
        )
        self.assertLess(
            light.negation_density_index,
            heavy.negation_density_index,
        )


class TestMixedNegationTypes(unittest.TestCase):
    def test_explicit_and_contracted(self):
        text = "I do not agree and she doesn't either."
        w = WriterNegationDensity(text)
        self.assertGreater(w.explicit_negation_rate, 0.0)
        self.assertGreater(w.contracted_negation_rate, 0.0)

    def test_prefix_and_verb(self):
        text = "She denied the impossible claim."
        w = WriterNegationDensity(text)
        self.assertGreater(w.negative_prefix_rate, 0.0)
        self.assertGreater(w.negative_verb_rate, 0.0)


if __name__ == "__main__":
    unittest.main()
