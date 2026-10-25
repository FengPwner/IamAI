"""Tests for tools/uptime_fatigue_analysis.py"""

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from uptime_fatigue_analysis import (
    detect_stalls,
    build_sessions,
    compute_fatigue_score,
    classify_fatigue,
    summarize,
)


# ---------------------------------------------------------------------------
# detect_stalls
# ---------------------------------------------------------------------------

class TestDetectStalls:
    def test_no_stalls(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts = [base + timedelta(seconds=i * 15) for i in range(20)]
        assert detect_stalls(ts, threshold_seconds=300) == []

    def test_single_stall(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts = [base, base + timedelta(seconds=15), base + timedelta(seconds=600)]
        stalls = detect_stalls(ts, threshold_seconds=300)
        assert len(stalls) == 1
        assert stalls[0]["gap_seconds"] == 585.0
        assert stalls[0]["index"] == 2

    def test_multiple_stalls(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts = [
            base,
            base + timedelta(seconds=15),
            base + timedelta(seconds=400),   # gap 385
            base + timedelta(seconds=415),
            base + timedelta(seconds=900),   # gap 485
        ]
        stalls = detect_stalls(ts, threshold_seconds=300)
        assert len(stalls) == 2
        assert stalls[0]["gap_seconds"] == 385.0
        assert stalls[1]["gap_seconds"] == 485.0

    def test_empty_list(self):
        assert detect_stalls([], threshold_seconds=300) == []

    def test_single_timestamp(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert detect_stalls([base], threshold_seconds=300) == []

    def test_threshold_boundary(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts = [base, base + timedelta(seconds=300)]
        # exactly at threshold — should NOT be flagged (gap must be > threshold)
        assert detect_stalls(ts, threshold_seconds=300) == []

    def test_threshold_just_over(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts = [base, base + timedelta(seconds=301)]
        stalls = detect_stalls(ts, threshold_seconds=300)
        assert len(stalls) == 1
        assert stalls[0]["gap_seconds"] == 301.0


# ---------------------------------------------------------------------------
# build_sessions
# ---------------------------------------------------------------------------

class TestBuildSessions:
    def test_no_stalls_one_session(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts = [base + timedelta(seconds=i * 15) for i in range(10)]
        sessions = build_sessions(ts, detect_stalls(ts, 300))
        assert len(sessions) == 1
        assert sessions[0]["stroke_count"] == 10
        assert sessions[0]["uptime_seconds"] == 135.0
        assert sessions[0]["stall_gap"] == 0.0

    def test_one_stall_two_sessions(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts = [
            base,
            base + timedelta(seconds=15),
            base + timedelta(seconds=30),   # session 1 ends
            base + timedelta(seconds=600),  # gap 570
            base + timedelta(seconds=615),
            base + timedelta(seconds=630),
        ]
        stalls = detect_stalls(ts, 300)
        sessions = build_sessions(ts, stalls)
        assert len(sessions) == 2
        assert sessions[0]["stroke_count"] == 3
        assert sessions[0]["uptime_seconds"] == 30.0
        assert sessions[0]["stall_gap"] == 570.0
        assert sessions[1]["stroke_count"] == 3
        assert sessions[1]["stall_gap"] == 0.0

    def test_empty_timestamps(self):
        assert build_sessions([], []) == []

    def test_multiple_stalls(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts = [
            base,
            base + timedelta(seconds=10),
            base + timedelta(seconds=500),   # gap 490
            base + timedelta(seconds=510),
            base + timedelta(seconds=1000),  # gap 490
            base + timedelta(seconds=1010),
        ]
        stalls = detect_stalls(ts, 300)
        sessions = build_sessions(ts, stalls)
        assert len(sessions) == 3
        # first session: 2 strokes, 10s uptime
        assert sessions[0]["stroke_count"] == 2
        assert sessions[0]["uptime_seconds"] == 10.0
        # second session: 2 strokes
        assert sessions[1]["stroke_count"] == 2
        # third session: 2 strokes, no stall
        assert sessions[2]["stroke_count"] == 2
        assert sessions[2]["stall_gap"] == 0.0


# ---------------------------------------------------------------------------
# compute_fatigue_score
# ---------------------------------------------------------------------------

class TestComputeFatigueScore:
    def test_no_sessions(self):
        assert compute_fatigue_score([]) == 0.5

    def test_single_session(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        sessions = [{
            "session_start": base,
            "session_end": base + timedelta(seconds=100),
            "uptime_seconds": 100.0,
            "stroke_count": 10,
            "stall_gap": 0.0,
        }]
        assert compute_fatigue_score(sessions) == 0.5

    def test_all_stalls_long_uptime(self):
        """Stalls always happen in long sessions → score near 1.0."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # short sessions (no stall), long sessions (with stall)
        sessions = []
        for i in range(10):
            uptime = 60.0 if i < 5 else 3600.0
            sessions.append({
                "session_start": base,
                "session_end": base + timedelta(seconds=uptime),
                "uptime_seconds": uptime,
                "stroke_count": 10,
                "stall_gap": 500.0 if uptime > 1000 else 0.0,
            })
        score = compute_fatigue_score(sessions)
        assert score >= 0.8

    def test_all_stalls_short_uptime(self):
        """Stalls always happen in short sessions → score near 0.0."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        sessions = []
        for i in range(10):
            uptime = 3600.0 if i < 5 else 60.0
            sessions.append({
                "session_start": base,
                "session_end": base + timedelta(seconds=uptime),
                "uptime_seconds": uptime,
                "stroke_count": 10,
                "stall_gap": 500.0 if uptime < 1000 else 0.0,
            })
        score = compute_fatigue_score(sessions)
        assert score <= 0.2

    def test_uniform_distribution(self):
        """Stalls spread evenly → score near 0.5."""
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        sessions = []
        for i in range(20):
            uptime = 60.0 * (i + 1)
            sessions.append({
                "session_start": base,
                "session_end": base + timedelta(seconds=uptime),
                "uptime_seconds": uptime,
                "stroke_count": 10,
                "stall_gap": 500.0,
            })
        score = compute_fatigue_score(sessions)
        assert 0.4 <= score <= 0.6

    def test_no_stalled_sessions(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        sessions = [{
            "session_start": base,
            "session_end": base + timedelta(seconds=100),
            "uptime_seconds": 100.0,
            "stroke_count": 10,
            "stall_gap": 0.0,
        }, {
            "session_start": base,
            "session_end": base + timedelta(seconds=200),
            "uptime_seconds": 200.0,
            "stroke_count": 20,
            "stall_gap": 0.0,
        }]
        assert compute_fatigue_score(sessions) == 0.5


# ---------------------------------------------------------------------------
# classify_fatigue
# ---------------------------------------------------------------------------

class TestClassifyFatigue:
    def test_fatigue(self):
        assert classify_fatigue(0.80) == "fatigue"
        assert classify_fatigue(0.65) == "fatigue"

    def test_mixed(self):
        assert classify_fatigue(0.55) == "mixed"
        assert classify_fatigue(0.50) == "mixed"

    def test_independent(self):
        assert classify_fatigue(0.49) == "independent"
        assert classify_fatigue(0.0) == "independent"

    def test_boundary_values(self):
        assert classify_fatigue(0.64999) == "mixed"
        assert classify_fatigue(0.65) == "fatigue"
        assert classify_fatigue(0.49999) == "independent"
        assert classify_fatigue(0.50) == "mixed"


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------

class TestSummarize:
    def test_basic_summary(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        sessions = [
            {
                "session_start": base,
                "session_end": base + timedelta(seconds=3600),
                "uptime_seconds": 3600.0,
                "stroke_count": 240,
                "stall_gap": 500.0,
            },
            {
                "session_start": base + timedelta(seconds=4100),
                "session_end": base + timedelta(seconds=4200),
                "uptime_seconds": 100.0,
                "stroke_count": 7,
                "stall_gap": 0.0,
            },
        ]
        text = summarize(sessions, 0.75, "fatigue")
        assert "sessions analyzed : 2" in text
        assert "stalls recorded   : 1" in text
        assert "fatigue_score     : 0.7500" in text
        assert "verdict           : fatigue" in text
        assert "max uptime        : 3600s" in text

    def test_no_stalls_summary(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        sessions = [{
            "session_start": base,
            "session_end": base + timedelta(seconds=100),
            "uptime_seconds": 100.0,
            "stroke_count": 10,
            "stall_gap": 0.0,
        }]
        text = summarize(sessions, 0.5, "independent")
        assert "stalls recorded   : 0" in text
        # no median/max/min lines when no stalls
        assert "median uptime" not in text
