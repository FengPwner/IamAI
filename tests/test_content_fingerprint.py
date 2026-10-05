"""Tests for snippets/content_fingerprint.py — near-duplicate detection."""

import pytest
from snippets.content_fingerprint import (
    shingle,
    fingerprint,
    jaccard,
    similarity,
    find_duplicates,
    nearest,
)


# ── shingle ──────────────────────────────────────────────────────────────────


class TestShingle:
    def test_basic(self):
        assert shingle("abcd", n=2) == {"ab", "bc", "cd"}

    def test_n_equals_1(self):
        assert shingle("abc", n=1) == {"a", "b", "c"}

    def test_text_shorter_than_n(self):
        assert shingle("ab", n=4) == set()

    def test_empty_string(self):
        assert shingle("", n=3) == set()

    def test_whitespace_normalization(self):
        # "a  b" and "a b" should produce the same shingles after normalization
        assert shingle("hello  world", n=3) == shingle("hello world", n=3)

    def test_case_insensitive(self):
        assert shingle("Hello World", n=3) == shingle("hello world", n=3)

    def test_exact_length(self):
        assert shingle("abcd", n=4) == {"abcd"}


# ── fingerprint ──────────────────────────────────────────────────────────────


class TestFingerprint:
    def test_returns_frozenset(self):
        assert isinstance(fingerprint("test"), frozenset)

    def test_empty(self):
        assert fingerprint("") == frozenset()

    def test_identical_texts_same_fingerprint(self):
        assert fingerprint("hello world") == fingerprint("hello world")

    def test_different_texts_different_fingerprint(self):
        assert fingerprint("hello world") != fingerprint("goodbye moon")


# ── jaccard ──────────────────────────────────────────────────────────────────


class TestJaccard:
    def test_identical_sets(self):
        assert jaccard({1, 2, 3}, {1, 2, 3}) == 1.0

    def test_disjoint_sets(self):
        assert jaccard({1, 2}, {3, 4}) == 0.0

    def test_partial_overlap(self):
        # {1,2,3} & {2,3,4} = {2,3} → 2/4 = 0.5
        assert jaccard({1, 2, 3}, {2, 3, 4}) == 0.5

    def test_both_empty(self):
        assert jaccard(set(), set()) == 0.0

    def test_one_empty(self):
        assert jaccard({1, 2}, set()) == 0.0

    def test_subset(self):
        # {1} ⊂ {1,2,3} → 1/3
        assert abs(jaccard({1}, {1, 2, 3}) - 1 / 3) < 1e-9


# ── similarity ───────────────────────────────────────────────────────────────


class TestSimilarity:
    def test_identical(self):
        assert similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        assert similarity("abcxyz", "mnopqr") == 0.0

    def test_partial_overlap(self):
        sim = similarity("the quick brown fox", "the quick brown dog")
        assert 0.3 < sim < 0.9

    def test_empty_texts(self):
        assert similarity("", "") == 0.0

    def test_one_empty(self):
        assert similarity("hello world", "") == 0.0

    def test_symmetry(self):
        a = "the quick brown fox jumps"
        b = "the quick brown dog jumps"
        assert similarity(a, b) == similarity(b, a)

    def test_custom_n(self):
        sim_2 = similarity("abcdef", "abcxyz", n=2)
        sim_4 = similarity("abcdef", "abcxyz", n=4)
        # larger n → fewer shared n-grams → lower similarity
        assert sim_2 >= sim_4


# ── find_duplicates ──────────────────────────────────────────────────────────


class TestFindDuplicates:
    def test_finds_near_duplicates(self):
        texts = [
            "the quick brown fox jumps over the lazy dog today",
            "the quick brown fox leaps over the lazy dog today",
            "nothing in common with the others at all here today",
        ]
        pairs = find_duplicates(texts, threshold=0.4)
        assert len(pairs) >= 1
        assert pairs[0][0] == 0
        assert pairs[0][1] == 1

    def test_no_duplicates_below_threshold(self):
        texts = [
            "alpha beta gamma delta epsilon zeta eta theta iota",
            "completely different text about something else entirely",
        ]
        pairs = find_duplicates(texts, threshold=0.9)
        assert len(pairs) == 0

    def test_empty_list(self):
        assert find_duplicates([], threshold=0.5) == []

    def test_single_text(self):
        assert find_duplicates(["just one text here today"], threshold=0.5) == []

    def test_min_length_filter(self):
        texts = ["short", "also short", "this one is long enough to pass the filter"]
        pairs = find_duplicates(texts, threshold=0.1, min_length=20)
        # first two are too short, so no pairs involving them
        assert all(2 in p[:2] for p in pairs) or len(pairs) == 0

    def test_sorted_by_similarity_desc(self):
        texts = [
            "the quick brown fox jumps over the lazy dog again and again today",
            "the quick brown fox leaps over the lazy dog again and again today",
            "the quick brown fox something completely different from others",
            "the quick brown fox jumps over the lazy dog again but different",
        ]
        pairs = find_duplicates(texts, threshold=0.2)
        if len(pairs) > 1:
            for i in range(len(pairs) - 1):
                assert pairs[i][2] >= pairs[i + 1][2]

    def test_all_identical(self):
        texts = ["same text here today"] * 4
        pairs = find_duplicates(texts, threshold=0.9)
        # C(4,2) = 6 pairs, all with similarity 1.0
        assert len(pairs) == 6
        assert all(sim == 1.0 for _, _, sim in pairs)


# ── nearest ──────────────────────────────────────────────────────────────────


class TestNearest:
    def test_basic(self):
        corpus = [
            "hello world foo bar baz qux",
            "goodbye moon something else entirely different",
            "hello world foo bar baz different ending",
        ]
        results = nearest("hello world foo bar baz qux ending", corpus, top_k=2)
        assert len(results) == 2
        # first result should be most similar
        assert results[0][1] >= results[1][1]

    def test_empty_corpus(self):
        assert nearest("hello", [], top_k=3) == []

    def test_empty_query(self):
        assert nearest("", ["hello world foo bar"], top_k=3) == []

    def test_top_k_larger_than_corpus(self):
        corpus = ["one text here today", "another text here today"]
        results = nearest("some query text here today please", corpus, top_k=10)
        assert len(results) == 2

    def test_returns_index_and_score(self):
        corpus = ["hello world this is a test of the system"]
        results = nearest("hello world this is also a test", corpus)
        assert len(results) == 1
        idx, score = results[0]
        assert idx == 0
        assert 0.0 <= score <= 1.0
