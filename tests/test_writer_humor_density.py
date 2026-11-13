#!/usr/bin/env python3
"""Tests for writer_humor_density — 103 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_humor_density import (  # noqa: E402
    WORDPLAY_PATTERNS,
    HYPERBOLE_PATTERNS,
    ABSURDIST_PATTERNS,
    SELF_DEPRECATION_PATTERNS,
    COMEDIC_TIMING_PATTERNS,
    WriterHumorDensity,
    _split_sentences,
    _count_matching,
)


# ── Initialization ───────────────────────────────────────────────────


class TestInit(unittest.TestCase):
    """Test WriterHumorDensity initialization."""

    def test_init_default(self):
        whd = WriterHumorDensity()
        self.assertIsNotNone(whd.wordplay)
        self.assertIsNotNone(whd.hyperbole)
        self.assertIsNotNone(whd.absurdist)
        self.assertIsNotNone(whd.self_deprecation)
        self.assertIsNotNone(whd.comedic_timing)

    def test_init_sets_all_constants(self):
        whd = WriterHumorDensity()
        self.assertEqual(whd.wordplay, WORDPLAY_PATTERNS)
        self.assertEqual(whd.hyperbole, HYPERBOLE_PATTERNS)
        self.assertEqual(whd.absurdist, ABSURDIST_PATTERNS)
        self.assertEqual(whd.self_deprecation, SELF_DEPRECATION_PATTERNS)
        self.assertEqual(whd.comedic_timing, COMEDIC_TIMING_PATTERNS)

    def test_wordplay_patterns_are_compiled(self):
        import re
        for p in WORDPLAY_PATTERNS:
            self.assertIsInstance(p, re.Pattern)

    def test_hyperbole_patterns_are_compiled(self):
        import re
        for p in HYPERBOLE_PATTERNS:
            self.assertIsInstance(p, re.Pattern)

    def test_absurdist_patterns_are_compiled(self):
        import re
        for p in ABSURDIST_PATTERNS:
            self.assertIsInstance(p, re.Pattern)

    def test_self_deprecation_patterns_are_compiled(self):
        import re
        for p in SELF_DEPRECATION_PATTERNS:
            self.assertIsInstance(p, re.Pattern)

    def test_comedic_timing_patterns_are_compiled(self):
        import re
        for p in COMEDIC_TIMING_PATTERNS:
            self.assertIsInstance(p, re.Pattern)

    def test_pattern_counts(self):
        whd = WriterHumorDensity()
        self.assertGreaterEqual(len(whd.wordplay), 10)
        self.assertGreaterEqual(len(whd.hyperbole), 10)
        self.assertGreaterEqual(len(whd.absurdist), 10)
        self.assertGreaterEqual(len(whd.self_deprecation), 10)
        self.assertGreaterEqual(len(whd.comedic_timing), 8)


# ── Helper functions ─────────────────────────────────────────────────


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_empty_string(self):
        self.assertEqual(_split_sentences(""), [])

    def test_single_sentence(self):
        result = _split_sentences("Hello world.")
        self.assertEqual(len(result), 1)

    def test_multiple_sentences(self):
        result = _split_sentences("First. Second. Third.")
        self.assertEqual(len(result), 3)

    def test_exclamation(self):
        result = _split_sentences("Wow! Amazing!")
        self.assertEqual(len(result), 2)

    def test_question(self):
        result = _split_sentences("Really? Are you sure?")
        self.assertEqual(len(result), 2)

    def test_mixed_punctuation(self):
        result = _split_sentences("Wait! Really? Yes.")
        self.assertEqual(len(result), 3)

    def test_whitespace_only(self):
        self.assertEqual(_split_sentences("   "), [])

    def test_no_terminator(self):
        result = _split_sentences("no terminator here")
        self.assertEqual(len(result), 1)

    def test_strips_whitespace(self):
        result = _split_sentences("  Hello world.   Another one.  ")
        self.assertEqual(result[0], "Hello world")
        self.assertEqual(result[1], "Another one")


class TestCountMatching(unittest.TestCase):
    """Test _count_matching helper."""

    def test_no_matches(self):
        sentences = ["Hello world", "How are you"]
        import re
        patterns = [re.compile(r"zzz")]
        self.assertEqual(_count_matching(sentences, patterns), 0)

    def test_all_match(self):
        sentences = ["Hello world", "Hello there"]
        import re
        patterns = [re.compile(r"Hello")]
        self.assertEqual(_count_matching(sentences, patterns), 2)

    def test_some_match(self):
        sentences = ["Hello world", "Goodbye world"]
        import re
        patterns = [re.compile(r"Hello")]
        self.assertEqual(_count_matching(sentences, patterns), 1)

    def test_empty_sentences(self):
        import re
        patterns = [re.compile(r"Hello")]
        self.assertEqual(_count_matching([], patterns), 0)

    def test_empty_patterns(self):
        sentences = ["Hello world"]
        self.assertEqual(_count_matching(sentences, []), 0)


# ── Wordplay Rate ─────────────────────────────────────────────────────


class TestWordplayRate(unittest.TestCase):
    """Test measure_wordplay_rate."""

    def test_empty_text(self):
        whd = WriterHumorDensity()
        self.assertEqual(whd.measure_wordplay_rate(""), 0.0)

    def test_no_wordplay(self):
        whd = WriterHumorDensity()
        text = "The report was submitted on time. All tasks completed."
        self.assertEqual(whd.measure_wordplay_rate(text), 0.0)

    def test_no_pun_intended(self):
        whd = WriterHumorDensity()
        text = "That joke about the baker was no pun intended. Next topic."
        result = whd.measure_wordplay_rate(text)
        self.assertGreater(result, 0.0)

    def test_pun_intended(self):
        whd = WriterHumorDensity()
        text = "That was a pun intended. Moving on."
        result = whd.measure_wordplay_rate(text)
        self.assertGreater(result, 0.0)

    def test_play_on_words(self):
        whd = WriterHumorDensity()
        text = "It was a clever play on words. Nothing else."
        result = whd.measure_wordplay_rate(text)
        self.assertGreater(result, 0.0)

    def test_double_entendre(self):
        whd = WriterHumorDensity()
        text = "She used a double entendre. The audience laughed."
        result = whd.measure_wordplay_rate(text)
        self.assertGreater(result, 0.0)

    def test_see_what_you_did_there(self):
        whd = WriterHumorDensity()
        text = "I see what you did there. Very clever."
        result = whd.measure_wordplay_rate(text)
        self.assertGreater(result, 0.0)

    def test_multiple_wordplay(self):
        whd = WriterHumorDensity()
        text = "No pun intended. That was a play on words. I see what you did there."
        result = whd.measure_wordplay_rate(text)
        self.assertGreaterEqual(result, 0.5)


# ── Hyperbole Rate ────────────────────────────────────────────────────


class TestHyperboleRate(unittest.TestCase):
    """Test measure_hyperbole_rate."""

    def test_empty_text(self):
        whd = WriterHumorDensity()
        self.assertEqual(whd.measure_hyperbole_rate(""), 0.0)

    def test_no_hyperbole(self):
        whd = WriterHumorDensity()
        text = "The meeting lasted one hour. We discussed the budget."
        self.assertEqual(whd.measure_hyperbole_rate(text), 0.0)

    def test_literally_the_best(self):
        whd = WriterHumorDensity()
        text = "That was literally the best thing ever. Everyone agreed."
        result = whd.measure_hyperbole_rate(text)
        self.assertGreater(result, 0.0)

    def test_million_times(self):
        whd = WriterHumorDensity()
        text = "I told you a million times already. Please listen."
        result = whd.measure_hyperbole_rate(text)
        self.assertGreater(result, 0.0)

    def test_would_rather_die(self):
        whd = WriterHumorDensity()
        text = "I would rather die than attend another meeting. Seriously."
        result = whd.measure_hyperbole_rate(text)
        self.assertGreater(result, 0.0)

    def test_longest_day_in_history(self):
        whd = WriterHumorDensity()
        text = "It was the longest day in history. Everyone was exhausted."
        result = whd.measure_hyperbole_rate(text)
        self.assertGreater(result, 0.0)

    def test_brain_exploded(self):
        whd = WriterHumorDensity()
        text = "My brain exploded after that lecture. Nothing made sense."
        result = whd.measure_hyperbole_rate(text)
        self.assertGreater(result, 0.0)

    def test_dumpster_fire(self):
        whd = WriterHumorDensity()
        text = "The entire project was an absolute dumpster fire. Nothing worked."
        result = whd.measure_hyperbole_rate(text)
        self.assertGreater(result, 0.0)

    def test_cant_even(self):
        whd = WriterHumorDensity()
        text = "I can't even. Just leave me alone."
        result = whd.measure_hyperbole_rate(text)
        self.assertGreater(result, 0.0)

    def test_end_of_civilization(self):
        whd = WriterHumorDensity()
        text = "It was the end of civilization as we know it. The WiFi was down."
        result = whd.measure_hyperbole_rate(text)
        self.assertGreater(result, 0.0)


# ── Absurdist Language Rate ──────────────────────────────────────────


class TestAbsurdistRate(unittest.TestCase):
    """Test measure_absurdist_language_rate."""

    def test_empty_text(self):
        whd = WriterHumorDensity()
        self.assertEqual(whd.measure_absurdist_language_rate(""), 0.0)

    def test_no_absurdity(self):
        whd = WriterHumorDensity()
        text = "The process completed successfully. Results were normal."
        self.assertEqual(whd.measure_absurdist_language_rate(text), 0.0)

    def test_plot_twist(self):
        whd = WriterHumorDensity()
        text = "I woke up. Plot twist: the alarm was unplugged. I was late."
        result = whd.measure_absurdist_language_rate(text)
        self.assertGreater(result, 0.0)

    def test_narrator_pattern(self):
        whd = WriterHumorDensity()
        text = "Narrator: it was not fine. Everything was on fire."
        result = whd.measure_absurdist_language_rate(text)
        self.assertGreater(result, 0.0)

    def test_this_is_fine(self):
        whd = WriterHumorDensity()
        text = "The house was on fire. This is fine. Everything is fine."
        result = whd.measure_absurdist_language_rate(text)
        self.assertGreater(result, 0.0)

    def test_record_scratch(self):
        whd = WriterHumorDensity()
        text = "Record scratch. Freeze frame. You are wondering how I got here."
        result = whd.measure_absurdist_language_rate(text)
        self.assertGreater(result, 0.0)

    def test_sure_why_not(self):
        whd = WriterHumorDensity()
        text = "I decided to learn the trombone at midnight. Sure, why not."
        result = whd.measure_absurdist_language_rate(text)
        self.assertGreater(result, 0.0)

    def test_chaos_ensued(self):
        whd = WriterHumorDensity()
        text = "I opened the spreadsheet. Chaos ensued. Numbers everywhere."
        result = whd.measure_absurdist_language_rate(text)
        self.assertGreater(result, 0.0)

    def test_404_pattern(self):
        whd = WriterHumorDensity()
        text = "404 — motivation not found. I stayed in bed. Productive day."
        result = whd.measure_absurdist_language_rate(text)
        self.assertGreater(result, 0.0)

    def test_cue_dramatic_music(self):
        whd = WriterHumorDensity()
        text = "Cue the dramatic music. I opened my bank account. Screamed."
        result = whd.measure_absurdist_language_rate(text)
        self.assertGreater(result, 0.0)


# ── Self-Deprecation Rate ────────────────────────────────────────────


class TestSelfDeprecationRate(unittest.TestCase):
    """Test measure_self_deprecation_rate."""

    def test_empty_text(self):
        whd = WriterHumorDensity()
        self.assertEqual(whd.measure_self_deprecation_rate(""), 0.0)

    def test_no_self_deprecation(self):
        whd = WriterHumorDensity()
        text = "The team performed well. Results exceeded expectations."
        self.assertEqual(whd.measure_self_deprecation_rate(text), 0.0)

    def test_im_a_disaster(self):
        whd = WriterHumorDensity()
        text = "I'm a walking disaster. I spilled coffee on my laptop. Again."
        result = whd.measure_self_deprecation_rate(text)
        self.assertGreater(result, 0.0)

    def test_im_not_smart(self):
        whd = WriterHumorDensity()
        text = "I'm not smart enough for quantum physics. I struggle with fractions."
        result = whd.measure_self_deprecation_rate(text)
        self.assertGreater(result, 0.0)

    def test_iq_of_potato(self):
        whd = WriterHumorDensity()
        text = "I have the IQ of a potato. I once got lost in my own house."
        result = whd.measure_self_deprecation_rate(text)
        self.assertGreater(result, 0.0)

    def test_terrible_at(self):
        whd = WriterHumorDensity()
        text = "I'm terrible at cooking. I once burned water. Yes, water."
        result = whd.measure_self_deprecation_rate(text)
        self.assertGreater(result, 0.0)

    def test_in_my_defense(self):
        whd = WriterHumorDensity()
        text = "In my defense, I was half asleep. The fire was small."
        result = whd.measure_self_deprecation_rate(text)
        self.assertGreater(result, 0.0)

    def test_peaked_in_high_school(self):
        whd = WriterHumorDensity()
        text = "I peaked in high school. It has been downhill since. Everyone agrees."
        result = whd.measure_self_deprecation_rate(text)
        self.assertGreater(result, 0.0)

    def test_surprisingly_succeeded(self):
        whd = WriterHumorDensity()
        text = "Surprisingly, I managed to pass. Nobody expected it, least of all me."
        result = whd.measure_self_deprecation_rate(text)
        self.assertGreater(result, 0.0)

    def test_bar_on_the_floor(self):
        whd = WriterHumorDensity()
        text = "The bar was on the floor. I still tripped over it. Classic."
        result = whd.measure_self_deprecation_rate(text)
        self.assertGreater(result, 0.0)


# ── Comedic Timing Rate ──────────────────────────────────────────────


class TestComedicTimingRate(unittest.TestCase):
    """Test measure_comedic_timing_rate."""

    def test_empty_text(self):
        whd = WriterHumorDensity()
        self.assertEqual(whd.measure_comedic_timing_rate(""), 0.0)

    def test_no_comedic_timing(self):
        whd = WriterHumorDensity()
        text = "The process runs in three steps. First, initialize."
        self.assertEqual(whd.measure_comedic_timing_rate(text), 0.0)

    def test_plot_twist_colon(self):
        whd = WriterHumorDensity()
        text = "Plot twist: the cake was a lie. Everyone was disappointed."
        result = whd.measure_comedic_timing_rate(text)
        self.assertGreater(result, 0.0)

    def test_wait_for_it(self):
        whd = WriterHumorDensity()
        text = "The winner is, wait for it, the cat. Everyone was shocked."
        result = whd.measure_comedic_timing_rate(text)
        self.assertGreater(result, 0.0)

    def test_real_tragedy(self):
        whd = WriterHumorDensity()
        text = "The real tragedy is that I forgot my umbrella. Again. It rained."
        result = whd.measure_comedic_timing_rate(text)
        self.assertGreater(result, 0.0)

    def test_dash_punchline(self):
        whd = WriterHumorDensity()
        text = "I opened the fridge — oh, never mind. Empty. As always."
        result = whd.measure_comedic_timing_rate(text)
        self.assertGreater(result, 0.0)

    def test_no_judgment_parenthetical(self):
        whd = WriterHumorDensity()
        text = "I ate the entire pizza (no judgment). It was a rough day."
        result = whd.measure_comedic_timing_rate(text)
        self.assertGreater(result, 0.0)

    def test_took_that_personally(self):
        whd = WriterHumorDensity()
        text = "Someone said pineapple belongs on pizza. And I took that personally."
        result = whd.measure_comedic_timing_rate(text)
        self.assertGreater(result, 0.0)


# ── Compute Index ────────────────────────────────────────────────────


class TestComputeHumorDensityIndex(unittest.TestCase):
    """Test compute_humor_density_index."""

    def test_all_zeros(self):
        whd = WriterHumorDensity()
        result = whd.compute_humor_density_index(0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(result, 0.0)

    def test_all_ones(self):
        whd = WriterHumorDensity()
        result = whd.compute_humor_density_index(1.0, 1.0, 1.0, 1.0, 1.0)
        self.assertAlmostEqual(result, 1.0)

    def test_equal_weights(self):
        whd = WriterHumorDensity()
        # All equal values should give that value as the index
        result = whd.compute_humor_density_index(0.5, 0.5, 0.5, 0.5, 0.5)
        self.assertAlmostEqual(result, 0.5)

    def test_single_dimension(self):
        whd = WriterHumorDensity()
        # Only wordplay at 1.0, rest 0 — should be 0.20
        result = whd.compute_humor_density_index(1.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.20)

    def test_weighted_average(self):
        whd = WriterHumorDensity()
        result = whd.compute_humor_density_index(0.2, 0.4, 0.6, 0.8, 1.0)
        expected = 0.2 * 0.2 + 0.4 * 0.2 + 0.6 * 0.2 + 0.8 * 0.2 + 1.0 * 0.2
        self.assertAlmostEqual(result, expected)

    def test_symmetry(self):
        whd = WriterHumorDensity()
        r1 = whd.compute_humor_density_index(0.1, 0.2, 0.3, 0.4, 0.5)
        r2 = whd.compute_humor_density_index(0.5, 0.4, 0.3, 0.2, 0.1)
        self.assertAlmostEqual(r1, r2)


# ── Classification ────────────────────────────────────────────────────


class TestClassify(unittest.TestCase):
    """Test classify."""

    def test_humor_free(self):
        whd = WriterHumorDensity()
        self.assertEqual(whd.classify(0.0), "humor_free")
        self.assertEqual(whd.classify(0.01), "humor_free")
        self.assertEqual(whd.classify(0.04), "humor_free")

    def test_deadpan(self):
        whd = WriterHumorDensity()
        self.assertEqual(whd.classify(0.05), "deadpan")
        self.assertEqual(whd.classify(0.10), "deadpan")
        self.assertEqual(whd.classify(0.14), "deadpan")

    def test_witty(self):
        whd = WriterHumorDensity()
        self.assertEqual(whd.classify(0.15), "witty")
        self.assertEqual(whd.classify(0.20), "witty")
        self.assertEqual(whd.classify(0.29), "witty")

    def test_comedic(self):
        whd = WriterHumorDensity()
        self.assertEqual(whd.classify(0.30), "comedic")
        self.assertEqual(whd.classify(0.40), "comedic")
        self.assertEqual(whd.classify(0.49), "comedic")

    def test_laugh_out_loud(self):
        whd = WriterHumorDensity()
        self.assertEqual(whd.classify(0.50), "laugh_out_loud")
        self.assertEqual(whd.classify(0.75), "laugh_out_loud")
        self.assertEqual(whd.classify(1.0), "laugh_out_loud")

    def test_boundary_values(self):
        whd = WriterHumorDensity()
        # Exact boundaries
        self.assertEqual(whd.classify(0.05), "deadpan")
        self.assertEqual(whd.classify(0.15), "witty")
        self.assertEqual(whd.classify(0.30), "comedic")
        self.assertEqual(whd.classify(0.50), "laugh_out_loud")


# ── Integration: measure() ───────────────────────────────────────────


class TestMeasure(unittest.TestCase):
    """Test the full measure() pipeline."""

    def test_empty_text(self):
        whd = WriterHumorDensity()
        result = whd.measure("")
        self.assertEqual(result["wordplay_rate"], 0.0)
        self.assertEqual(result["hyperbole_rate"], 0.0)
        self.assertEqual(result["absurdist_language_rate"], 0.0)
        self.assertEqual(result["self_deprecation_rate"], 0.0)
        self.assertEqual(result["comedic_timing_rate"], 0.0)
        self.assertEqual(result["humor_density_index"], 0.0)
        self.assertEqual(result["classification"], "humor_free")

    def test_serious_text(self):
        whd = WriterHumorDensity()
        text = (
            "The committee reviewed the quarterly financial statements. "
            "Revenue increased by twelve percent. "
            "Operating expenses remained within budget. "
            "The board approved the capital expenditure plan."
        )
        result = whd.measure(text)
        self.assertEqual(result["classification"], "humor_free")
        self.assertEqual(result["humor_density_index"], 0.0)

    def test_comedic_text_classification(self):
        whd = WriterHumorDensity()
        text = (
            "It was literally the worst day in history. "
            "My brain exploded when I saw the bill. "
            "Plot twist: the cat ate my homework. "
            "I'm a walking disaster, truly. "
            "The real tragedy is that I peaked in high school."
        )
        result = whd.measure(text)
        self.assertGreater(result["humor_density_index"], 0.0)
        self.assertIn(result["classification"],
                      ["witty", "comedic", "laugh_out_loud", "deadpan"])

    def test_result_keys(self):
        whd = WriterHumorDensity()
        result = whd.measure("Hello world.")
        expected_keys = {
            "wordplay_rate",
            "hyperbole_rate",
            "absurdist_language_rate",
            "self_deprecation_rate",
            "comedic_timing_rate",
            "humor_density_index",
            "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_result_values_are_rounded(self):
        whd = WriterHumorDensity()
        text = "No pun intended. A million times I told you. Plot twist: nope."
        result = whd.measure(text)
        for key in ["wordplay_rate", "hyperbole_rate", "absurdist_language_rate",
                     "self_deprecation_rate", "comedic_timing_rate",
                     "humor_density_index"]:
            # Check that values are rounded to 4 decimal places
            value = result[key]
            self.assertEqual(value, round(value, 4))

    def test_heavily_comedic_text(self):
        whd = WriterHumorDensity()
        text = (
            "It was literally the worst day in history. "
            "A million times I tried. "
            "My brain exploded. "
            "Plot twist: the cat did it. "
            "I'm a walking disaster. "
            "The bar was on the floor and I tripped. "
            "Sure, why not. "
            "404 — motivation not found. "
            "Chaos ensued. "
            "The real tragedy is my cooking."
        )
        result = whd.measure(text)
        self.assertGreater(result["humor_density_index"], 0.15)

    def test_mixed_text(self):
        whd = WriterHumorDensity()
        text = (
            "The quarterly report was submitted on time. "
            "No pun intended, but the numbers were pun-ishing. "
            "Revenue increased by twelve percent. "
            "I'm terrible at math, so I celebrated anyway. "
            "The board approved the plan."
        )
        result = whd.measure(text)
        self.assertGreater(result["humor_density_index"], 0.0)


# ── Edge cases ────────────────────────────────────────────────────────


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_single_word(self):
        whd = WriterHumorDensity()
        result = whd.measure("Hello")
        self.assertEqual(result["humor_density_index"], 0.0)

    def test_repeated_punctuation(self):
        whd = WriterHumorDensity()
        result = whd.measure("Wait!!! Really?! No...")
        self.assertIn("classification", result)

    def test_very_long_text(self):
        whd = WriterHumorDensity()
        text = "The process completed successfully. " * 1000
        result = whd.measure(text)
        self.assertEqual(result["classification"], "humor_free")

    def test_all_patterns_in_one_text(self):
        whd = WriterHumorDensity()
        text = (
            "No pun intended. "
            "Literally the best thing ever. "
            "Plot twist: aliens showed up. "
            "I'm a walking disaster. "
            "Wait for it, the real tragedy is my cooking."
        )
        result = whd.measure(text)
        self.assertGreater(result["humor_density_index"], 0.0)
        # All dimensions should be non-zero
        self.assertGreater(result["wordplay_rate"], 0.0)
        self.assertGreater(result["hyperbole_rate"], 0.0)
        self.assertGreater(result["absurdist_language_rate"], 0.0)
        self.assertGreater(result["self_deprecation_rate"], 0.0)
        self.assertGreater(result["comedic_timing_rate"], 0.0)

    def test_case_insensitivity(self):
        whd = WriterHumorDensity()
        text_upper = "NO PUN INTENDED. PLOT TWIST: NOTHING."
        text_lower = "no pun intended. plot twist: nothing."
        r_upper = whd.measure(text_upper)
        r_lower = whd.measure(text_lower)
        self.assertEqual(r_upper["wordplay_rate"], r_lower["wordplay_rate"])
        self.assertEqual(r_upper["absurdist_language_rate"], r_lower["absurdist_language_rate"])

    def test_newline_handling(self):
        whd = WriterHumorDensity()
        text = "First sentence.\nSecond sentence.\nThird sentence."
        result = whd.measure(text)
        self.assertIn("classification", result)

    def test_unicode_text(self):
        whd = WriterHumorDensity()
        text = "Unicode characters: émojis 🎉 and café. Plot twist: nothing."
        result = whd.measure(text)
        self.assertIn("classification", result)


if __name__ == "__main__":
    unittest.main()
