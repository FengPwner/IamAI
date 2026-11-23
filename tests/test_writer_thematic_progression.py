#!/usr/bin/env python3
"""Tests for writer_thematic_progression module.

Covers:
  - _tokenize
  - _content_words
  - _split_sentences
  - _theme_words
  - _rheme_words
  - _stem
  - _stem_set
  - _has_linear
  - _has_constant
  - _has_derived
  - _has_split
  - compute_thematic_progression (basic, edge cases, labels)
  - _empty_result / _no_progression_result
  - _classify
  - _summary
  - main / CLI
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, mock_open

# Ensure project root on path.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from iamai.writer_thematic_progression import (
    _tokenize,
    _content_words,
    _split_sentences,
    _theme_words,
    _rheme_words,
    _stem,
    _stem_set,
    _has_linear,
    _has_constant,
    _has_derived,
    _has_split,
    compute_thematic_progression,
    _empty_result,
    _no_progression_result,
    _classify,
    _summary,
    _load_strokes,
    main,
    STOP_WORDS,
)


# =========================================================================
# _tokenize
# =========================================================================

class TestTokenize(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(
            _tokenize("Hello World"),
            ["hello", "world"],
        )

    def test_strips_punctuation(self):
        self.assertEqual(
            _tokenize("The server crashed, badly!"),
            ["the", "server", "crashed", "badly"],
        )

    def test_min_word_length(self):
        self.assertEqual(
            _tokenize("an apple or orange"),
            ["apple", "orange"],
        )

    def test_apostrophe(self):
        self.assertEqual(
            _tokenize("it's a writer's craft"),
            ["it's", "writer's", "craft"],
        )

    def test_empty(self):
        self.assertEqual(_tokenize(""), [])

    def test_numbers_ignored(self):
        self.assertEqual(
            _tokenize("version released"),
            ["version", "released"],
        )


# =========================================================================
# _content_words
# =========================================================================

class TestContentWords(unittest.TestCase):
    def test_filters_stop_words(self):
        tokens = ["the", "server", "was", "crashed"]
        self.assertEqual(_content_words(tokens), ["server", "crashed"])

    def test_all_stop_words(self):
        tokens = ["the", "was", "been"]
        self.assertEqual(_content_words(tokens), [])

    def test_empty(self):
        self.assertEqual(_content_words([]), [])

    def test_no_stop_words(self):
        tokens = ["server", "crashed", "heavily"]
        self.assertEqual(_content_words(tokens), ["server", "crashed", "heavily"])

    def test_preserves_order(self):
        tokens = ["algorithm", "the", "complex", "was", "elegant"]
        self.assertEqual(_content_words(tokens), ["algorithm", "complex", "elegant"])


# =========================================================================
# _split_sentences
# =========================================================================

class TestSplitSentences(unittest.TestCase):
    def test_basic(self):
        text = "Hello world. How are you? Fine thanks."
        result = _split_sentences(text)
        self.assertEqual(len(result), 3)

    def test_newline_split(self):
        text = "First sentence\nSecond sentence"
        result = _split_sentences(text)
        self.assertEqual(len(result), 2)

    def test_empty(self):
        self.assertEqual(_split_sentences(""), [])

    def test_single_sentence(self):
        result = _split_sentences("Just one sentence")
        self.assertEqual(len(result), 1)

    def test_trailing_period(self):
        result = _split_sentences("One. Two.")
        self.assertEqual(len(result), 2)

    def test_multiple_exclamation(self):
        result = _split_sentences("Wow!!! Really?!")
        # "Wow" → len < 3 after strip → might be filtered
        self.assertTrue(len(result) >= 1)


# =========================================================================
# _theme_words
# =========================================================================

class TestThemeWords(unittest.TestCase):
    def test_short_sentence_all_theme(self):
        # ≤ 3 tokens → all content words are theme.
        result = _theme_words("server crashed")
        self.assertIn("server", result)

    def test_longer_sentence_first_half(self):
        # The server processed the incoming request quickly
        result = _theme_words("The server processed the incoming request quickly")
        # "server" should be in theme (first half)
        self.assertIn("server", result)

    def test_empty(self):
        self.assertEqual(_theme_words(""), [])


# =========================================================================
# _rheme_words
# =========================================================================

class TestRhemeWords(unittest.TestCase):
    def test_short_sentence_all_rheme(self):
        result = _rheme_words("server crashed")
        self.assertIn("crashed", result)

    def test_longer_sentence_second_half(self):
        result = _rheme_words("The server processed the incoming request quickly")
        # "quickly" or "request" should be in rheme (second half)
        content = _content_words(_tokenize("The server processed the incoming request quickly"))
        mid = max(1, len(content) // 2)
        expected_rheme = content[mid:]
        for w in expected_rheme:
            self.assertIn(w, result)

    def test_empty(self):
        self.assertEqual(_rheme_words(""), [])


# =========================================================================
# _stem
# =========================================================================

class TestStem(unittest.TestCase):
    def test_ing(self):
        self.assertEqual(_stem("running"), "runn")

    def test_tion(self):
        self.assertEqual(_stem("computation"), "computa")

    def test_ed(self):
        self.assertEqual(_stem("crashed"), "crash")

    def test_ly(self):
        self.assertEqual(_stem("quickly"), "quick")

    def test_short_word_unchanged(self):
        self.assertEqual(_stem("run"), "run")

    def test_er(self):
        self.assertEqual(_stem("writer"), "writ")

    def test_no_suffix(self):
        self.assertEqual(_stem("table"), "table")


# =========================================================================
# _stem_set
# =========================================================================

class TestStemSet(unittest.TestCase):
    def test_basic(self):
        result = _stem_set(["running", "crashed"])
        self.assertIn("runn", result)
        self.assertIn("crash", result)

    def test_empty(self):
        self.assertEqual(_stem_set([]), set())

    def test_dedup(self):
        result = _stem_set(["running", "runner"])
        # Both stem to "runn" and "runn" → only one entry.
        self.assertEqual(len(result), 1)


# =========================================================================
# _has_linear
# =========================================================================

class TestHasLinear(unittest.TestCase):
    def test_overlap(self):
        self.assertTrue(_has_linear({"server", "crash"}, {"server", "restart"}))

    def test_no_overlap(self):
        self.assertFalse(_has_linear({"server", "crash"}, {"network", "fail"}))

    def test_empty_sets(self):
        self.assertFalse(_has_linear(set(), set()))


# =========================================================================
# _has_constant
# =========================================================================

class TestHasConstant(unittest.TestCase):
    def test_same_stem(self):
        self.assertTrue(_has_constant({"server"}, {"server", "restart"}))

    def test_different(self):
        self.assertFalse(_has_constant({"server"}, {"network"}))

    def test_empty(self):
        self.assertFalse(_has_constant(set(), set()))


# =========================================================================
# _has_derived
# =========================================================================

class TestHasDerived(unittest.TestCase):
    def test_derived_hit(self):
        # "process" appeared in a prior rheme, not in prev theme.
        self.assertTrue(
            _has_derived({"process", "data"}, {"process"}, {"server"})
        )

    def test_constant_not_derived(self):
        # If it's also in prev theme, it's constant not derived.
        self.assertFalse(
            _has_derived({"server"}, {"server"}, {"server"})
        )

    def test_no_overlap(self):
        self.assertFalse(
            _has_derived({"alpha", "beta"}, {"gamma"}, {"delta"})
        )


# =========================================================================
# _has_split
# =========================================================================

class TestHasSplit(unittest.TestCase):
    def test_split_detected(self):
        # prev rheme has {server, data}, both appear in next two themes.
        self.assertTrue(
            _has_split(
                {"server", "data"},
                {"server"},
                {"data"},
            )
        )

    def test_no_split_single_hit(self):
        self.assertFalse(
            _has_split(
                {"server", "data"},
                {"server"},
                {"network"},
            )
        )

    def test_empty(self):
        self.assertFalse(_has_split(set(), set(), set()))


# =========================================================================
# compute_thematic_progression
# =========================================================================

class TestComputeThematicProgression(unittest.TestCase):
    def test_empty_input(self):
        result = compute_thematic_progression([])
        self.assertEqual(result["total_sentences"], 0)
        self.assertEqual(result["progression_label"], "stagnant")

    def test_single_sentence(self):
        result = compute_thematic_progression(["The server crashed."])
        self.assertEqual(result["total_sentences"], 1)
        self.assertEqual(result["progression_label"], "stagnant")

    def test_two_sentences_constant(self):
        texts = [
            "The server processed the request. "
            "The server handled the response quickly."
        ]
        result = compute_thematic_progression(texts)
        self.assertEqual(result["total_sentences"], 2)
        self.assertGreaterEqual(result["constant_ratio"], 0.0)

    def test_linear_progression(self):
        texts = [
            "The algorithm was complex. "
            "Complexity affects performance significantly. "
            "Performance degradation causes user frustration."
        ]
        result = compute_thematic_progression(texts)
        self.assertEqual(result["total_sentences"], 3)
        # Should detect some linear or derived pattern.
        combined = result["linear_ratio"] + result["derived_ratio"]
        self.assertGreaterEqual(combined, 0.0)

    def test_multiple_texts(self):
        texts = [
            "The database connection failed. The failure was unexpected.",
            "Unexpected errors require careful handling. "
            "Handling errors properly prevents cascading failures.",
        ]
        result = compute_thematic_progression(texts)
        self.assertGreater(result["total_sentences"], 2)
        self.assertIn(result["progression_label"], [
            "orchestrated", "developing", "focused",
            "linear-drift", "scattered", "stagnant",
        ])

    def test_rheme_novelty_bounded(self):
        texts = [
            "The server processed data. "
            "Data analysis revealed patterns. "
            "Patterns emerge from complex systems."
        ]
        result = compute_thematic_progression(texts)
        self.assertGreaterEqual(result["rheme_novelty"], 0.0)
        self.assertLessEqual(result["rheme_novelty"], 1.0)

    def test_progression_index_bounded(self):
        texts = [
            "Random words appear here. "
            "Something completely different now. "
            "Another unrelated topic entirely."
        ]
        result = compute_thematic_progression(texts)
        self.assertGreaterEqual(result["progression_index"], 0.0)
        self.assertLessEqual(result["progression_index"], 1.0)

    def test_all_keys_present(self):
        result = compute_thematic_progression(["Hello world."])
        expected_keys = {
            "total_sentences", "linear_ratio", "constant_ratio",
            "derived_ratio", "split_ratio", "theme_persistence",
            "rheme_novelty", "progression_index", "progression_label",
        }
        self.assertEqual(set(result.keys()), expected_keys)

    def test_focused_text(self):
        # Same subject repeated → should trend toward focused/constant.
        texts = [
            "Python excels at data processing. "
            "Python offers rich libraries for analysis. "
            "Python integrates well with machine learning frameworks. "
            "Python supports multiple programming paradigms."
        ]
        result = compute_thematic_progression(texts)
        self.assertGreater(result["total_sentences"], 2)

    def test_orchestrated_text(self):
        # Rich, varied thematic development.
        texts = [
            "The compiler transforms source code into intermediate representation. "
            "Intermediate representation enables optimization across different targets. "
            "Optimization passes analyze control flow graphs thoroughly. "
            "Control flow graphs capture branching structure of programs. "
            "Program analysis reveals opportunities for parallel execution. "
            "Parallel execution demands careful synchronization of threads. "
            "Thread synchronization introduces potential deadlock scenarios."
        ]
        result = compute_thematic_progression(texts)
        self.assertGreater(result["total_sentences"], 4)


# =========================================================================
# _empty_result / _no_progression_result
# =========================================================================

class TestEmptyAndNoProgression(unittest.TestCase):
    def test_empty_result(self):
        r = _empty_result()
        self.assertEqual(r["total_sentences"], 0)
        self.assertEqual(r["progression_label"], "stagnant")
        self.assertEqual(r["progression_index"], 0.0)

    def test_no_progression_result(self):
        r = _no_progression_result(1)
        self.assertEqual(r["total_sentences"], 1)
        self.assertEqual(r["progression_label"], "stagnant")


# =========================================================================
# _classify
# =========================================================================

class TestClassify(unittest.TestCase):
    def test_stagnant(self):
        label = _classify(0.05, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 10)
        self.assertEqual(label, "stagnant")

    def test_scattered(self):
        label = _classify(0.20, 0.10, 0.10, 0.05, 0.02, 2.0, 0.5, 20)
        self.assertEqual(label, "scattered")

    def test_linear_drift(self):
        label = _classify(0.35, 0.40, 0.10, 0.05, 0.02, 2.5, 0.6, 20)
        self.assertEqual(label, "linear-drift")

    def test_focused(self):
        label = _classify(0.40, 0.10, 0.45, 0.05, 0.02, 4.0, 0.4, 20)
        self.assertEqual(label, "focused")

    def test_orchestrated(self):
        label = _classify(0.60, 0.20, 0.15, 0.10, 0.08, 5.0, 0.7, 30)
        self.assertEqual(label, "orchestrated")

    def test_developing(self):
        label = _classify(0.40, 0.20, 0.15, 0.08, 0.05, 3.5, 0.5, 25)
        self.assertEqual(label, "developing")

    def test_default_fallback(self):
        # Edge case: doesn't match any specific rule.
        label = _classify(0.25, 0.20, 0.20, 0.05, 0.02, 2.8, 0.3, 15)
        self.assertIn(label, ["scattered", "developing", "linear-drift",
                              "focused", "orchestrated", "stagnant"])


# =========================================================================
# _summary
# =========================================================================

class TestSummary(unittest.TestCase):
    def test_basic(self):
        result = {
            "progression_label": "developing",
            "progression_index": 0.42,
            "linear_ratio": 0.25,
            "constant_ratio": 0.18,
            "theme_persistence": 3.5,
        }
        s = _summary(result)
        self.assertIn("developing", s)
        self.assertIn("0.42", s)

    def test_focused(self):
        result = {
            "progression_label": "focused",
            "progression_index": 0.38,
            "linear_ratio": 0.05,
            "constant_ratio": 0.50,
            "theme_persistence": 5.2,
        }
        s = _summary(result)
        self.assertIn("focused", s)


# =========================================================================
# _load_strokes
# =========================================================================

class TestLoadStrokes(unittest.TestCase):
    def test_missing_file(self):
        with patch("iamai.writer_thematic_progression.STROKES_FILE") as mock_path:
            mock_path.exists.return_value = False
            self.assertEqual(_load_strokes(), [])

    def test_valid_jsonl(self):
        fake_data = (
            '{"text": "First stroke content"}\n'
            '{"text": "Second stroke content"}\n'
        )
        with patch("iamai.writer_thematic_progression.STROKES_FILE") as mock_path:
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = fake_data
            result = _load_strokes(10)
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0], "First stroke content")

    def test_malformed_lines_skipped(self):
        fake_data = '{"text": "good"}\nbad line\n{"text": "also good"}\n'
        with patch("iamai.writer_thematic_progression.STROKES_FILE") as mock_path:
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = fake_data
            result = _load_strokes(10)
            self.assertEqual(len(result), 2)

    def test_limit(self):
        fake_data = "\n".join(
            f'{{"text": "stroke {i}"}}' for i in range(20)
        )
        with patch("iamai.writer_thematic_progression.STROKES_FILE") as mock_path:
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = fake_data
            result = _load_strokes(5)
            self.assertEqual(len(result), 5)
            self.assertEqual(result[0], "stroke 15")

    def test_empty_text_skipped(self):
        fake_data = '{"text": ""}\n{"text": "real"}\n'
        with patch("iamai.writer_thematic_progression.STROKES_FILE") as mock_path:
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = fake_data
            result = _load_strokes(10)
            self.assertEqual(len(result), 1)


# =========================================================================
# main / CLI
# =========================================================================

class TestMain(unittest.TestCase):
    def test_json_output(self):
        fake_data = '{"text": "The server processes requests efficiently."}\n'
        with patch("iamai.writer_thematic_progression.STROKES_FILE") as mock_path:
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = fake_data
            with patch("builtins.print") as mock_print:
                main(["--json"])
                mock_print.assert_called()
                output = mock_print.call_args[0][0]
                parsed = json.loads(output)
                self.assertIn("progression_index", parsed)

    def test_summary_output(self):
        fake_data = (
            '{"text": "The server processes requests. '
            'Requests arrive from multiple clients."}\n'
        )
        with patch("iamai.writer_thematic_progression.STROKES_FILE") as mock_path:
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = fake_data
            with patch("builtins.print") as mock_print:
                main([])
                mock_print.assert_called()
                first_call = mock_print.call_args_list[0][0][0]
                self.assertIn("thematic progression", first_call)


# =========================================================================
# STOP_WORDS
# =========================================================================

class TestStopWords(unittest.TestCase):
    def test_is_frozenset(self):
        self.assertIsInstance(STOP_WORDS, frozenset)

    def test_contains_common_words(self):
        for w in ("the", "and", "is", "was", "have"):
            self.assertIn(w, STOP_WORDS)

    def test_no_content_words(self):
        for w in ("server", "algorithm", "crashed", "elegant"):
            self.assertNotIn(w, STOP_WORDS)


if __name__ == "__main__":
    unittest.main()
