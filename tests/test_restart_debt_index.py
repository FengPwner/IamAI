"""Tests for tools.restart_debt_index — restart debt accumulation metrics."""

from __future__ import annotations

import json
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

from restart_debt_index import (
    parse_iso,
    extract_restarts_from_log,
    compute_intervals,
    compute_clustering_factor,
    compute_debt_index,
    compute_steady_state_ratio,
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

    def test_empty_returns_none(self):
        assert parse_iso("") is None
        assert parse_iso(None) is None

    def test_garbage_returns_none(self):
        assert parse_iso("not a date") is None
        assert parse_iso("2026-13-40") is None


# ---------------------------------------------------------------------------
# extract_restarts_from_log
# ---------------------------------------------------------------------------

class TestExtractRestartsFromLog:
    def test_valid_log(self, tmp_path):
        log = tmp_path / "restarts.jsonl"
        entries = [
            {"at": "2026-11-03T01:00:00Z", "kind": "restart"},
            {"at": "2026-11-03T03:00:00Z", "kind": "restart"},
            {"at": "2026-11-03T06:00:00Z", "kind": "restart"},
        ]
        log.write_text("\n".join(json.dumps(e) for e in entries))
        ts = extract_restarts_from_log(log)
        assert len(ts) == 3
        assert ts[0] < ts[1] < ts[2]

    def test_filters_non_restart_events(self, tmp_path):
        log = tmp_path / "events.jsonl"
        entries = [
            {"at": "2026-11-03T01:00:00Z", "kind": "restart"},
            {"at": "2026-11-03T02:00:00Z", "kind": "stroke"},
            {"at": "2026-11-03T03:00:00Z", "kind": "commit"},
        ]
        log.write_text("\n".join(json.dumps(e) for e in entries))
        ts = extract_restarts_from_log(log)
        assert len(ts) == 1

    def test_missing_file_returns_empty(self, tmp_path):
        ts = extract_restarts_from_log(tmp_path / "nonexistent.jsonl")
        assert ts == []

    def test_empty_file_returns_empty(self, tmp_path):
        log = tmp_path / "empty.jsonl"
        log.write_text("")
        ts = extract_restarts_from_log(log)
        assert ts == []

    def test_malformed_lines_skipped(self, tmp_path):
        log = tmp_path / "bad.jsonl"
        log.write_text(
            '{"at": "2026-11-03T01:00:00Z", "kind": "restart"}\n'
            'not json\n'
            '{"at": "2026-11-03T02:00:00Z", "kind": "restart"}\n'
        )
        ts = extract_restarts_from_log(log)
        assert len(ts) == 2

    def test_results_sorted(self, tmp_path):
        log = tmp_path / "unsorted.jsonl"
        entries = [
            {"at": "2026-11-03T06:00:00Z", "kind": "restart"},
            {"at": "2026-11-03T01:00:00Z", "kind": "restart"},
            {"at": "2026-11-03T03:00:00Z", "kind": "restart"},
        ]
        log.write_text("\n".join(json.dumps(e) for e in entries))
        ts = extract_restarts_from_log(log)
        assert ts[0].hour == 1
        assert ts[1].hour == 3
        assert ts[2].hour == 6


# ---------------------------------------------------------------------------
# compute_intervals
# ---------------------------------------------------------------------------

class TestComputeIntervals:
    def test_basic_intervals(self):
        base = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)
        ts = [
            base,
            base + timedelta(minutes=60),
            base + timedelta(minutes=150),
        ]
        iv = compute_intervals(ts)
        assert len(iv) == 2
        assert iv[0] == pytest.approx(60.0)
        assert iv[1] == pytest.approx(90.0)

    def test_single_timestamp_returns_empty(self):
        ts = [datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)]
        assert compute_intervals(ts) == []

    def test_empty_returns_empty(self):
        assert compute_intervals([]) == []

    def test_sub_minute_intervals(self):
        base = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)
        ts = [base, base + timedelta(seconds=30)]
        iv = compute_intervals(ts)
        assert len(iv) == 1
        assert iv[0] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# compute_debt_index
# ---------------------------------------------------------------------------

class TestComputeDebtIndex:
    def test_healthy_system_low_debt(self):
        # Restarts every 24 hours = ideal → debt ≈ 0
        intervals = [1440.0, 1440.0, 1440.0]
        debt = compute_debt_index(intervals, ideal_interval_minutes=1440.0)
        assert debt == pytest.approx(0.0, abs=0.01)

    def test_frequent_restarts_high_debt(self):
        # Restarts every 30 minutes → debt ≈ 0.979
        intervals = [30.0, 30.0, 30.0]
        debt = compute_debt_index(intervals, ideal_interval_minutes=1440.0)
        assert debt > 0.95

    def test_empty_intervals_zero_debt(self):
        assert compute_debt_index([], ideal_interval_minutes=1440.0) == 0.0

    def test_debt_clamped_to_one(self):
        # Restarts every 1 minute — debt should be clamped to ≤ 1
        intervals = [1.0, 1.0, 1.0]
        debt = compute_debt_index(intervals, ideal_interval_minutes=1440.0)
        assert debt <= 1.0

    def test_custom_ideal_interval(self):
        intervals = [60.0]
        debt = compute_debt_index(intervals, ideal_interval_minutes=60.0)
        assert debt == pytest.approx(0.0, abs=0.01)

    def test_half_ideal(self):
        intervals = [720.0]
        debt = compute_debt_index(intervals, ideal_interval_minutes=1440.0)
        assert debt == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------------
# compute_clustering_factor
# ---------------------------------------------------------------------------

