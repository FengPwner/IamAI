"""Tests for restart_latency — measure recovery time after process restarts."""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.restart_latency import (
    classify_latency,
    latency_report,
    latency_summary,
    pair_restart_recovery,
    parse_git_log_line,
    parse_restart_events,
    _is_restart_commit,
    _is_catchup_commit,
    _parse_timestamp,
)


# ---------------------------------------------------------------------------
# classify_latency — band mapping
# ---------------------------------------------------------------------------


class TestClassifyLatency:
    def test_zero_is_healthy(self):
        assert classify_latency(0) == "healthy"

    def test_below_300_is_healthy(self):
        assert classify_latency(299) == "healthy"

    def test_300_is_degraded(self):
        assert classify_latency(300) == "degraded"

    def test_mid_degraded(self):
        assert classify_latency(600) == "degraded"

    def test_899_is_degraded(self):
        assert classify_latency(899) == "degraded"

    def test_900_is_slow(self):
        assert classify_latency(900) == "slow"

    def test_mid_slow(self):
        assert classify_latency(1200) == "slow"

    def test_1799_is_slow(self):
        assert classify_latency(1799) == "slow"

    def test_1800_is_critical(self):
        assert classify_latency(1800) == "critical"

    def test_3599_is_critical(self):
        assert classify_latency(3599) == "critical"

    def test_3600_is_broken(self):
        assert classify_latency(3600) == "broken"

    def test_very_large_is_broken(self):
        assert classify_latency(99999) == "broken"


# ---------------------------------------------------------------------------
# parse_git_log_line
# ---------------------------------------------------------------------------


class TestParseGitLogLine:
    def test_basic_line(self):
        line = "abc1234 2026-10-27 12:00:00 +0800 feat: add something cool"
        result = parse_git_log_line(line)
        assert result is not None
        assert result["hash"] == "abc1234"
        assert result["message"] == "feat: add something cool"

    def test_line_with_timezone(self):
        line = "def5678 2026-10-27 10:30:00 +0000 caretaker visit 400"
        result = parse_git_log_line(line)
        assert result is not None
        assert result["hash"] == "def5678"
        assert "+0000" in result["timestamp"]

    def test_negative_timezone(self):
        line = "aaa1111 2026-10-26 08:00:00 -0500 fix: broken thing"
        result = parse_git_log_line(line)
        assert result is not None
        assert "-0500" in result["timestamp"]

    def test_empty_line(self):
        assert parse_git_log_line("") is None

    def test_garbage_line(self):
        assert parse_git_log_line("not a git log line") is None

    def test_short_hash(self):
        line = "abcdef1 2026-10-27 12:00:00 +0800 short hash commit"
        result = parse_git_log_line(line)
        assert result is not None
        assert result["hash"] == "abcdef1"

    def test_long_hash(self):
        line = "abcdef1234567890 2026-10-27 12:00:00 +0800 full hash commit"
        result = parse_git_log_line(line)
        assert result is not None
        assert result["hash"] == "abcdef1234567890"


# ---------------------------------------------------------------------------
# _is_restart_commit / _is_catchup_commit
# ---------------------------------------------------------------------------


class TestCommitClassification:
    def test_restart_detected(self):
        assert _is_restart_commit("writer pid 48266: up after restart")

    def test_process_restart_detected(self):
        assert _is_restart_commit("process restart completed")

    def test_caretaker_restart(self):
        assert _is_restart_commit("caretaker visit 402 — process restart")

    def test_normal_commit_not_restart(self):
        assert not _is_restart_commit("feat: add cool feature")

    def test_catchup_detected(self):
        assert _is_catchup_commit("catch-up: hourly monitor auto-commit")

    def test_auto_commit_detected(self):
        assert _is_catchup_commit("auto-commit from monitor")

    def test_pending_detected(self):
        assert _is_catchup_commit("commit pending changes before restart")

    def test_feature_not_catchup(self):
        assert not _is_catchup_commit("feat: add restart_latency module")


# ---------------------------------------------------------------------------
# parse_restart_events
# ---------------------------------------------------------------------------


