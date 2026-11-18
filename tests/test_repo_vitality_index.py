#!/usr/bin/env python3
"""Tests for repo_vitality_index.py — composite repo health scoring."""

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.repo_vitality_index import (
    VitalityReport,
    _clamp,
    _is_substantive,
    _parse_ts,
    _to_epoch,
    assess,
    cadence_regularity_score,
    classify,
    commit_hygiene_score,
    content_freshness_score,
    grade,
    stall_resilience_score,
    stroke_diversity_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 11, 19, 3, 0, 0, tzinfo=timezone.utc)
_BASE_EPOCH = _BASE.timestamp()

_KINDS = ["thought", "note", "snippet", "devlog", "garden", "metrics"]


def _ts(offset_seconds: float) -> str:
    dt = _BASE + timedelta(seconds=offset_seconds)
    return dt.isoformat()


def _make_strokes(offsets: list, kind: str = "thought") -> list:
    return [
        {"seq": i, "at": _ts(s), "kind": kind, "text": f"stroke {i}"}
        for i, s in enumerate(offsets)
    ]


def _make_mixed_strokes(offsets: list, kinds: list) -> list:
    return [
        {"seq": i, "at": _ts(s), "kind": kinds[i % len(kinds)], "text": f"s {i}"}
        for i, s in enumerate(offsets)
    ]


def _make_commits(messages: list) -> list:
    return [
        {"at": _ts(i * 600), "message": m} for i, m in enumerate(messages)
    ]


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

class TestParseTimestamp:
    def test_iso_with_tz(self):
        dt = _parse_ts("2026-11-19T03:00:00+00:00")
        assert dt.year == 2026

    def test_z_suffix(self):
        dt = _parse_ts("2026-11-19T03:00:00Z")
        assert dt.tzinfo is not None

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _parse_ts("not-a-date")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _parse_ts("")


class TestToEpoch:
    def test_positive(self):
        dt = datetime(2026, 11, 19, 3, 0, 0, tzinfo=timezone.utc)
        assert _to_epoch(dt) > 0

    def test_roundtrip(self):
        dt = datetime(2026, 11, 19, 3, 0, 0, tzinfo=timezone.utc)
        epoch = _to_epoch(dt)
        dt2 = datetime.fromtimestamp(epoch, tz=timezone.utc)
        assert dt2.year == dt.year
        assert dt2.hour == dt.hour


# ---------------------------------------------------------------------------
# Grading helpers
# ---------------------------------------------------------------------------

class TestGrade:
    def test_a(self):
        assert grade(95) == "A"
        assert grade(90) == "A"

    def test_b(self):
        assert grade(89) == "B"
        assert grade(70) == "B"

    def test_c(self):
        assert grade(69) == "C"
        assert grade(50) == "C"

    def test_d(self):
        assert grade(49) == "D"
        assert grade(30) == "D"

    def test_f(self):
        assert grade(29) == "F"
        assert grade(0) == "F"


class TestClassify:
    def test_thriving(self):
        assert classify(80) == "thriving"
        assert classify(100) == "thriving"

    def test_healthy(self):
        assert classify(60) == "healthy"
        assert classify(79) == "healthy"

    def test_stressed(self):
        assert classify(40) == "stressed"
        assert classify(59) == "stressed"

    def test_critical(self):
        assert classify(20) == "critical"
        assert classify(39) == "critical"

    def test_dormant(self):
        assert classify(0) == "dormant"
        assert classify(19) == "dormant"


class TestClamp:
    def test_within_range(self):
        assert _clamp(50) == 50

    def test_below(self):
        assert _clamp(-10) == 0

    def test_above(self):
        assert _clamp(200) == 100


# ---------------------------------------------------------------------------
# Vital sign 1: cadence regularity
# ---------------------------------------------------------------------------

