"""Tests for iamai.stroke_freshness."""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.stroke_freshness import (
    _classify,
    _last_stroke_time,
    freshness,
    freshness_report,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path, strokes: list[dict] | None = None) -> Path:
    """Create a fake repo with a strokes.jsonl."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    if strokes is not None:
        with open(data_dir / "strokes.jsonl", "w", encoding="utf-8") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")
    return tmp_path


def _stroke(seconds_ago: float, kind: str = "thought") -> dict:
    ts = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return {"seq": 1, "at": ts.isoformat(), "kind": kind, "text": "test"}


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_fresh(self):
        assert _classify(10, 15) == "fresh"

    def test_fresh_boundary(self):
        # exactly at 2× cadence → not fresh (boundary is exclusive)
        assert _classify(30, 15) == "warm"

    def test_warm(self):
        assert _classify(60, 15) == "warm"

    def test_stale(self):
        assert _classify(200, 15) == "stale"

    def test_dead(self):
        assert _classify(500, 15) == "dead"

    def test_zero_age(self):
        assert _classify(0, 15) == "fresh"


# ---------------------------------------------------------------------------
# _last_stroke_time
# ---------------------------------------------------------------------------

class TestLastStrokeTime:
    def test_missing_file(self, tmp_path):
        path = tmp_path / "nope.jsonl"
        assert _last_stroke_time(path) is None

    def test_empty_file(self, tmp_path):
        path = tmp_path / "strokes.jsonl"
        path.write_text("")
        assert _last_stroke_time(path) is None

    def test_single_line(self, tmp_path):
        ts = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
        path = tmp_path / "strokes.jsonl"
        path.write_text(json.dumps({"seq": 1, "at": ts.isoformat()}) + "\n")
        result = _last_stroke_time(path)
        assert result is not None
        assert abs((result - ts).total_seconds()) < 1

    def test_multiple_lines_returns_last(self, tmp_path):
        ts1 = datetime(2026, 10, 7, 10, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
        path = tmp_path / "strokes.jsonl"
        with open(path, "w") as f:
            f.write(json.dumps({"seq": 1, "at": ts1.isoformat()}) + "\n")
            f.write(json.dumps({"seq": 2, "at": ts2.isoformat()}) + "\n")
        result = _last_stroke_time(path)
        assert result is not None
        assert abs((result - ts2).total_seconds()) < 1

    def test_malformed_last_line(self, tmp_path):
        path = tmp_path / "strokes.jsonl"
        path.write_text("not json\n")
        assert _last_stroke_time(path) is None

    def test_missing_at_field(self, tmp_path):
        path = tmp_path / "strokes.jsonl"
        path.write_text(json.dumps({"seq": 1}) + "\n")
        assert _last_stroke_time(path) is None


# ---------------------------------------------------------------------------
# freshness
# ---------------------------------------------------------------------------

class TestFreshness:
    def test_no_strokes_file(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=None)
        info = freshness(repo)
        assert info["verdict"] == "dead"
        assert info["age_seconds"] == float("inf")
        assert info["last_stroke_at"] is None

    def test_fresh_stroke(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(5)])
        now = datetime.now(timezone.utc)
        info = freshness(repo, cadence_seconds=15, now=now)
        assert info["verdict"] == "fresh"
        assert info["age_seconds"] < 30

    def test_warm_stroke(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(60)])
        now = datetime.now(timezone.utc)
        info = freshness(repo, cadence_seconds=15, now=now)
        assert info["verdict"] == "warm"

    def test_stale_stroke(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(200)])
        now = datetime.now(timezone.utc)
        info = freshness(repo, cadence_seconds=15, now=now)
        assert info["verdict"] == "stale"

    def test_dead_stroke(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(500)])
        now = datetime.now(timezone.utc)
        info = freshness(repo, cadence_seconds=15, now=now)
        assert info["verdict"] == "dead"

    def test_custom_cadence(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(45)])
        now = datetime.now(timezone.utc)
        # With cadence=30, 45s is 1.5× → fresh
        info = freshness(repo, cadence_seconds=30, now=now)
        assert info["verdict"] == "fresh"

    def test_returns_strokes_path(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(5)])
        info = freshness(repo)
        assert "strokes.jsonl" in info["strokes_path"]

    def test_now_override(self, tmp_path):
        ts = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
        stroke = {"seq": 1, "at": ts.isoformat(), "kind": "thought", "text": "x"}
        repo = _make_repo(tmp_path, strokes=[stroke])
        fake_now = ts + timedelta(seconds=10)
        info = freshness(repo, cadence_seconds=15, now=fake_now)
        assert info["verdict"] == "fresh"
        assert abs(info["age_seconds"] - 10.0) < 1

    def test_last_stroke_at_is_iso(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(5)])
        info = freshness(repo)
        assert info["last_stroke_at"] is not None
        # Should parse without error
        datetime.fromisoformat(info["last_stroke_at"])


# ---------------------------------------------------------------------------
# freshness_report
# ---------------------------------------------------------------------------

class TestFreshnessReport:
    def test_no_strokes(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=None)
        report = freshness_report(repo)
        assert "dead" in report
        assert "no strokes" in report

    def test_seconds_format(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(8)])
        now = datetime.now(timezone.utc)
        report = freshness_report(repo, cadence_seconds=15, now=now)
        assert "fresh" in report
        assert "s ago" in report

    def test_minutes_format(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(120)])
        now = datetime.now(timezone.utc)
        report = freshness_report(repo, cadence_seconds=15, now=now)
        assert "stale" in report  # 120s / 15s = 8× cadence → stale
        assert "m ago" in report

    def test_hours_format(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(7200)])
        now = datetime.now(timezone.utc)
        report = freshness_report(repo, cadence_seconds=15, now=now)
        assert "dead" in report
        assert "h ago" in report

    def test_includes_cadence(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[_stroke(5)])
        report = freshness_report(repo, cadence_seconds=20)
        assert "20s" in report
