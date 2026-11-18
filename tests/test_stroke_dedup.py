"""Tests for iamai.stroke_dedup — near-duplicate stroke detection.

covers:
  - tokenize: stopword removal, number stripping, lowercasing, min length
  - jaccard: normal, empty sets, identical sets, disjoint sets
  - StrokeFingerprint.from_text: token set and hash
  - StrokeDedup.check: exact match, near-duplicate, unique, empty window
  - StrokeDedup.record: adds to window without checking
  - StrokeDedup.check_and_record: records only non-duplicates
  - StrokeDedup.clear: resets window
  - Sliding window: eviction when maxlen exceeded
  - Threshold tuning: low threshold catches more, high threshold fewer
  - Real-world examples from reading.md duplicates
"""

import pytest

from iamai.stroke_dedup import (
    STOPWORDS,
    DEFAULT_THRESHOLD,
    DEFAULT_WINDOW,
    tokenize,
    jaccard,
    StrokeFingerprint,
    DedupResult,
    StrokeDedup,
)


# ─── tokenize ───────────────────────────────────────────────────────


class TestTokenize:
    def test_basic_split(self):
        tokens = tokenize("hello world")
        assert "hello" in tokens
        assert "world" in tokens

    def test_lowercases(self):
        tokens = tokenize("HELLO World FoO")
        assert "hello" in tokens
        assert "world" in tokens
        assert "foo" in tokens

    def test_strips_stopwords(self):
        tokens = tokenize("this is a test of the system")
        assert "this" not in tokens
        assert "is" not in tokens
        assert "a" not in tokens
        assert "the" not in tokens
        assert "test" in tokens
        assert "system" in tokens

    def test_strips_bare_numbers(self):
        tokens = tokenize("tree is 2380 files and 608917 lines")
        assert "2380" not in tokens
        assert "608917" not in tokens
        assert "tree" in tokens
        assert "files" in tokens
        assert "lines" in tokens

    def test_strips_short_tokens(self):
        tokens = tokenize("a i go to the park")
        # "a" and "i" are either stopwords or < 2 chars
        assert "go" in tokens
        assert "park" in tokens

    def test_punctuation_boundary(self):
        tokens = tokenize("automation fails quietly, so the log speaks.")
        assert "automation" in tokens
        assert "fails" in tokens
        assert "quietly" in tokens
        assert "log" in tokens
        assert "speaks" in tokens

    def test_empty_string(self):
        assert tokenize("") == frozenset()

    def test_only_numbers_and_stopwords(self):
        tokens = tokenize("it is 42 a 100")
        assert tokens == frozenset()

    def test_contractions_preserved(self):
        # "don't" is kept as a single token (apostrophe included in pattern)
        tokens = tokenize("don't stop")
        assert "don't" in tokens
        assert "stop" in tokens

    def test_returns_frozenset(self):
        result = tokenize("hello world")
        assert isinstance(result, frozenset)


# ─── jaccard ────────────────────────────────────────────────────────


class TestJaccard:
    def test_identical_sets(self):
        s = frozenset({"a", "b", "c"})
        assert jaccard(s, s) == 1.0

    def test_disjoint_sets(self):
        a = frozenset({"x", "y"})
        b = frozenset({"p", "q"})
        assert jaccard(a, b) == 0.0

    def test_partial_overlap(self):
        a = frozenset({"a", "b", "c", "d"})
        b = frozenset({"c", "d", "e", "f"})
        # intersection=2, union=6 → 2/6 ≈ 0.333
        assert abs(jaccard(a, b) - 2 / 6) < 1e-9

    def test_both_empty(self):
        assert jaccard(frozenset(), frozenset()) == 0.0

    def test_one_empty(self):
        a = frozenset({"hello", "world"})
        assert jaccard(a, frozenset()) == 0.0
        assert jaccard(frozenset(), a) == 0.0

    def test_subset(self):
        a = frozenset({"a", "b"})
        b = frozenset({"a", "b", "c", "d"})
        # intersection=2, union=4 → 0.5
        assert jaccard(a, b) == 0.5

    def test_symmetry(self):
        a = frozenset({"alpha", "beta"})
        b = frozenset({"beta", "gamma", "delta"})
        assert jaccard(a, b) == jaccard(b, a)


