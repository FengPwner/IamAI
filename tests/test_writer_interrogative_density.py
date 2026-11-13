#!/usr/bin/env python3
"""Tests for writer_interrogative_density — comprehensive test suite."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_interrogative_density import (  # noqa: E402
    DIRECT_QUESTION_RE,
    INDIRECT_QUESTION_RE,
    RHETORICAL_RE,
    TAG_QUESTION_RE,
    WH_WORD_RE,
    WriterInterrogativeDensity,
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


# ── Pattern-level tests ─────────────────────────────────────────────


class TestWhWordRE(unittest.TestCase):
    def test_who(self):
        self.assertTrue(WH_WORD_RE.search("Who is there?"))

    def test_what(self):
        self.assertTrue(WH_WORD_RE.search("What happened?"))

    def test_when(self):
        self.assertTrue(WH_WORD_RE.search("When did it start?"))

    def test_where(self):
        self.assertTrue(WH_WORD_RE.search("Where are we?"))

    def test_why(self):
        self.assertTrue(WH_WORD_RE.search("Why did she leave?"))

    def test_how(self):
        self.assertTrue(WH_WORD_RE.search("How does it work?"))

    def test_which(self):
        self.assertTrue(WH_WORD_RE.search("Which one?"))

    def test_whose(self):
        self.assertTrue(WH_WORD_RE.search("Whose book is this?"))

    def test_whom(self):
        self.assertTrue(WH_WORD_RE.search("Whom did you see?"))

    def test_whoever(self):
        self.assertTrue(WH_WORD_RE.search("Whoever told you that?"))

    def test_whatever(self):
        self.assertTrue(WH_WORD_RE.search("Whatever do you mean?"))

    def test_wherever(self):
        self.assertTrue(WH_WORD_RE.search("Wherever did it go?"))

    def test_case_insensitive(self):
        self.assertTrue(WH_WORD_RE.search("WHY is this?"))

    def test_no_false_positive_whole(self):
        # "whole" starts with "who" but should not match
        self.assertIsNone(WH_WORD_RE.search("the whole thing"))

    def test_no_false_positive_show(self):
        self.assertIsNone(WH_WORD_RE.search("show me the way"))

    def test_multiple_wh_words(self):
        result = WH_WORD_RE.findall("who did what and when?")
        self.assertEqual(len(result), 3)


class TestTagQuestionRE(unittest.TestCase):
    def test_isnt_it(self):
        self.assertTrue(TAG_QUESTION_RE.search("It's cold, isn't it?"))

    def test_dont_you(self):
        self.assertTrue(TAG_QUESTION_RE.search("You like tea, don't you?"))

    def test_wont_they(self):
        self.assertTrue(TAG_QUESTION_RE.search("They'll come, won't they?"))

    def test_right(self):
        self.assertTrue(TAG_QUESTION_RE.search("That's correct, right?"))

    def test_innit(self):
        self.assertTrue(TAG_QUESTION_RE.search("Good stuff, innit?"))

    def test_you_know(self):
        self.assertTrue(TAG_QUESTION_RE.search("It's weird, you know?"))

    def test_positive_tag(self):
        self.assertTrue(TAG_QUESTION_RE.search("She left, did she?"))

    def test_no_false_positive_plain(self):
        self.assertIsNone(TAG_QUESTION_RE.search("She went to the store."))


class TestIndirectQuestionRE(unittest.TestCase):
    def test_wondered_if(self):
        self.assertTrue(INDIRECT_QUESTION_RE.search("She wondered if he was coming."))

    def test_asked_whether(self):
        self.assertTrue(INDIRECT_QUESTION_RE.search("He asked whether it was true."))

    def test_wonder_what(self):
        self.assertTrue(INDIRECT_QUESTION_RE.search("I wonder what happened."))

    def test_question_is(self):
        self.assertTrue(INDIRECT_QUESTION_RE.search("The question is how we proceed."))

    def test_remains_unclear(self):
        self.assertTrue(INDIRECT_QUESTION_RE.search(
            "It remains unclear why this happened."
        ))

    def test_one_might_ask(self):
        self.assertTrue(INDIRECT_QUESTION_RE.search(
            "One might ask what the point is."
        ))

    def test_pondering_how(self):
        self.assertTrue(INDIRECT_QUESTION_RE.search(
            "She was pondering how to escape."
        ))

    def test_considered_whether(self):
        self.assertTrue(INDIRECT_QUESTION_RE.search(
            "They considered whether to stay."
        ))

    def test_exploring_why(self):
        self.assertTrue(INDIRECT_QUESTION_RE.search(
            "We are exploring why this works."
        ))

    def test_i_wonder(self):
        self.assertTrue(INDIRECT_QUESTION_RE.search("I wonder if it matters."))

    def test_no_false_positive_plain(self):
        self.assertIsNone(INDIRECT_QUESTION_RE.search("She walked to the park."))


class TestRhetoricalRE(unittest.TestCase):
    def test_after_all(self):
        self.assertTrue(RHETORICAL_RE.search("After all, who could deny it?"))

    def test_isnt_it_obvious(self):
        self.assertTrue(RHETORICAL_RE.search("Isn't it obvious that this works?"))

    def test_what_could_be_more(self):
        self.assertTrue(RHETORICAL_RE.search("What could be more important?"))

    def test_who_among_us(self):
        self.assertTrue(RHETORICAL_RE.search("Who among us hasn't made mistakes?"))

    def test_how_many_times(self):
        self.assertTrue(RHETORICAL_RE.search("How many times must we repeat this?"))

    def test_why_on_earth(self):
        self.assertTrue(RHETORICAL_RE.search("Why on earth would anyone do that?"))

    def test_are_we_supposed(self):
        self.assertTrue(RHETORICAL_RE.search(
            "Are we really supposed to believe that?"
        ))

    def test_no_false_positive_plain(self):
        self.assertIsNone(RHETORICAL_RE.search("She asked him a question."))


# ── Class-level tests ────────────────────────────────────────────────


class TestWriterInterrogativeDensityEmpty(unittest.TestCase):
    def test_empty_text(self):
        w = WriterInterrogativeDensity("")
        self.assertEqual(w.n_sentences, 0)
        self.assertEqual(w.direct_question_rate, 0.0)
        self.assertEqual(w.wh_word_question_rate, 0.0)
        self.assertEqual(w.tag_question_rate, 0.0)
        self.assertEqual(w.indirect_question_rate, 0.0)
        self.assertEqual(w.rhetorical_question_rate, 0.0)
        self.assertEqual(w.question_clustering_ratio, 0.0)
        self.assertEqual(w.interrogative_density_index, 0.0)
        self.assertEqual(w.classification, "declarative")

    def test_whitespace_only(self):
        w = WriterInterrogativeDensity("   \n  ")
        self.assertEqual(w.n_sentences, 0)
        self.assertEqual(w.direct_question_rate, 0.0)


class TestWriterInterrogativeDensityDeclarative(unittest.TestCase):
    """Text with no questions should be fully declarative."""

    TEXT = (
        "The sun rose over the mountains. "
        "Birds sang in the trees. "
        "A gentle breeze carried the scent of pine. "
        "The river flowed steadily toward the sea. "
        "Clouds drifted across the pale blue sky. "
        "She walked along the path, counting her steps. "
        "He sat on the bench and opened his book. "
        "The children played near the fountain. "
        "An old man watched from his window. "
        "The day passed quietly, as most days did."
    )

    def setUp(self):
        self.w = WriterInterrogativeDensity(self.TEXT)

    def test_n_sentences(self):
        self.assertEqual(self.w.n_sentences, 10)

    def test_n_questions_zero(self):
        self.assertEqual(self.w.n_questions, 0)

    def test_direct_question_rate_zero(self):
        self.assertEqual(self.w.direct_question_rate, 0.0)

    def test_classification(self):
        self.assertEqual(self.w.classification, "declarative")

    def test_index_low(self):
        self.assertLess(self.w.interrogative_density_index, 0.08)


class TestWriterInterrogativeDensityAllQuestions(unittest.TestCase):
    """Text that is entirely questions."""

    TEXT = (
        "What happened? "
        "Who saw it? "
        "When did it start? "
        "Where were you? "
        "Why did she leave? "
        "How could this be? "
        "Which way did they go? "
        "Whose fault is this? "
        "What now? "
        "Why not?"
    )

    def setUp(self):
        self.w = WriterInterrogativeDensity(self.TEXT)

    def test_n_sentences(self):
        self.assertEqual(self.w.n_sentences, 10)

    def test_n_questions(self):
        self.assertEqual(self.w.n_questions, 10)

    def test_direct_question_rate(self):
        self.assertAlmostEqual(self.w.direct_question_rate, 100.0)

    def test_wh_word_rate_high(self):
        self.assertGreater(self.w.wh_word_question_rate, 80.0)

    def test_classification(self):
        self.assertEqual(self.w.classification, "question_saturated")

    def test_index_high(self):
        self.assertGreater(self.w.interrogative_density_index, 0.60)


class TestWriterInterrogativeDensityMixed(unittest.TestCase):
    """Mixed text with some questions and some declarative sentences."""

    TEXT = (
        "The experiment began at dawn. "
        "What would the results show? "
        "The researchers gathered their equipment carefully. "
        "Could the hypothesis withstand scrutiny? "
        "Data flowed in steadily throughout the morning. "
        "The first results were promising. "
        "She checked the instruments one final time. "
        "Would the pattern hold across all samples? "
        "By evening, the answer was clear. "
        "The hypothesis was confirmed."
    )

    def setUp(self):
        self.w = WriterInterrogativeDensity(self.TEXT)

    def test_n_sentences(self):
        self.assertEqual(self.w.n_sentences, 10)

    def test_n_questions(self):
        self.assertEqual(self.w.n_questions, 3)

    def test_direct_question_rate(self):
        self.assertAlmostEqual(self.w.direct_question_rate, 30.0)

    def test_wh_word_rate(self):
        # "What", "Would", "Would" — but "would" is not a wh-word
        # only "What" should match
        self.assertGreater(self.w.wh_word_question_rate, 5.0)


class TestDirectQuestionRate(unittest.TestCase):
    def test_single_question_in_ten(self):
        text = "One. Two. Three. Four. Five. Six. Seven. Eight. Nine. Really?"
        w = WriterInterrogativeDensity(text)
        self.assertAlmostEqual(w.direct_question_rate, 10.0)

    def test_five_questions_in_ten(self):
        text = "A? B. C? D. E? F. G? H. I? J."
        w = WriterInterrogativeDensity(text)
        self.assertAlmostEqual(w.direct_question_rate, 50.0)

    def test_no_questions(self):
        text = "Hello world. This is a test. Nothing more."
        w = WriterInterrogativeDensity(text)
        self.assertAlmostEqual(w.direct_question_rate, 0.0)


class TestTagQuestionRate(unittest.TestCase):
    def test_with_tag(self):
        text = "It's warm today, isn't it? The sky is blue. Birds sing, don't they?"
        w = WriterInterrogativeDensity(text)
        self.assertGreater(w.tag_question_rate, 0.0)

    def test_no_tags(self):
        text = "What is this? Where are we? Who came?"
        w = WriterInterrogativeDensity(text)
        self.assertAlmostEqual(w.tag_question_rate, 0.0)


class TestIndirectQuestionRate(unittest.TestCase):
    def test_with_indirect(self):
        text = (
            "She wondered if he would come. "
            "The question is how we proceed. "
            "It remains unclear why this happened."
        )
        w = WriterInterrogativeDensity(text)
        self.assertGreater(w.indirect_question_rate, 0.0)

    def test_no_indirect(self):
        text = "She walked. He talked. They walked together."
        w = WriterInterrogativeDensity(text)
        self.assertAlmostEqual(w.indirect_question_rate, 0.0)


class TestQuestionClustering(unittest.TestCase):
    def test_clustered_questions(self):
        text = "What? Why? How? She walked. He ran. They stayed. We left."
        w = WriterInterrogativeDensity(text)
        # All three questions are adjacent — 100% clustered
        self.assertAlmostEqual(w.question_clustering_ratio, 1.0)

    def test_spread_questions(self):
        text = (
            "What? One. Two. Three. Four. "
            "Why? Six. Seven. Eight. Nine. "
            "How? Eleven. Twelve. Thirteen. Fourteen."
        )
        w = WriterInterrogativeDensity(text)
        # Each question is 5 sentences apart — 0% clustered
        self.assertAlmostEqual(w.question_clustering_ratio, 0.0)

    def test_partial_clustering(self):
        text = "What? Why? One. Two. Three. Four. Five. How? Six."
        w = WriterInterrogativeDensity(text)
        # "What?" and "Why?" are clustered (indices 0,1), "How?" (index 7) is not
        # 2 out of 3 clustered
        self.assertAlmostEqual(w.question_clustering_ratio, 2.0 / 3.0)

    def test_no_questions(self):
        text = "Hello. World. Test."
        w = WriterInterrogativeDensity(text)
        self.assertAlmostEqual(w.question_clustering_ratio, 0.0)


class TestRhetoricalQuestionRate(unittest.TestCase):
    def test_with_rhetorical(self):
        text = (
            "After all, who could deny the evidence? "
            "The results were clear. "
            "Isn't it obvious that we need to act? "
            "What could be more important than survival?"
        )
        w = WriterInterrogativeDensity(text)
        self.assertGreater(w.rhetorical_question_rate, 0.0)

    def test_no_rhetorical(self):
        text = "What time is it? Where is the station? Who are you?"
        w = WriterInterrogativeDensity(text)
        self.assertAlmostEqual(w.rhetorical_question_rate, 0.0)


class TestClassification(unittest.TestCase):
    def test_declarative(self):
        text = "The cat sat. The dog ran. The bird flew. The fish swam."
        w = WriterInterrogativeDensity(text)
        self.assertEqual(w.classification, "declarative")

    def test_question_saturated(self):
        text = " ".join(["What happened?"] * 20)
        w = WriterInterrogativeDensity(text)
        self.assertEqual(w.classification, "question_saturated")

    def test_lightly_inquisitive(self):
        # 1 question in 10 sentences = 10% direct rate → norm 0.2 → weighted ~0.06
        # but with wh-word boost it should cross 0.08
        sentences = ["Statement one."] * 9 + ["What happened?"]
        w = WriterInterrogativeDensity(" ".join(sentences))
        self.assertIn(w.classification, ("declarative", "lightly_inquisitive"))

    def test_moderately_inquisitive(self):
        # 3 questions in 10 sentences
        sentences = ["Statement."] * 7
        sentences.insert(1, "Why did it happen?")
        sentences.insert(4, "How could we fix it?")
        sentences.insert(7, "What should we do?")
        w = WriterInterrogativeDensity(" ".join(sentences))
        self.assertIn(
            w.classification, ("lightly_inquisitive", "moderately_inquisitive")
        )


class TestCompositeIndex(unittest.TestCase):
    def test_index_range(self):
        """Index should always be between 0 and 1."""
        texts = [
            "No questions here at all. Just plain statements.",
            "What? Why? How? Where? When? Who?",
            "Mixed text. Some questions? Some not. Wonder if it works.",
            "",
            "One sentence.",
        ]
        for text in texts:
            w = WriterInterrogativeDensity(text)
            idx = w.interrogative_density_index
            self.assertGreaterEqual(idx, 0.0, f"Index {idx} < 0 for: {text[:50]}")
            self.assertLessEqual(idx, 1.0, f"Index {idx} > 1 for: {text[:50]}")

    def test_more_questions_higher_index(self):
        """More questions should generally yield higher index."""
        low = "A. B. C. D. E. F. G. H. I. J."
        high = "A? B? C? D? E? F? G? H? I? J?"
        w_low = WriterInterrogativeDensity(low)
        w_high = WriterInterrogativeDensity(high)
        self.assertGreater(
            w_high.interrogative_density_index,
            w_low.interrogative_density_index,
        )

    def test_wh_questions_boost(self):
        """Texts with wh-words should score higher than texts with only ? marks."""
        plain_q = "Really? Really? Really? Really? Really?"
        wh_q = "What? Why? How? Where? When?"
        w_plain = WriterInterrogativeDensity(plain_q)
        w_wh = WriterInterrogativeDensity(wh_q)
        self.assertGreater(
            w_wh.interrogative_density_index,
            w_plain.interrogative_density_index,
        )


class TestAsDict(unittest.TestCase):
    def test_keys_present(self):
        w = WriterInterrogativeDensity("What happened? She walked. Why?")
        d = w.as_dict()
        expected_keys = {
            "direct_question_rate",
            "wh_word_question_rate",
            "tag_question_rate",
            "indirect_question_rate",
            "rhetorical_question_rate",
            "question_clustering_ratio",
            "interrogative_density_index",
            "classification",
            "n_sentences",
            "n_questions",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    def test_values_are_rounded(self):
        w = WriterInterrogativeDensity("What? Why? How? She went.")
        d = w.as_dict()
        for key in [
            "direct_question_rate",
            "wh_word_question_rate",
            "tag_question_rate",
            "indirect_question_rate",
            "rhetorical_question_rate",
            "question_clustering_ratio",
            "interrogative_density_index",
        ]:
            val = d[key]
            # check at most 4 decimal places
            self.assertEqual(val, round(val, 4))


class TestAnalyse(unittest.TestCase):
    def test_returns_dict(self):
        result = analyse("What is this? She smiled.")
        self.assertIsInstance(result, dict)
        self.assertIn("interrogative_density_index", result)

    def test_empty_text(self):
        result = analyse("")
        self.assertEqual(result["classification"], "declarative")
        self.assertEqual(result["interrogative_density_index"], 0.0)

    def test_consistency_with_class(self):
        text = "What? Why? How? She went. He came. They left."
        d1 = analyse(text)
        w = WriterInterrogativeDensity(text)
        d2 = w.as_dict()
        self.assertEqual(d1, d2)


class TestEdgeCases(unittest.TestCase):
    def test_single_question(self):
        w = WriterInterrogativeDensity("What?")
        self.assertEqual(w.n_sentences, 1)
        self.assertEqual(w.n_questions, 1)
        self.assertAlmostEqual(w.direct_question_rate, 100.0)

    def test_single_statement(self):
        w = WriterInterrogativeDensity("Hello world.")
        self.assertEqual(w.n_sentences, 1)
        self.assertEqual(w.n_questions, 0)
        self.assertAlmostEqual(w.direct_question_rate, 0.0)

    def test_unicode_text(self):
        text = "¿Qué pasó? Ella caminó. ¿Por qué?"
        w = WriterInterrogativeDensity(text)
        # Two sentences end with ? — but the Spanish ¿ doesn't affect splitting
        self.assertEqual(w.n_questions, 2)

    def test_very_long_text(self):
        sentences = ["This is sentence number %d." % i for i in range(1000)]
        sentences[100] = "What happened here?"
        sentences[500] = "Why did it change?"
        sentences[900] = "How could we know?"
        text = " ".join(sentences)
        w = WriterInterrogativeDensity(text)
        self.assertEqual(w.n_sentences, 1000)
        self.assertEqual(w.n_questions, 3)

    def test_multiple_question_marks_in_sentence(self):
        # "What?? Why??" — these split oddly but still count as questions
        text = "What?? Why?? She left."
        w = WriterInterrogativeDensity(text)
        self.assertGreater(w.direct_question_rate, 0.0)

    def test_quoted_question(self):
        text = 'She asked, "What happened?" and he shrugged.'
        w = WriterInterrogativeDensity(text)
        # The sentence contains a ? but doesn't end with it (ends with .)
        self.assertEqual(w.n_questions, 0)

    def test_indirect_question_no_question_mark(self):
        text = (
            "She wondered if he was lying. "
            "The question is how we proceed. "
            "It remains unclear why this happened."
        )
        w = WriterInterrogativeDensity(text)
        # None of these end with ?, so direct_question_rate = 0
        self.assertAlmostEqual(w.direct_question_rate, 0.0)
        # But indirect questions should still be detected
        self.assertGreater(w.indirect_question_rate, 0.0)


class TestRealWorldTexts(unittest.TestCase):
    def test_socratic_dialogue(self):
        text = (
            "What is justice, Socrates? "
            "Is it merely the interest of the stronger? "
            "Or is it something more fundamental? "
            "Can a just man be happy in an unjust city? "
            "These are the questions we must examine."
        )
        w = WriterInterrogativeDensity(text)
        self.assertGreater(w.direct_question_rate, 60.0)
        self.assertIn(
            w.classification, ("heavily_inquisitive", "question_saturated")
        )

    def test_technical_specification(self):
        text = (
            "The system shall process all incoming requests within 200ms. "
            "Authentication tokens must be refreshed every 3600 seconds. "
            "Error responses shall include a machine-readable error code. "
            "The database shall maintain at least three replicas at all times. "
            "All API endpoints shall be versioned using semantic versioning."
        )
        w = WriterInterrogativeDensity(text)
        self.assertAlmostEqual(w.direct_question_rate, 0.0)
        self.assertEqual(w.classification, "declarative")

    def test_investigative_journalism(self):
        text = (
            "The documents arrived on a Tuesday morning. "
            "Who authorized the transfer? "
            "The committee had no record of the meeting. "
            "Why was the audit delayed by three months? "
            "Sources close to the investigation refused to comment. "
            "What role did the deputy director play in the decision? "
            "The timeline does not add up. "
            "One might ask whether anyone was truly in charge. "
            "The official statement was released the following day. "
            "It raised more questions than it answered."
        )
        w = WriterInterrogativeDensity(text)
        self.assertGreater(w.direct_question_rate, 20.0)
        self.assertGreater(w.indirect_question_rate, 0.0)
        self.assertIn(
            w.classification,
            ("lightly_inquisitive", "moderately_inquisitive", "heavily_inquisitive"),
        )


# ── Main ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main()
