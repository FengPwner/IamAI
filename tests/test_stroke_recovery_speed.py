"""Tests for iamai.stroke_recovery_speed — post-stall cadence recovery analysis.

Visit 811: this module measures how quickly the writer returns to its normal
15-second cadence after a stall event (process death, resource starvation, etc.).

Test areas:
    1. _parse_timestamp       — ISO 8601 parsing
    2. compute_gaps           — inter-stroke interval computation
    3. detect_stalls          — stall gap identification
    4. measure_recovery       — recovery distance measurement
    5. stall_score            — exponential decay scoring
    6. aggregate_score        — geometric mean aggregation
    7. recovery_label         — band classification
    8. recovery_report        — full report structure
    9. recovery_summary       — human-readable format
   10. _cli                   — exit codes, --json flag
   11. edge cases             — empty input, single stroke, no stalls, all stalls
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_recovery_speed import (
    _cli,
    _load_strokes_with_timestamps,
    _parse_timestamp,
    _TARGET_CADENCE,
    _TOLERANCE,
    _STALL_MULTIPLIER,
    _WINDOW_SIZE,
    _MAX_LOOKAHEAD,
    _DECAY_CONSTANT,
    aggregate_score,
    compute_gaps,
    detect_stalls,
    measure_recovery,
    recovery_label,
    recovery_report,
    recovery_summary,
    stall_score,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _stroke_at(at: str, seq: int = 0, kind: str = "thought", text: str = "hello") -> dict:
    return {"seq": seq, "at": at, "kind": kind, "text": text}


def _write_strokes(tmp_path: Path, strokes: list) -> Path:
    p = tmp_path / "strokes.jsonl"
    lines = [json.dumps(s) for s in strokes]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _ts_series(start: datetime, intervals: list) -> list:
    """Generate strokes from a start time and a list of inter-stroke intervals (seconds)."""
    strokes = [_stroke_at(_iso(start), seq=0)]
    t = start
    for i, gap in enumerate(intervals):
        t = t + timedelta(seconds=gap)
        strokes.append(_stroke_at(_iso(t), seq=i + 1))
    return strokes


_BASE = datetime(2026, 11, 23, 0, 0, 0, tzinfo=timezone.utc)


# -----------------------------------------------------------------------
# 1. _parse_timestamp
# -----------------------------------------------------------------------


class TestParseTimestamp:
    def test_standard_iso(self):
        dt = _parse_timestamp("2026-11-23T10:00:00+00:00")
        assert dt.year == 2026
        assert dt.month == 11
        assert dt.day == 23

    def test_z_suffix(self):
        dt = _parse_timestamp("2026-11-23T10:00:00Z")
        assert dt.tzinfo is not None

    def test_whitespace_stripped(self):
        dt = _parse_timestamp("  2026-11-23T10:00:00+08:00  ")
        assert dt.hour == 10

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _parse_timestamp("not-a-date")

    def test_microseconds(self):
        dt = _parse_timestamp("2026-11-23T10:00:00.123456+00:00")
        assert dt.microsecond == 123456


# -----------------------------------------------------------------------
# 2. compute_gaps
# -----------------------------------------------------------------------


class TestComputeGaps:
    def test_basic_gaps(self):
        strokes = _ts_series(_BASE, [15.0, 20.0, 10.0])
        gaps = compute_gaps(strokes)
        assert len(gaps) == 3
        assert gaps[0] == pytest.approx(15.0, abs=0.01)
        assert gaps[1] == pytest.approx(20.0, abs=0.01)
        assert gaps[2] == pytest.approx(10.0, abs=0.01)

    def test_single_stroke(self):
        strokes = [_stroke_at(_iso(_BASE))]
        gaps = compute_gaps(strokes)
        assert gaps == []

    def test_empty(self):
        assert compute_gaps([]) == []

    def test_negative_clamped_to_zero(self):
        # Two strokes at the same time
        strokes = [_stroke_at(_iso(_BASE)), _stroke_at(_iso(_BASE))]
        gaps = compute_gaps(strokes)
        assert gaps[0] == 0.0

    def test_large_gap(self):
        strokes = _ts_series(_BASE, [3600.0])
        gaps = compute_gaps(strokes)
        assert gaps[0] == pytest.approx(3600.0, abs=0.01)


# -----------------------------------------------------------------------
# 3. detect_stalls
# -----------------------------------------------------------------------


class TestDetectStalls:
    def test_no_stalls(self):
        gaps = [15.0, 14.5, 16.0, 15.2, 14.8]
        stalls = detect_stalls(gaps)
        assert stalls == []

    def test_single_stall(self):
        # threshold = 3.0 * 15.0 = 45.0
        gaps = [15.0, 15.0, 120.0, 15.0, 15.0]
        stalls = detect_stalls(gaps)
        assert stalls == [2]

    def test_multiple_stalls(self):
        gaps = [15.0, 60.0, 15.0, 90.0, 15.0]
        stalls = detect_stalls(gaps)
        assert stalls == [1, 3]

    def test_boundary_not_stall(self):
        # Exactly at threshold (45.0) — not a stall (need >)
        gaps = [15.0, 45.0, 15.0]
        stalls = detect_stalls(gaps)
        assert stalls == []

    def test_just_over_threshold(self):
        gaps = [15.0, 45.1, 15.0]
        stalls = detect_stalls(gaps)
        assert stalls == [1]

    def test_custom_target_cadence(self):
        # With target=5, threshold=15
        gaps = [5.0, 16.0, 5.0]
        stalls = detect_stalls(gaps, target_cadence=5.0, stall_multiplier=3.0)
        assert stalls == [1]

    def test_empty_gaps(self):
        assert detect_stalls([]) == []


# -----------------------------------------------------------------------
# 4. measure_recovery
# -----------------------------------------------------------------------


class TestMeasureRecovery:
    def test_instant_recovery(self):
        # Stall at index 2, then 4 consecutive normal gaps
        gaps = [15.0, 15.0, 120.0, 15.0, 15.0, 15.0, 15.0, 15.0]
        result = measure_recovery(gaps, stall_index=2)
        assert result["resolved"] is True
        assert result["recovery_strokes"] == _WINDOW_SIZE
        assert result["stall_gap"] == pytest.approx(120.0, abs=0.01)

    def test_delayed_recovery(self):
        # Stall, then some erratic intervals, then normal
        gaps = [15.0, 120.0, 2.0, 100.0, 15.0, 15.0, 15.0, 15.0, 15.0]
        result = measure_recovery(gaps, stall_index=1)
        assert result["resolved"] is True
        # After the erratic bit (indices 2,3), recovery starts at index 4
        # Need 4 consecutive normal: indices 4,5,6,7 → j=7
        # recovery_strokes = j - stall_index = 7 - 1 = 6
        assert result["recovery_strokes"] == 6

    def test_unresolved(self):
        # Stall followed by all erratic intervals
        gaps = [15.0, 120.0] + [100.0] * 60
        result = measure_recovery(gaps, stall_index=1, max_lookahead=50)
        assert result["resolved"] is False
        assert result["recovery_strokes"] == -1
        assert result["recovery_seconds"] == -1.0

    def test_stall_at_end_of_data(self):
        # Stall is the last gap — no data after
        gaps = [15.0, 15.0, 120.0]
        result = measure_recovery(gaps, stall_index=2)
        assert result["resolved"] is False

    def test_recovery_seconds_correct(self):
        # Stall at index 1, then 4 normal gaps of 15s each
        gaps = [15.0, 120.0, 15.0, 15.0, 15.0, 15.0]
        result = measure_recovery(gaps, stall_index=1)
        assert result["resolved"] is True
        assert result["recovery_seconds"] == pytest.approx(60.0, abs=0.01)

    def test_custom_window_size(self):
        gaps = [15.0, 120.0, 15.0, 15.0, 15.0]
        result = measure_recovery(gaps, stall_index=1, window_size=3)
        assert result["resolved"] is True
        assert result["recovery_strokes"] == 3

    def test_custom_tolerance(self):
        # Gaps of 20.0 are outside default tolerance (15±5 = [10,20])
        # Actually 20.0 is right at boundary — should be included
        gaps = [15.0, 120.0, 20.0, 20.0, 20.0, 20.0]
        result = measure_recovery(gaps, stall_index=1)
        assert result["resolved"] is True

    def test_tolerance_just_outside(self):
        # Gaps of 20.1 are outside tolerance [10, 20]
        gaps = [15.0, 120.0, 20.1, 20.1, 20.1, 20.1, 15.0, 15.0, 15.0, 15.0]
        result = measure_recovery(gaps, stall_index=1)
        assert result["resolved"] is True
        # Indices 2-5 (20.1) are outside tolerance, indices 6-9 (15.0) are good
        # j=9, recovery_strokes = 9 - 1 = 8
        assert result["recovery_strokes"] == 8


# -----------------------------------------------------------------------
# 5. stall_score
# -----------------------------------------------------------------------


class TestStallScore:
    def test_instant_recovery(self):
        # 0 strokes → exp(0) = 1.0
        assert stall_score(0) == pytest.approx(1.0)

    def test_10_strokes(self):
        # 10 strokes → exp(-1) ≈ 0.368
        expected = math.exp(-10.0 / _DECAY_CONSTANT)
        assert stall_score(10) == pytest.approx(expected)

    def test_unresolved_uses_max_lookahead(self):
        expected = math.exp(-_MAX_LOOKAHEAD / _DECAY_CONSTANT)
        assert stall_score(-1) == pytest.approx(expected)

    def test_monotonically_decreasing(self):
        scores = [stall_score(n) for n in range(0, 50)]
        for i in range(1, len(scores)):
            assert scores[i] <= scores[i - 1]

    def test_custom_decay_constant(self):
        # With decay=5, 5 strokes → exp(-1)
        expected = math.exp(-1.0)
        assert stall_score(5, decay_constant=5.0) == pytest.approx(expected)

    def test_large_recovery_small_score(self):
        s = stall_score(100, decay_constant=10.0)
        assert s < 0.001


# -----------------------------------------------------------------------
# 6. aggregate_score
# -----------------------------------------------------------------------


class TestAggregateScore:
    def test_empty_returns_one(self):
        assert aggregate_score([]) == 1.0

    def test_single(self):
        assert aggregate_score([0.5]) == pytest.approx(0.5)

    def test_geometric_mean(self):
        scores = [0.25, 1.0]
        # Geometric mean of 0.25 and 1.0 = sqrt(0.25) = 0.5
        result = aggregate_score(scores)
        assert result == pytest.approx(0.5)

    def test_all_ones(self):
        assert aggregate_score([1.0, 1.0, 1.0]) == pytest.approx(1.0)

    def test_penalises_outlier(self):
        # Geometric mean is lower than arithmetic mean for dispersed values
        scores = [1.0, 1.0, 0.01]
        result = aggregate_score(scores)
        arithmetic = sum(scores) / len(scores)
        assert result < arithmetic

    def test_zero_clamped(self):
        # Zero score shouldn't cause log(0)
        result = aggregate_score([0.0, 1.0])
        assert result >= 0.0


# -----------------------------------------------------------------------
# 7. recovery_label
# -----------------------------------------------------------------------


class TestRecoveryLabel:
    def test_instant(self):
        assert recovery_label(0.9) == "instant"
        assert recovery_label(0.8) == "instant"

    def test_fast(self):
        assert recovery_label(0.79) == "fast"
        assert recovery_label(0.5) == "fast"

    def test_slow(self):
        assert recovery_label(0.49) == "slow"
        assert recovery_label(0.3) == "slow"

    def test_stuck(self):
        assert recovery_label(0.29) == "stuck"
        assert recovery_label(0.0) == "stuck"


# -----------------------------------------------------------------------
# 8. recovery_report
# -----------------------------------------------------------------------


class TestRecoveryReport:
    def test_no_stalls(self, tmp_path):
        strokes = _ts_series(_BASE, [15.0] * 20)
        path = _write_strokes(tmp_path, strokes)
        report = recovery_report(n_strokes=21, path=path)
        assert report["stall_count"] == 0
        assert report["recovery_score"] == 1.0
        assert report["label"] == "instant"
        assert report["stalls"] == []

    def test_single_stall_with_recovery(self, tmp_path):
        intervals = [15.0] * 5 + [120.0] + [15.0] * 10
        strokes = _ts_series(_BASE, intervals)
        path = _write_strokes(tmp_path, strokes)
        report = recovery_report(n_strokes=16, path=path)
        assert report["stall_count"] == 1
        assert report["stalls"][0]["resolved"] is True
        assert report["recovery_score"] > 0.0

    def test_unresolved_stall(self, tmp_path):
        # 300s is a stall (>45); 30s gaps after are outside [10,20] tolerance
        # so recovery never achieves 4 consecutive good intervals
        intervals = [15.0] * 3 + [300.0] + [30.0] * 60
        strokes = _ts_series(_BASE, intervals)
        path = _write_strokes(tmp_path, strokes)
        report = recovery_report(n_strokes=64, path=path)
        assert report["stall_count"] == 1
        assert report["stalls"][0]["resolved"] is False
        assert report["recovery_score"] < 0.01

    def test_empty_file(self, tmp_path):
        path = _write_strokes(tmp_path, [])
        report = recovery_report(n_strokes=10, path=path)
        assert report["stall_count"] == 0
        assert report["recovery_score"] == 1.0

    def test_insufficient_data(self, tmp_path):
        strokes = [_stroke_at(_iso(_BASE))]
        path = _write_strokes(tmp_path, strokes)
        report = recovery_report(n_strokes=1, path=path)
        assert report["n_intervals"] == 0
        assert report["recovery_score"] == 1.0

    def test_report_keys(self, tmp_path):
        strokes = _ts_series(_BASE, [15.0] * 10)
        path = _write_strokes(tmp_path, strokes)
        report = recovery_report(n_strokes=11, path=path)
        expected_keys = {
            "n_strokes_analysed", "n_intervals", "stall_count", "stalls",
            "mean_recovery_strokes", "mean_recovery_seconds",
            "max_recovery_strokes", "max_recovery_seconds",
            "recovery_score", "label",
        }
        assert set(report.keys()) == expected_keys

    def test_multiple_stalls(self, tmp_path):
        intervals = [15.0] * 5 + [120.0] + [15.0] * 10 + [200.0] + [15.0] * 10
        strokes = _ts_series(_BASE, intervals)
        path = _write_strokes(tmp_path, strokes)
        report = recovery_report(n_strokes=27, path=path)
        assert report["stall_count"] == 2
        assert len(report["stalls"]) == 2

    def test_n_strokes_analysed_correct(self, tmp_path):
        strokes = _ts_series(_BASE, [15.0] * 30)
        path = _write_strokes(tmp_path, strokes)
        report = recovery_report(n_strokes=31, path=path)
        assert report["n_strokes_analysed"] == 31

    def test_malformed_lines_skipped(self, tmp_path):
        good = _ts_series(_BASE, [15.0] * 10)  # 11 good strokes
        path = tmp_path / "strokes.jsonl"
        lines = [json.dumps(s) for s in good]
        lines.insert(3, "not-json{{{")
        lines.insert(7, '{"no_at_field": true}')  # has no 'at' field → skipped
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = recovery_report(n_strokes=20, path=path)
        # 11 good strokes loaded (2 bad lines skipped: 1 invalid JSON, 1 missing 'at')
        assert report["n_strokes_analysed"] == 11


# -----------------------------------------------------------------------
# 9. recovery_summary
# -----------------------------------------------------------------------


class TestRecoverySummary:
    def test_no_stalls_text(self, tmp_path):
        strokes = _ts_series(_BASE, [15.0] * 20)
        path = _write_strokes(tmp_path, strokes)
        s = recovery_summary(n_strokes=21, path=path)
        assert "no stalls" in s.lower()

    def test_with_stall_text(self, tmp_path):
        intervals = [15.0] * 5 + [120.0] + [15.0] * 10
        strokes = _ts_series(_BASE, intervals)
        path = _write_strokes(tmp_path, strokes)
        s = recovery_summary(n_strokes=16, path=path)
        assert "stall" in s.lower()
        assert "recover" in s.lower()

    def test_single_stall_singular(self, tmp_path):
        intervals = [15.0] * 5 + [120.0] + [15.0] * 10
        strokes = _ts_series(_BASE, intervals)
        path = _write_strokes(tmp_path, strokes)
        s = recovery_summary(n_strokes=16, path=path)
        assert "1 stall" in s
        assert "stalls" not in s.split("1 stall")[1][:2]

    def test_multiple_stalls_plural(self, tmp_path):
        intervals = [15.0] * 5 + [120.0] + [15.0] * 10 + [200.0] + [15.0] * 10
        strokes = _ts_series(_BASE, intervals)
        path = _write_strokes(tmp_path, strokes)
        s = recovery_summary(n_strokes=27, path=path)
        assert "2 stalls" in s


# -----------------------------------------------------------------------
# 10. _cli
# -----------------------------------------------------------------------


class TestCli:
    def test_json_output(self, tmp_path, capsys):
        strokes = _ts_series(_BASE, [15.0] * 10)
        path = _write_strokes(tmp_path, strokes)
        rc = _cli(["--n", "11", "--path", str(path), "--json"])
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "recovery_score" in data

    def test_text_output(self, tmp_path, capsys):
        strokes = _ts_series(_BASE, [15.0] * 10)
        path = _write_strokes(tmp_path, strokes)
        rc = _cli(["--n", "11", "--path", str(path)])
        assert rc == 0
        captured = capsys.readouterr()
        assert "recovery" in captured.out.lower()

    def test_exit_code_good(self, tmp_path):
        strokes = _ts_series(_BASE, [15.0] * 20)
        path = _write_strokes(tmp_path, strokes)
        rc = _cli(["--n", "21", "--path", str(path)])
        assert rc == 0  # instant → good

    def test_exit_code_bad(self, tmp_path):
        # Create data with an unresolved stall (30s gaps are outside [10,20] tolerance)
        intervals = [15.0] * 3 + [300.0] + [30.0] * 60
        strokes = _ts_series(_BASE, intervals)
        path = _write_strokes(tmp_path, strokes)
        rc = _cli(["--n", "64", "--path", str(path)])
        assert rc == 1  # stuck → bad

    def test_custom_target_cadence(self, tmp_path, capsys):
        strokes = _ts_series(_BASE, [5.0] * 20)
        path = _write_strokes(tmp_path, strokes)
        rc = _cli(["--n", "21", "--path", str(path), "--target-cadence", "5", "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["stall_count"] == 0


# -----------------------------------------------------------------------
# 11. Edge cases
# -----------------------------------------------------------------------


class TestEdgeCases:
    def test_all_stalls(self, tmp_path):
        # Every interval is a stall
        intervals = [120.0] * 20
        strokes = _ts_series(_BASE, intervals)
        path = _write_strokes(tmp_path, strokes)
        report = recovery_report(n_strokes=21, path=path)
        assert report["stall_count"] == 20
        # All unresolved → very low score
        assert report["recovery_score"] < 0.01

    def test_alternating_stall_normal(self, tmp_path):
        intervals = ([15.0] * 4 + [120.0]) * 5
        strokes = _ts_series(_BASE, intervals)
        path = _write_strokes(tmp_path, strokes)
        report = recovery_report(n_strokes=26, path=path)
        assert report["stall_count"] == 5

    def test_stroke_without_at_field(self, tmp_path):
        strokes = _ts_series(_BASE, [15.0] * 10)
        strokes.append({"seq": 99, "text": "no at field"})
        path = _write_strokes(tmp_path, strokes)
        report = recovery_report(n_strokes=20, path=path)
        # Should only count strokes with valid 'at'
        assert report["n_strokes_analysed"] == 11

    def test_z_suffix_timestamps(self, tmp_path):
        strokes = [
            _stroke_at("2026-11-23T00:00:00Z", seq=0),
            _stroke_at("2026-11-23T00:00:15Z", seq=1),
            _stroke_at("2026-11-23T00:00:30Z", seq=2),
            _stroke_at("2026-11-23T00:02:30Z", seq=3),  # stall: 120s
            _stroke_at("2026-11-23T00:02:45Z", seq=4),
            _stroke_at("2026-11-23T00:03:00Z", seq=5),
            _stroke_at("2026-11-23T00:03:15Z", seq=6),
            _stroke_at("2026-11-23T00:03:30Z", seq=7),
        ]
        path = _write_strokes(tmp_path, strokes)
        report = recovery_report(n_strokes=8, path=path)
        assert report["stall_count"] == 1
        assert report["stalls"][0]["resolved"] is True

    def test_two_strokes_one_gap(self, tmp_path):
        strokes = _ts_series(_BASE, [15.0])
        path = _write_strokes(tmp_path, strokes)
        report = recovery_report(n_strokes=2, path=path)
        assert report["n_intervals"] == 1
        assert report["stall_count"] == 0

    def test_recovery_strokes_detail_keys(self, tmp_path):
        intervals = [15.0] * 5 + [120.0] + [15.0] * 10
        strokes = _ts_series(_BASE, intervals)
        path = _write_strokes(tmp_path, strokes)
        report = recovery_report(n_strokes=16, path=path)
        stall = report["stalls"][0]
        assert "stall_gap" in stall
        assert "recovery_strokes" in stall
        assert "recovery_seconds" in stall
        assert "resolved" in stall
        assert "score" in stall

    def test_mean_recovery_only_resolved(self, tmp_path):
        # One stall resolves (120s gap, then normal cadence),
        # one doesn't (300s gap, then 30s gaps which are outside [10,20] tolerance)
        intervals = [15.0] * 5 + [120.0] + [15.0] * 10 + [300.0] + [30.0] * 60
        strokes = _ts_series(_BASE, intervals)
        path = _write_strokes(tmp_path, strokes)
        report = recovery_report(n_strokes=76, path=path)
        assert report["stall_count"] == 2
        # mean_recovery_strokes should only count the resolved one
        resolved = [s for s in report["stalls"] if s["resolved"]]
        if resolved:
            expected_mean = sum(s["recovery_strokes"] for s in resolved) / len(resolved)
            assert report["mean_recovery_strokes"] == pytest.approx(expected_mean, abs=0.1)


# -----------------------------------------------------------------------
# Integration: _load_strokes_with_timestamps
# -----------------------------------------------------------------------


class TestLoadStrokes:
    def test_loads_from_file(self, tmp_path):
        strokes = _ts_series(_BASE, [15.0] * 5)
        path = _write_strokes(tmp_path, strokes)
        loaded = _load_strokes_with_timestamps(n=10, path=path)
        assert len(loaded) == 6

    def test_tail_only(self, tmp_path):
        strokes = _ts_series(_BASE, [15.0] * 100)
        path = _write_strokes(tmp_path, strokes)
        loaded = _load_strokes_with_timestamps(n=10, path=path)
        assert len(loaded) == 10

    def test_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.jsonl"
        loaded = _load_strokes_with_timestamps(n=10, path=path)
        assert loaded == []

    def test_skips_bad_json(self, tmp_path):
        path = tmp_path / "strokes.jsonl"
        good = json.dumps(_stroke_at(_iso(_BASE), seq=0))
        bad = "not json at all"
        path.write_text(f"{good}\n{bad}\n", encoding="utf-8")
        loaded = _load_strokes_with_timestamps(n=10, path=path)
        assert len(loaded) == 1
