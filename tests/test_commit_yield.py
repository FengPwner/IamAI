"""Tests for iamai.commit_yield."""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.commit_yield import (
    _classify,
    _parse_strokes,
    commit_yield,
    yield_report,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path, strokes: list[dict] | None = None) -> Path:
    """Create a fake repo with data/strokes.jsonl."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    if strokes is not None:
        with open(data_dir / "strokes.jsonl", "w", encoding="utf-8") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")
    return tmp_path


def _stroke(seconds_ago: float, kind: str = "thought", seq: int = 1) -> dict:
    ts = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return {"seq": seq, "at": ts.isoformat(), "kind": kind, "text": "test stroke"}


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_healthy(self):
        assert _classify(0.95) == "healthy"

    def test_healthy_boundary(self):
        assert _classify(0.90) == "healthy"

    def test_degraded(self):
        assert _classify(0.80) == "degraded"

    def test_degraded_boundary(self):
        assert _classify(0.70) == "degraded"

    def test_poor(self):
        assert _classify(0.55) == "poor"

    def test_poor_boundary(self):
        assert _classify(0.50) == "poor"

    def test_critical(self):
        assert _classify(0.30) == "critical"

    def test_zero(self):
        assert _classify(0.0) == "critical"

    def test_one(self):
        assert _classify(1.0) == "healthy"


# ---------------------------------------------------------------------------
# _parse_strokes
# ---------------------------------------------------------------------------

class TestParseStrokes:
    def test_empty_file(self, tmp_path: Path):
        repo = _make_repo(tmp_path, strokes=[])
        strokes_path = repo / "data" / "strokes.jsonl"
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _parse_strokes(strokes_path, since)
        assert result == []

    def test_missing_file(self, tmp_path: Path):
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _parse_strokes(tmp_path / "nonexistent.jsonl", since)
        assert result == []

    def test_filters_by_time(self, tmp_path: Path):
        old = _stroke(seconds_ago=7200, seq=1)  # 2 hours ago
        recent = _stroke(seconds_ago=600, seq=2)  # 10 min ago
        repo = _make_repo(tmp_path, strokes=[old, recent])
        strokes_path = repo / "data" / "strokes.jsonl"
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _parse_strokes(strokes_path, since)
        assert len(result) == 1
        assert result[0]["seq"] == 2

    def test_includes_boundary(self, tmp_path: Path):
        # use 59 minutes ago with a 60-minute window to avoid timing jitter
        nearly = _stroke(seconds_ago=3540, seq=1)  # 59 min ago
        repo = _make_repo(tmp_path, strokes=[nearly])
        strokes_path = repo / "data" / "strokes.jsonl"
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _parse_strokes(strokes_path, since)
        assert len(result) == 1

    def test_skips_malformed_lines(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        with open(data_dir / "strokes.jsonl", "w") as f:
            f.write("not json\n")
            f.write(json.dumps(_stroke(seconds_ago=60)) + "\n")
            f.write("{bad json\n")
        strokes_path = data_dir / "strokes.jsonl"
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _parse_strokes(strokes_path, since)
        assert len(result) == 1

    def test_handles_missing_at_field(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        with open(data_dir / "strokes.jsonl", "w") as f:
            f.write(json.dumps({"seq": 1, "kind": "thought"}) + "\n")
        strokes_path = data_dir / "strokes.jsonl"
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        result = _parse_strokes(strokes_path, since)
        assert result == []


# ---------------------------------------------------------------------------
# commit_yield
# ---------------------------------------------------------------------------

class TestCommitYield:
    def test_no_strokes(self, tmp_path: Path):
        repo = _make_repo(tmp_path, strokes=[])
        info = commit_yield(repo_root=repo, cadence_seconds=15, window_minutes=60)
        assert info["actual"] == 0
        assert info["yield"] == 0.0
        assert info["verdict"] == "critical"

    def test_perfect_yield(self, tmp_path: Path):
        # Generate strokes at 15s intervals for the last 10 minutes
        strokes = []
        for i in range(40):
            strokes.append(_stroke(seconds_ago=i * 15, seq=i + 1))
        repo = _make_repo(tmp_path, strokes=strokes)
        info = commit_yield(repo_root=repo, cadence_seconds=15, window_minutes=10)
        # actual should be >= expected (we wrote 40 in 600s = 40 expected)
        assert info["yield"] >= 0.90
        assert info["verdict"] == "healthy"

    def test_half_yield(self, tmp_path: Path):
        # Generate only half the expected strokes for a 10-min window
        strokes = []
        for i in range(20):  # 20 strokes, but expected ~40
            strokes.append(_stroke(seconds_ago=i * 30, seq=i + 1))
        repo = _make_repo(tmp_path, strokes=strokes)
        info = commit_yield(repo_root=repo, cadence_seconds=15, window_minutes=10)
        # yield should be around 0.5
        assert 0.3 <= info["yield"] <= 0.7

    def test_capped_at_one(self, tmp_path: Path):
        # Generate way more strokes than expected
        strokes = []
        for i in range(200):
            strokes.append(_stroke(seconds_ago=i * 2, seq=i + 1))
        repo = _make_repo(tmp_path, strokes=strokes)
        info = commit_yield(repo_root=repo, cadence_seconds=15, window_minutes=10)
        assert info["yield"] <= 1.0

    def test_missing_strokes_file(self, tmp_path: Path):
        # No strokes.jsonl at all
        info = commit_yield(repo_root=tmp_path, cadence_seconds=15, window_minutes=60)
        assert info["actual"] == 0
        assert info["verdict"] == "critical"

    def test_zero_cadence(self, tmp_path: Path):
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=60)])
        info = commit_yield(repo_root=repo, cadence_seconds=0, window_minutes=60)
        # should not crash; yield is 1.0 when cadence is 0
        assert info["yield"] == 1.0

    def test_return_keys(self, tmp_path: Path):
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=60)])
        info = commit_yield(repo_root=repo, cadence_seconds=15, window_minutes=60)
        expected_keys = {
            "yield", "actual", "expected", "window_minutes",
            "cadence_seconds", "verdict", "commit_count",
        }
        assert set(info.keys()) == expected_keys

    def test_actual_is_int(self, tmp_path: Path):
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=60)])
        info = commit_yield(repo_root=repo, cadence_seconds=15, window_minutes=60)
        assert isinstance(info["actual"], int)

    def test_yield_is_float(self, tmp_path: Path):
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=60)])
        info = commit_yield(repo_root=repo, cadence_seconds=15, window_minutes=60)
        assert isinstance(info["yield"], float)


# ---------------------------------------------------------------------------
# yield_report
# ---------------------------------------------------------------------------

class TestYieldReport:
    def test_report_is_string(self, tmp_path: Path):
        repo = _make_repo(tmp_path, strokes=[_stroke(seconds_ago=60)])
        report = yield_report(repo_root=repo, cadence_seconds=15, window_minutes=60)
        assert isinstance(report, str)

    def test_report_contains_verdict(self, tmp_path: Path):
        repo = _make_repo(tmp_path, strokes=[])
        report = yield_report(repo_root=repo, cadence_seconds=15, window_minutes=60)
        assert "critical" in report

    def test_report_contains_numbers(self, tmp_path: Path):
        strokes = [_stroke(seconds_ago=i * 15, seq=i) for i in range(10)]
        repo = _make_repo(tmp_path, strokes=strokes)
        report = yield_report(repo_root=repo, cadence_seconds=15, window_minutes=10)
        # should contain the stroke count
        assert "/" in report
        assert "strokes" in report

    def test_report_format(self, tmp_path: Path):
        repo = _make_repo(tmp_path, strokes=[])
        report = yield_report(repo_root=repo, cadence_seconds=15, window_minutes=60)
        # Expected format: "critical — yield 0.00 (0/240 strokes in last 60 min, N commits)"
        assert "yield" in report
        assert "min" in report
