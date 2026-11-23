"""Tests for iamai.stroke_gap_regularity — gap timing analysis.

Visit 809: this module measures the regularity of inter-stroke gaps,
providing an early signal of writer degradation before full stalls.

Test areas:
    1. _parse_timestamp     — ISO 8601 parsing
    2. compute_gaps         — inter-stroke interval computation
    3. _median / _mean      — statistical helpers
    4. find_anomalous_gaps  — outlier gap detection
    5. regularity_score     — CV-based sigmoid scoring
    6. regularity_label     — band classification
    7. gap_report           — full report structure
    8. gap_summary          — human-readable format
    9. _cli                 — exit codes, --json flag
   10. edge cases           — empty input, single stroke, zero gaps
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_gap_regularity import (
    _cli,
    _load_strokes_with_timestamps,
    _median,
    _mean,
    _parse_timestamp,
    _std,
    compute_gaps,
    find_anomalous_gaps,
    gap_report,
    gap_report,
    gap_summary,
    regularity_label,
    regularity_score,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _stroke_at(at: str, seq: int = 0, kind: str = "thought", text: str = "hello") -> dict:
    return {"seq": seq, "at": at, "kind": kind, "text": text}


def _write_strokes(tmp_path: Path, strokes: list[dict]) -> Path:
    p = tmp_path / "strokes.jsonl"
    lines = [json.dumps(s) for s in strokes]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _ts_series(start: datetime, n: int, interval_sec: float) -> list[dict]:
    """Generate n strokes with fixed interval."""
    return [
        _stroke_at(_iso(start + timedelta(seconds=i * interval_sec)), seq=i)
        for i in range(n)
    ]


_BASE = datetime(2026, 11, 23, 0, 0, 0, tzinfo=timezone.utc)


# -----------------------------------------------------------------------
# 1. _parse_timestamp
# -----------------------------------------------------------------------


class TestParseTimestamp:
    def test_iso_with_offset(self):
        dt = _parse_timestamp("2026-11-23T08:00:00+08:00")
        assert dt.hour == 8
        assert dt.utcoffset() == timedelta(hours=8)

    def test_iso_with_z(self):
        dt = _parse_timestamp("2026-11-23T00:00:00Z")
        assert dt.tzinfo is not None
        assert dt.utcoffset() == timedelta(0)

    def test_iso_utc(self):
        dt = _parse_timestamp("2026-11-23T00:00:00+00:00")
        assert dt.year == 2026
        assert dt.month == 11
        assert dt.day == 23

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _parse_timestamp("not-a-date")

    def test_whitespace_stripped(self):
        dt = _parse_timestamp("  2026-11-23T00:00:00+00:00  ")
        assert dt.year == 2026


# -----------------------------------------------------------------------
# 2. compute_gaps
# -----------------------------------------------------------------------


class TestComputeGaps:
    def test_regular_intervals(self):
        strokes = _ts_series(_BASE, 5, 15.0)
        gaps = compute_gaps(strokes)
        assert len(gaps) == 4
        assert all(g == pytest.approx(15.0, abs=0.01) for g in gaps)

    def test_varying_intervals(self):
        strokes = [
            _stroke_at(_iso(_BASE)),
            _stroke_at(_iso(_BASE + timedelta(seconds=10))),
            _stroke_at(_iso(_BASE + timedelta(seconds=30))),
            _stroke_at(_iso(_BASE + timedelta(seconds=35))),
        ]
        gaps = compute_gaps(strokes)
        assert gaps == pytest.approx([10.0, 20.0, 5.0], abs=0.01)

    def test_single_stroke(self):
        gaps = compute_gaps([_stroke_at(_iso(_BASE))])
        assert gaps == []

    def test_empty(self):
        assert compute_gaps([]) == []

    def test_negative_clamped_to_zero(self):
        # Out-of-order timestamps
        strokes = [
            _stroke_at(_iso(_BASE + timedelta(seconds=30))),
            _stroke_at(_iso(_BASE)),
        ]
        gaps = compute_gaps(strokes)
        assert len(gaps) == 1
        assert gaps[0] == 0.0

    def test_large_gap(self):
        strokes = [
            _stroke_at(_iso(_BASE)),
            _stroke_at(_iso(_BASE + timedelta(hours=8))),
        ]
        gaps = compute_gaps(strokes)
        assert gaps[0] == pytest.approx(8 * 3600, abs=1)


# -----------------------------------------------------------------------
# 3. _median / _mean / _std
# -----------------------------------------------------------------------


class TestStatistics:
    def test_median_odd(self):
        assert _median([3, 1, 2]) == 2.0

    def test_median_even(self):
        assert _median([1, 2, 3, 4]) == 2.5

    def test_median_single(self):
        assert _median([42.0]) == 42.0

    def test_median_empty(self):
        assert _median([]) == 0.0

    def test_mean_basic(self):
        assert _mean([10, 20, 30]) == pytest.approx(20.0)

    def test_mean_empty(self):
        assert _mean([]) == 0.0

    def test_std_uniform(self):
        assert _std([5, 5, 5, 5]) == pytest.approx(0.0)

    def test_std_known(self):
        # std of [2, 4, 4, 4, 5, 5, 7, 9] = 2.0
        assert _std([2, 4, 4, 4, 5, 5, 7, 9]) == pytest.approx(2.0)

    def test_std_single(self):
        assert _std([100]) == 0.0


# -----------------------------------------------------------------------
# 4. find_anomalous_gaps
# -----------------------------------------------------------------------


class TestFindAnomalousGaps:
    def test_no_anomalies(self):
        gaps = [15.0, 16.0, 14.0, 15.5, 15.0]
        result = find_anomalous_gaps(gaps)
        assert result == []

    def test_one_anomaly(self):
        gaps = [15.0, 15.0, 300.0, 15.0, 15.0]
        result = find_anomalous_gaps(gaps)
        assert len(result) == 1
        assert result[0] == (2, 300.0)

    def test_multiple_anomalies(self):
        gaps = [15.0, 500.0, 15.0, 1000.0, 15.0]
        result = find_anomalous_gaps(gaps)
        assert len(result) == 2

    def test_custom_multiplier(self):
        gaps = [10.0, 10.0, 25.0, 10.0]
        # median=10, threshold=25 with mult=2.5 → 25 is NOT anomalous
        result = find_anomalous_gaps(gaps, multiplier=2.5)
        assert len(result) == 0
        # But with mult=2.0 → threshold=20, 25 IS anomalous
        result = find_anomalous_gaps(gaps, multiplier=2.0)
        assert len(result) == 1

    def test_empty_gaps(self):
        assert find_anomalous_gaps([]) == []

    def test_explicit_median(self):
        gaps = [10.0, 10.0, 100.0, 10.0]
        result = find_anomalous_gaps(gaps, median_gap=10.0, multiplier=3.0)
        assert len(result) == 1
        assert result[0] == (2, 100.0)

    def test_zero_median(self):
        gaps = [0.0, 0.0, 0.0]
        assert find_anomalous_gaps(gaps) == []


# -----------------------------------------------------------------------
# 5. regularity_score
# -----------------------------------------------------------------------


class TestRegularityScore:
    def test_perfect_regularity(self):
        gaps = [15.0] * 100
        score = regularity_score(gaps)
        assert score == pytest.approx(1.0, abs=0.001)

    def test_moderate_jitter(self):
        # CV ≈ 0.3 should yield score ≈ 0.5
        import random
        random.seed(42)
        gaps = [15.0 + random.gauss(0, 4.5) for _ in range(1000)]
        gaps = [max(0.1, g) for g in gaps]
        score = regularity_score(gaps)
        assert 0.3 < score < 0.7

    def test_high_irregularity(self):
        gaps = [15.0, 500.0, 15.0, 1000.0, 15.0, 200.0, 15.0]
        score = regularity_score(gaps)
        assert score < 0.2

    def test_empty_input(self):
        assert regularity_score([]) == 0.0

    def test_single_gap(self):
        assert regularity_score([15.0]) == 1.0

    def test_score_range(self):
        for gaps in [[1, 1, 1], [1, 100, 1], [50, 50, 50, 50]]:
            s = regularity_score(gaps)
            assert 0.0 <= s <= 1.0

    def test_custom_reference_cv(self):
        gaps = [15.0, 18.0, 12.0, 16.0, 14.0]
        # With very small reference_cv, score should be lower
        s_small = regularity_score(gaps, reference_cv=0.01)
        s_large = regularity_score(gaps, reference_cv=10.0)
        assert s_small < s_large


# -----------------------------------------------------------------------
# 6. regularity_label
# -----------------------------------------------------------------------


class TestRegularityLabel:
    def test_clockwork(self):
        assert regularity_label(0.9) == "clockwork"
        assert regularity_label(0.8) == "clockwork"

    def test_steady(self):
        assert regularity_label(0.5) == "steady"
        assert regularity_label(0.79) == "steady"

    def test_jittery(self):
        assert regularity_label(0.2) == "jittery"
        assert regularity_label(0.49) == "jittery"

    def test_erratic(self):
        assert regularity_label(0.0) == "erratic"
        assert regularity_label(0.19) == "erratic"


# -----------------------------------------------------------------------
# 7. gap_report
# -----------------------------------------------------------------------


class TestGapReport:
    def test_basic_report(self, tmp_path):
        strokes = _ts_series(_BASE, 20, 15.0)
        p = _write_strokes(tmp_path, strokes)
        report = gap_report(n_strokes=20, path=p)
        assert report["n_strokes_analysed"] == 20
        assert report["n_intervals"] == 19
        assert report["regularity_score"] > 0.9
        assert report["label"] == "clockwork"
        assert report["median_gap"] == pytest.approx(15.0, abs=0.1)
        assert report["anomaly_count"] == 0

    def test_report_with_anomaly(self, tmp_path):
        strokes = _ts_series(_BASE, 10, 15.0)
        # Insert a huge gap
        strokes.append(_stroke_at(_iso(_BASE + timedelta(hours=2)), seq=10))
        strokes.extend(_ts_series(_BASE + timedelta(hours=2, seconds=15), 5, 15.0))
        p = _write_strokes(tmp_path, strokes)
        report = gap_report(n_strokes=100, path=p)
        assert report["anomaly_count"] >= 1
        assert report["max_gap"] > 3600

    def test_empty_file(self, tmp_path):
        p = _write_strokes(tmp_path, [])
        report = gap_report(path=p)
        assert report["n_strokes_analysed"] == 0
        assert report["regularity_score"] == 0.0

    def test_missing_file(self, tmp_path):
        report = gap_report(path=tmp_path / "nonexistent.jsonl")
        assert report["n_strokes_analysed"] == 0

    def test_report_keys(self, tmp_path):
        strokes = _ts_series(_BASE, 10, 15.0)
        p = _write_strokes(tmp_path, strokes)
        report = gap_report(n_strokes=10, path=p)
        expected_keys = {
            "n_strokes_analysed", "n_intervals", "regularity_score",
            "label", "median_gap", "mean_gap", "max_gap",
            "anomaly_count", "anomalous_gaps",
        }
        assert set(report.keys()) == expected_keys

    def test_anomalous_gaps_structure(self, tmp_path):
        strokes = _ts_series(_BASE, 5, 15.0)
        strokes.append(_stroke_at(_iso(_BASE + timedelta(hours=1)), seq=5))
        p = _write_strokes(tmp_path, strokes)
        report = gap_report(n_strokes=10, path=p)
        if report["anomalous_gaps"]:
            ag = report["anomalous_gaps"][0]
            assert "index" in ag
            assert "gap_seconds" in ag


# -----------------------------------------------------------------------
# 8. gap_summary
# -----------------------------------------------------------------------


class TestGapSummary:
    def test_normal_summary(self, tmp_path):
        strokes = _ts_series(_BASE, 30, 15.0)
        p = _write_strokes(tmp_path, strokes)
        summary = gap_summary(n_strokes=30, path=p)
        assert "clockwork" in summary or "steady" in summary
        assert "median" in summary
        assert "30 strokes" in summary

    def test_empty_summary(self, tmp_path):
        p = _write_strokes(tmp_path, [])
        summary = gap_summary(path=p)
        assert "no data" in summary

    def test_summary_contains_anomaly_count(self, tmp_path):
        strokes = _ts_series(_BASE, 10, 15.0)
        strokes.append(_stroke_at(_iso(_BASE + timedelta(hours=3)), seq=10))
        p = _write_strokes(tmp_path, strokes)
        summary = gap_summary(n_strokes=20, path=p)
        assert "anomal" in summary


# -----------------------------------------------------------------------
# 9. _cli
# -----------------------------------------------------------------------


class TestCLI:
    def test_text_output(self, tmp_path, capsys):
        strokes = _ts_series(_BASE, 30, 15.0)
        p = _write_strokes(tmp_path, strokes)
        exit_code = _cli(["--n", "30", "--path", str(p)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "gaps:" in captured.out

    def test_json_output(self, tmp_path, capsys):
        strokes = _ts_series(_BASE, 30, 15.0)
        p = _write_strokes(tmp_path, strokes)
        exit_code = _cli(["--n", "30", "--path", str(p), "--json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "regularity_score" in data

    def test_exit_code_erratic(self, tmp_path):
        # Create highly irregular gaps
        strokes = [
            _stroke_at(_iso(_BASE)),
            _stroke_at(_iso(_BASE + timedelta(seconds=15))),
            _stroke_at(_iso(_BASE + timedelta(hours=5))),
            _stroke_at(_iso(_BASE + timedelta(hours=5, seconds=15))),
            _stroke_at(_iso(_BASE + timedelta(hours=10))),
        ]
        p = _write_strokes(tmp_path, strokes)
        exit_code = _cli(["--n", "10", "--path", str(p)])
        assert exit_code == 1

    def test_custom_anomaly_multiplier(self, tmp_path, capsys):
        strokes = _ts_series(_BASE, 20, 15.0)
        p = _write_strokes(tmp_path, strokes)
        exit_code = _cli(["--n", "20", "--path", str(p), "--anomaly-multiplier", "5.0", "--json"])
        assert exit_code == 0
        data = json.loads(capsys.readouterr().out)
        assert data["anomaly_count"] == 0


# -----------------------------------------------------------------------
# 10. Edge cases
# -----------------------------------------------------------------------


class TestEdgeCases:
    def test_two_strokes(self, tmp_path):
        strokes = _ts_series(_BASE, 2, 15.0)
        p = _write_strokes(tmp_path, strokes)
        report = gap_report(n_strokes=2, path=p)
        assert report["n_intervals"] == 1
        # Single gap → CV is 0 → score should be 1.0
        assert report["regularity_score"] == 1.0

    def test_malformed_lines_skipped(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps(_stroke_at(_iso(_BASE), seq=0)),
            "this is not json",
            json.dumps(_stroke_at(_iso(_BASE + timedelta(seconds=15)), seq=1)),
            "",
            json.dumps(_stroke_at(_iso(_BASE + timedelta(seconds=30)), seq=2)),
        ]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        strokes = _load_strokes_with_timestamps(n=10, path=p)
        assert len(strokes) == 3

    def test_strokes_without_at_field(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 0, "kind": "thought", "text": "no timestamp"}),
            json.dumps(_stroke_at(_iso(_BASE), seq=1)),
            json.dumps(_stroke_at(_iso(_BASE + timedelta(seconds=15)), seq=2)),
        ]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        strokes = _load_strokes_with_timestamps(n=10, path=p)
        assert len(strokes) == 2

    def test_all_zero_gaps(self):
        """All strokes at the same time."""
        strokes = [_stroke_at(_iso(_BASE))] * 5
        gaps = compute_gaps(strokes)
        assert all(g == 0.0 for g in gaps)
        # regularity_score handles this: mean=0 → score=0
        assert regularity_score(gaps) == 0.0

    def test_large_dataset(self, tmp_path):
        strokes = _ts_series(_BASE, 1000, 15.0)
        p = _write_strokes(tmp_path, strokes)
        report = gap_report(n_strokes=1000, path=p)
        assert report["n_strokes_analysed"] == 1000
        assert report["regularity_score"] > 0.95
