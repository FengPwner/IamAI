#!/usr/bin/env python3
"""Tests for visit_interval_monitor.py — caretaker visit gap analyzer."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from visit_interval_monitor import (
    analyze,
    classify_interval,
    compute_intervals,
    human_summary,
    parse_visits,
)


# ---------------------------------------------------------------------------
# parse_visits
# ---------------------------------------------------------------------------


class TestParseVisits:
    def test_empty_directory(self, tmp_path):
        visits = parse_visits(tmp_path)
        assert visits == []

    def test_nonexistent_directory(self, tmp_path):
        visits = parse_visits(tmp_path / "nonexistent")
        assert visits == []

    def test_parses_date_stamped_visits(self, tmp_path):
        (tmp_path / "caretaker-visit-540-2026-11-04.md").write_text("# visit")
        (tmp_path / "caretaker-visit-541-2026-11-04.md").write_text("# visit")
        (tmp_path / "caretaker-visit-532-2026-11-03.md").write_text("# visit")
        visits = parse_visits(tmp_path)
        assert len(visits) == 3
        # sorted by date then visit number
        assert visits[0]["visit"] == 532
        assert visits[1]["visit"] == 540
        assert visits[2]["visit"] == 541

    def test_ignores_non_date_visits(self, tmp_path):
        (tmp_path / "caretaker-visit-522-commit-signal.md").write_text("# visit")
        (tmp_path / "caretaker-visit-541-2026-11-04.md").write_text("# visit")
        visits = parse_visits(tmp_path)
        assert len(visits) == 1
        assert visits[0]["visit"] == 541

    def test_ignores_non_visit_files(self, tmp_path):
        (tmp_path / "limits.md").write_text("# limits")
        (tmp_path / "reading.md").write_text("# reading")
        visits = parse_visits(tmp_path)
        assert visits == []

    def test_sorts_by_date_then_visit(self, tmp_path):
        (tmp_path / "caretaker-visit-100-2026-10-09.md").write_text("")
        (tmp_path / "caretaker-visit-50-2026-10-06.md").write_text("")
        (tmp_path / "caretaker-visit-200-2026-10-15.md").write_text("")
        visits = parse_visits(tmp_path)
        assert [v["visit"] for v in visits] == [50, 100, 200]


# ---------------------------------------------------------------------------
# compute_intervals
# ---------------------------------------------------------------------------


class TestComputeIntervals:
    def test_empty_list(self):
        assert compute_intervals([]) == []

    def test_single_visit(self):
        visits = [{"visit": 1, "date": None, "filename": "f"}]
        assert compute_intervals(visits) == []

    def test_two_visits_same_day(self, tmp_path):
        from datetime import datetime

        visits = [
            {"visit": 540, "date": datetime(2026, 11, 4), "filename": "a.md"},
            {"visit": 541, "date": datetime(2026, 11, 4), "filename": "b.md"},
        ]
        intervals = compute_intervals(visits)
        assert len(intervals) == 1
        assert intervals[0]["gap_days"] == 0
        assert intervals[0]["visit_diff"] == 1

    def test_two_visits_different_days(self):
        from datetime import datetime

        visits = [
            {"visit": 532, "date": datetime(2026, 11, 3), "filename": "a.md"},
            {"visit": 540, "date": datetime(2026, 11, 4), "filename": "b.md"},
        ]
        intervals = compute_intervals(visits)
        assert len(intervals) == 1
        assert intervals[0]["gap_days"] == 1
        assert intervals[0]["visit_diff"] == 8

    def test_three_visits(self):
        from datetime import datetime

        visits = [
            {"visit": 1, "date": datetime(2026, 10, 1), "filename": "a.md"},
            {"visit": 5, "date": datetime(2026, 10, 2), "filename": "b.md"},
            {"visit": 10, "date": datetime(2026, 10, 5), "filename": "c.md"},
        ]
        intervals = compute_intervals(visits)
        assert len(intervals) == 2
        assert intervals[0]["gap_days"] == 1
        assert intervals[1]["gap_days"] == 3


# ---------------------------------------------------------------------------
# classify_interval
# ---------------------------------------------------------------------------


class TestClassifyInterval:
    def test_cluster(self):
        iv = {"gap_days": 0, "visit_diff": 1}
        assert classify_interval(iv) == "cluster"

    def test_dense(self):
        iv = {"gap_days": 0, "visit_diff": 10}
        assert classify_interval(iv) == "dense"

    def test_healthy_one_day(self):
        iv = {"gap_days": 1, "visit_diff": 5}
        assert classify_interval(iv) == "healthy"

    def test_healthy_two_days(self):
        iv = {"gap_days": 2, "visit_diff": 3}
        assert classify_interval(iv) == "healthy"

    def test_sparse(self):
        iv = {"gap_days": 5, "visit_diff": 20}
        assert classify_interval(iv) == "sparse"

    def test_neglect(self):
        iv = {"gap_days": 10, "visit_diff": 50}
        assert classify_interval(iv) == "neglect"


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


class TestAnalyze:
    def test_insufficient_data_empty(self):
        result = analyze([])
        assert result["status"] == "insufficient_data"
        assert result["exit_code"] == 4

    def test_insufficient_data_one(self):
        result = analyze([{"gap_days": 1, "visit_diff": 1}])
        assert result["status"] == "insufficient_data"

    def test_healthy_pattern(self):
        intervals = [
            {"gap_days": 1, "visit_diff": 5},
            {"gap_days": 1, "visit_diff": 3},
            {"gap_days": 2, "visit_diff": 8},
        ]
        result = analyze(intervals)
        assert result["status"] == "healthy"
        assert result["exit_code"] == 0

    def test_storm_detection(self):
        # 5+ consecutive cluster/dense intervals
        intervals = [
            {"gap_days": 0, "visit_diff": 1},
            {"gap_days": 0, "visit_diff": 1},
            {"gap_days": 0, "visit_diff": 1},
            {"gap_days": 0, "visit_diff": 1},
            {"gap_days": 0, "visit_diff": 1},
        ]
        result = analyze(intervals)
        assert result["status"] == "storm"
        assert result["exit_code"] == 2

    def test_neglect_detection(self):
        intervals = [
            {"gap_days": 1, "visit_diff": 5},
            {"gap_days": 30, "visit_diff": 100},
        ]
        result = analyze(intervals)
        assert result["status"] == "neglect"
        assert result["exit_code"] == 3

    def test_max_consecutive_clusters(self):
        intervals = [
            {"gap_days": 0, "visit_diff": 1},
            {"gap_days": 0, "visit_diff": 1},
            {"gap_days": 1, "visit_diff": 5},  # breaks the run
            {"gap_days": 0, "visit_diff": 1},
            {"gap_days": 0, "visit_diff": 1},
            {"gap_days": 0, "visit_diff": 1},
        ]
        result = analyze(intervals)
        assert result["max_consecutive_clusters"] == 3


# ---------------------------------------------------------------------------
# human_summary
# ---------------------------------------------------------------------------


class TestHumanSummary:
    def test_insufficient_data_message(self):
        analysis = {"status": "insufficient_data", "total_intervals": 1}
        msg = human_summary(analysis)
        assert "insufficient data" in msg
        assert "1" in msg

    def test_healthy_message(self):
        analysis = {
            "status": "healthy",
            "total_intervals": 10,
            "max_gap_days": 3,
            "max_consecutive_clusters": 1,
            "classifications": {"healthy": 8, "sparse": 2},
        }
        msg = human_summary(analysis)
        assert "healthy" in msg
        assert "10" in msg

    def test_storm_message(self):
        analysis = {
            "status": "storm",
            "total_intervals": 20,
            "max_gap_days": 0,
            "max_consecutive_clusters": 15,
            "classifications": {"cluster": 18, "dense": 2},
        }
        msg = human_summary(analysis)
        assert "storm" in msg


# ---------------------------------------------------------------------------
# integration: parse from real temp directory
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_pipeline(self, tmp_path):
        from datetime import datetime

        # create a sequence of visit notes
        for i, d in enumerate([
            "2026-10-01", "2026-10-02", "2026-10-03",
            "2026-10-04", "2026-10-05", "2026-10-10",
        ], start=1):
            fname = f"caretaker-visit-{i}-{d}.md"
            (tmp_path / fname).write_text(f"# visit {i}")

        visits = parse_visits(tmp_path)
        assert len(visits) == 6

        intervals = compute_intervals(visits)
        assert len(intervals) == 5
        # last interval should be 5 days (sparse)
        assert intervals[-1]["gap_days"] == 5

        result = analyze(intervals)
        assert result["status"] in ("healthy", "sparse", "warning")
        assert result["exit_code"] in (0, 1)
