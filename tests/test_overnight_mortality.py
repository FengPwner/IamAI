"""Tests for iamai.overnight_mortality — overnight stall classifier."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from iamai.overnight_mortality import (
    classify_stalls,
    from_mortality_ledger,
    OvernightReport,
    _to_datetime,
    _is_night_hour,
)


# ---------------------------------------------------------------------------
# _to_datetime helpers
# ---------------------------------------------------------------------------

class TestToDatetime:
    def test_iso_string_with_tz(self):
        dt = _to_datetime("2026-10-19T02:00:00+08:00")
        assert dt.hour == 2  # preserved local hour? No — fromisoformat keeps offset
        assert dt.tzinfo is not None

    def test_iso_string_utc(self):
        dt = _to_datetime("2026-10-19T02:00:00+00:00")
        assert dt.hour == 2

    def test_naive_string_gets_utc(self):
        dt = _to_datetime("2026-10-19T02:00:00")
        assert dt.tzinfo == timezone.utc

    def test_epoch_float(self):
        dt = _to_datetime(0.0)
        assert dt == datetime(1970, 1, 1, tzinfo=timezone.utc)

    def test_datetime_passthrough(self):
        dt = datetime(2026, 10, 19, 3, 0, tzinfo=timezone.utc)
        assert _to_datetime(dt) is dt

    def test_naive_datetime_gets_utc(self):
        dt = datetime(2026, 10, 19, 3, 0)
        result = _to_datetime(dt)
        assert result.tzinfo == timezone.utc

    def test_bad_type_raises(self):
        with pytest.raises(TypeError):
            _to_datetime([1, 2, 3])

    def test_bad_string_raises(self):
        with pytest.raises(ValueError):
            _to_datetime("not-a-date")


# ---------------------------------------------------------------------------
# _is_night_hour
# ---------------------------------------------------------------------------

class TestIsNightHour:
    def test_midnight_in_range(self):
        dt = datetime(2026, 10, 19, 0, 30, tzinfo=timezone.utc)
        assert _is_night_hour(dt, 0, 6) is True

    def test_5am_in_range(self):
        dt = datetime(2026, 10, 19, 5, 59, tzinfo=timezone.utc)
        assert _is_night_hour(dt, 0, 6) is True

    def test_6am_excluded(self):
        dt = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)
        assert _is_night_hour(dt, 0, 6) is False

    def test_noon_not_night(self):
        dt = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
        assert _is_night_hour(dt, 0, 6) is False

    def test_wrapping_range_late_night(self):
        # night 22:00–06:00: hour 23 should be in range
        dt = datetime(2026, 10, 19, 23, 0, tzinfo=timezone.utc)
        assert _is_night_hour(dt, 22, 6) is True

    def test_wrapping_range_early_morning(self):
        dt = datetime(2026, 10, 19, 3, 0, tzinfo=timezone.utc)
        assert _is_night_hour(dt, 22, 6) is True

    def test_wrapping_range_afternoon_excluded(self):
        dt = datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc)
        assert _is_night_hour(dt, 22, 6) is False


# ---------------------------------------------------------------------------
# classify_stalls
# ---------------------------------------------------------------------------

class TestClassifyStalls:
    def test_empty_list(self):
        report = classify_stalls([])
        assert report.total_stalls == 0
        assert report.is_overnight_pattern is False
        assert report.overnight_ratio == 0.0

    def test_all_overnight(self):
        stalls = [
            "2026-10-19T01:00:00+08:00",
            "2026-10-19T02:30:00+08:00",
            "2026-10-19T03:45:00+08:00",
            "2026-10-19T04:00:00+08:00",
        ]
        report = classify_stalls(stalls)
        assert report.total_stalls == 4
        assert report.overnight_stalls == 4
        assert report.overnight_ratio == 1.0
        assert report.is_overnight_pattern is True

    def test_mixed_stalls(self):
        stalls = [
            "2026-10-19T02:00:00+00:00",  # night
            "2026-10-19T14:00:00+00:00",  # day
            "2026-10-19T03:00:00+00:00",  # night
            "2026-10-19T10:00:00+00:00",  # day
            "2026-10-19T01:00:00+00:00",  # night
        ]
        report = classify_stalls(stalls)
        assert report.total_stalls == 5
        assert report.overnight_stalls == 3
        assert report.overnight_ratio == pytest.approx(0.6, abs=0.01)
        assert report.is_overnight_pattern is False  # 60% < 70% threshold

    def test_threshold_boundary(self):
        # Exactly 70% overnight → should be True
        stalls = [
            "2026-10-19T02:00:00+00:00",  # night
            "2026-10-19T03:00:00+00:00",  # night
            "2026-10-19T04:00:00+00:00",  # night
            "2026-10-19T05:00:00+00:00",  # night
            "2026-10-19T01:00:00+00:00",  # night
            "2026-10-19T02:30:00+00:00",  # night
            "2026-10-19T03:30:00+00:00",  # night
            "2026-10-19T10:00:00+00:00",  # day
            "2026-10-19T14:00:00+00:00",  # day
            "2026-10-19T18:00:00+00:00",  # day
        ]
        report = classify_stalls(stalls)
        assert report.total_stalls == 10
        assert report.overnight_stalls == 7
        assert report.overnight_ratio == pytest.approx(0.7)
        assert report.is_overnight_pattern is True

    def test_custom_night_window(self):
        stalls = [
            "2026-10-19T22:00:00+00:00",  # in 22–06 window
            "2026-10-19T23:30:00+00:00",  # in window
            "2026-10-19T12:00:00+00:00",  # day
        ]
        report = classify_stalls(stalls, night_start=22, night_end=6)
        assert report.overnight_stalls == 2
        assert report.overnight_ratio == pytest.approx(2 / 3, abs=0.01)

    def test_custom_threshold(self):
        stalls = [
            "2026-10-19T02:00:00+00:00",  # night
            "2026-10-19T14:00:00+00:00",  # day
        ]
        # 50% overnight — below default 70%, but above 40%
        report_low = classify_stalls(stalls, threshold=0.4)
        assert report_low.is_overnight_pattern is True

        report_high = classify_stalls(stalls, threshold=0.8)
        assert report_high.is_overnight_pattern is False

    def test_hour_distribution(self):
        stalls = [
            "2026-10-19T02:00:00+00:00",
            "2026-10-19T02:30:00+00:00",
            "2026-10-19T14:00:00+00:00",
        ]
        report = classify_stalls(stalls)
        assert report.hour_distribution[2] == 2
        assert report.hour_distribution[14] == 1

    def test_report_as_dict(self):
        report = classify_stalls(["2026-10-19T02:00:00+00:00"])
        d = report.as_dict()
        assert "total_stalls" in d
        assert "overnight_ratio" in d
        assert "is_overnight_pattern" in d
        assert "night_window" in d
        assert d["night_window"] == "00:00-06:00"

    def test_report_frozen(self):
        report = classify_stalls(["2026-10-19T02:00:00+00:00"])
        with pytest.raises(AttributeError):
            report.total_stalls = 999

    def test_epoch_floats(self):
        # 2026-10-19 02:00 UTC = epoch 1792460000 (approximately)
        from datetime import datetime, timezone
        dt = datetime(2026, 10, 19, 2, 0, tzinfo=timezone.utc)
        epoch = dt.timestamp()
        report = classify_stalls([epoch])
        assert report.total_stalls == 1
        assert report.overnight_stalls == 1

    def test_single_stall_day(self):
        report = classify_stalls(["2026-10-19T15:00:00+00:00"])
        assert report.total_stalls == 1
        assert report.overnight_stalls == 0
        assert report.is_overnight_pattern is False


# ---------------------------------------------------------------------------
# from_mortality_ledger (integration with file I/O)
# ---------------------------------------------------------------------------

class TestFromMortalityLedger:
    def test_missing_ledger(self, tmp_path):
        report = from_mortality_ledger(tmp_path)
        assert report.total_stalls == 0

    def test_with_ledger(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        ledger = data_dir / "process_mortality.jsonl"
        events = [
            {"ts": "2026-10-19T02:00:00+00:00", "writer": "qwen", "event": "death"},
            {"ts": "2026-10-19T03:00:00+00:00", "writer": "qwen", "event": "restart"},
            {"ts": "2026-10-19T04:00:00+00:00", "writer": "qwen", "event": "death"},
            {"ts": "2026-10-19T14:00:00+00:00", "writer": "qwen", "event": "death"},
            {"ts": "2026-10-19T14:05:00+00:00", "writer": "kimi", "event": "death"},
        ]
        ledger.write_text(
            "\n".join(json.dumps(e) for e in events) + "\n",
            encoding="utf-8",
        )
        report = from_mortality_ledger(tmp_path, writer="qwen")
        assert report.total_stalls == 3  # only "death" events for "qwen"
        assert report.overnight_stalls == 2  # hours 2 and 4
        assert report.overnight_ratio == pytest.approx(2 / 3, abs=0.01)

    def test_filters_writer(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        ledger = data_dir / "process_mortality.jsonl"
        events = [
            {"ts": "2026-10-19T02:00:00+00:00", "writer": "kimi", "event": "death"},
            {"ts": "2026-10-19T14:00:00+00:00", "writer": "kimi", "event": "death"},
        ]
        ledger.write_text(
            "\n".join(json.dumps(e) for e in events) + "\n",
            encoding="utf-8",
        )
        report = from_mortality_ledger(tmp_path, writer="qwen")
        assert report.total_stalls == 0  # no qwen events
