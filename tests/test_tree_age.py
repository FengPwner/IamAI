"""Tests for iamai.tree_age — file-age distribution analysis."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest import TestCase

import sys

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.tree_age import (
    TreeAge,
    TreeAgeSummary,
    FileAge,
    _classify,
    age_report,
)


class TestClassify(TestCase):
    """Decay score classification."""

    def test_fresh(self):
        self.assertEqual(_classify(0.0), "fresh")
        self.assertEqual(_classify(0.1), "fresh")
        self.assertEqual(_classify(0.19), "fresh")

    def test_healthy(self):
        self.assertEqual(_classify(0.2), "healthy")
        self.assertEqual(_classify(0.3), "healthy")
        self.assertEqual(_classify(0.39), "healthy")

    def test_aging(self):
        self.assertEqual(_classify(0.4), "aging")
        self.assertEqual(_classify(0.5), "aging")
        self.assertEqual(_classify(0.59), "aging")

    def test_stale(self):
        self.assertEqual(_classify(0.6), "stale")
        self.assertEqual(_classify(0.7), "stale")
        self.assertEqual(_classify(0.79), "stale")

    def test_rotting(self):
        self.assertEqual(_classify(0.8), "rotting")
        self.assertEqual(_classify(0.99), "rotting")
        self.assertEqual(_classify(1.0), "rotting")


class TestFileAge(TestCase):
    """FileAge dataclass basics."""

    def test_creation(self):
        fa = FileAge(path="foo.py", last_modified=1000.0, age_days=5.0)
        self.assertEqual(fa.path, "foo.py")
        self.assertEqual(fa.lines, 0)

    def test_with_lines(self):
        fa = FileAge(path="bar.py", last_modified=2000.0, age_days=3.0, lines=42)
        self.assertEqual(fa.lines, 42)


class TestTreeAgeEmptyRepo(TestCase):
    """Behaviour on an empty or non-git directory."""

    def test_no_git(self):
        with tempfile.TemporaryDirectory() as td:
            ta = TreeAge(Path(td))
            s = ta.summary()
            self.assertEqual(s.total_files, 0)
            self.assertEqual(s.decay_score, 0.0)
            self.assertEqual(s.health, "fresh")
            self.assertEqual(s.oldest, [])
            self.assertEqual(s.newest, [])

    def test_empty_repo(self):
        """A git repo with no commits returns sensible defaults."""
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", td], capture_output=True)
            ta = TreeAge(Path(td))
            s = ta.summary()
            self.assertEqual(s.total_files, 0)
            self.assertEqual(s.health, "fresh")


class TestTreeAgeWithCommits(TestCase):
    """Integration tests with a real temp git repo."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = Path(self.tmpdir)
        subprocess.run(["git", "init", self.tmpdir], capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test"],
            capture_output=True, cwd=self.tmpdir, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            capture_output=True, cwd=self.tmpdir, check=True,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _commit_file(self, name: str, content: str = "x", msg: str = ""):
        p = self.repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        subprocess.run(["git", "add", "."], cwd=self.tmpdir, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", msg or f"add {name}"],
            cwd=self.tmpdir, capture_output=True, check=True,
        )

    def test_single_file_fresh(self):
        self._commit_file("a.py", "hello")
        ta = TreeAge(self.repo, stale_days=30, cold_days=7)
        s = ta.summary()
        self.assertEqual(s.total_files, 1)
        self.assertLess(s.median_age_days, 1.0)
        self.assertEqual(s.stale_count, 0)
        self.assertEqual(s.cold_count, 0)
        self.assertEqual(s.health, "fresh")

    def test_decay_score_zero_when_all_new(self):
        self._commit_file("a.py")
        self._commit_file("b.py")
        self._commit_file("c.py")
        ta = TreeAge(self.repo)
        s = ta.summary()
        self.assertAlmostEqual(s.decay_score, 0.0, places=2)

    def test_oldest_and_newest(self):
        self._commit_file("old.py", "old content")
        # Force both author and committer dates to the past
        env = {
            **os.environ,
            "GIT_AUTHOR_DATE": "2020-01-01T00:00:00",
            "GIT_COMMITTER_DATE": "2020-01-01T00:00:00",
        }
        subprocess.run(
            ["git", "commit", "--amend", "--date=2020-01-01T00:00:00", "--no-edit"],
            cwd=self.tmpdir, capture_output=True, check=True, env=env,
        )
        self._commit_file("new.py", "new content")
        ta = TreeAge(self.repo)
        s = ta.summary(top_n=2)
        # oldest should have much more age than newest
        self.assertGreater(s.oldest[0].age_days, 1000)
        self.assertLess(s.newest[0].age_days, 1.0)

    def test_json_serializable(self):
        """Summary can be serialized to JSON."""
        self._commit_file("x.py")
        ta = TreeAge(self.repo)
        s = ta.summary()
        import dataclasses
        d = dataclasses.asdict(s)
        # Should not raise
        text = json.dumps(d)
        self.assertIn("total_files", text)

    def test_age_report_string(self):
        self._commit_file("y.py")
        report = age_report(self.repo)
        self.assertIn("tree age:", report)
        self.assertIn("median", report)
        self.assertIn("decay", report)


class TestTreeAgeSummary(TestCase):
    """TreeAgeSummary edge cases."""

    def test_all_defaults(self):
        s = TreeAgeSummary(
            total_files=0,
            median_age_days=0.0,
            mean_age_days=0.0,
            stale_count=0,
            cold_count=0,
            stale_pct=0.0,
            cold_pct=0.0,
            decay_score=0.0,
            health="fresh",
            oldest=[],
            newest=[],
        )
        self.assertEqual(s.total_files, 0)
        self.assertEqual(s.health, "fresh")


class TestDecayTrend(TestCase):
    """decay_trend with the real IamAI repo if available."""

    def test_trend_on_real_repo(self):
        """Run against the actual repo — should not crash."""
        repo = REPO
        if not (repo / ".git").exists():
            self.skipTest("Not running inside IamAI repo")
        ta = TreeAge(repo)
        ta.load()
        trend = ta.decay_trend(commits=3)
        # Should return up to 3 entries
        self.assertLessEqual(len(trend), 3)
        for commit_hash, score in trend:
            self.assertGreater(len(commit_hash), 0)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)


class TestCaching(TestCase):
    """File ages are cached after first load."""

    def test_load_called_once(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", td], capture_output=True, check=True)
            ta = TreeAge(Path(td))
            ages1 = ta.load()
            ages2 = ta.load()
            # Same object reference — cached
            self.assertIs(ages1, ages2)


if __name__ == "__main__":
    import unittest
    unittest.main()
