#!/usr/bin/env python3
"""Tests for overnight_gap_classifier.py — 15 tests.

Covers:
  - load_strokes with valid, empty, and malformed data
  - classify_gaps with various gap patterns (clean, mild, severe, extended)
  - edge cases: single stroke, zero cadence, timezone handling
  - main() CLI entrypoint with --json flag
"""

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from overnight_gap_classifier import (
    EXTENDED_OUTAGE_X,
    MILD_STALL_X,
    SEVERE_STALL_X,
    OvernightReport,
    classify_gaps,
    find_repo_root,
    load_strokes,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_strokes(base_time: datetime, intervals_s: list[float], seq_start: int = 1) -> list[dict]:
    """Build a list of stroke dicts with given intervals (seconds) between them."""
    strokes = []
    current = base_time
    for i, interval in enumerate(intervals_s):
        strokes.append({
            "seq": seq_start + i,
            "at": current,
            "raw_at": current.isoformat(),
        })
        current = current + timedelta(seconds=interval)
    # Add the last stroke after the final interval.
    strokes.append({
        "seq": seq_start + len(intervals_s),
        "at": current,
        "raw_at": current.isoformat(),
    })
    return strokes


def _write_strokes_file(repo: Path, lines: list[str]) -> None:
    """Write raw JSONL lines to data/strokes.jsonl in the given repo."""
    data_dir = repo / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "strokes.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_repo(tmp_path: Path) -> Path:
    """Create a minimal repo structure with data/ dir."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "data").mkdir()
    return repo


# ---------------------------------------------------------------------------
# find_repo_root
# ---------------------------------------------------------------------------

class TestFindRepoRoot:
    def test_finds_repo_with_data_dir(self, tmp_path):
        repo = _make_repo(tmp_path)
        (repo / "data" / "strokes.jsonl").write_text("")
        result = find_repo_root(repo)
        assert result == repo

    def test_finds_repo_from_subdir(self, tmp_path):
        repo = _make_repo(tmp_path)
        (repo / "data" / "strokes.jsonl").write_text("")
        subdir = repo / "tools"
        subdir.mkdir()
        result = find_repo_root(subdir)
        assert result == repo

    def test_returns_cwd_when_no_data(self, tmp_path):
        result = find_repo_root(tmp_path)
        assert result == tmp_path


# ---------------------------------------------------------------------------
# load_strokes
# ---------------------------------------------------------------------------

class TestLoadStrokes:
    def test_loads_recent_strokes(self, tmp_path):
        repo = _make_repo(tmp_path)
        now = datetime.now(timezone.utc)
        lines = []
        for i in range(5):
            t = (now - timedelta(hours=2, minutes=i * 5)).isoformat()
            lines.append(json.dumps({"seq": i + 1, "at": t, "kind": "thought", "text": f"stroke {i}"}))
        _write_strokes_file(repo, lines)

        strokes = load_strokes(repo, window_hours=3)
        assert len(strokes) == 5

    def test_filters_old_strokes(self, tmp_path):
        repo = _make_repo(tmp_path)
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=48)).isoformat()
        recent = (now - timedelta(hours=1)).isoformat()
        lines = [
            json.dumps({"seq": 1, "at": old, "kind": "thought", "text": "old"}),
            json.dumps({"seq": 2, "at": recent, "kind": "thought", "text": "recent"}),
        ]
        _write_strokes_file(repo, lines)

        strokes = load_strokes(repo, window_hours=12)
        assert len(strokes) == 1
        assert strokes[0]["seq"] == 2

    def test_handles_malformed_lines(self, tmp_path):
        repo = _make_repo(tmp_path)
        now = datetime.now(timezone.utc)
        lines = [
            "this is not json",
            json.dumps({"seq": 1, "at": now.isoformat(), "kind": "thought", "text": "ok"}),
            json.dumps({"seq": 2, "kind": "thought", "text": "missing at"}),
            "",
            json.dumps({"seq": 3, "at": (now - timedelta(minutes=5)).isoformat(), "kind": "note", "text": "also ok"}),
        ]
        _write_strokes_file(repo, lines)

        strokes = load_strokes(repo, window_hours=12)
        assert len(strokes) == 2

    def test_returns_empty_when_no_file(self, tmp_path):
        repo = _make_repo(tmp_path)
        # Don't create strokes.jsonl
        strokes = load_strokes(repo, window_hours=12)
        assert strokes == []

    def test_naive_timestamps_treated_as_utc(self, tmp_path):
        repo = _make_repo(tmp_path)
        now = datetime.now(timezone.utc)
        naive = now.replace(tzinfo=None).isoformat()
        lines = [json.dumps({"seq": 1, "at": naive, "kind": "thought", "text": "naive ts"})]
        _write_strokes_file(repo, lines)

        strokes = load_strokes(repo, window_hours=12)
        assert len(strokes) == 1
        assert strokes[0]["at"].tzinfo is not None


# ---------------------------------------------------------------------------
# classify_gaps
# ---------------------------------------------------------------------------

class TestClassifyGaps:
    def test_clean_run(self):
        """All gaps are within 2× cadence — clean run."""
        base = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)
        # 15s cadence, all gaps are 15s → multiplier 1.0
        strokes = _make_strokes(base, [15] * 10)
        report = classify_gaps(strokes, cadence_s=15.0)
        assert report.label == "clean_run"
        assert report.multiplier == pytest.approx(1.0, abs=0.1)
        assert report.strokes_in_window == 11

    def test_mild_stall(self):
        """A gap of 3× cadence is mild_stall."""
        base = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)
        # Normal strokes, then one 45s gap (3× 15s cadence)
        intervals = [15, 15, 15, 45, 15, 15]
        strokes = _make_strokes(base, intervals)
        report = classify_gaps(strokes, cadence_s=15.0)
        assert report.label == "mild_stall"
        assert report.longest_gap_s == pytest.approx(45.0, abs=0.1)

    def test_severe_stall(self):
        """A gap of 10× cadence is severe_stall."""
        base = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)
        intervals = [15, 15, 150, 15, 15]  # 150s = 10× 15s
        strokes = _make_strokes(base, intervals)
        report = classify_gaps(strokes, cadence_s=15.0)
        assert report.label == "severe_stall"
        assert report.multiplier == pytest.approx(10.0, abs=0.1)

    def test_extended_outage(self):
        """A gap of 120× cadence (30 min at 15s cadence) is extended_outage."""
        base = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)
        intervals = [15, 15, 1800, 15]  # 1800s = 120× 15s
        strokes = _make_strokes(base, intervals)
        report = classify_gaps(strokes, cadence_s=15.0)
        assert report.label == "extended_outage"
        assert report.longest_gap_s == pytest.approx(1800.0, abs=0.1)

    def test_single_stroke(self):
        """Only one stroke in window — no gap measurable, classify as clean_run."""
        base = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)
        strokes = [{"seq": 1, "at": base, "raw_at": base.isoformat()}]
        report = classify_gaps(strokes, cadence_s=15.0)
        assert report.label == "clean_run"
        assert report.strokes_in_window == 1

    def test_empty_strokes(self):
        """No strokes at all — extended_outage by default."""
        report = classify_gaps([], cadence_s=15.0)
        assert report.label == "extended_outage"

    def test_zero_cadence(self):
        """Zero cadence should not crash — multiplier becomes inf → extended_outage."""
        base = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)
        strokes = _make_strokes(base, [15, 15])
        report = classify_gaps(strokes, cadence_s=0.0)
        assert report.label == "extended_outage"
        assert report.multiplier == float("inf")

    def test_gap_timestamps_recorded(self):
        """The report should point to the strokes bracketing the longest gap."""
        base = datetime(2026, 10, 31, 2, 0, tzinfo=timezone.utc)
        intervals = [15, 300, 15]  # 300s gap between stroke 2 and 3
        strokes = _make_strokes(base, intervals)
        report = classify_gaps(strokes, cadence_s=15.0)
        # gap_started_at is the stroke before the gap (stroke index 1)
        # gap_ended_at is the stroke after the gap (stroke index 2)
        assert report.gap_started_at == strokes[1]["raw_at"]
        assert report.gap_ended_at == strokes[2]["raw_at"]


# ---------------------------------------------------------------------------
# OvernightReport
# ---------------------------------------------------------------------------

class TestOvernightReport:
    def test_to_dict(self):
        report = OvernightReport(
            label="clean_run",
            longest_gap_s=14.5,
            cadence_s=15.0,
            window_hours=8,
            strokes_in_window=1920,
            gap_started_at="2026-10-31T00:00:00+00:00",
            gap_ended_at="2026-10-31T00:00:15+00:00",
            multiplier=0.97,
        )
        d = report.to_dict()
        assert d["label"] == "clean_run"
        assert d["longest_gap_s"] == 14.5
        assert d["strokes_in_window"] == 1920

    def test_json_serializable(self):
        report = OvernightReport(
            label="severe_stall",
            longest_gap_s=225.0,
            cadence_s=15.0,
            window_hours=6,
            strokes_in_window=500,
            gap_started_at="2026-10-31T03:00:00+00:00",
            gap_ended_at="2026-10-31T03:03:45+00:00",
            multiplier=15.0,
        )
        # Should not raise.
        serialized = json.dumps(report.to_dict())
        parsed = json.loads(serialized)
        assert parsed["label"] == "severe_stall"


# ---------------------------------------------------------------------------
# main() CLI
# ---------------------------------------------------------------------------

class TestMain:
    def test_main_with_missing_repo(self, tmp_path, monkeypatch):
        """main() should exit 2 when no strokes found."""
        monkeypatch.setattr(sys, "argv", [
            "overnight_gap_classifier.py",
            "--repo", str(tmp_path),
            "--hours", "1",
        ])
        result = main()
        assert result == 2

    def test_main_json_output(self, tmp_path, monkeypatch, capsys):
        """--json flag should produce valid JSON output."""
        repo = _make_repo(tmp_path)
        now = datetime.now(timezone.utc)
        lines = []
        for i in range(10):
            t = (now - timedelta(minutes=i)).isoformat()
            lines.append(json.dumps({"seq": i + 1, "at": t, "kind": "thought", "text": f"s{i}"}))
        _write_strokes_file(repo, lines)

        monkeypatch.setattr(sys, "argv", [
            "overnight_gap_classifier.py",
            "--repo", str(repo),
            "--hours", "1",
            "--json",
        ])
        result = main()
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "label" in output
        assert result in (0, 1, 2, 3)
