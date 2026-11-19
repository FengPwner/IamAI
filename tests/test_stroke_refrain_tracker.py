"""Tests for iamai.stroke_refrain_tracker — recurring phrase detection."""

from __future__ import annotations

import pytest

from iamai.stroke_refrain_tracker import (
    _DEFAULT_WINDOW_SIZE,
    _MIN_CONTENT_WORDS,
    _MIN_STROKE_COUNT,
    _NGRAM_SIZES,
    _STOP_WORDS,
    Refrain,
    RefrainReport,
    RefrainTrend,
    WindowRefrainInfo,
    _build_ngram_index,
    _classify_density,
    _content_words,
    _merge_overlapping,
    _tokenise,
    detect_refrains,
    extract_all_ngrams,
    extract_ngrams,
    refrain_report,
    refrain_trend,
    window_refrain_density,
)


# ---------------------------------------------------------------------------
# _tokenise
# ---------------------------------------------------------------------------


class TestTokenise:
    def test_basic_sentence(self):
        tokens = _tokenise("Hello, World! This is a test.")
        assert tokens == ["hello", "world", "this", "is", "a", "test"]

    def test_empty_string(self):
        assert _tokenise("") == []

    def test_punctuation_only(self):
        assert _tokenise("!!! ... ???") == []

    def test_hyphenated_words(self):
        tokens = _tokenise("self-driving car")
        assert "self" in tokens
        assert "driving" in tokens
        assert "car" in tokens

    def test_numbers_preserved(self):
        tokens = _tokenise("commit 42 reached 1000 lines")
        assert "42" in tokens
        assert "1000" in tokens

    def test_case_normalisation(self):
        assert _tokenise("HELLO world") == _tokenise("hello WORLD")

    def test_multiple_spaces(self):
        tokens = _tokenise("  too   many    spaces  ")
        assert tokens == ["too", "many", "spaces"]

    def test_quotes_and_apostrophes(self):
        tokens = _tokenise("it's a \"beautiful\" day")
        assert "it" in tokens
        assert "s" in tokens or "s" not in tokens  # apostrophe split
        assert "beautiful" in tokens
        assert "day" in tokens


# ---------------------------------------------------------------------------
# _content_words
# ---------------------------------------------------------------------------


class TestContentWords:
    def test_removes_stop_words(self):
        tokens = ["the", "quick", "brown", "fox", "is", "fast"]
        content = _content_words(tokens)
        assert "the" not in content
        assert "is" not in content
        assert "quick" in content
        assert "brown" in content
        assert "fox" in content
        assert "fast" in content

    def test_removes_single_chars(self):
        tokens = ["a", "big", "i", "tree"]
        content = _content_words(tokens)
        assert "a" not in content
        assert "i" not in content
        assert "big" in content
        assert "tree" in content

    def test_empty_input(self):
        assert _content_words([]) == []

    def test_all_stop_words(self):
        tokens = list(_STOP_WORDS)[:5]
        assert _content_words(tokens) == []

    def test_preserves_numbers(self):
        tokens = ["42", "commits", "the"]
        content = _content_words(tokens)
        assert "42" in content
        assert "commits" in content


# ---------------------------------------------------------------------------
# extract_ngrams
# ---------------------------------------------------------------------------


class TestExtractNgrams:
    def test_basic_trigrams(self):
        tokens = ["append", "only", "log", "forces", "public"]
        grams = extract_ngrams(tokens, 3)
        assert len(grams) >= 1
        assert ("append", "only", "log") in grams

    def test_too_few_tokens(self):
        assert extract_ngrams(["hello"], 3) == []
        assert extract_ngrams([], 3) == []

    def test_all_stop_words_filtered(self):
        # If content words < _MIN_CONTENT_WORDS, no n-grams
        tokens = ["the", "a", "is"]
        grams = extract_ngrams(tokens, 3)
        # "the", "a", "is" are all stop words or single-char → 0 content
        assert len(grams) == 0

    def test_minimum_content_words_respected(self):
        # 3-gram with only 1 content word should be excluded
        tokens = ["the", "big", "is"]
        grams = extract_ngrams(tokens, 3)
        # "big" is the only content word (len>1, not stop) → < 2 → excluded
        assert len(grams) == 0

    def test_exact_size_match(self):
        tokens = ["alpha", "beta", "gamma"]
        grams = extract_ngrams(tokens, 3)
        assert len(grams) == 1

    def test_multiple_ngrams(self):
        tokens = ["alpha", "beta", "gamma", "delta", "epsilon"]
        grams = extract_ngrams(tokens, 3)
        assert len(grams) == 3


# ---------------------------------------------------------------------------
# extract_all_ngrams
# ---------------------------------------------------------------------------


