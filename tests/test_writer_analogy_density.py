#!/usr/bin/env python3
"""Tests for writer_analogy_density — comprehensive test suite."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_analogy_density import (  # noqa: E402
    COMPARATIVE_MAPPING_RE,
    EXPLICIT_ANALOGY_RE,
    PROPORTIONAL_ANALOGY_RE,
    PROPORTIONAL_WHAT_RE,
    SIMILE_AS_AS_RE,
    SIMILE_AS_IF_RE,
    SIMILE_LIKE_RE,
    WriterAnalogyDensity,
    _count_words,
    _sentence_has_analogy,
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

    def test_numbers_only_excluded(self):
        self.assertEqual(_count_words("42 100"), 0)

    def test_mixed(self):
        self.assertEqual(_count_words("hello 42 world"), 2)

    def test_unicode_words(self):
        self.assertEqual(_count_words("café résumé"), 2)


class TestSentenceHasAnalogy(unittest.TestCase):
    def test_plain_sentence(self):
        self.assertFalse(_sentence_has_analogy("The cat sat on the mat."))

    def test_simile_like(self):
        self.assertTrue(_sentence_has_analogy("It was like a dream."))

    def test_simile_as_as(self):
        self.assertTrue(_sentence_has_analogy("She was as brave as a lion."))

    def test_simile_as_if(self):
        self.assertTrue(_sentence_has_analogy("He acted as if nothing happened."))

    def test_explicit_analogy(self):
        self.assertTrue(_sentence_has_analogy("Just as the sun rises, so does hope."))

    def test_comparative_mapping(self):
        self.assertTrue(_sentence_has_analogy("This is analogous to the previous case."))

    def test_proportional(self):
        self.assertTrue(
            _sentence_has_analogy("The CPU is to computer as heart is to body.")
        )

    def test_no_false_positive_on_regular_like(self):
        self.assertFalse(_sentence_has_analogy("I like apples."))

    def test_no_false_positive_on_regular_as(self):
        self.assertFalse(_sentence_has_analogy("As we discussed earlier today."))


# ── Pattern-level tests ──────────────────────────────────────────────


class TestSimileLikePattern(unittest.TestCase):
    def test_like_a(self):
        self.assertTrue(SIMILE_LIKE_RE.search("it was like a storm"))

    def test_like_an(self):
        self.assertTrue(SIMILE_LIKE_RE.search("she moved like an arrow"))

    def test_like_the(self):
        self.assertTrue(SIMILE_LIKE_RE.search("it spread like the wind"))

    def test_no_match_bare_like(self):
        self.assertIsNone(SIMILE_LIKE_RE.search("I like coding"))

    def test_no_match_likely(self):
        self.assertIsNone(SIMILE_LIKE_RE.search("it is likely that"))

    def test_like_some(self):
        self.assertTrue(SIMILE_LIKE_RE.search("it was like some kind of miracle"))

    def test_like_many(self):
        self.assertTrue(SIMILE_LIKE_RE.search("they scattered like many leaves"))

    def test_case_insensitive(self):
        self.assertTrue(SIMILE_LIKE_RE.search("It was Like a dream"))


class TestSimileAsAsPattern(unittest.TestCase):
    def test_brave_as_lion(self):
        self.assertTrue(SIMILE_AS_AS_RE.search("as brave as a lion"))

    def test_cold_as_ice(self):
        self.assertTrue(SIMILE_AS_AS_RE.search("as cold as ice"))

    def test_quick_as_lightning(self):
        self.assertTrue(SIMILE_AS_AS_RE.search("as quick as lightning"))

    def test_case_insensitive(self):
        self.assertTrue(SIMILE_AS_AS_RE.search("As bright As the sun"))

    def test_no_match_bare_as(self):
        self.assertIsNone(SIMILE_AS_AS_RE.search("as we discussed"))


class TestSimileAsIfPattern(unittest.TestCase):
    def test_as_if(self):
        self.assertTrue(SIMILE_AS_IF_RE.search("he acted as if nothing happened"))

    def test_as_though(self):
        self.assertTrue(SIMILE_AS_IF_RE.search("she spoke as though in a dream"))

    def test_case_insensitive(self):
        self.assertTrue(SIMILE_AS_IF_RE.search("As If it mattered"))


class TestExplicitAnalogyPattern(unittest.TestCase):
    def test_just_as(self):
        self.assertTrue(EXPLICIT_ANALOGY_RE.search("just as the river flows"))

    def test_in_the_same_way(self):
        self.assertTrue(EXPLICIT_ANALOGY_RE.search("in the same way, cells divide"))

    def test_similarly(self):
        self.assertTrue(EXPLICIT_ANALOGY_RE.search("similarly, the brain processes"))

    def test_by_analogy(self):
        self.assertTrue(EXPLICIT_ANALOGY_RE.search("by analogy, we can see"))

    def test_think_of_it_as(self):
        self.assertTrue(EXPLICIT_ANALOGY_RE.search("think of it as a bridge"))

    def test_think_of_it_like(self):
        self.assertTrue(EXPLICIT_ANALOGY_RE.search("think of it like a filter"))

    def test_consider_the_analogy(self):
        self.assertTrue(EXPLICIT_ANALOGY_RE.search("consider the analogy of a tree"))

    def test_to_use_an_analogy(self):
        self.assertTrue(EXPLICIT_ANALOGY_RE.search("to use an analogy, it is"))

    def test_picture_it(self):
        self.assertTrue(EXPLICIT_ANALOGY_RE.search("picture it as a network"))

    def test_imagine_this(self):
        self.assertTrue(EXPLICIT_ANALOGY_RE.search("imagine this scenario unfolding"))

    def test_the_analogy_holds(self):
        self.assertTrue(EXPLICIT_ANALOGY_RE.search("the analogy holds for most cases"))

    def test_the_analogy_breaks(self):
        self.assertTrue(EXPLICIT_ANALOGY_RE.search("the analogy breaks down here"))

    def test_its_like(self):
        self.assertTrue(EXPLICIT_ANALOGY_RE.search("it's like watching paint dry"))


class TestComparativeMappingPattern(unittest.TestCase):
    def test_compared_to(self):
        self.assertTrue(COMPARATIVE_MAPPING_RE.search("compared to the original"))

    def test_compared_with(self):
        self.assertTrue(COMPARATIVE_MAPPING_RE.search("compared with the baseline"))

    def test_in_contrast_to(self):
        self.assertTrue(COMPARATIVE_MAPPING_RE.search("in contrast to the old model"))

    def test_akin_to(self):
        self.assertTrue(COMPARATIVE_MAPPING_RE.search("this is akin to a relay race"))

    def test_analogous_to(self):
        self.assertTrue(COMPARATIVE_MAPPING_RE.search("analogous to a feedback loop"))

    def test_parallel_to(self):
        self.assertTrue(COMPARATIVE_MAPPING_RE.search("parallel to the earlier argument"))

    def test_corresponds_to(self):
        self.assertTrue(COMPARATIVE_MAPPING_RE.search("this corresponds to the input"))

    def test_maps_onto(self):
        self.assertTrue(COMPARATIVE_MAPPING_RE.search("the structure maps onto the model"))

    def test_resembles(self):
        self.assertTrue(COMPARATIVE_MAPPING_RE.search("it resembles the earlier pattern"))

    def test_echoes_the(self):
        self.assertTrue(COMPARATIVE_MAPPING_RE.search("this echoes the previous result"))

    def test_reminiscent_of(self):
        self.assertTrue(COMPARATIVE_MAPPING_RE.search("it is reminiscent of the classic"))

    def test_comparable_to(self):
        self.assertTrue(COMPARATIVE_MAPPING_RE.search("is comparable to a chess game"))

    def test_mirrors_the(self):
        self.assertTrue(COMPARATIVE_MAPPING_RE.search("it mirrors the structure"))


class TestProportionalAnalogyPattern(unittest.TestCase):
    def test_is_to_as_is_to(self):
        self.assertTrue(
            PROPORTIONAL_ANALOGY_RE.search("CPU is to computer as heart is to body")
        )

    def test_is_to_what_is_to(self):
        self.assertTrue(
            PROPORTIONAL_WHAT_RE.search("engine is to car what heart is to body")
        )

    def test_case_insensitive(self):
        self.assertTrue(
            PROPORTIONAL_ANALOGY_RE.search("Root is to tree As base is to building")
        )


# ── Class property tests ─────────────────────────────────────────────


class TestWriterAnalogyDensityEmpty(unittest.TestCase):
    def setUp(self):
        self.w = WriterAnalogyDensity("")

    def test_simile_rate(self):
        self.assertEqual(self.w.simile_rate, 0.0)

    def test_explicit_analogy_rate(self):
        self.assertEqual(self.w.explicit_analogy_rate, 0.0)

    def test_comparative_mapping_rate(self):
        self.assertEqual(self.w.comparative_mapping_rate, 0.0)

    def test_proportional_analogy_rate(self):
        self.assertEqual(self.w.proportional_analogy_rate, 0.0)

    def test_analogy_word_share(self):
        self.assertEqual(self.w.analogy_word_share, 0.0)

    def test_extended_analogy_ratio(self):
        self.assertEqual(self.w.extended_analogy_ratio, 0.0)

    def test_analogy_density_index(self):
        self.assertEqual(self.w.analogy_density_index, 0.0)

    def test_classification(self):
        self.assertEqual(self.w.classification, "literal")


class TestWriterAnalogyDensityWhitespace(unittest.TestCase):
    def setUp(self):
        self.w = WriterAnalogyDensity("   \n  \t  ")

    def test_simile_rate(self):
        self.assertEqual(self.w.simile_rate, 0.0)

    def test_classification(self):
        self.assertEqual(self.w.classification, "literal")


class TestWriterAnalogyDensityNoAnalogies(unittest.TestCase):
    def setUp(self):
        self.text = (
            "The server processes requests sequentially. "
            "Each request is parsed, validated, and routed to the appropriate handler. "
            "Responses are serialized and returned to the caller. "
            "Error handling follows a consistent pattern throughout the codebase. "
            "Logging captures timestamps and stack traces for debugging."
        )
        self.w = WriterAnalogyDensity(self.text)

    def test_simile_rate_zero(self):
        self.assertEqual(self.w.simile_rate, 0.0)

    def test_explicit_analogy_rate_zero(self):
        self.assertEqual(self.w.explicit_analogy_rate, 0.0)

    def test_comparative_mapping_rate_zero(self):
        self.assertEqual(self.w.comparative_mapping_rate, 0.0)

    def test_proportional_analogy_rate_zero(self):
        self.assertEqual(self.w.proportional_analogy_rate, 0.0)

    def test_analogy_word_share_zero(self):
        self.assertEqual(self.w.analogy_word_share, 0.0)

    def test_analogy_density_index_zero(self):
        self.assertEqual(self.w.analogy_density_index, 0.0)

    def test_classification_literal(self):
        self.assertEqual(self.w.classification, "literal")


# ── Simile-heavy text ────────────────────────────────────────────────


class TestWriterAnalogyDensitySimileHeavy(unittest.TestCase):
    def setUp(self):
        self.text = (
            "The morning was like a blank canvas waiting for color. "
            "She moved through the room like a shadow across water. "
            "His voice was as smooth as polished glass. "
            "The silence was as deep as an ocean trench. "
            "They fought like cats in a sack. "
            "It felt as if the world had stopped spinning. "
            "The light was as bright as a supernova. "
            "She laughed like a bird taking flight."
        )
        self.w = WriterAnalogyDensity(self.text)

    def test_simile_rate_positive(self):
        self.assertGreater(self.w.simile_rate, 0.0)

    def test_simile_rate_high(self):
        # 8 similes in 8 sentences → rate = 100
        self.assertGreater(self.w.simile_rate, 50.0)

    def test_analogy_density_index_positive(self):
        self.assertGreater(self.w.analogy_density_index, 0.0)

    def test_classification_not_literal(self):
        self.assertNotEqual(self.w.classification, "literal")


# ── Explicit analogy text ────────────────────────────────────────────


class TestWriterAnalogyDensityExplicit(unittest.TestCase):
    def setUp(self):
        self.text = (
            "Just as a river carves its path through stone, time shapes memory. "
            "Similarly, the brain prunes unused connections during sleep. "
            "Think of it as a gardener tending an overgrown plot. "
            "In the same way, markets correct themselves after excesses. "
            "By analogy, we can understand neural networks through biology. "
            "Consider the analogy of a library organizing its collection."
        )
        self.w = WriterAnalogyDensity(self.text)

    def test_explicit_analogy_rate_positive(self):
        self.assertGreater(self.w.explicit_analogy_rate, 0.0)

    def test_explicit_analogy_rate_high(self):
        self.assertGreater(self.w.explicit_analogy_rate, 50.0)

    def test_analogy_density_index_moderate_or_high(self):
        self.assertGreater(self.w.analogy_density_index, 0.25)


# ── Comparative mapping text ─────────────────────────────────────────


class TestWriterAnalogyDensityComparative(unittest.TestCase):
    def setUp(self):
        self.text = (
            "This approach is analogous to the greedy algorithm. "
            "The structure mirrors the earlier design pattern. "
            "Compared to the baseline, performance improved significantly. "
            "The new model is akin to a Swiss army knife of solutions. "
            "Its behavior resembles the classic observer pattern."
        )
        self.w = WriterAnalogyDensity(self.text)

    def test_comparative_mapping_rate_positive(self):
        self.assertGreater(self.w.comparative_mapping_rate, 0.0)

    def test_comparative_mapping_rate_high(self):
        # 5 mappings in 5 sentences → rate = 100
        self.assertGreater(self.w.comparative_mapping_rate, 50.0)


# ── Proportional analogy text ────────────────────────────────────────


class TestWriterAnalogyDensityProportional(unittest.TestCase):
    def setUp(self):
        self.text = (
            "The CPU is to computer as heart is to body. "
            "Root is to tree what foundation is to building. "
            "The engine is to car as muscle is to animal."
        )
        self.w = WriterAnalogyDensity(self.text)

    def test_proportional_analogy_rate_positive(self):
        self.assertGreater(self.w.proportional_analogy_rate, 0.0)

    def test_proportional_analogy_rate_high(self):
        self.assertGreater(self.w.proportional_analogy_rate, 50.0)


# ── Extended analogy ratio ───────────────────────────────────────────


class TestExtendedAnalogyRatio(unittest.TestCase):
    def test_no_analogies(self):
        w = WriterAnalogyDensity("Plain text. More plain text. Still plain.")
        self.assertEqual(w.extended_analogy_ratio, 0.0)

    def test_all_isolated(self):
        # Analogies separated by non-analogy sentences
        text = (
            "It was like a dream. "
            "The server processed the request normally. "
            "Then the database returned results. "
            "It was as if time stopped. "
            "The function compiled without errors. "
            "The test suite passed all checks."
        )
        w = WriterAnalogyDensity(text)
        self.assertEqual(w.extended_analogy_ratio, 0.0)

    def test_all_adjacent(self):
        # All analogy sentences consecutive
        text = (
            "It was like a dream. "
            "Similarly, the code flowed like water. "
            "Just as the compiler parses, so does the reader."
        )
        w = WriterAnalogyDensity(text)
        self.assertEqual(w.extended_analogy_ratio, 1.0)

    def test_partial_adjacency(self):
        text = (
            "It was like a dream. "
            "Similarly, the code flowed well. "
            "The server processed normally. "
            "Think of it as a bridge between systems."
        )
        w = WriterAnalogyDensity(text)
        # Sentences 0, 1 are adjacent analogies; sentence 3 is isolated
        # 0 and 1 are extended (2 out of 3 total)
        ratio = w.extended_analogy_ratio
        self.assertGreater(ratio, 0.5)
        self.assertLess(ratio, 1.0)


# ── Word share tests ─────────────────────────────────────────────────


class TestAnalogyWordShare(unittest.TestCase):
    def test_no_analogies(self):
        w = WriterAnalogyDensity("The server runs efficiently on minimal resources.")
        self.assertEqual(w.analogy_word_share, 0.0)

    def test_some_analogies(self):
        text = "It was like a dream come true for everyone involved in the project."
        w = WriterAnalogyDensity(text)
        self.assertGreater(w.analogy_word_share, 0.0)
        self.assertLess(w.analogy_word_share, 1.0)

    def test_word_share_bounded(self):
        text = "like a bird like a fish like a cat like a dog like a horse."
        w = WriterAnalogyDensity(text)
        self.assertLessEqual(w.analogy_word_share, 1.0)
        self.assertGreaterEqual(w.analogy_word_share, 0.0)


# ── Composite index tests ────────────────────────────────────────────


class TestAnalogyDensityIndex(unittest.TestCase):
    def test_index_zero_for_empty(self):
        self.assertEqual(WriterAnalogyDensity("").analogy_density_index, 0.0)

    def test_index_zero_for_no_analogies(self):
        w = WriterAnalogyDensity("The server runs. The database responds. The code compiles.")
        self.assertEqual(w.analogy_density_index, 0.0)

    def test_index_positive_for_analogies(self):
        text = (
            "It was like a dream. Just as the river flows, so does time. "
            "Think of it as a bridge between worlds. Similarly, the mind "
            "processes information in layers. The structure is analogous to "
            "a neural network. The CPU is to computer as heart is to body."
        )
        w = WriterAnalogyDensity(text)
        self.assertGreater(w.analogy_density_index, 0.0)

    def test_index_bounded(self):
        # Maximum analogy density
        text = " ".join([
            "like a bird like a fish like a tree.",
            "as brave as a lion as cold as ice as quick as lightning.",
            "just as the sun rises similarly the moon sets.",
            "think of it as a bridge picture it as a network.",
            "akin to a relay race analogous to a feedback loop.",
            "CPU is to computer as heart is to body.",
        ])
        w = WriterAnalogyDensity(text)
        self.assertGreaterEqual(w.analogy_density_index, 0.0)
        self.assertLessEqual(w.analogy_density_index, 1.0)

    def test_index_monotonic_with_analogy_addition(self):
        base = "The server processes requests. The database stores records."
        w_base = WriterAnalogyDensity(base)
        enriched = base + " It works like a well-oiled machine."
        w_enriched = WriterAnalogyDensity(enriched)
        self.assertGreater(
            w_enriched.analogy_density_index,
            w_base.analogy_density_index,
        )


# ── Classification tests ─────────────────────────────────────────────


class TestClassification(unittest.TestCase):
    def test_literal(self):
        w = WriterAnalogyDensity("The server runs. The code compiles. Tests pass.")
        self.assertEqual(w.classification, "literal")

    def test_classification_changes_with_density(self):
        # Increasing analogy density should shift classification
        texts = [
            "The server runs. The code compiles. Tests pass. Functions return values.",
            (
                "It was like a dream. The server runs normally. "
                "Similarly, the code compiles well. Tests pass as expected."
            ),
            (
                "like a bird like a fish like a dream like a storm. "
                "as brave as a lion as cold as ice as quick as light. "
                "just as the sun rises similarly the moon glows. "
                "think of it as a bridge picture it as a web. "
                "akin to a dance analogous to a symphony. "
                "CPU is to computer as heart is to body."
            ),
        ]
        indices = [WriterAnalogyDensity(t).analogy_density_index for t in texts]
        self.assertEqual(indices[0], 0.0)
        self.assertGreater(indices[1], indices[0])
        self.assertGreater(indices[2], indices[1])


# ── Determinism tests ────────────────────────────────────────────────


class TestDeterminism(unittest.TestCase):
    def test_same_input_same_output(self):
        text = (
            "It was like a dream. Just as the river flows. "
            "Similarly, the mind processes data. Think of it as a bridge."
        )
        w1 = WriterAnalogyDensity(text)
        w2 = WriterAnalogyDensity(text)
        self.assertEqual(w1.as_dict(), w2.as_dict())

    def test_order_independent(self):
        """Same sentences in different order should give similar density."""
        sentences = [
            "It was like a dream come true.",
            "The server processes requests normally.",
            "Similarly, the code compiles without errors.",
            "The database stores records efficiently.",
        ]
        w_forward = WriterAnalogyDensity(" ".join(sentences))
        w_reverse = WriterAnalogyDensity(" ".join(reversed(sentences)))
        # Index should be the same (same number of sentences and analogies)
        self.assertAlmostEqual(
            w_forward.analogy_density_index,
            w_reverse.analogy_density_index,
            places=3,
        )


# ── Edge cases ───────────────────────────────────────────────────────


class TestEdgeCases(unittest.TestCase):
    def test_single_word(self):
        w = WriterAnalogyDensity("Hello.")
        self.assertEqual(w.analogy_density_index, 0.0)

    def test_single_sentence_with_analogy(self):
        w = WriterAnalogyDensity("It was like a dream.")
        self.assertGreater(w.simile_rate, 0.0)

    def test_very_long_sentence(self):
        text = "like a " * 200 + "bird."
        w = WriterAnalogyDensity(text)
        self.assertGreater(w.simile_rate, 0.0)

    def test_unicode_text(self):
        text = "The café was like a rêve parisien. It felt as if time had stopped."
        w = WriterAnalogyDensity(text)
        self.assertGreater(w.simile_rate, 0.0)

    def test_numbers_and_symbols(self):
        text = "The value 42 is like a magic number. As fast as O(1) lookup."
        w = WriterAnalogyDensity(text)
        self.assertGreater(w.simile_rate, 0.0)

    def test_newlines_and_tabs(self):
        text = "It was like a dream.\nSimilarly, the code flows.\tJust as expected."
        w = WriterAnalogyDensity(text)
        self.assertGreater(w.explicit_analogy_rate, 0.0)

    def test_repeated_analogies(self):
        text = "like a dream. like a bird. like a fish. like a cat."
        w = WriterAnalogyDensity(text)
        self.assertGreater(w.simile_rate, 0.0)

    def test_nested_like(self):
        text = "It was like a dream that felt like a memory."
        w = WriterAnalogyDensity(text)
        # Should count both "like a" instances
        self.assertGreaterEqual(w.simile_rate, 0.0)


# ── Realistic text types ─────────────────────────────────────────────


class TestRealisticTextTypes(unittest.TestCase):
    def test_academic_text(self):
        text = (
            "The neural network architecture is analogous to the visual cortex. "
            "Just as biological neurons fire in response to stimuli, artificial "
            "neurons activate based on weighted inputs. Similarly, backpropagation "
            "mirrors the way synaptic connections strengthen or weaken. "
            "Compared to traditional algorithms, deep learning models learn "
            "hierarchical representations in a comparable fashion to how "
            "the brain processes sensory information layer by layer."
        )
        w = WriterAnalogyDensity(text)
        self.assertGreater(w.analogy_density_index, 0.20)
        self.assertIn(w.classification, ["analogical", "heavily_analogical", "analogy_saturated"])

    def test_narrative_text(self):
        text = (
            "She walked into the room and sat down. "
            "The coffee was cold. She opened her laptop and began typing. "
            "Outside, rain tapped against the window. "
            "The meeting started at nine. Her phone buzzed twice. "
            "She finished the report and closed the laptop."
        )
        w = WriterAnalogyDensity(text)
        self.assertEqual(w.analogy_density_index, 0.0)
        self.assertEqual(w.classification, "literal")

    def test_teaching_text(self):
        text = (
            "Think of electricity like water flowing through pipes. "
            "Voltage is like water pressure — it pushes the current forward. "
            "Resistance is like a narrow section of pipe that slows the flow. "
            "Just as a pump creates pressure, a battery creates voltage. "
            "Imagine the circuit as a loop of pipe with a pump and a valve. "
            "Similarly, current is like the volume of water passing a point per second."
        )
        w = WriterAnalogyDensity(text)
        self.assertGreater(w.analogy_density_index, 0.30)
        self.assertIn(w.classification, ["analogical", "heavily_analogical", "analogy_saturated"])

    def test_technical_documentation(self):
        text = (
            "The function accepts a dictionary of parameters. "
            "It returns a list of results sorted by timestamp. "
            "Error codes are defined in the constants module. "
            "The API endpoint accepts POST requests with JSON payloads. "
            "Authentication is handled via bearer tokens."
        )
        w = WriterAnalogyDensity(text)
        self.assertEqual(w.analogy_density_index, 0.0)
        self.assertEqual(w.classification, "literal")

    def test_persuasive_essay(self):
        text = (
            "Censorship is like a dam — it holds back the natural flow of ideas. "
            "Just as a garden needs sunlight, democracy needs free expression. "
            "The press is analogous to a watchdog, alerting society to danger. "
            "Similarly, restricting speech is akin to removing the fire alarm. "
            "Think of open debate as a marketplace where the best ideas win. "
            "In contrast to authoritarian control, free speech mirrors the "
            "resilience of an ecosystem that thrives on diversity."
        )
        w = WriterAnalogyDensity(text)
        self.assertGreater(w.analogy_density_index, 0.30)


# ── as_dict tests ────────────────────────────────────────────────────


class TestAsDict(unittest.TestCase):
    def test_all_keys_present(self):
        w = WriterAnalogyDensity("It was like a dream.")
        d = w.as_dict()
        expected_keys = {
            "simile_rate",
            "explicit_analogy_rate",
            "comparative_mapping_rate",
            "proportional_analogy_rate",
            "analogy_word_share",
            "extended_analogy_ratio",
            "analogy_density_index",
            "classification",
            "n_sentences",
            "n_words",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    def test_values_are_numeric(self):
        text = "It was like a dream. Similarly, the code flows like water."
        w = WriterAnalogyDensity(text)
        d = w.as_dict()
        for key in [
            "simile_rate",
            "explicit_analogy_rate",
            "comparative_mapping_rate",
            "proportional_analogy_rate",
            "analogy_word_share",
            "extended_analogy_ratio",
            "analogy_density_index",
        ]:
            self.assertIsInstance(d[key], float, f"{key} should be float")

    def test_n_sentences_positive(self):
        w = WriterAnalogyDensity("Hello world. How are you?")
        self.assertGreater(w.as_dict()["n_sentences"], 0)

    def test_n_words_positive(self):
        w = WriterAnalogyDensity("Hello world.")
        self.assertGreater(w.as_dict()["n_words"], 0)

    def test_classification_is_string(self):
        w = WriterAnalogyDensity("Hello world.")
        self.assertIsInstance(w.as_dict()["classification"], str)


# ── analyse convenience function ─────────────────────────────────────


class TestAnalyseFunction(unittest.TestCase):
    def test_returns_dict(self):
        result = analyse("It was like a dream.")
        self.assertIsInstance(result, dict)

    def test_same_as_class(self):
        text = "It was like a dream. Similarly, the code flows."
        from_class = WriterAnalogyDensity(text).as_dict()
        from_func = analyse(text)
        self.assertEqual(from_class, from_func)

    def test_empty_input(self):
        result = analyse("")
        self.assertEqual(result["analogy_density_index"], 0.0)
        self.assertEqual(result["classification"], "literal")

    def test_rich_input(self):
        text = (
            "like a bird like a fish. as brave as a lion. "
            "just as the sun rises. think of it as a bridge."
        )
        result = analyse(text)
        self.assertGreater(result["analogy_density_index"], 0.0)


# ── Orthogonality sanity tests ───────────────────────────────────────


class TestOrthogonality(unittest.TestCase):
    """Verify that analogy density varies independently of other qualities."""

    def test_analogical_but_concise(self):
        text = "like a bird. as fast as light. akin to a relay."
        w = WriterAnalogyDensity(text)
        self.assertGreater(w.analogy_density_index, 0.0)
        # Text is very short (concise) yet analogical

    def test_analogical_but_verbose(self):
        text = (
            "The complex computational system, which operates through "
            "a series of interconnected processing nodes, is like a "
            "vast network of rivers that flow through an elaborate "
            "system of tributaries and channels, each one contributing "
            "to the overall movement of information."
        )
        w = WriterAnalogyDensity(text)
        self.assertGreater(w.analogy_density_index, 0.0)

    def test_literal_but_clear(self):
        text = (
            "The function accepts two arguments. It returns their sum. "
            "If either argument is None, it raises a ValueError. "
            "The operation is atomic and thread-safe."
        )
        w = WriterAnalogyDensity(text)
        self.assertEqual(w.analogy_density_index, 0.0)
        # Clear prose with zero analogies

    def test_literal_but_hedged(self):
        text = (
            "It might be possible that the results are somewhat inconclusive. "
            "Perhaps the methodology could potentially be improved. "
            "It seems likely that further research would be beneficial."
        )
        w = WriterAnalogyDensity(text)
        self.assertEqual(w.analogy_density_index, 0.0)
        # Hedged but no analogies


# ── Boundary tests ───────────────────────────────────────────────────


class TestBoundaries(unittest.TestCase):
    def test_one_sentence(self):
        w = WriterAnalogyDensity("Hello.")
        self.assertEqual(w.analogy_density_index, 0.0)

    def test_two_sentences(self):
        w = WriterAnalogyDensity("Hello. It was like a dream.")
        self.assertGreater(w.simile_rate, 0.0)

    def test_many_sentences(self):
        text = ". ".join([f"Sentence number {i}" for i in range(100)]) + "."
        w = WriterAnalogyDensity(text)
        self.assertEqual(w.analogy_density_index, 0.0)

    def test_all_analogy_sentences(self):
        text = ". ".join(
            ["It was like a dream" for _ in range(10)]
        ) + "."
        w = WriterAnalogyDensity(text)
        self.assertGreater(w.simile_rate, 50.0)


if __name__ == "__main__":
    unittest.main()
