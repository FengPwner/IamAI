#!/usr/bin/env python3
"""Tests for writer_interrogative_density — 100 test cases."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_interrogative_density import (  # noqa: E402
    DIRECT_QUESTION_PATTERNS,
    RHETORICAL_QUESTION_PATTERNS,
    EMBEDDED_QUESTION_PATTERNS,
    SELF_ADDRESSED_QUESTION_PATTERNS,
    INTERROGATIVE_PRONOUN_PATTERNS,
    WriterInterrogativeDensity,
    _split_sentences,
    _count_matching,
    _count_tokens,
)


# ── Initialization ───────────────────────────────────────────────────


class TestInit(unittest.TestCase):
    """Test WriterInterrogativeDensity initialization."""

    def test_init_default(self):
        wid = WriterInterrogativeDensity()
        self.assertIsNotNone(wid.direct_question)
        self.assertIsNotNone(wid.rhetorical_question)
        self.assertIsNotNone(wid.embedded_question)
        self.assertIsNotNone(wid.self_addressed_question)
        self.assertIsNotNone(wid.interrogative_pronoun)

    def test_init_sets_all_constants(self):
        wid = WriterInterrogativeDensity()
        self.assertEqual(wid.direct_question, DIRECT_QUESTION_PATTERNS)
        self.assertEqual(wid.rhetorical_question, RHETORICAL_QUESTION_PATTERNS)
        self.assertEqual(wid.embedded_question, EMBEDDED_QUESTION_PATTERNS)
        self.assertEqual(wid.self_addressed_question, SELF_ADDRESSED_QUESTION_PATTERNS)
        self.assertEqual(wid.interrogative_pronoun, INTERROGATIVE_PRONOUN_PATTERNS)

    def test_direct_question_patterns_are_compiled(self):
        for p in DIRECT_QUESTION_PATTERNS:
            self.assertIsInstance(p, re.Pattern)

    def test_rhetorical_question_patterns_are_compiled(self):
        for p in RHETORICAL_QUESTION_PATTERNS:
            self.assertIsInstance(p, re.Pattern)

    def test_embedded_question_patterns_are_compiled(self):
        for p in EMBEDDED_QUESTION_PATTERNS:
            self.assertIsInstance(p, re.Pattern)

    def test_self_addressed_question_patterns_are_compiled(self):
        for p in SELF_ADDRESSED_QUESTION_PATTERNS:
            self.assertIsInstance(p, re.Pattern)

    def test_interrogative_pronoun_patterns_are_compiled(self):
        for p in INTERROGATIVE_PRONOUN_PATTERNS:
            self.assertIsInstance(p, re.Pattern)

    def test_pattern_counts(self):
        wid = WriterInterrogativeDensity()
        self.assertGreaterEqual(len(wid.direct_question), 4)
        self.assertGreaterEqual(len(wid.rhetorical_question), 8)
        self.assertGreaterEqual(len(wid.embedded_question), 8)
        self.assertGreaterEqual(len(wid.self_addressed_question), 8)
        self.assertGreaterEqual(len(wid.interrogative_pronoun), 7)


# ── Helper functions ─────────────────────────────────────────────────


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences."""

    def test_empty_string(self):
        self.assertEqual(_split_sentences(""), [])

    def test_single_sentence(self):
        self.assertEqual(_split_sentences("Hello world."), ["Hello world."])

    def test_multiple_sentences(self):
        text = "First sentence. Second sentence. Third sentence."
        result = _split_sentences(text)
        self.assertEqual(len(result), 3)
        self.assertTrue(all(s.endswith('.') for s in result))

    def test_question_marks_split(self):
        text = "What is this? Who knows? Why bother?"
        result = _split_sentences(text)
        self.assertEqual(len(result), 3)
        self.assertTrue(all(s.endswith('?') for s in result))

    def test_mixed_punctuation(self):
        text = "Statement. Question? Exclamation!"
        result = _split_sentences(text)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], "Statement.")
        self.assertEqual(result[1], "Question?")
        self.assertEqual(result[2], "Exclamation!")


