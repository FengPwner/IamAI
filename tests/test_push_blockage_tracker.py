"""Tests for iamai.push_blockage_tracker — push blockage event tracking."""

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from pathlib import Path

import pytest

from iamai.push_blockage_tracker import (
    BlockageEvent,
    probe,
    get_open_event,
    get_event_history,
    format_summary,
    _load_state,
    _save_state,
    _clear_state,
    _append_event,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def clean_state(tmp_path, monkeypatch):
    """redirect data dir to tmp_path so tests don't pollute real data."""
    import iamai.push_blockage_tracker as mod
    monkeypatch.setattr(mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "EVENTS_LOG", tmp_path / "push_blockage_events.jsonl")
    monkeypatch.setattr(mod, "STATE_CACHE", tmp_path / "push_blockage_state.json")
    yield tmp_path


# ---------------------------------------------------------------------------
# BlockageEvent dataclass
# ---------------------------------------------------------------------------

class TestBlockageEvent:
    def test_is_open_when_no_ended_at(self):
        e = BlockageEvent(started_at="2026-10-26T00:00:00+08:00", cause="MISSING_KEY")
        assert e.is_open is True

    def test_is_closed_when_ended_at_set(self):
        e = BlockageEvent(
            started_at="2026-10-26T00:00:00+08:00",
            cause="MISSING_KEY",
            ended_at="2026-10-26T02:00:00+08:00",
        )
        assert e.is_open is False

    def test_duration_hours_closed(self):
        e = BlockageEvent(
            started_at="2026-10-26T00:00:00+00:00",
            cause="NETWORK",
            ended_at="2026-10-26T03:30:00+00:00",
        )
        assert abs(e.duration_hours - 3.5) < 0.01

    def test_duration_hours_open_uses_now(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        e = BlockageEvent(started_at=past, cause="MISSING_KEY")
        assert e.duration_hours >= 1.99
        assert e.duration_hours < 2.1

    def test_duration_never_negative(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        e = BlockageEvent(started_at=future, cause="UNKNOWN")
        assert e.duration_hours == 0.0

    def test_to_dict_includes_computed_fields(self):
        e = BlockageEvent(
            started_at="2026-10-26T00:00:00+00:00",
            cause="UNREGISTERED_KEY",
            peak_unpushed=50,
        )
        d = e.to_dict()
        assert "duration_hours" in d
        assert "is_open" in d
        assert d["is_open"] is True
        assert d["peak_unpushed"] == 50

    def test_visit_count_default(self):
        e = BlockageEvent(started_at="2026-10-26T00:00:00+08:00", cause="X")
        assert e.visit_count == 1

    def test_visit_timestamps_default_empty(self):
        e = BlockageEvent(started_at="2026-10-26T00:00:00+08:00", cause="X")
        assert e.visit_timestamps == []

    def test_peak_unpushed_default_zero(self):
        e = BlockageEvent(started_at="2026-10-26T00:00:00+08:00", cause="X")
        assert e.peak_unpushed == 0


# ---------------------------------------------------------------------------
# state persistence
# ---------------------------------------------------------------------------

class TestStatePersistence:
    def test_load_state_returns_none_when_empty(self, clean_state):
        assert _load_state() is None

    def test_save_and_load_roundtrip(self, clean_state):
        e = BlockageEvent(
            started_at="2026-10-26T00:00:00+08:00",
            cause="MISSING_KEY",
            peak_unpushed=42,
        )
        _save_state(e)
        loaded = _load_state()
        assert loaded is not None
        assert loaded.cause == "MISSING_KEY"
        assert loaded.peak_unpushed == 42

    def test_clear_state_removes_file(self, clean_state):
        e = BlockageEvent(started_at="2026-10-26T00:00:00+08:00", cause="X")
        _save_state(e)
        assert _load_state() is not None
        _clear_state()
        assert _load_state() is None

    def test_clear_state_safe_when_no_file(self, clean_state):
        _clear_state()  # should not raise

    def test_load_state_handles_corrupt_file(self, clean_state):
        cache_file = clean_state / "push_blockage_state.json"
        cache_file.write_text("{invalid json!!")
        assert _load_state() is None

    def test_append_event_creates_log(self, clean_state):
        e = BlockageEvent(
            started_at="2026-10-26T00:00:00+08:00",
            cause="NETWORK",
            ended_at="2026-10-26T01:00:00+08:00",
        )
        _append_event(e)
        log_file = clean_state / "push_blockage_events.jsonl"
        assert log_file.exists()
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["cause"] == "NETWORK"

    def test_append_event_appends_not_overwrites(self, clean_state):
        for i in range(3):
            e = BlockageEvent(
                started_at=f"2026-10-26T0{i}:00:00+08:00",
                cause=f"CAUSE_{i}",
            )
            _append_event(e)
        log_file = clean_state / "push_blockage_events.jsonl"
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 3


# ---------------------------------------------------------------------------
# probe() — push OK
# ---------------------------------------------------------------------------

class TestProbeOk:
    def test_probe_ok_when_no_open_event(self, clean_state):
        result = probe(push_ok=True)
        assert result is None

    def test_probe_ok_closes_open_event(self, clean_state):
        # first create an open event
        probe(push_ok=False, cause="MISSING_KEY", unpushed_count=10)
        assert get_open_event() is not None
        # now probe ok
        result = probe(push_ok=True)
        assert result is not None
        assert result.ended_at is not None
        assert result.cause == "MISSING_KEY"
        # state should be cleared
        assert get_open_event() is None

    def test_probe_ok_records_event_to_log(self, clean_state):
        probe(push_ok=False, cause="NETWORK", unpushed_count=5)
        probe(push_ok=True)
        events = get_event_history()
        assert len(events) == 1
        assert events[0]["cause"] == "NETWORK"
        assert events[0]["is_open"] is False


# ---------------------------------------------------------------------------
# probe() — push FAIL
# ---------------------------------------------------------------------------

class TestProbeFail:
    def test_probe_fail_creates_new_event(self, clean_state):
        event = probe(push_ok=False, cause="UNREGISTERED_KEY",
                      unpushed_count=79)
        assert event is not None
        assert event.cause == "UNREGISTERED_KEY"
        assert event.peak_unpushed == 79
        assert event.visit_count == 1

    def test_probe_fail_extends_existing_event(self, clean_state):
        probe(push_ok=False, cause="MISSING_KEY", unpushed_count=10)
        event = probe(push_ok=False, cause="UNREGISTERED_KEY",
                      unpushed_count=50)
        assert event.visit_count == 2
        assert event.cause == "UNREGISTERED_KEY"  # updated
        assert event.peak_unpushed == 50  # updated

    def test_probe_fail_peak_only_goes_up(self, clean_state):
        probe(push_ok=False, cause="X", unpushed_count=100)
        event = probe(push_ok=False, cause="X", unpushed_count=30)
        assert event.peak_unpushed == 100  # not overwritten

    def test_probe_fail_unknown_cause_preserves_existing(self, clean_state):
        probe(push_ok=False, cause="MISSING_KEY", unpushed_count=10)
        event = probe(push_ok=False, cause="UNKNOWN", unpushed_count=20)
        assert event.cause == "MISSING_KEY"  # not overwritten by UNKNOWN

    def test_probe_fail_records_visit_timestamps(self, clean_state):
        probe(push_ok=False, cause="X", unpushed_count=1)
        event = probe(push_ok=False, cause="X", unpushed_count=2)
        assert len(event.visit_timestamps) == 2

    def test_multiple_probes_increment_visits(self, clean_state):
        for i in range(5):
            probe(push_ok=False, cause="X", unpushed_count=i)
        event = get_open_event()
        assert event.visit_count == 5


# ---------------------------------------------------------------------------
# get_open_event()
# ---------------------------------------------------------------------------

class TestGetOpenEvent:
    def test_returns_none_initially(self, clean_state):
        assert get_open_event() is None

    def test_returns_event_after_probe_fail(self, clean_state):
        probe(push_ok=False, cause="X", unpushed_count=1)
        event = get_open_event()
        assert event is not None
        assert event.is_open

    def test_returns_none_after_recovery(self, clean_state):
        probe(push_ok=False, cause="X", unpushed_count=1)
        probe(push_ok=True)
        assert get_open_event() is None


# ---------------------------------------------------------------------------
# get_event_history()
# ---------------------------------------------------------------------------

class TestGetEventHistory:
    def test_empty_history(self, clean_state):
        assert get_event_history() == []

    def test_history_after_events(self, clean_state):
        for _ in range(3):
            probe(push_ok=False, cause="X", unpushed_count=1)
            probe(push_ok=True)
        events = get_event_history()
        assert len(events) == 3

    def test_history_limit(self, clean_state):
        for i in range(5):
            probe(push_ok=False, cause=f"C{i}", unpushed_count=1)
            probe(push_ok=True)
        events = get_event_history(limit=2)
        assert len(events) == 2


# ---------------------------------------------------------------------------
# format_summary()
# ---------------------------------------------------------------------------

class TestFormatSummary:
    def test_open_event_format(self):
        e = BlockageEvent(
            started_at="2026-10-26T00:00:00+08:00",
            cause="MISSING_KEY",
            peak_unpushed=79,
        )
        s = format_summary(e)
        assert "OPEN" in s
        assert "MISSING_KEY" in s
        assert "79" in s

    def test_closed_event_format(self):
        e = BlockageEvent(
            started_at="2026-10-26T00:00:00+08:00",
            cause="NETWORK",
            ended_at="2026-10-26T02:00:00+08:00",
            peak_unpushed=10,
        )
        s = format_summary(e)
        assert "CLOSED" in s
        assert "ended" in s

    def test_duration_appears_in_summary(self):
        e = BlockageEvent(
            started_at="2026-10-26T00:00:00+00:00",
            cause="X",
            ended_at="2026-10-26T05:00:00+00:00",
        )
        s = format_summary(e)
        assert "5.0" in s


# ---------------------------------------------------------------------------
# timezone edge cases
# ---------------------------------------------------------------------------

class TestTimezoneEdgeCases:
    def test_naive_timestamps_treated_as_utc(self):
        e = BlockageEvent(
            started_at="2026-10-26T00:00:00",
            cause="X",
            ended_at="2026-10-26T01:00:00",
        )
        assert abs(e.duration_hours - 1.0) < 0.01

    def test_mixed_timezone_handling(self):
        e = BlockageEvent(
            started_at="2026-10-26T00:00:00+00:00",
            cause="X",
            ended_at="2026-10-26T09:00:00+08:00",
        )
        # 09:00+08:00 = 01:00 UTC, so duration is 1 hour
        assert abs(e.duration_hours - 1.0) < 0.01


# ---------------------------------------------------------------------------
# integration: full lifecycle
# ---------------------------------------------------------------------------

class TestFullLifecycle:
    def test_blockage_lifecycle(self, clean_state):
        # push fails — new event
        e1 = probe(push_ok=False, cause="MISSING_KEY", unpushed_count=5)
        assert e1.visit_count == 1
        assert get_open_event() is not None

        # push fails again — event extends
        e2 = probe(push_ok=False, cause="UNREGISTERED_KEY",
                    unpushed_count=20)
        assert e2.visit_count == 2
        assert e2.cause == "UNREGISTERED_KEY"
        assert e2.peak_unpushed == 20

        # push recovers
        e3 = probe(push_ok=True)
        assert e3 is not None
        assert e3.ended_at is not None
        assert get_open_event() is None

        # history shows the closed event
        history = get_event_history()
        assert len(history) == 1
        assert history[0]["visit_count"] == 2
        assert history[0]["peak_unpushed"] == 20

    def test_two_separate_blockage_events(self, clean_state):
        # first blockage
        probe(push_ok=False, cause="NETWORK", unpushed_count=3)
        probe(push_ok=True)

        # second blockage
        probe(push_ok=False, cause="CREDENTIAL_EXPIRED", unpushed_count=7)
        probe(push_ok=True)

        history = get_event_history()
        assert len(history) == 2
        assert history[0]["cause"] == "NETWORK"
        assert history[1]["cause"] == "CREDENTIAL_EXPIRED"
