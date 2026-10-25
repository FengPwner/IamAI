#!/usr/bin/env python3
"""tests for scripts/recovery_time_analyzer.py — recovery health analyzer."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from recovery_time_analyzer import (
    classify_commit,
    detect_stalls,
    compute_recovery_times,
    score_mean_recovery,
    score_consistency,
    score_stall_frequency,
    score_post_recovery_cadence,
    compute_recovery_score,
    format_bar,
    format_report,
    parse_timestamp,
)
from datetime import datetime, timezone, timedelta


# ── timestamp parsing ────────────────────────────────────────────────


class TestParseTimestamp:
    def test_standard_format(self):
        ts = parse_timestamp("2026-10-24 14:00:00 +0800")
        assert ts is not None
        assert ts.year == 2026
        assert ts.month == 10
        assert ts.day == 24

    def test_without_timezone(self):
        ts = parse_timestamp("2026-10-24 14:00:00")
        assert ts is not None
        assert ts.hour == 14

    def test_invalid_format(self):
        ts = parse_timestamp("not a date")
        assert ts is None

    def test_empty_string(self):
        ts = parse_timestamp("")
        assert ts is None


# ── commit classification ───────────────────────────────────────────


class TestClassifyCommit:
    def test_stroke_commit(self):
        assert classify_commit("writer stroke (auto-sync)") == "stroke"

    def test_caretaker_visit(self):
        assert classify_commit("caretaker visit 339: add feature") == "caretaker"

    def test_recovery_commit(self):
        assert classify_commit("catch-up: commit pending changes") == "recovery"

    def test_restart_commit(self):
        assert classify_commit("process restart after stall") == "recovery"

    def test_other_commit(self):
        assert classify_commit("update documentation") == "other"

    def test_case_insensitive(self):
        assert classify_commit("CARETAKER VISIT 100") == "caretaker"

    def test_writer_sync(self):
        assert classify_commit("writer sync before push") == "stroke"


# ── stall detection ──────────────────────────────────────────────────


def _make_commit(sha: str, minutes_offset: int, msg: str = "commit") -> dict:
    """helper to create a commit dict with a specific timestamp offset."""
    base = datetime(2026, 10, 24, 12, 0, 0, tzinfo=timezone.utc)
    ts = base + timedelta(minutes=minutes_offset)
    return {"sha": sha, "timestamp": ts, "message": msg}


class TestDetectStalls:
    def test_no_stalls(self):
        commits = [
            _make_commit("aaa", 0),
            _make_commit("bbb", 1),
            _make_commit("ccc", 2),
        ]
        stalls = detect_stalls(commits, threshold_seconds=300)
        assert len(stalls) == 0

    def test_single_stall(self):
        commits = [
            _make_commit("aaa", 0),
            _make_commit("bbb", 1),
            _make_commit("ccc", 20),  # 19-minute gap = stall
        ]
        stalls = detect_stalls(commits, threshold_seconds=300)
        assert len(stalls) == 1
        assert stalls[0]["before_sha"] == "bbb"
        assert stalls[0]["after_sha"] == "ccc"
        assert stalls[0]["gap_seconds"] == 19 * 60

    def test_multiple_stalls(self):
        commits = [
            _make_commit("aaa", 0),
            _make_commit("bbb", 10),   # 10-min gap
            _make_commit("ccc", 11),
            _make_commit("ddd", 25),   # 14-min gap
        ]
        stalls = detect_stalls(commits, threshold_seconds=300)
        assert len(stalls) == 2

    def test_empty_commits(self):
        stalls = detect_stalls([], threshold_seconds=300)
        assert len(stalls) == 0

    def test_single_commit(self):
        commits = [_make_commit("aaa", 0)]
        stalls = detect_stalls(commits, threshold_seconds=300)
        assert len(stalls) == 0

    def test_exact_threshold(self):
        commits = [
            _make_commit("aaa", 0),
            _make_commit("bbb", 5),  # exactly 300s
        ]
        stalls = detect_stalls(commits, threshold_seconds=300)
        assert len(stalls) == 0  # not greater than threshold

    def test_stall_records_context(self):
        commits = [
            _make_commit("aaa", 0, "writer stroke"),
            _make_commit("bbb", 15, "caretaker visit 340"),
        ]
        stalls = detect_stalls(commits, threshold_seconds=300)
        assert len(stalls) == 1
        assert stalls[0]["before_kind"] == "stroke"
        assert stalls[0]["after_kind"] == "caretaker"
        assert stalls[0]["before_msg"] == "writer stroke"


# ── recovery times ───────────────────────────────────────────────────


class TestComputeRecoveryTimes:
    def test_extracts_gaps(self):
        stalls = [
            {"gap_seconds": 600},
            {"gap_seconds": 900},
            {"gap_seconds": 300},
        ]
        times = compute_recovery_times(stalls)
        assert times == [600, 900, 300]

    def test_empty_stalls(self):
        times = compute_recovery_times([])
        assert times == []


# ── mean recovery score ──────────────────────────────────────────────


class TestScoreMeanRecovery:
    def test_no_recovery_times(self):
        assert score_mean_recovery([]) == 0

    def test_instant_recovery(self):
        assert score_mean_recovery([10, 20, 30]) == 0 or score_mean_recovery([10, 20, 30]) <= 5

    def test_fast_recovery(self):
        score = score_mean_recovery([60, 60, 60])
        assert 0 <= score <= 8

    def test_moderate_recovery(self):
        score = score_mean_recovery([300, 400, 350])
        assert 8 <= score <= 18

    def test_slow_recovery(self):
        score = score_mean_recovery([1200, 1500, 1800])
        assert score >= 18

    def test_score_bounded(self):
        score = score_mean_recovery([99999])
        assert score <= 25


# ── consistency score ────────────────────────────────────────────────


class TestScoreConsistency:
    def test_single_value(self):
        assert score_consistency([100]) == 0

    def test_empty(self):
        assert score_consistency([]) == 0

    def test_consistent(self):
        score = score_consistency([100, 100, 100, 100])
        assert score == 0

    def test_low_variance(self):
        score = score_consistency([100, 110, 105, 95])
        assert score <= 5

    def test_high_variance(self):
        score = score_consistency([100, 500, 50, 800])
        assert score >= 10

    def test_score_bounded(self):
        score = score_consistency([10, 9999, 5, 8888])
        assert score <= 25


# ── stall frequency score ────────────────────────────────────────────


class TestScoreStallFrequency:
    def test_no_stalls(self):
        assert score_stall_frequency([], 100) == 0

    def test_rare_stalls(self):
        stalls = [{"gap_seconds": 600}]
        score = score_stall_frequency(stalls, 500)
        assert score <= 5

    def test_frequent_stalls(self):
        stalls = [{"gap_seconds": 600} for _ in range(20)]
        score = score_stall_frequency(stalls, 100)
        assert score >= 15

    def test_zero_commits(self):
        assert score_stall_frequency([], 0) == 0

    def test_score_bounded(self):
        stalls = [{"gap_seconds": 600} for _ in range(100)]
        score = score_stall_frequency(stalls, 10)
        assert score <= 25


# ── post-recovery cadence score ──────────────────────────────────────


class TestScorePostRecoveryCadence:
    def test_no_stalls(self):
        assert score_post_recovery_cadence([], []) == 0

    def test_few_commits(self):
        commits = [_make_commit("aaa", 0)]
        stalls = [{"after_sha": "aaa", "gap_seconds": 600}]
        assert score_post_recovery_cadence(commits, stalls) == 0

    def test_healthy_recovery(self):
        # commits with consistent cadence before and after
        commits = [
            _make_commit("a1", 0),
            _make_commit("a2", 1),
            _make_commit("a3", 2),
            _make_commit("a4", 3),
            _make_commit("a5", 4),
            _make_commit("a6", 5),
            _make_commit("stall_start", 6),
            _make_commit("recovery", 20),  # stall
            _make_commit("r1", 21),
            _make_commit("r2", 22),
            _make_commit("r3", 23),
            _make_commit("r4", 24),
            _make_commit("r5", 25),
        ]
        stalls = [{
            "after_sha": "recovery",
            "gap_seconds": 14 * 60,
            "before_sha": "stall_start",
        }]
        score = score_post_recovery_cadence(commits, stalls)
        assert score <= 10  # should recover at same cadence


# ── full score computation ───────────────────────────────────────────


class TestComputeRecoveryScore:
    def test_no_git_repo(self, tmp_path):
        result = compute_recovery_score(str(tmp_path))
        assert "error" in result or result["grade"] == "BRITTLE"

    def test_result_structure(self, tmp_path):
        # create a minimal git repo with multiple commits
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
            capture_output=True,
        )
        for i in range(5):
            subprocess.run(
                ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", f"commit {i}"],
                capture_output=True,
            )
        result = compute_recovery_score(str(tmp_path))
        assert "total_score" in result
        assert "grade" in result
        assert "metrics" in result
        assert result["grade"] in ("RESILIENT", "ROBUST", "FRAGILE", "BRITTLE")


# ── formatting ───────────────────────────────────────────────────────


class TestFormatBar:
    def test_zero_value(self):
        bar = format_bar(0, 25, 20)
        assert "░" * 20 in bar
        assert "0/25" in bar

    def test_max_value(self):
        bar = format_bar(25, 25, 20)
        assert "█" * 20 in bar
        assert "25/25" in bar

    def test_half_value(self):
        bar = format_bar(12, 25, 20)
        assert "█" in bar
        assert "░" in bar
        assert "12/25" in bar


class TestFormatReport:
    def test_error_report(self):
        result = {"error": "no commits found"}
        report = format_report(result)
        assert "ERROR" in report

    def test_full_report(self):
        result = {
            "total_score": 15,
            "grade": "RESILIENT",
            "metrics": {
                "mean_recovery_time": 3,
                "recovery_consistency": 4,
                "stall_frequency": 5,
                "post_recovery_cadence": 3,
            },
            "stall_count": 2,
            "total_commits": 100,
            "mean_recovery_seconds": 45.0,
            "stalls": [
                {
                    "gap_seconds": 600,
                    "before_sha": "abc12345",
                    "after_sha": "def67890",
                    "before_kind": "stroke",
                    "after_kind": "recovery",
                }
            ],
        }
        report = format_report(result)
        assert "RESILIENT" in report
        assert "15/100" in report
        assert "stall" in report.lower()