class TestCountMatching(unittest.TestCase):
    """Test _count_matching."""

    def test_no_matches(self):
        sentences = ["Hello world", "Goodbye world"]
        patterns = [re.compile(r"\bfoo\b")]
        self.assertEqual(_count_matching(sentences, patterns), 0)

    def test_all_match(self):
        sentences = ["foo bar", "foo baz"]
        patterns = [re.compile(r"\bfoo\b")]
        self.assertEqual(_count_matching(sentences, patterns), 2)

    def test_some_match(self):
        sentences = ["foo bar", "hello world", "foo baz"]
        patterns = [re.compile(r"\bfoo\b")]
        self.assertEqual(_count_matching(sentences, patterns), 2)


class TestCountTokens(unittest.TestCase):
    """Test _count_tokens."""

    def test_no_tokens(self):
        self.assertEqual(_count_tokens("hello world", [re.compile(r"\bfoo\b")]), 0)

    def test_single_token(self):
        self.assertEqual(_count_tokens("who is there", [re.compile(r"\bwho\b", re.I)]), 1)

    def test_multiple_tokens(self):
        self.assertEqual(
            _count_tokens("who asked what and where", [re.compile(r"\b(?:who|what|where)\b", re.I)]),
            3
        )


# ── Direct question patterns ────────────────────────────────────────


class TestDirectQuestionPatterns(unittest.TestCase):
    """Test direct question pattern matching."""

    def test_question_mark_ending(self):
        self.assertTrue(any(p.search("What is your name?") for p in DIRECT_QUESTION_PATTERNS))

    def test_wh_question(self):
        self.assertTrue(any(p.search("where are you going") for p in DIRECT_QUESTION_PATTERNS))

    def test_yes_no_question(self):
        self.assertTrue(any(p.search("is this correct") for p in DIRECT_QUESTION_PATTERNS))

    def test_tag_question(self):
        self.assertTrue(any(p.search("it is cold, isn't it?") for p in DIRECT_QUESTION_PATTERNS))

    def test_declarative_no_match(self):
        # A plain declarative sentence should not match most patterns
        # (though the question-mark pattern would match if it ends with ?)
        text = "the sky is blue"
        matches = sum(1 for p in DIRECT_QUESTION_PATTERNS if p.search(text))
        self.assertEqual(matches, 0)

    def test_how_question(self):
        self.assertTrue(any(p.search("how does this work") for p in DIRECT_QUESTION_PATTERNS))

    def test_why_question(self):
        self.assertTrue(any(p.search("why is this happening") for p in DIRECT_QUESTION_PATTERNS))

    def test_which_question(self):
        self.assertTrue(any(p.search("which option is better") for p in DIRECT_QUESTION_PATTERNS))

    def test_alternative_question(self):
        self.assertTrue(any(p.search("do you want tea or coffee?") for p in DIRECT_QUESTION_PATTERNS))

    def test_mid_sentence_question_mark(self):
        self.assertTrue(any(p.search("really? that seems unlikely") for p in DIRECT_QUESTION_PATTERNS))


# ── Rhetorical question patterns ────────────────────────────────────


