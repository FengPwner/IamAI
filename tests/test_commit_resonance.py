#!/usr/bin/env python3
"""Tests for commit_resonance.py — consecutive-commit resonance measurement."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import commit_resonance as cr


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _c(sha="x", msg="test", files=None, add=10, delete=0):
    """Shorthand factory for CommitInfo."""
    return cr.CommitInfo(
        sha=sha,
        message=msg,
        files=set(files or []),
        additions=add,
        deletions=delete,
    )


# ---------------------------------------------------------------------------
# classify_resonance
# ---------------------------------------------------------------------------

class TestClassifyResonance:
    def test_resonant_at_boundary(self):
        assert cr.classify_resonance(0.80) == "resonant"

    def test_resonant_high(self):
        assert cr.classify_resonance(0.95) == "resonant"

    def test_resonant_at_one(self):
        assert cr.classify_resonance(1.0) == "resonant"

    def test_coherent_lower_boundary(self):
        assert cr.classify_resonance(0.60) == "coherent"

    def test_coherent_upper(self):
        assert cr.classify_resonance(0.79) == "coherent"

    def test_scattered_lower(self):
        assert cr.classify_resonance(0.40) == "scattered"

    def test_scattered_upper(self):
        assert cr.classify_resonance(0.55) == "scattered"

    def test_noisy_lower(self):
        assert cr.classify_resonance(0.20) == "noisy"

    def test_noisy_upper(self):
        assert cr.classify_resonance(0.35) == "noisy"

    def test_incoherent_at_zero(self):
        assert cr.classify_resonance(0.0) == "incoherent"

    def test_incoherent_low(self):
        assert cr.classify_resonance(0.15) == "incoherent"

    def test_just_below_coherent(self):
        assert cr.classify_resonance(0.599) == "scattered"

    def test_just_below_noisy(self):
        assert cr.classify_resonance(0.199) == "incoherent"

    def test_clamp_above_one(self):
        assert cr.classify_resonance(1.5) == "resonant"

    def test_clamp_below_zero(self):
        assert cr.classify_resonance(-0.5) == "incoherent"


# ---------------------------------------------------------------------------
# _jaccard
# ---------------------------------------------------------------------------

class TestJaccard:
    def test_identical_sets(self):
        assert cr._jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self):
        assert cr._jaccard({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self):
        assert cr._jaccard({"a", "b", "c"}, {"b", "c", "d"}) == pytest.approx(0.5)

    def test_both_empty(self):
        assert cr._jaccard(set(), set()) == 0.0

    def test_one_empty(self):
        assert cr._jaccard({"a"}, set()) == 0.0

    def test_subset(self):
        assert cr._jaccard({"a"}, {"a", "b"}) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# _tokenise
# ---------------------------------------------------------------------------

class TestTokenise:
    def test_basic(self):
        tokens = cr._tokenise("add caretaker_yield module")
        # "add" has length 3, not a stop word → included
        assert "add" in tokens
        # underscore is punctuation → stripped, merging into one token
        assert "caretakeryield" in tokens
        assert "module" in tokens

    def test_stops_removed(self):
        tokens = cr._tokenise("the quick brown fox")
        assert "the" not in tokens
        assert "quick" in tokens

    def test_empty_string(self):
        assert cr._tokenise("") == []

    def test_single_char_ignored(self):
        tokens = cr._tokenise("a b c hello")
        assert tokens == ["hello"]

    def test_punctuation_stripped(self):
        tokens = cr._tokenise("fix: broken test, again")
        assert "fix" in tokens
        assert "broken" in tokens


# ---------------------------------------------------------------------------
# _pairwise_file_overlap
# ---------------------------------------------------------------------------

class TestPairwiseFileOverlap:
    def test_single_commit(self):
        commits = [_c(files={"a.py"})]
        assert cr._pairwise_file_overlap(commits) == 0.0

    def test_two_identical(self):
        commits = [_c(files={"a.py", "b.py"}), _c(files={"a.py", "b.py"})]
        assert cr._pairwise_file_overlap(commits) == 1.0

    def test_two_disjoint(self):
        commits = [_c(files={"a.py"}), _c(files={"b.py"})]
        assert cr._pairwise_file_overlap(commits) == 0.0

    def test_three_mixed(self):
        commits = [
            _c(files={"a.py", "b.py"}),
            _c(files={"b.py", "c.py"}),
            _c(files={"c.py", "d.py"}),
        ]
        # pair1: {a,b}∩{b,c} / {a,b,c} = 1/3
        # pair2: {b,c}∩{c,d} / {b,c,d} = 1/3
        # avg = 1/3
        assert cr._pairwise_file_overlap(commits) == pytest.approx(1 / 3)

    def test_empty(self):
        assert cr._pairwise_file_overlap([]) == 0.0


# ---------------------------------------------------------------------------
# _message_coherence
# ---------------------------------------------------------------------------

class TestMessageCoherence:
    def test_identical_messages(self):
        commits = [
            _c(msg="add caretaker_yield module tests"),
            _c(msg="add caretaker_yield module tests"),
        ]
        assert cr._message_coherence(commits) == 1.0

    def test_completely_different(self):
        commits = [
            _c(msg="refactor database connection pooling"),
            _c(msg="update readme badges"),
        ]
        # "refactor", "database", "connection", "pooling" vs "update", "readme", "badges"
        # No overlap → 0.0
        assert cr._message_coherence(commits) == 0.0

    def test_partial_overlap(self):
        commits = [
            _c(msg="add caretaker yield module"),
            _c(msg="fix caretaker yield edge case"),
        ]
        # tokens: {"add","caretaker","yield","module"} vs {"fix","caretaker","yield","edge","case"}
        # intersection = 2 (caretaker, yield), min set size = 4
        # score = 2/4 = 0.5
        assert cr._message_coherence(commits) == pytest.approx(0.5)

    def test_single_commit(self):
        assert cr._message_coherence([_c(msg="hello world")]) == 0.0

    def test_empty(self):
        assert cr._message_coherence([]) == 0.0


# ---------------------------------------------------------------------------
# _commit_direction
# ---------------------------------------------------------------------------

class TestCommitDirection:
    def test_pure_add(self):
        assert cr._commit_direction(_c(add=100, delete=0)) == "add"

    def test_pure_delete(self):
        assert cr._commit_direction(_c(add=0, delete=100)) == "delete"

    def test_mostly_add(self):
        assert cr._commit_direction(_c(add=90, delete=10)) == "add"

    def test_mostly_delete(self):
        assert cr._commit_direction(_c(add=10, delete=90)) == "delete"

    def test_mixed(self):
        assert cr._commit_direction(_c(add=50, delete=50)) == "modify"

    def test_zero_changes(self):
        assert cr._commit_direction(_c(add=0, delete=0)) == "modify"


# ---------------------------------------------------------------------------
# _direction_consistency
# ---------------------------------------------------------------------------

class TestDirectionConsistency:
    def test_all_adds(self):
        commits = [_c(add=100, delete=0)] * 4
        assert cr._direction_consistency(commits) == 1.0

    def test_alternating(self):
        commits = [
            _c(add=100, delete=0),
            _c(add=0, delete=100),
            _c(add=100, delete=0),
            _c(add=0, delete=100),
        ]
        assert cr._direction_consistency(commits) == 0.0

    def test_mostly_same(self):
        commits = [
            _c(add=100, delete=0),
            _c(add=100, delete=0),
            _c(add=50, delete=50),  # modify
            _c(add=100, delete=0),
        ]
        # pairs: (add,add)=match, (add,modify)=no, (modify,add)=no → 1/3
        assert cr._direction_consistency(commits) == pytest.approx(1 / 3)

    def test_single_commit(self):
        assert cr._direction_consistency([_c()]) == 0.0

    def test_empty(self):
        assert cr._direction_consistency([]) == 0.0


# ---------------------------------------------------------------------------
# _build_chain_fraction
# ---------------------------------------------------------------------------

class TestBuildChainFraction:
    def test_perfect_chain(self):
        commits = [
            _c(files={"a.py"}),
            _c(files={"a.py", "b.py"}),
            _c(files={"b.py", "c.py"}),
            _c(files={"c.py", "d.py"}),
        ]
        assert cr._build_chain_fraction(commits, window=1) == 1.0

    def test_no_chain(self):
        commits = [
            _c(files={"a.py"}),
            _c(files={"b.py"}),
            _c(files={"c.py"}),
        ]
        assert cr._build_chain_fraction(commits, window=1) == 0.0

    def test_window_matters(self):
        commits = [
            _c(files={"a.py"}),
            _c(files={"b.py"}),
            _c(files={"a.py"}),  # connects to commit 0 but not 1
        ]
        # window=1: only looks at immediately previous commit
        # commit 1 vs {a.py}: {b.py}∩{a.py}=∅ → no
        # commit 2 vs {b.py}: {a.py}∩{b.py}=∅ → no
        assert cr._build_chain_fraction(commits, window=1) == 0.0
        # window=2: looks back up to 2 commits
        # commit 1 vs {a.py}: {b.py}∩{a.py}=∅ → no
        # commit 2 vs {a.py,b.py}: {a.py}∩{a.py,b.py}={a.py} → yes
        assert cr._build_chain_fraction(commits, window=2) == 0.5

    def test_single_commit(self):
        assert cr._build_chain_fraction([_c(files={"a.py"})], window=5) == 0.0

    def test_empty(self):
        assert cr._build_chain_fraction([], window=5) == 0.0


# ---------------------------------------------------------------------------
# _signal_strength
# ---------------------------------------------------------------------------

class TestSignalStrength:
    def test_all_substantive(self):
        commits = [_c(add=10, delete=5), _c(add=20, delete=0), _c(add=8, delete=3)]
        assert cr._signal_strength(commits) == 1.0

    def test_all_noise(self):
        commits = [_c(add=1, delete=0), _c(add=2, delete=1), _c(add=0, delete=3)]
        # totals: 1, 3, 3 — all < 5
        assert cr._signal_strength(commits) == 0.0

    def test_mixed(self):
        commits = [_c(add=10, delete=0), _c(add=1, delete=0), _c(add=20, delete=5), _c(add=2, delete=0)]
        # substantive: commit 0 (10), commit 2 (25) → 2/4
        assert cr._signal_strength(commits) == 0.5

    def test_empty(self):
        assert cr._signal_strength([]) == 0.0

    def test_exactly_five(self):
        commits = [_c(add=3, delete=2)]
        assert cr._signal_strength(commits) == 1.0


# ---------------------------------------------------------------------------
# compute_resonance — integration
# ---------------------------------------------------------------------------

class TestComputeResonance:
    def test_empty(self):
        r = cr.compute_resonance([])
        assert r.resonance_score == 0.0
        assert r.resonance_class == "incoherent"
        assert r.commit_count == 0

    def test_single_commit(self):
        r = cr.compute_resonance([_c(files={"a.py"}, msg="hello world", add=50)])
        assert r.commit_count == 1
        assert r.resonance_score >= 0.0
        # With only one commit, overlap/coherence/direction are all 0,
        # but signal_strength should be 1.0
        assert r.signal_strength == 1.0

    def test_resonant_sequence(self):
        """Commits that clearly build on each other."""
        commits = [
            cr.CommitInfo(sha="a", message="add caretaker yield module",
                          files={"iamai/caretaker_yield.py", "tests/test_caretaker_yield.py"},
                          additions=580, deletions=0),
            cr.CommitInfo(sha="b", message="caretaker yield fix edge case classify",
                          files={"iamai/caretaker_yield.py"},
                          additions=12, deletions=3),
            cr.CommitInfo(sha="c", message="caretaker yield add trend analysis",
                          files={"iamai/caretaker_yield.py", "tests/test_caretaker_yield.py"},
                          additions=80, deletions=5),
        ]
        r = cr.compute_resonance(commits)
        assert r.commit_count == 3
        # High file overlap, good message coherence, build chain connected
        assert r.file_overlap > 0.3
        assert r.message_coherence > 0.3
        assert r.build_chain_fraction == 1.0
        assert r.signal_strength == 1.0
        assert r.resonance_class in ("resonant", "coherent")

    def test_noisy_sequence(self):
        """Commits touching unrelated files with different messages."""
        commits = [
            cr.CommitInfo(sha="a", message="update readme badges",
                          files={"README.md"}, additions=2, deletions=2),
            cr.CommitInfo(sha="b", message="fix ssh key permission",
                          files={"tools/deploy_key.sh"}, additions=3, deletions=1),
            cr.CommitInfo(sha="c", message="add pool diversity tracker",
                          files={"iamai/pool_diversity.py", "tests/test_pool_diversity.py"},
                          additions=200, deletions=0),
            cr.CommitInfo(sha="d", message="typo in changelog",
                          files={"CHANGELOG.md"}, additions=1, deletions=1),
        ]
        r = cr.compute_resonance(commits)
        # Low overlap, low coherence, but some signal strength
        assert r.file_overlap < 0.2
        assert r.message_coherence < 0.3
        assert r.resonance_class in ("noisy", "scattered", "incoherent")

    def test_window_parameter(self):
        commits = [
            _c(files={"a.py"}, add=10),
            _c(files={"b.py"}, add=10),
            _c(files={"a.py"}, add=10),
        ]
        r1 = cr.compute_resonance(commits, window=1)
        r5 = cr.compute_resonance(commits, window=5)
        # window=1: commit 2 looks back at commit 1 → {a}∩{b}=∅ → 0/2
        # window=5: commit 2 looks back at both → {a}∩{a,b}={a} → 1/2
        assert r1.build_chain_fraction < r5.build_chain_fraction

    def test_result_fields(self):
        commits = [_c(files={"a.py"}, msg="test add", add=50)] * 3
        r = cr.compute_resonance(commits)
        assert hasattr(r, "file_overlap")
        assert hasattr(r, "message_coherence")
        assert hasattr(r, "direction_consistency")
        assert hasattr(r, "build_chain_fraction")
        assert hasattr(r, "signal_strength")
        assert hasattr(r, "resonance_score")
        assert hasattr(r, "resonance_class")
        assert hasattr(r, "window_size")
        assert hasattr(r, "commit_count")
        assert r.window_size == 5  # default


# ---------------------------------------------------------------------------
# resonance_trend
# ---------------------------------------------------------------------------

class TestResonanceTrend:
    def test_empty(self):
        t = cr.resonance_trend([])
        assert t.scores == []
        assert t.trend == "stable"
        assert t.slope == 0.0

    def test_improving(self):
        results = [
            cr.ResonanceResult(resonance_score=0.3),
            cr.ResonanceResult(resonance_score=0.5),
            cr.ResonanceResult(resonance_score=0.7),
            cr.ResonanceResult(resonance_score=0.9),
        ]
        t = cr.resonance_trend(results)
        assert t.trend == "improving"
        assert t.slope > 0
        assert len(t.scores) == 4

    def test_degrading(self):
        results = [
            cr.ResonanceResult(resonance_score=0.9),
            cr.ResonanceResult(resonance_score=0.7),
            cr.ResonanceResult(resonance_score=0.5),
            cr.ResonanceResult(resonance_score=0.3),
        ]
        t = cr.resonance_trend(results)
        assert t.trend == "degrading"
        assert t.slope < 0

    def test_stable(self):
        results = [
            cr.ResonanceResult(resonance_score=0.65),
            cr.ResonanceResult(resonance_score=0.66),
            cr.ResonanceResult(resonance_score=0.64),
            cr.ResonanceResult(resonance_score=0.65),
        ]
        t = cr.resonance_trend(results)
        assert t.trend == "stable"
        assert abs(t.slope) < 0.02

    def test_single_result(self):
        results = [cr.ResonanceResult(resonance_score=0.5)]
        t = cr.resonance_trend(results)
        assert t.slope == 0.0
        assert t.mean == 0.5

    def test_stddev(self):
        results = [
            cr.ResonanceResult(resonance_score=0.5),
            cr.ResonanceResult(resonance_score=0.5),
            cr.ResonanceResult(resonance_score=0.5),
        ]
        t = cr.resonance_trend(results)
        assert t.stddev == 0.0

    def test_mean_calculation(self):
        results = [
            cr.ResonanceResult(resonance_score=0.2),
            cr.ResonanceResult(resonance_score=0.4),
            cr.ResonanceResult(resonance_score=0.6),
        ]
        t = cr.resonance_trend(results)
        assert t.mean == 0.4


# ---------------------------------------------------------------------------
# resonance_report / trend_report
# ---------------------------------------------------------------------------

class TestReporting:
    def test_resonance_report_contains_class(self):
        r = cr.ResonanceResult(
            resonance_score=0.85,
            resonance_class="resonant",
            commit_count=5,
            window_size=5,
            file_overlap=0.7,
            message_coherence=0.6,
            direction_consistency=0.8,
            build_chain_fraction=0.9,
            signal_strength=1.0,
        )
        report = cr.resonance_report(r)
        assert "resonant" in report
        assert "0.85" in report
        assert "5" in report

    def test_resonance_report_multiline(self):
        r = cr.ResonanceResult(resonance_score=0.5, resonance_class="scattered")
        report = cr.resonance_report(r)
        lines = report.strip().split("\n")
        assert len(lines) >= 7

    def test_trend_report_empty(self):
        t = cr.ResonanceTrend()
        report = cr.trend_report(t)
        assert "No resonance data" in report

    def test_trend_report_improving(self):
        t = cr.ResonanceTrend(
            scores=[0.3, 0.5, 0.7],
            trend="improving",
            slope=0.2,
            mean=0.5,
            stddev=0.16,
        )
        report = cr.trend_report(t)
        assert "improving" in report
        assert "0.50" in report

    def test_trend_report_recent_scores(self):
        t = cr.ResonanceTrend(
            scores=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            trend="improving",
            slope=0.1,
            mean=0.35,
            stddev=0.17,
        )
        report = cr.trend_report(t)
        # Should show last 5 scores
        assert "0.20" in report
        assert "0.60" in report


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_all_empty_commits(self):
        commits = [_c(files=set(), msg="", add=0, delete=0)] * 3
        r = cr.compute_resonance(commits)
        assert r.signal_strength == 0.0
        assert r.resonance_score >= 0.0

    def test_identical_commits(self):
        c = _c(files={"a.py", "b.py"}, msg="add module with tests", add=100)
        commits = [c, c, c]
        r = cr.compute_resonance(commits)
        assert r.file_overlap == 1.0
        assert r.message_coherence == 1.0
        assert r.direction_consistency == 1.0
        assert r.build_chain_fraction == 1.0

    def test_very_long_sequence(self):
        commits = [
            _c(files={"a.py"}, msg="add module iteration", add=50)
            for _ in range(100)
        ]
        r = cr.compute_resonance(commits)
        assert r.commit_count == 100
        assert r.resonance_score > 0.0

    def test_mixed_file_patterns(self):
        """One commit touches many files, others touch few."""
        commits = [
            _c(files={"a.py", "b.py", "c.py", "d.py"}, msg="big refactor", add=200, delete=100),
            _c(files={"a.py"}, msg="fix refactor typo", add=5, delete=2),
            _c(files={"e.py"}, msg="add new unrelated module", add=80, delete=0),
        ]
        r = cr.compute_resonance(commits)
        # First pair shares {a.py}, second pair shares nothing
        assert 0 < r.file_overlap < 1
