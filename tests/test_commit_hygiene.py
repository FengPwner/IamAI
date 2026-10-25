"""Tests for iamai.commit_hygiene."""

import math
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.commit_hygiene import (
    HygieneReport,
    classify_commit,
    focus_score_batch,
    hygiene_report,
    hygiene_summary,
    message_quality_score,
    message_score,
    regularity_score,
    size_health_score,
    size_health_score_batch,
    type_diversity_score,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _commit(msg: str, ts: float = 0.0, files: list[str] | None = None) -> dict:
    """Helper: build a minimal commit dict."""
    return {
        "hash": "abc1234",
        "message": msg,
        "timestamp": ts,
        "files": files or [],
    }


# ---------------------------------------------------------------------------
# message_score
# ---------------------------------------------------------------------------

class TestMessageScore:
    def test_empty_message(self):
        assert message_score("") == 0.0

    def test_very_short(self):
        assert message_score("hi") == 0.0

    def test_short_but_valid(self):
        assert message_score("fix bug") == 0.5

    def test_good_message(self):
        assert message_score("add stroke velocity trend analysis") == 1.0

    def test_generic_single_word(self):
        assert message_score("fix") == 0.0
        assert message_score("update") == 0.0
        assert message_score("wip") == 0.0
        assert message_score("save") == 0.0

    def test_generic_with_punctuation(self):
        assert message_score("fix:") == 0.0
        assert message_score("update.") == 0.0

    def test_all_caps_shouting(self):
        assert message_score("THIS IS A VERY LOUD COMMIT MESSAGE") == 0.3

    def test_short_caps_not_penalised(self):
        # Too short to trigger ALL-CAPS check (< 5 alpha)
        assert message_score("FIX") == 0.0  # generic word

    def test_mixed_case_normal(self):
        assert message_score("Add new test for commit hygiene module") == 1.0

    def test_caretaker_visit(self):
        assert message_score("caretaker visit 346: upgrade stroke_novelty.py") == 1.0

    def test_catch_up(self):
        assert message_score("catch-up: commit pending changes before restart") == 1.0


# ---------------------------------------------------------------------------
# message_quality_score
# ---------------------------------------------------------------------------

class TestMessageQualityScore:
    def test_empty_commits(self):
        assert message_quality_score([]) == 1.0

    def test_all_good(self):
        commits = [
            _commit("add new feature for pipeline analysis"),
            _commit("upgrade stroke novelty with cycle detection"),
            _commit("caretaker visit 100: comprehensive review"),
        ]
        assert message_quality_score(commits) == 1.0

    def test_all_bad(self):
        commits = [
            _commit("fix"),
            _commit("wip"),
            _commit("update"),
        ]
        assert message_quality_score(commits) == 0.0

    def test_mixed(self):
        commits = [
            _commit("add new feature for pipeline analysis"),  # 1.0
            _commit("fix"),  # 0.0
        ]
        assert message_quality_score(commits) == 0.5


# ---------------------------------------------------------------------------
# size_health_score
# ---------------------------------------------------------------------------

class TestSizeHealthScore:
    def test_empty_commit(self):
        assert size_health_score(_commit("msg", files=[])) == 0.8

    def test_small_commit(self):
        assert size_health_score(_commit("msg", files=["a.py"])) == 1.0

    def test_medium_commit(self):
        files = [f"dir{i}/file.py" for i in range(5)]
        assert size_health_score(_commit("msg", files=files)) == 1.0

    def test_large_commit(self):
        files = [f"dir{i}/file.py" for i in range(15)]
        assert size_health_score(_commit("msg", files=files)) == 0.7

    def test_very_large_commit(self):
        files = [f"dir{i}/file.py" for i in range(30)]
        assert size_health_score(_commit("msg", files=files)) == 0.4

    def test_huge_commit(self):
        files = [f"dir{i}/file.py" for i in range(60)]
        assert size_health_score(_commit("msg", files=files)) == 0.1


class TestSizeHealthScoreBatch:
    def test_empty(self):
        assert size_health_score_batch([]) == 1.0

    def test_average(self):
        commits = [
            _commit("a", files=["a.py"]),  # 1.0
            _commit("b", files=[]),  # 0.8
        ]
        assert size_health_score_batch(commits) == 0.9


# ---------------------------------------------------------------------------
# focus_score_batch
# ---------------------------------------------------------------------------

class TestFocusScoreBatch:
    def test_empty(self):
        assert focus_score_batch([]) == 1.0

    def test_focused_commits(self):
        commits = [
            _commit("a", files=["tools/foo.py"]),
            _commit("b", files=["tests/test_foo.py"]),
        ]
        score = focus_score_batch(commits)
        assert score == 1.0  # 1 file, 1 dir each

    def test_sprawling_commit(self):
        files = [f"dir{i}/file{j}.py" for i in range(5) for j in range(3)]
        commits = [_commit("big", files=files)]
        score = focus_score_batch(commits)
        assert score < 0.3


# ---------------------------------------------------------------------------
# regularity_score
# ---------------------------------------------------------------------------

class TestRegularityScore:
    def test_too_few_commits(self):
        assert regularity_score([_commit("a", ts=100)]) == 1.0
        assert regularity_score([_commit("a", ts=100), _commit("b", ts=200)]) == 1.0

    def test_perfectly_regular(self):
        commits = [_commit(f"c{i}", ts=1000 + i * 600) for i in range(5)]
        assert regularity_score(commits) == 1.0

    def test_somewhat_irregular(self):
        # Intervals: 600, 300, 900, 600 → CV ≈ 0.36
        commits = [
            _commit("a", ts=0),
            _commit("b", ts=600),
            _commit("c", ts=900),
            _commit("d", ts=1800),
            _commit("e", ts=2400),
        ]
        score = regularity_score(commits)
        assert 0.5 <= score <= 1.0

    def test_very_erratic(self):
        # Intervals: 10, 10000, 5, 8000 → huge CV
        commits = [
            _commit("a", ts=0),
            _commit("b", ts=10),
            _commit("c", ts=10010),
            _commit("d", ts=10015),
            _commit("e", ts=18015),
        ]
        score = regularity_score(commits)
        assert score < 0.5

    def test_unsorted_input(self):
        # Should sort internally
        commits = [
            _commit("c", ts=1200),
            _commit("a", ts=0),
            _commit("b", ts=600),
        ]
        assert regularity_score(commits) == 1.0  # perfectly regular

    def test_duplicate_timestamps(self):
        commits = [
            _commit("a", ts=100),
            _commit("b", ts=100),
            _commit("c", ts=100),
        ]
        # All intervals zero → mean=0 → return 1.0
        assert regularity_score(commits) == 1.0


# ---------------------------------------------------------------------------
# classify_commit
# ---------------------------------------------------------------------------

class TestClassifyCommit:
    def test_caretaker(self):
        assert classify_commit("caretaker visit 346: upgrade") == "caretaker"

    def test_catch_up(self):
        assert classify_commit("catch-up: commit pending changes") == "catch-up"

    def test_writer_flush(self):
        assert classify_commit("writer strokes: flush pending changes") == "writer_flush"

    def test_feature_add(self):
        assert classify_commit("add stroke_velocity_trend.py") == "feature"

    def test_feature_feat_prefix(self):
        assert classify_commit("feat: new monitoring tool") == "feature"

    def test_fix(self):
        assert classify_commit("fix: broken test assertion") == "fix"

    def test_bugfix(self):
        assert classify_commit("bugfix: handle empty input") == "fix"

    def test_docs(self):
        assert classify_commit("docs: update README") == "docs"
        assert classify_commit("notes: add observation") == "docs"

    def test_test(self):
        assert classify_commit("tests: add hygiene tests") == "test"

    def test_merge(self):
        assert classify_commit("Merge branch 'feature'") == "merge"

    def test_other(self):
        assert classify_commit("random commit message") == "other"

    def test_case_insensitive(self):
        assert classify_commit("Caretaker Visit 100: stuff") == "caretaker"
        assert classify_commit("CATCH-UP: pending") == "catch-up"


# ---------------------------------------------------------------------------
# type_diversity_score
# ---------------------------------------------------------------------------

class TestTypeDiversityScore:
    def test_empty(self):
        assert type_diversity_score([]) == 1.0

    def test_single_commit(self):
        assert type_diversity_score([_commit("fix")]) == 1.0

    def test_all_same_type(self):
        commits = [_commit("fix: thing " + str(i)) for i in range(10)]
        assert type_diversity_score(commits) == 0.0

    def test_balanced_mix(self):
        commits = [
            _commit("caretaker visit 1: review"),
            _commit("catch-up: pending"),
            _commit("add new feature"),
            _commit("fix: broken test"),
            _commit("docs: update notes"),
        ]
        score = type_diversity_score(commits)
        assert score > 0.8

    def test_dominated_by_one(self):
        commits = [_commit("fix: thing " + str(i)) for i in range(8)]
        commits.append(_commit("add feature"))
        commits.append(_commit("docs update"))
        score = type_diversity_score(commits)
        assert score < 0.5

    def test_two_types_balanced(self):
        commits = [
            _commit("fix: thing 1"),
            _commit("fix: thing 2"),
            _commit("fix: thing 3"),
            _commit("add feature 1"),
            _commit("add feature 2"),
            _commit("add feature 3"),
        ]
        score = type_diversity_score(commits)
        assert score == 1.0  # perfectly balanced 50/50


# ---------------------------------------------------------------------------
# HygieneReport & hygiene_report
# ---------------------------------------------------------------------------

class TestHygieneReport:
    def test_default_is_healthy(self):
        report = HygieneReport()
        assert report.score == 100.0
        assert report.verdict == "healthy"

    def test_to_dict(self):
        report = HygieneReport(n=10, score=82.5, verdict="healthy")
        d = report.to_dict()
        assert d["n"] == 10
        assert d["score"] == 82.5
        assert d["verdict"] == "healthy"
        assert "signals" in d
        assert "message" in d["signals"]


class TestHygieneSummary:
    def test_no_commits(self):
        report = HygieneReport(n=0)
        assert "no commits" in hygiene_summary(report)

    def test_normal_output(self):
        report = HygieneReport(
            n=20,
            message=0.9,
            size=1.0,
            focus=0.8,
            regularity=0.7,
            diversity=0.6,
            score=80.0,
            verdict="healthy",
        )
        summary = hygiene_summary(report)
        assert "healthy" in summary
        assert "80.0" in summary
        assert "message" in summary


# ---------------------------------------------------------------------------
# hygiene_report integration (mocked git)
# ---------------------------------------------------------------------------

class TestHygieneReportIntegration:
    """Test the full report pipeline with mocked git output."""

    def test_no_git(self):
        """When git is unavailable, returns default healthy report."""
        with patch("iamai.commit_hygiene._git", return_value=""):
            report = hygiene_report(repo="/fake/path", n=10)
            assert report.verdict == "healthy"
            assert report.score == 100.0

    def test_with_mock_commits(self):
        """Simulate a small set of commits through the full pipeline."""
        mock_commits = [
            {"hash": "aaa1111", "message": "caretaker visit 10: review", "timestamp": 1000.0, "files": ["tools/foo.py"]},
            {"hash": "bbb2222", "message": "add bar.py with tests", "timestamp": 1600.0, "files": ["tools/bar.py", "tests/test_bar.py"]},
            {"hash": "ccc3333", "message": "fix: broken assertion", "timestamp": 2200.0, "files": ["tests/test_bar.py"]},
            {"hash": "ddd4444", "message": "catch-up: pending changes", "timestamp": 2800.0, "files": ["data/strokes.jsonl"]},
        ]

        with patch("iamai.commit_hygiene._recent_commits", return_value=mock_commits):
            report = hygiene_report(repo="/fake/path", n=4)

        assert report.n == 4
        assert report.message == 1.0  # all messages are good quality
        assert report.size == 1.0  # all small commits
        assert report.focus > 0.8  # mostly focused (2-file commit lowers avg slightly)
        assert report.regularity == 1.0  # perfectly regular (600s intervals)
        assert 0 < report.diversity <= 1.0  # 4 different types
        assert report.score >= 75
        assert report.verdict == "healthy"

    def test_poor_health(self):
        """Simulate a repo in bad shape."""
        mock_commits = [
            {"hash": "aaa1111", "message": "fix", "timestamp": 0.0,
             "files": [f"d{i}/f{j}.py" for i in range(6) for j in range(10)]},
            {"hash": "bbb2222", "message": "wip", "timestamp": 10.0,
             "files": [f"d{i}/f{j}.py" for i in range(6) for j in range(10)]},
            {"hash": "ccc3333", "message": "fix", "timestamp": 10000.0,
             "files": [f"d{i}/f{j}.py" for i in range(6) for j in range(10)]},
            {"hash": "ddd4444", "message": "update", "timestamp": 10010.0,
             "files": [f"d{i}/f{j}.py" for i in range(6) for j in range(10)]},
        ]

        with patch("iamai.commit_hygiene._recent_commits", return_value=mock_commits):
            report = hygiene_report(repo="/fake/path", n=4)

        assert report.message < 0.5  # generic messages
        assert report.size < 0.5  # huge commits
        assert report.regularity < 0.5  # erratic timing
        assert report.diversity == 0.0  # all "fix" or generic
        assert report.score < 50
        assert report.verdict == "poor"
