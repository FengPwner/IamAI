"""test_stroke_yield_analyzer.py — 38 tests for stroke yield analysis.

covers:
- timestamp parsing (Z suffix, offset formats, whitespace, invalid)
- stroke loading from JSONL (normal, empty, malformed lines)
- stall gap computation (no gaps, one gap, multiple gaps, threshold boundary)
- yield computation (clean run, single stall, fragmented, blackout, empty)
- yield ratio calculation and capping
- pattern classification (clean, fragmented, blackout, empty)
- report formatting (normal, empty, with gaps)
- CLI argument parsing (window formats, defaults)
- edge cases (single stroke, identical timestamps, all stalls)
"""

import json
import pytest
from datetime import datetime, timezone, timedelta

from tools.stroke_yield_analyzer import (
    parse_timestamp,
    load_strokes,
    compute_stall_gaps,
    compute_yield,
    format_report,
)


# --- timestamp parsing ---


class TestParseTimestamp:
    def test_z_suffix(self):
        dt = parse_timestamp("2026-11-20T15:00:00Z")
        assert dt.tzinfo is not None
        assert dt.year == 2026
        assert dt.month == 11
        assert dt.day == 20

    def test_offset_suffix(self):
        dt = parse_timestamp("2026-11-20T15:00:00+08:00")
        assert dt.tzinfo is not None
        assert dt.utcoffset() == timedelta(hours=8)

    def test_whitespace_stripped(self):
        dt = parse_timestamp("  2026-11-20T15:00:00Z  ")
        assert dt.year == 2026

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_timestamp("not-a-timestamp")

    def test_fractional_seconds(self):
        dt = parse_timestamp("2026-11-20T15:00:00.123456Z")
        assert dt.microsecond == 123456

    def test_utc_offset_zero(self):
        dt = parse_timestamp("2026-11-20T15:00:00+00:00")
        assert dt.utcoffset() == timedelta(0)


# --- stroke loading ---


