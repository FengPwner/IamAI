#!/usr/bin/env python3
"""Tests for tools/writer_recovery_monitor.py — writer restart recovery monitor."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from writer_recovery_monitor import (
    RecoveryEvent,
    RecoveryReport,
    analyze,
    classify_recovery,
    compute_cadence,
    find_restart_gaps,
    load_history,
    parse_iso,
    state_path,
    as_markdown,
    DEFAULT_TOLERANCE,
)


# ── Fixtures ──


def _ts(base: datetime, offset_seconds: float) -> str:
    """Build an ISO timestamp offset from a base datetime."""
    return (base + timedelta(seconds=offset_seconds)).isoformat()


def _make_history(base: datetime, cadence: float, count: int,
                  gap_at: int | None = None, gap_seconds: float = 0,
                  post_cadence: float | None = None) -> list[dict]:
    """Build a synthetic stroke history with an optional gap.

    Args:
        base: start time
        cadence: seconds between strokes before the gap
        count: total stroke count
        gap_at: index where the gap is inserted (None = no gap)
        gap_seconds: duration of the gap
        post_cadence: cadence after the gap (defaults to same as pre)
    """
    pc = post_cadence if post_cadence is not None else cadence
    history = []
    offset = 0.0
    kinds = ["note", "snippet", "thought", "devlog", "garden", "metrics"]

    for i in range(count):
        if gap_at is not None and i == gap_at:
            offset += gap_seconds
        cad = pc if (gap_at is not None and i >= gap_at) else cadence
        history.append({
            "seq": i + 1,
            "at": _ts(base, offset),
            "kind": kinds[i % len(kinds)],
        })
        offset += cad

    return history


@pytest.fixture
def base_time() -> datetime:
    return datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def healthy_history(base_time: datetime) -> list[dict]:
    """100 strokes at 15s cadence, no gaps."""
    return _make_history(base_time, cadence=15, count=100)


@pytest.fixture
def restarted_history(base_time: datetime) -> list[dict]:
    """100 strokes with a 1-hour gap at index 50, full recovery."""
    return _make_history(
        base_time, cadence=15, count=100,
        gap_at=50, gap_seconds=3600, post_cadence=15,
    )


@pytest.fixture
def degraded_history(base_time: datetime) -> list[dict]:
    """100 strokes with a 1-hour gap at index 50, 3× slower after."""
    return _make_history(
        base_time, cadence=15, count=100,
        gap_at=50, gap_seconds=3600, post_cadence=45,
    )


@pytest.fixture
def failed_history(base_time: datetime) -> list[dict]:
    """100 strokes with a 1-hour gap at index 50, nearly dead after."""
    return _make_history(
        base_time, cadence=15, count=100,
        gap_at=50, gap_seconds=3600, post_cadence=600,
    )


@pytest.fixture
def tmp_state(tmp_path: Path):
    """Redirect state_path to a temporary location."""
    def _path(writer_id: str) -> Path:
        return tmp_path / f"writer_state.{writer_id}.json"
    with patch("writer_recovery_monitor.state_path", _path):
        yield tmp_path, _path


# ── parse_iso ──


class TestParseIso:
    def test_z_suffix(self) -> None:
        ts = "2026-10-09T12:00:00Z"
        result = parse_iso(ts)
        assert isinstance(result, float)
        assert result > 0

    def test_offset_suffix(self) -> None:
        ts = "2026-10-09T12:00:00+00:00"
        result = parse_iso(ts)
        assert isinstance(result, float)

    def test_naive_timestamp(self) -> None:
        ts = "2026-10-09T12:00:00"
        result = parse_iso(ts)
        assert isinstance(result, float)

    def test_consistent_across_formats(self) -> None:
        z = parse_iso("2026-10-09T12:00:00Z")
        off = parse_iso("2026-10-09T12:00:00+00:00")
        naive = parse_iso("2026-10-09T12:00:00")
        assert abs(z - off) < 1
        assert abs(z - naive) < 1

    def test_whitespace_stripped(self) -> None:
        result = parse_iso("  2026-10-09T12:00:00Z  ")
        assert isinstance(result, float)


# ── compute_cadence ──


class TestComputeCadence:
    def test_before_direction(self, healthy_history: list[dict]) -> None:
        cad, n = compute_cadence(healthy_history, 50, "before", 20)
        assert cad is not None
        assert abs(cad - 15.0) < 1.0
        # n = intervals (strokes - 1)
        assert n == 19

    def test_after_direction(self, healthy_history: list[dict]) -> None:
        cad, n = compute_cadence(healthy_history, 50, "after", 20)
        assert cad is not None
        assert abs(cad - 15.0) < 1.0

    def test_insufficient_data_before(self, healthy_history: list[dict]) -> None:
        cad, n = compute_cadence(healthy_history, 0, "before", 20)
        # index 0 has nothing before it
        assert cad is None
        assert n <= 1

    def test_insufficient_data_after(self, healthy_history: list[dict]) -> None:
        cad, n = compute_cadence(healthy_history, len(healthy_history) - 1, "after", 20)
        assert cad is None

    def test_small_sample(self, healthy_history: list[dict]) -> None:
        cad, n = compute_cadence(healthy_history, 10, "before", 5)
        assert cad is not None
        assert n == 4  # 5 strokes sampled = 4 intervals

    def test_sample_larger_than_available(self) -> None:
        history = [
            {"seq": 1, "at": "2026-10-09T12:00:00Z", "kind": "note"},
            {"seq": 2, "at": "2026-10-09T12:00:15Z", "kind": "note"},
            {"seq": 3, "at": "2026-10-09T12:00:30Z", "kind": "note"},
        ]
        cad, n = compute_cadence(history, 2, "before", 100)
        assert cad is not None
        assert abs(cad - 15.0) < 1.0


# ── find_restart_gaps ──


class TestFindRestartGaps:
    def test_no_gaps(self, healthy_history: list[dict]) -> None:
        gaps = find_restart_gaps(healthy_history, gap_threshold=150)
        assert gaps == []

    def test_single_gap(self, restarted_history: list[dict]) -> None:
        gaps = find_restart_gaps(restarted_history, gap_threshold=150)
        assert len(gaps) == 1
        assert gaps[0] == 50

    def test_multiple_gaps(self, base_time: datetime) -> None:
        # Build history with 2 gaps
        h = _make_history(base_time, 15, 40, gap_at=20, gap_seconds=600)
        # Add a second gap manually
        offset = parse_iso(h[-1]["at"]) - parse_iso(h[0]["at"]) + 600
        for i in range(40, 80):
            h.append({
                "seq": i + 1,
                "at": _ts(base_time, offset + (i - 40) * 15),
                "kind": "note",
            })
        gaps = find_restart_gaps(h, gap_threshold=150)
        assert len(gaps) >= 1

    def test_threshold_sensitivity(self, restarted_history: list[dict]) -> None:
        # Very high threshold should miss the gap
        gaps_high = find_restart_gaps(restarted_history, gap_threshold=999999)
        assert gaps_high == []
        # Very low threshold should catch everything
        gaps_low = find_restart_gaps(restarted_history, gap_threshold=1)
        assert len(gaps_low) >= 1

    def test_empty_history(self) -> None:
        gaps = find_restart_gaps([], gap_threshold=150)
        assert gaps == []

    def test_single_stroke(self) -> None:
        h = [{"seq": 1, "at": "2026-10-09T12:00:00Z", "kind": "note"}]
        gaps = find_restart_gaps(h, gap_threshold=150)
        assert gaps == []


# ── classify_recovery ──


class TestClassifyRecovery:
    def test_perfect_recovery(self) -> None:
        assert classify_recovery(15.0, 15.0, DEFAULT_TOLERANCE) == "recovered"

    def test_close_to_perfect(self) -> None:
        assert classify_recovery(15.0, 16.0, DEFAULT_TOLERANCE) == "recovered"

    def test_degraded(self) -> None:
        assert classify_recovery(15.0, 30.0, DEFAULT_TOLERANCE) == "degraded"

    def test_failed_no_post(self) -> None:
        assert classify_recovery(15.0, None, DEFAULT_TOLERANCE) == "failed"

    def test_failed_zero_post(self) -> None:
        assert classify_recovery(15.0, 0.0, DEFAULT_TOLERANCE) == "failed"

    def test_failed_extremely_slow(self) -> None:
        # ratio = 15/600 = 0.025 < DEGRADED_FLOOR (0.10)
        assert classify_recovery(15.0, 600.0, DEFAULT_TOLERANCE) == "failed"

    def test_no_pre_data_reasonable_post(self) -> None:
        assert classify_recovery(None, 15.0, DEFAULT_TOLERANCE) == "recovered"

    def test_no_pre_data_slow_post(self) -> None:
        assert classify_recovery(None, 200.0, DEFAULT_TOLERANCE) == "degraded"

    def test_tolerance_boundary(self) -> None:
        # ratio = 15/22 ≈ 0.682 < 0.70 (1 - 0.30) → degraded
        assert classify_recovery(15.0, 22.0, 0.30) == "degraded"
        # ratio = 15/21 ≈ 0.714 > 0.69 (1 - 0.31) → recovered
        assert classify_recovery(15.0, 21.0, 0.31) == "recovered"


# ── analyze ──


class TestAnalyze:
    def test_healthy_writer(self, healthy_history: list[dict], tmp_state) -> None:
        tmp_path, sp = tmp_state
        state_file = sp("qwen")
        state_file.write_text(json.dumps({"history": healthy_history}))
        report = analyze(writer_id="qwen")
        assert report.total_strokes == 100
        assert report.restarts_found == 0
        assert report.overall_status == "healthy"

    def test_restarted_writer(self, restarted_history: list[dict], tmp_state) -> None:
        tmp_path, sp = tmp_state
        state_file = sp("qwen")
        state_file.write_text(json.dumps({"history": restarted_history}))
        report = analyze(writer_id="qwen")
        assert report.restarts_found == 1
        assert len(report.events) == 1
        ev = report.events[0]
        assert ev.status == "recovered"
        assert ev.gap_seconds > 3000  # ~3600s

    def test_degraded_writer(self, degraded_history: list[dict], tmp_state) -> None:
        tmp_path, sp = tmp_state
        state_file = sp("qwen")
        state_file.write_text(json.dumps({"history": degraded_history}))
        report = analyze(writer_id="qwen")
        assert report.restarts_found == 1
        ev = report.events[0]
        assert ev.status == "degraded"
        assert ev.post_cadence > ev.pre_cadence

    def test_failed_writer(self, failed_history: list[dict], tmp_state) -> None:
        tmp_path, sp = tmp_state
        state_file = sp("qwen")
        state_file.write_text(json.dumps({"history": failed_history}))
        # gap_threshold=700 avoids counting slow post-cadence (600s) strokes as restarts
        report = analyze(writer_id="qwen", gap_threshold=700)
        assert report.restarts_found == 1
        ev = report.events[0]
        assert ev.status == "failed"

    def test_missing_state_file(self, tmp_state) -> None:
        report = analyze(writer_id="nonexistent")
        assert report.total_strokes == 0
        assert report.overall_status == "unknown"

    def test_empty_history(self, tmp_state) -> None:
        tmp_path, sp = tmp_state
        state_file = sp("qwen")
        state_file.write_text(json.dumps({"history": []}))
        report = analyze(writer_id="qwen")
        assert report.total_strokes == 0
        assert report.overall_status == "insufficient_data"

    def test_single_stroke(self, tmp_state) -> None:
        tmp_path, sp = tmp_state
        state_file = sp("qwen")
        state_file.write_text(json.dumps({
            "history": [{"seq": 1, "at": "2026-10-09T12:00:00Z", "kind": "note"}]
        }))
        report = analyze(writer_id="qwen")
        assert report.total_strokes == 1
        assert report.restarts_found == 0

    def test_overall_status_worst_wins(self, base_time: datetime, tmp_state) -> None:
        """Two restarts: one recovered, one degraded → overall degraded."""
        tmp_path, sp = tmp_state
        # Build history: healthy → gap → healthy → gap → degraded
        h = _make_history(base_time, 15, 30, gap_at=15, gap_seconds=600)
        offset = parse_iso(h[-1]["at"]) - parse_iso(h[0]["at"])
        for i in range(30, 60):
            h.append({
                "seq": i + 1,
                "at": _ts(base_time, offset + (i - 30) * 15),
                "kind": "note",
            })
        offset2 = parse_iso(h[-1]["at"]) - parse_iso(h[0]["at"]) + 600
        for i in range(60, 90):
            h.append({
                "seq": i + 1,
                "at": _ts(base_time, offset2 + (i - 60) * 45),  # 3× slower
                "kind": "note",
            })
        state_file = sp("qwen")
        state_file.write_text(json.dumps({"history": h}))
        report = analyze(writer_id="qwen", gap_threshold=150)
        assert report.restarts_found == 2
        assert report.overall_status == "degraded"

    def test_custom_gap_threshold(self, restarted_history: list[dict], tmp_state) -> None:
        tmp_path, sp = tmp_state
        state_file = sp("qwen")
        state_file.write_text(json.dumps({"history": restarted_history}))
        # Threshold higher than the gap → no restarts found
        report = analyze(writer_id="qwen", gap_threshold=999999)
        assert report.restarts_found == 0

    def test_invalid_json(self, tmp_state) -> None:
        tmp_path, sp = tmp_state
        state_file = sp("qwen")
        state_file.write_text("not json at all {{{")
        report = analyze(writer_id="qwen")
        assert report.overall_status == "unknown"

    def test_invalid_history_type(self, tmp_state) -> None:
        tmp_path, sp = tmp_state
        state_file = sp("qwen")
        state_file.write_text(json.dumps({"history": "not a list"}))
        report = analyze(writer_id="qwen")
        assert report.overall_status == "unknown"


# ── RecoveryEvent ──


class TestRecoveryEvent:
    def test_gap_human_seconds(self) -> None:
        ev = RecoveryEvent(
            gap_index=10, gap_start_iso="a", gap_end_iso="b",
            gap_seconds=45.0, pre_cadence=15.0, post_cadence=15.0,
            recovery_ratio=1.0, status="recovered",
            sample_pre=20, sample_post=20,
        )
        assert ev.gap_human == "45s"

    def test_gap_human_minutes(self) -> None:
        ev = RecoveryEvent(
            gap_index=10, gap_start_iso="a", gap_end_iso="b",
            gap_seconds=180.0, pre_cadence=15.0, post_cadence=15.0,
            recovery_ratio=1.0, status="recovered",
            sample_pre=20, sample_post=20,
        )
        assert ev.gap_human == "3.0m"

    def test_gap_human_hours(self) -> None:
        ev = RecoveryEvent(
            gap_index=10, gap_start_iso="a", gap_end_iso="b",
            gap_seconds=7200.0, pre_cadence=15.0, post_cadence=15.0,
            recovery_ratio=1.0, status="recovered",
            sample_pre=20, sample_post=20,
        )
        assert ev.gap_human == "2.0h"


# ── RecoveryReport ──


class TestRecoveryReport:
    def test_counts(self) -> None:
        events = [
            RecoveryEvent(0, "a", "b", 100, 15, 15, 1.0, "recovered", 20, 20),
            RecoveryEvent(1, "a", "b", 200, 15, 30, 0.5, "degraded", 20, 20),
            RecoveryEvent(2, "a", "b", 300, 15, None, None, "failed", 20, 20),
        ]
        report = RecoveryReport(
            writer_id="qwen", total_strokes=100,
            restarts_found=3, events=events,
        )
        assert report.recovered_count == 1
        assert report.degraded_count == 1
        assert report.failed_count == 1


# ── as_markdown ──


class TestAsMarkdown:
    def test_healthy_report(self) -> None:
        report = RecoveryReport(
            writer_id="qwen", total_strokes=100,
            restarts_found=0, overall_status="healthy",
        )
        md = as_markdown(report)
        assert "no restart gaps detected" in md
        assert "qwen" in md

    def test_report_with_events(self) -> None:
        events = [
            RecoveryEvent(50, "2026-10-09T12:00:00Z", "2026-10-09T13:00:00Z",
                          3600, 15.0, 15.5, 0.968, "recovered", 20, 20),
        ]
        report = RecoveryReport(
            writer_id="qwen", total_strokes=100,
            restarts_found=1, events=events, overall_status="recovered",
        )
        md = as_markdown(report)
        assert "restart 1" in md
        assert "1.0h" in md
        assert "recovered" in md
        assert "15.5" in md


# ── load_history ──


class TestLoadHistory:
    def test_load_valid(self, tmp_state) -> None:
        tmp_path, sp = tmp_state
        state_file = sp("qwen")
        data = {"history": [{"seq": 1, "at": "2026-10-09T12:00:00Z"}]}
        state_file.write_text(json.dumps(data))
        with patch("writer_recovery_monitor.state_path", sp):
            result = load_history("qwen")
        assert len(result) == 1

    def test_load_missing(self, tmp_state) -> None:
        tmp_path, sp = tmp_state
        with patch("writer_recovery_monitor.state_path", sp):
            with pytest.raises(FileNotFoundError):
                load_history("qwen")

    def test_load_invalid_json(self, tmp_state) -> None:
        tmp_path, sp = tmp_state
        state_file = sp("qwen")
        state_file.write_text("{broken json")
        with patch("writer_recovery_monitor.state_path", sp):
            with pytest.raises(json.JSONDecodeError):
                load_history("qwen")

    def test_load_non_list_history(self, tmp_state) -> None:
        tmp_path, sp = tmp_state
        state_file = sp("qwen")
        state_file.write_text(json.dumps({"history": "oops"}))
        with patch("writer_recovery_monitor.state_path", sp):
            with pytest.raises(ValueError):
                load_history("qwen")


# ── Integration ──


class TestIntegration:
    def test_full_cycle_healthy(self, tmp_state) -> None:
        """Write a clean history, run analyze, verify healthy."""
        tmp_path, sp = tmp_state
        base = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
        history = _make_history(base, 15, 50)
        state_file = sp("qwen")
        state_file.write_text(json.dumps({"history": history}))
        with patch("writer_recovery_monitor.state_path", sp):
            report = analyze(writer_id="qwen")
        assert report.total_strokes == 50
        assert report.restarts_found == 0
        assert report.overall_status == "healthy"

    def test_full_cycle_restart_and_recovery(self, tmp_state) -> None:
        """Write a history with a restart, verify recovery detected."""
        tmp_path, sp = tmp_state
        base = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
        history = _make_history(base, 15, 80, gap_at=40, gap_seconds=3600,
                                post_cadence=15)
        state_file = sp("qwen")
        state_file.write_text(json.dumps({"history": history}))
        with patch("writer_recovery_monitor.state_path", sp):
            report = analyze(writer_id="qwen")
        assert report.restarts_found == 1
        assert report.events[0].status == "recovered"

    def test_full_cycle_degraded(self, tmp_state) -> None:
        """Write a history with degraded recovery, verify detection."""
        tmp_path, sp = tmp_state
        base = datetime(2026, 10, 9, 12, 0, 0, tzinfo=timezone.utc)
        history = _make_history(base, 15, 80, gap_at=40, gap_seconds=3600,
                                post_cadence=30)  # 2× slower
        state_file = sp("qwen")
        state_file.write_text(json.dumps({"history": history}))
        with patch("writer_recovery_monitor.state_path", sp):
            report = analyze(writer_id="qwen")
        assert report.restarts_found == 1
        assert report.events[0].status == "degraded"
        assert report.overall_status == "degraded"
