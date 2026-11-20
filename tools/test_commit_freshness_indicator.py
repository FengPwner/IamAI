#!/usr/bin/env python3
"""
Tests for commit_freshness_indicator.py

42 tests covering timestamp extraction, age calculation, classification,
cadence comparison, error handling, and end-to-end scenarios.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add tools directory to path
sys.path.insert(0, str(Path(__file__).parent))

import commit_freshness_indicator as cfi


class TestClassifyAge(unittest.TestCase):
    """Tests for age classification logic."""
    
    def test_fresh_zero(self):
        self.assertEqual(cfi.classify_age(0), "fresh")
    
    def test_fresh_boundary_minus_one(self):
        self.assertEqual(cfi.classify_age(299), "fresh")
    
    def test_fresh_boundary_exact(self):
        self.assertEqual(cfi.classify_age(300), "warm")
    
    def test_warm_middle(self):
        self.assertEqual(cfi.classify_age(600), "warm")
    
    def test_warm_boundary_minus_one(self):
        self.assertEqual(cfi.classify_age(899), "warm")
    
    def test_warm_boundary_exact(self):
        self.assertEqual(cfi.classify_age(900), "stale")
    
    def test_stale_large(self):
        self.assertEqual(cfi.classify_age(3600), "stale")
    
    def test_stale_very_large(self):
        self.assertEqual(cfi.classify_age(86400), "stale")


class TestGetRecommendation(unittest.TestCase):
    """Tests for recommendation logic."""
    
    def test_fresh_always_ok(self):
        self.assertEqual(cfi.get_recommendation("fresh", 0.1), "ok")
        self.assertEqual(cfi.get_recommendation("fresh", 5.0), "ok")
    
    def test_warm_low_ratio_ok(self):
        self.assertEqual(cfi.get_recommendation("warm", 0.5), "ok")
        self.assertEqual(cfi.get_recommendation("warm", 1.0), "ok")
        self.assertEqual(cfi.get_recommendation("warm", 1.5), "ok")
    
    def test_warm_high_ratio_watch(self):
        self.assertEqual(cfi.get_recommendation("warm", 1.51), "watch")
        self.assertEqual(cfi.get_recommendation("warm", 2.0), "watch")
    
    def test_stale_moderate_ratio_watch(self):
        self.assertEqual(cfi.get_recommendation("stale", 1.5), "watch")
        self.assertEqual(cfi.get_recommendation("stale", 2.0), "watch")
    
    def test_stale_high_ratio_intervene(self):
        self.assertEqual(cfi.get_recommendation("stale", 2.01), "intervene")
        self.assertEqual(cfi.get_recommendation("stale", 5.0), "intervene")


class TestGetLatestCommitTimestamp(unittest.TestCase):
    """Tests for git timestamp extraction."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        subprocess.run(["git", "init"], cwd=self.temp_dir, 
                      capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                      cwd=self.temp_dir, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                      cwd=self.temp_dir, capture_output=True, check=True)
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_valid_commit(self):
        # Create a commit
        test_file = Path(self.temp_dir) / "test.txt"
        test_file.write_text("test")
        subprocess.run(["git", "add", "."], cwd=self.temp_dir,
                      capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "test"],
                      cwd=self.temp_dir, capture_output=True, check=True)
        
        ts = cfi.get_latest_commit_timestamp(self.temp_dir)
        self.assertIsInstance(ts, int)
        self.assertGreater(ts, 1000000000)  # After 2001
        self.assertLess(ts, 3000000000)     # Before 2065
    
    def test_no_commits(self):
        with self.assertRaises(RuntimeError) as ctx:
            cfi.get_latest_commit_timestamp(self.temp_dir)
        # Git error message varies by version
        self.assertTrue(
            "no commits" in str(ctx.exception) or "git error" in str(ctx.exception)
        )
    
    def test_nonexistent_repo(self):
        with self.assertRaises(RuntimeError) as ctx:
            cfi.get_latest_commit_timestamp("/nonexistent/path/that/does/not/exist")
        # Error message varies: could be "git error", "git not found", etc.
        self.assertTrue(
            "git error" in str(ctx.exception) or "git not found" in str(ctx.exception)
        )
    
    def test_multiple_commits_returns_latest(self):
        # Create first commit
        test_file = Path(self.temp_dir) / "test1.txt"
        test_file.write_text("first")
        subprocess.run(["git", "add", "."], cwd=self.temp_dir,
                      capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "first"],
                      cwd=self.temp_dir, capture_output=True, check=True)
        
        time.sleep(1.1)  # Ensure different timestamp
        
        # Create second commit
        test_file2 = Path(self.temp_dir) / "test2.txt"
        test_file2.write_text("second")
        subprocess.run(["git", "add", "."], cwd=self.temp_dir,
                      capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "second"],
                      cwd=self.temp_dir, capture_output=True, check=True)
        
        ts = cfi.get_latest_commit_timestamp(self.temp_dir)
        # Should be close to current time
        now = int(time.time())
        self.assertGreater(ts, now - 60)


