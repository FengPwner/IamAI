#!/usr/bin/env python3
"""Tests for rebase_readiness.py — rebase safety checker."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# ensure tools/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from rebase_readiness import (
    ReadinessReport,
    parse_porcelain,
    check_tree,
    check_process_liveness,
    check_divergence,
    check_union_driver,
    assess,
    find_repo_root,
)


class TestParsePorcelain(unittest.TestCase):
    """Test git status --porcelain output parsing."""

    def test_clean_tree(self):
        staged, unstaged, untracked = parse_porcelain("")
        self.assertEqual(staged, [])
        self.assertEqual(unstaged, [])
        self.assertEqual(untracked, [])

    def test_staged_modification(self):
        staged, unstaged, untracked = parse_porcelain("M  data/strokes.jsonl\n")
        self.assertEqual(staged, ["data/strokes.jsonl"])
        self.assertEqual(unstaged, [])
        self.assertEqual(untracked, [])

    def test_unstaged_modification(self):
        staged, unstaged, untracked = parse_porcelain(" M data/strokes.jsonl\n")
        self.assertEqual(staged, [])
        self.assertEqual(unstaged, ["data/strokes.jsonl"])
        self.assertEqual(untracked, [])

    def test_untracked_file(self):
        staged, unstaged, untracked = parse_porcelain("?? notes/new-note.md\n")
        self.assertEqual(staged, [])
        self.assertEqual(unstaged, [])
        self.assertEqual(untracked, ["notes/new-note.md"])

    def test_both_staged_and_unstaged(self):
        """MM means file has changes in both index and working tree."""
        staged, unstaged, untracked = parse_porcelain("MM docs/DEVLOG.md\n")
        self.assertEqual(staged, ["docs/DEVLOG.md"])
        self.assertEqual(unstaged, ["docs/DEVLOG.md"])

    def test_mixed_status(self):
        raw = (
            "M  tools/new_tool.py\n"
            " M data/strokes.jsonl\n"
            "?? notes/visit-508.md\n"
            "A  tests/test_new.py\n"
        )
        staged, unstaged, untracked = parse_porcelain(raw)
        self.assertEqual(sorted(staged), ["tests/test_new.py", "tools/new_tool.py"])
        self.assertEqual(unstaged, ["data/strokes.jsonl"])
        self.assertEqual(untracked, ["notes/visit-508.md"])

    def test_renamed_file(self):
        """Renamed files show as 'R  old -> new'."""
        staged, unstaged, untracked = parse_porcelain("R  old_name.py -> new_name.py\n")
        self.assertEqual(staged, ["new_name.py"])

    def test_short_lines_skipped(self):
        """Lines shorter than 4 chars are ignored (malformed output)."""
        staged, unstaged, untracked = parse_porcelain("M\nAB\n")
        self.assertEqual(staged, [])
        self.assertEqual(unstaged, [])

    def test_deleted_file(self):
        staged, unstaged, untracked = parse_porcelain(" D removed_file.py\n")
        self.assertEqual(unstaged, ["removed_file.py"])

    def test_new_file_staged(self):
        staged, unstaged, untracked = parse_porcelain("A  new_file.py\n")
        self.assertEqual(staged, ["new_file.py"])


class TestCheckProcessLiveness(unittest.TestCase):
    """Test writer/batch process detection via pidfiles."""

    def test_no_pidfiles(self):
        """When no pidfiles exist, nothing is running."""
        with patch("rebase_readiness.Path") as mock_path_cls:
            mock_path = MagicMock()
            mock_path.exists.return_value = False
            mock_path_cls.return_value = mock_path
            result = check_process_liveness("qwen")
            self.assertFalse(result["writer_running"])
            self.assertFalse(result["batch_running"])
            self.assertIsNone(result["writer_pid"])
            self.assertIsNone(result["batch_pid"])

    def test_stale_pidfile(self):
        """When pidfile exists but process is dead, report not running."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pid", delete=False) as f:
            f.write("999999")  # hopefully no such PID
            pidpath = f.name
        try:
            with patch("rebase_readiness.Path") as mock_path_cls:
                mock_path = MagicMock()
                mock_path.exists.return_value = True
                mock_path.read_text.return_value = "999999"
                mock_path_cls.return_value = mock_path
                result = check_process_liveness("qwen")
                self.assertFalse(result["writer_running"])
        finally:
            os.unlink(pidpath)


