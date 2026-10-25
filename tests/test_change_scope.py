"""Tests for iamai.change_scope — commit change scope classification."""

import pytest

from iamai.change_scope import (
    ChangeScope,
    ScopeLabel,
    classify_commit,
    scope_distribution,
)


# ---------------------------------------------------------------------------
# Basic classification
# ---------------------------------------------------------------------------

class TestClassifyBasic:
    def test_empty_commit(self):
        cs = ChangeScope()
        assert cs.classify(files=0, additions=0, deletions=0) == "empty"

    def test_trivial_one_file_few_lines(self):
        cs = ChangeScope()
        assert cs.classify(files=1, additions=5, deletions=3) == "small"

    def test_trivial_one_file_zero_lines(self):
        """One file, no actual changes — trivial on both dimensions."""
        cs = ChangeScope()
        # files=1 → trivial file scope; lines=0 → trivial line scope
        assert cs.classify(files=1, additions=0, deletions=0) == "trivial"

    def test_small(self):
        cs = ChangeScope()
        assert cs.classify(files=3, additions=20, deletions=5) == "small"

    def test_normal(self):
        cs = ChangeScope()
        assert cs.classify(files=5, additions=100, deletions=50) == "normal"

    def test_large_by_files(self):
        cs = ChangeScope()
        assert cs.classify(files=20, additions=50, deletions=10) == "large"

    def test_large_by_lines(self):
        cs = ChangeScope()
        assert cs.classify(files=2, additions=400, deletions=100) == "large"

    def test_massive_by_files(self):
        cs = ChangeScope()
        assert cs.classify(files=50, additions=10, deletions=5) == "massive"

    def test_massive_by_lines(self):
        cs = ChangeScope()
        assert cs.classify(files=2, additions=3000, deletions=2000) == "massive"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestClassifyEdgeCases:
    def test_negative_files_clamped(self):
        cs = ChangeScope()
        # Negative values clamped to 0
        assert cs.classify(files=-5, additions=0, deletions=0) == "empty"

    def test_negative_lines_clamped(self):
        cs = ChangeScope()
        # additions and deletions clamped to 0; files=2 → small; max(small, trivial) = small
        assert cs.classify(files=2, additions=-10, deletions=-5) == "small"

    def test_zero_files_some_lines(self):
        """0 files but nonzero lines — file dim is empty, line dim is small."""
        cs = ChangeScope()
        # max("empty", "small") => "small"
        assert cs.classify(files=0, additions=10, deletions=0) == "small"

    def test_boundary_small_files(self):
        cs = ChangeScope()
        # Exactly at small_files boundary (default 3)
        assert cs.classify(files=3, additions=10, deletions=0) == "small"

    def test_boundary_normal_files(self):
        cs = ChangeScope()
        # Exactly at normal_files boundary (default 10)
        assert cs.classify(files=10, additions=10, deletions=0) == "normal"

    def test_boundary_large_files(self):
        cs = ChangeScope()
        # Exactly at large_files boundary (default 30)
        assert cs.classify(files=30, additions=10, deletions=0) == "large"

    def test_boundary_small_lines(self):
        cs = ChangeScope()
        # files=2 → small file; lines=30 → small line; max = small
        assert cs.classify(files=2, additions=20, deletions=10) == "small"

    def test_boundary_normal_lines(self):
        cs = ChangeScope()
        # files=2 → small file; lines=200 → normal line; max = normal
        assert cs.classify(files=2, additions=150, deletions=50) == "normal"

    def test_boundary_large_lines(self):
        cs = ChangeScope()
        # files=1 → trivial; lines=1000 → large; max = large
        assert cs.classify(files=1, additions=600, deletions=400) == "large"

    def test_file_dominant(self):
        """Many files, few lines — file dimension wins."""
        cs = ChangeScope()
        assert cs.classify(files=15, additions=1, deletions=1) == "large"

    def test_line_dominant(self):
        """Few files, many lines — line dimension wins."""
        cs = ChangeScope()
        assert cs.classify(files=1, additions=2000, deletions=0) == "massive"


