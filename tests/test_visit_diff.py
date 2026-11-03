"""Tests for iamai.visit_diff — caretaker visit snapshot comparison."""

import pytest

from iamai.visit_diff import (
    VisitDelta,
    _parse_ts,
    _safe_bool,
    _safe_int,
    diff,
    diff_many,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _snap(
    ts="2026-11-03T16:00:00+08:00",
    writer_running=True,
    batch_running=True,
    writer_pid=1000,
    batch_pid=1001,
    uncommitted_files=0,
    unpushed_commits=0,
    total_strokes=6000,
    last_commit_sha="abc1234",
    stall_detected=False,
):
    return {
        "ts": ts,
        "writer_running": writer_running,
        "batch_running": batch_running,
        "writer_pid": writer_pid,
        "batch_pid": batch_pid,
        "uncommitted_files": uncommitted_files,
        "unpushed_commits": unpushed_commits,
        "total_strokes": total_strokes,
        "last_commit_sha": last_commit_sha,
        "stall_detected": stall_detected,
    }


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------


class TestParseTs:
    def test_iso_with_offset(self):
        dt = _parse_ts("2026-11-03T16:00:00+08:00")
        assert dt is not None
        assert dt.year == 2026

    def test_iso_utc(self):
        dt = _parse_ts("2026-11-03T08:00:00Z")
        assert dt is not None

    def test_iso_naive_gets_utc(self):
        dt = _parse_ts("2026-11-03T08:00:00")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_empty_string(self):
        assert _parse_ts("") is None

    def test_none(self):
        assert _parse_ts(None) is None

    def test_garbage(self):
        assert _parse_ts("not-a-date") is None


# ---------------------------------------------------------------------------
# _safe_int / _safe_bool
# ---------------------------------------------------------------------------


class TestSafeInt:
    def test_int(self):
        assert _safe_int(42) == 42

    def test_string_int(self):
        assert _safe_int("7") == 7

    def test_none(self):
        assert _safe_int(None) == 0

    def test_garbage(self):
        assert _safe_int("hello") == 0

    def test_custom_default(self):
        assert _safe_int(None, 99) == 99


class TestSafeBool:
    def test_true_bool(self):
        assert _safe_bool(True) is True

    def test_false_bool(self):
        assert _safe_bool(False) is False

    def test_string_true(self):
        assert _safe_bool("true") is True
        assert _safe_bool("True") is True
        assert _safe_bool("1") is True
        assert _safe_bool("yes") is True

    def test_string_false(self):
        assert _safe_bool("false") is False
        assert _safe_bool("no") is False
        assert _safe_bool("0") is False

    def test_none(self):
        assert _safe_bool(None) is False


# ---------------------------------------------------------------------------
# diff — elapsed time
# ---------------------------------------------------------------------------


class TestDiffElapsed:
    def test_normal_gap(self):
        prev = _snap(ts="2026-11-03T16:00:00+08:00")
        curr = _snap(ts="2026-11-03T16:10:00+08:00")
        d = diff(prev, curr)
        assert d.elapsed_seconds == 600.0

    def test_zero_gap(self):
        prev = _snap(ts="2026-11-03T16:00:00+08:00")
        curr = _snap(ts="2026-11-03T16:00:00+08:00")
        d = diff(prev, curr)
        assert d.elapsed_seconds == 0.0

    def test_missing_prev_ts(self):
        prev = _snap(ts="")
        curr = _snap(ts="2026-11-03T16:00:00+08:00")
        d = diff(prev, curr)
        assert d.elapsed_seconds == 0.0

    def test_clock_backwards(self):
        prev = _snap(ts="2026-11-03T16:10:00+08:00")
        curr = _snap(ts="2026-11-03T16:00:00+08:00")
        d = diff(prev, curr)
        assert d.elapsed_seconds == 0.0

    def test_hour_gap(self):
        prev = _snap(ts="2026-11-03T15:00:00+08:00")
        curr = _snap(ts="2026-11-03T16:00:00+08:00")
        d = diff(prev, curr)
        assert d.elapsed_seconds == 3600.0


# ---------------------------------------------------------------------------
# diff — strokes
# ---------------------------------------------------------------------------


class TestDiffStrokes:
    def test_normal_production(self):
        prev = _snap(total_strokes=6000)
        curr = _snap(total_strokes=6100)
        d = diff(prev, curr)
        assert d.strokes_produced == 100

    def test_zero_production(self):
        prev = _snap(total_strokes=6000)
        curr = _snap(total_strokes=6000)
        d = diff(prev, curr)
        assert d.strokes_produced == 0

    def test_negative_clamped_to_zero(self):
        """Strokes can't go backwards in a healthy system."""
        prev = _snap(total_strokes=6100)
        curr = _snap(total_strokes=6000)
        d = diff(prev, curr)
        assert d.strokes_produced == 0

    def test_strokes_per_minute(self):
        prev = _snap(
            ts="2026-11-03T16:00:00+08:00",
            total_strokes=6000,
        )
        curr = _snap(
            ts="2026-11-03T16:10:00+08:00",
            total_strokes=6040,
        )
        d = diff(prev, curr)
        # 40 strokes in 10 minutes = 4.0/min
        assert abs(d.strokes_per_minute - 4.0) < 0.01

    def test_strokes_per_minute_zero_elapsed(self):
        prev = _snap(total_strokes=6000)
        curr = _snap(total_strokes=6100)  # same ts
        d = diff(prev, curr)
        assert d.strokes_per_minute == 0.0


# ---------------------------------------------------------------------------
# diff — commits and backlog
# ---------------------------------------------------------------------------


class TestDiffCommits:
    def test_commits_grew(self):
        prev = _snap(unpushed_commits=3)
        curr = _snap(unpushed_commits=5)
        d = diff(prev, curr)
        assert d.commits_made == 2

    def test_commits_shrunk_after_push(self):
        prev = _snap(unpushed_commits=10)
        curr = _snap(unpushed_commits=2)
        d = diff(prev, curr)
        assert d.commits_made == -8

    def test_backlog_cleared(self):
        prev = _snap(uncommitted_files=7)
        curr = _snap(uncommitted_files=0)
        d = diff(prev, curr)
        assert d.backlog_cleared is True

    def test_backlog_not_cleared_still_pending(self):
        prev = _snap(uncommitted_files=7)
        curr = _snap(uncommitted_files=3)
        d = diff(prev, curr)
        assert d.backlog_cleared is False

    def test_backlog_was_already_zero(self):
        prev = _snap(uncommitted_files=0)
        curr = _snap(uncommitted_files=0)
        d = diff(prev, curr)
        assert d.backlog_cleared is False


# ---------------------------------------------------------------------------
# diff — writer restart detection
# ---------------------------------------------------------------------------


class TestDiffWriterRestart:
    def test_writer_was_down_now_up(self):
        prev = _snap(writer_running=False, writer_pid=None)
        curr = _snap(writer_running=True, writer_pid=2000)
        d = diff(prev, curr)
        assert d.writer_restarted is True
        assert d.writer_downtime == "was_down"

    def test_writer_running_both_visits_same_pid(self):
        prev = _snap(writer_running=True, writer_pid=1000)
        curr = _snap(writer_running=True, writer_pid=1000)
        d = diff(prev, curr)
        assert d.writer_restarted is False
        assert d.writer_downtime == "was_up"

    def test_writer_running_both_visits_pid_changed(self):
        """Process restarted but both snapshots show running."""
        prev = _snap(writer_running=True, writer_pid=1000)
        curr = _snap(writer_running=True, writer_pid=2000)
        d = diff(prev, curr)
        assert d.writer_restarted is True
        assert d.writer_downtime == "was_up"

    def test_writer_down_both_visits(self):
        prev = _snap(writer_running=False, writer_pid=None)
        curr = _snap(writer_running=False, writer_pid=None)
        d = diff(prev, curr)
        assert d.writer_restarted is False
        assert d.writer_downtime == "was_down"

    def test_writer_up_then_down(self):
        prev = _snap(writer_running=True, writer_pid=1000)
        curr = _snap(writer_running=False, writer_pid=None)
        d = diff(prev, curr)
        assert d.writer_restarted is False
        assert d.writer_downtime == "was_up"


# ---------------------------------------------------------------------------
# diff — batch restart detection
# ---------------------------------------------------------------------------


class TestDiffBatchRestart:
    def test_batch_was_down_now_up(self):
        prev = _snap(batch_running=False, batch_pid=None)
        curr = _snap(batch_running=True, batch_pid=3000)
        d = diff(prev, curr)
        assert d.batch_restarted is True

    def test_batch_running_both_same_pid(self):
        prev = _snap(batch_running=True, batch_pid=1001)
        curr = _snap(batch_running=True, batch_pid=1001)
        d = diff(prev, curr)
        assert d.batch_restarted is False

    def test_batch_pid_changed(self):
        prev = _snap(batch_running=True, batch_pid=1001)
        curr = _snap(batch_running=True, batch_pid=3001)
        d = diff(prev, curr)
        assert d.batch_restarted is True


# ---------------------------------------------------------------------------
# diff — stall detection
# ---------------------------------------------------------------------------


class TestDiffStall:
    def test_stall_detected(self):
        prev = _snap(stall_detected=False)
        curr = _snap(stall_detected=True)
        d = diff(prev, curr)
        assert d.stall_now is True

    def test_stall_cleared(self):
        prev = _snap(stall_detected=True)
        curr = _snap(stall_detected=False)
        d = diff(prev, curr)
        assert d.stall_now is False


# ---------------------------------------------------------------------------
# diff — summary
# ---------------------------------------------------------------------------


class TestDiffSummary:
    def test_healthy_interval(self):
        prev = _snap(
            ts="2026-11-03T16:00:00+08:00",
            total_strokes=6000,
        )
        curr = _snap(
            ts="2026-11-03T16:10:00+08:00",
            total_strokes=6040,
        )
        d = diff(prev, curr)
        assert "10min gap" in d.summary
        assert "40 new strokes" in d.summary
        assert "4.0/min" in d.summary
        assert "restarted" not in d.summary

    def test_restart_summary(self):
        prev = _snap(
            ts="2026-11-03T16:00:00+08:00",
            writer_running=False,
            batch_running=False,
            writer_pid=None,
            batch_pid=None,
            total_strokes=6000,
            uncommitted_files=7,
        )
        curr = _snap(
            ts="2026-11-03T16:05:00+08:00",
            writer_running=True,
            batch_running=True,
            writer_pid=2000,
            batch_pid=2001,
            total_strokes=6010,
            uncommitted_files=0,
        )
        d = diff(prev, curr)
        assert "writer restarted" in d.summary
        assert "batch restarted" in d.summary
        assert "backlog cleared" in d.summary

    def test_stall_in_summary(self):
        prev = _snap(stall_detected=False)
        curr = _snap(stall_detected=True)
        d = diff(prev, curr)
        assert "STALL" in d.summary

    def test_no_change_summary(self):
        snap = _snap()
        d = diff(snap, snap)
        assert d.summary == "no change"


# ---------------------------------------------------------------------------
# diff — edge cases
# ---------------------------------------------------------------------------


class TestDiffEdgeCases:
    def test_empty_dicts(self):
        d = diff({}, {})
        assert d.elapsed_seconds == 0.0
        assert d.strokes_produced == 0
        assert d.writer_downtime == "unknown"

    def test_missing_fields_use_defaults(self):
        prev = {"ts": "2026-11-03T16:00:00+08:00"}
        curr = {"ts": "2026-11-03T16:10:00+08:00"}
        d = diff(prev, curr)
        assert d.elapsed_seconds == 600.0
        assert d.strokes_produced == 0

    def test_to_dict_serialization(self):
        prev = _snap(
            ts="2026-11-03T16:00:00+08:00",
            total_strokes=6000,
        )
        curr = _snap(
            ts="2026-11-03T16:10:00+08:00",
            total_strokes=6050,
        )
        d = diff(prev, curr)
        result = d.to_dict()
        assert isinstance(result, dict)
        assert result["strokes_produced"] == 50
        assert result["elapsed_seconds"] == 600.0
        assert isinstance(result["summary"], str)


# ---------------------------------------------------------------------------
# diff_many
# ---------------------------------------------------------------------------


class TestDiffMany:
    def test_three_snapshots(self):
        snaps = [
            _snap(ts="2026-11-03T16:00:00+08:00", total_strokes=6000),
            _snap(ts="2026-11-03T16:10:00+08:00", total_strokes=6040),
            _snap(ts="2026-11-03T16:20:00+08:00", total_strokes=6080),
        ]
        deltas = diff_many(snaps)
        assert len(deltas) == 2
        assert deltas[0].strokes_produced == 40
        assert deltas[1].strokes_produced == 40

    def test_single_snapshot(self):
        snaps = [_snap()]
        assert diff_many(snaps) == []

    def test_empty_list(self):
        assert diff_many([]) == []

    def test_chain_with_restart(self):
        snaps = [
            _snap(
                ts="2026-11-03T16:00:00+08:00",
                writer_running=True,
                writer_pid=1000,
                total_strokes=6000,
            ),
            _snap(
                ts="2026-11-03T16:10:00+08:00",
                writer_running=False,
                writer_pid=None,
                total_strokes=6000,
            ),
            _snap(
                ts="2026-11-03T16:15:00+08:00",
                writer_running=True,
                writer_pid=2000,
                total_strokes=6010,
            ),
        ]
        deltas = diff_many(snaps)
        assert len(deltas) == 2
        # first interval: writer died
        assert deltas[0].writer_restarted is False
        assert deltas[0].strokes_produced == 0
        # second interval: writer came back
        assert deltas[1].writer_restarted is True
        assert deltas[1].writer_downtime == "was_down"
        assert deltas[1].strokes_produced == 10
