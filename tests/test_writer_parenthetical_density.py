#!/usr/bin/env python3
"""Tests for writer_parenthetical_density — comprehensive test suite."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_parenthetical_density import (  # noqa: E402
    COMMA_APPOSITIVE_RE,
    COMMA_NOUN_APPOSITIVE_RE,
    DOUBLE_DASH_ASIDE_RE,
    EM_DASH_ASIDE_RE,
    EN_DASH_ASIDE_RE,
    ROUND_BRACKET_RE,
    SQUARE_BRACKET_RE,
    WriterParentheticalDensity,
    _count_matching,
    _count_words,
    _sentence_has_parenthetical,
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

    def test_numbers_only_not_counted(self):
        # tokens with no letter are not words
        self.assertEqual(_count_words("42 99"), 0)

    def test_mixed_number_word(self):
        self.assertEqual(_count_words("n=42 items"), 2)

    def test_parenthetical_text(self):
        self.assertEqual(_count_words("(like this)"), 2)


class TestCountMatching(unittest.TestCase):
    def test_empty_sentences(self):
        self.assertEqual(_count_matching([], ROUND_BRACKET_RE), 0)

    def test_no_matches(self):
        sentences = ["The cat sat on the mat.", "She walked home quietly."]
        self.assertEqual(_count_matching(sentences, ROUND_BRACKET_RE), 0)

    def test_all_match(self):
        sentences = [
            "The result (significant) was reported.",
            "The data (n=42) showed improvement.",
        ]
        count = _count_matching(sentences, ROUND_BRACKET_RE)
        self.assertEqual(count, 2)

    def test_partial_match(self):
        sentences = [
            "The cat sat on the mat.",
            "The result (significant) was reported.",
            "She walked home.",
        ]
        count = _count_matching(sentences, ROUND_BRACKET_RE)
        self.assertEqual(count, 1)


class TestSentenceHasParenthetical(unittest.TestCase):
    def test_no_parenthetical(self):
        self.assertFalse(_sentence_has_parenthetical("The cat sat on the mat."))

    def test_round_bracket(self):
        self.assertTrue(_sentence_has_parenthetical("The result (n=42) was significant."))

    def test_square_bracket(self):
        self.assertTrue(_sentence_has_parenthetical("He said it was [sic] reported."))

    def test_em_dash(self):
        self.assertTrue(_sentence_has_parenthetical("The result — surprisingly — was positive."))

    def test_comma_relative(self):
        self.assertTrue(_sentence_has_parenthetical("The committee, which met on Tuesday, approved it."))

    def test_plain_sentence(self):
        self.assertFalse(_sentence_has_parenthetical("She approved the budget yesterday."))


# ── Pattern tests ────────────────────────────────────────────────────


class TestRoundBracketPattern(unittest.TestCase):
    def test_simple(self):
        matches = ROUND_BRACKET_RE.findall("The result (significant) was reported.")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0], "(significant)")

    def test_multiple(self):
        matches = ROUND_BRACKET_RE.findall("The (first) and (second) results.")
        self.assertEqual(len(matches), 2)

    def test_none(self):
        matches = ROUND_BRACKET_RE.findall("No brackets here at all.")
        self.assertEqual(len(matches), 0)

    def test_nested_content(self):
        matches = ROUND_BRACKET_RE.findall("See (Smith, 2024, p. 42) for details.")
        self.assertEqual(len(matches), 1)

    def test_empty_brackets(self):
        matches = ROUND_BRACKET_RE.findall("Empty () brackets.")
        self.assertEqual(len(matches), 1)


class TestSquareBracketPattern(unittest.TestCase):
    def test_sic(self):
        matches = SQUARE_BRACKET_RE.findall("He said it was [sic] reported.")
        self.assertEqual(len(matches), 1)

    def test_citation(self):
        matches = SQUARE_BRACKET_RE.findall("As noted [1] in the paper.")
        self.assertEqual(len(matches), 1)

    def test_editorial(self):
        matches = SQUARE_BRACKET_RE.findall("The [former] president spoke.")
        self.assertEqual(len(matches), 1)

    def test_none(self):
        matches = SQUARE_BRACKET_RE.findall("No brackets here.")
        self.assertEqual(len(matches), 0)


class TestEmDashPattern(unittest.TestCase):
    def test_simple(self):
        matches = EM_DASH_ASIDE_RE.findall("The result — surprisingly — was positive.")
        self.assertEqual(len(matches), 1)

    def test_multiple(self):
        text = "He — tired — walked — slowly — home."
        # should find at least one pair
        matches = EM_DASH_ASIDE_RE.findall(text)
        self.assertGreaterEqual(len(matches), 1)

    def test_none(self):
        matches = EM_DASH_ASIDE_RE.findall("No dashes here at all.")
        self.assertEqual(len(matches), 0)


class TestEnDashPattern(unittest.TestCase):
    def test_spaced(self):
        matches = EN_DASH_ASIDE_RE.findall("He walked – slowly – home.")
        self.assertEqual(len(matches), 1)

    def test_none(self):
        matches = EN_DASH_ASIDE_RE.findall("No dashes here.")
        self.assertEqual(len(matches), 0)


class TestDoubleDashPattern(unittest.TestCase):
    def test_simple(self):
        matches = DOUBLE_DASH_ASIDE_RE.findall("The result -- surprisingly -- was positive.")
        self.assertEqual(len(matches), 1)

    def test_none(self):
        matches = DOUBLE_DASH_ASIDE_RE.findall("No dashes here.")
        self.assertEqual(len(matches), 0)


class TestCommaAppositivePattern(unittest.TestCase):
    def test_which_clause(self):
        matches = COMMA_APPOSITIVE_RE.findall("The committee, which met on Tuesday, approved it.")
        self.assertEqual(len(matches), 1)

    def test_who_clause(self):
        matches = COMMA_APPOSITIVE_RE.findall("The author, who won the prize, spoke tonight.")
        self.assertEqual(len(matches), 1)

    def test_where_clause(self):
        matches = COMMA_APPOSITIVE_RE.findall("The city, where I was born, has changed.")
        self.assertEqual(len(matches), 1)

    def test_none(self):
        matches = COMMA_APPOSITIVE_RE.findall("The restrictive clause that follows is essential.")
        self.assertEqual(len(matches), 0)


class TestCommaNounAppositivePattern(unittest.TestCase):
    def test_appositive(self):
        matches = COMMA_NOUN_APPOSITIVE_RE.findall(
            "The committee, a group of experts, decided."
        )
        self.assertEqual(len(matches), 1)

    def test_none(self):
        matches = COMMA_NOUN_APPOSITIVE_RE.findall("She walked to the store.")
        self.assertEqual(len(matches), 0)


# ── WriterParentheticalDensity class tests ──────────────────────────


class TestBracketRate(unittest.TestCase):
    def test_empty_text(self):
        w = WriterParentheticalDensity("")
        self.assertEqual(w.bracket_rate, 0.0)

    def test_no_brackets(self):
        w = WriterParentheticalDensity("The cat sat on the mat. She walked home.")
        self.assertEqual(w.bracket_rate, 0.0)

    def test_one_round_bracket(self):
        w = WriterParentheticalDensity("The result (significant) was reported.")
        self.assertGreater(w.bracket_rate, 0.0)

    def test_multiple_brackets(self):
        w = WriterParentheticalDensity(
            "The (first) result. The [second] finding. The (third) data."
        )
        self.assertGreater(w.bracket_rate, 50.0)

    def test_rate_scales_with_sentences(self):
        text = "One (here). Two. Three. Four (there). Five. Six."
        w = WriterParentheticalDensity(text)
        # 2 brackets in 6 sentences = ~33.3 per 100
        self.assertAlmostEqual(w.bracket_rate, 2 / 6 * 100, places=0)


class TestEmDashAsideRate(unittest.TestCase):
    def test_empty(self):
        w = WriterParentheticalDensity("")
        self.assertEqual(w.em_dash_aside_rate, 0.0)

    def test_no_dashes(self):
        w = WriterParentheticalDensity("Simple sentence here. Another one.")
        self.assertEqual(w.em_dash_aside_rate, 0.0)

    def test_one_em_dash_aside(self):
        w = WriterParentheticalDensity("The result — surprisingly — was positive.")
        self.assertGreater(w.em_dash_aside_rate, 0.0)


class TestCommaAppositiveRate(unittest.TestCase):
    def test_empty(self):
        w = WriterParentheticalDensity("")
        self.assertEqual(w.comma_appositive_rate, 0.0)

    def test_no_appositives(self):
        w = WriterParentheticalDensity("She walked to the store. He ran home.")
        self.assertEqual(w.comma_appositive_rate, 0.0)

    def test_one_relative_clause(self):
        w = WriterParentheticalDensity(
            "The committee, which met on Tuesday, approved the budget."
        )
        self.assertGreater(w.comma_appositive_rate, 0.0)


class TestNestedDepth(unittest.TestCase):
    def test_empty(self):
        w = WriterParentheticalDensity("")
        self.assertEqual(w.nested_depth, 0)

    def test_no_nesting(self):
        w = WriterParentheticalDensity("No brackets at all here.")
        self.assertEqual(w.nested_depth, 0)

    def test_depth_one(self):
        w = WriterParentheticalDensity("The result (significant) was reported.")
        self.assertEqual(w.nested_depth, 1)

    def test_depth_two(self):
        w = WriterParentheticalDensity("The (outer (inner) outer) text.")
        self.assertEqual(w.nested_depth, 2)

    def test_depth_three(self):
        w = WriterParentheticalDensity("A (B [C (D) C] B) A.")
        self.assertEqual(w.nested_depth, 3)

    def test_unbalanced_close(self):
        # Extra close should not go negative
        w = WriterParentheticalDensity("Text ) extra close.")
        self.assertEqual(w.nested_depth, 0)

    def test_mixed_brackets(self):
        w = WriterParentheticalDensity("A (B [C] B) end.")
        self.assertEqual(w.nested_depth, 2)


class TestParentheticalWordShare(unittest.TestCase):
    def test_empty(self):
        w = WriterParentheticalDensity("")
        self.assertEqual(w.parenthetical_word_share, 0.0)

    def test_no_parentheticals(self):
        w = WriterParentheticalDensity("The cat sat on the mat.")
        self.assertEqual(w.parenthetical_word_share, 0.0)

    def test_some_parenthetical(self):
        text = "The result (very significant) was reported today."
        w = WriterParentheticalDensity(text)
        self.assertGreater(w.parenthetical_word_share, 0.0)
        self.assertLess(w.parenthetical_word_share, 1.0)

    def test_all_parenthetical(self):
        # Everything in brackets
        text = "(all words here)"
        w = WriterParentheticalDensity(text)
        self.assertAlmostEqual(w.parenthetical_word_share, 1.0, places=1)

    def test_share_capped_at_one(self):
        # Edge case: should never exceed 1.0
        w = WriterParentheticalDensity("(one) (two) (three)")
        self.assertLessEqual(w.parenthetical_word_share, 1.0)


class TestInterruptionRatio(unittest.TestCase):
    def test_empty(self):
        w = WriterParentheticalDensity("")
        self.assertEqual(w.interruption_ratio, 0.0)

    def test_no_interruptions(self):
        w = WriterParentheticalDensity("Simple sentence. Another simple one.")
        self.assertEqual(w.interruption_ratio, 0.0)

    def test_all_interrupted(self):
        text = "The (first) one. The [second] one. The — third — one."
        w = WriterParentheticalDensity(text)
        self.assertEqual(w.interruption_ratio, 1.0)

    def test_half_interrupted(self):
        text = "One (here). Two plain. Three (also). Four plain."
        w = WriterParentheticalDensity(text)
        self.assertAlmostEqual(w.interruption_ratio, 0.5, places=1)


class TestParentheticalDensityIndex(unittest.TestCase):
    def test_empty(self):
        w = WriterParentheticalDensity("")
        self.assertEqual(w.parenthetical_density_index, 0.0)

    def test_plain_text(self):
        text = "The cat sat on the mat. She walked to the store. He ran home."
        w = WriterParentheticalDensity(text)
        self.assertLess(w.parenthetical_density_index, 0.15)

    def test_heavily_parenthetical(self):
        text = (
            "The (first) result — surprisingly — was (very) significant. "
            "The committee, which met on Tuesday, approved [unanimously] the budget. "
            "Every (single) sentence — without exception — contained (at least) one aside. "
            "The (nested (deeply) nested) structure was [see appendix] remarkable."
        )
        w = WriterParentheticalDensity(text)
        self.assertGreater(w.parenthetical_density_index, 0.15)

    def test_index_range(self):
        texts = [
            "",
            "Simple.",
            "The (result) was — very — [sic] significant.",
            "A (B [C (D) C] B) text — with — asides, which were many, everywhere.",
        ]
        for text in texts:
            w = WriterParentheticalDensity(text)
            idx = w.parenthetical_density_index
            self.assertGreaterEqual(idx, 0.0, f"Index {idx} < 0 for: {text}")
            self.assertLessEqual(idx, 1.0, f"Index {idx} > 1 for: {text}")


class TestClassification(unittest.TestCase):
    def test_unadorned(self):
        w = WriterParentheticalDensity("The cat sat on the mat. She walked home.")
        self.assertEqual(w.classification, "unadorned")

    def test_empty_is_unadorned(self):
        w = WriterParentheticalDensity("")
        self.assertEqual(w.classification, "unadorned")

    def test_classification_is_string(self):
        w = WriterParentheticalDensity("Some (text) here.")
        self.assertIsInstance(w.classification, str)

    def test_valid_classifications(self):
        valid = {
            "unadorned",
            "lightly_parenthetical",
            "moderately_parenthetical",
            "heavily_parenthetical",
            "recursively_asided",
        }
        texts = [
            "Simple text.",
            "Some (brackets) here and [there].",
            "The — dramatic — aside, which was long, appeared often (very often).",
            "A (B [C (D) E] F) deeply — nested — text, which had, a group of, many asides [1] [2] [3].",
        ]
        for text in texts:
            w = WriterParentheticalDensity(text)
            self.assertIn(w.classification, valid, f"Invalid class for: {text}")


class TestAsDict(unittest.TestCase):
    def test_keys(self):
        w = WriterParentheticalDensity("The (result) was reported.")
        d = w.as_dict()
        expected_keys = {
            "bracket_rate",
            "em_dash_aside_rate",
            "comma_appositive_rate",
            "nested_depth",
            "parenthetical_word_share",
            "interruption_ratio",
            "parenthetical_density_index",
            "classification",
            "n_sentences",
            "n_words",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    def test_values_are_numeric(self):
        w = WriterParentheticalDensity("The (result) — surprisingly — was [sic] noted.")
        d = w.as_dict()
        for key in [
            "bracket_rate",
            "em_dash_aside_rate",
            "comma_appositive_rate",
            "parenthetical_word_share",
            "interruption_ratio",
            "parenthetical_density_index",
        ]:
            self.assertIsInstance(d[key], (int, float), f"{key} not numeric")

    def test_classification_is_string(self):
        w = WriterParentheticalDensity("Text.")
        d = w.as_dict()
        self.assertIsInstance(d["classification"], str)

    def test_nested_depth_is_int(self):
        w = WriterParentheticalDensity("(nested [deep])")
        d = w.as_dict()
        self.assertIsInstance(d["nested_depth"], int)

    def test_n_sentences_positive(self):
        w = WriterParentheticalDensity("One. Two. Three.")
        d = w.as_dict()
        self.assertEqual(d["n_sentences"], 3)

    def test_empty_dict(self):
        w = WriterParentheticalDensity("")
        d = w.as_dict()
        self.assertEqual(d["n_sentences"], 0)
        self.assertEqual(d["n_words"], 0)
        self.assertEqual(d["classification"], "unadorned")


class TestAnalyseFunction(unittest.TestCase):
    def test_returns_dict(self):
        result = analyse("The (result) was reported.")
        self.assertIsInstance(result, dict)

    def test_empty(self):
        result = analyse("")
        self.assertEqual(result["parenthetical_density_index"], 0.0)
        self.assertEqual(result["classification"], "unadorned")

    def test_matches_class(self):
        text = "The (result) — surprisingly — was [sic] noted, which was unexpected."
        a = analyse(text)
        w = WriterParentheticalDensity(text)
        self.assertAlmostEqual(a["bracket_rate"], w.bracket_rate, places=3)
        self.assertAlmostEqual(
            a["parenthetical_density_index"], w.parenthetical_density_index, places=3
        )
        self.assertEqual(a["classification"], w.classification)


# ── Orthogonality tests ─────────────────────────────────────────────


class TestOrthogonality(unittest.TestCase):
    """Verify that parenthetical density is independent of other properties."""

    def test_long_sentences_no_parentheticals(self):
        """Long sentences don't imply parentheticals."""
        text = (
            "The extraordinarily long and complex sentence that wound through "
            "many subordinate clauses and prepositional phrases without ever "
            "using a single bracket or dash was finally complete."
        )
        w = WriterParentheticalDensity(text)
        self.assertEqual(w.bracket_rate, 0.0)
        self.assertEqual(w.em_dash_aside_rate, 0.0)

    def test_short_sentences_with_parentheticals(self):
        """Short sentences can be heavily parenthetical."""
        text = "The (small) cat."
        w = WriterParentheticalDensity(text)
        self.assertGreater(w.bracket_rate, 0.0)

    def test_parentheticals_without_complexity(self):
        """Parentheticals don't imply complex vocabulary."""
        text = "The (big) dog (ran) fast."
        w = WriterParentheticalDensity(text)
        self.assertGreater(w.bracket_rate, 0.0)

    def test_complex_without_parentheticals(self):
        """Complex text doesn't need parentheticals."""
        text = (
            "The juxtaposition of contradictory epistemological frameworks "
            "necessitates a thorough reevaluation of foundational assumptions."
        )
        w = WriterParentheticalDensity(text)
        self.assertEqual(w.bracket_rate, 0.0)
        self.assertEqual(w.em_dash_aside_rate, 0.0)


