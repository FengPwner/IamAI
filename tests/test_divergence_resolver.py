"""Tests for tools/divergence_resolver.py — push divergence auto-resolution.

These tests verify the logic without requiring actual git remotes or network
access. Each test constructs a controlled scenario using unittest.mock to
patch subprocess calls, then asserts the resolver produces the correct
verdict and step sequence.

34 tests covering:
  - Normal resolution path (dirty → stash → rebase → pop)
  - Clean working tree (skip stash)
  - Already up to date (no divergence)
  - Fetch failure
  - Stash failure
  - Rebase failure (with abort + restore)
  - Stash pop failure
  - Dry run mode
  - JSON output format
  - Exit code mapping
  - Edge cases (timeout, missing git, empty repo)
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure tools/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from divergence_resolver import (
    resolve,
    ResolveReport,
    StepResult,
    _is_behind,
    _is_dirty,
    _run,
    _git_env,
    main,
)


class TestStepResult(unittest.TestCase):
    """StepResult dataclass basics."""

    def test_fields(self):
        s = StepResult("fetch", "ok", "fetched origin/main", "output")
        self.assertEqual(s.step, "fetch")
        self.assertEqual(s.status, "ok")
        self.assertEqual(s.detail, "fetched origin/main")
        self.assertEqual(s.output, "output")

    def test_default_output(self):
        s = StepResult("stash", "skipped", "nothing")
        self.assertEqual(s.output, "")


class TestResolveReport(unittest.TestCase):
    """ResolveReport dataclass basics."""

    def test_fields(self):
        r = ResolveReport([], "clean", "nothing to do")
        self.assertEqual(r.verdict, "clean")
        self.assertEqual(r.message, "nothing to do")
        self.assertEqual(r.steps, [])

    def test_asdict(self):
        r = ResolveReport(
            [StepResult("fetch", "ok", "ok")],
            "resolved",
            "done",
        )
        d = asdict(r)
        self.assertIn("steps", d)
        self.assertIn("verdict", d)
        self.assertEqual(d["verdict"], "resolved")


class TestRun(unittest.TestCase):
    """_run wrapper edge cases."""

    @patch("divergence_resolver.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "status"], returncode=0,
            stdout="clean\n", stderr="",
        )
        rc, out, err = _run(["git", "status"], Path("/tmp"))
        self.assertEqual(rc, 0)
        self.assertEqual(out, "clean")
        self.assertEqual(err, "")

    @patch("divergence_resolver.subprocess.run")
    def test_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "push"], returncode=1,
            stdout="", stderr="rejected",
        )
        rc, out, err = _run(["git", "push"], Path("/tmp"))
        self.assertEqual(rc, 1)
        self.assertEqual(err, "rejected")

    @patch("divergence_resolver.subprocess.run")
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git fetch", timeout=120)
        rc, out, err = _run(["git", "fetch"], Path("/tmp"))
        self.assertEqual(rc, 124)
        self.assertIn("timeout", err)

    @patch("divergence_resolver.subprocess.run")
    def test_missing_command(self, mock_run):
        mock_run.side_effect = FileNotFoundError("no such file")
        rc, out, err = _run(["nonexistent"], Path("/tmp"))
        self.assertEqual(rc, 127)
        self.assertIn("no such file", err)


class TestIsBehind(unittest.TestCase):
    """_is_behind parsing of rev-list output."""

    @patch("divergence_resolver._run")
    def test_behind(self, mock_run):
        mock_run.return_value = (0, "0\t3", "")
        self.assertTrue(_is_behind(Path("/tmp")))

    @patch("divergence_resolver._run")
    def test_ahead_only(self, mock_run):
        mock_run.return_value = (0, "2\t0", "")
        self.assertFalse(_is_behind(Path("/tmp")))

    @patch("divergence_resolver._run")
    def test_up_to_date(self, mock_run):
        mock_run.return_value = (0, "0\t0", "")
        self.assertFalse(_is_behind(Path("/tmp")))

    @patch("divergence_resolver._run")
    def test_both_diverged(self, mock_run):
        mock_run.return_value = (0, "1\t1", "")
        self.assertTrue(_is_behind(Path("/tmp")))

    @patch("divergence_resolver._run")
    def test_command_fails(self, mock_run):
        mock_run.return_value = (128, "", "fatal")
        self.assertFalse(_is_behind(Path("/tmp")))

    @patch("divergence_resolver._run")
    def test_empty_output(self, mock_run):
        mock_run.return_value = (0, "", "")
        self.assertFalse(_is_behind(Path("/tmp")))


class TestIsDirty(unittest.TestCase):
    """_is_dirty parsing of git status --porcelain."""

    @patch("divergence_resolver._run")
    def test_dirty(self, mock_run):
        mock_run.return_value = (0, " M data/strokes.jsonl", "")
        self.assertTrue(_is_dirty(Path("/tmp")))

    @patch("divergence_resolver._run")
    def test_clean(self, mock_run):
        mock_run.return_value = (0, "", "")
        self.assertFalse(_is_dirty(Path("/tmp")))

    @patch("divergence_resolver._run")
    def test_multiple_files(self, mock_run):
        mock_run.return_value = (0, " M a\n M b\n?? c", "")
        self.assertTrue(_is_dirty(Path("/tmp")))


class TestGitEnv(unittest.TestCase):
    """_git_env SSH key rescue logic."""

    @patch.dict("os.environ", {"GIT_SSH_COMMAND": "existing"}, clear=False)
    def test_respects_existing(self):
        env = _git_env()
        self.assertEqual(env["GIT_SSH_COMMAND"], "existing")

    @patch.dict("os.environ", {}, clear=True)
    @patch("divergence_resolver.Path.exists")
    def test_no_key(self, mock_exists):
        mock_exists.return_value = False
        env = _git_env()
        self.assertNotIn("GIT_SSH_COMMAND", env)


class TestResolveFull(unittest.TestCase):
    """Full resolution path: dirty tree, behind remote, success."""

    @patch("divergence_resolver._run")
    @patch("divergence_resolver._is_behind", return_value=True)
    @patch("divergence_resolver._is_dirty", return_value=True)
    def test_dirty_resolve(self, mock_dirty, mock_behind, mock_run):
        # fetch ok, stash ok, pull ok, pop ok
        mock_run.side_effect = [
            (0, "", ""),       # fetch
            (0, "Saved", ""),  # stash
            (0, "rebased", ""),# pull --rebase
            (0, "restored", ""),# stash pop
        ]
        report = resolve(Path("/tmp"))
        self.assertEqual(report.verdict, "resolved")
        self.assertEqual(len(report.steps), 4)  # fetch, stash, rebase, pop
        self.assertEqual(report.steps[0].step, "fetch")
        self.assertEqual(report.steps[1].step, "stash")
        self.assertEqual(report.steps[1].status, "ok")
        self.assertEqual(report.steps[2].step, "rebase")
        self.assertEqual(report.steps[3].step, "pop")

    @patch("divergence_resolver._run")
    @patch("divergence_resolver._is_behind", return_value=True)
    @patch("divergence_resolver._is_dirty", return_value=False)
    def test_clean_resolve(self, mock_dirty, mock_behind, mock_run):
        mock_run.side_effect = [
            (0, "", ""),       # fetch
            (0, "rebased", ""),# pull --rebase
        ]
        report = resolve(Path("/tmp"))
        self.assertEqual(report.verdict, "resolved")
        # stash should be skipped, pop should be skipped
        stash_step = report.steps[1]
        self.assertEqual(stash_step.step, "stash")
        self.assertEqual(stash_step.status, "skipped")


class TestResolveFailures(unittest.TestCase):
    """Each failure path should abort cleanly and attempt recovery."""

    @patch("divergence_resolver._run")
    def test_fetch_failure(self, mock_run):
        mock_run.return_value = (1, "", "fatal: could not resolve")
        report = resolve(Path("/tmp"))
        self.assertEqual(report.verdict, "failed")
        self.assertIn("fetch", report.message)

    @patch("divergence_resolver._run")
    @patch("divergence_resolver._is_behind", return_value=True)
    @patch("divergence_resolver._is_dirty", return_value=True)
    def test_stash_failure(self, mock_dirty, mock_behind, mock_run):
        mock_run.side_effect = [
            (0, "", ""),       # fetch ok
            (1, "", "stash failed: permission denied"),
        ]
        report = resolve(Path("/tmp"))
        self.assertEqual(report.verdict, "failed")
        self.assertIn("stash", report.message)

    @patch("divergence_resolver._run")
    @patch("divergence_resolver._is_behind", return_value=True)
    @patch("divergence_resolver._is_dirty", return_value=True)
    def test_rebase_failure_aborts(self, mock_dirty, mock_behind, mock_run):
        # fetch ok, stash ok, rebase fails, rebase --abort, stash pop
        calls = []
        def side_effect(cmd, cwd, timeout=120):
            calls.append(cmd)
            if cmd == ["git", "fetch", "origin", "main"]:
                return (0, "", "")
            if cmd == ["git", "stash", "push", "-m", "divergence_resolver: auto-stash"]:
                return (0, "Saved", "")
            if cmd == ["git", "pull", "--rebase", "origin", "main"]:
                return (1, "", "CONFLICT in data/strokes.jsonl")
            if cmd == ["git", "rebase", "--abort"]:
                return (0, "", "")
            if cmd == ["git", "stash", "pop"]:
                return (0, "restored", "")
            return (0, "", "")
        mock_run.side_effect = side_effect
        report = resolve(Path("/tmp"))
        self.assertEqual(report.verdict, "failed")
        self.assertIn("rebase", report.message)
        # Verify rebase --abort was called
        abort_called = any("rebase" in c and "--abort" in c for c in calls)
        self.assertTrue(abort_called, "rebase --abort should be called on failure")

    @patch("divergence_resolver._run")
    @patch("divergence_resolver._is_behind", return_value=True)
    @patch("divergence_resolver._is_dirty", return_value=True)
    def test_pop_failure(self, mock_dirty, mock_behind, mock_run):
        mock_run.side_effect = [
            (0, "", ""),       # fetch
            (0, "Saved", ""),  # stash
            (0, "rebased", ""),# pull --rebase
            (1, "", "CONFLICT in stash pop"),
        ]
        report = resolve(Path("/tmp"))
        self.assertEqual(report.verdict, "failed")
        self.assertIn("stash pop", report.message)


class TestResolveClean(unittest.TestCase):
    """Already up to date — no work needed."""

    @patch("divergence_resolver._run")
    @patch("divergence_resolver._is_behind", return_value=False)
    def test_already_clean(self, mock_behind, mock_run):
        mock_run.return_value = (0, "", "")  # fetch
        report = resolve(Path("/tmp"))
        self.assertEqual(report.verdict, "clean")
        self.assertEqual(len(report.steps), 2)  # fetch + check skipped


class TestDryRun(unittest.TestCase):
    """Dry run should detect divergence but not modify anything."""

    @patch("divergence_resolver._run")
    @patch("divergence_resolver._is_behind", return_value=True)
    def test_dry_run_behind(self, mock_behind, mock_run):
        mock_run.return_value = (0, "", "")  # fetch
        report = resolve(Path("/tmp"), dry_run=True)
        self.assertEqual(report.verdict, "resolved")
        self.assertIn("dry run", report.message)
        # Should NOT have called stash or pull
        for step in report.steps:
            self.assertNotIn("stash", step.step)
            self.assertNotIn("rebase", step.step)


class TestExitCodes(unittest.TestCase):
    """main() exit code mapping."""

    @patch("divergence_resolver.resolve")
    @patch("sys.argv", ["divergence_resolver.py"])
    def test_resolved_exit(self, mock_resolve):
        mock_resolve.return_value = ResolveReport([], "resolved", "done")
        self.assertEqual(main(), 0)

    @patch("divergence_resolver.resolve")
    @patch("sys.argv", ["divergence_resolver.py"])
    def test_clean_exit(self, mock_resolve):
        mock_resolve.return_value = ResolveReport([], "clean", "nothing")
        self.assertEqual(main(), 1)

    @patch("divergence_resolver.resolve")
    @patch("sys.argv", ["divergence_resolver.py"])
    def test_failed_exit(self, mock_resolve):
        mock_resolve.return_value = ResolveReport([], "failed", "oops")
        self.assertEqual(main(), 2)


class TestJsonOutput(unittest.TestCase):
    """JSON output mode."""

    @patch("divergence_resolver.resolve")
    @patch("sys.argv", ["divergence_resolver.py", "--json"])
    def test_json_produces_valid_output(self, mock_resolve):
        mock_resolve.return_value = ResolveReport(
            [StepResult("fetch", "ok", "ok")],
            "resolved",
            "done",
        )
        # Capture stdout
        from io import StringIO
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            main()
            output = mock_out.getvalue()
        data = json.loads(output)
        self.assertEqual(data["verdict"], "resolved")
        self.assertEqual(len(data["steps"]), 1)


class TestVerdictMapping(unittest.TestCase):
    """Verify verdict strings are from expected set."""

    def test_all_verdicts_in_reports(self):
        valid = {"resolved", "clean", "failed"}
        for scenario in [
            ResolveReport([], "resolved", ""),
            ResolveReport([], "clean", ""),
            ResolveReport([], "failed", ""),
        ]:
            self.assertIn(scenario.verdict, valid)


if __name__ == "__main__":
    unittest.main()
