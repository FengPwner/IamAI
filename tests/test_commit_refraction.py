#!/usr/bin/env python3
"""Tests for commit_refraction.py — change intent fidelity at module boundaries."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "iamai"))

import commit_refraction as cr

# ---------------------------------------------------------------------------
# Reference time
# ---------------------------------------------------------------------------
REF = datetime(2026, 11, 11, 0, 0, 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _commit(sha, hours_after, files, areas=None, message="",
            additions=0, deletions=0, is_revert=False):
    """Create a CommitRecord at REF + hours_after."""
    return cr.CommitRecord(
        sha=sha,
        timestamp=REF + timedelta(hours=hours_after),
        files=frozenset(files),
        areas=frozenset(areas or []),
        message=message,
        additions=additions,
        deletions=deletions,
        is_revert=is_revert,
    )


def _sequence(n, hours_step=1, files_fn=None, areas_fn=None, msg_fn=None):
    """Generate n commits spaced hours_step apart."""
    if files_fn is None:
        files_fn = lambda i: frozenset([f"iamai/mod_{i % 5}.py"])
    if areas_fn is None:
        areas_fn = lambda i: frozenset()
    if msg_fn is None:
        msg_fn = lambda i: f"update module {i % 5}"
    return [
        cr.CommitRecord(
            sha=f"c{i}",
            timestamp=REF + timedelta(hours=i * hours_step),
            files=files_fn(i),
            areas=areas_fn(i),
            message=msg_fn(i),
        )
        for i in range(n)
    ]


# ===========================================================================
# CommitRecord
# ===========================================================================

class TestCommitRecord:
    def test_basic_creation(self):
        c = cr.CommitRecord(
            sha="abc123",
            timestamp=REF,
            files=frozenset(["a.py"]),
            areas=frozenset(["iamai"]),
            message="fix timeout",
        )
        assert c.sha == "abc123"
        assert c.files == frozenset(["a.py"])
        assert c.areas == frozenset(["iamai"])
        assert c.message == "fix timeout"

    def test_default_empty(self):
        c = cr.CommitRecord(sha="x", timestamp=REF)
        assert c.files == frozenset()
        assert c.areas == frozenset()
        assert c.message == ""
        assert c.is_revert is False

    def test_auto_convert_list_to_frozenset(self):
        c = cr.CommitRecord(
            sha="x", timestamp=REF,
            files=["a.py", "b.py"],
            areas=["area1"],
        )
        assert isinstance(c.files, frozenset)
        assert isinstance(c.areas, frozenset)

    def test_frozen(self):
        c = cr.CommitRecord(sha="x", timestamp=REF)
        with pytest.raises(AttributeError):
            c.sha = "y"

    def test_revert_flag(self):
        c = cr.CommitRecord(sha="x", timestamp=REF, is_revert=True)
        assert c.is_revert is True

    def test_additions_deletions(self):
        c = cr.CommitRecord(sha="x", timestamp=REF, additions=42, deletions=7)
        assert c.additions == 42
        assert c.deletions == 7


# ===========================================================================
# Classification
# ===========================================================================

class TestClassifyRefraction:
    def test_transparent(self):
        assert cr.classify_refraction(0.80) == "transparent"
        assert cr.classify_refraction(0.95) == "transparent"
        assert cr.classify_refraction(1.00) == "transparent"

    def test_clear(self):
        assert cr.classify_refraction(0.60) == "clear"
        assert cr.classify_refraction(0.70) == "clear"
        assert cr.classify_refraction(0.79) == "clear"

    def test_refractive(self):
        assert cr.classify_refraction(0.40) == "refractive"
        assert cr.classify_refraction(0.50) == "refractive"
        assert cr.classify_refraction(0.59) == "refractive"

    def test_opaque(self):
        assert cr.classify_refraction(0.20) == "opaque"
        assert cr.classify_refraction(0.30) == "opaque"
        assert cr.classify_refraction(0.39) == "opaque"

    def test_mirrored(self):
        assert cr.classify_refraction(0.00) == "mirrored"
        assert cr.classify_refraction(0.10) == "mirrored"
        assert cr.classify_refraction(0.19) == "mirrored"

    def test_boundary_values(self):
        assert cr.classify_refraction(0.80) == "transparent"
        assert cr.classify_refraction(0.60) == "clear"
        assert cr.classify_refraction(0.40) == "refractive"
        assert cr.classify_refraction(0.20) == "opaque"


# ===========================================================================
# Helpers
# ===========================================================================

class TestHelpers:
    def test_extract_area_from_path(self):
        assert cr._extract_area_from_path("iamai/core.py") == "iamai"
        assert cr._extract_area_from_path("tests/test_core.py") == "tests"
        assert cr._extract_area_from_path("docs/README.md") == "docs"
        assert cr._extract_area_from_path("simple.py") == "simple.py"

    def test_infer_areas_with_explicit(self):
        files = frozenset(["iamai/core.py"])
        areas = frozenset(["custom_area"])
        result = cr._infer_areas(files, areas)
        assert result == frozenset(["custom_area"])

    def test_infer_areas_from_paths(self):
        files = frozenset(["iamai/core.py", "tests/test_core.py"])
        result = cr._infer_areas(files, frozenset())
        assert result == frozenset(["iamai", "tests"])

    def test_extract_intent_keywords(self):
        kw = cr._extract_intent_keywords("update timeout parameter")
        assert "timeout" in kw
        assert "parameter" in kw

    def test_extract_intent_strips_prefixes(self):
        kw = cr._extract_intent_keywords("add timeout parameter")
        # "add" should be stripped
        assert "add" not in kw
        assert "timeout" in kw

    def test_extract_intent_empty_message(self):
        assert cr._extract_intent_keywords("") == set()

    def test_file_matches_intent_match(self):
        assert cr._file_matches_intent("iamai/timeout.py", {"timeout"}) is True

    def test_file_matches_intent_no_match(self):
        assert cr._file_matches_intent("iamai/core.py", {"timeout"}) is False

    def test_file_matches_intent_empty_keywords(self):
        assert cr._file_matches_intent("any/path.py", set()) is True


# ===========================================================================
# Core computation — edge cases
# ===========================================================================

class TestComputeRefractionEdgeCases:
    def test_empty_commits(self):
        r = cr.compute_refraction([])
        assert r.window_commits == 0
        assert r.refraction_class == "mirrored"
        assert r.refraction_score == 0.0

    def test_single_commit(self):
        r = cr.compute_refraction([
            _commit("c0", 0, ["iamai/core.py"], message="update core module")
        ])
        assert r.window_commits == 1
        assert r.window_hours == 0.0

    def test_single_commit_no_cross_area(self):
        """Single-area commits don't contribute to scope distortion."""
        r = cr.compute_refraction([
            _commit("c0", 0, ["iamai/core.py"], message="update core")
        ])
        assert r.scope_distortion == 0.0
        assert r.coupling_index == 1.0  # no cross-area = default good

    def test_window_hours(self):
        commits = [
            _commit("c0", 0, ["a.py"]),
            _commit("c1", 24, ["b.py"]),
        ]
        r = cr.compute_refraction(commits)
        assert r.window_hours == 24.0


