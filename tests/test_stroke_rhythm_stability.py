#!/usr/bin/env python3
"""Tests for tools/stroke_rhythm_stability.py — rhythm jitter analysis."""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from stroke_rhythm_stability import (
    analyze,
    classify_stability,
    coefficient_of_variation,
    compute_intervals,
    count_micro_stalls,
    format_text,
    load_strokes,
    micro_stall_rate,
    parse_timestamp,
)


# ── helpers ──────────────────────────────────────────────────────────────


def _make_strokes(timestamps: list[str]) -> list[dict]:
    """Create minimal stroke records with explicit ISO timestamps."""
    return [
        {"seq": i, "at": ts, "kind": "thought", "text": f"s{i}"}
        for i, ts in enumerate(timestamps)
    ]


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _even_strokes(n: int, interval_s: float = 15.0, start: datetime | None = None) -> list[dict]:
    """Generate n strokes at perfectly even intervals."""
    if start is None:
        start = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)
    timestamps = [_iso(start + timedelta(seconds=i * interval_s)) for i in range(n)]
    return _make_strokes(timestamps)


# ── load_strokes ─────────────────────────────────────────────────────────


def test_load_strokes_missing_file(tmp_path: Path):
    assert load_strokes(tmp_path / "nope.jsonl") == []


def test_load_strokes_valid(tmp_path: Path):
    f = tmp_path / "s.jsonl"
    f.write_text(json.dumps({"seq": 1, "at": "x", "kind": "note"}) + "\n")
    result = load_strokes(f)
    assert len(result) == 1
    assert result[0]["seq"] == 1


def test_load_strokes_blank_lines(tmp_path: Path):
    f = tmp_path / "s.jsonl"
    f.write_text("\n\n" + json.dumps({"seq": 2}) + "\n\n")
    assert len(load_strokes(f)) == 1


def test_load_strokes_malformed_json(tmp_path: Path):
    f = tmp_path / "s.jsonl"
    f.write_text("{bad\n" + json.dumps({"seq": 3}) + "\n")
    result = load_strokes(f)
    assert len(result) == 1
    assert result[0]["seq"] == 3


# ── parse_timestamp ──────────────────────────────────────────────────────


def test_parse_timestamp_z_suffix():
    dt = parse_timestamp("2026-10-24T12:00:00Z")
    assert dt is not None
    assert dt.year == 2026


def test_parse_timestamp_offset():
    dt = parse_timestamp("2026-10-24T12:00:00+08:00")
    assert dt is not None


def test_parse_timestamp_empty():
    assert parse_timestamp("") is None


def test_parse_timestamp_none():
    assert parse_timestamp(None) is None


def test_parse_timestamp_garbage():
    assert parse_timestamp("not-a-date") is None


# ── compute_intervals ────────────────────────────────────────────────────


def test_compute_intervals_even():
    strokes = _even_strokes(5, interval_s=10.0)
    intervals = compute_intervals(strokes)
    assert len(intervals) == 4
    assert all(abs(iv - 10.0) < 0.01 for iv in intervals)


def test_compute_intervals_single_stroke():
    assert compute_intervals(_even_strokes(1)) == []


def test_compute_intervals_empty():
    assert compute_intervals([]) == []


def test_compute_intervals_skips_bad_timestamps():
    strokes = [
        {"seq": 0, "at": "2026-10-24T12:00:00Z"},
        {"seq": 1, "at": "bad"},
        {"seq": 2, "at": "2026-10-24T12:00:30Z"},
    ]
    intervals = compute_intervals(strokes)
    assert len(intervals) == 1
    assert abs(intervals[0] - 30.0) < 0.01


def test_compute_intervals_negative_gap_skipped():
    """Out-of-order timestamps produce negative deltas which are skipped."""
    strokes = _make_strokes([
        "2026-10-24T12:00:00Z",
        "2026-10-24T11:59:00Z",  # earlier than first
        "2026-10-24T12:00:30Z",
    ])
    intervals = compute_intervals(strokes)
    # first gap is negative (skipped), second gap is 90s from stroke 0 to 2
    assert len(intervals) == 1
    assert abs(intervals[0] - 90.0) < 0.01


# ── coefficient_of_variation ─────────────────────────────────────────────


def test_cv_empty():
    assert coefficient_of_variation([]) == 0.0


def test_cv_single():
    assert coefficient_of_variation([15.0]) == 0.0


def test_cv_perfectly_even():
    assert coefficient_of_variation([15.0, 15.0, 15.0, 15.0]) == 0.0


def test_cv_known_value():
    """CV of [10, 20, 30] = stddev/mean = 10/20 = 0.5."""
    cv = coefficient_of_variation([10.0, 20.0, 30.0])
    assert abs(cv - 0.5) < 0.01  # stddev=10, mean=20, cv=0.5


def test_cv_high_variance():
    cv = coefficient_of_variation([1.0, 100.0, 1.0, 100.0])
    assert cv > 1.0


def test_cv_low_variance():
    cv = coefficient_of_variation([14.5, 15.0, 15.5, 14.8, 15.2])
    assert cv < 0.1


# ── count_micro_stalls ───────────────────────────────────────────────────


def test_count_micro_stalls_none():
    # all intervals at cadence (15s) — none in 30-75s range
    assert count_micro_stalls([15.0, 15.0, 15.0], cadence=15.0) == 0


