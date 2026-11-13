#!/usr/bin/env python3
"""Tests for writer_citation_density — 110 test cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_citation_density import (  # noqa: E402
    ATTRIBUTION_PHRASES,
    ATTRIBUTION_VERBS,
    BIBLIOGRAPHIC_PATTERNS,
    NAMED_SOURCE_PATTERNS,
    QUOTATION_PATTERNS,
    STATISTICAL_MARKERS,
    STATISTICAL_NUMBER_PATTERNS,
    WriterCitationDensity,
    _count_pattern_matches,
    _count_pattern_matches_case,
    _count_phrase_occurrences,
    _split_sentences,
    _tokenize,
)


# ── Initialization ───────────────────────────────────────────────────


class TestInit(unittest.TestCase):
    """Test WriterCitationDensity initialization."""

    def test_init_default(self):
        wcd = WriterCitationDensity()
        self.assertIsNotNone(wcd.quotation_patterns)
        self.assertIsNotNone(wcd.attribution_verbs)

    def test_init_sets_all_constants(self):
        wcd = WriterCitationDensity()
        self.assertEqual(wcd.quotation_patterns, QUOTATION_PATTERNS)
        self.assertEqual(wcd.attribution_phrases, ATTRIBUTION_PHRASES)
        self.assertEqual(wcd.attribution_verbs, ATTRIBUTION_VERBS)
        self.assertEqual(wcd.named_source_patterns, NAMED_SOURCE_PATTERNS)
        self.assertEqual(wcd.statistical_markers, STATISTICAL_MARKERS)
        self.assertEqual(wcd.statistical_number_patterns, STATISTICAL_NUMBER_PATTERNS)
        self.assertEqual(wcd.bibliographic_patterns, BIBLIOGRAPHIC_PATTERNS)

    def test_attribution_phrases_sorted_longest_first(self):
        lengths = [len(p) for p in ATTRIBUTION_PHRASES]
        self.assertEqual(lengths, sorted(lengths, reverse=True))

    def test_statistical_markers_sorted_longest_first(self):
        lengths = [len(m) for m in STATISTICAL_MARKERS]
        self.assertEqual(lengths, sorted(lengths, reverse=True))

    def test_bibliographic_patterns_are_strings(self):
        for pat in BIBLIOGRAPHIC_PATTERNS:
            self.assertIsInstance(pat, str)

    def test_quotation_patterns_are_strings(self):
        for pat in QUOTATION_PATTERNS:
            self.assertIsInstance(pat, str)

    def test_named_source_patterns_are_strings(self):
        for pat in NAMED_SOURCE_PATTERNS:
            self.assertIsInstance(pat, str)


# ── Helpers ──────────────────────────────────────────────────────────


class TestSplitSentences(unittest.TestCase):
    """Test _split_sentences helper."""

    def test_empty_string(self):
        self.assertEqual(_split_sentences(""), [])

    def test_single_sentence(self):
        result = _split_sentences("Hello world.")
        self.assertEqual(len(result), 1)

    def test_multiple_sentences(self):
        result = _split_sentences("Hello. World. How are you?")
        self.assertEqual(len(result), 3)

    def test_exclamation(self):
        result = _split_sentences("Wow! Amazing! Great!")
        self.assertEqual(len(result), 3)

    def test_question_mark(self):
        result = _split_sentences("What? Why? How?")
        self.assertEqual(len(result), 3)

    def test_trailing_whitespace(self):
        result = _split_sentences("Hello.  ")
        self.assertEqual(result, ["Hello."])

    def test_mixed_punctuation(self):
        result = _split_sentences("She said hi. He asked what? They left!")
        self.assertEqual(len(result), 3)


class TestTokenize(unittest.TestCase):
    """Test _tokenize helper."""

    def test_empty_string(self):
        self.assertEqual(_tokenize(""), [])

    def test_simple_text(self):
        result = _tokenize("Hello World")
        self.assertEqual(result, ["hello", "world"])

    def test_punctuation(self):
        result = _tokenize("She said, hello!")
        self.assertEqual("said" in result, True)

    def test_contractions(self):
        result = _tokenize("don't can't won't")
        self.assertTrue(any("'" in w for w in result))

    def test_numbers_excluded(self):
        result = _tokenize("test 42 hello")
        self.assertNotIn("42", result)


class TestCountPhraseOccurrences(unittest.TestCase):
    """Test _count_phrase_occurrences helper."""

    def test_no_match(self):
        self.assertEqual(_count_phrase_occurrences("hello world", ("xyz",)), 0)

    def test_single_match(self):
        self.assertEqual(_count_phrase_occurrences("according to Smith", ("according to",)), 1)

    def test_multiple_matches(self):
        text = "according to X and according to Y"
        self.assertEqual(_count_phrase_occurrences(text, ("according to",)), 2)

    def test_case_insensitive(self):
        self.assertEqual(_count_phrase_occurrences("According to", ("according to",)), 1)


class TestCountPatternMatches(unittest.TestCase):
    """Test _count_pattern_matches helper."""

    def test_no_match(self):
        self.assertEqual(_count_pattern_matches("hello", (r"\d+",)), 0)

    def test_single_match(self):
        self.assertEqual(_count_pattern_matches("42 things", (r"\d+",)), 1)

    def test_multiple_matches(self):
        self.assertEqual(_count_pattern_matches("42 and 7", (r"\d+",)), 2)


class TestCountPatternMatchesCase(unittest.TestCase):
    """Test _count_pattern_matches_case helper."""

    def test_preserves_case(self):
        self.assertEqual(_count_pattern_matches_case("Hello", (r"hello",)), 0)

    def test_matches_exact_case(self):
        self.assertEqual(_count_pattern_matches_case("Hello", (r"Hello",)), 1)

    def test_empty_text(self):
        self.assertEqual(_count_pattern_matches_case("", (r"Hello",)), 0)


# ── Dimension 1: Direct Quotation Rate ───────────────────────────────


class TestDirectQuotationRate(unittest.TestCase):
    """Test measure_direct_quotation_rate."""

    def setUp(self):
        self.wcd = WriterCitationDensity()

    def test_no_quotations(self):
        text = "The cat sat on the mat. The dog ran in the park."
        result = self.wcd.measure_direct_quotation_rate(text)
        self.assertEqual(result, 0.0)

    def test_single_double_quote(self):
        text = 'She said "hello" to everyone. Then she left.'
        result = self.wcd.measure_direct_quotation_rate(text)
        self.assertGreater(result, 0.0)

    def test_multiple_quotations(self):
        text = 'He said "goodbye" and she replied "farewell". They walked away.'
        result = self.wcd.measure_direct_quotation_rate(text)
        self.assertGreater(result, 0.0)

    def test_smart_quotes(self):
        text = 'She said \u201chello\u201d to everyone. Then she left.'
        result = self.wcd.measure_direct_quotation_rate(text)
        self.assertGreater(result, 0.0)

    def test_empty_text(self):
        result = self.wcd.measure_direct_quotation_rate("")
        self.assertEqual(result, 0.0)

    def test_max_capped_at_one(self):
        text = '"a" "b" "c" "d" "e" "f".'
        result = self.wcd.measure_direct_quotation_rate(text)
        self.assertLessEqual(result, 1.0)

    def test_short_single_quotes_ignored(self):
        text = "The cat napped. The dog slept outside."
        result = self.wcd.measure_direct_quotation_rate(text)
        self.assertEqual(result, 0.0)

    def test_em_dash_attribution(self):
        text = "——She spoke softly. Then she was gone."
        result = self.wcd.measure_direct_quotation_rate(text)
        self.assertGreater(result, 0.0)


# ── Dimension 2: Attribution Verb Rate ───────────────────────────────


class TestAttributionVerbRate(unittest.TestCase):
    """Test measure_attribution_verb_rate."""

    def setUp(self):
        self.wcd = WriterCitationDensity()

    def test_no_attribution(self):
        text = "The cat sat on the mat. The dog ran in the park."
        result = self.wcd.measure_attribution_verb_rate(text)
        self.assertEqual(result, 0.0)

    def test_single_attribution_phrase(self):
        text = "According to Smith, the results are significant. The study continues."
        result = self.wcd.measure_attribution_verb_rate(text)
        self.assertGreater(result, 0.0)

    def test_attribution_verb_says(self):
        text = "She says the results are clear. He says otherwise."
        result = self.wcd.measure_attribution_verb_rate(text)
        self.assertGreater(result, 0.0)

    def test_attribution_verb_argues(self):
        text = "Smith argues that the data is flawed. Jones contends otherwise."
        result = self.wcd.measure_attribution_verb_rate(text)
        self.assertGreater(result, 0.0)

    def test_multiple_verbs(self):
        text = "She claims X. He notes Y. They suggest Z. We observe W."
        result = self.wcd.measure_attribution_verb_rate(text)
        self.assertGreater(result, 0.0)

    def test_empty_text(self):
        result = self.wcd.measure_attribution_verb_rate("")
        self.assertEqual(result, 0.0)

    def test_points_out_phrase(self):
        text = "She points out the error. He pointed out the flaw."
        result = self.wcd.measure_attribution_verb_rate(text)
        self.assertGreater(result, 0.0)

    def test_in_the_words_of(self):
        text = "In the words of the founder, this changes everything. We proceed."
        result = self.wcd.measure_attribution_verb_rate(text)
        self.assertGreater(result, 0.0)

    def test_max_capped_at_one(self):
        text = "says says says says says says."
        result = self.wcd.measure_attribution_verb_rate(text)
        self.assertLessEqual(result, 1.0)


# ── Dimension 3: Named-Source Rate ───────────────────────────────────


class TestNamedSourceRate(unittest.TestCase):
    """Test measure_named_source_rate."""

    def setUp(self):
        self.wcd = WriterCitationDensity()

    def test_no_named_sources(self):
        text = "The cat sat on the mat. The dog ran in the park."
        result = self.wcd.measure_named_source_rate(text)
        self.assertEqual(result, 0.0)

    def test_author_year(self):
        text = "Smith (2023) found significant results. The study continues."
        result = self.wcd.measure_named_source_rate(text)
        self.assertGreater(result, 0.0)

    def test_et_al(self):
        text = "Johnson et al. reported similar findings. The experiment continues."
        result = self.wcd.measure_named_source_rate(text)
        self.assertGreater(result, 0.0)

    def test_ampersand_pair(self):
        text = "Williams & Chen observed the effect. The results were clear."
        result = self.wcd.measure_named_source_rate(text)
        self.assertGreater(result, 0.0)

    def test_according_to_name(self):
        text = "According to Brown, the effect is real. We tested it."
        result = self.wcd.measure_named_source_rate(text)
        self.assertGreater(result, 0.0)

    def test_empty_text(self):
        result = self.wcd.measure_named_source_rate("")
        self.assertEqual(result, 0.0)

    def test_multiple_sources(self):
        text = "Smith (2021) and Jones (2022) both confirmed it. Brown et al. agreed."
        result = self.wcd.measure_named_source_rate(text)
        self.assertGreater(result, 0.0)

    def test_as_smith_argues(self):
        text = "As Smith argues, the evidence is clear. Others disagree."
        result = self.wcd.measure_named_source_rate(text)
        self.assertGreater(result, 0.0)


# ── Dimension 4: Statistical Citation Rate ───────────────────────────


class TestStatisticalCitationRate(unittest.TestCase):
    """Test measure_statistical_citation_rate."""

    def setUp(self):
        self.wcd = WriterCitationDensity()

    def test_no_statistical(self):
        text = "The cat sat on the mat. The dog ran in the park."
        result = self.wcd.measure_statistical_citation_rate(text)
        self.assertEqual(result, 0.0)

    def test_percentage(self):
        text = "About 42% of participants showed improvement. The rest did not."
        result = self.wcd.measure_statistical_citation_rate(text)
        self.assertGreater(result, 0.0)

    def test_study_found(self):
        text = "A study found that sleep improves memory. The research continues."
        result = self.wcd.measure_statistical_citation_rate(text)
        self.assertGreater(result, 0.0)

    def test_p_value(self):
        text = "The effect was significant with p < 0.05. The results held."
        result = self.wcd.measure_statistical_citation_rate(text)
        self.assertGreater(result, 0.0)

    def test_meta_analysis(self):
        text = "A meta-analysis confirmed the trend. Further studies are needed."
        result = self.wcd.measure_statistical_citation_rate(text)
        self.assertGreater(result, 0.0)

    def test_research_shows(self):
        text = "Research shows that exercise helps. The data is compelling."
        result = self.wcd.measure_statistical_citation_rate(text)
        self.assertGreater(result, 0.0)

    def test_confidence_interval(self):
        text = "The 95% CI was [0.3, 0.7]. Results were robust."
        result = self.wcd.measure_statistical_citation_rate(text)
        self.assertGreater(result, 0.0)

    def test_empty_text(self):
        result = self.wcd.measure_statistical_citation_rate("")
        self.assertEqual(result, 0.0)

    def test_sample_size(self):
        text = "The study included 500 participants from three countries. Results varied."
        result = self.wcd.measure_statistical_citation_rate(text)
        self.assertGreater(result, 0.0)

    def test_correlation_coefficient(self):
        text = "The correlation was r = 0.85 between the variables. Significance held."
        result = self.wcd.measure_statistical_citation_rate(text)
        self.assertGreater(result, 0.0)

    def test_peer_reviewed(self):
        text = "The peer-reviewed study confirmed the hypothesis. Further work is needed."
        result = self.wcd.measure_statistical_citation_rate(text)
        self.assertGreater(result, 0.0)

    def test_max_capped_at_one(self):
        text = "42% 55% 67% 89% 12% 34% 56% 78% 90% 11%."
        result = self.wcd.measure_statistical_citation_rate(text)
        self.assertLessEqual(result, 1.0)


# ── Dimension 5: Bibliographic Marker Rate ───────────────────────────


class TestBibliographicMarkerRate(unittest.TestCase):
    """Test measure_bibliographic_marker_rate."""

    def setUp(self):
        self.wcd = WriterCitationDensity()

    def test_no_bibliographic(self):
        text = "The cat sat on the mat. The dog ran in the park."
        result = self.wcd.measure_bibliographic_marker_rate(text)
        self.assertEqual(result, 0.0)

    def test_numbered_reference(self):
        text = "The effect was confirmed [1]. Further studies agreed [2]."
        result = self.wcd.measure_bibliographic_marker_rate(text)
        self.assertGreater(result, 0.0)

    def test_range_reference(self):
        text = "Multiple studies confirmed this [1-4]. The consensus is clear."
        result = self.wcd.measure_bibliographic_marker_rate(text)
        self.assertGreater(result, 0.0)

    def test_parenthetical_author_year(self):
        text = "The effect was real (Smith, 2023). Others confirmed it."
        result = self.wcd.measure_bibliographic_marker_rate(text)
        self.assertGreater(result, 0.0)

    def test_et_al_parenthetical(self):
        text = "The trend was confirmed (Jones et al., 2022). Results held."
        result = self.wcd.measure_bibliographic_marker_rate(text)
        self.assertGreater(result, 0.0)

    def test_doi_reference(self):
        text = "See the original study doi: 10.1234/example. It was thorough."
        result = self.wcd.measure_bibliographic_marker_rate(text)
        self.assertGreater(result, 0.0)

    def test_ibid(self):
        text = "The same source confirms this (ibid.). Further details follow."
        result = self.wcd.measure_bibliographic_marker_rate(text)
        self.assertGreater(result, 0.0)

    def test_op_cit(self):
        text = "As previously noted (op. cit.), the effect holds. New data agrees."
        result = self.wcd.measure_bibliographic_marker_rate(text)
        self.assertGreater(result, 0.0)

    def test_empty_text(self):
        result = self.wcd.measure_bibliographic_marker_rate("")
        self.assertEqual(result, 0.0)

    def test_see_smith(self):
        text = "See Smith for details. The methodology was sound."
        result = self.wcd.measure_bibliographic_marker_rate(text)
        self.assertGreater(result, 0.0)

    def test_isbn(self):
        text = "The textbook ISBN 978-0-123456-78-9 covers this topic. It is thorough."
        result = self.wcd.measure_bibliographic_marker_rate(text)
        self.assertGreater(result, 0.0)

    def test_cf_reference(self):
        text = "The original finding (cf. Brown) was replicated. Results held."
        result = self.wcd.measure_bibliographic_marker_rate(text)
        self.assertGreater(result, 0.0)

    def test_max_capped_at_one(self):
        text = "[1] [2] [3] [4] [5] [6] [7] [8] [9] [10]."
        result = self.wcd.measure_bibliographic_marker_rate(text)
        self.assertLessEqual(result, 1.0)


# ── Composite Index ──────────────────────────────────────────────────


class TestCompositeIndex(unittest.TestCase):
    """Test compute_citation_density_index."""

    def setUp(self):
        self.wcd = WriterCitationDensity()

    def test_all_zeros(self):
        result = self.wcd.compute_citation_density_index(0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(result, 0.0)

    def test_all_ones(self):
        result = self.wcd.compute_citation_density_index(1.0, 1.0, 1.0, 1.0, 1.0)
        self.assertEqual(result, 1.0)

    def test_weighted_average(self):
        result = self.wcd.compute_citation_density_index(1.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.25)

    def test_attribution_only(self):
        result = self.wcd.compute_citation_density_index(0.0, 1.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.25)

    def test_named_source_only(self):
        result = self.wcd.compute_citation_density_index(0.0, 0.0, 1.0, 0.0, 0.0)
        self.assertAlmostEqual(result, 0.20)

    def test_statistical_only(self):
        result = self.wcd.compute_citation_density_index(0.0, 0.0, 0.0, 1.0, 0.0)
        self.assertAlmostEqual(result, 0.15)

    def test_bibliographic_only(self):
        result = self.wcd.compute_citation_density_index(0.0, 0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(result, 0.15)

    def test_clamped_above_one(self):
        result = self.wcd.compute_citation_density_index(2.0, 2.0, 2.0, 2.0, 2.0)
        self.assertLessEqual(result, 1.0)

    def test_clamped_below_zero(self):
        result = self.wcd.compute_citation_density_index(-1.0, -1.0, -1.0, -1.0, -1.0)
        self.assertGreaterEqual(result, 0.0)

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(0.25 + 0.25 + 0.20 + 0.15 + 0.15, 1.0)


# ── Classification ────────────────────────────────────────────────────


class TestClassification(unittest.TestCase):
    """Test classify method."""

    def test_uncited(self):
        self.assertEqual(WriterCitationDensity.classify(0.0), "uncited")
        self.assertEqual(WriterCitationDensity.classify(0.01), "uncited")
        self.assertEqual(WriterCitationDensity.classify(0.049), "uncited")

    def test_minimally_cited(self):
        self.assertEqual(WriterCitationDensity.classify(0.05), "minimally_cited")
        self.assertEqual(WriterCitationDensity.classify(0.10), "minimally_cited")
        self.assertEqual(WriterCitationDensity.classify(0.149), "minimally_cited")

    def test_moderately_cited(self):
        self.assertEqual(WriterCitationDensity.classify(0.15), "moderately_cited")
        self.assertEqual(WriterCitationDensity.classify(0.25), "moderately_cited")
        self.assertEqual(WriterCitationDensity.classify(0.349), "moderately_cited")

    def test_heavily_cited(self):
        self.assertEqual(WriterCitationDensity.classify(0.35), "heavily_cited")
        self.assertEqual(WriterCitationDensity.classify(0.45), "heavily_cited")
        self.assertEqual(WriterCitationDensity.classify(0.549), "heavily_cited")

    def test_saturated(self):
        self.assertEqual(WriterCitationDensity.classify(0.55), "saturated_with_citation")
        self.assertEqual(WriterCitationDensity.classify(0.80), "saturated_with_citation")
        self.assertEqual(WriterCitationDensity.classify(1.0), "saturated_with_citation")


# ── Measure (integration) ────────────────────────────────────────────


class TestMeasure(unittest.TestCase):
    """Test the main measure() method."""

    def setUp(self):
        self.wcd = WriterCitationDensity()

    def test_empty_text(self):
        result = self.wcd.measure("")
        self.assertEqual(result["citation_density_index"], 0.0)
        self.assertEqual(result["classification"], "uncited")

    def test_whitespace_only(self):
        result = self.wcd.measure("   \n  \t  ")
        self.assertEqual(result["citation_density_index"], 0.0)
        self.assertEqual(result["classification"], "uncited")

    def test_none_equivalent(self):
        result = self.wcd.measure("")
        self.assertIn("direct_quotation_rate", result)
        self.assertIn("attribution_verb_rate", result)
        self.assertIn("named_source_rate", result)
        self.assertIn("statistical_citation_rate", result)
        self.assertIn("bibliographic_marker_rate", result)
        self.assertIn("citation_density_index", result)
        self.assertIn("classification", result)

    def test_uncited_text(self):
        text = "The cat sat on the mat. The dog ran in the park. Birds flew overhead."
        result = self.wcd.measure(text)
        self.assertEqual(result["classification"], "uncited")
        self.assertAlmostEqual(result["citation_density_index"], 0.0)

    def test_citation_rich_text(self):
        text = (
            'According to Smith (2023), "the effect is real" [1]. '
            "A study found that 42% of participants improved (p < 0.05). "
            "Jones et al. confirmed these results. As Brown argues, the data "
            'shows a clear trend. "We were surprised," the authors wrote.'
        )
        result = self.wcd.measure(text)
        self.assertGreater(result["citation_density_index"], 0.0)
        self.assertNotEqual(result["classification"], "uncited")

    def test_all_dimensions_present(self):
        text = "Smith (2023) argues that 42% improved [1]. Jones et al. agree."
        result = self.wcd.measure(text)
        keys = set(result.keys())
        expected = {
            "direct_quotation_rate",
            "attribution_verb_rate",
            "named_source_rate",
            "statistical_citation_rate",
            "bibliographic_marker_rate",
            "citation_density_index",
            "classification",
        }
        self.assertEqual(keys, expected)

    def test_values_are_rounded(self):
        text = "According to Smith (2023), the effect is real. Others disagree."
        result = self.wcd.measure(text)
        for key in [
            "direct_quotation_rate",
            "attribution_verb_rate",
            "named_source_rate",
            "statistical_citation_rate",
            "bibliographic_marker_rate",
            "citation_density_index",
        ]:
            value = result[key]
            self.assertEqual(value, round(value, 4))

    def test_index_bounded(self):
        text = '"A" "B" "C" says says says Smith (2023) Smith (2024) 42% 55% [1] [2] [3].'
        result = self.wcd.measure(text)
        self.assertGreaterEqual(result["citation_density_index"], 0.0)
        self.assertLessEqual(result["citation_density_index"], 1.0)

    def test_single_sentence(self):
        text = "According to Smith (2023), 42% of subjects improved."
        result = self.wcd.measure(text)
        self.assertGreater(result["citation_density_index"], 0.0)


if __name__ == "__main__":
    unittest.main()
