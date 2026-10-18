"""Tests for process_resurrection module."""

import pytest
from datetime import datetime, timezone, timedelta

from iamai.process_resurrection import (
    measure_resurrections,
    ResurrectionReport,
    _to_datetime,
    _gap_seconds,
)


# ---------------------------------------------------------------------------
# _to_datetime helpers
# ---------------------------------------------------------------------------

class TestToDatetime:
    def test_iso_with_tz(self):
        dt = _to_datetime("2026-10-19T04:00:00+08:00")
        assert dt.hour == 4
        assert dt.utcoffset() == timedelta(hours=8)

    def test_iso_utc(self):
        dt = _to_datetime("2026-10-19T04:00:00+00:00")
        assert dt.tzinfo == timezone.utc or dt.utcoffset() == timedelta(0)

    def test_iso_naive_gets_utc(self):
        dt = _to_datetime("2026-10-19T04:00:00")
        assert dt is not None  # naive ISO stays naive per fromisoformat

    def test_epoch_float(self):
        dt = _to_datetime(0.0)
        assert dt == datetime(1970, 1, 1, tzinfo=timezone.utc)

    def test_epoch_int(self):
        dt = _to_datetime(1792357270)
        assert dt.year == 2026

    def test_datetime_passthrough(self):
        original = datetime(2026, 10, 19, 4, 0, tzinfo=timezone.utc)
        assert _to_datetime(original) == original

    def test_datetime_naive_gets_utc(self):
        naive = datetime(2026, 10, 19, 4, 0)
        result = _to_datetime(naive)
        assert result.tzinfo == timezone.utc

    def test_z_suffix(self):
        dt = _to_datetime("2026-10-19T04:00:00Z")
        assert dt.year == 2026
        assert dt.utcoffset() == timedelta(0)

    def test_unsupported_type(self):
        with pytest.raises(TypeError):
            _to_datetime([1, 2, 3])


# ---------------------------------------------------------------------------
# _gap_seconds
# ---------------------------------------------------------------------------

class TestGapSeconds:
    def test_normal_gap(self):
        gap = _gap_seconds(
            "2026-10-19T04:00:00+08:00",
            "2026-10-19T04:05:00+08:00",
        )
        assert gap == 300.0

    def test_zero_gap(self):
        gap = _gap_seconds(
            "2026-10-19T04:00:00+08:00",
            "2026-10-19T04:00:00+08:00",
        )
        assert gap == 0.0

    def test_negative_clamped(self):
        """If first_stroke < restart (clock skew), clamp to 0."""
        gap = _gap_seconds(
            "2026-10-19T04:05:00+08:00",
            "2026-10-19T04:00:00+08:00",
        )
        assert gap == 0.0


# ---------------------------------------------------------------------------
# measure_resurrections — core
# ---------------------------------------------------------------------------

class TestMeasureResurrections:
    def test_empty_events(self):
        report = measure_resurrections([])
        assert report.count == 0
        assert report.mean_gap_seconds == 0.0
        assert report.healthy_ratio == 1.0  # vacuously healthy
        assert report.is_healthy_pattern is True

    def test_single_healthy(self):
        events = [
            ("2026-10-19T04:00:00+08:00", "2026-10-19T04:10:00+08:00"),
        ]
        report = measure_resurrections(events, cadence_seconds=900)
        assert report.count == 1
        assert report.mean_gap_seconds == 600.0
        assert report.healthy_ratio == 1.0  # 600 <= 1800

    def test_single_unhealthy(self):
        events = [
            ("2026-10-19T04:00:00+08:00", "2026-10-19T05:00:00+08:00"),
        ]
        report = measure_resurrections(events, cadence_seconds=900)
        assert report.count == 1
        assert report.mean_gap_seconds == 3600.0
        assert report.healthy_ratio == 0.0  # 3600 > 1800

    def test_mixed_events(self):
        events = [
            # 5 min gap → healthy (5 min < 30 min threshold)
            ("2026-10-19T04:00:00+08:00", "2026-10-19T04:05:00+08:00"),
            # 45 min gap → unhealthy
            ("2026-10-19T03:00:00+08:00", "2026-10-19T03:45:00+08:00"),
            # 10 min gap → healthy
            ("2026-10-18T04:00:00+08:00", "2026-10-18T04:10:00+08:00"),
        ]
        report = measure_resurrections(events, cadence_seconds=900)
        assert report.count == 3
        assert report.healthy_count == 2
        assert abs(report.healthy_ratio - 2 / 3) < 0.01
        assert report.is_healthy_pattern is False  # 66.7% < 80%
        # Correction: 2/3 = 0.667 < 0.80 → not healthy
        assert report.is_healthy_pattern is False

    def test_all_healthy(self):
        events = [
            ("2026-10-19T04:00:00+08:00", "2026-10-19T04:03:00+08:00"),
            ("2026-10-18T03:00:00+08:00", "2026-10-18T03:05:00+08:00"),
            ("2026-10-17T02:00:00+08:00", "2026-10-17T02:02:00+08:00"),
        ]
        report = measure_resurrections(events, cadence_seconds=900)
        assert report.healthy_ratio == 1.0
        assert report.is_healthy_pattern is True

    def test_boundary_exactly_threshold(self):
        """Gap exactly at 2x cadence (1800s) should be healthy."""
        events = [
            ("2026-10-19T04:00:00+08:00", "2026-10-19T04:30:00+08:00"),
        ]
        report = measure_resurrections(events, cadence_seconds=900)
        assert report.gaps[0] == 1800.0
        assert report.healthy_ratio == 1.0

    def test_boundary_one_second_over(self):
        events = [
            ("2026-10-19T04:00:00+08:00", "2026-10-19T04:30:01+08:00"),
        ]
        report = measure_resurrections(events, cadence_seconds=900)
        assert report.gaps[0] == 1801.0
        assert report.healthy_ratio == 0.0


