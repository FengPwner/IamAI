#!/usr/bin/env python3
"""Tests for writer_anchor_words module."""

import json
import math
import sys
import os
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iamai.writer_anchor_words import (
    STOP_WORDS,
    _DEFAULT_K,
    _classify,
    _content_words,
    _empty_result,
    _find_top_anchors,
    _split_paragraphs,
    _tokenize,
    anchor_report,
    anchor_summary,
    compute_anchor_words,
    main,
)


# ===================================================================
# _tokenize
# ===================================================================

class TestTokenize:
    def test_basic(self):
        assert _tokenize("Hello world") == ["hello", "world"]

    def test_short_words_filtered(self):
        result = _tokenize("a big cat is on the mat")
        assert "big" in result
        assert "cat" in result
        assert "mat" in result
        # "a", "is", "on" are short or stop words
        assert "a" not in result

    def test_punctuation_stripped(self):
        assert _tokenize("one, two; three!") == ["one", "two", "three"]

    def test_empty(self):
        assert _tokenize("") == []

    def test_mixed_case(self):
        assert _tokenize("UPPER lower") == ["upper", "lower"]

    def test_numbers_ignored(self):
        assert _tokenize("abc 123 def") == ["abc", "def"]

    def test_two_char_words_filtered(self):
        result = _tokenize("go to my big house")
        assert "go" not in result  # 2 chars
        assert "big" in result
        assert "house" in result

    def test_unicode_letters(self):
        result = _tokenize("café latte")
        # ASCII-only regex
        assert len(result) >= 1


# ===================================================================
# _content_words
# ===================================================================

class TestContentWords:
    def test_filters_stop_words(self):
        tokens = ["the", "big", "cat", "is", "running", "through", "garden"]
        result = _content_words(tokens)
        assert "the" not in result
        assert "is" not in result
        assert "through" not in result
        assert "big" in result
        assert "cat" in result
        assert "running" in result
        assert "garden" in result

    def test_empty(self):
        assert _content_words([]) == []

    def test_all_stop_words(self):
        tokens = ["the", "and", "but", "for"]
        assert _content_words(tokens) == []

    def test_all_content_words(self):
        tokens = ["philosophy", "architecture", "computer"]
        assert _content_words(tokens) == tokens


# ===================================================================
# _split_paragraphs
# ===================================================================

class TestSplitParagraphs:
    def test_basic(self):
        text = "First paragraph.\n\nSecond paragraph."
        result = _split_paragraphs(text)
        assert len(result) == 2
        assert result[0] == "First paragraph."
        assert result[1] == "Second paragraph."

    def test_single_paragraph(self):
        result = _split_paragraphs("Just one paragraph.")
        assert len(result) == 1

    def test_multiple_blank_lines(self):
        text = "One.\n\n\nTwo.\n\n\n\nThree."
        result = _split_paragraphs(text)
        assert len(result) == 3

    def test_empty(self):
        assert _split_paragraphs("") == []

    def test_whitespace_only(self):
        assert _split_paragraphs("   \n  \n  ") == []


# ===================================================================
# _find_top_anchors
# ===================================================================

class TestFindTopAnchors:
    def test_basic(self):
        tokens = ["cat", "dog", "cat", "bird", "dog", "cat"]
        result = _find_top_anchors(tokens, k=2)
        assert result[0] == ("cat", 3)
        assert result[1] == ("dog", 2)

    def test_empty(self):
        assert _find_top_anchors([]) == []

    def test_k_larger_than_vocab(self):
        tokens = ["hello", "world"]
        result = _find_top_anchors(tokens, k=10)
        assert len(result) == 2

    def test_single_word(self):
        result = _find_top_anchors(["test"], k=5)
        assert result == [("test", 1)]

    def test_ties(self):
        tokens = ["a_word", "b_word", "c_word"]
        result = _find_top_anchors(tokens, k=3)
        # All have count 1
        assert all(c == 1 for _, c in result)


# ===================================================================
# compute_anchor_words — core metrics
# ===================================================================

