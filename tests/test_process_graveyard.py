#!/usr/bin/env python3
"""Tests for iamai/process_graveyard.py — process death/restart tracking."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.process_graveyard import (
    Graveyard,
    GraveyardEntry,
    HourProfile,
    _CST,
)


# -- fixtures ----------------------------------------------------------------


@pytest.fixture
def gy_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "process_graveyard.jsonl"


@pytest.fixture
def gy(gy_path: Path) -> Graveyard:
    return Graveyard(gy_path)


def _yesterday(hour: int = 3) -> datetime:
    """Return a CST datetime for yesterday at the given hour."""
    now = datetime.now(_CST)
    return now.replace(hour=hour, minute=0, second=0, microsecond=0) - timedelta(days=1)


def _today(hour: int = 2) -> datetime:
    now = datetime.now(_CST)
    return now.replace(hour=hour, minute=0, second=0, microsecond=0)


# -- GraveyardEntry ----------------------------------------------------------


class TestGraveyardEntry:
    def test_basic_structure(self) -> None:
        e = GraveyardEntry("writer", "death", pid=123, cause="container_sweep")
        assert e["process"] == "writer"
        assert e["event"] == "death"
        assert e["pid"] == 123
        assert e["cause"] == "container_sweep"
        assert "ts" in e

    def test_defaults(self) -> None:
        e = GraveyardEntry("batch", "restart")
        assert e["pid"] is None
        assert e["cause"] is None
        assert e["gap_seconds"] is None

    def test_custom_timestamp(self) -> None:
        ts = datetime(2026, 10, 20, 5, 0, tzinfo=_CST)
        e = GraveyardEntry("writer", "death", ts=ts)
        assert "2026-10-20" in e["ts"]
        assert "05:00" in e["ts"]

    def test_gap_seconds(self) -> None:
        e = GraveyardEntry("writer", "restart", gap_seconds=5266.0)
        assert e["gap_seconds"] == 5266.0


# -- Graveyard.record --------------------------------------------------------


class TestRecord:
    def test_record_creates_file(self, gy: Graveyard, gy_path: Path) -> None:
        gy.record("writer", "death", pid=100, cause="oom")
        assert gy_path.exists()
        lines = gy_path.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["process"] == "writer"
        assert data["event"] == "death"

    def test_record_appends(self, gy: Graveyard, gy_path: Path) -> None:
        gy.record("writer", "death")
        gy.record("writer", "restart", pid=200)
        gy.record("batch", "death")
        lines = gy_path.read_text().strip().splitlines()
        assert len(lines) == 3

    def test_record_returns_entry(self, gy: Graveyard) -> None:
        e = gy.record("writer", "stall", gap_seconds=300)
        assert e["event"] == "stall"
        assert e["gap_seconds"] == 300


# -- Graveyard.filter --------------------------------------------------------


class TestFilter:
    def test_filter_by_process(self, gy: Graveyard) -> None:
        gy.record("writer", "death")
        gy.record("batch", "death")
        gy.record("writer", "restart")
        result = gy.filter(process="writer")
        assert len(result) == 2

    def test_filter_by_event(self, gy: Graveyard) -> None:
        gy.record("writer", "death")
        gy.record("writer", "restart")
        gy.record("writer", "death")
        result = gy.filter(event="death")
        assert len(result) == 2

    def test_filter_since(self, gy: Graveyard) -> None:
        old_ts = _yesterday(3)
        new_ts = _today(8)
        gy.record("writer", "death", ts=old_ts)
        gy.record("writer", "death", ts=new_ts)
        cutoff = _today(0)
        result = gy.filter(since=cutoff)
        assert len(result) == 1
        assert "T08:00" in result[0]["ts"]

    def test_filter_combined(self, gy: Graveyard) -> None:
        gy.record("writer", "death")
        gy.record("batch", "death")
        gy.record("writer", "restart")
        result = gy.filter(process="writer", event="death")
        assert len(result) == 1

    def test_filter_empty(self, gy: Graveyard) -> None:
        gy.record("writer", "death")
        result = gy.filter(process="nonexistent")
        assert len(result) == 0


# -- deaths_today / restarts_today -------------------------------------------


class TestTodayCounts:
    def test_deaths_today_empty(self, gy: Graveyard) -> None:
        assert gy.deaths_today() == 0

    def test_deaths_today_counts(self, gy: Graveyard) -> None:
        gy.record("writer", "death", ts=_today(3))
        gy.record("writer", "death", ts=_today(4))
        gy.record("batch", "death", ts=_today(3))
        gy.record("writer", "death", ts=_yesterday(3))
        assert gy.deaths_today("writer") == 2
        assert gy.deaths_today() == 3

    def test_restarts_today(self, gy: Graveyard) -> None:
        gy.record("writer", "restart", ts=_today(3))
        gy.record("writer", "restart", ts=_today(3))
        assert gy.restarts_today("writer") == 2


# -- mean_gap ----------------------------------------------------------------


class TestMeanGap:
    def test_none_when_empty(self, gy: Graveyard) -> None:
        assert gy.mean_gap() is None

    def test_none_when_no_gaps(self, gy: Graveyard) -> None:
        gy.record("writer", "restart")  # no gap_seconds
        assert gy.mean_gap() is None

    def test_single_gap(self, gy: Graveyard) -> None:
        gy.record("writer", "restart", gap_seconds=100)
        assert gy.mean_gap() == 100.0

    def test_average(self, gy: Graveyard) -> None:
        gy.record("writer", "restart", gap_seconds=100)
        gy.record("writer", "restart", gap_seconds=200)
        gy.record("writer", "restart", gap_seconds=300)
        assert gy.mean_gap() == 200.0

    def test_process_filter(self, gy: Graveyard) -> None:
        gy.record("writer", "restart", gap_seconds=100)
        gy.record("batch", "restart", gap_seconds=500)
        assert gy.mean_gap("writer") == 100.0
        assert gy.mean_gap("batch") == 500.0


# -- HourProfile -------------------------------------------------------------


class TestHourProfile:
    def test_empty_profile(self) -> None:
        hp = HourProfile()
        assert hp.peak_hour() is None
        assert hp.quiet_hours(3) == [0, 1, 2]

    def test_add_and_peak(self) -> None:
        hp = HourProfile()
        hp.add("2026-10-20T03:00:00+08:00")
        hp.add("2026-10-20T03:30:00+08:00")
        hp.add("2026-10-20T08:00:00+08:00")
        assert hp.peak_hour() == 3

    def test_quiet_hours_with_gaps(self) -> None:
        hp = HourProfile()
        hp.add("2026-10-20T03:00:00+08:00")
        hp.add("2026-10-20T15:00:00+08:00")
        quiet = hp.quiet_hours(3)
        # hours with zero events should come first
        assert 0 in quiet
        assert len(quiet) == 3

    def test_as_dict(self) -> None:
        hp = HourProfile()
        hp.add("2026-10-20T03:00:00+08:00")
        hp.add("2026-10-20T03:30:00+08:00")
        d = hp.as_dict()
        assert d == {3: 2}

    def test_graveyard_hour_profile(self, gy: Graveyard) -> None:
        gy.record("writer", "death", ts=_today(3))
        gy.record("writer", "death", ts=_today(3))
        gy.record("writer", "death", ts=_today(8))
        gy.record("batch", "death", ts=_today(15))
        hp = gy.hour_profile("writer")
        assert hp.peak_hour() == 3
        assert hp.as_dict() == {3: 2, 8: 1}


# -- cause_breakdown ---------------------------------------------------------


class TestCauseBreakdown:
    def test_empty(self, gy: Graveyard) -> None:
        assert gy.cause_breakdown() == {}

    def test_counts(self, gy: Graveyard) -> None:
        gy.record("writer", "death", cause="container_sweep")
        gy.record("writer", "death", cause="container_sweep")
        gy.record("writer", "death", cause="oom")
        gy.record("writer", "death")  # no cause -> "unknown"
        bd = gy.cause_breakdown()
        assert bd == {"container_sweep": 2, "unknown": 1, "oom": 1}


# -- summary -----------------------------------------------------------------


class TestSummary:
    def test_empty_summary(self, gy: Graveyard) -> None:
        s = gy.summary("writer")
        assert s["process"] == "writer"
        assert s["total_deaths"] == 0
        assert s["total_restarts"] == 0
        assert s["mean_gap_seconds"] is None

    def test_full_summary(self, gy: Graveyard) -> None:
        gy.record("writer", "death", cause="sweep", ts=_today(3))
        gy.record("writer", "restart", gap_seconds=300, ts=_today(3))
        gy.record("writer", "death", cause="sweep", ts=_today(4))
        gy.record("writer", "restart", gap_seconds=500, ts=_today(4))
        s = gy.summary("writer")
        assert s["total_deaths"] == 2
        assert s["total_restarts"] == 2
        assert s["deaths_today"] == 2
        assert s["mean_gap_seconds"] == 400.0
        assert s["cause_breakdown"] == {"sweep": 2}

    def test_summary_all(self, gy: Graveyard) -> None:
        gy.record("writer", "death")
        gy.record("batch", "death")
        s = gy.summary()
        assert s["process"] == "all"
        assert s["total_deaths"] == 2


# -- load/reload -------------------------------------------------------------


class TestPersistence:
    def test_load_from_existing(self, gy_path: Path) -> None:
        gy_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": "2026-10-20T03:00:00+08:00", "process": "writer",
                 "event": "death", "pid": 100, "cause": "test",
                 "gap_seconds": None}
        gy_path.write_text(json.dumps(entry) + "\n")
        gy = Graveyard(gy_path)
        assert len(gy.entries) == 1
        assert gy.entries[0]["process"] == "writer"

    def test_load_skips_bad_lines(self, gy_path: Path) -> None:
        gy_path.parent.mkdir(parents=True, exist_ok=True)
        gy_path.write_text("not json\n" + json.dumps({"ts": "2026-10-20T03:00:00+08:00",
                           "process": "w", "event": "death", "pid": None,
                           "cause": None, "gap_seconds": None}) + "\n")
        gy = Graveyard(gy_path)
        assert len(gy.entries) == 1

    def test_record_then_reload(self, gy: Graveyard, gy_path: Path) -> None:
        gy.record("writer", "death", cause="sweep")
        gy.record("writer", "restart", pid=200)
        gy2 = Graveyard(gy_path)
        gy2.load()
        assert len(gy2.entries) == 2
