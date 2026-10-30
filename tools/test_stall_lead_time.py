#!/usr/bin/env python3
"""Tests for stall_lead_time.py"""

import json
import sys
import tempfile
from pathlib import Path

# Ensure imports work when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stall_lead_time import (
    WarningSign,
    StallEvent,
    detect_gaps,
    compute_rolling_median,
    detect_stalls,
    detect_warning_signs,
    format_report,
    parse_stroke_timestamps,
    analyse,
)


def test_warning_sign_creation():
    ws = WarningSign(kind="cadence_drift", timestamp=1000.0, severity=0.5, detail="test")
    assert ws.kind == "cadence_drift"
    assert ws.severity == 0.5
    print("  pass: warning_sign_creation")


def test_stall_event_lead_time():
    stall = StallEvent(onset=2000.0, duration=300.0)
    assert stall.lead_time == 0.0  # no warnings

    stall.warnings = [
        WarningSign("cadence_drift", 1900.0, 0.3),
        WarningSign("gap_spike", 1950.0, 0.6),
    ]
    assert stall.lead_time == 100.0  # earliest warning at 1900
    print("  pass: stall_event_lead_time")


def test_stall_event_warning_types():
    stall = StallEvent(onset=2000.0, duration=300.0)
    stall.warnings = [
        WarningSign("cadence_drift", 1900.0, 0.3),
        WarningSign("gap_spike", 1950.0, 0.6),
        WarningSign("cadence_drift", 1920.0, 0.4),
    ]
    types = stall.warning_types
    assert types.count("cadence_drift") == 2
    assert types.count("gap_spike") == 1
    print("  pass: stall_event_warning_types")


def test_detect_gaps():
    timestamps = [100.0, 115.0, 130.0, 200.0, 215.0]
    gaps = detect_gaps(timestamps)
    assert len(gaps) == 4
    assert gaps[0] == (100.0, 15.0)
    assert gaps[1] == (115.0, 15.0)
    assert gaps[2] == (130.0, 70.0)  # big gap
    assert gaps[3] == (200.0, 15.0)
    print("  pass: detect_gaps")


def test_detect_gaps_empty():
    assert detect_gaps([]) == []
    assert detect_gaps([100.0]) == []
    print("  pass: detect_gaps_empty")


def test_rolling_median_basic():
    gaps = [15.0, 15.0, 15.0, 15.0, 15.0]
    medians = compute_rolling_median(gaps, window=5)
    assert len(medians) == 5
    assert all(m == 15.0 for m in medians)
    print("  pass: rolling_median_basic")


def test_rolling_median_with_outlier():
    gaps = [15.0] * 10 + [100.0] + [15.0] * 10
    medians = compute_rolling_median(gaps, window=5)
    # The outlier should not shift the median much
    assert medians[10] == 15.0 or medians[10] == 100.0  # median of [15,15,15,15,100] = 15
    print("  pass: rolling_median_with_outlier")


def test_detect_stalls_basic():
    # Regular 15s cadence with one 300s gap (stall)
    timestamps = list(range(0, 300, 15))  # 0,15,30,...,285
    timestamps.append(585)  # 300s gap
    timestamps.extend(range(600, 900, 15))

    gaps = detect_gaps(timestamps)
    gap_durations = [g for _, g in gaps]
    medians = compute_rolling_median(gap_durations, window=10)
    stalls = detect_stalls(gaps, medians, stall_threshold=10.0)

    assert len(stalls) >= 1
    found_big = any(s.duration >= 285 for s in stalls)
    assert found_big, f"expected stall >= 285s, got {[s.duration for s in stalls]}"
    print("  pass: detect_stalls_basic")


def test_detect_stalls_none():
    # Perfectly regular cadence
    timestamps = list(range(0, 300, 15))
    gaps = detect_gaps(timestamps)
    gap_durations = [g for _, g in gaps]
    medians = compute_rolling_median(gap_durations, window=10)
    stalls = detect_stalls(gaps, medians, stall_threshold=10.0)
    assert len(stalls) == 0
    print("  pass: detect_stalls_none")


def test_detect_warning_signs():
    # Build a scenario with cadence drift before a stall
    base_ts = 1000.0
    timestamps = []
    # Normal cadence: 15s
    for i in range(20):
        timestamps.append(base_ts + i * 15)
    # Drift: gaps gradually increase
    drift_start = timestamps[-1]
    for i in range(5):
        gap = 15 + (i + 1) * 8  # 23, 31, 39, 47, 55
        timestamps.append(timestamps[-1] + gap)
    # Stall: 500s gap
    timestamps.append(timestamps[-1] + 500)
    # Recovery
    for i in range(5):
        timestamps.append(timestamps[-1] + 15)

    gaps = detect_gaps(timestamps)
    gap_durations = [g for _, g in gaps]
    medians = compute_rolling_median(gap_durations, window=10)

    # Find the stall
    stalls = detect_stalls(gaps, medians, stall_threshold=10.0)
    assert len(stalls) >= 1

    stall = stalls[0]
    warnings = detect_warning_signs(gaps, medians, stall, lookback=30)

    # Should have detected some cadence drift warnings
    drift_warnings = [w for w in warnings if w.kind == "cadence_drift"]
    assert len(drift_warnings) > 0, "expected cadence_drift warnings"
    print("  pass: detect_warning_signs")


def test_format_report_no_stalls():
    report = format_report([])
    assert "no stalls" in report.lower()
    print("  pass: format_report_no_stalls")


