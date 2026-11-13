#!/usr/bin/env python3
"""Tests for writer_repetition_index — 108 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_repetition_index import (  # noqa: E402
    STOP_WORDS,
    WriterRepetitionIndex,
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


class TestContentWords(unittest.TestCase):
    def test_filters_stopwords(self):
        tokens = ["the", "cat", "in", "the", "hat"]
        self.assertEqual(_content_words(tokens), ["cat", "hat"])

    def test_filters_short_tokens(self):
        tokens = ["a", "i", "oh", "hello"]
        # "a" and "i" filtered by len <= 1; "oh" filtered as stop word
        self.assertEqual(_content_words(tokens), ["hello"])

    def test_empty(self):
        self.assertEqual(_content_words([]), [])

    def test_all_stopwords(self):
        tokens = ["the", "in", "on", "at"]
        self.assertEqual(_content_words(tokens), [])


# ── Type Token Ratio ─────────────────────────────────────────────────


class TestTypeTokenRatio(unittest.TestCase):
    def setUp(self):
        self.wri = WriterRepetitionIndex()

    def test_empty_text(self):
        self.assertEqual(self.wri.type_token_ratio(""), 1.0)

    def test_single_word(self):
        self.assertEqual(self.wri.type_token_ratio("Hello."), 1.0)

    def test_all_unique(self):
        text = "Cat dog bird fish horse elephant giraffe."
        self.assertAlmostEqual(self.wri.type_token_ratio(text), 1.0, places=2)

    def test_all_repeated(self):
        text = "Cat cat cat cat cat cat."
        ttr = self.wri.type_token_ratio(text)
        self.assertLess(ttr, 0.3)

    def test_moderate_repetition(self):
        text = "The cat sat on the mat. The same cat ran in the park."
        # content words: cat, sat, mat, same, cat, ran, park → "cat" repeats
        ttr = self.wri.type_token_ratio(text)
        self.assertGreater(ttr, 0.5)
        self.assertLess(ttr, 1.0)

    def test_higher_than_zero(self):
        text = "She walked through the garden slowly."
        self.assertGreater(self.wri.type_token_ratio(text), 0.0)


# ── Content Word Reuse Rate ──────────────────────────────────────────


class TestContentWordReuseRate(unittest.TestCase):
    def setUp(self):
        self.wri = WriterRepetitionIndex()

    def test_empty(self):
        self.assertEqual(self.wri.content_word_reuse_rate(""), 0.0)

    def test_no_reuse(self):
        text = "Cat dog bird fish horse."
        self.assertEqual(self.wri.content_word_reuse_rate(text), 0.0)

    def test_full_reuse(self):
        text = "Cat cat dog dog bird bird."
        rate = self.wri.content_word_reuse_rate(text)
        self.assertEqual(rate, 1.0)

    def test_partial_reuse(self):
        text = "The cat sat on the mat. The same cat ran across the yard."
        # content words: cat, sat, mat, same, cat, ran, across, yard
        # "cat" reused → 1 of 7 unique words reused
        rate = self.wri.content_word_reuse_rate(text)
        self.assertGreater(rate, 0.0)
        self.assertLess(rate, 1.0)

    def test_single_repeated_word(self):
        text = "Cat cat cat."
        rate = self.wri.content_word_reuse_rate(text)
        self.assertEqual(rate, 1.0)


# ── Bigram Repeat Rate ───────────────────────────────────────────────


class TestBigramRepeatRate(unittest.TestCase):
    def setUp(self):
        self.wri = WriterRepetitionIndex()

    def test_empty(self):
        self.assertEqual(self.wri.bigram_repeat_rate(""), 0.0)

    def test_short_text(self):
        self.assertEqual(self.wri.bigram_repeat_rate("Hello."), 0.0)

    def test_no_bigram_repeat(self):
        text = "Cat dog bird fish horse elephant."
        self.assertEqual(self.wri.bigram_repeat_rate(text), 0.0)

    def test_repeated_bigram(self):
        text = "The quick brown fox. The quick red dog."
        rate = self.wri.bigram_repeat_rate(text)
        self.assertGreater(rate, 0.0)

    def test_stopword_bigrams_ignored(self):
        text = "In the garden of the house."
        # "in the", "of the" are stopword-only, should be ignored
        rate = self.wri.bigram_repeat_rate(text)
        self.assertEqual(rate, 0.0)


# ── Trigram Repeat Rate ──────────────────────────────────────────────


class TestTrigramRepeatRate(unittest.TestCase):
    def setUp(self):
        self.wri = WriterRepetitionIndex()

    def test_empty(self):
        self.assertEqual(self.wri.trigram_repeat_rate(""), 0.0)

    def test_short_text(self):
        self.assertEqual(self.wri.trigram_repeat_rate("Hello world."), 0.0)

    def test_no_trigram_repeat(self):
        text = "Cat dog bird fish horse elephant giraffe lion."
        self.assertEqual(self.wri.trigram_repeat_rate(text), 0.0)

    def test_repeated_trigram(self):
        text = "The quick brown fox jumped. The quick brown dog barked."
        rate = self.wri.trigram_repeat_rate(text)
        self.assertGreater(rate, 0.0)

    def test_all_stopwords_ignored(self):
        text = "In the of a on the."
        self.assertEqual(self.wri.trigram_repeat_rate(text), 0.0)


# ── Sentence Opening Diversity ───────────────────────────────────────


class TestSentenceOpeningDiversity(unittest.TestCase):
    def setUp(self):
        self.wri = WriterRepetitionIndex()

    def test_empty(self):
        self.assertEqual(self.wri.sentence_opening_diversity(""), 1.0)

    def test_single_sentence(self):
        self.assertEqual(self.wri.sentence_opening_diversity("Hello world."), 1.0)

    def test_all_different_openings(self):
        text = "Cats sleep all day. Dogs run every morning. Birds sing at dawn."
        div = self.wri.sentence_opening_diversity(text)
        self.assertAlmostEqual(div, 1.0, places=1)

    def test_all_same_openings(self):
        text = "He walked home. He walked away. He walked slowly. He walked fast."
        div = self.wri.sentence_opening_diversity(text)
        # all open with "he" → 1 unique / 4 total = 0.25
        self.assertAlmostEqual(div, 0.25, places=2)

    def test_mixed_openings(self):
        text = "She ran fast. He walked slowly. She jumped high. He sat down."
        div = self.wri.sentence_opening_diversity(text)
        # openings: she, he, she, he → 2 unique / 4 = 0.5
        self.assertAlmostEqual(div, 0.5, places=2)

    def test_article_openings(self):
        text = "The cat slept. The dog ran. The bird flew."
        div = self.wri.sentence_opening_diversity(text)
        # all open with "the" → 1/3 ≈ 0.33
        self.assertAlmostEqual(div, 1.0 / 3.0, places=2)


# ── Sentence Length CV ──────────────────────────────────────────────


class TestSentenceLengthCV(unittest.TestCase):
    def setUp(self):
        self.wri = WriterRepetitionIndex()

    def test_empty(self):
        self.assertEqual(self.wri.sentence_length_cv(""), 0.0)

    def test_single_sentence(self):
        self.assertEqual(self.wri.sentence_length_cv("Hello world."), 0.0)

    def test_uniform_lengths(self):
        # All sentences ~3 words
        text = "Cat dog bird. Fish horse cow. Pig hen duck."
        cv = self.wri.sentence_length_cv(text)
        self.assertLess(cv, 0.3)

    def test_varied_lengths(self):
        text = "Cat. The big dog ran quickly across the field. Bird."
        cv = self.wri.sentence_length_cv(text)
        self.assertGreater(cv, 0.5)

    def test_cv_capped(self):
        # Extreme variation
        text = "A. " + " ".join(["word"] * 50) + "."
        cv = self.wri.sentence_length_cv(text)
        self.assertLessEqual(cv, 2.0)


# ── Structural Template Diversity ────────────────────────────────────


class TestStructuralTemplateDiversity(unittest.TestCase):
    def setUp(self):
        self.wri = WriterRepetitionIndex()

    def test_empty(self):
        self.assertEqual(self.wri.structural_template_diversity(""), 1.0)

    def test_single_sentence(self):
        self.assertEqual(self.wri.structural_template_diversity("Hello."), 1.0)

    def test_all_same_bucket(self):
        # All medium (9-15 words)
        sentences = ". ".join([
            " ".join(["word"] * 10) for _ in range(5)
        ]) + "."
        div = self.wri.structural_template_diversity(sentences)
        self.assertLess(div, 0.4)

    def test_diverse_buckets(self):
        text = "Cat. Dog ran fast. The bird flew over the tall tree quickly. "
        text += "She walked through the ancient forest slowly and carefully today. "
        text += ("Many " * 30).rstrip() + "."
        div = self.wri.structural_template_diversity(text)
        self.assertGreater(div, 0.3)


# ── Anaphora Rate ────────────────────────────────────────────────────


class TestAnaphoraRate(unittest.TestCase):
    def setUp(self):
        self.wri = WriterRepetitionIndex()

    def test_empty(self):
        self.assertEqual(self.wri.anaphora_rate(""), 0.0)

    def test_single_sentence(self):
        self.assertEqual(self.wri.anaphora_rate("Hello world."), 0.0)

    def test_no_anaphora(self):
        text = "Cats sleep. Dogs run. Birds fly. Fish swim."
        rate = self.wri.anaphora_rate(text)
        self.assertEqual(rate, 0.0)

    def test_full_anaphora(self):
        text = "She walked. She talked. She listened. She answered."
        rate = self.wri.anaphora_rate(text)
        # "she" repeats in every consecutive pair → 3/3 = 1.0
        self.assertAlmostEqual(rate, 1.0, places=2)

    def test_bigram_anaphora(self):
        text = "She quickly ran home. She quickly walked back."
        rate = self.wri.anaphora_rate(text)
        # both word and bigram match ("she" / "she quickly")
        self.assertGreater(rate, 0.0)

    def test_partial_anaphora(self):
        text = "She walked. He ran. She jumped. He swam."
        rate = self.wri.anaphora_rate(text)
        # pairs: (she,he) no, (he,she) no, (she,he) no → 0
        # but "she" ≠ "he", so rate = 0
        self.assertEqual(rate, 0.0)

    def test_alternating_anaphora(self):
        text = "She walked. She talked. He ran. He swam."
        rate = self.wri.anaphora_rate(text)
        # pairs: (she,she) yes, (she,he) no, (he,he) yes → 2/3
        self.assertAlmostEqual(rate, 2.0 / 3.0, places=2)


# ── Composite Analysis ──────────────────────────────────────────────


class TestAnalyze(unittest.TestCase):
    def setUp(self):
        self.wri = WriterRepetitionIndex()

    def test_empty_text(self):
        result = self.wri.analyze("")
        self.assertIn("repetition_index", result)
        self.assertIn("classification", result)
        self.assertEqual(result["type_token_ratio"], 1.0)

    def test_returns_all_keys(self):
        result = self.wri.analyze("The cat sat on the mat.")
        expected_keys = {
            "type_token_ratio", "content_word_reuse_rate",
            "bigram_repeat_rate", "trigram_repeat_rate",
            "sentence_opening_diversity", "sentence_length_cv",
            "structural_template_diversity", "anaphora_rate",
            "repetition_index", "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_classification_values(self):
        valid = {"highly_repetitive", "moderately_repetitive",
                 "balanced", "varied", "highly_varied"}
        for text in [
            "Cat cat cat cat cat.",
            "The quick brown fox jumped over the lazy dog.",
            "A. B. C. D. E. F. G. H. I. J.",
            "She walked through the garden slowly and carefully.",
        ]:
            result = self.wri.analyze(text)
            self.assertIn(result["classification"], valid)

    def test_repetition_index_range(self):
        for text in [
            "Hello world.",
            "Cat cat cat cat cat cat cat.",
            "The cat sat. The dog ran. The bird flew. The fish swam.",
            "She walked through the garden. He ran across the bridge.",
        ]:
            result = self.wri.analyze(text)
            self.assertGreaterEqual(result["repetition_index"], 0.0)
            self.assertLessEqual(result["repetition_index"], 1.0)

    def test_highly_repetitive_text(self):
        text = " ".join(["Cat cat cat."] * 10)
        result = self.wri.analyze(text)
        self.assertGreater(result["repetition_index"], 0.3)

    def test_highly_varied_text(self):
        text = (
            "Elephants migrate across vast savannas every autumn. "
            "Quantum mechanics challenges our deepest intuitions. "
            "A single raindrop fell onto the parched earth below. "
            "Philosophers debate whether free will truly exists. "
            "The orchestra performed Beethoven's ninth symphony magnificently."
        )
        result = self.wri.analyze(text)
        self.assertLess(result["repetition_index"], 0.5)

    def test_values_are_rounded(self):
        result = self.wri.analyze("The cat sat on the mat. The dog ran.")
        for key in result:
            if key != "classification":
                # check at most 4 decimal places
                self.assertEqual(result[key], round(result[key], 4))


# ── Initialization ───────────────────────────────────────────────────


class TestInit(unittest.TestCase):
    def test_default_init(self):
        wri = WriterRepetitionIndex()
        self.assertEqual(wri.stop_words, STOP_WORDS)
        self.assertIsNotNone(wri.stop_words)

    def test_stop_words_is_frozenset(self):
        self.assertIsInstance(STOP_WORDS, frozenset)

    def test_stop_words_contains_common(self):
        for word in ["the", "a", "in", "on", "and", "but"]:
            self.assertIn(word, STOP_WORDS)


# ── Edge Cases ───────────────────────────────────────────────────────


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.wri = WriterRepetitionIndex()

    def test_only_stopwords(self):
        text = "The in on at by of to."
        result = self.wri.analyze(text)
        self.assertIn("repetition_index", result)

    def test_single_character_words(self):
        text = "I a I a I a."
        result = self.wri.analyze(text)
        self.assertIn("repetition_index", result)

    def test_very_long_text(self):
        sentence = "The quick brown fox jumped over the lazy dog. "
        text = sentence * 100
        result = self.wri.analyze(text)
        self.assertIn("repetition_index", result)
        self.assertGreater(result["repetition_index"], 0.3)

    def test_unicode_ignored(self):
        text = "Hello 世界 cat dog."
        result = self.wri.analyze(text)
        self.assertIn("repetition_index", result)

    def test_newlines_as_whitespace(self):
        text = "Cat sat.\nDog ran.\nBird flew."
        result = self.wri.analyze(text)
        sentences = self.wri._split_sentences(text)
        self.assertEqual(len(sentences), 3)


# ── Boundary and stress tests ────────────────────────────────────────


class TestBoundaryValues(unittest.TestCase):
    def setUp(self):
        self.wri = WriterRepetitionIndex()

    def test_single_letter_sentence(self):
        result = self.wri.analyze("A.")
        self.assertIn("repetition_index", result)

    def test_two_words(self):
        result = self.wri.analyze("Hello world.")
        self.assertIn("repetition_index", result)

    def test_only_punctuation_between_words(self):
        text = "Hello, world! How, are! You, doing?"
        result = self.wri.analyze(text)
        self.assertIn("repetition_index", result)

    def test_all_same_word(self):
        text = "Cat. " * 50
        result = self.wri.analyze(text)
        self.assertGreater(result["repetition_index"], 0.4)

    def test_very_diverse_text(self):
        # use purely alphabetic unique words
        import string
        words = [f"{c}lpha" for c in string.ascii_lowercase]  # 26 unique
        words += [f"{c}ravo" for c in string.ascii_lowercase]  # 26 more
        text = " ".join(words) + "."
        ttr = self.wri.type_token_ratio(text)
        self.assertAlmostEqual(ttr, 1.0, places=2)

    def test_repeated_bigrams(self):
        text = "Big cat small dog big cat small dog."
        rate = self.wri.bigram_repeat_rate(text)
        self.assertGreater(rate, 0.0)

    def test_long_sentence_cv(self):
        # alternating short and long
        text = "Cat. " + " ".join(["word"] * 20) + ". Dog. " + " ".join(["word"] * 20) + "."
        cv = self.wri.sentence_length_cv(text)
        self.assertGreater(cv, 0.5)

    def test_no_sentences_analyze(self):
        result = self.wri.analyze("   ")
        self.assertEqual(result["type_token_ratio"], 1.0)
        self.assertEqual(result["content_word_reuse_rate"], 0.0)
        self.assertEqual(result["bigram_repeat_rate"], 0.0)
        self.assertEqual(result["trigram_repeat_rate"], 0.0)
        self.assertEqual(result["sentence_opening_diversity"], 1.0)
        self.assertEqual(result["sentence_length_cv"], 0.0)
        self.assertEqual(result["structural_template_diversity"], 1.0)
        self.assertEqual(result["anaphora_rate"], 0.0)


class TestRealisticTexts(unittest.TestCase):
    def setUp(self):
        self.wri = WriterRepetitionIndex()

    def test_rhetorical_anaphora(self):
        text = (
            "We shall fight on the beaches. "
            "We shall fight on the landing grounds. "
            "We shall fight in the fields and in the streets. "
            "We shall fight in the hills."
        )
        result = self.wri.analyze(text)
        self.assertGreater(result["anaphora_rate"], 0.5)
        self.assertGreater(result["repetition_index"], 0.3)

    def test_stream_of_consciousness(self):
        text = (
            "Walking through the city at midnight the neon lights "
            "reflected in puddles on the cracked pavement and the "
            "sound of distant traffic hummed like a low frequency "
            "beneath everything and the smell of rain mixed with "
            "exhaust fumes creating something almost nostalgic."
        )
        result = self.wri.analyze(text)
        self.assertIn(result["classification"],
                      {"highly_repetitive", "moderately_repetitive",
                       "balanced", "varied", "highly_varied"})

    def test_technical_documentation(self):
        text = (
            "The function accepts a string parameter. "
            "The function returns a boolean value. "
            "The function raises a ValueError on invalid input. "
            "The function is thread-safe by default."
        )
        result = self.wri.analyze(text)
        # heavy "the function" repetition
        self.assertGreater(result["anaphora_rate"], 0.5)

    def test_dialogue_heavy(self):
        text = (
            "'I don't know,' she said. "
            "'Neither do I,' he replied. "
            "'We should go,' she insisted. "
            "'Not yet,' he whispered."
        )
        result = self.wri.analyze(text)
        self.assertIn("repetition_index", result)

    def test_poetry_like(self):
        text = (
            "Roses are red. "
            "Violets are blue. "
            "Sugar is sweet. "
            "And so are you."
        )
        result = self.wri.analyze(text)
        self.assertIn("repetition_index", result)


class TestRobustness(unittest.TestCase):
    def setUp(self):
        self.wri = WriterRepetitionIndex()

    def test_many_exclamation_marks(self):
        text = "Wow! Amazing! Incredible! Unbelievable!"
        result = self.wri.analyze(text)
        self.assertIn("repetition_index", result)

    def test_question_answer_pairs(self):
        text = "What is life? Life is complex. What is death? Death is mysterious."
        result = self.wri.analyze(text)
        # "what" and "life" and "death" repeat
        self.assertGreater(result["content_word_reuse_rate"], 0.0)

    def test_repeated_contractions(self):
        text = "I can't believe it. She can't believe it. They can't believe it."
        rate = self.wri.bigram_repeat_rate(text)
        self.assertGreater(rate, 0.0)

    def test_empty_sentences_in_middle(self):
        text = "Hello world.  .  .  .  Goodbye world."
        result = self.wri.analyze(text)
        self.assertIn("repetition_index", result)

    def test_very_short_sentences(self):
        text = "Go. Run. Fly. Swim. Jump. Walk. Sit. Stand."
        cv = self.wri.sentence_length_cv(text)
        self.assertLess(cv, 0.1)  # all single-word → CV = 0

    def test_numbers_and_symbols(self):
        text = "Price is $5.00. Sale is $3.00. Discount is 40%."
        result = self.wri.analyze(text)
        self.assertIn("repetition_index", result)

    def test_classification_boundary_0_15(self):
        # craft text that lands right around the boundary
        result = self.wri.analyze("Quick brown fox. Lazy sleeping dog. Fast running cat.")
        self.assertIn(result["classification"],
                      {"balanced", "varied", "highly_varied"})

    def test_classification_boundary_0_30(self):
        text = " ".join(["The quick brown fox jumped."] * 5)
        result = self.wri.analyze(text)
        self.assertIn(result["classification"],
                      {"highly_repetitive", "moderately_repetitive", "balanced"})

    def test_bigram_with_apostrophe(self):
        # "don't" not in stop words; need actual consecutive repetition
        text = "Don't worry she said. Don't worry he replied. Be calm."
        rate = self.wri.bigram_repeat_rate(text)
        # "don't worry" appears twice as a bigram
        self.assertGreater(rate, 0.0)

    def test_trigram_all_same(self):
        text = "A B C D. A B C E. A B C F."
        rate = self.wri.trigram_repeat_rate(text)
        self.assertGreater(rate, 0.0)


class TestStructuralTemplateDiversity(unittest.TestCase):
    def setUp(self):
        self.wri = WriterRepetitionIndex()

    def test_all_micro(self):
        text = "Cat. Dog. Bird. Fish. Horse."
        div = self.wri.structural_template_diversity(text)
        self.assertLess(div, 0.4)

    def test_all_sprawling(self):
        long_sentence = " ".join(["word"] * 30) + "."
        text = (long_sentence + " ") * 5
        div = self.wri.structural_template_diversity(text)
        self.assertLess(div, 0.4)

    def test_mixed_buckets(self):
        text = (
            "Cat. "  # micro
            "The quick brown fox. "  # short
            "The quick brown fox jumped over the lazy dog. "  # medium-ish
            "The quick brown fox jumped over the lazy dog and then ran away. "  # long
            + " ".join(["word"] * 30) + "."  # sprawling
        )
        div = self.wri.structural_template_diversity(text)
        self.assertGreater(div, 0.3)


class TestAdditionalEdgeCases(unittest.TestCase):
    def setUp(self):
        self.wri = WriterRepetitionIndex()

    def test_contraction_in_stop_words(self):
        # "don't" is NOT in our stop words (only plain words are)
        from iamai.writer_repetition_index import STOP_WORDS
        self.assertNotIn("don't", STOP_WORDS)

    def test_content_word_reuse_with_contractions(self):
        text = "She can't believe she can't win."
        # content words: can't, believe, can't, win → "can't" reused
        rate = self.wri.content_word_reuse_rate(text)
        self.assertGreater(rate, 0.0)

    def test_type_token_ratio_with_repeated_verbs(self):
        text = "She runs. He runs. They run. We run."
        ttr = self.wri.type_token_ratio(text)
        # "run"/"runs" are different tokens; content words: runs, runs, run, run
        # unique: {runs, run} → TTR = 2/4 = 0.5
        self.assertAlmostEqual(ttr, 0.5, places=1)

    def test_sentence_opening_with_period_only(self):
        # a lone "." after split is kept (non-empty after strip)
        text = "Hello world. . Goodbye world."
        sentences = self.wri._split_sentences(text)
        # "." is kept as a sentence — opening_diversity handles it gracefully
        self.assertEqual(len(sentences), 3)

    def test_anaphora_single_sentence(self):
        self.assertEqual(self.wri.anaphora_rate("Hello world."), 0.0)

    def test_structural_diversity_two_buckets(self):
        text = "Cat dog. Bird fish. " + " ".join(["word"] * 10) + ". " + " ".join(["word"] * 12) + "."
        div = self.wri.structural_template_diversity(text)
        self.assertGreater(div, 0.2)


if __name__ == "__main__":
    unittest.main()
