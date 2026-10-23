"""Tests for iamai.caretaker_workload — workload classification and grading."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.caretaker_workload import (
    WorkloadReport,
    _CARETAKER_RE,
    _CATCHUP_RE,
    _AUTO_CONTENT_RE,
    _GRADE_THRESHOLDS,
    _GRADE_MANUAL,
    _classify_grade,
    classify_commit,
    workload_report,
    workload_summary,
)


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

class TestPatterns:
    """Verify the regex patterns match expected commit messages."""

    def test_caretaker_pattern_basic(self):
        assert _CARETAKER_RE.match("caretaker visit 311: add module")

    def test_caretaker_pattern_single_digit(self):
        assert _CARETAKER_RE.match("caretaker visit 1: first check")

    def test_caretaker_pattern_case_insensitive(self):
        assert _CARETAKER_RE.match("Caretaker Visit 99: something")

    def test_caretaker_pattern_no_match_partial(self):
        assert not _CARETAKER_RE.match("add caretaker visit log")

    def test_catchup_pattern_hyphen(self):
        assert _CATCHUP_RE.match("catch-up: commit pending changes")

    def test_catchup_pattern_no_hyphen(self):
        assert _CATCHUP_RE.match("catchup: flush backlog")

    def test_catchup_pattern_case_insensitive(self):
        assert _CATCHUP_RE.match("Catch-Up: something")

    def test_catchup_pattern_no_match(self):
        assert not _CATCHUP_RE.match("add catch-up module")

    def test_auto_content_flush_strokes(self):
        assert _AUTO_CONTENT_RE.search(
            "caretaker visit 311: add module + flush writer strokes"
        )

    def test_auto_content_add_module(self):
        assert _AUTO_CONTENT_RE.search(
            "add commit_breadth module (66 tests)"
        )

    def test_auto_content_add_module_singular(self):
        assert _AUTO_CONTENT_RE.search(
            "add foo module (1 test)"
        )

    def test_auto_content_no_match(self):
        assert not _AUTO_CONTENT_RE.search("fix typo in README")


# ---------------------------------------------------------------------------
# classify_commit
# ---------------------------------------------------------------------------

class TestClassifyCommit:
    """Unit tests for single-message classification."""

    # Caretaker commits
    def test_caretaker_visit(self):
        msg = "caretaker visit 311: add category_momentum module (62 tests)"
        assert classify_commit(msg) == "caretaker"

    def test_caretaker_visit_flush_only(self):
        msg = "caretaker visit 308: flush 9 pending files from stall recovery"
        assert classify_commit(msg) == "caretaker"

    def test_caretaker_visit_with_strokes(self):
        msg = "caretaker visit 309: add stroke_yield module (31 tests) + flush writer strokes"
        # Starts with "caretaker visit" → caretaker takes priority
        assert classify_commit(msg) == "caretaker"

    # Catch-up commits
    def test_catchup_basic(self):
        msg = "catch-up: commit pending changes before process restart"
        assert classify_commit(msg) == "catchup"

    def test_catchup_with_count(self):
        msg = "catch-up: commit 9 pending files (writer stall recovery)"
        assert classify_commit(msg) == "catchup"

    def test_catchup_before_visit(self):
        msg = "catch-up: commit 9 pending files before caretaker visit 304"
        assert classify_commit(msg) == "catchup"

    # Auto content commits
    def test_auto_add_module_with_tests(self):
        msg = "add commit_breadth module (66 tests) + flush writer strokes"
        assert classify_commit(msg) == "auto_content"

    def test_auto_add_module_only(self):
        msg = "add commit_debt module (31 tests pass)"
        assert classify_commit(msg) == "auto_content"

    def test_auto_flush_strokes_only(self):
        msg = "daily: flush writer strokes to data/strokes.jsonl"
        assert classify_commit(msg) == "auto_content"

    # Manual commits
    def test_manual_fix(self):
        assert classify_commit("fix typo in README") == "manual"

    def test_manual_update(self):
        assert classify_commit("update CHANGELOG for v0.2.0") == "manual"

    def test_manual_note(self):
        assert classify_commit("guoban: note (stroke 159)") == "manual"

    def test_manual_config(self):
        assert classify_commit("bump pytest to 8.0") == "manual"

    def test_empty_message(self):
        assert classify_commit("") == "manual"

    def test_none_like_empty(self):
        # Empty after strip
        assert classify_commit("   ") == "manual"


# ---------------------------------------------------------------------------
# _classify_grade
# ---------------------------------------------------------------------------

class TestClassifyGrade:
    """Unit tests for the grade classification function."""

    def test_perfect_autonomous(self):
        assert _classify_grade(1.0) == "autonomous"

    def test_at_autonomous_threshold(self):
        assert _classify_grade(0.70) == "autonomous"

    def test_just_below_autonomous(self):
        assert _classify_grade(0.699) == "supervised"

    def test_at_supervised_threshold(self):
        assert _classify_grade(0.50) == "supervised"

    def test_just_below_supervised(self):
        assert _classify_grade(0.499) == "attended"

    def test_at_attended_threshold(self):
        assert _classify_grade(0.30) == "attended"

    def test_just_below_attended(self):
        assert _classify_grade(0.299) == "dependent"

    def test_at_dependent_threshold(self):
        assert _classify_grade(0.10) == "dependent"

    def test_just_below_dependent(self):
        assert _classify_grade(0.099) == "manual"

    def test_zero_is_manual(self):
        assert _classify_grade(0.0) == "manual"

    def test_all_thresholds_match(self):
        for threshold, grade in _GRADE_THRESHOLDS:
            assert _classify_grade(threshold) == grade


# ---------------------------------------------------------------------------
# WorkloadReport
# ---------------------------------------------------------------------------

class TestWorkloadReport:
    """Unit tests for the WorkloadReport dataclass."""

    def test_empty_report_defaults(self):
        r = WorkloadReport()
        assert r.total_commits == 0
        assert r.self_sufficiency == 0.0
        assert r.grade == "manual"
        assert r.counts["caretaker"] == 0
        assert r.classified == []

    def test_to_dict(self):
        r = WorkloadReport(
            total_commits=10,
            counts={"caretaker": 5, "catchup": 3, "auto_content": 1, "manual": 1},
            self_sufficiency=0.40,
            intervention_rate=0.50,
            manual_rate=0.10,
            catchup_rate=0.30,
            grade="attended",
        )
        d = r.to_dict()
        assert d["total_commits"] == 10
        assert d["self_sufficiency"] == 0.40
        assert d["grade"] == "attended"
        assert d["counts"]["caretaker"] == 5

    def test_to_dict_rounding(self):
        r = WorkloadReport(self_sufficiency=0.333333333)
        assert r.to_dict()["self_sufficiency"] == 0.333


# ---------------------------------------------------------------------------
# workload_report (mocked git)
# ---------------------------------------------------------------------------

class TestWorkloadReportFunction:
    """Integration tests for the workload_report function."""

    @patch("iamai.caretaker_workload._get_recent_commits")
    def test_basic_report(self, mock_commits):
        mock_commits.return_value = [
            ("aaa", "caretaker visit 311: add module"),
            ("bbb", "catch-up: commit pending changes"),
            ("ccc", "add foo module (10 tests) + flush writer strokes"),
            ("ddd", "fix typo in README"),
        ]
        r = workload_report(repo_path="/tmp/fake", last=4)
        assert r.total_commits == 4
        assert r.counts["caretaker"] == 1
        assert r.counts["catchup"] == 1
        assert r.counts["auto_content"] == 1
        assert r.counts["manual"] == 1

    @patch("iamai.caretaker_workload._get_recent_commits")
    def test_self_sufficiency_calculation(self, mock_commits):
        mock_commits.return_value = [
            ("a", "add foo module (5 tests)"),
            ("b", "catch-up: flush"),
            ("c", "catch-up: flush again"),
            ("d", "caretaker visit 1: check"),
            ("e", "manual fix"),
        ]
        r = workload_report(repo_path="/tmp/fake", last=5)
        # auto=1, catchup=2, total=5 → self_sufficiency = 3/5 = 0.60
        assert r.self_sufficiency == pytest.approx(0.60, abs=0.001)
        assert r.grade == "supervised"

    @patch("iamai.caretaker_workload._get_recent_commits")
    def test_intervention_rate(self, mock_commits):
        mock_commits.return_value = [
            ("a", "caretaker visit 1: check"),
            ("b", "caretaker visit 2: check"),
            ("c", "catch-up: flush"),
            ("d", "add foo module (5 tests)"),
        ]
        r = workload_report(repo_path="/tmp/fake", last=4)
        assert r.intervention_rate == pytest.approx(0.50, abs=0.001)

    @patch("iamai.caretaker_workload._get_recent_commits")
    def test_manual_rate(self, mock_commits):
        mock_commits.return_value = [
            ("a", "fix bug"),
            ("b", "update docs"),
            ("c", "caretaker visit 1: check"),
            ("d", "catch-up: flush"),
        ]
        r = workload_report(repo_path="/tmp/fake", last=4)
        assert r.manual_rate == pytest.approx(0.50, abs=0.001)

    @patch("iamai.caretaker_workload._get_recent_commits")
    def test_empty_commits(self, mock_commits):
        mock_commits.return_value = []
        r = workload_report(repo_path="/tmp/fake", last=10)
        assert r.total_commits == 0
        assert r.grade == "manual"

    @patch("iamai.caretaker_workload._get_recent_commits")
    def test_classified_pairs(self, mock_commits):
        mock_commits.return_value = [
            ("sha1", "caretaker visit 5: stuff"),
            ("sha2", "catch-up: flush"),
        ]
        r = workload_report(repo_path="/tmp/fake", last=2)
        assert len(r.classified) == 2
        assert r.classified[0] == ("sha1", "caretaker")
        assert r.classified[1] == ("sha2", "catchup")

    @patch("iamai.caretaker_workload._get_recent_commits")
    def test_all_auto_is_autonomous(self, mock_commits):
        mock_commits.return_value = [
            (f"s{i}", f"add mod{i} module ({i} tests)")
            for i in range(10)
        ]
        r = workload_report(repo_path="/tmp/fake", last=10)
        assert r.self_sufficiency == 1.0
        assert r.grade == "autonomous"

    @patch("iamai.caretaker_workload._get_recent_commits")
    def test_all_manual_grade(self, mock_commits):
        mock_commits.return_value = [
            (f"s{i}", f"manual fix {i}") for i in range(10)
        ]
        r = workload_report(repo_path="/tmp/fake", last=10)
        assert r.self_sufficiency == 0.0
        assert r.grade == "manual"

    @patch("iamai.caretaker_workload._get_recent_commits")
    def test_dependent_grade(self, mock_commits):
        # 1 auto out of 10 = 0.10 self_sufficiency → dependent
        mock_commits.return_value = [
            ("a", "add foo module (5 tests)"),
        ] + [(f"s{i}", f"fix {i}") for i in range(9)]
        r = workload_report(repo_path="/tmp/fake", last=10)
        assert r.self_sufficiency == pytest.approx(0.10, abs=0.001)
        assert r.grade == "dependent"


# ---------------------------------------------------------------------------
# workload_summary
# ---------------------------------------------------------------------------

class TestWorkloadSummary:
    """Unit tests for the summary formatter."""

    def test_empty_report(self):
        r = WorkloadReport()
        result = workload_summary(r)
        assert "no commits" in result

    def test_normal_report(self):
        r = WorkloadReport(
            total_commits=10,
            counts={"caretaker": 4, "catchup": 3, "auto_content": 2, "manual": 1},
            self_sufficiency=0.50,
            grade="supervised",
        )
        result = workload_summary(r)
        assert "50%" in result
        assert "supervised" in result
        assert "10 commits" in result
        assert "auto 2" in result
        assert "caretaker 4" in result

    def test_autonomous_report(self):
        r = WorkloadReport(
            total_commits=20,
            counts={"caretaker": 2, "catchup": 5, "auto_content": 12, "manual": 1},
            self_sufficiency=0.85,
            grade="autonomous",
        )
        result = workload_summary(r)
        assert "85%" in result
        assert "autonomous" in result


# ---------------------------------------------------------------------------
# Integration test (real git, temp repo)
# ---------------------------------------------------------------------------

class TestIntegration:
    """End-to-end tests using a temporary git repository."""

    @pytest.fixture
    def temp_repo(self, tmp_path):
        repo = tmp_path / "test_repo"
        repo.mkdir()

        subprocess.run(
            ["git", "init", str(repo)],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "test@test.com"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Test"],
            capture_output=True, check=True,
        )

        # Commit 1: auto content
        (repo / "foo.py").write_text("# foo")
        subprocess.run(
            ["git", "-C", str(repo), "add", "."],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m",
             "add foo module (5 tests) + flush writer strokes"],
            capture_output=True, check=True,
        )

        # Commit 2: catch-up
        (repo / "bar.py").write_text("# bar")
        subprocess.run(
            ["git", "-C", str(repo), "add", "."],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m",
             "catch-up: commit pending changes"],
            capture_output=True, check=True,
        )

        # Commit 3: caretaker visit
        (repo / "baz.py").write_text("# baz")
        subprocess.run(
            ["git", "-C", str(repo), "add", "."],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m",
             "caretaker visit 42: add baz + flush writer strokes"],
            capture_output=True, check=True,
        )

        # Commit 4: manual
        (repo / "README.md").write_text("# Hello")
        subprocess.run(
            ["git", "-C", str(repo), "add", "."],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "add README"],
            capture_output=True, check=True,
        )

        return repo

    def test_real_repo_total(self, temp_repo):
        r = workload_report(repo_path=temp_repo, last=10)
        assert r.total_commits == 4

    def test_real_repo_counts(self, temp_repo):
        r = workload_report(repo_path=temp_repo, last=10)
        assert r.counts["auto_content"] == 1
        assert r.counts["catchup"] == 1
        assert r.counts["caretaker"] == 1
        assert r.counts["manual"] == 1

    def test_real_repo_self_sufficiency(self, temp_repo):
        r = workload_report(repo_path=temp_repo, last=10)
        # auto(1) + catchup(1) = 2 out of 4 → 0.50
        assert r.self_sufficiency == pytest.approx(0.50, abs=0.001)

    def test_real_repo_grade(self, temp_repo):
        r = workload_report(repo_path=temp_repo, last=10)
        assert r.grade == "supervised"

    def test_real_repo_summary(self, temp_repo):
        r = workload_report(repo_path=temp_repo, last=10)
        s = workload_summary(r)
        assert "caretaker_workload" in s
        assert "%" in s

    def test_real_repo_classified_pairs(self, temp_repo):
        r = workload_report(repo_path=temp_repo, last=10)
        buckets = [b for _, b in r.classified]
        assert "caretaker" in buckets
        assert "catchup" in buckets
        assert "auto_content" in buckets
        assert "manual" in buckets