# ---------------------------------------------------------------------------
# Custom thresholds
# ---------------------------------------------------------------------------

class TestCustomThresholds:
    def test_tight_thresholds(self):
        cs = ChangeScope(
            small_files=1, normal_files=2, large_files=5,
            small_lines=10, normal_lines=50, large_lines=100,
        )
        assert cs.classify(files=3, additions=20, deletions=10) == "large"
        assert cs.classify(files=6, additions=5, deletions=0) == "massive"

    def test_loose_thresholds(self):
        cs = ChangeScope(
            small_files=10, normal_files=50, large_files=200,
            small_lines=100, normal_lines=1000, large_lines=10000,
        )
        # files=20 → normal (10 < 20 ≤ 50); lines=300 → normal (100 < 300 ≤ 1000)
        assert cs.classify(files=20, additions=200, deletions=100) == "normal"


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

class TestAnomaly:
    def test_empty_is_anomaly(self):
        cs = ChangeScope()
        assert cs.is_anomaly(files=0, additions=0, deletions=0) is True

    def test_massive_is_anomaly(self):
        cs = ChangeScope()
        assert cs.is_anomaly(files=50, additions=100, deletions=100) is True

    def test_zero_change_touch_is_anomaly(self):
        """Files touched but no lines changed."""
        cs = ChangeScope()
        assert cs.is_anomaly(files=5, additions=0, deletions=0) is True

    def test_pure_deletion_is_anomaly(self):
        cs = ChangeScope()
        assert cs.is_anomaly(files=2, additions=0, deletions=50) is True

    def test_normal_commit_not_anomaly(self):
        cs = ChangeScope()
        assert cs.is_anomaly(files=3, additions=50, deletions=10) is False

    def test_small_commit_not_anomaly(self):
        cs = ChangeScope()
        assert cs.is_anomaly(files=1, additions=10, deletions=5) is False

    def test_additions_only_not_anomaly(self):
        cs = ChangeScope()
        assert cs.is_anomaly(files=2, additions=30, deletions=0) is False

    def test_large_but_not_massive_not_anomaly(self):
        cs = ChangeScope()
        # large scope is not automatically anomalous
        assert cs.is_anomaly(files=15, additions=200, deletions=100) is False


# ---------------------------------------------------------------------------
# Record and history
# ---------------------------------------------------------------------------

class TestRecordAndHistory:
    def test_record_returns_dict(self):
        cs = ChangeScope()
        entry = cs.record(files=3, additions=50, deletions=10, timestamp=1000.0)
        assert entry["files"] == 3
        assert entry["additions"] == 50
        assert entry["deletions"] == 10
        assert entry["total_lines"] == 60
        assert entry["label"] in ("empty", "trivial", "small", "normal", "large", "massive")
        assert isinstance(entry["anomaly"], bool)
        assert entry["timestamp"] == 1000.0

    def test_history_accumulates(self):
        cs = ChangeScope()
        cs.record(files=1, additions=10, deletions=5)
        cs.record(files=5, additions=100, deletions=50)
        cs.record(files=2, additions=20, deletions=10)
        assert len(cs.history()) == 3

    def test_history_is_copy(self):
        cs = ChangeScope()
        cs.record(files=1, additions=10, deletions=5)
        h = cs.history()
        h.append({"fake": True})
        assert len(cs.history()) == 1

    def test_record_anomaly_flagged(self):
        cs = ChangeScope()
        entry = cs.record(files=0, additions=0, deletions=0)
        assert entry["anomaly"] is True
        assert entry["label"] == "empty"


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

