"""Tests for tools/stroke_kind_momentum.py — per-kind growth momentum analysis.

Run:  python3 -m pytest tests/test_stroke_kind_momentum.py -v
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import stroke_kind_momentum as skm  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_strokes(kinds: list[str], start_seq: int = 1) -> list[dict]:
    """Build a list of stroke dicts from a sequence of kind labels."""
    return [
        {
            "seq": start_seq + i,
            "at": f"2026-11-22T{(i // 60):02d}:{(i % 60):02d}:00Z",
            "kind": k,
            "text": f"stroke {start_seq + i}",
        }
        for i, k in enumerate(kinds)
    ]


def _write_jsonl(path: Path, strokes: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for s in strokes:
            fh.write(json.dumps(s) + "\n")


# ---------------------------------------------------------------------------
# load_strokes
# ---------------------------------------------------------------------------


class TestLoadStrokes:
    def test_loads_valid_jsonl(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        _write_jsonl(p, _make_strokes(["thought", "devlog", "garden"]))
        result = skm.load_strokes(p)
        assert len(result) == 3

    def test_count_limits_to_last_n(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        _write_jsonl(p, _make_strokes(["thought"] * 20))
        result = skm.load_strokes(p, count=5)
        assert len(result) == 5
        assert result[0]["seq"] == 16

    def test_missing_file_returns_empty(self, tmp_path):
        assert skm.load_strokes(tmp_path / "nope.jsonl") == []

    def test_malformed_lines_skipped(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text('{"seq": 1, "kind": "thought"}\nbad line\n{"seq": 2, "kind": "note"}\n')
        result = skm.load_strokes(p)
        assert len(result) == 2

    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        assert skm.load_strokes(p) == []

    def test_blank_lines_skipped(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text('{"seq": 1, "kind": "thought"}\n\n\n{"seq": 2, "kind": "note"}\n')
        result = skm.load_strokes(p)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# kind_counts
# ---------------------------------------------------------------------------


class TestKindCounts:
    def test_counts_each_kind(self):
        strokes = _make_strokes(["thought", "thought", "devlog", "garden"])
        counts = skm.kind_counts(strokes)
        assert counts["thought"] == 2
        assert counts["devlog"] == 1
        assert counts["garden"] == 1

    def test_empty_list(self):
        assert skm.kind_counts([]) == Counter()

    def test_unknown_kind(self):
        strokes = [{"kind": "mystery"}]
        counts = skm.kind_counts(strokes)
        assert counts["mystery"] == 1

    def test_missing_kind_key(self):
        counts = skm.kind_counts([{"text": "no kind field"}])
        assert counts["unknown"] == 1


# ---------------------------------------------------------------------------
# compute_shares
# ---------------------------------------------------------------------------


class TestComputeShares:
    def test_equal_distribution(self):
        counts = Counter({"thought": 10, "devlog": 10, "garden": 10, "note": 10, "metrics": 10, "snippet": 10})
        shares = skm.compute_shares(counts, 60)
        for k in skm.ALL_KINDS:
            assert abs(shares[k] - 1 / 6) < 1e-6

    def test_zero_total(self):
        shares = skm.compute_shares(Counter(), 0)
        assert all(v == 0.0 for v in shares.values())

    def test_single_kind(self):
        counts = Counter({"thought": 100})
        shares = skm.compute_shares(counts, 100)
        assert shares["thought"] == 1.0
        assert shares["devlog"] == 0.0

    def test_shares_sum_to_one(self):
        counts = Counter({"thought": 5, "devlog": 3, "garden": 2})
        shares = skm.compute_shares(counts, 10)
        total = sum(shares.values())
        assert abs(total - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# compute_momentum
# ---------------------------------------------------------------------------


class TestComputeMomentum:
    def test_positive_momentum(self):
        recent = {k: 0.2 for k in skm.ALL_KINDS}
        older = {k: 0.1 for k in skm.ALL_KINDS}
        older["thought"] = 0.3
        recent["thought"] = 0.5
        m = skm.compute_momentum(recent, older)
        assert m["thought"] == pytest.approx(0.2)

    def test_zero_momentum(self):
        shares = {k: 1 / 6 for k in skm.ALL_KINDS}
        m = skm.compute_momentum(shares, shares)
        for k in skm.ALL_KINDS:
            assert m[k] == pytest.approx(0.0)

    def test_negative_momentum(self):
        recent = {k: 0.1 for k in skm.ALL_KINDS}
        older = {k: 0.2 for k in skm.ALL_KINDS}
        m = skm.compute_momentum(recent, older)
        for k in skm.ALL_KINDS:
            assert m[k] < 0


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


class TestClassify:
    def test_stable(self):
        assert skm.classify(0.0) == "stable"
        assert skm.classify(0.03) == "stable"
        assert skm.classify(-0.03) == "stable"

    def test_accelerating(self):
        assert skm.classify(0.1) == "accelerating"
        assert skm.classify(0.06) == "accelerating"

    def test_decelerating(self):
        assert skm.classify(-0.1) == "decelerating"
        assert skm.classify(-0.06) == "decelerating"

    def test_boundary(self):
        assert skm.classify(0.05) == "stable"
        assert skm.classify(-0.05) == "stable"

    def test_custom_threshold(self):
        assert skm.classify(0.15, threshold=0.1) == "accelerating"
        assert skm.classify(0.05, threshold=0.1) == "stable"


# ---------------------------------------------------------------------------
# compute_deficit
# ---------------------------------------------------------------------------


class TestComputeDeficit:
    def test_equal_shares_zero_deficit(self):
        shares = {k: 1 / 6 for k in skm.ALL_KINDS}
        deficits = skm.compute_deficit(shares)
        for k in skm.ALL_KINDS:
            assert abs(deficits[k]) < 1e-6

    def test_overrepresented_negative_deficit(self):
        shares = {k: 0.0 for k in skm.ALL_KINDS}
        shares["thought"] = 1.0
        deficits = skm.compute_deficit(shares)
        assert deficits["thought"] < 0  # overrepresented
        assert deficits["devlog"] > 0  # underrepresented

    def test_deficits_sum_to_zero(self):
        shares = {"thought": 0.3, "devlog": 0.2, "garden": 0.15, "note": 0.15, "metrics": 0.1, "snippet": 0.1}
        deficits = skm.compute_deficit(shares)
        assert abs(sum(deficits.values())) < 1e-6


# ---------------------------------------------------------------------------
# analyze (integration)
# ---------------------------------------------------------------------------


class TestAnalyze:
    def test_balanced_strokes_healthy(self):
        kinds = list(skm.ALL_KINDS) * 40  # 240 strokes, perfectly balanced
        strokes = _make_strokes(kinds)
        result = skm.analyze(strokes, window=100)
        assert result["verdict"] == "healthy"
        assert not result["any_decelerating"]

    def test_imbalanced_strokes_detected(self):
        # older half: balanced
        older_kinds = list(skm.ALL_KINDS) * 20  # 120 balanced
        # recent half: only thought (extreme imbalance)
        recent_kinds = ["thought"] * 120
        strokes = _make_strokes(older_kinds + recent_kinds)
        result = skm.analyze(strokes, window=100)
        assert result["verdict"] == "imbalanced"
        assert result["any_decelerating"]

    def test_insufficient_data(self):
        strokes = _make_strokes(["thought"])
        result = skm.analyze(strokes, window=100)
        assert result["verdict"] == "insufficient_data"
        assert result["kinds"] == []

    def test_fallback_small_dataset(self):
        kinds = ["thought", "devlog", "thought", "garden", "note", "metrics"]
        strokes = _make_strokes(kinds)
        result = skm.analyze(strokes, window=100)
        # should split in half instead of requiring 200 strokes
        assert result["window"] == 3
        assert len(result["kinds"]) == 6

    def test_window_parameter_respected(self):
        kinds = list(skm.ALL_KINDS) * 100  # 600 strokes
        strokes = _make_strokes(kinds)
        result = skm.analyze(strokes, window=50)
        assert result["window"] == 50

    def test_custom_threshold(self):
        # create slight imbalance that passes with high threshold, fails with low
        older_kinds = ["thought"] * 50 + ["devlog"] * 50
        recent_kinds = ["thought"] * 60 + ["devlog"] * 40
        strokes = _make_strokes(older_kinds + recent_kinds)
        result_high = skm.analyze(strokes, window=100, threshold=0.2)
        result_low = skm.analyze(strokes, window=100, threshold=0.01)
        # high threshold should be more lenient
        assert len(result_high["kinds"]) == 6
        assert len(result_low["kinds"]) == 6

    def test_all_kinds_present_in_result(self):
        strokes = _make_strokes(["thought"] * 200)
        result = skm.analyze(strokes, window=100)
        kinds_in_result = [k["kind"] for k in result["kinds"]]
        for k in skm.ALL_KINDS:
            assert k in kinds_in_result

    def test_momentum_values_are_rounded(self):
        kinds = list(skm.ALL_KINDS) * 40
        strokes = _make_strokes(kinds)
        result = skm.analyze(strokes, window=100)
        for k in result["kinds"]:
            # all floats should be rounded to 4 decimal places
            assert k["momentum"] == round(k["momentum"], 4)
            assert k["recent_share"] == round(k["recent_share"], 4)


# ---------------------------------------------------------------------------
# text_report
# ---------------------------------------------------------------------------


class TestTextReport:
    def test_contains_kind_names(self):
        strokes = _make_strokes(list(skm.ALL_KINDS) * 40)
        result = skm.analyze(strokes, window=100)
        report = skm.text_report(result)
        for k in skm.ALL_KINDS:
            assert k in report

    def test_contains_verdict(self):
        strokes = _make_strokes(list(skm.ALL_KINDS) * 40)
        result = skm.analyze(strokes, window=100)
        report = skm.text_report(result)
        assert "verdict:" in report

    def test_contains_header(self):
        result = {"window": 50, "num_kinds": 6, "kinds": [], "verdict": "healthy"}
        report = skm.text_report(result)
        assert "window=50" in report


# ---------------------------------------------------------------------------
# main (CLI smoke test)
# ---------------------------------------------------------------------------


class TestMain:
    def test_runs_with_real_data(self):
        """Smoke test: the tool should not crash on its own strokes.jsonl."""
        default = skm.DEFAULT_STROKES
        if not default.exists():
            pytest.skip("no strokes.jsonl found")
        strokes = skm.load_strokes(default)
        if len(strokes) < 2:
            pytest.skip("too few strokes")
        result = skm.analyze(strokes)
        assert result["verdict"] in ("healthy", "imbalanced", "insufficient_data")

    def test_window_zero_returns_error(self):
        """--window 0 should exit with code 2."""
        import subprocess
        result = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "stroke_kind_momentum.py"), "--window", "0"],
            capture_output=True, text=True,
        )
        assert result.returncode == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_kind_dominates_recently(self):
        """When one kind suddenly dominates, it should show as accelerating."""
        older = ["devlog"] * 50 + ["garden"] * 50
        recent = ["thought"] * 100
        strokes = _make_strokes(older + recent)
        result = skm.analyze(strokes, window=100)
        thought_entry = [k for k in result["kinds"] if k["kind"] == "thought"][0]
        assert thought_entry["trend"] == "accelerating"
        assert thought_entry["momentum"] > 0

    def test_kind_disappearing_shows_decelerating(self):
        """When a kind vanishes from recent strokes, it should show decelerating."""
        older = ["metrics"] * 100
        recent = ["thought"] * 100
        strokes = _make_strokes(older + recent)
        result = skm.analyze(strokes, window=100)
        metrics_entry = [k for k in result["kinds"] if k["kind"] == "metrics"][0]
        assert metrics_entry["trend"] == "decelerating"
        assert metrics_entry["recent_count"] == 0

    def test_exactly_two_strokes(self):
        strokes = _make_strokes(["thought", "devlog"])
        result = skm.analyze(strokes, window=100)
        assert result["verdict"] in ("healthy", "imbalanced", "insufficient_data")

    def test_empty_strokes_list(self):
        result = skm.analyze([], window=100)
        assert result["verdict"] == "insufficient_data"
        assert result["kinds"] == []
