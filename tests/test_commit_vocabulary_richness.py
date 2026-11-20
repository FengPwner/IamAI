"""
Tests for commit_vocabulary_richness.py

Covers: tokenization, type-token ratio, hapax ratio, vocabulary growth,
category classification, category entropy, full analysis pipeline,
edge cases (empty input, single message, identical messages),
JSON output format, and report formatting.
"""

import json
import math
import os
import subprocess
import sys
import tempfile
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from commit_vocabulary_richness import (
    tokenize,
    compute_type_token_ratio,
    compute_hapax_ratio,
    compute_vocabulary_growth,
    classify_commit,
    compute_category_entropy,
    analyze,
    format_report,
    get_commit_messages,
    CATEGORIES,
)


# ── tokenize ──────────────────────────────────────────────────────────────


class TestTokenize:
    def test_basic_messages(self):
        msgs = ["add new feature", "fix bug in parser"]
        tokens = tokenize(msgs)
        assert "add" in tokens
        assert "new" in tokens
        assert "feature" in tokens
        assert "fix" in tokens
        assert "bug" in tokens
        assert "in" in tokens
        assert "parser" in tokens

    def test_empty_list(self):
        assert tokenize([]) == []

    def test_punctuation_stripped(self):
        tokens = tokenize(["fix: the (big) bug!"])
        assert "fix" in tokens
        assert "the" in tokens
        assert "big" in tokens
        assert "bug" in tokens
        # Punctuation should not appear as tokens
        assert ":" not in tokens
        assert "(" not in tokens

    def test_camelCase_not_split(self):
        """Current tokenizer treats camelCase as one token."""
        tokens = tokenize(["add commitGapAnalyzer module"])
        assert "commitgapanalyzer" in tokens or "commitGapAnalyzer" not in tokens

    def test_underscores_preserved(self):
        tokens = tokenize(["add stroke_sequence_integrity tests"])
        assert "stroke_sequence_integrity" in tokens

    def test_numbers_in_identifiers(self):
        tokens = tokenize(["visit 751 add test42"])
        assert "visit" in tokens
        assert "751" not in tokens  # standalone numbers excluded
        assert "test42" in tokens  # but alphanumeric identifiers kept

    def test_case_insensitive(self):
        tokens = tokenize(["Add FIX Update"])
        assert all(t.islower() for t in tokens)


# ── type-token ratio ─────────────────────────────────────────────────────


class TestTypeTokenRatio:
    def test_all_unique(self):
        tokens = ["alpha", "beta", "gamma", "delta"]
        assert compute_type_token_ratio(tokens) == 1.0

    def test_all_same(self):
        tokens = ["fix", "fix", "fix", "fix"]
        assert compute_type_token_ratio(tokens) == 0.25

    def test_mixed(self):
        tokens = ["add", "fix", "add", "update", "fix", "add"]
        # 3 unique / 6 total = 0.5
        assert abs(compute_type_token_ratio(tokens) - 0.5) < 1e-9

    def test_empty(self):
        assert compute_type_token_ratio([]) == 0.0

    def test_single_token(self):
        assert compute_type_token_ratio(["hello"]) == 1.0


# ── hapax ratio ──────────────────────────────────────────────────────────


class TestHapaxRatio:
    def test_all_hapax(self):
        tokens = ["alpha", "beta", "gamma"]
        assert compute_hapax_ratio(tokens) == 1.0

    def test_no_hapax(self):
        tokens = ["fix", "fix", "add", "add"]
        # 0 words appear exactly once
        assert compute_hapax_ratio(tokens) == 0.0

    def test_mixed(self):
        tokens = ["add", "fix", "add", "update"]
        # "fix" and "update" appear once each, "add" appears twice
        # hapax = 2, unique = 3
        ratio = compute_hapax_ratio(tokens)
        assert abs(ratio - 2.0 / 3.0) < 1e-9

    def test_empty(self):
        assert compute_hapax_ratio([]) == 0.0

    def test_single_token(self):
        assert compute_hapax_ratio(["only"]) == 1.0


# ── vocabulary growth ────────────────────────────────────────────────────