def test_count_micro_stalls_some():
    # 45s and 60s are micro-stalls at cadence 15 (range 30-75)
    intervals = [15.0, 45.0, 15.0, 60.0, 15.0]
    assert count_micro_stalls(intervals, cadence=15.0) == 2


def test_count_micro_stalls_boundary():
    # exactly 30s and 75s are on boundaries (inclusive)
    assert count_micro_stalls([30.0, 75.0], cadence=15.0) == 2


def test_count_micro_stalls_full_stall_not_counted():
    # 100s > 5× cadence — that's a full stall, not micro
    assert count_micro_stalls([100.0], cadence=15.0) == 0


def test_count_micro_stalls_empty():
    assert count_micro_stalls([], cadence=15.0) == 0


# ── micro_stall_rate ─────────────────────────────────────────────────────


def test_micro_stall_rate_none():
    assert micro_stall_rate([15.0, 15.0, 15.0], cadence=15.0) == 0.0


def test_micro_stall_rate_all():
    assert micro_stall_rate([45.0, 45.0, 45.0], cadence=15.0) == 1.0


def test_micro_stall_rate_half():
    assert abs(micro_stall_rate([15.0, 45.0], cadence=15.0) - 0.5) < 0.01


def test_micro_stall_rate_empty():
    assert micro_stall_rate([], cadence=15.0) == 0.0


# ── classify_stability ───────────────────────────────────────────────────


def test_classify_steady():
    assert classify_stability(0.0) == "STEADY"
    assert classify_stability(0.29) == "STEADY"


def test_classify_wobbly():
    assert classify_stability(0.3) == "WOBBLY"
    assert classify_stability(0.5) == "WOBBLY"
    assert classify_stability(0.69) == "WOBBLY"


def test_classify_erratic():
    assert classify_stability(0.7) == "ERRATIC"
    assert classify_stability(1.0) == "ERRATIC"
    assert classify_stability(1.49) == "ERRATIC"


def test_classify_broken():
    assert classify_stability(1.5) == "BROKEN"
    assert classify_stability(3.0) == "BROKEN"


# ── format_text ──────────────────────────────────────────────────────────


def test_format_text_contains_key_fields():
    result = {
        "stroke_count": 50,
        "interval_count": 49,
        "mean_interval_s": 16.3,
        "median_interval_s": 15.1,
        "cv": 0.4234,
        "stability_class": "WOBBLY",
        "micro_stall_count": 5,
        "micro_stall_rate": 0.1020,
        "target_cadence_s": 15.0,
    }
    text = format_text(result)
    assert "WOBBLY" in text
    assert "50" in text
    assert "16.3" in text
    assert "micro-stalls" in text


def test_format_text_empty_result():
    result = {
        "stroke_count": 0, "interval_count": 0,
        "mean_interval_s": 0.0, "median_interval_s": 0.0,
        "cv": 0.0, "stability_class": "STEADY",
        "micro_stall_count": 0, "micro_stall_rate": 0.0,
        "target_cadence_s": 15.0,
    }
    text = format_text(result)
    assert "STEADY" in text


# ── analyze (integration) ────────────────────────────────────────────────


def test_analyze_even_strokes(tmp_path: Path):
    f = tmp_path / "s.jsonl"
    strokes = _even_strokes(50, interval_s=15.0)
    with open(f, "w") as fh:
        for s in strokes:
            fh.write(json.dumps(s) + "\n")
    result = analyze(path=f, window=100, cadence=15.0)
    assert result["stability_class"] == "STEADY"
    assert result["cv"] < 0.1
    assert result["micro_stall_count"] == 0
    assert result["stroke_count"] == 50


def test_analyze_erratic_strokes(tmp_path: Path):
    f = tmp_path / "s.jsonl"
    base = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)
    # alternate between 5s and 60s intervals — high CV
    timestamps = []
    t = base
    for i in range(40):
        timestamps.append(_iso(t))
        t += timedelta(seconds=5.0 if i % 2 == 0 else 60.0)
    strokes = _make_strokes(timestamps)
    with open(f, "w") as fh:
        for s in strokes:
            fh.write(json.dumps(s) + "\n")
    result = analyze(path=f, window=100, cadence=15.0)
    assert result["cv"] > 0.5
    assert result["micro_stall_count"] > 0


def test_analyze_window_truncation(tmp_path: Path):
    f = tmp_path / "s.jsonl"
    strokes = _even_strokes(200, interval_s=15.0)
    with open(f, "w") as fh:
        for s in strokes:
            fh.write(json.dumps(s) + "\n")
    result = analyze(path=f, window=50, cadence=15.0)
    assert result["stroke_count"] == 50
    assert result["interval_count"] == 49


def test_analyze_missing_file(tmp_path: Path):
    result = analyze(path=tmp_path / "nope.jsonl", window=100, cadence=15.0)
    assert result["stroke_count"] == 0
    assert result["stability_class"] == "STEADY"


def test_analyze_empty_file(tmp_path: Path):
    f = tmp_path / "s.jsonl"
    f.write_text("")
    result = analyze(path=f, window=100, cadence=15.0)
    assert result["stroke_count"] == 0


def test_analyze_custom_cadence(tmp_path: Path):
    f = tmp_path / "s.jsonl"
    strokes = _even_strokes(30, interval_s=30.0)
    with open(f, "w") as fh:
        for s in strokes:
            fh.write(json.dumps(s) + "\n")
    result = analyze(path=f, window=100, cadence=30.0)
    assert result["stability_class"] == "STEADY"
    assert result["micro_stall_count"] == 0