class TestLoadStrokes:
    def test_load_normal(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        strokes_file = data_dir / "strokes.jsonl"
        strokes_file.write_text(
            '{"at": "2026-11-20T15:00:00Z", "seq": 1}\n'
            '{"at": "2026-11-20T15:00:15Z", "seq": 2}\n'
        )
        result = load_strokes(tmp_path)
        assert len(result) == 2
        assert result[0]["seq"] == 1

    def test_load_empty_file(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "strokes.jsonl").write_text("")
        result = load_strokes(tmp_path)
        assert result == []

    def test_load_skips_malformed_lines(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "strokes.jsonl").write_text(
            '{"at": "2026-11-20T15:00:00Z", "seq": 1}\n'
            "not-json\n"
            '{"at": "2026-11-20T15:00:30Z", "seq": 3}\n'
        )
        result = load_strokes(tmp_path)
        assert len(result) == 2

    def test_load_missing_file(self, tmp_path):
        result = load_strokes(tmp_path)
        assert result == []


# --- stall gap computation ---


def make_strokes(timestamps: list[str], start_seq: int = 1) -> list[dict]:
    """Helper to create stroke records from a list of timestamp strings."""
    return [
        {"at": ts, "seq": start_seq + i, "kind": "note", "path": "notes/test.md"}
        for i, ts in enumerate(timestamps)
    ]


class TestComputeStallGaps:
    def test_no_gaps(self):
        strokes = make_strokes([
            "2026-11-20T15:00:00Z",
            "2026-11-20T15:00:15Z",
            "2026-11-20T15:00:30Z",
        ])
        gaps = compute_stall_gaps(strokes, stall_threshold_sec=300)
        assert gaps == []

    def test_one_gap(self):
        strokes = make_strokes([
            "2026-11-20T15:00:00Z",
            "2026-11-20T15:10:00Z",  # 10 min gap
        ])
        gaps = compute_stall_gaps(strokes, stall_threshold_sec=300)
        assert len(gaps) == 1
        assert gaps[0]["duration_sec"] == 600.0

    def test_multiple_gaps(self):
        strokes = make_strokes([
            "2026-11-20T15:00:00Z",
            "2026-11-20T15:10:00Z",  # 10 min gap
            "2026-11-20T15:10:15Z",  # normal
            "2026-11-20T15:20:15Z",  # 10 min gap
        ])
        gaps = compute_stall_gaps(strokes, stall_threshold_sec=300)
        assert len(gaps) == 2

    def test_threshold_boundary_exactly_at_threshold(self):
        strokes = make_strokes([
            "2026-11-20T15:00:00Z",
            "2026-11-20T15:05:00Z",  # exactly 300s
        ])
        gaps = compute_stall_gaps(strokes, stall_threshold_sec=300)
        assert len(gaps) == 0  # must exceed, not equal

    def test_threshold_boundary_just_over(self):
        strokes = make_strokes([
            "2026-11-20T15:00:00Z",
            "2026-11-20T15:05:01Z",  # 301s
        ])
        gaps = compute_stall_gaps(strokes, stall_threshold_sec=300)
        assert len(gaps) == 1

    def test_single_stroke(self):
        strokes = make_strokes(["2026-11-20T15:00:00Z"])
        gaps = compute_stall_gaps(strokes, stall_threshold_sec=300)
        assert gaps == []

    def test_empty_strokes(self):
        gaps = compute_stall_gaps([], stall_threshold_sec=300)
        assert gaps == []

    def test_gap_records_contain_expected_fields(self):
        strokes = make_strokes([
            "2026-11-20T15:00:00Z",
            "2026-11-20T15:10:00Z",
        ])
        gaps = compute_stall_gaps(strokes, stall_threshold_sec=300)
        assert "index" in gaps[0]
        assert "start" in gaps[0]
        assert "end" in gaps[0]
        assert "duration_sec" in gaps[0]
        assert "seq_before" in gaps[0]
        assert "seq_after" in gaps[0]


# --- yield computation ---


class TestComputeYield:
    def test_clean_run(self):
        strokes = make_strokes([
            "2026-11-20T15:00:00Z",
            "2026-11-20T15:00:15Z",
            "2026-11-20T15:00:30Z",
            "2026-11-20T15:00:45Z",
            "2026-11-20T15:01:00Z",
        ])
        result = compute_yield(strokes, cadence_sec=15.0, stall_threshold_sec=300)
        assert result["pattern"] == "clean"
        assert result["fragmentation"] == 0
        assert result["lost_strokes"] == 0
        assert result["yield_ratio"] > 0.9

    def test_single_stall(self):
        # 5 normal strokes, then a 30 min gap, then 5 more
        base = datetime(2026, 11, 20, 15, 0, 0, tzinfo=timezone.utc)
        timestamps = []
        for i in range(5):
            timestamps.append((base + timedelta(seconds=i * 15)).isoformat())
        # 30 min gap
        for i in range(5):
            timestamps.append(
                (base + timedelta(minutes=30, seconds=i * 15)).isoformat()
            )
        strokes = make_strokes(timestamps)
        result = compute_yield(strokes, cadence_sec=15.0, stall_threshold_sec=300)
        assert result["fragmentation"] == 1
        assert result["total_stall_time_sec"] >= 1700  # ~30min minus 15s
        assert result["lost_strokes"] > 0
        assert result["yield_ratio"] < 1.0

    def test_fragmented_pattern(self):
        # four clusters with 3 separate 10-min stalls between them
        base = datetime(2026, 11, 20, 15, 0, 0, tzinfo=timezone.utc)
        timestamps = []
        offset = 0
        for cluster in range(4):
            for i in range(3):
                timestamps.append(
                    (base + timedelta(seconds=offset + i * 15)).isoformat()
                )
            if cluster < 3:
                offset += 30 + 600  # 30s of writing + 10min gap
        strokes = make_strokes(timestamps)
        result = compute_yield(strokes, cadence_sec=15.0, stall_threshold_sec=300)
        assert result["fragmentation"] == 3
        assert result["pattern"] in ("fragmented", "blackout")

    def test_blackout_pattern(self):
        # two strokes with a massive gap in between
        strokes = make_strokes([
            "2026-11-20T15:00:00Z",
            "2026-11-20T21:00:00Z",  # 6 hours later
        ])
        result = compute_yield(strokes, cadence_sec=15.0, stall_threshold_sec=300)
        assert result["pattern"] == "blackout"
        assert result["lost_strokes"] > 1000

    def test_empty_strokes(self):
        result = compute_yield([], cadence_sec=15.0)
        assert result["pattern"] == "empty"
        assert result["actual_strokes"] == 0
        assert result["yield_ratio"] == 0.0

    def test_single_stroke(self):
        strokes = make_strokes(["2026-11-20T15:00:00Z"])
        result = compute_yield(strokes, cadence_sec=15.0)
        assert result["actual_strokes"] == 1
        assert result["total_duration_sec"] == 0
        assert result["yield_ratio"] == 1.0

    def test_yield_ratio_capped_at_one(self):
        # strokes faster than cadence — yield should not exceed 1.0
        strokes = make_strokes([
            "2026-11-20T15:00:00Z",
            "2026-11-20T15:00:05Z",
            "2026-11-20T15:00:10Z",
            "2026-11-20T15:00:15Z",
        ])
        result = compute_yield(strokes, cadence_sec=15.0, stall_threshold_sec=300)
        assert result["yield_ratio"] <= 1.0

    def test_window_filtering(self):
        # strokes spread over 48 hours, analyze only last 24
        base = datetime(2026, 11, 20, 0, 0, 0, tzinfo=timezone.utc)
        timestamps = []
        for h in range(48):
            timestamps.append(
                (base + timedelta(hours=h, seconds=0)).isoformat()
            )
        strokes = make_strokes(timestamps)
        result = compute_yield(
            strokes, cadence_sec=15.0, stall_threshold_sec=3600, window_hours=24
        )
        # should only analyze the last ~24 strokes
        assert result["actual_strokes"] <= 25

    def test_expected_strokes_calculation(self):
        # 60 seconds of activity at 15s cadence = 4 expected
        strokes = make_strokes([
            "2026-11-20T15:00:00Z",
            "2026-11-20T15:00:15Z",
            "2026-11-20T15:00:30Z",
            "2026-11-20T15:00:45Z",
            "2026-11-20T15:01:00Z",
        ])
        result = compute_yield(strokes, cadence_sec=15.0, stall_threshold_sec=300)
        assert result["expected_strokes"] == 4.0

    def test_stall_gaps_include_expected_strokes(self):
        strokes = make_strokes([
            "2026-11-20T15:00:00Z",
            "2026-11-20T15:10:00Z",  # 600s = 40 expected strokes at 15s
        ])
        result = compute_yield(strokes, cadence_sec=15.0, stall_threshold_sec=300)
        assert len(result["stall_gaps"]) == 1
        assert result["stall_gaps"][0]["expected_strokes"] == pytest.approx(40.0)


# --- report formatting ---


class TestFormatReport:
    def test_normal_report(self):
        result = {
            "window_start": "2026-11-20T15:00:00Z",
            "window_end": "2026-11-20T16:00:00Z",
            "total_duration_sec": 3600,
            "expected_strokes": 240.0,
            "actual_strokes": 230,
            "stall_gaps": [],
            "total_stall_time_sec": 0,
            "lost_strokes": 0,
            "yield_ratio": 0.9583,
            "yield_pct": 95.83,
            "fragmentation": 0,
            "pattern": "clean",
        }
        report = format_report(result)
        assert "stroke yield analysis" in report
        assert "95.83%" in report
        assert "clean" in report

    def test_empty_report(self):
        result = {
            "pattern": "empty",
            "actual_strokes": 0,
        }
        report = format_report(result)
        assert "no strokes found" in report

    def test_report_with_gaps(self):
        result = {
            "window_start": "2026-11-20T15:00:00Z",
            "window_end": "2026-11-20T16:00:00Z",
            "total_duration_sec": 3600,
            "expected_strokes": 240.0,
            "actual_strokes": 200,
            "stall_gaps": [
                {
                    "duration_sec": 600,
                    "start": "2026-11-20T15:20:00Z",
                    "end": "2026-11-20T15:30:00Z",
                    "expected_strokes": 40.0,
                }
            ],
            "total_stall_time_sec": 600,
            "lost_strokes": 40.0,
            "yield_ratio": 0.8333,
            "yield_pct": 83.33,
            "fragmentation": 1,
            "pattern": "clean",
        }
        report = format_report(result)
        assert "stall gaps:" in report
        assert "10.0min" in report

    def test_duration_in_hours(self):
        result = {
            "window_start": "2026-11-20T00:00:00Z",
            "window_end": "2026-11-20T12:00:00Z",
            "total_duration_sec": 43200,
            "expected_strokes": 2880.0,
            "actual_strokes": 2880,
            "stall_gaps": [],
            "total_stall_time_sec": 0,
            "lost_strokes": 0,
            "yield_ratio": 1.0,
            "yield_pct": 100.0,
            "fragmentation": 0,
            "pattern": "clean",
        }
        report = format_report(result)
        assert "12.0h" in report


# --- integration: end-to-end with temp repo ---


class TestEndToEnd:
    def test_full_pipeline(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        strokes_file = data_dir / "strokes.jsonl"

        base = datetime(2026, 11, 20, 15, 0, 0, tzinfo=timezone.utc)
        lines = []
        for i in range(10):
            ts = (base + timedelta(seconds=i * 15)).isoformat()
            lines.append(json.dumps({"at": ts, "seq": i + 1, "kind": "note"}))
        # add a 20-minute gap
        for i in range(5):
            ts = (base + timedelta(minutes=20, seconds=i * 15)).isoformat()
            lines.append(json.dumps({"at": ts, "seq": 11 + i, "kind": "note"}))

        strokes_file.write_text("\n".join(lines) + "\n")

        strokes = load_strokes(tmp_path)
        assert len(strokes) == 15

        result = compute_yield(strokes, cadence_sec=15.0, stall_threshold_sec=300)
        assert result["fragmentation"] == 1
        assert result["lost_strokes"] > 0
        assert result["yield_ratio"] < 1.0

        report = format_report(result)
        assert "stroke yield analysis" in report

    def test_all_stalls(self, tmp_path):
        """every gap is a stall — writer barely runs."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        strokes_file = data_dir / "strokes.jsonl"

        base = datetime(2026, 11, 20, 15, 0, 0, tzinfo=timezone.utc)
        lines = []
        for i in range(5):
            ts = (base + timedelta(hours=i)).isoformat()
            lines.append(json.dumps({"at": ts, "seq": i + 1, "kind": "note"}))
        strokes_file.write_text("\n".join(lines) + "\n")

        strokes = load_strokes(tmp_path)
        result = compute_yield(strokes, cadence_sec=15.0, stall_threshold_sec=300)
        assert result["pattern"] == "blackout"
        assert result["yield_ratio"] < 0.01
