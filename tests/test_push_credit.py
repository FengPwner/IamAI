"""Tests for iamai.push_credit — push reliability tracker.

Covers:
  - empty log produces zero reliability
  - recency weight decay at all breakpoints
  - success rate computation from mixed events
  - failure streak counting from tail
  - reliability formula: rate × recency × streak_penalty
  - record_event / load_events round-trip
  - malformed log lines are skipped gracefully
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from iamai.push_credit import (
    PushEvent,
    Outcome,
    compute_recency_weight,
    compute_reliability,
    load_events,
    record_event,
    ReliabilityReport,
    CREDIT_LOG,
    DATA_DIR,
)


# -- fixtures ---------------------------------------------------------------

@pytest.fixture
def tmp_log(tmp_path, monkeypatch):
    """redirect CREDIT_LOG to a temp directory for isolation."""
    import iamai.push_credit as mod
    monkeypatch.setattr(mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mod, "CREDIT_LOG", tmp_path / "push_credit.jsonl")
    return tmp_path / "push_credit.jsonl"


def _event(outcome: str, hours_ago: float = 0.0, reason: str = "") -> PushEvent:
    """helper: build a PushEvent at a given offset from now."""
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return PushEvent(timestamp=ts, outcome=outcome, reason=reason)


# -- recency weight ---------------------------------------------------------

class TestRecencyWeight:
    def test_just_now_is_full_weight(self):
        assert compute_recency_weight(0.0) == 1.0

    def test_one_hour_is_full_weight(self):
        assert compute_recency_weight(1.0) == 1.0

    def test_twelve_hours_decays(self):
        w = compute_recency_weight(12.0)
        assert 0.5 < w < 1.0

    def test_twenty_four_hours_is_half(self):
        w = compute_recency_weight(24.0)
        assert abs(w - 0.5) < 0.01

    def test_forty_eight_hours_between_half_and_tenth(self):
        w = compute_recency_weight(48.0)
        assert 0.1 < w < 0.5

    def test_seventy_two_hours_is_tenth(self):
        w = compute_recency_weight(72.0)
        assert abs(w - 0.1) < 0.01

    def test_beyond_seventy_two_stays_tenth(self):
        assert compute_recency_weight(100.0) == 0.1
        assert compute_recency_weight(1000.0) == 0.1

    def test_negative_clamped_to_zero(self):
        assert compute_recency_weight(-5.0) == 1.0


# -- reliability computation ------------------------------------------------

class TestComputeReliability:
    def test_empty_log_is_zero(self):
        report = compute_reliability([])
        assert report.total_attempts == 0
        assert report.reliability == 0.0
        assert report.failure_streak == 0

    def test_all_successes_recent(self):
        events = [_event("ok", 0.5), _event("ok", 1.5), _event("ok", 2.5)]
        report = compute_reliability(events)
        assert report.total_attempts == 3
        assert report.successes == 3
        assert report.success_rate == 1.0
        assert report.failure_streak == 0
        # recent + 100% success → high reliability
        assert report.reliability >= 0.9

    def test_all_failures(self):
        events = [_event("fail", 0.5), _event("fail", 1.0)]
        report = compute_reliability(events)
        assert report.success_rate == 0.0
        assert report.failure_streak == 2
        assert report.reliability == 0.0

    def test_mixed_success_rate(self):
        events = [
            _event("ok", 10.0),
            _event("fail", 8.0),
            _event("ok", 6.0),
            _event("ok", 4.0),
        ]
        report = compute_reliability(events)
        assert report.total_attempts == 4
        assert report.successes == 3
        assert abs(report.success_rate - 0.75) < 0.001
        assert report.failure_streak == 0  # last was ok

    def test_failure_streak_from_tail(self):
        events = [
            _event("ok", 5.0),
            _event("fail", 4.0),
            _event("ok", 3.0),
            _event("fail", 2.0),
            _event("fail", 1.0),
            _event("fail", 0.5),
        ]
        report = compute_reliability(events)
        assert report.failure_streak == 3

    def test_streak_penalty_reduces_reliability(self):
        # 3 successes then 3 failures: rate=0.5, streak=3
        events = [
            _event("ok", 6.0),
            _event("ok", 5.0),
            _event("ok", 4.0),
            _event("fail", 3.0),
            _event("fail", 2.0),
            _event("fail", 1.0),
        ]
        report = compute_reliability(events)
        # streak_penalty = 1.0 - 3*0.15 = 0.55
        # reliability = 0.5 × recency(~0.98) × 0.55 ≈ 0.27
        assert report.reliability < 0.35

    def test_single_success(self):
        events = [_event("ok", 0.1)]
        report = compute_reliability(events)
        assert report.total_attempts == 1
        assert report.success_rate == 1.0
        assert report.reliability > 0.9

    def test_malformed_timestamp_handled(self):
        events = [PushEvent(timestamp="not-a-date", outcome="ok")]
        report = compute_reliability(events)
        assert report.hours_since_last == float("inf")
        assert report.recency_weight == 0.1


# -- log i/o ----------------------------------------------------------------

class TestLogIO:
    def test_record_and_load(self, tmp_log):
        event = _event("ok", 1.0)
        record_event(event)
        record_event(_event("fail", 0.5, reason="rejected"))

        loaded = load_events()
        assert len(loaded) == 2
        assert loaded[0].outcome == "ok"
        assert loaded[1].outcome == "fail"
        assert loaded[1].reason == "rejected"

    def test_load_nonexistent_returns_empty(self, tmp_log):
        assert load_events() == []

    def test_load_with_malformed_lines(self, tmp_log):
        from dataclasses import asdict as _asdict
        tmp_log.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_log, "w", encoding="utf-8") as f:
            f.write(json.dumps(_asdict(_event("ok", 1.0))) + "\n")
            f.write("this is not json\n")
            f.write(json.dumps(_asdict(_event("fail", 0.5))) + "\n")

        loaded = load_events()
        assert len(loaded) == 2  # malformed line skipped

    def test_load_with_limit(self, tmp_log):
        for i in range(10):
            record_event(_event("ok", float(10 - i)))

        loaded = load_events(limit=3)
        assert len(loaded) == 3

    def test_empty_lines_ignored(self, tmp_log):
        tmp_log.parent.mkdir(parents=True, exist_ok=True)
        tmp_log.write_text("\n\n\n", encoding="utf-8")
        assert load_events() == []


# -- helpers: asdict for manual construction --------------------------------

from dataclasses import asdict  # noqa: E402 (re-import is idempotent)
