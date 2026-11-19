"""Tests for iamai/stroke_resonance.py — forward idea propagation tracker.

Covers: extract_concepts, stroke_resonance, _classify_stream,
_half_life_trend, _alternation_score, resonance_report,
resonance_health, resonance_delta, edge cases.

Pure Python, no numpy/scipy.  Written by Qwen during caretaker visit 738,
2026-11-20.
"""

from __future__ import annotations

import statistics
import pytest

from iamai.stroke_resonance import (
    _alternation_score,
    _classify_stream,
    _half_life_trend,
    extract_concepts,
    resonance_delta,
    resonance_health,
    resonance_report,
    stroke_resonance,
)


# ── helpers ──────────────────────────────────────────────────────────────

def _texts(lines):
    """Pass-through to make test intent clear."""
    return list(lines)


# ── extract_concepts ─────────────────────────────────────────────────────

class TestExtractConcepts:
    def test_basic_extraction(self):
        result = extract_concepts("machine learning algorithms process data")
        assert result == {"machine", "learning", "algorithms", "process", "data"}

    def test_filters_short_words(self):
        result = extract_concepts("a an the big small tiny")
        assert result == {"small", "tiny"}

    def test_filters_stopwords(self):
        result = extract_concepts("that this these those with from")
        assert result == set()

    def test_empty_string(self):
        assert extract_concepts("") == set()

    def test_only_short_words(self):
        assert extract_concepts("a b c d") == set()

    def test_case_insensitive(self):
        result = extract_concepts("Machine LEARNING Algorithms")
        assert result == {"machine", "learning", "algorithms"}

    def test_hyphenated_words(self):
        result = extract_concepts("self-driving long-term well-known")
        assert "self-driving" in result
        assert "long-term" in result
        assert "well-known" in result


# ── stroke_resonance ─────────────────────────────────────────────────────

class TestStrokeResonance:
    def test_full_overlap(self):
        src = {"alpha", "beta", "gamma"}
        fwd = [{"alpha", "beta", "gamma"}] * 3
        r = stroke_resonance(src, fwd)
        assert r["forward_echo"] == 3
        assert r["resonance_score"] == 1.0

    def test_no_overlap(self):
        src = {"alpha", "beta", "gamma"}
        fwd = [{"delta", "epsilon"}, {"zeta", "eta"}, {"theta", "iota"}]
        r = stroke_resonance(src, fwd)
        assert r["forward_echo"] == 0
        assert r["resonance_score"] == 0.0

    def test_partial_overlap(self):
        src = {"alpha", "beta", "gamma"}
        fwd = [
            {"alpha", "beta", "delta"},
            {"alpha", "epsilon"},
            {"zeta", "eta"},
        ]
        r = stroke_resonance(src, fwd)
        assert r["forward_echo"] == 2
        assert r["peak_offset"] == 1
        assert r["half_life"] == 2

    def test_empty_source(self):
        r = stroke_resonance(set(), [{"alpha"}])
        assert r["forward_echo"] == 0
        assert r["resonance_score"] == 0.0

    def test_empty_forward(self):
        r = stroke_resonance({"alpha"}, [])
        assert r["forward_echo"] == 0
        assert r["half_life"] == 0

    def test_decay_curve_length(self):
        src = {"alpha", "beta"}
        fwd = [{"alpha"}, {"beta"}, {"gamma"}]
        r = stroke_resonance(src, fwd)
        assert len(r["decay_curve"]) == 3

    def test_half_life_never_decays(self):
        src = {"alpha", "beta"}
        fwd = [{"alpha", "beta"}] * 5
        r = stroke_resonance(src, fwd)
        assert r["half_life"] == 5  # never drops below 0.5

    def test_half_life_immediate(self):
        src = {"alpha", "beta"}
        fwd = [{"gamma"}, {"delta"}, {"epsilon"}]
        r = stroke_resonance(src, fwd)
        assert r["half_life"] == 1


# ── _half_life_trend ─────────────────────────────────────────────────────

class TestHalfLifeTrend:
    def test_increasing(self):
        assert _half_life_trend([1, 2, 3, 4, 5]) == "increasing"

    def test_decreasing(self):
        assert _half_life_trend([5, 4, 3, 2, 1]) == "decreasing"

    def test_stable(self):
        assert _half_life_trend([3, 3, 3, 3]) == "stable"

    def test_empty(self):
        assert _half_life_trend([]) == "stable"

    def test_two_elements(self):
        assert _half_life_trend([1, 5]) == "stable"

    def test_mostly_increasing(self):
        assert _half_life_trend([1, 2, 3, 3, 5]) == "increasing"