class TestCadenceRegularity:
    def test_perfect_cadence(self):
        """All gaps exactly 15 s → CV = 0 → score 100."""
        offsets = [i * 15 for i in range(20)]
        score = cadence_regularity_score(_make_strokes(offsets))
        assert score == pytest.approx(100.0)

    def test_moderate_variance(self):
        """Gaps oscillate ±50 % → CV ≈ 0.5 → score ≈ 75."""
        offsets = [0, 20, 30, 50, 60, 80, 90, 110, 120, 140]
        score = cadence_regularity_score(_make_strokes(offsets))
        assert 50 < score < 95

    def test_high_variance(self):
        """Wildly irregular gaps → low score."""
        offsets = [0, 1, 1000, 1001, 5000, 5002, 20000]
        score = cadence_regularity_score(_make_strokes(offsets))
        assert score < 40

    def test_single_stroke(self):
        """Fewer than 2 strokes → neutral 50."""
        score = cadence_regularity_score(_make_strokes([0]))
        assert score == 50.0

    def test_empty(self):
        score = cadence_regularity_score([])
        assert score == 50.0

    def test_two_strokes_perfect(self):
        score = cadence_regularity_score(_make_strokes([0, 15]))
        assert score == pytest.approx(100.0)

    def test_clamped_at_zero(self):
        """CV > 2 → score clamped to 0."""
        offsets = [0, 1, 100000, 100001]
        score = cadence_regularity_score(_make_strokes(offsets))
        assert score >= 0


# ---------------------------------------------------------------------------
# Vital sign 2: content freshness
# ---------------------------------------------------------------------------

class TestContentFreshness:
    def test_very_fresh(self):
        """Stroke 1 second ago → score near 100."""
        now = _BASE + timedelta(seconds=1)
        strokes = _make_strokes([0])
        score = content_freshness_score(strokes, now=now, half_life_seconds=3600)
        assert score > 99

    def test_one_half_life(self):
        """Stroke exactly one half-life ago → score ≈ 50."""
        strokes = _make_strokes([0])
        now = _BASE + timedelta(seconds=3600)
        score = content_freshness_score(strokes, now=now, half_life_seconds=3600)
        assert score == pytest.approx(50.0)

    def test_two_half_lives(self):
        """Stroke two half-lives ago → score ≈ 25."""
        strokes = _make_strokes([0])
        now = _BASE + timedelta(seconds=7200)
        score = content_freshness_score(strokes, now=now, half_life_seconds=3600)
        assert score == pytest.approx(25.0)

    def test_very_old(self):
        """Stroke 10 half-lives ago → score near 0."""
        strokes = _make_strokes([0])
        now = _BASE + timedelta(seconds=36000)
        score = content_freshness_score(strokes, now=now, half_life_seconds=3600)
        assert score < 1

    def test_empty_strokes(self):
        score = content_freshness_score([], now=_BASE)
        assert score == 0.0

    def test_newest_wins(self):
        """Only the newest stroke matters."""
        strokes = _make_strokes([0, 100, 200])
        now = _BASE + timedelta(seconds=200)
        score = content_freshness_score(strokes, now=now, half_life_seconds=3600)
        assert score == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Vital sign 3: commit hygiene
# ---------------------------------------------------------------------------

class TestCommitHygiene:
    def test_all_substantive(self):
        commits = _make_commits([
            "add stroke_burst_detector module + 45 tests",
            "refactor push_reconcile for clarity",
            "implement commit_substance analyzer",
        ])
        assert commit_hygiene_score(commits) == pytest.approx(100.0)

    def test_all_low_value(self):
        commits = _make_commits([
            "catch-up: commit pending changes",
            "Merge branch 'main'",
            "fixup! previous commit",
        ])
        assert commit_hygiene_score(commits) == pytest.approx(0.0)

    def test_mixed(self):
        commits = _make_commits([
            "add new analysis module",
            "catch-up: pending changes",
            "refactor writer loop",
            "Merge pull request #42",
        ])
        assert commit_hygiene_score(commits) == pytest.approx(50.0)

    def test_empty(self):
        assert commit_hygiene_score([]) == 50.0

    def test_wip_is_low_value(self):
        assert not _is_substantive("WIP: working on it")

    def test_rebase_is_low_value(self):
        assert not _is_substantive("rebase onto main")


