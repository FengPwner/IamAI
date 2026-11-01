#!/usr/bin/env python3
"""Tests for stroke_kind_balance.py — stroke kind distribution analysis.

Covers:
  - load_recent_strokes (windowing, malformed input, missing file)
  - kind_counts
  - shannon_entropy (edge cases, known values)
  - normalized_entropy (scaling, single kind, uniform)
  - dominance_ratio (empty, single, skewed, uniform)
  - classify (thresholds and boundary conditions)
  - health_score (range, edge cases)
  - analyze (integration, end-to-end)
  - CLI (JSON and text output)
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from unittest import mock

import pytest

# Ensure the tools directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import stroke_kind_balance as skb


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_jsonl(tmp_path: Path, strokes: list[dict]) -> Path:
    """Write a list of stroke dicts to a temporary JSONL file."""
    f = tmp_path / "strokes.jsonl"
    with open(f, "w", encoding="utf-8") as fh:
        for s in strokes:
            fh.write(json.dumps(s) + "\n")
    return f


def _make_strokes(kinds: list[str], start_seq: int = 1) -> list[dict]:
    """Create minimal stroke dicts with given kinds."""
    return [
        {"seq": start_seq + i, "kind": k, "text": f"stroke {i}", "at": "2026-01-01T00:00:00Z"}
        for i, k in enumerate(kinds)
    ]


# ===========================================================================
# load_recent_strokes
# ===========================================================================


class TestLoadRecentStrokes:
    def test_basic_loading(self, tmp_path):
        strokes = _make_strokes(["note", "thought", "devlog"])
        f = _write_jsonl(tmp_path, strokes)
        result = skb.load_recent_strokes(f, window=100)
        assert len(result) == 3
        assert result[0]["kind"] == "note"

    def test_window_truncation(self, tmp_path):
        strokes = _make_strokes(["thought"] * 50 + ["note"] * 50)
        f = _write_jsonl(tmp_path, strokes)
        result = skb.load_recent_strokes(f, window=30)
        assert len(result) == 30
        # Should be the last 30 — all "note"
        assert all(s["kind"] == "note" for s in result)

    def test_window_larger_than_file(self, tmp_path):
        strokes = _make_strokes(["note", "thought"])
        f = _write_jsonl(tmp_path, strokes)
        result = skb.load_recent_strokes(f, window=1000)
        assert len(result) == 2

    def test_empty_file(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text("")
        result = skb.load_recent_strokes(f, window=100)
        assert result == []

    def test_missing_file(self, tmp_path):
        f = tmp_path / "nonexistent.jsonl"
        result = skb.load_recent_strokes(f, window=100)
        assert result == []

    def test_malformed_lines_skipped(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text(
            '{"kind": "note", "seq": 1}\n'
            "this is not json\n"
            '{"kind": "thought", "seq": 2}\n'
            "{bad json\n"
            '{"kind": "devlog", "seq": 3}\n'
        )
        result = skb.load_recent_strokes(f, window=100)
        assert len(result) == 3
        assert [s["kind"] for s in result] == ["note", "thought", "devlog"]

    def test_blank_lines_skipped(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text(
            '{"kind": "note", "seq": 1}\n'
            "\n"
            "   \n"
            '{"kind": "thought", "seq": 2}\n'
        )
        result = skb.load_recent_strokes(f, window=100)
        assert len(result) == 2

    def test_missing_kind_field(self, tmp_path):
        """Strokes without a 'kind' key should get 'unknown' in counting."""
        strokes = [{"seq": 1, "text": "no kind"}, {"seq": 2, "kind": "note", "text": "ok"}]
        f = _write_jsonl(tmp_path, strokes)
        result = skb.load_recent_strokes(f, window=100)
        assert len(result) == 2

    def test_window_zero(self, tmp_path):
        strokes = _make_strokes(["note"] * 10)
        f = _write_jsonl(tmp_path, strokes)
        result = skb.load_recent_strokes(f, window=0)
        assert result == []

    def test_window_one(self, tmp_path):
        strokes = _make_strokes(["note", "thought", "devlog"])
        f = _write_jsonl(tmp_path, strokes)
        result = skb.load_recent_strokes(f, window=1)
        assert len(result) == 1
        assert result[0]["kind"] == "devlog"


# ===========================================================================
# kind_counts
# ===========================================================================


class TestKindCounts:
    def test_basic_counting(self):
        strokes = _make_strokes(["note", "note", "thought", "devlog"])
        counts = skb.kind_counts(strokes)
        assert counts == Counter({"note": 2, "thought": 1, "devlog": 1})

    def test_empty_list(self):
        counts = skb.kind_counts([])
        assert counts == Counter()

    def test_missing_kind_becomes_unknown(self):
        strokes = [{"seq": 1}, {"seq": 2, "kind": "note"}]
        counts = skb.kind_counts(strokes)
        assert counts["unknown"] == 1
        assert counts["note"] == 1

    def test_single_kind(self):
        strokes = _make_strokes(["thought"] * 100)
        counts = skb.kind_counts(strokes)
        assert counts == Counter({"thought": 100})

    def test_all_different_kinds(self):
        kinds = ["note", "thought", "devlog", "garden", "snippet", "metrics"]
        strokes = _make_strokes(kinds)
        counts = skb.kind_counts(strokes)
        assert len(counts) == 6
        assert all(v == 1 for v in counts.values())


# ===========================================================================
# shannon_entropy
# ===========================================================================


class TestShannonEntropy:
    def test_empty_counter(self):
        assert skb.shannon_entropy(Counter()) == 0.0

    def test_single_item(self):
        assert skb.shannon_entropy(Counter({"a": 100})) == 0.0

    def test_two_equal_items(self):
        counts = Counter({"a": 50, "b": 50})
        expected = math.log(2)  # ln(2)
        assert abs(skb.shannon_entropy(counts) - expected) < 1e-10

    def test_two_unequal_items(self):
        counts = Counter({"a": 75, "b": 25})
        # H = -0.75*ln(0.75) - 0.25*ln(0.25)
        expected = -(0.75 * math.log(0.75) + 0.25 * math.log(0.25))
        assert abs(skb.shannon_entropy(counts) - expected) < 1e-10

    def test_uniform_six_kinds(self):
        counts = Counter({k: 10 for k in "abcdef"})
        expected = math.log(6)
        assert abs(skb.shannon_entropy(counts) - expected) < 1e-10

    def test_highly_skewed(self):
        counts = Counter({"a": 999, "b": 1})
        # Should be close to 0
        ent = skb.shannon_entropy(counts)
        assert ent < 0.01

    def test_non_negative(self):
        """Entropy should never be negative."""
        for _ in range(100):
            import random
            counts = Counter({f"k{i}": random.randint(1, 1000) for i in range(5)})
            assert skb.shannon_entropy(counts) >= 0.0

    def test_increases_with_more_equal_kinds(self):
        """Adding more equally-sized categories should increase entropy."""
        ent2 = skb.shannon_entropy(Counter({"a": 50, "b": 50}))
        ent4 = skb.shannon_entropy(Counter({"a": 25, "b": 25, "c": 25, "d": 25}))
        ent6 = skb.shannon_entropy(Counter({k: 100 // 6 for k in "abcdef"}))
        assert ent2 < ent4 < ent6


# ===========================================================================
# normalized_entropy
# ===========================================================================


class TestNormalizedEntropy:
    def test_empty_counter(self):
        assert skb.normalized_entropy(Counter()) == 0.0

    def test_single_kind(self):
        assert skb.normalized_entropy(Counter({"a": 100})) == 0.0

    def test_two_equal_kinds(self):
        counts = Counter({"a": 50, "b": 50})
        assert abs(skb.normalized_entropy(counts) - 1.0) < 1e-10

    def test_uniform_six_kinds(self):
        counts = Counter({k: 10 for k in "abcdef"})
        assert abs(skb.normalized_entropy(counts) - 1.0) < 1e-10

    def test_range_zero_to_one(self):
        """Normalized entropy should always be in [0, 1]."""
        import random
        for _ in range(100):
            counts = Counter({f"k{i}": random.randint(1, 500) for i in range(random.randint(2, 10))})
            ne = skb.normalized_entropy(counts)
            assert 0.0 <= ne <= 1.0 + 1e-10

    def test_two_kinds_skewed(self):
        counts = Counter({"a": 90, "b": 10})
        ne = skb.normalized_entropy(counts)
        assert 0.0 < ne < 1.0
        assert ne < 0.5  # quite skewed

    def test_returns_zero_for_single_category(self):
        assert skb.normalized_entropy(Counter({"x": 1})) == 0.0


# ===========================================================================
# dominance_ratio
# ===========================================================================


class TestDominanceRatio:
    def test_empty_counter(self):
        assert skb.dominance_ratio(Counter()) == 0.0

    def test_single_kind(self):
        assert skb.dominance_ratio(Counter({"a": 100})) == 1.0

    def test_two_equal(self):
        assert abs(skb.dominance_ratio(Counter({"a": 50, "b": 50})) - 0.5) < 1e-10

    def test_highly_dominant(self):
        counts = Counter({"thought": 99, "note": 1})
        assert abs(skb.dominance_ratio(counts) - 0.99) < 1e-10

    def test_uniform_six(self):
        counts = Counter({k: 10 for k in "abcdef"})
        expected = 10 / 60
        assert abs(skb.dominance_ratio(counts) - expected) < 1e-10

    def test_range_zero_to_one(self):
        import random
        for _ in range(100):
            counts = Counter({f"k{i}": random.randint(1, 500) for i in range(random.randint(1, 10))})
            dr = skb.dominance_ratio(counts)
            assert 0.0 <= dr <= 1.0


# ===========================================================================
# classify
# ===========================================================================


class TestClassify:
    def test_monoculture_high_dominance(self):
        assert skb.classify(0.95, 0.1) == "monoculture"
        assert skb.classify(0.90, 0.0) == "monoculture"
        assert skb.classify(1.0, 0.0) == "monoculture"

    def test_skewed_moderate_dominance(self):
        assert skb.classify(0.75, 0.4) == "skewed"
        assert skb.classify(0.80, 0.2) == "skewed"
        assert skb.classify(0.70, 0.5) == "skewed"

    def test_skewed_low_entropy(self):
        assert skb.classify(0.60, 0.25) == "skewed"
        assert skb.classify(0.50, 0.10) == "skewed"

    def test_balanced(self):
        assert skb.classify(0.40, 0.80) == "balanced"
        assert skb.classify(0.30, 0.90) == "balanced"
        assert skb.classify(0.20, 0.95) == "balanced"

    def test_boundary_dominance_90(self):
        """Exactly 0.90 dominance should be monoculture."""
        assert skb.classify(0.90, 0.3) == "monoculture"

    def test_boundary_dominance_70(self):
        """Exactly 0.70 dominance with entropy >= 0.30 should be skewed."""
        assert skb.classify(0.70, 0.50) == "skewed"

    def test_boundary_entropy_30(self):
        """Exactly 0.30 normalized entropy with dominance < 0.70 should be skewed."""
        assert skb.classify(0.60, 0.29) == "skewed"

    def test_balanced_at_boundary(self):
        """Dominance < 0.70 and entropy >= 0.30 should be balanced."""
        assert skb.classify(0.69, 0.30) == "balanced"


# ===========================================================================
# health_score
# ===========================================================================


class TestHealthScore:
    def test_perfect_balance(self):
        """Uniform distribution should score high."""
        score = skb.health_score(1.0, 1 / 6)
        assert score >= 80

    def test_perfect_monoculture(self):
        """Single kind should score low."""
        score = skb.health_score(0.0, 1.0)
        assert score == 0

    def test_range_0_to_100(self):
        import random
        for _ in range(200):
            ne = random.random()
            dom = random.random()
            score = skb.health_score(ne, dom)
            assert 0 <= score <= 100

    def test_higher_entropy_higher_score(self):
        """With same dominance, higher entropy should give higher score."""
        s_low = skb.health_score(0.2, 0.5)
        s_high = skb.health_score(0.8, 0.5)
        assert s_high > s_low

    def test_lower_dominance_higher_score(self):
        """With same entropy, lower dominance should give higher score."""
        s_high_dom = skb.health_score(0.5, 0.9)
        s_low_dom = skb.health_score(0.5, 0.2)
        assert s_low_dom > s_high_dom

    def test_returns_integer(self):
        score = skb.health_score(0.5, 0.5)
        assert isinstance(score, int)

    def test_moderate_values(self):
        score = skb.health_score(0.5, 0.5)
        assert 10 <= score <= 60


# ===========================================================================
# analyze (integration)
# ===========================================================================


class TestAnalyze:
    def test_basic_analysis(self, tmp_path):
        strokes = _make_strokes(["note"] * 30 + ["thought"] * 30 + ["devlog"] * 40)
        f = _write_jsonl(tmp_path, strokes)
        result = skb.analyze(f, window=100)

        assert result["actual_count"] == 100
        assert result["num_kinds"] == 3
        assert result["kinds"]["devlog"] == 40
        assert result["kinds"]["note"] == 30
        assert result["kinds"]["thought"] == 30
        assert 0.0 <= result["entropy"] <= 5.0
        assert 0.0 <= result["normalized_entropy"] <= 1.0
        assert result["dominance_ratio"] == 0.4
        assert result["verdict"] in ("balanced", "skewed", "monoculture")
        assert 0 <= result["health_score"] <= 100

    def test_monoculture_analysis(self, tmp_path):
        strokes = _make_strokes(["thought"] * 100)
        f = _write_jsonl(tmp_path, strokes)
        result = skb.analyze(f, window=100)

        assert result["verdict"] == "monoculture"
        assert result["dominance_ratio"] == 1.0
        assert result["normalized_entropy"] == 0.0
        assert result["health_score"] == 0

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        result = skb.analyze(f, window=100)
        assert result["verdict"] == "empty"
        assert result["actual_count"] == 0

    def test_missing_file(self, tmp_path):
        f = tmp_path / "missing.jsonl"
        result = skb.analyze(f, window=100)
        assert result["verdict"] == "empty"

    def test_window_respected(self, tmp_path):
        strokes = _make_strokes(["note"] * 50 + ["thought"] * 50)
        f = _write_jsonl(tmp_path, strokes)
        result = skb.analyze(f, window=20)
        assert result["actual_count"] == 20
        # Last 20 are all "thought"
        assert result["verdict"] == "monoculture"

    def test_result_keys(self, tmp_path):
        strokes = _make_strokes(["note", "thought"])
        f = _write_jsonl(tmp_path, strokes)
        result = skb.analyze(f, window=100)
        expected_keys = {
            "window", "actual_count", "kinds", "num_kinds",
            "entropy", "normalized_entropy", "dominance_ratio",
            "verdict", "health_score",
        }
        assert set(result.keys()) == expected_keys

    def test_balanced_distribution(self, tmp_path):
        kinds = ["note", "thought", "devlog", "garden", "snippet", "metrics"]
        strokes = _make_strokes(kinds * 20)
        f = _write_jsonl(tmp_path, strokes)
        result = skb.analyze(f, window=120)
        assert result["verdict"] == "balanced"
        assert result["health_score"] >= 70

    def test_small_window(self, tmp_path):
        strokes = _make_strokes(["note", "thought"])
        f = _write_jsonl(tmp_path, strokes)
        result = skb.analyze(f, window=1)
        assert result["actual_count"] == 1
        assert result["verdict"] == "monoculture"


# ===========================================================================
# CLI
# ===========================================================================


class TestCLI:
    def test_json_output(self, tmp_path, capsys):
        strokes = _make_strokes(["note"] * 5 + ["thought"] * 5)
        f = _write_jsonl(tmp_path, strokes)

        with mock.patch.object(skb, "STROKES_FILE", f):
            with mock.patch("sys.argv", ["stroke_kind_balance.py", "--json"]):
                skb.main()

        output = capsys.readouterr().out
        data = json.loads(output)
        assert data["actual_count"] == 10
        assert data["num_kinds"] == 2

    def test_text_output(self, tmp_path, capsys):
        strokes = _make_strokes(["note"] * 5 + ["thought"] * 5)
        f = _write_jsonl(tmp_path, strokes)

        with mock.patch.object(skb, "STROKES_FILE", f):
            with mock.patch("sys.argv", ["stroke_kind_balance.py"]):
                skb.main()

        output = capsys.readouterr().out
        assert "stroke kind balance" in output
        assert "verdict:" in output
        assert "health score:" in output

    def test_window_argument(self, tmp_path, capsys):
        strokes = _make_strokes(["note"] * 10 + ["thought"] * 10)
        f = _write_jsonl(tmp_path, strokes)

        with mock.patch.object(skb, "STROKES_FILE", f):
            with mock.patch("sys.argv", ["stroke_kind_balance.py", "--window", "5", "--json"]):
                skb.main()

        output = capsys.readouterr().out
        data = json.loads(output)
        assert data["actual_count"] == 5
        assert data["window"] == 5

    def test_json_has_required_fields(self, tmp_path, capsys):
        strokes = _make_strokes(["note", "thought", "devlog"])
        f = _write_jsonl(tmp_path, strokes)

        with mock.patch.object(skb, "STROKES_FILE", f):
            with mock.patch("sys.argv", ["stroke_kind_balance.py", "--json"]):
                skb.main()

        output = capsys.readouterr().out
        data = json.loads(output)
        for key in ("window", "actual_count", "kinds", "entropy",
                     "normalized_entropy", "dominance_ratio", "verdict", "health_score"):
            assert key in data

    def test_empty_file_json_output(self, tmp_path, capsys):
        f = tmp_path / "empty.jsonl"
        f.write_text("")

        with mock.patch.object(skb, "STROKES_FILE", f):
            with mock.patch("sys.argv", ["stroke_kind_balance.py", "--json"]):
                skb.main()

        output = capsys.readouterr().out
        data = json.loads(output)
        assert data["verdict"] == "empty"
        assert data["actual_count"] == 0


# ===========================================================================
# Edge cases and robustness
# ===========================================================================


class TestEdgeCases:
    def test_very_large_window(self, tmp_path):
        strokes = _make_strokes(["note"] * 5)
        f = _write_jsonl(tmp_path, strokes)
        result = skb.analyze(f, window=1_000_000)
        assert result["actual_count"] == 5

    def test_unicode_kind_names(self, tmp_path):
        strokes = _make_strokes(["笔记", "思考", "日志"])
        f = _write_jsonl(tmp_path, strokes)
        result = skb.analyze(f, window=100)
        assert result["num_kinds"] == 3
        assert "笔记" in result["kinds"]

    def test_null_kind_field(self, tmp_path):
        """A stroke with kind=None should be counted as 'unknown'-ish."""
        strokes = [{"seq": 1, "kind": None, "text": "x"}]
        f = _write_jsonl(tmp_path, strokes)
        result = skb.analyze(f, window=100)
        # None gets treated as "None" string by Counter
        assert result["actual_count"] == 1

    def test_extra_fields_ignored(self, tmp_path):
        strokes = [
            {"seq": 1, "kind": "note", "text": "hello", "extra": "data", "tags": ["a"]},
            {"seq": 2, "kind": "thought", "text": "world"},
        ]
        f = _write_jsonl(tmp_path, strokes)
        result = skb.analyze(f, window=100)
        assert result["actual_count"] == 2
        assert result["num_kinds"] == 2

    def test_deterministic_output(self, tmp_path):
        """Same input should always produce same output."""
        strokes = _make_strokes(["note"] * 30 + ["thought"] * 70)
        f = _write_jsonl(tmp_path, strokes)
        r1 = skb.analyze(f, window=100)
        r2 = skb.analyze(f, window=100)
        assert r1 == r2

    def test_jsonl_with_trailing_newline(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text('{"kind": "note", "seq": 1}\n{"kind": "thought", "seq": 2}\n\n')
        result = skb.load_recent_strokes(f, window=100)
        assert len(result) == 2

    def test_mixed_valid_invalid_json(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(20):
            if i % 3 == 0:
                lines.append("not json at all")
            else:
                lines.append(json.dumps({"kind": "note", "seq": i}))
        f.write_text("\n".join(lines) + "\n")
        result = skb.load_recent_strokes(f, window=100)
        # 20 lines, indices 0,3,6,9,12,15,18 are bad = 7 bad, 13 good
        assert len(result) == 13


# ===========================================================================
# Mathematical properties
# ===========================================================================


class TestMathProperties:
    def test_entropy_adding_kind_increases(self):
        """Adding a new equally-frequent kind should increase entropy."""
        c1 = Counter({"a": 50, "b": 50})
        c2 = Counter({"a": 33, "b": 33, "c": 34})
        assert skb.shannon_entropy(c2) > skb.shannon_entropy(c1)

    def test_normalized_entropy_uniform_equals_one(self):
        """Perfectly uniform distribution should have normalized entropy = 1."""
        for n in range(2, 20):
            counts = Counter({f"k{i}": 100 for i in range(n)})
            ne = skb.normalized_entropy(counts)
            assert abs(ne - 1.0) < 1e-10, f"Failed for n={n}"

    def test_dominance_at_least_one_over_k(self):
        """Dominance ratio is always >= 1/num_kinds."""
        import random
        for _ in range(100):
            k = random.randint(2, 10)
            counts = Counter({f"k{i}": random.randint(1, 100) for i in range(k)})
            dr = skb.dominance_ratio(counts)
            assert dr >= 1.0 / k - 1e-10

    def test_health_score_monotonicity_entropy(self):
        """Increasing entropy (fixed dominance) should not decrease score."""
        # This tests the formula, not a strict mathematical property
        s1 = skb.health_score(0.3, 0.5)
        s2 = skb.health_score(0.6, 0.5)
        s3 = skb.health_score(0.9, 0.5)
        assert s1 <= s2 <= s3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
