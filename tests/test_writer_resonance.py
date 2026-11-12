#!/usr/bin/env python3
"""Tests for writer_resonance — 100+ test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_resonance import (  # noqa: E402
    CONNOTATIVE_WORDS,
    METAPHORICAL_VERBS,
    NEUTRAL_COUNTERPARTS,
    SIMILE_PATTERNS,
    METAPHOR_LINKING,
    ALLUSION_PATTERNS,
    WriterResonance,
)


class TestWriterResonanceInit(unittest.TestCase):
    """Test WriterResonance initialization."""

    def test_init_default(self):
        wr = WriterResonance()
        self.assertIsNotNone(wr.simile_patterns)
        self.assertIsNotNone(wr.metaphorical_verbs)

    def test_init_compiled_patterns(self):
        wr = WriterResonance()
        self.assertEqual(len(wr.simile_patterns), len(SIMILE_PATTERNS))
        self.assertEqual(len(wr.metaphor_linking), len(METAPHOR_LINKING))
        self.assertEqual(len(wr.allusion_patterns), len(ALLUSION_PATTERNS))

    def test_init_word_sets(self):
        wr = WriterResonance()
        self.assertEqual(wr.metaphorical_verbs, METAPHORICAL_VERBS)
        self.assertEqual(wr.connotative_words, CONNOTATIVE_WORDS)
        self.assertEqual(wr.neutral_counterparts, NEUTRAL_COUNTERPARTS)


class TestTokenize(unittest.TestCase):
    """Test _tokenize helper."""

    def test_empty_string(self):
        wr = WriterResonance()
        self.assertEqual(wr._tokenize(""), [])

    def test_single_word(self):
        wr = WriterResonance()
        self.assertEqual(wr._tokenize("hello"), ["hello"])

    def test_multiple_words(self):
        wr = WriterResonance()
        tokens = wr._tokenize("The quick brown fox")
        self.assertEqual(tokens, ["the", "quick", "brown", "fox"])

    def test_punctuation_stripped(self):
        wr = WriterResonance()
        tokens = wr._tokenize("echo, whisper, silence")
        self.assertEqual(tokens, ["echo", "whisper", "silence"])

    def test_uppercase_lowered(self):
        wr = WriterResonance()
        tokens = wr._tokenize("PROMETHEUS Bound")
        self.assertEqual(tokens, ["prometheus", "bound"])


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_empty_string(self):
        wr = WriterResonance()
        self.assertEqual(wr._split_sentences(""), [])

    def test_single_sentence(self):
        wr = WriterResonance()
        result = wr._split_sentences("The shadow lingered.")
        self.assertEqual(result, ["The shadow lingered"])

    def test_multiple_sentences(self):
        wr = WriterResonance()
        result = wr._split_sentences("First sentence. Second sentence!")
        self.assertEqual(len(result), 2)

    def test_question_mark(self):
        wr = WriterResonance()
        result = wr._split_sentences("Is it haunted? Yes it is.")
        self.assertEqual(len(result), 2)


class TestStemSimple(unittest.TestCase):
    """Test _stem_simple helper."""

    def test_ed_suffix(self):
        wr = WriterResonance()
        self.assertEqual(wr._stem_simple("haunted"), "haunt")

    def test_ing_suffix(self):
        wr = WriterResonance()
        self.assertEqual(wr._stem_simple("crumbling"), "crumbl")

    def test_es_suffix(self):
        wr = WriterResonance()
        self.assertEqual(wr._stem_simple("echoes"), "echo")

    def test_s_suffix(self):
        wr = WriterResonance()
        self.assertEqual(wr._stem_simple("shadows"), "shadow")

    def test_no_change(self):
        wr = WriterResonance()
        self.assertEqual(wr._stem_simple("echo"), "echo")

    def test_short_word_no_change(self):
        wr = WriterResonance()
        self.assertEqual(wr._stem_simple("as"), "as")


class TestMetaphorDensity(unittest.TestCase):
    """Test measure_metaphor_density."""

    def test_empty_text(self):
        wr = WriterResonance()
        self.assertEqual(wr.measure_metaphor_density(""), 0.0)

    def test_simile_detected(self):
        wr = WriterResonance()
        text = "The memory was like a ghost."
        result = wr.measure_metaphor_density(text)
        self.assertGreater(result, 0.0)

    def test_metaphor_linking_detected(self):
        wr = WriterResonance()
        text = "Time is a river that flows forward."
        result = wr.measure_metaphor_density(text)
        self.assertGreater(result, 0.0)

    def test_metaphorical_verb_detected(self):
        wr = WriterResonance()
        text = "The idea blossomed into a revolution."
        result = wr.measure_metaphor_density(text)
        self.assertGreater(result, 0.0)

    def test_flat_text_no_metaphors(self):
        wr = WriterResonance()
        text = "The meeting ended at five. They went home."
        result = wr.measure_metaphor_density(text)
        self.assertEqual(result, 0.0)

    def test_all_sentences_metaphorical(self):
        wr = WriterResonance()
        text = "Time devoured the garden. The idea blossomed. The old wall shattered."
        result = wr.measure_metaphor_density(text)
        self.assertEqual(result, 1.0)

    def test_partial_metaphors(self):
        wr = WriterResonance()
        text = "She walked home. The silence haunted her. She slept."
        result = wr.measure_metaphor_density(text)
        self.assertGreater(result, 0.0)
        self.assertLess(result, 1.0)


class TestAllusionRate(unittest.TestCase):
    """Test measure_allusion_rate."""

    def test_empty_text(self):
        wr = WriterResonance()
        self.assertEqual(wr.measure_allusion_rate(""), 0.0)

    def test_mythological_allusion(self):
        wr = WriterResonance()
        text = "He carried the weight of Prometheus on his shoulders."
        result = wr.measure_allusion_rate(text)
        self.assertGreater(result, 0.0)

    def test_literary_allusion(self):
        wr = WriterResonance()
        text = "It was a tragedy worthy of Shakespeare himself."
        result = wr.measure_allusion_rate(text)
        self.assertGreater(result, 0.0)

    def test_biblical_allusion(self):
        wr = WriterResonance()
        text = "They had wandered far from Eden."
        result = wr.measure_allusion_rate(text)
        self.assertGreater(result, 0.0)

    def test_famous_phrase(self):
        wr = WriterResonance()
        text = "It was the sound and fury of modern life."
        result = wr.measure_allusion_rate(text)
        self.assertGreater(result, 0.0)

    def test_no_allusion(self):
        wr = WriterResonance()
        text = "The coffee was hot and the bread was fresh."
        result = wr.measure_allusion_rate(text)
        self.assertEqual(result, 0.0)

    def test_historical_allusion(self):
        wr = WriterResonance()
        text = "They crossed their Rubicon that day."
        result = wr.measure_allusion_rate(text)
        self.assertGreater(result, 0.0)


class TestConnotativeWordRatio(unittest.TestCase):
    """Test measure_connotative_word_ratio."""

    def test_empty_text(self):
        wr = WriterResonance()
        self.assertEqual(wr.measure_connotative_word_ratio(""), 0.0)

    def test_all_connotative(self):
        wr = WriterResonance()
        text = "haunting shadows linger whisper echo mourn"
        result = wr.measure_connotative_word_ratio(text)
        self.assertGreater(result, 0.0)

    def test_no_connotative(self):
        wr = WriterResonance()
        text = "the cat sat on the mat"
        result = wr.measure_connotative_word_ratio(text)
        self.assertEqual(result, 0.0)

    def test_mixed_text(self):
        wr = WriterResonance()
        text = "The haunting memory of her gentle whisper lingered."
        result = wr.measure_connotative_word_ratio(text)
        self.assertGreater(result, 0.0)
        self.assertLess(result, 1.0)

    def test_stemmed_match(self):
        wr = WriterResonance()
        text = "The shadows lingered and whispered."
        result = wr.measure_connotative_word_ratio(text)
        self.assertGreater(result, 0.0)


class TestImageryDensity(unittest.TestCase):
    """Test measure_imagery_density."""

    def test_empty_text(self):
        wr = WriterResonance()
        self.assertEqual(wr.measure_imagery_density(""), 0.0)

    def test_evocative_imagery(self):
        wr = WriterResonance()
        text = "The haunting silence echoed through the desolate corridor like a ghost."
        result = wr.measure_imagery_density(text)
        self.assertGreater(result, 0.0)

    def test_flat_description(self):
        wr = WriterResonance()
        text = "The room had a table and two chairs."
        result = wr.measure_imagery_density(text)
        self.assertEqual(result, 0.0)

    def test_connotative_long_sentence(self):
        wr = WriterResonance()
        text = "The melancholy afternoon light crept across the weathered floorboards of the abandoned house."
        result = wr.measure_imagery_density(text)
        self.assertGreater(result, 0.0)

    def test_no_imagery_minimal(self):
        wr = WriterResonance()
        text = "He went to the store."
        result = wr.measure_imagery_density(text)
        self.assertEqual(result, 0.0)


class TestEchoDensity(unittest.TestCase):
    """Test measure_echo_density."""

    def test_empty_text(self):
        wr = WriterResonance()
        self.assertEqual(wr.measure_echo_density(""), 0.0)

    def test_single_sentence(self):
        wr = WriterResonance()
        self.assertEqual(wr.measure_echo_density("Just one sentence."), 0.0)

    def test_alliteration_echo(self):
        wr = WriterResonance()
        text = "Bright bells rang softly by the misty morning sea. Bold birds called many men home."
        result = wr.measure_echo_density(text)
        self.assertGreater(result, 0.0)

    def test_repeated_content_words(self):
        wr = WriterResonance()
        text = "The silence was absolute. That silence defined everything."
        result = wr.measure_echo_density(text)
        self.assertGreater(result, 0.0)

    def test_anaphora(self):
        wr = WriterResonance()
        text = "We shall fight on the beaches. We shall fight on the hills."
        result = wr.measure_echo_density(text)
        self.assertGreater(result, 0.0)

    def test_no_echo(self):
        wr = WriterResonance()
        text = "The cat ate fish. Dogs prefer bones. Birds eat seeds."
        result = wr.measure_echo_density(text)
        self.assertEqual(result, 0.0)


class TestComputeResonanceIndex(unittest.TestCase):
    """Test compute_resonance_index."""

    def test_all_zeros(self):
        wr = WriterResonance()
        self.assertEqual(wr.compute_resonance_index(0, 0, 0, 0, 0), 0.0)

    def test_all_ones(self):
        wr = WriterResonance()
        result = wr.compute_resonance_index(1, 1, 1, 1, 1)
        self.assertAlmostEqual(result, 1.0)

    def test_weighted_average(self):
        wr = WriterResonance()
        # Only connotative (weight 0.30) is 1.0
        result = wr.compute_resonance_index(0, 0, 1, 0, 0)
        self.assertAlmostEqual(result, 0.30)

    def test_partial_weights(self):
        wr = WriterResonance()
        result = wr.compute_resonance_index(1, 0, 0, 0, 0)
        self.assertAlmostEqual(result, 0.25)

    def test_metaphor_and_echo(self):
        wr = WriterResonance()
        result = wr.compute_resonance_index(1, 0, 0, 0, 1)
        self.assertAlmostEqual(result, 0.35)


class TestClassify(unittest.TestCase):
    """Test classify."""

    def test_profound(self):
        wr = WriterResonance()
        self.assertEqual(wr.classify(0.55), "profound")
        self.assertEqual(wr.classify(0.80), "profound")

    def test_evocative(self):
        wr = WriterResonance()
        self.assertEqual(wr.classify(0.40), "evocative")
        self.assertEqual(wr.classify(0.54), "evocative")

    def test_textured(self):
        wr = WriterResonance()
        self.assertEqual(wr.classify(0.25), "textured")
        self.assertEqual(wr.classify(0.39), "textured")

    def test_surface(self):
        wr = WriterResonance()
        self.assertEqual(wr.classify(0.10), "surface")
        self.assertEqual(wr.classify(0.24), "surface")

    def test_flat(self):
        wr = WriterResonance()
        self.assertEqual(wr.classify(0.0), "flat")
        self.assertEqual(wr.classify(0.09), "flat")

    def test_boundary_values(self):
        wr = WriterResonance()
        self.assertEqual(wr.classify(0.10), "surface")
        self.assertEqual(wr.classify(0.25), "textured")
        self.assertEqual(wr.classify(0.40), "evocative")
        self.assertEqual(wr.classify(0.55), "profound")


class TestMeasure(unittest.TestCase):
    """Test measure end-to-end."""

    def test_empty_text(self):
        wr = WriterResonance()
        result = wr.measure("")
        self.assertIn("resonance_index", result)
        self.assertIn("classification", result)
        self.assertEqual(result["resonance_index"], 0.0)
        self.assertEqual(result["classification"], "flat")

    def test_profound_text(self):
        wr = WriterResonance()
        text = (
            "The memory haunted her like a ghost she could not exorcise. "
            "Each morning she crossed the threshold of the old house, "
            "its shadow stretching toward her like a Sisyphean boulder. "
            "Time had devoured the garden, leaving only ash and silence. "
            "The silence echoed, and the echo whispered of doors she had "
            "closed behind her — doors that would never open again."
        )
        result = wr.measure(text)
        self.assertIn("resonance_index", result)
        self.assertGreater(result["resonance_index"], 0.0)
        self.assertIn("metaphor_density", result)
        self.assertIn("allusion_rate", result)
        self.assertIn("connotative_word_ratio", result)
        self.assertIn("imagery_density", result)
        self.assertIn("echo_density", result)
        self.assertIn(result["classification"],
                      ["profound", "evocative", "textured", "surface", "flat"])

    def test_flat_text(self):
        wr = WriterResonance()
        text = (
            "The meeting started at nine. There were five people. "
            "The manager talked about the budget. Everyone took notes. "
            "The meeting ended at ten."
        )
        result = wr.measure(text)
        self.assertLess(result["resonance_index"], 0.15)

    def test_all_keys_present(self):
        wr = WriterResonance()
        result = wr.measure("Some text here.")
        expected_keys = {
            "metaphor_density", "allusion_rate", "connotative_word_ratio",
            "imagery_density", "echo_density", "resonance_index",
            "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_values_are_rounded(self):
        wr = WriterResonance()
        text = "The haunting shadow whispered like a ghost in the darkness."
        result = wr.measure(text)
        for key in ["metaphor_density", "allusion_rate", "connotative_word_ratio",
                     "imagery_density", "echo_density", "resonance_index"]:
            # Check that values are rounded to 4 decimal places
            self.assertEqual(result[key], round(result[key], 4))

    def test_classification_is_valid(self):
        wr = WriterResonance()
        valid_classes = {"profound", "evocative", "textured", "surface", "flat"}
        for text in [
            "haunting shadows linger whisper echo mourn grieve weep",
            "The cat sat on the mat",
            "Like Prometheus bound to his rock, he endured each day",
            "",
            "Time devoured everything. Hope withered. Silence echoed.",
        ]:
            result = wr.measure(text)
            self.assertIn(result["classification"], valid_classes)


class TestHasEcho(unittest.TestCase):
    """Test _has_echo helper."""

    def test_empty_tokens(self):
        wr = WriterResonance()
        self.assertFalse(wr._has_echo([], ["word"]))
        self.assertFalse(wr._has_echo(["word"], []))

    def test_shared_content_words(self):
        wr = WriterResonance()
        a = ["the", "silence", "echoed", "through", "darkness"]
        b = ["that", "silence", "defined", "everything", "through"]
        self.assertTrue(wr._has_echo(a, b))

    def test_anaphora(self):
        wr = WriterResonance()
        a = ["we", "shall", "fight", "beaches"]
        b = ["we", "shall", "fight", "hills"]
        self.assertTrue(wr._has_echo(a, b))

    def test_no_echo(self):
        wr = WriterResonance()
        a = ["the", "cat", "ate", "fish"]
        b = ["dogs", "prefer", "bones", "today"]
        self.assertFalse(wr._has_echo(a, b))


class TestGetInitialConsonants(unittest.TestCase):
    """Test _get_initial_consonants helper."""

    def test_empty(self):
        wr = WriterResonance()
        self.assertEqual(wr._get_initial_consonants([]), set())

    def test_single_word(self):
        wr = WriterResonance()
        result = wr._get_initial_consonants(["dark"])
        self.assertEqual(result, {"plosive_alveolar"})

    def test_shared_group(self):
        wr = WriterResonance()
        result = wr._get_initial_consonants(["big", "bold", "brave"])
        self.assertEqual(result, {"plosive_labial"})

    def test_multiple_groups(self):
        wr = WriterResonance()
        result = wr._get_initial_consonants(["dark", "bold"])
        self.assertIn("plosive_alveolar", result)
        self.assertIn("plosive_labial", result)


class TestCountContentWords(unittest.TestCase):
    """Test _count_content_words helper."""

    def test_empty(self):
        wr = WriterResonance()
        self.assertEqual(wr._count_content_words([]), 1)

    def test_function_words_only(self):
        wr = WriterResonance()
        tokens = ["the", "a", "is", "and"]
        self.assertEqual(wr._count_content_words(tokens), 1)

    def test_mixed(self):
        wr = WriterResonance()
        tokens = ["the", "haunting", "shadow", "whispered"]
        result = wr._count_content_words(tokens)
        self.assertGreaterEqual(result, 3)


class TestSentenceHelpers(unittest.TestCase):
    """Test sentence-level detection helpers."""

    def test_simile_like(self):
        wr = WriterResonance()
        self.assertTrue(wr._sentence_has_simile("She ran like the wind"))

    def test_simile_as(self):
        wr = WriterResonance()
        self.assertTrue(wr._sentence_has_simile("As cold as ice"))

    def test_no_simile(self):
        wr = WriterResonance()
        self.assertFalse(wr._sentence_has_simile("The cat sat"))

    def test_metaphor_linking_is(self):
        wr = WriterResonance()
        self.assertTrue(wr._sentence_has_metaphor_linking("Time is a river"))

    def test_metaphor_linking_was(self):
        wr = WriterResonance()
        self.assertTrue(wr._sentence_has_metaphor_linking("Life was a journey"))

    def test_no_metaphor_linking(self):
        wr = WriterResonance()
        self.assertFalse(wr._sentence_has_metaphor_linking("The cat is hungry"))

    def test_metaphorical_verb_blossomed(self):
        wr = WriterResonance()
        self.assertTrue(wr._sentence_has_metaphorical_verb("The idea blossomed"))

    def test_metaphorical_verb_devoured(self):
        wr = WriterResonance()
        self.assertTrue(wr._sentence_has_metaphorical_verb("Time devoured all"))

    def test_no_metaphorical_verb(self):
        wr = WriterResonance()
        self.assertFalse(wr._sentence_has_metaphorical_verb("She walked home"))


class TestIntegrationProfoundVsFlat(unittest.TestCase):
    """Integration: profound text should score higher than flat text."""

    def test_profound_beats_flat(self):
        wr = WriterResonance()
        profound = (
            "The haunting memory of her whisper echoed through the "
            "desolate corridors of his mind like a ghost he could not "
            "exorcise. Time had devoured every garden, leaving only "
            "ash and silence. The silence lingered, and the lingering "
            "silence mourned what could never bloom again."
        )
        flat = (
            "He went to the office on Monday. The weather was normal. "
            "He had lunch at noon. He came back and worked until five. "
            "Then he went home."
        )
        r_profound = wr.measure(profound)
        r_flat = wr.measure(flat)
        self.assertGreater(
            r_profound["resonance_index"],
            r_flat["resonance_index"],
        )

    def test_metaphor_density_higher_in_profound(self):
        wr = WriterResonance()
        profound = "Time devoured the garden. Hope withered. The idea blossomed."
        flat = "He went home. She came in. They ate food."
        r_profound = wr.measure(profound)
        r_flat = wr.measure(flat)
        self.assertGreater(
            r_profound["metaphor_density"],
            r_flat["metaphor_density"],
        )

    def test_connotative_higher_in_profound(self):
        wr = WriterResonance()
        profound = "The haunting melancholy shadows whispered of a wistful dawn."
        flat = "The big red car went fast down the long road."
        r_profound = wr.measure(profound)
        r_flat = wr.measure(flat)
        self.assertGreater(
            r_profound["connotative_word_ratio"],
            r_flat["connotative_word_ratio"],
        )


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_single_word(self):
        wr = WriterResonance()
        result = wr.measure("haunting")
        self.assertIn("resonance_index", result)

    def test_very_long_sentence(self):
        wr = WriterResonance()
        text = ("The haunting melancholy shadow whispered through the " * 20 + ".")
        result = wr.measure(text)
        self.assertIn("resonance_index", result)
        self.assertLessEqual(result["resonance_index"], 1.0)

    def test_unicode_text(self):
        wr = WriterResonance()
        text = "Café résumé naïve über"
        result = wr.measure(text)
        self.assertIn("resonance_index", result)

    def test_numbers_only(self):
        wr = WriterResonance()
        text = "123 456 789"
        result = wr.measure(text)
        self.assertIn("resonance_index", result)
        self.assertEqual(result["classification"], "flat")

    def test_repeated_words(self):
        wr = WriterResonance()
        text = "echo echo echo echo echo echo."
        result = wr.measure(text)
        self.assertIn("resonance_index", result)


if __name__ == "__main__":
    unittest.main()