class TestRhetoricalQuestionPatterns(unittest.TestCase):
    """Test rhetorical question pattern matching."""

    def test_who_knows(self):
        self.assertTrue(any(p.search("who knows?") for p in RHETORICAL_QUESTION_PATTERNS))

    def test_whats_the_point(self):
        self.assertTrue(any(p.search("what's the point?") for p in RHETORICAL_QUESTION_PATTERNS))

    def test_why_bother(self):
        self.assertTrue(any(p.search("why bother?") for p in RHETORICAL_QUESTION_PATTERNS))

    def test_who_cares(self):
        self.assertTrue(any(p.search("who cares?") for p in RHETORICAL_QUESTION_PATTERNS))

    def test_isnt_it_obvious(self):
        self.assertTrue(any(p.search("isn't it obvious?") for p in RHETORICAL_QUESTION_PATTERNS))

    def test_is_the_pope_catholic(self):
        self.assertTrue(any(p.search("is the pope Catholic?") for p in RHETORICAL_QUESTION_PATTERNS))

    def test_does_it_really_matter(self):
        self.assertTrue(any(p.search("does it really matter?") for p in RHETORICAL_QUESTION_PATTERNS))

    def test_how_could_anyone(self):
        self.assertTrue(any(p.search("how could anyone possibly do this?") for p in RHETORICAL_QUESTION_PATTERNS))

    def test_tag_isnt_it(self):
        self.assertTrue(any(p.search("nice weather, isn't it?") for p in RHETORICAL_QUESTION_PATTERNS))

    def test_after_all(self):
        self.assertTrue(any(p.search("after all, right?") for p in RHETORICAL_QUESTION_PATTERNS))

    def test_who_am_i_to_judge(self):
        self.assertTrue(any(p.search("who am I to judge?") for p in RHETORICAL_QUESTION_PATTERNS))

    def test_whats_not_to_love(self):
        self.assertTrue(any(p.search("what's not to love?") for p in RHETORICAL_QUESTION_PATTERNS))

    def test_genuine_question_not_rhetorical(self):
        # A genuine information-seeking question should not match rhetorical patterns
        text = "what time is the meeting?"
        matches = sum(1 for p in RHETORICAL_QUESTION_PATTERNS if p.search(text))
        self.assertEqual(matches, 0)


# ── Embedded question patterns ──────────────────────────────────────


class TestEmbeddedQuestionPatterns(unittest.TestCase):
    """Test embedded/indirect question pattern matching."""

    def test_i_wonder_if(self):
        self.assertTrue(any(p.search("I wonder if this is correct") for p in EMBEDDED_QUESTION_PATTERNS))

    def test_i_wonder_whether(self):
        self.assertTrue(any(p.search("I wonder whether we should proceed") for p in EMBEDDED_QUESTION_PATTERNS))

    def test_i_wonder_what(self):
        self.assertTrue(any(p.search("I wonder what happened yesterday") for p in EMBEDDED_QUESTION_PATTERNS))

    def test_the_question_is_whether(self):
        self.assertTrue(any(p.search("the question is whether this approach works") for p in EMBEDDED_QUESTION_PATTERNS))

    def test_we_must_ask(self):
        self.assertTrue(any(p.search("we must ask whether this is sustainable") for p in EMBEDDED_QUESTION_PATTERNS))

    def test_remains_unclear(self):
        self.assertTrue(any(p.search("it remains unclear what caused the failure") for p in EMBEDDED_QUESTION_PATTERNS))

    def test_consider_whether(self):
        self.assertTrue(any(p.search("consider whether the tradeoff is worthwhile") for p in EMBEDDED_QUESTION_PATTERNS))

    def test_one_might_ask(self):
        self.assertTrue(any(p.search("one might ask whether this is even possible") for p in EMBEDDED_QUESTION_PATTERNS))

    def test_need_to_figure_out(self):
        self.assertTrue(any(p.search("we need to figure out what went wrong") for p in EMBEDDED_QUESTION_PATTERNS))

    def test_whether_or_not(self):
        self.assertTrue(any(p.search("whether or not we proceed") for p in EMBEDDED_QUESTION_PATTERNS))

    def test_what_happens_if(self):
        self.assertTrue(any(p.search("what happens if we remove this line") for p in EMBEDDED_QUESTION_PATTERNS))

    def test_plain_statement_no_match(self):
        text = "the solution is straightforward and well-documented"
        matches = sum(1 for p in EMBEDDED_QUESTION_PATTERNS if p.search(text))
        self.assertEqual(matches, 0)


# ── Self-addressed question patterns ────────────────────────────────