class TestComputeClusteringFactor:
    def test_no_clustering(self):
        # All intervals > 30 minutes
        intervals = [60.0, 120.0, 180.0]
        cf = compute_clustering_factor(intervals, cluster_threshold_minutes=30.0)
        assert cf == pytest.approx(0.0)

    def test_full_clustering(self):
        # All intervals < 30 minutes
        intervals = [5.0, 10.0, 15.0]
        cf = compute_clustering_factor(intervals, cluster_threshold_minutes=30.0)
        assert cf == pytest.approx(1.0)

    def test_partial_clustering(self):
        intervals = [10.0, 60.0, 15.0, 120.0]
        cf = compute_clustering_factor(intervals, cluster_threshold_minutes=30.0)
        assert cf == pytest.approx(0.5)

    def test_empty_returns_zero(self):
        assert compute_clustering_factor([], cluster_threshold_minutes=30.0) == 0.0

    def test_custom_threshold(self):
        intervals = [45.0, 45.0]
        cf = compute_clustering_factor(intervals, cluster_threshold_minutes=60.0)
        assert cf == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# compute_steady_state_ratio
# ---------------------------------------------------------------------------

class TestComputeSteadyStateRatio:
    def test_few_restarts_high_steady(self):
        base = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)
        ts = [base, base + timedelta(hours=24)]
        # 1 restart * 5 min recovery / (24*60 min span) = 0.35% lost
        ratio = compute_steady_state_ratio(ts, recovery_minutes=5.0)
        assert ratio > 0.99

    def test_many_restarts_lower_steady(self):
        base = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)
        # 100 restarts in 1 hour = 500 min recovery / 60 min span → clamped to 0
        ts = [base + timedelta(seconds=i * 36) for i in range(100)]
        ratio = compute_steady_state_ratio(ts, recovery_minutes=5.0)
        assert ratio == pytest.approx(0.0, abs=0.01)

    def test_single_timestamp_full_steady(self):
        ts = [datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)]
        assert compute_steady_state_ratio(ts) == 1.0

    def test_empty_timestamps_full_steady(self):
        assert compute_steady_state_ratio([]) == 1.0

    def test_custom_recovery_time(self):
        base = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)
        # 2 restarts * 15 min recovery / 60 min span = 0.5
        ts = [base, base + timedelta(hours=1)]
        ratio = compute_steady_state_ratio(ts, recovery_minutes=15.0)
        assert ratio == pytest.approx(0.5, abs=0.01)


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------

class TestBuildReport:
    def test_empty_timestamps(self):
        report = build_report([])
        assert report["total_restarts"] == 0
        assert report["debt_index"] == 0.0
        assert report["steady_state_ratio"] == 1.0

    def test_populated_report(self):
        base = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)
        ts = [
            base,
            base + timedelta(hours=2),
            base + timedelta(hours=4),
            base + timedelta(hours=6),
        ]
        report = build_report(ts, ideal_interval_minutes=1440.0)
        assert report["total_restarts"] == 4
        assert report["mean_interval_minutes"] == pytest.approx(120.0)
        assert 0 < report["debt_index"] < 1
        assert report["observation_span_hours"] == pytest.approx(6.0)
        assert len(report["intervals"]) == 3

    def test_report_has_all_keys(self):
        report = build_report([])
        expected_keys = {
            "total_restarts",
            "mean_interval_minutes",
            "debt_index",
            "clustering_factor",
            "steady_state_ratio",
            "observation_span_hours",
            "intervals",
        }
        assert set(report.keys()) == expected_keys


# ---------------------------------------------------------------------------
# render_report
# ---------------------------------------------------------------------------

class TestRenderReport:
    def test_render_contains_key_labels(self):
        report = {
            "total_restarts": 5,
            "mean_interval_minutes": 120.0,
            "debt_index": 0.75,
            "clustering_factor": 0.3,
            "steady_state_ratio": 0.85,
            "observation_span_hours": 12.0,
            "intervals": [],
        }
        text = render_report(report)
        assert "Total restarts" in text
        assert "Debt index" in text
        assert "Clustering factor" in text
        assert "Steady-state ratio" in text
        assert "5" in text

    def test_render_debt_bar_present(self):
        report = {
            "total_restarts": 1,
            "mean_interval_minutes": 0.0,
            "debt_index": 0.5,
            "clustering_factor": 0.0,
            "steady_state_ratio": 1.0,
            "observation_span_hours": 1.0,
            "intervals": [],
        }
        text = render_report(report)
        assert "▓" in text
        assert "░" in text

    def test_render_zero_debt(self):
        report = {
            "total_restarts": 0,
            "mean_interval_minutes": 0.0,
            "debt_index": 0.0,
            "clustering_factor": 0.0,
            "steady_state_ratio": 1.0,
            "observation_span_hours": 0.0,
            "intervals": [],
        }
        text = render_report(report)
        assert "0.0%" in text


# ---------------------------------------------------------------------------
# Integration: end-to-end with a log file
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_full_pipeline(self, tmp_path):
        log = tmp_path / "restarts.jsonl"
        base = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
        entries = []
        # 10 restarts spread over 3 days
        for i in range(10):
            entries.append({
                "at": (base + timedelta(hours=i * 7)).isoformat(),
                "kind": "restart",
            })
        log.write_text("\n".join(json.dumps(e) for e in entries))

        ts = extract_restarts_from_log(log)
        assert len(ts) == 10

        report = build_report(ts, ideal_interval_minutes=1440.0)
        assert report["total_restarts"] == 10
        assert report["observation_span_hours"] > 0

        text = render_report(report)
        assert "Restart Debt Index" in text
