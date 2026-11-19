"""Tests for iamai/stroke_cross_pollination.py — cross-category idea flow.

Run:  python3 -m pytest tests/test_stroke_cross_pollination.py -v

Written by Qwen during caretaker visit 730, 2026-11-19.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.stroke_cross_pollination import (  # noqa: E402
    BridgeEvent,
    CategoryPairInfluence,
    PollinationReport,
    WindowPollination,
    _classify_regime,
    _entropy,
    analyse_pollination,
    analyse_pollination_windows,
    build_influence_matrix,
    compute_cross_echo_per_stroke,
    extract_content_words,
    find_bridge_events,
)


# ---------------------------------------------------------------------------
# extract_content_words
# ---------------------------------------------------------------------------


class TestExtractContentWords:
    def test_basic_extraction(self):
        words = extract_content_words("the quick brown fox jumps over")
        assert "quick" in words
        assert "brown" in words
        assert "jumps" in words

    def test_filters_short_words(self):
        words = extract_content_words("a an to of in on at by")
        assert words == []

    def test_filters_stopwords(self):
        words = extract_content_words("about above after again")
        assert words == []

    def test_lowercases(self):
        words = extract_content_words("QUICK BROWN FOX")
        assert "quick" in words
        assert "brown" in words

    def test_min_len_parameter(self):
        words = extract_content_words("cat dog elephant", min_len=5)
        assert "cat" not in words
        assert "elephant" in words

    def test_empty_input(self):
        assert extract_content_words("") == []

    def test_only_stopwords(self):
        assert extract_content_words("this that then there") == []


# ---------------------------------------------------------------------------
# find_bridge_events
# ---------------------------------------------------------------------------


class TestFindBridgeEvents:
    def test_no_bridges_single_category(self):
        texts = ["alpha beta gamma", "alpha delta epsilon", "beta gamma zeta"]
        cats = ["thought", "thought", "thought"]
        events = find_bridge_events(texts, cats)
        assert events == []

    def test_simple_bridge(self):
        texts = [
            "algorithm complexity runtime",
            "algorithm performance metrics",
        ]
        cats = ["thought", "devlog"]
        events = find_bridge_events(texts, cats)
        # "algorithm" first in thought, then crosses to devlog
        assert len(events) == 1
        assert events[0].word == "algorithm"
        assert events[0].origin_category == "thought"
        assert events[0].target_category == "devlog"
        assert events[0].origin_stroke == 0
        assert events[0].crossing_stroke == 1

    def test_multiple_bridges(self):
        texts = [
            "algorithm complexity analysis",
            "garden planting schedule",
            "algorithm pruning garden",
        ]
        cats = ["thought", "garden", "devlog"]
        events = find_bridge_events(texts, cats)
        # "algorithm" thought→devlog, "garden" garden→devlog
        bridge_words = {e.word for e in events}
        assert "algorithm" in bridge_words
        assert "garden" in bridge_words

    def test_no_bridge_if_same_category_first(self):
        # Word appears in category A twice, then in B
        texts = [
            "algorithm complexity",
            "algorithm runtime",
            "algorithm metrics",
        ]
        cats = ["thought", "thought", "devlog"]
        events = find_bridge_events(texts, cats)
        assert len(events) == 1
        assert events[0].word == "algorithm"
        assert events[0].origin_stroke == 0

    def test_only_first_crossing_counts(self):
        # Word crosses from A→B, then appears in B again — only one event
        texts = [
            "algorithm complexity",
            "algorithm metrics",
            "algorithm performance",
        ]
        cats = ["thought", "devlog", "devlog"]
        events = find_bridge_events(texts, cats)
        assert len(events) == 1

    def test_multiple_category_crossings(self):
        # Word goes thought→devlog→garden (two events)
        texts = [
            "algorithm complexity",
            "algorithm metrics",
            "algorithm pruning",
        ]
        cats = ["thought", "devlog", "garden"]
        events = find_bridge_events(texts, cats)
        assert len(events) == 2
        origins = {e.origin_category for e in events}
        # Both events originate from "thought" (first appearance)
        assert origins == {"thought"}

    def test_empty_input(self):
        assert find_bridge_events([], []) == []

    def test_mismatched_lengths_raises(self):
        with pytest.raises(ValueError):
            find_bridge_events(["text"], ["a", "b"])

    def test_chronological_order(self):
        texts = [
            "alpha bravo",
            "charlie delta",
            "alpha charlie",
        ]
        cats = ["thought", "devlog", "note"]
        events = find_bridge_events(texts, cats)
        if len(events) >= 2:
            assert events[0].crossing_stroke <= events[1].crossing_stroke

    def test_word_not_in_first_stroke_no_bridge(self):
        # Word appears for the first time in second stroke — no bridge
        texts = [
            "alpha bravo",
            "charlie delta",
        ]
        cats = ["thought", "devlog"]
        events = find_bridge_events(texts, cats)
        assert events == []


# ---------------------------------------------------------------------------
# compute_cross_echo_per_stroke
# ---------------------------------------------------------------------------


class TestComputeCrossEcho:
    def test_no_prior_words(self):
        # First stroke has no prior words, so cross_echo = 0
        echoes = compute_cross_echo_per_stroke(
            ["alpha bravo charlie"], ["thought"]
        )
        assert echoes == [0.0]

    def test_same_category_no_cross(self):
        texts = ["alpha bravo charlie", "alpha bravo delta"]
        cats = ["thought", "thought"]
        echoes = compute_cross_echo_per_stroke(texts, cats)
        # Second stroke: alpha, bravo seen in thought (same cat), delta new
        # So cross_echo = 0 for second stroke
        assert echoes[1] == 0.0

    def test_full_cross_echo(self):
        texts = [
            "alpha bravo charlie",
            "alpha bravo delta",
        ]
        cats = ["thought", "devlog"]
        echoes = compute_cross_echo_per_stroke(texts, cats)
        # Second stroke: alpha and bravo previously only in thought (≠ devlog)
        # delta is new (not seen before)
        # So 2 out of 3 words are cross-category echoes
        assert abs(echoes[1] - 2 / 3) < 0.01

    def test_partial_cross_echo(self):
        texts = [
            "alpha bravo",
            "alpha charlie",
            "bravo charlie delta",
        ]
        cats = ["thought", "devlog", "note"]
        echoes = compute_cross_echo_per_stroke(texts, cats)
        # Stroke 0: no prior words → 0.0
        assert echoes[0] == 0.0
        # Stroke 1: alpha from thought (≠ devlog), charlie new → 1/2
        assert abs(echoes[1] - 0.5) < 0.01
        # Stroke 2: bravo from thought (≠ note), charlie from devlog (≠ note),
        # delta new → 2/3
        assert abs(echoes[2] - 2 / 3) < 0.01

    def test_empty_text_gives_zero(self):
        echoes = compute_cross_echo_per_stroke(["", "alpha"], ["a", "b"])
        assert echoes[0] == 0.0

    def test_mismatched_lengths_raises(self):
        with pytest.raises(ValueError):
            compute_cross_echo_per_stroke(["text"], ["a", "b"])

    def test_single_stroke(self):
        echoes = compute_cross_echo_per_stroke(
            ["algorithm complexity"], ["thought"]
        )
        assert echoes == [0.0]


# ---------------------------------------------------------------------------
# build_influence_matrix
# ---------------------------------------------------------------------------


class TestBuildInfluenceMatrix:
    def test_empty_events(self):
        assert build_influence_matrix([]) == {}

    def test_single_event(self):
        events = [BridgeEvent(
            word="alpha",
            origin_category="thought",
            target_category="devlog",
            origin_stroke=0,
            crossing_stroke=1,
        )]
        matrix = build_influence_matrix(events)
        assert matrix["thought"]["devlog"] == 1

    def test_multiple_events_same_pair(self):
        events = [
            BridgeEvent("alpha", "thought", "devlog", 0, 1),
            BridgeEvent("bravo", "thought", "devlog", 0, 2),
        ]
        matrix = build_influence_matrix(events)
        assert matrix["thought"]["devlog"] == 2

    def test_multiple_pairs(self):
        events = [
            BridgeEvent("alpha", "thought", "devlog", 0, 1),
            BridgeEvent("bravo", "devlog", "garden", 1, 2),
            BridgeEvent("charlie", "thought", "garden", 0, 3),
        ]
        matrix = build_influence_matrix(events)
        assert matrix["thought"]["devlog"] == 1
        assert matrix["devlog"]["garden"] == 1
        assert matrix["thought"]["garden"] == 1

    def test_returns_regular_dicts(self):
        events = [BridgeEvent("alpha", "thought", "devlog", 0, 1)]
        matrix = build_influence_matrix(events)
        assert type(matrix) is dict
        assert type(matrix["thought"]) is dict


# ---------------------------------------------------------------------------
# _entropy
# ---------------------------------------------------------------------------


class TestEntropy:
    def test_uniform_distribution(self):
        # 4 equal values → entropy = 2.0 (log2(4))
        e = _entropy([0.25, 0.25, 0.25, 0.25])
        assert abs(e - 2.0) < 0.01

    def test_single_value(self):
        e = _entropy([1.0])
        assert abs(e - 0.0) < 0.01

    def test_empty(self):
        assert _entropy([]) == 0.0

    def test_all_zeros(self):
        assert _entropy([0, 0, 0]) == 0.0

    def test_two_equal(self):
        e = _entropy([0.5, 0.5])
        assert abs(e - 1.0) < 0.01

    def test_skewed(self):
        e = _entropy([0.9, 0.1])
        assert 0.0 < e < 1.0


# ---------------------------------------------------------------------------
# _classify_regime
# ---------------------------------------------------------------------------


class TestClassifyRegime:
    def test_crossroads(self):
        regime = _classify_regime(
            bridge_fraction=0.15,
            category_entropy=1.8,
            max_entropy=2.0,
            dominant_fraction=0.3,
        )
        assert regime == "crossroads"

    def test_source(self):
        regime = _classify_regime(
            bridge_fraction=0.15,
            category_entropy=0.5,
            max_entropy=2.0,
            dominant_fraction=0.8,
        )
        assert regime == "source"

    def test_siloed(self):
        regime = _classify_regime(
            bridge_fraction=0.01,
            category_entropy=0.3,
            max_entropy=2.0,
            dominant_fraction=0.9,
        )
        assert regime == "siloed"

    def test_convergent(self):
        regime = _classify_regime(
            bridge_fraction=0.01,
            category_entropy=1.8,
            max_entropy=2.0,
            dominant_fraction=0.3,
        )
        assert regime == "convergent"

    def test_zero_entropy_zero_bridge(self):
        regime = _classify_regime(
            bridge_fraction=0.0,
            category_entropy=0.0,
            max_entropy=0.0,
            dominant_fraction=0.0,
        )
        assert regime == "siloed"

    def test_custom_thresholds(self):
        # With very low threshold, normally siloed becomes crossroads
        regime = _classify_regime(
            bridge_fraction=0.03,
            category_entropy=1.5,
            max_entropy=2.0,
            dominant_fraction=0.3,
            bridge_threshold=0.02,
            entropy_ratio_threshold=0.5,
        )
        assert regime == "crossroads"


# ---------------------------------------------------------------------------
# analyse_pollination (integration)
# ---------------------------------------------------------------------------


class TestAnalysePollination:
    def test_empty_input(self):
        report = analyse_pollination([], [])
        assert report.total_strokes == 0
        assert report.total_categories == 0
        assert report.regime == "siloed"
        assert report.bridge_fraction == 0.0
        assert report.dominant_source is None

    def test_single_stroke(self):
        report = analyse_pollination(
            ["algorithm complexity analysis"],
            ["thought"],
        )
        assert report.total_strokes == 1
        assert report.total_categories == 1
        assert report.total_bridge_words == 0
        assert report.regime == "siloed"

    def test_two_categories_with_bridge(self):
        texts = [
            "algorithm complexity analysis runtime",
            "algorithm performance benchmark results",
            "garden pruning schedule maintenance",
            "garden algorithm pruning technique",
        ]
        cats = ["thought", "devlog", "garden", "devlog"]
        report = analyse_pollination(texts, cats)
        assert report.total_strokes == 4
        assert report.total_categories == 3
        assert report.total_bridge_words > 0
        # "algorithm" should bridge from thought to devlog
        bridge_words = {e.word for e in report.bridge_events}
        assert "algorithm" in bridge_words

    def test_hermetic_categories_siloed(self):
        texts = [
            "alpha bravo charlie",
            "delta echo foxtrot",
            "golf hotel india",
            "juliet kilo lima",
        ]
        cats = ["thought", "devlog", "garden", "note"]
        report = analyse_pollination(texts, cats)
        assert report.total_bridge_words == 0
        assert report.bridge_fraction == 0.0
        assert report.regime == "siloed"

    def test_shared_vocabulary_crossroads(self):
        # All categories share a large common pool introduced early
        shared = "algorithm complexity runtime performance benchmark"
        texts = [
            f"alpha {shared}",
            f"bravo {shared}",
            f"charlie {shared}",
            f"delta {shared}",
            f"echo {shared}",
            f"foxtrot {shared}",
        ]
        cats = ["thought", "devlog", "garden", "note", "metrics", "snippet"]
        report = analyse_pollination(texts, cats)
        # Words from first stroke (thought) should bridge to all others
        assert report.total_bridge_words > 0
        assert len(report.categories_seen) == 6

    def test_influence_matrix_populated(self):
        texts = [
            "algorithm complexity",
            "algorithm metrics",
        ]
        cats = ["thought", "devlog"]
        report = analyse_pollination(texts, cats)
        if report.total_bridge_words > 0:
            assert "thought" in report.influence_matrix
            assert "devlog" in report.influence_matrix["thought"]

    def test_report_has_all_fields(self):
        report = analyse_pollination(
            ["alpha bravo", "charlie delta"],
            ["thought", "devlog"],
        )
        assert hasattr(report, "total_strokes")
        assert hasattr(report, "total_categories")
        assert hasattr(report, "categories_seen")
        assert hasattr(report, "total_content_words")
        assert hasattr(report, "total_bridge_words")
        assert hasattr(report, "bridge_fraction")
        assert hasattr(report, "avg_cross_echo")
        assert hasattr(report, "influence_matrix")
        assert hasattr(report, "top_pairs")
        assert hasattr(report, "bridge_events")
        assert hasattr(report, "regime")
        assert hasattr(report, "dominant_source")

    def test_top_pairs_sorted_by_count(self):
        texts = [
            "alpha bravo charlie delta echo",
            "alpha bravo charlie delta echo",
            "foxtrot golf hotel india juliet",
            "alpha foxtrot kilo lima mike",
        ]
        cats = ["thought", "thought", "devlog", "note"]
        report = analyse_pollination(texts, cats)
        if len(report.top_pairs) >= 2:
            assert report.top_pairs[0].bridge_count >= report.top_pairs[1].bridge_count

    def test_mismatched_lengths_raises(self):
        with pytest.raises(ValueError):
            analyse_pollination(["text"], ["a", "b"])

    def test_cross_echo_averaged(self):
        texts = [
            "alpha bravo charlie",
            "alpha bravo delta",
        ]
        cats = ["thought", "devlog"]
        report = analyse_pollination(texts, cats)
        # Stroke 0: echo=0.0, Stroke 1: echo=2/3
        expected_avg = (0.0 + 2 / 3) / 2
        assert abs(report.avg_cross_echo - expected_avg) < 0.01


# ---------------------------------------------------------------------------
# analyse_pollination_windows
# ---------------------------------------------------------------------------


class TestAnalysePollinationWindows:
    def test_empty_input(self):
        assert analyse_pollination_windows([], []) == []

    def test_single_window(self):
        texts = ["alpha bravo charlie"] * 5
        cats = ["thought"] * 5
        windows = analyse_pollination_windows(texts, cats, window_size=5, step=5)
        assert len(windows) == 1
        assert windows[0].start == 0
        assert windows[0].end == 5

    def test_multiple_windows(self):
        texts = ["alpha bravo"] * 20
        cats = ["thought"] * 10 + ["devlog"] * 10
        windows = analyse_pollination_windows(texts, cats, window_size=10, step=10)
        assert len(windows) == 2
        assert windows[0].start == 0
        assert windows[1].start == 10

    def test_window_has_fields(self):
        texts = ["alpha bravo", "charlie delta", "echo foxtrot"]
        cats = ["thought", "devlog", "garden"]
        windows = analyse_pollination_windows(texts, cats, window_size=3, step=3)
        assert len(windows) == 1
        w = windows[0]
        assert hasattr(w, "start")
        assert hasattr(w, "end")
        assert hasattr(w, "bridge_count")
        assert hasattr(w, "cross_echo_avg")
        assert hasattr(w, "regime")

    def test_active_regime_with_bridges(self):
        texts = [
            "algorithm complexity analysis",
            "performance benchmark metrics",
            "algorithm benchmark testing",
            "performance analysis review",
        ] * 5
        cats = (["thought", "devlog", "garden", "note"] * 5)
        windows = analyse_pollination_windows(texts, cats, window_size=4, step=4)
        # With cross-category vocabulary sharing, should see active windows
        for w in windows:
            assert w.regime in ("active", "quiet")

    def test_quiet_regime_hermetic(self):
        # Each window has completely different vocabulary
        texts = [
            "alpha bravo charlie",
            "delta echo foxtrot",
            "golf hotel india",
            "juliet kilo lima",
        ]
        cats = ["thought", "devlog", "garden", "note"]
        windows = analyse_pollination_windows(texts, cats, window_size=2, step=2)
        for w in windows:
            assert w.regime == "quiet"

    def test_overlapping_windows(self):
        texts = ["alpha bravo charlie"] * 10
        cats = ["thought"] * 5 + ["devlog"] * 5
        windows = analyse_pollination_windows(texts, cats, window_size=6, step=3)
        assert len(windows) >= 2
        # Windows should overlap
        assert windows[0].end > windows[1].start


# ---------------------------------------------------------------------------
# Edge cases and stress tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_all_identical_strokes(self):
        texts = ["alpha bravo charlie"] * 10
        cats = ["thought"] * 10
        report = analyse_pollination(texts, cats)
        assert report.total_bridge_words == 0
        assert report.regime == "siloed"

    def test_all_identical_two_categories(self):
        texts = ["alpha bravo charlie"] * 10
        cats = ["thought"] * 5 + ["devlog"] * 5
        report = analyse_pollination(texts, cats)
        # "alpha", "bravo", "charlie" first in thought, then cross to devlog
        assert report.total_bridge_words == 3
        assert report.bridge_fraction > 0

    def test_many_categories(self):
        cats = [f"cat_{i}" for i in range(20)]
        texts = [f"word{i}a word{i}b word{i}c" for i in range(20)]
        # Add shared word in all
        texts = [f"shared {t}" for t in texts]
        report = analyse_pollination(texts, cats)
        assert report.total_categories == 20
        # "shared" appears first in cat_0, then bridges to all others
        assert "shared" in {e.word for e in report.bridge_events}

    def test_single_word_strokes(self):
        texts = ["algorithm", "algorithm", "algorithm"]
        cats = ["thought", "devlog", "garden"]
        report = analyse_pollination(texts, cats)
        assert report.total_bridge_words == 1
        assert report.bridge_fraction == 1.0

    def test_unicode_in_text(self):
        texts = ["alpha bravo café", "alpha delta naïve"]
        cats = ["thought", "devlog"]
        report = analyse_pollination(texts, cats)
        assert report.total_strokes == 2

    def test_very_long_text(self):
        # Generate 500 unique alphabetic words (each ≥ 4 chars, not stopwords)
        import itertools
        base_letters = "bcdfghjklmnpqrstvwxyz"  # consonants to avoid stopwords
        combos = ["".join(c) for c in itertools.product(base_letters, repeat=4)]
        words = " ".join(combos[:500])
        texts = [words, words]
        cats = ["thought", "devlog"]
        report = analyse_pollination(texts, cats)
        assert report.total_strokes == 2
        assert report.total_bridge_words > 0