# ===========================================================================
# Intent preservation
# ===========================================================================

class TestIntentPreservation:
    def test_perfect_intent(self):
        """All files match the commit message keywords."""
        commits = [
            _commit("c0", 0, ["iamai/timeout.py", "iamai/handler.py"],
                    message="fix timeout handler"),
            _commit("c1", 1, ["iamai/timeout.py"],
                    message="update timeout parameter"),
        ]
        r = cr.compute_refraction(commits)
        assert r.intent_preservation >= 0.9

    def test_poor_intent(self):
        """Files don't match the commit message at all."""
        commits = [
            _commit("c0", 0, ["iamai/unrelated.py"],
                    message="fix timeout handling in core"),
            _commit("c1", 1, ["docs/readme.md"],
                    message="update authentication module"),
        ]
        r = cr.compute_refraction(commits)
        assert r.intent_preservation < 0.5

    def test_no_messages(self):
        """Commits with empty messages get 0 intent preservation."""
        commits = [
            _commit("c0", 0, ["iamai/core.py"], message=""),
            _commit("c1", 1, ["iamai/utils.py"], message=""),
        ]
        r = cr.compute_refraction(commits)
        assert r.intent_preservation == 0.0

    def test_mixed_intent(self):
        """Some commits match well, some poorly."""
        commits = [
            _commit("c0", 0, ["iamai/timeout.py"],
                    message="fix timeout"),
            _commit("c1", 1, ["iamai/unrelated.py"],
                    message="fix timeout"),
        ]
        r = cr.compute_refraction(commits)
        assert 0.0 < r.intent_preservation < 1.0


