#!/usr/bin/env python3
"""Tests for commit_memory.py — repo memory measurement."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import commit_memory as cm


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _c(sha="x", msg="test commit", files=None):
    """Shorthand factory for CommitRecord."""
    return cm.CommitRecord(
        sha=sha,
        message=msg,
        files=set(files or []),
    )


# ---------------------------------------------------------------------------
# classify_memory
# ---------------------------------------------------------------------------

class TestClassifyMemory:
    def test_eidetic_at_boundary(self):
        assert cm.classify_memory(0.80) == "eidetic"

    def test_eidetic_high(self):
        assert cm.classify_memory(0.95) == "eidetic"

    def test_eidetic_at_one(self):
        assert cm.classify_memory(1.0) == "eidetic"

    def test_sharp_lower(self):
        assert cm.classify_memory(0.60) == "sharp"

    def test_sharp_upper(self):
        assert cm.classify_memory(0.79) == "sharp"

    def test_adequate_lower(self):
        assert cm.classify_memory(0.40) == "adequate"

    def test_adequate_upper(self):
        assert cm.classify_memory(0.55) == "adequate"

    def test_foggy_lower(self):
        assert cm.classify_memory(0.20) == "foggy"

    def test_foggy_upper(self):
        assert cm.classify_memory(0.35) == "foggy"

    def test_amnesiac_at_zero(self):
        assert cm.classify_memory(0.0) == "amnesiac"

    def test_amnesiac_low(self):
        assert cm.classify_memory(0.10) == "amnesiac"

    def test_amnesiac_below_boundary(self):
        assert cm.classify_memory(0.19) == "amnesiac"


# ---------------------------------------------------------------------------
# _meaningful_tokens
# ---------------------------------------------------------------------------

class TestMeaningfulTokens:
    def test_basic_extraction(self):
        tokens = cm._meaningful_tokens("add foo module")
        assert "add" in tokens
        assert "foo" in tokens
        assert "module" in tokens

    def test_stop_words_removed(self):
        tokens = cm._meaningful_tokens("the quick and the dead")
        assert "the" not in tokens
        assert "and" not in tokens
        assert "quick" in tokens
        assert "dead" in tokens

    def test_empty_message(self):
        assert cm._meaningful_tokens("") == set()

    def test_all_stop_words(self):
        assert cm._meaningful_tokens("a an the and or but") == set()


# ---------------------------------------------------------------------------
# _compute_ancestry_depth
# ---------------------------------------------------------------------------

class TestAncestryDepth:
    def test_single_commit(self):
        """First commit has nothing to build on — but single commit = 0."""
        commits = [_c(files={"a.py", "b.py"})]
        assert cm._compute_ancestry_depth(commits) == 0.0

    def test_full_overlap(self):
        """Every subsequent commit only touches known files."""
        commits = [
            _c(files={"a.py", "b.py"}),
            _c(files={"a.py"}),
            _c(files={"b.py"}),
        ]
        assert cm._compute_ancestry_depth(commits) == 1.0

    def test_zero_overlap(self):
        """Every commit introduces entirely new files."""
        commits = [
            _c(files={"a.py"}),
            _c(files={"b.py"}),
            _c(files={"c.py"}),
        ]
        assert cm._compute_ancestry_depth(commits) == 0.0

    def test_partial_overlap(self):
        commits = [
            _c(files={"a.py"}),
            _c(files={"a.py", "b.py"}),  # 1/2 known
        ]
        assert cm._compute_ancestry_depth(commits) == pytest.approx(0.5)

    def test_empty_commit(self):
        commits = [
            _c(files={"a.py"}),
            _c(files=set()),  # empty commit
        ]
        assert cm._compute_ancestry_depth(commits) == 0.0

    def test_empty_list(self):
        assert cm._compute_ancestry_depth([]) == 0.0


# ---------------------------------------------------------------------------
# _compute_echo_rate
# ---------------------------------------------------------------------------

class TestEchoRate:
    def test_single_commit(self):
        assert cm._compute_echo_rate([_c(msg="hello world")]) == 0.0

    def test_full_echo(self):
        """Every message reuses keywords from earlier."""
        commits = [
            _c(msg="add foo module"),
            _c(msg="extend foo with bar"),
            _c(msg="refactor foo internals"),
        ]
        assert cm._compute_echo_rate(commits) == 1.0

    def test_zero_echo(self):
        """Every message uses completely different words."""
        commits = [
            _c(msg="add alpha widget"),
            _c(msg="build beta service"),
            _c(msg="create gamma engine"),
        ]
        assert cm._compute_echo_rate(commits) == 0.0

    def test_partial_echo(self):
        commits = [
            _c(msg="add foo module"),
            _c(msg="build bar service"),  # no echo
        ]
        assert cm._compute_echo_rate(commits) == pytest.approx(0.0)

    def test_empty_messages(self):
        commits = [_c(msg=""), _c(msg="")]
        assert cm._compute_echo_rate(commits) == 0.0

    def test_empty_list(self):
        assert cm._compute_echo_rate([]) == 0.0


# ---------------------------------------------------------------------------
# _compute_reinvention_rate
# ---------------------------------------------------------------------------

class TestReinventionRate:
    def test_all_new(self):
        """Every file touch is a brand-new file."""
        commits = [
            _c(files={"a.py"}),
            _c(files={"b.py"}),
            _c(files={"c.py"}),
        ]
        assert cm._compute_reinvention_rate(commits) == 1.0

    def test_all_known(self):
        """Only the first commit introduces files; rest reuse."""
        commits = [
            _c(files={"a.py", "b.py"}),
            _c(files={"a.py"}),
            _c(files={"b.py"}),
        ]
        # first commit: 2 new touches; second: 0 new; third: 0 new
        # total: 2 new / 4 touches = 0.5
        assert cm._compute_reinvention_rate(commits) == pytest.approx(0.5)

    def test_empty_commits(self):
        assert cm._compute_reinvention_rate([]) == 0.0

    def test_empty_files(self):
        commits = [_c(files=set()), _c(files=set())]
        assert cm._compute_reinvention_rate(commits) == 0.0


# ---------------------------------------------------------------------------
# compute_memory
# ---------------------------------------------------------------------------

class TestComputeMemory:
    def test_empty_commits(self):
        r = cm.compute_memory([])
        assert r.continuity_score == 0.0
        assert r.memory_class == "amnesiac"
        assert r.commit_count == 0

    def test_strong_memory(self):
        """Commits that heavily overlap and echo each other."""
        commits = [
            _c(msg="add commit memory module",
               files={"iamai/commit_memory.py", "tests/test_commit_memory.py"}),
            _c(msg="extend commit memory with trend analysis",
               files={"iamai/commit_memory.py", "tests/test_commit_memory.py",
                      "docs/MEMORY.md"}),
            _c(msg="refactor commit memory scoring",
               files={"iamai/commit_memory.py", "tests/test_commit_memory.py"}),
            _c(msg="polish commit memory reporting",
               files={"iamai/commit_memory.py", "docs/MEMORY.md"}),
        ]
        r = cm.compute_memory(commits)
        assert r.memory_class in ("eidetic", "sharp")
        assert r.continuity_score >= 0.55
        assert r.commit_count == 4

    def test_weak_memory(self):
        """Every commit touches brand-new files with unique vocabulary."""
        commits = [
            _c(msg="add alpha widget", files={"alpha.py"}),
            _c(msg="build beta service", files={"beta.py"}),
            _c(msg="create gamma engine", files={"gamma.py"}),
            _c(msg="make delta handler", files={"delta.py"}),
        ]
        r = cm.compute_memory(commits)
        assert r.memory_class in ("amnesiac", "foggy")
        assert r.reinvention_rate == 1.0
        assert r.ancestry_depth == 0.0

    def test_file_count(self):
        commits = [
            _c(files={"a.py", "b.py"}),
            _c(files={"b.py", "c.py"}),
        ]
        r = cm.compute_memory(commits)
        assert r.file_count == 3

    def test_score_in_range(self):
        """Score is always in [0, 1]."""
        commits = [
            _c(msg="initial setup", files={"setup.py"}),
            _c(msg="add foo", files={"foo.py"}),
            _c(msg="extend foo", files={"foo.py", "bar.py"}),
        ]
        r = cm.compute_memory(commits)
        assert 0.0 <= r.continuity_score <= 1.0


# ---------------------------------------------------------------------------
# memory_trend
# ---------------------------------------------------------------------------

class TestMemoryTrend:
    def test_empty(self):
        t = cm.memory_trend([])
        assert t.scores == []
        assert t.trend == "stable"

    def test_strengthening(self):
        t = cm.memory_trend([
            cm.MemoryResult(continuity_score=0.3),
            cm.MemoryResult(continuity_score=0.5),
            cm.MemoryResult(continuity_score=0.7),
            cm.MemoryResult(continuity_score=0.9),
        ])
        assert t.trend == "strengthening"
        assert t.slope > 0

    def test_fading(self):
        t = cm.memory_trend([
            cm.MemoryResult(continuity_score=0.9),
            cm.MemoryResult(continuity_score=0.7),
            cm.MemoryResult(continuity_score=0.5),
            cm.MemoryResult(continuity_score=0.3),
        ])
        assert t.trend == "fading"
        assert t.slope < 0

    def test_stable(self):
        t = cm.memory_trend([
            cm.MemoryResult(continuity_score=0.50),
            cm.MemoryResult(continuity_score=0.51),
            cm.MemoryResult(continuity_score=0.50),
        ])
        assert t.trend == "stable"
        assert abs(t.slope) < 0.02

    def test_single_result(self):
        t = cm.memory_trend([cm.MemoryResult(continuity_score=0.6)])
        assert len(t.scores) == 1
        assert t.slope == 0.0

    def test_stddev_zero_when_identical(self):
        t = cm.memory_trend([
            cm.MemoryResult(continuity_score=0.5),
            cm.MemoryResult(continuity_score=0.5),
            cm.MemoryResult(continuity_score=0.5),
        ])
        assert t.stddev == 0.0


# ---------------------------------------------------------------------------
# memory_report
# ---------------------------------------------------------------------------

class TestMemoryReport:
    def test_report_contains_key_info(self):
        r = cm.compute_memory([
            _c(msg="add foo", files={"a.py", "b.py"}),
            _c(msg="extend foo", files={"b.py", "c.py"}),
        ])
        report = cm.memory_report(r)
        assert r.memory_class in report
        assert f"{r.continuity_score:.2f}" in report
        assert "ancestry depth" in report
        assert "echo rate" in report

    def test_report_non_empty(self):
        r = cm.compute_memory([_c(files={"a.py"})])
        report = cm.memory_report(r)
        assert len(report) > 50


# ---------------------------------------------------------------------------
# trend_report
# ---------------------------------------------------------------------------

class TestTrendReport:
    def test_empty_trend(self):
        t = cm.MemoryTrend()
        report = cm.trend_report(t)
        assert "No memory data" in report

    def test_report_contains_info(self):
        t = cm.memory_trend([
            cm.MemoryResult(continuity_score=0.3),
            cm.MemoryResult(continuity_score=0.5),
            cm.MemoryResult(continuity_score=0.7),
        ])
        report = cm.trend_report(t)
        assert "strengthening" in report
        assert "windows analysed : 3" in report


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_commit_with_no_files(self):
        commits = [_c(files=set()), _c(files=set())]
        r = cm.compute_memory(commits)
        assert r.file_count == 0
        assert r.reinvention_rate == 0.0

    def test_mixed_empty_and_full(self):
        commits = [
            _c(msg="initial", files=set()),
            _c(msg="initial work on foo module", files={"a.py", "b.py", "c.py"}),
        ]
        r = cm.compute_memory(commits)
        assert r.file_count == 3
        assert r.commit_count == 2

    def test_many_commits_single_file(self):
        """Repeatedly touching one file = high ancestry, low reinvention."""
        commits = [_c(msg=f"update foo pass {i}", files={"foo.py"})
                   for i in range(50)]
        r = cm.compute_memory(commits)
        assert r.file_count == 1
        assert r.ancestry_depth == 1.0  # all but first see foo.py
        assert r.reinvention_rate == pytest.approx(1.0 / 50)

    def test_large_history(self):
        """Scale test with many commits and files."""
        commits = []
        for i in range(20):
            files = {f"file_{i * 3 + j}.py" for j in range(3)}
            commits.append(_c(sha=f"c{i}", msg=f"batch {i} work",
                              files=files))
        r = cm.compute_memory(commits)
        assert r.file_count == 60
        assert r.commit_count == 20
        assert 0.0 <= r.continuity_score <= 1.0

    def test_score_boundary_eidetic(self):
        assert cm.classify_memory(0.80) == "eidetic"
        assert cm.classify_memory(0.799) == "sharp"

    def test_score_boundary_amnesiac(self):
        assert cm.classify_memory(0.199) == "amnesiac"
        assert cm.classify_memory(0.20) == "foggy"
