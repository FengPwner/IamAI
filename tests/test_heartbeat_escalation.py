"""Tests for snippets/heartbeat_escalation.py — tiered heartbeat alert escalation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from heartbeat_escalation import HeartbeatEscalation  # noqa: E402


# ---------------------------------------------------------------------------
# construction & validation
# ---------------------------------------------------------------------------


def test_default_thresholds():
    h = HeartbeatEscalation()
    assert h.level == "ok"
    assert h.consecutive_misses == 0


def test_yellow_after_must_be_at_least_1():
    with pytest.raises(ValueError, match="yellow_after must be >= 1"):
        HeartbeatEscalation(yellow_after=0)


def test_red_after_must_exceed_yellow():
    with pytest.raises(ValueError, match="red_after must be > yellow_after"):
        HeartbeatEscalation(yellow_after=3, red_after=2, critical_after=5)


def test_critical_after_must_exceed_red():
    with pytest.raises(ValueError, match="critical_after must be > red_after"):
        HeartbeatEscalation(yellow_after=1, red_after=4, critical_after=3)


def test_custom_thresholds():
    h = HeartbeatEscalation(yellow_after=1, red_after=2, critical_after=3)
    assert h.level == "ok"


# ---------------------------------------------------------------------------
# miss → escalation curve
# ---------------------------------------------------------------------------


def test_single_miss_stays_ok():
    h = HeartbeatEscalation(yellow_after=2, red_after=4, critical_after=6)
    result = h.miss()
    assert result == "ok"
    assert h.level == "ok"
    assert h.consecutive_misses == 1


def test_escalates_to_yellow_at_threshold():
    h = HeartbeatEscalation(yellow_after=2, red_after=4, critical_after=6)
    h.miss()  # 1 — ok
    result = h.miss()  # 2 — yellow
    assert result == "yellow"
    assert h.level == "yellow"


def test_stays_yellow_between_yellow_and_red():
    h = HeartbeatEscalation(yellow_after=2, red_after=4, critical_after=6)
    h.miss()  # 1
    h.miss()  # 2 → yellow
    result = h.miss()  # 3 — still yellow
    assert result == "yellow"


def test_escalates_to_red_at_threshold():
    h = HeartbeatEscalation(yellow_after=2, red_after=4, critical_after=6)
    for _ in range(3):
        h.miss()
    result = h.miss()  # 4 → red
    assert result == "red"


def test_escalates_to_critical_at_threshold():
    h = HeartbeatEscalation(yellow_after=2, red_after=4, critical_after=6)
    for _ in range(5):
        h.miss()
    result = h.miss()  # 6 → critical
    assert result == "critical"


def test_full_escalation_sequence():
    h = HeartbeatEscalation(yellow_after=1, red_after=3, critical_after=5)
    # miss 1→yellow, 2→yellow, 3→red, 4→red, 5→critical, 6→critical
    expected = ["yellow", "yellow", "red", "red", "critical", "critical"]
    results = []
    for _ in range(6):
        results.append(h.miss())
    assert results == expected


def test_aggressive_thresholds():
    h = HeartbeatEscalation(yellow_after=1, red_after=2, critical_after=3)
    assert h.miss() == "yellow"  # 1
    assert h.miss() == "red"     # 2
    assert h.miss() == "critical"  # 3


# ---------------------------------------------------------------------------
# ping → reset
# ---------------------------------------------------------------------------


def test_ping_resets_to_ok():
    h = HeartbeatEscalation(yellow_after=1, red_after=2, critical_after=3)
    h.miss()  # yellow
    h.miss()  # red
    result = h.ping()
    assert result == "ok"
    assert h.level == "ok"
    assert h.consecutive_misses == 0


def test_ping_after_critical_resets():
    h = HeartbeatEscalation(yellow_after=1, red_after=2, critical_after=3)
    for _ in range(5):
        h.miss()
    assert h.level == "critical"
    h.ping()
    assert h.level == "ok"
    assert h.consecutive_misses == 0


def test_ping_when_already_ok():
    h = HeartbeatEscalation()
    result = h.ping()
    assert result == "ok"
    assert h.history == []  # no escalation happened, no history entry


def test_re_escalation_after_ping():
    h = HeartbeatEscalation(yellow_after=1, red_after=2, critical_after=3)
    h.miss()  # yellow
    h.ping()  # ok
    h.miss()  # yellow again
    assert h.level == "yellow"


# ---------------------------------------------------------------------------
# history tracking
# ---------------------------------------------------------------------------


def test_history_empty_initially():
    h = HeartbeatEscalation()
    assert h.history == []


def test_history_records_escalations():
    h = HeartbeatEscalation(yellow_after=1, red_after=2, critical_after=3)
    h.miss()  # → yellow
    h.miss()  # → red
    h.miss()  # → critical
    assert h.history == ["yellow", "red", "critical"]


def test_history_records_reset_to_ok():
    h = HeartbeatEscalation(yellow_after=1, red_after=2, critical_after=3)
    h.miss()  # yellow
    h.miss()  # red
    h.ping()  # ok
    assert h.history == ["yellow", "red", "ok"]


def test_history_is_copy():
    h = HeartbeatEscalation(yellow_after=1, red_after=2, critical_after=3)
    h.miss()
    hist = h.history
    hist.append("tampered")
    assert h.history == ["yellow"]


def test_history_full_lifecycle():
    h = HeartbeatEscalation(yellow_after=1, red_after=2, critical_after=3)
    h.miss()   # yellow
    h.miss()   # red
    h.ping()   # ok
    h.miss()   # yellow
    h.ping()   # ok
    assert h.history == ["yellow", "red", "ok", "yellow", "ok"]


# ---------------------------------------------------------------------------
# consecutive_misses tracking
# ---------------------------------------------------------------------------


def test_consecutive_misses_increments():
    h = HeartbeatEscalation()
    h.miss()
    h.miss()
    h.miss()
    assert h.consecutive_misses == 3


def test_consecutive_misses_resets_on_ping():
    h = HeartbeatEscalation()
    h.miss()
    h.miss()
    h.ping()
    assert h.consecutive_misses == 0


# ---------------------------------------------------------------------------
# seconds_since
# ---------------------------------------------------------------------------


def test_seconds_since_with_custom_clock():
    h = HeartbeatEscalation(clock=lambda: 100.0)
    assert h.seconds_since(95.0) == 5.0


def test_seconds_since_zero_at_ping_time():
    h = HeartbeatEscalation(clock=lambda: 42.0)
    assert h.seconds_since(42.0) == 0.0


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


def test_repr_ok():
    h = HeartbeatEscalation()
    r = repr(h)
    assert "ok" in r
    assert "misses=0" in r


def test_repr_escalated():
    h = HeartbeatEscalation(yellow_after=1, red_after=2, critical_after=3)
    h.miss()
    r = repr(h)
    assert "yellow" in r
    assert "misses=1" in r


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


def test_large_miss_count():
    h = HeartbeatEscalation(yellow_after=1, red_after=2, critical_after=3)
    for _ in range(1000):
        h.miss()
    assert h.level == "critical"
    assert h.consecutive_misses == 1000


def test_many_ping_miss_cycles():
    h = HeartbeatEscalation(yellow_after=1, red_after=2, critical_after=3)
    for _ in range(50):
        h.miss()  # yellow
        h.ping()  # ok
    assert h.level == "ok"
    assert h.consecutive_misses == 0
    # each cycle: 1 yellow + 1 ok = 2 entries × 50 = 100
    assert len(h.history) == 100


def test_miss_does_not_deescalate():
    """Once escalated, more misses at same level don't change it."""
    h = HeartbeatEscalation(yellow_after=1, red_after=3, critical_after=5)
    h.miss()  # yellow
    h.miss()  # still yellow (not red yet)
    assert h.level == "yellow"
    # history should only have one 'yellow' entry, not two
    assert h.history == ["yellow"]


def test_thresholds_equal_raises():
    with pytest.raises(ValueError):
        HeartbeatEscalation(yellow_after=2, red_after=2, critical_after=5)


def test_thresholds_inverted_raises():
    with pytest.raises(ValueError):
        HeartbeatEscalation(yellow_after=5, red_after=3, critical_after=2)
