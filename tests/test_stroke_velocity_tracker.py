#!/usr/bin/env python3
"""tests for scripts/stroke_velocity_tracker.py — stroke velocity tracker."""

import sys
import os
import json
import math
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from stroke_velocity_tracker import (
    load_strokes,
    filter_since,
    compute_recent_rate,
    score_recent_rate,
    compute_rate_trend,
    score_rate_trend,
    compute_inter_stroke_gaps,
    compute_gap_cv,
    score_cadence_regularity,
    compute_kind_distribution,
    compute_kind_balance_ratio,
    score_kind_balance,
    compute_all_scores,
    classify,
    exit_code_for,
    format_bar,
    format_report,
    TARGET_RATE_PER_HOUR,
    STROKE_KINDS,
)
from datetime import datetime, timezone, timedelta
from collections import Counter


# ── helpers ──────────────────────────────────────────────────────────

def _make_stroke(seq: int, ts: datetime, kind: str = "thought",
                 text: str = "test stroke") -> dict:
    return {"seq": seq, "at": ts.isoformat(), "kind": kind, "text": text,
            "_ts": ts}


def _write_strokes_file(strokes: list, tmpdir: str) -> str:
    """write strokes to a temp jsonl file and return the path."""
    data_dir = os.path.join(tmpdir, "data")
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "strokes.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for s in strokes:
            # exclude _ts (datetime) from serialization
            record = {k: v for k, v in s.items() if k != "_ts"}
            f.write(json.dumps(record) + "\n")
    return path


# ── load_strokes ─────────────────────────────────────────────────────


