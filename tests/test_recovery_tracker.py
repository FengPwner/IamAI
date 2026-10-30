"""Tests for iamai.recovery_tracker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iamai.recovery_tracker import (
    load_events,
    record_event,
    recovery_stats,
)


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    return tmp_path / "recovery.jsonl"


def test_record_event_creates_file(log_path: Path):
    """record_event should create the JSONL file and write one line."""
    event = record_event(
        log_path,
        detected_at="2026-10-06T04:00:00+08:00",
        restarted_at="2026-10-06T04:00:30+08:00",
        pushed_at="2026-10-06T04:01:00+08:00",
        uncommitted_files=10,
        notes="push rejected, rebase needed",
    )
    assert event["uncommitted_files"] == 10
    assert log_path.exists()

    lines = log_path.read_text().strip().split("\n")
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["notes"] == "push rejected, rebase needed"


def test_record_event_appends(log_path: Path):
    """Multiple record_event calls should append, not overwrite."""
    for i in range(3):
        record_event(
            log_path,
            detected_at=f"2026-10-06T04:0{i}:00+08:00",
            restarted_at=f"2026-10-06T04:0{i}:30+08:00",
            pushed_at=f"2026-10-06T04:0{i}:59+08:00",
        )

    events = load_events(log_path)
    assert len(events) == 3


def test_load_events_missing_file(tmp_path: Path):
    """load_events on a nonexistent file should return empty list."""
    assert load_events(tmp_path / "nope.jsonl") == []


def test_recovery_stats_empty(log_path: Path):
    """Stats on no events should return all zeros."""
    stats = recovery_stats(log_path)
    assert stats["count"] == 0
    assert stats["avg_total_seconds"] == 0.0


def test_recovery_stats_single_event(log_path: Path):
    """Single event: averages equal that event's values."""
    record_event(
        log_path,
        detected_at="2026-10-06T04:00:00+08:00",
        restarted_at="2026-10-06T04:00:20+08:00",
        pushed_at="2026-10-06T04:01:00+08:00",
    )

    stats = recovery_stats(log_path)
    assert stats["count"] == 1
    assert stats["avg_restart_seconds"] == 20.0
    assert stats["avg_push_seconds"] == 40.0
    assert stats["avg_total_seconds"] == 60.0
    assert stats["max_total_seconds"] == 60.0


def test_recovery_stats_multiple_events(log_path: Path):
    """Multiple events: verify averages and max."""
    # Event 1: 30s restart + 30s push = 60s total
    record_event(
        log_path,
        detected_at="2026-10-06T04:00:00+08:00",
        restarted_at="2026-10-06T04:00:30+08:00",
        pushed_at="2026-10-06T04:01:00+08:00",
    )
    # Event 2: 60s restart + 60s push = 120s total
    record_event(
        log_path,
        detected_at="2026-10-06T05:00:00+08:00",
        restarted_at="2026-10-06T05:01:00+08:00",
        pushed_at="2026-10-06T05:02:00+08:00",
    )

    stats = recovery_stats(log_path)
    assert stats["count"] == 2
    assert stats["avg_restart_seconds"] == 45.0   # (30+60)/2
    assert stats["avg_push_seconds"] == 45.0       # (30+60)/2
    assert stats["avg_total_seconds"] == 90.0      # (60+120)/2
    assert stats["max_total_seconds"] == 120.0