# ===========================================================================
# Scope distortion
# ===========================================================================

class TestScopeDistortion:
    def test_uniform_scope(self):
        """Equal files per area → low distortion."""
        commits = [
            _commit(f"c{i}", i,
                    [f"iamai/mod_{i}.py", f"tests/test_mod_{i}.py"],
                    message=f"update mod {i}")
            for i in range(10)
        ]
        r = cr.compute_refraction(commits)
        assert r.scope_distortion <= 0.1

    def test_skewed_scope(self):
        """Many files in one area, few in another → high distortion."""
        commits = [
            _commit(f"c{i}", i,
                    [f"iamai/mod_a.py", f"iamai/mod_b.py", f"iamai/mod_c.py",
                     f"iamai/mod_d.py", f"tests/test_a.py"],
                    message=f"update modules")
            for i in range(10)
        ]
        r = cr.compute_refraction(commits)
        assert r.scope_distortion > 0.3

    def test_no_cross_area_commits(self):
        """All single-area → no distortion measured."""
        commits = [
            _commit(f"c{i}", i, [f"iamai/mod_{i}.py"], message="update")
            for i in range(5)
        ]
        r = cr.compute_refraction(commits)
        assert r.scope_distortion == 0.0


# ===========================================================================
# Boundary reflection
# ===========================================================================

class TestBoundaryReflection:
    def test_no_reverts(self):
        """No reverts → reflection is 0."""
        commits = [
            _commit(f"c{i}", i, [f"iamai/mod_{i % 3}.py"], message="update")
            for i in range(10)
        ]
        r = cr.compute_refraction(commits)
        assert r.boundary_reflection == 0.0

    def test_all_reverted(self):
        """Every commit is reverted by the next one."""
        commits = []
        for i in range(5):
            commits.append(_commit(
                f"c{2*i}", i * 2,
                ["iamai/core.py"], message="update core",
            ))
            commits.append(_commit(
                f"c{2*i+1}", i * 2 + 1,
                ["iamai/core.py"], message="revert update core",
                is_revert=True,
            ))
        r = cr.compute_refraction(commits)
        assert r.boundary_reflection > 0.0

    def test_revert_outside_window(self):
        """Revert beyond revert_window doesn't count."""
        commits = [
            _commit("c0", 0, ["iamai/core.py"], message="update"),
            _commit("c1", 1, ["iamai/other.py"], message="other"),
            _commit("c2", 2, ["iamai/other.py"], message="other"),
            _commit("c3", 3, ["iamai/other.py"], message="other"),
            _commit("c4", 4, ["iamai/other.py"], message="other"),
            _commit("c5", 5, ["iamai/other.py"], message="other"),
            _commit("c6", 6, ["iamai/core.py"], message="revert update",
                    is_revert=True),
        ]
        r = cr.compute_refraction(commits, revert_window=3)
        # c0's revert at c6 is 6 commits later, beyond window of 3
        assert r.boundary_reflection == 0.0

    def test_partial_revert(self):
        """Revert touching only some of the original files."""
        commits = [
            _commit("c0", 0, ["iamai/core.py", "iamai/utils.py"],
                    message="update core and utils"),
            _commit("c1", 1, ["iamai/core.py"],
                    message="revert core changes", is_revert=True),
        ]
        r = cr.compute_refraction(commits)
        assert r.boundary_reflection > 0.0


# ===========================================================================
# Coupling index
# ===========================================================================

