"""Tests for iamai.content_diversity module."""

from __future__ import annotations

import json
import math
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.content_diversity import (
    ALL_KINDS,
    _grade_diversity,
    _load_strokes,
    _max_entropy,
    _parse_timestamp,
    _shannon_entropy,
    _strokes_in_window,
    diversity_report,
    diversity_summary,
    diversity_trend,
)


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------


class TestParseTimestamp:
    def test_utc_offset(self):
        dt = _parse_timestamp("2026-10-06T09:00:00+00:00")
        assert dt.tzinfo is not None
        assert dt.hour == 9

    def test_z_suffix(self):
        dt = _parse_timestamp("2026-10-06T09:00:00Z")
        assert dt.tzinfo is not None
        assert dt.hour == 9

    def test_bare_datetime(self):
        dt = _parse_timestamp("2026-10-06T09:00:00")
        assert dt.tzinfo == timezone.utc

    def test_whitespace_stripped(self):
        dt = _parse_timestamp("  2026-10-06T09:00:00Z  ")
        assert dt.hour == 9


# ---------------------------------------------------------------------------
# Stroke loading
# ---------------------------------------------------------------------------


def _write_jsonl(lines: list[dict], path: Path) -> None:
    """Helper to write JSONL data."""
    with open(path, "w", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")


class TestLoadStrokes:
    def test_basic_loading(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        _write_jsonl([
            {"seq": 1, "at": "2026-10-06T09:00:00Z", "kind": "thought"},
            {"seq": 2, "at": "2026-10-06T09:01:00Z", "kind": "snippet"},
        ], p)
        strokes = _load_strokes(p)
        assert len(strokes) == 2
        assert "_dt" in strokes[0]

    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        assert _load_strokes(p) == []

    def test_malformed_lines_skipped(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        with open(p, "w") as f:
            f.write("not json\n")
            f.write(json.dumps({"seq": 1, "at": "2026-10-06T09:00:00Z", "kind": "thought"}) + "\n")
            f.write("{bad json\n")
        strokes = _load_strokes(p)
        assert len(strokes) == 1

    def test_missing_keys_skipped(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        _write_jsonl([{"seq": 1}], p)  # missing "at"
        assert _load_strokes(p) == []

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _load_strokes(tmp_path / "nope.jsonl")


# ---------------------------------------------------------------------------
# Window filtering
# ---------------------------------------------------------------------------


class TestStrokesInWindow:
    def test_all_within(self):
        now = datetime(2026, 10, 6, 10, 0, 0, tzinfo=timezone.utc)
        strokes = [
            {"_dt": datetime(2026, 10, 6, 9, 30, 0, tzinfo=timezone.utc)},
            {"_dt": datetime(2026, 10, 6, 9, 45, 0, tzinfo=timezone.utc)},
        ]
        result = _strokes_in_window(strokes, now, 1.0)
        assert len(result) == 2

    def test_some_outside(self):
        now = datetime(2026, 10, 6, 10, 0, 0, tzinfo=timezone.utc)
        strokes = [
            {"_dt": datetime(2026, 10, 6, 8, 0, 0, tzinfo=timezone.utc)},
            {"_dt": datetime(2026, 10, 6, 9, 30, 0, tzinfo=timezone.utc)},
        ]
        result = _strokes_in_window(strokes, now, 1.0)
        assert len(result) == 1

    def test_empty_window(self):
        now = datetime(2026, 10, 6, 10, 0, 0, tzinfo=timezone.utc)
        strokes = [
            {"_dt": datetime(2026, 10, 5, 10, 0, 0, tzinfo=timezone.utc)},
        ]
        assert _strokes_in_window(strokes, now, 1.0) == []


# ---------------------------------------------------------------------------
# Shannon entropy
# ---------------------------------------------------------------------------


class TestShannonEntropy:
    def test_single_kind(self):
        c = {"thought": 100}
        assert _shannon_entropy(c, 100) == 0.0

    def test_two_equal_kinds(self):
        c = {"thought": 50, "snippet": 50}
        h = _shannon_entropy(c, 100)
        assert abs(h - math.log(2)) < 1e-9

    def test_six_equal_kinds(self):
        c = {k: 100 for k in ALL_KINDS}
        h = _shannon_entropy(c, 600)
        assert abs(h - math.log(6)) < 1e-9

    def test_empty(self):
        assert _shannon_entropy({}, 0) == 0.0

    def test_skewed(self):
        c = {"thought": 95, "snippet": 5}
        h = _shannon_entropy(c, 100)
        # Entropy should be low for skewed distribution
        assert 0 < h < math.log(2)


# ---------------------------------------------------------------------------
# Max entropy
# ---------------------------------------------------------------------------


class TestMaxEntropy:
    def test_six_kinds(self):
        assert abs(_max_entropy(6) - math.log(6)) < 1e-9

    def test_one_kind(self):
        assert _max_entropy(1) == 0.0

    def test_two_kinds(self):
        assert abs(_max_entropy(2) - math.log(2)) < 1e-9


# ---------------------------------------------------------------------------
# Grade assignment
# ---------------------------------------------------------------------------


class TestGradeDiversity:
    def test_grade_a(self):
        assert _grade_diversity(0.95) == "A"
        assert _grade_diversity(0.90) == "A"
        assert _grade_diversity(1.00) == "A"

    def test_grade_b(self):
        assert _grade_diversity(0.85) == "B"
        assert _grade_diversity(0.75) == "B"

    def test_grade_c(self):
        assert _grade_diversity(0.60) == "C"
        assert _grade_diversity(0.50) == "C"

    def test_grade_f(self):
        assert _grade_diversity(0.49) == "F"
        assert _grade_diversity(0.0) == "F"
        assert _grade_diversity(0.10) == "F"


# ---------------------------------------------------------------------------
# Diversity report (integration)
# ---------------------------------------------------------------------------


class TestDiversityReport:
    def test_perfect_diversity(self, tmp_path):
        """All six kinds equally represented."""
        p = tmp_path / "strokes.jsonl"
        base = datetime(2026, 10, 6, 9, 0, 0, tzinfo=timezone.utc)
        lines = []
        seq = 1
        for k in ALL_KINDS:
            for i in range(10):
                lines.append({
                    "seq": seq,
                    "at": (base + timedelta(seconds=seq * 15)).isoformat(),
                    "kind": k,
                })
                seq += 1
        _write_jsonl(lines, p)

        now = base + timedelta(hours=1)
        report = diversity_report(window_hours=1.0, strokes_path=p, now=now)

        assert report["total"] == 60
        assert report["grade"] == "A"
        assert report["underrepresented"] == []
        assert abs(report["entropy"] - math.log(6)) < 0.01
        assert abs(report["effective_kinds"] - 6.0) < 0.1
        assert report["normalized_entropy"] > 0.95

    def test_skewed_diversity(self, tmp_path):
        """Only one kind present — minimum diversity."""
        p = tmp_path / "strokes.jsonl"
        base = datetime(2026, 10, 6, 9, 0, 0, tzinfo=timezone.utc)
        lines = [
            {"seq": i, "at": (base + timedelta(seconds=i * 15)).isoformat(), "kind": "thought"}
            for i in range(1, 21)
        ]
        _write_jsonl(lines, p)

        now = base + timedelta(hours=1)
        report = diversity_report(window_hours=1.0, strokes_path=p, now=now)

        assert report["total"] == 20
        assert report["entropy"] == 0.0
        assert report["effective_kinds"] == 0.0 or report["effective_kinds"] == 1.0
        assert report["grade"] == "F"
        # All other kinds are underrepresented
        assert set(report["underrepresented"]) == set(ALL_KINDS) - {"thought"}

    def test_moderate_diversity(self, tmp_path):
        """Three of six kinds present equally."""
        p = tmp_path / "strokes.jsonl"
        base = datetime(2026, 10, 6, 9, 0, 0, tzinfo=timezone.utc)
        kinds = ("thought", "snippet", "note")
        lines = []
        seq = 1
        for k in kinds:
            for i in range(10):
                lines.append({
                    "seq": seq,
                    "at": (base + timedelta(seconds=seq * 15)).isoformat(),
                    "kind": k,
                })
                seq += 1
        _write_jsonl(lines, p)

        now = base + timedelta(hours=1)
        report = diversity_report(window_hours=1.0, strokes_path=p, now=now)

        assert report["total"] == 30
        assert report["grade"] in ("B", "C")
        assert "devlog" in report["underrepresented"]
        assert "garden" in report["underrepresented"]
        assert "metrics" in report["underrepresented"]

    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        now = datetime(2026, 10, 6, 10, 0, 0, tzinfo=timezone.utc)
        report = diversity_report(window_hours=1.0, strokes_path=p, now=now)

        assert report["total"] == 0
        assert report["entropy"] == 0.0
        assert report["effective_kinds"] == 0.0
        assert report["grade"] == "F"
        assert len(report["underrepresented"]) == len(ALL_KINDS)

    def test_missing_file(self, tmp_path):
        now = datetime(2026, 10, 6, 10, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(FileNotFoundError):
            diversity_report(window_hours=1.0, strokes_path=tmp_path / "nope.jsonl", now=now)

    def test_kind_fractions_sum_to_one(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        base = datetime(2026, 10, 6, 9, 0, 0, tzinfo=timezone.utc)
        lines = [
            {"seq": i, "at": (base + timedelta(seconds=i * 15)).isoformat(), "kind": ALL_KINDS[i % 6]}
            for i in range(1, 61)
        ]
        _write_jsonl(lines, p)

        now = base + timedelta(hours=1)
        report = diversity_report(window_hours=1.0, strokes_path=p, now=now)

        total_frac = sum(report["kind_fractions"].values())
        assert abs(total_frac - 1.0) < 0.01


# ---------------------------------------------------------------------------
# Diversity summary
# ---------------------------------------------------------------------------


class TestDiversitySummary:
    def test_with_data(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        base = datetime(2026, 10, 6, 9, 0, 0, tzinfo=timezone.utc)
        lines = []
        seq = 1
        for k in ALL_KINDS:
            for i in range(10):
                lines.append({
                    "seq": seq,
                    "at": (base + timedelta(seconds=seq * 15)).isoformat(),
                    "kind": k,
                })
                seq += 1
        _write_jsonl(lines, p)

        now = base + timedelta(hours=1)
        # Need to pass strokes_path via the report, but summary doesn't
        # accept now. We test by ensuring the file is recent enough.
        # Instead, test the format via a report-based check.
        summary = diversity_summary(window_hours=24.0, strokes_path=p)
        assert "diversity" in summary
        assert "effective kinds" in summary
        assert "entropy" in summary

    def test_format_contains_grade(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        base = datetime(2026, 10, 6, 9, 0, 0, tzinfo=timezone.utc)
        lines = [
            {"seq": 1, "at": base.isoformat(), "kind": "thought"},
        ]
        _write_jsonl(lines, p)

        summary = diversity_summary(window_hours=24.0, strokes_path=p)
        # Should contain one of A/B/C/F as grade
        assert any(f"diversity {g}:" in summary for g in ("A", "B", "C", "F"))


# ---------------------------------------------------------------------------
# Diversity trend
# ---------------------------------------------------------------------------


class TestDiversityTrend:
    def test_stable_trend(self, tmp_path):
        """Same distribution in short and long windows → stable."""
        p = tmp_path / "strokes.jsonl"
        base = datetime(2026, 10, 6, 4, 0, 0, tzinfo=timezone.utc)
        lines = []
        seq = 1
        # Uniform distribution over 6 hours
        for minute in range(360):
            k = ALL_KINDS[minute % 6]
            lines.append({
                "seq": seq,
                "at": (base + timedelta(minutes=minute)).isoformat(),
                "kind": k,
            })
            seq += 1
        _write_jsonl(lines, p)

        now = base + timedelta(hours=6)
        trend = diversity_trend(strokes_path=p, now=now)

        assert trend["verdict"] == "stable"
        assert trend["long_effective"] > 0

    def test_unknown_when_no_long_data(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        now = datetime(2026, 10, 6, 10, 0, 0, tzinfo=timezone.utc)
        trend = diversity_trend(strokes_path=p, now=now)
        assert trend["verdict"] == "unknown"

    def test_improving_trend(self, tmp_path):
        """Long window is skewed, short window is balanced → improving."""
        p = tmp_path / "strokes.jsonl"
        base = datetime(2026, 10, 6, 4, 0, 0, tzinfo=timezone.utc)
        lines = []
        seq = 1

        # First 5 hours: only "thought" strokes
        for i in range(300):
            lines.append({
                "seq": seq,
                "at": (base + timedelta(minutes=i)).isoformat(),
                "kind": "thought",
            })
            seq += 1

        # Last 1 hour: all six kinds equally
        for i in range(60):
            k = ALL_KINDS[i % 6]
            lines.append({
                "seq": seq,
                "at": (base + timedelta(minutes=300 + i)).isoformat(),
                "kind": k,
            })
            seq += 1

        _write_jsonl(lines, p)

        now = base + timedelta(hours=6)
        trend = diversity_trend(strokes_path=p, now=now)

        assert trend["verdict"] == "improving"
        assert trend["short_effective"] > trend["long_effective"]
