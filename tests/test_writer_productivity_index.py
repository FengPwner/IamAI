"""Tests for tools.writer_productivity_index — writing throughput metrics."""

from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import sys

# Ensure tools/ is importable
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

from writer_productivity_index import (
    parse_iso,
    load_strokes,
    filter_strokes_by_window,
    compute_net_strokes_per_hour,
    compute_diversity_score,
    compute_efficiency_ratio,
    compute_productivity_index,
    extract_restart_timestamps_from_git,
    build_report,
    render_report,
)


# ---------------------------------------------------------------------------
# parse_iso
# ---------------------------------------------------------------------------

class TestParseIso:
    def test_utc_z_suffix(self):
        dt = parse_iso("2026-11-03T12:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.hour == 12

    def test_offset_suffix(self):
        dt = parse_iso("2026-11-03T12:00:00+08:00")
        assert dt is not None
        assert dt.utcoffset() == timedelta(hours=8)

    def test_naive_gets_utc(self):
        dt = parse_iso("2026-11-03T12:00:00")
        assert dt is not None
        assert dt.tzinfo == timezone.utc

    def test_microseconds(self):
        dt = parse_iso("2026-11-03T12:00:00.123456Z")
        assert dt is not None
        assert dt.microsecond == 123456

    def test_empty_returns_none(self):
        assert parse_iso("") is None
        assert parse_iso(None) is None

    def test_garbage_returns_none(self):
        assert parse_iso("not a date") is None
        assert parse_iso("2026-13-40") is None

    def test_whitespace_stripped(self):
        dt = parse_iso("  2026-11-03T12:00:00Z  ")
        assert dt is not None


# ---------------------------------------------------------------------------
# load_strokes
# ---------------------------------------------------------------------------

class TestLoadStrokes:
    def test_valid_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        entries = [
            {"seq": 1, "at": "2026-11-03T10:00:00Z", "kind": "thought", "text": "a"},
            {"seq": 2, "at": "2026-11-03T10:00:15Z", "kind": "note", "text": "b"},
            {"seq": 3, "at": "2026-11-03T10:00:30Z", "kind": "thought", "text": "c"},
        ]
        p.write_text("\n".join(json.dumps(e) for e in entries))
        strokes = load_strokes(p)
        assert len(strokes) == 3
        assert strokes[0]["_ts"] < strokes[1]["_ts"] < strokes[2]["_ts"]

    def test_skips_malformed_lines(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            '{"seq":1,"at":"2026-11-03T10:00:00Z","kind":"thought","text":"a"}',
            'this is not json',
            '{"seq":3,"at":"2026-11-03T10:00:30Z","kind":"thought","text":"c"}',
        ]
        p.write_text("\n".join(lines))
        strokes = load_strokes(p)
        assert len(strokes) == 2

    def test_skips_missing_timestamp(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        entries = [
            {"seq": 1, "kind": "thought", "text": "no timestamp"},
            {"seq": 2, "at": "2026-11-03T10:00:15Z", "kind": "note", "text": "ok"},
        ]
        p.write_text("\n".join(json.dumps(e) for e in entries))
        strokes = load_strokes(p)
        assert len(strokes) == 1

    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        strokes = load_strokes(p)
        assert len(strokes) == 0

    def test_nonexistent_file(self, tmp_path):
        p = tmp_path / "does_not_exist.jsonl"
        strokes = load_strokes(p)
        assert len(strokes) == 0

    def test_blank_lines_skipped(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            '{"seq":1,"at":"2026-11-03T10:00:00Z","kind":"thought","text":"a"}',
            '',
            '   ',
            '{"seq":2,"at":"2026-11-03T10:00:15Z","kind":"note","text":"b"}',
        ]
        p.write_text("\n".join(lines))
        strokes = load_strokes(p)
        assert len(strokes) == 2


# ---------------------------------------------------------------------------
# filter_strokes_by_window
# ---------------------------------------------------------------------------

class TestFilterStrokesByWindow:
    def _make_strokes(self, times: list[str]) -> list[dict]:
        result = []
        for t in times:
            result.append({"at": t, "_ts": parse_iso(t), "kind": "thought"})
        return result

    def test_filters_old_strokes(self):
        now = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
        strokes = self._make_strokes([
            "2026-11-03T11:00:00Z",  # within 2h
            "2026-11-03T10:30:00Z",  # within 2h
            "2026-11-03T09:00:00Z",  # outside 2h
            "2026-11-03T08:00:00Z",  # outside 2h
        ])
        filtered = filter_strokes_by_window(strokes, 2.0, now=now)
        assert len(filtered) == 2

    def test_all_within_window(self):
        now = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
        strokes = self._make_strokes([
            "2026-11-03T11:30:00Z",
            "2026-11-03T11:45:00Z",
        ])
        filtered = filter_strokes_by_window(strokes, 1.0, now=now)
        assert len(filtered) == 2

    def test_none_within_window(self):
        now = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
        strokes = self._make_strokes([
            "2026-11-03T08:00:00Z",
            "2026-11-03T07:00:00Z",
        ])
        filtered = filter_strokes_by_window(strokes, 1.0, now=now)
        assert len(filtered) == 0

    def test_empty_input(self):
        now = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
        filtered = filter_strokes_by_window([], 24.0, now=now)
        assert len(filtered) == 0


# ---------------------------------------------------------------------------
# compute_net_strokes_per_hour
# ---------------------------------------------------------------------------

class TestNetStrokesPerHour:
    def test_basic_rate(self):
        strokes = [{"_ts": datetime.now(timezone.utc)}] * 100
        rate = compute_net_strokes_per_hour(strokes, 4.0)
        assert rate == 25.0

    def test_zero_hours(self):
        strokes = [{"_ts": datetime.now(timezone.utc)}] * 10
        rate = compute_net_strokes_per_hour(strokes, 0.0)
        assert rate == 0.0

    def test_empty_strokes(self):
        rate = compute_net_strokes_per_hour([], 24.0)
        assert rate == 0.0

    def test_fractional_hours(self):
        strokes = [{"_ts": datetime.now(timezone.utc)}] * 10
        rate = compute_net_strokes_per_hour(strokes, 0.5)
        assert rate == 20.0


# ---------------------------------------------------------------------------
# compute_diversity_score
# ---------------------------------------------------------------------------

class TestDiversityScore:
    def test_single_kind(self):
        strokes = [{"kind": "thought"}] * 100
        assert compute_diversity_score(strokes) == 0.0

    def test_uniform_distribution(self):
        # 4 kinds, 25 each → max entropy → score = 1.0
        strokes = []
        for kind in ("thought", "note", "devlog", "snippet"):
            strokes.extend([{"kind": kind}] * 25)
        score = compute_diversity_score(strokes)
        assert abs(score - 1.0) < 0.01

    def test_skewed_distribution(self):
        # Mostly one kind → low score
        strokes = [{"kind": "thought"}] * 97
        strokes += [{"kind": "note"}] * 1
        strokes += [{"kind": "devlog"}] * 1
        strokes += [{"kind": "snippet"}] * 1
        score = compute_diversity_score(strokes)
        assert 0.0 < score < 0.4

    def test_two_kinds_balanced(self):
        strokes = [{"kind": "thought"}] * 50 + [{"kind": "note"}] * 50
        score = compute_diversity_score(strokes)
        assert abs(score - 1.0) < 0.01

    def test_single_stroke(self):
        assert compute_diversity_score([{"kind": "thought"}]) == 0.0

    def test_empty(self):
        assert compute_diversity_score([]) == 0.0

    def test_unknown_kind_included(self):
        strokes = [{"kind": "thought"}] * 50 + [{"kind": "unknown"}] * 50
        score = compute_diversity_score(strokes)
        assert abs(score - 1.0) < 0.01


# ---------------------------------------------------------------------------
# compute_efficiency_ratio
# ---------------------------------------------------------------------------

class TestEfficiencyRatio:
    def _make_timed_strokes(self, start: datetime, interval_sec: float, n: int):
        strokes = []
        for i in range(n):
            ts = start + timedelta(seconds=i * interval_sec)
            strokes.append({"_ts": ts, "kind": "thought"})
        return strokes

    def test_perfect_cadence(self):
        # 240 strokes at 15s intervals over 1 hour → near 100% efficiency
        start = datetime(2026, 11, 3, 10, 0, 0, tzinfo=timezone.utc)
        strokes = self._make_timed_strokes(start, 15, 240)
        eff = compute_efficiency_ratio(strokes, 1.0)
        assert eff > 0.95

    def test_large_gaps_reduce_efficiency(self):
        # 10 strokes with 30-minute gaps → significant downtime
        start = datetime(2026, 11, 3, 10, 0, 0, tzinfo=timezone.utc)
        strokes = self._make_timed_strokes(start, 1800, 10)
        eff = compute_efficiency_ratio(strokes, 5.0)
        assert eff < 0.8

    def test_zero_hours(self):
        eff = compute_efficiency_ratio([], 0.0)
        assert eff == 0.0

    def test_restart_overhead_deducted(self):
        start = datetime(2026, 11, 3, 10, 0, 0, tzinfo=timezone.utc)
        strokes = self._make_timed_strokes(start, 15, 240)
        restarts = [
            datetime(2026, 11, 3, 10, 15, 0, tzinfo=timezone.utc),
            datetime(2026, 11, 3, 10, 45, 0, tzinfo=timezone.utc),
        ]
        eff_no_restarts = compute_efficiency_ratio(strokes, 1.0)
        eff_with_restarts = compute_efficiency_ratio(
            strokes, 1.0, restart_timestamps=restarts, restart_overhead_minutes=5.0
        )
        # With 2 restarts × 5 min = 10 min overhead on 60 min window
        assert eff_with_restarts < eff_no_restarts
        assert abs(eff_no_restarts - eff_with_restarts - 10 / 60) < 0.02

    def test_efficiency_never_negative(self):
        # Many restarts in a short window could push downtime > total
        strokes = [{"_ts": datetime(2026, 11, 3, 10, 0, 0, tzinfo=timezone.utc)}]
        restarts = [datetime(2026, 11, 3, 10, 0, 0, tzinfo=timezone.utc)] * 100
        eff = compute_efficiency_ratio(
            strokes, 1.0, restart_timestamps=restarts, restart_overhead_minutes=5.0
        )
        assert eff == 0.0


# ---------------------------------------------------------------------------
# compute_productivity_index
# ---------------------------------------------------------------------------

class TestProductivityIndex:
    def test_perfect_system(self):
        pi = compute_productivity_index(240.0, 1.0, 1.0, 240.0)
        assert abs(pi - 1.0) < 0.001

    def test_idle_system(self):
        pi = compute_productivity_index(0.0, 0.0, 0.0, 240.0)
        assert pi == 0.0

    def test_low_rate(self):
        pi = compute_productivity_index(10.0, 1.0, 1.0, 240.0)
        assert abs(pi - 10 / 240) < 0.001

    def test_low_diversity(self):
        pi = compute_productivity_index(240.0, 0.1, 1.0, 240.0)
        assert abs(pi - 0.1) < 0.001

    def test_low_efficiency(self):
        pi = compute_productivity_index(240.0, 1.0, 0.5, 240.0)
        assert abs(pi - 0.5) < 0.001

    def test_composite(self):
        pi = compute_productivity_index(120.0, 0.8, 0.9, 240.0)
        expected = (120 / 240) * 0.8 * 0.9
        assert abs(pi - expected) < 0.001

    def test_rate_exceeds_max(self):
        # Rate above theoretical max should cap at 1.0
        pi = compute_productivity_index(500.0, 1.0, 1.0, 240.0)
        assert abs(pi - 1.0) < 0.001

    def test_zero_theoretical_max(self):
        pi = compute_productivity_index(100.0, 1.0, 1.0, 0.0)
        assert pi == 0.0


# ---------------------------------------------------------------------------
# extract_restart_timestamps_from_git
# ---------------------------------------------------------------------------

class TestExtractRestartTimestamps:
    def test_with_mock_git(self, tmp_path):
        mock_output = (
            "2026-11-03T10:00:00+00:00 catch-up: commit pending\n"
            "2026-11-03T09:00:00+00:00 visit 529: some feature\n"
            "2026-11-03T08:00:00+00:00 restart: recovery after crash\n"
            "2026-11-03T07:00:00+00:00 regular commit\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=mock_output
            )
            ts = extract_restart_timestamps_from_git(tmp_path)
            # Should match "catch-up" and "restart" lines
            assert len(ts) == 2

    def test_git_failure_returns_empty(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            ts = extract_restart_timestamps_from_git(tmp_path)
            assert ts == []

    def test_timeout_returns_empty(self, tmp_path):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            ts = extract_restart_timestamps_from_git(tmp_path)
            assert ts == []


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------

class TestBuildReport:
    def test_report_structure(self):
        now = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
        strokes = [
            {"at": "2026-11-03T11:00:00Z", "_ts": parse_iso("2026-11-03T11:00:00Z"),
             "kind": "thought", "text": "a"},
            {"at": "2026-11-03T11:00:15Z", "_ts": parse_iso("2026-11-03T11:00:15Z"),
             "kind": "note", "text": "b"},
            {"at": "2026-11-03T11:00:30Z", "_ts": parse_iso("2026-11-03T11:00:30Z"),
             "kind": "thought", "text": "c"},
        ]
        report = build_report(strokes, 1.0)

        assert "period_hours" in report
        assert "total_strokes" in report
        assert "net_strokes_per_hour" in report
        assert "diversity_score" in report
        assert "efficiency_ratio" in report
        assert "productivity_index" in report
        assert "kind_breakdown" in report
        assert "restart_count" in report

        assert report["total_strokes"] == 3
        assert report["period_hours"] == 1.0
        assert report["net_strokes_per_hour"] == 3.0
        assert report["kind_breakdown"]["thought"] == 2
        assert report["kind_breakdown"]["note"] == 1

    def test_report_with_restarts(self):
        strokes = [
            {"_ts": datetime(2026, 11, 3, 11, 0, 0, tzinfo=timezone.utc),
             "kind": "thought"},
        ]
        restarts = [datetime(2026, 11, 3, 11, 0, 0, tzinfo=timezone.utc)]
        report = build_report(strokes, 1.0, restart_timestamps=restarts)
        assert report["restart_count"] == 1

    def test_report_empty_strokes(self):
        report = build_report([], 24.0)
        assert report["total_strokes"] == 0
        assert report["productivity_index"] == 0.0


# ---------------------------------------------------------------------------
# render_report
# ---------------------------------------------------------------------------

class TestRenderReport:
    def test_contains_key_fields(self):
        report = {
            "period_hours": 24,
            "total_strokes": 400,
            "net_strokes_per_hour": 16.67,
            "theoretical_max": 240,
            "diversity_score": 0.82,
            "efficiency_ratio": 0.91,
            "productivity_index": 0.0517,
            "kind_breakdown": {"thought": 380, "note": 15, "devlog": 5},
            "restart_count": 3,
        }
        text = render_report(report)
        assert "Writer Productivity Index" in text
        assert "400" in text
        assert "16.67" in text
        assert "0.82" in text
        assert "91%" in text
        assert "thought" in text
        assert "Restart events:         3" in text

    def test_no_restarts_omits_line(self):
        report = {
            "period_hours": 24,
            "total_strokes": 400,
            "net_strokes_per_hour": 16.67,
            "theoretical_max": 240,
            "diversity_score": 0.82,
            "efficiency_ratio": 0.91,
            "productivity_index": 0.0517,
            "kind_breakdown": {"thought": 400},
            "restart_count": 0,
        }
        text = render_report(report)
        assert "Restart events" not in text


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_end_to_end(self, tmp_path):
        """Full pipeline: write strokes → load → compute → report."""
        strokes_path = tmp_path / "strokes.jsonl"
        base = datetime(2026, 11, 3, 10, 0, 0, tzinfo=timezone.utc)
        kinds = ["thought", "note", "devlog", "snippet", "thought", "thought"]
        entries = []
        for i, kind in enumerate(kinds):
            ts = base + timedelta(seconds=i * 15)
            entries.append({
                "seq": i + 1,
                "at": ts.isoformat(),
                "kind": kind,
                "text": f"stroke {i}",
            })
        strokes_path.write_text("\n".join(json.dumps(e) for e in entries))

        strokes = load_strokes(strokes_path)
        assert len(strokes) == 6

        # Filter to 1 hour window
        now = base + timedelta(minutes=30)
        filtered = filter_strokes_by_window(strokes, 1.0, now=now)
        assert len(filtered) == 6

        report = build_report(filtered, 1.0)
        assert report["total_strokes"] == 6
        assert report["net_strokes_per_hour"] == 6.0
        assert report["diversity_score"] > 0  # Multiple kinds
        assert report["efficiency_ratio"] >= 0

        text = render_report(report)
        assert "Writer Productivity Index" in text
