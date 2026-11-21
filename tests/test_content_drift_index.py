#!/usr/bin/env python3
"""Tests for content_drift_index.py — topic diversity measurer."""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iamai.content_drift_index import (
    DEFAULT_STOPWORDS,
    DriftReport,
    VocabStats,
    analyse_jsonl,
    analyse_strokes,
    classify,
    drift_score,
    tokenize,
    vocabulary_stats,
)


# ---------------------------------------------------------------------------
# tokenize
# ---------------------------------------------------------------------------


class TestTokenize(unittest.TestCase):
    """Test the tokenize function."""

    def test_basic_splitting(self):
        tokens = tokenize("hello world testing code")
        self.assertEqual(tokens, ["hello", "world", "testing", "code"])

    def test_stopwords_removed(self):
        tokens = tokenize("the writer is running very fast")
        # "the", "is", "very" are stopwords; "fast" is only 4 chars
        self.assertNotIn("the", tokens)
        self.assertNotIn("is", tokens)
        self.assertNotIn("very", tokens)
        self.assertIn("fast", tokens)
        self.assertIn("writer", tokens)
        self.assertIn("running", tokens)

    def test_min_word_length(self):
        tokens = tokenize("big cat ran far away quickly", min_word_length=5)
        # "big"(3), "cat"(3), "ran"(3), "far"(3), "away"(4) are all < 5 chars
        self.assertNotIn("big", tokens)
        self.assertNotIn("cat", tokens)
        self.assertNotIn("ran", tokens)
        self.assertNotIn("far", tokens)
        self.assertNotIn("away", tokens)  # 4 chars, excluded at min=5
        self.assertIn("quickly", tokens)  # 7 chars, passes

    def test_punctuation_handling(self):
        tokens = tokenize("hello, world! test-code; extra.stuff")
        self.assertIn("hello", tokens)
        self.assertIn("world", tokens)
        self.assertIn("test", tokens)
        self.assertIn("code", tokens)
        self.assertIn("extra", tokens)
        self.assertIn("stuff", tokens)

    def test_case_insensitive(self):
        tokens = tokenize("HELLO World TeSt")
        self.assertEqual(tokens, ["hello", "world", "test"])

    def test_empty_string(self):
        tokens = tokenize("")
        self.assertEqual(tokens, [])

    def test_only_stopwords(self):
        tokens = tokenize("the and is was were")
        self.assertEqual(tokens, [])

    def test_custom_stopwords(self):
        custom = frozenset({"hello", "world"})
        tokens = tokenize("hello world testing code", stopwords=custom)
        self.assertNotIn("hello", tokens)
        self.assertNotIn("world", tokens)
        self.assertIn("testing", tokens)
        self.assertIn("code", tokens)

    def test_numbers_as_tokens(self):
        tokens = tokenize("test 1234 value 5678")
        self.assertIn("1234", tokens)
        self.assertIn("5678", tokens)

    def test_hyphenated_words(self):
        tokens = tokenize("self-monitoring auto-restart pre-commit")
        # split on non-alphanumeric, so hyphens break words
        # "pre" is only 3 chars, below default min_word_length=4
        self.assertIn("self", tokens)
        self.assertIn("monitoring", tokens)
        self.assertIn("auto", tokens)
        self.assertIn("restart", tokens)
        self.assertNotIn("pre", tokens)  # 3 chars, filtered out
        self.assertIn("commit", tokens)


# ---------------------------------------------------------------------------
# vocabulary_stats
# ---------------------------------------------------------------------------


