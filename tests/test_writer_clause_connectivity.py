#!/usr/bin/env python3
"""Tests for writer_clause_connectivity module."""

import json
import math
import sys
import os
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iamai.writer_clause_connectivity import (
    COORDINATING,
    SUBORDINATING,
    _classify,
    _clause_segments,
    _sentence_nesting_depth,
    _split_sentences,
    _tokenize,
    compute_connectivity,
    connectivity_report,
    connectivity_summary,
    main,
)


# ===================================================================
# _tokenize
# ===================================================================

class TestTokenize:
    def test_basic(self):
        assert _tokenize("Hello world") == ["hello", "world"]

    def test_punctuation_stripped(self):
        assert _tokenize("one, two; three!") == ["one", "two", "three"]

    def test_empty(self):
        assert _tokenize("") == []

    def test_contractions(self):
        tokens = _tokenize("don't stop")
        assert "don't" in tokens

    def test_numbers_ignored(self):
        assert _tokenize("abc 123 def") == ["abc", "def"]

    def test_mixed_case(self):
        assert _tokenize("UPPER lower") == ["upper", "lower"]

    def test_multiple_spaces(self):
        assert _tokenize("a   b   c") == ["a", "b", "c"]


# ===================================================================
# _split_sentences
# ===================================================================

class TestSplitSentences:
    def test_single_sentence(self):
        assert _split_sentences("Hello world.") == ["Hello world."]

    def test_multiple_sentences(self):
        result = _split_sentences("One. Two. Three.")
        assert len(result) == 3

    def test_question_marks(self):
        result = _split_sentences("What? Why? How?")
        assert len(result) == 3

    def test_exclamation(self):
        result = _split_sentences("Wow! Great! Nice!")
        assert len(result) == 3

    def test_empty(self):
        assert _split_sentences("") == []

    def test_no_terminator(self):
        result = _split_sentences("no terminator here")
        assert len(result) == 1

    def test_trailing_spaces(self):
        result = _split_sentences("One.   Two.   Three.")
        assert len(result) == 3

    def test_only_whitespace(self):
        assert _split_sentences("   ") == []


# ===================================================================
# _clause_segments
# ===================================================================

class TestClauseSegments:
    def test_simple_sentence(self):
        segs = _clause_segments("the cat sat on the mat")
        assert len(segs) == 1
        assert segs[0]["type"] == "main"

    def test_coordination(self):
        segs = _clause_segments("I went home and I ate dinner")
        assert len(segs) == 2
        types = [s["type"] for s in segs]
        assert "coordinated" in types

    def test_subordination(self):
        segs = _clause_segments("I left because it was late")
        assert len(segs) == 2
        types = [s["type"] for s in segs]
        assert "subordinated" in types

    def test_multiple_conjunctions(self):
        segs = _clause_segments("I ran and she walked but he stayed")
        assert len(segs) == 3

    def test_empty(self):
        assert _clause_segments("") == []

    def test_punctuation_only(self):
        assert _clause_segments("... !!! ???") == []

    def test_mixed_types(self):
        segs = _clause_segments("I ran and she left because it rained")
        assert len(segs) == 3
        types = [s["type"] for s in segs]
        assert "coordinated" in types
        assert "subordinated" in types

    def test_coordinator_at_start(self):
        # "and" at start of sentence — first segment has no connector
        segs = _clause_segments("and then we left")
        assert len(segs) == 1

    def test_subordinator_but(self):
        segs = _clause_segments("she tried but failed")
        assert any(s["type"] == "coordinated" for s in segs)


# ===================================================================
# _sentence_nesting_depth
# ===================================================================

class TestNestingDepth:
    def test_no_subordination(self):
        assert _sentence_nesting_depth("simple flat sentence") == 0

    def test_one_subordinator(self):
        assert _sentence_nesting_depth("I left because it rained") == 1

    def test_two_subordinators(self):
        depth = _sentence_nesting_depth(
            "although it rained while I waited"
        )
        assert depth == 2

    def test_empty(self):
        assert _sentence_nesting_depth("") == 0

    def test_coordinators_not_counted(self):
        assert _sentence_nesting_depth("I ran and she walked") == 0

    def test_deep_nesting(self):
        depth = _sentence_nesting_depth(
            "because although if when while since unless"
        )
        assert depth == 7


# ===================================================================
# _classify
# ===================================================================

class TestClassify:
    def test_balanced(self):
        label = _classify(0.33, 0.33, 0.34, 0.99, ["co"] * 10, 0.5)
        assert label == "balanced"

    def test_telegraphic_few_sentences(self):
        label = _classify(0.1, 0.1, 0.8, 0.3, ["p", "p"], 0.1)
        assert label == "telegraphic"

    def test_coordinated(self):
        label = _classify(0.6, 0.1, 0.3, 0.5, ["co"] * 10, 0.2)
        assert label == "coordinated"

    def test_subordinated(self):
        label = _classify(0.1, 0.6, 0.3, 0.5, ["sub"] * 10, 2.0)
        assert label == "subordinated"

    def test_paratactic(self):
        label = _classify(0.05, 0.05, 0.9, 0.2, ["p"] * 10, 0.0)
        assert label == "paratactic"

    def test_mixed_shift(self):
        dominant = ["co", "sub", "p", "co", "sub", "p", "co", "sub"]
        label = _classify(0.3, 0.3, 0.4, 0.6, dominant, 0.8)
        assert label == "mixed-shift"

    def test_subordinated_by_depth(self):
        # Neither ratio dominates, but depth is high
        label = _classify(0.2, 0.3, 0.5, 0.4, ["p"] * 10, 2.5)
        assert label in ("subordinated", "paratactic")

    def test_balanced_threshold(self):
        label = _classify(0.33, 0.34, 0.33, 0.85, ["co"] * 10, 0.5)
        assert label == "balanced"


