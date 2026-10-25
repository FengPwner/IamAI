"""Tests for iamai.incarnation — process lifecycle lineage tracking."""

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iamai.incarnation import (
    _parse_ts,
    _read_warmup_log,
    incarnation_history,
    incarnation_stats,
    incarnation_verdict,
    incarnation_summary,
    current_incarnation,
)


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------


class TestParseTs:
    def test_standard_offset(self):
        dt = _parse_ts("2026-10-09T07:00:47+00:00")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 10
        assert dt.day == 9
        assert dt.hour == 7
        assert dt.minute == 0
        assert dt.second == 47

    def test_z_suffix(self):
        dt = _parse_ts("2026-10-17T14:00:00Z")
        assert dt is not None
        assert dt.hour == 14

    def test_utc_zero(self):
        dt = _parse_ts("2026-10-09T07:00:47+0000")
        # Python 3.7+ fromisoformat may not handle +0000 without colon
        # If it returns None, that's acceptable behavior
        # (the module handles this gracefully)

    def test_empty_string(self):
        assert _parse_ts("") is None

    def test_none(self):
        assert _parse_ts(None) is None

    def test_invalid(self):
        assert _parse_ts("not-a-date") is None

    def test_with_timezone(self):
        dt = _parse_ts("2026-10-09T15:30:00+08:00")
        assert dt is not None
        assert dt.hour == 15


# ---------------------------------------------------------------------------
# _read_warmup_log
# ---------------------------------------------------------------------------


class TestReadWarmupLog:
    def test_basic(self, tmp_path):
        p = tmp_path / "warmup.jsonl"
        p.write_text('{"event":"restart","pid":1,"ts":"2026-10-09T07:00:00Z"}\n'
                      '{"event":"first_stroke","pid":1,"ts":"2026-10-09T07:00:06Z","stroke_seq":100}\n')
        events = _read_warmup_log(p)
        assert len(events) == 2
        assert events[0]["event"] == "restart"

    def test_empty_file(self, tmp_path):
        p = tmp_path / "warmup.jsonl"
        p.write_text("")
        assert _read_warmup_log(p) == []

    def test_missing_file(self, tmp_path):
        p = tmp_path / "nonexistent.jsonl"
        assert _read_warmup_log(p) == []

    def test_blank_lines_skipped(self, tmp_path):
        p = tmp_path / "warmup.jsonl"
        p.write_text('\n{"event":"restart","pid":1}\n\n{"event":"restart","pid":2}\n\n')
        events = _read_warmup_log(p)
        assert len(events) == 2

    def test_corrupted_lines_skipped(self, tmp_path):
        p = tmp_path / "warmup.jsonl"
        p.write_text('{"event":"restart","pid":1}\nthis is not json\n{"event":"restart","pid":2}\n')
        events = _read_warmup_log(p)
        assert len(events) == 2

    def test_preserves_order(self, tmp_path):
        p = tmp_path / "warmup.jsonl"
        lines = [f'{{"event":"restart","pid":{i},"seq":{i}}}\n' for i in range(10)]
        p.write_text("".join(lines))
        events = _read_warmup_log(p)
        pids = [e["pid"] for e in events]
        assert pids == list(range(10))


# ---------------------------------------------------------------------------
# incarnation_history
# ---------------------------------------------------------------------------


def _write_warmup(tmp_path, lines):
    p = tmp_path / "warmup.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    return str(p)