# ── Edge cases ──────────────────────────────────────────────────────


class TestEdgeCases(unittest.TestCase):
    def test_single_word(self):
        w = WriterParentheticalDensity("hello")
        self.assertEqual(w.parenthetical_density_index, 0.0)

    def test_only_punctuation(self):
        w = WriterParentheticalDensity(". ! ?")
        self.assertEqual(w.parenthetical_density_index, 0.0)

    def test_only_brackets(self):
        w = WriterParentheticalDensity("(())")
        self.assertEqual(w.nested_depth, 2)

    def test_mismatched_brackets(self):
        # Should not crash
        w = WriterParentheticalDensity("(unmatched [brackets)")
        self.assertGreaterEqual(w.nested_depth, 0)

    def test_very_long_text(self):
        text = "The (result) was reported. " * 100
        w = WriterParentheticalDensity(text)
        self.assertGreater(w.bracket_rate, 0.0)
        self.assertLessEqual(w.parenthetical_density_index, 1.0)

    def test_unicode_text(self):
        w = WriterParentheticalDensity("Le résultat (significatif) était rapporté.")
        self.assertGreater(w.bracket_rate, 0.0)

    def test_numbers_in_brackets(self):
        w = WriterParentheticalDensity("See [1] and [2] and [3].")
        self.assertEqual(w.bracket_rate, 300.0)  # 3 in 1 sentence = 300/100

    def test_multiple_dashes_in_sentence(self):
        text = "He — tired — and — hungry — walked home."
        w = WriterParentheticalDensity(text)
        self.assertGreater(w.em_dash_aside_rate, 0.0)

    def test_newlines_between_sentences(self):
        text = "First (one).\nSecond (two).\nThird (three)."
        w = WriterParentheticalDensity(text)
        self.assertEqual(w.interruption_ratio, 1.0)


