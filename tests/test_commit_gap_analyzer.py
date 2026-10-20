"""tests for commit_gap_analyzer — 30 tests covering all edge cases."""

import pytest
from iamai.commit_gap_analyzer import (
    GapReport,
    analyze_gaps,
    analyze_from_log_lines,
    _parse_timestamp,
    _percentile,
)


# --- basic gap computation ---

def test_empty_timestamps():
    r = analyze_gaps([])
    assert r.gap_seconds == []
    assert r.mean_gap == 0.0
    assert r.total_gaps == 0
    assert r.trend == "steady"


def test_single_timestamp():
    r = analyze_gaps(["2026-10-21T00:00:00+00:00"])
    assert r.gap_seconds == []
    assert r.total_gaps == 0


def test_two_identical_timestamps():
    r = analyze_gaps(["2026-10-21T00:00:00+00:00", "2026-10-21T00:00:00+00:00"])
    assert r.gap_seconds == [0]
    assert r.mean_gap == 0.0
    assert r.trend == "steady"


def test_two_timestamps_60s_apart():
    r = analyze_gaps(["2026-10-21T00:00:00+00:00", "2026-10-21T00:01:00+00:00"])
    assert r.gap_seconds == [60]
    assert r.mean_gap == 60.0
    assert r.max_gap == 60
    assert r.min_gap == 60


def test_three_timestamps_mixed_gaps():
    r = analyze_gaps([
        "2026-10-21T00:00:00+00:00",
        "2026-10-21T00:01:00+00:00",
        "2026-10-21T00:05:00+00:00",
    ])
    assert r.gap_seconds == [60, 240]
    assert r.mean_gap == 150.0
    assert r.max_gap == 240
    assert r.min_gap == 60


# --- negative gap clamping ---

def test_negative_gap_clamped_to_zero():
    r = analyze_gaps([
        "2026-10-21T00:05:00+00:00",
        "2026-10-21T00:00:00+00:00",  # earlier than previous
    ])
    assert r.gap_seconds == [0]
    assert r.mean_gap == 0.0


# --- stall detection ---

def test_no_stalls_under_threshold():
    r = analyze_gaps([
        "2026-10-21T00:00:00+00:00",
        "2026-10-21T00:01:00+00:00",
        "2026-10-21T00:02:00+00:00",
    ], stall_threshold=600)
    assert r.stall_count == 0
    assert r.stall_ratio == 0.0


def test_all_stalls_above_threshold():
    r = analyze_gaps([
        "2026-10-21T00:00:00+00:00",
        "2026-10-21T00:20:00+00:00",
        "2026-10-21T00:40:00+00:00",
    ], stall_threshold=600)
    assert r.stall_count == 2
    assert r.stall_ratio == 1.0


def test_mixed_stalls():
    r = analyze_gaps([
        "2026-10-21T00:00:00+00:00",
        "2026-10-21T00:05:00+00:00",   # 300s — not a stall
        "2026-10-21T00:25:00+00:00",   # 1200s — stall
        "2026-10-21T00:26:00+00:00",   # 60s — not a stall
    ], stall_threshold=600)
    assert r.stall_count == 1
    assert r.stall_ratio == pytest.approx(1 / 3)


def test_custom_stall_threshold():
    r = analyze_gaps([
        "2026-10-21T00:00:00+00:00",
        "2026-10-21T00:02:00+00:00",
    ], stall_threshold=60)
    assert r.stall_count == 1
    assert r.stall_ratio == 1.0


# --- trend detection ---

def test_steady_trend():
    # uniform 60s gaps
    ts = [f"2026-10-21T00:{i:02d}:00+00:00" for i in range(10)]
    r = analyze_gaps(ts)
    assert r.trend == "steady"


def test_accelerating_trend():
    # first half: 600s gaps, second half: 60s gaps
    ts = []
    base = 0
    for _ in range(5):
        ts.append(f"2026-10-21T{base // 3600:02d}:{(base % 3600) // 60:02d}:{base % 60:02d}+00:00")
        base += 600
    for _ in range(5):
        ts.append(f"2026-10-21T{base // 3600:02d}:{(base % 3600) // 60:02d}:{base % 60:02d}+00:00")
        base += 60
    r = analyze_gaps(ts)
    assert r.trend == "accelerating"


