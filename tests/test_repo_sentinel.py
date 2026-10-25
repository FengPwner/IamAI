#!/usr/bin/env python3
"""tests for scripts/repo_sentinel.py — failure-mode sentinel detector."""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from repo_sentinel import (
    is_catchup,
    is_intervention,
    is_productive,
    score_recovery_ratio,
    score_stall_frequency,
    score_intervention_depth,
    score_backlog_oscillation,
    compute_sentinel_score,
    format_bar,
    get_commit_log,
)


def _make_commit(msg, ts="2026-01-01T00:00:00+00:00", author="qwen"):
    """helper: build a commit dict."""
    return {"hash": "abc12345", "message": msg, "timestamp": ts, "author": author}


# ── classification ────────────────────────────────────────────────


class TestClassification:
    def test_catchup_exact(self):
        assert is_catchup("catch-up: commit pending changes before restart")

    def test_catchup_no_hyphen(self):
        assert is_catchup("catchup: flush pending strokes")

    def test_catchup_backlog(self):
        assert is_catchup("backlog commit: overnight accumulation")

    def test_catchup_flush(self):
        assert is_catchup("flush pending changes")

    def test_not_catchup(self):
        assert not is_catchup("add repo_sentinel.py (failure-mode sentinel)")

    def test_intervention_caretaker_visit(self):
        assert is_intervention("caretaker visit 337: add sentinel tool")

    def test_intervention_caretaker_recovery(self):
        assert is_intervention("caretaker recovery after overnight stall")

    def test_intervention_process_restart(self):
        assert is_intervention("process restart: writer and batch")

    def test_intervention_recovery_colon(self):
        assert is_intervention("recovery: re-push after force-push race")

    def test_not_intervention(self):
        assert not is_intervention("add thought about entropy")

    def test_productive_normal(self):
        assert is_productive("add repo_graft.py (multi-writer health scorer)")
        assert is_productive("update METRICS.md with graft data")
        assert not is_productive("catch-up: commit pending")
        assert not is_productive("caretaker visit 100: check in")


# ── recovery ratio ────────────────────────────────────────────────


class TestRecoveryRatio:
    def test_empty(self):
        score = score_recovery_ratio([])
        assert score == 25.0

    def test_all_productive(self):
        commits = [_make_commit(f"add feature {i}",
                                f"2026-01-01T{i:02d}:00:00+00:00")
                   for i in range(20)]
        score = score_recovery_ratio(commits)
        assert score == 0.0

    def test_all_recovery(self):
        commits = [_make_commit("catch-up: flush pending",
                                f"2026-01-01T{i:02d}:00:00+00:00")
                   for i in range(20)]
        score = score_recovery_ratio(commits)
        assert score == 25.0

    def test_half_recovery(self):
        commits = []
        for i in range(20):
            if i % 2 == 0:
                commits.append(_make_commit("catch-up: flush",
                                            f"2026-01-01T{i:02d}:00:00+00:00"))
            else:
                commits.append(_make_commit(f"add feature {i}",
                                            f"2026-01-01T{i:02d}:00:00+00:00"))
        score = score_recovery_ratio(commits)
        # 10/20 = 0.5 ratio → 0.5 * 50 = 25.0
        assert score == 25.0

    def test_ten_percent_recovery(self):
        commits = []
        for i in range(100):
            if i < 10:
                commits.append(_make_commit("catch-up: flush",
                                            f"2026-01-01T{i:02d}:00:00+00:00"))
            else:
                commits.append(_make_commit(f"add feature {i}",
                                            f"2026-01-01T{i:02d}:00:00+00:00"))
        score = score_recovery_ratio(commits)
        # 10/100 = 0.1 → 0.1 * 50 = 5.0
        assert score == 5.0

    def test_mixed_recovery_and_intervention(self):
        commits = []
        for i in range(20):
            if i < 3:
                commits.append(_make_commit("catch-up: flush",
                                            f"2026-01-01T{i:02d}:00:00+00:00"))
            elif i < 5:
                commits.append(_make_commit("caretaker visit 10: check",
                                            f"2026-01-01T{i:02d}:00:00+00:00"))
            else:
                commits.append(_make_commit(f"add note {i}",
                                            f"2026-01-01T{i:02d}:00:00+00:00"))
        score = score_recovery_ratio(commits)
        # 5/20 = 0.25 → 0.25 * 50 = 12.5
        assert score == 12.5


# ── stall frequency ───────────────────────────────────────────────


