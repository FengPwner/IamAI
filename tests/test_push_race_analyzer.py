#!/usr/bin/env python3
"""Tests for push_race_analyzer.py — push-race frequency and pattern analysis."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.push_race_analyzer import (
    hourly_heatmap,
    race_count,
    race_trend,
    resolution_breakdown,
)


def _write_races(log_path: Path, entries: list[dict]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _ts(hours_ago: float, base: datetime | None = None) -> str:
    if base is None:
        base = datetime.now(timezone.utc)
    return (base - timedelta(hours=hours_ago)).isoformat()


@pytest.fixture
def race_log(tmp_path):
    """Provide a repo-shaped tmp_path with an empty race log."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    log_path = data_dir / "push_races.jsonl"
    return tmp_path, log_path


# ---------------------------------------------------------------------------
# race_count
# ---------------------------------------------------------------------------

class TestRaceCount:
    def test_no_log_file(self, tmp_path):
        assert race_count(tmp_path, hours=24) == 0

    def test_empty_log(self, race_log):
        repo, log_path = race_log
        log_path.touch()
        assert race_count(repo, hours=24) == 0

    def test_counts_recent_races(self, race_log):
        repo, log_path = race_log
        _write_races(log_path, [
            {"at": _ts(1), "writer": "qwen", "resolution": "rebase"},
            {"at": _ts(5), "writer": "guoban", "resolution": "rebase"},
            {"at": _ts(12), "writer": "qwen", "resolution": "force"},
        ])
        assert race_count(repo, hours=24) == 3

    def test_excludes_old_races(self, race_log):
        repo, log_path = race_log
        _write_races(log_path, [
            {"at": _ts(2), "writer": "qwen", "resolution": "rebase"},
            {"at": _ts(48), "writer": "qwen", "resolution": "rebase"},
        ])
        assert race_count(repo, hours=24) == 1

    def test_filters_by_writer(self, race_log):
        repo, log_path = race_log
        _write_races(log_path, [
            {"at": _ts(1), "writer": "qwen", "resolution": "rebase"},
            {"at": _ts(2), "writer": "guoban", "resolution": "rebase"},
            {"at": _ts(3), "writer": "kimi", "resolution": "rebase"},
        ])
        assert race_count(repo, hours=24, writer="qwen") == 1
        assert race_count(repo, hours=24, writer="guoban") == 1
        assert race_count(repo, hours=24, writer="doubao") == 0

    def test_malformed_lines_skipped(self, race_log):
        repo, log_path = race_log
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            '{"at": "' + _ts(1) + '", "writer": "qwen", "resolution": "rebase"}\n'
            'not valid json\n'
            '\n'
            '{"at": "' + _ts(3) + '", "writer": "kimi", "resolution": "skip"}\n'
        )
        assert race_count(repo, hours=24) == 2


# ---------------------------------------------------------------------------
# race_trend
# ---------------------------------------------------------------------------

class TestRaceTrend:
    def test_no_data_returns_flat(self, tmp_path):
        assert race_trend(tmp_path, hours=168) == "flat"

    def test_single_race_returns_flat(self, race_log):
        repo, log_path = race_log
        _write_races(log_path, [
            {"at": _ts(10), "writer": "qwen", "resolution": "rebase"},
        ])
        assert race_trend(repo, hours=168) == "flat"

    def test_rising_trend(self, race_log):
        repo, log_path = race_log
        entries = []
        # Old period (days 5-7 ago): 1 race
        entries.append({"at": _ts(144), "writer": "qwen", "resolution": "rebase"})
        # Recent period (last 2 days): 10 races
        for i in range(10):
            entries.append({"at": _ts(i * 4 + 1), "writer": "qwen", "resolution": "rebase"})
        _write_races(log_path, entries)
        assert race_trend(repo, hours=168, bucket_hours=24) == "rising"

    def test_falling_trend(self, race_log):
        repo, log_path = race_log
        entries = []
        # Old period: 10 races spread across days 5-7
        for i in range(10):
            entries.append({"at": _ts(120 + i * 5), "writer": "qwen", "resolution": "rebase"})
        # Recent period: 1 race
        entries.append({"at": _ts(2), "writer": "qwen", "resolution": "rebase"})
        _write_races(log_path, entries)
        assert race_trend(repo, hours=168, bucket_hours=24) == "falling"

    def test_flat_trend(self, race_log):
        repo, log_path = race_log
        entries = []
        # Evenly distributed: 1 race per day for 7 days
        for i in range(7):
            entries.append({"at": _ts(i * 24 + 12), "writer": "qwen", "resolution": "rebase"})
        _write_races(log_path, entries)
        assert race_trend(repo, hours=168, bucket_hours=24) == "flat"


# ---------------------------------------------------------------------------
# hourly_heatmap
# ---------------------------------------------------------------------------

class TestHourlyHeatmap:
    def test_empty_returns_all_zeros(self, tmp_path):
        hm = hourly_heatmap(tmp_path, hours=168)
        assert len(hm) == 24
        assert all(v == 0 for v in hm.values())

    def test_counts_by_hour(self, race_log):
        repo, log_path = race_log
        # Create races at known hours
        base = datetime(2026, 10, 7, 0, 0, 0, tzinfo=timezone.utc)
        entries = [
            {"at": "2026-10-07T03:00:00+00:00", "writer": "qwen", "resolution": "rebase"},
            {"at": "2026-10-07T03:30:00+00:00", "writer": "qwen", "resolution": "rebase"},
            {"at": "2026-10-07T14:00:00+00:00", "writer": "guoban", "resolution": "rebase"},
            {"at": "2026-10-07T23:59:00+00:00", "writer": "kimi", "resolution": "skip"},
        ]
        _write_races(log_path, entries)
        hm = hourly_heatmap(repo, hours=168)
        assert hm[3] == 2
        assert hm[14] == 1
        assert hm[23] == 1
        assert hm[0] == 0
        assert len(hm) == 24


# ---------------------------------------------------------------------------
# resolution_breakdown
# ---------------------------------------------------------------------------

class TestResolutionBreakdown:
    def test_empty(self, tmp_path):
        assert resolution_breakdown(tmp_path) == {}

    def test_counts_resolutions(self, race_log):
        repo, log_path = race_log
        _write_races(log_path, [
            {"at": _ts(1), "writer": "qwen", "resolution": "rebase"},
            {"at": _ts(2), "writer": "qwen", "resolution": "rebase"},
            {"at": _ts(3), "writer": "guoban", "resolution": "force"},
            {"at": _ts(4), "writer": "kimi", "resolution": "skip"},
            {"at": _ts(5), "writer": "doubao", "resolution": "rebase"},
        ])
        bd = resolution_breakdown(repo, hours=24)
        assert bd["rebase"] == 3
        assert bd["force"] == 1
        assert bd["skip"] == 1

    def test_unknown_resolution(self, race_log):
        repo, log_path = race_log
        _write_races(log_path, [
            {"at": _ts(1), "writer": "qwen"},
        ])
        bd = resolution_breakdown(repo, hours=24)
        assert bd["unknown"] == 1
