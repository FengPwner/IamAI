"""Tests for iamai.repo_circulation."""

import pytest
from unittest.mock import patch

from iamai.repo_circulation import (
    CirculationReport,
    ALL_CATEGORIES,
    classify_file,
    classify_files,
    circulation_report,
    circulation_summary,
    _category_commit_count,
    _category_last_seen,
    _classify_state,
    _compute_circulation_score,
    _detect_bloated,
    _detect_starving,
    _freshness_score,
    _git_log_files,
)


# ---------------------------------------------------------------------------
# classify_file
# ---------------------------------------------------------------------------

class TestClassifyFile:
    def test_devlog(self):
        assert classify_file("docs/DEVLOG.md") == "devlog"

    def test_garden(self):
        assert classify_file("docs/GARDEN.md") == "garden"

    def test_metrics(self):
        assert classify_file("docs/METRICS.md") == "metrics"

    def test_thoughts(self):
        assert classify_file("docs/THOUGHTS.md") == "thought"

    def test_note(self):
        assert classify_file("notes/conventions.md") == "note"

    def test_note_subdir(self):
        assert classify_file("notes/archive/old.md") == "note"

    def test_snippet(self):
        assert classify_file("snippets/example.py") == "snippet"

    def test_code_generic(self):
        assert classify_file("iamai/heartbeat.py") == "code"

    def test_code_tests(self):
        assert classify_file("tests/test_heartbeat.py") == "code"

    def test_code_tools(self):
        assert classify_file("tools/writer_loop.py") == "code"

    def test_readme(self):
        assert classify_file("README.md") == "code"


# ---------------------------------------------------------------------------
# classify_files
# ---------------------------------------------------------------------------

class TestClassifyFiles:
    def test_counts(self):
        files = [
            "docs/DEVLOG.md",
            "docs/GARDEN.md",
            "notes/a.md",
            "notes/b.md",
            "iamai/x.py",
        ]
        result = classify_files(files)
        assert result == {"devlog": 1, "garden": 1, "note": 2}

    def test_empty(self):
        assert classify_files([]) == {}

    def test_all_code(self):
        result = classify_files(["iamai/x.py", "tools/y.py"])
        assert result == {}


# ---------------------------------------------------------------------------
# _freshness_score
# ---------------------------------------------------------------------------

class TestFreshnessScore:
    def test_just_committed(self):
        assert _freshness_score(0, 3600) == 100.0

    def test_half_max_age(self):
        score = _freshness_score(1800, 3600)
        assert 70.0 <= score <= 80.0

    def test_at_max_age(self):
        score = _freshness_score(3600, 3600)
        assert 45.0 <= score <= 55.0

    def test_double_max_age(self):
        assert _freshness_score(7200, 3600) == 0.0

    def test_beyond_double(self):
        assert _freshness_score(10000, 3600) == 0.0

    def test_negative_age_treated_as_zero(self):
        assert _freshness_score(-1, 3600) == 100.0


# ---------------------------------------------------------------------------
# _category_last_seen
# ---------------------------------------------------------------------------

class TestCategoryLastSeen:
    def test_basic(self):
        entries = [
            (1000, ["docs/DEVLOG.md"]),
            (900, ["docs/GARDEN.md"]),
            (800, ["notes/a.md"]),
        ]
        result = _category_last_seen(entries, now=1000)
        assert result == {"devlog": 0, "garden": 100, "note": 200}

    def test_code_excluded(self):
        entries = [(1000, ["iamai/x.py", "docs/DEVLOG.md"])]
        result = _category_last_seen(entries, now=1000)
        assert result == {"devlog": 0}

    def test_empty(self):
        assert _category_last_seen([]) == {}

    def test_default_now(self):
        entries = [
            (1000, ["docs/DEVLOG.md"]),
            (500, ["notes/a.md"]),
        ]
        result = _category_last_seen(entries)
        assert result["devlog"] == 0
        assert result["note"] == 500


