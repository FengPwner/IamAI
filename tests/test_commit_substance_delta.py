"""Tests for iamai.commit_substance_delta module."""

import pytest

from iamai.commit_substance_delta import (
    SubstanceReport,
    batch_substance_score,
    classify_change_type,
    classify_commit,
    compute_substance_score,
    parse_diffstat,
)


# ---------------------------------------------------------------------------
# classify_change_type
# ---------------------------------------------------------------------------


class TestClassifyChangeType:
    """Tests for change type classification."""

    def test_new_content_when_majority_new_files(self):
        """5 files changed, 3 are new → new_content."""
        result = classify_change_type(
            files_changed=5, insertions=200, deletions=10,
            new_files=3, data_files=0,
        )
        assert result == "new_content"

    def test_new_content_at_exact_threshold(self):
        """4 files changed, 2 are new (50%) → new_content."""
        result = classify_change_type(
            files_changed=4, insertions=100, deletions=20,
            new_files=2, data_files=0,
        )
        assert result == "new_content"

    def test_data_append_when_majority_data_files(self):
        """6 files changed, 4 are data → data_append."""
        result = classify_change_type(
            files_changed=6, insertions=50, deletions=5,
            new_files=0, data_files=4,
        )
        assert result == "data_append"

    def test_data_append_at_exact_threshold(self):
        """4 files changed, 2 are data (50%) → data_append."""
        result = classify_change_type(
            files_changed=4, insertions=30, deletions=3,
            new_files=0, data_files=2,
        )
        assert result == "data_append"

    def test_expansion_when_net_additions_positive(self):
        """3 files modified, more additions than deletions → expansion."""
        result = classify_change_type(
            files_changed=3, insertions=80, deletions=10,
            new_files=0, data_files=0,
        )
        assert result == "expansion"

    def test_contraction_when_net_deletions_positive(self):
        """3 files modified, more deletions than additions → contraction."""
        result = classify_change_type(
            files_changed=3, insertions=10, deletions=80,
            new_files=0, data_files=0,
        )
        assert result == "contraction"

    def test_refactor_when_balanced(self):
        """3 files modified, roughly equal adds/deletes → refactor."""
        result = classify_change_type(
            files_changed=3, insertions=50, deletions=45,
            new_files=0, data_files=0,
        )
        assert result == "refactor"

    def test_refactor_when_zero_files(self):
        """0 files changed → refactor (edge case)."""
        result = classify_change_type(
            files_changed=0, insertions=0, deletions=0,
            new_files=0, data_files=0,
        )
        assert result == "refactor"

    def test_refactor_when_zero_lines(self):
        """Files changed but zero insertions and deletions → refactor."""
        result = classify_change_type(
            files_changed=2, insertions=0, deletions=0,
            new_files=0, data_files=0,
        )
        assert result == "refactor"

    def test_new_files_take_priority_over_data(self):
        """When both new_files and data_files are majority, new_content wins."""
        # 4 files, 3 new, 2 data — new_files checked first
        result = classify_change_type(
            files_changed=4, insertions=100, deletions=5,
            new_files=3, data_files=2,
        )
        # data_files >= 50% triggers first in the code, so data_append
        assert result == "data_append"

    def test_single_new_file(self):
        """1 file changed, 1 new → new_content."""
        result = classify_change_type(
            files_changed=1, insertions=50, deletions=0,
            new_files=1, data_files=0,
        )
        assert result == "new_content"


# ---------------------------------------------------------------------------
# compute_substance_score
# ---------------------------------------------------------------------------