class TestCheckDivergence(unittest.TestCase):
    """Test divergence detection between local and remote branches."""

    def test_in_sync(self):
        """When local and remote point to the same commit."""
        with patch("rebase_readiness._run_git") as mock_git:
            mock_git.side_effect = [
                (0, "0\t0\n", ""),  # rev-list --count
                (0, "abc1234\n", ""),  # merge-base
            ]
            local, remote, ancestor = check_divergence("/fake/repo", "origin/main")
            self.assertEqual(local, 0)
            self.assertEqual(remote, 0)
            self.assertEqual(ancestor, "abc1234")

    def test_local_ahead(self):
        """When local has commits that remote doesn't."""
        with patch("rebase_readiness._run_git") as mock_git:
            mock_git.side_effect = [
                (0, "3\t0\n", ""),
                (0, "def5678\n", ""),
            ]
            local, remote, ancestor = check_divergence("/fake/repo")
            self.assertEqual(local, 3)
            self.assertEqual(remote, 0)

    def test_remote_ahead(self):
        """When remote has commits that local doesn't."""
        with patch("rebase_readiness._run_git") as mock_git:
            mock_git.side_effect = [
                (0, "0\t2\n", ""),
                (0, "aaa1111\n", ""),
            ]
            local, remote, ancestor = check_divergence("/fake/repo")
            self.assertEqual(local, 0)
            self.assertEqual(remote, 2)

    def test_diverged(self):
        """When both local and remote have new commits."""
        with patch("rebase_readiness._run_git") as mock_git:
            mock_git.side_effect = [
                (0, "5\t1\n", ""),
                (0, "bbb2222\n", ""),
            ]
            local, remote, ancestor = check_divergence("/fake/repo")
            self.assertEqual(local, 5)
            self.assertEqual(remote, 1)

    def test_git_failure(self):
        """When git command fails, return zeros."""
        with patch("rebase_readiness._run_git") as mock_git:
            mock_git.return_value = (128, "", "fatal: not a git repo")
            local, remote, ancestor = check_divergence("/fake/repo")
            self.assertEqual(local, 0)
            self.assertEqual(remote, 0)
            self.assertEqual(ancestor, "")


class TestCheckUnionDriver(unittest.TestCase):
    """Test merge driver configuration check."""

    def test_configured(self):
        with patch("rebase_readiness._run_git") as mock_git:
            mock_git.return_value = (0, "git merge-file --union %A %O %B\n", "")
            self.assertTrue(check_union_driver("/fake/repo"))

    def test_not_configured(self):
        with patch("rebase_readiness._run_git") as mock_git:
            mock_git.return_value = (1, "", "error: key not found")
            self.assertFalse(check_union_driver("/fake/repo"))

    def test_wrong_driver(self):
        with patch("rebase_readiness._run_git") as mock_git:
            mock_git.return_value = (0, "some-other-driver\n", "")
            self.assertFalse(check_union_driver("/fake/repo"))


