"""Tests for the warmup_until parameter on heartbeat.report().

After a container reclamation and process restart, the heartbeat reads
the last stroke timestamp from before the death.  The gap between that
timestamp and 'now' is always larger than 2x cadence, which triggers a
false STALL.  The warmup window lets the caller say 'the writer just
restarted; give it a minute before calling it stalled.'
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iamai.heartbeat import report


def _history_with_old_stroke():
    """One stroke from 5 minutes ago — enough to look stalled at 15s cadence."""
    five_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    return [{"at": five_min_ago, "kind": "thought", "path": "docs/THOUGHTS.md"}]


def test_stall_without_warmup():
    """Without warmup_until, a 5-minute gap at 15s cadence reports stalled."""
    history = _history_with_old_stroke()
    now = datetime.now(timezone.utc).isoformat()
    rep = report(history, since=None, interval=600, now=now, every=15)
    assert rep["stalled"] is True
    assert rep["warmup_active"] is False


def test_warmup_suppresses_stall():
    """Inside the warmup window, stall is suppressed even with a large gap."""
    history = _history_with_old_stroke()
    now = datetime.now(timezone.utc)
    warmup_until = (now + timedelta(seconds=30)).isoformat()
    rep = report(history, since=None, interval=600, now=now.isoformat(), every=15, warmup_until=warmup_until)
    assert rep["stalled"] is False
    assert rep["warmup_active"] is True


def test_warmup_expired_does_not_suppress():
    """After the warmup window closes, stall fires normally."""
    history = _history_with_old_stroke()
    now = datetime.now(timezone.utc)
    # Warmup already expired: deadline is in the past.
    warmup_until = (now - timedelta(seconds=10)).isoformat()
    rep = report(history, since=None, interval=600, now=now.isoformat(), every=15, warmup_until=warmup_until)
    assert rep["stalled"] is True
    assert rep["warmup_active"] is False


def test_warmup_with_no_stall():
    """When there is no stall to suppress, warmup_active stays False."""
    recent = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    history = [{"at": recent, "kind": "note", "path": "notes/test.md"}]
    now = datetime.now(timezone.utc).isoformat()
    warmup_until = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    rep = report(history, since=None, interval=600, now=now, every=15, warmup_until=warmup_until)
    assert rep["stalled"] is False
    assert rep["warmup_active"] is False


def test_warmup_none_means_disabled():
    """warmup_until=None (the default) behaves exactly as before."""
    history = _history_with_old_stroke()
    now = datetime.now(timezone.utc).isoformat()
    rep = report(history, since=None, interval=600, now=now, every=15, warmup_until=None)
    assert rep["stalled"] is True
    assert rep["warmup_active"] is False


def test_warmup_active_in_return_dict():
    """warmup_active is always present in the result, even when False."""
    history = []
    now = datetime.now(timezone.utc).isoformat()
    rep = report(history, since=None, interval=600, now=now, every=15)
    assert "warmup_active" in rep
    assert rep["warmup_active"] is False


def test_warmup_accepts_datetime_object():
    """warmup_until accepts a datetime object, not just an ISO string."""
    history = _history_with_old_stroke()
    now = datetime.now(timezone.utc)
    warmup_until = now + timedelta(seconds=30)  # datetime object
    rep = report(history, since=None, interval=600, now=now.isoformat(), every=15, warmup_until=warmup_until)
    assert rep["stalled"] is False
    assert rep["warmup_active"] is True
