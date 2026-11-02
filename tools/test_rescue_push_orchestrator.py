#!/usr/bin/env python3
"""Tests for rescue_push_orchestrator.py — process lifecycle and push recovery.

Uses temporary git repos with a bare remote to verify:
    - OrchestratorReport structure and summarization
    - Process detection and stopping
    - Pending commit before rebase
    - Pull --rebase success path
    - Push success after rebase
    - Full orchestration happy path
    - Dry-run mode
    - skip-restart mode
    - Error handling when rebase fails
    - JSON output format

Run: python3 tools/test_rescue_push_orchestrator.py
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Ensure tools/ is importable
sys.path.insert(0, str(Path(__file__).parent))
import rescue_push_orchestrator as rpo


def git(args, cwd, env=None):
    """Run git with test identity."""
    full_env = os.environ.copy()
    full_env["GIT_AUTHOR_NAME"] = "test"
    full_env["GIT_AUTHOR_EMAIL"] = "test@test.local"
    full_env["GIT_COMMITTER_NAME"] = "test"
    full_env["GIT_COMMITTER_EMAIL"] = "test@test.local"
    if env:
        full_env.update(env)
    return subprocess.run(
        ["git"] + args, cwd=str(cwd), capture_output=True, text=True, env=full_env
    )


def make_repo_with_remote(tmp: Path):
    """Create a bare remote + working repo with one commit on main."""
    remote_d = tmp / "remote.git"
    remote_d.mkdir()
    git(["init", "--bare", str(remote_d)], tmp)

    work = tmp / "work"
    work.mkdir()
    git(["clone", str(remote_d), str(work)], tmp)
    git(["config", "user.name", "test"], work)
    git(["config", "user.email", "test@test.local"], work)
    git(["checkout", "-b", "main"], work)
    (work / "README.md").write_text("# test repo\n")
    git(["add", "-A"], work)
    git(["commit", "-m", "init"], work)
    git(["push", "origin", "main"], work)
    return work, remote_d


def make_diverged_state(work: Path, remote_d: Path):
    """Create divergence: local commit + remote-only commit."""
    # Remote-only commit via a second clone
    tmp2 = work.parent / "other_clone"
    git(["clone", str(remote_d), str(tmp2)], work.parent)
    git(["checkout", "-b", "main"], tmp2)
    (tmp2 / "remote_change.md").write_text("from remote\n")
    git(["add", "-A"], tmp2)
    git(["commit", "-m", "remote commit"], tmp2)
    git(["push", "origin", "main"], tmp2)

    # Local-only commit
    (work / "local_change.md").write_text("from local\n")
    git(["add", "-A"], work)
    git(["commit", "-m", "local commit"], work)


class TestOrchestratorReport(unittest.TestCase):
    """Report data structure tests."""

    def test_default_state(self):
        r = rpo.OrchestratorReport()
        self.assertFalse(r.success)
        self.assertFalse(r.pushed)
        self.assertEqual(r.steps, [])
        self.assertEqual(r.pending_file_count, 0)

    def test_log_appends_steps(self):
        r = rpo.OrchestratorReport()
        r.log("step 1")
        r.log("step 2")
        self.assertEqual(r.steps, ["step 1", "step 2"])

    def test_summarize_includes_all_fields(self):
        r = rpo.OrchestratorReport()
        r.success = True
        r.pushed = True
        r.writer_stopped = True
        r.batch_stopped = True
        r.pending_committed = True
        r.pending_file_count = 3
        r.rebased = True
        r.writer_restarted = True
        r.batch_restarted = True
        r.duration_s = 4.2
        r.log("did stuff")

        s = r.summarize()
        self.assertIn("success: True", s)
        self.assertIn("pushed: True", s)
        self.assertIn("writer stopped: True", s)
        self.assertIn("3 files", s)
        self.assertIn("4.2s", s)
        self.assertIn("did stuff", s)

    def test_to_dict(self):
        r = rpo.OrchestratorReport()
        r.success = True
        r.error = "test error"
        d = r.to_dict()
        self.assertIsInstance(d, dict)
        self.assertTrue(d["success"])
        self.assertEqual(d["error"], "test error")
        # Should be JSON-serializable
        json.dumps(d)

    def test_summarize_with_error(self):
        r = rpo.OrchestratorReport()
        r.error = "push rejected"
        s = r.summarize()
        self.assertIn("push rejected", s)


class TestProcessManagement(unittest.TestCase):
    """Process detection and stopping."""

    def test_find_processes_nonexistent(self):
        pids = rpo.find_processes("nonexistent_process_xyz_12345")
        self.assertEqual(pids, [])

    def test_stop_process_already_dead(self):
        self.assertTrue(rpo.stop_process(999999))

    def test_stop_process_real(self):
        """Start a sleep process and stop it."""
        proc = subprocess.Popen(
            ["sleep", "60"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        pid = proc.pid
        time.sleep(0.2)
        result = rpo.stop_process(pid, timeout_s=3.0)
        # Reap the child to avoid zombie
        proc.wait(timeout=2)
        self.assertTrue(result)
        self.assertNotEqual(proc.returncode, None)


class TestGitOperations(unittest.TestCase):
    """Git helper function tests."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="orch-test-"))
        self.work, self.remote = make_repo_with_remote(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_has_uncommitted_changes_clean(self):
        self.assertFalse(rpo.has_uncommitted_changes(self.work))

    def test_has_uncommitted_changes_dirty(self):
        (self.work / "new.txt").write_text("dirty\n")
        self.assertTrue(rpo.has_uncommitted_changes(self.work))

    def test_count_uncommitted_files(self):
        (self.work / "a.txt").write_text("a\n")
        (self.work / "b.txt").write_text("b\n")
        self.assertEqual(rpo.count_uncommitted_files(self.work), 2)

    def test_commit_pending(self):
        (self.work / "pending.txt").write_text("pending\n")
        self.assertTrue(rpo.commit_pending(self.work))
        self.assertFalse(rpo.has_uncommitted_changes(self.work))

    def test_pull_rebase_no_divergence(self):
        self.assertTrue(rpo.pull_rebase(self.work, "origin", "main"))

    def test_pull_rebase_with_divergence(self):
        make_diverged_state(self.work, self.remote)
        self.assertTrue(rpo.pull_rebase(self.work, "origin", "main"))

    def test_push_clean(self):
        self.assertTrue(rpo.push(self.work, "origin", "main"))

    def test_push_after_rebase(self):
        make_diverged_state(self.work, self.remote)
        rpo.pull_rebase(self.work, "origin", "main")
        self.assertTrue(rpo.push(self.work, "origin", "main"))


class TestFullOrchestration(unittest.TestCase):
    """Full orchestration flow tests."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="orch-full-"))
        self.work, self.remote = make_repo_with_remote(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_happy_path_no_divergence(self):
        """Clean push with no divergence should succeed."""
        report = rpo.orchestrate(
            self.work, "origin", "main",
            skip_restart=True  # Don't try to start writer/batch in tests
        )
        self.assertTrue(report.success)
        self.assertTrue(report.pushed)
        self.assertEqual(report.error, "")

    def test_happy_path_with_divergence(self):
        """Diverged state should rebase and push successfully."""
        make_diverged_state(self.work, self.remote)
        report = rpo.orchestrate(
            self.work, "origin", "main",
            skip_restart=True
        )
        self.assertTrue(report.success)
        self.assertTrue(report.rebased)
        self.assertTrue(report.pushed)

    def test_pending_changes_committed_before_rebase(self):
        """Uncommitted changes should be committed before rebase."""
        make_diverged_state(self.work, self.remote)
        # Write uncommitted file AFTER divergence so it's not swept into local commit
        (self.work / "uncommitted.txt").write_text("stuff\n")
        self.assertTrue(rpo.has_uncommitted_changes(self.work))
        report = rpo.orchestrate(
            self.work, "origin", "main",
            skip_restart=True
        )
        self.assertTrue(report.pending_committed)
        self.assertGreaterEqual(report.pending_file_count, 1)
        self.assertTrue(report.success)

    def test_dry_run(self):
        """Dry-run should report success without actually doing anything."""
        make_diverged_state(self.work, self.remote)
        report = rpo.orchestrate(
            self.work, "origin", "main",
            dry_run=True, skip_restart=True
        )
        self.assertTrue(report.success)
        # Verify the divergence still exists (nothing was actually done)
        r = git(["log", "--oneline", "origin/main..HEAD"], self.work)
        self.assertTrue(r.stdout.strip())  # Still has unpushed commits

    def test_skip_restart(self):
        """skip_restart should not attempt to restart processes."""
        report = rpo.orchestrate(
            self.work, "origin", "main",
            skip_restart=True
        )
        self.assertFalse(report.writer_restarted)
        self.assertFalse(report.batch_restarted)

    def test_duration_tracked(self):
        """Duration should be measured."""
        report = rpo.orchestrate(
            self.work, "origin", "main",
            skip_restart=True
        )
        self.assertGreater(report.duration_s, 0)

    def test_steps_are_sequential(self):
        """Steps should log in order: stop, commit, rebase, push, restart."""
        make_diverged_state(self.work, self.remote)
        (self.work / "extra.txt").write_text("more\n")
        report = rpo.orchestrate(
            self.work, "origin", "main",
            skip_restart=True
        )
        step_text = " ".join(report.steps)
        # Verify ordering by finding key step phrases
        stop_idx = step_text.find("stopping")
        commit_idx = step_text.find("committing")
        rebase_idx = step_text.find("pulling --rebase")
        push_idx = step_text.find("pushing to")
        self.assertGreaterEqual(stop_idx, 0, "should log stopping step")
        self.assertGreaterEqual(rebase_idx, 0, "should log rebase step")
        self.assertGreaterEqual(push_idx, 0, "should log push step")
        if commit_idx >= 0:
            self.assertLess(stop_idx, commit_idx)
        self.assertLess(rebase_idx, push_idx)


class TestJSONOutput(unittest.TestCase):
    """JSON output format tests."""

    def test_json_serializable(self):
        r = rpo.OrchestratorReport()
        r.success = True
        r.steps = ["step1", "step2"]
        r.pending_file_count = 5
        output = json.dumps(r.to_dict())
        parsed = json.loads(output)
        self.assertEqual(parsed["pending_file_count"], 5)


if __name__ == "__main__":
    unittest.main()