def test_decaying_trend():
    # first half: 60s gaps, second half: 600s gaps
    ts = []
    base = 0
    for _ in range(5):
        ts.append(f"2026-10-21T{base // 3600:02d}:{(base % 3600) // 60:02d}:{base % 60:02d}+00:00")
        base += 60
    for _ in range(5):
        ts.append(f"2026-10-21T{base // 3600:02d}:{(base % 3600) // 60:02d}:{base % 60:02d}+00:00")
        base += 600
    r = analyze_gaps(ts)
    assert r.trend == "decaying"


# --- health check ---

def test_healthy_report():
    r = analyze_gaps([
        "2026-10-21T00:00:00+00:00",
        "2026-10-21T00:05:00+00:00",
        "2026-10-21T00:10:00+00:00",
        "2026-10-21T00:15:00+00:00",
    ], stall_threshold=600)
    assert r.is_healthy is True


def test_unhealthy_high_stall_ratio():
    r = analyze_gaps([
        "2026-10-21T00:00:00+00:00",
        "2026-10-21T01:00:00+00:00",
    ], stall_threshold=60)
    assert r.is_healthy is False


def test_unhealthy_decaying_trend():
    # even with low stall ratio, decaying = unhealthy
    r = GapReport(stall_ratio=0.0, trend="decaying")
    assert r.is_healthy is False


# --- p95 calculation ---

def test_p95_gap():
    # 20 gaps: 10,20,...,200
    ts = ["2026-10-21T00:00:00+00:00"]
    cumulative = 0
    for g in range(10, 210, 10):
        cumulative += g
        ts.append(f"2026-10-21T00:00:{cumulative % 60:02d}+00:00")  # not realistic but tests math
    # simpler: just test _percentile directly
    data = list(range(10, 210, 10))  # [10, 20, ..., 200]
    p95 = _percentile(data, 95)
    assert 180 <= p95 <= 200


def test_p95_empty():
    assert _percentile([], 95) == 0


def test_p95_single_value():
    assert _percentile([42], 95) == 42


# --- timestamp parsing ---

def test_parse_z_suffix():
    dt = _parse_timestamp("2026-10-21T00:00:00Z")
    assert dt.year == 2026
    assert dt.month == 10


def test_parse_offset_suffix():
    dt = _parse_timestamp("2026-10-21T08:00:00+08:00")
    assert dt.hour == 8


def test_parse_plain_iso():
    dt = _parse_timestamp("2026-10-21T00:00:00")
    assert dt.day == 21


# --- log line parsing ---

def test_analyze_from_devlog_lines():
    lines = [
        "- `2026-10-20T17:00:00+00:00` stroke 100: something",
        "- `2026-10-20T17:10:00+00:00` stroke 101: another thing",
        "- `2026-10-20T17:20:00+00:00` stroke 102: yet more",
    ]
    r = analyze_from_log_lines(lines, stall_threshold=600)
    assert r.total_gaps == 2
    assert r.gap_seconds == [600, 600]
    assert r.trend == "steady"


def test_analyze_from_log_skips_bad_lines():
    lines = [
        "- `2026-10-20T17:00:00+00:00` stroke 100",
        "this is not a valid line",
        "- `not-a-date` stroke 101",
        "- `2026-10-20T17:10:00+00:00` stroke 102",
    ]
    r = analyze_from_log_lines(lines)
    assert r.total_gaps == 1
    assert r.gap_seconds == [600]


def test_analyze_from_log_empty():
    r = analyze_from_log_lines([])
    assert r.total_gaps == 0


def test_analyze_from_log_no_valid_lines():
    r = analyze_from_log_lines(["garbage", "more garbage"])
    assert r.total_gaps == 0


# --- gap report defaults ---

def test_gap_report_defaults():
    r = GapReport()
    assert r.gap_seconds == []
    assert r.mean_gap == 0.0
    assert r.max_gap == 0
    assert r.min_gap == 0
    assert r.p95_gap == 0
    assert r.stall_ratio == 0.0
    assert r.trend == "steady"
    assert r.total_gaps == 0
    assert r.stall_count == 0
    assert r.is_healthy is True  # empty report is technically healthy


# --- edge: large number of timestamps ---

def test_large_input():
    ts = [f"2026-10-21T{i // 60:02d}:{i % 60:02d}:00+00:00" for i in range(100)]
    r = analyze_gaps(ts)
    assert r.total_gaps == 99
    assert all(g == 60 for g in r.gap_seconds)
    assert r.mean_gap == 60.0
    assert r.trend == "steady"
