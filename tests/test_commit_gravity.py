#!/usr/bin/env python3
"""Tests for commit_gravity.py — commit gravitational influence analysis."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import commit_gravity as cg

# ---------------------------------------------------------------------------
# Reference time
# ---------------------------------------------------------------------------
REF = datetime(2026, 11, 11, 0, 0, 0)  # Wed 2026-11-11 00:00 UTC


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _commit(sha, hours_after, files):
    """Create a CommitInfo at REF + hours_after with the given files."""
    return cg.CommitInfo(
        sha=sha,
        timestamp=REF + timedelta(hours=hours_after),
        files=frozenset(files),
    )


def _source(hours_before=0, files=("iamai/foo.py", "tests/test_foo.py")):
    """Create a source CommitInfo at REF - hours_before."""
    return cg.CommitInfo(
        sha="source",
        timestamp=REF - timedelta(hours=hours_before),
        files=frozenset(files),
    )


# ---------------------------------------------------------------------------
# CommitInfo
# ---------------------------------------------------------------------------

class TestCommitInfo:
    def test_frozenset_conversion(self):
        c = cg.CommitInfo(sha="a", timestamp=REF, files=["x.py", "y.py"])
        assert isinstance(c.files, frozenset)
        assert c.files == frozenset({"x.py", "y.py"})

    def test_already_frozenset(self):
        fs = frozenset({"a.py"})
        c = cg.CommitInfo(sha="a", timestamp=REF, files=fs)
        assert c.files is fs

    def test_empty_files(self):
        c = cg.CommitInfo(sha="a", timestamp=REF, files=frozenset())
        assert len(c.files) == 0

    def test_immutable(self):
        c = _commit("a", 0, ["x.py"])
        with pytest.raises(AttributeError):
            c.sha = "b"


# ---------------------------------------------------------------------------
# classify_gravity
# ---------------------------------------------------------------------------

class TestClassifyGravity:
    def test_massive(self):
        assert cg.classify_gravity(0.80) == "massive"
        assert cg.classify_gravity(0.95) == "massive"
        assert cg.classify_gravity(1.0) == "massive"

    def test_strong(self):
        assert cg.classify_gravity(0.60) == "strong"
        assert cg.classify_gravity(0.79) == "strong"

    def test_moderate(self):
        assert cg.classify_gravity(0.40) == "moderate"
        assert cg.classify_gravity(0.59) == "moderate"

    def test_weak(self):
        assert cg.classify_gravity(0.20) == "weak"
        assert cg.classify_gravity(0.39) == "weak"

    def test_negligible(self):
        assert cg.classify_gravity(0.19) == "negligible"
        assert cg.classify_gravity(0.0) == "negligible"

    def test_just_below_boundary(self):
        assert cg.classify_gravity(0.7999) == "strong"
        assert cg.classify_gravity(0.5999) == "moderate"
        assert cg.classify_gravity(0.3999) == "weak"
        assert cg.classify_gravity(0.1999) == "negligible"


# ---------------------------------------------------------------------------
# _top_area
# ---------------------------------------------------------------------------

class TestTopArea:
    def test_simple(self):
        assert cg._top_area("iamai/foo.py") == "iamai"

    def test_root_file(self):
        assert cg._top_area("README.md") == "."

    def test_deep(self):
        assert cg._top_area("src/core/utils/helpers.py") == "src"

    def test_backslash(self):
        assert cg._top_area("tests\\unit\\test_foo.py") == "tests"


# ---------------------------------------------------------------------------
# _area_set
# ---------------------------------------------------------------------------

class TestAreaSet:
    def test_mixed(self):
        fs = frozenset(["iamai/a.py", "tests/test_a.py", "README.md"])
        result = cg._area_set(fs)
        assert result == frozenset({"iamai", "tests", "."})

    def test_empty(self):
        assert cg._area_set(frozenset()) == frozenset()


# ---------------------------------------------------------------------------
# _dir_depth
# ---------------------------------------------------------------------------

class TestDirDepth:
    def test_root(self):
        assert cg._dir_depth("README.md") == 0

    def test_one_level(self):
        assert cg._dir_depth("iamai/foo.py") == 1

    def test_deep(self):
        assert cg._dir_depth("src/core/utils/helpers.py") == 3


# ---------------------------------------------------------------------------
# _max_depth_overlap
# ---------------------------------------------------------------------------

class TestMaxDepthOverlap:
    def test_no_overlap(self):
        s = frozenset(["iamai/foo.py"])
        o = frozenset(["tests/bar.py"])
        assert cg._max_depth_overlap(s, o) == 0

    def test_same_directory(self):
        s = frozenset(["iamai/foo.py"])
        o = frozenset(["iamai/bar.py"])
        assert cg._max_depth_overlap(s, o) == 1

    def test_deeper_overlap(self):
        s = frozenset(["iamai/core/foo.py"])
        o = frozenset(["iamai/core/bar.py"])
        assert cg._max_depth_overlap(s, o) == 2

    def test_exact_prefix(self):
        s = frozenset(["iamai/core/utils/a.py"])
        o = frozenset(["iamai/core/utils/b.py"])
        assert cg._max_depth_overlap(s, o) == 3


# ---------------------------------------------------------------------------
# compute_gravity — basic scenarios
# ---------------------------------------------------------------------------

class TestComputeGravityBasic:
    def test_no_subsequent(self):
        """Empty subsequent list yields negligible gravity."""
        r = cg.compute_gravity(_source(), [])
        assert r.pull_count == 0
        assert r.pull_ratio == 0.0
        assert r.gravity_class == "negligible"
        assert r.influence_hours is None

    def test_all_outside_window(self):
        """Commits outside the window are ignored."""
        src = _source(hours_before=100)
        subs = [
            _commit("a", -90, ["iamai/x.py"]),  # before source
            _commit("b", 100, ["iamai/y.py"]),   # way after window
        ]
        r = cg.compute_gravity(src, subs, window_hours=1.0)
        assert r.window_commits == 0
        assert r.pull_count == 0

    def test_single_pulled_commit(self):
        """One commit touching the same area counts as pulled."""
        src = _source(files=["iamai/foo.py"])
        sub = _commit("a", 1, ["iamai/bar.py"])
        r = cg.compute_gravity(src, [sub])
        assert r.pull_count == 1
        assert r.window_commits == 1
        assert r.pull_ratio == 1.0

    def test_no_overlap_not_pulled(self):
        """A commit in a different area is not pulled."""
        src = _source(files=["iamai/foo.py"])
        sub = _commit("a", 1, ["docs/CHANGELOG.md"])
        r = cg.compute_gravity(src, [sub])
        assert r.pull_count == 0
        assert r.window_commits == 1


# ---------------------------------------------------------------------------
# compute_gravity — metrics
# ---------------------------------------------------------------------------

class TestComputeGravityMetrics:
    def _setup(self):
        src = _source(files=["iamai/core.py", "tests/test_core.py"])
        subs = [
            _commit("a", 1, ["iamai/core.py", "iamai/utils.py"]),
            _commit("b", 2, ["tests/test_core.py", "tests/test_utils.py"]),
            _commit("c", 3, ["docs/README.md"]),  # not pulled
            _commit("d", 5, ["iamai/api.py"]),
        ]
        return src, subs

    def test_pull_count(self):
        src, subs = self._setup()
        r = cg.compute_gravity(src, subs)
        assert r.pull_count == 3  # a, b, d touch iamai or tests

    def test_pull_ratio(self):
        src, subs = self._setup()
        r = cg.compute_gravity(src, subs)
        assert r.pull_ratio == pytest.approx(0.75)

    def test_affected_areas(self):
        src, subs = self._setup()
        r = cg.compute_gravity(src, subs)
        # Pulled commits touch "iamai" and "tests" (both overlap with source)
        assert r.affected_areas == 2

    def test_influence_hours(self):
        src, subs = self._setup()
        r = cg.compute_gravity(src, subs)
        # Last pulled commit is "d" at +5h
        assert r.influence_hours == pytest.approx(5.0)

    def test_reach_depth(self):
        src = _source(files=["iamai/core/engine.py"])
        sub = _commit("a", 1, ["iamai/core/pump.py"])
        r = cg.compute_gravity(src, [sub])
        assert r.reach_depth == 2  # "iamai/core" is depth-2 overlap


# ---------------------------------------------------------------------------
# compute_gravity — score composition
# ---------------------------------------------------------------------------

class TestComputeGravityScore:
    def test_strong_gravity(self):
        """Broad, deep pull across many commits → high score."""
        src = _source(files=["iamai/core/engine.py", "tests/test_engine.py"])
        subs = [
            _commit(f"c{i}", i + 1,
                    [f"iamai/core/module_{i}.py", f"tests/test_module_{i}.py"])
            for i in range(10)
        ]
        r = cg.compute_gravity(src, subs)
        assert r.gravity_score >= 0.60
        assert r.gravity_class in ("massive", "strong")

    def test_weak_gravity_few_pulls(self):
        """Almost no commits overlap a multi-area source → low score."""
        src = _source(files=[
            "iamai/rare.py", "tests/test_rare.py", "docs/rare.md",
        ])
        subs = [
            _commit(f"c{i}", i + 1, [f"other/page_{i}.txt"])
            for i in range(20)
        ]
        subs.append(_commit("one_pulled", 2, ["iamai/other.py"]))
        r = cg.compute_gravity(src, subs)
        assert r.pull_count == 1
        assert r.pull_ratio < 0.05
        assert r.gravity_score < 0.40
        assert r.gravity_class in ("weak", "negligible")

    def test_zero_pulls_zero_score(self):
        src = _source(files=["iamai/foo.py"])
        subs = [_commit("a", 1, ["docs/README.md"])]
        r = cg.compute_gravity(src, subs)
        assert r.gravity_score == 0.0
        assert r.gravity_class == "negligible"

    def test_score_clamped(self):
        """Score is always in [0, 1]."""
        src = _source(files=["a.py"])
        subs = [_commit("c", 1, ["a.py"])]
        r = cg.compute_gravity(src, subs)
        assert 0.0 <= r.gravity_score <= 1.0


# ---------------------------------------------------------------------------
# compute_gravity — window boundary
# ---------------------------------------------------------------------------

class TestComputeGravityWindow:
    def test_commit_at_exact_boundary(self):
        """A commit exactly at window_hours is included."""
        src = _source(files=["iamai/foo.py"])
        sub = _commit("a", 24, ["iamai/bar.py"])
        r = cg.compute_gravity(src, [sub], window_hours=24.0)
        assert r.window_commits == 1

    def test_commit_just_past_boundary(self):
        """A commit just past window_hours is excluded."""
        src = _source(files=["iamai/foo.py"])
        sub = _commit("a", 25, ["iamai/bar.py"])
        r = cg.compute_gravity(src, [sub], window_hours=24.0)
        assert r.window_commits == 0


# ---------------------------------------------------------------------------
# compute_gravity — source files edge cases
# ---------------------------------------------------------------------------

class TestComputeGravityEdgeCases:
    def test_source_no_files(self):
        """Source with empty file set — nothing to pull from."""
        src = cg.CommitInfo(sha="s", timestamp=REF, files=frozenset())
        sub = _commit("a", 1, ["iamai/foo.py"])
        r = cg.compute_gravity(src, [sub])
        assert r.pull_count == 0
        assert r.gravity_class == "negligible"

    def test_subsequent_no_files(self):
        """Subsequent commit with no files doesn't crash."""
        src = _source(files=["iamai/foo.py"])
        sub = cg.CommitInfo(sha="a", timestamp=REF + timedelta(hours=1),
                            files=frozenset())
        r = cg.compute_gravity(src, [sub])
        assert r.pull_count == 0

    def test_both_empty(self):
        src = cg.CommitInfo(sha="s", timestamp=REF, files=frozenset())
        r = cg.compute_gravity(src, [])
        assert r.gravity_class == "negligible"