class TestParseRestartEvents:
    def test_finds_restart(self):
        lines = [
            "aaa1111 2026-10-27 12:00:00 +0800 feat: normal commit",
            "bbb2222 2026-10-27 11:50:00 +0800 caretaker visit — process restart",
            "ccc3333 2026-10-27 11:40:00 +0800 feat: another feature",
        ]
        events = parse_restart_events(lines)
        assert len(events) == 1
        assert events[0]["hash"] == "bbb2222"

    def test_multiple_restarts(self):
        lines = [
            "aaa1111 2026-10-27 12:00:00 +0800 process restart round 2",
            "bbb2222 2026-10-27 11:00:00 +0800 feat: something",
            "ccc3333 2026-10-27 10:00:00 +0800 process restart round 1",
        ]
        events = parse_restart_events(lines)
        assert len(events) == 2

    def test_no_restarts(self):
        lines = [
            "aaa1111 2026-10-27 12:00:00 +0800 feat: feature a",
            "bbb2222 2026-10-27 11:00:00 +0800 feat: feature b",
        ]
        events = parse_restart_events(lines)
        assert len(events) == 0

    def test_empty_input(self):
        assert parse_restart_events([]) == []

    def test_ignores_garbage(self):
        lines = [
            "not a valid line",
            "aaa1111 2026-10-27 12:00:00 +0800 process restart here",
        ]
        events = parse_restart_events(lines)
        assert len(events) == 1


# ---------------------------------------------------------------------------
# pair_restart_recovery
# ---------------------------------------------------------------------------


class TestPairRestartRecovery:
    def test_basic_pairing(self):
        # git log is newest-first
        lines = [
            "aaa1111 2026-10-27 12:10:00 +0800 feat: add new feature",
            "bbb2222 2026-10-27 12:00:00 +0800 process restart after crash",
            "ccc3333 2026-10-27 11:50:00 +0800 feat: old feature",
        ]
        pairs = pair_restart_recovery(lines)
        assert len(pairs) == 1
        assert pairs[0]["restart_hash"] == "bbb2222"
        assert pairs[0]["recovery_hash"] == "aaa1111"
        assert pairs[0]["latency_seconds"] == 600.0
        assert pairs[0]["band"] == "degraded"

    def test_skips_catchup_after_restart(self):
        lines = [
            "aaa1111 2026-10-27 12:15:00 +0800 feat: real feature",
            "bbb2222 2026-10-27 12:05:00 +0800 catch-up: auto-commit",
            "ccc3333 2026-10-27 12:00:00 +0800 process restart",
            "ddd4444 2026-10-27 11:50:00 +0800 feat: earlier work",
        ]
        pairs = pair_restart_recovery(lines)
        assert len(pairs) == 1
        # should skip catch-up and pair with the real feature
        assert pairs[0]["recovery_hash"] == "aaa1111"
        assert pairs[0]["latency_seconds"] == 900.0
        assert pairs[0]["band"] == "slow"

    def test_no_recovery_found(self):
        # restart is newest — no commit after it
        lines = [
            "aaa1111 2026-10-27 12:00:00 +0800 process restart",
            "bbb2222 2026-10-27 11:00:00 +0800 feat: old work",
        ]
        pairs = pair_restart_recovery(lines)
        assert len(pairs) == 0

    def test_multiple_restarts_paired(self):
        lines = [
            "aaa1111 2026-10-27 14:00:00 +0800 feat: feature c",
            "bbb2222 2026-10-27 13:00:00 +0800 process restart second",
            "ccc3333 2026-10-27 12:05:00 +0800 feat: feature b",
            "ddd4444 2026-10-27 12:00:00 +0800 process restart first",
            "eee5555 2026-10-27 11:00:00 +0800 feat: feature a",
        ]
        pairs = pair_restart_recovery(lines)
        assert len(pairs) == 2
        # second restart → feature c (3600s = broken)
        assert pairs[0]["restart_hash"] == "bbb2222"
        assert pairs[0]["latency_seconds"] == 3600.0
        assert pairs[0]["band"] == "broken"
        # first restart → feature b (300s = degraded)
        assert pairs[1]["restart_hash"] == "ddd4444"
        assert pairs[1]["latency_seconds"] == 300.0
        assert pairs[1]["band"] == "degraded"

    def test_empty_input(self):
        assert pair_restart_recovery([]) == []

    def test_healthy_recovery(self):
        lines = [
            "aaa1111 2026-10-27 12:02:00 +0800 feat: quick recovery",
            "bbb2222 2026-10-27 12:00:00 +0800 process restart",
        ]
        pairs = pair_restart_recovery(lines)
        assert len(pairs) == 1
        assert pairs[0]["latency_seconds"] == 120.0
        assert pairs[0]["band"] == "healthy"

    def test_zero_latency(self):
        # same-second restart and recovery
        lines = [
            "aaa1111 2026-10-27 12:00:00 +0800 feat: instant recovery",
            "bbb2222 2026-10-27 12:00:00 +0800 process restart",
        ]
        pairs = pair_restart_recovery(lines)
        assert len(pairs) == 1
        assert pairs[0]["latency_seconds"] == 0.0
        assert pairs[0]["band"] == "healthy"


