#!/usr/bin/env python3
"""Tests for stroke_uniqueness_scorer.py — content uniqueness analysis."""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_uniqueness_scorer import (
    DuplicateCluster,
    UniquenessReport,
    _jaccard,
    _tokenize,
    find_clusters,
    score_corpus,
    score_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stroke(text: str, kind: str = "thought", seq: int = 0) -> dict:
    """Build a minimal stroke dict."""
    return {"text": text, "kind": kind, "seq": seq, "at": "2026-11-18T12:00:00+00:00"}


def _corpus(texts: list[str], kind: str = "thought") -> list[dict]:
    """Build a corpus of strokes from a list of texts."""
    return [_stroke(t, kind=kind, seq=i) for i, t in enumerate(texts)]


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_empty(self):
        assert _tokenize("") == []

    def test_simple(self):
        assert _tokenize("hello world") == ["hello", "world"]

    def test_case_insensitive(self):
        assert _tokenize("Hello WORLD") == ["hello", "world"]

    def test_strip_punctuation(self):
        assert _tokenize("hello, world! how's it?") == [
            "hello", "world", "hows", "it"
        ]

    def test_extra_whitespace(self):
        assert _tokenize("  hello   world  ") == ["hello", "world"]


# ---------------------------------------------------------------------------
# _jaccard
# ---------------------------------------------------------------------------

class TestJaccard:
    def test_identical_sets(self):
        s = {"hello", "world"}
        assert _jaccard(s, s) == 1.0

    def test_disjoint_sets(self):
        assert _jaccard({"hello"}, {"world"}) == 0.0

    def test_partial_overlap(self):
        a = {"hello", "world", "foo"}
        b = {"hello", "world", "bar"}
        # intersection=2, union=4
        assert _jaccard(a, b) == pytest.approx(0.5)

    def test_both_empty(self):
        assert _jaccard(set(), set()) == 1.0

    def test_one_empty(self):
        assert _jaccard({"hello"}, set()) == 0.0

    def test_subset(self):
        a = {"hello", "world"}
        b = {"hello", "world", "foo", "bar"}
        assert _jaccard(a, b) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# score_text
# ---------------------------------------------------------------------------

class TestScoreText:
    def test_unique_text(self):
        corpus = ["the cat sat on the mat", "a dog ran in the park"]
        assert score_text("quantum computing is fascinating", corpus) == 1.0

    def test_exact_duplicate(self):
        corpus = ["deleting a file is progress too"]
        score = score_text("deleting a file is progress too", corpus, threshold=0.7)
        assert score == pytest.approx(0.0, abs=0.01)

    def test_near_duplicate(self):
        corpus = ["deleting a file is progress too eventually"]
        score = score_text(
            "deleting a file is progress too eventually at this moment",
            corpus,
            threshold=0.7,
        )
        assert score < 0.5  # near-duplicate detected

    def test_empty_text(self):
        corpus = ["hello world"]
        assert score_text("", corpus) == 0.0

    def test_empty_corpus(self):
        assert score_text("hello world", []) == 1.0

    def test_threshold_boundary(self):
        corpus = ["the quick brown fox jumps over the lazy dog"]
        # Same text → sim=1.0, score=0.0
        s = score_text("the quick brown fox jumps over the lazy dog", corpus, threshold=0.99)
        assert s < 0.01


# ---------------------------------------------------------------------------
# find_clusters
# ---------------------------------------------------------------------------

class TestFindClusters:
    def test_no_duplicates(self):
        strokes = _corpus([
            "hello world",
            "goodbye moon",
            "quantum physics rocks",
        ])
        clusters = find_clusters(strokes, threshold=0.7)
        assert clusters == []

    def test_exact_duplicates(self):
        strokes = _corpus([
            "deleting a file is progress too",
            "something completely different",
            "deleting a file is progress too",
        ])
        clusters = find_clusters(strokes, threshold=0.7)
        assert len(clusters) == 1
        assert clusters[0].size == 2
        assert 0 in clusters[0].indices
        assert 2 in clusters[0].indices

    def test_multiple_clusters(self):
        strokes = _corpus([
            "alpha beta gamma",
            "one two three",
            "alpha beta gamma",
            "one two three four",
            "completely unique",
        ])
        clusters = find_clusters(strokes, threshold=0.7)
        assert len(clusters) == 2

    def test_cluster_sorted_by_size(self):
        strokes = _corpus([
            "aaa bbb",
            "aaa bbb",
            "aaa bbb",
            "xxx yyy",
            "xxx yyy",
        ])
        clusters = find_clusters(strokes, threshold=0.7)
        assert clusters[0].size >= clusters[1].size

    def test_empty_corpus(self):
        assert find_clusters([], threshold=0.7) == []

    def test_single_stroke(self):
        strokes = _corpus(["hello world"])
        assert find_clusters(strokes, threshold=0.7) == []

    def test_empty_text_strokes(self):
        strokes = _corpus(["", "", ""])
        clusters = find_clusters(strokes, threshold=0.7)
        # empty texts have no tokens → skipped by clustering (no content to compare)
        assert len(clusters) == 0


# ---------------------------------------------------------------------------
# UniquenessReport
# ---------------------------------------------------------------------------

class TestUniquenessReport:
    def test_is_healthy_above_90(self):
        report = UniquenessReport(
            total=100, unique_count=95, dup_count=5,
            global_ratio=0.95, cluster_count=2, clusters=[],
            kind_breakdown={}, entropy=5.0, worst_offender=None,
        )
        assert report.is_healthy is True

    def test_is_healthy_below_90(self):
        report = UniquenessReport(
            total=100, unique_count=80, dup_count=20,
            global_ratio=0.80, cluster_count=5, clusters=[],
            kind_breakdown={}, entropy=4.0, worst_offender=None,
        )
        assert report.is_healthy is False

    def test_is_healthy_boundary(self):
        report = UniquenessReport(
            total=100, unique_count=90, dup_count=10,
            global_ratio=0.90, cluster_count=3, clusters=[],
            kind_breakdown={}, entropy=4.5, worst_offender=None,
        )
        assert report.is_healthy is True

    def test_clusters_of_size(self):
        clusters = [
            DuplicateCluster("a", (0, 1, 2), 3),
            DuplicateCluster("b", (3, 4), 2),
            DuplicateCluster("c", (5, 6, 7, 8), 4),
        ]
        report = UniquenessReport(
            total=10, unique_count=1, dup_count=9,
            global_ratio=0.1, cluster_count=3, clusters=clusters,
            kind_breakdown={}, entropy=3.0, worst_offender=("c", 4),
        )
        assert len(report.clusters_of_size(3)) == 2
        assert len(report.clusters_of_size(4)) == 1
        assert len(report.clusters_of_size(5)) == 0

    def test_summary_no_dups(self):
        report = UniquenessReport(
            total=50, unique_count=50, dup_count=0,
            global_ratio=1.0, cluster_count=0, clusters=[],
            kind_breakdown={}, entropy=6.0, worst_offender=None,
        )
        assert "unique" in report.summary()

    def test_summary_with_dups(self):
        report = UniquenessReport(
            total=50, unique_count=40, dup_count=10,
            global_ratio=0.80, cluster_count=3, clusters=[],
            kind_breakdown={}, entropy=4.0, worst_offender=("foo", 5),
        )
        s = report.summary()
        assert "10" in s
        assert "clusters" in s


# ---------------------------------------------------------------------------
# score_corpus
# ---------------------------------------------------------------------------

class TestScoreCorpus:
    def test_empty_corpus(self):
        report = score_corpus([])
        assert report.total == 0
        assert report.global_ratio == 1.0
        assert report.dup_count == 0
        assert report.is_healthy is True

    def test_all_unique(self):
        strokes = _corpus([
            "the cat sat on the mat",
            "a dog ran in the park",
            "quantum computing is fascinating",
            "pizza is the best food ever",
            "sunsets over the ocean are beautiful",
        ])
        report = score_corpus(strokes, threshold=0.7)
        assert report.dup_count == 0
        assert report.global_ratio == 1.0
        assert report.cluster_count == 0
        assert report.worst_offender is None

    def test_with_duplicates(self):
        strokes = _corpus([
            "deleting a file is progress too",
            "naming is hard because a bad name is cheap to type",
            "deleting a file is progress too",
            "automation fails quietly so the log has to say something",
            "naming is hard because a bad name is cheap to type",
        ])
        report = score_corpus(strokes, threshold=0.7)
        assert report.dup_count == 4
        assert report.unique_count == 1
        assert report.cluster_count == 2
        assert report.worst_offender is not None
        assert report.worst_offender[1] == 2

    def test_kind_breakdown(self):
        strokes = [
            _stroke("hello world", kind="thought", seq=0),
            _stroke("hello world", kind="thought", seq=1),
            _stroke("goodbye moon", kind="note", seq=2),
            _stroke("farewell sun", kind="note", seq=3),
        ]
        report = score_corpus(strokes, threshold=0.7)
        assert "thought" in report.kind_breakdown
        assert "note" in report.kind_breakdown
        # "hello world" is duplicated → thought uniqueness low
        assert report.kind_breakdown["thought"] < 1.0

    def test_entropy_positive(self):
        strokes = _corpus(["hello world", "goodbye moon"])
        report = score_corpus(strokes)
        assert report.entropy > 0

    def test_single_stroke(self):
        strokes = _corpus(["hello world"])
        report = score_corpus(strokes)
        assert report.total == 1
        assert report.dup_count == 0
        assert report.global_ratio == 1.0

    def test_near_duplicates_detected(self):
        strokes = _corpus([
            "deleting a file is progress too eventually",
            "deleting a file is progress too eventually at this moment",
            "something completely different about quantum physics",
        ])
        report = score_corpus(strokes, threshold=0.7)
        assert report.dup_count >= 2
        assert report.cluster_count >= 1

    def test_worst_offender_is_largest_cluster(self):
        strokes = _corpus([
            "aaa bbb ccc",
            "aaa bbb ccc",
            "xxx yyy zzz",
            "xxx yyy zzz",
            "xxx yyy zzz",
        ])
        report = score_corpus(strokes, threshold=0.7)
        assert report.worst_offender[1] == 3  # xxx cluster is largest


# ---------------------------------------------------------------------------
# Integration: realistic scenario
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_realistic_corpus(self):
        """Simulate a corpus where the writer starts repeating."""
        texts = [
            "commit history is the only honest documentation",
            "automation fails quietly so the log has to say something",
            "naming is hard because a bad name is cheap to type",
            "the useful abstraction deletes a branch not adds a class",
            "commit history is the only honest documentation",  # dup
            "deleting a file is progress too eventually",
            "automation fails quietly so the log has to say something",  # dup
            "a brand new thought about distributed systems",
            "testing is the only way to know if code works",
            "the best code is the code you never had to write",
        ]
        strokes = _corpus(texts)
        report = score_corpus(strokes, threshold=0.7)
        assert report.total == 10
        assert report.dup_count == 4  # 2 pairs of duplicates
        assert report.global_ratio == 0.6
        assert report.is_healthy is False
        assert report.cluster_count == 2

    def test_healthy_large_corpus(self):
        """A corpus with diverse content should be healthy."""
        import hashlib
        texts = [
            f"unique thought number {i} about topic {hashlib.md5(str(i).encode()).hexdigest()[:8]}"
            for i in range(100)
        ]
        strokes = _corpus(texts)
        report = score_corpus(strokes, threshold=0.7)
        assert report.is_healthy is True
        assert report.global_ratio > 0.95

    def test_duplicate_cluster_repr(self):
        """Representative text should be from the first member."""
        strokes = _corpus([
            "first occurrence of the thought",
            "something else entirely",
            "first occurrence of the thought",
        ])
        clusters = find_clusters(strokes, threshold=0.7)
        assert len(clusters) == 1
        assert clusters[0].representative == "first occurrence of the thought"

    def test_jsonl_roundtrip(self, tmp_path):
        """Test loading from a JSONL file via score_corpus."""
        path = tmp_path / "strokes.jsonl"
        strokes = [
            {"text": "hello world", "kind": "thought", "seq": 1, "at": "2026-01-01T00:00:00+00:00"},
            {"text": "hello world", "kind": "thought", "seq": 2, "at": "2026-01-01T00:00:15+00:00"},
            {"text": "goodbye moon", "kind": "note", "seq": 3, "at": "2026-01-01T00:00:30+00:00"},
        ]
        with open(path, "w") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")

        loaded = [json.loads(line) for line in open(path)]
        report = score_corpus(loaded, threshold=0.7)
        assert report.total == 3
        assert report.dup_count == 2
        assert report.unique_count == 1

    def test_threshold_sensitivity(self):
        """Higher threshold means fewer near-duplicates detected."""
        strokes = _corpus([
            "the quick brown fox jumps over the lazy dog",
            "the quick brown fox leaps over the lazy dog",
        ])
        report_low = score_corpus(strokes, threshold=0.5)
        report_high = score_corpus(strokes, threshold=0.99)
        # At low threshold, these should be flagged as duplicates
        assert report_low.dup_count >= report_high.dup_count


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_all_identical(self):
        strokes = _corpus(["same"] * 5)
        report = score_corpus(strokes, threshold=0.7)
        assert report.dup_count == 5
        assert report.unique_count == 0
        assert report.cluster_count == 1
        assert report.clusters[0].size == 5

    def test_mixed_kinds_with_dups(self):
        """Same text across different kinds still detected."""
        strokes = [
            _stroke("hello world", kind="thought", seq=0),
            _stroke("hello world", kind="note", seq=1),
            _stroke("goodbye moon", kind="thought", seq=2),
        ]
        report = score_corpus(strokes, threshold=0.7)
        assert report.dup_count == 2

    def test_very_short_texts(self):
        strokes = _corpus(["a", "a", "b", "b", "c"])
        report = score_corpus(strokes, threshold=0.7)
        assert report.dup_count == 4

    def test_long_repetitive_text(self):
        base = "the quick brown fox jumps over the lazy dog " * 10
        variant = "the quick brown fox leaps over the lazy dog " * 10
        strokes = _corpus([base, variant])
        report = score_corpus(strokes, threshold=0.7)
        # Very similar despite length
        assert report.dup_count == 2
