"""Tests for iamai.stall_recovery_latency — stall recovery analysis.

Covers:
  - timestamp parsing
  - stall detection with various thresholds
  - recovery latency measurement
  - recovery classification
  - aggregate statistics
  - stall↔recovery correlation
  - edge cases (insufficient data, end-of-timeline stalls)
  - summary formatting
  - CLI integration
"""

import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
import io

from iamai.stall_recovery_latency import (
    parse_timestamps,
    detect_stalls,
    recovery_latency,
    median_cadence,
    classify_recovery,
    recovery_stats,
    recovery_trend,
    stall_recovery_correlation,
    summarize,
    format_report,
    main,
)

_TZ = timezone(timedelta(hours=8))


def _dt(h, m=0, s=0):
    """Helper: build a datetime on 2026-10-21 at given h/m/s GMT+8."""
    return datetime(2026, 10, 21, h, m, s, tzinfo=_TZ)


def _make_strokes(dts):
    """Write a temporary strokes.jsonl and return its path."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for i, dt in enumerate(dts):
        tmp.write(json.dumps({"at": dt.isoformat(), "seq": i}) + "\n")
    tmp.close()
    return tmp.name


class TestParseTimestamps(unittest.TestCase):
    def test_basic_parsing(self):
        dts = [_dt(10, 0), _dt(10, 5), _dt(10, 10)]
        path = _make_strokes(dts)
        result = parse_timestamps(path)
        self.assertEqual(len(result), 3)
        Path(path).unlink()

    def test_empty_file(self):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        tmp.close()
        result = parse_timestamps(tmp.name)
        self.assertEqual(result, [])
        Path(tmp.name).unlink()

    def test_skips_malformed_lines(self):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        tmp.write("not json\n")
        tmp.write(json.dumps({"at": _dt(10, 0).isoformat()}) + "\n")
        tmp.write(json.dumps({"no_at_field": True}) + "\n")
        tmp.write(json.dumps({"at": _dt(10, 5).isoformat()}) + "\n")
        tmp.close()
        result = parse_timestamps(tmp.name)
        self.assertEqual(len(result), 2)
        Path(tmp.name).unlink()

    def test_sorted_output(self):
        dts = [_dt(10, 10), _dt(10, 0), _dt(10, 5)]
        path = _make_strokes(dts)
        result = parse_timestamps(path)
        self.assertEqual(result[0], _dt(10, 0))
        self.assertEqual(result[2], _dt(10, 10))
        Path(path).unlink()

    def test_naive_timestamps_get_utc(self):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        tmp.write(json.dumps({"at": "2026-10-21T10:00:00"}) + "\n")
        tmp.close()
        result = parse_timestamps(tmp.name)
        self.assertEqual(result[0].tzinfo, timezone.utc)
        Path(tmp.name).unlink()


class TestDetectStalls(unittest.TestCase):
    def test_no_stalls(self):
        dts = [_dt(10, 0), _dt(10, 2), _dt(10, 4)]
        stalls = detect_stalls(dts, threshold_seconds=300)
        self.assertEqual(stalls, [])

    def test_one_stall(self):
        dts = [_dt(10, 0), _dt(10, 10)]  # 600s gap
        stalls = detect_stalls(dts, threshold_seconds=300)
        self.assertEqual(len(stalls), 1)
        self.assertEqual(stalls[0]["index"], 0)
        self.assertAlmostEqual(stalls[0]["duration"], 600.0)

    def test_multiple_stalls(self):
        dts = [_dt(10, 0), _dt(10, 10), _dt(10, 12), _dt(10, 22)]
        stalls = detect_stalls(dts, threshold_seconds=300)
        self.assertEqual(len(stalls), 2)

    def test_threshold_boundary(self):
        dts = [_dt(10, 0), _dt(10, 5)]  # exactly 300s
        stalls_at = detect_stalls(dts, threshold_seconds=300)
        self.assertEqual(len(stalls_at), 0)  # not > threshold
        stalls_below = detect_stalls(dts, threshold_seconds=299)
        self.assertEqual(len(stalls_below), 1)

    def test_empty_timestamps(self):
        self.assertEqual(detect_stalls([], 300), [])

    def test_single_timestamp(self):
        self.assertEqual(detect_stalls([_dt(10, 0)], 300), [])


class TestRecoveryLatency(unittest.TestCase):
    def test_basic_recovery(self):
        dts = [_dt(10, 0), _dt(10, 10), _dt(10, 12), _dt(10, 14)]
        stalls = detect_stalls(dts, threshold_seconds=300)
        lats = recovery_latency(stalls, dts)
        self.assertEqual(len(lats), 1)
        # gap_end is at 10:10, next stroke at 10:12 → 120s
        self.assertAlmostEqual(lats[0], 120.0)

    def test_stall_at_end_skipped(self):
        dts = [_dt(10, 0), _dt(10, 10)]
        stalls = detect_stalls(dts, threshold_seconds=300)
        lats = recovery_latency(stalls, dts)
        self.assertEqual(len(lats), 0)  # no second post-stall stroke

    def test_multiple_recoveries(self):
        dts = [
            _dt(10, 0), _dt(10, 10), _dt(10, 12),  # stall + recovery
            _dt(10, 22), _dt(10, 24), _dt(10, 26),  # stall + recovery
        ]
        stalls = detect_stalls(dts, threshold_seconds=300)
        lats = recovery_latency(stalls, dts)
        self.assertEqual(len(lats), 2)

    def test_empty_stalls(self):
        dts = [_dt(10, 0), _dt(10, 5)]
        lats = recovery_latency([], dts)
        self.assertEqual(lats, [])


class TestMedianCadence(unittest.TestCase):
    def test_basic(self):
        dts = [_dt(10, 0), _dt(10, 5), _dt(10, 10), _dt(10, 15)]
        c = median_cadence(dts)
        self.assertAlmostEqual(c, 300.0)

    def test_single_timestamp(self):
        self.assertAlmostEqual(median_cadence([_dt(10, 0)]), 0.0)

    def test_empty(self):
        self.assertAlmostEqual(median_cadence([]), 0.0)

    def test_irregular_cadence(self):
        dts = [_dt(10, 0), _dt(10, 1), _dt(10, 10)]  # gaps: 60s, 540s
        c = median_cadence(dts)
        self.assertAlmostEqual(c, 300.0)  # median of [60, 540]


class TestClassifyRecovery(unittest.TestCase):
    def test_instant(self):
        self.assertEqual(classify_recovery(100, 100), "instant")  # 1×
        self.assertEqual(classify_recovery(199, 100), "instant")  # 1.99×

    def test_slow(self):
        self.assertEqual(classify_recovery(200, 100), "slow")  # 2×
        self.assertEqual(classify_recovery(499, 100), "slow")  # 4.99×

    def test_stuck(self):
        self.assertEqual(classify_recovery(500, 100), "stuck")  # 5×
        self.assertEqual(classify_recovery(1000, 100), "stuck")

    def test_zero_cadence(self):
        self.assertEqual(classify_recovery(100, 0), "instant")

    def test_boundary_values(self):
        self.assertEqual(classify_recovery(0, 100), "instant")
        self.assertEqual(classify_recovery(200, 100), "slow")
        self.assertEqual(classify_recovery(500, 100), "stuck")


class TestRecoveryStats(unittest.TestCase):
    def test_basic_stats(self):
        lats = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
        stats = recovery_stats(lats, cadence=200)
        self.assertEqual(stats["count"], 10)
        self.assertAlmostEqual(stats["median"], 550.0)
        self.assertAlmostEqual(stats["min"], 100.0)
        self.assertAlmostEqual(stats["max"], 1000.0)

    def test_empty(self):
        stats = recovery_stats([])
        self.assertEqual(stats["count"], 0)
        self.assertAlmostEqual(stats["median"], 0.0)

    def test_single_value(self):
        stats = recovery_stats([42.0], cadence=20)
        self.assertEqual(stats["count"], 1)
        self.assertAlmostEqual(stats["median"], 42.0)

    def test_buckets(self):
        # cadence = 100
        lats = [50, 150, 250, 600]  # instant, instant, slow, stuck
        stats = recovery_stats(lats, cadence=100)
        self.assertEqual(stats["buckets"]["instant"], 2)
        self.assertEqual(stats["buckets"]["slow"], 1)
        self.assertEqual(stats["buckets"]["stuck"], 1)


class TestRecoveryTrend(unittest.TestCase):
    def test_basic(self):
        lats = [100.123, 200.456, 300.789]
        trend = recovery_trend(lats)
        self.assertEqual(trend, [(0, 100.1), (1, 200.5), (2, 300.8)])

    def test_empty(self):
        self.assertEqual(recovery_trend([]), [])


class TestStallRecoveryCorrelation(unittest.TestCase):
    def test_positive_correlation(self):
        stalls = [
            {"duration": 300}, {"duration": 600}, {"duration": 900},
            {"duration": 1200}, {"duration": 1500},
        ]
        lats = [100, 200, 300, 400, 500]
        r = stall_recovery_correlation(stalls, lats)
        self.assertGreater(r, 0.9)

    def test_negative_correlation(self):
        stalls = [
            {"duration": 300}, {"duration": 600}, {"duration": 900},
            {"duration": 1200},
        ]
        lats = [400, 100, 400, 100]
        r = stall_recovery_correlation(stalls, lats)
        # longer stalls → shorter recoveries yields negative correlation
        self.assertLess(r, -0.3)

    def test_insufficient_data(self):
        stalls = [{"duration": 300}, {"duration": 600}]
        lats = [100, 200]
        self.assertEqual(stall_recovery_correlation(stalls, lats), 0.0)

    def test_mismatched_lengths(self):
        stalls = [{"duration": 300}]
        lats = [100, 200, 300]
        self.assertEqual(stall_recovery_correlation(stalls, lats), 0.0)

    def test_zero_variance(self):
        stalls = [{"duration": 300}, {"duration": 300}, {"duration": 300}]
        lats = [100, 100, 100]
        self.assertEqual(stall_recovery_correlation(stalls, lats), 0.0)


class TestSummarize(unittest.TestCase):
    def test_end_to_end(self):
        dts = [
            _dt(10, 0), _dt(10, 2), _dt(10, 4),  # normal: 2min cadence
            _dt(10, 20),  # stall: 960s gap (4→20)
            _dt(10, 22), _dt(10, 24),  # recovery: 120s between post-stall strokes
        ]
        path = _make_strokes(dts)
        result = summarize(path=path, threshold_seconds=300)
        self.assertEqual(result["stroke_count"], 6)
        self.assertEqual(result["stall_count"], 1)
        self.assertIn("recovery", result)
        self.assertEqual(result["recovery"]["count"], 1)
        Path(path).unlink()

    def test_insufficient_data(self):
        dts = [_dt(10, 0)]
        path = _make_strokes(dts)
        result = summarize(path=path)
        self.assertIn("error", result)
        Path(path).unlink()


class TestFormatReport(unittest.TestCase):
    def test_normal_report(self):
        summary = {
            "stroke_count": 100,
            "stall_count": 5,
            "cadence_median_s": 300.0,
            "threshold_s": 300,
            "recovery": {
                "count": 4,
                "median": 120.0,
                "mean": 150.0,
                "p95": 300.0,
                "max": 400.0,
                "min": 60.0,
                "buckets": {"instant": 2, "slow": 1, "stuck": 1},
            },
            "stall_recovery_correlation": 0.15,
        }
        report = format_report(summary)
        self.assertIn("Strokes analysed : 100", report)
        self.assertIn("Stalls detected  : 5", report)
        self.assertIn("instant : 2", report)
        self.assertIn("correlation: 0.15", report)

    def test_error_report(self):
        report = format_report({"error": "insufficient data", "stroke_count": 1})
        self.assertIn("Error", report)


class TestCLI(unittest.TestCase):
    def test_json_output(self):
        dts = [_dt(10, 0), _dt(10, 5), _dt(10, 15), _dt(10, 20)]
        path = _make_strokes(dts)
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            main(["--json", "--strokes", path])
        output = mock_out.getvalue()
        data = json.loads(output)
        self.assertIn("stroke_count", data)
        Path(path).unlink()

    def test_text_output(self):
        dts = [_dt(10, 0), _dt(10, 5), _dt(10, 15), _dt(10, 20)]
        path = _make_strokes(dts)
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            main(["--strokes", path])
        output = mock_out.getvalue()
        self.assertIn("Strokes analysed", output)
        Path(path).unlink()

    def test_custom_threshold(self):
        dts = [_dt(10, 0), _dt(10, 5), _dt(10, 15), _dt(10, 20)]
        path = _make_strokes(dts)
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            main(["--json", "--threshold", "60", "--strokes", path])
        data = json.loads(mock_out.getvalue())
        # threshold=60 means the 5-min gaps become stalls too
        self.assertGreater(data["stall_count"], 0)
        Path(path).unlink()


if __name__ == "__main__":
    unittest.main()
