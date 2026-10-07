"""Tests for iamai.process_mortality — process death/restart ledger."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.process_mortality import (
    LEDGER,
    ledger_path,
    mortality_report,
    read_events,
    record_event,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return tmp_path


# ---------------------------------------------------------------------------
# ledger_path
# ---------------------------------------------------------------------------


class TestLedgerPath:
    def test_returns_correct_path(self, repo: Path):
        assert ledger_path(repo) == repo / LEDGER

    def test_string_input(self, repo: Path):
        assert ledger_path(str(repo)) == repo / LEDGER


# ---------------------------------------------------------------------------
# record_event
# ---------------------------------------------------------------------------


class TestRecordEvent:
    def test_creates_ledger_file(self, repo: Path):
        ts = datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc)
        record = record_event(repo, writer="qwen", event="restart", pid=1355, ts=ts)
        path = ledger_path(repo)
        assert path.exists()
        assert record["ts"] == ts.isoformat()
        assert record["writer"] == "qwen"
        assert record["event"] == "restart"
        assert record["pid"] == 1355

    def test_first_event_gap_is_none(self, repo: Path):
        ts = datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc)
        record = record_event(repo, writer="qwen", event="restart", ts=ts)
        assert record["gap_sec"] is None

    def test_second_event_has_gap(self, repo: Path):
        t1 = datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 8, 0, 10, 0, tzinfo=timezone.utc)
        record_event(repo, writer="qwen", event="death", pid=1300, ts=t1)
        r2 = record_event(repo, writer="qwen", event="restart", pid=1355, ts=t2)
        assert r2["gap_sec"] == 600.0

    def test_appends_to_existing(self, repo: Path):
        t1 = datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 8, 0, 5, 0, tzinfo=timezone.utc)
        record_event(repo, writer="qwen", event="death", ts=t1)
        record_event(repo, writer="qwen", event="restart", ts=t2)
        lines = ledger_path(repo).read_text().strip().split("\n")
        assert len(lines) == 2

    def test_pid_can_be_none(self, repo: Path):
        ts = datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc)
        record = record_event(repo, writer="qwen", event="death", pid=None, ts=ts)
        assert record["pid"] is None

    def test_creates_parent_dirs(self, tmp_path: Path):
        deep = tmp_path / "a" / "b" / "c"
        ts = datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc)
        record_event(deep, writer="qwen", event="restart", ts=ts)
        assert (deep / LEDGER).exists()


# ---------------------------------------------------------------------------
# read_events
# ---------------------------------------------------------------------------


class TestReadEvents:
    def test_empty_repo(self, repo: Path):
        assert read_events(repo) == []

    def test_reads_all_events(self, repo: Path):
        t1 = datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 8, 0, 5, 0, tzinfo=timezone.utc)
        record_event(repo, writer="qwen", event="death", ts=t1)
        record_event(repo, writer="qwen", event="restart", ts=t2)
        events = read_events(repo)
        assert len(events) == 2

    def test_filters_by_writer(self, repo: Path):
        t1 = datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 8, 0, 5, 0, tzinfo=timezone.utc)
        record_event(repo, writer="qwen", event="death", ts=t1)
        record_event(repo, writer="guoban", event="death", ts=t2)
        events = read_events(repo, writer="qwen")
        assert len(events) == 1
        assert events[0]["writer"] == "qwen"

    def test_handles_malformed_lines(self, repo: Path):
        path = ledger_path(repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json\n" + json.dumps({
            "ts": "2026-10-08T00:00:00+00:00",
            "writer": "qwen",
            "event": "restart",
            "pid": 1,
            "gap_sec": None
        }) + "\n")
        events = read_events(repo)
        assert len(events) == 1


# ---------------------------------------------------------------------------
# mortality_report
# ---------------------------------------------------------------------------


class TestMortalityReport:
    def _seed(self, repo: Path, events: list[tuple[str, str, int]]):
        """Helper: seed events as (event_type, minutes_offset, pid)."""
        base = datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc)
        for event_type, minutes, pid in events:
            ts = base + timedelta(minutes=minutes)
            record_event(repo, writer="qwen", event=event_type, pid=pid, ts=ts)

    def test_empty_report(self, repo: Path):
        report = mortality_report(repo, writer="qwen")
        assert report["total_events"] == 0
        assert report["deaths"] == 0
        assert report["restarts"] == 0
        assert report["uptime_pct"] == 100.0
        assert report["mtbf_minutes"] is None

    def test_single_death_restart(self, repo: Path):
        self._seed(repo, [
            ("death", 0, 1300),
            ("restart", 50, 1355),
        ])
        now = datetime(2026, 10, 8, 1, 0, 0, tzinfo=timezone.utc)
        report = mortality_report(repo, writer="qwen", now=now, window_hours=2)
        assert report["deaths"] == 1
        assert report["restarts"] == 1
        assert report["total_events"] == 2
        # 50 min downtime in a 120-min window = ~58% uptime
        assert report["uptime_pct"] == pytest.approx(58.3, abs=1.0)
        assert report["avg_downtime_minutes"] == pytest.approx(50.0)

    def test_multiple_deaths_mtbf(self, repo: Path):
        self._seed(repo, [
            ("death", 0, 100),
            ("restart", 10, 101),
            ("death", 90, 101),
            ("restart", 100, 102),
            ("death", 180, 102),
            ("restart", 190, 103),
        ])
        now = datetime(2026, 10, 8, 4, 0, 0, tzinfo=timezone.utc)
        report = mortality_report(repo, writer="qwen", now=now, window_hours=5)
        assert report["deaths"] == 3
        assert report["restarts"] == 3
        # MTBF: gaps between deaths are 90min and 90min → average 90
        assert report["mtbf_minutes"] == pytest.approx(90.0)
        # window_hours=5 < 24 → deaths_24h is None
        assert report["deaths_24h"] is None

    def test_deaths_24h_limited(self, repo: Path):
        self._seed(repo, [
            ("death", 0, 100),
            ("restart", 10, 101),
            ("death", 90, 101),
            ("restart", 100, 102),
        ])
        # Set now so that only the second death is within 24h
        # (both are within 2h, so this is a contrived test)
        now = datetime(2026, 10, 8, 2, 0, 0, tzinfo=timezone.utc)
        report = mortality_report(repo, writer="qwen", now=now, window_hours=24)
        assert report["deaths_24h"] == 2

    def test_uptime_bounded(self, repo: Path):
        # More downtime than window → uptime clamped to 0
        self._seed(repo, [
            ("death", 0, 100),
            ("restart", 200, 101),
        ])
        now = datetime(2026, 10, 8, 2, 0, 0, tzinfo=timezone.utc)
        report = mortality_report(repo, writer="qwen", now=now, window_hours=2)
        assert report["uptime_pct"] == 0.0

    def test_no_deaths_full_uptime(self, repo: Path):
        self._seed(repo, [
            ("restart", 0, 100),
            ("restart", 60, 101),
        ])
        now = datetime(2026, 10, 8, 2, 0, 0, tzinfo=timezone.utc)
        report = mortality_report(repo, writer="qwen", now=now, window_hours=2)
        assert report["uptime_pct"] == 100.0
        assert report["avg_downtime_minutes"] is None

    def test_deaths_24h_none_when_small_window(self, repo: Path):
        self._seed(repo, [("death", 0, 100)])
        now = datetime(2026, 10, 8, 1, 0, 0, tzinfo=timezone.utc)
        report = mortality_report(repo, writer="qwen", now=now, window_hours=12)
        assert report["deaths_24h"] is None

    def test_report_details_keys(self, repo: Path):
        now = datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc)
        report = mortality_report(repo, writer="qwen", now=now)
        expected_keys = {
            "total_events", "deaths", "restarts", "deaths_24h",
            "mtbf_minutes", "uptime_pct", "avg_downtime_minutes",
        }
        assert set(report.keys()) == expected_keys

    def test_writer_filter_isolation(self, repo: Path):
        base = datetime(2026, 10, 8, 0, 0, 0, tzinfo=timezone.utc)
        record_event(repo, writer="qwen", event="death", pid=1, ts=base)
        record_event(repo, writer="guoban", event="death", pid=2, ts=base)
        record_event(repo, writer="guoban", event="death", pid=3,
                     ts=base + timedelta(minutes=30))

        now = base + timedelta(hours=1)
        qwen_report = mortality_report(repo, writer="qwen", now=now, window_hours=2)
        guoban_report = mortality_report(repo, writer="guoban", now=now, window_hours=2)

        assert qwen_report["deaths"] == 1
        assert guoban_report["deaths"] == 2