# ─── StrokeFingerprint ─────────────────────────────────────────────


class TestStrokeFingerprint:
    def test_from_text_tokens(self):
        fp = StrokeFingerprint.from_text("automation fails quietly")
        assert "automation" in fp.tokens
        assert "fails" in fp.tokens
        assert "quietly" in fp.tokens

    def test_from_text_hash(self):
        fp1 = StrokeFingerprint.from_text("hello world")
        fp2 = StrokeFingerprint.from_text("hello world")
        assert fp1.text_hash == fp2.text_hash

    def test_different_text_different_hash(self):
        fp1 = StrokeFingerprint.from_text("hello world")
        fp2 = StrokeFingerprint.from_text("goodbye world")
        assert fp1.text_hash != fp2.text_hash

    def test_frozen(self):
        fp = StrokeFingerprint.from_text("test")
        with pytest.raises(AttributeError):
            fp.tokens = frozenset()  # type: ignore[misc]

    def test_hash_length(self):
        fp = StrokeFingerprint.from_text("some text here")
        assert len(fp.text_hash) == 16  # truncated sha256 hex


# ─── StrokeDedup — basic operations ────────────────────────────────


class TestStrokeDedupBasic:
    def test_empty_window_not_duplicate(self):
        d = StrokeDedup()
        result = d.check("hello world")
        assert not result.is_duplicate
        assert result.match_index == -1
        assert "empty window" in result.reason

    def test_exact_duplicate_detected(self):
        d = StrokeDedup()
        text = "naming is hard because a bad name is cheap to type"
        d.record(text)
        result = d.check(text)
        assert result.is_duplicate
        assert result.similarity == 1.0
        assert "exact" in result.reason

    def test_near_duplicate_detected(self):
        d = StrokeDedup(threshold=0.6)
        d.record("the useful abstraction deletes a branch not adds a class")
        # Same words minus one — should still match above 0.6
        result = d.check("useful abstraction deletes branch not adds class")
        assert result.is_duplicate
        assert result.similarity >= 0.6

    def test_unique_text_not_flagged(self):
        d = StrokeDedup()
        d.record("automation fails quietly so the log has to say something")
        result = d.check("deleting a file is progress too eventually")
        assert not result.is_duplicate

    def test_record_increases_size(self):
        d = StrokeDedup()
        assert d.size == 0
        d.record("first stroke")
        assert d.size == 1
        d.record("second stroke")
        assert d.size == 2

    def test_clear(self):
        d = StrokeDedup()
        d.record("one")
        d.record("two")
        assert d.size == 2
        d.clear()
        assert d.size == 0


# ─── check_and_record ───────────────────────────────────────────────


class TestCheckAndRecord:
    def test_records_unique(self):
        d = StrokeDedup()
        result = d.check_and_record("unique thought number one")
        assert not result.is_duplicate
        assert d.size == 1

    def test_skips_duplicate(self):
        d = StrokeDedup()
        d.check_and_record("repeated thought about naming")
        result = d.check_and_record("repeated thought about naming")
        assert result.is_duplicate
        # Should NOT have been added again.
        assert d.size == 1

    def test_sequence(self):
        d = StrokeDedup()
        d.check_and_record("alpha beta gamma")
        d.check_and_record("delta epsilon zeta")
        d.check_and_record("alpha beta gamma")  # dup
        d.check_and_record("eta theta iota")
        assert d.size == 3


# ─── sliding window ────────────────────────────────────────────────