# ── _alternation_score ───────────────────────────────────────────────────

class TestAlternationScore:
    def test_fully_alternating(self):
        assert _alternation_score([0.8, 0.1, 0.7, 0.1, 0.8]) == 1.0

    def test_no_alternation(self):
        assert _alternation_score([0.5, 0.5, 0.5, 0.5]) == 0.0

    def test_empty(self):
        assert _alternation_score([]) == 0.0

    def test_two_elements(self):
        assert _alternation_score([0.8, 0.2]) == 0.0

    def test_partial_alternation(self):
        score = _alternation_score([0.9, 0.1, 0.8, 0.5, 0.1])
        assert 0.0 < score <= 1.0

    def test_returns_float(self):
        result = _alternation_score([0.5, 0.6, 0.4, 0.7])
        assert isinstance(result, float)


# ── _classify_stream ─────────────────────────────────────────────────────

class TestClassifyStream:
    def test_pulsing(self):
        assert _classify_stream(0.4, 0.5, "stable", 0.7) == "pulsing"

    def test_cascading(self):
        assert _classify_stream(0.3, 0.5, "increasing", 0.2) == "cascading"

    def test_resonant_by_score(self):
        assert _classify_stream(0.4, 0.5, "stable", 0.1) == "resonant"

    def test_resonant_by_ratio(self):
        assert _classify_stream(0.2, 0.7, "stable", 0.1) == "resonant"

    def test_fragmented(self):
        assert _classify_stream(0.05, 0.1, "stable", 0.1) == "fragmented"


# ── resonance_report ─────────────────────────────────────────────────────

class TestResonanceReport:
    def test_empty_input(self):
        r = resonance_report([])
        assert r["total_strokes"] == 0
        assert r["stream_pattern"] == "fragmented"
        assert r["mean_resonance"] == 0.0

    def test_single_stroke(self):
        r = resonance_report(["alpha beta gamma delta"])
        assert r["total_strokes"] == 1
        assert r["resonant_count"] == 0
        assert r["dissonant_count"] == 1

    def test_identical_strokes(self):
        texts = ["alpha beta gamma delta"] * 8
        r = resonance_report(texts, window=3)
        assert r["stream_pattern"] == "resonant"
        assert r["mean_resonance"] >= 0.85
        assert r["resonant_count"] >= 7

    def test_completely_disjoint(self):
        texts = [
            "alpha beta gamma",
            "delta epsilon zeta",
            "theta iota kappa",
            "lambda mu nu xi",
            "omicron pi rho sigma",
            "tau upsilon phi chi",
        ]
        r = resonance_report(texts, window=3)
        assert r["dissonant_count"] == 6
        assert r["mean_resonance"] == 0.0

    def test_report_keys(self):
        texts = ["alpha beta gamma"] * 5
        r = resonance_report(texts)
        expected_keys = {
            "total_strokes", "window", "per_stroke", "mean_resonance",
            "median_resonance", "resonant_count", "dissonant_count",
            "resonance_ratio", "mean_half_life", "peak_distribution",
            "stream_pattern", "top_resonant",
        }
        assert set(r.keys()) == expected_keys

    def test_per_stroke_structure(self):
        texts = ["alpha beta gamma", "alpha beta delta", "epsilon zeta"]
        r = resonance_report(texts, window=2)
        ps = r["per_stroke"][0]
        assert "stroke_index" in ps
        assert "resonance_score" in ps
        assert "forward_echo" in ps
        assert "decay_curve" in ps
        assert "half_life" in ps
        assert "is_resonant" in ps

    def test_custom_window(self):
        texts = ["alpha beta gamma"] * 10
        r = resonance_report(texts, window=2)
        assert r["window"] == 2

    def test_custom_threshold(self):
        texts = [
            "alpha beta gamma delta epsilon",
            "alpha zeta",
            "beta zeta",
            "gamma zeta",
            "delta zeta",
        ]
        r_low = resonance_report(texts, threshold=0.05)
        r_high = resonance_report(texts, threshold=0.9)
        assert r_low["resonant_count"] >= r_high["resonant_count"]

    def test_top_resonant_limit(self):
        texts = ["alpha beta gamma"] * 20
        r = resonance_report(texts)
        assert len(r["top_resonant"]) <= 5

    def test_stream_pattern_valid(self):
        texts = [
            "machine learning algorithms process data efficiently",
            "learning algorithms improve with more training data",
            "training data quality affects algorithm performance",
            "algorithm performance metrics guide optimization",
            "optimization techniques enhance learning outcomes",
            "completely unrelated thoughts about weather patterns",
            "weather forecasting uses different methods entirely",
            "sunny days make people happy in northern climates",
            "nothing connects to anything else here today",
            "random musings about coffee and afternoon naps",
        ]
        r = resonance_report(texts, window=3)
        assert r["stream_pattern"] in ("resonant", "cascading", "fragmented", "pulsing")

    def test_mixed_content(self):
        texts = [
            "alpha beta gamma",
            "alpha beta delta",
            "alpha gamma epsilon",
            "completely different topic now",
            "another unrelated subject matter",
            "yet more random content here",
        ]
        r = resonance_report(texts, window=3)
        assert r["total_strokes"] == 6
        assert 0 <= r["mean_resonance"] <= 1.0