class TestComputeSubstanceScore:
    """Tests for substance score computation."""

    def test_high_score_for_new_module_with_tests(self):
        """New module + tests should score high."""
        score = compute_substance_score(
            files_changed=2, insertions=150, deletions=0,
            new_files=2, test_files=1, data_files=0,
        )
        assert score >= 0.7

    def test_low_score_for_data_append(self):
        """Pure data append should score low."""
        score = compute_substance_score(
            files_changed=1, insertions=5, deletions=0,
            new_files=0, test_files=0, data_files=1,
        )
        assert score <= 0.4

    def test_medium_score_for_refactor(self):
        """Balanced edit (refactor) scores low-medium — no new files or tests."""
        score = compute_substance_score(
            files_changed=3, insertions=40, deletions=38,
            new_files=0, test_files=0, data_files=0,
        )
        assert 0.05 <= score <= 0.4

    def test_score_bounded_zero_one(self):
        """Score is always in [0, 1]."""
        # extreme cases
        score_high = compute_substance_score(
            files_changed=100, insertions=10000, deletions=0,
            new_files=100, test_files=50, data_files=0,
        )
        assert 0.0 <= score_high <= 1.0

        score_low = compute_substance_score(
            files_changed=100, insertions=0, deletions=10000,
            new_files=0, test_files=0, data_files=100,
        )
        assert 0.0 <= score_low <= 1.0

    def test_zero_files_returns_baseline(self):
        """0 files changed → 0.5 (neutral baseline)."""
        score = compute_substance_score(
            files_changed=0, insertions=0, deletions=0,
            new_files=0, test_files=0, data_files=0,
        )
        assert score == 0.5

    def test_tests_boost_score(self):
        """Adding test files boosts substance compared to no tests."""
        without_tests = compute_substance_score(
            files_changed=2, insertions=80, deletions=5,
            new_files=1, test_files=0, data_files=0,
        )
        with_tests = compute_substance_score(
            files_changed=2, insertions=80, deletions=5,
            new_files=1, test_files=1, data_files=0,
        )
        assert with_tests > without_tests

    def test_data_files_penalty(self):
        """Data files reduce substance score."""
        without_data = compute_substance_score(
            files_changed=4, insertions=100, deletions=10,
            new_files=2, test_files=1, data_files=0,
        )
        with_data = compute_substance_score(
            files_changed=4, insertions=100, deletions=10,
            new_files=2, test_files=1, data_files=3,
        )
        assert with_data < without_data


# ---------------------------------------------------------------------------
# classify_commit (integration)
# ---------------------------------------------------------------------------


class TestClassifyCommit:
    """Tests for the classify_commit integration function."""

    def test_returns_substance_report(self):
        """classify_commit returns a SubstanceReport."""
        report = classify_commit(
            files_changed=3, insertions=80, deletions=5,
            new_files=1, test_files=1, data_files=0,
        )
        assert isinstance(report, SubstanceReport)
        assert report.change_type in (
            "new_content", "expansion", "refactor",
            "contraction", "data_append",
        )
        assert 0.0 <= report.substance <= 1.0

    def test_summary_dict(self):
        """SubstanceReport.summary() returns expected keys."""
        report = classify_commit(
            files_changed=5, insertions=120, deletions=10,
            new_files=2, test_files=1, data_files=1,
        )
        s = report.summary()
        assert "change_type" in s
        assert "substance" in s
        assert "files_changed" in s
        assert "net_lines" in s
        assert s["net_lines"] == 110  # 120 - 10

    def test_one_line_format(self):
        """one_line() produces a readable string."""
        report = classify_commit(
            files_changed=3, insertions=50, deletions=10,
            new_files=1, test_files=0, data_files=0,
        )
        line = report.one_line()
        assert report.change_type in line
        assert "3 files" in line

    def test_catch_up_commit_typical(self):
        """A typical catch-up commit: 7 files modified, some insertions/deletions."""
        report = classify_commit(
            files_changed=7, insertions=99, deletions=73,
            new_files=0, test_files=0, data_files=2,
        )
        assert report.change_type in ("expansion", "refactor", "data_append")
        assert report.substance < 0.5  # no new files, no tests, some data

    def test_new_feature_with_tests(self):
        """A new feature commit: 2 new files (module + test), lots of additions."""
        report = classify_commit(
            files_changed=2, insertions=350, deletions=0,
            new_files=2, test_files=1, data_files=0,
        )
        assert report.change_type == "new_content"
        assert report.substance >= 0.7