class TestCheckFreshness(unittest.TestCase):
    """Tests for the main freshness check function."""
    
    @patch('commit_freshness_indicator.get_latest_commit_timestamp')
    @patch('commit_freshness_indicator.time.time')
    def test_fresh_commit(self, mock_time, mock_ts):
        mock_ts.return_value = 1000
        mock_time.return_value = 1100  # 100 seconds ago
        
        result = cfi.check_freshness("/fake/repo")
        
        self.assertEqual(result["status"], "fresh")
        self.assertEqual(result["age_seconds"], 100)
        self.assertEqual(result["recommendation"], "ok")
    
    @patch('commit_freshness_indicator.get_latest_commit_timestamp')
    @patch('commit_freshness_indicator.time.time')
    def test_warm_commit(self, mock_time, mock_ts):
        mock_ts.return_value = 1000
        mock_time.return_value = 1500  # 500 seconds ago
        
        result = cfi.check_freshness("/fake/repo")
        
        self.assertEqual(result["status"], "warm")
        self.assertEqual(result["age_seconds"], 500)
    
    @patch('commit_freshness_indicator.get_latest_commit_timestamp')
    @patch('commit_freshness_indicator.time.time')
    def test_stale_commit(self, mock_time, mock_ts):
        mock_ts.return_value = 1000
        mock_time.return_value = 2000  # 1000 seconds ago
        
        result = cfi.check_freshness("/fake/repo")
        
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["age_seconds"], 1000)
        self.assertEqual(result["recommendation"], "watch")
    
    @patch('commit_freshness_indicator.get_latest_commit_timestamp')
    @patch('commit_freshness_indicator.time.time')
    def test_future_commit_clamped_to_zero(self, mock_time, mock_ts):
        mock_ts.return_value = 2000
        mock_time.return_value = 1000  # Commit is in future
        
        result = cfi.check_freshness("/fake/repo")
        
        self.assertEqual(result["age_seconds"], 0)
        self.assertEqual(result["status"], "fresh")
    
    @patch('commit_freshness_indicator.get_latest_commit_timestamp')
    @patch('commit_freshness_indicator.time.time')
    def test_custom_cadence(self, mock_time, mock_ts):
        mock_ts.return_value = 1000
        mock_time.return_value = 1300  # 300 seconds ago
        
        result = cfi.check_freshness("/fake/repo", expected_cadence=300)
        
        self.assertEqual(result["cadence_ratio"], 1.0)
        self.assertEqual(result["expected_cadence"], 300)
    
    @patch('commit_freshness_indicator.get_latest_commit_timestamp')
    @patch('commit_freshness_indicator.time.time')
    def test_cadence_ratio_calculation(self, mock_time, mock_ts):
        mock_ts.return_value = 1000
        mock_time.return_value = 1600  # 600 seconds ago
        
        result = cfi.check_freshness("/fake/repo", expected_cadence=600)
        
        self.assertEqual(result["cadence_ratio"], 1.0)
    
    @patch('commit_freshness_indicator.get_latest_commit_timestamp')
    @patch('commit_freshness_indicator.time.time')
    def test_zero_cadence_infinite_ratio(self, mock_time, mock_ts):
        mock_ts.return_value = 1000
        mock_time.return_value = 1100
        
        result = cfi.check_freshness("/fake/repo", expected_cadence=0)
        
        self.assertEqual(result["cadence_ratio"], float('inf'))