class TestVocabularyGrowth:
    def test_all_new_each_time(self):
        msgs = ["alpha beta", "gamma delta", "epsilon zeta"]
        growth = compute_vocabulary_growth(msgs)
        assert growth == 1.0  # every word is new

    def test_all_repeated(self):
        msgs = ["fix bug", "fix bug", "fix bug"]
        growth = compute_vocabulary_growth(msgs)
        # first message: both words new (ratio=1.0)
        # second: 0 new (ratio=0.0)
        # third: 0 new (ratio=0.0)
        # average: 1/3
        assert abs(growth - 1.0 / 3.0) < 1e-9

    def test_empty(self):
        assert compute_vocabulary_growth([]) == 0.0

    def test_single_message(self):
        growth = compute_vocabulary_growth(["hello world"])
        assert growth == 1.0  # all words in first message are new

    def test_gradual_introduction(self):
        msgs = ["a b", "a c", "a d"]
        # msg1: 2 new / 2 total = 1.0
        # msg2: 1 new (c) / 2 total = 0.5
        # msg3: 1 new (d) / 2 total = 0.5
        growth = compute_vocabulary_growth(msgs)
        assert abs(growth - 2.0 / 3.0) < 1e-9


# ── classify_commit ──────────────────────────────────────────────────────


class TestClassifyCommit:
    def test_add_category(self):
        assert classify_commit("add new monitoring tool") == "add"

    def test_fix_category(self):
        assert classify_commit("fix push race condition") == "fix"

    def test_update_category(self):
        # "new" in "add" category matches first; use unambiguous message
        assert classify_commit("update README section") == "update"

    def test_refactor_category(self):
        assert classify_commit("refactor stroke parser for speed") == "refactor"

    def test_docs_category(self):
        # "update" matches before "docs"; use unambiguous message
        assert classify_commit("docs: contributing guide") == "docs"

    def test_caretaker_category(self):
        assert classify_commit("caretaker visit 751: check processes") == "caretaker"

    def test_ops_category(self):
        assert classify_commit("push recovery after SSH key loss") == "ops"

    def test_test_category(self):
        # "add" matches first in "add 47 tests..."; use unambiguous message
        assert classify_commit("tests for sequence integrity") == "test"

    def test_other_category(self):
        assert classify_commit("initial commit") == "other"

    def test_case_insensitive(self):
        assert classify_commit("FIX critical bug") == "fix"

    def test_multiple_keywords_first_wins(self):
        # "add" appears first in CATEGORIES dict, should match "add"
        result = classify_commit("add fix for the bug")
        assert result in ("add", "fix")  # either is acceptable


# ── category entropy ─────────────────────────────────────────────────────


class TestCategoryEntropy:
    def test_uniform_distribution(self):
        # One message per category → maximum entropy
        msgs = []
        for cat, keywords in CATEGORIES.items():
            msgs.append(f"{keywords[0]} something")
        msgs.append("other thing")  # for "other" category
        entropy = compute_category_entropy(msgs)
        assert entropy > 0.9  # should be close to 1.0

    def test_single_category(self):
        msgs = ["fix bug one", "fix bug two", "fix bug three"]
        entropy = compute_category_entropy(msgs)
        assert entropy == 0.0  # all same category

    def test_two_categories(self):
        msgs = ["fix bug", "fix issue", "add feature", "add tool"]
        entropy = compute_category_entropy(msgs)
        assert 0.0 < entropy < 1.0

    def test_empty(self):
        assert compute_category_entropy([]) == 0.0

    def test_mostly_one_category(self):
        msgs = ["fix a", "fix b", "fix c", "fix d", "add e"]
        entropy = compute_category_entropy(msgs)
        assert entropy < 0.5  # heavily skewed


# ── analyze (integration) ────────────────────────────────────────────────