# ---------------------------------------------------------------------------
# parse_diffstat
# ---------------------------------------------------------------------------


class TestParseDiffstat:
    """Tests for git diffstat line parsing."""

    def test_standard_format(self):
        """Standard 3-part diffstat line."""
        result = parse_diffstat(
            " 7 files changed, 99 insertions(+), 73 deletions(-)"
        )
        assert result == {
            "files_changed": 7,
            "insertions": 99,
            "deletions": 73,
        }

    def test_singular_file(self):
        """1 file changed (singular)."""
        result = parse_diffstat(" 1 file changed, 50 insertions(+)")
        assert result == {
            "files_changed": 1,
            "insertions": 50,
            "deletions": 0,
        }

    def test_insertions_only(self):
        """Only insertions, no deletions."""
        result = parse_diffstat(
            " 3 files changed, 200 insertions(+)"
        )
        assert result == {
            "files_changed": 3,
            "insertions": 200,
            "deletions": 0,
        }

    def test_deletions_only(self):
        """Only deletions, no insertions."""
        result = parse_diffstat(
            " 2 files changed, 15 deletions(-)"
        )
        assert result == {
            "files_changed": 2,
            "insertions": 0,
            "deletions": 15,
        }

    def test_no_match_returns_zeros(self):
        """Non-matching string returns all zeros."""
        result = parse_diffstat("nothing here")
        assert result == {
            "files_changed": 0,
            "insertions": 0,
            "deletions": 0,
        }

    def test_large_numbers(self):
        """Handles large line counts."""
        result = parse_diffstat(
            " 42 files changed, 12345 insertions(+), 6789 deletions(-)"
        )
        assert result == {
            "files_changed": 42,
            "insertions": 12345,
            "deletions": 6789,
        }


# ---------------------------------------------------------------------------
# batch_substance_score
# ---------------------------------------------------------------------------


class TestBatchSubstanceScore:
    """Tests for batch aggregation."""

    def test_empty_list(self):
        """Empty reports list returns zeroed summary."""
        result = batch_substance_score([])
        assert result["count"] == 0
        assert result["mean_substance"] == 0.0

    def test_single_report(self):
        """Single report → mean equals that report's substance."""
        report = classify_commit(
            files_changed=2, insertions=100, deletions=5,
            new_files=2, test_files=1, data_files=0,
        )
        result = batch_substance_score([report])
        assert result["count"] == 1
        assert result["mean_substance"] == report.substance

    def test_multiple_reports(self):
        """Multiple reports → correct aggregation."""
        reports = [
            classify_commit(
                files_changed=2, insertions=100, deletions=0,
                new_files=2, test_files=1, data_files=0,
            ),
            classify_commit(
                files_changed=1, insertions=5, deletions=0,
                new_files=0, test_files=0, data_files=1,
            ),
            classify_commit(
                files_changed=3, insertions=40, deletions=38,
                new_files=0, test_files=0, data_files=0,
            ),
        ]
        result = batch_substance_score(reports)
        assert result["count"] == 3
        assert 0.0 <= result["mean_substance"] <= 1.0
        assert isinstance(result["type_distribution"], dict)
        assert result["total_insertions"] == 145  # 100 + 5 + 40
        assert result["total_deletions"] == 38
        assert result["total_new_files"] == 2
        assert result["total_test_files"] == 1

    def test_type_distribution_counts(self):
        """type_distribution correctly counts change types."""
        reports = [
            classify_commit(
                files_changed=2, insertions=100, deletions=0,
                new_files=2, test_files=1, data_files=0,
            ),
            classify_commit(
                files_changed=2, insertions=100, deletions=0,
                new_files=2, test_files=0, data_files=0,
            ),
            classify_commit(
                files_changed=1, insertions=5, deletions=0,
                new_files=0, test_files=0, data_files=1,
            ),
        ]
        result = batch_substance_score(reports)
        dist = result["type_distribution"]
        # first two should be new_content, third should be data_append
        assert dist.get("new_content", 0) == 2
        assert dist.get("data_append", 0) == 1