class TestCouplingIndex:
    def test_surgical_crossings(self):
        """Each cross-area commit touches exactly one file per area."""
        commits = [
            _commit(f"c{i}", i,
                    [f"iamai/mod_{i}.py", f"tests/test_mod_{i}.py"],
                    message=f"update mod {i}")
            for i in range(10)
        ]
        r = cr.compute_refraction(commits)
        assert r.coupling_index == 1.0

    def test_scattered_crossings(self):
        """Many files per area in cross-area commits."""
        commits = [
            _commit(f"c{i}", i,
                    [f"iamai/a.py", f"iamai/b.py", f"iamai/c.py",
                     f"tests/x.py", f"tests/y.py", f"tests/z.py"],
                    message="massive update")
            for i in range(5)
        ]
        r = cr.compute_refraction(commits)
        assert r.coupling_index == 0.0

    def test_no_cross_area(self):
        """No cross-area commits → default 1.0."""
        commits = [
            _commit(f"c{i}", i, [f"iamai/mod_{i}.py"], message="update")
            for i in range(5)
        ]
        r = cr.compute_refraction(commits)
        assert r.coupling_index == 1.0


# ===========================================================================
# Boundary coherence
# ===========================================================================

class TestBoundaryCoherence:
    def test_full_coherence(self):
        """Every area in a cross-area commit has matching files."""
        commits = [
            _commit(f"c{i}", i,
                    [f"iamai/mod_{i}.py", f"tests/test_{i}.py"],
                    message=f"update mod {i}")
            for i in range(10)
        ]
        r = cr.compute_refraction(commits)
        assert r.boundary_coherence >= 0.9

    def test_no_cross_area(self):
        """No cross-area commits → default 1.0."""
        commits = [
            _commit(f"c{i}", i, [f"iamai/mod_{i}.py"], message="update")
            for i in range(5)
        ]
        r = cr.compute_refraction(commits)
        assert r.boundary_coherence == 1.0


# ===========================================================================
# Composite score
# ===========================================================================

class TestCompositeScore:
    def test_high_refraction_scenario(self):
        """Clean intent, no reverts, surgical crossings → high score."""
        commits = [
            _commit(f"c{i}", i,
                    [f"iamai/timeout_{i % 3}.py",
                     f"tests/test_timeout_{i % 3}.py"],
                    message=f"fix timeout handling {i}")
            for i in range(10)
        ]
        r = cr.compute_refraction(commits)
        assert r.refraction_score >= 0.60
        assert r.refraction_class in ("transparent", "clear")

    def test_low_refraction_scenario(self):
        """Poor intent, many reverts → low score."""
        commits = []
        for i in range(10):
            commits.append(_commit(
                f"c{2*i}", i * 2,
                ["docs/unrelated.md"],
                message="fix timeout core parameter",
            ))
            commits.append(_commit(
                f"c{2*i+1}", i * 2 + 1,
                ["docs/unrelated.md"],
                message="revert timeout fix",
                is_revert=True,
            ))
        r = cr.compute_refraction(commits)
        assert r.refraction_score < 0.60

    def test_score_bounds(self):
        for n in [2, 5, 10, 20]:
            commits = _sequence(n)
            r = cr.compute_refraction(commits)
            assert 0.0 <= r.refraction_score <= 1.0

    def test_score_is_rounded(self):
        commits = _sequence(10)
        r = cr.compute_refraction(commits)
        assert r.refraction_score == round(r.refraction_score, 4)


# ===========================================================================
# Result dataclass
# ===========================================================================

class TestRefractionResult:
    def test_all_fields(self):
        r = cr.RefractionResult(
            window_commits=10,
            window_hours=24.0,
            intent_preservation=0.8,
            scope_distortion=0.1,
            boundary_reflection=0.05,
            coupling_index=0.9,
            boundary_coherence=0.85,
            refraction_score=0.75,
            refraction_class="clear",
        )
        assert r.window_commits == 10
        assert r.window_hours == 24.0
        assert r.intent_preservation == 0.8
        assert r.scope_distortion == 0.1
        assert r.boundary_reflection == 0.05
        assert r.coupling_index == 0.9
        assert r.boundary_coherence == 0.85
        assert r.refraction_score == 0.75
        assert r.refraction_class == "clear"

    def test_frozen(self):
        r = cr.RefractionResult(
            window_commits=1, window_hours=0.0,
            intent_preservation=0.0, scope_distortion=0.0,
            boundary_reflection=0.0, coupling_index=0.0,
            boundary_coherence=0.0, refraction_score=0.0,
            refraction_class="mirrored",
        )
        with pytest.raises(AttributeError):
            r.refraction_score = 1.0


# ===========================================================================
# Report
# ===========================================================================

