#!/usr/bin/env python3
"""Tests for writer_reflexivity — 90+ test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_reflexivity import (  # noqa: E402
    SELF_REFERENCE_PATTERNS,
    METACOGNITION_PATTERNS,
    PERSPECTIVE_PATTERNS,
    EPISTEMIC_HUMILITY_PATTERNS,
    GROWTH_MARKER_PATTERNS,
    WriterReflexivity,
)


class TestWriterReflexivityInit(unittest.TestCase):
    """Test WriterReflexivity initialization."""

    def test_init_default(self):
        wr = WriterReflexivity()
        self.assertIsNotNone(wr.self_reference)
        self.assertIsNotNone(wr.metacognition)
        self.assertIsNotNone(wr.perspective)
        self.assertIsNotNone(wr.epistemic_humility)
        self.assertIsNotNone(wr.growth_markers)

    def test_init_compiled_patterns(self):
        wr = WriterReflexivity()
        self.assertEqual(len(wr.self_reference), len(SELF_REFERENCE_PATTERNS))
        self.assertEqual(len(wr.metacognition), len(METACOGNITION_PATTERNS))
        self.assertEqual(len(wr.perspective), len(PERSPECTIVE_PATTERNS))
        self.assertEqual(len(wr.epistemic_humility), len(EPISTEMIC_HUMILITY_PATTERNS))
        self.assertEqual(len(wr.growth_markers), len(GROWTH_MARKER_PATTERNS))


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_empty_string(self):
        wr = WriterReflexivity()
        self.assertEqual(wr._split_sentences(""), [])

    def test_single_sentence(self):
        wr = WriterReflexivity()
        result = wr._split_sentences("I think this is true.")
        self.assertEqual(len(result), 1)

    def test_multiple_sentences(self):
        wr = WriterReflexivity()
        result = wr._split_sentences("Hello world. How are you. Fine thanks.")
        self.assertEqual(len(result), 3)

    def test_exclamation_question(self):
        wr = WriterReflexivity()
        result = wr._split_sentences("Really! Is that so? Yes.")
        self.assertEqual(len(result), 3)

    def test_whitespace_stripped(self):
        wr = WriterReflexivity()
        result = wr._split_sentences("  One.  Two.  ")
        self.assertEqual(result, ["One", "Two"])


class TestSelfReferenceDensity(unittest.TestCase):
    """Test self-reference detection."""

    def test_empty_text(self):
        wr = WriterReflexivity()
        self.assertEqual(wr.measure_self_reference_density(""), 0.0)

    def test_no_self_reference(self):
        wr = WriterReflexivity()
        text = "The data shows a trend. Revenue increased. Markets responded."
        self.assertEqual(wr.measure_self_reference_density(text), 0.0)

    def test_i_think(self):
        wr = WriterReflexivity()
        text = "I think this is correct. The data confirms it."
        result = wr.measure_self_reference_density(text)
        self.assertGreater(result, 0.0)

    def test_i_believe(self):
        wr = WriterReflexivity()
        text = "I believe the answer lies elsewhere. We should look deeper."
        result = wr.measure_self_reference_density(text)
        self.assertGreater(result, 0.0)

    def test_in_my_experience(self):
        wr = WriterReflexivity()
        text = "In my experience, this rarely works. The theory is sound though."
        result = wr.measure_self_reference_density(text)
        self.assertGreater(result, 0.0)

    def test_it_seems_to_me(self):
        wr = WriterReflexivity()
        text = "It seems to me that we are missing something."
        result = wr.measure_self_reference_density(text)
        self.assertGreater(result, 0.0)

    def test_from_where_i_stand(self):
        wr = WriterReflexivity()
        text = "From where I stand, the situation looks different."
        result = wr.measure_self_reference_density(text)
        self.assertGreater(result, 0.0)

    def test_i_confess(self):
        wr = WriterReflexivity()
        text = "I confess I was surprised. The outcome was unexpected."
        result = wr.measure_self_reference_density(text)
        self.assertGreater(result, 0.0)

    def test_i_wonder(self):
        wr = WriterReflexivity()
        text = "I wonder if this is the right approach. Time will tell."
        result = wr.measure_self_reference_density(text)
        self.assertGreater(result, 0.0)

    def test_all_sentences_reflexive(self):
        wr = WriterReflexivity()
        text = "I think so. I believe it. I feel the same."
        result = wr.measure_self_reference_density(text)
        self.assertEqual(result, 1.0)

    def test_case_insensitive(self):
        wr = WriterReflexivity()
        text = "I THINK this works. I Believe it does."
        result = wr.measure_self_reference_density(text)
        self.assertGreater(result, 0.0)

    def test_my_sense_is(self):
        wr = WriterReflexivity()
        text = "My sense is that this will work. The data supports it."
        result = wr.measure_self_reference_density(text)
        self.assertGreater(result, 0.0)

    def test_i_am_not_sure(self):
        wr = WriterReflexivity()
        text = "I am not sure about this. The evidence is mixed."
        result = wr.measure_self_reference_density(text)
        self.assertGreater(result, 0.0)


class TestMetacognitionRatio(unittest.TestCase):
    """Test metacognition detection."""

    def test_empty_text(self):
        wr = WriterReflexivity()
        self.assertEqual(wr.measure_metacognition_ratio(""), 0.0)

    def test_no_metacognition(self):
        wr = WriterReflexivity()
        text = "The experiment was conducted. Results were recorded."
        self.assertEqual(wr.measure_metacognition_ratio(text), 0.0)

    def test_the_more_i_consider(self):
        wr = WriterReflexivity()
        text = "The more I consider this, the more complex it becomes."
        result = wr.measure_metacognition_ratio(text)
        self.assertGreater(result, 0.0)

    def test_on_reflection(self):
        wr = WriterReflexivity()
        text = "On reflection, I was too hasty. The data tells a different story."
        result = wr.measure_metacognition_ratio(text)
        self.assertGreater(result, 0.0)

    def test_initial_instinct(self):
        wr = WriterReflexivity()
        text = "My initial instinct was to reject the idea. But I reconsidered."
        result = wr.measure_metacognition_ratio(text)
        self.assertGreater(result, 0.0)

    def test_i_find_myself(self):
        wr = WriterReflexivity()
        text = "I find myself drawn to this argument. It has merit."
        result = wr.measure_metacognition_ratio(text)
        self.assertGreater(result, 0.0)

    def test_what_strikes_me(self):
        wr = WriterReflexivity()
        text = "What strikes me is the pattern. It appears everywhere."
        result = wr.measure_metacognition_ratio(text)
        self.assertGreater(result, 0.0)

    def test_i_notice_that_i(self):
        wr = WriterReflexivity()
        text = "I notice that I keep returning to this theme."
        result = wr.measure_metacognition_ratio(text)
        self.assertGreater(result, 0.0)

    def test_i_realize_that_i(self):
        wr = WriterReflexivity()
        text = "I realize that I was wrong. The evidence is clear."
        result = wr.measure_metacognition_ratio(text)
        self.assertGreater(result, 0.0)

    def test_but_then_i(self):
        wr = WriterReflexivity()
        text = "I had a plan, but then I reconsidered the whole approach."
        result = wr.measure_metacognition_ratio(text)
        self.assertGreater(result, 0.0)


class TestPerspectiveAcknowledgment(unittest.TestCase):
    """Test perspective acknowledgment detection."""

    def test_empty_text(self):
        wr = WriterReflexivity()
        self.assertEqual(wr.measure_perspective_acknowledgment(""), 0.0)

    def test_no_perspective(self):
        wr = WriterReflexivity()
        text = "This is the correct answer. The data proves it conclusively."
        self.assertEqual(wr.measure_perspective_acknowledgment(text), 0.0)

    def test_others_might_argue(self):
        wr = WriterReflexivity()
        text = "Others might argue that this is wrong. They have a point."
        result = wr.measure_perspective_acknowledgment(text)
        self.assertGreater(result, 0.0)

    def test_one_could_say(self):
        wr = WriterReflexivity()
        text = "One could say the opposite is true. Context matters."
        result = wr.measure_perspective_acknowledgment(text)
        self.assertGreater(result, 0.0)

    def test_from_a_different_angle(self):
        wr = WriterReflexivity()
        text = "From a different angle, the problem looks simpler."
        result = wr.measure_perspective_acknowledgment(text)
        self.assertGreater(result, 0.0)

    def test_not_everyone_would_agree(self):
        wr = WriterReflexivity()
        text = "Not everyone would agree with this assessment. Fair enough."
        result = wr.measure_perspective_acknowledgment(text)
        self.assertGreater(result, 0.0)

    def test_counter_argument(self):
        wr = WriterReflexivity()
        text = "The counter-argument is that costs outweigh benefits."
        result = wr.measure_perspective_acknowledgment(text)
        self.assertGreater(result, 0.0)

    def test_it_depends_on(self):
        wr = WriterReflexivity()
        text = "It depends on the context. There is no universal answer."
        result = wr.measure_perspective_acknowledgment(text)
        self.assertGreater(result, 0.0)

    def test_fair_point(self):
        wr = WriterReflexivity()
        text = "That's a fair point. I hadn't considered that angle."
        result = wr.measure_perspective_acknowledgment(text)
        self.assertGreater(result, 0.0)

    def test_there_are_those_who(self):
        wr = WriterReflexivity()
        text = "There are those who disagree with this interpretation."
        result = wr.measure_perspective_acknowledgment(text)
        self.assertGreater(result, 0.0)


class TestEpistemicHumilityRatio(unittest.TestCase):
    """Test epistemic humility detection."""

    def test_empty_text(self):
        wr = WriterReflexivity()
        self.assertEqual(wr.measure_epistemic_humility_ratio(""), 0.0)

    def test_no_humility(self):
        wr = WriterReflexivity()
        text = "This is absolutely true. The evidence is conclusive and definitive."
        self.assertEqual(wr.measure_epistemic_humility_ratio(text), 0.0)

    def test_i_dont_know(self):
        wr = WriterReflexivity()
        text = "I don't know the answer. The question remains open."
        result = wr.measure_epistemic_humility_ratio(text)
        self.assertGreater(result, 0.0)

    def test_perhaps(self):
        wr = WriterReflexivity()
        text = "Perhaps this is the right approach. Or perhaps not."
        result = wr.measure_epistemic_humility_ratio(text)
        self.assertGreater(result, 0.0)

    def test_maybe(self):
        wr = WriterReflexivity()
        text = "Maybe we should reconsider. The data is inconclusive."
        result = wr.measure_epistemic_humility_ratio(text)
        self.assertGreater(result, 0.0)

    def test_i_may_be_wrong(self):
        wr = WriterReflexivity()
        text = "I may be wrong about this. The evidence is still emerging."
        result = wr.measure_epistemic_humility_ratio(text)
        self.assertGreater(result, 0.0)

    def test_as_far_as_i_know(self):
        wr = WriterReflexivity()
        text = "As far as I know, no one has tried this before."
        result = wr.measure_epistemic_humility_ratio(text)
        self.assertGreater(result, 0.0)

    def test_honest_truth(self):
        wr = WriterReflexivity()
        text = "The honest truth is that nobody knows for certain."
        result = wr.measure_epistemic_humility_ratio(text)
        self.assertGreater(result, 0.0)

    def test_evidence_suggests_but(self):
        wr = WriterReflexivity()
        text = "Evidence suggests but doesn't prove a causal link."
        result = wr.measure_epistemic_humility_ratio(text)
        self.assertGreater(result, 0.0)

    def test_i_might_be_oversimplifying(self):
        wr = WriterReflexivity()
        text = "I might be oversimplifying a complex issue."
        result = wr.measure_epistemic_humility_ratio(text)
        self.assertGreater(result, 0.0)

    def test_to_the_best_of_my_knowledge(self):
        wr = WriterReflexivity()
        text = "To the best of my knowledge, this hasn't been attempted."
        result = wr.measure_epistemic_humility_ratio(text)
        self.assertGreater(result, 0.0)

    def test_ill_be_honest(self):
        wr = WriterReflexivity()
        text = "I'll be honest — this puzzles me greatly."
        result = wr.measure_epistemic_humility_ratio(text)
        self.assertGreater(result, 0.0)


class TestGrowthMarkerDensity(unittest.TestCase):
    """Test growth marker detection."""

    def test_empty_text(self):
        wr = WriterReflexivity()
        self.assertEqual(wr.measure_growth_marker_density(""), 0.0)

    def test_no_growth(self):
        wr = WriterReflexivity()
        text = "The results are consistent. The method works as expected."
        self.assertEqual(wr.measure_growth_marker_density(text), 0.0)

    def test_i_used_to_think(self):
        wr = WriterReflexivity()
        text = "I used to think this was simple. Now I see the complexity."
        result = wr.measure_growth_marker_density(text)
        self.assertGreater(result, 0.0)

    def test_looking_back(self):
        wr = WriterReflexivity()
        text = "Looking back, I made the wrong call. The data was clear."
        result = wr.measure_growth_marker_density(text)
        self.assertGreater(result, 0.0)

    def test_over_time(self):
        wr = WriterReflexivity()
        text = "Over time I've come to appreciate the nuance."
        result = wr.measure_growth_marker_density(text)
        self.assertGreater(result, 0.0)

    def test_i_was_wrong(self):
        wr = WriterReflexivity()
        text = "I was wrong about the timeline. It took much longer."
        result = wr.measure_growth_marker_density(text)
        self.assertGreater(result, 0.0)

    def test_my_thinking_has_shifted(self):
        wr = WriterReflexivity()
        text = "My thinking has shifted on this matter significantly."
        result = wr.measure_growth_marker_density(text)
        self.assertGreater(result, 0.0)

    def test_what_i_didnt_understand(self):
        wr = WriterReflexivity()
        text = "What I didn't understand then was the scope of the problem."
        result = wr.measure_growth_marker_density(text)
        self.assertGreater(result, 0.0)

    def test_i_have_since_realized(self):
        wr = WriterReflexivity()
        text = "I've since realized that my original approach was flawed."
        result = wr.measure_growth_marker_density(text)
        self.assertGreater(result, 0.0)

    def test_with_hindsight(self):
        wr = WriterReflexivity()
        text = "With the benefit of hindsight, the signs were obvious."
        result = wr.measure_growth_marker_density(text)
        self.assertGreater(result, 0.0)

    def test_now_i_see(self):
        wr = WriterReflexivity()
        text = "Now I see what was missing all along."
        result = wr.measure_growth_marker_density(text)
        self.assertGreater(result, 0.0)


class TestComputeReflexivityIndex(unittest.TestCase):
    """Test composite score computation."""

    def test_all_zeros(self):
        wr = WriterReflexivity()
        result = wr.compute_reflexivity_index(0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(result, 0.0)

    def test_all_ones(self):
        wr = WriterReflexivity()
        result = wr.compute_reflexivity_index(1.0, 1.0, 1.0, 1.0, 1.0)
        self.assertAlmostEqual(result, 1.0)

    def test_weights(self):
        wr = WriterReflexivity()
        # Only metacognition (weight 0.25)
        result = wr.compute_reflexivity_index(0.0, 1.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.25)
        # Only self-reference (weight 0.20)
        result = wr.compute_reflexivity_index(1.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.20)
        # Only growth (weight 0.15)
        result = wr.compute_reflexivity_index(0.0, 0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(result, 0.15)

    def test_mixed(self):
        wr = WriterReflexivity()
        result = wr.compute_reflexivity_index(0.5, 0.5, 0.5, 0.5, 0.5)
        self.assertAlmostEqual(result, 0.5)


class TestClassify(unittest.TestCase):
    """Test classification."""

    def test_deeply_reflexive(self):
        wr = WriterReflexivity()
        self.assertEqual(wr.classify(0.50), "deeply_reflexive")
        self.assertEqual(wr.classify(0.75), "deeply_reflexive")
        self.assertEqual(wr.classify(1.0), "deeply_reflexive")

    def test_reflexive(self):
        wr = WriterReflexivity()
        self.assertEqual(wr.classify(0.35), "reflexive")
        self.assertEqual(wr.classify(0.42), "reflexive")
        self.assertEqual(wr.classify(0.49), "reflexive")

    def test_aware(self):
        wr = WriterReflexivity()
        self.assertEqual(wr.classify(0.20), "aware")
        self.assertEqual(wr.classify(0.28), "aware")
        self.assertEqual(wr.classify(0.34), "aware")

    def test_detached(self):
        wr = WriterReflexivity()
        self.assertEqual(wr.classify(0.08), "detached")
        self.assertEqual(wr.classify(0.12), "detached")
        self.assertEqual(wr.classify(0.19), "detached")

    def test_absent(self):
        wr = WriterReflexivity()
        self.assertEqual(wr.classify(0.0), "absent")
        self.assertEqual(wr.classify(0.05), "absent")
        self.assertEqual(wr.classify(0.07), "absent")

    def test_boundary_values(self):
        wr = WriterReflexivity()
        self.assertEqual(wr.classify(0.08), "detached")
        self.assertEqual(wr.classify(0.20), "aware")
        self.assertEqual(wr.classify(0.35), "reflexive")
        self.assertEqual(wr.classify(0.50), "deeply_reflexive")


class TestMeasure(unittest.TestCase):
    """Test full measurement pipeline."""

    def test_empty_text(self):
        wr = WriterReflexivity()
        result = wr.measure("")
        self.assertEqual(result["reflexivity_index"], 0.0)
        self.assertEqual(result["classification"], "absent")

    def test_deeply_reflexive_text(self):
        wr = WriterReflexivity()
        text = (
            "I think the more I consider this, the more complex it becomes. "
            "My initial instinct was to dismiss it, but then I reconsidered. "
            "Others might argue differently, and that's a fair point. "
            "Perhaps I'm oversimplifying the issue at hand. "
            "I used to think this was straightforward, but now I see nuance. "
            "I don't know the answer, and I'm not sure anyone does. "
            "Looking back, I was wrong about several key assumptions. "
            "What strikes me is how much my thinking has shifted over time."
        )
        result = wr.measure(text)
        self.assertGreater(result["reflexivity_index"], 0.2)
        self.assertIn(result["classification"], [
            "deeply_reflexive", "reflexive", "aware"
        ])

    def test_absent_text(self):
        wr = WriterReflexivity()
        text = (
            "The data shows a clear trend. Revenue increased by twelve "
            "percent. The market responded positively. Customer satisfaction "
            "improved across all segments. The strategy proved effective."
        )
        result = wr.measure(text)
        self.assertLess(result["reflexivity_index"], 0.10)
        self.assertEqual(result["classification"], "absent")

    def test_mixed_text(self):
        wr = WriterReflexivity()
        text = (
            "The results are clear. I think this approach works best. "
            "The data supports the conclusion. Perhaps there are other "
            "valid interpretations. The methodology was sound."
        )
        result = wr.measure(text)
        self.assertGreater(result["reflexivity_index"], 0.0)
        self.assertLess(result["reflexivity_index"], 0.50)

    def test_result_keys(self):
        wr = WriterReflexivity()
        result = wr.measure("I think this works.")
        expected_keys = {
            "self_reference_density",
            "metacognition_ratio",
            "perspective_acknowledgment",
            "epistemic_humility_ratio",
            "growth_marker_density",
            "reflexivity_index",
            "classification",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_result_values_range(self):
        wr = WriterReflexivity()
        text = (
            "I think this is right. On reflection, perhaps I should "
            "reconsider. Others might disagree with my assessment. "
            "I don't know for certain. I used to think differently."
        )
        result = wr.measure(text)
        for key, value in result.items():
            if key != "classification":
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)

    def test_single_sentence(self):
        wr = WriterReflexivity()
        result = wr.measure("I think this is true.")
        self.assertGreater(result["self_reference_density"], 0.0)
        self.assertEqual(result["metacognition_ratio"], 0.0)
        self.assertEqual(result["perspective_acknowledgment"], 0.0)


class TestPatternConstants(unittest.TestCase):
    """Test that pattern constants are well-formed."""

    def test_self_reference_not_empty(self):
        self.assertGreater(len(SELF_REFERENCE_PATTERNS), 0)

    def test_metacognition_not_empty(self):
        self.assertGreater(len(METACOGNITION_PATTERNS), 0)

    def test_perspective_not_empty(self):
        self.assertGreater(len(PERSPECTIVE_PATTERNS), 0)

    def test_epistemic_humility_not_empty(self):
        self.assertGreater(len(EPISTEMIC_HUMILITY_PATTERNS), 0)

    def test_growth_markers_not_empty(self):
        self.assertGreater(len(GROWTH_MARKER_PATTERNS), 0)

    def test_all_patterns_compile(self):
        """Ensure all regex patterns are valid."""
        import re
        for patterns in [
            SELF_REFERENCE_PATTERNS,
            METACOGNITION_PATTERNS,
            PERSPECTIVE_PATTERNS,
            EPISTEMIC_HUMILITY_PATTERNS,
            GROWTH_MARKER_PATTERNS,
        ]:
            for p in patterns:
                re.compile(p)  # Should not raise


class TestEdgeCases(unittest.TestCase):
    """Test edge cases."""

    def test_single_word(self):
        wr = WriterReflexivity()
        result = wr.measure("I")
        self.assertEqual(result["reflexivity_index"], 0.0)

    def test_only_punctuation(self):
        wr = WriterReflexivity()
        result = wr.measure("...!!!")
        self.assertEqual(result["classification"], "absent")

    def test_very_long_text(self):
        wr = WriterReflexivity()
        text = "I think this is important. " * 100
        result = wr.measure(text)
        self.assertGreater(result["self_reference_density"], 0.0)

    def test_mixed_languages_ignored(self):
        wr = WriterReflexivity()
        text = "这是中文文本。I think this is important."
        result = wr.measure(text)
        self.assertGreaterEqual(result["reflexivity_index"], 0.0)

    def test_repeated_patterns_count_once(self):
        wr = WriterReflexivity()
        text = "I think I think I think."
        result = wr.measure_self_reference_density(text)
        # One sentence, should be 1.0
        self.assertEqual(result, 1.0)


if __name__ == "__main__":
    unittest.main()