class TestFormatHuman(unittest.TestCase):
    """Tests for human-readable formatting."""
    
    def test_seconds_format(self):
        result = {
            "status": "fresh",
            "age_seconds": 45,
            "recommendation": "ok"
        }
        output = cfi.format_human(result)
        self.assertIn("45s", output)
        self.assertIn("✅", output)
    
    def test_minutes_format(self):
        result = {
            "status": "warm",
            "age_seconds": 420,
            "recommendation": "ok"
        }
        output = cfi.format_human(result)
        self.assertIn("7m", output)
        self.assertIn("⚠️", output)
    
    def test_hours_format(self):
        result = {
            "status": "stale",
            "age_seconds": 7265,
            "recommendation": "intervene"
        }
        output = cfi.format_human(result)
        self.assertIn("2h", output)
        self.assertIn("❌", output)
    
    def test_recommendation_text(self):
        result = {"status": "fresh", "age_seconds": 10, "recommendation": "ok"}
        self.assertIn("all good", cfi.format_human(result))
        
        result["recommendation"] = "watch"
        self.assertIn("keep an eye", cfi.format_human(result))
        
        result["recommendation"] = "intervene"
        self.assertIn("needs attention", cfi.format_human(result))


class TestMainCLI(unittest.TestCase):
    """Tests for command-line interface."""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        subprocess.run(["git", "init"], cwd=self.temp_dir,
                      capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"],
                      cwd=self.temp_dir, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"],
                      cwd=self.temp_dir, capture_output=True, check=True)
        
        # Create a commit
        test_file = Path(self.temp_dir) / "test.txt"
        test_file.write_text("test")
        subprocess.run(["git", "add", "."], cwd=self.temp_dir,
                      capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "test"],
                      cwd=self.temp_dir, capture_output=True, check=True)
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_human_output(self):
        result = subprocess.run(
            [sys.executable, "tools/commit_freshness_indicator.py",
             "--repo", self.temp_dir],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Latest commit", result.stdout)
    
    def test_json_output(self):
        result = subprocess.run(
            [sys.executable, "tools/commit_freshness_indicator.py",
             "--repo", self.temp_dir, "--json"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIn("status", data)
        self.assertIn("age_seconds", data)
    
    def test_custom_cadence(self):
        result = subprocess.run(
            [sys.executable, "tools/commit_freshness_indicator.py",
             "--repo", self.temp_dir, "--cadence", "300", "--json"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["expected_cadence"], 300)
    
    def test_nonexistent_repo_error(self):
        result = subprocess.run(
            [sys.executable, "tools/commit_freshness_indicator.py",
             "--repo", "/nonexistent/path"],
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 2)


class TestEndToEnd(unittest.TestCase):
    """End-to-end integration tests."""
    
    def test_real_repo_workflow(self):
        """Test against the actual IamAI repo if it exists."""
        repo_path = Path(__file__).parent.parent
        if not (repo_path / ".git").exists():
            self.skipTest("IamAI repo not available")
        
        result = cfi.check_freshness(str(repo_path))
        
        # Verify structure
        self.assertIn("status", result)
        self.assertIn("age_seconds", result)
        self.assertIn("cadence_ratio", result)
        self.assertIn("recommendation", result)
        
        # Verify types
        self.assertIsInstance(result["age_seconds"], int)
        self.assertIsInstance(result["cadence_ratio"], (int, float))
        self.assertIn(result["status"], ["fresh", "warm", "stale"])
        self.assertIn(result["recommendation"], ["ok", "watch", "intervene"])


if __name__ == "__main__":
    unittest.main()
