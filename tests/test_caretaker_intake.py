"""Tests for iamai.caretaker_intake — single-call arrival diagnosis."""

from dataclasses import asdict
from unittest.mock import patch, MagicMock

import pytest

from iamai.caretaker_intake import (
    BacklogStatus,
    IntakeReport,
    PushStatus,
    TreeStatus,
    _check_backlog,
    _check_push,
    _check_tree,
    _compute_verdict,
    format_intake,
    run_intake,
)


# ---------------------------------------------------------------------------
# TreeStatus
# ---------------------------------------------------------------------------


class TestTreeStatus:
    def test_defaults(self):
        ts = TreeStatus()
        assert ts.clean is True
        assert ts.uncommitted_files == 0
        assert ts.files == []

    def test_dirty_tree(self):
        ts = TreeStatus(
            clean=False,
            uncommitted_files=3,
            files=["a.py", "b.py", "c.py"],
        )
        assert ts.clean is False
        assert ts.uncommitted_files == 3
        assert len(ts.files) == 3


# ---------------------------------------------------------------------------
# PushStatus
# ---------------------------------------------------------------------------


class TestPushStatus:
    def test_defaults(self):
        ps = PushStatus()
        assert ps.ready is False
        assert ps.unpushed_commits == 0

    def test_ready(self):
        ps = PushStatus(
            ready=True,
            unpushed_commits=0,
            ssh_key_present=True,
            remote_reachable=True,
        )
        assert ps.ready is True


# ---------------------------------------------------------------------------
# BacklogStatus
# ---------------------------------------------------------------------------


class TestBacklogStatus:
    def test_defaults(self):
        bs = BacklogStatus()
        assert bs.depth == 0
        assert bs.risk == "low"
        assert bs.oldest_unpushed_seconds is None

    def test_high_risk(self):
        bs = BacklogStatus(depth=7, risk="high", oldest_unpushed_seconds=3600)
        assert bs.risk == "high"


# ---------------------------------------------------------------------------
# IntakeReport
# ---------------------------------------------------------------------------


class TestIntakeReport:
    def test_to_dict(self):
        report = IntakeReport(
            liveness={"verdict": "healthy"},
            tree=TreeStatus(clean=True),
            push=PushStatus(ready=True),
            backlog=BacklogStatus(depth=0),
            verdict="healthy",
            checked_at=1000.0,
        )
        d = report.to_dict()
        assert d["verdict"] == "healthy"
        assert d["tree"]["clean"] is True
        assert d["push"]["ready"] is True
        assert d["backlog"]["depth"] == 0


# ---------------------------------------------------------------------------
# _compute_verdict
# ---------------------------------------------------------------------------


