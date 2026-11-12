#!/usr/bin/env python3
"""Tests for writer_dialog_density — 108 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_dialog_density import (  # noqa: E402
    DIALOG_OPENERS,
    FUNCTION_WORDS,
    SPEECH_VERBS,
    WriterDialogDensity,
)


class TestWriterDialogDensityInit(unittest.TestCase):
    """Test WriterDialogDensity initialization."""

    def test_init_default(self):
        wdd = WriterDialogDensity()
        self.assertIsNotNone(wdd.speech_verbs)
        self.assertIsNotNone(wdd.dialog_openers)

    def test_init_sets_all_attributes(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd.speech_verbs, SPEECH_VERBS)
        self.assertEqual(wdd.dialog_openers, DIALOG_OPENERS)
        self.assertEqual(wdd.function_words, FUNCTION_WORDS)


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_empty_string(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd._split_sentences(""), [])

    def test_whitespace_only(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd._split_sentences("   "), [])

    def test_single_sentence(self):
        wdd = WriterDialogDensity()
        result = wdd._split_sentences("She walked home.")
        self.assertEqual(result, ["She walked home."])

    def test_multiple_sentences(self):
        wdd = WriterDialogDensity()
        result = wdd._split_sentences("She walked. He ran. They flew.")
        self.assertEqual(len(result), 3)

    def test_question_marks(self):
        wdd = WriterDialogDensity()
        result = wdd._split_sentences("Did she walk? Yes she did.")
        self.assertEqual(len(result), 2)

    def test_exclamation_marks(self):
        wdd = WriterDialogDensity()
        result = wdd._split_sentences("Run! Go! Now!")
        self.assertEqual(len(result), 3)


class TestTokenize(unittest.TestCase):
    """Test _tokenize helper."""

    def test_empty_string(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd._tokenize(""), [])

    def test_single_word(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd._tokenize("hello"), ["hello"])

    def test_multiple_words(self):
        wdd = WriterDialogDensity()
        tokens = wdd._tokenize("The quick brown fox")
        self.assertEqual(tokens, ["the", "quick", "brown", "fox"])

    def test_with_punctuation(self):
        wdd = WriterDialogDensity()
        tokens = wdd._tokenize("Hello, world!")
        self.assertEqual(tokens, ["hello", "world"])

    def test_with_contractions(self):
        wdd = WriterDialogDensity()
        tokens = wdd._tokenize("don't can't won't")
        self.assertIn("don't", tokens)
        self.assertIn("can't", tokens)
        self.assertIn("won't", tokens)


class TestExtractQuotedSegments(unittest.TestCase):
    """Test _extract_quoted_segments helper."""

    def test_empty_string(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd._extract_quoted_segments(""), [])

    def test_no_quotes(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd._extract_quoted_segments("Just plain text."), [])

    def test_single_double_quote(self):
        wdd = WriterDialogDensity()
        result = wdd._extract_quoted_segments('"Hello world"')
        self.assertEqual(result, ["Hello world"])

    def test_multiple_double_quotes(self):
        wdd = WriterDialogDensity()
        text = '"Hello" she said. "Goodbye" he replied.'
        result = wdd._extract_quoted_segments(text)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], "Hello")
        self.assertEqual(result[1], "Goodbye")

    def test_smart_double_quotes(self):
        wdd = WriterDialogDensity()
        text = "\u201cHello world\u201d she said."
        result = wdd._extract_quoted_segments(text)
        self.assertEqual(result, ["Hello world"])

    def test_guillemets(self):
        wdd = WriterDialogDensity()
        text = "\u00abBonjour le monde\u00bb dit-elle."
        result = wdd._extract_quoted_segments(text)
        self.assertEqual(result, ["Bonjour le monde"])

    def test_single_quote_short_ignored(self):
        wdd = WriterDialogDensity()
        text = "It's a nice day."
        result = wdd._extract_quoted_segments(text)
        # Single char segments should be ignored (contractions)
        self.assertEqual(result, [])

    def test_single_quote_long_accepted(self):
        wdd = WriterDialogDensity()
        text = "'Hello there friend' he said."
        result = wdd._extract_quoted_segments(text)
        self.assertEqual(len(result), 1)

    def test_em_dash_dialog(self):
        wdd = WriterDialogDensity()
        text = "\u2014 Hello there\n\u2014 How are you"
        result = wdd._extract_quoted_segments(text)
        self.assertEqual(len(result), 2)

    def test_nested_text(self):
        wdd = WriterDialogDensity()
        text = '"She told me \'go away\' but I stayed."'
        result = wdd._extract_quoted_segments(text)
        # Should find the outer double-quoted segment
        self.assertTrue(len(result) >= 1)


class TestHasSpeechAttribution(unittest.TestCase):
    """Test _has_speech_attribution helper."""

    def test_attribution_after(self):
        wdd = WriterDialogDensity()
        text = '"Hello world" she said.'
        seg = "Hello world"
        idx = text.find(seg)
        result = wdd._has_speech_attribution(text, seg, idx - 1, idx + len(seg) + 1)
        self.assertTrue(result)

    def test_attribution_before(self):
        wdd = WriterDialogDensity()
        text = 'She said, "Hello world."'
        seg = "Hello world"
        idx = text.find(seg)
        result = wdd._has_speech_attribution(text, seg, idx - 1, idx + len(seg) + 1)
        self.assertTrue(result)

    def test_no_attribution(self):
        wdd = WriterDialogDensity()
        text = '"Hello world" The rain fell on the roof.'
        seg = "Hello world"
        idx = text.find(seg)
        result = wdd._has_speech_attribution(text, seg, idx - 1, idx + len(seg) + 1)
        self.assertFalse(result)

    def test_various_speech_verbs(self):
        wdd = WriterDialogDensity()
        verbs = ["whispered", "shouted", "muttered", "demanded", "begged"]
        for verb in verbs:
            text = f'"Hello" she {verb}.'
            seg = "Hello"
            idx = text.find(seg)
            result = wdd._has_speech_attribution(
                text, seg, idx - 1, idx + len(seg) + 1
            )
            self.assertTrue(result, f"Failed for verb: {verb}")


class TestIsNarrativeBridge(unittest.TestCase):
    """Test _is_narrative_bridge helper."""

    def test_empty_gap(self):
        wdd = WriterDialogDensity()
        self.assertFalse(wdd._is_narrative_bridge("text", 0, 0))

    def test_bare_attribution(self):
        wdd = WriterDialogDensity()
        text = '"Hello" she said. "World"'
        # Gap between the two quotes
        start = text.find("she")
        end = text.find('"World')
        # "she said." is a bare attribution, not a narrative bridge
        result = wdd._is_narrative_bridge(text, start, end)
        self.assertFalse(result)

    def test_rich_narrative_bridge(self):
        wdd = WriterDialogDensity()
        text = '"Hello" She crossed the room, picked up the phone, and sighed. "World"'
        start = text.find("She crossed")
        end = text.find('"World')
        result = wdd._is_narrative_bridge(text, start, end)
        self.assertTrue(result)

    def test_action_beat(self):
        wdd = WriterDialogDensity()
        text = '"Go" He slammed the door behind him. "Fine"'
        start = text.find("He slammed")
        end = text.find('"Fine')
        result = wdd._is_narrative_bridge(text, start, end)
        self.assertTrue(result)


class TestMeasureDialogRatio(unittest.TestCase):
    """Test measure_dialog_ratio."""

    def test_empty_text(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd.measure_dialog_ratio(""), 0.0)

    def test_no_dialog(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd.measure_dialog_ratio("Just plain prose."), 0.0)

    def test_all_dialog(self):
        wdd = WriterDialogDensity()
        text = '"Hello there my dear friend" she said.'
        ratio = wdd.measure_dialog_ratio(text)
        # Most tokens are inside the quote
        self.assertGreater(ratio, 0.5)

    def test_partial_dialog(self):
        wdd = WriterDialogDensity()
        text = (
            "The rain fell heavily on the tin roof. "
            '"I think we should leave," she said quietly. '
            "But he did not move from his chair by the window."
        )
        ratio = wdd.measure_dialog_ratio(text)
        self.assertGreater(ratio, 0.0)
        self.assertLess(ratio, 0.5)

    def test_returns_float_between_0_and_1(self):
        wdd = WriterDialogDensity()
        text = '"Hello" she said. The world kept turning as it always does.'
        ratio = wdd.measure_dialog_ratio(text)
        self.assertIsInstance(ratio, float)
        self.assertGreaterEqual(ratio, 0.0)
        self.assertLessEqual(ratio, 1.0)


class TestMeasureAttributionDensity(unittest.TestCase):
    """Test measure_attribution_density."""

    def test_empty_text(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd.measure_attribution_density("", []), 0.0)

    def test_no_segments(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd.measure_attribution_density("text", []), 0.0)

    def test_all_attributed(self):
        wdd = WriterDialogDensity()
        text = '"Hello" she said. "Goodbye" he replied.'
        result = wdd.measure_attribution_density(text)
        self.assertGreater(result, 0.0)

    def test_none_attributed(self):
        wdd = WriterDialogDensity()
        text = '"Hello" The rain fell on the roof. "Goodbye" The wind picked up.'
        result = wdd.measure_attribution_density(text)
        self.assertEqual(result, 0.0)

    def test_partial_attribution(self):
        wdd = WriterDialogDensity()
        text = '"Hello" she said. "Goodbye" The door closed.'
        result = wdd.measure_attribution_density(text)
        self.assertGreater(result, 0.0)
        self.assertLessEqual(result, 1.0)


class TestMeasureQuoteCount(unittest.TestCase):
    """Test measure_quote_count."""

    def test_empty_text(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd.measure_quote_count(""), 0)

    def test_no_quotes(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd.measure_quote_count("Just prose."), 0)

    def test_one_quote(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd.measure_quote_count('"Hello" she said.'), 1)

    def test_multiple_quotes(self):
        wdd = WriterDialogDensity()
        text = '"Hello" "World" "Goodbye"'
        self.assertEqual(wdd.measure_quote_count(text), 3)

    def test_returns_int(self):
        wdd = WriterDialogDensity()
        result = wdd.measure_quote_count('"Hi" she said.')
        self.assertIsInstance(result, int)


class TestMeasureMeanQuoteLength(unittest.TestCase):
    """Test measure_mean_quote_length."""

    def test_empty_text(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd.measure_mean_quote_length(""), 0.0)

    def test_no_quotes(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd.measure_mean_quote_length("No dialog."), 0.0)

    def test_single_short_quote(self):
        wdd = WriterDialogDensity()
        result = wdd.measure_mean_quote_length('"Go" she said.')
        self.assertEqual(result, 1.0)

    def test_single_long_quote(self):
        wdd = WriterDialogDensity()
        result = wdd.measure_mean_quote_length(
            '"I think we should go to the store now"'
        )
        self.assertEqual(result, 9.0)

    def test_multiple_quotes_average(self):
        wdd = WriterDialogDensity()
        text = '"Go" she said. "I think we should leave now" he replied.'
        result = wdd.measure_mean_quote_length(text)
        # "Go" = 1 word, "I think we should leave now" = 6 words
        self.assertAlmostEqual(result, 3.5)


class TestMeasureDialogTurnFrequency(unittest.TestCase):
    """Test measure_dialog_turn_frequency."""

    def test_empty_text(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd.measure_dialog_turn_frequency(""), 0.0)

    def test_no_dialog(self):
        wdd = WriterDialogDensity()
        self.assertEqual(
            wdd.measure_dialog_turn_frequency("Just plain prose here."), 0.0
        )

    def test_some_dialog(self):
        wdd = WriterDialogDensity()
        text = (
            "The morning was cold. "
            '"Hello" she said. '
            "He looked up from his book. "
            '"How are you" he asked. '
            "She smiled and sat down."
        )
        freq = wdd.measure_dialog_turn_frequency(text)
        self.assertGreater(freq, 0.0)

    def test_high_frequency(self):
        wdd = WriterDialogDensity()
        # Short text with many quotes
        text = '"Hi" "Hey" "Yo" "Sup" "Good"'
        freq = wdd.measure_dialog_turn_frequency(text)
        self.assertGreater(freq, 50.0)  # 5 quotes / 5 words * 1000


class TestMeasureNarrativeBridgeRatio(unittest.TestCase):
    """Test measure_narrative_bridge_ratio."""

    def test_empty_text(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd.measure_narrative_bridge_ratio(""), 0.0)

    def test_no_dialog(self):
        wdd = WriterDialogDensity()
        self.assertEqual(
            wdd.measure_narrative_bridge_ratio("Just plain text."), 0.0
        )

    def test_single_quote(self):
        wdd = WriterDialogDensity()
        self.assertEqual(
            wdd.measure_narrative_bridge_ratio('"Hello" she said.'), 0.0
        )

    def test_bare_attributions_only(self):
        wdd = WriterDialogDensity()
        text = '"Hello" she said. "Goodbye" he replied.'
        ratio = wdd.measure_narrative_bridge_ratio(text)
        self.assertEqual(ratio, 0.0)

    def test_rich_bridges(self):
        wdd = WriterDialogDensity()
        text = (
            '"Hello" She crossed the room and opened the window. '
            '"Nice day" He poured himself a glass of water and sat down.'
        )
        ratio = wdd.measure_narrative_bridge_ratio(text)
        self.assertGreater(ratio, 0.0)


class TestComputeDialogDensityIndex(unittest.TestCase):
    """Test compute_dialog_density_index."""

    def test_all_zeros(self):
        wdd = WriterDialogDensity()
        result = wdd.compute_dialog_density_index(0.0, 0.0, 0, 0.0, 0.0)
        self.assertEqual(result, 0.0)

    def test_all_max(self):
        wdd = WriterDialogDensity()
        result = wdd.compute_dialog_density_index(1.0, 30.0, 30, 20.0, 1.0)
        self.assertAlmostEqual(result, 1.0)

    def test_partial_values(self):
        wdd = WriterDialogDensity()
        result = wdd.compute_dialog_density_index(0.5, 15.0, 15, 10.0, 0.5)
        self.assertGreater(result, 0.0)
        self.assertLess(result, 1.0)

    def test_weights_sum_to_one(self):
        # Implicit test: if all normalized inputs are 1.0, output is 1.0
        wdd = WriterDialogDensity()
        result = wdd.compute_dialog_density_index(1.0, 30.0, 30, 20.0, 1.0)
        self.assertAlmostEqual(result, 1.0)

    def test_returns_float(self):
        wdd = WriterDialogDensity()
        result = wdd.compute_dialog_density_index(0.3, 10.0, 5, 8.0, 0.4)
        self.assertIsInstance(result, float)


class TestClassify(unittest.TestCase):
    """Test classify."""

    def test_dialog_heavy(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd.classify(0.60), "dialog_heavy")
        self.assertEqual(wdd.classify(0.80), "dialog_heavy")
        self.assertEqual(wdd.classify(1.00), "dialog_heavy")

    def test_mixed(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd.classify(0.40), "mixed")
        self.assertEqual(wdd.classify(0.50), "mixed")
        self.assertEqual(wdd.classify(0.59), "mixed")

    def test_narrative_heavy(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd.classify(0.20), "narrative_heavy")
        self.assertEqual(wdd.classify(0.30), "narrative_heavy")
        self.assertEqual(wdd.classify(0.39), "narrative_heavy")

    def test_pure_narrative(self):
        wdd = WriterDialogDensity()
        self.assertEqual(wdd.classify(0.00), "pure_narrative")
        self.assertEqual(wdd.classify(0.10), "pure_narrative")
        self.assertEqual(wdd.classify(0.19), "pure_narrative")


class TestMeasure(unittest.TestCase):
    """Test the full measure() method."""

    def test_empty_text(self):
        wdd = WriterDialogDensity()
        result = wdd.measure("")
        self.assertEqual(result["dialog_ratio"], 0.0)
        self.assertEqual(result["attribution_density"], 0.0)
        self.assertEqual(result["quote_count"], 0)
        self.assertEqual(result["mean_quote_length"], 0.0)
        self.assertEqual(result["dialog_turn_frequency"], 0.0)
        self.assertEqual(result["narrative_bridge_ratio"], 0.0)
        self.assertEqual(result["dialog_density_index"], 0.0)
        self.assertEqual(result["classification"], "pure_narrative")

    def test_none_like_empty(self):
        wdd = WriterDialogDensity()
        result = wdd.measure("   ")
        self.assertEqual(result["classification"], "pure_narrative")

    def test_pure_narrative_text(self):
        wdd = WriterDialogDensity()
        text = (
            "The rain fell in sheets across the empty parking lot. "
            "A single streetlight flickered at the far end. "
            "The wind carried the smell of wet earth and gasoline."
        )
        result = wdd.measure(text)
        self.assertEqual(result["dialog_ratio"], 0.0)
        self.assertEqual(result["quote_count"], 0)
        self.assertEqual(result["classification"], "pure_narrative")

    def test_dialog_heavy_text(self):
        wdd = WriterDialogDensity()
        text = (
            '"What time is it" she asked. '
            '"Almost midnight" he replied. '
            '"We should go" she said. '
            '"Wait" he called. '
            '"What" she asked. '
            '"I never meant this" he said.'
        )
        result = wdd.measure(text)
        self.assertGreater(result["dialog_ratio"], 0.3)
        self.assertGreater(result["quote_count"], 4)
        self.assertIn(
            result["classification"],
            ["dialog_heavy", "mixed", "narrative_heavy"],
        )

    def test_result_keys(self):
        wdd = WriterDialogDensity()
        result = wdd.measure("Some text here.")
        expected_keys = {
            "dialog_ratio",
            "attribution_density",
            "quote_count",
            "mean_quote_length",
            "dialog_turn_frequency",
            "narrative_bridge_ratio",
            "dialog_density_index",
            "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_all_values_are_numeric_or_string(self):
        wdd = WriterDialogDensity()
        result = wdd.measure('"Hello" she said. The world kept turning.')
        for key in [
            "dialog_ratio",
            "attribution_density",
            "mean_quote_length",
            "dialog_turn_frequency",
            "narrative_bridge_ratio",
            "dialog_density_index",
        ]:
            self.assertIsInstance(result[key], float, f"{key} should be float")
        self.assertIsInstance(result["quote_count"], int)
        self.assertIsInstance(result["classification"], str)

    def test_mixed_prose(self):
        wdd = WriterDialogDensity()
        text = (
            "The morning was cold and gray. "
            '"Good morning" she said, pouring coffee. '
            "He grunted without looking up from his newspaper. "
            '"Did you sleep well" she asked, setting the mug down. '
            '"Fine" he muttered behind the sports section. '
            "She stared at him for a long moment, then turned away."
        )
        result = wdd.measure(text)
        self.assertGreater(result["dialog_ratio"], 0.0)
        self.assertEqual(result["quote_count"], 3)
        self.assertGreater(result["mean_quote_length"], 0.0)

    def test_smart_quotes(self):
        wdd = WriterDialogDensity()
        text = "\u201cHello there\u201d she said. \u201cHow are you\u201d he asked."
        result = wdd.measure(text)
        self.assertEqual(result["quote_count"], 2)
        self.assertGreater(result["dialog_ratio"], 0.0)

    def test_guillemets(self):
        wdd = WriterDialogDensity()
        text = "\u00abBonjour\u00bb dit-elle. \u00abComment allez-vous\u00bb demanda-t-il."
        result = wdd.measure(text)
        self.assertEqual(result["quote_count"], 2)


class TestSpeechVerbsConstant(unittest.TestCase):
    """Test the SPEECH_VERBS constant."""

    def test_not_empty(self):
        self.assertGreater(len(SPEECH_VERBS), 50)

    def test_common_verbs_present(self):
        for verb in ["said", "asked", "replied", "whispered", "shouted"]:
            self.assertIn(verb, SPEECH_VERBS)

    def test_all_lowercase(self):
        for verb in SPEECH_VERBS:
            self.assertEqual(verb, verb.lower())


class TestDialogOpenersConstant(unittest.TestCase):
    """Test the DIALOG_OPENERS constant."""

    def test_not_empty(self):
        self.assertGreater(len(DIALOG_OPENERS), 10)

    def test_common_openers_present(self):
        for word in ["yes", "no", "hello", "please", "sorry"]:
            self.assertIn(word, DIALOG_OPENERS)


class TestFunctionWordsConstant(unittest.TestCase):
    """Test the FUNCTION_WORDS constant."""

    def test_not_empty(self):
        self.assertGreater(len(FUNCTION_WORDS), 30)

    def test_common_words_present(self):
        for word in ["the", "a", "is", "and", "but"]:
            self.assertIn(word, FUNCTION_WORDS)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_very_short_text(self):
        wdd = WriterDialogDensity()
        result = wdd.measure("Hi")
        self.assertEqual(result["classification"], "pure_narrative")

    def test_only_quotes(self):
        wdd = WriterDialogDensity()
        text = '"Hello" "World" "Goodbye"'
        result = wdd.measure(text)
        self.assertGreater(result["dialog_ratio"], 0.5)

    def test_repeated_same_quote(self):
        wdd = WriterDialogDensity()
        text = '"No" she said. "No" she said. "No" she said.'
        result = wdd.measure(text)
        self.assertEqual(result["quote_count"], 3)

    def test_unicode_text(self):
        wdd = WriterDialogDensity()
        text = "\u201c\u4f60\u597d\u201d \u5979\u8bf4\u3002"
        # Should not crash
        result = wdd.measure(text)
        self.assertIsNotNone(result)

    def test_multiline_text(self):
        wdd = WriterDialogDensity()
        text = (
            '"First line of dialog,"\n'
            "she said, turning the page.\n"
            '"Second line follows,"\n'
            "he replied with a nod."
        )
        result = wdd.measure(text)
        self.assertEqual(result["quote_count"], 2)

    def test_dialog_with_inner_thought(self):
        wdd = WriterDialogDensity()
        text = (
            '"I agree," she said, though inside she was screaming. '
            '"Let us proceed," he said, unaware of her turmoil.'
        )
        result = wdd.measure(text)
        self.assertEqual(result["quote_count"], 2)
        self.assertGreater(result["dialog_ratio"], 0.0)

    def test_long_text_performance(self):
        wdd = WriterDialogDensity()
        # Generate a moderately long text
        lines = []
        for i in range(100):
            if i % 3 == 0:
                lines.append(f'"Line number {i}" she said.')
            else:
                lines.append(f"The prose continued with line {i}.")
        text = " ".join(lines)
        result = wdd.measure(text)
        self.assertIsNotNone(result)
        self.assertGreater(result["quote_count"], 20)

    def test_empty_quotes_ignored(self):
        wdd = WriterDialogDensity()
        text = '"" she said. "" he replied.'
        result = wdd.measure(text)
        # Empty quotes should be handled gracefully
        self.assertIsNotNone(result)

    def test_dialog_ratio_never_exceeds_one(self):
        wdd = WriterDialogDensity()
        text = '"This is all dialog nothing else" said she.'
        ratio = wdd.measure_dialog_ratio(text)
        self.assertLessEqual(ratio, 1.0)


if __name__ == "__main__":
    unittest.main()
