#!/usr/bin/env python3
"""Tests for tempo_variance — writer cadence consistency metrics."""

import json
import math
import tempfile
from pathlib import Path

import pytest

from iamai.tempo_variance import (
    gap_seconds,
    variance,
    stddev,
    coefficient_of_variation,
    classify,
    is_steady,
    from_strokes,
    DEFAULT_THRESHOLDS,
)


# ---------------------------------------------------------------------------
# gap_seconds
# ---------------------------------------------------------------------------

class TestGapSeconds:
    def test_empty_input(self):
        assert gap_seconds([]) == []

    def test_single_timestamp(self):
        assert gap_seconds(["2026-11-03T10:00:00+00:00"]) == []

    def test_two_timestamps(self):
        ts = ["2026-11-03T10:00:00+00:00", "2026-11-03T10:00:15+00:00"]
        assert gap_seconds(ts) == [15.0]

    def test_unsorted_input_is_sorted(self):
        ts = ["2026-11-03T10:01:00+00:00", "2026-11-03T10:00:00+00:00"]
        assert gap_seconds(ts) == [60.0]

    def test_multiple_gaps(self):
        ts = [
            "2026-11-03T10:00:00+00:00",
            "2026-11-03T10:00:10+00:00",
            "2026-11-03T10:00:30+00:00",
        ]
        assert gap_seconds(ts) == [10.0, 20.0]

    def test_identical_timestamps(self):
        ts = ["2026-11-03T10:00:00+00:00"] * 5
        assert gap_seconds(ts) == [0.0, 0.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# variance & stddev
# ---------------------------------------------------------------------------

class TestVarianceStddev:
    def test_empty(self):
        assert variance([]) == 0.0
        assert stddev([]) == 0.0

    def test_single_value(self):
        assert variance([42.0]) == 0.0
        assert stddev([42.0]) == 0.0

    def test_uniform_gaps(self):
        gaps = [15.0, 15.0, 15.0, 15.0]
        assert variance(gaps) == 0.0
        assert stddev(gaps) == 0.0

    def test_known_variance(self):
        gaps = [10.0, 20.0, 30.0]
        # mean = 20, var = ((100+0+100)/3) = 66.666...
        assert abs(variance(gaps) - 66.6667) < 0.01

    def test_stddev_is_sqrt_of_variance(self):
        gaps = [5.0, 15.0, 25.0, 35.0]
        assert abs(stddev(gaps) - math.sqrt(variance(gaps))) < 1e-10

    def test_non_negative(self):
        for gaps in [[1.0], [0.0, 0.0], [100.0, 1.0], [0.5, 0.5, 0.5]]:
            assert variance(gaps) >= 0.0
            assert stddev(gaps) >= 0.0


# ---------------------------------------------------------------------------
# coefficient_of_variation
# ---------------------------------------------------------------------------

class TestCV:
    def test_empty(self):
        assert coefficient_of_variation([]) == 0.0

    def test_single_gap(self):
        assert coefficient_of_variation([15.0]) == 0.0

    def test_uniform(self):
        assert coefficient_of_variation([15.0, 15.0, 15.0]) == 0.0

    def test_known_cv(self):
        gaps = [10.0, 20.0, 30.0]
        # mean=20, stddev=sqrt(66.667)≈8.165, cv≈0.4082
        cv = coefficient_of_variation(gaps)
        assert abs(cv - 0.4082) < 0.01

    def test_zero_mean_returns_zero(self):
        assert coefficient_of_variation([0.0, 0.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_steady(self):
        assert classify(0.05) == "steady"

    def test_normal(self):
        assert classify(0.2) == "normal"

    def test_irregular(self):
        assert classify(0.45) == "irregular"

    def test_erratic(self):
        assert classify(0.8) == "erratic"

    def test_boundary_steady(self):
        assert classify(0.09) == "steady"

    def test_boundary_not_steady(self):
        assert classify(0.1) == "normal"

    def test_custom_thresholds(self):
        custom = [(0.5, "ok"), (1.0, "bad")]
        assert classify(0.3, custom) == "ok"
        assert classify(0.7, custom) == "bad"
        assert classify(1.5, custom) == "erratic"


# ---------------------------------------------------------------------------
# is_steady
# ---------------------------------------------------------------------------

class TestIsSteady:
    def test_empty_is_steady(self):
        assert is_steady([]) is True

    def test_uniform_is_steady(self):
        assert is_steady([15.0, 15.0, 15.0]) is True

    def test_wild_gaps_not_steady(self):
        assert is_steady([1.0, 3600.0, 2.0, 7200.0]) is False

    def test_custom_threshold(self):
        gaps = [10.0, 12.0, 11.0]
        assert is_steady(gaps, max_cv=0.5) is True


# ---------------------------------------------------------------------------
# from_strokes
# ---------------------------------------------------------------------------

class TestFromStrokes:
    @pytest.fixture
    def strokes_file(self, tmp_path):
        path = tmp_path / "strokes.jsonl"
        lines = []
        base = "2026-11-03T10:00:00+00:00"
        for i in range(10):
            ts = f"2026-11-03T10:{i:02d}:00+00:00"
            lines.append(json.dumps({"seq": i, "at": ts, "kind": "thought", "text": f"t{i}"}))
        path.write_text("\n".join(lines) + "\n")
        return path

    def test_returns_dict(self, strokes_file):
        result = from_strokes(strokes_file)
        assert isinstance(result, dict)
        assert "cv" in result
        assert "label" in result

    def test_count(self, strokes_file):
        result = from_strokes(strokes_file)
        assert result["count"] == 10

    def test_gaps_count(self, strokes_file):
        result = from_strokes(strokes_file)
        assert result["gaps"] == 9

    def test_last_n(self, strokes_file):
        result = from_strokes(strokes_file, last_n=5)
        assert result["count"] == 5
        assert result["gaps"] == 4

    def test_uniform_strokes_is_steady(self, strokes_file):
        result = from_strokes(strokes_file)
        # All 60-second gaps → cv = 0 → steady
        assert result["steady"] is True
        assert result["label"] == "steady"

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        result = from_strokes(path)
        assert result["count"] == 0
        assert result["cv"] == 0.0