# ---------------------------------------------------------------------------
# _category_commit_count
# ---------------------------------------------------------------------------

class TestCategoryCommitCount:
    def test_counts_unique_categories_per_commit(self):
        entries = [
            (1000, ["docs/DEVLOG.md", "docs/GARDEN.md"]),
            (900, ["docs/DEVLOG.md"]),
            (800, ["notes/a.md"]),
        ]
        result = _category_commit_count(entries)
        assert result == {"devlog": 2, "garden": 1, "note": 1}

    def test_no_double_count_same_category_in_commit(self):
        entries = [
            (1000, ["notes/a.md", "notes/b.md"]),
        ]
        result = _category_commit_count(entries)
        assert result == {"note": 1}

    def test_code_ignored(self):
        entries = [(1000, ["iamai/x.py"])]
        result = _category_commit_count(entries)
        assert result == {}

    def test_empty(self):
        assert _category_commit_count([]) == {}


# ---------------------------------------------------------------------------
# _detect_starving
# ---------------------------------------------------------------------------

class TestDetectStarving:
    def test_none_starving(self):
        ages = {"devlog": 100, "garden": 200}
        max_ages = {"devlog": 3600, "garden": 3600}
        assert _detect_starving(ages, max_ages) == []

    def test_one_starving(self):
        ages = {"devlog": 100, "garden": 5000}
        max_ages = {"devlog": 3600, "garden": 3600}
        assert _detect_starving(ages, max_ages) == ["garden"]

    def test_all_starving(self):
        ages = {"devlog": 5000, "garden": 6000}
        max_ages = {"devlog": 3600, "garden": 3600}
        result = _detect_starving(ages, max_ages)
        assert sorted(result) == ["devlog", "garden"]

    def test_sorted_output(self):
        ages = {"note": 5000, "devlog": 4000}
        max_ages = {"note": 3600, "devlog": 3600}
        result = _detect_starving(ages, max_ages)
        assert result == ["devlog", "note"]


# ---------------------------------------------------------------------------
# _detect_bloated
# ---------------------------------------------------------------------------

class TestDetectBloated:
    def test_none_bloated(self):
        counts = {"devlog": 5, "garden": 5, "note": 5}
        assert _detect_bloated(counts, 15) == []

    def test_one_bloated(self):
        counts = {"devlog": 12, "garden": 2, "note": 1}
        result = _detect_bloated(counts, 15)
        assert result == ["devlog"]

    def test_zero_commits(self):
        assert _detect_bloated({}, 0) == []

    def test_sorted_output(self):
        counts = {"note": 10, "devlog": 10, "garden": 1}
        result = _detect_bloated(counts, 21)
        assert result == ["devlog", "note"]


# ---------------------------------------------------------------------------
# _compute_circulation_score
# ---------------------------------------------------------------------------

class TestComputeCirculationScore:
    def test_all_fresh(self):
        ages = {"devlog": 0, "garden": 0, "note": 0}
        max_ages = {"devlog": 3600, "garden": 3600, "note": 3600}
        assert _compute_circulation_score(ages, max_ages) == 100.0

    def test_all_dead(self):
        ages = {"devlog": 10000, "garden": 10000}
        max_ages = {"devlog": 3600, "garden": 3600}
        assert _compute_circulation_score(ages, max_ages) == 0.0

    def test_empty(self):
        assert _compute_circulation_score({}, {}) == 0.0

    def test_mixed(self):
        ages = {"devlog": 0, "garden": 3600}
        max_ages = {"devlog": 3600, "garden": 3600}
        score = _compute_circulation_score(ages, max_ages)
        # devlog=100, garden=50 → average=75
        assert 70.0 <= score <= 80.0


# ---------------------------------------------------------------------------
# _classify_state
# ---------------------------------------------------------------------------