# ---------------------------------------------------------------------------
# latency_summary
# ---------------------------------------------------------------------------


class TestLatencySummary:
    def test_empty_pairs(self):
        result = latency_summary([])
        assert result["count"] == 0
        assert result["mean_latency"] == 0.0
        assert result["health_score"] == 100.0

    def test_single_pair(self):
        pairs = [{
            "latency_seconds": 200.0,
            "band": "healthy",
            "restart_hash": "a",
            "recovery_hash": "b",
        }]
        result = latency_summary(pairs)
        assert result["count"] == 1
        assert result["mean_latency"] == 200.0
        assert result["median_latency"] == 200.0
        assert result["min_latency"] == 200.0
        assert result["max_latency"] == 200.0
        assert result["band_distribution"] == {"healthy": 1}
        assert result["health_score"] == 100.0

    def test_mixed_bands(self):
        pairs = [
            {"latency_seconds": 100.0, "band": "healthy"},
            {"latency_seconds": 500.0, "band": "degraded"},
            {"latency_seconds": 1200.0, "band": "slow"},
            {"latency_seconds": 2000.0, "band": "critical"},
            {"latency_seconds": 5000.0, "band": "broken"},
        ]
        result = latency_summary(pairs)
        assert result["count"] == 5
        assert result["min_latency"] == 100.0
        assert result["max_latency"] == 5000.0
        assert result["band_distribution"] == {
            "healthy": 1, "degraded": 1, "slow": 1,
            "critical": 1, "broken": 1,
        }
        # health score: (100+70+40+15+0)/5 = 45
        assert result["health_score"] == 45.0

    def test_median_odd_count(self):
        pairs = [
            {"latency_seconds": 100.0, "band": "healthy"},
            {"latency_seconds": 200.0, "band": "healthy"},
            {"latency_seconds": 300.0, "band": "degraded"},
        ]
        result = latency_summary(pairs)
        assert result["median_latency"] == 200.0

    def test_median_even_count(self):
        pairs = [
            {"latency_seconds": 100.0, "band": "healthy"},
            {"latency_seconds": 200.0, "band": "healthy"},
            {"latency_seconds": 300.0, "band": "degraded"},
            {"latency_seconds": 400.0, "band": "degraded"},
        ]
        result = latency_summary(pairs)
        assert result["median_latency"] == 250.0


# ---------------------------------------------------------------------------
# latency_report — integration
# ---------------------------------------------------------------------------


class TestLatencyReport:
    def test_full_report(self):
        lines = [
            "aaa1111 2026-10-27 12:03:00 +0800 feat: add widget",
            "bbb2222 2026-10-27 12:00:00 +0800 process restart after crash",
            "ccc3333 2026-10-27 11:00:00 +0800 feat: earlier work",
        ]
        report = latency_report(lines)
        assert "pairs" in report
        assert "summary" in report
        assert report["summary"]["count"] == 1
        assert report["pairs"][0]["band"] == "healthy"

    def test_report_no_restarts(self):
        lines = [
            "aaa1111 2026-10-27 12:00:00 +0800 feat: something",
            "bbb2222 2026-10-27 11:00:00 +0800 feat: other thing",
        ]
        report = latency_report(lines)
        assert report["summary"]["count"] == 0
        assert report["summary"]["health_score"] == 100.0

    def test_report_real_repo(self):
        """Integration test using the actual repo git log."""
        import subprocess
        result = subprocess.run(
            ["git", "log", "--format=%h %ai %s", "-200"],
            capture_output=True, text=True,
            cwd=str(REPO),
        )
        if result.returncode != 0:
            pytest.skip("git log not available")
        lines = result.stdout.strip().splitlines()
        report = latency_report(lines)
        assert isinstance(report["summary"]["count"], int)
        assert isinstance(report["summary"]["health_score"], float)
        # every pair should have a valid band
        for pair in report["pairs"]:
            assert pair["band"] in (
                "healthy", "degraded", "slow", "critical", "broken"
            )


# ---------------------------------------------------------------------------
# _parse_timestamp
# ---------------------------------------------------------------------------


class TestParseTimestamp:
    def test_positive_tz(self):
        dt = _parse_timestamp("2026-10-27 12:00:00 +0800")
        assert dt.year == 2026
        assert dt.month == 10
        assert dt.day == 27
        assert dt.hour == 12

    def test_zero_tz(self):
        dt = _parse_timestamp("2026-10-27 12:00:00 +0000")
        assert dt.hour == 12

    def test_negative_tz(self):
        dt = _parse_timestamp("2026-10-26 08:30:00 -0500")
        assert dt.hour == 8
        assert dt.minute == 30
