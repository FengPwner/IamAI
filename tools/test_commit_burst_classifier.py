#!/usr/bin/env python3
"""tests for commit_burst_classifier.py"""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from commit_burst_classifier import (
    Commit, Burst, find_bursts, classify_burst,
    compute_report, _is_admin, _is_recovery,
    BurstReport,
)


def _mkcommit(
    ts: datetime,
    message: str = "add feature X",
    hash_val: str = "abc12345",
    files_changed: int = 3,
) -> Commit:
    return Commit(hash=hash_val, timestamp=ts, message=message,
                  files_changed=files_changed)


# ── _is_admin ──────────────────────────────────────────────

class TestIsAdmin:
    def test_catch_up(self):
        assert _is_admin("catch-up: commit pending changes") is True

    def test_auto_commit(self):
        assert _is_admin("auto-commit: hourly sync") is True

    def test_auto_commit_no_hyphen(self):
        assert _is_admin("autocommit: blah") is True

    def test_hourly_monitor(self):
        assert _is_admin("hourly monitor auto-commit") is True

    def test_backlog(self):
        assert _is_admin("backlog drain: flush 50 pending") is True

    def test_caretaker_visit(self):
        assert _is_admin("caretaker visit 753: add tool") is True

    def test_feature_commit_not_admin(self):
        assert _is_admin("add stroke_novelty tool + 20 tests") is False

    def test_fix_not_admin(self):
        assert _is_admin("fix cadence drift bug") is False

    def test_process_restart(self):
        assert _is_admin("process restart after OOM") is True

    def test_rescue(self):
        assert _is_admin("rescue push after ssh key expiry") is True


# ── _is_recovery ───────────────────────────────────────────

class TestIsRecovery:
    def test_fix(self):
        assert _is_recovery("fix push divergence") is True

    def test_restart(self):
        assert _is_recovery("restart writer loop") is True

    def test_revert(self):
        assert _is_recovery("revert bad merge") is True

    def test_recover(self):
        assert _is_recovery("recover from stall") is True

    def test_patch(self):
        assert _is_recovery("patch broken config") is True

    def test_hotfix(self):
        assert _is_recovery("hotfix: ssh key perms") is True

    def test_stall_keyword(self):
        assert _is_recovery("address stall in writer") is True

    def test_broken_keyword(self):
        assert _is_recovery("repair broken pipeline") is True

    def test_normal_feature(self):
        assert _is_recovery("add commit diversity tool") is False


# ── find_bursts ────────────────────────────────────────────

class TestFindBursts:
    def _ts(self, minute: int) -> datetime:
        return datetime(2026, 11, 21, 0, minute, 0, tzinfo=timezone.utc)

    def test_single_burst(self):
        commits = [
            _mkcommit(self._ts(0), "a"),
            _mkcommit(self._ts(1), "b"),
            _mkcommit(self._ts(2), "c"),
        ]
        bursts = find_bursts(commits, burst_gap_s=120)
        assert len(bursts) == 1
        assert len(bursts[0].commits) == 3

    def test_two_bursts(self):
        commits = [
            _mkcommit(self._ts(0), "a"),
            _mkcommit(self._ts(1), "b"),
            # 10 minute gap
            _mkcommit(self._ts(11), "c"),
            _mkcommit(self._ts(12), "d"),
        ]
        bursts = find_bursts(commits, burst_gap_s=120)
        assert len(bursts) == 2

    def test_isolated_commits_excluded(self):
        """Single commits between gaps are not bursts."""
        commits = [
            _mkcommit(self._ts(0), "a"),
            # 10 min gap
            _mkcommit(self._ts(10), "b"),
            # 10 min gap
            _mkcommit(self._ts(20), "c"),
        ]
        bursts = find_bursts(commits, burst_gap_s=120)
        assert len(bursts) == 0

    def test_empty_input(self):
        assert find_bursts([], burst_gap_s=120) == []

    def test_custom_gap(self):
        commits = [
            _mkcommit(self._ts(0), "a"),
            _mkcommit(self._ts(5), "b"),
            _mkcommit(self._ts(10), "c"),
        ]
        # with 5-minute gap threshold, all are in one burst
        bursts = find_bursts(commits, burst_gap_s=300)
        assert len(bursts) == 1

    def test_chronological_reorder(self):
        """Commits arrive newest-first; bursts should still work."""
        commits = [
            _mkcommit(self._ts(2), "c"),
            _mkcommit(self._ts(1), "b"),
            _mkcommit(self._ts(0), "a"),
        ]
        bursts = find_bursts(commits, burst_gap_s=120)
        assert len(bursts) == 1
        # verify chronological order inside burst
        assert bursts[0].commits[0].message == "a"
        assert bursts[0].commits[-1].message == "c"


# ── classify_burst ─────────────────────────────────────────

