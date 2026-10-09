"""Tests for iamai.restart_warmup — cold-start latency tracker."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.restart_warmup import (
    LEDGER,
    SLOW_THRESHOLD_SEC,
    ledger_path,
    read_events,
    record_first_stroke,
    record_restart,
    warmup_report,
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
# record_restart
# ---------------------------------------------------------------------------


class TestRecordRestart:
    def test_creates_ledger_file(self, repo: Path):
        ts = datetime(2026, 10, 9, 7, 0, 0, tzinfo=timezone.utc)
        record = record_restart(repo, writer="qwen", pid=1411, ts=ts)
        path = ledger_path(repo)
        assert path.exists()
        assert record["ts"] == ts.isoformat()
        assert record["writer"] == "qwen"
        assert record["event"] == "restart"
        assert record["pid"] == 1411
        assert record["stroke_seq"] is None

    def test_appends_multiple(self, repo: Path):
        ts1 = datetime(2026, 10, 9, 7, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 10, 9, 8, 0, 0, tzinfo=timezone.utc)
        record_restart(repo, writer="qwen", pid=100, ts=ts1)
        record_restart(repo, writer="qwen", pid=200, ts=ts2)
        events = read_events(repo)
        assert len(events) == 2
        assert events[0]["pid"] == 100
        assert events[1]["pid"] == 200

    def test_pid_optional(self, repo: Path):
        ts = datetime(2026, 10, 9, 7, 0, 0, tzinfo=timezone.utc)
        record = record_restart(repo, writer="qwen", ts=ts)
        assert record["pid"] is None

    def test_ts_defaults_to_now(self, repo: Path):
        record = record_restart(repo, writer="qwen")
        ts = datetime.fromisoformat(record["ts"])
        # Should be within last minute
        assert (datetime.now(timezone.utc) - ts).total_seconds() < 60


# ---------------------------------------------------------------------------
# record_first_stroke
# ---------------------------------------------------------------------------


class TestRecordFirstStroke:
    def test_basic(self, repo: Path):
        ts = datetime(2026, 10, 9, 7, 0, 15, tzinfo=timezone.utc)
        record = record_first_stroke(repo, writer="qwen", pid=1411, stroke_seq=12468, ts=ts)
        assert record["event"] == "first_stroke"
        assert record["stroke_seq"] == 12468
        assert record["pid"] == 1411

    def test_stroke_seq_optional(self, repo: Path):
        ts = datetime(2026, 10, 9, 7, 0, 15, tzinfo=timezone.utc)
        record = record_first_stroke(repo, writer="qwen", ts=ts)
        assert record["stroke_seq"] is None


# ---------------------------------------------------------------------------
# read_events
# ---------------------------------------------------------------------------


class TestReadEvents:
    def test_empty_repo(self, repo: Path):
        assert read_events(repo) == []

    def test_filter_by_writer(self, repo: Path):
        ts = datetime(2026, 10, 9, 7, 0, 0, tzinfo=timezone.utc)
        record_restart(repo, writer="qwen", ts=ts)
        record_restart(repo, writer="doubao", ts=ts)
        record_restart(repo, writer="qwen", ts=ts)

        qwen_events = read_events(repo, writer="qwen")
        assert len(qwen_events) == 2

        doubao_events = read_events(repo, writer="doubao")
        assert len(doubao_events) == 1

        all_events = read_events(repo)
        assert len(all_events) == 3

    def test_ignores_malformed_lines(self, repo: Path):
        path = ledger_path(repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"event":"restart","writer":"qwen","ts":"x","pid":null,"stroke_seq":null}\n'
                        'not json\n'
                        '{"event":"restart","writer":"qwen","ts":"y","pid":null,"stroke_seq":null}\n')
        events = read_events(repo)
        assert len(events) == 2


# ---------------------------------------------------------------------------
# warmup_report — pairing logic
# ---------------------------------------------------------------------------


class TestWarmupReport:
    def test_empty_repo(self, repo: Path):
        report = warmup_report(repo)
        assert report["pairs"] == 0
        assert report["mean_seconds"] == 0.0
        assert report["last_latency_sec"] is None

    def test_single_pair(self, repo: Path):
        t0 = datetime(2026, 10, 9, 7, 0, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(seconds=8)
        record_restart(repo, writer="qwen", pid=100, ts=t0)
        record_first_stroke(repo, writer="qwen", pid=100, stroke_seq=1, ts=t1)

        report = warmup_report(repo, writer="qwen")
        assert report["pairs"] == 1
        assert report["mean_seconds"] == 8.0
        assert report["max_seconds"] == 8.0
        assert report["last_latency_sec"] == 8.0
        assert report["slow_count"] == 0

    def test_multiple_pairs(self, repo: Path):
        base = datetime(2026, 10, 9, 7, 0, 0, tzinfo=timezone.utc)
        # pair 1: 5s
        record_restart(repo, writer="qwen", ts=base)
        record_first_stroke(repo, writer="qwen", ts=base + timedelta(seconds=5))
        # pair 2: 10s
        record_restart(repo, writer="qwen", ts=base + timedelta(minutes=10))
        record_first_stroke(repo, writer="qwen", ts=base + timedelta(minutes=10, seconds=10))
        # pair 3: 90s (slow)
        record_restart(repo, writer="qwen", ts=base + timedelta(minutes=20))
        record_first_stroke(repo, writer="qwen", ts=base + timedelta(minutes=21, seconds=30))

        report = warmup_report(repo, writer="qwen")
        assert report["pairs"] == 3
        assert report["slow_count"] == 1  # 90s > 60s threshold
        assert report["max_seconds"] == 90.0
        assert report["mean_seconds"] == round((5 + 10 + 90) / 3, 2)

    def test_unmatched_restart_not_counted(self, repo: Path):
        """A restart with no following first_stroke should not appear in stats."""
        t0 = datetime(2026, 10, 9, 7, 0, 0, tzinfo=timezone.utc)
        record_restart(repo, writer="qwen", ts=t0)
        record_restart(repo, writer="qwen", ts=t0 + timedelta(minutes=5))
        # Only the second restart gets a first_stroke
        record_first_stroke(repo, writer="qwen", ts=t0 + timedelta(minutes=5, seconds=12))

        report = warmup_report(repo, writer="qwen")
        # The first restart was overwritten by the second; only one pair
        assert report["pairs"] == 1
        assert report["mean_seconds"] == 12.0

    def test_orphan_first_stroke_ignored(self, repo: Path):
        """A first_stroke without a preceding restart is ignored."""
        t0 = datetime(2026, 10, 9, 7, 0, 0, tzinfo=timezone.utc)
        record_first_stroke(repo, writer="qwen", ts=t0)  # orphan
        record_restart(repo, writer="qwen", ts=t0 + timedelta(minutes=1))
        record_first_stroke(repo, writer="qwen", ts=t0 + timedelta(minutes=1, seconds=7))

        report = warmup_report(repo, writer="qwen")
        assert report["pairs"] == 1
        assert report["mean_seconds"] == 7.0

    def test_negative_latency_clamped_to_zero(self, repo: Path):
        """Clock skew could produce negative delta; we clamp to 0."""
        t0 = datetime(2026, 10, 9, 7, 0, 0, tzinfo=timezone.utc)
        record_restart(repo, writer="qwen", ts=t0)
        record_first_stroke(repo, writer="qwen", ts=t0 - timedelta(seconds=5))

        report = warmup_report(repo, writer="qwen")
        assert report["pairs"] == 1
        assert report["mean_seconds"] == 0.0

    def test_writer_filter(self, repo: Path):
        t0 = datetime(2026, 10, 9, 7, 0, 0, tzinfo=timezone.utc)
        record_restart(repo, writer="qwen", ts=t0)
        record_first_stroke(repo, writer="qwen", ts=t0 + timedelta(seconds=5))
        record_restart(repo, writer="doubao", ts=t0)
        record_first_stroke(repo, writer="doubao", ts=t0 + timedelta(seconds=20))

        qwen_report = warmup_report(repo, writer="qwen")
        assert qwen_report["pairs"] == 1
        assert qwen_report["mean_seconds"] == 5.0

        doubao_report = warmup_report(repo, writer="doubao")
        assert doubao_report["pairs"] == 1
        assert doubao_report["mean_seconds"] == 20.0

    def test_p95(self, repo: Path):
        """With 20 pairs, p95 should be the 19th value (0-indexed: index 18)."""
        base = datetime(2026, 10, 9, 7, 0, 0, tzinfo=timezone.utc)
        for i in range(20):
            latency = (i + 1) * 2  # 2, 4, 6, ..., 40
            record_restart(repo, writer="qwen", ts=base + timedelta(hours=i))
            record_first_stroke(repo, writer="qwen", ts=base + timedelta(hours=i, seconds=latency))

        report = warmup_report(repo, writer="qwen")
        assert report["pairs"] == 20
        # p95 index = int(20 * 95 / 100) = 19 -> value = 40
        assert report["p95_seconds"] == 40.0

    def test_slow_threshold_constant(self):
        assert SLOW_THRESHOLD_SEC == 60.0
