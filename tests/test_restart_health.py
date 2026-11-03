"""Tests for iamai.restart_health — assess restart effectiveness."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.restart_health import (
    RestartReport,
    _load_strokes,
    _parse_ts,
    assess,
    format_report,
    is_healthy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_strokes(tmp_path: Path, timestamps: list[datetime], start_seq: int = 1) -> Path:
    """Write a strokes.jsonl with given timestamps and return the path."""
    p = tmp_path / "strokes.jsonl"
    with open(p, "w", encoding="utf-8") as fh:
        for i, ts in enumerate(timestamps):
            fh.write(json.dumps({"seq": start_seq + i, "ts": ts.isoformat(), "writer": "qwen"}) + "\n")
    return p


def _dt(offset_minutes: float = 0) -> datetime:
    """Return a fixed base datetime plus offset in minutes."""
    base = datetime(2026, 11, 3, 19, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(minutes=offset_minutes)


# ---------------------------------------------------------------------------
# _load_strokes
# ---------------------------------------------------------------------------

class TestLoadStrokes:
    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        assert _load_strokes(p) == []

    def test_missing_file(self, tmp_path):
        p = tmp_path / "nope.jsonl"
        assert _load_strokes(p) == []

    def test_loads_records(self, tmp_path):
        p = _mk_strokes(tmp_path, [_dt(0), _dt(1)])
        strokes = _load_strokes(p)
        assert len(strokes) == 2
        assert strokes[0]["seq"] == 1
        assert strokes[1]["seq"] == 2


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------

class TestParseTs:
    def test_iso_with_tz(self):
        dt = _parse_ts("2026-11-03T19:00:00+00:00")
        assert dt.year == 2026
        assert dt.hour == 19

    def test_iso_with_z(self):
        dt = _parse_ts("2026-11-03T19:00:00Z")
        assert dt.tzinfo is not None
        assert dt.hour == 19

    def test_iso_no_tz(self):
        dt = _parse_ts("2026-11-03T19:00:00")
        # Should still parse without raising
        assert dt.year == 2026


# ---------------------------------------------------------------------------
# assess — healthy restart
# ---------------------------------------------------------------------------

class TestAssessHealthy:
    def test_healthy_cadence_after_restart(self, tmp_path):
        """Post-restart strokes at ~15s gap → healthy."""
        # Pre: two strokes well before restart
        pre = [_dt(-10), _dt(-9)]
        # Restart at t=0
        restart = _dt(0)
        # Post: two strokes 15s apart (exactly target)
        post = [_dt(0.25), _dt(0.5)]  # 15s apart
        all_ts = pre + post
        p = _mk_strokes(tmp_path, all_ts)

        report = assess(p, restart.isoformat(), target_gap=15.0)
        assert report.verdict == "healthy"
        assert report.strokes_after == 2
        assert report.pre_gap > 0
        assert report.post_gap == pytest.approx(15.0 * 60 / 60, abs=1)  # 15s

    def test_healthy_slightly_fast(self, tmp_path):
        """Post-restart strokes at 10s gap → still healthy (within 1.5x)."""
        pre = [_dt(-5), _dt(-4)]
        restart = _dt(0)
        # 10s apart = 0.67x target, well within 1.5x
        post = [_dt(0.1), _dt(0.1 + 10/60)]
        p = _mk_strokes(tmp_path, pre + post)

        report = assess(p, restart.isoformat(), target_gap=15.0)
        assert report.verdict == "healthy"


# ---------------------------------------------------------------------------
# assess — recovering
# ---------------------------------------------------------------------------

class TestAssessRecovering:
    def test_slow_but_running(self, tmp_path):
        """Post-restart gap is 2x target → recovering."""
        pre = [_dt(-10), _dt(-8)]
        restart = _dt(0)
        # 30s apart = 2x target
        post = [_dt(0.5), _dt(0.5 + 30/60)]
        p = _mk_strokes(tmp_path, pre + post)

        report = assess(p, restart.isoformat(), target_gap=15.0)
        assert report.verdict == "recovering"

    def test_single_post_stroke(self, tmp_path):
        """Only one stroke after restart → recovering (not enough data)."""
        pre = [_dt(-5), _dt(-3)]
        restart = _dt(0)
        post = [_dt(1)]
        p = _mk_strokes(tmp_path, pre + post)

        report = assess(p, restart.isoformat(), target_gap=15.0)
        assert report.verdict == "recovering"
        assert report.strokes_after == 1


# ---------------------------------------------------------------------------
# assess — still stalled
# ---------------------------------------------------------------------------

class TestAssessStillStalled:
    def test_huge_gap_after_restart(self, tmp_path):
        """Post-restart gap is 5x target → still_stalled."""
        pre = [_dt(-20), _dt(-15)]
        restart = _dt(0)
        # 75s apart = 5x target
        post = [_dt(1), _dt(1 + 75/60)]
        p = _mk_strokes(tmp_path, pre + post)

        report = assess(p, restart.isoformat(), target_gap=15.0)
        assert report.verdict == "still_stalled"


# ---------------------------------------------------------------------------
# assess — dead
# ---------------------------------------------------------------------------

class TestAssessDead:
    def test_no_strokes_after_restart(self, tmp_path):
        """No strokes at all after restart → dead."""
        pre = [_dt(-10), _dt(-5)]
        restart = _dt(0)
        p = _mk_strokes(tmp_path, pre)

        report = assess(p, restart.isoformat(), target_gap=15.0)
        assert report.verdict == "dead"
        assert report.strokes_after == 0
        assert report.post_gap == float("inf")

    def test_empty_strokes_file(self, tmp_path):
        """Empty strokes file → dead."""
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        restart = _dt(0)

        report = assess(p, restart.isoformat(), target_gap=15.0)
        assert report.verdict == "dead"


# ---------------------------------------------------------------------------
# assess — edge cases
# ---------------------------------------------------------------------------

class TestAssessEdgeCases:
    def test_pre_gap_with_one_pre_stroke(self, tmp_path):
        """Only one stroke before restart — pre_gap measured to restart_ts."""
        pre = [_dt(-2)]
        restart = _dt(0)
        post = [_dt(0.5), _dt(0.5 + 15/60)]
        p = _mk_strokes(tmp_path, pre + post)

        report = assess(p, restart.isoformat(), target_gap=15.0)
        assert report.pre_gap == pytest.approx(120.0, abs=1)  # 2 min

    def test_datetime_object_input(self, tmp_path):
        """Accept datetime object instead of string for restart_ts."""
        pre = [_dt(-5), _dt(-3)]
        restart_dt = _dt(0)
        post = [_dt(0.5), _dt(0.5 + 15/60)]
        p = _mk_strokes(tmp_path, pre + post)

        report = assess(p, restart_dt, target_gap=15.0)
        assert report.verdict == "healthy"

    def test_naive_restart_datetime(self, tmp_path):
        """Naive datetime (no tz) gets treated as UTC."""
        pre = [_dt(-5), _dt(-3)]
        restart_naive = datetime(2026, 11, 3, 19, 0, 0)  # naive
        post = [_dt(0.5), _dt(0.5 + 15/60)]
        p = _mk_strokes(tmp_path, pre + post)

        report = assess(p, restart_naive, target_gap=15.0)
        assert report.verdict in ("healthy", "recovering", "still_stalled")

    def test_target_gap_zero(self, tmp_path):
        """Zero target gap should not crash (division by zero guard)."""
        pre = [_dt(-5), _dt(-3)]
        restart = _dt(0)
        post = [_dt(0.5), _dt(1)]
        p = _mk_strokes(tmp_path, pre + post)

        report = assess(p, restart.isoformat(), target_gap=0.0)
        # With target_gap=0, any gap is infinite ratio → still_stalled
        assert report.verdict == "still_stalled"


# ---------------------------------------------------------------------------
# is_healthy
# ---------------------------------------------------------------------------

class TestIsHealthy:
    def test_healthy(self):
        r = RestartReport("healthy", 100, 15, 15, 10, 300)
        assert is_healthy(r) is True

    def test_not_healthy(self):
        for v in ("recovering", "still_stalled", "dead"):
            r = RestartReport(v, 100, 15, 15, 10, 300)
            assert is_healthy(r) is False


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_contains_verdict(self):
        r = RestartReport("healthy", 2264, 15, 15, 5, 600)
        s = format_report(r)
        assert "healthy" in s
        assert "2264" in s

    def test_dead_format(self):
        r = RestartReport("dead", 300, float("inf"), 15, 0, 120)
        s = format_report(r)
        assert "dead" in s
        assert "inf" in s
