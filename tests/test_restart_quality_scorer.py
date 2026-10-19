#!/usr/bin/env python3
"""Tests for restart_quality_scorer.py"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from restart_quality_scorer import (
    GAP_BAD,
    GAP_GOOD,
    RestartScore,
    _cadence_spm,
    _score_linear,
    _score_linear_inv,
    detect_restarts,
    format_json,
    format_text,
    load_strokes,
    parse_ts,
    run,
    score_restart,
    worst_exit_code,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stroke(seq: int, ts: datetime, kind: str = "thought", text: str = "") -> dict:
    return {
        "seq": seq,
        "at": ts.isoformat(),
        "kind": kind,
        "text": text or f"stroke {seq}",
    }


def _make_stroke_series(
    start: datetime, count: int, interval_seconds: float = 15.0, start_seq: int = 1
) -> list[dict]:
    """Generate a series of strokes at regular intervals."""
    strokes = []
    for i in range(count):
        ts = start + timedelta(seconds=interval_seconds * i)
        strokes.append(_make_stroke(start_seq + i, ts))
    return strokes


def _make_strokes_with_gap(
    pre_count: int = 20,
    post_count: int = 20,
    gap_seconds: float = 600.0,
    interval: float = 15.0,
) -> list[dict]:
    """Generate pre-gap strokes, a gap, then post-gap strokes."""
    base = datetime(2026, 10, 19, 8, 0, 0, tzinfo=timezone.utc)
    pre = _make_stroke_series(base, pre_count, interval, start_seq=100)
    last_pre_ts = pre[-1]["at"]
    last_pre_dt = datetime.fromisoformat(last_pre_ts)
    post_start = last_pre_dt + timedelta(seconds=gap_seconds)
    post = _make_stroke_series(
        post_start, post_count, interval, start_seq=100 + pre_count
    )
    return pre + post


# ---------------------------------------------------------------------------
# parse_ts
# ---------------------------------------------------------------------------


class TestParseTs:
    def test_valid_iso(self):
        dt = parse_ts("2026-10-19T08:00:00+00:00")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 10

    def test_z_suffix(self):
        dt = parse_ts("2026-10-19T08:00:00Z")
        assert dt is not None

    def test_invalid(self):
        assert parse_ts("not a date") is None

    def test_none(self):
        assert parse_ts(None) is None  # type: ignore

    def test_empty(self):
        assert parse_ts("") is None


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


class TestScoreLinear:
    def test_at_good(self):
        assert _score_linear(100, 200, 400) == 100.0

    def test_at_bad(self):
        assert _score_linear(400, 200, 400) == 0.0

    def test_midpoint(self):
        score = _score_linear(300, 200, 400)
        assert score == pytest.approx(50.0, abs=1)

    def test_below_good(self):
        assert _score_linear(50, 200, 400) == 100.0

    def test_above_bad(self):
        assert _score_linear(500, 200, 400) == 0.0


class TestScoreLinearInv:
    def test_at_good(self):
        assert _score_linear_inv(0.9, 0.3, 0.8) == 100.0

    def test_at_bad(self):
        assert _score_linear_inv(0.3, 0.3, 0.8) == 0.0

    def test_above_good(self):
        assert _score_linear_inv(1.5, 0.3, 0.8) == 100.0

    def test_below_bad(self):
        assert _score_linear_inv(0.1, 0.3, 0.8) == 0.0


# ---------------------------------------------------------------------------
# Cadence calculation
# ---------------------------------------------------------------------------


class TestCadenceSpm:
    def test_normal_series(self):
        base = datetime(2026, 10, 19, 8, 0, 0, tzinfo=timezone.utc)
        strokes = _make_stroke_series(base, 10, interval_seconds=15.0)
        spm = _cadence_spm(strokes)
        # 10 strokes in 135 seconds = 2.25 minutes → 10/2.25 ≈ 4.44 spm
        assert spm == pytest.approx(4.44, abs=0.1)

    def test_single_stroke(self):
        base = datetime(2026, 10, 19, 8, 0, 0, tzinfo=timezone.utc)
        strokes = [_make_stroke(1, base)]
        assert _cadence_spm(strokes) == 0.0

    def test_empty(self):
        assert _cadence_spm([]) == 0.0

    def test_same_timestamp(self):
        base = datetime(2026, 10, 19, 8, 0, 0, tzinfo=timezone.utc)
        strokes = [_make_stroke(1, base), _make_stroke(2, base)]
        assert _cadence_spm(strokes) == 0.0


# ---------------------------------------------------------------------------
# Restart detection
# ---------------------------------------------------------------------------


class TestDetectRestarts:
    def test_no_gap(self):
        base = datetime(2026, 10, 19, 8, 0, 0, tzinfo=timezone.utc)
        strokes = _make_stroke_series(base, 50, interval_seconds=15.0)
        restarts = detect_restarts(strokes, gap_threshold=300)
        assert len(restarts) == 0

    def test_single_gap(self):
        strokes = _make_strokes_with_gap(gap_seconds=600)
        restarts = detect_restarts(strokes, gap_threshold=300)
        assert len(restarts) == 1
        assert restarts[0] == (19, 20)

    def test_multiple_gaps(self):
        base = datetime(2026, 10, 19, 8, 0, 0, tzinfo=timezone.utc)
        seg1 = _make_stroke_series(base, 10, 15.0, start_seq=1)
        seg1_last = datetime.fromisoformat(seg1[-1]["at"])
        seg2_start = seg1_last + timedelta(seconds=600)
        seg2 = _make_stroke_series(seg2_start, 10, 15.0, start_seq=11)
        seg2_last = datetime.fromisoformat(seg2[-1]["at"])
        seg3_start = seg2_last + timedelta(seconds=600)
        seg3 = _make_stroke_series(seg3_start, 10, 15.0, start_seq=21)

        all_strokes = seg1 + seg2 + seg3
        restarts = detect_restarts(all_strokes, gap_threshold=300)
        assert len(restarts) == 2

    def test_gap_below_threshold(self):
        strokes = _make_strokes_with_gap(gap_seconds=200)
        restarts = detect_restarts(strokes, gap_threshold=300)
        assert len(restarts) == 0

    def test_custom_threshold(self):
        strokes = _make_strokes_with_gap(gap_seconds=120)
        restarts_60 = detect_restarts(strokes, gap_threshold=60)
        restarts_300 = detect_restarts(strokes, gap_threshold=300)
        assert len(restarts_60) == 1
        assert len(restarts_300) == 0


# ---------------------------------------------------------------------------
# Score a restart
# ---------------------------------------------------------------------------


class TestScoreRestart:
    def test_perfect_restart(self):
        """Short gap, same cadence → high score."""
        strokes = _make_strokes_with_gap(gap_seconds=60, interval=15.0)
        score = score_restart(strokes, 19, 20, index=0)
        assert score.composite >= 70
        assert score.grade == "good"
        assert score.gap_seconds == pytest.approx(60, abs=1)
        assert score.cadence_ratio == pytest.approx(1.0, abs=0.1)

    def test_degraded_restart(self):
        """Long gap, reduced post-cadence → medium score."""
        pre = _make_stroke_series(
            datetime(2026, 10, 19, 8, 0, 0, tzinfo=timezone.utc),
            20,
            15.0,
            start_seq=100,
        )
        last_pre_ts = datetime.fromisoformat(pre[-1]["at"])
        # 20 minute gap
        post_start = last_pre_ts + timedelta(seconds=1200)
        # Post cadence is slower: 30s intervals instead of 15s
        post = _make_stroke_series(post_start, 10, 30.0, start_seq=120)
        all_strokes = pre + post
        score = score_restart(all_strokes, 19, 20, index=0)
        assert score.grade in ("degraded", "poor")
        assert score.estimated_loss > 0

    def test_poor_restart(self):
        """Very long gap, very slow post-cadence → low score."""
        pre = _make_stroke_series(
            datetime(2026, 10, 19, 8, 0, 0, tzinfo=timezone.utc),
            20,
            15.0,
            start_seq=100,
        )
        last_pre_ts = datetime.fromisoformat(pre[-1]["at"])
        # 2 hour gap
        post_start = last_pre_ts + timedelta(seconds=7200)
        # Very slow post cadence: 120s intervals
        post = _make_stroke_series(post_start, 5, 120.0, start_seq=120)
        all_strokes = pre + post
        score = score_restart(all_strokes, 19, 20, index=0)
        assert score.composite < 40
        assert score.grade == "poor"
        assert score.estimated_loss > 50

    def test_seq_gap_calculation(self):
        strokes = _make_strokes_with_gap(gap_seconds=60)
        score = score_restart(strokes, 19, 20, index=0)
        # seqs 119 → 120, gap = 0
        assert score.seq_gap == 0

    def test_seq_gap_with_missing(self):
        """Simulate lost strokes during restart."""
        pre = _make_stroke_series(
            datetime(2026, 10, 19, 8, 0, 0, tzinfo=timezone.utc),
            20,
            15.0,
            start_seq=100,
        )
        last_pre_ts = datetime.fromisoformat(pre[-1]["at"])
        post_start = last_pre_ts + timedelta(seconds=600)
        # Skip 30 seq numbers (simulating lost strokes)
        post = _make_stroke_series(post_start, 20, 15.0, start_seq=150)
        all_strokes = pre + post
        score = score_restart(all_strokes, 19, 20, index=0)
        assert score.seq_gap == 30  # 150 - 119 - 1

    def test_recovery_latency_estimate(self):
        strokes = _make_strokes_with_gap(gap_seconds=300)
        score = score_restart(strokes, 19, 20, index=0)
        # Recovery latency is gap/2 = 150s
        assert score.recovery_latency == pytest.approx(150.0, abs=1)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


class TestFormatting:
    def test_format_text_no_restarts(self):
        result = format_text([], 0)
        assert "no restarts" in result

    def test_format_text_with_scores(self):
        strokes = _make_strokes_with_gap(gap_seconds=60)
        score = score_restart(strokes, 19, 20, index=0)
        result = format_text([score], 1)
        assert "#0" in result
        assert "good" in result or "degraded" in result or "poor" in result

    def test_format_json_structure(self):
        strokes = _make_strokes_with_gap(gap_seconds=60)
        score = score_restart(strokes, 19, 20, index=0)
        result = format_json([score])
        data = json.loads(result)
        assert "restart_count" in data
        assert data["restart_count"] == 1
        assert len(data["restarts"]) == 1
        r = data["restarts"][0]
        assert "grade" in r
        assert "composite" in r
        assert "gap_seconds" in r
        assert "cadence_ratio" in r

    def test_format_json_multiple(self):
        s1 = RestartScore(
            restart_index=0,
            gap_seconds=60,
            recovery_latency=30,
            cadence_ratio=1.0,
            estimated_loss=2,
            pre_cadence_spm=4.0,
            post_cadence_spm=4.0,
            last_pre_seq=100,
            first_post_seq=101,
            seq_gap=0,
        )
        s2 = RestartScore(
            restart_index=1,
            gap_seconds=900,
            recovery_latency=450,
            cadence_ratio=0.5,
            estimated_loss=30,
            pre_cadence_spm=4.0,
            post_cadence_spm=2.0,
            last_pre_seq=200,
            first_post_seq=231,
            seq_gap=30,
        )
        result = format_json([s1, s2])
        data = json.loads(result)
        assert data["restart_count"] == 2


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


class TestExitCode:
    def test_all_good(self):
        scores = [
            RestartScore(
                restart_index=0,
                gap_seconds=60,
                recovery_latency=30,
                cadence_ratio=1.0,
                estimated_loss=2,
                pre_cadence_spm=4.0,
                post_cadence_spm=4.0,
                last_pre_seq=100,
                first_post_seq=101,
                seq_gap=0,
            )
        ]
        assert worst_exit_code(scores) == 0

    def test_any_degraded(self):
        scores = [
            RestartScore(
                restart_index=0,
                gap_seconds=60,
                recovery_latency=30,
                cadence_ratio=1.0,
                estimated_loss=2,
                pre_cadence_spm=4.0,
                post_cadence_spm=4.0,
                last_pre_seq=100,
                first_post_seq=101,
                seq_gap=0,
            ),
            RestartScore(
                restart_index=1,
                gap_seconds=600,
                recovery_latency=300,
                cadence_ratio=0.6,
                estimated_loss=10,
                pre_cadence_spm=4.0,
                post_cadence_spm=2.4,
                last_pre_seq=200,
                first_post_seq=211,
                seq_gap=10,
            ),
        ]
        assert worst_exit_code(scores) == 1

    def test_any_poor(self):
        scores = [
            RestartScore(
                restart_index=0,
                gap_seconds=7200,
                recovery_latency=3600,
                cadence_ratio=0.1,
                estimated_loss=100,
                pre_cadence_spm=4.0,
                post_cadence_spm=0.4,
                last_pre_seq=100,
                first_post_seq=201,
                seq_gap=100,
            )
        ]
        assert worst_exit_code(scores) == 2

    def test_empty(self):
        assert worst_exit_code([]) == 2


# ---------------------------------------------------------------------------
# RestartScore dataclass
# ---------------------------------------------------------------------------


class TestRestartScore:
    def test_auto_composite(self):
        s = RestartScore(
            restart_index=0,
            gap_seconds=60,
            recovery_latency=30,
            cadence_ratio=1.0,
            estimated_loss=0,
            pre_cadence_spm=4.0,
            post_cadence_spm=4.0,
            last_pre_seq=100,
            first_post_seq=101,
            seq_gap=0,
        )
        assert 0 <= s.composite <= 100
        assert s.grade in ("good", "degraded", "poor")

    def test_cadence_ratio_capped(self):
        """cadence_ratio is capped at 2.0 in score_restart."""
        s = RestartScore(
            restart_index=0,
            gap_seconds=60,
            recovery_latency=30,
            cadence_ratio=5.0,  # would be above cap
            estimated_loss=0,
            pre_cadence_spm=4.0,
            post_cadence_spm=20.0,
            last_pre_seq=100,
            first_post_seq=101,
            seq_gap=0,
        )
        # The dataclass doesn't cap — score_restart does.
        # Just verify the composite is valid.
        assert 0 <= s.composite <= 100

    def test_grade_boundaries(self):
        good = RestartScore(
            restart_index=0,
            gap_seconds=0,
            recovery_latency=0,
            cadence_ratio=1.0,
            estimated_loss=0,
            pre_cadence_spm=4.0,
            post_cadence_spm=4.0,
            last_pre_seq=1,
            first_post_seq=2,
            seq_gap=0,
        )
        assert good.grade == "good"
        assert good.composite >= 70


# ---------------------------------------------------------------------------
# load_strokes
# ---------------------------------------------------------------------------


class TestLoadStrokes:
    def test_missing_file(self):
        strokes = load_strokes(Path("/nonexistent/path.jsonl"))
        assert strokes == []

    def test_valid_file(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"seq":1,"at":"2026-10-19T08:00:00+00:00","kind":"thought","text":"a"}\n'
            '{"seq":2,"at":"2026-10-19T08:00:15+00:00","kind":"thought","text":"b"}\n'
        )
        strokes = load_strokes(f)
        assert len(strokes) == 2
        assert strokes[0]["seq"] == 1

    def test_malformed_lines(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"seq":1,"at":"2026-10-19T08:00:00+00:00","kind":"thought","text":"a"}\n'
            'not valid json\n'
            '{"seq":3,"at":"2026-10-19T08:00:30+00:00","kind":"thought","text":"c"}\n'
            '\n'
        )
        strokes = load_strokes(f)
        assert len(strokes) == 2

    def test_empty_file(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text("")
        strokes = load_strokes(f)
        assert strokes == []


# ---------------------------------------------------------------------------
# Integration: run()
# ---------------------------------------------------------------------------


class TestRun:
    def test_run_with_file(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        strokes = _make_strokes_with_gap(gap_seconds=600)
        with open(f, "w") as fh:
            for s in strokes:
                fh.write(json.dumps(s) + "\n")

        code, output = run(f)
        assert code in (0, 1, 2)
        assert "restart_quality_scorer" in output

    def test_run_json_mode(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        strokes = _make_strokes_with_gap(gap_seconds=600)
        with open(f, "w") as fh:
            for s in strokes:
                fh.write(json.dumps(s) + "\n")

        code, output = run(f, as_json=True)
        data = json.loads(output)
        assert "restart_count" in data
        assert data["restart_count"] >= 1

    def test_run_empty_file(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text("")
        code, output = run(f)
        assert code == 2
        assert "error" in output

    def test_run_no_restarts(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        base = datetime(2026, 10, 19, 8, 0, 0, tzinfo=timezone.utc)
        strokes = _make_stroke_series(base, 50, 15.0)
        with open(f, "w") as fh:
            for s in strokes:
                fh.write(json.dumps(s) + "\n")
        code, output = run(f)
        assert code == 0
        assert "continuous" in output or "no restarts" in output
