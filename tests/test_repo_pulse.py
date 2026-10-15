"""Tests for iamai.repo_pulse — single-shot health reading."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.repo_pulse import (
    DEFAULT_STALL_THRESHOLD,
    DEGRADED_MULTIPLIER,
    WRITER_CADENCE_SECONDS,
    _count_recent_strokes,
    _lag_seconds,
    _latest_stroke_ts,
    _parse_ts,
    _tail_strokes,
    pulse_one_liner,
    take_pulse,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _stroke(seq: int, at: str, kind: str = "thought") -> dict:
    return {"seq": seq, "at": at, "kind": kind}


def _write_strokes(tmp: Path, strokes: list[dict], filename: str = "strokes.jsonl") -> Path:
    p = tmp / filename
    p.write_text("\n".join(json.dumps(s) for s in strokes) + "\n", encoding="utf-8")
    return p


def _utc(year: int, month: int, day: int, hour: int = 12, minute: int = 0, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------

class TestParseTimestamp:
    def test_utc_z_suffix(self):
        dt = _parse_ts("2026-10-15T12:00:00Z")
        assert dt.tzinfo is not None
        assert dt.hour == 12

    def test_offset_suffix(self):
        dt = _parse_ts("2026-10-15T12:00:00+08:00")
        assert dt.tzinfo is not None

    def test_naive_gets_utc(self):
        dt = _parse_ts("2026-10-15T12:00:00")
        assert dt.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# _tail_strokes
# ---------------------------------------------------------------------------

class TestTailStrokes:
    def test_reads_all_from_small_file(self, tmp_path):
        strokes = [_stroke(i, "2026-10-15T12:00:00Z") for i in range(1, 11)]
        p = _write_strokes(tmp_path, strokes)
        result = _tail_strokes(p)
        assert len(result) == 10

    def test_limits_to_max_lines(self, tmp_path):
        strokes = [_stroke(i, "2026-10-15T12:00:00Z") for i in range(1, 101)]
        p = _write_strokes(tmp_path, strokes)
        result = _tail_strokes(p, max_lines=20)
        assert len(result) == 20
        # Should be the LAST 20 strokes
        assert result[0]["seq"] == 81
        assert result[-1]["seq"] == 100

    def test_missing_file_returns_empty(self, tmp_path):
        result = _tail_strokes(tmp_path / "nonexistent.jsonl")
        assert result == []

    def test_skips_blank_lines(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        content = json.dumps(_stroke(1, "2026-10-15T12:00:00Z")) + "\n\n" + \
                  json.dumps(_stroke(2, "2026-10-15T12:01:00Z")) + "\n"
        p.write_text(content, encoding="utf-8")
        result = _tail_strokes(p)
        assert len(result) == 2

    def test_skips_corrupt_lines(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        content = json.dumps(_stroke(1, "2026-10-15T12:00:00Z")) + "\n" + \
                  "this is not json\n" + \
                  json.dumps(_stroke(2, "2026-10-15T12:01:00Z")) + "\n"
        p.write_text(content, encoding="utf-8")
        result = _tail_strokes(p)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _count_recent_strokes
# ---------------------------------------------------------------------------

class TestCountRecentStrokes:
    def test_counts_within_window(self):
        now = _utc(2026, 10, 15, 12, 0, 0)
        strokes = [
            _stroke(1, "2026-10-15T11:50:00Z"),   # 600s ago
            _stroke(2, "2026-10-15T11:55:00Z"),   # 300s ago
            _stroke(3, "2026-10-15T11:59:00Z"),   # 60s ago
        ]
        assert _count_recent_strokes(strokes, 3600, reference=now) == 3
        assert _count_recent_strokes(strokes, 600, reference=now) == 3  # 600s ago is exactly on boundary (inclusive)
        assert _count_recent_strokes(strokes, 599, reference=now) == 2  # 300s + 60s
        assert _count_recent_strokes(strokes, 120, reference=now) == 1  # only 60s

    def test_excludes_old_strokes(self):
        now = _utc(2026, 10, 15, 12, 0, 0)
        strokes = [
            _stroke(1, "2026-10-14T12:00:00Z"),   # 24h ago
        ]
        assert _count_recent_strokes(strokes, 3600, reference=now) == 0

    def test_empty_strokes(self):
        now = _utc(2026, 10, 15, 12, 0, 0)
        assert _count_recent_strokes([], 3600, reference=now) == 0

    def test_handles_missing_timestamps(self):
        now = _utc(2026, 10, 15, 12, 0, 0)
        strokes = [{"seq": 1}, {"seq": 2, "at": ""}]
        assert _count_recent_strokes(strokes, 3600, reference=now) == 0


# ---------------------------------------------------------------------------
# _latest_stroke_ts / _lag_seconds
# ---------------------------------------------------------------------------

class TestLatestAndLag:
    def test_latest_finds_max(self):
        strokes = [
            _stroke(1, "2026-10-15T10:00:00Z"),
            _stroke(2, "2026-10-15T12:00:00Z"),
            _stroke(3, "2026-10-15T11:00:00Z"),
        ]
        latest = _latest_stroke_ts(strokes)
        assert latest is not None
        assert latest.hour == 12

    def test_latest_returns_none_for_empty(self):
        assert _latest_stroke_ts([]) is None

    def test_lag_computes_correctly(self):
        now = _utc(2026, 10, 15, 12, 0, 30)
        strokes = [_stroke(1, "2026-10-15T12:00:00Z")]
        lag = _lag_seconds(strokes, reference=now)
        assert lag == pytest.approx(30.0, abs=0.1)

    def test_lag_none_for_empty(self):
        now = _utc(2026, 10, 15, 12, 0, 0)
        assert _lag_seconds([], reference=now) is None

    def test_lag_never_negative(self):
        # Stroke timestamp is in the "future" relative to reference.
        now = _utc(2026, 10, 15, 12, 0, 0)
        strokes = [_stroke(1, "2026-10-15T13:00:00Z")]
        lag = _lag_seconds(strokes, reference=now)
        assert lag == 0.0


# ---------------------------------------------------------------------------
# take_pulse — verdict logic
# ---------------------------------------------------------------------------

class TestTakePulseVerdict:
    def test_healthy_when_recent(self, tmp_path):
        now = _utc(2026, 10, 15, 12, 0, 10)
        strokes = [_stroke(i, f"2026-10-15T12:00:{i:02d}Z") for i in range(10)]
        p = _write_strokes(tmp_path, strokes)
        pulse = take_pulse(strokes_path=p, reference=now, include_git=False)
        assert pulse["verdict"] == "healthy"

    def test_stalled_when_no_strokes(self, tmp_path):
        now = _utc(2026, 10, 15, 12, 0, 0)
        p = _write_strokes(tmp_path, [])
        pulse = take_pulse(strokes_path=p, reference=now, include_git=False)
        assert pulse["verdict"] == "stalled"
        assert pulse["lag_seconds"] is None

    def test_stalled_when_old(self, tmp_path):
        now = _utc(2026, 10, 15, 12, 0, 0)
        # Last stroke 2 hours ago — well past the 1800s stall threshold.
        strokes = [_stroke(1, "2026-10-15T10:00:00Z")]
        p = _write_strokes(tmp_path, strokes)
        pulse = take_pulse(strokes_path=p, reference=now, include_git=False)
        assert pulse["verdict"] == "stalled"
        assert pulse["lag_seconds"] == pytest.approx(7200.0, abs=1)

    def test_degraded_when_slipping(self, tmp_path):
        now = _utc(2026, 10, 15, 12, 0, 0)
        # Lag of 90 seconds: past DEGRADED_MULTIPLIER (4×15=60s) but under stall threshold.
        strokes = [_stroke(1, "2026-10-15T11:58:30Z")]
        p = _write_strokes(tmp_path, strokes)
        pulse = take_pulse(strokes_path=p, reference=now, include_git=False)
        assert pulse["verdict"] == "degraded"

    def test_custom_stall_threshold(self, tmp_path):
        now = _utc(2026, 10, 15, 12, 0, 0)
        strokes = [_stroke(1, "2026-10-15T11:50:00Z")]  # 600s ago
        p = _write_strokes(tmp_path, strokes)
        # With default threshold (1800s), this is degraded.
        pulse = take_pulse(strokes_path=p, reference=now, include_git=False)
        assert pulse["verdict"] == "degraded"
        # With a tight threshold (300s), this is stalled.
        pulse2 = take_pulse(strokes_path=p, stall_threshold=300, reference=now, include_git=False)
        assert pulse2["verdict"] == "stalled"

    def test_missing_file_is_stalled(self, tmp_path):
        now = _utc(2026, 10, 15, 12, 0, 0)
        pulse = take_pulse(strokes_path=tmp_path / "nope.jsonl", reference=now, include_git=False)
        assert pulse["verdict"] == "stalled"


# ---------------------------------------------------------------------------
# take_pulse — data fields
# ---------------------------------------------------------------------------

class TestTakePulseFields:
    def test_strokes_1h_and_6h(self, tmp_path):
        now = _utc(2026, 10, 15, 12, 0, 0)
        strokes = (
            [_stroke(i, "2026-10-15T11:30:00Z") for i in range(1, 11)]   # 30min ago → in 1h
            + [_stroke(i, "2026-10-15T07:00:00Z") for i in range(11, 21)]  # 5h ago → in 6h but not 1h
            + [_stroke(i, "2026-10-14T12:00:00Z") for i in range(21, 31)]  # 24h ago → neither
        )
        p = _write_strokes(tmp_path, strokes)
        pulse = take_pulse(strokes_path=p, reference=now, include_git=False)
        assert pulse["strokes_1h"] == 10
        assert pulse["strokes_6h"] == 20

    def test_latest_seq(self, tmp_path):
        now = _utc(2026, 10, 15, 12, 0, 0)
        strokes = [_stroke(100, "2026-10-15T11:59:00Z"), _stroke(2804, "2026-10-15T11:59:30Z")]
        p = _write_strokes(tmp_path, strokes)
        pulse = take_pulse(strokes_path=p, reference=now, include_git=False)
        assert pulse["latest_seq"] == 2804

    def test_include_git_false_zeros_git_fields(self, tmp_path):
        now = _utc(2026, 10, 15, 12, 0, 0)
        strokes = [_stroke(1, "2026-10-15T11:59:00Z")]
        p = _write_strokes(tmp_path, strokes)
        pulse = take_pulse(strokes_path=p, reference=now, include_git=False)
        assert pulse["commits_1h"] == 0
        assert pulse["uncommitted"] == 0

    def test_stall_threshold_echoed(self, tmp_path):
        now = _utc(2026, 10, 15, 12, 0, 0)
        p = _write_strokes(tmp_path, [])
        pulse = take_pulse(strokes_path=p, stall_threshold=999, reference=now, include_git=False)
        assert pulse["stall_threshold"] == 999


# ---------------------------------------------------------------------------
# pulse_one_liner
# ---------------------------------------------------------------------------

class TestPulseOneLiner:
    def test_healthy_format(self):
        pulse = {
            "verdict": "healthy",
            "lag_seconds": 12.3,
            "strokes_1h": 240,
            "strokes_6h": 1200,
            "latest_seq": 2804,
            "commits_1h": 4,
            "uncommitted": 0,
            "stall_threshold": 1800,
        }
        line = pulse_one_liner(pulse)
        assert "healthy" in line
        assert "12s" in line
        assert "240" in line
        assert "2804" in line
        assert "4 commits" in line
        assert "0 dirty" in line

    def test_stalled_no_lag(self):
        pulse = {
            "verdict": "stalled",
            "lag_seconds": None,
            "strokes_1h": 0,
            "strokes_6h": 0,
            "latest_seq": 0,
            "commits_1h": 0,
            "uncommitted": 0,
            "stall_threshold": 1800,
        }
        line = pulse_one_liner(pulse)
        assert "stalled" in line
        assert "n/a" in line

    def test_degraded_format(self):
        pulse = {
            "verdict": "degraded",
            "lag_seconds": 120.0,
            "strokes_1h": 50,
            "strokes_6h": 400,
            "latest_seq": 1500,
            "commits_1h": 1,
            "uncommitted": 3,
            "stall_threshold": 1800,
        }
        line = pulse_one_liner(pulse)
        assert "degraded" in line
        assert "3 dirty" in line


# ---------------------------------------------------------------------------
# integration: constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_degraded_boundary(self):
        # degraded starts at cadence * multiplier
        boundary = WRITER_CADENCE_SECONDS * DEGRADED_MULTIPLIER
        assert boundary == 60.0

    def test_stall_threshold_greater_than_degraded(self):
        assert DEFAULT_STALL_THRESHOLD > WRITER_CADENCE_SECONDS * DEGRADED_MULTIPLIER