def test_format_report_with_stalls():
    stall = StallEvent(onset=1698000000.0, duration=300.0)
    stall.warnings = [
        WarningSign("cadence_drift", 1697999900.0, 0.4, "gap 25s vs median 15s"),
        WarningSign("gap_spike", 1697999950.0, 0.7, "spike 80s (5.3x median)"),
    ]
    report = format_report([stall])
    assert "stall 1" in report
    assert "lead time: 100s" in report
    assert "cadence_drift" in report
    assert "gap_spike" in report
    print("  pass: format_report_with_stalls")


def test_format_report_abrupt_stall():
    stall = StallEvent(onset=1698000000.0, duration=600.0)
    report = format_report([stall])
    assert "no warning signs" in report.lower()
    assert "abrupt" in report.lower()
    print("  pass: format_report_abrupt_stall")


def test_parse_stroke_timestamps():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        data_dir = repo / "data"
        data_dir.mkdir()

        strokes = [
            {"writer": "qwen", "timestamp": "2026-10-22T10:00:00+00:00", "content": "a"},
            {"writer": "qwen", "timestamp": "2026-10-22T10:00:15+00:00", "content": "b"},
            {"writer": "other", "timestamp": "2026-10-22T10:00:30+00:00", "content": "c"},
            {"writer": "qwen", "timestamp": "2026-10-22T10:00:30+00:00", "content": "d"},
        ]
        (data_dir / "strokes.jsonl").write_text(
            "\n".join(json.dumps(s) for s in strokes)
        )

        ts = parse_stroke_timestamps(repo, "qwen")
        assert len(ts) == 3  # only qwen's strokes
        assert ts == sorted(ts)  # should be sorted
        print("  pass: parse_stroke_timestamps")


def test_parse_stroke_timestamps_missing_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        ts = parse_stroke_timestamps(repo, "qwen")
        assert ts == []
        print("  pass: parse_stroke_timestamps_missing_file")


def test_analyse_insufficient_data():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        stalls = analyse(repo, "qwen", window=20)
        assert stalls == []
        print("  pass: analyse_insufficient_data")


def test_analyse_end_to_end():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        data_dir = repo / "data"
        data_dir.mkdir()

        # Build a realistic stroke sequence with a stall
        strokes = []
        t = 1698000000.0
        # Normal strokes: 15s apart
        for i in range(50):
            dt = t + i * 15
            strokes.append({
                "writer": "qwen",
                "timestamp": f"2026-10-22T{(i//240)+10:02d}:{((i*15)//60)%60:02d}:{(i*15)%60:02d}+00:00",
                "content": f"stroke {i}"
            })

        # Use ISO timestamps properly
        from datetime import datetime, timezone
        strokes = []
        base = datetime(2026, 10, 22, 10, 0, 0, tzinfo=timezone.utc)
        for i in range(50):
            ts = base.timestamp() + i * 15
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            strokes.append({
                "writer": "qwen",
                "timestamp": dt.isoformat(),
                "content": f"stroke {i}"
            })

        # Gap: 300s
        last_ts = base.timestamp() + 49 * 15
        gap_ts = last_ts + 300
        dt = datetime.fromtimestamp(gap_ts, tz=timezone.utc)
        strokes.append({
            "writer": "qwen",
            "timestamp": dt.isoformat(),
            "content": "after stall"
        })

        # Recovery
        for i in range(10):
            ts = gap_ts + (i + 1) * 15
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            strokes.append({
                "writer": "qwen",
                "timestamp": dt.isoformat(),
                "content": f"recovery {i}"
            })

        (data_dir / "strokes.jsonl").write_text(
            "\n".join(json.dumps(s) for s in strokes)
        )

        stalls = analyse(repo, "qwen", window=10, stall_threshold=10.0)
        assert len(stalls) >= 1
        print("  pass: analyse_end_to_end")


def test_lead_time_zero_no_warnings():
    stall = StallEvent(onset=1000.0, duration=500.0)
    assert stall.lead_time == 0.0
    print("  pass: lead_time_zero_no_warnings")


def test_multiple_stalls():
    """Test detection of multiple distinct stalls."""
    timestamps = []
    base = 1000.0
    # First normal segment
    for i in range(20):
        timestamps.append(base + i * 15)
    # First stall (200s)
    timestamps.append(timestamps[-1] + 200)
    # Recovery
    for i in range(20):
        timestamps.append(timestamps[-1] + 15)
    # Second stall (300s)
    timestamps.append(timestamps[-1] + 300)
    # Recovery
    for i in range(10):
        timestamps.append(timestamps[-1] + 15)

    gaps = detect_gaps(timestamps)
    gap_durations = [g for _, g in gaps]
    medians = compute_rolling_median(gap_durations, window=10)
    stalls = detect_stalls(gaps, medians, stall_threshold=10.0)

    assert len(stalls) >= 2, f"expected 2 stalls, got {len(stalls)}"
    print("  pass: multiple_stalls")


if __name__ == "__main__":
    tests = [
        test_warning_sign_creation,
        test_stall_event_lead_time,
        test_stall_event_warning_types,
        test_detect_gaps,
        test_detect_gaps_empty,
        test_rolling_median_basic,
        test_rolling_median_with_outlier,
        test_detect_stalls_basic,
        test_detect_stalls_none,
        test_detect_warning_signs,
        test_format_report_no_stalls,
        test_format_report_with_stalls,
        test_format_report_abrupt_stall,
        test_parse_stroke_timestamps,
        test_parse_stroke_timestamps_missing_file,
        test_analyse_insufficient_data,
        test_analyse_end_to_end,
        test_lead_time_zero_no_warnings,
        test_multiple_stalls,
    ]

    passed = 0
    failed = 0
    print(f"running {len(tests)} tests...\n")

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {test.__name__}: {e}")
            failed += 1

    print(f"\n{passed}/{len(tests)} passed, {failed} failed")
    sys.exit(1 if failed else 0)
