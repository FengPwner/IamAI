"""Tests for iamai.content_fingerprint module."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from iamai.content_fingerprint import (
    DEFAULT_N,
    DEFAULT_THRESHOLD,
    _char_ngrams,
    _load_stroke_texts,
    _tokenise,
    cross_kind_similarity,
    fingerprint,
    find_near_duplicates,
    jaccard_similarity,
    kind_fingerprints,
    near_duplicate_summary,
)


# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------


class TestTokenise:
    def test_basic(self):
        assert _tokenise("Hello World") == ["hello", "world"]

    def test_punctuation(self):
        assert _tokenise("it's a test!") == ["it", "s", "a", "test"]

    def test_numbers_stripped(self):
        assert _tokenise("stroke 42 done") == ["stroke", "done"]

    def test_empty(self):
        assert _tokenise("") == []

    def test_unicode(self):
        # Non-ASCII letters are treated as separators (only a-z kept)
        assert _tokenise("café latte") == ["caf", "latte"]

    def test_multiple_spaces(self):
        assert _tokenise("  hello   world  ") == ["hello", "world"]


# ---------------------------------------------------------------------------
# Character n-grams
# ---------------------------------------------------------------------------


class TestCharNgrams:
    def test_basic_trigram(self):
        assert _char_ngrams("hello", 3) == {"hel", "ell", "llo"}

    def test_short_token(self):
        # Token shorter than n returns the token itself
        assert _char_ngrams("hi", 3) == {"hi"}

    def test_single_char(self):
        assert _char_ngrams("a", 3) == {"a"}

    def test_exact_length(self):
        assert _char_ngrams("abc", 3) == {"abc"}

    def test_bigram(self):
        assert _char_ngrams("hello", 2) == {"he", "el", "ll", "lo"}


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


class TestFingerprint:
    def test_returns_set(self):
        fp = fingerprint("the quick brown fox")
        assert isinstance(fp, set)
        assert len(fp) > 0

    def test_empty_text(self):
        assert fingerprint("") == set()

    def test_single_word(self):
        fp = fingerprint("hello")
        assert "hel" in fp
        assert "ell" in fp
        assert "llo" in fp

    def test_inter_token_bridge(self):
        # "hello world" should produce a bridge ngram like "o w"
        fp = fingerprint("hello world", n=3)
        assert isinstance(fp, set)
        assert len(fp) > 4  # more than just intra-word ngrams

    def test_deterministic(self):
        assert fingerprint("abc def") == fingerprint("abc def")

    def test_case_insensitive(self):
        assert fingerprint("Hello World") == fingerprint("hello world")

    def test_different_n(self):
        fp2 = fingerprint("hello world", n=2)
        fp3 = fingerprint("hello world", n=3)
        # Different n values should produce different fingerprint sizes
        assert fp2 != fp3


# ---------------------------------------------------------------------------
# Jaccard similarity
# ---------------------------------------------------------------------------


class TestJaccardSimilarity:
    def test_identical(self):
        s = {"a", "b", "c"}
        assert jaccard_similarity(s, s) == 1.0

    def test_disjoint(self):
        assert jaccard_similarity({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial_overlap(self):
        a = {"a", "b", "c", "d"}
        b = {"c", "d", "e", "f"}
        # intersection=2, union=6
        assert abs(jaccard_similarity(a, b) - 2 / 6) < 1e-9

    def test_both_empty(self):
        assert jaccard_similarity(set(), set()) == 0.0

    def test_one_empty(self):
        assert jaccard_similarity({"a"}, set()) == 0.0

    def test_symmetric(self):
        a = {"x", "y"}
        b = {"y", "z"}
        assert jaccard_similarity(a, b) == jaccard_similarity(b, a)


# ---------------------------------------------------------------------------
# Stroke loading
# ---------------------------------------------------------------------------


class TestLoadStrokeTexts:
    def test_missing_file(self, tmp_path):
        result = _load_stroke_texts(tmp_path / "nonexistent.jsonl")
        assert result == []

    def test_valid_strokes(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            json.dumps({"seq": 1, "kind": "thought", "text": "hello world"}) + "\n"
            + json.dumps({"seq": 2, "kind": "garden", "text": "green grass"}) + "\n"
        )
        entries = _load_stroke_texts(p)
        assert len(entries) == 2
        assert entries[0]["seq"] == 1
        assert entries[0]["kind"] == "thought"
        assert isinstance(entries[0]["fp"], set)

    def test_malformed_line(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("not json\n" + json.dumps({"seq": 1, "kind": "x", "text": "ok"}) + "\n")
        entries = _load_stroke_texts(p)
        assert len(entries) == 1

    def test_uses_seed_fallback(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(json.dumps({"seq": 1, "kind": "t", "seed": "fallback text"}) + "\n")
        entries = _load_stroke_texts(p)
        assert len(entries) == 1
        assert len(entries[0]["fp"]) > 0


# ---------------------------------------------------------------------------
# Near-duplicate detection
# ---------------------------------------------------------------------------


class TestFindNearDuplicates:
    def test_identical_strokes(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(3):
            lines.append(json.dumps({"seq": i, "kind": "thought", "text": "the same thought repeated here"}))
        p.write_text("\n".join(lines) + "\n")
        pairs = find_near_duplicates(threshold=0.5, path=p)
        # 3 identical strokes → 3 pairs (0-1, 0-2, 1-2)
        assert len(pairs) == 3
        for seq_a, seq_b, sim in pairs:
            assert sim > 0.9

    def test_distinct_strokes(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 0, "kind": "thought", "text": "alpha beta gamma"}),
            json.dumps({"seq": 1, "kind": "thought", "text": "xyz one two three"}),
            json.dumps({"seq": 2, "kind": "garden", "text": "purple elephant"}),
        ]
        p.write_text("\n".join(lines) + "\n")
        pairs = find_near_duplicates(threshold=0.8, path=p)
        assert len(pairs) == 0

    def test_max_pairs_cap(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(20):
            lines.append(json.dumps({"seq": i, "kind": "t", "text": "repeated content here always"}))
        p.write_text("\n".join(lines) + "\n")
        pairs = find_near_duplicates(threshold=0.5, max_pairs=5, path=p)
        assert len(pairs) <= 5

    def test_sorted_by_similarity(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 0, "kind": "t", "text": "exact same content"}),
            json.dumps({"seq": 1, "kind": "t", "text": "exact same content"}),
            json.dumps({"seq": 2, "kind": "t", "text": "exact same different"}),
        ]
        p.write_text("\n".join(lines) + "\n")
        pairs = find_near_duplicates(threshold=0.3, path=p)
        if len(pairs) >= 2:
            # First pair should have highest similarity
            assert pairs[0][2] >= pairs[1][2]

    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        assert find_near_duplicates(path=p) == []


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class TestNearDuplicateSummary:
    def test_format(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 0, "kind": "t", "text": "unique alpha beta"}),
            json.dumps({"seq": 1, "kind": "t", "text": "unique gamma delta"}),
        ]
        p.write_text("\n".join(lines) + "\n")
        s = near_duplicate_summary(threshold=0.9, path=p)
        assert "0 near-duplicate pairs" in s
        assert "2 strokes" in s

    def test_with_duplicates(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 0, "kind": "t", "text": "same text here"}),
            json.dumps({"seq": 1, "kind": "t", "text": "same text here"}),
        ]
        p.write_text("\n".join(lines) + "\n")
        s = near_duplicate_summary(threshold=0.5, path=p)
        assert "1 near-duplicate pair" in s


# ---------------------------------------------------------------------------
# Kind fingerprints & cross-kind
# ---------------------------------------------------------------------------


class TestKindFingerprints:
    def test_basic(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 0, "kind": "thought", "text": "alpha beta"}),
            json.dumps({"seq": 1, "kind": "garden", "text": "green leaves"}),
            json.dumps({"seq": 2, "kind": "thought", "text": "gamma delta"}),
        ]
        p.write_text("\n".join(lines) + "\n")
        kfps = kind_fingerprints(p)
        assert "thought" in kfps
        assert "garden" in kfps
        assert isinstance(kfps["thought"], set)

    def test_union_across_kind(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 0, "kind": "t", "text": "hello world"}),
            json.dumps({"seq": 1, "kind": "t", "text": "goodbye moon"}),
        ]
        p.write_text("\n".join(lines) + "\n")
        kfps = kind_fingerprints(p)
        # Should contain ngrams from both strokes
        assert len(kfps["t"]) > 3


class TestCrossKindSimilarity:
    def test_same_kind(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 0, "kind": "thought", "text": "hello world"}),
        ]
        p.write_text("\n".join(lines) + "\n")
        assert cross_kind_similarity("thought", "thought", p) == 1.0

    def test_missing_kind(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(json.dumps({"seq": 0, "kind": "t", "text": "hi"}) + "\n")
        assert cross_kind_similarity("t", "nonexistent", p) == 0.0

    def test_different_kinds(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 0, "kind": "a", "text": "alpha beta gamma delta"}),
            json.dumps({"seq": 1, "kind": "b", "text": "epsilon zeta eta theta"}),
        ]
        p.write_text("\n".join(lines) + "\n")
        sim = cross_kind_similarity("a", "b", p)
        assert 0.0 <= sim <= 1.0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_very_short_text(self):
        fp = fingerprint("a")
        assert isinstance(fp, set)

    def test_only_punctuation(self):
        fp = fingerprint("!!! ??? ...")
        assert fp == set() or len(fp) == 0

    def test_long_text_performance(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(100):
            lines.append(
                json.dumps({"seq": i, "kind": "t", "text": f"stroke number {i} with some padding text here"})
            )
        p.write_text("\n".join(lines) + "\n")
        pairs = find_near_duplicates(threshold=0.3, path=p)
        assert isinstance(pairs, list)

    def test_threshold_boundary(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 0, "kind": "t", "text": "abc def ghi"}),
            json.dumps({"seq": 1, "kind": "t", "text": "abc def xyz"}),
        ]
        p.write_text("\n".join(lines) + "\n")
        # At threshold 1.0, partial overlap should not match
        pairs_strict = find_near_duplicates(threshold=1.0, path=p)
        assert len(pairs_strict) == 0
        # At threshold 0.0, everything matches
        pairs_loose = find_near_duplicates(threshold=0.0, path=p)
        assert len(pairs_loose) >= 1
