"""Tests for iamai.commit_atomicity — 49 test cases."""

import math
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from iamai.commit_atomicity import (
    ALL_CATEGORIES,
    FILE_CATEGORIES,
    _categorise,
    _classify,
    _shannon_entropy_normalised,
    _scatter_ratio,
    _top_directory,
    atomicity_summary,
    score_commit,
    score_recent,
)


# ── _top_directory ─────────────────────────────────────────────────────

class TestTopDirectory:
    def test_nested_path(self):
        assert _top_directory("iamai/foo/bar.py") == "iamai"

    def test_single_level(self):
        assert _top_directory("iamai/foo.py") == "iamai"

    def test_root_file(self):
        assert _top_directory("README.md") == "."

    def test_dotfile(self):
        assert _top_directory(".gitignore") == "."

    def test_hidden_directory(self):
        assert _top_directory(".github/workflows/ci.yml") == ".github"

    def test_empty_string(self):
        assert _top_directory("") == "."


# ── _categorise ────────────────────────────────────────────────────────

class TestCategorise:
    def test_code_module(self):
        assert _categorise("iamai/cadence_drift.py") == "code"

    def test_test_file(self):
        assert _categorise("tests/test_foo.py") == "tests"

    def test_data_file(self):
        assert _categorise("data/strokes.jsonl") == "data"

    def test_doc_file(self):
        assert _categorise("docs/DEVLOG.md") == "docs"

    def test_notes_file(self):
        assert _categorise("notes/history.md") == "notes"

    def test_snippets_file(self):
        assert _categorise("snippets/example.py") == "notes"

    def test_github_config(self):
        assert _categorise(".github/workflows/ci.yml") == "config"

    def test_root_file_other(self):
        assert _categorise("Makefile") == "other"

    def test_unknown_dir(self):
        assert _categorise("misc/random.txt") == "other"

    def test_tools_code(self):
        assert _categorise("tools/run_both.sh") == "code"

    def test_scripts_code(self):
        assert _categorise("scripts/cleanup.py") == "code"

    def test_agent_code(self):
        assert _categorise("agent/main.py") == "code"


# ── _shannon_entropy_normalised ────────────────────────────────────────

class TestShannonEntropyNormalised:
    def test_single_category(self):
        from collections import Counter
        assert _shannon_entropy_normalised(Counter({"a": 10})) == 0.0

    def test_two_equal(self):
        from collections import Counter
        c = Counter({"a": 50, "b": 50})
        assert _shannon_entropy_normalised(c) == pytest.approx(1.0, abs=0.01)

    def test_two_unequal(self):
        from collections import Counter
        c = Counter({"a": 90, "b": 10})
        val = _shannon_entropy_normalised(c)
        assert 0.0 < val < 1.0

    def test_empty_counter(self):
        from collections import Counter
        assert _shannon_entropy_normalised(Counter()) == 0.0

    def test_three_uniform(self):
        from collections import Counter
        c = Counter({"a": 33, "b": 33, "c": 34})
        assert _shannon_entropy_normalised(c) == pytest.approx(1.0, abs=0.02)

    def test_many_categories_uniform(self):
        from collections import Counter
        c = Counter({f"cat{i}": 10 for i in range(7)})
        assert _shannon_entropy_normalised(c) == pytest.approx(1.0, abs=0.01)

    def test_dominant_one(self):
        from collections import Counter
        c = Counter({"a": 97, "b": 1, "c": 1, "d": 1})
        val = _shannon_entropy_normalised(c)
        assert val < 0.4  # low diversity


# ── _scatter_ratio ─────────────────────────────────────────────────────

class TestScatterRatio:
    def test_all_same_dir(self):
        from collections import Counter
        assert _scatter_ratio(Counter({"iamai": 5})) == 0.0

    def test_all_different_dirs(self):
        from collections import Counter
        c = Counter({"iamai": 1, "tests": 1, "data": 1, "docs": 1})
        assert _scatter_ratio(c) == 0.75

    def test_half_half(self):
        from collections import Counter
        c = Counter({"iamai": 5, "tests": 5})
        assert _scatter_ratio(c) == 0.5

    def test_empty(self):
        from collections import Counter
        assert _scatter_ratio(Counter()) == 0.0

    def test_mostly_one_dir(self):
        from collections import Counter
        c = Counter({"iamai": 9, "tests": 1})
        assert _scatter_ratio(c) == pytest.approx(0.1, abs=1e-9)


# ── _classify ──────────────────────────────────────────────────────────

class TestClassify:
    def test_atomic_high(self):
        assert _classify(0.85) == "atomic"

    def test_atomic_boundary(self):
        assert _classify(0.70) == "atomic"

    def test_mixed_middle(self):
        assert _classify(0.55) == "mixed"

    def test_mixed_lower_boundary(self):
        assert _classify(0.40) == "mixed"

    def test_scattered_low(self):
        assert _classify(0.25) == "scattered"

    def test_scattered_zero(self):
        assert _classify(0.0) == "scattered"

    def test_perfect_one(self):
        assert _classify(1.0) == "atomic"


