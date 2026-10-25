"""Tests for restart_quality — verify a restart actually fixed things.

A process that restarts but produces no output is not recovered; it is
a zombie with a pid. These tests ensure the verdict system correctly
distinguishes alive, healthy, recovered, and failed states.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from iamai.restart_quality import (
    restart_quality,
    restart_report,
    DEFAULT_GRACE_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ts(offset_seconds: int, base: str = "2026-10-18T03:00:00+00:00") -> str:
    """Return an ISO timestamp offset by the given seconds from base."""
    base_dt = datetime.fromisoformat(base)
    return (base_dt + timedelta(seconds=offset_seconds)).isoformat()


# ---------------------------------------------------------------------------
# failed: process dead, no strokes
# ---------------------------------------------------------------------------


def test_dead_no_strokes_is_failed():
    result = restart_quality(
        restarted_at=_ts(0),
        strokes_after=[],
        process_alive=False,
    )
    assert result["verdict"] == "failed"
    assert result["strokes"] == 0
    assert result["first_stroke_seconds"] is None


def test_dead_timeout_is_failed():
    """Process is dead but strokes existed — still failed if no new ones."""
    result = restart_quality(
        restarted_at=_ts(0),
        strokes_after=[],
        process_alive=False,
        timeout_seconds=60,
    )
    assert result["verdict"] == "failed"


# ---------------------------------------------------------------------------
# alive: process running but no output yet (within grace)
# ---------------------------------------------------------------------------


def test_alive_within_grace():
    """Process just started, no strokes yet — alive, not failed."""
    # We fake "now" by making restarted_at very recent
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(seconds=5)).isoformat()
    result = restart_quality(
        restarted_at=recent,
        strokes_after=[],
        process_alive=True,
        grace_seconds=30,
    )
    assert result["verdict"] == "alive"
    assert result["strokes"] == 0


def test_alive_past_grace_before_timeout():
    """Process running past grace window but under timeout — still alive."""
    now = datetime.now(timezone.utc)
    past_grace = (now - timedelta(seconds=45)).isoformat()
    result = restart_quality(
        restarted_at=past_grace,
        strokes_after=[],
        process_alive=True,
        grace_seconds=30,
        timeout_seconds=120,
    )
    assert result["verdict"] == "alive"


# ---------------------------------------------------------------------------
# healthy: at least one stroke but cadence not yet established
# ---------------------------------------------------------------------------


def test_single_stroke_is_healthy():
    result = restart_quality(
        restarted_at=_ts(0),
        strokes_after=[_ts(18)],
        process_alive=True,
        expected_cadence=15,
    )
    assert result["verdict"] == "healthy"
    assert result["strokes"] == 1
    assert result["first_stroke_seconds"] == 18.0
    assert result["cadence_ok"] is False


def test_two_strokes_bad_cadence_is_healthy():
    """Two strokes but intervals way too long — healthy, not recovered."""
    result = restart_quality(
        restarted_at=_ts(0),
        strokes_after=[_ts(10), _ts(200)],
        process_alive=True,
        expected_cadence=15,
    )
    assert result["verdict"] == "healthy"
    assert result["cadence_ok"] is False


# ---------------------------------------------------------------------------
# recovered: cadence stabilized
# ---------------------------------------------------------------------------


def test_three_strokes_good_cadence_is_recovered():
    result = restart_quality(
        restarted_at=_ts(0),
        strokes_after=[_ts(15), _ts(30), _ts(45)],
        process_alive=True,
        expected_cadence=15,
    )
    assert result["verdict"] == "recovered"
    assert result["strokes"] == 3
    assert result["cadence_ok"] is True


def test_recovered_with_jitter_within_tolerance():
    """Intervals vary (14, 16, 15) — all within 2x of expected 15."""
    result = restart_quality(
        restarted_at=_ts(0),
        strokes_after=[_ts(14), _ts(30), _ts(45)],
        process_alive=True,
        expected_cadence=15,
    )
    assert result["verdict"] == "recovered"
    assert result["cadence_ok"] is True


def test_recovered_requires_two_strokes():
    """One stroke cannot be recovered — cadence needs at least 2 points."""
    result = restart_quality(
        restarted_at=_ts(0),
        strokes_after=[_ts(15)],
        process_alive=True,
        expected_cadence=15,
    )
    assert result["verdict"] == "healthy"
    assert result["cadence_ok"] is False


# ---------------------------------------------------------------------------
# failed: timeout with no strokes
# ---------------------------------------------------------------------------


def test_timeout_with_no_strokes_is_failed():
    now = datetime.now(timezone.utc)
    long_ago = (now - timedelta(seconds=200)).isoformat()
    result = restart_quality(
        restarted_at=long_ago,
        strokes_after=[],
        process_alive=True,
        timeout_seconds=120,
    )
    assert result["verdict"] == "failed"


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


def test_strokes_before_restart_ignored_by_cadence():
    """Strokes that happen before the restart timestamp are still counted
    (the function trusts the caller to only pass post-restart strokes)."""
    result = restart_quality(
        restarted_at=_ts(100),
        strokes_after=[_ts(50), _ts(60)],  # before restart
        process_alive=True,
        expected_cadence=15,
    )
    # Function processes them; negative first_stroke_seconds signals pre-restart
    assert result["strokes"] == 2
    assert result["first_stroke_seconds"] < 0


def test_unsorted_strokes_handled():
    """Strokes passed out of order should still produce correct verdict."""
    result = restart_quality(
        restarted_at=_ts(0),
        strokes_after=[_ts(45), _ts(15), _ts(30)],
        process_alive=True,
        expected_cadence=15,
    )
    assert result["verdict"] == "recovered"
    assert result["strokes"] == 3
    assert result["first_stroke_seconds"] == 15.0


def test_empty_strokes_with_dead_process():
    result = restart_quality(
        restarted_at=_ts(0),
        strokes_after=[],
        process_alive=False,
    )
    assert result["verdict"] == "failed"
    assert result["strokes"] == 0


# ---------------------------------------------------------------------------
# restart_report
# ---------------------------------------------------------------------------


def test_report_recovered():
    report = restart_report(
        restarted_at=_ts(0),
        strokes_after=[_ts(15), _ts(30), _ts(45)],
        process_alive=True,
        expected_cadence=15,
    )
    assert "recovered" in report
    assert "3 strokes" in report
    assert "cadence ok" in report


def test_report_healthy():
    report = restart_report(
        restarted_at=_ts(0),
        strokes_after=[_ts(20)],
        process_alive=True,
        expected_cadence=15,
    )
    assert "healthy" in report
    assert "1 stroke" in report


def test_report_failed():
    now = datetime.now(timezone.utc)
    long_ago = (now - timedelta(seconds=200)).isoformat()
    report = restart_report(
        restarted_at=long_ago,
        strokes_after=[],
        process_alive=True,
        timeout_seconds=120,
    )
    assert "failed" in report


def test_report_alive():
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(seconds=5)).isoformat()
    report = restart_report(
        restarted_at=recent,
        strokes_after=[],
        process_alive=True,
    )
    assert "alive" in report


# ---------------------------------------------------------------------------
# tolerance boundary tests
# ---------------------------------------------------------------------------


def test_cadence_at_exactly_2x_boundary():
    """Median interval at exactly 2x expected — should still count as ok."""
    result = restart_quality(
        restarted_at=_ts(0),
        strokes_after=[_ts(30), _ts(60)],  # interval = 30, exactly 2x of 15
        process_alive=True,
        expected_cadence=15,
    )
    assert result["cadence_ok"] is True
    assert result["verdict"] == "recovered"


def test_cadence_beyond_2x_boundary():
    """Median interval just over 2x — cadence not ok."""
    result = restart_quality(
        restarted_at=_ts(0),
        strokes_after=[_ts(31), _ts(62)],  # interval = 31, > 2x of 15
        process_alive=True,
        expected_cadence=15,
    )
    assert result["cadence_ok"] is False
    assert result["verdict"] == "healthy"  # has strokes but bad cadence


def test_many_strokes_with_one_outlier():
    """Five good intervals, one bad — median should still pass."""
    result = restart_quality(
        restarted_at=_ts(0),
        strokes_after=[
            _ts(15), _ts(30), _ts(45), _ts(60), _ts(75), _ts(300),
        ],
        process_alive=True,
        expected_cadence=15,
    )
    assert result["cadence_ok"] is True
    assert result["verdict"] == "recovered"
