"""Tests for iamai.stroke_novelty — stroke novelty detection.

Covers:
  - NoveltyVerdict enum values and string identity
  - NoveltyResult dataclass (frozen, ok property)
  - _shingles: extraction, edge cases, validation
  - _jaccard: set similarity, empty sets
  - check_novelty: fresh / repetitive / duplicate verdicts
  - Edge cases: empty candidate, empty recent, single-char strokes
  - check_batch and summary convenience functions
"""

import pytest

from iamai.stroke_novelty import (
    NoveltyResult,
    NoveltyVerdict,
    _jaccard,
    _shingles,
    check_batch,
    check_novelty,
    summary,
)


# ---------------------------------------------------------------------------
# NoveltyVerdict
# ---------------------------------------------------------------------------

class TestNoveltyVerdict:
    def test_values(self):
        assert NoveltyVerdict.FRESH == "fresh"
        assert NoveltyVerdict.REPETITIVE == "repetitive"
        assert NoveltyVerdict.DUPLICATE == "duplicate"

    def test_is_string(self):
        assert isinstance(NoveltyVerdict.FRESH, str)

    def test_all_members(self):
        assert set(NoveltyVerdict) == {
            NoveltyVerdict.FRESH,
            NoveltyVerdict.REPETITIVE,
            NoveltyVerdict.DUPLICATE,
        }


# ---------------------------------------------------------------------------
# NoveltyResult
# ---------------------------------------------------------------------------

class TestNoveltyResult:
    def test_defaults(self):
        r = NoveltyResult(verdict=NoveltyVerdict.FRESH, max_similarity=0.0, nearest_index=-1)
        assert r.similarities == []
        assert r.reasons == []

    def test_ok_property(self):
        fresh = NoveltyResult(verdict=NoveltyVerdict.FRESH, max_similarity=0.1, nearest_index=0)
        rep = NoveltyResult(verdict=NoveltyVerdict.REPETITIVE, max_similarity=0.6, nearest_index=0)
        dup = NoveltyResult(verdict=NoveltyVerdict.DUPLICATE, max_similarity=0.9, nearest_index=0)
        assert fresh.ok is True
        assert rep.ok is False
        assert dup.ok is False

    def test_frozen(self):
        r = NoveltyResult(verdict=NoveltyVerdict.FRESH, max_similarity=0.0, nearest_index=-1)
        with pytest.raises(AttributeError):
            r.max_similarity = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _shingles
# ---------------------------------------------------------------------------

class TestShingles:
    def test_basic(self):
        s = _shingles("abcdef", n=3)
        assert s == {"abc", "bcd", "cde", "def"}

    def test_single_shingle(self):
        s = _shingles("abcd", n=4)
        assert s == {"abcd"}

    def test_text_shorter_than_n(self):
        assert _shingles("ab", n=4) == set()

    def test_empty_string(self):
        assert _shingles("", n=4) == set()

    def test_whitespace_only(self):
        assert _shingles("   ", n=4) == set()

    def test_strips_whitespace(self):
        s = _shingles("  abcd  ", n=3)
        assert s == {"abc", "bcd"}

    def test_deduplication(self):
        # "abab" with n=2 → {"ab", "ba"} — the second "ab" is deduplicated
        s = _shingles("abab", n=2)
        assert s == {"ab", "ba"}

    def test_invalid_n(self):
        with pytest.raises(ValueError, match="shingle size must be >= 1"):
            _shingles("hello", n=0)

    def test_unicode(self):
        s = _shingles("你好世界", n=2)
        assert "你好" in s
        assert "好世" in s
        assert "世界" in s


# ---------------------------------------------------------------------------
# _jaccard
# ---------------------------------------------------------------------------

