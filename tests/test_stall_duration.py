"""Tests for iamai.stall_duration — stall duration and uptime measurement."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from iamai.stall_duration import (
    measure_stalls,
    from_mortality_ledger,
    StallReport,
    _merge_intervals,
)


# ---------------------------------------------------------------------------
# _merge_intervals
# ---------------------------------------------------------------------------

class TestMergeIntervals:
    def test_empty(self):
        assert _merge_intervals([]) == []

    def test_single(self):
        iv = [(datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc),
               datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc))]
        assert _merge_intervals(iv) == iv

    def test_non_overlapping(self):
        a = (datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc),
             datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc))
        b = (datetime(2026, 1, 1, 5, 0, tzinfo=timezone.utc),
             datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc))
        assert _merge_intervals([a, b]) == [a, b]

    def test_overlapping(self):
        a = (datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc),
             datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc))
        b = (datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc),
             datetime(2026, 1, 1, 5, 0, tzinfo=timezone.utc))
        result = _merge_intervals([a, b])
        assert len(result) == 1
        assert result[0][0] == datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)
        assert result[0][1] == datetime(2026, 1, 1, 5, 0, tzinfo=timezone.utc)

    def test_adjacent(self):
        a = (datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc),
             datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc))
        b = (datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc),
             datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc))
        result = _merge_intervals([a, b])
        assert len(result) == 1

    def test_unsorted_input(self):
        a = (datetime(2026, 1, 1, 5, 0, tzinfo=timezone.utc),
             datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc))
        b = (datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc),
             datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc))
        result = _merge_intervals([a, b])
        assert result[0][0].hour == 2
        assert result[1][0].hour == 5

    def test_contained_interval(self):
        outer = (datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc),
                 datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc))
        inner = (datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc),
                 datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc))
        result = _merge_intervals([outer, inner])
        assert len(result) == 1
        assert result[0] == outer


# ---------------------------------------------------------------------------
# measure_stalls — basic behavior
# ---------------------------------------------------------------------------

class TestMeasureStalls:
    def test_empty_events(self):
        report = measure_stalls([])
        assert report.total_stalls == 0
        assert report.uptime_ratio == 1.0
        assert report.total_downtime_seconds == 0.0

    def test_single_stall_one_hour(self):
        events = [
            ("2026-10-19T02:00:00+08:00", "2026-10-19T03:00:00+08:00"),
        ]
        report = measure_stalls(events)
        assert report.total_stalls == 1
        assert report.total_downtime_seconds == 3600.0
        assert report.longest_stall_seconds == 3600.0
        assert report.shortest_stall_seconds == 3600.0

    def test_two_non_overlapping_stalls(self):
        events = [
            ("2026-10-19T02:00:00+08:00", "2026-10-19T03:00:00+08:00"),
            ("2026-10-19T05:00:00+08:00", "2026-10-19T05:30:00+08:00"),
        ]
        report = measure_stalls(events)
        assert report.total_stalls == 2
        assert report.total_downtime_seconds == 5400.0  # 3600 + 1800
        assert report.longest_stall_seconds == 3600.0
        assert report.shortest_stall_seconds == 1800.0
        assert report.average_stall_seconds == 2700.0

    def test_overlapping_stalls_merged(self):
        events = [
            ("2026-10-19T02:00:00+08:00", "2026-10-19T03:30:00+08:00"),
            ("2026-10-19T03:00:00+08:00", "2026-10-19T04:00:00+08:00"),
        ]
        report = measure_stalls(events)
        assert report.total_stalls == 1  # merged
        assert report.total_downtime_seconds == 7200.0  # 02:00 to 04:00

    def test_instant_restart(self):
        events = [
            ("2026-10-19T02:00:00+08:00", "2026-10-19T02:00:00+08:00"),
        ]
        report = measure_stalls(events)
        assert report.total_downtime_seconds == 0.0

    def test_restart_before_death_clamped(self):
        # Restart timestamp before death — should clamp to zero.
        events = [
            ("2026-10-19T03:00:00+08:00", "2026-10-19T02:00:00+08:00"),
        ]
        report = measure_stalls(events)
        assert report.total_downtime_seconds == 0.0


# ---------------------------------------------------------------------------
# measure_stalls — uptime ratio
# ---------------------------------------------------------------------------

class TestUptimeRatio:
    def test_explicit_window(self):
        events = [
            ("2026-10-19T02:00:00+08:00", "2026-10-19T03:00:00+08:00"),
        ]
        report = measure_stalls(
            events,
            window_start="2026-10-19T00:00:00+08:00",
            window_end="2026-10-19T04:00:00+08:00",
        )
        # 4-hour window, 1 hour down → uptime = 0.75
        assert report.window_seconds == 14400.0
        assert abs(report.uptime_ratio - 0.75) < 0.001

    def test_implicit_window_from_events(self):
        events = [
            ("2026-10-19T02:00:00+08:00", "2026-10-19T02:30:00+08:00"),
        ]
        report = measure_stalls(events)
        # Window is exactly the event span → 30 min total, 30 min down → uptime = 0
        assert report.window_seconds == 1800.0
        assert report.uptime_ratio == 0.0

    def test_uptime_clamped_to_unit(self):
        # Window smaller than downtime — should clamp uptime to 0.
        events = [
            ("2026-10-19T02:00:00+08:00", "2026-10-19T04:00:00+08:00"),
        ]
        report = measure_stalls(
            events,
            window_start="2026-10-19T02:30:00+08:00",
            window_end="2026-10-19T03:30:00+08:00",
        )
        assert report.uptime_ratio == 0.0

    def test_zero_window(self):
        events = [
            ("2026-10-19T02:00:00+08:00", "2026-10-19T02:00:00+08:00"),
        ]
        report = measure_stalls(
            events,
            window_start="2026-10-19T02:00:00+08:00",
            window_end="2026-10-19T02:00:00+08:00",
        )
        # Zero window, zero downtime → uptime = 1.0
        assert report.uptime_ratio == 1.0


# ---------------------------------------------------------------------------
# measure_stalls — epoch and datetime inputs
# ---------------------------------------------------------------------------

class TestTimestampTypes:
    def test_datetime_objects(self):
        events = [
            (datetime(2026, 10, 19, 2, 0, tzinfo=timezone.utc),
             datetime(2026, 10, 19, 3, 0, tzinfo=timezone.utc)),
        ]
        report = measure_stalls(events)
        assert report.total_downtime_seconds == 3600.0

    def test_epoch_floats(self):
        t0 = 1729267200.0  # some epoch
        events = [(t0, t0 + 600)]  # 10 minutes
        report = measure_stalls(events)
        assert report.total_downtime_seconds == 600.0

    def test_mixed_types(self):
        events = [
            ("2026-10-19T02:00:00+00:00",
             datetime(2026, 10, 19, 3, 0, tzinfo=timezone.utc)),
        ]
        report = measure_stalls(events)
        assert report.total_downtime_seconds == 3600.0


# ---------------------------------------------------------------------------
# as_dict
# ---------------------------------------------------------------------------

class TestAsDict:
    def test_round_trips(self):
        events = [
            ("2026-10-19T02:00:00+08:00", "2026-10-19T03:00:00+08:00"),
        ]
        report = measure_stalls(events)
        d = report.as_dict()
        assert "total_stalls" in d
        assert "uptime_ratio" in d
        assert isinstance(d["stall_durations"], list)

    def test_frozen_dataclass(self):
        events = [
            ("2026-10-19T02:00:00+08:00", "2026-10-19T03:00:00+08:00"),
        ]
        report = measure_stalls(events)
        with pytest.raises(AttributeError):
            report.total_stalls = 999


# ---------------------------------------------------------------------------
# from_mortality_ledger
# ---------------------------------------------------------------------------

class TestFromMortalityLedger:
    def test_missing_ledger(self, tmp_path):
        report = from_mortality_ledger(str(tmp_path))
        assert report.total_stalls == 0

    def test_paired_events(self, tmp_path):
        ledger = tmp_path / "data" / "process_mortality.jsonl"
        ledger.parent.mkdir()
        lines = [
            json.dumps({"event": "death", "writer": "qwen",
                        "ts": "2026-10-19T02:00:00+00:00"}),
            json.dumps({"event": "restart", "writer": "qwen",
                        "ts": "2026-10-19T02:30:00+00:00"}),
        ]
        ledger.write_text("\n".join(lines), encoding="utf-8")
        report = from_mortality_ledger(str(tmp_path))
        assert report.total_stalls == 1
        assert report.total_downtime_seconds == 1800.0

    def test_filters_by_writer(self, tmp_path):
        ledger = tmp_path / "data" / "process_mortality.jsonl"
        ledger.parent.mkdir()
        lines = [
            json.dumps({"event": "death", "writer": "doubao",
                        "ts": "2026-10-19T02:00:00+00:00"}),
            json.dumps({"event": "restart", "writer": "doubao",
                        "ts": "2026-10-19T02:30:00+00:00"}),
        ]
        ledger.write_text("\n".join(lines), encoding="utf-8")
        report = from_mortality_ledger(str(tmp_path), writer="qwen")
        assert report.total_stalls == 0

    def test_unpaired_death_ignored(self, tmp_path):
        ledger = tmp_path / "data" / "process_mortality.jsonl"
        ledger.parent.mkdir()
        lines = [
            json.dumps({"event": "death", "writer": "qwen",
                        "ts": "2026-10-19T02:00:00+00:00"}),
            # No restart follows
            json.dumps({"event": "death", "writer": "qwen",
                        "ts": "2026-10-19T04:00:00+00:00"}),
            json.dumps({"event": "restart", "writer": "qwen",
                        "ts": "2026-10-19T04:10:00+00:00"}),
        ]
        ledger.write_text("\n".join(lines), encoding="utf-8")
        report = from_mortality_ledger(str(tmp_path))
        # First death has no restart; second pair is valid.
        assert report.total_stalls == 1
        assert report.total_downtime_seconds == 600.0

    def test_malformed_lines_skipped(self, tmp_path):
        ledger = tmp_path / "data" / "process_mortality.jsonl"
        ledger.parent.mkdir()
        lines = [
            "this is not json",
            json.dumps({"event": "death", "writer": "qwen",
                        "ts": "2026-10-19T02:00:00+00:00"}),
            "",
            json.dumps({"event": "restart", "writer": "qwen",
                        "ts": "2026-10-19T02:05:00+00:00"}),
        ]
        ledger.write_text("\n".join(lines), encoding="utf-8")
        report = from_mortality_ledger(str(tmp_path))
        assert report.total_stalls == 1
        assert report.total_downtime_seconds == 300.0
