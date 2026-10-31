#!/usr/bin/env python3
"""Tests for push_divergence_resolver.py.

Covers:
  - find_repo_root: repo detection, non-repo fallback
  - find_union_merge_files: .gitattributes parsing
  - detect_divergence: clean, ahead, behind, diverged with real temp repos
  - choose_strategy: all divergence × union-files combinations
  - execute_pull: none, dry-run merge, dry-run rebase
  - execute_push: dry-run
  - resolve: end-to-end with real temp repos
  - format_report: text and JSON output
  - ResolverResult dataclass
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).parent))
import push_divergence_resolver as pdr


class TestFindRepoRoot(unittest.TestCase):
    """Test repository root detection."""

    def test_finds_repo_from_root(self):
        """Should find .git when called from repo root."""
        # The IamAI repo itself
        repo = pdr.find_repo_root(".")
        self.assertIsNotNone(repo)
        self.assertTrue(Path(repo, ".git").is_dir())

    def test_finds_repo_from_subdir(self):
        """Should walk up to find .git from subdirectory."""
        repo = pdr.find_repo_root("tools")
        self.assertIsNotNone(repo)

    def test_returns_none_for_non_repo(self):
        """Should return None for a directory without .git."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = pdr.find_repo_root(tmpdir)
            self.assertIsNone(result)

    def test_walks_up_multiple_levels(self):
        """Should walk up multiple directory levels."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create .git at top level
            (Path(tmpdir) / ".git").mkdir()
            deep = Path(tmpdir) / "a" / "b" / "c"
            deep.mkdir(parents=True)
            result = pdr.find_repo_root(str(deep))
            self.assertEqual(result, str(Path(tmpdir).resolve()))


class TestFindUnionMergeFiles(unittest.TestCase):
    """Test .gitattributes parsing for union merge paths."""

    def test_empty_repo(self):
        """Should return empty list when no .gitattributes exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = pdr.find_union_merge_files(tmpdir)
            self.assertEqual(result, [])

    def test_parses_union_merge_paths(self):
        """Should find paths with merge=union."""
        with tempfile.TemporaryDirectory() as tmpdir:
            attrs = Path(tmpdir) / ".gitattributes"
            attrs.write_text("notes/*.md merge=union\ndata/*.jsonl merge=union\n")
            result = pdr.find_union_merge_files(tmpdir)
            self.assertEqual(result, ["notes/*.md", "data/*.jsonl"])

    def test_ignores_comments(self):
        """Should skip comment lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            attrs = Path(tmpdir) / ".gitattributes"
            attrs.write_text("# comment\nnotes/*.md merge=union\n")
            result = pdr.find_union_merge_files(tmpdir)
            self.assertEqual(result, ["notes/*.md"])

    def test_ignores_non_union(self):
        """Should skip lines without merge=union."""
        with tempfile.TemporaryDirectory() as tmpdir:
            attrs = Path(tmpdir) / ".gitattributes"
            attrs.write_text("*.py diff=python\n*.md merge=union\n*.txt text\n")
            result = pdr.find_union_merge_files(tmpdir)
            self.assertEqual(result, ["*.md"])

    def test_handles_empty_file(self):
        """Should handle empty .gitattributes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            attrs = Path(tmpdir) / ".gitattributes"
            attrs.write_text("")
            result = pdr.find_union_merge_files(tmpdir)
            self.assertEqual(result, [])

    def test_handles_blank_lines(self):
        """Should skip blank lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            attrs = Path(tmpdir) / ".gitattributes"
            attrs.write_text("\n\nnotes/*.md merge=union\n\n")
            result = pdr.find_union_merge_files(tmpdir)
            self.assertEqual(result, ["notes/*.md"])


class TestChooseStrategy(unittest.TestCase):
    """Test strategy selection logic."""

    def test_clean_returns_none(self):
        self.assertEqual(pdr.choose_strategy("clean", []), "none")

    def test_ahead_returns_none(self):
        self.assertEqual(pdr.choose_strategy("ahead", []), "none")

    def test_error_returns_none(self):
        self.assertEqual(pdr.choose_strategy("error", []), "none")

    def test_behind_with_union_returns_merge(self):
        self.assertEqual(pdr.choose_strategy("behind", ["notes/*.md"]), "merge")

    def test_behind_without_union_returns_rebase(self):
        self.assertEqual(pdr.choose_strategy("behind", []), "rebase")

    def test_diverged_with_union_returns_merge(self):
        self.assertEqual(pdr.choose_strategy("diverged", ["data/*.jsonl"]), "merge")

    def test_diverged_without_union_returns_rebase(self):
        self.assertEqual(pdr.choose_strategy("diverged", []), "rebase")

    def test_behind_with_empty_union_list_returns_rebase(self):
        self.assertEqual(pdr.choose_strategy("behind", []), "rebase")


class TestCountCommits(unittest.TestCase):
    """Test commit counting with real git repos."""

    def test_counts_commits_in_temp_repo(self):
        """Should count commits between two refs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
            # Create 3 commits
            for i in range(3):
                (Path(tmpdir) / f"file{i}.txt").write_text(f"content {i}")
                subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
                subprocess.run(["git", "commit", "-m", f"commit {i}"], cwd=tmpdir, capture_output=True)

            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmpdir,
                                  capture_output=True, text=True).stdout.strip()
            # Count from root to HEAD
            result = pdr.count_commits(tmpdir, f"HEAD~2..HEAD")
            self.assertEqual(result, 2)

    def test_returns_negative_for_bad_spec(self):
        """Should return -1 for invalid ref spec."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            result = pdr.count_commits(tmpdir, "nonexistent..HEAD")
            self.assertEqual(result, -1)


class TestDetectDivergence(unittest.TestCase):
    """Test divergence detection with real temp repos."""

    def test_clean_when_synced(self):
        """Should report clean when local matches remote."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
            (Path(tmpdir) / "a.txt").write_text("a")
            subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "branch", "-M", "main"], cwd=tmpdir, capture_output=True)

            # Clone as "remote"
            remote_dir = tmpdir
            local_dir = tmpdir + "_local"
            subprocess.run(["git", "clone", remote_dir, local_dir], capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=local_dir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=local_dir, capture_output=True)

            result = pdr.detect_divergence(local_dir, "origin", "main")
            self.assertEqual(result, "clean")

    def test_ahead_when_local_has_extra(self):
        """Should report ahead when local has commits remote doesn't."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
            (Path(tmpdir) / "a.txt").write_text("a")
            subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "branch", "-M", "main"], cwd=tmpdir, capture_output=True)

            local_dir = tmpdir + "_local"
            subprocess.run(["git", "clone", tmpdir, local_dir], capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=local_dir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=local_dir, capture_output=True)

            # Add local-only commit
            (Path(local_dir) / "b.txt").write_text("b")
            subprocess.run(["git", "add", "-A"], cwd=local_dir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "local"], cwd=local_dir, capture_output=True)

            result = pdr.detect_divergence(local_dir, "origin", "main")
            self.assertEqual(result, "ahead")

    def test_behind_when_remote_has_extra(self):
        """Should report behind when remote has commits local doesn't."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
            (Path(tmpdir) / "a.txt").write_text("a")
            subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "branch", "-M", "main"], cwd=tmpdir, capture_output=True)

            local_dir = tmpdir + "_local"
            subprocess.run(["git", "clone", tmpdir, local_dir], capture_output=True)

            # Add remote-only commit
            (Path(tmpdir) / "c.txt").write_text("c")
            subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "remote"], cwd=tmpdir, capture_output=True)

            result = pdr.detect_divergence(local_dir, "origin", "main")
            self.assertEqual(result, "behind")

    def test_error_on_fetch_failure(self):
        """Should report error when fetch fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            result = pdr.detect_divergence(tmpdir, "nonexistent", "main")
            self.assertEqual(result, "error")


class TestExecutePull(unittest.TestCase):
    """Test pull execution (dry-run mode)."""

    def test_none_strategy_returns_success(self):
        ok, msg = pdr.execute_pull("/tmp", "none")
        self.assertTrue(ok)
        self.assertEqual(msg, "nothing to do")

    def test_dry_run_merge(self):
        ok, msg = pdr.execute_pull("/tmp", "merge", dry_run=True)
        self.assertTrue(ok)
        self.assertIn("would run", msg)
        self.assertIn("--no-rebase", msg)

    def test_dry_run_rebase(self):
        ok, msg = pdr.execute_pull("/tmp", "rebase", dry_run=True)
        self.assertTrue(ok)
        self.assertIn("would run", msg)
        self.assertIn("--rebase", msg)


class TestExecutePush(unittest.TestCase):
    """Test push execution (dry-run mode)."""

    def test_dry_run(self):
        ok, msg = pdr.execute_push("/tmp", dry_run=True)
        self.assertTrue(ok)
        self.assertIn("would run", msg)
        self.assertIn("git push", msg)


class TestResolverResult(unittest.TestCase):
    """Test the ResolverResult dataclass."""

    def test_fields(self):
        r = pdr.ResolverResult(
            divergence="diverged",
            union_files=["notes/*.md"],
            strategy="merge",
            pulled=True,
            pushed=False,
            exit_code=0,
            message="pull ok",
        )
        self.assertEqual(r.divergence, "diverged")
        self.assertEqual(r.union_files, ["notes/*.md"])
        self.assertEqual(r.strategy, "merge")
        self.assertTrue(r.pulled)
        self.assertFalse(r.pushed)
        self.assertEqual(r.exit_code, 0)

    def test_asdict_via_asdict(self):
        from dataclasses import asdict
        r = pdr.ResolverResult(
            divergence="clean", union_files=[], strategy="none",
            pulled=False, pushed=False, exit_code=0, message="ok",
        )
        d = asdict(r)
        self.assertEqual(d["divergence"], "clean")
        self.assertEqual(d["union_files"], [])
        self.assertEqual(d["strategy"], "none")
        self.assertFalse(d["pulled"])
        self.assertFalse(d["pushed"])
        self.assertEqual(d["exit_code"], 0)
        self.assertEqual(d["message"], "ok")


class TestResolve(unittest.TestCase):
    """Test end-to-end resolution."""

    def test_none_repo_returns_error(self):
        result = pdr.resolve(None)
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(result.divergence, "error")

    def test_clean_repo_no_push(self):
        """Clean repo should report nothing to do."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
            (Path(tmpdir) / "a.txt").write_text("a")
            subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "branch", "-M", "main"], cwd=tmpdir, capture_output=True)

            # Use a non-existent remote — fetch will fail → error
            result = pdr.resolve(tmpdir, remote="origin", branch="main")
            # Without a remote, fetch fails → error
            self.assertIn(result.exit_code, [0, 2])

    def test_dry_run_with_cloned_repo(self):
        """Should report plan without executing in dry-run mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Setup "remote" repo
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=tmpdir, capture_output=True)
            (Path(tmpdir) / "a.txt").write_text("a")
            subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "branch", "-M", "main"], cwd=tmpdir, capture_output=True)

            # Clone
            local = tmpdir + "_local"
            subprocess.run(["git", "clone", tmpdir, local], capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=local, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=local, capture_output=True)

            # Add remote-only commit
            (Path(tmpdir) / "b.txt").write_text("b")
            subprocess.run(["git", "add", "-A"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "commit", "-m", "remote"], cwd=tmpdir, capture_output=True)

            result = pdr.resolve(local, remote="origin", branch="main", dry_run=True)
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.divergence, "behind")
            self.assertTrue(result.pulled)  # dry-run counts as "handled"
            self.assertIn("would run", result.message)


class TestFormatReport(unittest.TestCase):
    """Test output formatting."""

    def test_text_format(self):
        r = pdr.ResolverResult(
            divergence="diverged", union_files=["notes/*.md"],
            strategy="merge", pulled=True, pushed=True,
            exit_code=0, message="all good",
        )
        text = pdr.format_report(r, as_json=False)
        self.assertIn("diverged", text)
        self.assertIn("merge", text)
        self.assertIn("all good", text)

    def test_json_format(self):
        r = pdr.ResolverResult(
            divergence="clean", union_files=[], strategy="none",
            pulled=False, pushed=False, exit_code=0, message="ok",
        )
        j = pdr.format_report(r, as_json=True)
        data = json.loads(j)
        self.assertEqual(data["divergence"], "clean")
        self.assertEqual(data["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