class TestSelfAddressedQuestionPatterns(unittest.TestCase):
    """Test self-addressed question pattern matching."""

    def test_why_do_i_keep(self):
        self.assertTrue(any(p.search("why do I keep making this mistake?") for p in SELF_ADDRESSED_QUESTION_PATTERNS))

    def test_what_was_i_thinking(self):
        self.assertTrue(any(p.search("what was I thinking?") for p in SELF_ADDRESSED_QUESTION_PATTERNS))

    def test_how_should_i_explain(self):
        self.assertTrue(any(p.search("how should I explain this to the team?") for p in SELF_ADDRESSED_QUESTION_PATTERNS))

    def test_do_i_even_know(self):
        self.assertTrue(any(p.search("do I even know what I'm doing?") for p in SELF_ADDRESSED_QUESTION_PATTERNS))

    def test_am_i_the_only_one(self):
        self.assertTrue(any(p.search("am I the only one who sees this?") for p in SELF_ADDRESSED_QUESTION_PATTERNS))

    def test_why_cant_i_just(self):
        self.assertTrue(any(p.search("why can't I just get this right?") for p in SELF_ADDRESSED_QUESTION_PATTERNS))

    def test_what_am_i_doing(self):
        self.assertTrue(any(p.search("what am I doing with my life?") for p in SELF_ADDRESSED_QUESTION_PATTERNS))

    def test_where_did_i_go_wrong(self):
        self.assertTrue(any(p.search("where did I go wrong?") for p in SELF_ADDRESSED_QUESTION_PATTERNS))

    def test_note_to_self(self):
        self.assertTrue(any(p.search("note to self: never do that again") for p in SELF_ADDRESSED_QUESTION_PATTERNS))

    def test_i_ask_myself(self):
        self.assertTrue(any(p.search("I ask myself: why bother?") for p in SELF_ADDRESSED_QUESTION_PATTERNS))

    def test_am_i_wrong(self):
        self.assertTrue(any(p.search("am I wrong about this?") for p in SELF_ADDRESSED_QUESTION_PATTERNS))

    def test_have_i_mentioned(self):
        self.assertTrue(any(p.search("have I mentioned this before?") for p in SELF_ADDRESSED_QUESTION_PATTERNS))

    def test_general_question_not_self(self):
        # A general question not self-directed
        text = "why does the system behave this way?"
        matches = sum(1 for p in SELF_ADDRESSED_QUESTION_PATTERNS if p.search(text))
        self.assertEqual(matches, 0)


# ── Interrogative pronoun patterns ──────────────────────────────────


class TestInterrogativePronounPatterns(unittest.TestCase):
    """Test interrogative pronoun/adverb pattern matching."""

    def test_who(self):
        self.assertEqual(len([p for p in INTERROGATIVE_PRONOUN_PATTERNS if p.search("who")]), 1)

    def test_what(self):
        self.assertEqual(len([p for p in INTERROGATIVE_PRONOUN_PATTERNS if p.search("what")]), 1)

    def test_where(self):
        self.assertEqual(len([p for p in INTERROGATIVE_PRONOUN_PATTERNS if p.search("where")]), 1)

    def test_when(self):
        self.assertEqual(len([p for p in INTERROGATIVE_PRONOUN_PATTERNS if p.search("when")]), 1)

    def test_why(self):
        self.assertEqual(len([p for p in INTERROGATIVE_PRONOUN_PATTERNS if p.search("why")]), 1)

    def test_how(self):
        self.assertEqual(len([p for p in INTERROGATIVE_PRONOUN_PATTERNS if p.search("how")]), 1)

    def test_which(self):
        self.assertEqual(len([p for p in INTERROGATIVE_PRONOUN_PATTERNS if p.search("which")]), 1)

    def test_whose(self):
        self.assertEqual(len([p for p in INTERROGATIVE_PRONOUN_PATTERNS if p.search("whose")]), 1)

    def test_whom(self):
        self.assertEqual(len([p for p in INTERROGATIVE_PRONOUN_PATTERNS if p.search("whom")]), 1)

    def test_no_pronoun(self):
        matches = sum(1 for p in INTERROGATIVE_PRONOUN_PATTERNS if p.search("hello world"))
        self.assertEqual(matches, 0)


# ── Composite measure ───────────────────────────────────────────────