class TestStallFrequency:
    def test_too_few_commits(self):
        score = score_stall_frequency([_make_commit("a"), _make_commit("b")])
        assert score == 12.5

    def test_no_stalls(self):
        """commits every 10 minutes, cadence=600 → no stalls."""
        commits = [
            _make_commit(f"stroke {i}", f"2026-01-01T{i // 6:02d}:{(i % 6) * 10:02d}:00+00:00")
            for i in range(20)
        ]
        score = score_stall_frequency(commits, expected_cadence_s=600)
        assert score == 0.0

    def test_all_stalls(self):
        """commits every 2 hours, cadence=600 → all gaps > 1200s."""
        commits = [
            _make_commit(f"stroke {i}", f"2026-01-01T{i * 2:02d}:00:00+00:00")
            for i in range(10)
        ]
        score = score_stall_frequency(commits, expected_cadence_s=600)
        # every interval is 7200s > 1200s threshold → stall_ratio=1.0 → 25
        assert score == 25.0

    def test_some_stalls(self):
        """mix of normal and stalled intervals."""
        timestamps = [
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:10:00+00:00",  # 10 min (normal)
            "2026-01-01T00:20:00+00:00",  # 10 min (normal)
            "2026-01-01T02:00:00+00:00",  # 100 min (stall!)
            "2026-01-01T02:10:00+00:00",  # 10 min (normal)
            "2026-01-01T04:00:00+00:00",  # 110 min (stall!)
            "2026-01-01T04:10:00+00:00",  # 10 min (normal)
        ]
        commits = [_make_commit(f"msg {i}", ts) for i, ts in enumerate(timestamps)]
        score = score_stall_frequency(commits, expected_cadence_s=600)
        # 2 stalls out of 6 intervals = 0.333 ratio → score = min(1, 0.333/0.6)*25 ≈ 13.9
        assert 10.0 <= score <= 18.0, f"expected moderate stall score, got {score}"

    def test_empty(self):
        score = score_stall_frequency([])
        assert score == 12.5


# ── intervention depth ────────────────────────────────────────────


class TestInterventionDepth:
    def test_empty(self):
        score = score_intervention_depth([])
        assert score == 12.5

    def test_no_interventions(self):
        """all productive — no interventions needed."""
        commits = [_make_commit(f"add feature {i}") for i in range(20)]
        score = score_intervention_depth(commits)
        assert score == 0.0

    def test_shallow_depth(self):
        """intervention → 1 productive → intervention → 1 productive → ..."""
        commits = []
        for i in range(20):
            if i % 2 == 0:
                commits.append(_make_commit("caretaker visit: restart"))
            else:
                commits.append(_make_commit(f"add note {i}"))
        score = score_intervention_depth(commits)
        # avg depth = 1 → score should be 25.0
        assert score == 25.0

    def test_deep_runs(self):
        """intervention → 15 productive → intervention → 15 productive."""
        commits = []
        for _ in range(2):
            commits.append(_make_commit("caretaker visit: restart"))
            for j in range(15):
                commits.append(_make_commit(f"add feature {j}"))
        score = score_intervention_depth(commits)
        # avg depth = 15 → score should be 0.0
        assert score == 0.0

    def test_moderate_depth(self):
        """intervention → 5 productive → intervention → 5 productive."""
        commits = []
        for _ in range(3):
            commits.append(_make_commit("caretaker visit: check"))
            for j in range(5):
                commits.append(_make_commit(f"add note {j}"))
        score = score_intervention_depth(commits)
        # avg depth = 5 → score = (10-5)/9 * 25 ≈ 13.9
        assert 10.0 <= score <= 18.0, f"expected moderate, got {score}"

    def test_single_intervention_at_end(self):
        """one intervention at the start (newest), rest productive."""
        commits = [_make_commit("caretaker visit: restart")]
        commits.extend(_make_commit(f"add {i}") for i in range(10))
        score = score_intervention_depth(commits)
        # found_intervention=True but runs is empty (no second intervention)
        assert score == 12.5

    def test_catchup_counts_as_intervention(self):
        """catch-up commits should also reset the run counter."""
        commits = [
            _make_commit("caretaker visit: restart"),
            _make_commit("add feature A"),
            _make_commit("add feature B"),
            _make_commit("catch-up: flush pending"),
            _make_commit("add feature C"),
            _make_commit("add feature D"),
            _make_commit("caretaker visit: check"),
        ]
        score = score_intervention_depth(commits)
        # runs: [2, 2] → avg=2 → score = (10-2)/9*25 ≈ 22.2
        assert 18.0 <= score <= 25.0, f"expected shallow depth, got {score}"


# ── backlog oscillation ──────────────────────────────────────────