class TestVocabularyStats(unittest.TestCase):
    """Test the vocabulary_stats function."""

    def test_empty_tokens(self):
        stats = vocabulary_stats([])
        self.assertEqual(stats.total_tokens, 0)
        self.assertEqual(stats.unique_tokens, 0)
        self.assertEqual(stats.type_token_ratio, 0.0)
        self.assertEqual(stats.hapax_ratio, 0.0)
        self.assertEqual(stats.entropy, 0.0)

    def test_all_unique(self):
        tokens = ["alpha", "bravo", "charlie", "delta", "echo"]
        stats = vocabulary_stats(tokens)
        self.assertEqual(stats.total_tokens, 5)
        self.assertEqual(stats.unique_tokens, 5)
        self.assertAlmostEqual(stats.type_token_ratio, 1.0)
        self.assertEqual(stats.hapax_legomena, 5)
        self.assertAlmostEqual(stats.hapax_ratio, 1.0)

    def test_all_same(self):
        tokens = ["test"] * 10
        stats = vocabulary_stats(tokens)
        self.assertEqual(stats.total_tokens, 10)
        self.assertEqual(stats.unique_tokens, 1)
        self.assertAlmostEqual(stats.type_token_ratio, 0.1)
        self.assertEqual(stats.hapax_legomena, 0)
        self.assertAlmostEqual(stats.hapax_ratio, 0.0)
        # entropy of a single symbol is 0
        self.assertAlmostEqual(stats.entropy, 0.0)

    def test_mixed_frequency(self):
        # "alpha" x4, "bravo" x2, "charlie" x1
        tokens = ["alpha"] * 4 + ["bravo"] * 2 + ["charlie"]
        stats = vocabulary_stats(tokens)
        self.assertEqual(stats.total_tokens, 7)
        self.assertEqual(stats.unique_tokens, 3)
        self.assertAlmostEqual(stats.type_token_ratio, 3 / 7)
        self.assertEqual(stats.hapax_legomena, 1)  # only "charlie"
        # entropy check
        expected_entropy = -(
            (4/7) * math.log2(4/7)
            + (2/7) * math.log2(2/7)
            + (1/7) * math.log2(1/7)
        )
        self.assertAlmostEqual(stats.entropy, expected_entropy, places=5)

    def test_normalised_entropy_uniform(self):
        # 4 words each appearing once → max entropy
        tokens = ["alpha", "bravo", "charlie", "delta"]
        stats = vocabulary_stats(tokens)
        # uniform distribution → entropy = log2(4) = 2.0
        self.assertAlmostEqual(stats.entropy, 2.0, places=5)
        # normalised = 2.0 / log2(4) = 1.0
        self.assertAlmostEqual(stats.normalised_entropy, 1.0, places=5)

    def test_normalised_entropy_skewed(self):
        # one word dominates
        tokens = ["alpha"] * 100 + ["bravo", "charlie"]
        stats = vocabulary_stats(tokens)
        # normalised entropy should be low
        self.assertLess(stats.normalised_entropy, 0.3)


# ---------------------------------------------------------------------------
# drift_score
# ---------------------------------------------------------------------------


class TestDriftScore(unittest.TestCase):
    """Test the drift_score composite function."""

    def test_perfect_diversity(self):
        stats = VocabStats(
            total_tokens=100,
            unique_tokens=100,
            type_token_ratio=1.0,
            hapax_legomena=100,
            hapax_ratio=1.0,
            entropy=math.log2(100),
            normalised_entropy=1.0,
        )
        score = drift_score(stats)
        # 0.4*1.0 + 0.3*1.0 + 0.3*1.0 = 1.0
        self.assertAlmostEqual(score, 1.0)

    def test_zero_diversity(self):
        stats = VocabStats(
            total_tokens=100,
            unique_tokens=1,
            type_token_ratio=0.01,
            hapax_legomena=0,
            hapax_ratio=0.0,
            entropy=0.0,
            normalised_entropy=0.0,
        )
        score = drift_score(stats)
        # 0.4*0.01 + 0.3*0 + 0.3*0 = 0.004
        self.assertAlmostEqual(score, 0.004)

    def test_score_in_range(self):
        stats = VocabStats(
            total_tokens=50,
            unique_tokens=20,
            type_token_ratio=0.4,
            hapax_legomena=10,
            hapax_ratio=0.5,
            entropy=3.5,
            normalised_entropy=0.81,
        )
        score = drift_score(stats)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


class TestClassify(unittest.TestCase):
    """Test the classify function."""

    def test_drifting(self):
        self.assertEqual(classify(0.70), "drifting")
        self.assertEqual(classify(0.85), "drifting")
        self.assertEqual(classify(1.0), "drifting")

    def test_stable(self):
        self.assertEqual(classify(0.45), "stable")
        self.assertEqual(classify(0.55), "stable")
        self.assertEqual(classify(0.69), "stable")

    def test_anchored(self):
        self.assertEqual(classify(0.25), "anchored")
        self.assertEqual(classify(0.35), "anchored")
        self.assertEqual(classify(0.44), "anchored")

    def test_frozen(self):
        self.assertEqual(classify(0.0), "frozen")
        self.assertEqual(classify(0.10), "frozen")
        self.assertEqual(classify(0.24), "frozen")

    def test_boundary_values(self):
        # exact boundaries
        self.assertEqual(classify(0.70), "drifting")
        self.assertEqual(classify(0.69999), "stable")
        self.assertEqual(classify(0.45), "stable")
        self.assertEqual(classify(0.44999), "anchored")
        self.assertEqual(classify(0.25), "anchored")
        self.assertEqual(classify(0.24999), "frozen")


# ---------------------------------------------------------------------------
# analyse_strokes
# ---------------------------------------------------------------------------