class TestRefractionReport:
    def test_report_contains_all_metrics(self):
        r = cr.RefractionResult(
            window_commits=20,
            window_hours=48.0,
            intent_preservation=0.75,
            scope_distortion=0.15,
            boundary_reflection=0.10,
            coupling_index=0.80,
            boundary_coherence=0.90,
            refraction_score=0.68,
            refraction_class="clear",
        )
        report = cr.refraction_report(r)
        assert "Refraction analysis" in report
        assert "20 commits" in report
        assert "48.0h" in report
        assert "clear" in report
        assert "0.68" in report
        assert "75.00%" in report
        assert "0.15" in report
        assert "10.00%" in report
        assert "80.00%" in report
        assert "90.00%" in report

    def test_report_format(self):
        r = cr.RefractionResult(
            window_commits=5, window_hours=10.0,
            intent_preservation=0.5, scope_distortion=0.5,
            boundary_reflection=0.5, coupling_index=0.5,
            boundary_coherence=0.5, refraction_score=0.5,
            refraction_class="refractive",
        )
        report = cr.refraction_report(r)
        lines = report.split("\n")
        assert len(lines) == 8


# ===========================================================================
# Trend analysis
# ===========================================================================

class TestRefractionTrend:
    def test_increasing_trend(self):
        results = [
            cr.RefractionResult(
                window_commits=10, window_hours=24.0,
                intent_preservation=0.5, scope_distortion=0.5,
                boundary_reflection=0.3, coupling_index=0.5,
                boundary_coherence=0.5, refraction_score=0.40,
                refraction_class="refractive",
            ),
            cr.RefractionResult(
                window_commits=10, window_hours=24.0,
                intent_preservation=0.7, scope_distortion=0.2,
                boundary_reflection=0.1, coupling_index=0.8,
                boundary_coherence=0.8, refraction_score=0.70,
                refraction_class="clear",
            ),
            cr.RefractionResult(
                window_commits=10, window_hours=24.0,
                intent_preservation=0.9, scope_distortion=0.1,
                boundary_reflection=0.0, coupling_index=0.95,
                boundary_coherence=0.95, refraction_score=0.90,
                refraction_class="transparent",
            ),
        ]
        t = cr.refraction_trend(results)
        assert t.direction == "increasing"
        assert t.score_delta == pytest.approx(0.50, abs=0.01)
        assert t.earliest_score == 0.40
        assert t.latest_score == 0.90
        assert t.sample_count == 3

    def test_decreasing_trend(self):
        results = [
            cr.RefractionResult(
                window_commits=10, window_hours=24.0,
                intent_preservation=0.9, scope_distortion=0.1,
                boundary_reflection=0.0, coupling_index=0.9,
                boundary_coherence=0.9, refraction_score=0.85,
                refraction_class="transparent",
            ),
            cr.RefractionResult(
                window_commits=10, window_hours=24.0,
                intent_preservation=0.4, scope_distortion=0.6,
                boundary_reflection=0.4, coupling_index=0.3,
                boundary_coherence=0.3, refraction_score=0.30,
                refraction_class="opaque",
            ),
        ]
        t = cr.refraction_trend(results)
        assert t.direction == "decreasing"
        assert t.score_delta == pytest.approx(-0.55, abs=0.01)

    def test_stable_trend(self):
        results = [
            cr.RefractionResult(
                window_commits=10, window_hours=24.0,
                intent_preservation=0.6, scope_distortion=0.3,
                boundary_reflection=0.1, coupling_index=0.7,
                boundary_coherence=0.7, refraction_score=0.55,
                refraction_class="refractive",
            ),
            cr.RefractionResult(
                window_commits=10, window_hours=24.0,
                intent_preservation=0.6, scope_distortion=0.3,
                boundary_reflection=0.1, coupling_index=0.7,
                boundary_coherence=0.7, refraction_score=0.57,
                refraction_class="refractive",
            ),
        ]
        t = cr.refraction_trend(results)
        assert t.direction == "stable"

    def test_single_result(self):
        results = [
            cr.RefractionResult(
                window_commits=10, window_hours=24.0,
                intent_preservation=0.6, scope_distortion=0.3,
                boundary_reflection=0.1, coupling_index=0.7,
                boundary_coherence=0.7, refraction_score=0.55,
                refraction_class="refractive",
            ),
        ]
        t = cr.refraction_trend(results)
        assert t.direction == "stable"
        assert t.sample_count == 1

    def test_empty_results(self):
        t = cr.refraction_trend([])
        assert t.direction == "stable"
        assert t.score_delta == 0.0
        assert t.sample_count == 0