class TestClassifyState:
    def test_insufficient_data(self):
        assert _classify_state(50, [], [], 0) == "insufficient_data"

    def test_vibrant(self):
        assert _classify_state(85, [], [], 3) == "vibrant"

    def test_balanced(self):
        assert _classify_state(70, [], [], 3) == "balanced"

    def test_uneen_with_starving(self):
        assert _classify_state(70, ["garden"], [], 3) == "uneven"

    def test_uneven_low_score(self):
        # 1 starving out of 4 → not majority → "uneven"
        assert _classify_state(50, ["garden"], [], 4) == "uneven"

    def test_stagnant(self):
        # 2 out of 3 starving → stagnant at score 45
        assert _classify_state(45, ["devlog", "garden"], [], 3) == "stagnant"

    def test_critical(self):
        assert _classify_state(20, ["a", "b", "c"], [], 3) == "critical"


# ---------------------------------------------------------------------------
# _git_log_files
# ---------------------------------------------------------------------------

class TestGitLogFiles:
    @patch("subprocess.check_output")
    def test_parses_output(self, mock_sub):
        mock_sub.return_value = (
            "1729828800\n"
            "docs/DEVLOG.md\n"
            "docs/GARDEN.md\n"
            "1729828700\n"
            "notes/a.md\n"
            "\n"
        )
        entries = _git_log_files(".")
        assert len(entries) == 2
        assert entries[0] == (1729828800, ["docs/DEVLOG.md", "docs/GARDEN.md"])
        assert entries[1] == (1729828700, ["notes/a.md"])

    @patch("subprocess.check_output")
    def test_empty_repo(self, mock_sub):
        mock_sub.return_value = ""
        entries = _git_log_files(".")
        assert entries == []

    @patch("subprocess.check_output", side_effect=FileNotFoundError)
    def test_no_git(self, mock_sub):
        entries = _git_log_files("/nonexistent")
        assert entries == []

    @patch("subprocess.check_output", side_effect=Exception("git error"))
    def test_git_error(self, mock_sub):
        with pytest.raises(Exception):
            _git_log_files(".")


# ---------------------------------------------------------------------------
# circulation_report (integration with mocks)
# ---------------------------------------------------------------------------

class TestCirculationReport:
    @patch("iamai.repo_circulation._git_log_files")
    def test_insufficient_data(self, mock_log):
        mock_log.return_value = [(1000, ["docs/DEVLOG.md"])] * 3
        r = circulation_report(repo_path=".", last=10)
        assert r.state == "insufficient_data"
        assert r.circulation_score == 0.0

    @patch("iamai.repo_circulation._git_log_files")
    def test_healthy_circulation(self, mock_log):
        now = 10000
        entries = [
            (now, ["docs/DEVLOG.md"]),
            (now - 100, ["docs/GARDEN.md"]),
            (now - 200, ["notes/a.md"]),
            (now - 300, ["docs/METRICS.md"]),
            (now - 400, ["snippets/x.py"]),
            (now - 500, ["docs/THOUGHTS.md"]),
            (now - 600, ["docs/DEVLOG.md"]),
            (now - 700, ["notes/b.md"]),
        ]
        mock_log.return_value = entries
        r = circulation_report(repo_path=".", last=10, now=now)
        assert r.state in ("vibrant", "balanced")
        assert r.circulation_score >= 60
        assert r.starving_categories == []
        assert r.active_categories == 6

    @patch("iamai.repo_circulation._git_log_files")
    def test_starving_category(self, mock_log):
        now = 10000
        entries = [
            (now, ["docs/DEVLOG.md"]),
            (now - 100, ["docs/DEVLOG.md"]),
            (now - 200, ["docs/DEVLOG.md"]),
            (now - 300, ["docs/DEVLOG.md"]),
            (now - 400, ["docs/DEVLOG.md"]),
            (now - 8000, ["notes/a.md"]),
        ]
        mock_log.return_value = entries
        r = circulation_report(repo_path=".", last=10, now=now)
        assert "note" in r.starving_categories

    @patch("iamai.repo_circulation._git_log_files")
    def test_bloated_category(self, mock_log):
        now = 10000
        entries = [(now - i * 10, ["docs/DEVLOG.md"]) for i in range(8)]
        entries.append((now - 100, ["notes/a.md"]))
        entries.append((now - 200, ["notes/b.md"]))
        mock_log.return_value = entries
        r = circulation_report(repo_path=".", last=20, now=now)
        assert "devlog" in r.bloated_categories

    @patch("iamai.repo_circulation._git_log_files")
    def test_custom_max_ages(self, mock_log):
        now = 10000
        entries = [
            (now, ["docs/DEVLOG.md"]),
            (now - 100, ["notes/a.md"]),
            (now - 200, ["docs/GARDEN.md"]),
            (now - 300, ["docs/METRICS.md"]),
            (now - 400, ["snippets/x.py"]),
        ]
        mock_log.return_value = entries
        custom = {"devlog": 60, "garden": 60, "note": 60, "metrics": 60, "snippet": 60}
        r = circulation_report(repo_path=".", last=10, max_ages=custom, now=now)
        # garden at 200s age with 60s max → starving
        assert "garden" in r.starving_categories

    @patch("iamai.repo_circulation._git_log_files")
    def test_report_dataclass_defaults(self, mock_log):
        mock_log.return_value = [(1, ["x.py"])] * 2
        r = circulation_report(repo_path=".")
        assert r.commits_analysed == 2
        assert r.state == "insufficient_data"


