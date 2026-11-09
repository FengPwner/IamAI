"""Tests for iamai.stroke_diversity — 42 test cases."""

import math
import pytest

from iamai.stroke_diversity import (
    KNOWN_CATEGORIES,
    _category_of,
    _empty_report,
    analyse_strokes,
    brief,
)


# ── helpers ────────────────────────────────────────────────────────────

def _make_strokes(counts: dict) -> list:
    """Build a list of stroke dicts from ``{category: count}``."""
    out = []
    for kind, n in counts.items():
        for _ in range(n):
            out.append({"kind": kind, "seq": len(out)})
    return out


def _uniform(count_per_cat: int = 10) -> list:
    return _make_strokes({c: count_per_cat for c in sorted(KNOWN_CATEGORIES)})


# ── _category_of ───────────────────────────────────────────────────────

class TestCategoryOf:
    def test_dict_kind(self):
        assert _category_of({"kind": "note"}) == "note"

    def test_dict_category_key(self):
        assert _category_of({"category": "devlog"}) == "devlog"

    def test_dict_missing_keys(self):
        assert _category_of({}) == "unknown"

    def test_tuple_format(self):
        assert _category_of(("2026-01-01", "metrics", "data")) == "metrics"

    def test_single_element_tuple(self):
        assert _category_of(("lonely",)) == "unknown"

    def test_plain_string(self):
        assert _category_of("snippet") == "unknown"

    def test_none(self):
        assert _category_of(None) == "unknown"


# ── analyse_strokes — empty / edge cases ───────────────────────────────

class TestEmptyInput:
    def test_empty_list(self):
        r = analyse_strokes([])
        assert r["verdict"] == "EMPTY"
        assert r["sample_size"] == 0

    def test_none_window_zero(self):
        r = analyse_strokes([], window=0)
        assert r["verdict"] == "EMPTY"

    def test_empty_report_helper(self):
        r = _empty_report(KNOWN_CATEGORIES)
        assert r["shannon_entropy"] == 0.0
        assert r["richness"] == 0.0
        assert r["verdict"] == "EMPTY"


# ── Shannon entropy ────────────────────────────────────────────────────

class TestShannonEntropy:
    def test_perfect_uniform(self):
        strokes = _uniform(50)
        r = analyse_strokes(strokes)
        assert r["shannon_entropy"] == pytest.approx(1.0, abs=0.01)

    def test_single_category(self):
        strokes = _make_strokes({"metrics": 100})
        r = analyse_strokes(strokes)
        assert r["shannon_entropy"] == 0.0

    def test_two_categories_equal(self):
        strokes = _make_strokes({"note": 50, "snippet": 50})
        r = analyse_strokes(strokes)
        assert r["shannon_entropy"] == pytest.approx(1.0, abs=0.01)

    def test_skewed_distribution(self):
        strokes = _make_strokes({"metrics": 90, "note": 5, "snippet": 5})
        r = analyse_strokes(strokes)
        assert r["shannon_entropy"] < 0.5

    def test_entropy_bounded(self):
        strokes = _uniform(20)
        r = analyse_strokes(strokes)
        assert 0.0 <= r["shannon_entropy"] <= 1.0


# ── Richness ───────────────────────────────────────────────────────────

class TestRichness:
    def test_all_categories_present(self):
        strokes = _uniform(5)
        r = analyse_strokes(strokes)
        assert r["richness"] == 1.0

    def test_one_category(self):
        strokes = _make_strokes({"garden": 30})
        r = analyse_strokes(strokes)
        assert r["richness"] == pytest.approx(1.0 / len(KNOWN_CATEGORIES), abs=0.01)

    def test_three_of_seven(self):
        strokes = _make_strokes({"note": 10, "devlog": 10, "thought": 10})
        r = analyse_strokes(strokes)
        assert r["richness"] == pytest.approx(3.0 / len(KNOWN_CATEGORIES), abs=0.01)

    def test_unknown_category_not_counted(self):
        strokes = [{"kind": "alien"}] + _make_strokes({"note": 5})
        r = analyse_strokes(strokes)
        assert r["richness"] == pytest.approx(1.0 / len(KNOWN_CATEGORIES), abs=0.01)


# ── Dominance ──────────────────────────────────────────────────────────

class TestDominance:
    def test_single_category_dominance(self):
        strokes = _make_strokes({"thought": 100})
        r = analyse_strokes(strokes)
        assert r["dominance"] == 1.0

    def test_uniform_dominance(self):
        strokes = _uniform(10)
        n = len(KNOWN_CATEGORIES)
        r = analyse_strokes(strokes)
        assert r["dominance"] == pytest.approx(1.0 / n, abs=0.01)

    def test_slightly_skewed(self):
        strokes = _make_strokes({"note": 14, "snippet": 6})
        r = analyse_strokes(strokes)
        assert r["dominance"] == 0.70

    def test_dominance_range(self):
        strokes = _uniform(7)
        r = analyse_strokes(strokes)
        assert 0.0 < r["dominance"] <= 1.0


# ── Evenness ───────────────────────────────────────────────────────────

class TestEvenness:
    def test_perfect_evenness(self):
        strokes = _uniform(20)
        r = analyse_strokes(strokes)
        assert r["evenness"] == pytest.approx(1.0, abs=0.01)

    def test_single_category_evenness(self):
        strokes = _make_strokes({"reading": 50})
        r = analyse_strokes(strokes)
        assert r["evenness"] == 0.0

    def test_two_categories_equal(self):
        strokes = _make_strokes({"metrics": 50, "garden": 50})
        r = analyse_strokes(strokes)
        assert r["evenness"] == pytest.approx(1.0, abs=0.01)

    def test_evenness_bounded(self):
        strokes = _make_strokes({"note": 30, "devlog": 20, "thought": 10})
        r = analyse_strokes(strokes)
        assert 0.0 <= r["evenness"] <= 1.0


