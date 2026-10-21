"""Tests for iamai.topic_continuity — session topical continuity scoring.

Each test class isolates one concern so that a regression points at
the specific broken piece rather than an opaque aggregate.
"""

import pytest

from iamai.topic_continuity import (
    _extract_keywords,
    _jaccard,
    assess_pair,
    assess_session,
    _STOPWORDS,
    _MIN_TOKEN_LEN,
)


# --- Keyword Extraction ---


class TestExtractKeywords:
    def test_basic_extraction(self):
        kw = _extract_keywords("add commit message quality scoring")
        assert "commit" in kw
        assert "message" in kw
        assert "quality" in kw
        assert "scoring" in kw

    def test_short_tokens_filtered(self):
        kw = _extract_keywords("the cat sat on a mat")
        # All tokens are < 4 chars except none
        assert kw == set()

    def test_stopwords_removed(self):
        kw = _extract_keywords("that this with from have been")
        assert kw == set()

    def test_punctuation_stripped(self):
        kw = _extract_keywords("commit, message. quality!")
        assert "commit" in kw
        assert "message" in kw
        assert "quality" in kw

    def test_non_alpha_excluded(self):
        kw = _extract_keywords("test123 hello 456world commit")
        assert "commit" in kw
        assert "test123" not in kw
        assert "456world" not in kw

    def test_empty_input(self):
        assert _extract_keywords("") == set()

    def test_none_like_input(self):
        assert _extract_keywords(None) == set()

    def test_case_insensitive(self):
        kw = _extract_keywords("COMMIT commit Commit")
        assert len(kw) == 1
        assert "commit" in kw


# --- Jaccard Similarity ---


class TestJaccard:
    def test_identical_sets(self):
        s = {"commit", "message", "quality"}
        assert _jaccard(s, s) == 1.0

    def test_disjoint_sets(self):
        a = {"commit", "message"}
        b = {"caretaker", "visit"}
        assert _jaccard(a, b) == 0.0

    def test_partial_overlap(self):
        a = {"commit", "message", "quality"}
        b = {"commit", "message", "scoring"}
        # Intersection: {commit, message} = 2
        # Union: {commit, message, quality, scoring} = 4
        assert _jaccard(a, b) == 0.5

    def test_both_empty(self):
        assert _jaccard(set(), set()) == 0.0

    def test_one_empty(self):
        a = {"commit"}
        assert _jaccard(a, set()) == 0.0


# --- Pair Assessment ---


class TestAssessPair:
    def test_high_overlap(self):
        a = "add commit message quality scoring with length checks"
        b = "extend commit message quality scoring to detect vague subjects"
        result = assess_pair(a, b)
        assert result["score"] > 0.3
        assert "commit" in result["shared"]
        assert "message" in result["shared"]

    def test_no_overlap(self):
        a = "quantum physics explains subatomic particle behavior"
        b = "medieval agriculture relied on crop rotation techniques"
        result = assess_pair(a, b)
        assert result["score"] == 0.0
        assert result["shared"] == []

    def test_empty_inputs(self):
        result = assess_pair("", "")
        assert result["score"] == 0.0

    def test_one_empty(self):
        result = assess_pair("commit message quality", "")
        assert result["score"] == 0.0

    def test_returns_sorted_keywords(self):
        a = "zebra apple mango"
        b = "zebra apple banana"
        result = assess_pair(a, b)
        assert result["keywords_a"] == sorted(result["keywords_a"])
        assert result["keywords_b"] == sorted(result["keywords_b"])
        assert result["shared"] == sorted(result["shared"])


# --- Session Assessment ---


class TestAssessSession:
    def test_continuous_session(self):
        strokes = [
            "commit message quality scoring length mood imperative checks",
            "commit message quality scoring detects vague subject lines",
            "commit message quality scoring extended with punctuation rules",
        ]
        result = assess_session(strokes)
        assert result["verdict"] == "continuous"
        assert result["score"] >= 30
        assert result["pair_count"] == 2

    def test_scattered_session(self):
        strokes = [
            "quantum physics explains subatomic particle behavior",
            "medieval agriculture relied on crop rotation techniques",
            "tropical fish require specific water temperature ranges",
        ]
        result = assess_session(strokes)
        assert result["verdict"] == "scattered"
        assert result["score"] < 10
        assert result["pair_count"] == 2

    def test_fragmented_session(self):
        strokes = [
            "commit message quality scoring helps maintain readable logs",
            "caretaker visits monitor the writer process health status",
            "commit density measures changes per unit time period",
        ]
        result = assess_session(strokes)
        assert result["verdict"] in ("fragmented", "scattered")
        assert result["pair_count"] == 2

    def test_single_stroke(self):
        result = assess_session(["only one stroke in this session"])
        assert result["score"] == 0
        assert result["verdict"] == "scattered"
        assert result["pair_count"] == 0
        assert result["weakest_pair"] is None

    def test_empty_session(self):
        result = assess_session([])
        assert result["score"] == 0
        assert result["pair_count"] == 0

    def test_weakest_pair_identified(self):
        strokes = [
            "commit message quality scoring with length checks",
            "commit message quality detects vague subject lines",
            "tropical fish require specific water temperature ranges",
        ]
        result = assess_session(strokes)
        # Pair 1 (index 1) should be weakest — strokes 2 and 3 are unrelated
        assert result["weakest_pair"] == 1
        assert result["pair_scores"][1] < result["pair_scores"][0]

    def test_pair_scores_list_length(self):
        strokes = ["stroke one content", "stroke two content", "stroke three content"]
        result = assess_session(strokes)
        assert len(result["pair_scores"]) == 2

    def test_score_bounded(self):
        strokes = [
            "commit commit commit commit",
            "commit commit commit commit",
        ]
        result = assess_session(strokes)
        assert 0 <= result["score"] <= 100


# --- Edge Cases ---


class TestEdgeCases:
    def test_identical_strokes(self):
        text = "commit message quality scoring with length checks"
        result = assess_session([text, text])
        # Identical strokes should have high continuity
        assert result["score"] > 50
        assert result["verdict"] == "continuous"

    def test_all_stopwords(self):
        strokes = [
            "that this with from have been",
            "that this with from have been",
        ]
        result = assess_session(strokes)
        # No keywords extracted, so score is 0
        assert result["score"] == 0

    def test_very_long_strokes(self):
        # Long strokes should still work (no performance blowup)
        text_a = " ".join(["commit", "message", "quality"] * 100)
        text_b = " ".join(["commit", "message", "scoring"] * 100)
        result = assess_pair(text_a, text_b)
        assert 0.0 <= result["score"] <= 1.0
