#!/usr/bin/env python3
"""Tests for tools/stroke_kind_scheduler.py

Covers: weight computation, kind picking, edge cases, CLI behaviour,
mathematical properties of the weighting function.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools.stroke_kind_scheduler import (  # noqa: E402
    ALL_KINDS,
    compute_weights,
    load_recent_kinds,
    pick_kind,
    recommend,
    DEFAULT_TARGET_PCT,
    DEFAULT_POWER,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_strokes(path: Path, kinds: list[str]) -> None:
    """Write a minimal strokes.jsonl with the given kind sequence."""
    with open(path, "w", encoding="utf-8") as f:
        for i, kind in enumerate(kinds):
            record = {"seq": i, "kind": kind, "text": f"stroke {i}", "at": "2026-11-02T00:00:00+00:00"}
            f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# load_recent_kinds
# ---------------------------------------------------------------------------

class TestLoadRecentKinds:
    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        assert load_recent_kinds(p, 100) == []

    def test_missing_file(self, tmp_path: Path) -> None:
        p = tmp_path / "nonexistent.jsonl"
        assert load_recent_kinds(p, 100) == []

    def test_reads_all(self, tmp_path: Path) -> None:
        p = tmp_path / "strokes.jsonl"
        _write_strokes(p, ["thought", "note", "devlog"])
        result = load_recent_kinds(p, 100)
        assert result == ["thought", "note", "devlog"]

    def test_window_truncation(self, tmp_path: Path) -> None:
        p = tmp_path / "strokes.jsonl"
        _write_strokes(p, ["thought"] * 10 + ["note"])
        result = load_recent_kinds(p, 5)
        assert result == ["thought"] * 4 + ["note"]

    def test_skips_blank_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "strokes.jsonl"
        content = '{"seq":0,"kind":"thought"}\n\n{"seq":1,"kind":"note"}\n'
        p.write_text(content)
        result = load_recent_kinds(p, 100)
        assert result == ["thought", "note"]

    def test_skips_malformed_json(self, tmp_path: Path) -> None:
        p = tmp_path / "strokes.jsonl"
        content = '{"seq":0,"kind":"thought"}\n{bad json}\n{"seq":2,"kind":"note"}\n'
        p.write_text(content)
        result = load_recent_kinds(p, 100)
        assert result == ["thought", "note"]

    def test_missing_kind_field_defaults_to_unknown(self, tmp_path: Path) -> None:
        p = tmp_path / "strokes.jsonl"
        p.write_text('{"seq":0,"text":"hello"}\n')
        result = load_recent_kinds(p, 100)
        assert result == ["unknown"]


# ---------------------------------------------------------------------------
# compute_weights
# ---------------------------------------------------------------------------

class TestComputeWeights:
    def test_balanced_input_gives_equal_weights(self) -> None:
        # Equal distribution → all gaps are similar → similar weights
        kinds = ALL_KINDS * 10  # 80 strokes, 10 each
        weights = compute_weights(kinds)
        values = list(weights.values())
        # All weights should be close to each other
        assert max(values) - min(values) < 2.0

    def test_monoculture_gives_massive_thought_weight(self) -> None:
        kinds = ["thought"] * 100
        weights = compute_weights(kinds)
        # thought is oversaturated → lowest weight
        thought_w = weights["thought"]
        starved_w = weights["note"]
        assert starved_w > thought_w * 5

    def test_empty_input_gives_equal_weights(self) -> None:
        weights = compute_weights([])
        # With 0 strokes, all kinds have 0% share → equal gaps → equal weights
        values = list(weights.values())
        assert len(set(round(v, 4) for v in values)) == 1

    def test_higher_power_amplifies_correction(self) -> None:
        kinds = ["thought"] * 90 + ["note"] * 10
        w_low = compute_weights(kinds, power=1.0)
        w_high = compute_weights(kinds, power=3.0)
        # Higher power should make starved kinds relatively heavier
        ratio_low = w_low["note"] / w_low["thought"]
        ratio_high = w_high["note"] / w_high["thought"]
        assert ratio_high > ratio_low

    def test_all_kinds_present_in_output(self) -> None:
        weights = compute_weights(["thought"] * 50)
        for kind in ALL_KINDS:
            assert kind in weights

    def test_custom_all_kinds(self) -> None:
        weights = compute_weights(["a", "a", "b"], all_kinds=["a", "b"])
        assert set(weights.keys()) == {"a", "b"}
        assert weights["b"] > weights["a"]  # b is underrepresented

    def test_oversaturated_weight_below_one(self) -> None:
        # A kind at 99.9% is massively oversaturated → weight < 1.0
        kinds = ["thought"] * 999 + ["note"]
        weights = compute_weights(kinds)
        assert weights["thought"] < 1.0

    def test_target_pct_parameter(self) -> None:
        kinds = ["thought"] * 50 + ["note"] * 50
        # With target 50%, both at 50% → balanced
        w50 = compute_weights(kinds, target_pct=50.0)
        assert abs(w50["thought"] - w50["note"]) < 1.0
        # With target 12.5%, thought is over → low weight
        w12 = compute_weights(kinds, target_pct=12.5)
        assert w12["thought"] < w12["snippet"]  # snippet at 0% gets higher weight


# ---------------------------------------------------------------------------
# pick_kind
# ---------------------------------------------------------------------------

class TestPickKind:
    def test_deterministic_with_seed(self) -> None:
        weights = {"thought": 1.0, "note": 100.0}
        r1 = pick_kind(weights, random.Random(42))
        r2 = pick_kind(weights, random.Random(42))
        assert r1 == r2

    def test_heavy_weight_wins_mostly(self) -> None:
        weights = {"thought": 1.0, "note": 1000.0}
        rng = random.Random(0)
        picks = [pick_kind(weights, rng) for _ in range(200)]
        note_count = picks.count("note")
        # note should win >95% of the time
        assert note_count > 190

    def test_returns_valid_kind(self) -> None:
        weights = {"a": 1.0, "b": 1.0, "c": 1.0}
        for seed in range(50):
            result = pick_kind(weights, random.Random(seed))
            assert result in weights

    def test_single_kind(self) -> None:
        weights = {"thought": 5.0}
        assert pick_kind(weights, random.Random(0)) == "thought"

    def test_zero_weight_fallback(self) -> None:
        # All weights 0 → fallback to random.choice
        weights = {"a": 0.0, "b": 0.0}
        result = pick_kind(weights, random.Random(42))
        assert result in weights


# ---------------------------------------------------------------------------
# recommend
# ---------------------------------------------------------------------------

class TestRecommend:
    def test_recommend_structure(self, tmp_path: Path) -> None:
        p = tmp_path / "strokes.jsonl"
        _write_strokes(p, ["thought"] * 100)
        result = recommend(path=p, window=100)
        assert "window" in result
        assert "total_strokes" in result
        assert "shares_pct" in result
        assert "weights" in result
        assert "next_kind" in result
        assert result["total_strokes"] == 100

    def test_recommend_with_real_data(self) -> None:
        """Smoke test with the actual repo strokes file."""
        result = recommend()
        assert result["total_strokes"] > 0
        assert result["next_kind"] in ALL_KINDS

    def test_recommend_empty_log(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        result = recommend(path=p, window=100)
        assert result["total_strokes"] == 0
        assert result["next_kind"] in ALL_KINDS


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestCLI:
    def test_text_output(self, tmp_path: Path) -> None:
        p = tmp_path / "strokes.jsonl"
        _write_strokes(p, ["thought"] * 80 + ["note"] * 20)
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "stroke_kind_scheduler.py"),
             "--log", str(p), "--window", "100"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "Stroke Kind Scheduler" in result.stdout
        assert "thought" in result.stdout
        assert "recommended next kind" in result.stdout

    def test_json_output(self, tmp_path: Path) -> None:
        p = tmp_path / "strokes.jsonl"
        _write_strokes(p, ["thought"] * 50 + ["note"] * 50)
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "stroke_kind_scheduler.py"),
             "--log", str(p), "--json", "--window", "100"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "weights" in data
        assert "next_kind" in data

    def test_pick_multiple(self, tmp_path: Path) -> None:
        p = tmp_path / "strokes.jsonl"
        _write_strokes(p, ["thought"] * 90 + ["note"] * 10)
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "stroke_kind_scheduler.py"),
             "--log", str(p), "--pick", "5", "--window", "100"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "picks" in result.stdout

    def test_custom_target_and_power(self, tmp_path: Path) -> None:
        p = tmp_path / "strokes.jsonl"
        _write_strokes(p, ["thought"] * 50 + ["note"] * 50)
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "stroke_kind_scheduler.py"),
             "--log", str(p), "--target", "20", "--power", "3", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# Mathematical properties
# ---------------------------------------------------------------------------

class TestMathProperties:
    def test_weights_are_positive(self) -> None:
        for _ in range(20):
            kinds = [random.choice(ALL_KINDS) for _ in range(100)]
            weights = compute_weights(kinds)
            assert all(w > 0.0 for w in weights.values())

    def test_weight_monotonicity(self) -> None:
        """Less represented kind → higher weight."""
        kinds = ["thought"] * 80 + ["note"] * 15 + ["devlog"] * 5
        weights = compute_weights(kinds)
        assert weights["devlog"] > weights["note"] > weights["thought"]

    def test_weights_sum_positive(self) -> None:
        weights = compute_weights(["thought"] * 50)
        assert sum(weights.values()) > 0

    def test_power_zero_gives_uniform(self) -> None:
        """power=0 → all weights are 1.0 (uniform)."""
        kinds = ["thought"] * 99 + ["note"]
        weights = compute_weights(kinds, power=0.0)
        # gap ** 0 = 1.0 for all
        for w in weights.values():
            assert abs(w - 1.0) < 0.001


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