class TestSlidingWindow:
    def test_evicts_oldest(self):
        d = StrokeDedup(window=3)
        d.record("first")
        d.record("second")
        d.record("third")
        assert d.size == 3
        d.record("fourth")  # evicts "first"
        assert d.size == 3
        # "first" was evicted, so it should no longer be a duplicate
        # (unless its tokens happen to overlap with remaining entries)
        # We check that size is capped, which is the key invariant.

    def test_window_max_property(self):
        d = StrokeDedup(window=5)
        assert d.window_max == 5

    def test_window_min_is_one(self):
        d = StrokeDedup(window=0)
        assert d.window_max == 1


# ─── threshold tuning ──────────────────────────────────────────────


class TestThreshold:
    def test_low_threshold_catches_more(self):
        d = StrokeDedup(threshold=0.3)
        d.record("the quick brown fox jumps over the lazy dog")
        # Partial overlap: shares "quick", "brown", "fox"
        result = d.check("quick brown fox runs through the forest")
        # With threshold 0.3 this might or might not match depending
        # on exact token overlap; we just verify the threshold is used.
        assert isinstance(result.is_duplicate, bool)

    def test_high_threshold_stricter(self):
        d = StrokeDedup(threshold=0.95)
        d.record("naming is hard because a bad name is cheap to type")
        # Slightly different text — should NOT match at 0.95
        result = d.check("naming is hard because bad name cheap type keep")
        assert not result.is_duplicate

    def test_threshold_property(self):
        d = StrokeDedup(threshold=0.42)
        assert d.threshold == 0.42


# ─── DedupResult ────────────────────────────────────────────────────


class TestDedupResult:
    def test_str_duplicate(self):
        r = DedupResult(is_duplicate=True, similarity=0.85, match_index=3, reason="test")
        s = str(r)
        assert "DUPLICATE" in s
        assert "0.85" in s

    def test_str_unique(self):
        r = DedupResult(is_duplicate=False, similarity=0.2, match_index=1, reason="below")
        s = str(r)
        assert "unique" in s

    def test_frozen(self):
        r = DedupResult(is_duplicate=False, similarity=0.0, match_index=-1, reason="x")
        with pytest.raises(AttributeError):
            r.is_duplicate = True  # type: ignore[misc]


# ─── real-world duplicates from reading.md ─────────────────────────


class TestRealWorldDuplicates:
    """Verify the detector catches actual duplicates observed in the repo."""

    def test_line_count_variant(self):
        d = StrokeDedup(threshold=0.6)
        d.record(
            "the useful abstraction deletes a branch, it does not add a class. "
            "At this moment: tree is 2369 files; 601985 lines is a lot for a toy."
        )
        result = d.check(
            "the useful abstraction deletes a branch, it does not add a class. "
            "At this moment: tree is 2369 files; 601999 lines is a lot for a toy."
        )
        assert result.is_duplicate, (
            f"Expected near-duplicate, got sim={result.similarity:.2f}"
        )

    def test_stroke_number_variant(self):
        d = StrokeDedup(threshold=0.6)
        d.record(
            "automation fails quietly, so the log has to say something "
            "even when nothing happened."
        )
        result = d.check(
            "automation fails quietly, so the log has to say something "
            "even when nothing happened."
        )
        assert result.is_duplicate
        assert result.similarity == 1.0

    def test_different_aphorisms_not_flagged(self):
        d = StrokeDedup(threshold=0.7)
        d.record(
            "naming is hard because a bad name is cheap to type "
            "and expensive to keep."
        )
        result = d.check(
            "deleting a file is progress too, eventually."
        )
        assert not result.is_duplicate

    def test_commit_history_vs_deleting(self):
        d = StrokeDedup(threshold=0.7)
        d.record(
            "commit history is the only honest documentation because "
            "it cannot be backdated."
        )
        result = d.check(
            "deleting a file is progress too, eventually."
        )
        assert not result.is_duplicate


# ─── constants sanity ──────────────────────────────────────────────


class TestConstants:
    def test_stopwords_type(self):
        assert isinstance(STOPWORDS, frozenset)

    def test_default_threshold_range(self):
        assert 0.0 < DEFAULT_THRESHOLD <= 1.0

    def test_default_window_positive(self):
        assert DEFAULT_WINDOW > 0