# ===========================================================================
# Trend dataclass
# ===========================================================================

class TestRefractionTrendDataclass:
    def test_fields(self):
        t = cr.RefractionTrend(
            direction="increasing",
            score_delta=0.25,
            earliest_score=0.40,
            latest_score=0.65,
            sample_count=5,
        )
        assert t.direction == "increasing"
        assert t.score_delta == 0.25
        assert t.earliest_score == 0.40
        assert t.latest_score == 0.65
        assert t.sample_count == 5

    def test_frozen(self):
        t = cr.RefractionTrend(
            direction="stable", score_delta=0.0,
            earliest_score=0.5, latest_score=0.5,
            sample_count=1,
        )
        with pytest.raises(AttributeError):
            t.direction = "increasing"


# ===========================================================================
# Integration scenarios
# ===========================================================================

class TestIntegrationScenarios:
    def test_healthy_codebase(self):
        """Clean intent, surgical crossings, no reverts."""
        commits = []
        for i in range(20):
            commits.append(_commit(
                f"c{i}", i,
                [f"iamai/timeout_{i % 3}.py",
                 f"tests/test_timeout_{i % 3}.py"],
                message=f"fix timeout handling {i % 3}",
            ))
        r = cr.compute_refraction(commits)
        assert r.refraction_score >= 0.50
        assert r.window_commits == 20
        assert r.boundary_reflection == 0.0

    def test_noisy_codebase(self):
        """Vague messages, frequent reverts, scattered crossings."""
        commits = []
        for i in range(20):
            if i % 3 == 0:
                commits.append(_commit(
                    f"c{i}", i,
                    ["iamai/a.py", "iamai/b.py", "docs/readme.md",
                     "tools/script.sh"],
                    message="stuff",
                ))
            elif i % 3 == 1:
                commits.append(_commit(
                    f"c{i}", i,
                    ["iamai/a.py"],
                    message="revert stuff",
                    is_revert=True,
                ))
            else:
                commits.append(_commit(
                    f"c{i}", i,
                    ["notes/random.md"],
                    message="notes",
                ))
        r = cr.compute_refraction(commits)
        assert r.boundary_reflection > 0.0

    def test_explicit_areas(self):
        """Commits with explicit area annotations."""
        commits = [
            _commit(f"c{i}", i,
                    [f"iamai/mod_{i}.py"],
                    areas=["core", "api"],
                    message=f"update module {i}")
            for i in range(5)
        ]
        r = cr.compute_refraction(commits)
        assert r.window_commits == 5

    def test_custom_revert_window(self):
        """Wider window catches more reverts."""
        commits = [
            _commit("c0", 0, ["iamai/core.py"], message="update core"),
            _commit("c1", 1, ["iamai/other.py"], message="other"),
            _commit("c2", 2, ["iamai/other.py"], message="other"),
            _commit("c3", 3, ["iamai/other.py"], message="other"),
            _commit("c4", 4, ["iamai/core.py"], message="revert core",
                    is_revert=True),
        ]
        r_narrow = cr.compute_refraction(commits, revert_window=2)
        r_wide = cr.compute_refraction(commits, revert_window=5)
        # Narrow window: c0 not reverted (c4 is 4 commits away)
        assert r_narrow.boundary_reflection <= r_wide.boundary_reflection

    def test_window_hours_single_commit(self):
        r = cr.compute_refraction([
            _commit("c0", 0, ["a.py"], message="init")
        ])
        assert r.window_hours == 0.0

    def test_all_classes_achievable(self):
        """Verify the score range covers all classes."""
        assert cr.classify_refraction(0.0) == "mirrored"
        assert cr.classify_refraction(0.3) == "opaque"
        assert cr.classify_refraction(0.5) == "refractive"
        assert cr.classify_refraction(0.7) == "clear"
        assert cr.classify_refraction(0.9) == "transparent"