# ---------------------------------------------------------------------------
# gravity_report
# ---------------------------------------------------------------------------

class TestGravityReport:
    def test_contains_key_fields(self):
        src = _source(files=["iamai/foo.py"])
        sub = _commit("a", 1, ["iamai/bar.py"])
        r = cg.compute_gravity(src, [sub])
        report = cg.gravity_report(r)
        assert "Gravity analysis for" in report
        assert "class:" in report
        assert "score:" in report
        assert "pull count:" in report

    def test_no_influence(self):
        src = _source(files=["iamai/foo.py"])
        sub = _commit("a", 1, ["docs/bar.md"])
        r = cg.compute_gravity(src, [sub])
        report = cg.gravity_report(r)
        assert "(none)" in report


# ---------------------------------------------------------------------------
# gravity_trend
# ---------------------------------------------------------------------------

class TestGravityTrend:
    def test_empty(self):
        t = cg.gravity_trend([])
        assert t.direction == "stable"
        assert t.sample_count == 0

    def test_single_result(self):
        src = _source(files=["iamai/foo.py"])
        sub = _commit("a", 1, ["iamai/bar.py"])
        r = cg.compute_gravity(src, [sub])
        t = cg.gravity_trend([r])
        assert t.direction == "stable"
        assert t.sample_count == 1

    def test_increasing(self):
        r1 = cg.GravityResult("a", 10, 1, 0.1, 1, 1, 1.0, 0.30, "weak")
        r2 = cg.GravityResult("b", 10, 5, 0.5, 3, 2, 5.0, 0.70, "strong")
        t = cg.gravity_trend([r1, r2])
        assert t.direction == "increasing"
        assert t.score_delta == pytest.approx(0.40)

    def test_declining(self):
        r1 = cg.GravityResult("a", 10, 5, 0.5, 3, 2, 5.0, 0.70, "strong")
        r2 = cg.GravityResult("b", 10, 1, 0.1, 1, 1, 1.0, 0.30, "weak")
        t = cg.gravity_trend([r1, r2])
        assert t.direction == "declining"

    def test_stable_small_delta(self):
        r1 = cg.GravityResult("a", 10, 3, 0.3, 2, 1, 3.0, 0.50, "moderate")
        r2 = cg.GravityResult("b", 10, 3, 0.3, 2, 1, 3.0, 0.53, "moderate")
        t = cg.gravity_trend([r1, r2])
        assert t.direction == "stable"
        assert t.score_delta == pytest.approx(0.03)