class TestAnalyseStrokes(unittest.TestCase):
    """Test the analyse_strokes function."""

    def _make_strokes(self, texts):
        return [{"text": t, "seq": i} for i, t in enumerate(texts)]

    def test_diverse_content(self):
        texts = [
            "quantum computing uses superposition and entanglement",
            "baking sourdough bread requires patience and temperature control",
            "distributed systems face consensus problems under partition",
            "marine biology studies ocean ecosystems and coral reefs",
            "typography affects readability through spacing and contrast",
            "mountain climbing demands physical endurance and navigation",
            "compiler optimization transforms abstract syntax trees",
            "watercolor painting blends pigments with controlled moisture",
            "machine learning trains models through gradient descent",
            "urban planning balances density with transportation networks",
        ]
        strokes = self._make_strokes(texts)
        report = analyse_strokes(strokes, window=10)
        self.assertIn(report.verdict, ("drifting", "stable"))
        self.assertGreater(report.score, 0.4)
        self.assertEqual(report.stroke_count, 10)

    def test_repetitive_content(self):
        template = "ten minutes is long enough to be honest and short enough to be boring measured now {n} files"
        texts = [template.format(n=i) for i in range(50)]
        strokes = self._make_strokes(texts)
        report = analyse_strokes(strokes, window=50)
        self.assertIn(report.verdict, ("frozen", "anchored"))
        self.assertLess(report.score, 0.45)

    def test_empty_strokes(self):
        report = analyse_strokes([])
        self.assertEqual(report.verdict, "frozen")
        self.assertEqual(report.score, 0.0)
        self.assertEqual(report.reason, "no strokes provided")

    def test_window_truncation(self):
        texts = [f"unique topic number {i} about different subject matter" for i in range(100)]
        strokes = self._make_strokes(texts)
        report = analyse_strokes(strokes, window=10)
        self.assertEqual(report.stroke_count, 10)  # not 100

    def test_custom_text_field(self):
        strokes = [{"content": "hello world testing", "seq": 1}]
        report = analyse_strokes(strokes, text_field="content")
        self.assertEqual(report.stroke_count, 1)

    def test_missing_text_field(self):
        strokes = [{"seq": 1, "data": "something"}]
        report = analyse_strokes(strokes)
        # empty text → empty tokens → frozen
        self.assertEqual(report.verdict, "frozen")

    def test_top_words_populated(self):
        texts = ["testing modules and testing code and testing functions"] * 5
        strokes = self._make_strokes(texts)
        report = analyse_strokes(strokes, window=5)
        self.assertTrue(len(report.top_words) > 0)
        # "testing" should be the most common
        self.assertEqual(report.top_words[0][0], "testing")

    def test_report_to_dict(self):
        texts = ["hello world testing code"]
        strokes = self._make_strokes(texts)
        report = analyse_strokes(strokes)
        d = report.to_dict()
        self.assertIn("score", d)
        self.assertIn("verdict", d)
        self.assertIn("top_words", d)
        self.assertIsInstance(d["score"], float)

    def test_moderately_diverse(self):
        # Mix of repeated and unique content
        texts = [
            "commit gaps measure repository heartbeat frequency",
            "process restarts recover interrupted writing cadence",
            "commit gaps measure repository heartbeat frequency",
            "backlog drain clears accumulated pending changes",
            "process restarts recover interrupted writing cadence",
            "template exhaustion detects structural repetition patterns",
            "cadence monitoring tracks writing interval consistency",
            "backlog drain clears accumulated pending changes",
            "ssh key health validates deployment credentials automatically",
            "stroke deduplication fingerprints structural content patterns",
        ]
        strokes = self._make_strokes(texts)
        report = analyse_strokes(strokes, window=10)
        # Should be moderate — some repetition but also variety
        self.assertIn(report.verdict, ("stable", "anchored", "drifting"))


# ---------------------------------------------------------------------------
# analyse_jsonl
# ---------------------------------------------------------------------------