class TestComputeVerdict:
    def test_healthy(self):
        verdict = _compute_verdict(
            liveness={"verdict": "healthy"},
            tree=TreeStatus(clean=True),
            push=PushStatus(ready=True, ssh_key_present=True, remote_reachable=True),
            backlog=BacklogStatus(depth=0, risk="low"),
        )
        assert verdict == "healthy"

    def test_attention_degraded_process(self):
        verdict = _compute_verdict(
            liveness={"verdict": "degraded"},
            tree=TreeStatus(clean=True),
            push=PushStatus(ready=True, ssh_key_present=True, remote_reachable=True),
            backlog=BacklogStatus(depth=0, risk="low"),
        )
        assert verdict == "attention"

    def test_attention_few_uncommitted(self):
        verdict = _compute_verdict(
            liveness={"verdict": "healthy"},
            tree=TreeStatus(clean=False, uncommitted_files=2),
            push=PushStatus(ready=True, ssh_key_present=True, remote_reachable=True),
            backlog=BacklogStatus(depth=0, risk="low"),
        )
        assert verdict == "attention"

    def test_attention_moderate_backlog(self):
        verdict = _compute_verdict(
            liveness={"verdict": "healthy"},
            tree=TreeStatus(clean=True),
            push=PushStatus(ready=True, ssh_key_present=True, remote_reachable=True),
            backlog=BacklogStatus(depth=2, risk="moderate"),
        )
        assert verdict == "attention"

    def test_action_dead_processes(self):
        verdict = _compute_verdict(
            liveness={"verdict": "dead"},
            tree=TreeStatus(clean=True),
            push=PushStatus(ready=True, ssh_key_present=True, remote_reachable=True),
            backlog=BacklogStatus(depth=0, risk="low"),
        )
        assert verdict == "action"

    def test_action_push_broken(self):
        verdict = _compute_verdict(
            liveness={"verdict": "healthy"},
            tree=TreeStatus(clean=True),
            push=PushStatus(ready=False, ssh_key_present=False, remote_reachable=False),
            backlog=BacklogStatus(depth=0, risk="low"),
        )
        assert verdict == "action"

    def test_action_large_backlog(self):
        verdict = _compute_verdict(
            liveness={"verdict": "healthy"},
            tree=TreeStatus(clean=True),
            push=PushStatus(ready=True, ssh_key_present=True, remote_reachable=True),
            backlog=BacklogStatus(depth=15, risk="critical"),
        )
        assert verdict == "action"

    def test_action_many_uncommitted(self):
        verdict = _compute_verdict(
            liveness={"verdict": "healthy"},
            tree=TreeStatus(clean=False, uncommitted_files=10),
            push=PushStatus(ready=True, ssh_key_present=True, remote_reachable=True),
            backlog=BacklogStatus(depth=0, risk="low"),
        )
        assert verdict == "action"

    def test_combined_issues_escalate(self):
        verdict = _compute_verdict(
            liveness={"verdict": "degraded"},
            tree=TreeStatus(clean=False, uncommitted_files=3),
            push=PushStatus(ready=False, ssh_key_present=True, remote_reachable=False),
            backlog=BacklogStatus(depth=5, risk="high"),
        )
        assert verdict == "action"


# ---------------------------------------------------------------------------
# format_intake
# ---------------------------------------------------------------------------


class TestFormatIntake:
    def test_healthy_format(self):
        report = IntakeReport(
            liveness={"writer_alive": True, "batch_alive": True, "verdict": "healthy"},
            tree=TreeStatus(clean=True),
            push=PushStatus(ready=True, ssh_key_present=True, remote_reachable=True),
            backlog=BacklogStatus(depth=0, risk="low"),
            verdict="healthy",
        )
        text = format_intake(report)
        assert "healthy" in text
        assert "writer up" in text
        assert "batch up" in text
        assert "tree clean" in text

    def test_action_format(self):
        report = IntakeReport(
            liveness={"writer_alive": False, "batch_alive": False, "verdict": "dead"},
            tree=TreeStatus(clean=False, uncommitted_files=7),
            push=PushStatus(
                ready=False,
                ssh_key_present=False,
                remote_reachable=False,
                unpushed_commits=3,
            ),
            backlog=BacklogStatus(depth=5, risk="high"),
            verdict="action",
        )
        text = format_intake(report)
        assert "action" in text
        assert "writer down" in text
        assert "7 uncommitted" in text
        assert "no key" in text
        assert "backlog 5" in text

    def test_attention_format(self):
        report = IntakeReport(
            liveness={"writer_alive": True, "batch_alive": False, "verdict": "degraded"},
            tree=TreeStatus(clean=True),
            push=PushStatus(ready=True, ssh_key_present=True, remote_reachable=True),
            backlog=BacklogStatus(depth=0, risk="low"),
            verdict="attention",
        )
        text = format_intake(report)
        assert "attention" in text
        assert "batch down" in text


# ---------------------------------------------------------------------------
# _check_tree (mocked git)
# ---------------------------------------------------------------------------


class TestCheckTree:
    @patch("iamai.caretaker_intake.subprocess.run")
    def test_clean_tree(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        ts = _check_tree("/fake/repo")
        assert ts.clean is True
        assert ts.uncommitted_files == 0

    @patch("iamai.caretaker_intake.subprocess.run")
    def test_dirty_tree(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=" M docs/DEVLOG.md\n M data/strokes.jsonl\n",
        )
        ts = _check_tree("/fake/repo")
        assert ts.clean is False
        assert ts.uncommitted_files == 2

    @patch("iamai.caretaker_intake.subprocess.run")
    def test_untracked_files(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="?? new_file.py\n?? another.py\n",
        )
        ts = _check_tree("/fake/repo")
        assert ts.clean is False
        assert ts.untracked_files == 2

    @patch("iamai.caretaker_intake.subprocess.run")
    def test_git_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=128, stdout="")
        ts = _check_tree("/fake/repo")
        assert ts.clean is False

    @patch("iamai.caretaker_intake.subprocess.run")
    def test_git_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        ts = _check_tree("/fake/repo")
        assert ts.clean is False


