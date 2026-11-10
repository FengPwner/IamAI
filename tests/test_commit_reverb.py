#!/usr/bin/env python3
"""Tests for commit_reverb.py — commit reverberation analysis."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import commit_reverb as cr

# ---------------------------------------------------------------------------
# Reference time
# ---------------------------------------------------------------------------
REF = datetime(2026, 11, 11, 0, 0, 0)  # Wed 2026-11-11 00:00 UTC


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _commit(sha, hours_after, files):
    """Create a CommitInfo at REF + hours_after with the given files."""
    return cr.CommitInfo(
        sha=sha,
        timestamp=REF + timedelta(hours=hours_after),
        files=frozenset(files),
    )


def _source(hours_before=0, files=("iamai/foo.py", "tests/test_foo.py")):
    """Create a source CommitInfo at REF - hours_before."""
    return cr.CommitInfo(
        sha="source",
        timestamp=REF - timedelta(hours=hours_before),
        files=frozenset(files),
    )


# ---------------------------------------------------------------------------
# CommitInfo
# ---------------------------------------------------------------------------

class TestCommitInfo:
    def test_frozenset_conversion(self):
        c = cr.CommitInfo(sha="a", timestamp=REF, files=["x.py", "y.py"])
        assert isinstance(c.files, frozenset)
        assert c.files == frozenset({"x.py", "y.py"})

    def test_already_frozenset(self):
        fs = frozenset({"a.py"})
        c = cr.CommitInfo(sha="a", timestamp=REF, files=fs)
        assert c.files is fs

    def test_empty_files(self):
        c = cr.CommitInfo(sha="a", timestamp=REF, files=frozenset())
        assert len(c.files) == 0

    def test_immutable(self):
        c = _commit("a", 0, ["x.py"])
        with pytest.raises(AttributeError):
            c.sha = "b"


# ---------------------------------------------------------------------------
# classify_reverb
# ---------------------------------------------------------------------------

class TestClassifyReverb:
    def test_resonant(self):
        assert cr.classify_reverb(0.80) == "resonant"
        assert cr.classify_reverb(0.95) == "resonant"
        assert cr.classify_reverb(1.0) == "resonant"

    def test_warm(self):
        assert cr.classify_reverb(0.60) == "warm"
        assert cr.classify_reverb(0.79) == "warm"

    def test_quiet(self):
        assert cr.classify_reverb(0.40) == "quiet"
        assert cr.classify_reverb(0.59) == "quiet"

    def test_silent(self):
        assert cr.classify_reverb(0.20) == "silent"
        assert cr.classify_reverb(0.39) == "silent"

    def test_chaotic(self):
        assert cr.classify_reverb(0.0) == "chaotic"
        assert cr.classify_reverb(0.19) == "chaotic"

    def test_boundary_zero(self):
        assert cr.classify_reverb(0.0) == "chaotic"

    def test_boundary_one(self):
        assert cr.classify_reverb(1.0) == "resonant"


# ---------------------------------------------------------------------------
# compute_reverb — edge cases
# ---------------------------------------------------------------------------

class TestComputeReverbEdgeCases:
    def test_empty_source_files(self):
        """Source with no files → silent."""
        source = cr.CommitInfo(sha="s", timestamp=REF, files=frozenset())
        result = cr.compute_reverb(source, [])
        assert result.reverb_class == "silent"
        assert result.echo_count == 0

    def test_no_subsequent(self):
        """No subsequent commits → silent."""
        source = _source(files=["iamai/foo.py"])
        result = cr.compute_reverb(source, [])
        assert result.reverb_class == "silent"
        assert result.window_commits == 0

    def test_all_before_source(self):
        """All subsequent commits timestamped before source → ignored."""
        source = _source(files=["iamai/foo.py"])
        later = [_commit("a", -5, ["iamai/foo.py"])]
        result = cr.compute_reverb(source, later)
        assert result.window_commits == 0

    def test_all_outside_window(self):
        """All commits beyond window → silent."""
        source = _source(files=["iamai/foo.py"])
        later = [_commit("a", 100, ["iamai/foo.py"])]
        result = cr.compute_reverb(source, later, window_hours=72)
        assert result.window_commits == 0

    def test_same_timestamp_ignored(self):
        """Commits at exactly the source timestamp are excluded."""
        source = _source(files=["iamai/foo.py"])
        same = [_commit("a", 0, ["iamai/foo.py"])]
        result = cr.compute_reverb(source, same)
        assert result.window_commits == 0


# ---------------------------------------------------------------------------
# compute_reverb — echo detection
# ---------------------------------------------------------------------------

class TestComputeReverbEchoes:
    def test_single_echo(self):
        source = _source(files=["iamai/foo.py", "tests/test_foo.py"])
        later = [_commit("a", 1, ["iamai/foo.py", "iamai/bar.py"])]
        r = cr.compute_reverb(source, later)
        assert r.echo_count == 1
        assert r.echo_ratio == 1.0

    def test_no_echo(self):
        source = _source(files=["iamai/foo.py"])
        later = [_commit("a", 1, ["iamai/bar.py"])]
        r = cr.compute_reverb(source, later)
        assert r.echo_count == 0
        assert r.echo_ratio == 0.0

    def test_mixed_echoes(self):
        source = _source(files=["iamai/foo.py"])
        later = [
            _commit("a", 1, ["iamai/foo.py"]),   # echo
            _commit("b", 2, ["iamai/bar.py"]),    # not echo
            _commit("c", 3, ["iamai/foo.py"]),    # echo
            _commit("d", 4, ["iamai/baz.py"]),    # not echo
        ]
        r = cr.compute_reverb(source, later)
        assert r.echo_count == 2
        assert r.echo_ratio == 0.5
        assert r.window_commits == 4

    def test_first_echo_hours(self):
        source = _source(files=["iamai/foo.py"])
        later = [
            _commit("a", 3, ["iamai/bar.py"]),
            _commit("b", 1.5, ["iamai/foo.py"]),  # first echo at 1.5h
            _commit("c", 5, ["iamai/foo.py"]),
        ]
        r = cr.compute_reverb(source, later)
        assert r.first_echo_hours == pytest.approx(1.5, abs=0.01)

    def test_no_echo_first_echo_none(self):
        source = _source(files=["iamai/foo.py"])
        later = [_commit("a", 1, ["iamai/bar.py"])]
        r = cr.compute_reverb(source, later)
        assert r.first_echo_hours is None


# ---------------------------------------------------------------------------
# compute_reverb — decay
# ---------------------------------------------------------------------------

class TestComputeReverbDecay:
    def test_decay_single_echo(self):
        source = _source(files=["iamai/foo.py"])
        later = [_commit("a", 2, ["iamai/foo.py"])]
        r = cr.compute_reverb(source, later)
        # Single echo at 2h → λ = 1/2 = 0.5
        assert r.decay_rate == pytest.approx(0.5, abs=0.01)

    def test_decay_multiple_echoes(self):
        source = _source(files=["iamai/foo.py"])
        later = [
            _commit("a", 1, ["iamai/foo.py"]),
            _commit("b", 3, ["iamai/foo.py"]),
            _commit("c", 5, ["iamai/foo.py"]),
        ]
        r = cr.compute_reverb(source, later)
        # mean = (1+3+5)/3 = 3; λ = 1/3 ≈ 0.333
        assert r.decay_rate == pytest.approx(1 / 3, abs=0.01)

    def test_half_life(self):
        source = _source(files=["iamai/foo.py"])
        later = [
            _commit("a", 2, ["iamai/foo.py"]),
            _commit("b", 4, ["iamai/foo.py"]),
        ]
        r = cr.compute_reverb(source, later)
        # mean = 3; λ = 1/3; half-life = ln2 / (1/3) ≈ 2.08
        assert r.half_life_hours is not None
        import math
        expected = math.log(2) / (1 / 3)
        assert r.half_life_hours == pytest.approx(expected, abs=0.1)

    def test_no_echo_no_decay(self):
        source = _source(files=["iamai/foo.py"])
        later = [_commit("a", 1, ["iamai/bar.py"])]
        r = cr.compute_reverb(source, later)
        assert r.decay_rate == 0.0
        assert r.half_life_hours is None


# ---------------------------------------------------------------------------
# compute_reverb — concentrated fraction
# ---------------------------------------------------------------------------

class TestConcentratedFraction:
    def test_all_same_files(self):
        """Every echo only touches source files → concentrated = 1.0."""
        source = _source(files=["iamai/foo.py", "tests/test_foo.py"])
        later = [
            _commit("a", 1, ["iamai/foo.py"]),
            _commit("b", 2, ["tests/test_foo.py"]),
            _commit("c", 3, ["iamai/foo.py", "tests/test_foo.py"]),
        ]
        r = cr.compute_reverb(source, later)
        assert r.concentrated_fraction == 1.0

    def test_all_expanded(self):
        """Every echo adds at least one new file → concentrated = 0.0."""
        source = _source(files=["iamai/foo.py"])
        later = [
            _commit("a", 1, ["iamai/foo.py", "iamai/bar.py"]),
            _commit("b", 2, ["iamai/foo.py", "docs/FOO.md"]),
        ]
        r = cr.compute_reverb(source, later)
        assert r.concentrated_fraction == 0.0

    def test_mixed(self):
        source = _source(files=["iamai/foo.py"])
        later = [
            _commit("a", 1, ["iamai/foo.py"]),                   # same only
            _commit("b", 2, ["iamai/foo.py", "iamai/bar.py"]),   # expanded
        ]
        r = cr.compute_reverb(source, later)
        assert r.concentrated_fraction == 0.5


# ---------------------------------------------------------------------------
# compute_reverb — composite score & class
# ---------------------------------------------------------------------------

class TestCompositeScore:
    def test_healthy_pattern(self):
        """Moderate echoes, fast decay, good spread → high score."""
        source = _source(files=["iamai/foo.py", "tests/test_foo.py"])
        later = [
            _commit("a", 0.5, ["iamai/foo.py", "iamai/bar.py"]),
            _commit("b", 1, ["tests/test_foo.py", "docs/FOO.md"]),
            _commit("c", 2, ["iamai/qux.py"]),          # no echo
            _commit("d", 3, ["iamai/baz.py"]),          # no echo
            _commit("e", 4, ["iamai/foo.py", "iamai/new.py"]),
        ]
        r = cr.compute_reverb(source, later)
        # 3 echoes out of 5 → ratio 0.6 (slightly high but reasonable)
        assert r.echo_count == 3
        assert r.reverb_score >= 0.40  # at least quiet
        assert r.reverb_class in ("resonant", "warm", "quiet")

    def test_silent_pattern(self):
        """No echoes at all → silent."""
        source = _source(files=["iamai/foo.py"])
        later = [
            _commit("a", 1, ["iamai/bar.py"]),
            _commit("b", 2, ["iamai/baz.py"]),
            _commit("c", 3, ["tests/test_bar.py"]),
        ]
        r = cr.compute_reverb(source, later)
        assert r.reverb_class == "silent"
        assert r.reverb_score <= 0.40

    def test_score_bounded(self):
        """Score always in [0, 1]."""
        source = _source(files=["iamai/foo.py"])
        later = [_commit("a", h, ["iamai/foo.py"]) for h in range(1, 50)]
        r = cr.compute_reverb(source, later)
        assert 0.0 <= r.reverb_score <= 1.0


# ---------------------------------------------------------------------------
# reverb_report
# ---------------------------------------------------------------------------

class TestReverbReport:
    def test_basic_report(self):
        source = _source(files=["iamai/foo.py"])
        later = [_commit("a", 1, ["iamai/foo.py"])]
        r = cr.compute_reverb(source, later)
        report = cr.reverb_report(r)
        assert "source" in report
        assert "echo count" in report.lower() or "echo_count" in report.lower() or "echo count" in report
        assert r.reverb_class in report

    def test_no_echo_report(self):
        source = _source(files=["iamai/foo.py"])
        r = cr.compute_reverb(source, [])
        report = cr.reverb_report(r)
        assert "(none)" in report


# ---------------------------------------------------------------------------
# reverb_trend
# ---------------------------------------------------------------------------

class TestReverbTrend:
    def test_empty(self):
        t = cr.reverb_trend([])
        assert t.direction == "stable"
        assert t.sample_count == 0

    def test_improving(self):
        results = [
            cr.ReverbResult("a", 10, 2, 0.2, 1.0, 0.3, 2.3, 0.5, 0.3, "silent"),
            cr.ReverbResult("b", 10, 3, 0.3, 0.5, 0.5, 1.4, 0.3, 0.7, "warm"),
        ]
        t = cr.reverb_trend(results)
        assert t.direction == "improving"
        assert t.score_delta > 0

    def test_declining(self):
        results = [
            cr.ReverbResult("a", 10, 3, 0.3, 0.5, 0.5, 1.4, 0.3, 0.8, "resonant"),
            cr.ReverbResult("b", 10, 1, 0.1, 5.0, 0.1, 6.9, 0.8, 0.3, "silent"),
        ]
        t = cr.reverb_trend(results)
        assert t.direction == "declining"
        assert t.score_delta < 0

    def test_stable(self):
        results = [
            cr.ReverbResult("a", 10, 2, 0.2, 1.0, 0.3, 2.3, 0.5, 0.65, "warm"),
            cr.ReverbResult("b", 10, 2, 0.2, 1.0, 0.3, 2.3, 0.5, 0.67, "warm"),
        ]
        t = cr.reverb_trend(results)
        assert t.direction == "stable"

    def test_single_sample(self):
        results = [
            cr.ReverbResult("a", 10, 2, 0.2, 1.0, 0.3, 2.3, 0.5, 0.65, "warm"),
        ]
        t = cr.reverb_trend(results)
        assert t.direction == "stable"
        assert t.sample_count == 1


# ---------------------------------------------------------------------------
# Window boundary
# ---------------------------------------------------------------------------

class TestWindowBoundary:
    def test_exactly_at_boundary(self):
        """Commit at exactly window_hours should be included."""
        source = _source(files=["iamai/foo.py"])
        later = [_commit("a", 72, ["iamai/foo.py"])]
        r = cr.compute_reverb(source, later, window_hours=72)
        assert r.window_commits == 1
        assert r.echo_count == 1

    def test_just_past_boundary(self):
        """Commit just past window should be excluded."""
        source = _source(files=["iamai/foo.py"])
        later = [_commit("a", 72.01, ["iamai/foo.py"])]
        r = cr.compute_reverb(source, later, window_hours=72)
        assert r.window_commits == 0

    def test_custom_window(self):
        source = _source(files=["iamai/foo.py"])
        later = [
            _commit("a", 5, ["iamai/foo.py"]),
            _commit("b", 15, ["iamai/foo.py"]),
        ]
        r = cr.compute_reverb(source, later, window_hours=10)
        assert r.window_commits == 1
        assert r.echo_count == 1