class TestIsSubstantive:
    def test_normal_commit(self):
        assert _is_substantive("add new feature")

    def test_catch_up(self):
        assert not _is_substantive("catch-up: commit pending")

    def test_merge(self):
        assert not _is_substantive("Merge branch 'feature'")

    def test_fixup(self):
        assert not _is_substantive("fixup! previous")

    def test_case_insensitive(self):
        assert not _is_substantive("CATCH-UP: blah")
        assert not _is_substantive("MERGE branch foo")


# ---------------------------------------------------------------------------
# Vital sign 4: stall resilience
# ---------------------------------------------------------------------------

class TestStallResilience:
    def test_no_stalls(self):
        """All gaps below threshold → 100."""
        offsets = [i * 15 for i in range(20)]
        score = stall_resilience_score(
            _make_strokes(offsets), stall_threshold_seconds=300
        )
        assert score == 100.0

    def test_moderate_stall(self):
        """One 1-hour stall in a 24-hour window."""
        offsets = [0, 15, 30, 3600 + 30, 3600 + 45]
        score = stall_resilience_score(
            _make_strokes(offsets),
            window_seconds=86400,
            stall_threshold_seconds=300,
        )
        # longest stall = 3570 s; score = 100 × (1 − 3570/86400) ≈ 95.9
        expected = 100.0 * (1.0 - 3570.0 / 86400.0)
        assert score == pytest.approx(expected, abs=0.5)

    def test_massive_stall(self):
        """A 12-hour stall → score near 50."""
        offsets = [0, 15, 43200 + 15, 43200 + 30]
        score = stall_resilience_score(
            _make_strokes(offsets),
            window_seconds=86400,
            stall_threshold_seconds=300,
        )
        expected = 100.0 * (1.0 - 43185.0 / 86400.0)
        assert score == pytest.approx(expected, abs=0.5)

    def test_stall_exceeds_window(self):
        """Stall longer than window → clamped to 0."""
        offsets = [0, 100000]
        score = stall_resilience_score(
            _make_strokes(offsets),
            window_seconds=86400,
            stall_threshold_seconds=300,
        )
        assert score == 0.0

    def test_single_stroke(self):
        score = stall_resilience_score(_make_strokes([0]))
        assert score == 50.0

    def test_empty(self):
        score = stall_resilience_score([])
        assert score == 50.0


# ---------------------------------------------------------------------------
# Vital sign 5: stroke diversity
# ---------------------------------------------------------------------------

class TestStrokeDiversity:
    def test_uniform_distribution(self):
        """Equal counts across 6 kinds → entropy ratio near 1.0 → score near 100."""
        offsets = list(range(60))
        strokes = _make_mixed_strokes(offsets, _KINDS)
        score = stroke_diversity_score(strokes, expected_kinds=_KINDS)
        assert score > 95

    def test_single_kind(self):
        """All strokes same kind → score 0."""
        strokes = _make_strokes(list(range(20)), kind="thought")
        score = stroke_diversity_score(strokes)
        assert score == 0.0

    def test_two_kinds_balanced(self):
        """50/50 split of 2 kinds → score 100 (max for 2 kinds)."""
        offsets = list(range(20))
        strokes = _make_mixed_strokes(offsets, ["thought", "note"])
        score = stroke_diversity_score(strokes, expected_kinds=["thought", "note"])
        assert score == pytest.approx(100.0)

    def test_skewed_distribution(self):
        """One dominant kind → lower score."""
        strokes = []
        for i in range(100):
            kind = "thought" if i < 95 else _KINDS[i % len(_KINDS)]
            strokes.append({"seq": i, "at": _ts(i * 15), "kind": kind, "text": f"s{i}"})
        score = stroke_diversity_score(strokes, expected_kinds=_KINDS)
        assert score < 50

    def test_empty(self):
        assert stroke_diversity_score([]) == 0.0

    def test_single_stroke(self):
        assert stroke_diversity_score([{"kind": "thought"}]) == 0.0