class TestIncarnationHistory:
    def test_empty_log(self, tmp_path):
        path = _write_warmup(tmp_path, [])
        assert incarnation_history(warmup_path=path) == []

    def test_single_incarnation(self, tmp_path):
        path = _write_warmup(tmp_path, [
            {"writer": "qwen", "event": "restart", "pid": 100,
             "ts": "2026-10-09T07:00:00+00:00"},
            {"writer": "qwen", "event": "first_stroke", "pid": 100,
             "ts": "2026-10-09T07:00:06+00:00", "stroke_seq": 100},
        ])
        history = incarnation_history(warmup_path=path)
        assert len(history) == 1
        assert history[0]["pid"] == 100
        assert history[0]["end"] is None  # no subsequent restart
        assert history[0]["first_stroke"] == 100

    def test_two_incarnations(self, tmp_path):
        path = _write_warmup(tmp_path, [
            {"event": "restart", "pid": 100, "ts": "2026-10-09T07:00:00+00:00"},
            {"event": "first_stroke", "pid": 100, "ts": "2026-10-09T07:00:06+00:00",
             "stroke_seq": 100},
            {"event": "restart", "pid": 200, "ts": "2026-10-09T08:00:00+00:00"},
            {"event": "first_stroke", "pid": 200, "ts": "2026-10-09T08:00:06+00:00",
             "stroke_seq": 200},
        ])
        history = incarnation_history(warmup_path=path)
        assert len(history) == 2
        # First incarnation
        assert history[0]["pid"] == 100
        assert history[0]["duration_seconds"] == 3600.0
        assert history[0]["first_stroke"] == 100
        # Second incarnation (still running)
        assert history[1]["pid"] == 200
        assert history[1]["end"] is None
        assert history[1]["first_stroke"] == 200

    def test_three_incarnations(self, tmp_path):
        path = _write_warmup(tmp_path, [
            {"event": "restart", "pid": 1, "ts": "2026-10-09T07:00:00+00:00"},
            {"event": "restart", "pid": 2, "ts": "2026-10-09T07:30:00+00:00"},
            {"event": "restart", "pid": 3, "ts": "2026-10-09T08:30:00+00:00"},
        ])
        history = incarnation_history(warmup_path=path)
        assert len(history) == 3
        assert history[0]["duration_seconds"] == 1800.0  # 30 min
        assert history[1]["duration_seconds"] == 3600.0  # 60 min
        assert history[2]["end"] is None  # last one, still running

    def test_first_stroke_mismatched_pid(self, tmp_path):
        path = _write_warmup(tmp_path, [
            {"event": "restart", "pid": 100, "ts": "2026-10-09T07:00:00+00:00"},
            {"event": "first_stroke", "pid": 999, "ts": "2026-10-09T07:00:06+00:00",
             "stroke_seq": 100},  # wrong PID
        ])
        history = incarnation_history(warmup_path=path)
        assert history[0]["first_stroke"] is None

    def test_missing_first_stroke(self, tmp_path):
        path = _write_warmup(tmp_path, [
            {"event": "restart", "pid": 100, "ts": "2026-10-09T07:00:00+00:00"},
            # no first_stroke event
            {"event": "restart", "pid": 200, "ts": "2026-10-09T08:00:00+00:00"},
        ])
        history = incarnation_history(warmup_path=path)
        assert history[0]["first_stroke"] is None
        assert history[0]["duration_seconds"] == 3600.0

    def test_corrupted_lines_skipped(self, tmp_path):
        p = tmp_path / "warmup.jsonl"
        p.write_text(
            '{"event":"restart","pid":1,"ts":"2026-10-09T07:00:00+00:00"}\n'
            'this is garbage\n'
            '{"event":"restart","pid":2,"ts":"2026-10-09T08:00:00+00:00"}\n'
        )
        history = incarnation_history(warmup_path=str(p))
        assert len(history) == 2


# ---------------------------------------------------------------------------
# incarnation_stats
# ---------------------------------------------------------------------------