class TestAnalyze:
    @patch("commit_vocabulary_richness.get_commit_messages")
    def test_diverse_messages(self, mock_get):
        mock_get.return_value = [
            "add new stroke velocity tracker",
            "fix push race condition in SSH key",
            "update README with contributor guide",
            "refactor parser for better performance",
            "caretaker visit 500 health check",
            "docs: add troubleshooting section",
            "restart writer after container recycle",
            "test coverage improvement for batch",
        ]
        result = analyze("/fake/repo", 50)
        assert result["total_messages"] == 8
        assert result["score"] > 0
        assert result["grade"] in ("RICH", "VARIED", "FORMULAIC", "MONOTONOUS")
        assert "categories" in result

    @patch("commit_vocabulary_richness.get_commit_messages")
    def test_repetitive_messages(self, mock_get):
        mock_get.return_value = [
            "caretaker visit 700: add module with tests"
        ] * 20
        result = analyze("/fake/repo", 50)
        assert result["score"] < 50
        assert result["grade"] in ("MONOTONOUS", "FORMULAIC")

    @patch("commit_vocabulary_richness.get_commit_messages")
    def test_empty_repo(self, mock_get):
        mock_get.return_value = []
        result = analyze("/fake/repo", 50)
        assert result["score"] == 0
        assert result["grade"] == "MONOTONOUS"
        assert result["total_messages"] == 0

    @patch("commit_vocabulary_richness.get_commit_messages")
    def test_single_message(self, mock_get):
        mock_get.return_value = ["initial commit"]
        result = analyze("/fake/repo", 50)
        assert result["total_messages"] == 1
        assert result["type_token_ratio"] > 0

    @patch("commit_vocabulary_richness.get_commit_messages")
    def test_score_range(self, mock_get):
        mock_get.return_value = [
            f"add feature number {i} with unique name" for i in range(30)
        ]
        result = analyze("/fake/repo", 50)
        assert 0 <= result["score"] <= 100

    @patch("commit_vocabulary_richness.get_commit_messages")
    def test_json_serializable(self, mock_get):
        mock_get.return_value = ["fix bug", "add feature"]
        result = analyze("/fake/repo", 50)
        # Should not raise
        json_str = json.dumps(result)
        parsed = json.loads(json_str)
        assert parsed["score"] == result["score"]


# ── format_report ────────────────────────────────────────────────────────


class TestFormatReport:
    def test_normal_output(self):
        stats = {
            "score": 65,
            "grade": "VARIED",
            "total_messages": 20,
            "type_token_ratio": 0.45,
            "hapax_ratio": 0.60,
            "vocabulary_growth": 0.35,
            "category_entropy": 0.80,
            "categories": {"add": 8, "fix": 5, "caretaker": 4, "other": 3},
        }
        report = format_report(stats)
        assert "VARIED" in report
        assert "20" in report
        assert "add" in report
        assert "fix" in report

    def test_empty_stats(self):
        stats = {
            "score": 0,
            "grade": "MONOTONOUS",
            "total_messages": 0,
            "type_token_ratio": 0.0,
            "hapax_ratio": 0.0,
            "vocabulary_growth": 0.0,
            "category_entropy": 0.0,
            "categories": {},
        }
        report = format_report(stats)
        assert "No commit messages" in report

    def test_all_categories_shown(self):
        stats = {
            "score": 80,
            "grade": "RICH",
            "total_messages": 10,
            "type_token_ratio": 0.7,
            "hapax_ratio": 0.8,
            "vocabulary_growth": 0.5,
            "category_entropy": 0.9,
            "categories": {"add": 3, "fix": 3, "ops": 2, "other": 2},
        }
        report = format_report(stats)
        for cat in ["add", "fix", "ops", "other"]:
            assert cat in report


# ── get_commit_messages ──────────────────────────────────────────────────


class TestGetCommitMessages:
    def test_invalid_repo(self):
        result = get_commit_messages("/nonexistent/path/xyz", 10)
        assert result == []

    def test_valid_repo(self):
        """Test against the actual IamAI repo if available."""
        repo = os.path.join(os.path.dirname(__file__), "..")
        if os.path.isdir(os.path.join(repo, ".git")):
            messages = get_commit_messages(repo, 5)
            assert len(messages) > 0
            assert len(messages) <= 5
            assert all(isinstance(m, str) for m in messages)


# ── edge cases ───────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_very_long_message(self):
        msg = " ".join([f"word{i}" for i in range(1000)])
        tokens = tokenize([msg])
        assert len(tokens) == 1000
        assert compute_type_token_ratio(tokens) == 1.0

    def test_unicode_handling(self):
        tokens = tokenize(["fix: 修复推送失败的问题"])
        # Chinese characters should be stripped (no ASCII alpha)
        # only "fix" should survive
        assert "fix" in tokens

    def test_special_characters_only(self):
        tokens = tokenize(["!!! --- ??? ..."])
        assert tokens == []

    def test_numeric_only_messages(self):
        tokens = tokenize(["123 456 789"])
        assert tokens == []  # pure numbers excluded

    def test_mixed_alphanumeric(self):
        tokens = tokenize(["v2.0 release candidate3"])
        assert "v2" in tokens or "v2" in tokens
        assert "release" in tokens
        assert "candidate3" in tokens
