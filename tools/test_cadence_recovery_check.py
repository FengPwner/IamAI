#!/usr/bin/env python3
"""Tests for cadence_recovery_check.py"""

import json
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add tools directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from cadence_recovery_check import (
    check_cadence_recovery,
    compute_cadence,
    find_restart_gap,
    parse_timestamp,
    CadenceReport,
    RECOVERED_RATIO,
    MIN_STROKES_FOR_CADENCE,
)


def make_strokes(count, start_time, interval_seconds, kinds=None):
    """Generate test stroke data."""
    if kinds is None:
        kinds = ["devlog", "garden", "note", "thought", "snippet", "metrics"]
    
    strokes = []
    t = start_time
    for i in range(count):
        stroke = {
            "seq": 1000 + i,
            "kind": kinds[i % len(kinds)],
            "at": t.isoformat(),
            "content": f"test stroke {i}"
        }
        strokes.append(stroke)
        t += timedelta(seconds=interval_seconds)
    
    return strokes


def write_strokes_file(strokes):
    """Write strokes to a temp file and return path."""
    fd, path = tempfile.mkstemp(suffix='.jsonl')
    with open(fd, 'w', encoding='utf-8') as f:
        for stroke in strokes:
            f.write(json.dumps(stroke) + '\n')
    return Path(path)


def test_parse_timestamp():
    """Test timestamp parsing."""
    # ISO with timezone
    dt = parse_timestamp("2026-10-31T15:00:00+00:00")
    assert dt.year == 2026
    assert dt.month == 10
    assert dt.day == 31
    assert dt.hour == 15
    
    # ISO with Z
    dt = parse_timestamp("2026-10-31T15:00:00Z")
    assert dt.hour == 15
    
    print("✓ test_parse_timestamp")


def test_compute_cadence():
    """Test cadence computation."""
    start = datetime(2026, 10, 31, 15, 0, 0, tzinfo=timezone.utc)
    strokes = make_strokes(10, start, 15)
    
    cadence = compute_cadence(strokes, 0, 10)
    assert 14.5 <= cadence <= 15.5, f"Expected ~15s, got {cadence}"
    
    # Single stroke
    cadence = compute_cadence(strokes, 0, 1)
    assert cadence == 0.0
    
    # Empty range
    cadence = compute_cadence(strokes, 5, 5)
    assert cadence == 0.0
    
    print("✓ test_compute_cadence")


def test_find_restart_gap():
    """Test restart gap detection."""
    start = datetime(2026, 10, 31, 15, 0, 0, tzinfo=timezone.utc)
    
    # Normal strokes with a big gap in the middle
    strokes = make_strokes(10, start, 15)
    # Insert a 1-hour gap after stroke 5
    for i in range(5, 10):
        old_time = parse_timestamp(strokes[i]['at'])
        new_time = old_time + timedelta(hours=1)
        strokes[i]['at'] = new_time.isoformat()
    
    gap_idx = find_restart_gap(strokes, max_gap=300)
    assert gap_idx == 5, f"Expected gap at index 5, got {gap_idx}"
    
    # No gap case
    strokes_no_gap = make_strokes(10, start, 15)
    gap_idx = find_restart_gap(strokes_no_gap, max_gap=300)
    assert gap_idx is None
    
    print("✓ test_find_restart_gap")


def test_recovered_cadence():
    """Test detection of recovered cadence."""
    start = datetime(2026, 10, 31, 15, 0, 0, tzinfo=timezone.utc)
    
    # Pre-restart: 15s cadence
    pre_strokes = make_strokes(15, start, 15)
    
    # 1-hour gap (restart)
    restart_time = parse_timestamp(pre_strokes[-1]['at']) + timedelta(hours=1)
    
    # Post-restart: 15s cadence (recovered)
    post_strokes = make_strokes(15, restart_time, 15)
    for i, stroke in enumerate(post_strokes):
        stroke['seq'] = 2000 + i
    
    all_strokes = pre_strokes + post_strokes
    path = write_strokes_file(all_strokes)
    
    try:
        report = check_cadence_recovery(path, threshold=0.7)
        assert report.status == "recovered", f"Expected recovered, got {report.status}"
        assert report.recovery_ratio >= 0.7
        assert report.gap_seconds > 3000  # ~1 hour
    finally:
        path.unlink()
    
    print("✓ test_recovered_cadence")


def test_degraded_cadence():
    """Test detection of degraded cadence."""
    start = datetime(2026, 10, 31, 15, 0, 0, tzinfo=timezone.utc)
    
    # Pre-restart: 15s cadence
    pre_strokes = make_strokes(15, start, 15)
    
    # 1-hour gap
    restart_time = parse_timestamp(pre_strokes[-1]['at']) + timedelta(hours=1)
    
    # Post-restart: 60s cadence (degraded, 4x slower)
    post_strokes = make_strokes(15, restart_time, 60)
    for i, stroke in enumerate(post_strokes):
        stroke['seq'] = 2000 + i
    
    all_strokes = pre_strokes + post_strokes
    path = write_strokes_file(all_strokes)
    
    try:
        report = check_cadence_recovery(path, threshold=0.7)
        assert report.status in ("degraded", "stalled"), f"Expected degraded/stalled, got {report.status}"
        assert report.recovery_ratio < 0.7
    finally:
        path.unlink()
    
    print("✓ test_degraded_cadence")