class TestJaccard:
    def test_identical_sets(self):
        assert _jaccard({"a", "b", "c"}, {"a", "b", "c"}) == 1.0

    def test_disjoint_sets(self):
        assert _jaccard({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial_overlap(self):
        # intersection=1, union=3 → 1/3
        assert abs(_jaccard({"a", "b"}, {"b", "c"}) - 1 / 3) < 1e-9

    def test_both_empty(self):
        assert _jaccard(set(), set()) == 0.0

    def test_one_empty(self):
        assert _jaccard({"a"}, set()) == 0.0

    def test_subset(self):
        # {"a"} ⊂ {"a", "b"} → 1/2
        assert abs(_jaccard({"a"}, {"a", "b"}) - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# check_novelty
# ---------------------------------------------------------------------------

class TestCheckNovelty:
    def test_fresh_when_no_recent(self):
        result = check_novelty("anything goes", [])
        assert result.verdict == NoveltyVerdict.FRESH
        assert result.max_similarity == 0.0
        assert result.nearest_index == -1
        assert result.ok is True

    def test_fresh_when_completely_different(self):
        recent = ["the quick brown fox jumps over the lazy dog"]
        candidate = "quantum mechanics explains wave-particle duality in photons"
        result = check_novelty(candidate, recent)
        assert result.verdict == NoveltyVerdict.FRESH
        assert result.max_similarity < 0.3

    def test_duplicate_when_nearly_identical(self):
        recent = [
            "The writer produced 400 strokes today across six kinds.",
        ]
        candidate = "The writer produced 401 strokes today across six kinds."
        result = check_novelty(candidate, recent)
        assert result.verdict == NoveltyVerdict.DUPLICATE
        assert result.max_similarity >= 0.80
        assert result.nearest_index == 0
        assert result.ok is False
        assert len(result.reasons) > 0

    def test_repetitive_when_similar_but_not_identical(self):
        recent = [
            "caretaker visit 100: all systems nominal, writer running smoothly.",
        ]
        candidate = "caretaker visit 101: systems still nominal, writer still running."
        result = check_novelty(
            candidate, recent,
            warn_threshold=0.40,
            reject_threshold=0.85,
        )
        # Should be at least repetitive with these lowered thresholds
        assert result.verdict in {NoveltyVerdict.REPETITIVE, NoveltyVerdict.DUPLICATE}
        assert result.max_similarity >= 0.40

    def test_nearest_index_points_to_most_similar(self):
        recent = [
            "completely unrelated sentence about weather",
            "the quick brown fox jumps over the lazy dog",
            "alpha beta gamma delta epsilon zeta eta theta",  # most similar
        ]
        candidate = "alpha beta gamma delta epsilon zeta eta iota"
        result = check_novelty(candidate, recent)
        assert result.nearest_index == 2
        assert result.max_similarity > 0.5

    def test_custom_thresholds(self):
        recent = ["some moderately similar text here for testing"]
        candidate = "some moderately similar text here for evaluation"
        # With very strict thresholds, even moderate similarity triggers duplicate
        result = check_novelty(candidate, recent, reject_threshold=0.30)
        assert result.verdict == NoveltyVerdict.DUPLICATE

    def test_empty_candidate(self):
        recent = ["something real"]
        result = check_novelty("", recent)
        # Empty candidate produces empty shingles → similarity 0 → fresh
        assert result.verdict == NoveltyVerdict.FRESH

    def test_all_empty(self):
        result = check_novelty("", ["", ""])
        # Both empty → Jaccard 0.0 → fresh
        assert result.verdict == NoveltyVerdict.FRESH

    def test_similarities_list_length(self):
        recent = ["a", "b", "c"]
        result = check_novelty("test", recent)
        assert len(result.similarities) == 3

    def test_reasons_empty_for_fresh(self):
        result = check_novelty("completely different text", ["nothing like it"])
        assert result.reasons == []

    def test_reasons_populated_for_duplicate(self):
        recent = ["The quick brown fox jumps over the lazy dog."]
        candidate = "The quick brown fox jumps over the lazy dog!"
        result = check_novelty(candidate, recent)
        assert any("reject threshold" in r for r in result.reasons)


# ---------------------------------------------------------------------------
# check_batch
# ---------------------------------------------------------------------------

class TestCheckBatch:
    def test_empty_batch(self):
        assert check_batch([], ["recent"]) == []

    def test_batch_length(self):
        results = check_batch(["a", "b", "c"], ["recent text"])
        assert len(results) == 3

    def test_batch_verdicts(self):
        recent = ["The writer produced 400 strokes today."]
        candidates = [
            "Quantum entanglement is a physical phenomenon.",  # fresh
            "The writer produced 400 strokes today.",          # duplicate (identical)
        ]
        results = check_batch(candidates, recent)
        assert results[0].verdict == NoveltyVerdict.FRESH
        assert results[1].verdict == NoveltyVerdict.DUPLICATE


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------

class TestSummary:
    def test_empty_batch(self):
        s = summary([], ["recent"])
        assert "0 fresh" in s
        assert "0 repetitive" in s
        assert "0 duplicate" in s
        assert "0 candidates" in s

    def test_mixed_batch(self):
        recent = ["The writer produced 400 strokes today."]
        candidates = [
            "Quantum entanglement is spooky action at a distance.",  # fresh
            "The writer produced 401 strokes today.",                # duplicate
            "Completely unrelated sentence about weather patterns.", # fresh
        ]
        s = summary(candidates, recent)
        assert "3 candidates" in s
        assert "fresh" in s

    def test_summary_format(self):
        s = summary(["hello world"], ["goodbye moon"])
        assert s.startswith("novelty:")
