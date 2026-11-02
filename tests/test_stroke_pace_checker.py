"""Tests for stroke_pace_checker.py — pace classification and edge cases."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from stroke_pace_checker import (
    parse_timestamp,
    load_recent_strokes,
    compute_intervals,
    classify_pace,
    check_pace,
    PaceReport,
)


# --- parse_timestamp ---

def test_parse_timestamp_with_timezone():
    dt = parse_timestamp("2026-11-02T18:16:00+00:00")
    assert dt.year == 2026
    assert dt.month == 11
    assert dt.hour == 18


def test_parse_timestamp_with_z_suffix():
    dt = parse_timestamp("2026-11-02T18:16:00Z")
    assert dt.year == 2026
    assert dt.tzinfo is not None


# --- load_recent_strokes ---

def test_load_recent_strokes_empty_file(tmp_path):
    p = tmp_path / "strokes.jsonl"
    p.write_text("")
    assert load_recent_strokes(p, 10) == []


def test_load_recent_strokes_missing_file(tmp_path):
    p = tmp_path / "nonexistent.jsonl"
    assert load_recent_strokes(p, 10) == []


def test_load_recent_strokes_returns_last_n(tmp_path):
    p = tmp_path / "strokes.jsonl"
    lines = [json.dumps({"seq": i, "at": f"2026-11-02T{10+i:02d}:00:00+00:00", "kind": "thought", "text": f"t{i}"}) for i in range(10)]
    p.write_text("\n".join(lines) + "\n")
    result = load_recent_strokes(p, 5)
    assert len(result) == 5
    assert result[0]["seq"] == 5
    assert result[-1]["seq"] == 9


# --- compute_intervals ---

def test_compute_intervals_single_stroke():
    strokes = [{"at": "2026-11-02T18:00:00+00:00", "seq": 1}]
    assert compute_intervals(strokes) == []


def test_compute_intervals_normal():
    base = datetime(2026, 11, 2, 18, 0, 0, tzinfo=timezone.utc)
    strokes = []
    for i in range(5):
        t = base + timedelta(seconds=15 * i)
        strokes.append({"at": t.isoformat(), "seq": i})
    intervals = compute_intervals(strokes)
    assert len(intervals) == 4
    assert all(iv == 15.0 for iv in intervals)


def test_compute_intervals_irregular():
    strokes = [
        {"at": "2026-11-02T18:00:00+00:00", "seq": 1},
        {"at": "2026-11-02T18:00:15+00:00", "seq": 2},
        {"at": "2026-11-02T18:01:00+00:00", "seq": 3},
    ]
    intervals = compute_intervals(strokes)
    assert intervals == [15.0, 45.0]


# --- classify_pace ---

def test_classify_on_pace():
    assert classify_pace(15.0, 15) == "on-pace"
    assert classify_pace(22.0, 15) == "on-pace"  # 22/15 = 1.47, just under 1.5


def test_classify_drifting():
    assert classify_pace(30.0, 15) == "drifting"  # 2.0×
    assert classify_pace(44.0, 15) == "drifting"  # 2.93×


def test_classify_stalled():
    assert classify_pace(46.0, 15) == "stalled"  # 3.07×
    assert classify_pace(300.0, 15) == "stalled"


def test_classify_zero_cadence():
    assert classify_pace(15.0, 0) == "stalled"


# --- check_pace integration ---

def test_check_pace_on_pace(tmp_path):
    p = tmp_path / "strokes.jsonl"
    base = datetime(2026, 11, 2, 18, 0, 0, tzinfo=timezone.utc)
    lines = []
    for i in range(20):
        t = base + timedelta(seconds=15 * i)
        lines.append(json.dumps({"seq": i, "at": t.isoformat(), "kind": "thought", "text": f"stroke {i}"}))
    p.write_text("\n".join(lines) + "\n")

    report = check_pace(strokes_path=p, expected_cadence=15, lookback=20)
    assert report.verdict == "on-pace"
    assert report.median_interval == 15.0
    assert report.stroke_count == 20


def test_check_pace_drifting(tmp_path):
    p = tmp_path / "strokes.jsonl"
    base = datetime(2026, 11, 2, 18, 0, 0, tzinfo=timezone.utc)
    lines = []
    for i in range(10):
        t = base + timedelta(seconds=30 * i)  # 2× expected
        lines.append(json.dumps({"seq": i, "at": t.isoformat(), "kind": "thought", "text": f"stroke {i}"}))
    p.write_text("\n".join(lines) + "\n")

    report = check_pace(strokes_path=p, expected_cadence=15, lookback=10)
    assert report.verdict == "drifting"
    assert report.median_interval == 30.0


def test_check_pace_stalled_empty(tmp_path):
    p = tmp_path / "strokes.jsonl"
    p.write_text("")

    report = check_pace(strokes_path=p, expected_cadence=15)
    assert report.verdict == "stalled"
    assert report.stroke_count == 0


def test_check_pace_json_serializable(tmp_path):
    p = tmp_path / "strokes.jsonl"
    base = datetime(2026, 11, 2, 18, 0, 0, tzinfo=timezone.utc)
    lines = []
    for i in range(5):
        t = base + timedelta(seconds=15 * i)
        lines.append(json.dumps({"seq": i, "at": t.isoformat(), "kind": "thought", "text": f"stroke {i}"}))
    p.write_text("\n".join(lines) + "\n")

    report = check_pace(strokes_path=p, expected_cadence=15, lookback=5)
    # Verify it serializes without error
    data = json.loads(json.dumps(report.__dict__))
    assert "verdict" in data
    assert data["verdict"] in ("on-pace", "drifting", "stalled")
