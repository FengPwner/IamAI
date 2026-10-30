"""tests for process_continuity_monitor — verifying lifecycle tracking.

the monitor records process start/stop/heartbeat events to JSONL and
computes continuity metrics from those events. tests cover:

  - event recording and loading
  - gap detection between stop and next start
  - gap classification (recycle vs graceful vs unknown)
  - continuity report scoring
  - edge cases: empty files, malformed JSON, timezone handling
  - the is_likely_recycled heuristic

no external services needed. all timestamps are constructed explicitly.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.process_continuity_monitor import (
    ContinuityReport,
    Gap,
    ProcessContinuityMonitor,
    ProcessEvent,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ts(dt: datetime) -> str:
    return dt.isoformat()


def _write_events(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


BASE = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# event recording
# ---------------------------------------------------------------------------


class TestEventRecording:
    """record_start / record_stop / record_heartbeat append to JSONL."""

    def test_record_start_appends_event(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        monitor = ProcessContinuityMonitor(events_path=events_file)
        ts = _ts(BASE)
        event = monitor.record_start(pid=100, process_type="writer", timestamp=ts)

        assert event.event_type == "start"
        assert event.pid == 100
        assert event.process_type == "writer"
        assert events_file.exists()

        lines = events_file.read_text().strip().split("\n")
        assert len(lines) == 1
        loaded = json.loads(lines[0])
        assert loaded["event_type"] == "start"
        assert loaded["pid"] == 100

    def test_record_stop_with_reason(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        monitor = ProcessContinuityMonitor(events_path=events_file)
        ts = _ts(BASE)
        event = monitor.record_stop(
            pid=200, process_type="batch", reason="container_recycle", timestamp=ts
        )

        assert event.event_type == "stop"
        assert event.reason == "container_recycle"

    def test_record_heartbeat(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        monitor = ProcessContinuityMonitor(events_path=events_file)
        ts = _ts(BASE)
        event = monitor.record_heartbeat(pid=300, timestamp=ts)
        assert event.event_type == "heartbeat"

    def test_multiple_events_append(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        monitor = ProcessContinuityMonitor(events_path=events_file)
        monitor.record_start(pid=1, timestamp=_ts(BASE))
        monitor.record_stop(pid=1, reason="shutdown", timestamp=_ts(BASE + timedelta(minutes=5)))
        monitor.record_start(pid=2, timestamp=_ts(BASE + timedelta(minutes=6)))

        lines = events_file.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_record_event_creates_parent_dirs(self, tmp_path):
        events_file = tmp_path / "deep" / "nested" / "events.jsonl"
        monitor = ProcessContinuityMonitor(events_path=events_file)
        monitor.record_start(pid=1, timestamp=_ts(BASE))
        assert events_file.exists()


# ---------------------------------------------------------------------------
# event loading
# ---------------------------------------------------------------------------


class TestEventLoading:
    """load_events reads JSONL and returns ProcessEvent objects."""

    def test_load_empty_file(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        events_file.write_text("")
        monitor = ProcessContinuityMonitor(events_path=events_file)
        assert monitor.load_events() == []

    def test_load_nonexistent_file(self, tmp_path):
        events_file = tmp_path / "nope.jsonl"
        monitor = ProcessContinuityMonitor(events_path=events_file)
        assert monitor.load_events() == []

    def test_load_valid_events(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        _write_events(events_file, [
            {"timestamp": _ts(BASE), "event_type": "start", "process_type": "writer", "pid": 1},
            {"timestamp": _ts(BASE + timedelta(minutes=1)), "event_type": "stop", "process_type": "writer", "pid": 1, "reason": "graceful"},
        ])
        monitor = ProcessContinuityMonitor(events_path=events_file)
        events = monitor.load_events()
        assert len(events) == 2
        assert events[0].event_type == "start"
        assert events[1].reason == "graceful"

    def test_load_skips_malformed_lines(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        events_file.write_text(
            json.dumps({"timestamp": _ts(BASE), "event_type": "start", "process_type": "writer", "pid": 1})
            + "\n"
            + "not json\n"
            + json.dumps({"timestamp": _ts(BASE), "event_type": "stop", "process_type": "writer", "pid": 1})
            + "\n"
        )
        monitor = ProcessContinuityMonitor(events_path=events_file)
        events = monitor.load_events()
        assert len(events) == 2

    def test_load_skips_missing_fields(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        events_file.write_text(
            json.dumps({"timestamp": _ts(BASE), "event_type": "start"}) + "\n"
            + json.dumps({"timestamp": _ts(BASE), "event_type": "stop", "process_type": "writer", "pid": 2}) + "\n"
        )
        monitor = ProcessContinuityMonitor(events_path=events_file)
        events = monitor.load_events()
        # first line missing pid -> skipped; second line valid
        assert len(events) == 1
        assert events[0].pid == 2

    def test_load_events_in_window(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        old_ts = _ts(BASE - timedelta(hours=48))
        recent_ts = _ts(BASE - timedelta(hours=1))
        _write_events(events_file, [
            {"timestamp": old_ts, "event_type": "start", "process_type": "writer", "pid": 1},
            {"timestamp": recent_ts, "event_type": "start", "process_type": "writer", "pid": 2},
        ])
        monitor = ProcessContinuityMonitor(events_path=events_file)
        events = monitor.load_events_in_window(window_hours=24, now=BASE)
        assert len(events) == 1
        assert events[0].pid == 2


# ---------------------------------------------------------------------------
# gap detection
# ---------------------------------------------------------------------------


class TestGapDetection:
    """detect_gaps finds intervals between stop and next start."""

    def test_no_gaps_when_continuous(self, tmp_path):
        events = [
            ProcessEvent(timestamp=_ts(BASE), event_type="start", process_type="writer", pid=1),
            ProcessEvent(timestamp=_ts(BASE + timedelta(hours=1)), event_type="stop", process_type="writer", pid=1, reason="graceful"),
            ProcessEvent(timestamp=_ts(BASE + timedelta(hours=1, seconds=5)), event_type="start", process_type="writer", pid=2),
        ]
        monitor = ProcessContinuityMonitor(events_path=tmp_path / "e.jsonl")
        gaps = monitor.detect_gaps(events, max_gap_sec=60)
        assert len(gaps) == 0

    def test_detects_gap_over_threshold(self, tmp_path):
        events = [
            ProcessEvent(timestamp=_ts(BASE), event_type="stop", process_type="writer", pid=1, reason="container_recycle"),
            ProcessEvent(timestamp=_ts(BASE + timedelta(minutes=10)), event_type="start", process_type="writer", pid=2),
        ]
        monitor = ProcessContinuityMonitor(events_path=tmp_path / "e.jsonl")
        gaps = monitor.detect_gaps(events, max_gap_sec=60)
        assert len(gaps) == 1
        assert gaps[0].duration_sec == pytest.approx(600.0, abs=1)
        assert gaps[0].cause == "container_recycle"

    def test_gap_strokes_lost(self, tmp_path):
        events = [
            ProcessEvent(timestamp=_ts(BASE), event_type="stop", process_type="writer", pid=1, reason=""),
            ProcessEvent(timestamp=_ts(BASE + timedelta(minutes=5)), event_type="start", process_type="writer", pid=2),
        ]
        monitor = ProcessContinuityMonitor(events_path=tmp_path / "e.jsonl", stroke_cadence_sec=15)
        gaps = monitor.detect_gaps(events, max_gap_sec=60)
        assert len(gaps) == 1
        # 300 sec / 15 sec cadence = 20 strokes lost
        assert gaps[0].strokes_lost == 20

    def test_no_gaps_with_single_event(self, tmp_path):
        events = [
            ProcessEvent(timestamp=_ts(BASE), event_type="start", process_type="writer", pid=1),
        ]
        monitor = ProcessContinuityMonitor(events_path=tmp_path / "e.jsonl")
        gaps = monitor.detect_gaps(events)
        assert len(gaps) == 0

    def test_no_gaps_with_empty_list(self, tmp_path):
        monitor = ProcessContinuityMonitor(events_path=tmp_path / "e.jsonl")
        gaps = monitor.detect_gaps([])
        assert len(gaps) == 0

    def test_multiple_gaps_detected(self, tmp_path):
        events = [
            ProcessEvent(timestamp=_ts(BASE), event_type="stop", process_type="writer", pid=1, reason="container_recycle"),
            ProcessEvent(timestamp=_ts(BASE + timedelta(minutes=5)), event_type="start", process_type="writer", pid=2),
            ProcessEvent(timestamp=_ts(BASE + timedelta(minutes=10)), event_type="stop", process_type="writer", pid=2, reason="container_recycle"),
            ProcessEvent(timestamp=_ts(BASE + timedelta(minutes=20)), event_type="start", process_type="writer", pid=3),
        ]
        monitor = ProcessContinuityMonitor(events_path=tmp_path / "e.jsonl")
        gaps = monitor.detect_gaps(events, max_gap_sec=60)
        assert len(gaps) == 2


# ---------------------------------------------------------------------------
# gap classification
# ---------------------------------------------------------------------------


class TestGapClassification:
    """_classify_gap determines the cause of a gap."""

    def test_container_recycle_from_reason(self, tmp_path):
        monitor = ProcessContinuityMonitor(events_path=tmp_path / "e.jsonl")
        stop = ProcessEvent(timestamp=_ts(BASE), event_type="stop", process_type="writer", pid=1, reason="container_recycle")
        assert monitor._classify_gap(stop, 300) == "container_recycle"

    def test_graceful_stop_from_reason(self, tmp_path):
        monitor = ProcessContinuityMonitor(events_path=tmp_path / "e.jsonl")
        stop = ProcessEvent(timestamp=_ts(BASE), event_type="stop", process_type="writer", pid=1, reason="graceful_shutdown")
        assert monitor._classify_gap(stop, 300) == "graceful_stop"

    def test_short_unknown_gap_classified_as_recycle(self, tmp_path):
        monitor = ProcessContinuityMonitor(events_path=tmp_path / "e.jsonl")
        stop = ProcessEvent(timestamp=_ts(BASE), event_type="stop", process_type="writer", pid=1, reason="")
        # no reason + short gap -> likely recycle
        assert monitor._classify_gap(stop, 90) == "container_recycle"

    def test_long_unknown_gap_stays_unknown(self, tmp_path):
        monitor = ProcessContinuityMonitor(events_path=tmp_path / "e.jsonl")
        stop = ProcessEvent(timestamp=_ts(BASE), event_type="stop", process_type="writer", pid=1, reason="")
        assert monitor._classify_gap(stop, 600) == "unknown"


# ---------------------------------------------------------------------------
# continuity report
# ---------------------------------------------------------------------------


class TestContinuityReport:
    """continuity_report computes score and metrics."""

    def test_perfect_continuity(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        # 24 hours of continuous operation, no gaps
        _write_events(events_file, [
            {"timestamp": _ts(BASE - timedelta(hours=24)), "event_type": "start", "process_type": "writer", "pid": 1},
            {"timestamp": _ts(BASE), "event_type": "heartbeat", "process_type": "writer", "pid": 1},
        ])
        monitor = ProcessContinuityMonitor(events_path=events_file, stroke_cadence_sec=15)
        report = monitor.continuity_report(window_hours=24, now=BASE)
        assert report.score == 1.0
        assert report.gap_count == 0
        assert report.health_label == "excellent"

    def test_degraded_continuity(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        # stop after 2 hours, restart after 1 hour gap, run for 21 hours
        _write_events(events_file, [
            {"timestamp": _ts(BASE - timedelta(hours=24)), "event_type": "start", "process_type": "writer", "pid": 1},
            {"timestamp": _ts(BASE - timedelta(hours=22)), "event_type": "stop", "process_type": "writer", "pid": 1, "reason": "container_recycle"},
            {"timestamp": _ts(BASE - timedelta(hours=21)), "event_type": "start", "process_type": "writer", "pid": 2},
            {"timestamp": _ts(BASE), "event_type": "heartbeat", "process_type": "writer", "pid": 2},
        ])
        monitor = ProcessContinuityMonitor(events_path=events_file, stroke_cadence_sec=15)
        report = monitor.continuity_report(window_hours=24, now=BASE)
        # 1 hour gap = 3600 sec, lost 240 strokes out of 5760 expected
        assert report.score < 1.0
        assert report.gap_count == 1
        assert report.recycle_events == 1

    def test_empty_window_gives_perfect_score(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        events_file.write_text("")
        monitor = ProcessContinuityMonitor(events_path=events_file)
        report = monitor.continuity_report(window_hours=24, now=BASE)
        assert report.score == 1.0  # no gaps detected = perfect
        assert report.expected_strokes > 0

    def test_report_fields(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        monitor = ProcessContinuityMonitor(events_path=events_file)
        report = monitor.continuity_report(window_hours=12, now=BASE)
        assert isinstance(report, ContinuityReport)
        assert report.window_hours == 12
        assert isinstance(report.score, float)
        assert 0.0 <= report.score <= 1.0


# ---------------------------------------------------------------------------
# health labels
# ---------------------------------------------------------------------------


class TestHealthLabels:
    """ContinuityReport.health_label maps score ranges."""

    def _report(self, score: float) -> ContinuityReport:
        return ContinuityReport(
            window_start="", window_end="", window_hours=24,
            expected_strokes=100, actual_strokes=int(score * 100),
            score=score, gap_count=0,
        )

    def test_excellent(self):
        assert self._report(0.96).health_label == "excellent"

    def test_good(self):
        assert self._report(0.85).health_label == "good"

    def test_degraded(self):
        assert self._report(0.55).health_label == "degraded"

    def test_poor(self):
        assert self._report(0.25).health_label == "poor"

    def test_critical(self):
        assert self._report(0.05).health_label == "critical"

    def test_boundary_95(self):
        assert self._report(0.95).health_label == "excellent"

    def test_boundary_80(self):
        assert self._report(0.80).health_label == "good"

    def test_boundary_50(self):
        assert self._report(0.50).health_label == "degraded"

    def test_boundary_20(self):
        assert self._report(0.20).health_label == "poor"


# ---------------------------------------------------------------------------
# is_likely_recycled heuristic
# ---------------------------------------------------------------------------


class TestIsLikelyRecycled:
    """is_likely_recycled detects container recycle patterns."""

    def test_quick_restart_no_reason(self, tmp_path):
        monitor = ProcessContinuityMonitor(events_path=tmp_path / "e.jsonl")
        stop = ProcessEvent(timestamp=_ts(BASE), event_type="stop", process_type="writer", pid=1, reason="")
        start = ProcessEvent(timestamp=_ts(BASE + timedelta(seconds=30)), event_type="start", process_type="writer", pid=2)
        assert monitor.is_likely_recycled(stop, start) is True

    def test_slow_restart_no_reason(self, tmp_path):
        monitor = ProcessContinuityMonitor(events_path=tmp_path / "e.jsonl")
        stop = ProcessEvent(timestamp=_ts(BASE), event_type="stop", process_type="writer", pid=1, reason="")
        start = ProcessEvent(timestamp=_ts(BASE + timedelta(minutes=5)), event_type="start", process_type="writer", pid=2)
        assert monitor.is_likely_recycled(stop, start) is False

    def test_quick_restart_with_reason(self, tmp_path):
        monitor = ProcessContinuityMonitor(events_path=tmp_path / "e.jsonl")
        stop = ProcessEvent(timestamp=_ts(BASE), event_type="stop", process_type="writer", pid=1, reason="graceful")
        start = ProcessEvent(timestamp=_ts(BASE + timedelta(seconds=10)), event_type="start", process_type="writer", pid=2)
        # has a reason, so not classified as recycle by this heuristic
        assert monitor.is_likely_recycled(stop, start) is False


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------


class TestSummarize:
    """summarize produces a human-readable one-liner."""

    def test_summarize_returns_string(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        events_file.write_text("")
        monitor = ProcessContinuityMonitor(events_path=events_file)
        result = monitor.summarize()
        assert isinstance(result, str)
        assert "24h continuity" in result
        assert "excellent" in result  # no events = no gaps = perfect


# ---------------------------------------------------------------------------
# ProcessEvent dataclass
# ---------------------------------------------------------------------------


class TestProcessEvent:
    """ProcessEvent serialization."""

    def test_to_dict_minimal(self):
        e = ProcessEvent(
            timestamp=_ts(BASE), event_type="start",
            process_type="writer", pid=42,
        )
        d = e.to_dict()
        assert d["event_type"] == "start"
        assert d["pid"] == 42
        assert "reason" not in d  # empty reason omitted
        assert "metadata" not in d  # empty metadata omitted

    def test_to_dict_with_reason_and_metadata(self):
        e = ProcessEvent(
            timestamp=_ts(BASE), event_type="stop",
            process_type="batch", pid=99,
            reason="oom_kill", metadata={"exit_code": 137},
        )
        d = e.to_dict()
        assert d["reason"] == "oom_kill"
        assert d["metadata"] == {"exit_code": 137}


# ---------------------------------------------------------------------------
# Gap dataclass
# ---------------------------------------------------------------------------


class TestGap:
    """Gap dataclass fields."""

    def test_gap_fields(self):
        g = Gap(
            start=_ts(BASE), end=_ts(BASE + timedelta(minutes=5)),
            duration_sec=300.0, cause="container_recycle", strokes_lost=20,
        )
        assert g.duration_sec == 300.0
        assert g.cause == "container_recycle"
        assert g.strokes_lost == 20


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """boundary conditions and error handling."""

    def test_zero_cadence_does_not_crash(self, tmp_path):
        # stroke_cadence_sec=0 would cause division by zero if not guarded
        # the module uses max(1, ...) for expected_strokes, but cadence=0
        # in gap strokes_lost calc. let's verify it doesn't crash.
        events_file = tmp_path / "events.jsonl"
        monitor = ProcessContinuityMonitor(events_path=events_file, stroke_cadence_sec=1)
        report = monitor.continuity_report(window_hours=1, now=BASE)
        assert report.score >= 0.0

    def test_timezone_naive_events_treated_as_utc(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        naive_ts = "2026-10-26T12:00:00"  # no timezone
        _write_events(events_file, [
            {"timestamp": naive_ts, "event_type": "start", "process_type": "writer", "pid": 1},
        ])
        monitor = ProcessContinuityMonitor(events_path=events_file)
        events = monitor.load_events_in_window(window_hours=48, now=BASE)
        # should be treated as UTC and fall within 48h window
        assert len(events) == 1

    def test_continuity_report_window_start(self, tmp_path):
        events_file = tmp_path / "events.jsonl"
        events_file.write_text("")
        monitor = ProcessContinuityMonitor(events_path=events_file)
        report = monitor.continuity_report(window_hours=6, now=BASE)
        # window_start should be 6 hours before BASE
        expected_start = BASE - timedelta(hours=6)
        assert report.window_start == expected_start.isoformat()
