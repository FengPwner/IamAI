"""Tests for stroke_density — sliding-window density analysis."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_density import (
    classify_density,
    density_report,
    density_summary,
    parse_strokes_jsonl,
    window_density,
)


# ---------------------------------------------------------------------------
# classify_density — band mapping
# ---------------------------------------------------------------------------


class TestClassifyDensity:
    def test_zero_is_dormant(self):
        assert classify_density(0.0) == "dormant"

    def test_below_threshold_is_dormant(self):
        assert classify_density(0.49) == "dormant"

    def test_sparse_start(self):
        assert classify_density(0.5) == "sparse"

    def test_sparse_boundary(self):
        assert classify_density(1.49) == "sparse"

    def test_steady_start(self):
        assert classify_density(1.5) == "steady"

    def test_steady_mid(self):
        assert classify_density(2.5) == "steady"

    def test_steady_boundary(self):
        assert classify_density(3.49) == "steady"

    def test_dense_start(self):
        assert classify_density(3.5) == "dense"

    def test_dense_boundary(self):
        assert classify_density(5.99) == "dense"

    def test_hyper_start(self):
        assert classify_density(6.0) == "hyper"

    def test_hyper_large(self):
        assert classify_density(100.0) == "hyper"


# ---------------------------------------------------------------------------
# parse_strokes_jsonl
# ---------------------------------------------------------------------------


class TestParseStrokesJsonl:
    def test_basic_parse(self):
        lines = [
            json.dumps({"seq": 1, "at": "2026-10-01T10:00:00+00:00", "kind": "thought", "text": "hello"}),
            json.dumps({"seq": 2, "at": "2026-10-01T10:01:00+00:00", "kind": "note", "text": "world"}),
        ]
        result = parse_strokes_jsonl(lines)
        assert len(result) == 2
        assert result[0]["seq"] == 1
        assert result[1]["kind"] == "note"

    def test_sorted_by_time(self):
        lines = [
            json.dumps({"seq": 2, "at": "2026-10-01T10:05:00+00:00", "kind": "a", "text": ""}),
            json.dumps({"seq": 1, "at": "2026-10-01T10:00:00+00:00", "kind": "b", "text": ""}),
        ]
        result = parse_strokes_jsonl(lines)
        assert result[0]["seq"] == 1
        assert result[1]["seq"] == 2

    def test_skip_invalid_json(self):
        lines = [
            "not json at all",
            json.dumps({"seq": 1, "at": "2026-10-01T10:00:00+00:00", "kind": "x", "text": ""}),
        ]
        result = parse_strokes_jsonl(lines)
        assert len(result) == 1

    def test_skip_missing_at(self):
        lines = [
            json.dumps({"seq": 1, "kind": "x", "text": "no timestamp"}),
            json.dumps({"seq": 2, "at": "2026-10-01T10:00:00+00:00", "kind": "y", "text": ""}),
        ]
        result = parse_strokes_jsonl(lines)
        assert len(result) == 1
        assert result[0]["seq"] == 2

    def test_skip_empty_lines(self):
        lines = ["", "  ", json.dumps({"seq": 1, "at": "2026-10-01T10:00:00+00:00", "kind": "x", "text": ""})]
        result = parse_strokes_jsonl(lines)
        assert len(result) == 1

    def test_empty_input(self):
        assert parse_strokes_jsonl([]) == []

    def test_kind_defaults_to_unknown(self):
        lines = [json.dumps({"seq": 1, "at": "2026-10-01T10:00:00+00:00"})]
        result = parse_strokes_jsonl(lines)
        assert result[0]["kind"] == "unknown"


# ---------------------------------------------------------------------------
# window_density
# ---------------------------------------------------------------------------


class TestWindowDensity:
    def _make_strokes(self, n: int, interval_seconds: int = 15, start: datetime | None = None) -> list[dict]:
        """Generate n synthetic strokes with fixed interval."""
        base = start or datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
        return [
            {"seq": i + 1, "at": base + timedelta(seconds=i * interval_seconds), "kind": "thought", "text": ""}
            for i in range(n)
        ]

    def test_single_stroke_returns_empty(self):
        strokes = [{"seq": 1, "at": datetime(2026, 10, 1, tzinfo=timezone.utc), "kind": "x", "text": ""}]
        assert window_density(strokes) == []

    def test_empty_returns_empty(self):
        assert window_density([]) == []

    def test_steady_cadence_gives_steady_density(self):
        # 15s interval = 4 strokes/min → dense band over 10-min windows
        strokes = self._make_strokes(80, interval_seconds=15)
        windows = window_density(strokes, window_minutes=10, step_minutes=5)
        assert len(windows) > 0
        # most windows should be "dense" (4/min)
        dense_count = sum(1 for w in windows if w["band"] == "dense")
        assert dense_count >= len(windows) // 2

    def test_sparse_cadence(self):
        # one stroke every 60s = 1/min → sparse
        strokes = self._make_strokes(20, interval_seconds=60)
        windows = window_density(strokes, window_minutes=10, step_minutes=5)
        sparse_or_dormant = sum(1 for w in windows if w["band"] in ("sparse", "dormant"))
        assert sparse_or_dormant >= len(windows) // 2

    def test_window_count_field(self):
        strokes = self._make_strokes(40, interval_seconds=15)
        windows = window_density(strokes, window_minutes=10, step_minutes=10)
        # first 10-min window: 40 strokes at 15s = 4/min → 40 strokes in 10 min
        assert windows[0]["count"] == 40
        assert windows[0]["duration_min"] == 10.0

    def test_kinds_distribution(self):
        base = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
        strokes = []
        for i in range(20):
            kind = "thought" if i % 3 == 0 else "note"
            strokes.append({"seq": i, "at": base + timedelta(seconds=i * 15), "kind": kind, "text": ""})
        windows = window_density(strokes, window_minutes=10, step_minutes=10)
        kinds = windows[0]["kinds"]
        assert "thought" in kinds
        assert "note" in kinds
        assert kinds["thought"] + kinds["note"] == 20

    def test_step_controls_overlap(self):
        strokes = self._make_strokes(80, interval_seconds=15)
        w5 = window_density(strokes, window_minutes=10, step_minutes=5)
        w10 = window_density(strokes, window_minutes=10, step_minutes=10)
        # smaller step → more windows
        assert len(w5) > len(w10)


# ---------------------------------------------------------------------------
# density_summary
# ---------------------------------------------------------------------------


class TestDensitySummary:
    def _make_windows(self, densities: list[float]) -> list[dict]:
        base = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
        windows = []
        for i, d in enumerate(densities):
            start = base + timedelta(minutes=i * 10)
            windows.append({
                "start": start,
                "end": start + timedelta(minutes=10),
                "count": int(d * 10),
                "duration_min": 10.0,
                "density": d,
                "band": classify_density(d),
                "kinds": {"thought": int(d * 10)},
            })
        return windows

    def test_empty_windows(self):
        s = density_summary([])
        assert s["total_windows"] == 0
        assert s["dominant_band"] == "dormant"

    def test_mean_density(self):
        windows = self._make_windows([1.0, 2.0, 3.0])
        s = density_summary(windows)
        assert s["mean_density"] == 2.0

    def test_peak_window(self):
        windows = self._make_windows([1.0, 5.0, 2.0])
        s = density_summary(windows)
        assert s["peak_density"] == 5.0
        assert s["peak_window"]["density"] == 5.0

    def test_dominant_band(self):
        windows = self._make_windows([2.0, 2.5, 3.0, 0.1])  # 3 steady, 1 dormant
        s = density_summary(windows)
        assert s["dominant_band"] == "steady"

    def test_band_distribution_counts(self):
        windows = self._make_windows([0.2, 1.0, 2.0, 4.0, 7.0])
        s = density_summary(windows)
        assert s["band_distribution"]["dormant"] == 1
        assert s["band_distribution"]["sparse"] == 1
        assert s["band_distribution"]["steady"] == 1
        assert s["band_distribution"]["dense"] == 1
        assert s["band_distribution"]["hyper"] == 1

    def test_total_windows(self):
        windows = self._make_windows([1.0, 2.0, 3.0, 4.0])
        s = density_summary(windows)
        assert s["total_windows"] == 4


# ---------------------------------------------------------------------------
# density_report — integration
# ---------------------------------------------------------------------------


class TestDensityReport:
    def test_full_pipeline(self):
        base = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
        lines = []
        for i in range(60):
            lines.append(json.dumps({
                "seq": i + 1,
                "at": (base + timedelta(seconds=i * 15)).isoformat(),
                "kind": "thought",
                "text": f"stroke {i}",
            }))
        report = density_report(lines, window_minutes=10, step_minutes=5)
        assert report["strokes_parsed"] == 60
        assert len(report["windows"]) > 0
        assert report["summary"]["total_windows"] > 0
        assert report["summary"]["mean_density"] > 0

    def test_empty_input(self):
        report = density_report([], window_minutes=10, step_minutes=5)
        assert report["strokes_parsed"] == 0
        assert report["summary"]["total_windows"] == 0


# ---------------------------------------------------------------------------
# real-repo integration
# ---------------------------------------------------------------------------


class TestRealRepoIntegration:
    def test_against_repo_strokes(self):
        """Parse the actual data/strokes.jsonl if it exists."""
        path = REPO / "data" / "strokes.jsonl"
        if not path.exists():
            pytest.skip("data/strokes.jsonl not found")

        lines = path.read_text(encoding="utf-8").splitlines()
        report = density_report(lines, window_minutes=10, step_minutes=10)

        assert report["strokes_parsed"] > 100
        assert report["summary"]["total_windows"] > 0
        assert report["summary"]["dominant_band"] in (
            "dormant", "sparse", "steady", "dense", "hyper"
        )
        # mean density should be positive
        assert report["summary"]["mean_density"] > 0