# ---------------------------------------------------------------------------
# Composite assessment
# ---------------------------------------------------------------------------

class TestAssess:
    def test_thriving_repo(self):
        """All signals strong → thriving."""
        offsets = [i * 15 for i in range(40)]
        strokes = _make_mixed_strokes(offsets, _KINDS)
        commits = _make_commits([
            "add new module",
            "refactor core",
            "implement tests",
        ])
        now = _BASE + timedelta(seconds=offsets[-1] + 10)
        report = assess(strokes, commits, now=now, expected_kinds=_KINDS)
        assert report.vitality >= 70
        assert report.vitality_class in ("thriving", "healthy")

    def test_dormant_repo(self):
        """Very old, single-kind, with stalls → low vitality."""
        strokes = _make_strokes([0, 50000, 100000], kind="thought")
        commits = _make_commits(["catch-up: pending", "Merge branch 'main'"])
        now = _BASE + timedelta(seconds=200000)
        report = assess(strokes, commits, now=now)
        assert report.vitality < 40

    def test_report_grades(self):
        offsets = [i * 15 for i in range(20)]
        strokes = _make_strokes(offsets)
        commits = _make_commits(["add feature"])
        now = _BASE + timedelta(seconds=offsets[-1] + 5)
        report = assess(strokes, commits, now=now)
        g = report.grades
        assert "cadence" in g
        assert "vitality" in g
        assert all(v in ("A", "B", "C", "D", "F") for v in g.values())

    def test_summary_format(self):
        offsets = [i * 15 for i in range(10)]
        strokes = _make_strokes(offsets)
        commits = _make_commits(["add feature"])
        now = _BASE + timedelta(seconds=offsets[-1] + 5)
        report = assess(strokes, commits, now=now)
        s = report.summary()
        assert "vitality=" in s
        assert "grade=" in s

    def test_to_dict(self):
        offsets = [i * 15 for i in range(10)]
        strokes = _make_strokes(offsets)
        commits = _make_commits(["add feature"])
        now = _BASE + timedelta(seconds=offsets[-1] + 5)
        report = assess(strokes, commits, now=now)
        d = report.to_dict()
        assert "vitality" in d
        assert "vitality_class" in d
        assert "grades" in d
        assert isinstance(d["grades"], dict)

    def test_custom_parameters(self):
        offsets = [i * 30 for i in range(20)]
        strokes = _make_strokes(offsets)
        commits = _make_commits(["add feature"])
        now = _BASE + timedelta(seconds=offsets[-1] + 5)
        report = assess(
            strokes, commits,
            now=now,
            target_gap=30.0,
            freshness_half_life=7200.0,
            stall_window=43200.0,
            stall_threshold=600.0,
        )
        assert report.vitality >= 0

    def test_empty_inputs(self):
        report = assess([], [], now=_BASE)
        # all defaults → vitality should be some number in [0, 100]
        assert 0 <= report.vitality <= 100


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_identical_timestamps(self):
        """All strokes at the same time → gaps are all 0."""
        strokes = _make_strokes([0, 0, 0, 0, 0])
        score = cadence_regularity_score(strokes)
        # mean gap = 0 → score = 0
        assert score == 0.0

    def test_negative_age_clamped(self):
        """Stroke in the 'future' relative to now → age < 0 → clamped."""
        strokes = _make_strokes([3600])
        now = _BASE
        score = content_freshness_score(strokes, now=now)
        assert score == pytest.approx(100.0)

    def test_very_many_strokes(self):
        """Stress test with 1000 strokes."""
        offsets = [i * 15 for i in range(1000)]
        strokes = _make_mixed_strokes(offsets, _KINDS)
        now = _BASE + timedelta(seconds=offsets[-1] + 5)
        report = assess(strokes, [], now=now, expected_kinds=_KINDS)
        assert report.vitality >= 0