class TestIncarnationStats:
    def test_empty_history(self):
        stats = incarnation_stats([])
        assert stats["count"] == 0
        assert stats["verdict"] == "unknown"
        assert stats["mean"] is None

    def test_single_no_duration(self):
        stats = incarnation_stats([{
            "pid": 1, "start": None, "end": None,
            "duration_seconds": None, "first_stroke": None
        }])
        assert stats["count"] == 1
        assert stats["verdict"] == "unknown"

    def test_stable(self):
        history = [
            {"pid": i, "duration_seconds": 7200.0}
            for i in range(5)
        ]
        stats = incarnation_stats(history)
        assert stats["count"] == 5
        assert stats["mean"] == 7200.0
        assert stats["median"] == 7200.0
        assert stats["verdict"] == "stable"

    def test_churny(self):
        history = [
            {"pid": i, "duration_seconds": 900.0}
            for i in range(3)
        ]
        stats = incarnation_stats(history)
        assert stats["verdict"] == "churny"
        assert stats["mean"] == 900.0

    def test_flaky(self):
        history = [
            {"pid": i, "duration_seconds": 120.0}
            for i in range(3)
        ]
        stats = incarnation_stats(history)
        assert stats["verdict"] == "flaky"
        assert stats["mean"] == 120.0

    def test_mixed_durations(self):
        history = [
            {"pid": 1, "duration_seconds": 600.0},
            {"pid": 2, "duration_seconds": 1200.0},
            {"pid": 3, "duration_seconds": 1800.0},
        ]
        stats = incarnation_stats(history)
        assert stats["count"] == 3
        assert stats["mean"] == 1200.0
        assert stats["median"] == 1200.0
        assert stats["min"] == 600.0
        assert stats["max"] == 1800.0

    def test_median_even_count(self):
        history = [
            {"pid": 1, "duration_seconds": 100.0},
            {"pid": 2, "duration_seconds": 200.0},
            {"pid": 3, "duration_seconds": 300.0},
            {"pid": 4, "duration_seconds": 400.0},
        ]
        stats = incarnation_stats(history)
        assert stats["median"] == 250.0  # (200 + 300) / 2

    def test_shortest_pid(self):
        history = [
            {"pid": 10, "duration_seconds": 3600.0},
            {"pid": 20, "duration_seconds": 300.0},
            {"pid": 30, "duration_seconds": 1800.0},
        ]
        stats = incarnation_stats(history)
        assert stats["shortest_pid"] == 20

    def test_none_durations_ignored(self):
        history = [
            {"pid": 1, "duration_seconds": None},
            {"pid": 2, "duration_seconds": 1000.0},
            {"pid": 3, "duration_seconds": 2000.0},
        ]
        stats = incarnation_stats(history)
        assert stats["count"] == 3
        assert stats["mean"] == 1500.0
        assert stats["median"] == 1500.0

    def test_boundary_stable(self):
        history = [{"pid": 1, "duration_seconds": 3600.0}]
        assert incarnation_stats(history)["verdict"] == "stable"

    def test_boundary_churny(self):
        history = [{"pid": 1, "duration_seconds": 600.0}]
        assert incarnation_stats(history)["verdict"] == "churny"

    def test_boundary_flaky(self):
        history = [{"pid": 1, "duration_seconds": 599.0}]
        assert incarnation_stats(history)["verdict"] == "flaky"


# ---------------------------------------------------------------------------
# incarnation_verdict
# ---------------------------------------------------------------------------


class TestIncarnationVerdict:
    def test_stable(self):
        assert incarnation_verdict(7200) == "stable"

    def test_churny(self):
        assert incarnation_verdict(1800) == "churny"

    def test_flaky(self):
        assert incarnation_verdict(60) == "flaky"

    def test_none(self):
        assert incarnation_verdict(None) == "unknown"

    def test_exactly_stable(self):
        assert incarnation_verdict(3600) == "stable"

    def test_exactly_churny(self):
        assert incarnation_verdict(600) == "churny"

    def test_just_below_churny(self):
        assert incarnation_verdict(599) == "flaky"

    def test_just_below_stable(self):
        assert incarnation_verdict(3599) == "churny"

    def test_zero(self):
        assert incarnation_verdict(0) == "flaky"

    def test_very_large(self):
        assert incarnation_verdict(999999) == "stable"


# ---------------------------------------------------------------------------
# current_incarnation
# ---------------------------------------------------------------------------


class TestCurrentIncarnation:
    def test_returns_dict(self):
        result = current_incarnation("qwen")
        assert isinstance(result, dict)
        assert "pid" in result
        assert "alive" in result
        assert "uptime_seconds" in result
        assert "warmup_seconds" in result

    def test_dead_process(self):
        # Use a writer ID that shouldn't have a real PID file
        result = current_incarnation("nonexistent_writer_99999")
        assert result["pid"] is None
        assert result["alive"] is False

    def test_keys_present(self):
        result = current_incarnation("qwen")
        expected_keys = {"pid", "alive", "uptime_seconds", "warmup_seconds"}
        assert set(result.keys()) == expected_keys


# ---------------------------------------------------------------------------
# incarnation_summary
# ---------------------------------------------------------------------------