# ===================================================================
# compute_connectivity
# ===================================================================

class TestComputeConnectivity:
    def test_empty_input(self):
        result = compute_connectivity([])
        assert result["total_clauses"] == 0
        assert result["connectivity_label"] == "telegraphic"

    def test_single_simple_sentence(self):
        result = compute_connectivity(["The cat sat."])
        assert result["total_clauses"] >= 1
        assert result["parataxis_ratio"] >= 0.0

    def test_coordinated_text(self):
        text = "I ran and she walked and he sat and they left."
        result = compute_connectivity([text])
        assert result["coordination_ratio"] > 0.0

    def test_subordinated_text(self):
        text = (
            "Because it rained although the sky was clear, "
            "we stayed while the storm passed."
        )
        result = compute_connectivity([text])
        assert result["subordination_ratio"] > 0.0

    def test_multiple_texts(self):
        texts = [
            "I ran. She walked.",
            "But he stayed and they left.",
            "Because it was late although we tried.",
        ]
        result = compute_connectivity(texts)
        assert result["total_clauses"] > 3

    def test_metrics_are_rounded(self):
        result = compute_connectivity(["a and b but c."])
        for key in [
            "coordination_ratio", "subordination_ratio",
            "parataxis_ratio", "connectivity_index",
        ]:
            val = result[key]
            assert isinstance(val, float)
            # Should have at most 4 decimal places
            assert round(val, 4) == val

    def test_connectivity_index_range(self):
        result = compute_connectivity([
            "One and two but three. Four because five although six."
        ])
        assert 0.0 <= result["connectivity_index"] <= 1.0

    def test_all_keys_present(self):
        result = compute_connectivity(["Hello world."])
        expected_keys = {
            "total_clauses", "coordination_ratio",
            "subordination_ratio", "parataxis_ratio",
            "mean_nesting_depth", "connectivity_index",
            "avg_clauses_per_sentence", "connectivity_label",
        }
        assert expected_keys.issubset(result.keys())

    def test_only_stopwords(self):
        result = compute_connectivity(["the the the."])
        assert result["total_clauses"] >= 1

    def test_paratactic_text(self):
        texts = [
            "The sun set. The moon rose. Stars appeared.",
            "Wind blew. Leaves fell. Birds sang. Rain came.",
        ]
        result = compute_connectivity(texts)
        assert result["parataxis_ratio"] > 0.5


# ===================================================================
# connectivity_summary
# ===================================================================

class TestConnectivitySummary:
    def test_basic_summary(self):
        metrics = {
            "total_clauses": 50,
            "coordination_ratio": 0.3,
            "subordination_ratio": 0.2,
            "parataxis_ratio": 0.5,
            "mean_nesting_depth": 0.8,
            "connectivity_index": 0.75,
            "avg_clauses_per_sentence": 2.5,
            "connectivity_label": "balanced",
        }
        text = connectivity_summary(metrics)
        assert "balanced" in text
        assert "50" in text

    def test_all_lines_present(self):
        metrics = {
            "total_clauses": 1,
            "coordination_ratio": 0.0,
            "subordination_ratio": 0.0,
            "parataxis_ratio": 1.0,
            "mean_nesting_depth": 0.0,
            "connectivity_index": 0.0,
            "avg_clauses_per_sentence": 1.0,
            "connectivity_label": "telegraphic",
        }
        text = connectivity_summary(metrics)
        lines = text.strip().split("\n")
        assert len(lines) == 8


# ===================================================================
# On-disk integration (connectivity_report)
# ===================================================================