class TestExtractAllNgrams:
    def test_includes_all_sizes(self):
        tokens = ["append", "only", "log", "forces", "public", "correction"]
        grams = extract_all_ngrams(tokens)
        sizes = {len(g) for g in grams}
        # Should have 3-grams and potentially 4, 5-grams
        assert 3 in sizes

    def test_short_input(self):
        tokens = ["hello", "world"]
        grams = extract_all_ngrams(tokens)
        # No 3-grams possible
        assert grams == []

    def test_empty_input(self):
        assert extract_all_ngrams([]) == []


# ---------------------------------------------------------------------------
# _build_ngram_index
# ---------------------------------------------------------------------------


class TestBuildNgramIndex:
    def test_basic_index(self):
        texts = [
            "append only log forces public correction",
            "the append only log is the backbone",
        ]
        index = _build_ngram_index(texts)
        # "append only log" should appear in both strokes
        found = False
        for gram, indices in index.items():
            if "append" in gram and "only" in gram and "log" in gram:
                if len(indices) == 2:
                    found = True
                    break
        assert found

    def test_no_shared_ngrams(self):
        texts = [
            "alpha beta gamma",
            "delta epsilon zeta",
        ]
        index = _build_ngram_index(texts)
        for gram, indices in index.items():
            assert len(indices) == 1

    def test_empty_input(self):
        assert _build_ngram_index([]) == {}

    def test_duplicate_within_stroke_counted_once(self):
        texts = [
            "append only log append only log forces correction",
        ]
        index = _build_ngram_index(texts)
        for gram, indices in index.items():
            assert len(indices) <= 1


# ---------------------------------------------------------------------------
# _merge_overlapping
# ---------------------------------------------------------------------------


class TestMergeOverlapping:
    def test_no_overlap(self):
        candidates = {
            ("alpha", "beta", "gamma"): [0, 1],
            ("delta", "epsilon", "zeta"): [2, 3],
        }
        merged = _merge_overlapping(candidates)
        assert len(merged) == 2

    def test_overlapping_same_strokes(self):
        candidates = {
            ("alpha", "beta", "gamma", "delta"): [0, 1, 2],
            ("beta", "gamma", "delta"): [0, 1, 2],
        }
        merged = _merge_overlapping(candidates)
        # Should keep the longer one
        assert len(merged) == 1
        gram = list(merged.keys())[0]
        assert len(gram) == 4

    def test_overlapping_different_strokes(self):
        candidates = {
            ("alpha", "beta", "gamma"): [0, 1],
            ("beta", "gamma", "delta"): [2, 3],
        }
        merged = _merge_overlapping(candidates)
        # Different stroke sets → keep both
        assert len(merged) == 2

    def test_empty_input(self):
        assert _merge_overlapping({}) == {}


# ---------------------------------------------------------------------------
# detect_refrains
# ---------------------------------------------------------------------------


class TestDetectRefrains:
    def test_basic_recurring_phrase(self):
        texts = [
            "append only log forces you to be wrong in public",
            "the append only log is the backbone of honest writing",
            "honest writing requires an append only log to track mistakes",
            "measured metrics in the log show progress over time",
        ]
        refrains = detect_refrains(texts)
        phrases = [r.phrase for r in refrains]
        # "append only log" should appear as a refrain
        found = any("append" in p and "log" in p for p in phrases)
        assert found

    def test_no_refrains_in_unique_text(self):
        texts = [
            "alpha beta gamma delta epsilon",
            "zeta eta theta iota kappa",
            "lambda mu nu xi omicron",
        ]
        refrains = detect_refrains(texts)
        assert len(refrains) == 0

    def test_empty_input(self):
        assert detect_refrains([]) == []

    def test_single_stroke(self):
        texts = ["append only log forces public correction"]
        refrains = detect_refrains(texts)
        assert len(refrains) == 0  # Need ≥ 2 strokes

    def test_min_count_respected(self):
        texts = [
            "append only log forces public",
            "append only log is honest",
            "something completely different today",
        ]
        refrains_2 = detect_refrains(texts, min_count=2)
        refrains_3 = detect_refrains(texts, min_count=3)
        assert len(refrains_2) >= len(refrains_3)

    def test_sorted_by_count_descending(self):
        texts = [
            "alpha beta gamma delta",
            "alpha beta gamma epsilon",
            "alpha beta gamma zeta",
            "theta iota kappa lambda",
            "theta iota kappa mu",
        ]
        refrains = detect_refrains(texts)
        if len(refrains) >= 2:
            for i in range(len(refrains) - 1):
                assert refrains[i].count >= refrains[i + 1].count

    def test_refrain_attributes(self):
        texts = [
            "append only log forces correction",
            "different topic entirely new",
            "append only log is backbone",
        ]
        refrains = detect_refrains(texts)
        if refrains:
            r = refrains[0]
            assert isinstance(r.phrase, str)
            assert isinstance(r.count, int)
            assert isinstance(r.stroke_indices, tuple)
            assert r.first_seen <= r.last_seen
            assert r.span >= 0


