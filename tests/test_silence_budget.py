"""Tests for iamai.silence_budget — silence-budget tracker."""

import json
from pathlib import Path

import pytest

from iamai.silence_budget import (
    BudgetResult,
    SilenceBudget,
    _classify,
    extract_stall_gaps,
    silence_report,
)


# ---------------------------------------------------------------------------
# SilenceBudget basics
# ---------------------------------------------------------------------------


class TestSilenceBudget:
    def test_window_seconds(self):
        sb = SilenceBudget(window_hours=12)
        assert sb.window_seconds == 12 * 3600

    def test_window_budget_default(self):
        sb = SilenceBudget(window_hours=24, max_fraction=0.10)
        assert sb.window_budget == pytest.approx(24 * 3600 * 0.10)

    def test_effective_cap_defaults_to_budget(self):
        sb = SilenceBudget(window_hours=24, max_fraction=0.10, cap_seconds=0)
        assert sb.effective_cap == sb.window_budget

    def test_effective_cap_explicit(self):
        sb = SilenceBudget(cap_seconds=500)
        assert sb.effective_cap == 500

    def test_evaluate_empty_no_stalls(self):
        sb = SilenceBudget(window_hours=24, max_fraction=0.10)
        result = sb.evaluate([])
        assert result.verdict == "plenty"
        assert result.spent == 0.0
        assert result.fraction_left == 1.0
        assert result.stall_count == 0

    def test_evaluate_some_stalls(self):
        sb = SilenceBudget(cadence_seconds=15, window_hours=24, max_fraction=0.10)
        # budget = 8640s; spend 1200s across 3 stalls
        result = sb.evaluate([300, 600, 300])
        assert result.spent == pytest.approx(1200)
        assert result.remaining == pytest.approx(8640 - 1200)
        assert result.fraction_left > 0.50
        assert result.verdict == "plenty"

    def test_evaluate_tightening(self):
        sb = SilenceBudget(cadence_seconds=15, window_hours=24, max_fraction=0.10)
        # budget = 8640s; spend 5000s → remaining 3640/8640 = 0.42 → tightening
        result = sb.evaluate([2500, 2500])
        assert result.verdict == "tightening"
        assert 0.25 <= result.fraction_left < 0.50

    def test_evaluate_exhausted(self):
        sb = SilenceBudget(cadence_seconds=15, window_hours=24, max_fraction=0.10)
        # budget = 8640s; spend 7500s → remaining 1140/8640 = 0.13 → exhausted
        result = sb.evaluate([4000, 3500])
        assert result.verdict == "exhausted"
        assert 0 < result.fraction_left < 0.25

    def test_evaluate_bankrupt(self):
        sb = SilenceBudget(cadence_seconds=15, window_hours=24, max_fraction=0.10)
        # budget = 8640s; spend way more
        result = sb.evaluate([5000, 5000])
        assert result.verdict == "bankrupt"
        assert result.fraction_left == 0.0
        assert result.remaining == 0.0

    def test_cap_prevents_single_stall_bankruptcy(self):
        sb = SilenceBudget(
            cadence_seconds=15, window_hours=24,
            max_fraction=0.10, cap_seconds=1000,
        )
        # One massive stall of 999999s, but capped at 1000
        result = sb.evaluate([999999])
        assert result.spent == pytest.approx(1000)
        assert result.verdict == "plenty"


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------


class TestClassify:
    def test_plenty(self):
        assert _classify(1.0) == "plenty"
        assert _classify(0.50) == "plenty"

    def test_tightening(self):
        assert _classify(0.49) == "tightening"
        assert _classify(0.25) == "tightening"

    def test_exhausted(self):
        assert _classify(0.24) == "exhausted"
        assert _classify(0.01) == "exhausted"

    def test_bankrupt(self):
        assert _classify(0.0) == "bankrupt"


# ---------------------------------------------------------------------------
# BudgetResult
# ---------------------------------------------------------------------------


class TestBudgetResult:
    def test_describe(self):
        r = BudgetResult(
            spent=600, remaining=8040, budget=8640,
            fraction_left=0.9306, stall_count=2,
            verdict="plenty", window_hours=24,
        )
        desc = r.describe()
        assert "plenty" in desc
        assert "2 stall(s)" in desc

    def test_to_dict(self):
        r = BudgetResult(
            spent=100, remaining=8540, budget=8640,
            fraction_left=0.988, stall_count=1,
            verdict="plenty", window_hours=24,
        )
        d = r.to_dict()
        assert d["verdict"] == "plenty"
        assert d["spent_seconds"] == 100
        assert d["stall_count"] == 1