class TestLoadStrokes:
    def test_load_valid_file(self, tmp_path):
        now = datetime.now(timezone.utc)
        strokes = [
            _make_stroke(1, now - timedelta(hours=2), "thought"),
            _make_stroke(2, now - timedelta(hours=1), "garden"),
        ]
        path = _write_strokes_file(strokes, str(tmp_path))
        loaded = load_strokes(path)
        assert len(loaded) == 2
        assert loaded[0]["seq"] == 1
        assert loaded[1]["kind"] == "garden"

    def test_load_empty_file(self, tmp_path):
        path = os.path.join(str(tmp_path), "data", "strokes.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("")
        loaded = load_strokes(path)
        assert len(loaded) == 0

    def test_load_nonexistent(self, tmp_path):
        loaded = load_strokes(os.path.join(str(tmp_path), "nope.jsonl"))
        assert len(loaded) == 0

    def test_load_skips_malformed_lines(self, tmp_path):
        path = os.path.join(str(tmp_path), "data", "strokes.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        now = datetime.now(timezone.utc)
        with open(path, "w") as f:
            r1 = {k: v for k, v in _make_stroke(1, now, "thought").items() if k != "_ts"}
            f.write(json.dumps(r1) + "\n")
            f.write("this is not json\n")
            r2 = {k: v for k, v in _make_stroke(2, now, "garden").items() if k != "_ts"}
            f.write(json.dumps(r2) + "\n")
        loaded = load_strokes(path)
        assert len(loaded) == 2

    def test_sorted_by_timestamp(self, tmp_path):
        now = datetime.now(timezone.utc)
        strokes = [
            _make_stroke(2, now, "garden"),
            _make_stroke(1, now - timedelta(hours=1), "thought"),
        ]
        path = _write_strokes_file(strokes, str(tmp_path))
        loaded = load_strokes(path)
        assert loaded[0]["seq"] == 1
        assert loaded[1]["seq"] == 2


# ── filter_since ─────────────────────────────────────────────────────


class TestFilterSince:
    def test_filters_correctly(self):
        now = datetime.now(timezone.utc)
        strokes = [
            _make_stroke(1, now - timedelta(hours=5)),
            _make_stroke(2, now - timedelta(hours=3)),
            _make_stroke(3, now - timedelta(hours=1)),
        ]
        cutoff = now - timedelta(hours=4)
        result = filter_since(strokes, cutoff)
        assert len(result) == 2
        assert result[0]["seq"] == 2

    def test_empty_input(self):
        now = datetime.now(timezone.utc)
        result = filter_since([], now)
        assert len(result) == 0

    def test_all_before_cutoff(self):
        now = datetime.now(timezone.utc)
        strokes = [_make_stroke(1, now - timedelta(hours=10))]
        result = filter_since(strokes, now - timedelta(hours=5))
        assert len(result) == 0


# ── recent stroke rate ───────────────────────────────────────────────


class TestComputeRecentRate:
    def test_normal_rate(self):
        now = datetime.now(timezone.utc)
        # 240 strokes/hour * 6 hours = 1440 strokes
        strokes = [
            _make_stroke(i, now - timedelta(seconds=i * 15), "thought")
            for i in range(1440)
        ]
        rate = compute_recent_rate(strokes, now, window_hours=6.0)
        assert 230 <= rate <= 250  # approximately 240

    def test_no_strokes(self):
        now = datetime.now(timezone.utc)
        rate = compute_recent_rate([], now)
        assert rate == 0.0

    def test_short_window(self):
        now = datetime.now(timezone.utc)
        strokes = [
            _make_stroke(i, now - timedelta(minutes=i), "thought")
            for i in range(60)
        ]
        rate = compute_recent_rate(strokes, now, window_hours=1.0)
        assert 55 <= rate <= 65  # ~60/hour


class TestScoreRecentRate:
    def test_perfect_rate(self):
        assert score_recent_rate(240.0) == 25

    def test_good_rate(self):
        assert score_recent_rate(180.0) == 20  # 75% of target

    def test_half_rate(self):
        assert score_recent_rate(120.0) == 15  # 50% of target

    def test_low_rate(self):
        assert score_recent_rate(50.0) == 5  # 50/240 ≈ 0.21

    def test_very_low_rate(self):
        assert score_recent_rate(20.0) == 0  # 20/240 ≈ 0.08

    def test_zero_rate(self):
        assert score_recent_rate(0.0) == 0

    def test_zero_target(self):
        assert score_recent_rate(100.0, target=0) == 0


# ── rate trend ───────────────────────────────────────────────────────


class TestComputeRateTrend:
    def test_steady_rate(self):
        now = datetime.now(timezone.utc)
        # uniform strokes every 15s for 24 hours
        strokes = [
            _make_stroke(i, now - timedelta(seconds=i * 15), "thought")
            for i in range(5760)  # 24h * 240/h
        ]
        trend = compute_rate_trend(strokes, now, recent_hours=6, baseline_hours=18)
        assert 0.9 <= trend <= 1.1

    def test_accelerating(self):
        now = datetime.now(timezone.utc)
        strokes = []
        # baseline period: sparse strokes (1 per minute for 18h = 1080)
        for i in range(1080):
            strokes.append(_make_stroke(
                i, now - timedelta(hours=6) - timedelta(minutes=i), "thought"
            ))
        # recent period: dense strokes (4 per minute for 6h = 1440)
        for i in range(1440):
            strokes.append(_make_stroke(
                1080 + i, now - timedelta(seconds=i * 15), "thought"
            ))
        strokes.sort(key=lambda s: s["_ts"])
        trend = compute_rate_trend(strokes, now, recent_hours=6, baseline_hours=18)
        assert trend > 1.5  # clearly accelerating

    def test_decelerating(self):
        now = datetime.now(timezone.utc)
        strokes = []
        # baseline: dense (4/min for 18h = 4320)
        for i in range(4320):
            strokes.append(_make_stroke(
                i, now - timedelta(hours=6) - timedelta(seconds=i * 15), "thought"
            ))
        # recent: sparse (1/min for 6h = 360)
        for i in range(360):
            strokes.append(_make_stroke(
                4320 + i, now - timedelta(minutes=i), "thought"
            ))
        strokes.sort(key=lambda s: s["_ts"])
        trend = compute_rate_trend(strokes, now, recent_hours=6, baseline_hours=18)
        assert trend < 0.5  # clearly decelerating

    def test_no_baseline(self):
        now = datetime.now(timezone.utc)
        # only recent strokes, nothing in baseline
        strokes = [
            _make_stroke(i, now - timedelta(hours=1), "thought")
            for i in range(10)
        ]
        trend = compute_rate_trend(strokes, now)
        assert trend == 1.0  # neutral when no baseline

    def test_empty_strokes(self):
        now = datetime.now(timezone.utc)
        trend = compute_rate_trend([], now)
        assert trend == 0.0  # no data = stalled, not neutral


class TestScoreRateTrend:
    def test_steady(self):
        assert score_rate_trend(1.0) == 25

    def test_mild_drift_low(self):
        assert score_rate_trend(0.7) == 20

    def test_mild_drift_high(self):
        assert score_rate_trend(1.3) == 20

    def test_moderate_low(self):
        assert score_rate_trend(0.5) == 12

    def test_moderate_high(self):
        assert score_rate_trend(1.8) == 12

    def test_decelerating(self):
        assert score_rate_trend(0.3) == 5

    def test_extreme(self):
        assert score_rate_trend(0.05) == 0


# ── cadence regularity ───────────────────────────────────────────────


class TestComputeInterStrokeGaps:
    def test_uniform_gaps(self):
        now = datetime.now(timezone.utc)
        strokes = [
            _make_stroke(i, now + timedelta(seconds=i * 15), "thought")
            for i in range(10)
        ]
        gaps = compute_inter_stroke_gaps(strokes)
        assert len(gaps) == 9
        assert all(abs(g - 15.0) < 0.01 for g in gaps)

    def test_single_stroke(self):
        strokes = [_make_stroke(1, datetime.now(timezone.utc), "thought")]
        gaps = compute_inter_stroke_gaps(strokes)
        assert len(gaps) == 0

    def test_empty(self):
        gaps = compute_inter_stroke_gaps([])
        assert len(gaps) == 0


class TestComputeGapCV:
    def test_perfectly_regular(self):
        gaps = [15.0] * 100
        cv = compute_gap_cv(gaps)
        assert cv < 0.01

    def test_moderate_variation(self):
        # mix of 10s and 20s gaps, mean=15, std~5
        gaps = [10.0, 20.0] * 50
        cv = compute_gap_cv(gaps)
        assert 0.3 < cv < 0.5

    def test_high_variation(self):
        # very irregular: three short gaps and one huge gap → CV > 1
        gaps = [1.0, 1.0, 1.0, 1000.0] * 25
        cv = compute_gap_cv(gaps)
        assert cv > 1.0

    def test_empty(self):
        assert compute_gap_cv([]) == float("inf")

    def test_zero_mean(self):
        assert compute_gap_cv([0.0, 0.0, 0.0]) == float("inf")


class TestScoreCadenceRegularity:
    def test_excellent(self):
        assert score_cadence_regularity(0.2) == 25

    def test_good(self):
        assert score_cadence_regularity(0.4) == 20

    def test_moderate(self):
        assert score_cadence_regularity(0.8) == 15

    def test_poor(self):
        assert score_cadence_regularity(1.2) == 10

    def test_very_poor(self):
        assert score_cadence_regularity(1.8) == 5

    def test_extreme(self):
        assert score_cadence_regularity(3.0) == 0


# ── kind balance ─────────────────────────────────────────────────────


class TestComputeKindDistribution:
    def test_counts_kinds(self):
        strokes = [
            _make_stroke(1, datetime.now(timezone.utc), "thought"),
            _make_stroke(2, datetime.now(timezone.utc), "thought"),
            _make_stroke(3, datetime.now(timezone.utc), "garden"),
        ]
        dist = compute_kind_distribution(strokes)
        assert dist["thought"] == 2
        assert dist["garden"] == 1
        assert dist.get("metrics", 0) == 0


class TestComputeKindBalanceRatio:
    def test_perfectly_balanced(self):
        dist = Counter({k: 100 for k in STROKE_KINDS})
        ratio = compute_kind_balance_ratio(dist)
        assert ratio == 1.0

    def test_imbalanced(self):
        dist = Counter({"thought": 100, "garden": 10, "metrics": 10,
                        "note": 10, "snippet": 10, "devlog": 10})
        ratio = compute_kind_balance_ratio(dist)
        assert abs(ratio - 0.1) < 0.01

    def test_empty(self):
        dist = Counter()
        ratio = compute_kind_balance_ratio(dist)
        assert ratio == 0.0

    def test_one_kind_only(self):
        dist = Counter({"thought": 500})
        ratio = compute_kind_balance_ratio(dist)
        assert ratio == 0.0  # all other kinds have 0


class TestScoreKindBalance:
    def test_perfect(self):
        assert score_kind_balance(0.95) == 25

    def test_good(self):
        assert score_kind_balance(0.8) == 20

    def test_moderate(self):
        assert score_kind_balance(0.6) == 15

    def test_poor(self):
        assert score_kind_balance(0.4) == 10

    def test_very_poor(self):
        assert score_kind_balance(0.15) == 5

    def test_zero(self):
        assert score_kind_balance(0.0) == 0


# ── classify & exit codes ────────────────────────────────────────────


class TestClassify:
    def test_cruising(self):
        assert classify(80) == "CRUISING"
        assert classify(71) == "CRUISING"

    def test_steady(self):
        assert classify(50) == "STEADY"
        assert classify(46) == "STEADY"

    def test_sputtering(self):
        assert classify(30) == "SPUTTERING"
        assert classify(21) == "SPUTTERING"

    def test_stalled(self):
        assert classify(10) == "STALLED"
        assert classify(0) == "STALLED"


class TestExitCodeFor:
    def test_cruising(self):
        assert exit_code_for("CRUISING") == 0

    def test_steady(self):
        assert exit_code_for("STEADY") == 0

    def test_sputtering(self):
        assert exit_code_for("SPUTTERING") == 1

    def test_stalled(self):
        assert exit_code_for("STALLED") == 2

    def test_unknown(self):
        assert exit_code_for("UNKNOWN") == 1


# ── formatting ───────────────────────────────────────────────────────


class TestFormatBar:
    def test_full_bar(self):
        bar = format_bar(25, 25, 20)
        assert bar == "█" * 20

    def test_empty_bar(self):
        bar = format_bar(0, 25, 20)
        assert bar == "░" * 20

    def test_half_bar(self):
        bar = format_bar(12, 25, 20)
        assert len(bar) == 20
        assert "█" in bar
        assert "░" in bar

    def test_zero_max(self):
        bar = format_bar(5, 0, 20)
        assert bar == "░" * 20


class TestFormatReport:
    def test_contains_grade(self):
        result = {
            "grade": "CRUISING", "total_score": 85,
            "strokes_analyzed_24h": 5000,
            "timestamp": "2026-10-24T12:00:00+00:00",
            "recent_rate_per_hour": 230.0,
            "recent_rate_score": 25,
            "rate_trend": 1.02,
            "rate_trend_score": 25,
            "cadence_cv": 0.25,
            "cadence_score": 25,
            "kind_balance_ratio": 0.95,
            "kind_balance_score": 25,
            "kind_counts": {k: 800 for k in STROKE_KINDS},
        }
        report = format_report(result)
        assert "CRUISING" in report
        assert "85" in report
        assert "5000" in report

    def test_contains_all_kinds(self):
        result = {
            "grade": "STEADY", "total_score": 50,
            "strokes_analyzed_24h": 100,
            "timestamp": "2026-10-24T12:00:00+00:00",
            "recent_rate_per_hour": 10.0,
            "recent_rate_score": 10,
            "rate_trend": 0.8,
            "rate_trend_score": 20,
            "cadence_cv": 0.5,
            "cadence_score": 20,
            "kind_balance_ratio": 0.0,
            "kind_balance_score": 0,
            "kind_counts": {"thought": 100},
        }
        report = format_report(result)
        for kind in STROKE_KINDS:
            assert kind in report


# ── compute_all_scores integration ───────────────────────────────────


class TestComputeAllScores:
    def test_healthy_system(self):
        """simulate a healthy writer producing strokes every 15s."""
        now = datetime.now(timezone.utc)
        strokes = [
            _make_stroke(
                i,
                now - timedelta(seconds=i * 15),
                kind=list(STROKE_KINDS)[i % 6],
            )
            for i in range(5760)  # 24h at 240/hr
        ]
        result = compute_all_scores(strokes, now)
        assert result["total_score"] >= 46  # at least STEADY
        assert result["grade"] in ("CRUISING", "STEADY")
        assert result["strokes_analyzed_24h"] == 5760
        assert result["recent_rate_per_hour"] > 200

    def test_stalled_system(self):
        """simulate a stalled writer with very few strokes."""
        now = datetime.now(timezone.utc)
        strokes = [
            _make_stroke(i, now - timedelta(hours=20), "thought")
            for i in range(5)
        ]
        result = compute_all_scores(strokes, now)
        assert result["total_score"] <= 25
        assert result["grade"] in ("STALLED", "SPUTTERING")

    def test_empty_strokes(self):
        """no strokes at all."""
        now = datetime.now(timezone.utc)
        result = compute_all_scores([], now)
        assert result["total_score"] <= 10
        assert result["grade"] == "STALLED"

    def test_result_has_all_keys(self):
        now = datetime.now(timezone.utc)
        strokes = [_make_stroke(1, now, "thought")]
        result = compute_all_scores(strokes, now)
        expected_keys = {
            "recent_rate_per_hour", "recent_rate_score",
            "rate_trend", "rate_trend_score",
            "cadence_cv", "cadence_score",
            "kind_balance_ratio", "kind_balance_score",
            "kind_counts", "total_score", "grade",
            "strokes_analyzed_24h", "timestamp",
        }
        assert expected_keys == set(result.keys())

    def test_imbalanced_kinds(self):
        """all strokes are one kind — balance score should be low."""
        now = datetime.now(timezone.utc)
        strokes = [
            _make_stroke(i, now - timedelta(seconds=i * 15), "thought")
            for i in range(1440)  # 6h of output, all thought
        ]
        result = compute_all_scores(strokes, now)
        assert result["kind_balance_score"] <= 5
        assert result["kind_balance_ratio"] < 0.1