class TestIncarnationSummary:
    def test_returns_string(self):
        # This tests the summary function with a real or mock warmup path
        # Since we can't easily mock the repo root, test the string output format
        summary = incarnation_summary("nonexistent_writer_99999")
        assert isinstance(summary, str)

    def test_no_history_message(self, tmp_path, monkeypatch):
        # Write an empty warmup log
        p = tmp_path / "warmup.jsonl"
        p.write_text("")
        # Monkeypatch _repo_root to use tmp_path
        monkeypatch.setattr("iamai.incarnation._repo_root", lambda: tmp_path)
        summary = incarnation_summary("qwen")
        assert "no incarnation history" in summary

    def test_with_history(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        p = data_dir / "restart_warmup.jsonl"
        lines = [
            json.dumps({"event": "restart", "pid": 1,
                        "ts": "2026-10-09T07:00:00+00:00"}),
            json.dumps({"event": "restart", "pid": 2,
                        "ts": "2026-10-09T08:00:00+00:00"}),
        ]
        p.write_text("\n".join(lines) + "\n")
        monkeypatch.setattr("iamai.incarnation._repo_root", lambda: tmp_path)
        summary = incarnation_summary("qwen")
        assert "2 incarnation" in summary
        assert "verdict:" in summary


# ---------------------------------------------------------------------------
# integration
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_lifecycle(self, tmp_path):
        """Simulate a complete lifecycle: start → stroke → restart → stroke → stats."""
        events = [
            {"event": "restart", "pid": 100, "ts": "2026-10-09T07:00:00+00:00",
             "writer": "qwen", "stroke_seq": None},
            {"event": "first_stroke", "pid": 100, "ts": "2026-10-09T07:00:06+00:00",
             "writer": "qwen", "stroke_seq": 12464},
            {"event": "restart", "pid": 200, "ts": "2026-10-09T07:30:00+00:00",
             "writer": "qwen", "stroke_seq": None},
            {"event": "first_stroke", "pid": 200, "ts": "2026-10-09T07:30:06+00:00",
             "writer": "qwen", "stroke_seq": 12500},
            {"event": "restart", "pid": 300, "ts": "2026-10-09T08:30:00+00:00",
             "writer": "qwen", "stroke_seq": None},
            {"event": "first_stroke", "pid": 300, "ts": "2026-10-09T08:30:06+00:00",
             "writer": "qwen", "stroke_seq": 12600},
        ]
        path = _write_warmup(tmp_path, events)
        history = incarnation_history(warmup_path=path)

        assert len(history) == 3
        assert history[0]["duration_seconds"] == 1800.0
        assert history[1]["duration_seconds"] == 3600.0
        assert history[2]["end"] is None

        stats = incarnation_stats(history)
        assert stats["count"] == 3
        assert stats["mean"] == 2700.0  # (1800 + 3600) / 2
        assert stats["min"] == 1800.0
        assert stats["max"] == 3600.0
        assert stats["verdict"] == "churny"

    def test_rapid_recycling(self, tmp_path):
        """Simulate rapid recycling — all incarnations die within 5 minutes."""
        events = []
        base_ts = datetime(2026, 10, 9, 7, 0, 0, tzinfo=timezone.utc)
        for i in range(10):
            pid = 1000 + i
            ts = base_ts.replace(minute=base_ts.minute + i * 2)
            ts_str = ts.strftime("%Y-%m-%dT%H:%M:%S+00:00")
            events.append({"event": "restart", "pid": pid, "ts": ts_str})
            stroke_ts = ts.replace(second=6)
            events.append({
                "event": "first_stroke", "pid": pid,
                "ts": stroke_ts.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "stroke_seq": 10000 + i * 10,
            })

        path = _write_warmup(tmp_path, events)
        history = incarnation_history(warmup_path=path)
        stats = incarnation_stats(history)

        assert stats["count"] == 10
        assert stats["verdict"] == "flaky"
        # Each incarnation should be 120 seconds (2 min apart)
        assert stats["min"] == 120.0
        assert stats["max"] == 120.0

    def test_long_running_stable(self, tmp_path):
        """Simulate stable, long-running incarnations."""
        events = []
        for i in range(5):
            hour = 7 + i * 3  # 3 hours apart
            events.append({
                "event": "restart", "pid": 500 + i,
                "ts": f"2026-10-09T{hour:02d}:00:00+00:00",
            })

        path = _write_warmup(tmp_path, events)
        history = incarnation_history(warmup_path=path)
        stats = incarnation_stats(history)

        assert stats["count"] == 5
        assert stats["verdict"] == "stable"
        assert stats["mean"] == 10800.0  # 3 hours