# ---------------------------------------------------------------------------
# circulation_summary
# ---------------------------------------------------------------------------

class TestCirculationSummary:
    def test_insufficient_data(self):
        r = CirculationReport(state="insufficient_data")
        s = circulation_summary(r)
        assert "insufficient data" in s

    def test_healthy(self):
        r = CirculationReport(
            category_age={"devlog": 0, "garden": 0},
            category_freshness={"devlog": 100.0, "garden": 95.0},
            starving_categories=[],
            bloated_categories=[],
            circulation_score=97.5,
            state="vibrant",
            active_categories=2,
        )
        s = circulation_summary(r)
        assert "97.5" in s
        assert "vibrant" in s

    def test_with_starving(self):
        r = CirculationReport(
            category_age={"devlog": 0, "garden": 5000},
            category_freshness={"devlog": 100.0, "garden": 0.0},
            starving_categories=["garden"],
            bloated_categories=[],
            circulation_score=50.0,
            state="uneven",
            active_categories=2,
        )
        s = circulation_summary(r)
        assert "starving" in s
        assert "garden" in s

    def test_with_bloated(self):
        r = CirculationReport(
            category_age={"devlog": 0, "note": 100},
            category_freshness={"devlog": 100.0, "note": 90.0},
            starving_categories=[],
            bloated_categories=["devlog"],
            circulation_score=95.0,
            state="vibrant",
            active_categories=2,
        )
        s = circulation_summary(r)
        assert "bloated" in s
        assert "devlog" in s

    def test_driest_organ(self):
        r = CirculationReport(
            category_age={"devlog": 0, "garden": 100},
            category_freshness={"devlog": 100.0, "garden": 80.0},
            starving_categories=[],
            bloated_categories=[],
            circulation_score=90.0,
            state="vibrant",
            active_categories=2,
        )
        s = circulation_summary(r)
        assert "driest organ" in s
        assert "garden" in s


# ---------------------------------------------------------------------------
# ALL_CATEGORIES constant
# ---------------------------------------------------------------------------

class TestConstants:
    def test_all_categories_tuple(self):
        assert isinstance(ALL_CATEGORIES, tuple)
        assert len(ALL_CATEGORIES) == 6
        assert "devlog" in ALL_CATEGORIES
        assert "snippet" in ALL_CATEGORIES