class TestMeasure(unittest.TestCase):
    """Test the full measure() pipeline."""

    def setUp(self):
        self.wid = WriterInterrogativeDensity()

    def test_empty_text(self):
        result = self.wid.measure("")
        self.assertEqual(result["direct_question_rate"], 0.0)
        self.assertEqual(result["rhetorical_question_rate"], 0.0)
        self.assertEqual(result["embedded_question_rate"], 0.0)
        self.assertEqual(result["self_addressed_question_rate"], 0.0)
        self.assertEqual(result["interrogative_pronoun_density"], 0.0)
        self.assertEqual(result["interrogative_density_index"], 0.0)
        self.assertEqual(result["classification"], "statement_dominant")

    def test_pure_declarative(self):
        text = "The cat sat on the mat. The dog ran across the yard. The bird sang a song."
        result = self.wid.measure(text)
        self.assertEqual(result["classification"], "statement_dominant")
        self.assertLess(result["interrogative_density_index"], 0.05)

    def test_pure_interrogative(self):
        text = "What is this? Who are you? Where is the exit? Why is this happening? How does it work?"
        result = self.wid.measure(text)
        self.assertGreater(result["direct_question_rate"], 0.0)
        self.assertGreater(result["interrogative_density_index"], 0.0)

    def test_rhetorical_heavy(self):
        text = "Who cares? What's the point? Why bother? Who knows? Isn't it obvious?"
        result = self.wid.measure(text)
        self.assertGreater(result["rhetorical_question_rate"], 0.0)

    def test_embedded_questions(self):
        text = "I wonder if this is correct. The question is whether we should proceed. We must ask whether this is viable."
        result = self.wid.measure(text)
        self.assertGreater(result["embedded_question_rate"], 0.0)

    def test_self_addressed(self):
        text = "Why do I keep doing this? What was I thinking? How should I explain this? Am I wrong?"
        result = self.wid.measure(text)
        self.assertGreater(result["self_addressed_question_rate"], 0.0)

    def test_mixed_text(self):
        text = """What is the meaning of this? The answer is simple.
        Who knows the truth? I wonder if anyone cares.
        Why do I keep asking? The data speaks for itself.
        What was I thinking? Perhaps nothing at all."""
        result = self.wid.measure(text)
        self.assertIn("classification", result)
        self.assertGreater(result["interrogative_density_index"], 0.0)

    def test_result_keys(self):
        result = self.wid.measure("Hello world.")
        expected_keys = {
            "direct_question_rate",
            "rhetorical_question_rate",
            "embedded_question_rate",
            "self_addressed_question_rate",
            "interrogative_pronoun_density",
            "interrogative_density_index",
            "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_result_values_are_rounded(self):
        text = "What is this? I wonder why. Who knows?"
        result = self.wid.measure(text)
        for key in [
            "direct_question_rate",
            "rhetorical_question_rate",
            "embedded_question_rate",
            "self_addressed_question_rate",
            "interrogative_pronoun_density",
            "interrogative_density_index",
        ]:
            # Check rounding to 4 decimal places
            self.assertEqual(result[key], round(result[key], 4))


# ── Classification ───────────────────────────────────────────────────


class TestClassify(unittest.TestCase):
    """Test classification boundaries."""

    def setUp(self):
        self.wid = WriterInterrogativeDensity()

    def test_zero_is_statement_dominant(self):
        self.assertEqual(self.wid.classify(0.0), "statement_dominant")

    def test_below_threshold(self):
        self.assertEqual(self.wid.classify(0.04), "statement_dominant")

    def test_exactly_five_percent(self):
        self.assertEqual(self.wid.classify(0.05), "minimally_interrogative")

    def test_minimally_interrogative_range(self):
        self.assertEqual(self.wid.classify(0.10), "minimally_interrogative")
        self.assertEqual(self.wid.classify(0.14), "minimally_interrogative")

    def test_exactly_fifteen_percent(self):
        self.assertEqual(self.wid.classify(0.15), "moderately_interrogative")

    def test_moderately_interrogative_range(self):
        self.assertEqual(self.wid.classify(0.20), "moderately_interrogative")
        self.assertEqual(self.wid.classify(0.29), "moderately_interrogative")

    def test_exactly_thirty_percent(self):
        self.assertEqual(self.wid.classify(0.30), "richly_interrogative")

    def test_richly_interrogative_range(self):
        self.assertEqual(self.wid.classify(0.35), "richly_interrogative")
        self.assertEqual(self.wid.classify(0.49), "richly_interrogative")

    def test_exactly_fifty_percent(self):
        self.assertEqual(self.wid.classify(0.50), "socratic")

    def test_socratic_range(self):
        self.assertEqual(self.wid.classify(0.60), "socratic")
        self.assertEqual(self.wid.classify(0.99), "socratic")

    def test_one_is_socratic(self):
        self.assertEqual(self.wid.classify(1.0), "socratic")


# ── Compute index ────────────────────────────────────────────────────


class TestComputeIndex(unittest.TestCase):
    """Test the composite index computation."""

    def setUp(self):
        self.wid = WriterInterrogativeDensity()

    def test_all_zeros(self):
        idx = self.wid.compute_interrogative_density_index(0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(idx, 0.0)

    def test_all_ones(self):
        idx = self.wid.compute_interrogative_density_index(1.0, 1.0, 1.0, 1.0, 1.0)
        self.assertAlmostEqual(idx, 1.0)

    def test_weights_sum_to_one(self):
        # 0.25 + 0.25 + 0.20 + 0.15 + 0.15 = 1.00
        idx = self.wid.compute_interrogative_density_index(1.0, 1.0, 1.0, 1.0, 1.0)
        self.assertAlmostEqual(idx, 1.0, places=10)

    def test_direct_weight(self):
        idx = self.wid.compute_interrogative_density_index(1.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(idx, 0.25)

    def test_rhetorical_weight(self):
        idx = self.wid.compute_interrogative_density_index(0.0, 1.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(idx, 0.25)

    def test_embedded_weight(self):
        idx = self.wid.compute_interrogative_density_index(0.0, 0.0, 1.0, 0.0, 0.0)
        self.assertAlmostEqual(idx, 0.20)

    def test_self_addressed_weight(self):
        idx = self.wid.compute_interrogative_density_index(0.0, 0.0, 0.0, 1.0, 0.0)
        self.assertAlmostEqual(idx, 0.15)

    def test_pronoun_weight(self):
        idx = self.wid.compute_interrogative_density_index(0.0, 0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(idx, 0.15)

    def test_partial_values(self):
        idx = self.wid.compute_interrogative_density_index(0.5, 0.3, 0.2, 0.1, 0.4)
        expected = 0.5 * 0.25 + 0.3 * 0.25 + 0.2 * 0.20 + 0.1 * 0.15 + 0.4 * 0.15
        self.assertAlmostEqual(idx, expected)


# ── Individual measure methods ───────────────────────────────────────


class TestIndividualMeasures(unittest.TestCase):
    """Test individual measure_* methods."""

    def setUp(self):
        self.wid = WriterInterrogativeDensity()

    def test_direct_question_rate_empty(self):
        self.assertEqual(self.wid.measure_direct_question_rate(""), 0.0)

    def test_rhetorical_question_rate_empty(self):
        self.assertEqual(self.wid.measure_rhetorical_question_rate(""), 0.0)

    def test_embedded_question_rate_empty(self):
        self.assertEqual(self.wid.measure_embedded_question_rate(""), 0.0)

    def test_self_addressed_question_rate_empty(self):
        self.assertEqual(self.wid.measure_self_addressed_question_rate(""), 0.0)

    def test_interrogative_pronoun_density_empty(self):
        self.assertEqual(self.wid.measure_interrogative_pronoun_density(""), 0.0)

    def test_direct_question_rate_with_questions(self):
        text = "What is this? Who are you? The answer is here."
        rate = self.wid.measure_direct_question_rate(text)
        self.assertGreater(rate, 0.0)
        self.assertLessEqual(rate, 1.0)

    def test_rhetorical_question_rate_with_rhetorical(self):
        text = "Who cares? What's the point? The data is clear."
        rate = self.wid.measure_rhetorical_question_rate(text)
        self.assertGreater(rate, 0.0)

    def test_embedded_question_rate_with_embedded(self):
        text = "I wonder if this works. The question is whether we should try."
        rate = self.wid.measure_embedded_question_rate(text)
        self.assertGreater(rate, 0.0)

    def test_pronoun_density_with_pronouns(self):
        text = "What is this and where is that and who is here."
        density = self.wid.measure_interrogative_pronoun_density(text)
        self.assertGreater(density, 0.0)


if __name__ == "__main__":
    unittest.main()