class TestSummary:
    def test_empty_summary(self):
        cs = ChangeScope()
        s = cs.summary()
        assert s["total_commits"] == 0
        assert s["labels"] == {}
        assert s["anomaly_count"] == 0
        assert s["anomaly_rate"] == 0.0
        assert s["avg_files"] == 0.0
        assert s["avg_lines"] == 0.0

    def test_summary_with_data(self):
        cs = ChangeScope()
        cs.record(files=2, additions=50, deletions=10)  # small, no anomaly
        cs.record(files=5, additions=100, deletions=50)  # normal, no anomaly
        cs.record(files=0, additions=0, deletions=0)  # empty, anomaly
        s = cs.summary()
        assert s["total_commits"] == 3
        assert s["anomaly_count"] == 1
        assert s["anomaly_rate"] == pytest.approx(1 / 3, abs=0.01)
        assert s["avg_files"] == pytest.approx(7 / 3, abs=0.1)
        assert s["avg_lines"] == pytest.approx(210 / 3, abs=0.1)

    def test_summary_label_distribution(self):
        cs = ChangeScope()
        cs.record(files=1, additions=5, deletions=2)  # files=1→trivial, lines=7→small → small
        cs.record(files=1, additions=5, deletions=2)  # same
        cs.record(files=5, additions=100, deletions=50)  # files=5→normal, lines=150→normal → normal
        s = cs.summary()
        assert s["labels"].get("small", 0) == 2
        assert s["labels"].get("normal", 0) == 1


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

class TestReset:
    def test_reset_clears_history(self):
        cs = ChangeScope()
        cs.record(files=3, additions=50, deletions=10)
        cs.record(files=2, additions=20, deletions=5)
        assert len(cs.history()) == 2
        cs.reset()
        assert len(cs.history()) == 0
        assert cs.summary()["total_commits"] == 0


# ---------------------------------------------------------------------------
# Module-level functions
# ---------------------------------------------------------------------------

class TestClassifyCommit:
    def test_basic(self):
        # files=3 → small; lines=60 → normal; max = normal
        assert classify_commit(files=3, additions=50, deletions=10) == "normal"

    def test_custom_thresholds(self):
        # files=5 with normal_files=3, large_files=10 → large; lines=30 → small
        result = classify_commit(
            files=5, additions=20, deletions=10,
            thresholds={"small_files": 1, "normal_files": 3, "large_files": 10},
        )
        assert result == "large"

    def test_empty(self):
        assert classify_commit(files=0) == "empty"


class TestScopeDistribution:
    def test_basic_distribution(self):
        commits = [
            {"files": 1, "additions": 5, "deletions": 2},
            {"files": 5, "additions": 100, "deletions": 50},
            {"files": 50, "additions": 2000, "deletions": 1000},
        ]
        dist = scope_distribution(commits)
        assert dist["total"] == 3
        assert dist["anomaly_count"] >= 1  # massive is anomalous

    def test_empty_list(self):
        dist = scope_distribution([])
        assert dist["total"] == 0
        assert dist["labels"] == {}
        assert dist["anomaly_count"] == 0
        assert dist["anomalies"] == []

    def test_anomalies_include_index(self):
        commits = [
            {"files": 3, "additions": 50, "deletions": 10},  # normal
            {"files": 0, "additions": 0, "deletions": 0},  # anomaly
        ]
        dist = scope_distribution(commits)
        assert dist["anomaly_count"] == 1
        assert dist["anomalies"][0]["index"] == 1

    def test_all_normal(self):
        commits = [
            {"files": 3, "additions": 50, "deletions": 10},
            {"files": 5, "additions": 80, "deletions": 30},
        ]
        dist = scope_distribution(commits)
        assert dist["anomaly_count"] == 0

    def test_custom_thresholds(self):
        commits = [{"files": 5, "additions": 20, "deletions": 10}]
        dist = scope_distribution(
            commits,
            thresholds={"small_files": 1, "normal_files": 3, "large_files": 10},
        )
        assert dist["total"] == 1
