#!/usr/bin/env python3
"""Tests for process_death_clock.py."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import pytest

# allow importing from sibling directory
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.process_death_clock import (
    DeathEvent,
    load_ledger,
    save_ledger,
    record_death,
    recent_deaths,
    correlated_pairs,
    death_rate,
    time_since_last_death,
    classify,
    status_report,
    MAX_EVENTS,
    CLUSTER_THRESHOLD,
    STORM_THRESHOLD,
    CORRELATION_WINDOW_SEC,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ledger_path(tmp_path):
    return tmp_path / "death_clock.json"


@pytest.fixture
def sample_events():
    """Five events: two correlated pairs within 60s, one isolated."""
    base = 1_700_000_000.0
    return [
        DeathEvent("writer", base),
        DeathEvent("batch", base + 30),        # correlated with writer
        DeathEvent("writer", base + 600),      # 10 min later
        DeathEvent("batch", base + 660),       # correlated with writer
        DeathEvent("writer", base + 7200),     # 2 hours later, isolated
    ]


# ---------------------------------------------------------------------------
# load / save
# ---------------------------------------------------------------------------


class TestLedgerIO:

    def test_load_nonexistent(self, ledger_path):
        assert load_ledger(ledger_path) == []

    def test_load_corrupt_json(self, ledger_path):
        ledger_path.write_text("{bad json", encoding="utf-8")
        assert load_ledger(ledger_path) == []

    def test_save_and_load_roundtrip(self, ledger_path, sample_events):
        save_ledger(sample_events, ledger_path)
        loaded = load_ledger(ledger_path)
        assert len(loaded) == len(sample_events)
        for orig, loaded_evt in zip(sample_events, loaded):
            assert orig.process == loaded_evt.process
            assert abs(orig.ts - loaded_evt.ts) < 0.01

    def test_save_trims_to_max(self, ledger_path):
        events = [DeathEvent("writer", 1_700_000_000.0 + i)
                  for i in range(MAX_EVENTS + 100)]
        save_ledger(events, ledger_path)
        loaded = load_ledger(ledger_path)
        assert len(loaded) == MAX_EVENTS

    def test_save_custom_max(self, ledger_path):
        events = [DeathEvent("writer", 1_700_000_000.0 + i)
                  for i in range(50)]
        save_ledger(events, ledger_path, max_events=10)
        loaded = load_ledger(ledger_path)
        assert len(loaded) == 10
        # should keep the last 10
        assert loaded[0].ts == 1_700_000_000.0 + 40


# ---------------------------------------------------------------------------
# record_death
# ---------------------------------------------------------------------------


class TestRecordDeath:

    def test_record_appends_event(self, ledger_path):
        record_death("writer", ts=1_700_000_000.0, path=ledger_path)
        events = load_ledger(ledger_path)
        assert len(events) == 1
        assert events[0].process == "writer"

    def test_record_uses_current_time(self, ledger_path):
        before = time.time()
        evt = record_death("batch", path=ledger_path)
        after = time.time()
        assert before <= evt.ts <= after

    def test_record_preserves_pid_and_note(self, ledger_path):
        record_death("writer", ts=1_700_000_000.0, pid=1234,
                     note="OOM killed", path=ledger_path)
        events = load_ledger(ledger_path)
        assert events[0].pid == 1234
        assert events[0].note == "OOM killed"

    def test_multiple_records(self, ledger_path):
        for i in range(5):
            record_death("writer", ts=1_700_000_000.0 + i,
                         path=ledger_path)
        events = load_ledger(ledger_path)
        assert len(events) == 5


# ---------------------------------------------------------------------------
# recent_deaths
# ---------------------------------------------------------------------------


class TestRecentDeaths:

    def test_empty_ledger(self, ledger_path):
        assert recent_deaths(events=[], now=1_700_000_000.0) == []

    def test_all_within_window(self, sample_events):
        now = sample_events[-1].ts + 10
        result = recent_deaths(window_sec=86400, now=now,
                               events=sample_events)
        assert len(result) == 5

    def test_partial_window(self, sample_events):
        # window covers only the last event (7200s after base)
        now = sample_events[-1].ts + 100
        result = recent_deaths(window_sec=3600, now=now,
                               events=sample_events)
        assert len(result) == 1
        assert result[0].ts == sample_events[-1].ts

    def test_exact_boundary(self, sample_events):
        now = sample_events[-1].ts + 3600
        result = recent_deaths(window_sec=3600, now=now,
                               events=sample_events)
        # last event is exactly at the boundary
        assert len(result) == 1


# ---------------------------------------------------------------------------
# correlated_pairs
# ---------------------------------------------------------------------------


class TestCorrelatedPairs:

    def test_no_events(self):
        assert correlated_pairs(events=[]) == []

    def test_single_event(self):
        events = [DeathEvent("writer", 1_700_000_000.0)]
        assert correlated_pairs(events=events) == []

    def test_two_correlated(self, sample_events):
        # first two events are 30s apart — within CORRELATION_WINDOW_SEC
        pairs = correlated_pairs(events=sample_events[:2])
        assert len(pairs) == 1
        assert pairs[0][0].ts == sample_events[0].ts
        assert pairs[0][1].ts == sample_events[1].ts

    def test_two_uncorrelated(self):
        events = [
            DeathEvent("writer", 1_700_000_000.0),
            DeathEvent("batch", 1_700_000_000.0 + 3600),  # 1 hour later
        ]
        assert correlated_pairs(events=events) == []

    def test_sample_events_pairs(self, sample_events):
        pairs = correlated_pairs(events=sample_events)
        # pair 1: events[0] & events[1] (30s apart)
        # pair 2: events[2] & events[3] (60s apart)
        # event[4] is 6540s from event[3], too far
        assert len(pairs) == 2

    def test_custom_window(self):
        events = [
            DeathEvent("writer", 1_700_000_000.0),
            DeathEvent("batch", 1_700_000_000.0 + 200),
        ]
        # default window (120s) — not correlated
        assert len(correlated_pairs(events=events)) == 0
        # wider window (300s) — correlated
        assert len(correlated_pairs(window_sec=300, events=events)) == 1


# ---------------------------------------------------------------------------
# death_rate
# ---------------------------------------------------------------------------


class TestDeathRate:

    def test_empty(self):
        assert death_rate(events=[], now=1_700_000_000.0) == 0.0

    def test_one_per_hour(self, sample_events):
        # place events exactly 1 hour apart
        events = [DeathEvent("writer", 1_700_000_000.0 + i * 3600)
                  for i in range(5)]
        now = events[-1].ts
        rate = death_rate(window_sec=3600, now=now, events=events)
        # boundary event[-2] is exactly at cutoff (>=), so 2 events in window
        assert abs(rate - 2.0) < 0.01

    def test_multiple_in_window(self):
        base = 1_700_000_000.0
        events = [DeathEvent("writer", base + i * 600)
                  for i in range(6)]  # every 10 min
        now = events[-1].ts
        rate = death_rate(window_sec=3600, now=now, events=events)
        # 6 events in 50 min, all within 1h window
        assert abs(rate - 6.0) < 0.01


# ---------------------------------------------------------------------------
# time_since_last_death
# ---------------------------------------------------------------------------


class TestTimeSinceLastDeath:

    def test_empty(self):
        assert time_since_last_death(events=[]) is None

    def test_just_died(self):
        now = 1_700_000_000.0
        events = [DeathEvent("writer", now - 5)]
        result = time_since_last_death(now=now, events=events)
        assert abs(result - 5.0) < 0.01

    def test_long_ago(self):
        events = [DeathEvent("writer", 1_600_000_000.0)]
        result = time_since_last_death(now=1_700_000_000.0, events=events)
        assert abs(result - 100_000_000.0) < 0.01


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


class TestClassify:

    def test_clean(self):
        assert classify(events=[], now=1_700_000_000.0) == "clean"

    def test_isolated(self):
        events = [DeathEvent("writer", 1_700_000_000.0)]
        assert classify(events=events, now=1_700_000_000.0 + 10) == "isolated"

    def test_clustered(self):
        # create CLUSTER_THRESHOLD correlated pairs within 1h
        base = 1_700_000_000.0
        events = []
        for i in range(CLUSTER_THRESHOLD):
            events.append(DeathEvent("writer", base + i * 600))
            events.append(DeathEvent("batch", base + i * 600 + 30))
        now = events[-1].ts + 10
        result = classify(window_sec=3600, now=now, events=events)
        assert result in ("clustered", "storm")

    def test_storm(self):
        base = 1_700_000_000.0
        events = []
        for i in range(STORM_THRESHOLD + 2):
            events.append(DeathEvent("writer", base + i * 60))
            events.append(DeathEvent("batch", base + i * 60 + 10))
        now = events[-1].ts + 10
        result = classify(window_sec=3600, now=now, events=events)
        assert result == "storm"

    def test_old_deaths_are_clean(self):
        events = [DeathEvent("writer", 1_600_000_000.0)]
        assert classify(events=events, now=1_700_000_000.0) == "clean"


# ---------------------------------------------------------------------------
# status_report
# ---------------------------------------------------------------------------


class TestStatusReport:

    def test_empty_report(self, ledger_path):
        report = status_report(now=1_700_000_000.0, path=ledger_path)
        assert report["total_events"] == 0
        assert report["deaths_1h"] == 0
        assert report["deaths_24h"] == 0
        assert report["death_rate_1h"] == 0.0
        assert report["time_since_last_sec"] is None
        assert report["classification"] == "clean"
        assert report["last_event"] is None

    def test_with_events(self, ledger_path, sample_events):
        save_ledger(sample_events, ledger_path)
        now = sample_events[-1].ts + 60
        report = status_report(now=now, path=ledger_path)
        assert report["total_events"] == 5
        assert report["deaths_1h"] == 1  # only last event in 1h
        assert report["deaths_24h"] == 5  # all in 24h
        assert report["time_since_last_sec"] is not None
        assert report["last_event"]["process"] == "writer"
        assert "iso" in report["last_event"]

    def test_report_is_json_serializable(self, ledger_path, sample_events):
        save_ledger(sample_events, ledger_path)
        report = status_report(now=sample_events[-1].ts + 60,
                               path=ledger_path)
        # should not raise
        json.dumps(report)


# ---------------------------------------------------------------------------
# integration: record → query round trip
# ---------------------------------------------------------------------------


class TestIntegration:

    def test_record_then_status(self, ledger_path):
        record_death("writer", ts=1_700_000_000.0, path=ledger_path)
        record_death("batch", ts=1_700_000_000.0 + 30, path=ledger_path)
        report = status_report(now=1_700_000_000.0 + 60, path=ledger_path)
        assert report["total_events"] == 2
        assert report["deaths_1h"] == 2
        # two events 30s apart = 1 correlated pair, but only 1 pair < CLUSTER
        assert report["classification"] == "isolated"

    def test_storm_detection(self, ledger_path):
        base = 1_700_000_000.0
        for i in range(STORM_THRESHOLD + 2):
            record_death("writer", ts=base + i * 30, path=ledger_path)
            record_death("batch", ts=base + i * 30 + 5, path=ledger_path)
        report = status_report(now=base + (STORM_THRESHOLD + 2) * 30 + 10,
                               path=ledger_path)
        assert report["classification"] == "storm"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