# ── resonance_health ─────────────────────────────────────────────────────

class TestResonanceHealth:
    def test_resonant_is_coherent(self):
        assert resonance_health({"stream_pattern": "resonant"}) == "coherent"

    def test_cascading_is_building(self):
        assert resonance_health({"stream_pattern": "cascading"}) == "building"

    def test_pulsing_is_uneven(self):
        assert resonance_health({"stream_pattern": "pulsing"}) == "uneven"

    def test_fragmented_is_scattered(self):
        assert resonance_health({"stream_pattern": "fragmented"}) == "scattered"

    def test_unknown_pattern(self):
        assert resonance_health({"stream_pattern": "unknown"}) == "scattered"

    def test_missing_pattern(self):
        assert resonance_health({}) == "scattered"


# ── resonance_delta ──────────────────────────────────────────────────────

class TestResonanceDelta:
    def test_declining(self):
        early = ["alpha beta gamma"] * 5
        late = ["alpha beta gamma", "delta epsilon zeta"] * 3
        d = resonance_delta(early, late)
        assert d["delta"] < 0
        assert d["trend"] == "declining"

    def test_improving(self):
        early = ["alpha beta", "delta epsilon", "zeta eta", "theta iota", "kappa lambda"]
        late = ["alpha beta gamma"] * 5
        d = resonance_delta(early, late)
        assert d["delta"] > 0
        assert d["trend"] == "improving"

    def test_stable(self):
        texts = ["alpha beta gamma"] * 5
        d = resonance_delta(texts, texts)
        assert d["trend"] == "stable"
        assert d["delta"] == 0.0

    def test_delta_keys(self):
        texts = ["alpha beta gamma"] * 4
        d = resonance_delta(texts, texts)
        expected = {
            "earlier_mean_resonance", "earlier_pattern",
            "later_mean_resonance", "later_pattern",
            "delta", "trend",
        }
        assert set(d.keys()) == expected

    def test_custom_window(self):
        texts = ["alpha beta gamma"] * 6
        d = resonance_delta(texts, texts, window=2)
        assert d["delta"] == 0.0


# ── edge cases ───────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_all_empty_texts(self):
        texts = ["", "", ""]
        r = resonance_report(texts)
        assert r["total_strokes"] == 3
        assert r["mean_resonance"] == 0.0

    def test_two_strokes_window_larger(self):
        texts = ["alpha beta gamma", "alpha beta delta"]
        r = resonance_report(texts, window=10)
        assert r["total_strokes"] == 2

    def test_texts_with_numbers_and_symbols(self):
        texts = [
            "alpha 123 beta! gamma? delta.",
            "alpha epsilon beta zeta",
            "gamma delta eta theta",
        ]
        r = resonance_report(texts, window=2)
        assert r["total_strokes"] == 3

    def test_very_long_text(self):
        import string
        bases = [f"concept{chr(97 + i % 26)}{chr(98 + (i // 26) % 25)}{chr(99 + (i // 650) % 24)}" for i in range(500)]
        words = " ".join(bases)
        r = resonance_report([words, words, words], window=2)
        assert r["total_strokes"] == 3
        assert r["mean_resonance"] > 0

    def test_resonance_score_bounded(self):
        texts = [
            "alpha beta gamma delta epsilon",
            "alpha beta",
            "alpha",
            "completely different",
            "nothing shared at all",
        ]
        r = resonance_report(texts, window=3)
        for ps in r["per_stroke"]:
            assert 0.0 <= ps["resonance_score"] <= 1.0
