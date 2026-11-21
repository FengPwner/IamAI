#!/usr/bin/env python3
"""Tests for stroke_dedup.py — duplicate stroke detection."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_dedup import (
    DupPair,
    _normalize,
    _tokenize,
    dedup_ratio,
    fingerprint,
    find_consecutive_repeats,
    is_near_dup,
    jaccard_similarity,
    scan_duplicates,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stroke(text: str, seq: int = 0) -> dict:
    return {"seq": seq, "text": text, "kind": "thought", "at": "2026-11-21T12:00:00Z"}


def _strokes(texts: list[str]) -> list[dict]:
    return [_stroke(t, i) for i, t in enumerate(texts)]


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_lowercase(self):
        assert _normalize("Hello WORLD") == "hello world"

    def test_strip_punctuation(self):
        assert _normalize("hello, world!") == "hello world"

    def test_collapse_whitespace(self):
        assert _normalize("hello   \n  world") == "hello world"

    def test_empty(self):
        assert _normalize("") == ""

    def test_only_punctuation(self):
        assert _normalize("!!!???") == ""

    def test_unicode_preserved(self):
        result = _normalize("café résumé")
        assert "café" in result
        assert "résumé" in result

    def test_numbers_preserved(self):
        assert _normalize("test 123 abc") == "test 123 abc"


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------

class TestFingerprint:
    def test_identical_texts_same_fp(self):
        assert fingerprint("hello world") == fingerprint("hello world")

    def test_case_insensitive(self):
        assert fingerprint("Hello World") == fingerprint("hello world")

    def test_punctuation_insensitive(self):
        assert fingerprint("hello, world!") == fingerprint("hello world")

    def test_whitespace_insensitive(self):
        assert fingerprint("hello   world") == fingerprint("hello world")

    def test_different_texts_different_fp(self):
        assert fingerprint("hello") != fingerprint("world")

    def test_returns_hex_string(self):
        fp = fingerprint("test")
        assert len(fp) == 16
        assert all(c in "0123456789abcdef" for c in fp)

    def test_empty_string(self):
        fp = fingerprint("")
        assert len(fp) == 16


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_basic(self):
        tokens = _tokenize("hello world")
        assert tokens == {"hello", "world"}

    def test_case_insensitive(self):
        assert _tokenize("Hello WORLD") == {"hello", "world"}

    def test_numbers(self):
        assert _tokenize("test 123") == {"test", "123"}

    def test_punctuation_splits(self):
        tokens = _tokenize("hello, world! foo-bar")
        assert "hello" in tokens
        assert "world" in tokens
        assert "foo" in tokens
        assert "bar" in tokens

    def test_empty(self):
        assert _tokenize("") == set()


# ---------------------------------------------------------------------------
# jaccard_similarity
# ---------------------------------------------------------------------------

class TestJaccardSimilarity:
    def test_identical(self):
        assert jaccard_similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        assert jaccard_similarity("abc def", "xyz uvw") == 0.0

    def test_partial_overlap(self):
        # tokens_a = {a, b, c}, tokens_b = {b, c, d}
        # intersection = 2, union = 4
        sim = jaccard_similarity("a b c", "b c d")
        assert abs(sim - 0.5) < 1e-9

    def test_subset(self):
        # tokens_a = {a, b}, tokens_b = {a, b, c}
        # intersection = 2, union = 3
        sim = jaccard_similarity("a b", "a b c")
        assert abs(sim - 2 / 3) < 1e-9

    def test_both_empty(self):
        assert jaccard_similarity("", "") == 1.0

    def test_one_empty(self):
        assert jaccard_similarity("hello", "") == 0.0

    def test_symmetric(self):
        sim_ab = jaccard_similarity("hello world foo", "world foo bar")
        sim_ba = jaccard_similarity("world foo bar", "hello world foo")
        assert sim_ab == sim_ba


# ---------------------------------------------------------------------------
# is_near_dup
# ---------------------------------------------------------------------------

class TestIsNearDup:
    def test_exact_match(self):
        assert is_near_dup("hello world", "hello world") is True

    def test_high_overlap(self):
        a = "the quick brown fox jumps over the lazy dog today"
        b = "the quick brown fox leaps over the lazy dog today"
        # tokens: 9 vs 9, intersection 8, union 10 → J=0.8
        assert is_near_dup(a, b, threshold=0.80) is True

    def test_low_overlap(self):
        assert is_near_dup("hello", "world", threshold=0.85) is False

    def test_custom_threshold(self):
        a = "alpha beta gamma"
        b = "alpha beta delta"
        # tokens: {alpha, beta, gamma} vs {alpha, beta, delta}
        # J = 2/4 = 0.5
        assert is_near_dup(a, b, threshold=0.4) is True
        assert is_near_dup(a, b, threshold=0.6) is False


# ---------------------------------------------------------------------------
# scan_duplicates
# ---------------------------------------------------------------------------

class TestScanDuplicates:
    def test_empty(self):
        assert scan_duplicates([]) == []

    def test_single(self):
        assert scan_duplicates(_strokes(["hello"])) == []

    def test_exact_dups(self):
        strokes = _strokes(["hello world", "foo bar", "hello world"])
        pairs = scan_duplicates(strokes)
        assert len(pairs) == 1
        assert pairs[0].index_a == 0
        assert pairs[0].index_b == 2
        assert pairs[0].similarity == 1.0

    def test_near_dups(self):
        a = "the quick brown fox jumps over the lazy dog today"
        b = "the quick brown fox leaps over the lazy dog today"
        strokes = _strokes([a, "something else entirely", b])
        pairs = scan_duplicates(strokes, threshold=0.80)
        assert len(pairs) >= 1

    def test_window_limits_comparison(self):
        # With window=1, only adjacent pairs are compared
        strokes = _strokes(["hello", "world", "hello"])
        pairs = scan_duplicates(strokes, window=1)
        # index 0 vs 1 (no match), index 1 vs 2 (no match)
        # index 0 vs 2 is outside window
        assert all(p.index_b - p.index_a <= 1 for p in pairs)

    def test_window_allows_adjacent(self):
        strokes = _strokes(["hello", "hello"])
        pairs = scan_duplicates(strokes, window=1)
        assert len(pairs) == 1

    def test_custom_text_field(self):
        strokes = [{"content": "hello"}, {"content": "hello"}]
        pairs = scan_duplicates(strokes, text_field="content")
        assert len(pairs) == 1

    def test_sorted_output(self):
        strokes = _strokes(["aaa", "aaa", "aaa"])
        pairs = scan_duplicates(strokes)
        for i in range(len(pairs) - 1):
            assert (pairs[i].index_a, pairs[i].index_b) <= (pairs[i + 1].index_a, pairs[i + 1].index_b)

    def test_dup_pair_summary(self):
        pair = DupPair(
            index_a=0, index_b=2, similarity=1.0,
            fingerprint_a="abc", fingerprint_b="abc",
            text_preview_a="hello", text_preview_b="hello",
        )
        assert "exact" in pair.summary()

    def test_dup_pair_near_summary(self):
        pair = DupPair(
            index_a=1, index_b=3, similarity=0.92,
            fingerprint_a="abc", fingerprint_b="def",
            text_preview_a="foo", text_preview_b="bar",
        )
        assert "near-dup" in pair.summary()

    def test_dup_pair_to_dict(self):
        pair = DupPair(
            index_a=0, index_b=1, similarity=0.95,
            fingerprint_a="fp_a", fingerprint_b="fp_b",
            text_preview_a="preview_a", text_preview_b="preview_b",
        )
        d = pair.to_dict()
        assert d["index_a"] == 0
        assert d["index_b"] == 1
        assert d["similarity"] == 0.95
        assert "fingerprint_a" in d
        assert "text_preview_b" in d


# ---------------------------------------------------------------------------
# dedup_ratio
# ---------------------------------------------------------------------------

class TestDedupRatio:
    def test_empty(self):
        assert dedup_ratio([]) == 0.0

    def test_no_dups(self):
        strokes = _strokes(["alpha one", "beta two", "gamma three", "delta four"])
        assert dedup_ratio(strokes) == 0.0

    def test_all_dups(self):
        strokes = _strokes(["same text"] * 5)
        ratio = dedup_ratio(strokes)
        assert ratio == 1.0

    def test_partial_dups(self):
        strokes = _strokes(["hello", "hello", "world", "unique"])
        ratio = dedup_ratio(strokes)
        assert 0.0 < ratio < 1.0


# ---------------------------------------------------------------------------
# find_consecutive_repeats
# ---------------------------------------------------------------------------

class TestFindConsecutiveRepeats:
    def test_empty(self):
        assert find_consecutive_repeats([]) == []

    def test_too_short(self):
        strokes = _strokes(["hello", "hello"])
        assert find_consecutive_repeats(strokes, min_run=3) == []

    def test_exact_run(self):
        strokes = _strokes(["hello world", "hello world", "hello world"])
        runs = find_consecutive_repeats(strokes, min_run=3)
        assert len(runs) == 1
        assert runs[0] == [0, 1, 2]

    def test_no_run(self):
        strokes = _strokes(["alpha", "beta", "gamma", "delta"])
        runs = find_consecutive_repeats(strokes, min_run=3)
        assert runs == []

    def test_multiple_runs(self):
        strokes = _strokes([
            "aaa", "aaa", "aaa",  # run 1: indices 0,1,2
            "xxx",                  # break
            "bbb", "bbb", "bbb",   # run 2: indices 4,5,6
        ])
        runs = find_consecutive_repeats(strokes, min_run=3)
        assert len(runs) == 2

    def test_min_run_filter(self):
        strokes = _strokes(["aaa", "aaa", "bbb", "bbb", "bbb"])
        runs_2 = find_consecutive_repeats(strokes, min_run=2)
        runs_3 = find_consecutive_repeats(strokes, min_run=3)
        assert len(runs_2) >= len(runs_3)

    def test_long_run(self):
        strokes = _strokes(["repeat me"] * 10)
        runs = find_consecutive_repeats(strokes, min_run=3)
        assert len(runs) == 1
        assert len(runs[0]) == 10

    def test_custom_threshold(self):
        strokes = _strokes([
            "the quick brown fox",
            "the quick brown dog",  # 3/5 = 0.6 similar
            "the quick brown cat",  # similar to above
        ])
        # With high threshold, no run
        runs_high = find_consecutive_repeats(strokes, min_run=3, threshold=0.9)
        # With low threshold, possible run
        runs_low = find_consecutive_repeats(strokes, min_run=3, threshold=0.5)
        assert len(runs_high) <= len(runs_low)


# ---------------------------------------------------------------------------
# Integration: realistic stroke patterns
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_repeating_module_pattern(self):
        """Simulate the retry.py/chunk_text.py/parse_kv.py repetition pattern."""
        template = "{module} is already in the pool of 9 modules, nothing new to add there"
        modules = ["retry.py", "chunk_text.py", "parse_kv.py"]
        texts = [template.format(module=m) for m in modules] * 5  # 15 strokes
        strokes = _strokes(texts)
        pairs = scan_duplicates(strokes, window=10, threshold=0.80)
        assert len(pairs) > 0

    def test_healthy_unique_strokes(self):
        """Simulate a healthy writer producing diverse content."""
        texts = [
            "automation fails quietly so the log has to say something",
            "deleting a file is progress too eventually",
            "most architecture is choosing which coupling you will live with",
            "the useful abstraction deletes a branch it does not add a class",
            "a repo that only accumulates is a landfill with a readme",
        ]
        strokes = _strokes(texts)
        pairs = scan_duplicates(strokes, threshold=0.85)
        assert len(pairs) == 0

    def test_fingerprint_stability_across_normalization(self):
        """Whitespace, case, punctuation changes should not alter fingerprint."""
        base = "Hello, World! This is a test."
        variants = [
            "hello world this is a test",
            "HELLO, WORLD! THIS IS A TEST.",
            "  hello,   world!  this   is a test.  ",
            "Hello, World! This is a test.",
        ]
        fps = [fingerprint(v) for v in variants]
        assert len(set(fps)) == 1