class TestAssess(unittest.TestCase):
    """Test the main assess() function integration."""

    def test_not_a_repo(self):
        """When called outside a git repo, returns verdict 4."""
        with patch("rebase_readiness.find_repo_root", return_value=None):
            report = assess(repo=None)
            self.assertEqual(report.verdict, 4)
            self.assertIn("not a git repo", report.hint)

    def test_clean_idle_repo(self):
        """Happy path: clean tree, no processes, in sync."""
        with patch("rebase_readiness.find_repo_root", return_value="/fake"), \
             patch("rebase_readiness.check_tree", return_value=([], [], [])), \
             patch("rebase_readiness.check_process_liveness",
                   return_value={"writer_running": False, "writer_pid": None,
                                 "batch_running": False, "batch_pid": None}), \
             patch("rebase_readiness.check_divergence", return_value=(0, 0, "abc")), \
             patch("rebase_readiness.check_union_driver", return_value=True):
            report = assess(repo="/fake")
            self.assertEqual(report.verdict, 0)
            self.assertTrue(report.tree_clean)
            self.assertFalse(report.writer_running)
            self.assertEqual(report.hint, "safe to rebase")

    def test_dirty_tree(self):
        """Unstaged changes → verdict 1."""
        with patch("rebase_readiness.find_repo_root", return_value="/fake"), \
             patch("rebase_readiness.check_tree",
                   return_value=([], ["data/strokes.jsonl"], [])), \
             patch("rebase_readiness.check_process_liveness",
                   return_value={"writer_running": False, "writer_pid": None,
                                 "batch_running": False, "batch_pid": None}), \
             patch("rebase_readiness.check_divergence", return_value=(0, 0, "abc")), \
             patch("rebase_readiness.check_union_driver", return_value=False):
            report = assess(repo="/fake")
            self.assertEqual(report.verdict, 1)
            self.assertFalse(report.tree_clean)

    def test_processes_running(self):
        """Writer running with clean tree → verdict 2."""
        with patch("rebase_readiness.find_repo_root", return_value="/fake"), \
             patch("rebase_readiness.check_tree", return_value=([], [], [])), \
             patch("rebase_readiness.check_process_liveness",
                   return_value={"writer_running": True, "writer_pid": 1234,
                                 "batch_running": True, "batch_pid": 5678}), \
             patch("rebase_readiness.check_divergence", return_value=(2, 1, "def")), \
             patch("rebase_readiness.check_union_driver", return_value=True):
            report = assess(repo="/fake")
            self.assertEqual(report.verdict, 2)
            self.assertTrue(report.writer_running)
            self.assertEqual(report.writer_pid, 1234)

    def test_dirty_and_running(self):
        """Dirty tree AND running processes → verdict 3."""
        with patch("rebase_readiness.find_repo_root", return_value="/fake"), \
             patch("rebase_readiness.check_tree",
                   return_value=(["a.py"], ["b.py"], ["c.md"])), \
             patch("rebase_readiness.check_process_liveness",
                   return_value={"writer_running": True, "writer_pid": 111,
                                 "batch_running": False, "batch_pid": None}), \
             patch("rebase_readiness.check_divergence", return_value=(0, 0, "abc")), \
             patch("rebase_readiness.check_union_driver", return_value=True):
            report = assess(repo="/fake")
            self.assertEqual(report.verdict, 3)
            self.assertEqual(len(report.staged_files), 1)
            self.assertEqual(len(report.unstaged_files), 1)


class TestReadinessReportSerialization(unittest.TestCase):
    """Test JSON serialization of ReadinessReport."""

    def test_to_dict(self):
        report = ReadinessReport(
            repo_path="/tmp/test",
            tree_clean=True,
            writer_running=False,
            verdict=0,
            hint="safe to rebase",
        )
        d = report.to_dict()
        self.assertIsInstance(d, dict)
        self.assertTrue(d["tree_clean"])
        self.assertEqual(d["verdict"], 0)
        # should be JSON-serializable
        json_str = json.dumps(d)
        self.assertIn("safe to rebase", json_str)

    def test_full_report_json(self):
        report = ReadinessReport(
            repo_path="/home/user/IamAI",
            tree_clean=False,
            staged_files=["tools/new.py"],
            unstaged_files=["data/strokes.jsonl", "notes/history.md"],
            untracked_files=["notes/visit-508.md"],
            writer_running=True,
            writer_pid=3487,
            batch_running=True,
            batch_pid=3488,
            writer_id="qwen",
            local_ahead=5,
            remote_ahead=1,
            common_ancestor="abc123",
            union_driver_configured=True,
            remote_ref="origin/main",
            verdict=3,
            hint="dirty tree AND processes running",
        )
        d = report.to_dict()
        parsed = json.loads(json.dumps(d))
        self.assertEqual(parsed["writer_pid"], 3487)
        self.assertEqual(len(parsed["unstaged_files"]), 2)
        self.assertEqual(parsed["verdict"], 3)


if __name__ == "__main__":
    unittest.main()