# ── Integration / realistic texts ───────────────────────────────────


class TestRealisticTexts(unittest.TestCase):
    def test_academic_prose(self):
        text = (
            "The results (see Table 3) indicate a significant effect. "
            "The sample (n=142), which was drawn from three universities, "
            "showed consistent patterns across all conditions. "
            "Previous work [Smith, 2023] has documented similar findings."
        )
        w = WriterParentheticalDensity(text)
        self.assertGreater(w.bracket_rate, 50.0)
        self.assertGreater(w.parenthetical_word_share, 0.05)
        self.assertIn(w.classification, [
            "moderately_parenthetical",
            "heavily_parenthetical",
        ])

    def test_narrative_prose(self):
        text = (
            "She walked to the door and opened it slowly. "
            "The hallway was dark and smelled of old wood. "
            "She could hear footsteps somewhere above her."
        )
        w = WriterParentheticalDensity(text)
        self.assertEqual(w.bracket_rate, 0.0)
        self.assertEqual(w.em_dash_aside_rate, 0.0)
        self.assertEqual(w.classification, "unadorned")

    def test_essayistic_prose(self):
        text = (
            "The argument — which had been building since the opening "
            "paragraph — finally arrived at its conclusion. "
            "The evidence, which was overwhelming by this point, "
            "left little room for dissent. "
            "And yet — and this is the crucial point — the opposition "
            "remained unmoved."
        )
        w = WriterParentheticalDensity(text)
        self.assertGreater(w.em_dash_aside_rate, 0.0)
        self.assertGreater(w.comma_appositive_rate, 0.0)

    def test_technical_documentation(self):
        text = (
            "The function (see API reference) accepts a string parameter. "
            "Return values [deprecated] are documented in the changelog. "
            "The method, which was added in v2.0, handles edge cases."
        )
        w = WriterParentheticalDensity(text)
        self.assertGreater(w.bracket_rate, 0.0)
        d = w.as_dict()
        self.assertIn(d["classification"], [
            "lightly_parenthetical",
            "moderately_parenthetical",
            "heavily_parenthetical",
        ])

    def test_legal_text_high_density(self):
        text = (
            "The party (hereinafter 'the Licensor') grants to the "
            "recipient (hereinafter 'the Licensee') a non-exclusive "
            "license (the 'License'). The License, which is subject "
            "to the terms (see Appendix A), shall remain in effect "
            "[unless terminated earlier] as set forth (in Section 7)."
        )
        w = WriterParentheticalDensity(text)
        self.assertGreater(w.bracket_rate, 100.0)
        self.assertGreater(w.parenthetical_word_share, 0.10)


