#!/usr/bin/env python3
"""Tests for cadence_monitor — rhythm tracking and slowdown detection."""

import json
import os
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent

from iamai.cadence_monitor import (
    CadenceReport,
    _classify,
    _last_two_stroke_timestamps,
    _last_two_commit_timestamps,
    measure,
    is_healthy,
    DEFAULT_STROKE_TARGET,
    DEFAULT_BATCH_TARGET,
)


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_healthy_within_target(self):
        assert _classify(10.0, 15.0) == "healthy"

    def test_healthy_at_boundary(self):
        assert _classify(22.5, 15.0) == "healthy"  # 1.5x exactly

    def test_slowing(self):
        assert _classify(30.0, 15.0) == "slowing"  # 2x

    def test_slowing_at_boundary(self):
        assert _classify(45.0, 15.0) == "slowing"  # 3x exactly

    def test_stalled(self):
        assert _classify(60.0, 15.0) == "stalled"  # 4x

    def test_zero_target(self):
        assert _classify(10.0, 0) == "stalled"

    def test_negative_target(self):
        assert _classify(10.0, -5) == "stalled"


# ---------------------------------------------------------------------------
# CadenceReport properties
# ---------------------------------------------------------------------------

class TestCadenceReport:
    def test_frozen(self):
        r = CadenceReport(
            actual_stroke_gap=15.0, actual_batch_gap=600.0,
            target_stroke_gap=15.0, target_batch_gap=600.0,
            health="healthy", reason="ok",
        )
        with pytest.raises(AttributeError):
            r.health = "stalled"

    def test_stroke_ratio(self):
        r = CadenceReport(30.0, 600.0, 15.0, 600.0, "slowing", "test")
        assert r.stroke_ratio == pytest.approx(2.0)

    def test_batch_ratio(self):
        r = CadenceReport(15.0, 1200.0, 15.0, 600.0, "slowing", "test")
        assert r.batch_ratio == pytest.approx(2.0)

    def test_stroke_ratio_zero_target(self):
        r = CadenceReport(15.0, 600.0, 0, 600.0, "stalled", "test")
        assert r.stroke_ratio == float("inf")

    def test_batch_ratio_zero_target(self):
        r = CadenceReport(15.0, 600.0, 15.0, 0, "stalled", "test")
        assert r.batch_ratio == float("inf")


# ---------------------------------------------------------------------------
# _last_two_stroke_timestamps
# ---------------------------------------------------------------------------

class TestStrokeTimestamps:
    def test_file_not_found(self, tmp_path):
        assert _last_two_stroke_timestamps(tmp_path / "nope.jsonl") is None

    def test_single_stroke(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(json.dumps({"ts": 1000.0}) + "\n")
        assert _last_two_stroke_timestamps(p) is None

    def test_two_strokes(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            json.dumps({"ts": 1000.0}) + "\n"
            + json.dumps({"ts": 1015.0}) + "\n"
        )
        result = _last_two_stroke_timestamps(p)
        assert result == (1015.0, 1000.0)

    def test_many_strokes_returns_last_two(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [json.dumps({"ts": 1000.0 + i * 15}) for i in range(20)]
        p.write_text("\n".join(lines) + "\n")
        result = _last_two_stroke_timestamps(p)
        assert result is not None
        assert result[0] == pytest.approx(1000.0 + 19 * 15)
        assert result[1] == pytest.approx(1000.0 + 18 * 15)

    def test_alternate_timestamp_key(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            json.dumps({"timestamp": 2000.0}) + "\n"
            + json.dumps({"timestamp": 2020.0}) + "\n"
        )
        result = _last_two_stroke_timestamps(p)
        assert result == (2020.0, 2000.0)

    def test_malformed_lines_skipped(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            "not json\n"
            + json.dumps({"ts": 3000.0}) + "\n"
            + json.dumps({"ts": 3015.0}) + "\n"
        )
        result = _last_two_stroke_timestamps(p)
        assert result == (3015.0, 3000.0)

    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        assert _last_two_stroke_timestamps(p) is None


# ---------------------------------------------------------------------------
# measure
# ---------------------------------------------------------------------------

class TestMeasure:
    def test_no_data_stalled(self, tmp_path):
        """No strokes file and no git history → stalled."""
        (tmp_path / "data").mkdir()
        report = measure(tmp_path, writer="test", now=10000.0)
        assert report.health == "stalled"
        assert report.actual_stroke_gap == float("inf")

    def test_healthy_cadence(self, tmp_path):
        """Two recent strokes close together → healthy stroke gap."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        p = data_dir / "strokes.jsonl"
        now = time.time()
        p.write_text(
            json.dumps({"ts": now - 20}) + "\n"
            + json.dumps({"ts": now - 5}) + "\n"
        )
        report = measure(tmp_path, writer="test", now=now)
        # stroke gap = 15s, target = 15s → ratio 1.0 → healthy
        assert report.actual_stroke_gap == pytest.approx(15.0)
        # batch gap will be inf (no git commits) → overall stalled
        # but stroke health is healthy
        assert report.stroke_ratio == pytest.approx(1.0)

    def test_slowing_stroke(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        p = data_dir / "strokes.jsonl"
        now = time.time()
        p.write_text(
            json.dumps({"ts": now - 60}) + "\n"
            + json.dumps({"ts": now - 20}) + "\n"
        )
        report = measure(tmp_path, writer="test", now=now)
        # stroke gap = 40s, target = 15s → ratio ~2.67 → slowing
        assert report.actual_stroke_gap == pytest.approx(40.0)
        assert 1.5 < report.stroke_ratio <= 3.0

    def test_custom_targets(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        p = data_dir / "strokes.jsonl"
        p.write_text(
            json.dumps({"ts": 900.0}) + "\n"
            + json.dumps({"ts": 930.0}) + "\n"
        )
        report = measure(
            tmp_path, writer="test",
            stroke_target=30.0, batch_target=300.0,
            now=1000.0,
        )
        # stroke gap = 30s, target = 30s → ratio 1.0 → healthy
        assert report.stroke_ratio == pytest.approx(1.0)
        assert report.target_stroke_gap == 30.0
        assert report.target_batch_gap == 300.0


# ---------------------------------------------------------------------------
# is_healthy
# ---------------------------------------------------------------------------

class TestIsHealthy:
    def test_healthy(self):
        r = CadenceReport(15.0, 600.0, 15.0, 600.0, "healthy", "ok")
        assert is_healthy(r) is True

    def test_slowing(self):
        r = CadenceReport(30.0, 600.0, 15.0, 600.0, "slowing", "slow")
        assert is_healthy(r) is False

    def test_stalled(self):
        r = CadenceReport(
            float("inf"), float("inf"), 15.0, 600.0, "stalled", "no data"
        )
        assert is_healthy(r) is False