class TestAnalyseJsonl(unittest.TestCase):
    """Test the analyse_jsonl function."""

    def test_valid_jsonl(self):
        strokes = [
            {"seq": 1, "text": "quantum entanglement enables superposition"},
            {"seq": 2, "text": "distributed consensus requires fault tolerance"},
            {"seq": 3, "text": "coral reef ecosystems support marine biodiversity"},
            {"seq": 4, "text": "gradient descent optimizes neural network weights"},
            {"seq": 5, "text": "typography spacing improves readability metrics"},
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")
            path = f.name

        try:
            report = analyse_jsonl(path, tail=5)
            self.assertEqual(report.stroke_count, 5)
            self.assertGreater(report.score, 0.0)
        finally:
            os.unlink(path)

    def test_missing_file(self):
        report = analyse_jsonl("/nonexistent/path/strokes.jsonl")
        self.assertEqual(report.verdict, "frozen")
        self.assertIn("not found", report.reason)

    def test_malformed_lines_skipped(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            f.write('{"seq":1,"text":"valid content here testing"}\n')
            f.write("this is not json\n")
            f.write('{"seq":3,"text":"another valid stroke here"}\n')
            f.write("{broken json\n")
            path = f.name

        try:
            report = analyse_jsonl(path, tail=10)
            self.assertEqual(report.stroke_count, 2)
        finally:
            os.unlink(path)

    def test_tail_truncation(self):
        strokes = [{"seq": i, "text": f"stroke number {i} content"} for i in range(20)]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")
            path = f.name

        try:
            report = analyse_jsonl(path, tail=5)
            self.assertEqual(report.stroke_count, 5)
        finally:
            os.unlink(path)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as f:
            path = f.name

        try:
            report = analyse_jsonl(path)
            self.assertEqual(report.verdict, "frozen")
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Integration: detect template treadmill
# ---------------------------------------------------------------------------


class TestTemplateTreadmillDetection(unittest.TestCase):
    """Integration tests simulating the visit-780 template exhaustion."""

    def test_seven_template_cycle(self):
        """Reproduce the exact pattern from strokes.jsonl tail."""
        templates = [
            "ten minutes is long enough to be honest and short enough to be boring measured now {n} python files {m} logged thoughts",
            "a deterministic garden beats a random one it records elapsed time measured now {n} strokes written so far into {m} files",
            "reproducibility is a courtesy to whoever debugs this at usually measured now {n} lines across {m} tracked files {k} commits deep",
            "tests are the part of a repository that argues back measured now {n} python files {m} logged thoughts",
            "growth that never stops is a tumour not a garden measured now {n} strokes written so far into {m} files",
            "an append only log forces you to be wrong in public and then correct yourself measured now {n} lines across {m} tracked files {k} commits deep",
            "if a number in a diary is not measured it is fiction measured now commit {n} the count of times this repo was pushed",
        ]

        # Generate 50 strokes cycling through templates with incrementing numbers
        strokes = []
        for i in range(50):
            t = templates[i % len(templates)]
            text = t.format(n=1750 + i, m=6900 + i, k=1080 + i)
            strokes.append({"seq": i, "text": text})

        report = analyse_strokes(strokes, window=50)
        # Templates have varied vocabulary despite structural repetition,
        # so score is "stable" (0.45-0.69) — this is the key insight:
        # structural dedup catches the template cycle, but content drift
        # alone may not flag it because the vocabulary is diverse enough.
        # The real signal is that BOTH detectors together paint the picture.
        self.assertIn(report.verdict, ("stable", "anchored", "frozen"))
        # Score should be well below perfect diversity
        self.assertLess(report.score, 0.70)

    def test_truly_diverse_strokes(self):
        """50 unique strokes about different topics should score high."""
        # Each stroke is unique and about a different subject
        topics = [
            "photosynthesis converts sunlight into chemical energy through chloroplast reactions",
            "plate tectonics reshape continents through subduction and volcanic activity cycles",
            "shakespeare explored human nature through tragedy comedy and historical drama",
            "blockchain consensus mechanisms validate transactions without central authority",
            "migratory birds navigate using magnetic fields stellar patterns wind currents",
            "impressionist painters captured light through rapid visible brushstroke techniques",
            "antibiotic resistance evolves through horizontal gene transfer mutation selection",
            "jazz improvisation builds harmonic tension through chromatic substitution patterns",
            "glacial erosion carves valleys through freeze thaw cycles rock abrasion",
            "neural plasticity enables learning through synaptic strengthening pruning pathways",
            "ocean acidification dissolves calcium carbonate shells affecting marine food chains",
            "byzantine fault tolerance achieves agreement despite arbitrary component failures",
            "mitochondrial inheritance passes exclusively through maternal genetic lineages",
            "renaissance perspective drawing creates depth illusion through vanishing points",
            "superconductor materials eliminate electrical resistance below critical temperature thresholds",
            "linguistic typology classifies languages according structural features word order",
            "paleoclimate proxies reconstruct historical temperatures through ice core analysis",
            "quantum entanglement enables instantaneous correlation between separated particle states",
            "savanna ecology balances grazing pressure with grassland regeneration seasonal rainfall",
            "cryptographic hash functions produce deterministic fixed length output from arbitrary input",
        ]
        # Use each topic only once (or twice) in 20 strokes
        strokes = [
            {"seq": i, "text": topics[i]}
            for i in range(20)
        ]
        report = analyse_strokes(strokes, window=20)
        # With 20 unique topics, vocabulary should be highly diverse
        self.assertIn(report.verdict, ("drifting", "stable"))
        self.assertGreater(report.score, 0.40)


if __name__ == "__main__":
    unittest.main()