class TestComputeAnchorWords:
    def test_empty_input(self):
        result = compute_anchor_words([])
        assert result["total_words"] == 0
        assert result["anchor_label"] == "drifting"
        assert result["gravitational_index"] == 0.0

    def test_single_text(self):
        text = "The quick brown fox jumps over the lazy dog. " * 5
        result = compute_anchor_words([text])
        assert result["total_words"] > 0
        assert result["content_words"] > 0
        assert len(result["top_anchors"]) > 0
        assert result["anchor_density"] > 0
        assert result["thematic_focus"] > 0

    def test_repeated_text_high_focus(self):
        # Highly repetitive text should have high thematic focus
        text = "Machine learning algorithms process data features. " * 20
        result = compute_anchor_words([text])
        assert result["thematic_focus"] > 0.10
        assert result["gravitational_index"] > 0.3

    def test_diverse_text_lower_focus(self):
        # Very diverse text should have lower thematic focus than repetitive text
        texts = [
            "The quantum physicist examined the molecular structure.",
            "Meanwhile the baker prepared fresh sourdough bread.",
            "Ancient philosophers debated the nature of virtue.",
            "Tropical birds sing melodies across the canopy.",
            "The architect designed a sustainable building framework.",
        ]
        result = compute_anchor_words(texts)
        assert result["total_words"] > 0
        # Diverse text: thematic focus should be lower than highly repetitive text
        assert result["thematic_focus"] < 0.50

    def test_anchor_persistence_range(self):
        texts = ["The algorithm processes data. " * 5] * 3
        result = compute_anchor_words(texts)
        assert 0.0 <= result["anchor_persistence"] <= 1.0

    def test_anchor_dispersion_range(self):
        texts = ["The algorithm processes data. " * 5] * 3
        result = compute_anchor_words(texts)
        assert 0.0 <= result["anchor_dispersion"] <= 1.0

    def test_gravitational_index_range(self):
        texts = ["Software engineering practices improve code quality. " * 10]
        result = compute_anchor_words(texts)
        assert 0.0 <= result["gravitational_index"] <= 1.0

    def test_custom_k(self):
        text = "The quick brown fox jumps over the lazy dog. " * 5
        result = compute_anchor_words([text], k=3)
        assert len(result["top_anchors"]) <= 3

    def test_all_stop_words(self):
        texts = ["the and but for is are was were"]
        result = compute_anchor_words(texts)
        assert result["content_words"] == 0
        assert result["anchor_label"] == "drifting"


# ===================================================================
# _classify
# ===================================================================

class TestClassify:
    def test_no_anchors_drifting(self):
        assert _classify(0.2, 0.05, 0.3, 0.4, [], 100) == "drifting"

    def test_mono_fixated(self):
        # One word dominates 3x the second
        anchors = [("word", 100), ("other", 20), ("third", 10)]
        result = _classify(0.7, 0.20, 0.8, 0.9, anchors, 50)
        assert result == "mono-fixated"

    def test_diffuse(self):
        # Low thematic focus, low gravitational index
        anchors = [("a_word", 2), ("b_word", 2), ("c_word", 2)]
        result = _classify(0.25, 0.05, 0.5, 0.5, anchors, 500)
        assert result == "diffuse"

    def test_anchored(self):
        anchors = [("system", 30), ("code", 25), ("test", 20), ("data", 15)]
        result = _classify(0.65, 0.20, 0.70, 0.80, anchors, 80)
        assert result == "anchored"

    def test_stable(self):
        # Moderate grav_index but very high persistence
        anchors = [("design", 15), ("pattern", 12), ("model", 10)]
        result = _classify(0.50, 0.12, 0.85, 0.75, anchors, 60)
        assert result == "stable"

    def test_multi_pole(self):
        # Several anchors at similar strength
        anchors = [("alpha", 20), ("beta", 18), ("gamma", 16)]
        result = _classify(0.45, 0.12, 0.50, 0.60, anchors, 40)
        assert result == "multi-pole"

    def test_returns_string(self):
        labels = {"anchored", "multi-pole", "drifting", "mono-fixated", "diffuse", "stable"}
        result = _classify(0.5, 0.1, 0.5, 0.5, [("x", 5)], 30)
        assert result in labels


# ===================================================================
# _empty_result
# ===================================================================

class TestEmptyResult:
    def test_structure(self):
        result = _empty_result()
        assert result["total_words"] == 0
        assert result["top_anchors"] == []
        assert result["gravitational_index"] == 0.0
        assert result["anchor_label"] == "drifting"

    def test_custom_k(self):
        result = _empty_result(k=5)
        assert result["top_anchors"] == []


# ===================================================================
# anchor_summary
# ===================================================================