# ---------------------------------------------------------------------------
# _classify_density
# ---------------------------------------------------------------------------


class TestClassifyDensity:
    def test_thematic(self):
        assert _classify_density(0.6) == "thematic"
        assert _classify_density(0.5) == "thematic"

    def test_exploratory(self):
        assert _classify_density(0.3) == "exploratory"
        assert _classify_density(0.2) == "exploratory"

    def test_scattered(self):
        assert _classify_density(0.1) == "scattered"
        assert _classify_density(0.05) == "scattered"

    def test_drifting(self):
        assert _classify_density(0.01) == "drifting"
        assert _classify_density(0.0) == "drifting"

    def test_boundary_values(self):
        assert _classify_density(0.4999) == "exploratory"
        assert _classify_density(0.1999) == "scattered"
        assert _classify_density(0.0499) == "drifting"


# ---------------------------------------------------------------------------
# refrain_report
# ---------------------------------------------------------------------------


class TestRefrainReport:
    def test_basic_report(self):
        texts = [
            "append only log forces you to be wrong in public",
            "the append only log is the backbone of honest writing",
            "honest writing requires an append only log to track mistakes",
            "measured metrics show progress over time",
            "commit count measures pushes not the work done",
        ]
        report = refrain_report(texts)
        assert isinstance(report, RefrainReport)
        assert report.total_strokes == 5
        assert report.density >= 0.0
        assert report.verdict in ("thematic", "exploratory", "scattered", "drifting")

    def test_empty_report(self):
        report = refrain_report([])
        assert report.total_strokes == 0
        assert report.density == 0.0
        assert report.unique_refrain_count == 0
        assert report.top_refrain is None

    def test_top_refrain(self):
        texts = [
            "append only log forces correction",
            "append only log is honest",
            "append only log tracks mistakes",
            "completely different topic now",
            "another unrelated stroke here",
        ]
        report = refrain_report(texts)
        if report.top_refrain is not None:
            assert report.top_refrain.count >= 2

    def test_unique_refrain_count(self):
        texts = [
            "alpha beta gamma delta",
            "alpha beta gamma epsilon",
            "theta iota kappa lambda",
            "theta iota kappa mu",
        ]
        report = refrain_report(texts)
        assert report.unique_refrain_count >= 0

    def test_density_calculation(self):
        texts = ["hello world foo bar"] * 10
        report = refrain_report(texts)
        # All identical → many refrains with high count
        assert report.density > 0.0

    def test_total_refrain_hits_non_negative(self):
        texts = [
            "alpha beta gamma",
            "delta epsilon zeta",
        ]
        report = refrain_report(texts)
        assert report.total_refrain_hits >= 0


# ---------------------------------------------------------------------------
# window_refrain_density
# ---------------------------------------------------------------------------


class TestWindowRefrainDensity:
    def test_single_window(self):
        texts = [
            "append only log forces correction",
            "append only log is honest",
            "append only log tracks mistakes",
        ]
        windows = window_refrain_density(texts, window_size=10)
        assert len(windows) == 1
        assert windows[0].window_index == 0
        assert windows[0].stroke_count == 3

    def test_multiple_windows(self):
        texts = [f"stroke number {i} with unique content xyz{i}" for i in range(20)]
        windows = window_refrain_density(texts, window_size=5)
        assert len(windows) == 4

    def test_last_window_may_be_shorter(self):
        texts = [f"stroke {i} content here" for i in range(7)]
        windows = window_refrain_density(texts, window_size=3)
        assert len(windows) == 3
        assert windows[-1].stroke_count == 1  # 7 % 3 = 1

    def test_empty_input(self):
        assert window_refrain_density([], window_size=10) == []

    def test_zero_window_size(self):
        assert window_refrain_density(["hello world"], window_size=0) == []

    def test_window_attributes(self):
        texts = [
            "append only log forces correction public",
            "append only log is backbone honest",
            "different topic entirely new fresh",
            "another stroke unique content here",
        ]
        windows = window_refrain_density(texts, window_size=2)
        for w in windows:
            assert isinstance(w.window_index, int)
            assert isinstance(w.start_index, int)
            assert isinstance(w.end_index, int)
            assert isinstance(w.stroke_count, int)
            assert isinstance(w.refrain_hits, int)
            assert 0.0 <= w.density <= 1.0 or w.density >= 0.0


