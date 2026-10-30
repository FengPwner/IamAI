"""test_restart_cascade_detector.py — tests for the restart cascade detector.

covers:
  - empty / missing log
  - healthy: 0–1 restarts in window
  - watch: 2–3 restarts in window
  - cascade: 4+ restarts in window
  - window filtering (old events excluded)
  - reason breakdown
  - inter-restart gap statistics
  - edge cases: malformed lines, zero-gap restarts
"""

import json
import os
import tempfile
import time
import pytest

# allow importing from repo root
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.restart_cascade_detector import (
    read_restart_log,
    filter_by_window,
    classify,
    reason_breakdown,
    inter_restart_gaps,
    detect_cascade,
    CASCADE_THRESHOLD,
    WATCH_THRESHOLD,
    DEFAULT_WINDOW,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_log(tmp_path, events):
    """write a list of event dicts to a temp JSONL file, return path."""
    log = tmp_path / "restart_events.jsonl"
    with open(log, "w", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    return str(log)


def _make_events(n, base_ts, interval=60, reason="reclaimed"):
    """generate n restart events starting at base_ts, spaced by interval."""
    return [
        {"ts": base_ts + i * interval, "pid": 1000 + i, "reason": reason}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# read_restart_log
# ---------------------------------------------------------------------------

class TestReadRestartLog:
    def test_missing_file(self, tmp_path):
        assert read_restart_log(str(tmp_path / "nope.jsonl")) == []

    def test_empty_file(self, tmp_path):
        log = tmp_path / "empty.jsonl"
        log.write_text("")
        assert read_restart_log(str(log)) == []

    def test_valid_events(self, tmp_path):
        events = [{"ts": 100, "pid": 1}, {"ts": 200, "pid": 2}]
        path = _write_log(tmp_path, events)
        result = read_restart_log(path)
        assert len(result) == 2
        assert result[0]["ts"] == 100
        assert result[1]["pid"] == 2

    def test_skips_malformed_lines(self, tmp_path):
        log = tmp_path / "bad.jsonl"
        log.write_text('{"ts": 100}\nnot-json\n{"ts": 300}\n')
        result = read_restart_log(str(log))
        assert len(result) == 2

    def test_skips_lines_without_ts(self, tmp_path):
        log = tmp_path / "nots.jsonl"
        log.write_text('{"pid": 1}\n{"ts": 200, "pid": 2}\n')
        result = read_restart_log(str(log))
        assert len(result) == 1
        assert result[0]["ts"] == 200


# ---------------------------------------------------------------------------
# filter_by_window
# ---------------------------------------------------------------------------

class TestFilterByWindow:
    def test_all_within_window(self):
        events = _make_events(3, base_ts=1000, interval=10)
        result = filter_by_window(events, now=1030, window_secs=60)
        assert len(result) == 3

    def test_some_outside_window(self):
        events = [
            {"ts": 500, "pid": 1},
            {"ts": 900, "pid": 2},
            {"ts": 1000, "pid": 3},
        ]
        result = filter_by_window(events, now=1050, window_secs=200)
        assert len(result) == 2  # 900 and 1000

    def test_none_within_window(self):
        events = _make_events(3, base_ts=100, interval=10)
        result = filter_by_window(events, now=5000, window_secs=60)
        assert len(result) == 0

    def test_exact_boundary(self):
        events = [{"ts": 940}, {"ts": 1000}]
        result = filter_by_window(events, now=1000, window_secs=60)
        assert len(result) == 2  # both >= 940


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_zero_is_healthy(self):
        assert classify(0) == "healthy"

    def test_one_is_healthy(self):
        assert classify(1) == "healthy"

    def test_watch_threshold(self):
        assert classify(2) == "watch"
        assert classify(3) == "watch"

    def test_cascade_threshold(self):
        assert classify(4) == "cascade"
        assert classify(100) == "cascade"


# ---------------------------------------------------------------------------
# reason_breakdown
# ---------------------------------------------------------------------------

class TestReasonBreakdown:
    def test_empty(self):
        assert reason_breakdown([]) == {}

    def test_single_reason(self):
        events = [{"reason": "reclaimed"}, {"reason": "reclaimed"}]
        assert reason_breakdown(events) == {"reclaimed": 2}

    def test_mixed_reasons(self):
        events = [
            {"reason": "reclaimed"},
            {"reason": "oom"},
            {"reason": "reclaimed"},
        ]
        result = reason_breakdown(events)
        assert result == {"reclaimed": 2, "oom": 1}

    def test_missing_reason_defaults_to_unknown(self):
        events = [{"ts": 100}]
        result = reason_breakdown(events)
        assert result == {"unknown": 1}


# ---------------------------------------------------------------------------
# inter_restart_gaps
# ---------------------------------------------------------------------------

class TestInterRestartGaps:
    def test_empty(self):
        assert inter_restart_gaps([]) == []

    def test_single_event(self):
        assert inter_restart_gaps([{"ts": 100}]) == []

    def test_two_events(self):
        events = [{"ts": 100}, {"ts": 160}]
        assert inter_restart_gaps(events) == [60]

    def test_unsorted_input(self):
        events = [{"ts": 200}, {"ts": 100}, {"ts": 300}]
        gaps = inter_restart_gaps(events)
        assert gaps == [100, 100]

    def test_zero_gap(self):
        events = [{"ts": 100}, {"ts": 100}]
        assert inter_restart_gaps(events) == [0]


# ---------------------------------------------------------------------------
# detect_cascade (integration)
# ---------------------------------------------------------------------------

class TestDetectCascade:
    def test_no_log_file(self, tmp_path):
        result = detect_cascade(str(tmp_path / "missing.jsonl"))
        assert result["verdict"] == "healthy"
        assert result["restarts_in_window"] == 0

    def test_healthy_no_restarts(self, tmp_path):
        path = _write_log(tmp_path, [])
        result = detect_cascade(path, now=1000)
        assert result["verdict"] == "healthy"
        assert result["restarts_in_window"] == 0
        assert result["min_gap"] is None
        assert result["avg_gap"] is None

    def test_healthy_one_restart(self, tmp_path):
        events = _make_events(1, base_ts=500)
        path = _write_log(tmp_path, events)
        result = detect_cascade(path, now=600, window_secs=200)
        assert result["verdict"] == "healthy"
        assert result["restarts_in_window"] == 1

    def test_watch_two_restarts(self, tmp_path):
        events = _make_events(2, base_ts=500, interval=30)
        path = _write_log(tmp_path, events)
        result = detect_cascade(path, now=600, window_secs=200)
        assert result["verdict"] == "watch"
        assert result["restarts_in_window"] == 2
        assert result["min_gap"] == 30
        assert result["max_gap"] == 30
        assert result["avg_gap"] == 30

    def test_watch_three_restarts(self, tmp_path):
        events = _make_events(3, base_ts=500, interval=20)
        path = _write_log(tmp_path, events)
        result = detect_cascade(path, now=600, window_secs=200)
        assert result["verdict"] == "watch"
        assert result["restarts_in_window"] == 3

    def test_cascade_four_restarts(self, tmp_path):
        events = _make_events(4, base_ts=500, interval=15)
        path = _write_log(tmp_path, events)
        result = detect_cascade(path, now=600, window_secs=200)
        assert result["verdict"] == "cascade"
        assert result["restarts_in_window"] == 4
        assert len(result["gaps"]) == 3
        assert all(g == 15 for g in result["gaps"])

    def test_cascade_many_restarts(self, tmp_path):
        events = _make_events(10, base_ts=500, interval=10)
        path = _write_log(tmp_path, events)
        result = detect_cascade(path, now=600, window_secs=200)
        assert result["verdict"] == "cascade"
        assert result["restarts_in_window"] == 10
        assert result["min_gap"] == 10
        assert result["max_gap"] == 10

    def test_window_excludes_old_events(self, tmp_path):
        # 3 old events + 1 recent → should be healthy (only 1 in window)
        events = [
            {"ts": 100, "pid": 1, "reason": "reclaimed"},
            {"ts": 110, "pid": 2, "reason": "reclaimed"},
            {"ts": 120, "pid": 3, "reason": "reclaimed"},
            {"ts": 950, "pid": 4, "reason": "reclaimed"},
        ]
        path = _write_log(tmp_path, events)
        result = detect_cascade(path, now=1000, window_secs=100)
        assert result["verdict"] == "healthy"
        assert result["restarts_in_window"] == 1

    def test_window_boundary_includes_exact_cutoff(self, tmp_path):
        events = [{"ts": 900}, {"ts": 1000}]
        path = _write_log(tmp_path, events)
        result = detect_cascade(path, now=1000, window_secs=100)
        assert result["restarts_in_window"] == 2
        assert result["verdict"] == "watch"

    def test_reason_breakdown_in_result(self, tmp_path):
        events = [
            {"ts": 500, "reason": "reclaimed"},
            {"ts": 520, "reason": "oom"},
            {"ts": 540, "reason": "reclaimed"},
            {"ts": 560, "reason": "signal"},
        ]
        path = _write_log(tmp_path, events)
        result = detect_cascade(path, now=600, window_secs=200)
        assert result["verdict"] == "cascade"
        assert result["reasons"] == {"reclaimed": 2, "oom": 1, "signal": 1}

    def test_gap_statistics(self, tmp_path):
        events = [
            {"ts": 500},
            {"ts": 530},   # gap: 30
            {"ts": 580},   # gap: 50
        ]
        path = _write_log(tmp_path, events)
        result = detect_cascade(path, now=600, window_secs=200)
        assert result["min_gap"] == 30
        assert result["max_gap"] == 50
        assert result["avg_gap"] == pytest.approx(40.0)

    def test_malformed_lines_skipped(self, tmp_path):
        log = tmp_path / "bad.jsonl"
        log.write_text(
            '{"ts": 500, "reason": "reclaimed"}\n'
            'broken line\n'
            '{"ts": 520, "reason": "oom"}\n'
        )
        result = detect_cascade(str(log), now=600, window_secs=200)
        assert result["restarts_in_window"] == 2
        assert result["verdict"] == "watch"


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_zero_gap_rapid_restart(self, tmp_path):
        """two restarts at the exact same timestamp — cascade with zero gap."""
        events = [
            {"ts": 500, "pid": 1},
            {"ts": 500, "pid": 2},
            {"ts": 500, "pid": 3},
            {"ts": 500, "pid": 4},
        ]
        path = _write_log(tmp_path, events)
        result = detect_cascade(path, now=500, window_secs=10)
        assert result["verdict"] == "cascade"
        assert result["min_gap"] == 0
        assert result["max_gap"] == 0

    def test_custom_window(self, tmp_path):
        events = _make_events(3, base_ts=500, interval=100)
        path = _write_log(tmp_path, events)

        # wide window catches all 3 → watch
        r1 = detect_cascade(path, now=800, window_secs=500)
        assert r1["verdict"] == "watch"

        # narrow window only catches last 1 → healthy
        r2 = detect_cascade(path, now=800, window_secs=150)
        assert r2["verdict"] == "healthy"

    def test_large_file_performance(self, tmp_path):
        """1000 events should still be fast."""
        events = _make_events(1000, base_ts=1, interval=1)
        path = _write_log(tmp_path, events)
        start = time.time()
        result = detect_cascade(path, now=1001, window_secs=2000)
        elapsed = time.time() - start
        assert elapsed < 2.0  # generous but catches pathological bugs
        assert result["verdict"] == "cascade"
        assert result["restarts_in_window"] == 1000