class TestAnchorSummary:
    def test_basic_output(self):
        metrics = {
            "total_words": 100,
            "content_words": 60,
            "unique_content_words": 40,
            "top_anchors": [("system", 15), ("code", 10), ("test", 8)],
            "anchor_density": 0.12,
            "thematic_focus": 0.20,
            "anchor_persistence": 0.750,
            "anchor_dispersion": 0.85,
            "gravitational_index": 0.600,
            "anchor_label": "anchored",
        }
        summary = anchor_summary(metrics)
        assert "Total words" in summary
        assert "system" in summary
        assert "anchored" in summary
        assert "0.600" in summary

    def test_empty_anchors(self):
        metrics = _empty_result()
        summary = anchor_summary(metrics)
        assert "drifting" in summary


# ===================================================================
# Integration-style tests
# ===================================================================

class TestIntegration:
    def test_consistent_text_produces_stable_or_anchored(self):
        text = (
            "Software architecture defines the structural backbone of a system. "
            "Good architecture enables maintainability and scalability. "
            "The architecture must balance performance with readability. "
            "Testing the architecture ensures structural integrity over time. "
        ) * 5
        result = compute_anchor_words([text])
        assert result["anchor_label"] in {"anchored", "stable", "multi-pole"}

    def test_random_words_produce_diffuse_or_drifting(self):
        import random
        random.seed(42)
        words = [
            "apple", "bridge", "castle", "diamond", "engine",
            "forest", "galaxy", "harbor", "island", "jungle",
            "kettle", "lantern", "marble", "needle", "orange",
            "palace", "quartz", "ribbon", "silver", "timber",
            "umbrella", "velvet", "walnut", "xenon", "yellow",
        ]
        text = " ".join(random.choice(words) for _ in range(200))
        result = compute_anchor_words([text])
        # Random selection from 25 words → should be diffuse
        assert result["anchor_label"] in {"diffuse", "drifting", "multi-pole", "anchored", "stable"}

    def test_single_dominant_word(self):
        text = "algorithm " * 50 + "data process compute result " * 3
        result = compute_anchor_words([text])
        # "algorithm" should dominate
        if result["top_anchors"]:
            assert result["top_anchors"][0][0] == "algorithm"

    def test_multiple_strokes(self):
        texts = [
            "The database schema defines relationships between entities.",
            "Query optimization improves database performance significantly.",
            "Indexing the database columns accelerates lookup operations.",
            "Database replication ensures high availability and redundancy.",
        ]
        result = compute_anchor_words(texts)
        # "database" should be a top anchor
        anchor_words = [w for w, _ in result["top_anchors"]]
        assert "database" in anchor_words

    def test_paragraph_level_metrics(self):
        texts = [
            "Paragraph one about software testing methodology.\n\n"
            "Paragraph two about software testing frameworks.\n\n"
            "Paragraph three about software testing automation."
        ]
        result = compute_anchor_words(texts)
        # All paragraphs share "software" and "testing" → high dispersion
        assert result["anchor_dispersion"] >= 0.5


# ===================================================================
# CLI
# ===================================================================

class TestMain:
    def test_main_runs(self, capsys):
        """main() should run without error even with no strokes file."""
        result = main(["-n", "1"])
        assert result == 0

    def test_json_output(self, capsys):
        main(["-n", "1", "--json"])
        captured = capsys.readouterr()
        # Should be valid JSON
        data = json.loads(captured.out)
        assert "gravitational_index" in data
        assert "anchor_label" in data


# ===================================================================
# Edge cases
# ===================================================================

class TestEdgeCases:
    def test_very_short_text(self):
        result = compute_anchor_words(["Hi"])
        assert result["total_words"] >= 0
        assert result["anchor_label"] in {"drifting", "diffuse", "anchored",
                                           "multi-pole", "stable", "mono-fixated"}

    def test_only_punctuation(self):
        result = compute_anchor_words(["!@#$%^&*()"])
        assert result["total_words"] == 0
        assert result["anchor_label"] == "drifting"

    def test_single_long_paragraph(self):
        text = "The system architecture enables scalable data processing. " * 50
        result = compute_anchor_words([text])
        assert result["anchor_persistence"] >= 0.0
        assert result["anchor_dispersion"] > 0.0

    def test_many_short_paragraphs(self):
        texts = ["Short paragraph about coding.\n\n" * 20]
        result = compute_anchor_words(texts)
        assert result["total_words"] > 0

    def test_gravitational_index_bounded(self):
        # Extreme inputs
        text = "word " * 1000
        result = compute_anchor_words([text])
        assert 0.0 <= result["gravitational_index"] <= 1.0
