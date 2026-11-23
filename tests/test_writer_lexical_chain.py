#!/usr/bin/env python3
"""Tests for writer_lexical_chain module.

Covers:
  - _tokenize
  - _content_words
  - _word_set
  - _split_paragraphs
  - _split_sentences
  - _stem
  - _stem_set
  - _linking_words
  - _detect_chains
  - compute_lexical_chains (basic, edge cases, labels)
  - _empty_result / _no_chain_result
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

from iamai.writer_lexical_chain import (
    _tokenize,
    _content_words,
    _word_set,
    _split_paragraphs,
    _split_sentences,
    _stem,
    _stem_set,
    _linking_words,
    _detect_chains,
    compute_lexical_chains,
    _empty_result,
    _no_chain_result,
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
        # "an" and "or" are < 3 chars → filtered.
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
        self.assertEqual(_tokenize("version 3 released"), ["version", "released"])


# =========================================================================
# _content_words
# =========================================================================

class TestContentWords(unittest.TestCase):
    def test_filters_stop_words(self):
        tokens = ["the", "server", "was", "crashed"]
        self.assertEqual(_content_words(tokens), ["server", "crashed"])

    def test_all_stop_words(self):
        self.assertEqual(_content_words(["the", "and", "but"]), [])

    def test_all_content(self):
        self.assertEqual(
            _content_words(["algorithm", "entropy", "resilience"]),
            ["algorithm", "entropy", "resilience"],
        )


# =========================================================================
# _word_set
# =========================================================================

class TestWordSet(unittest.TestCase):
    def test_basic(self):
        result = _word_set("The server crashed badly")
        self.assertIn("server", result)
        self.assertIn("crashed", result)
        self.assertIn("badly", result)
        self.assertNotIn("the", result)

    def test_empty(self):
        self.assertEqual(_word_set(""), set())


# =========================================================================
# _split_paragraphs
# =========================================================================

class TestSplitParagraphs(unittest.TestCase):
    def test_basic(self):
        text = "First paragraph.\n\nSecond paragraph."
        self.assertEqual(
            _split_paragraphs(text),
            ["First paragraph.", "Second paragraph."],
        )

    def test_multiple_blank_lines(self):
        text = "One.\n\n\nTwo.\n\n\n\nThree."
        self.assertEqual(
            _split_paragraphs(text),
            ["One.", "Two.", "Three."],
        )

    def test_single_paragraph(self):
        self.assertEqual(
            _split_paragraphs("Just one paragraph."),
            ["Just one paragraph."],
        )

    def test_empty(self):
        self.assertEqual(_split_paragraphs(""), [])

    def test_whitespace_only(self):
        self.assertEqual(_split_paragraphs("   \n\n  "), [])


# =========================================================================
# _split_sentences
# =========================================================================

class TestSplitSentences(unittest.TestCase):
    def test_basic(self):
        text = "First sentence. Second sentence."
        self.assertEqual(
            _split_sentences(text),
            ["First sentence.", "Second sentence."],
        )

    def test_question_and_exclamation(self):
        text = "Really? Yes! Absolutely."
        self.assertEqual(
            _split_sentences(text),
            ["Really?", "Yes!", "Absolutely."],
        )

    def test_single_sentence(self):
        self.assertEqual(
            _split_sentences("Just one sentence."),
            ["Just one sentence."],
        )

    def test_empty(self):
        self.assertEqual(_split_sentences(""), [])


# =========================================================================
# _stem
# =========================================================================

class TestStem(unittest.TestCase):
    def test_ing_suffix(self):
        self.assertEqual(_stem("running"), "runn")

    def test_tion_suffix(self):
        self.assertEqual(_stem("rotation"), "rota")

    def test_short_word(self):
        self.assertEqual(_stem("run"), "run")

    def test_no_suffix(self):
        self.assertEqual(_stem("algorithm"), "algorithm")

    def test_plural_s(self):
        self.assertEqual(_stem("servers"), "server")

    def test_ed_suffix(self):
        self.assertEqual(_stem("crashed"), "crash")

    def test_ly_suffix(self):
        self.assertEqual(_stem("badly"), "bad")

    def test_ness_suffix(self):
        self.assertEqual(_stem("darkness"), "dark")


# =========================================================================
# _stem_set
# =========================================================================

class TestStemSet(unittest.TestCase):
    def test_basic(self):
        words = {"running", "server", "crashed"}
        stems = _stem_set(words)
        self.assertIn("runn", stems)
        self.assertIn("serv", stems)   # _stem("server") strips "er"
        self.assertIn("crash", stems)

    def test_empty(self):
        self.assertEqual(_stem_set(set()), set())


# =========================================================================
# _linking_words
# =========================================================================

class TestLinkingWords(unittest.TestCase):
    def test_exact_match(self):
        a = {"server", "crashed"}
        b = {"server", "restarted"}
        links = _linking_words(a, b)
        self.assertIn("server", links)

    def test_stem_match(self):
        a = {"running", "process"}
        b = {"run", "processes"}
        links = _linking_words(a, b)
        # "running" stem = "runn", "run" stem = "run" → no match
        # "process" stem = "process", "processes" stem = "processe" → no match
        # Actually let's check the stem function behaviour.
        # _stem("running") → "runn", _stem("run") → "run" → no match
        # _stem("process") → "process", _stem("processes") → "processe" → no match
        # So no links here.
        self.assertEqual(links, set())

    def test_morphological_match(self):
        a = {"analyzed", "metric"}
        b = {"analyse", "metrics"}
        links = _linking_words(a, b)
        # _stem("analyzed") = "analyz", _stem("analyse") = "analys" → no match
        # _stem("metric") = "metric", _stem("metrics") = "metric" → match!
        self.assertIn("metric", links)
        self.assertIn("metrics", links)

    def test_no_overlap(self):
        a = {"alpha", "beta"}
        b = {"gamma", "delta"}
        self.assertEqual(_linking_words(a, b), set())

    def test_empty_sets(self):
        self.assertEqual(_linking_words(set(), set()), set())

    def test_multiple_links(self):
        a = {"server", "process", "memory"}
        b = {"server", "process", "disk"}
        links = _linking_words(a, b)
        self.assertIn("server", links)
        self.assertIn("process", links)


# =========================================================================
# _detect_chains
# =========================================================================

class TestDetectChains(unittest.TestCase):
    def test_single_chain(self):
        # Three sentences all sharing "server"
        sentence_words = [
            {"server", "started"},
            {"server", "running"},
            {"server", "healthy"},
        ]
        chains = _detect_chains(sentence_words, [])
        self.assertEqual(len(chains), 1)
        self.assertEqual(chains[0]["length"], 3)
        self.assertEqual(chains[0]["start"], 0)
        self.assertEqual(chains[0]["end"], 2)

    def test_broken_chain(self):
        sentence_words = [
            {"server", "started"},
            {"server", "running"},
            {"banana", "yellow"},
            {"banana", "ripe"},
        ]
        chains = _detect_chains(sentence_words, [])
        self.assertEqual(len(chains), 2)
        self.assertEqual(chains[0]["length"], 2)
        self.assertEqual(chains[1]["length"], 2)

    def test_no_chains(self):
        sentence_words = [
            {"alpha"},
            {"beta"},
            {"gamma"},
        ]
        chains = _detect_chains(sentence_words, [])
        self.assertEqual(len(chains), 0)

    def test_paragraph_break_flag(self):
        sentence_words = [
            {"server", "started"},
            {"server", "running"},
            {"server", "stopped"},
        ]
        # Paragraph break before sentence 2.
        chains = _detect_chains(sentence_words, [2])
        self.assertEqual(len(chains), 1)
        self.assertTrue(chains[0]["crosses_paragraph"])

    def test_short_chain_filtered(self):
        # Single sentence → no chain possible.
        sentence_words = [{"hello"}]
        chains = _detect_chains(sentence_words, [])
        self.assertEqual(len(chains), 0)

    def test_exact_two_sentences(self):
        sentence_words = [
            {"metric", "analysis"},
            {"metric", "result"},
        ]
        chains = _detect_chains(sentence_words, [])
        self.assertEqual(len(chains), 1)
        self.assertEqual(chains[0]["length"], 2)


# =========================================================================
# compute_lexical_chains — basic
# =========================================================================

class TestComputeLexicalChainsBasic(unittest.TestCase):
    def test_connected_text(self):
        text = (
            "The server process started normally. "
            "The server process handled requests efficiently. "
            "The server process logged all activity."
        )
        result = compute_lexical_chains([text])
        self.assertGreater(result["total_sentences"], 0)
        self.assertGreater(result["total_chains"], 0)
        self.assertGreater(result["chain_coverage"], 0)
        self.assertGreater(result["propagation_index"], 0)

    def test_multi_paragraph(self):
        text = (
            "The algorithm processes input data efficiently. "
            "The algorithm handles large datasets well.\n\n"
            "The dataset contains millions of records. "
            "Each record in the dataset has unique identifiers."
        )
        result = compute_lexical_chains([text])
        self.assertGreater(result["total_sentences"], 3)
        self.assertGreater(result["total_chains"], 0)

    def test_empty_input(self):
        result = compute_lexical_chains([])
        self.assertEqual(result["total_sentences"], 0)
        self.assertEqual(result["chain_label"], "disconnected")

    def test_single_sentence(self):
        result = compute_lexical_chains(["Just one sentence here."])
        self.assertEqual(result["total_chains"], 0)
        self.assertEqual(result["chain_label"], "disconnected")

    def test_multiple_strokes(self):
        strokes = [
            "The server crashed unexpectedly.",
            "The server restarted automatically after the crash.",
            "The crash report contained detailed stack traces.",
        ]
        result = compute_lexical_chains(strokes)
        self.assertGreater(result["total_sentences"], 0)
        # "server" links strokes 1→2, "crash" links 2→3.
        self.assertGreater(result["total_chains"], 0)


# =========================================================================
# compute_lexical_chains — edge cases
# =========================================================================

class TestComputeLexicalChainsEdgeCases(unittest.TestCase):
    def test_all_same_word(self):
        text = "Data. Data. Data. Data. Data."
        result = compute_lexical_chains([text])
        # "data" is a content word linking all sentences.
        self.assertEqual(result["total_chains"], 1)
        self.assertEqual(result["max_chain_length"], 5)
        self.assertAlmostEqual(result["chain_coverage"], 1.0)

    def test_no_content_words(self):
        text = "The the the. And and and. But but but."
        result = compute_lexical_chains([text])
        # All words are stop words → no content words → no chains.
        self.assertEqual(result["total_chains"], 0)

    def test_very_short_words(self):
        text = "An ox. An ox. An ox."
        result = compute_lexical_chains([text])
        # "ox" is 2 chars → filtered by _MIN_WORD_LEN=3.
        self.assertEqual(result["total_chains"], 0)


# =========================================================================
# _classify
# =========================================================================

class TestClassify(unittest.TestCase):
    def test_disconnected(self):
        label = _classify(0.10, 0.1, 1.0, 2, 0.5, 0.2, 1, 20)
        self.assertEqual(label, "disconnected")

    def test_scattered(self):
        label = _classify(0.25, 0.30, 2.0, 3, 1.0, 0.4, 3, 20)
        self.assertEqual(label, "scattered")

    def test_coherent(self):
        label = _classify(0.55, 0.65, 4.5, 8, 2.0, 0.6, 4, 20)
        self.assertEqual(label, "coherent")

    def test_flowing(self):
        label = _classify(0.80, 0.90, 7.0, 15, 2.5, 0.85, 3, 20)
        self.assertEqual(label, "flowing")

    def test_threaded(self):
        # continuity < 0.50 to avoid episodic branch firing first.
        label = _classify(0.40, 0.50, 2.5, 4, 1.5, 0.30, 6, 20)
        self.assertEqual(label, "threaded")

    def test_episodic(self):
        label = _classify(0.45, 0.60, 3.5, 6, 1.8, 0.55, 3, 20)
        self.assertEqual(label, "episodic")


# =========================================================================
# _empty_result / _no_chain_result
# =========================================================================

class TestEmptyResults(unittest.TestCase):
    def test_empty_result_keys(self):
        result = _empty_result()
        expected_keys = {
            "total_sentences", "total_chains", "mean_chain_length",
            "max_chain_length", "chain_coverage", "chain_density",
            "chain_continuity", "cross_paragraph_fraction",
            "propagation_index", "chain_label",
        }
        self.assertEqual(set(result.keys()), expected_keys)
        self.assertEqual(result["chain_label"], "disconnected")

    def test_no_chain_result(self):
        result = _no_chain_result(10)
        self.assertEqual(result["total_sentences"], 10)
        self.assertEqual(result["total_chains"], 0)
        self.assertEqual(result["chain_label"], "disconnected")


# =========================================================================
# _summary
# =========================================================================

class TestSummary(unittest.TestCase):
    def test_format(self):
        result = {
            "chain_label": "coherent",
            "propagation_index": 0.5500,
            "total_chains": 4,
            "mean_chain_length": 4.5,
            "chain_coverage": 0.6500,
        }
        summary = _summary(result)
        self.assertIn("coherent", summary)
        self.assertIn("0.55", summary)
        self.assertIn("4 chains", summary)

    def test_zero_result(self):
        result = _empty_result()
        summary = _summary(result)
        self.assertIn("disconnected", summary)


# =========================================================================
# compute_lexical_chains — metric correctness
# =========================================================================

class TestMetricCorrectness(unittest.TestCase):
    def test_coverage_calculation(self):
        # 4 sentences, chain covers sentences 0-2 (3 sentences).
        text = (
            "Server process started. "
            "Server process running. "
            "Server process stopped. "
            "Banana yellow fruit."
        )
        result = compute_lexical_chains([text])
        self.assertEqual(result["total_sentences"], 4)
        # Chain covers 3 of 4 sentences.
        self.assertAlmostEqual(result["chain_coverage"], 0.75, places=2)

    def test_chain_density(self):
        # Two sentences sharing exactly one content word.
        text = "Algorithm processes data efficiently. Algorithm handles queries quickly."
        result = compute_lexical_chains([text])
        self.assertGreater(result["chain_density"], 0)

    def test_continuity_calculation(self):
        # 5 sentences: chain covers 0-2 and 3-4, so 3 linked pairs out of 4.
        text = (
            "Server started processing. "
            "Server finished processing. "
            "Server logged results. "
            "Banana yellow fruit. "
            "Banana ripe fruit."
        )
        result = compute_lexical_chains([text])
        # total_pairs = 4, linked = at least 3 (0-1, 1-2, 3-4).
        self.assertGreater(result["chain_continuity"], 0.5)

    def test_propagation_bounds(self):
        text = (
            "Server started. Server running. Server healthy. "
            "Server monitored. Server optimized. Server deployed."
        )
        result = compute_lexical_chains([text])
        self.assertGreaterEqual(result["propagation_index"], 0.0)
        self.assertLessEqual(result["propagation_index"], 1.0)


# =========================================================================
# compute_lexical_chains — multiple texts
# =========================================================================

class TestMultipleTexts(unittest.TestCase):
    def test_cross_text_chains(self):
        texts = [
            "The server crashed unexpectedly.",
            "The server restarted after the crash.",
        ]
        result = compute_lexical_chains(texts)
        # "server" and "crash" link the two texts.
        self.assertGreater(result["total_chains"], 0)

    def test_independent_texts(self):
        texts = [
            "Quantum physics explores subatomic particles.",
            "Medieval architecture featured Gothic cathedrals.",
            "Tropical rainforests contain diverse ecosystems.",
        ]
        result = compute_lexical_chains(texts)
        # No lexical overlap → no chains.
        self.assertEqual(result["total_chains"], 0)


# =========================================================================
# _load_strokes
# =========================================================================

class TestLoadStrokes(unittest.TestCase):
    def test_missing_file(self):
        with patch("iamai.writer_lexical_chain.STROKES_FILE") as mock_path:
            mock_path.exists.return_value = False
            result = _load_strokes(10)
            self.assertEqual(result, [])

    def test_valid_jsonl(self):
        jsonl = (
            '{"text": "First stroke about servers."}\n'
            '{"text": "Second stroke about servers."}\n'
        )
        with patch("iamai.writer_lexical_chain.STROKES_FILE") as mock_path:
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = jsonl
            result = _load_strokes(10)
            self.assertEqual(len(result), 2)

    def test_invalid_json_lines(self):
        jsonl = (
            '{"text": "Valid stroke."}\n'
            'not valid json\n'
            '{"text": "Another valid."}\n'
        )
        with patch("iamai.writer_lexical_chain.STROKES_FILE") as mock_path:
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = jsonl
            result = _load_strokes(10)
            self.assertEqual(len(result), 2)


# =========================================================================
# main / CLI
# =========================================================================

class TestMain(unittest.TestCase):
    def test_json_output(self):
        jsonl = '{"text": "Server process running. Server process healthy."}\n'
        with patch("iamai.writer_lexical_chain.STROKES_FILE") as mock_path:
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = jsonl
            # Capture stdout.
            import io
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                main(["--json", "-n", "5"])
            output = captured.getvalue()
            result = json.loads(output)
            self.assertIn("propagation_index", result)

    def test_summary_output(self):
        jsonl = '{"text": "Server process running. Server process healthy."}\n'
        with patch("iamai.writer_lexical_chain.STROKES_FILE") as mock_path:
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = jsonl
            import io
            captured = io.StringIO()
            with patch("sys.stdout", captured):
                main(["-n", "5"])
            output = captured.getvalue()
            self.assertIn("lexical chains:", output)
            self.assertIn("total sentences:", output)


# =========================================================================
# Long text behaviour
# =========================================================================

class TestLongText(unittest.TestCase):
    def test_many_paragraphs(self):
        paragraphs = []
        for i in range(10):
            paragraphs.append(
                f"Paragraph {i} discusses the server architecture. "
                f"The server handles {i * 100} requests per second."
            )
        text = "\n\n".join(paragraphs)
        result = compute_lexical_chains([text])
        self.assertGreater(result["total_sentences"], 10)
        self.assertGreater(result["total_chains"], 0)

    def test_propagation_increases_with_coherence(self):
        # Low coherence: random unrelated sentences.
        low_text = (
            "Quantum physics. Medieval history. Tropical fruit. "
            "Gothic cathedral. Subatomic particles. Rainforest ecology."
        )
        # High coherence: sentences sharing "server".
        high_text = (
            "Server started processing. Server handled requests. "
            "Server logged activity. Server monitored health. "
            "Server optimized performance. Server deployed updates."
        )
        low = compute_lexical_chains([low_text])
        high = compute_lexical_chains([high_text])
        self.assertGreater(high["propagation_index"], low["propagation_index"])


if __name__ == "__main__":
    unittest.main()
