#!/usr/bin/env python3
"""Tests for repo_nutrition_label — 45 test cases."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.repo_nutrition_label import (  # noqa: E402
    NutritionLabel,
    _classify_file,
    _commit_count,
    _count_lines,
    _days_since_last_commit,
    _density_score,
    _doc_balance_score,
    _find_orphans,
    _freshness_score,
    _fibre_score,
    _grade,
    _orphan_score,
    _repo_age_days,
    _run,
    _source_module_name,
    _tracked_files,
    format_label,
    generate_label,
    quick_label,
)


# ---------------------------------------------------------------------------
# _classify_file
# ---------------------------------------------------------------------------

class TestClassifyFile(unittest.TestCase):
    """Unit tests for file classification."""

    def test_python_source(self):
        self.assertEqual(_classify_file("iamai/writer.py"), "source")

    def test_python_test_by_path(self):
        self.assertEqual(_classify_file("tests/test_writer.py"), "test")

    def test_python_test_by_prefix(self):
        self.assertEqual(_classify_file("iamai/test_writer.py"), "test")

    def test_markdown_doc(self):
        self.assertEqual(_classify_file("docs/README.md"), "doc")

    def test_rst_doc(self):
        self.assertEqual(_classify_file("docs/api.rst"), "doc")

    def test_json_data(self):
        self.assertEqual(_classify_file("data/strokes.jsonl"), "data")

    def test_csv_data(self):
        self.assertEqual(_classify_file("data/metrics.csv"), "data")

    def test_yaml_data(self):
        self.assertEqual(_classify_file("config/settings.yaml"), "data")

    def test_unknown_extension(self):
        self.assertIsNone(_classify_file("Makefile"))

    def test_sh_script(self):
        self.assertIsNone(_classify_file("tools/run.sh"))

    def test_data_in_doc_path_not_double_counted(self):
        # .md files under data/ are excluded from docs (data/ takes precedence)
        result = _classify_file("data/notes.md")
        self.assertIsNone(result)

    def test_json_source_config(self):
        self.assertEqual(_classify_file("package.json"), "data")


# ---------------------------------------------------------------------------
# _source_module_name / _find_orphans
# ---------------------------------------------------------------------------

class TestModuleName(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(_source_module_name("iamai/writer.py"), "writer")

    def test_nested(self):
        self.assertEqual(_source_module_name("src/core/parser.py"), "parser")


class TestFindOrphans(unittest.TestCase):
    def test_no_orphans(self):
        sources = ["iamai/foo.py", "iamai/bar.py"]
        tests = ["tests/test_foo.py", "tests/test_bar.py"]
        self.assertEqual(_find_orphans(sources, tests), [])

    def test_one_orphan(self):
        sources = ["iamai/foo.py", "iamai/bar.py"]
        tests = ["tests/test_foo.py"]
        orphans = _find_orphans(sources, tests)
        self.assertIn("bar", orphans)
        self.assertEqual(len(orphans), 1)

    def test_all_orphans(self):
        sources = ["iamai/a.py", "iamai/b.py", "iamai/c.py"]
        tests = []
        orphans = _find_orphans(sources, tests)
        self.assertEqual(len(orphans), 3)

    def test_empty_sources(self):
        self.assertEqual(_find_orphans([], ["tests/test_x.py"]), [])

    def test_deduplication(self):
        sources = ["iamai/foo.py", "lib/foo.py"]
        tests = []
        orphans = _find_orphans(sources, tests)
        # both map to stem "foo" — should be deduped
        self.assertEqual(len(orphans), 1)


# ---------------------------------------------------------------------------
# Score functions
# ---------------------------------------------------------------------------

class TestFibreScore(unittest.TestCase):
    def test_zero_ratio(self):
        self.assertEqual(_fibre_score(0.0), 0.0)

    def test_full_ratio(self):
        self.assertEqual(_fibre_score(1.0), 100.0)

    def test_over_ratio(self):
        # should cap at 100
        self.assertEqual(_fibre_score(2.5), 100.0)

    def test_half_ratio(self):
        self.assertAlmostEqual(_fibre_score(0.5), 50.0)


class TestOrphanScore(unittest.TestCase):
    def test_no_orphans(self):
        self.assertEqual(_orphan_score(0.0), 100.0)

    def test_all_orphans(self):
        self.assertEqual(_orphan_score(100.0), 0.0)

    def test_half_orphans(self):
        self.assertAlmostEqual(_orphan_score(50.0), 50.0)


class TestFreshnessScore(unittest.TestCase):
    def test_zero_days(self):
        self.assertEqual(_freshness_score(0.0), 100.0)

    def test_negative_days(self):
        self.assertEqual(_freshness_score(-1.0), 100.0)

    def test_one_day(self):
        score = _freshness_score(1.0)
        self.assertGreater(score, 50.0)
        self.assertLess(score, 100.0)

    def test_old_repo(self):
        score = _freshness_score(100.0)
        self.assertLess(score, 20.0)

    def test_monotonic_decay(self):
        s1 = _freshness_score(1.0)
        s2 = _freshness_score(10.0)
        s3 = _freshness_score(100.0)
        self.assertGreater(s1, s2)
        self.assertGreater(s2, s3)


class TestDocBalanceScore(unittest.TestCase):
    def test_ideal_range_low(self):
        self.assertEqual(_doc_balance_score(10.0), 100.0)

    def test_ideal_range_high(self):
        self.assertEqual(_doc_balance_score(25.0), 100.0)

    def test_ideal_range_mid(self):
        self.assertEqual(_doc_balance_score(20.0), 100.0)

    def test_too_few_docs(self):
        score = _doc_balance_score(5.0)
        self.assertLess(score, 100.0)
        self.assertGreater(score, 0.0)

    def test_zero_docs(self):
        self.assertEqual(_doc_balance_score(0.0), 0.0)

    def test_too_many_docs(self):
        score = _doc_balance_score(50.0)
        self.assertLess(score, 100.0)
        self.assertGreaterEqual(score, 0.0)

    def test_negative(self):
        self.assertEqual(_doc_balance_score(-5.0), 0.0)


class TestDensityScore(unittest.TestCase):
    def test_zero_density(self):
        self.assertEqual(_density_score(0.0), 0.0)

    def test_full_density(self):
        self.assertEqual(_density_score(2.0), 100.0)

    def test_over_density(self):
        self.assertEqual(_density_score(10.0), 100.0)

    def test_half_density(self):
        self.assertAlmostEqual(_density_score(1.0), 50.0)


# ---------------------------------------------------------------------------
# _grade
# ---------------------------------------------------------------------------

class TestGrade(unittest.TestCase):
    def test_grade_a(self):
        self.assertEqual(_grade(85), "A")
        self.assertEqual(_grade(100), "A")

    def test_grade_b(self):
        self.assertEqual(_grade(70), "B")
        self.assertEqual(_grade(84.9), "B")

    def test_grade_c(self):
        self.assertEqual(_grade(55), "C")
        self.assertEqual(_grade(69.9), "C")

    def test_grade_d(self):
        self.assertEqual(_grade(40), "D")
        self.assertEqual(_grade(54.9), "D")

    def test_grade_f(self):
        self.assertEqual(_grade(0), "F")
        self.assertEqual(_grade(39.9), "F")

    def test_boundary_values(self):
        """Exact boundaries go to the higher grade."""
        self.assertEqual(_grade(85.0), "A")
        self.assertEqual(_grade(70.0), "B")
        self.assertEqual(_grade(55.0), "C")
        self.assertEqual(_grade(40.0), "D")


# ---------------------------------------------------------------------------
# _run helper
# ---------------------------------------------------------------------------

class TestRun(unittest.TestCase):
    def test_successful_command(self):
        result = _run(["echo", "hello"])
        self.assertEqual(result, "hello")

    def test_failed_command(self):
        result = _run(["false"])
        self.assertEqual(result, "")

    def test_nonexistent_command(self):
        result = _run(["nonexistent_command_xyz_12345"])
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# _count_lines
# ---------------------------------------------------------------------------

class TestCountLines(unittest.TestCase):
    def test_count_real_files(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            f1 = repo / "a.txt"
            f1.write_text("line1\nline2\nline3\n")
            f2 = repo / "b.txt"
            f2.write_text("x\ny\n")
            self.assertEqual(_count_lines(repo, ["a.txt", "b.txt"]), 5)

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self.assertEqual(_count_lines(repo, ["nonexistent.txt"]), 0)

    def test_empty_list(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(_count_lines(Path(td), []), 0)


# ---------------------------------------------------------------------------
# format_label
# ---------------------------------------------------------------------------

class TestFormatLabel(unittest.TestCase):
    def test_contains_key_sections(self):
        label = NutritionLabel(
            serving_size=100,
            serving_date="2026-11-10",
            source_g=5000,
            test_g=3000,
            doc_g=1000,
            data_g=500,
            total_lines=9500,
            test_fibre_ratio=0.6,
            orphan_pct=25.0,
            freshness_days=0.5,
            doc_sugar_pct=10.5,
            commit_density=3.2,
            fibre_score=60.0,
            orphan_score=75.0,
            freshness_score=90.0,
            doc_balance_score=100.0,
            density_score=100.0,
            composite_score=82.5,
            health_grade="B",
            source_files=50,
            test_files=30,
            doc_files=10,
            data_files=10,
        )
        text = format_label(label)
        self.assertIn("Nutrition Facts", text)
        self.assertIn("100 files", text)
        self.assertIn("2026-11-10", text)
        self.assertIn("protein", text)
        self.assertIn("fibre", text)
        self.assertIn("carbs", text)
        self.assertIn("fat", text)
        self.assertIn("B", text)
        self.assertIn("82.5", text)

    def test_format_empty_label(self):
        label = NutritionLabel()
        text = format_label(label)
        self.assertIn("Nutrition Facts", text)
        self.assertIn("0 files", text)
        self.assertIn("F", text)

    def test_format_orphan_detail(self):
        label = NutritionLabel(orphan_pct=42.3)
        text = format_label(label)
        self.assertIn("42.3%", text)


# ---------------------------------------------------------------------------
# generate_label — integration (uses real repo)
# ---------------------------------------------------------------------------

class TestGenerateLabelIntegration(unittest.TestCase):
    """Run against the actual IamAI repo; smoke tests."""

    def test_returns_label(self):
        label = generate_label(str(REPO))
        self.assertIsInstance(label, NutritionLabel)
        self.assertGreater(label.serving_size, 0)
        self.assertIn(label.health_grade, ("A", "B", "C", "D", "F"))

    def test_has_source(self):
        label = generate_label(str(REPO))
        self.assertGreater(label.source_g, 0)

    def test_has_tests(self):
        label = generate_label(str(REPO))
        self.assertGreater(label.test_g, 0)

    def test_composite_bounded(self):
        label = generate_label(str(REPO))
        self.assertGreaterEqual(label.composite_score, 0.0)
        self.assertLessEqual(label.composite_score, 100.0)

    def test_grade_matches_composite(self):
        label = generate_label(str(REPO))
        expected = _grade(label.composite_score)
        self.assertEqual(label.health_grade, expected)


# ---------------------------------------------------------------------------
# quick_label
# ---------------------------------------------------------------------------

class TestQuickLabel(unittest.TestCase):
    def test_returns_string(self):
        result = quick_label(str(REPO))
        self.assertIsInstance(result, str)
        self.assertIn("Nutrition Facts", result)


# ---------------------------------------------------------------------------
# NutritionLabel dataclass
# ---------------------------------------------------------------------------

class TestNutritionLabelDataclass(unittest.TestCase):
    def test_defaults(self):
        label = NutritionLabel()
        self.assertEqual(label.serving_size, 0)
        self.assertEqual(label.health_grade, "F")
        self.assertEqual(label.orphan_modules, [])
        self.assertEqual(label.composite_score, 0.0)

    def test_orphan_modules_independent(self):
        a = NutritionLabel()
        b = NutritionLabel()
        a.orphan_modules.append("foo")
        self.assertEqual(b.orphan_modules, [])


if __name__ == "__main__":
    unittest.main()