class TestConnectivityReport:
    def test_with_tmp_strokes(self, tmp_path):
        strokes_file = tmp_path / "strokes.jsonl"
        strokes = [
            {"text": "I ran and she walked."},
            {"text": "Because it rained although the sky was clear."},
            {"text": "The sun set. The moon rose."},
        ]
        strokes_file.write_text(
            "\n".join(json.dumps(s) for s in strokes) + "\n"
        )

        import iamai.writer_clause_connectivity as mod
        original = mod.STROKES_FILE
        try:
            mod.STROKES_FILE = strokes_file
            result = connectivity_report(3)
            assert result["strokes_analysed"] == 3
            assert result["total_clauses"] > 0
        finally:
            mod.STROKES_FILE = original

    def test_missing_file(self, tmp_path):
        import iamai.writer_clause_connectivity as mod
        original = mod.STROKES_FILE
        try:
            mod.STROKES_FILE = tmp_path / "nonexistent.jsonl"
            result = connectivity_report()
            assert result["strokes_analysed"] == 0
            assert result["connectivity_label"] == "telegraphic"
        finally:
            mod.STROKES_FILE = original

    def test_empty_file(self, tmp_path):
        strokes_file = tmp_path / "strokes.jsonl"
        strokes_file.write_text("")

        import iamai.writer_clause_connectivity as mod
        original = mod.STROKES_FILE
        try:
            mod.STROKES_FILE = strokes_file
            result = connectivity_report()
            assert result["strokes_analysed"] == 0
        finally:
            mod.STROKES_FILE = original

    def test_malformed_jsonl(self, tmp_path):
        strokes_file = tmp_path / "strokes.jsonl"
        strokes_file.write_text("not json\n{bad\n")

        import iamai.writer_clause_connectivity as mod
        original = mod.STROKES_FILE
        try:
            mod.STROKES_FILE = strokes_file
            result = connectivity_report()
            assert result["strokes_analysed"] == 0
        finally:
            mod.STROKES_FILE = original


# ===================================================================
# CLI (main)
# ===================================================================

class TestCLI:
    def test_default_output(self, tmp_path, capsys):
        strokes_file = tmp_path / "strokes.jsonl"
        strokes_file.write_text(
            json.dumps({"text": "I ran and she walked."}) + "\n"
        )

        import iamai.writer_clause_connectivity as mod
        original = mod.STROKES_FILE
        try:
            mod.STROKES_FILE = strokes_file
            rc = main(["-n", "1"])
            assert rc == 0
            captured = capsys.readouterr()
            assert "Clauses" in captured.out
        finally:
            mod.STROKES_FILE = original

    def test_json_output(self, tmp_path, capsys):
        strokes_file = tmp_path / "strokes.jsonl"
        strokes_file.write_text(
            json.dumps({"text": "Hello world."}) + "\n"
        )

        import iamai.writer_clause_connectivity as mod
        original = mod.STROKES_FILE
        try:
            mod.STROKES_FILE = strokes_file
            rc = main(["-n", "1", "--json"])
            assert rc == 0
            captured = capsys.readouterr()
            data = json.loads(captured.out)
            assert "total_clauses" in data
        finally:
            mod.STROKES_FILE = original


# ===================================================================
# Edge cases & additional coverage
# ===================================================================

class TestEdgeCases:
    def test_single_word_sentence(self):
        result = compute_connectivity(["Run."])
        assert result["total_clauses"] >= 1

    def test_very_long_sentence(self):
        text = " and ".join([f"clause{i}" for i in range(50)]) + "."
        result = compute_connectivity([text])
        assert result["coordination_ratio"] > 0.3

    def test_all_subordinators(self):
        text = "because although if when while since unless after before until."
        result = compute_connectivity([text])
        assert result["subordination_ratio"] > 0.0

    def test_repeated_sentences(self):
        texts = ["The cat sat."] * 20
        result = compute_connectivity(texts)
        assert result["total_clauses"] >= 20

    def test_mixed_punctuation(self):
        texts = ["What?! Really?! Yes!"]
        result = compute_connectivity(texts)
        assert result["total_clauses"] >= 1

    def test_connectivity_index_zero_single_strategy(self):
        # Heavy coordination → low entropy (main clause adds some parataxis)
        texts = ["a and b and c and d and e and f and g and h."]
        result = compute_connectivity(texts)
        assert result["connectivity_index"] < 0.5

    def test_sentence_with_only_conjunctions(self):
        # Edge: sentence is just conjunctions
        result = compute_connectivity(["and but or."])
        assert result["total_clauses"] >= 1

    def test_parataxis_ratio_non_negative(self):
        # Ensure parataxis_ratio doesn't go below 0
        texts = ["a and b but c or d so e yet f."]
        result = compute_connectivity(texts)
        assert result["parataxis_ratio"] >= 0.0

    def test_avg_clauses_per_sentence(self):
        texts = [
            "I ran and she walked and he sat.",
            "Simple.",
        ]
        result = compute_connectivity(texts)
        assert result["avg_clauses_per_sentence"] > 1.0

    def test_mean_nesting_depth_positive(self):
        texts = [
            "because although if when while since unless it rained.",
        ]
        result = compute_connectivity(texts)
        assert result["mean_nesting_depth"] > 0.0


# ===================================================================
# Constants validation
# ===================================================================

class TestConstants:
    def test_coordinating_is_frozenset(self):
        assert isinstance(COORDINATING, frozenset)

    def test_subordinating_is_frozenset(self):
        assert isinstance(SUBORDINATING, frozenset)

    def test_no_overlap(self):
        assert not (COORDINATING & SUBORDINATING)

    def test_coordinating_contains_and(self):
        assert "and" in COORDINATING

    def test_subordinating_contains_because(self):
        assert "because" in SUBORDINATING

    def test_coordinating_size(self):
        assert len(COORDINATING) >= 5

    def test_subordinating_size(self):
        assert len(SUBORDINATING) >= 10
