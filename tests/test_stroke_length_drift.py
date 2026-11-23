"""Tests for iamai.stroke_length_drift — stroke length trend analysis.

Visit 816: this module measures how stroke text length changes over time,
providing a signal of content quality degradation or verbosity creep.

Test areas:
     1. _mean                     — arithmetic mean helper
     2. _std                      — standard deviation helper
     3. _linear_slope             — OLS trend-line slope
     4. _bucket_means             — chunking into buckets
     5. _load_strokes             — JSONL loading (last n)
     6. stability_score           — sigmoid scoring
     7. stability_label           — band classification
     8. compute_drift             — full metric computation
     9. drift_report              — on-disk integration
    10. drift_summary             — human-readable output
    11. _cli                      — exit codes, --json flag
    12. edge cases                — empty, single, degenerate inputs
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_length_drift import (
    _bucket_means,
    _cli,
    _linear_slope,
    _load_strokes,
    _mean,
    _std,
    compute_drift,
    drift_report,
    drift_summary,
    stability_label,
    stability_score,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _stroke(text: str = "hello world", seq: int = 0, kind: str = "thought") -> dict:
    return {"seq": seq, "at": "2026-01-01T00:00:00+00:00", "kind": kind, "text": text}


def _write_strokes(tmp_path: Path, strokes: list[dict]) -> Path:
    p = tmp_path / "strokes.jsonl"
    with open(p, "w") as f:
        for s in strokes:
            f.write(json.dumps(s) + "\n")
    return p


# -----------------------------------------------------------------------
# 1. _mean
# -----------------------------------------------------------------------


class TestMean:
    def test_basic(self):
        assert _mean([2.0, 4.0, 6.0]) == pytest.approx(4.0)

    def test_single(self):
        assert _mean([7.0]) == pytest.approx(7.0)

    def test_empty(self):
        assert _mean([]) == 0.0

    def test_negative(self):
        assert _mean([-3.0, 3.0]) == pytest.approx(0.0)

    def test_large_values(self):
        assert _mean([1e6, 2e6, 3e6]) == pytest.approx(2e6)


# -----------------------------------------------------------------------
# 2. _std
# -----------------------------------------------------------------------


class TestStd:
    def test_uniform(self):
        assert _std([5.0, 5.0, 5.0]) == pytest.approx(0.0)

    def test_known(self):
        # std of [1,2,3,4,5] with sample formula = sqrt(2.5) ≈ 1.5811
        assert _std([1.0, 2.0, 3.0, 4.0, 5.0]) == pytest.approx(math.sqrt(2.5), abs=1e-4)

    def test_single_value(self):
        assert _std([42.0]) == 0.0

    def test_empty(self):
        assert _std([]) == 0.0

    def test_with_precomputed_mean(self):
        vals = [2.0, 4.0, 6.0]
        m = 4.0
        assert _std(vals, m) == pytest.approx(2.0, abs=1e-6)

    def test_two_values(self):
        # std of [0, 10] sample = sqrt((25+25)/1) = sqrt(50) ≈ 7.071
        assert _std([0.0, 10.0]) == pytest.approx(math.sqrt(50), abs=1e-4)


# -----------------------------------------------------------------------
# 3. _linear_slope
# -----------------------------------------------------------------------


class TestLinearSlope:
    def test_flat(self):
        assert _linear_slope([5.0, 5.0, 5.0, 5.0]) == pytest.approx(0.0)

    def test_positive(self):
        # y = 2x + 1 for x=0..3 → [1, 3, 5, 7]  slope ≈ 2.0
        assert _linear_slope([1.0, 3.0, 5.0, 7.0]) == pytest.approx(2.0, abs=1e-6)

    def test_negative(self):
        assert _linear_slope([7.0, 5.0, 3.0, 1.0]) == pytest.approx(-2.0, abs=1e-6)

    def test_single(self):
        assert _linear_slope([42.0]) == 0.0

    def test_empty(self):
        assert _linear_slope([]) == 0.0

    def test_two_points(self):
        assert _linear_slope([3.0, 7.0]) == pytest.approx(4.0, abs=1e-6)

    def test_noisy_positive(self):
        vals = [1.0, 2.5, 2.0, 5.0, 4.5, 6.0]
        slope = _linear_slope(vals)
        assert slope > 0.0


# -----------------------------------------------------------------------
# 4. _bucket_means
# -----------------------------------------------------------------------


class TestBucketMeans:
    def test_even_split(self):
        lengths = [10, 20, 30, 40]
        means = _bucket_means(lengths, 2)
        assert means == pytest.approx([15.0, 35.0])

    def test_single_bucket(self):
        means = _bucket_means([10, 20, 30], 1)
        assert means == pytest.approx([20.0])

    def test_more_buckets_than_items(self):
        means = _bucket_means([10, 20], 5)
        # size = max(1, 2//5) = 1; first bucket [10], second [20], rest empty
        assert len(means) >= 2

    def test_empty(self):
        assert _bucket_means([], 5) == []

    def test_zero_buckets(self):
        assert _bucket_means([10, 20], 0) == []

    def test_uneven_split(self):
        # 5 items, 2 buckets: size=2, bucket0=[10,20], bucket1=[30,40,50]
        means = _bucket_means([10, 20, 30, 40, 50], 2)
        assert means[0] == pytest.approx(15.0)
        assert means[1] == pytest.approx(40.0)

    def test_all_same(self):
        means = _bucket_means([7, 7, 7, 7], 2)
        assert all(m == pytest.approx(7.0) for m in means)


# -----------------------------------------------------------------------
# 5. _load_strokes
# -----------------------------------------------------------------------


class TestLoadStrokes:
    def test_basic_load(self, tmp_path):
        strokes = [_stroke(text=f"stroke {i}", seq=i) for i in range(10)]
        p = _write_strokes(tmp_path, strokes)
        loaded = _load_strokes(p, 5)
        assert len(loaded) == 5
        assert loaded[0]["seq"] == 5

    def test_n_larger_than_file(self, tmp_path):
        strokes = [_stroke(text="hi", seq=i) for i in range(3)]
        p = _write_strokes(tmp_path, strokes)
        loaded = _load_strokes(p, 100)
        assert len(loaded) == 3

    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        loaded = _load_strokes(p, 10)
        assert loaded == []


# -----------------------------------------------------------------------
# 6. stability_score
# -----------------------------------------------------------------------


class TestStabilityScore:
    def test_zero_drift(self):
        assert stability_score(0.0) == pytest.approx(1.0)

    def test_reference_drift(self):
        # At reference_drift=0.10, score should be 0.5
        assert stability_score(0.10) == pytest.approx(0.5)

    def test_negative_drift_same_as_positive(self):
        assert stability_score(0.05) == pytest.approx(stability_score(-0.05))

    def test_large_drift_near_zero(self):
        score = stability_score(1.0)
        assert 0.0 < score < 0.05

    def test_small_drift_near_one(self):
        score = stability_score(0.01)
        assert score > 0.95

    def test_custom_reference(self):
        assert stability_score(0.20, reference=0.20) == pytest.approx(0.5)

    def test_monotonic_decrease(self):
        scores = [stability_score(d) for d in [0.0, 0.05, 0.10, 0.15, 0.20, 0.30]]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]


# -----------------------------------------------------------------------
# 7. stability_label
# -----------------------------------------------------------------------


class TestStabilityLabel:
    def test_steady(self):
        assert stability_label(0.90) == "steady"
        assert stability_label(0.85) == "steady"

    def test_drifting(self):
        assert stability_label(0.60) == "drifting"
        assert stability_label(0.75) == "drifting"

    def test_shifting(self):
        assert stability_label(0.35) == "shifting"
        assert stability_label(0.50) == "shifting"

    def test_unstable(self):
        assert stability_label(0.0) == "unstable"
        assert stability_label(0.20) == "unstable"
        assert stability_label(0.34) == "unstable"

    def test_boundary_values(self):
        assert stability_label(0.849999) == "drifting"
        assert stability_label(0.599999) == "shifting"


# -----------------------------------------------------------------------
# 8. compute_drift
# -----------------------------------------------------------------------


class TestComputeDrift:
    def test_uniform_lengths(self):
        strokes = [_stroke(text="x" * 50, seq=i) for i in range(100)]
        result = compute_drift(strokes, bucket_count=5)
        assert result["total_strokes"] == 100
        assert result["overall_mean_length"] == pytest.approx(50.0)
        assert result["overall_std_length"] == pytest.approx(0.0)
        assert result["drift_rate"] == pytest.approx(0.0)
        assert result["stability_score"] == pytest.approx(1.0)
        assert result["stability_label"] == "steady"

    def test_growing_lengths(self):
        # Lengths grow linearly: 10, 20, 30, ..., 1000
        strokes = [_stroke(text="x" * (10 * (i + 1)), seq=i) for i in range(100)]
        result = compute_drift(strokes, bucket_count=5)
        assert result["drift_rate"] > 0.0
        assert result["stability_score"] < 0.5
        assert result["stability_label"] in ("shifting", "unstable")

    def test_shrinking_lengths(self):
        strokes = [_stroke(text="x" * (1000 - 10 * i), seq=i) for i in range(100)]
        result = compute_drift(strokes, bucket_count=5)
        assert result["drift_rate"] < 0.0

    def test_noisy_flat(self):
        # Random-looking but flat on average
        lengths = [50, 45, 55, 48, 52, 47, 53, 50, 49, 51] * 10
        strokes = [_stroke(text="x" * l, seq=i) for i, l in enumerate(lengths)]
        result = compute_drift(strokes, bucket_count=5)
        assert abs(result["drift_rate"]) < 0.05
        assert result["stability_score"] > 0.7

    def test_bucket_count_in_report(self):
        strokes = [_stroke(text="abc", seq=i) for i in range(50)]
        result = compute_drift(strokes, bucket_count=10)
        assert result["bucket_count"] == 10
        assert len(result["bucket_means"]) == 10

    def test_report_keys(self):
        strokes = [_stroke(text="hello", seq=0)]
        result = compute_drift(strokes, bucket_count=1)
        expected_keys = {
            "total_strokes", "bucket_count", "bucket_size",
            "overall_mean_length", "overall_std_length",
            "bucket_means", "trend_slope", "drift_rate",
            "stability_score", "stability_label",
        }
        assert set(result.keys()) == expected_keys


# -----------------------------------------------------------------------
# 9. drift_report
# -----------------------------------------------------------------------


class TestDriftReport:
    def test_on_disk(self, tmp_path):
        strokes = [_stroke(text="x" * 30, seq=i) for i in range(40)]
        p = _write_strokes(tmp_path, strokes)
        report = drift_report(n=40, bucket_count=4, strokes_path=p)
        assert report["total_strokes"] == 40
        assert report["overall_mean_length"] == pytest.approx(30.0)
        assert report["stability_label"] == "steady"

    def test_n_larger_than_file(self, tmp_path):
        strokes = [_stroke(text="abc", seq=i) for i in range(5)]
        p = _write_strokes(tmp_path, strokes)
        report = drift_report(n=100, bucket_count=2, strokes_path=p)
        assert report["total_strokes"] == 5


# -----------------------------------------------------------------------
# 10. drift_summary
# -----------------------------------------------------------------------


class TestDriftSummary:
    def test_steady_summary(self):
        report = {
            "total_strokes": 100,
            "bucket_count": 5,
            "bucket_size": 20,
            "overall_mean_length": 120.0,
            "overall_std_length": 15.0,
            "bucket_means": [118.0, 119.0, 121.0, 120.0, 122.0],
            "trend_slope": 0.5,
            "drift_rate": 0.004,
            "stability_score": 0.998,
            "stability_label": "steady",
        }
        summary = drift_summary(report)
        assert "100 strokes" in summary
        assert "120 chars" in summary
        assert "steady" in summary

    def test_growing_summary(self):
        report = {
            "total_strokes": 50,
            "bucket_count": 5,
            "bucket_size": 10,
            "overall_mean_length": 80.0,
            "overall_std_length": 20.0,
            "bucket_means": [60.0, 70.0, 80.0, 90.0, 100.0],
            "trend_slope": 10.0,
            "drift_rate": 0.125,
            "stability_score": 0.39,
            "stability_label": "shifting",
        }
        summary = drift_summary(report)
        assert "growing" in summary

    def test_shrinking_summary(self):
        report = {
            "total_strokes": 50,
            "bucket_count": 5,
            "bucket_size": 10,
            "overall_mean_length": 80.0,
            "overall_std_length": 20.0,
            "bucket_means": [100.0, 90.0, 80.0, 70.0, 60.0],
            "trend_slope": -10.0,
            "drift_rate": -0.125,
            "stability_score": 0.39,
            "stability_label": "shifting",
        }
        summary = drift_summary(report)
        assert "shrinking" in summary

    def test_empty_summary(self):
        report = {
            "total_strokes": 0,
            "bucket_count": 0,
            "bucket_size": 0,
            "overall_mean_length": 0.0,
            "overall_std_length": 0.0,
            "bucket_means": [],
            "trend_slope": 0.0,
            "drift_rate": 0.0,
            "stability_score": 1.0,
            "stability_label": "steady",
        }
        summary = drift_summary(report)
        assert "No strokes" in summary


# -----------------------------------------------------------------------
# 11. _cli
# -----------------------------------------------------------------------


class TestCLI:
    def test_plain_output(self, tmp_path, capsys):
        strokes = [_stroke(text="hello world", seq=i) for i in range(20)]
        p = _write_strokes(tmp_path, strokes)
        with patch("iamai.stroke_length_drift.DEFAULT_STROKES_PATH", p):
            rc = _cli(["-n", "20", "-b", "4"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "stroke_length_drift" in out

    def test_json_output(self, tmp_path, capsys):
        strokes = [_stroke(text="abc", seq=i) for i in range(10)]
        p = _write_strokes(tmp_path, strokes)
        with patch("iamai.stroke_length_drift.DEFAULT_STROKES_PATH", p):
            rc = _cli(["-n", "10", "-b", "2", "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "total_strokes" in data
        assert data["total_strokes"] == 10


# -----------------------------------------------------------------------
# 12. Edge cases
# -----------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_input(self):
        result = compute_drift([], bucket_count=5)
        assert result["total_strokes"] == 0
        assert result["stability_score"] == 1.0

    def test_single_stroke(self):
        result = compute_drift([_stroke(text="hi")], bucket_count=1)
        assert result["total_strokes"] == 1
        assert result["drift_rate"] == 0.0

    def test_all_empty_text(self):
        strokes = [_stroke(text="", seq=i) for i in range(20)]
        result = compute_drift(strokes, bucket_count=4)
        assert result["overall_mean_length"] == 0.0
        assert result["drift_rate"] == 0.0

    def test_missing_text_key(self):
        strokes = [{"seq": i, "at": "2026-01-01T00:00:00+00:00"} for i in range(20)]
        result = compute_drift(strokes, bucket_count=4)
        assert result["overall_mean_length"] == 0.0

    def test_very_long_text(self):
        strokes = [_stroke(text="x" * 100000, seq=i) for i in range(20)]
        result = compute_drift(strokes, bucket_count=4)
        assert result["overall_mean_length"] == pytest.approx(100000.0)

    def test_mixed_lengths_growing(self):
        # First half short, second half long → positive drift
        short = [_stroke(text="hi", seq=i) for i in range(10)]
        long = [_stroke(text="x" * 200, seq=i) for i in range(10, 20)]
        result = compute_drift(short + long, bucket_count=4)
        assert result["drift_rate"] > 0.0

    def test_bucket_count_one(self):
        strokes = [_stroke(text="x" * 50, seq=i) for i in range(10)]
        result = compute_drift(strokes, bucket_count=1)
        assert result["bucket_count"] == 1
        assert len(result["bucket_means"]) == 1

    def test_more_buckets_than_strokes(self):
        strokes = [_stroke(text="abc", seq=i) for i in range(3)]
        result = compute_drift(strokes, bucket_count=100)
        assert result["total_strokes"] == 3
        assert result["bucket_count"] >= 1

    def test_drift_rate_normalized_by_mean(self):
        # Same absolute slope but different means → different drift_rate
        short_strokes = [_stroke(text="x" * 10, seq=i) for i in range(50)]
        long_strokes = [_stroke(text="x" * 1000, seq=i) for i in range(50)]
        # Both have slope ≈ 0 → drift_rate ≈ 0
        r_short = compute_drift(short_strokes, bucket_count=5)
        r_long = compute_drift(long_strokes, bucket_count=5)
        assert abs(r_short["drift_rate"]) < 0.01
        assert abs(r_long["drift_rate"]) < 0.01