# ---------------------------------------------------------------------------
# extract_stall_gaps from strokes file
# ---------------------------------------------------------------------------


class TestExtractStallGaps:
    def _write_strokes(self, timestamps: list[float], path: Path) -> None:
        with open(path, "w") as f:
            for ts in timestamps:
                f.write(json.dumps({"timestamp": ts}) + "\n")

    def test_no_file(self, tmp_path):
        gaps = extract_stall_gaps(
            strokes_file=tmp_path / "nonexistent.jsonl",
            cadence_seconds=15,
        )
        assert gaps == []

    def test_empty_file(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text("")
        gaps = extract_stall_gaps(strokes_file=f, cadence_seconds=15)
        assert gaps == []

    def test_single_stroke(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        self._write_strokes([1000.0], f)
        gaps = extract_stall_gaps(strokes_file=f, cadence_seconds=15)
        assert gaps == []

    def test_detects_stall_gap(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        now = 2000.0
        # Two strokes: one at t=1000, next at t=1500 (gap=500s > 15s cadence)
        self._write_strokes([1000.0, 1500.0], f)
        gaps = extract_stall_gaps(
            strokes_file=f, cadence_seconds=15,
            window_hours=24, now=now,
        )
        assert len(gaps) == 1
        assert gaps[0] == pytest.approx(500.0)

    def test_no_gap_within_cadence(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        now = 2000.0
        # Strokes 10s apart, within 15s cadence
        self._write_strokes([1500.0, 1510.0, 1520.0], f)
        gaps = extract_stall_gaps(
            strokes_file=f, cadence_seconds=15,
            window_hours=24, now=now,
        )
        assert gaps == []

    def test_old_gaps_excluded_by_window(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        now = 200000.0
        # Window starts at 113600. All recent strokes clustered tightly.
        # Old gap at 1000->1500 has end=1500 < 113600 -> excluded.
        # Recent strokes 199980,199985,199990 within 5s -> no stall.
        # But the bridge gap 1500->199980 ends inside window -> detected.
        self._write_strokes([1000.0, 1500.0, 199980.0, 199985.0, 199990.0], f)
        gaps = extract_stall_gaps(
            strokes_file=f, cadence_seconds=15,
            window_hours=24, now=now,
        )
        # Bridge gap (1500->199980 = 198480s) ends inside window -> 1 gap
        assert len(gaps) == 1
        assert gaps[0] == pytest.approx(198480.0)


    def test_mixed_old_and_new_gaps(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        now = 200000.0
        # Window starts at 113600.
        # Gap 1000->1500: end=1500 < 113600 -> excluded.
        # Gap 1500->199000: end=199000 > 113600, gap=197500 -> included.
        # Gap 199000->199005: 5s, within cadence -> not a stall.
        self._write_strokes([1000.0, 1500.0, 199000.0, 199005.0], f)
        gaps = extract_stall_gaps(
            strokes_file=f, cadence_seconds=15,
            window_hours=24, now=now,
        )
        assert len(gaps) == 1
        assert gaps[0] == pytest.approx(197500.0)


# ---------------------------------------------------------------------------
# silence_report end-to-end
# ---------------------------------------------------------------------------


class TestSilenceReport:
    def test_no_file(self, tmp_path):
        report = silence_report(
            strokes_file=tmp_path / "missing.jsonl",
        )
        assert report["verdict"] == "plenty"
        assert report["spent_seconds"] == 0.0
        assert report["stall_count"] == 0

    def test_with_stalls(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        now = 5000.0
        lines = [
            json.dumps({"timestamp": 1000.0}),
            json.dumps({"timestamp": 1500.0}),  # gap=500s
            json.dumps({"timestamp": 2000.0}),  # gap=500s
            json.dumps({"timestamp": 4900.0}),  # gap=2900s
        ]
        f.write_text("\n".join(lines) + "\n")
        report = silence_report(
            cadence_seconds=15, window_hours=24,
            max_fraction=0.10, strokes_file=f, now=now,
        )
        assert report["stall_count"] == 3
        assert report["spent_seconds"] == pytest.approx(3900)
        assert report["budget_seconds"] == pytest.approx(8640)