def test_stalled_cadence():
    """Test detection of stalled cadence (no post-restart strokes)."""
    start = datetime(2026, 10, 31, 15, 0, 0, tzinfo=timezone.utc)
    
    # Pre-restart: 15s cadence
    pre_strokes = make_strokes(15, start, 15)
    
    # 2-hour gap
    restart_time = parse_timestamp(pre_strokes[-1]['at']) + timedelta(hours=2)
    
    # Post-restart: only 1 stroke (stalled — not enough to compute cadence)
    post_strokes = make_strokes(1, restart_time, 15)
    for i, stroke in enumerate(post_strokes):
        stroke['seq'] = 2000 + i
    
    all_strokes = pre_strokes + post_strokes
    path = write_strokes_file(all_strokes)
    
    try:
        report = check_cadence_recovery(path, threshold=0.7)
        # With only 1 post-restart stroke, cadence can't be computed
        assert report.status in ("stalled", "no_data"), f"Expected stalled/no_data, got {report.status}"
    finally:
        path.unlink()
    
    print("✓ test_stalled_cadence")


def test_no_strokes_file():
    """Test handling of missing strokes file."""
    report = check_cadence_recovery(Path("/nonexistent/strokes.jsonl"))
    assert report.status == "no_data"
    assert report.strokes_analyzed == 0
    
    print("✓ test_no_strokes_file")


def test_insufficient_strokes():
    """Test handling of insufficient stroke data."""
    start = datetime(2026, 10, 31, 15, 0, 0, tzinfo=timezone.utc)
    strokes = make_strokes(5, start, 15)
    path = write_strokes_file(strokes)
    
    try:
        report = check_cadence_recovery(path)
        assert report.status == "no_data"
    finally:
        path.unlink()
    
    print("✓ test_insufficient_strokes")


def test_irregular_cadence():
    """Test handling of irregular (jittery) cadence."""
    start = datetime(2026, 10, 31, 15, 0, 0, tzinfo=timezone.utc)
    
    # Pre-restart: 15s cadence with some jitter
    pre_strokes = make_strokes(15, start, 15)
    # Add jitter: every other stroke is 5s late
    for i in range(1, len(pre_strokes), 2):
        t = parse_timestamp(pre_strokes[i]['at'])
        t += timedelta(seconds=5)
        pre_strokes[i]['at'] = t.isoformat()
    
    # 1-hour gap
    restart_time = parse_timestamp(pre_strokes[-1]['at']) + timedelta(hours=1)
    
    # Post-restart: 15s cadence (recovered)
    post_strokes = make_strokes(15, restart_time, 15)
    for i, stroke in enumerate(post_strokes):
        stroke['seq'] = 2000 + i
    
    all_strokes = pre_strokes + post_strokes
    path = write_strokes_file(all_strokes)
    
    try:
        report = check_cadence_recovery(path, threshold=0.5)
        # Should still detect recovery despite jitter
        assert report.status in ("recovered", "degraded")
        assert report.gap_seconds > 3000
    finally:
        path.unlink()
    
    print("✓ test_irregular_cadence")


def test_json_output():
    """Test JSON output format."""
    start = datetime(2026, 10, 31, 15, 0, 0, tzinfo=timezone.utc)
    strokes = make_strokes(20, start, 15)
    path = write_strokes_file(strokes)
    
    try:
        report = check_cadence_recovery(path)
        # Verify all fields are present
        assert hasattr(report, 'status')
        assert hasattr(report, 'pre_cadence_s')
        assert hasattr(report, 'post_cadence_s')
        assert hasattr(report, 'current_cadence_s')
        assert hasattr(report, 'recovery_ratio')
        assert hasattr(report, 'gap_seconds')
        assert hasattr(report, 'strokes_analyzed')
        assert hasattr(report, 'last_stroke_age_s')
        assert hasattr(report, 'message')
    finally:
        path.unlink()
    
    print("✓ test_json_output")


if __name__ == "__main__":
    tests = [
        test_parse_timestamp,
        test_compute_cadence,
        test_find_restart_gap,
        test_recovered_cadence,
        test_degraded_cadence,
        test_stalled_cadence,
        test_no_strokes_file,
        test_insufficient_strokes,
        test_irregular_cadence,
        test_json_output,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: {type(e).__name__}: {e}")
            failed += 1
    
    print(f"\n{passed}/{passed + failed} tests passed")
    sys.exit(0 if failed == 0 else 1)
