"""Tests for iamai.stroke_pipeline_latency — write-to-commit delivery time.

Visit 814: this module measures how quickly strokes travel from the
writer's append to inclusion in a git commit, providing an end-to-end
view of the delivery pipeline's health.

Test areas:
    1. _parse_timestamp         — ISO 8601 parsing
    2. load_strokes             — JSONL loading, n-tail, error handling
    3. get_commit_timestamps    — git log parsing (mocked)
    4. match_strokes_to_commits — stroke-to-commit matching
    5. compute_latency_stats    — descriptive statistics
    6. within_target_fraction   — on-time delivery fraction
    7. health_label             — health classification
    8. compute_trend            — bucketed trend analysis
    9. trend_direction          — improving/stable/degrading
   10. pipeline_report          — full report integration
   11. pipeline_summary         — human-readable output
   12. _cli                     — exit codes, --json flag
   13. edge cases               — empty, single, degenerate inputs
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_pipeline_latency import (
    _cli,
    _parse_timestamp,
    compute_latency_stats,
    compute_trend,
    get_commit_timestamps,
    health_label,
    load_strokes,
    match_strokes_to_commits,
    pipeline_report,
    pipeline_summary,
    trend_direction,
    within_target_fraction,
    DEFAULT_TARGET_SECONDS,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _ts(offset_seconds: float) -> str:
    """Return an ISO-8601 timestamp at *offset_seconds* after a base time."""
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(seconds=offset_seconds)).isoformat()


def _make_strokes(timestamps: list) -> list:
    """Create a list of stroke dicts from a list of ISO timestamp strings."""
    return [
        {"seq": i + 1, "at": ts, "kind": "thought", "text": f"stroke {i+1}"}
        for i, ts in enumerate(timestamps)
    ]


def _write_strokes_jsonl(tmp_path: Path, strokes: list) -> Path:
    """Write strokes to a temporary JSONL file and return its path."""
    p = tmp_path / "strokes.jsonl"
    with open(p, "w") as f:
        for s in strokes:
            f.write(json.dumps(s) + "\n")
    return p


# -----------------------------------------------------------------------
# 1. _parse_timestamp
# -----------------------------------------------------------------------


class TestParseTimestamp:
    def test_valid_iso_with_timezone(self):
        dt = _parse_timestamp("2026-01-01T12:00:00+00:00")
        assert dt is not None
        assert dt.year == 2026
        assert dt.tzinfo is not None

    def test_valid_iso_without_timezone(self):
        dt = _parse_timestamp("2026-06-15T08:30:00")
        assert dt is not None
        assert dt.tzinfo is not None  # should default to UTC

    def test_empty_string(self):
        assert _parse_timestamp("") is None

    def test_none(self):
        assert _parse_timestamp(None) is None

    def test_garbage(self):
        assert _parse_timestamp("not-a-date") is None

    def test_preserves_timezone_offset(self):
        dt = _parse_timestamp("2026-01-01T12:00:00+08:00")
        assert dt is not None
        assert dt.utcoffset() == timedelta(hours=8)


# -----------------------------------------------------------------------
# 2. load_strokes
# -----------------------------------------------------------------------


class TestLoadStrokes:
    def test_load_all(self, tmp_path):
        strokes = _make_strokes([_ts(0), _ts(15), _ts(30)])
        p = _write_strokes_jsonl(tmp_path, strokes)
        result = load_strokes(path=p)
        assert len(result) == 3
        assert result[0]["seq"] == 1

    def test_load_last_n(self, tmp_path):
        strokes = _make_strokes([_ts(i * 15) for i in range(10)])
        p = _write_strokes_jsonl(tmp_path, strokes)
        result = load_strokes(path=p, n=3)
        assert len(result) == 3
        assert result[0]["seq"] == 8

    def test_nonexistent_file(self, tmp_path):
        result = load_strokes(path=tmp_path / "missing.jsonl")
        assert result == []

    def test_malformed_lines_skipped(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        with open(p, "w") as f:
            f.write('{"seq": 1, "at": "2026-01-01T12:00:00+00:00", "kind": "thought", "text": "ok"}\n')
            f.write("not json\n")
            f.write("\n")
            f.write('{"seq": 2, "at": "2026-01-01T12:00:15+00:00", "kind": "thought", "text": "ok2"}\n')
        result = load_strokes(path=p)
        assert len(result) == 2

    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        result = load_strokes(path=p)
        assert result == []


# -----------------------------------------------------------------------
# 3. get_commit_timestamps (mocked git)
# -----------------------------------------------------------------------


class TestGetCommitTimestamps:
    def test_parses_git_output(self):
        mock_output = (
            "2026-01-01T12:10:00+00:00\n"
            "2026-01-01T12:20:00+00:00\n"
            "2026-01-01T12:30:00+00:00\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=mock_output,
            )
            result = get_commit_timestamps(repo_root=Path("/fake"))
            assert len(result) == 3
            # should be sorted
            assert result[0] < result[1] < result[2]

    def test_handles_git_failure(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = get_commit_timestamps(repo_root=Path("/fake"))
            assert result == []

    def test_handles_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            result = get_commit_timestamps(repo_root=Path("/fake"))
            assert result == []

    def test_empty_output(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            result = get_commit_timestamps(repo_root=Path("/fake"))
            assert result == []

    def test_skips_malformed_lines(self):
        mock_output = "2026-01-01T12:10:00+00:00\ngarbage\n2026-01-01T12:20:00+00:00\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output)
            result = get_commit_timestamps(repo_root=Path("/fake"))
            assert len(result) == 2


import subprocess  # noqa: E402 — needed for TimeoutExpired in test


# -----------------------------------------------------------------------
# 4. match_strokes_to_commits
# -----------------------------------------------------------------------


class TestMatchStrokesToCommits:
    def test_basic_matching(self):
        strokes = _make_strokes([_ts(0), _ts(15), _ts(30)])
        commits = [
            datetime(2026, 1, 1, 12, 10, 0, tzinfo=timezone.utc),  # 600s after base
        ]
        result = match_strokes_to_commits(strokes, commits)
        assert len(result) == 3
        # all three strokes matched to the same commit
        for r in result:
            assert r["latency_seconds"] > 0

    def test_strokes_before_first_commit(self):
        strokes = _make_strokes([_ts(0), _ts(15)])
        commits = [
            datetime(2026, 1, 1, 12, 10, 0, tzinfo=timezone.utc),
        ]
        result = match_strokes_to_commits(strokes, commits)
        assert len(result) == 2
        assert result[0]["latency_seconds"] == 600.0

    def test_strokes_after_last_commit_omitted(self):
        strokes = _make_strokes([_ts(0), _ts(3600)])
        commits = [
            datetime(2026, 1, 1, 12, 10, 0, tzinfo=timezone.utc),
        ]
        result = match_strokes_to_commits(strokes, commits)
        # first stroke matched, second didn't (no commit after it)
        assert len(result) == 1

    def test_multiple_commits(self):
        strokes = _make_strokes([_ts(1), _ts(601), _ts(1201)])
        commits = [
            datetime(2026, 1, 1, 12, 10, 0, tzinfo=timezone.utc),   # +600s
            datetime(2026, 1, 1, 12, 20, 0, tzinfo=timezone.utc),   # +1200s
            datetime(2026, 1, 1, 12, 30, 0, tzinfo=timezone.utc),   # +1800s
        ]
        result = match_strokes_to_commits(strokes, commits)
        assert len(result) == 3
        assert result[0]["latency_seconds"] == 599.0
        assert result[1]["latency_seconds"] == 599.0
        assert result[2]["latency_seconds"] == 599.0

    def test_empty_commits(self):
        strokes = _make_strokes([_ts(0)])
        result = match_strokes_to_commits(strokes, [])
        assert result == []

    def test_empty_strokes(self):
        commits = [datetime(2026, 1, 1, 12, 10, 0, tzinfo=timezone.utc)]
        result = match_strokes_to_commits([], commits)
        assert result == []

    def test_stroke_without_timestamp_skipped(self):
        strokes = [{"seq": 1, "at": "", "kind": "thought", "text": "bad"}]
        commits = [datetime(2026, 1, 1, 12, 10, 0, tzinfo=timezone.utc)]
        result = match_strokes_to_commits(strokes, commits)
        assert result == []


# -----------------------------------------------------------------------
# 5. compute_latency_stats
# -----------------------------------------------------------------------


class TestComputeLatencyStats:
    def test_basic_stats(self):
        latencies = [100.0, 200.0, 300.0, 400.0, 500.0]
        stats = compute_latency_stats(latencies)
        assert stats["count"] == 5
        assert stats["mean"] == 300.0
        assert stats["median"] == 300.0
        assert stats["min"] == 100.0
        assert stats["max"] == 500.0

    def test_single_value(self):
        stats = compute_latency_stats([42.0])
        assert stats["count"] == 1
        assert stats["mean"] == 42.0
        assert stats["p95"] == 42.0
        assert stats["p99"] == 42.0

    def test_empty(self):
        stats = compute_latency_stats([])
        assert stats["count"] == 0
        assert stats["mean"] == 0.0

    def test_percentiles(self):
        latencies = list(range(1, 101))  # 1..100
        stats = compute_latency_stats([float(x) for x in latencies])
        assert stats["p95"] == 95.05  # 95th percentile
        assert stats["p99"] == 99.01  # 99th percentile (approximately)

    def test_two_values(self):
        stats = compute_latency_stats([10.0, 90.0])
        assert stats["mean"] == 50.0
        assert stats["median"] == 50.0


# -----------------------------------------------------------------------
# 6. within_target_fraction
# -----------------------------------------------------------------------


class TestWithinTargetFraction:
    def test_all_within(self):
        latencies = [100.0, 200.0, 300.0, 400.0, 500.0]
        assert within_target_fraction(latencies, 600) == 1.0

    def test_none_within(self):
        latencies = [700.0, 800.0, 900.0]
        assert within_target_fraction(latencies, 600) == 0.0

    def test_mixed(self):
        latencies = [100.0, 600.0, 700.0, 300.0]
        assert within_target_fraction(latencies, 600) == 0.75

    def test_exactly_at_target(self):
        latencies = [600.0]
        assert within_target_fraction(latencies, 600) == 1.0

    def test_empty(self):
        assert within_target_fraction([], 600) == 0.0


# -----------------------------------------------------------------------
# 7. health_label
# -----------------------------------------------------------------------


class TestHealthLabel:
    def test_excellent(self):
        assert health_label(0.95) == "excellent"
        assert health_label(1.0) == "excellent"

    def test_healthy(self):
        assert health_label(0.80) == "healthy"
        assert health_label(0.94) == "healthy"

    def test_degraded(self):
        assert health_label(0.60) == "degraded"
        assert health_label(0.79) == "degraded"

    def test_congested(self):
        assert health_label(0.59) == "congested"
        assert health_label(0.0) == "congested"

    def test_boundary_values(self):
        assert health_label(0.95) == "excellent"
        assert health_label(0.80) == "healthy"
        assert health_label(0.60) == "degraded"
        assert health_label(0.5999) == "congested"


# -----------------------------------------------------------------------
# 8. compute_trend
# -----------------------------------------------------------------------


class TestComputeTrend:
    def test_basic_buckets(self):
        matched = [
            {"latency_seconds": 100.0},
            {"latency_seconds": 200.0},
            {"latency_seconds": 300.0},
            {"latency_seconds": 400.0},
        ]
        trend = compute_trend(matched, bucket_size=2)
        assert len(trend) == 2
        assert trend[0] == 150.0
        assert trend[1] == 350.0

    def test_single_bucket(self):
        matched = [{"latency_seconds": 100.0}, {"latency_seconds": 200.0}]
        trend = compute_trend(matched, bucket_size=10)
        assert len(trend) == 1
        assert trend[0] == 150.0

    def test_empty(self):
        assert compute_trend([], bucket_size=5) == []

    def test_bucket_size_zero(self):
        assert compute_trend([{"latency_seconds": 1.0}], bucket_size=0) == []

    def test_uneven_buckets(self):
        matched = [{"latency_seconds": float(i)} for i in range(5)]
        trend = compute_trend(matched, bucket_size=3)
        assert len(trend) == 2
        assert trend[0] == 1.0  # mean of 0, 1, 2
        assert trend[1] == 3.5  # mean of 3, 4


# -----------------------------------------------------------------------
# 9. trend_direction
# -----------------------------------------------------------------------


class TestTrendDirection:
    def test_improving(self):
        # second half is >10% lower than first half
        assert trend_direction([500.0, 500.0, 200.0, 200.0]) == "improving"

    def test_degrading(self):
        # second half is >10% higher than first half
        assert trend_direction([100.0, 100.0, 500.0, 500.0]) == "degrading"

    def test_stable(self):
        assert trend_direction([300.0, 300.0, 310.0, 310.0]) == "stable"

    def test_single_value(self):
        assert trend_direction([100.0]) == "stable"

    def test_empty(self):
        assert trend_direction([]) == "stable"

    def test_two_values_improving(self):
        assert trend_direction([100.0, 50.0]) == "improving"

    def test_two_values_degrading(self):
        assert trend_direction([100.0, 200.0]) == "degrading"


# -----------------------------------------------------------------------
# 10. pipeline_report (integration with mocked git)
# -----------------------------------------------------------------------


class TestPipelineReport:
    def test_full_report(self, tmp_path):
        strokes = _make_strokes([_ts(i * 15) for i in range(10)])
        p = _write_strokes_jsonl(tmp_path, strokes)
        commits = [
            datetime(2026, 1, 1, 12, 10, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 1, 12, 20, 0, tzinfo=timezone.utc),
        ]
        with patch(
            "iamai.stroke_pipeline_latency.get_commit_timestamps",
            return_value=commits,
        ):
            report = pipeline_report(n=10, path=p)
        assert report["total_strokes"] == 10
        assert report["matched_strokes"] == 10
        assert report["health_label"] in ("excellent", "healthy", "degraded", "congested")
        assert "trend" in report
        assert "trend_direction" in report

    def test_report_with_no_commits(self, tmp_path):
        strokes = _make_strokes([_ts(0), _ts(15)])
        p = _write_strokes_jsonl(tmp_path, strokes)
        with patch(
            "iamai.stroke_pipeline_latency.get_commit_timestamps",
            return_value=[],
        ):
            report = pipeline_report(n=2, path=p)
        assert report["matched_strokes"] == 0
        assert report["health_label"] == "congested"


# -----------------------------------------------------------------------
# 11. pipeline_summary
# -----------------------------------------------------------------------


class TestPipelineSummary:
    def test_format(self):
        report = {
            "matched_strokes": 180,
            "total_strokes": 200,
            "health_label": "healthy",
            "within_target_fraction": 0.90,
            "median_latency_seconds": 300.0,
            "p95_latency_seconds": 580.0,
            "trend_direction": "stable",
        }
        summary = pipeline_summary(report)
        assert "healthy" in summary
        assert "180/200" in summary
        assert "90%" in summary
        assert "300s" in summary
        assert "stable" in summary

    def test_zero_values(self):
        report = {
            "matched_strokes": 0,
            "total_strokes": 0,
            "health_label": "congested",
            "within_target_fraction": 0.0,
            "median_latency_seconds": 0.0,
            "p95_latency_seconds": 0.0,
            "trend_direction": "stable",
        }
        summary = pipeline_summary(report)
        assert "congested" in summary


# -----------------------------------------------------------------------
# 12. _cli
# -----------------------------------------------------------------------


class TestCLI:
    def test_default_output(self, tmp_path, capsys):
        strokes = _make_strokes([_ts(i * 15) for i in range(5)])
        p = _write_strokes_jsonl(tmp_path, strokes)
        with patch("iamai.stroke_pipeline_latency.STROKES_PATH", p), \
             patch("iamai.stroke_pipeline_latency.get_commit_timestamps",
                   return_value=[datetime(2026, 1, 1, 12, 10, 0, tzinfo=timezone.utc)]):
            exit_code = _cli(["-n", "5"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "pipeline" in captured.out

    def test_json_output(self, tmp_path, capsys):
        strokes = _make_strokes([_ts(0), _ts(15)])
        p = _write_strokes_jsonl(tmp_path, strokes)
        with patch("iamai.stroke_pipeline_latency.STROKES_PATH", p), \
             patch("iamai.stroke_pipeline_latency.get_commit_timestamps",
                   return_value=[datetime(2026, 1, 1, 12, 10, 0, tzinfo=timezone.utc)]):
            exit_code = _cli(["-n", "2", "--json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "total_strokes" in data
        assert "health_label" in data


# -----------------------------------------------------------------------
# 13. Edge cases
# -----------------------------------------------------------------------


class TestEdgeCases:
    def test_all_strokes_at_same_time(self):
        strokes = _make_strokes([_ts(0), _ts(0), _ts(0)])
        commits = [datetime(2026, 1, 1, 12, 10, 0, tzinfo=timezone.utc)]
        result = match_strokes_to_commits(strokes, commits)
        assert len(result) == 3
        for r in result:
            assert r["latency_seconds"] == 600.0

    def test_very_large_latency(self):
        """Stroke written long before any commit (e.g. overnight stall)."""
        strokes = _make_strokes([_ts(0)])
        commits = [datetime(2026, 1, 1, 15, 0, 0, tzinfo=timezone.utc)]
        result = match_strokes_to_commits(strokes, commits)
        assert len(result) == 1
        assert result[0]["latency_seconds"] == 3 * 3600  # 3 hours

    def test_fractional_latency_precision(self):
        """Ensure sub-second precision is preserved."""
        base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        stroke_time = base + timedelta(seconds=0.5)
        commit_time = base + timedelta(seconds=100.3)
        strokes = [{"seq": 1, "at": stroke_time.isoformat(), "kind": "thought", "text": "x"}]
        result = match_strokes_to_commits(strokes, [commit_time])
        assert abs(result[0]["latency_seconds"] - 99.8) < 0.01

    def test_n_larger_than_available(self, tmp_path):
        strokes = _make_strokes([_ts(0), _ts(15)])
        p = _write_strokes_jsonl(tmp_path, strokes)
        result = load_strokes(path=p, n=100)
        assert len(result) == 2

    def test_compute_trend_single_stroke(self):
        matched = [{"latency_seconds": 42.0}]
        trend = compute_trend(matched, bucket_size=20)
        assert trend == [42.0]

    def test_latency_stats_all_identical(self):
        stats = compute_latency_stats([100.0] * 50)
        assert stats["mean"] == 100.0
        assert stats["median"] == 100.0
        assert stats["p95"] == 100.0
        assert stats["p99"] == 100.0
        assert stats["min"] == 100.0
        assert stats["max"] == 100.0