# ── Determinism tests ───────────────────────────────────────────────


class TestDeterminism(unittest.TestCase):
    def test_same_input_same_output(self):
        text = "The (result) — surprisingly — was [sic] noted, which was unexpected."
        a = analyse(text)
        b = analyse(text)
        self.assertEqual(a, b)

    def test_different_input_different_output(self):
        a = analyse("Simple text with no asides.")
        b = analyse("The (complex) text — with — many [asides], which were numerous.")
        self.assertNotEqual(a["parenthetical_density_index"], b["parenthetical_density_index"])


# ── Boundary tests ──────────────────────────────────────────────────


class TestBoundaries(unittest.TestCase):
    def test_index_never_negative(self):
        texts = ["", "x", "()", "[]", "— —", ", which ,"]
        for text in texts:
            w = WriterParentheticalDensity(text)
            self.assertGreaterEqual(w.parenthetical_density_index, 0.0)

    def test_index_never_exceeds_one(self):
        # Maximum parenthetical text
        text = "(a) " * 50
        w = WriterParentheticalDensity(text)
        self.assertLessEqual(w.parenthetical_density_index, 1.0)

    def test_word_share_never_exceeds_one(self):
        text = "(everything is in brackets) and nothing else"
        w = WriterParentheticalDensity(text)
        self.assertLessEqual(w.parenthetical_word_share, 1.0)

    def test_interruption_ratio_range(self):
        texts = [
            "No asides here. Plain text.",
            "One (aside). Two (asides). Three (asides).",
        ]
        for text in texts:
            w = WriterParentheticalDensity(text)
            self.assertGreaterEqual(w.interruption_ratio, 0.0)
            self.assertLessEqual(w.interruption_ratio, 1.0)


if __name__ == "__main__":
    unittest.main()
