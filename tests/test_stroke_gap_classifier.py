#!/usr/bin/env python3
"""Tests for tools/stroke_gap_classifier.py — inter-stroke gap classification."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from stroke_gap_classifier import (
    DEGRADED_MULT,
    DEAD_MULT,
    STALL_MULT,
    GapReport,
    analyze,
    classify_gap,
    exit_code,
    format_text,
    parse_iso,
    read_last_stroke,
    run,
)


# ---------------------------------------------------------------------------
# parse_iso
# ---------------------------------------------------------------------------


class TestParseIso:
    def test_utc_z_suffix(self) -> None:
        epoch = parse_iso("2026-10-19T05:33:04Z")
        assert isinstance(epoch, float)
        assert epoch > 0

    def test_utc_offset(self) -> None:
        epoch = parse_iso("2026-10-19T05:33:04+00:00")
        assert isinstance(epoch, float)

    def test_positive_offset(self) -> None:
        epoch = parse_iso("2026-10-19T13:33:04+08:00")
        assert isinstance(epoch, float)

    def test_z_and_offset_agree(self) -> None:
        z = parse_iso("2026-10-19T05:33:04Z")
        off = parse_iso("2026-10-19T05:33:04+00:00")
        assert abs(z - off) < 1.0

    def test_whitespace_stripped(self) -> None:
        epoch = parse_iso("  2026-10-19T05:33:04Z  ")
        assert epoch > 0


# ---------------------------------------------------------------------------
# classify_gap
# ---------------------------------------------------------------------------


class TestClassifyGap:
    def test_zero_gap_is_healthy(self) -> None:
        assert classify_gap(0, cadence=15) == "healthy"

    def test_exactly_cadence_is_healthy(self) -> None:
        assert classify_gap(15, cadence=15) == "healthy"

    def test_exactly_2x_is_healthy(self) -> None:
        assert classify_gap(30, cadence=15) == "healthy"

    def test_just_over_2x_is_degraded(self) -> None:
        assert classify_gap(31, cadence=15) == "degraded"

    def test_exactly_5x_is_degraded(self) -> None:
        assert classify_gap(75, cadence=15) == "degraded"

    def test_just_over_5x_is_stalled(self) -> None:
        assert classify_gap(76, cadence=15) == "stalled"

    def test_exactly_20x_is_stalled(self) -> None:
        assert classify_gap(300, cadence=15) == "stalled"

    def test_just_over_20x_is_dead(self) -> None:
        assert classify_gap(301, cadence=15) == "dead"

    def test_very_large_gap_is_dead(self) -> None:
        assert classify_gap(99999, cadence=15) == "dead"

    def test_custom_cadence(self) -> None:
        # 60s cadence: healthy up to 120s, degraded up to 300s
        assert classify_gap(60, cadence=60) == "healthy"
        assert classify_gap(121, cadence=60) == "degraded"
        assert classify_gap(301, cadence=60) == "stalled"
        assert classify_gap(1201, cadence=60) == "dead"

    def test_zero_cadence_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            classify_gap(10, cadence=0)

    def test_negative_cadence_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            classify_gap(10, cadence=-5)


# ---------------------------------------------------------------------------
# read_last_stroke
# ---------------------------------------------------------------------------


class TestReadLastStroke:
    def test_reads_last_line(self, tmp_path: Path) -> None:
        f = tmp_path / "strokes.jsonl"
        f.write_text(
            '{"seq":1,"at":"2026-01-01T00:00:00Z"}\n'
            '{"seq":2,"at":"2026-01-01T00:00:15Z"}\n'
        )
        last = read_last_stroke(f)
        assert last["seq"] == 2

    def test_skips_blank_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "strokes.jsonl"
        f.write_text(
            '{"seq":1,"at":"2026-01-01T00:00:00Z"}\n\n\n'
            '{"seq":99,"at":"2026-01-01T01:00:00Z"}\n'
        )
        last = read_last_stroke(f)
        assert last["seq"] == 99

    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "strokes.jsonl"
        f.write_text(
            "not json at all\n"
            '{"seq":5,"at":"2026-01-01T00:05:00Z"}\n'
            "{bad json\n"
        )
        last = read_last_stroke(f)
        assert last["seq"] == 5

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            read_last_stroke(tmp_path / "nope.jsonl")

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "strokes.jsonl"
        f.write_text("")
        with pytest.raises(ValueError, match="empty"):
            read_last_stroke(f)

    def test_all_bad_json_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "strokes.jsonl"
        f.write_text("not json\nstill not json\n")
        with pytest.raises(ValueError, match="empty"):
            read_last_stroke(f)


# ---------------------------------------------------------------------------
# analyze (integration with tmp strokes)
# ---------------------------------------------------------------------------


class TestAnalyze:
    def test_healthy_gap(self, tmp_path: Path) -> None:
        f = tmp_path / "strokes.jsonl"
        f.write_text('{"seq":100,"at":"2026-10-19T06:00:00Z"}\n')
        # "now" is 10 seconds later — well within 2× 15s cadence
        report = analyze(f, cadence=15, now=parse_iso("2026-10-19T06:00:10Z"))
        assert report.band == "healthy"
        assert report.last_seq == 100

    def test_degraded_gap(self, tmp_path: Path) -> None:
        f = tmp_path / "strokes.jsonl"
        f.write_text('{"seq":200,"at":"2026-10-19T06:00:00Z"}\n')
        # 40s gap at 15s cadence = ~2.67× → degraded
        report = analyze(f, cadence=15, now=parse_iso("2026-10-19T06:00:40Z"))
        assert report.band == "degraded"

    def test_stalled_gap(self, tmp_path: Path) -> None:
        f = tmp_path / "strokes.jsonl"
        f.write_text('{"seq":300,"at":"2026-10-19T06:00:00Z"}\n')
        # 200s gap at 15s cadence = ~13.3× → stalled
        report = analyze(f, cadence=15, now=parse_iso("2026-10-19T06:03:20Z"))
        assert report.band == "stalled"

    def test_dead_gap(self, tmp_path: Path) -> None:
        f = tmp_path / "strokes.jsonl"
        f.write_text('{"seq":400,"at":"2026-10-19T06:00:00Z"}\n')
        # 600s gap at 15s cadence = 40× → dead
        report = analyze(f, cadence=15, now=parse_iso("2026-10-19T06:10:00Z"))
        assert report.band == "dead"

    def test_gap_ratio_calculation(self, tmp_path: Path) -> None:
        f = tmp_path / "strokes.jsonl"
        f.write_text('{"seq":500,"at":"2026-10-19T06:00:00Z"}\n')
        # 45s gap / 15s cadence = 3.0×
        report = analyze(f, cadence=15, now=parse_iso("2026-10-19T06:00:45Z"))
        assert abs(report.gap_ratio - 3.0) < 0.01

    def test_missing_at_field_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "strokes.jsonl"
        f.write_text('{"seq":1,"no_at_field":true}\n')
        with pytest.raises(ValueError, match="at"):
            analyze(f, cadence=15, now=parse_iso("2026-10-19T06:00:00Z"))

    def test_report_has_required_fields(self, tmp_path: Path) -> None:
        f = tmp_path / "strokes.jsonl"
        f.write_text('{"seq":42,"at":"2026-10-19T06:00:00Z"}\n')
        report = analyze(f, cadence=15, now=parse_iso("2026-10-19T06:00:30Z"))
        d = report.to_dict()
        for key in ("last_seq", "last_at", "last_epoch", "now_epoch",
                     "gap_seconds", "cadence", "band", "gap_ratio"):
            assert key in d


# ---------------------------------------------------------------------------
# exit_code
# ---------------------------------------------------------------------------


class TestExitCode:
    def test_healthy_returns_zero(self) -> None:
        r = GapReport(1, "", 0, 10, 10, 15, "healthy", 0.67)
        assert exit_code(r) == 0

    def test_degraded_returns_zero(self) -> None:
        r = GapReport(1, "", 0, 40, 40, 15, "degraded", 2.67)
        assert exit_code(r) == 0

    def test_stalled_returns_one(self) -> None:
        r = GapReport(1, "", 0, 100, 100, 15, "stalled", 6.67)
        assert exit_code(r) == 1

    def test_dead_returns_one(self) -> None:
        r = GapReport(1, "", 0, 9999, 9999, 15, "dead", 666.6)
        assert exit_code(r) == 1


# ---------------------------------------------------------------------------
# format_text
# ---------------------------------------------------------------------------


class TestFormatText:
    def test_contains_band(self) -> None:
        r = GapReport(42, "2026-10-19T06:00:00Z", 0, 10, 10, 15, "healthy", 0.67)
        text = format_text(r)
        assert "healthy" in text

    def test_contains_seq(self) -> None:
        r = GapReport(42, "2026-10-19T06:00:00Z", 0, 10, 10, 15, "healthy", 0.67)
        assert "seq=42" in format_text(r)

    def test_contains_cadence(self) -> None:
        r = GapReport(1, "", 0, 10, 10, 30, "healthy", 0.33)
        assert "30s" in format_text(r)


# ---------------------------------------------------------------------------
# CLI (subprocess)
# ---------------------------------------------------------------------------


class TestCLI:
    def test_json_output(self, tmp_path: Path) -> None:
        f = tmp_path / "strokes.jsonl"
        f.write_text('{"seq":1,"at":"2026-10-19T06:00:00Z"}\n')
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "stroke_gap_classifier.py"),
             "--strokes", str(f), "--json"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode in (0, 1)
        data = json.loads(result.stdout)
        assert "band" in data

    def test_text_output(self, tmp_path: Path) -> None:
        f = tmp_path / "strokes.jsonl"
        f.write_text('{"seq":1,"at":"2026-10-19T06:00:00Z"}\n')
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "stroke_gap_classifier.py"),
             "--strokes", str(f)],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode in (0, 1)
        assert "healthy" in result.stdout or "degraded" in result.stdout or \
               "stalled" in result.stdout or "dead" in result.stdout

    def test_missing_file_exits_2(self, tmp_path: Path) -> None:
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "stroke_gap_classifier.py"),
             "--strokes", str(tmp_path / "nope.jsonl")],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 2

    def test_custom_cadence(self, tmp_path: Path) -> None:
        f = tmp_path / "strokes.jsonl"
        f.write_text('{"seq":1,"at":"2026-10-19T06:00:00Z"}\n')
        # 60s gap with 60s cadence → 1.0× → healthy
        result = subprocess.run(
            [sys.executable, str(REPO / "tools" / "stroke_gap_classifier.py"),
             "--strokes", str(f), "--cadence", "60", "--json"],
            capture_output=True, text=True, timeout=10,
            env={**__import__("os").environ, "SOURCE_DATE_EPOCH": str(
                int(parse_iso("2026-10-19T06:01:00Z"))
            )},
        )
        # Can't control "now" via CLI, but at least verify it runs
        assert result.returncode in (0, 1)


# ---------------------------------------------------------------------------
# Boundary conditions
# ---------------------------------------------------------------------------


class TestBoundaries:
    """Verify exact multiplier thresholds."""

    @pytest.mark.parametrize("gap,cadence,expected", [
        (15 * DEGRADED_MULT, 15, "healthy"),        # exactly at boundary
        (15 * DEGRADED_MULT + 0.01, 15, "degraded"), # just over
        (15 * STALL_MULT, 15, "degraded"),           # exactly at boundary
        (15 * STALL_MULT + 0.01, 15, "stalled"),     # just over
        (15 * DEAD_MULT, 15, "stalled"),             # exactly at boundary
        (15 * DEAD_MULT + 0.01, 15, "dead"),         # just over
    ])
    def test_threshold_boundaries(
        self, gap: float, cadence: float, expected: str
    ) -> None:
        assert classify_gap(gap, cadence) == expected