# ── score_commit ───────────────────────────────────────────────────────

class TestScoreCommit:
    def test_empty_files(self):
        r = score_commit([])
        assert r["atomicity_score"] == 1.0
        assert r["verdict"] == "atomic"
        assert r["file_count"] == 0

    def test_single_file(self):
        r = score_commit(["iamai/foo.py"])
        # One file = no scatter, no dir entropy, but 1 category out of 7
        # → score is very high but not literally 1.0.
        assert r["atomicity_score"] >= 0.90
        assert r["file_count"] == 1
        assert r["scatter_ratio"] == 0.0

    def test_focused_commit(self):
        """Module + its test — two dirs but still a tightly-scoped change."""
        files = ["iamai/foo.py", "tests/test_foo.py"]
        r = score_commit(files)
        # Two equal dirs raises dir_entropy and scatter; 2 categories.
        # Score lands in the mixed-to-atomic range — the important thing
        # is that it's clearly above a scattered commit.
        assert r["atomicity_score"] >= 0.35
        assert r["file_count"] == 2

    def test_scattered_commit(self):
        """Files across many dirs = low atomicity."""
        files = [
            "iamai/foo.py",
            "tests/test_bar.py",
            "data/strokes.jsonl",
            "docs/DEVLOG.md",
            "notes/history.md",
            ".github/ci.yml",
            "Makefile",
        ]
        r = score_commit(files)
        assert r["verdict"] == "scattered"
        assert r["category_mix"] >= 5

    def test_data_only(self):
        """All data files = high atomicity."""
        files = ["data/strokes.jsonl", "data/writer_state.json"]
        r = score_commit(files)
        assert r["scatter_ratio"] == 0.0
        assert r["atomicity_score"] >= 0.8

    def test_hash_and_message_preserved(self):
        r = score_commit(["foo.py"], commit_hash="abc1234", message="test commit")
        assert r["commit_hash"] == "abc1234"
        assert r["message"] == "test commit"

    def test_dominant_dir(self):
        files = ["iamai/a.py", "iamai/b.py", "iamai/c.py", "tests/t.py"]
        r = score_commit(files)
        assert r["dominant_dir"] == "iamai"

    def test_categories_touched(self):
        files = ["iamai/a.py", "tests/test_a.py", "data/x.jsonl"]
        r = score_commit(files)
        assert "code" in r["categories_touched"]
        assert "tests" in r["categories_touched"]
        assert "data" in r["categories_touched"]

    def test_score_in_range(self):
        files = ["iamai/a.py", "iamai/b.py", "tests/t.py", "data/d.jsonl"]
        r = score_commit(files)
        assert 0.0 <= r["atomicity_score"] <= 1.0

    def test_dir_entropy_range(self):
        files = ["a/b.py", "c/d.py", "e/f.py"]
        r = score_commit(files)
        assert 0.0 <= r["dir_entropy"] <= 1.0


# ── score_recent (integration, needs a git repo) ──────────────────────

class TestScoreRecent:
    def test_empty_repo(self, tmp_path):
        """A directory without git should return empty list."""
        r = score_recent(str(tmp_path), n=5)
        assert r == []

    def test_with_real_repo(self):
        """Run against the actual repo if available."""
        repo = os.environ.get("IAMAI_REPO", ".")
        reports = score_recent(repo, n=5)
        if reports:  # skip if not in repo
            assert len(reports) <= 5
            for r in reports:
                assert "atomicity_score" in r
                assert "verdict" in r
                assert 0.0 <= r["atomicity_score"] <= 1.0


# ── atomicity_summary ──────────────────────────────────────────────────

class TestAtomicitySummary:
    def test_empty_dir(self, tmp_path):
        s = atomicity_summary(str(tmp_path), n=10)
        assert s["total_commits"] == 0
        assert s["mean_score"] == 0.0

    def test_summary_fields(self):
        repo = os.environ.get("IAMAI_REPO", ".")
        s = atomicity_summary(repo, n=10)
        if s["total_commits"] > 0:
            assert 0.0 <= s["mean_score"] <= 1.0
            assert 0.0 <= s["median_score"] <= 1.0
            total_pct = s["atomic_pct"] + s["mixed_pct"] + s["scattered_pct"]
            assert total_pct == pytest.approx(1.0, abs=0.01)

    def test_details_present(self):
        repo = os.environ.get("IAMAI_REPO", ".")
        s = atomicity_summary(repo, n=5)
        if s["total_commits"] > 0:
            assert len(s["details"]) == s["total_commits"]