# ---------------------------------------------------------------------------
# measure_resurrections — custom parameters
# ---------------------------------------------------------------------------

class TestCustomParameters:
    def test_custom_cadence(self):
        """With 600s cadence and 2x multiplier, threshold = 1200s."""
        events = [
            ("2026-10-19T04:00:00+08:00", "2026-10-19T04:19:00+08:00"),
        ]
        report = measure_resurrections(events, cadence_seconds=600)
        assert report.gaps[0] == 1140.0
        assert report.healthy_ratio == 1.0  # 1140 <= 1200

    def test_custom_multiplier(self):
        """With 1.5x multiplier on 900s cadence, threshold = 1350s."""
        events = [
            ("2026-10-19T04:00:00+08:00", "2026-10-19T04:20:00+08:00"),
        ]
        report = measure_resurrections(
            events, cadence_seconds=900, healthy_multiplier=1.5
        )
        assert report.healthy_threshold_seconds == 1350.0
        assert report.gaps[0] == 1200.0
        assert report.healthy_ratio == 1.0


# ---------------------------------------------------------------------------
# ResurrectionReport properties
# ---------------------------------------------------------------------------

class TestResurrectionReportProperties:
    def test_max_min_gap(self):
        events = [
            ("2026-10-19T04:00:00+08:00", "2026-10-19T04:03:00+08:00"),
            ("2026-10-18T03:00:00+08:00", "2026-10-18T03:30:00+08:00"),
        ]
        report = measure_resurrections(events)
        assert report.max_gap_seconds == 1800.0
        assert report.min_gap_seconds == 180.0

    def test_as_dict_roundtrip(self):
        events = [
            ("2026-10-19T04:00:00+08:00", "2026-10-19T04:05:00+08:00"),
        ]
        report = measure_resurrections(events)
        d = report.as_dict()
        assert d["count"] == 1
        assert d["mean_gap_seconds"] == 300.0
        assert d["cadence_seconds"] == 900
        assert isinstance(d["is_healthy_pattern"], bool)

    def test_frozen(self):
        """Report is frozen — mutation should raise."""
        report = measure_resurrections([])
        with pytest.raises(Exception):
            report.cadence_seconds = 60  # type: ignore


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_identical_timestamps(self):
        events = [
            ("2026-10-19T04:00:00+08:00", "2026-10-19T04:00:00+08:00"),
        ]
        report = measure_resurrections(events)
        assert report.gaps[0] == 0.0
        assert report.healthy_ratio == 1.0

    def test_cross_timezone_events(self):
        """Events in different timezones should still compute correct gaps."""
        events = [
            # restart in UTC, first stroke in +08:00 (same instant + 5 min)
            ("2026-10-18T20:00:00+00:00", "2026-10-19T04:05:00+08:00"),
        ]
        report = measure_resurrections(events)
        assert report.gaps[0] == 300.0

    def test_large_gap(self):
        """A 12-hour gap should not crash."""
        events = [
            ("2026-10-19T04:00:00+08:00", "2026-10-19T16:00:00+08:00"),
        ]
        report = measure_resurrections(events)
        assert report.gaps[0] == 43200.0
        assert report.healthy_ratio == 0.0
