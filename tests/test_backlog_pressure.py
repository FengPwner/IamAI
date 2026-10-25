"""Tests for snippets/backlog_pressure.py — backlog pressure scoring.

Covers:
  - _classify_file for each extension bucket + unknown
  - _clamp boundary behaviour
  - _score_volume at low, high, and mid-range
  - _score_age at low, high, and mid-range
  - _score_kind with mixed file kinds and empty list
  - _verdict for each bracket
  - measure_pressure with injected files/age (no git call)
  - measure_pressure against a real git repo (integration)
  - pressure_report string format
  - edge cases: zero files, all-state, all-binary, very old files
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

# ensure snippets is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "snippets"))

from backlog_pressure import (
    _clamp,
    _classify_file,
    _score_volume,
    _score_age,
    _score_kind,
    _verdict,
    measure_pressure,
    pressure_report,
    _VOLUME_LOW,
    _VOLUME_HIGH,
    _AGE_LOW,
    _AGE_HIGH,
)


class TestClamp(unittest.TestCase):
    def test_below(self):
        self.assertEqual(_clamp(-0.5), 0.0)

    def test_above(self):
        self.assertEqual(_clamp(1.5), 1.0)

    def test_within(self):
        self.assertAlmostEqual(_clamp(0.37), 0.37)

    def test_boundary_low(self):
        self.assertEqual(_clamp(0.0), 0.0)

    def test_boundary_high(self):
        self.assertEqual(_clamp(1.0), 1.0)

    def test_custom_range(self):
        self.assertEqual(_clamp(5, lo=0, hi=10), 5)
        self.assertEqual(_clamp(-1, lo=0, hi=10), 0)
        self.assertEqual(_clamp(15, lo=0, hi=10), 10)


class TestClassifyFile(unittest.TestCase):
    def test_state_json(self):
        self.assertEqual(_classify_file("data/state.json"), "state")

    def test_state_lock(self):
        self.assertEqual(_classify_file(".git/index.lock"), "state")

    def test_state_pid(self):
        self.assertEqual(_classify_file("/tmp/writer.pid"), "state")

    def test_state_tmp(self):
        self.assertEqual(_classify_file("scratch.tmp"), "state")

    def test_data_jsonl(self):
        self.assertEqual(_classify_file("data/strokes.jsonl"), "data")

    def test_data_csv(self):
        self.assertEqual(_classify_file("export.csv"), "data")

    def test_data_log(self):
        self.assertEqual(_classify_file("output.log"), "data")

    def test_content_md(self):
        self.assertEqual(_classify_file("docs/DEVLOG.md"), "content")

    def test_content_py(self):
        self.assertEqual(_classify_file("tools/writer_loop.py"), "content")

    def test_content_yaml(self):
        self.assertEqual(_classify_file("config.yaml"), "content")

    def test_binary_png(self):
        self.assertEqual(_classify_file("img/chart.png"), "binary")

    def test_binary_pyc(self):
        self.assertEqual(_classify_file("__pycache__/foo.pyc"), "binary")

    def test_unknown_defaults_to_content(self):
        self.assertEqual(_classify_file("data.xyz"), "content")

    def test_no_extension(self):
        self.assertEqual(_classify_file("Makefile"), "content")


class TestScoreVolume(unittest.TestCase):
    def test_zero_files(self):
        self.assertEqual(_score_volume(0), 0.0)

    def test_at_low_threshold(self):
        self.assertEqual(_score_volume(_VOLUME_LOW), 0.0)

    def test_at_high_threshold(self):
        self.assertEqual(_score_volume(_VOLUME_HIGH), 1.0)

    def test_above_high(self):
        self.assertEqual(_score_volume(100), 1.0)

    def test_midpoint(self):
        mid = (_VOLUME_LOW + _VOLUME_HIGH) // 2
        score = _score_volume(mid)
        self.assertGreater(score, 0.3)
        self.assertLess(score, 0.7)

    def test_one_above_low(self):
        score = _score_volume(_VOLUME_LOW + 1)
        self.assertGreater(score, 0.0)
        self.assertLess(score, 0.1)

    def test_one_file(self):
        score = _score_volume(1)
        self.assertEqual(score, 0.0)  # ≤ _VOLUME_LOW


class TestScoreAge(unittest.TestCase):
    def test_zero_age(self):
        self.assertEqual(_score_age(0), 0.0)

    def test_at_low_threshold(self):
        self.assertEqual(_score_age(_AGE_LOW), 0.0)

    def test_at_high_threshold(self):
        self.assertEqual(_score_age(_AGE_HIGH), 1.0)

    def test_above_high(self):
        self.assertEqual(_score_age(7200), 1.0)

    def test_midpoint(self):
        mid = (_AGE_LOW + _AGE_HIGH) / 2
        score = _score_age(mid)
        self.assertGreater(score, 0.3)
        self.assertLess(score, 0.7)

    def test_just_above_low(self):
        score = _score_age(_AGE_LOW + 1)
        self.assertGreater(score, 0.0)
        self.assertLess(score, 0.01)


class TestScoreKind(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(_score_kind([]), 0.0)

    def test_all_state(self):
        files = ["a.json", "b.lock", "c.pid"]
        score = _score_kind(files)
        self.assertAlmostEqual(score, 0.2)

    def test_all_binary(self):
        files = ["a.png", "b.jpg"]
        score = _score_kind(files)
        self.assertAlmostEqual(score, 0.9)

    def test_all_content(self):
        files = ["a.md", "b.py"]
        score = _score_kind(files)
        self.assertAlmostEqual(score, 0.7)

    def test_all_data(self):
        files = ["a.jsonl", "b.csv"]
        score = _score_kind(files)
        self.assertAlmostEqual(score, 0.4)

    def test_mixed(self):
        files = ["state.json", "notes.md", "data.jsonl"]
        score = _score_kind(files)
        # (0.2 + 0.7 + 0.4) / 3 = 0.4333...
        self.assertAlmostEqual(score, (0.2 + 0.7 + 0.4) / 3, places=3)

    def test_single_file(self):
        self.assertAlmostEqual(_score_kind(["x.py"]), 0.7)


class TestVerdict(unittest.TestCase):
    def test_low(self):
        self.assertEqual(_verdict(0.0), "low")
        self.assertEqual(_verdict(0.1), "low")
        self.assertEqual(_verdict(0.19), "low")

    def test_moderate(self):
        self.assertEqual(_verdict(0.2), "moderate")
        self.assertEqual(_verdict(0.35), "moderate")
        self.assertEqual(_verdict(0.49), "moderate")

    def test_high(self):
        self.assertEqual(_verdict(0.5), "high")
        self.assertEqual(_verdict(0.65), "high")
        self.assertEqual(_verdict(0.79), "high")

    def test_critical(self):
        self.assertEqual(_verdict(0.8), "critical")
        self.assertEqual(_verdict(0.95), "critical")
        self.assertEqual(_verdict(1.0), "critical")


class TestMeasurePressure(unittest.TestCase):
    """Unit tests with injected files/age — no git or filesystem calls."""

    def test_empty_backlog(self):
        r = measure_pressure(".", files=[], oldest_age_s=0)
        self.assertEqual(r["pressure"], 0.0)
        self.assertEqual(r["verdict"], "low")
        self.assertEqual(r["volume"]["n_files"], 0)

    def test_small_fresh_backlog(self):
        # 1 content file (kind=0.7), volume=0, age=0 → pressure = 0.3*0.7 = 0.21
        r = measure_pressure(".", files=["docs/DEVLOG.md"], oldest_age_s=30)
        self.assertEqual(r["verdict"], "moderate")
        self.assertLess(r["pressure"], 0.3)

    def test_large_old_backlog(self):
        files = [f"notes/note_{i}.md" for i in range(60)]
        r = measure_pressure(".", files=files, oldest_age_s=7200)
        self.assertEqual(r["verdict"], "critical")
        self.assertGreater(r["pressure"], 0.8)

    def test_pressure_range(self):
        """pressure always in [0, 1] across sweep."""
        for n in [0, 1, 5, 10, 25, 50, 100]:
            for age in [0, 30, 300, 1800, 3600, 7200]:
                files = [f"docs/f{i}.md" for i in range(n)]
                r = measure_pressure(".", files=files, oldest_age_s=age)
                self.assertGreaterEqual(r["pressure"], 0.0)
                self.assertLessEqual(r["pressure"], 1.0)

    def test_volume_dominates_at_scale(self):
        """many files → high pressure even with young age."""
        files = [f"docs/f{i}.md" for i in range(50)]
        r = measure_pressure(".", files=files, oldest_age_s=10)
        self.assertGreater(r["pressure"], 0.3)

    def test_age_dominates_with_few_files(self):
        """few files but very old → moderate pressure."""
        r = measure_pressure(".", files=["notes/x.md"], oldest_age_s=7200)
        self.assertGreater(r["pressure"], 0.2)

    def test_state_files_lower_pressure(self):
        """state files should produce lower pressure than content files."""
        state = ["a.json", "b.lock", "c.pid"]
        content = ["a.md", "b.py", "c.txt"]
        r_state = measure_pressure(".", files=state, oldest_age_s=300)
        r_content = measure_pressure(".", files=content, oldest_age_s=300)
        self.assertLess(r_state["pressure"], r_content["pressure"])

    def test_breakdown_keys(self):
        r = measure_pressure(".", files=["a.md"], oldest_age_s=100)
        self.assertIn("volume_weight", r["breakdown"])
        self.assertIn("age_weight", r["breakdown"])
        self.assertIn("kind_weight", r["breakdown"])
        total_w = sum(r["breakdown"].values())
        self.assertAlmostEqual(total_w, 1.0)

    def test_classifications_populated(self):
        r = measure_pressure(".", files=["a.json", "b.md"], oldest_age_s=0)
        self.assertEqual(r["kind"]["classifications"]["a.json"], "state")
        self.assertEqual(r["kind"]["classifications"]["b.md"], "content")

    def test_volume_score_matches(self):
        r = measure_pressure(".", files=[f"f{i}.md" for i in range(10)], oldest_age_s=0)
        self.assertEqual(r["volume"]["n_files"], 10)
        expected = _score_volume(10)
        self.assertAlmostEqual(r["volume"]["score"], expected, places=4)

    def test_age_score_matches(self):
        r = measure_pressure(".", files=["x.md"], oldest_age_s=500)
        expected = _score_age(500)
        self.assertAlmostEqual(r["age"]["score"], expected, places=4)


class TestPressureReport(unittest.TestCase):
    def test_report_with_injected(self):
        """pressure_report calls measure_pressure; we mock via monkey-patch."""
        import snippets.backlog_pressure as bp
        original = bp.measure_pressure

        def fake_measure(path="."):
            return {
                "pressure": 0.34,
                "verdict": "moderate",
                "volume": {"n_files": 8, "score": 0.1},
                "age": {"oldest_seconds": 420.0, "score": 0.1},
                "kind": {"files": [], "classifications": {}, "score": 0.5},
                "breakdown": {},
            }

        bp.measure_pressure = fake_measure
        try:
            report = bp.pressure_report(".")
            self.assertIn("moderate", report)
            self.assertIn("0.34", report)
            self.assertIn("8 files", report)
            self.assertIn("420s", report)
        finally:
            bp.measure_pressure = original


class TestIntegration(unittest.TestCase):
    """Integration test against a real temporary git repo."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", self.tmpdir], check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.local"],
            cwd=self.tmpdir, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=self.tmpdir, check=True,
        )
        # create initial commit
        readme = os.path.join(self.tmpdir, "README.md")
        with open(readme, "w") as f:
            f.write("# test\n")
        subprocess.run(["git", "add", "."], cwd=self.tmpdir, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init", "-q"],
            cwd=self.tmpdir, check=True,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_clean_repo_low_pressure(self):
        r = measure_pressure(self.tmpdir)
        self.assertEqual(r["verdict"], "low")
        self.assertEqual(r["volume"]["n_files"], 0)
        self.assertAlmostEqual(r["pressure"], 0.0)

    def test_dirty_repo_higher_pressure(self):
        # create several uncommitted files
        for i in range(5):
            path = os.path.join(self.tmpdir, f"note_{i}.md")
            with open(path, "w") as f:
                f.write(f"content {i}\n")
        r = measure_pressure(self.tmpdir)
        self.assertGreater(r["volume"]["n_files"], 0)
        self.assertGreater(r["pressure"], 0.0)

    def test_pressure_report_returns_string(self):
        report = pressure_report(self.tmpdir)
        self.assertIsInstance(report, str)
        self.assertIn("backlog pressure:", report)

    def test_modified_tracked_file(self):
        readme = os.path.join(self.tmpdir, "README.md")
        with open(readme, "a") as f:
            f.write("appended line\n")
        r = measure_pressure(self.tmpdir)
        self.assertGreaterEqual(r["volume"]["n_files"], 1)
        self.assertIn("README.md", r["kind"]["files"])


class TestEdgeCases(unittest.TestCase):
    def test_nonexistent_repo(self):
        """Should not crash on invalid path; returns empty file list."""
        r = measure_pressure("/nonexistent/path/xyz")
        self.assertEqual(r["volume"]["n_files"], 0)

    def test_very_large_file_count(self):
        files = [f"f{i}.md" for i in range(200)]
        r = measure_pressure(".", files=files, oldest_age_s=0)
        self.assertEqual(r["volume"]["score"], 1.0)
        # 200 md files, age=0: vol=1.0, age=0.0, kind=0.7
        # pressure = 0.4*1.0 + 0.3*0.0 + 0.3*0.7 = 0.61 → high
        self.assertEqual(r["verdict"], "high")
        self.assertAlmostEqual(r["pressure"], 0.61, places=2)

    def test_very_old_age(self):
        r = measure_pressure(".", files=["x.md"], oldest_age_s=86400)
        self.assertEqual(r["age"]["score"], 1.0)

    def test_binary_files_high_kind_score(self):
        files = [f"img{i}.png" for i in range(10)]
        r = measure_pressure(".", files=files, oldest_age_s=0)
        self.assertAlmostEqual(r["kind"]["score"], 0.9)


if __name__ == "__main__":
    unittest.main()