# ── Diversity score ────────────────────────────────────────────────────

class TestDiversityScore:
    def test_perfect_score(self):
        strokes = _uniform(50)
        r = analyse_strokes(strokes)
        assert r["diversity_score"] >= 0.90

    def test_worst_score(self):
        strokes = _make_strokes({"metrics": 200})
        r = analyse_strokes(strokes)
        assert r["diversity_score"] < 0.35

    def test_score_range(self):
        strokes = _make_strokes({"note": 40, "devlog": 30, "thought": 20, "garden": 10})
        r = analyse_strokes(strokes)
        assert 0.0 <= r["diversity_score"] <= 1.0

    def test_score_increases_with_variety(self):
        low = _make_strokes({"note": 80, "snippet": 20})
        high = _make_strokes({"note": 20, "snippet": 20, "thought": 20, "devlog": 20, "garden": 20})
        assert analyse_strokes(low)["diversity_score"] < analyse_strokes(high)["diversity_score"]


# ── Verdict ────────────────────────────────────────────────────────────

class TestVerdict:
    def test_healthy(self):
        strokes = _uniform(30)
        r = analyse_strokes(strokes)
        assert r["verdict"] == "HEALTHY"

    def test_monotone(self):
        strokes = _make_strokes({"metrics": 200})
        r = analyse_strokes(strokes)
        assert r["verdict"] == "MONOTONE"

    def test_empty_verdict(self):
        r = analyse_strokes([])
        assert r["verdict"] == "EMPTY"

    def test_narrow(self):
        strokes = _make_strokes({"note": 70, "snippet": 30})
        r = analyse_strokes(strokes)
        assert r["verdict"] in ("FAIR", "NARROW")

    def test_all_verdicts_are_strings(self):
        for data in [
            _uniform(10),
            _make_strokes({"note": 100}),
            _make_strokes({"note": 50, "devlog": 50}),
            [],
        ]:
            r = analyse_strokes(data)
            assert isinstance(r["verdict"], str)


# ── Window ─────────────────────────────────────────────────────────────

class TestWindow:
    def test_window_limits_scope(self):
        big = _uniform(100)
        r = analyse_strokes(big, window=10)
        assert r["sample_size"] == 10

    def test_window_none_uses_all(self):
        big = _uniform(10)
        r = analyse_strokes(big)
        assert r["sample_size"] == len(KNOWN_CATEGORIES) * 10

    def test_window_larger_than_data(self):
        small = _uniform(5)
        r = analyse_strokes(small, window=10000)
        assert r["sample_size"] == len(KNOWN_CATEGORIES) * 5


# ── Custom categories ──────────────────────────────────────────────────

class TestCustomCategories:
    def test_custom_frozenset(self):
        custom = frozenset({"alpha", "beta"})
        strokes = [{"kind": "alpha"}, {"kind": "beta"}] * 25
        r = analyse_strokes(strokes, known_categories=custom)
        assert r["richness"] == 1.0

    def test_custom_single(self):
        custom = frozenset({"only"})
        strokes = [{"kind": "only"}] * 10
        r = analyse_strokes(strokes, known_categories=custom)
        assert r["richness"] == 1.0


# ── Distribution dict ──────────────────────────────────────────────────

class TestDistribution:
    def test_distribution_matches_input(self):
        strokes = _make_strokes({"note": 7, "devlog": 3})
        r = analyse_strokes(strokes)
        assert r["distribution"]["note"] == 7
        assert r["distribution"]["devlog"] == 3

    def test_distribution_sorted_desc(self):
        strokes = _make_strokes({"a": 1, "b": 5, "c": 3})
        r = analyse_strokes(strokes, known_categories=frozenset({"a", "b", "c"}))
        keys = list(r["distribution"].keys())
        assert keys == ["b", "c", "a"]


# ── brief() ────────────────────────────────────────────────────────────

class TestBrief:
    def test_brief_contains_score(self):
        r = analyse_strokes(_uniform(10))
        b = brief(r)
        assert "diversity=" in b

    def test_brief_contains_verdict(self):
        r = analyse_strokes(_uniform(10))
        b = brief(r)
        assert "HEALTHY" in b

    def test_brief_empty(self):
        r = analyse_strokes([])
        b = brief(r)
        assert "0 strokes" in b

    def test_brief_shows_top_category(self):
        strokes = _make_strokes({"note": 90, "snippet": 10})
        r = analyse_strokes(strokes)
        b = brief(r)
        assert "note" in b


# ── Integration: real-like data ────────────────────────────────────────

class TestIntegration:
    def test_realistic_cadence(self):
        """Simulate 400 strokes across 7 categories with slight imbalance."""
        counts = {"metrics": 67, "note": 67, "snippet": 67, "thought": 67,
                  "devlog": 66, "garden": 66}
        strokes = _make_strokes(counts)
        r = analyse_strokes(strokes)
        assert r["verdict"] == "HEALTHY"
        assert r["diversity_score"] >= 0.80
        assert r["sample_size"] == 400

    def test_mixed_tuple_and_dict(self):
        """Ensure tuple-format strokes coexist with dict-format."""
        data = [{"kind": "note"}, ("2026-01-01", "devlog"), {"kind": "note"}]
        r = analyse_strokes(data)
        assert r["sample_size"] == 3
        assert "note" in r["distribution"]
        assert "devlog" in r["distribution"]
