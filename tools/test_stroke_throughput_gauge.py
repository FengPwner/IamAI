#!/usr/bin/env python3
"""Tests for stroke_throughput_gauge.py"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Ensure tools/ is importable
sys.path.insert(0, str(Path(__file__).parent))
from stroke_throughput_gauge import (
    load_strokes,
    measure_throughput,
    measure_with_cadence,
    parse_timestamp,
)


def make_repo(strokes: list[dict] | None = None) -> Path:
    """Create a temporary repo structure with given strokes."""
    tmpdir = Path(tempfile.mkdtemp())
    data_dir = tmpdir / "data"
    data_dir.mkdir()

    if strokes is not None:
        with open(data_dir / "strokes.jsonl", "w") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")

    return tmpdir


class TestParseTimestamp(unittest.TestCase):
    def test_iso_with_offset(self):
        dt = parse_timestamp("2026-11-20T12:00:00+00:00")
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.hour, 12)

    def test_iso_with_z(self):
        dt = parse_timestamp("2026-11-20T12:00:00Z")
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.hour, 12)


class TestLoadStrokes(unittest.TestCase):
    def test_empty_repo(self):
        repo = make_repo()
        self.assertEqual(load_strokes(repo), [])

    def test_no_data_dir(self):
        tmpdir = Path(tempfile.mkdtemp())
        self.assertEqual(load_strokes(tmpdir), [])

    def test_loads_valid_strokes(self):
        strokes = [
            {"seq": 1, "at": "2026-11-20T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"seq": 2, "at": "2026-11-20T10:00:15+00:00", "kind": "note", "text": "b"},
        ]
        repo = make_repo(strokes)
        loaded = load_strokes(repo)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["seq"], 1)

    def test_skips_malformed_lines(self):
        tmpdir = Path(tempfile.mkdtemp())
        data_dir = tmpdir / "data"
        data_dir.mkdir()
        with open(data_dir / "strokes.jsonl", "w") as f:
            f.write('{"seq": 1, "at": "2026-11-20T10:00:00+00:00"}\n')
            f.write('this is not json\n')
            f.write('{"seq": 2, "at": "2026-11-20T10:00:15+00:00"}\n')
        loaded = load_strokes(tmpdir)
        self.assertEqual(len(loaded), 2)


class TestMeasureThroughput(unittest.TestCase):
    def test_empty_strokes(self):
        result = measure_throughput([])
        self.assertEqual(result["strokes_in_window"], 0)
        self.assertEqual(result["classification"], "stalled")

    def test_healthy_throughput(self):
        """At 15s cadence, 240 strokes/hr is 100%. Generate 220 in one hour."""
        now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
        base = now - timedelta(hours=1)
        strokes = []
        for i in range(220):
            ts = base + timedelta(seconds=i * 16)  # ~16s apart, fits 220 in 3520s < 3600s
            strokes.append({
                "seq": i + 1,
                "at": ts.isoformat(),
                "kind": "thought",
                "text": f"stroke {i}",
            })
        result = measure_throughput(strokes, window_seconds=3600, now=now)
        self.assertGreaterEqual(result["health_pct"], 80)
        self.assertEqual(result["classification"], "healthy")

    def test_degraded_throughput(self):
        """~120 strokes in window → 50% health → degraded."""
        now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
        base = now - timedelta(hours=1)
        strokes = []
        for i in range(120):
            ts = base + timedelta(seconds=i * 30)
            strokes.append({
                "seq": i + 1,
                "at": ts.isoformat(),
                "kind": "thought",
                "text": f"stroke {i}",
            })
        result = measure_throughput(strokes, window_seconds=3600, now=now)
        self.assertGreaterEqual(result["health_pct"], 40)
        self.assertIn(result["classification"], ["degraded", "struggling"])

    def test_stalled_throughput(self):
        """Only 5 strokes in the last hour → stalled."""
        now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
        base = now - timedelta(minutes=55)
        strokes = []
        for i in range(5):
            ts = base + timedelta(minutes=i * 2)
            strokes.append({
                "seq": i + 1,
                "at": ts.isoformat(),
                "kind": "thought",
                "text": f"stroke {i}",
            })
        result = measure_throughput(strokes, window_seconds=3600, now=now)
        self.assertLess(result["health_pct"], 20)
        self.assertEqual(result["classification"], "stalled")

    def test_strokes_outside_window_excluded(self):
        """Strokes older than the window should not count."""
        now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
        # All strokes are 2 hours ago — outside a 1-hour window
        base = now - timedelta(hours=2)
        strokes = []
        for i in range(100):
            ts = base + timedelta(seconds=i * 15)
            strokes.append({
                "seq": i + 1,
                "at": ts.isoformat(),
                "kind": "thought",
                "text": f"stroke {i}",
            })
        result = measure_throughput(strokes, window_seconds=3600, now=now)
        self.assertEqual(result["strokes_in_window"], 0)

    def test_custom_window(self):
        """Shorter window should extrapolate correctly."""
        now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
        base = now - timedelta(minutes=10)
        strokes = []
        # 40 strokes in 10 minutes = 240/hr = 100% health
        for i in range(40):
            ts = base + timedelta(seconds=i * 15)
            strokes.append({
                "seq": i + 1,
                "at": ts.isoformat(),
                "kind": "thought",
                "text": f"stroke {i}",
            })
        result = measure_throughput(strokes, window_seconds=600, now=now)
        self.assertAlmostEqual(result["actual_per_hour"], 240.0, delta=5.0)


class TestMeasureWithCadence(unittest.TestCase):
    def test_custom_cadence(self):
        """With cadence=30s, theoretical is 120/hr instead of 240/hr."""
        now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
        base = now - timedelta(hours=1)
        strokes = []
        for i in range(110):
            ts = base + timedelta(seconds=i * 30)
            strokes.append({
                "seq": i + 1,
                "at": ts.isoformat(),
                "kind": "thought",
                "text": f"stroke {i}",
            })
        result = measure_with_cadence(strokes, window_seconds=3600, cadence=30, now=now)
        self.assertAlmostEqual(result["theoretical_per_hour"], 120.0, delta=1.0)
        self.assertGreaterEqual(result["health_pct"], 80)
        self.assertEqual(result["classification"], "healthy")

    def test_zero_cadence(self):
        """Zero cadence should not crash — returns stalled."""
        now = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
        strokes = [{"seq": 1, "at": now.isoformat(), "kind": "thought", "text": "x"}]
        result = measure_with_cadence(strokes, window_seconds=3600, cadence=0, now=now)
        self.assertEqual(result["health_pct"], 0.0)
        self.assertEqual(result["classification"], "stalled")


if __name__ == "__main__":
    unittest.main()
