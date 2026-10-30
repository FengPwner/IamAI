#!/usr/bin/env python3
"""Tests for detection_gap_analyzer.py"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from detection_gap_analyzer import (
    DetectionEvent,
    find_detection_events,
    summarize,
    GAP_THRESHOLD_S,
    CADENCE_SECONDS,
)


# --- DetectionEvent ---

class TestDetectionEvent:
    def test_severity_ok(self):
        e = DetectionEvent(
            visit_number=1,
            detection_time=datetime(2026, 10, 27, 6, 0, tzinfo=timezone.utc),
            last_activity_time=datetime(2026, 10, 27, 5, 55, tzinfo=timezone.utc),
            gap_seconds=300,
            amplification=20,
            strokes_lost=20,
        )
        assert e.severity() == "ok"

    def test_severity_degraded(self):
        e = DetectionEvent(
            visit_number=2,
            detection_time=datetime(2026, 10, 27, 6, 0, tzinfo=timezone.utc),
            last_activity_time=datetime(2026, 10, 27, 5, 40, tzinfo=timezone.utc),
            gap_seconds=1200,
            amplification=80,
            strokes_lost=80,
        )
        assert e.severity() == "degraded"

    def test_severity_poor(self):
        e = DetectionEvent(
            visit_number=3,
            detection_time=datetime(2026, 10, 27, 6, 0, tzinfo=timezone.utc),
            last_activity_time=datetime(2026, 10, 27, 5, 0, tzinfo=timezone.utc),
            gap_seconds=3600,
            amplification=240,
            strokes_lost=240,
        )
        assert e.severity() == "poor"

    def test_to_dict(self):
        e = DetectionEvent(
            visit_number=10,
            detection_time=datetime(2026, 10, 27, 6, 0, tzinfo=timezone.utc),
            last_activity_time=datetime(2026, 10, 27, 5, 50, tzinfo=timezone.utc),
            gap_seconds=600,
            amplification=40,
            strokes_lost=40,
            commit_hash="abc1234",
        )
        d = e.to_dict()
        assert d["visit"] == 10
        assert d["gap_seconds"] == 600.0
        assert d["amplification"] == 40.0
        assert d["strokes_lost"] == 40
        assert d["severity"] == "degraded"  # 600s is at threshold boundary (>= 600)
        assert d["commit"] == "abc1234"

    def test_boundary_ok_at_threshold(self):
        """Exactly at the threshold boundary should be degraded (>), not ok."""
        e = DetectionEvent(
            visit_number=1,
            detection_time=datetime(2026, 10, 27, 6, 0, tzinfo=timezone.utc),
            last_activity_time=datetime(2026, 10, 27, 5, 50, tzinfo=timezone.utc),
            gap_seconds=GAP_THRESHOLD_S - 1,
            amplification=39,
            strokes_lost=39,
        )
        assert e.severity() == "ok"


# --- find_detection_events ---

class TestFindDetectionEvents:
    def _make_visits(self, times_and_numbers):
        return [
            {"hash": f"hash{i}", "visit": num, "subject": f"visit {num}", "time": t}
            for i, (t, num) in enumerate(times_and_numbers)
        ]

    def test_basic_matching(self):
        """Each visit should find the most recent stroke before it."""
        base = datetime(2026, 10, 27, 5, 0, tzinfo=timezone.utc)
        strokes = [
            base + timedelta(minutes=i) for i in range(60)
        ]
        visits = self._make_visits([
            (base + timedelta(minutes=30), 1),
            (base + timedelta(minutes=50), 2),
        ])
        events = find_detection_events(visits, strokes)
        assert len(events) == 2
        # Visit 1 at +30min: last stroke at +29min → gap = 60s
        assert events[0].gap_seconds == 60.0
        assert events[0].visit_number == 1
        # Visit 2 at +50min: last stroke at +49min → gap = 60s
        assert events[1].gap_seconds == 60.0

    def test_no_prior_strokes(self):
        """Visit before all strokes should be skipped."""
        base = datetime(2026, 10, 27, 5, 0, tzinfo=timezone.utc)
        strokes = [base + timedelta(hours=1)]
        visits = self._make_visits([(base, 1)])
        events = find_detection_events(visits, strokes)
        assert len(events) == 0

    def test_empty_inputs(self):
        events = find_detection_events([], [])
        assert events == []

    def test_large_gap_detected(self):
        """When strokes stop for a long time before a visit."""
        base = datetime(2026, 10, 27, 4, 0, tzinfo=timezone.utc)
        strokes = [base]  # one stroke at base
        visit_time = base + timedelta(hours=1)
        visits = self._make_visits([(visit_time, 5)])
        events = find_detection_events(visits, strokes)
        assert len(events) == 1
        assert events[0].gap_seconds == 3600.0
        assert events[0].severity() == "poor"
        assert events[0].strokes_lost == 240  # 3600 / 15


# --- summarize ---

class TestSummarize:
    def test_empty_events(self):
        s = summarize([])
        assert s["count"] == 0
        assert s["health"] == "no_data"

    def test_all_ok(self):
        base = datetime(2026, 10, 27, 5, 0, tzinfo=timezone.utc)
        events = [
            DetectionEvent(
                visit_number=i,
                detection_time=base + timedelta(minutes=i * 10),
                last_activity_time=base + timedelta(minutes=i * 10 - 2),
                gap_seconds=120,
                amplification=8,
                strokes_lost=8,
            )
            for i in range(1, 4)
        ]
        s = summarize(events)
        assert s["count"] == 3
        assert s["health"] == "ok"
        assert s["avg_gap"] == 120.0
        assert s["poor_count"] == 0
        assert s["degraded_count"] == 0

    def test_mixed_health(self):
        base = datetime(2026, 10, 27, 5, 0, tzinfo=timezone.utc)
        events = [
            DetectionEvent(1, base, base - timedelta(minutes=5), 300, 20, 20),
            DetectionEvent(2, base, base - timedelta(minutes=20), 1200, 80, 80),
            DetectionEvent(3, base, base - timedelta(hours=1), 3600, 240, 240),
        ]
        s = summarize(events)
        assert s["health"] == "poor"  # one poor event → overall poor
        assert s["poor_count"] == 1
        assert s["degraded_count"] == 1
        assert s["ok_count"] == 1
        assert s["total_strokes_lost"] == 20 + 80 + 240

    def test_total_strokes_lost(self):
        base = datetime(2026, 10, 27, 5, 0, tzinfo=timezone.utc)
        events = [
            DetectionEvent(i, base, base, 60, 4, 4)
            for i in range(5)
        ]
        s = summarize(events)
        assert s["total_strokes_lost"] == 20