class TestBacklogOscillation:
    def test_too_few_commits(self):
        commits = [_make_commit(f"msg {i}") for i in range(4)]
        score = score_backlog_oscillation(commits)
        assert score == 12.5

    def test_all_productive_no_oscillation(self):
        commits = [_make_commit(f"add feature {i}") for i in range(30)]
        score = score_backlog_oscillation(commits)
        assert score == 0.0

    def test_heavy_oscillation(self):
        """alternating: 3 productive, 1 catch-up, repeat.
        commits are newest-first (git log order); reversed inside the function
        gives chronological [0,0,0,1, 0,0,0,1, ...]."""
        chronological = []
        for i in range(40):
            if i % 4 == 3:
                chronological.append(_make_commit("catch-up: flush pending"))
            else:
                chronological.append(_make_commit(f"add note {i}"))
        # newest-first: reverse so index 0 = newest
        commits = list(reversed(chronological))
        score = score_backlog_oscillation(commits)
        assert score > 15.0, f"expected high oscillation, got {score}"

    def test_clustered_recovery(self):
        """one big cluster of recovery in the middle, rest productive."""
        commits = []
        for i in range(30):
            if 12 <= i <= 17:
                commits.append(_make_commit("catch-up: flush"))
            else:
                commits.append(_make_commit(f"add feature {i}"))
        score = score_backlog_oscillation(commits)
        # only 2 transitions (productive→recovery, recovery→productive) → low density
        assert score < 10.0, f"expected low oscillation for single cluster, got {score}"

    def test_empty(self):
        score = score_backlog_oscillation([])
        assert score == 12.5


# ── compute sentinel score & grading ─────────────────────────────


class TestComputeSentinelScore:
    def test_minimum(self):
        total, grade = compute_sentinel_score(0, 0, 0, 0)
        assert total == 0.0
        assert grade == "VIGILANT"

    def test_maximum(self):
        total, grade = compute_sentinel_score(25, 25, 25, 25)
        assert total == 100.0
        assert grade == "ASLEEP"

    def test_watchful(self):
        total, grade = compute_sentinel_score(8, 7, 6, 5)
        assert 21 <= total <= 45, f"expected WATCHFUL, got {total}"
        assert grade == "WATCHFUL"

    def test_drowsy(self):
        total, grade = compute_sentinel_score(15, 14, 12, 10)
        assert 46 <= total <= 70, f"expected DROWSY, got {total}"
        assert grade == "DROWSY"

    def test_clamp_above_100(self):
        total, grade = compute_sentinel_score(30, 30, 30, 30)
        assert total == 100.0

    def test_boundary_vigilant_watchful(self):
        total, grade = compute_sentinel_score(5, 5, 5, 6)
        assert total == 21.0
        assert grade == "WATCHFUL"

    def test_boundary_watchful_drowsy(self):
        total, grade = compute_sentinel_score(12, 12, 11, 11)
        assert total == 46.0
        assert grade == "DROWSY"


# ── format_bar ────────────────────────────────────────────────────


class TestFormatBar:
    def test_zero(self):
        bar = format_bar(0, 25, 20)
        assert bar == "░" * 20

    def test_max(self):
        bar = format_bar(25, 25, 20)
        assert bar == "█" * 20

    def test_half(self):
        bar = format_bar(12.5, 25, 20)
        assert len(bar) == 20
        assert "█" in bar
        assert "░" in bar


# ── integration ───────────────────────────────────────────────────


class TestIntegration:
    def test_get_commit_log(self):
        repo = os.path.join(os.path.dirname(__file__), "..")
        commits = get_commit_log(repo, 5)
        assert len(commits) > 0
        assert "hash" in commits[0]
        assert "message" in commits[0]
        assert "author" in commits[0]

    def test_full_analysis_json(self):
        from repo_sentinel import analyze
        import io
        from contextlib import redirect_stdout

        repo = os.path.join(os.path.dirname(__file__), "..")
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = analyze(repo, 50, as_json=True, cadence=600)

        assert exit_code in (0, 1, 2)
        output = json.loads(buf.getvalue())
        assert "sentinel_score" in output
        assert "grade" in output
        assert output["grade"] in ("VIGILANT", "WATCHFUL", "DROWSY", "ASLEEP")
        assert 0 <= output["sentinel_score"] <= 100
        assert "commit_breakdown" in output
        assert "productive" in output["commit_breakdown"]

    def test_full_analysis_text(self):
        from repo_sentinel import analyze
        import io
        from contextlib import redirect_stdout

        repo = os.path.join(os.path.dirname(__file__), "..")
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = analyze(repo, 50, as_json=False, cadence=600)

        assert exit_code in (0, 1, 2)
        text = buf.getvalue()
        assert "SENTINEL SCORE" in text
        assert "VIGILANT" in text or "WATCHFUL" in text or "DROWSY" in text or "ASLEEP" in text


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
