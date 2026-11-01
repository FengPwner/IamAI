"""Tests for snippets/stale_check.py — process freshness classifier."""

from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from stale_check import StaleChecker, FRESH, STALE, EXPIRED  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _now():
    return datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)


def _ago(seconds: float) -> datetime:
    return _now() - timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


def test_default_threshold_and_grace():
    sc = StaleChecker()
    assert sc.threshold_s == 300
    assert sc.grace_s == 300
    assert sc.total_deadline_s == 600


def test_custom_threshold_and_grace():
    sc = StaleChecker(threshold_s=60, grace_s=120)
    assert sc.threshold_s == 60
    assert sc.grace_s == 120
    assert sc.total_deadline_s == 180


def test_negative_threshold_raises():
    with pytest.raises(ValueError, match="threshold_s"):
        StaleChecker(threshold_s=-1)


def test_negative_grace_raises():
    with pytest.raises(ValueError, match="grace_s"):
        StaleChecker(grace_s=-10)


def test_zero_threshold_and_grace():
    sc = StaleChecker(threshold_s=0, grace_s=0)
    assert sc.total_deadline_s == 0


# ---------------------------------------------------------------------------
# FRESH verdict
# ---------------------------------------------------------------------------


def test_fresh_when_event_within_threshold():
    sc = StaleChecker(threshold_s=60, grace_s=120)
    assert sc.check(_ago(30), now=_now()) == FRESH


def test_fresh_at_exact_threshold():
    sc = StaleChecker(threshold_s=60, grace_s=120)
    assert sc.check(_ago(60), now=_now()) == FRESH


def test_fresh_with_zero_age():
    sc = StaleChecker(threshold_s=60, grace_s=120)
    assert sc.check(_now(), now=_now()) == FRESH


def test_fresh_with_future_event():
    """Clock skew: event timestamp is in the future — treat as fresh."""
    sc = StaleChecker(threshold_s=60, grace_s=120)
    future = _now() + timedelta(seconds=30)
    assert sc.check(future, now=_now()) == FRESH


# ---------------------------------------------------------------------------
# STALE verdict
# ---------------------------------------------------------------------------


def test_stale_when_beyond_threshold_within_grace():
    sc = StaleChecker(threshold_s=60, grace_s=120)
    assert sc.check(_ago(90), now=_now()) == STALE


def test_stale_at_threshold_plus_one():
    sc = StaleChecker(threshold_s=60, grace_s=120)
    assert sc.check(_ago(61), now=_now()) == STALE


def test_stale_at_grace_boundary():
    sc = StaleChecker(threshold_s=60, grace_s=120)
    # threshold + grace = 180s; exactly at boundary is STALE (<=)
    assert sc.check(_ago(180), now=_now()) == STALE


# ---------------------------------------------------------------------------
# EXPIRED verdict
# ---------------------------------------------------------------------------


def test_expired_when_beyond_grace():
    sc = StaleChecker(threshold_s=60, grace_s=120)
    assert sc.check(_ago(200), now=_now()) == EXPIRED


def test_expired_at_one_second_past_grace():
    sc = StaleChecker(threshold_s=60, grace_s=120)
    assert sc.check(_ago(181), now=_now()) == EXPIRED


def test_expired_with_large_age():
    sc = StaleChecker(threshold_s=60, grace_s=120)
    assert sc.check(_ago(9999), now=_now()) == EXPIRED


def test_expired_with_zero_threshold_and_grace():
    sc = StaleChecker(threshold_s=0, grace_s=0)
    assert sc.check(_ago(1), now=_now()) == EXPIRED


# ---------------------------------------------------------------------------
# naive datetime handling (no timezone)
# ---------------------------------------------------------------------------


def test_naive_datetime_treated_as_utc():
    sc = StaleChecker(threshold_s=60, grace_s=120)
    naive_now = datetime(2026, 11, 1, 12, 0, 0)  # no tzinfo
    naive_event = naive_now - timedelta(seconds=30)
    assert sc.check(naive_event, now=naive_now) == FRESH


def test_naive_event_with_tz_now():
    sc = StaleChecker(threshold_s=60, grace_s=120)
    naive_event = datetime(2026, 11, 1, 11, 59, 0)  # no tzinfo
    assert sc.check(naive_event, now=_now()) == FRESH


# ---------------------------------------------------------------------------
# age_seconds
# ---------------------------------------------------------------------------


def test_age_seconds_basic():
    sc = StaleChecker()
    age = sc.age_seconds(_ago(42), now=_now())
    assert age == pytest.approx(42.0, abs=0.1)


def test_age_seconds_zero():
    sc = StaleChecker()
    assert sc.age_seconds(_now(), now=_now()) == pytest.approx(0.0)


def test_age_seconds_negative_for_future():
    sc = StaleChecker()
    future = _now() + timedelta(seconds=10)
    assert sc.age_seconds(future, now=_now()) < 0


# ---------------------------------------------------------------------------
# deadline
# ---------------------------------------------------------------------------


def test_deadline_calculation():
    sc = StaleChecker(threshold_s=60, grace_s=120)
    event = _now()
    dl = sc.deadline(event)
    expected = event + timedelta(seconds=180)
    assert dl == expected


def test_deadline_with_naive_event():
    sc = StaleChecker(threshold_s=60, grace_s=120)
    naive_event = datetime(2026, 11, 1, 12, 0, 0)
    dl = sc.deadline(naive_event)
    assert dl.tzinfo is not None  # should be timezone-aware now


# ---------------------------------------------------------------------------
# check_count
# ---------------------------------------------------------------------------


def test_check_count_increments():
    sc = StaleChecker(threshold_s=60, grace_s=120)
    assert sc.check_count == 0
    sc.check(_now(), now=_now())
    sc.check(_now(), now=_now())
    sc.check(_now(), now=_now())
    assert sc.check_count == 3


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


def test_repr_contains_config():
    sc = StaleChecker(threshold_s=60, grace_s=120)
    r = repr(sc)
    assert "60" in r
    assert "120" in r
    assert "checks=0" in r


# ---------------------------------------------------------------------------
# integration: simulate a writer heartbeat
# ---------------------------------------------------------------------------


def test_writer_heartbeat_lifecycle():
    """Simulate a writer that stops producing and watch verdicts change."""
    sc = StaleChecker(threshold_s=15, grace_s=30)

    # writer producing every 15s
    last_event = _now()
    assert sc.check(last_event, now=_now()) == FRESH

    # writer stalls: 20s pass (beyond 15s threshold)
    assert sc.check(last_event, now=_now() + timedelta(seconds=20)) == STALE

    # writer stalls longer: 50s pass (beyond 15+30=45s deadline)
    assert sc.check(last_event, now=_now() + timedelta(seconds=50)) == EXPIRED

    # writer recovers
    new_event = _now() + timedelta(seconds=50)
    assert sc.check(new_event, now=new_event) == FRESH
