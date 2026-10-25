"""Tests for iamai.restart_recovery."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from iamai.restart_recovery import (
    RecoveryReport,
    _classify,
    _parse_strokes,
    analyse_recovery,
)


def _make_strokes(tmp_path, times: list[datetime]):
    """Write a minimal strokes.jsonl and return the Path."""
    p = tmp_path / "strokes.jsonl"
    lines = []
    for t in times:
        lines.append(json.dumps({"ts": t.isoformat(), "kind": "note", "text": "x"}))
    p.write_text("\n".join(lines))
    return p


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------


class TestClassify:
    def test_fast(self):
        assert _classify(30) == "fast"

    def test_fast_boundary(self):
        assert _classify(59.9) == "fast"

    def test_normal(self):
        assert _classify(120) == "normal"

    def test_normal_boundary(self):
        assert _classify(300) == "normal"

    def test_slow(self):
        assert _classify(450) == "slow"

    def test_slow_boundary(self):
        assert _classify(600) == "slow"

    def test_stalled(self):
        assert _classify(700) == "stalled"

    def test_none_is_stalled(self):
        assert _classify(None) == "stalled"

    def test_zero(self):
        assert _classify(0) == "fast"


# ---------------------------------------------------------------------------
# _parse_strokes
# ---------------------------------------------------------------------------


class TestParseStrokes:
    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        assert _parse_strokes(p) == []

    def test_missing_file(self, tmp_path):
        p = tmp_path / "nonexistent.jsonl"
        assert _parse_strokes(p) == []

    def test_iso_timestamps(self, tmp_path):
        t1 = datetime(2026, 10, 21, 23, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 21, 23, 0, 15, tzinfo=timezone.utc)
        path = _make_strokes(tmp_path, [t1, t2])
        result = _parse_strokes(path)
        assert len(result) == 2
        assert result[0] == t1
        assert result[1] == t2

    def test_unix_timestamps(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        ts = datetime(2026, 10, 21, 23, 0, 0, tzinfo=timezone.utc).timestamp()
        p.write_text(json.dumps({"ts": ts, "kind": "note", "text": "x"}))
        result = _parse_strokes(p)
        assert len(result) == 1

    def test_sorts_out_of_order(self, tmp_path):
        t1 = datetime(2026, 10, 21, 23, 0, 30, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 21, 23, 0, 0, tzinfo=timezone.utc)
        path = _make_strokes(tmp_path, [t1, t2])
        result = _parse_strokes(path)
        assert result[0] < result[1]

    def test_skips_bad_json(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("not json\n" + json.dumps({"ts": "2026-10-21T23:00:00+00:00"}))
        result = _parse_strokes(p)
        assert len(result) == 1

    def test_skips_missing_ts(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(json.dumps({"kind": "note", "text": "no ts"}))
        result = _parse_strokes(p)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# analyse_recovery
# ---------------------------------------------------------------------------


class TestAnalyseRecovery:
    def test_no_strokes_after_restart(self, tmp_path):
        restart = datetime(2026, 10, 21, 23, 0, 0, tzinfo=timezone.utc)
        # strokes all before restart
        before = [restart - timedelta(seconds=60)]
        path = _make_strokes(tmp_path, before)
        report = analyse_recovery(path, restart, cadence_s=15)
        assert report.quality == "stalled"
        assert report.first_stroke_latency_s is None
        assert report.recovery_time_s is None

    def test_fast_recovery(self, tmp_path):
        restart = datetime(2026, 10, 21, 23, 0, 0, tzinfo=timezone.utc)
        # first stroke 5s after restart, then every 15s
        times = [restart + timedelta(seconds=5 + 15 * i) for i in range(6)]
        path = _make_strokes(tmp_path, times)
        report = analyse_recovery(path, restart, cadence_s=15, consecutive=3)
        assert report.quality == "fast"
        assert report.first_stroke_latency_s == 5.0
        assert report.recovery_time_s is not None
        assert report.recovery_time_s < 60

    def test_slow_recovery(self, tmp_path):
        restart = datetime(2026, 10, 21, 23, 0, 0, tzinfo=timezone.utc)
        # long gap then steady
        times = [restart + timedelta(seconds=400)]
        for i in range(1, 6):
            times.append(times[-1] + timedelta(seconds=15))
        path = _make_strokes(tmp_path, times)
        report = analyse_recovery(path, restart, cadence_s=15, consecutive=3)
        assert report.quality in ("slow", "stalled")
        # first latency should be 400s
        assert report.first_stroke_latency_s == 400.0

    def test_stalled_no_recovery(self, tmp_path):
        restart = datetime(2026, 10, 21, 23, 0, 0, tzinfo=timezone.utc)
        # only 2 strokes, both with huge gaps — never achieves 3 consecutive
        times = [
            restart + timedelta(seconds=10),
            restart + timedelta(seconds=500),
        ]
        path = _make_strokes(tmp_path, times)
        report = analyse_recovery(path, restart, cadence_s=15, consecutive=3)
        assert report.quality == "stalled"
        assert report.recovery_time_s is None

    def test_cadence_stability(self, tmp_path):
        restart = datetime(2026, 10, 21, 23, 0, 0, tzinfo=timezone.utc)
        # perfectly regular strokes
        times = [restart + timedelta(seconds=15 * i) for i in range(1, 8)]
        path = _make_strokes(tmp_path, times)
        report = analyse_recovery(path, restart, cadence_s=15, consecutive=3)
        assert report.cadence_stability is not None
        assert report.cadence_stability < 0.01  # nearly zero variance

    def test_irregular_cadence(self, tmp_path):
        restart = datetime(2026, 10, 21, 23, 0, 0, tzinfo=timezone.utc)
        gaps = [5, 28, 3, 29, 2, 28]  # wildly varying but all <=30 (15*2)
        times = [restart]
        for g in gaps:
            times.append(times[-1] + timedelta(seconds=g))
        path = _make_strokes(tmp_path, times)
        report = analyse_recovery(path, restart, cadence_s=15, consecutive=3, tolerance=2.0)
        # should recover (all intervals <= 30) but with high instability
        if report.cadence_stability is not None:
            assert report.cadence_stability > 0.3

    def test_to_dict(self, tmp_path):
        restart = datetime(2026, 10, 21, 23, 0, 0, tzinfo=timezone.utc)
        times = [restart + timedelta(seconds=15 * i) for i in range(1, 6)]
        path = _make_strokes(tmp_path, times)
        report = analyse_recovery(path, restart, cadence_s=15, consecutive=3)
        d = report.to_dict()
        assert "quality" in d
        assert "recovery_time_s" in d
        assert "intervals" in d
        assert isinstance(d["intervals"], list)

    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        restart = datetime(2026, 10, 21, 23, 0, 0, tzinfo=timezone.utc)
        report = analyse_recovery(str(p), restart, cadence_s=15)
        assert report.quality == "stalled"
        assert report.strokes_to_steady == 0

    def test_tolerance_boundary(self, tmp_path):
        """Intervals exactly at tolerance boundary should count."""
        restart = datetime(2026, 10, 21, 23, 0, 0, tzinfo=timezone.utc)
        # intervals of exactly 30s (= 15 * 2.0 tolerance)
        times = [restart + timedelta(seconds=30 * i) for i in range(1, 6)]
        path = _make_strokes(tmp_path, times)
        report = analyse_recovery(path, restart, cadence_s=15, consecutive=3, tolerance=2.0)
        assert report.recovery_time_s is not None

    def test_strokes_before_restart_ignored(self, tmp_path):
        restart = datetime(2026, 10, 21, 23, 0, 0, tzinfo=timezone.utc)
        before = [restart - timedelta(hours=1, seconds=15 * i) for i in range(10)]
        after = [restart + timedelta(seconds=15 * i) for i in range(1, 6)]
        path = _make_strokes(tmp_path, before + after)
        report = analyse_recovery(path, restart, cadence_s=15, consecutive=3)
        assert report.quality == "fast"
        # intervals should only include post-restart ones
        assert len(report.intervals) <= 5
