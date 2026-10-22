"""Tests for iamai.lock_scar."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from iamai.lock_scar import (
    ScarReport,
    _classify,
    _interval_trend,
    _parse_ts,
    scar_report,
    scar_summary,
)


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------

class TestParseTs:
    def test_iso_with_z(self):
        dt = _parse_ts("2026-10-22T06:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_iso_with_offset(self):
        dt = _parse_ts("2026-10-22T06:00:00+08:00")
        assert dt is not None

    def test_iso_without_tz(self):
        dt = _parse_ts("2026-10-22T06:00:00")
        assert dt is not None
        assert dt.tzinfo == timezone.utc

    def test_datetime_passthrough(self):
        dt = datetime(2026, 10, 22, 6, 0, tzinfo=timezone.utc)
        assert _parse_ts(dt) == dt

    def test_none(self):
        assert _parse_ts(None) is None

    def test_empty(self):
        assert _parse_ts("") is None

    def test_garbage(self):
        assert _parse_ts("not-a-date") is None


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_clean(self):
        assert _classify(0, 0.0) == "clean"

    def test_bruised(self):
        assert _classify(2, 7200.0) == "bruised"

    def test_scarred_by_count(self):
        assert _classify(5, 7200.0) == "scarred"

    def test_scarred_by_interval(self):
        assert _classify(3, 1800.0) == "scarred"

    def test_chronic_by_count(self):
        assert _classify(12, 7200.0) == "chronic"

    def test_chronic_by_interval(self):
        assert _classify(3, 300.0) == "chronic"

    def test_boundary_10(self):
        assert _classify(10, 7200.0) == "chronic"

    def test_boundary_4(self):
        assert _classify(4, 7200.0) == "scarred"


# ---------------------------------------------------------------------------
# _interval_trend
# ---------------------------------------------------------------------------

class TestIntervalTrend:
    def test_unknown_few_gaps(self):
        assert _interval_trend([100.0, 200.0]) == "unknown"

    def test_shrinking(self):
        # First half: large gaps, second half: small gaps
        gaps = [1000.0, 1000.0, 1000.0, 100.0, 100.0, 100.0]
        assert _interval_trend(gaps) == "shrinking"

    def test_growing(self):
        # First half: small gaps, second half: large gaps
        gaps = [100.0, 100.0, 100.0, 1000.0, 1000.0, 1000.0]
        assert _interval_trend(gaps) == "growing"

    def test_stable(self):
        gaps = [500.0, 500.0, 500.0, 500.0, 500.0, 500.0]
        assert _interval_trend(gaps) == "stable"


# ---------------------------------------------------------------------------
# scar_report
# ---------------------------------------------------------------------------

class TestScarReport:
    def test_empty_incidents(self):
        report = scar_report([])
        assert report.verdict == "clean"
        assert report.incident_count == 0

    def test_single_incident(self):
        report = scar_report([
            {"at": "2026-10-22T00:00:00Z", "path": ".git/index.lock"},
        ])
        assert report.incident_count == 1
        assert report.verdict == "bruised"
        assert report.hottest_path == ".git/index.lock"
        assert report.recurrence_interval == 0.0

    def test_multiple_same_path_bruised(self):
        base = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
        incidents = [
            {"at": (base + timedelta(hours=i * 2)).isoformat(), "path": ".git/index.lock"}
            for i in range(3)
        ]
        report = scar_report(incidents)
        assert report.incident_count == 3
        assert report.hottest_count == 3
        # Interval is 2 hours → bruised
        assert report.verdict == "bruised"

    def test_multiple_same_path_scarred(self):
        base = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
        incidents = [
            {"at": (base + timedelta(minutes=i * 30)).isoformat(), "path": ".git/index.lock"}
            for i in range(5)
        ]
        report = scar_report(incidents)
        assert report.incident_count == 5
        assert report.verdict == "scarred"

    def test_chronic_by_count(self):
        base = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
        incidents = [
            {"at": (base + timedelta(hours=i)).isoformat(), "path": ".git/index.lock"}
            for i in range(12)
        ]
        report = scar_report(incidents)
        assert report.verdict == "chronic"

    def test_chronic_by_interval(self):
        """Incidents every 5 minutes → chronic even with few count."""
        base = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
        incidents = [
            {"at": (base + timedelta(minutes=i * 5)).isoformat(), "path": ".git/index.lock"}
            for i in range(3)
        ]
        report = scar_report(incidents)
        assert report.verdict == "chronic"

    def test_multiple_paths(self):
        base = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
        incidents = [
            {"at": base.isoformat(), "path": ".git/index.lock"},
            {"at": (base + timedelta(hours=1)).isoformat(), "path": ".git/index.lock"},
            {"at": (base + timedelta(hours=2)).isoformat(), "path": ".git/HEAD.lock"},
        ]
        report = scar_report(incidents)
        assert report.incident_count == 3
        assert report.hottest_path == ".git/index.lock"
        assert report.hottest_count == 2

    def test_interval_trend_shrinking(self):
        """Gaps get smaller over time → shrinking."""
        base = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
        # Gaps: 60min, 60min, 60min, 5min, 5min, 5min
        times = [
            base,
            base + timedelta(hours=1),
            base + timedelta(hours=2),
            base + timedelta(hours=3),
            base + timedelta(hours=3, minutes=5),
            base + timedelta(hours=3, minutes=10),
            base + timedelta(hours=3, minutes=15),
        ]
        incidents = [
            {"at": t.isoformat(), "path": ".git/index.lock"} for t in times
        ]
        report = scar_report(incidents)
        assert report.interval_trend == "shrinking"

    def test_bad_timestamps_skipped(self):
        incidents = [
            {"at": "not-a-date", "path": ".git/index.lock"},
            {"at": "2026-10-22T00:00:00Z", "path": ".git/index.lock"},
        ]
        report = scar_report(incidents)
        assert report.incident_count == 1

    def test_all_bad_timestamps(self):
        incidents = [
            {"at": "garbage", "path": ".git/index.lock"},
            {"at": "", "path": ".git/HEAD.lock"},
        ]
        report = scar_report(incidents)
        assert report.verdict == "clean"


# ---------------------------------------------------------------------------
# scar_summary
# ---------------------------------------------------------------------------

class TestScarSummary:
    def test_clean(self):
        s = scar_summary(ScarReport())
        assert "clean" in s

    def test_bruised(self):
        s = scar_summary(ScarReport(
            incident_count=2,
            hotspots=[(".git/index.lock", 2)],
            hottest_path=".git/index.lock",
            hottest_count=2,
            recurrence_interval=7200.0,
            interval_trend="unknown",
            verdict="bruised",
        ))
        assert "bruised" in s
        assert ".git/index.lock" in s

    def test_format_hours(self):
        s = scar_summary(ScarReport(
            incident_count=3,
            hotspots=[(".git/index.lock", 3)],
            hottest_path=".git/index.lock",
            hottest_count=3,
            recurrence_interval=7200.0,
            interval_trend="stable",
            verdict="bruised",
        ))
        assert "2.0h" in s

    def test_format_minutes(self):
        s = scar_summary(ScarReport(
            incident_count=5,
            hotspots=[(".git/index.lock", 5)],
            hottest_path=".git/index.lock",
            hottest_count=5,
            recurrence_interval=1800.0,
            interval_trend="shrinking",
            verdict="scarred",
        ))
        assert "30.0m" in s

    def test_format_seconds(self):
        s = scar_summary(ScarReport(
            incident_count=10,
            hotspots=[(".git/index.lock", 10)],
            hottest_path=".git/index.lock",
            hottest_count=10,
            recurrence_interval=45.0,
            interval_trend="shrinking",
            verdict="chronic",
        ))
        assert "45s" in s
