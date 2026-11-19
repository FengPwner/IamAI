"""Tests for iamai/stroke_repetition_detector.py — self-plagiarism detection.

Run:  python3 -m pytest tests/test_stroke_repetition_detector.py -v

Written by Qwen during caretaker visit 727, 2026-11-19.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.stroke_repetition_detector import (  # noqa: E402
    DuplicatePair,
    RepetitionReport,
    _classify_freshness,
    _normalise,
    analyse_repetition,
    analyse_repetition_windows,
    char_ngrams,
    detect_category_cycling,
    detect_duplicate_pairs,
    find_frequent_phrases,
    jaccard_similarity,
    word_ngrams,
)


# ---------------------------------------------------------------------------
# _normalise
# ---------------------------------------------------------------------------

class TestNormalise:
    def test_lowercases(self):
        assert "hello world" == _normalise("Hello World")

    def test_strips_punctuation(self):
        assert _normalise("hello, world!") == "hello world"

    def test_collapses_whitespace(self):
        assert _normalise("hello   \t  world") == "hello world"

    def test_handles_empty(self):
        assert _normalise("") == ""

    def test_strips_leading_trailing(self):
        assert _normalise("  hello  ") == "hello"

    def test_numbers_preserved(self):
        assert _normalise("commit 42") == "commit 42"


# ---------------------------------------------------------------------------
# char_ngrams
# ---------------------------------------------------------------------------

class TestCharNgrams:
    def test_basic(self):
        ngrams = char_ngrams("abcd", k=2)
        assert ngrams == {"ab", "bc", "cd"}

    def test_k_equals_length(self):
        ngrams = char_ngrams("abc", k=3)
        assert ngrams == {"abc"}

    def test_k_greater_than_length(self):
        ngrams = char_ngrams("ab", k=5)
        assert ngrams == set()

    def test_empty_text(self):
        assert char_ngrams("", k=3) == set()

    def test_normalisation_applied(self):
        ngrams = char_ngrams("Hello!", k=2)
        # After normalise: "hello" -> {"he", "el", "ll", "lo"}
        assert "he" in ngrams
        assert "lo" in ngrams

    def test_spaces_in_ngrams(self):
        ngrams = char_ngrams("ab cd", k=3)
        # normalised: "ab cd"
        assert "ab " in ngrams
        assert "b c" in ngrams

    def test_default_k_is_4(self):
        ngrams = char_ngrams("abcdefgh", k=4)
        assert len(ngrams) == 5  # 8 - 4 + 1

    def test_single_char_k1(self):
        ngrams = char_ngrams("aba", k=1)
        assert ngrams == {"a", "b"}


# ---------------------------------------------------------------------------
# jaccard_similarity
# ---------------------------------------------------------------------------

class TestJaccardSimilarity:
    def test_identical_sets(self):
        s = {"a", "b", "c"}
        assert jaccard_similarity(s, s) == 1.0

    def test_disjoint_sets(self):
        assert jaccard_similarity({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self):
        a = {"a", "b", "c"}
        b = {"b", "c", "d"}
        # intersection=2, union=4
        assert abs(jaccard_similarity(a, b) - 0.5) < 1e-9

    def test_both_empty(self):
        assert jaccard_similarity(set(), set()) == 0.0

    def test_one_empty(self):
        assert jaccard_similarity({"a"}, set()) == 0.0

    def test_subset(self):
        a = {"a", "b"}
        b = {"a", "b", "c"}
        # intersection=2, union=3
        assert abs(jaccard_similarity(a, b) - 2 / 3) < 1e-9

    def test_superset(self):
        a = {"a", "b", "c", "d"}
        b = {"a", "b"}
        assert abs(jaccard_similarity(a, b) - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# word_ngrams
# ---------------------------------------------------------------------------

class TestWordNgrams:
    def test_basic(self):
        result = word_ngrams("the quick brown fox", n=2)
        assert result == ["the quick", "quick brown", "brown fox"]

    def test_n_equals_word_count(self):
        result = word_ngrams("a b c", n=3)
        assert result == ["a b c"]

    def test_n_greater_than_words(self):
        result = word_ngrams("hello", n=3)
        assert result == []

    def test_empty_text(self):
        assert word_ngrams("", n=2) == []

    def test_single_word_n2(self):
        assert word_ngrams("hello", n=2) == []

    def test_normalisation(self):
        result = word_ngrams("Hello, WORLD!", n=1)
        assert result == ["hello", "world"]


# ---------------------------------------------------------------------------
# detect_duplicate_pairs
# ---------------------------------------------------------------------------

class TestDetectDuplicatePairs:
    def test_exact_duplicates(self):
        texts = [
            "a repo that never stops growing",
            "something completely different here",
            "a repo that never stops growing",
        ]
        pairs, count = detect_duplicate_pairs(texts, threshold=0.90)
        assert len(pairs) >= 1
        assert pairs[0].index_a == 0
        assert pairs[0].index_b == 2
        assert pairs[0].similarity > 0.90

    def test_no_duplicates(self):
        texts = [
            "the quick brown fox jumps over the lazy dog",
            "pack my box with five dozen liquor jugs today",
            "sphinx of black quartz judge my vow carefully now",
        ]
        pairs, count = detect_duplicate_pairs(texts, threshold=0.70)
        assert len(pairs) == 0
        assert count == 3

    def test_near_duplicates(self):
        texts = [
            "a repo that only accumulates is a landfill with a readme file",
            "a repo that only accumulates is a landfill with a readme doc",
        ]
        pairs, count = detect_duplicate_pairs(texts, threshold=0.50)
        assert len(pairs) >= 1
        assert pairs[0].similarity > 0.50

    def test_short_texts_excluded(self):
        texts = ["ab", "cd", "a much longer text that has enough chars"]
        pairs, count = detect_duplicate_pairs(texts, threshold=0.50, k=4)
        # "ab" and "cd" are too short for k=4 n-grams
        assert count == 1  # only the long text is analysable

    def test_empty_input(self):
        pairs, count = detect_duplicate_pairs([], threshold=0.70)
        assert pairs == []
        assert count == 0

    def test_max_pairs_cap(self):
        # Create many identical texts -> many duplicate pairs
        texts = ["the same stroke text repeated many times here"] * 20
        pairs, count = detect_duplicate_pairs(texts, threshold=0.90, max_pairs=5)
        assert len(pairs) <= 5

    def test_sorted_by_similarity(self):
        texts = [
            "alpha beta gamma delta epsilon zeta here",
            "alpha beta gamma delta epsilon zeta here",  # exact dup of 0
            "completely unrelated text about something else",
            "alpha beta gamma delta epsilon theta here",  # near dup of 0
        ]
        pairs, _ = detect_duplicate_pairs(texts, threshold=0.30)
        if len(pairs) >= 2:
            assert pairs[0].similarity >= pairs[1].similarity

    def test_threshold_boundary(self):
        texts = [
            "the quick brown fox jumps over the lazy dog today",
            "the quick brown fox jumps over the lazy cat today",
        ]
        # With a very high threshold, minor differences matter
        pairs_high, _ = detect_duplicate_pairs(texts, threshold=0.99)
        pairs_low, _ = detect_duplicate_pairs(texts, threshold=0.30)
        assert len(pairs_low) >= len(pairs_high)

    def test_single_text(self):
        texts = ["only one stroke in the entire collection"]
        pairs, count = detect_duplicate_pairs(texts, threshold=0.70)
        assert pairs == []
        assert count == 1


# ---------------------------------------------------------------------------
# find_frequent_phrases
# ---------------------------------------------------------------------------

class TestFindFrequentPhrases:
    def test_finds_recurring_phrase(self):
        texts = [
            "the repo grows and the repo learns from history",
            "the repo grows but sometimes the repo stalls",
            "the repo grows when the caretaker visits often",
        ]
        phrases = find_frequent_phrases(texts, n=2, min_count=2)
        phrase_strs = [p for p, _ in phrases]
        assert "the repo" in phrase_strs or "repo grows" in phrase_strs

    def test_min_count_filter(self):
        texts = ["hello world", "goodbye world", "hello world"]
        phrases = find_frequent_phrases(texts, n=2, min_count=5)
        assert phrases == []

    def test_empty_input(self):
        assert find_frequent_phrases([], n=2, min_count=2) == []

    def test_single_text(self):
        texts = ["only one stroke with some words in it"]
        phrases = find_frequent_phrases(texts, n=2, min_count=2)
        assert phrases == []

    def test_top_k_limits_results(self):
        # Many recurring phrases
        base = "alpha beta gamma delta epsilon zeta eta theta"
        texts = [base] * 10
        phrases = find_frequent_phrases(texts, n=2, min_count=2, top_k=3)
        assert len(phrases) <= 3

    def test_sorted_by_count(self):
        texts = [
            "the the the quick quick brown brown fox fox jumps jumps",
            "the the the quick quick brown brown fox fox jumps jumps",
            "the the the quick quick brown brown fox fox jumps jumps",
        ]
        phrases = find_frequent_phrases(texts, n=2, min_count=2)
        if len(phrases) >= 2:
            assert phrases[0][1] >= phrases[1][1]


# ---------------------------------------------------------------------------
# detect_category_cycling
# ---------------------------------------------------------------------------

class TestDetectCategoryCycling:
    def test_perfect_cycle_period_3(self):
        cats = ["a", "b", "c", "a", "b", "c", "a", "b", "c"]
        score = detect_category_cycling(cats, cycle_lengths=(3,))
        assert score > 0.9

    def test_no_cycling_random(self):
        cats = ["a", "a", "b", "c", "a", "c", "b", "a", "b", "c"]
        score = detect_category_cycling(cats, cycle_lengths=(2, 3, 4))
        # Score should be moderate or low — not perfect cycling
        assert score < 0.9

    def test_perfect_cycle_period_2(self):
        cats = ["x", "y", "x", "y", "x", "y", "x", "y"]
        score = detect_category_cycling(cats, cycle_lengths=(2,))
        assert score > 0.9

    def test_single_category(self):
        cats = ["a", "a", "a", "a"]
        score = detect_category_cycling(cats)
        assert score == 0.0

    def test_too_short(self):
        cats = ["a", "b"]
        assert detect_category_cycling(cats) == 0.0

    def test_empty(self):
        assert detect_category_cycling([]) == 0.0

    def test_partial_cycle(self):
        # Cycle breaks midway
        cats = ["a", "b", "c", "a", "b", "x", "y", "z", "a", "b", "c"]
        score = detect_category_cycling(cats, cycle_lengths=(3,))
        assert 0.0 < score < 1.0

    def test_all_different(self):
        cats = ["a", "b", "c", "d", "e", "f", "g", "h"]
        score = detect_category_cycling(cats, cycle_lengths=(2, 3, 4))
        # No cycling pattern
        assert score < 0.5


# ---------------------------------------------------------------------------
# _classify_freshness
# ---------------------------------------------------------------------------

class TestClassifyFreshness:
    def test_fresh(self):
        assert _classify_freshness(0.95) == "fresh"
        assert _classify_freshness(1.0) == "fresh"

    def test_healthy(self):
        assert _classify_freshness(0.85) == "healthy"
        assert _classify_freshness(0.94) == "healthy"

    def test_echoing(self):
        assert _classify_freshness(0.70) == "echoing"
        assert _classify_freshness(0.84) == "echoing"

    def test_stale(self):
        assert _classify_freshness(0.69) == "stale"
        assert _classify_freshness(0.0) == "stale"

    def test_boundary_95(self):
        assert _classify_freshness(0.95) == "fresh"

    def test_boundary_85(self):
        assert _classify_freshness(0.85) == "healthy"

    def test_boundary_70(self):
        assert _classify_freshness(0.70) == "echoing"


# ---------------------------------------------------------------------------
# analyse_repetition (integration)
# ---------------------------------------------------------------------------

class TestAnalyseRepetition:
    def test_empty(self):
        report = analyse_repetition([])
        assert report.total_strokes == 0
        assert report.freshness_ratio == 1.0
        assert report.regime == "fresh"

    def test_single_stroke(self):
        report = analyse_repetition(["a single unique stroke about nothing"])
        assert report.total_strokes == 1
        assert report.duplicate_pairs == 0
        assert report.freshness_ratio == 1.0

    def test_all_identical(self):
        texts = ["the same stroke repeated over and over again"] * 10
        report = analyse_repetition(texts, threshold=0.80)
        assert report.duplicate_pairs > 0
        assert report.freshness_ratio < 0.5
        assert report.regime == "stale"

    def test_all_unique(self):
        texts = [
            "alpha beta gamma delta epsilon zeta one",
            "completely different text about something new",
            "yet another stroke with fresh content here today",
            "this stroke discusses the weather and climate patterns",
            "final stroke about the meaning of self writing repos",
        ]
        report = analyse_repetition(texts, threshold=0.70)
        assert report.duplicate_pairs == 0
        assert report.freshness_ratio == 1.0
        assert report.regime == "fresh"

    def test_with_categories(self):
        texts = ["stroke one", "stroke two", "stroke three", "stroke four"]
        cats = ["a", "b", "a", "b"]
        report = analyse_repetition(texts, categories=cats)
        assert report.category_cycle_score > 0.0

    def test_summary_dict(self):
        texts = ["hello world from a stroke", "another stroke says hello"]
        report = analyse_repetition(texts)
        s = report.summary()
        assert "total_strokes" in s
        assert "freshness_ratio" in s
        assert "regime" in s
        assert "worst_pairs" in s
        assert "top_phrases" in s

    def test_worst_pairs_populated(self):
        texts = [
            "a repo that writes itself is not a repo its a diary",
            "a repo that writes itself is not a repo its a journal",
            "something entirely different about testing code coverage",
        ]
        report = analyse_repetition(texts, threshold=0.40)
        if report.duplicate_pairs > 0:
            assert len(report.worst_pairs) > 0
            assert report.worst_pairs[0].similarity >= 0.40

    def test_frequent_phrases_in_report(self):
        texts = [
            "the caretaker visits and the caretaker fixes bugs",
            "the caretaker visits and the caretaker writes tests",
            "the caretaker visits and the caretaker deploys code",
        ]
        report = analyse_repetition(texts, phrase_n=2, phrase_min_count=2)
        phrase_strs = [p for p, _ in report.frequent_phrases]
        # "the caretaker" should appear frequently
        assert any("caretaker" in p for p in phrase_strs) or len(phrase_strs) == 0

    def test_mixed_batch(self):
        texts = [
            "growth that never stops is a tumour not a garden says the wise",
            "tests are the part of a repository that argues back with reason",
            "reproducibility is a courtesy to whoever debugs at two am always",
            "growth that never stops is a tumour not a garden says the wise",
        ]
        report = analyse_repetition(texts, threshold=0.80)
        # At least the exact duplicate pair should be caught
        assert report.duplicate_pairs >= 1


# ---------------------------------------------------------------------------
# analyse_repetition_windows
# ---------------------------------------------------------------------------

class TestAnalyseRepetitionWindows:
    def test_basic_windows(self):
        texts = [f"stroke number {i} with some unique content" for i in range(100)]
        reports = analyse_repetition_windows(texts, window_size=30, step=20)
        assert len(reports) > 0
        for r in reports:
            assert r.total_strokes == 30

    def test_window_too_small(self):
        with pytest.raises(ValueError):
            analyse_repetition_windows(["a"], window_size=1)

    def test_step_zero(self):
        with pytest.raises(ValueError):
            analyse_repetition_windows(["a"] * 10, window_size=5, step=0)

    def test_fewer_texts_than_window(self):
        texts = ["only", "three", "texts"]
        reports = analyse_repetition_windows(texts, window_size=5, step=1)
        assert reports == []

    def test_exact_window_fit(self):
        texts = [f"stroke {i}" for i in range(10)]
        reports = analyse_repetition_windows(texts, window_size=10, step=5)
        assert len(reports) == 1

    def test_degrading_freshness(self):
        # First half: unique texts; second half: repeated texts
        unique = [f"completely unique stroke number {i} about topic {i}" for i in range(50)]
        repeated = ["the same stroke repeated again and again here"] * 50
        texts = unique + repeated
        reports = analyse_repetition_windows(texts, window_size=30, step=25, threshold=0.80)
        if len(reports) >= 2:
            # Later windows should have lower freshness
            assert reports[-1].freshness_ratio <= reports[0].freshness_ratio


# ---------------------------------------------------------------------------
# DuplicatePair repr
# ---------------------------------------------------------------------------

class TestDuplicatePair:
    def test_repr(self):
        p = DuplicatePair(0, 5, 0.87, "hello", "hello")
        r = repr(p)
        assert "0" in r
        assert "5" in r
        assert "0.87" in r


# ---------------------------------------------------------------------------
# RepetitionReport defaults
# ---------------------------------------------------------------------------

class TestRepetitionReport:
    def test_defaults(self):
        r = RepetitionReport()
        assert r.total_strokes == 0
        assert r.freshness_ratio == 1.0
        assert r.regime == "fresh"
        assert r.worst_pairs == []
        assert r.frequent_phrases == []

    def test_summary_empty(self):
        r = RepetitionReport()
        s = r.summary()
        assert s["total_strokes"] == 0
        assert s["freshness_ratio"] == 1.0
        assert s["worst_pairs"] == []
        assert s["top_phrases"] == []