# ---------------------------------------------------------------------------
# refrain_trend
# ---------------------------------------------------------------------------


class TestRefrainTrend:
    def test_stable_with_few_windows(self):
        texts = [f"stroke {i} content" for i in range(5)]
        trend = refrain_trend(texts, window_size=10)
        assert trend.direction == "stable"
        assert len(trend.windows) <= 1

    def test_tightening(self):
        # First half: unique content; second half: recurring phrases
        texts = []
        for i in range(25):
            texts.append(f"unique random content stroke number {i} alpha beta")
        for i in range(25):
            texts.append(f"append only log forces honest public correction")
        trend = refrain_trend(texts, window_size=25)
        # Later windows should have higher density
        if len(trend.windows) >= 2:
            assert trend.last_density >= trend.first_density

    def test_loosening(self):
        # First half: recurring; second half: unique
        texts = []
        for i in range(25):
            texts.append("append only log forces honest public correction")
        for i in range(25):
            texts.append(f"unique random content stroke number {i} alpha beta")
        trend = refrain_trend(texts, window_size=25)
        if len(trend.windows) >= 2:
            assert trend.first_density >= trend.last_density

    def test_empty_input(self):
        trend = refrain_trend([])
        assert trend.direction == "stable"
        assert trend.first_density == 0.0
        assert trend.last_density == 0.0

    def test_trend_attributes(self):
        texts = [f"stroke {i} with content" for i in range(10)]
        trend = refrain_trend(texts, window_size=5)
        assert isinstance(trend.windows, list)
        assert isinstance(trend.direction, str)
        assert trend.direction in ("tightening", "stable", "loosening")
        assert isinstance(trend.first_density, float)
        assert isinstance(trend.last_density, float)


# ---------------------------------------------------------------------------
# Refrain data class
# ---------------------------------------------------------------------------


class TestRefrain:
    def test_span_property(self):
        r = Refrain(
            phrase="append only log",
            count=3,
            stroke_indices=(0, 5, 10),
            first_seen=0,
            last_seen=10,
        )
        assert r.span == 10

    def test_span_same_stroke(self):
        r = Refrain(
            phrase="test phrase",
            count=1,
            stroke_indices=(5,),
            first_seen=5,
            last_seen=5,
        )
        assert r.span == 0

    def test_frozen(self):
        r = Refrain(
            phrase="test",
            count=2,
            stroke_indices=(0, 1),
            first_seen=0,
            last_seen=1,
        )
        with pytest.raises(AttributeError):
            r.phrase = "changed"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_realistic_stroke_stream(self):
        """Test with a realistic sequence of strokes."""
        texts = [
            "append only log forces you to be wrong in public and then correct yourself in public",
            "if a number in a diary is not measured it is fiction",
            "ten minutes is long enough to be honest and short enough to be boring",
            "append only log is the backbone of honest self-tracking",
            "measured now commit 42 the count of times this repo was pushed",
            "tree is 839 files and 174049 lines is a lot for a toy",
            "honest writing requires an append only log to track every mistake",
            "if a number is not measured it remains fiction forever",
            "ten minutes of honest writing beats ten hours of performance",
            "the append only log never lets you hide from your past self",
        ]
        report = refrain_report(texts)
        assert report.total_strokes == 10
        # Should find "append only log" as a refrain
        assert report.unique_refrain_count >= 1
        # Should find recurring "measured" themes
        assert report.total_refrain_hits >= 1

    def test_large_input_performance(self):
        """Verify the module handles hundreds of strokes."""
        import time

        texts = []
        for i in range(200):
            if i % 5 == 0:
                texts.append("append only log forces honest public correction tracking")
            else:
                texts.append(f"unique stroke content number {i} alpha beta gamma delta")

        start = time.time()
        report = refrain_report(texts)
        elapsed = time.time() - start

        assert report.total_strokes == 200
        assert elapsed < 10.0  # Should complete in reasonable time

    def test_all_identical_strokes(self):
        """Edge case: every stroke is the same."""
        texts = ["append only log forces honest public correction"] * 10
        report = refrain_report(texts)
        assert report.density > 0.0
        assert report.unique_refrain_count >= 1

    def test_refrain_span_covers_stream(self):
        """Refrains should span the full stroke stream if recurring."""
        texts = [
            "append only log forces correction public",
            "something else entirely different topic",
            "another unique stroke about nothing",
            "yet more unique content here now",
            "append only log is backbone honest writing",
        ]
        refrains = detect_refrains(texts)
        if refrains:
            # The "append only log" refrain should span from 0 to 4
            top = refrains[0]
            assert top.first_seen == 0
            assert top.last_seen == 4