class TestClassifyBurst:
    def _ts(self, minute: int) -> datetime:
        return datetime(2026, 11, 21, 0, minute, 0, tzinfo=timezone.utc)

    def test_productive(self):
        burst = Burst(commits=[
            _mkcommit(self._ts(0), "add stroke_novelty.py", files_changed=5),
            _mkcommit(self._ts(1), "add tests for novelty", files_changed=3),
            _mkcommit(self._ts(2), "update docs", files_changed=2),
        ])
        classify_burst(burst)
        assert burst.classification == "productive"

    def test_admin(self):
        burst = Burst(commits=[
            _mkcommit(self._ts(0), "catch-up: commit pending", files_changed=7),
            _mkcommit(self._ts(1), "caretaker visit 100", files_changed=4),
            _mkcommit(self._ts(2), "auto-commit: hourly", files_changed=2),
        ])
        classify_burst(burst)
        assert burst.classification == "admin"

    def test_recovery(self):
        burst = Burst(commits=[
            _mkcommit(self._ts(0), "fix push divergence", files_changed=2),
            _mkcommit(self._ts(1), "restart writer loop", files_changed=1),
            _mkcommit(self._ts(2), "patch config", files_changed=1),
        ])
        classify_burst(burst)
        assert burst.classification == "recovery"

    def test_churn(self):
        burst = Burst(commits=[
            _mkcommit(self._ts(0), "update file A", files_changed=1),
            _mkcommit(self._ts(1), "update file A again", files_changed=1),
            _mkcommit(self._ts(2), "update file A once more", files_changed=1),
            _mkcommit(self._ts(3), "update file A final", files_changed=1),
        ])
        classify_burst(burst)
        assert burst.classification == "churn"


# ── compute_report ─────────────────────────────────────────

class TestComputeReport:
    def _ts(self, minute: int) -> datetime:
        return datetime(2026, 11, 21, 0, minute, 0, tzinfo=timezone.utc)

    def test_healthy(self):
        bursts = [
            Burst(commits=[
                _mkcommit(self._ts(0), "add tool A", files_changed=5),
                _mkcommit(self._ts(1), "test tool A", files_changed=3),
            ], classification="productive"),
            Burst(commits=[
                _mkcommit(self._ts(10), "add tool B", files_changed=4),
                _mkcommit(self._ts(11), "test tool B", files_changed=2),
            ], classification="productive"),
            Burst(commits=[
                _mkcommit(self._ts(20), "catch-up: blah", files_changed=7),
                _mkcommit(self._ts(21), "auto-commit", files_changed=3),
            ], classification="admin"),
        ]
        report = compute_report(bursts, 10)
        assert report.verdict == "healthy"
        assert report.productive_pct == pytest.approx(66.7, abs=0.1)

    def test_stressed(self):
        bursts = [
            Burst(commits=[], classification="admin"),
            Burst(commits=[], classification="admin"),
            Burst(commits=[], classification="recovery"),
            Burst(commits=[], classification="productive"),
        ]
        report = compute_report(bursts, 10)
        assert report.verdict == "stressed"

    def test_churning(self):
        bursts = [
            Burst(commits=[], classification="churn"),
            Burst(commits=[], classification="churn"),
            Burst(commits=[], classification="churn"),
            Burst(commits=[], classification="productive"),
        ]
        report = compute_report(bursts, 10)
        assert report.verdict == "churning"

    def test_no_bursts(self):
        report = compute_report([], 5)
        assert report.verdict == "no_bursts"
        assert report.total_bursts == 0

    def test_mixed(self):
        bursts = [
            Burst(commits=[], classification="productive"),
            Burst(commits=[], classification="productive"),
            Burst(commits=[], classification="admin"),
            Burst(commits=[], classification="recovery"),
            Burst(commits=[], classification="churn"),
        ]
        report = compute_report(bursts, 10)
        assert report.verdict == "mixed"  # 40% productive


# ── edge cases ─────────────────────────────────────────────

class TestEdgeCases:
    def _ts(self, minute: int) -> datetime:
        return datetime(2026, 11, 21, 0, minute, 0, tzinfo=timezone.utc)

    def test_burst_with_mixed_messages(self):
        burst = Burst(commits=[
            _mkcommit(self._ts(0), "add new feature", files_changed=5),
            _mkcommit(self._ts(1), "catch-up: pending", files_changed=3),
        ])
        classify_burst(burst)
        # 50% admin, not >= 60%, so not classified as admin
        assert burst.classification != "admin" or burst.admin_ratio >= 0.6

    def test_zero_files_changed_defaults_to_one(self):
        burst = Burst(commits=[
            _mkcommit(self._ts(0), "add feature", files_changed=0),
            _mkcommit(self._ts(1), "test feature", files_changed=0),
        ])
        classify_burst(burst)
        # should not crash, unique_files_ratio should be low
        assert burst.unique_files_ratio >= 0

    def test_report_json_serializable(self):
        report = BurstReport(
            total_commits=10,
            total_bursts=2,
            burst_sizes=[3, 4],
            classifications={"productive": 2},
            verdict="healthy",
            productive_pct=100.0,
        )
        import json
        data = json.loads(json.dumps(report.__dict__))
        assert data["verdict"] == "healthy"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
