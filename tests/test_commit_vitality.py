#!/usr/bin/env python3
"""Tests for tools/commit_vitality.py — composite commit health scorer."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from commit_vitality import (
    DimensionScore,
    VitalityReport,
    _count_uncommitted,
    _count_unpushed,
    grade,
    measure,
    run,
    score_backlog,
    score_push_sync,
    score_recency,
    score_regularity,
    score_substance,
    as_text,
)


# ── score_recency ─────────────────────────────────────────────────────


class TestScoreRecency:
    def test_fresh_at_zero(self):
        d = score_recency(0, 600)
        assert d.score == 20.0

    def test_fresh_at_interval_boundary(self):
        d = score_recency(600, 600)
        assert d.score == 20.0

    def test_fresh_just_under_interval(self):
        d = score_recency(599, 600)
        assert d.score == 20.0

    def test_decay_midway(self):
        d = score_recency(3 * 600, 600)
        # (3*600 - 600) / (4*600) = 1200/2400 = 0.5 → score = 10
        assert d.score == 10.0

    def test_zero_at_5x(self):
        d = score_recency(5 * 600, 600)
        assert d.score == 0.0

    def test_zero_beyond_5x(self):
        d = score_recency(10 * 600, 600)
        assert d.score == 0.0

    def test_decay_linear(self):
        # at 2× interval: (1200-600)/(2400) = 0.25 → score = 15
        d = score_recency(1200, 600)
        assert d.score == 15.0

    def test_small_interval_fresh(self):
        d = score_recency(30, 60)
        assert d.score == 20.0

    def test_small_interval_dead(self):
        d = score_recency(600, 60)
        assert d.score == 0.0

    def test_name_is_recency(self):
        d = score_recency(100, 600)
        assert d.name == "recency"

    def test_max_is_20(self):
        d = score_recency(100, 600)
        assert d.max == 20.0


# ── score_regularity ─────────────────────────────────────────────────


class TestScoreRegularity:
    def test_empty_intervals(self):
        d = score_regularity([], 600)
        assert d.score == 0.0

    def test_single_interval_exact(self):
        d = score_regularity([600.0], 600)
        assert d.score == 20.0

    def test_single_interval_double(self):
        d = score_regularity([1200.0], 600)
        assert d.score == 10.0

    def test_perfect_regularity(self):
        d = score_regularity([600, 600, 600, 600, 600], 600)
        assert d.score == 20.0  # cv=0

    def test_moderate_irregularity(self):
        d = score_regularity([400, 600, 800, 600, 600], 600)
        # cv > 0 but < 1.5, so 0 < score < 20
        assert 0 < d.score < 20

    def test_high_variance(self):
        d = score_regularity([100, 2000, 50, 3000, 100], 600)
        # cv should be high → low score
        assert d.score < 10

    def test_name_is_regularity(self):
        d = score_regularity([600], 600)
        assert d.name == "regularity"


# ── score_substance ──────────────────────────────────────────────────


class TestScoreSubstance:
    def test_zero_files(self):
        d = score_substance(0.0)
        assert d.score == 0.0

    def test_one_file(self):
        d = score_substance(1.0)
        assert d.score == 4.0

    def test_five_files_max(self):
        d = score_substance(5.0)
        assert d.score == 20.0

    def test_more_than_five_caps(self):
        d = score_substance(10.0)
        assert d.score == 20.0

    def test_fractional(self):
        d = score_substance(2.5)
        assert d.score == 10.0

    def test_name_is_substance(self):
        d = score_substance(3.0)
        assert d.name == "substance"


# ── score_backlog ────────────────────────────────────────────────────


class TestScoreBacklog:
    def test_zero_uncommitted(self):
        d = score_backlog(0)
        assert d.score == 20.0

    def test_one_uncommitted(self):
        d = score_backlog(1)
        assert d.score == 16.0

    def test_five_uncommitted(self):
        d = score_backlog(5)
        assert d.score == 0.0

    def test_many_uncommitted_floor(self):
        d = score_backlog(10)
        assert d.score == 0.0

    def test_name_is_backlog(self):
        d = score_backlog(0)
        assert d.name == "backlog"


# ── score_push_sync ──────────────────────────────────────────────────


class TestScorePushSync:
    def test_zero_unpushed(self):
        d = score_push_sync(0)
        assert d.score == 20.0

    def test_one_unpushed(self):
        d = score_push_sync(1)
        assert d.score == 15.0

    def test_four_unpushed(self):
        d = score_push_sync(4)
        assert d.score == 0.0

    def test_many_unpushed_floor(self):
        d = score_push_sync(10)
        assert d.score == 0.0

    def test_name_is_push_sync(self):
        d = score_push_sync(0)
        assert d.name == "push_sync"


# ── grade ────────────────────────────────────────────────────────────


class TestGrade:
    def test_a_at_85(self):
        assert grade(85) == "A"

    def test_a_at_100(self):
        assert grade(100) == "A"

    def test_b_at_70(self):
        assert grade(70) == "B"

    def test_b_at_84(self):
        assert grade(84.99) == "B"

    def test_c_at_50(self):
        assert grade(50) == "C"

    def test_c_at_69(self):
        assert grade(69.99) == "C"

    def test_d_at_30(self):
        assert grade(30) == "D"

    def test_d_at_49(self):
        assert grade(49.99) == "D"

    def test_f_at_0(self):
        assert grade(0) == "F"

    def test_f_at_29(self):
        assert grade(29.99) == "F"


# ── measure (integration, mocked git) ────────────────────────────────


def _make_report(
    age=300.0,
    intervals=None,
    avg_files=3.0,
    uncommitted=0,
    unpushed=0,
) -> VitalityReport:
    """Build a report with controlled inputs via patches."""
    if intervals is None:
        intervals = [600, 600, 600, 600]
    with patch("commit_vitality._recent_commit_age", return_value=age), \
         patch("commit_vitality._recent_intervals", return_value=intervals), \
         patch("commit_vitality._avg_files_changed", return_value=avg_files), \
         patch("commit_vitality._count_uncommitted", return_value=uncommitted), \
         patch("commit_vitality._count_unpushed", return_value=unpushed):
        return measure(interval=600)


class TestMeasure:
    def test_perfect_pipeline(self):
        r = _make_report(age=100, intervals=[600]*10, avg_files=5.0,
                         uncommitted=0, unpushed=0)
        assert r.total == 100.0
        assert r.grade == "A"

    def test_stale_commit_penalises_recency(self):
        r = _make_report(age=3000)
        recency = [d for d in r.dimensions if d.name == "recency"][0]
        assert recency.score == 0.0

    def test_backlog_penalises(self):
        r = _make_report(uncommitted=5)
        backlog = [d for d in r.dimensions if d.name == "backlog"][0]
        assert backlog.score == 0.0

    def test_unpushed_penalises(self):
        r = _make_report(unpushed=3)
        ps = [d for d in r.dimensions if d.name == "push_sync"][0]
        assert ps.score == 5.0  # 20 - 3*5

    def test_five_dimensions(self):
        r = _make_report()
        assert len(r.dimensions) == 5

    def test_total_is_sum(self):
        r = _make_report()
        expected = round(sum(d.score for d in r.dimensions), 2)
        assert r.total == expected

    def test_grade_matches_total(self):
        r = _make_report()
        assert r.grade == grade(r.total)

    def test_report_has_timestamp(self):
        r = _make_report()
        assert r.timestamp  # non-empty ISO string

    def test_no_intervals_zero_regularity(self):
        r = _make_report(intervals=[])
        reg = [d for d in r.dimensions if d.name == "regularity"][0]
        assert reg.score == 0.0


# ── as_text ───────────────────────────────────────────────────────────


class TestAsText:
    def test_contains_grade(self):
        r = _make_report()
        txt = as_text(r)
        assert "grade" in txt

    def test_contains_all_dimensions(self):
        r = _make_report()
        txt = as_text(r)
        for d in r.dimensions:
            assert d.name in txt

    def test_contains_vitality(self):
        r = _make_report()
        txt = as_text(r)
        assert "commit vitality" in txt


# ── run (CLI wrapper) ────────────────────────────────────────────────


class TestRun:
    def test_json_output(self, capsys):
        with patch("commit_vitality.measure", return_value=_make_report()):
            code = run(as_json=True)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "total" in data
        assert "grade" in data
        assert "dimensions" in data

    def test_text_output(self, capsys):
        with patch("commit_vitality.measure", return_value=_make_report()):
            code = run(as_json=False)
        out = capsys.readouterr().out
        assert "commit vitality" in out

    def test_exit_code_a_is_zero(self):
        r = _make_report(age=100, intervals=[600]*10, avg_files=5.0,
                         uncommitted=0, unpushed=0)
        with patch("commit_vitality.measure", return_value=r):
            code = run()
        assert code == 0

    def test_exit_code_f_is_three(self):
        r = _make_report(age=99999, intervals=[], avg_files=0.0,
                         uncommitted=20, unpushed=20)
        with patch("commit_vitality.measure", return_value=r):
            code = run()
        assert code == 3