# ---------------------------------------------------------------------------
# _check_backlog (mocked git)
# ---------------------------------------------------------------------------


class TestCheckBacklog:
    @patch("iamai.caretaker_intake.subprocess.run")
    def test_no_backlog(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        bs = _check_backlog("/fake/repo")
        assert bs.depth == 0
        assert bs.risk == "low"

    @patch("iamai.caretaker_intake.subprocess.run")
    def test_small_backlog(self, mock_run):
        def side_effect(cmd, **kwargs):
            if "log" in cmd and "--oneline" in cmd:
                return MagicMock(returncode=0, stdout="abc1234 commit 1\ndef5678 commit 2\n")
            if "log" in cmd and "--format=%at" in cmd:
                return MagicMock(returncode=0, stdout="1730480000\n")
            return MagicMock(returncode=0, stdout="")

        mock_run.side_effect = side_effect
        bs = _check_backlog("/fake/repo")
        assert bs.depth == 2
        assert bs.risk in ("moderate", "high", "critical")  # depends on age

    @patch("iamai.caretaker_intake.subprocess.run")
    def test_large_backlog(self, mock_run):
        lines = "\n".join([f"abc{i:05d} commit {i}" for i in range(15)])
        mock_run.return_value = MagicMock(returncode=0, stdout=lines + "\n")
        bs = _check_backlog("/fake/repo")
        assert bs.depth == 15
        assert bs.risk == "critical"

    @patch("iamai.caretaker_intake.subprocess.run")
    def test_git_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        bs = _check_backlog("/fake/repo")
        assert bs.depth == 0
        assert bs.risk == "low"


# ---------------------------------------------------------------------------
# run_intake (integration-style with mocks)
# ---------------------------------------------------------------------------


class TestRunIntake:
    @patch("iamai.caretaker_intake._check_backlog")
    @patch("iamai.caretaker_intake._check_push")
    @patch("iamai.caretaker_intake._check_tree")
    @patch("iamai.caretaker_intake.check_liveness")
    def test_full_healthy(
        self, mock_liveness, mock_tree, mock_push, mock_backlog
    ):
        from iamai.process_liveness import LivenessReport, ProcessInfo

        mock_liveness.return_value = LivenessReport(
            writer=ProcessInfo(alive=True, pid=100, uptime=300),
            batch=ProcessInfo(alive=True, pid=101, uptime=300),
            verdict="healthy",
            checked_at=1000.0,
        )
        mock_tree.return_value = TreeStatus(clean=True)
        mock_push.return_value = PushStatus(
            ready=True, ssh_key_present=True, remote_reachable=True
        )
        mock_backlog.return_value = BacklogStatus(depth=0, risk="low")

        report = run_intake("/fake/repo")
        assert report.verdict == "healthy"
        assert report.tree.clean is True
        assert report.push.ready is True

    @patch("iamai.caretaker_intake._check_backlog")
    @patch("iamai.caretaker_intake._check_push")
    @patch("iamai.caretaker_intake._check_tree")
    @patch("iamai.caretaker_intake.check_liveness")
    def test_full_action(
        self, mock_liveness, mock_tree, mock_push, mock_backlog
    ):
        from iamai.process_liveness import LivenessReport, ProcessInfo

        mock_liveness.return_value = LivenessReport(
            writer=ProcessInfo(),
            batch=ProcessInfo(),
            verdict="dead",
            checked_at=1000.0,
        )
        mock_tree.return_value = TreeStatus(clean=False, uncommitted_files=8)
        mock_push.return_value = PushStatus(
            ready=False, ssh_key_present=False, remote_reachable=False
        )
        mock_backlog.return_value = BacklogStatus(depth=10, risk="critical")

        report = run_intake("/fake/repo")
        assert report.verdict == "action"
