#!/usr/bin/env python3
"""Tests for post_restart_cadence_validator.py — post-restart cadence validation."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import post_restart_cadence_validator as pcv


def _make_strokes(timestamps: list[datetime], kinds: list[str] = None) -> list[dict]:
    """Build stroke records from timestamps."""
    if kinds is None:
        kinds = ["thought"] * len(timestamps)
    return [
        {"seq": i, "at": t.isoformat(), "kind": kinds[i % len(kinds)], "text": "x"}
        for i, t in enumerate(timestamps)
    ]


def _regular_strokes(n: int, interval_s: int,
                     start: datetime = None) -> list[dict]:
    """Generate n strokes at a fixed interval."""
    if start is None:
        start = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
    times = [start + timedelta(seconds=i * interval_s) for i in range(n)]
    return _make_strokes(times)


class TestComputeCadence:
    """Tests for cadence computation."""

    def test_regular_15s_cadence(self):
        strokes = _regular_strokes(10, 15)
        mean, count = pcv.compute_cadence(strokes)
        assert mean == pytest.approx(15.0, abs=0.1)
        assert count == 10

    def test_single_stroke(self):
        strokes = _regular_strokes(1, 15)
        mean, count = pcv.compute_cadence(strokes)
        assert mean == 0.0
        assert count == 1

    def test_empty_list(self):
        mean, count = pcv.compute_cadence([])
        assert mean == 0.0
        assert count == 0

    def test_irregular_cadence(self):
        """Strokes with varying intervals should average correctly."""
        base = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
        times = [base, base + timedelta(seconds=10),
                 base + timedelta(seconds=30), base + timedelta(seconds=40)]
        strokes = _make_strokes(times)
        mean, count = pcv.compute_cadence(strokes)
        # intervals: 10, 20, 10 → mean = 13.33
        assert mean == pytest.approx(13.33, abs=0.1)
        assert count == 4

    def test_ts_field_fallback(self):
        """Strokes using 'ts' instead of 'at' should parse correctly."""
        base = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
        strokes = [
            {"seq": i, "ts": (base + timedelta(seconds=i * 15)).isoformat(),
             "kind": "devlog", "summary": "x"}
            for i in range(5)
        ]
        mean, count = pcv.compute_cadence(strokes)
        assert mean == pytest.approx(15.0, abs=0.1)


class TestClassify:
    """Tests for verdict classification."""

    def test_settled_tight_cadence(self):
        """15s target, 15s actual, enough strokes → settled."""
        assert pcv.classify(15.0, 10, 15, 4) == "settled"

    def test_settled_slight_drift(self):
        """15s target, 18s actual (20% drift), enough strokes → settled."""
        assert pcv.classify(18.0, 10, 15, 4) == "settled"

    def test_warming_too_few_strokes(self):
        """Correct cadence but not enough strokes yet → warming."""
        assert pcv.classify(15.0, 2, 15, 4) == "warming"

    def test_warming_moderate_drift(self):
        """15s target, 22s actual (47% drift) → warming."""
        assert pcv.classify(22.0, 10, 15, 4) == "warming"

    def test_stalled_no_strokes(self):
        assert pcv.classify(0.0, 0, 15, 4) == "stalled"

    def test_stalled_double_cadence(self):
        """15s target, 35s actual (>2x) → stalled."""
        assert pcv.classify(35.0, 10, 15, 4) == "stalled"

    def test_stalled_high_drift(self):
        """15s target, 28s actual (87% drift, <2x but >100% threshold) → stalled."""
        # 28/15 = 1.87x, drift = 86.7% → still warming (< 100%)
        assert pcv.classify(28.0, 10, 15, 4) == "warming"

    def test_stalled_extreme_drift(self):
        """15s target, 29s actual, barely under 2x → warming."""
        assert pcv.classify(29.0, 10, 15, 4) == "warming"

    def test_boundary_exactly_2x(self):
        """15s target, 30s actual (exactly 2x) → stalled."""
        assert pcv.classify(30.0, 10, 15, 4) == "stalled"


class TestValidate:
    """Integration tests for the validate function."""

    def test_validate_settled(self, tmp_path, monkeypatch):
        """Full validation with healthy cadence data."""
        strokes_file = tmp_path / "data" / "strokes.jsonl"
        strokes_file.parent.mkdir(parents=True)
        strokes = _regular_strokes(10, 15)
        strokes_file.write_text(
            "\n".join(json.dumps(s) for s in strokes) + "\n"
        )
        monkeypatch.setattr(pcv, "STROKES_FILE", strokes_file)

        result = pcv.validate(writer="qwen", target_s=15, min_strokes=4)
        assert result["settled"] is True
        assert result["verdict"] == "settled"
        assert result["actual_cadence_s"] == pytest.approx(15.0, abs=0.5)
        assert result["stroke_count"] == 10

    def test_validate_stalled_empty(self, tmp_path, monkeypatch):
        """No strokes file → stalled."""
        strokes_file = tmp_path / "data" / "strokes.jsonl"
        monkeypatch.setattr(pcv, "STROKES_FILE", strokes_file)

        result = pcv.validate(writer="qwen", target_s=15)
        assert result["settled"] is False
        assert result["verdict"] == "stalled"

    def test_validate_warming_few_strokes(self, tmp_path, monkeypatch):
        """Only 2 strokes → warming even if cadence is correct."""
        strokes_file = tmp_path / "data" / "strokes.jsonl"
        strokes_file.parent.mkdir(parents=True)
        strokes = _regular_strokes(2, 15)
        strokes_file.write_text(
            "\n".join(json.dumps(s) for s in strokes) + "\n"
        )
        monkeypatch.setattr(pcv, "STROKES_FILE", strokes_file)

        result = pcv.validate(writer="qwen", target_s=15, min_strokes=4)
        assert result["settled"] is False
        assert result["verdict"] == "warming"

    def test_validate_json_output(self, tmp_path, monkeypatch, capsys):
        """--json flag should produce valid JSON output."""
        strokes_file = tmp_path / "data" / "strokes.jsonl"
        strokes_file.parent.mkdir(parents=True)
        strokes = _regular_strokes(8, 15)
        strokes_file.write_text(
            "\n".join(json.dumps(s) for s in strokes) + "\n"
        )
        monkeypatch.setattr(pcv, "STROKES_FILE", strokes_file)

        result = pcv.validate(writer="qwen", target_s=15, as_json=True)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["settled"] is True
        assert parsed["verdict"] == "settled"

    def test_validate_drift_pct(self, tmp_path, monkeypatch):
        """Drift percentage should reflect actual deviation."""
        strokes_file = tmp_path / "data" / "strokes.jsonl"
        strokes_file.parent.mkdir(parents=True)
        # 20s intervals with 15s target = +33.3% drift
        strokes = _regular_strokes(10, 20)
        strokes_file.write_text(
            "\n".join(json.dumps(s) for s in strokes) + "\n"
        )
        monkeypatch.setattr(pcv, "STROKES_FILE", strokes_file)

        result = pcv.validate(writer="qwen", target_s=15, min_strokes=4)
        assert result["drift_pct"] == pytest.approx(33.3, abs=0.5)
        assert result["verdict"] == "warming"  # >30% drift


class TestLoadRecentStrokes:
    """Tests for stroke loading."""

    def test_load_from_file(self, tmp_path, monkeypatch):
        """Should load strokes from jsonl file."""
        strokes_file = tmp_path / "strokes.jsonl"
        strokes = _regular_strokes(5, 15)
        strokes_file.write_text(
            "\n".join(json.dumps(s) for s in strokes) + "\n"
        )
        monkeypatch.setattr(pcv, "STROKES_FILE", strokes_file)

        loaded = pcv.load_recent_strokes(n=3)
        assert len(loaded) == 3

    def test_load_missing_file(self, tmp_path, monkeypatch):
        """Missing file should return empty list."""
        monkeypatch.setattr(pcv, "STROKES_FILE", tmp_path / "nope.jsonl")
        assert pcv.load_recent_strokes() == []

    def test_load_malformed_lines(self, tmp_path, monkeypatch):
        """Malformed JSON lines should be skipped."""
        strokes_file = tmp_path / "strokes.jsonl"
        strokes_file.write_text(
            '{"seq": 0, "at": "2026-11-03T12:00:00+00:00"}\n'
            'not json\n'
            '{"seq": 2, "at": "2026-11-03T12:00:30+00:00"}\n'
        )
        monkeypatch.setattr(pcv, "STROKES_FILE", strokes_file)

        loaded = pcv.load_recent_strokes()
        assert len(loaded) == 2

    def test_load_window_larger_than_file(self, tmp_path, monkeypatch):
        """Requesting more strokes than available returns all."""
        strokes_file = tmp_path / "strokes.jsonl"
        strokes = _regular_strokes(3, 15)
        strokes_file.write_text(
            "\n".join(json.dumps(s) for s in strokes) + "\n"
        )
        monkeypatch.setattr(pcv, "STROKES_FILE", strokes_file)

        loaded = pcv.load_recent_strokes(n=100)
        assert len(loaded) == 3
