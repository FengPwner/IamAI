#!/usr/bin/env python3
"""tests for scripts/repo_echo.py — echo/repetition pattern detector."""

import json
import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from repo_echo import (
    score_message_diversity,
    score_file_churn,
    score_topic_drift,
    score_rhythm_monotony,
    compute_echo_score,
    format_bar,
    get_recent_commits,
    get_file_changes,
)


# ─── message diversity ────────────────────────────────────────────

class TestMessageDiversity:
    def test_all_unique_messages(self):
        commits = [
            {"hash": "a1", "message": "add feature X", "timestamp": "2026-01-01T00:00:00+00:00"},
            {"hash": "a2", "message": "fix bug in Y", "timestamp": "2026-01-01T01:00:00+00:00"},
            {"hash": "a3", "message": "refactor Z module", "timestamp": "2026-01-01T02:00:00+00:00"},
            {"hash": "a4", "message": "update documentation", "timestamp": "2026-01-01T03:00:00+00:00"},
        ]
        score = score_message_diversity(commits)
        assert score == 0.0, f"all unique should give 0 echo, got {score}"

    def test_all_identical_messages(self):
        commits = [
            {"hash": f"b{i}", "message": "update readme",
             "timestamp": f"2026-01-01T{i:02d}:00:00+00:00"}
            for i in range(10)
        ]
        score = score_message_diversity(commits)
        # 1 unique out of 10 → ratio=0.1 → (1-0.1)*25 = 22.5
        assert score == 22.5, f"all identical should give 22.5 echo, got {score}"

    def test_empty_commits(self):
        score = score_message_diversity([])
        assert score == 25.0, "empty should return worst case"

    def test_half_diverse(self):
        commits = [
            {"hash": "c1", "message": "add alpha", "timestamp": "2026-01-01T00:00:00+00:00"},
            {"hash": "c2", "message": "add alpha", "timestamp": "2026-01-01T01:00:00+00:00"},
            {"hash": "c3", "message": "add beta", "timestamp": "2026-01-01T02:00:00+00:00"},
            {"hash": "c4", "message": "add gamma", "timestamp": "2026-01-01T03:00:00+00:00"},
        ]
        score = score_message_diversity(commits)
        # 3 unique out of 4 = 0.75 ratio → (1-0.75)*25 = 6.25
        assert abs(score - 6.25) < 0.01, f"expected 6.25, got {score}"

    def test_caretaker_prefix_stripped(self):
        """caretaker visit prefixes should be normalized — different suffixes stay different."""
        commits = [
            {"hash": "d1", "message": "caretaker visit 100: add stuff",
             "timestamp": "2026-01-01T00:00:00+00:00"},
            {"hash": "d2", "message": "caretaker visit 101: add stuff",
             "timestamp": "2026-01-01T01:00:00+00:00"},
            {"hash": "d3", "message": "add feature alpha",
             "timestamp": "2026-01-01T02:00:00+00:00"},
            {"hash": "d4", "message": "refactor beta module",
             "timestamp": "2026-01-01T03:00:00+00:00"},
        ]
        score = score_message_diversity(commits)
        # after stripping: " 100: add stuff", " 101: add stuff", "add feature alpha", "refactor beta module"
        # 4 unique out of 4 → ratio=1.0 → echo=0.0
        assert score == 0.0, f"all different after strip should give 0 echo, got {score}"

    def test_catch_up_prefix_stripped(self):
        """repeated catch-up commits should show high echo."""
        commits = [
            {"hash": f"e{i}", "message": "catch-up: commit pending changes before restart",
             "timestamp": f"2026-01-01T{i:02d}:00:00+00:00"}
            for i in range(10)
        ]
        score = score_message_diversity(commits)
        # all strip to "commit pending changes before restart" → 1/10 unique → (1-0.1)*25=22.5
        assert score == 22.5, f"repeated catch-up should give high echo, got {score}"


# ─── file churn ────────────────────────────────────────────────────

class TestFileChurn:
    def test_empty_changes(self):
        score = score_file_churn([])
        assert score == 25.0

    def test_well_distributed(self):
        """many different files, no concentration."""
        changes = [[f"dir/file_{i}.py"] for i in range(100)]
        score = score_file_churn(changes)
        assert score < 5.0, f"well-distributed should be low echo, got {score}"

    def test_highly_concentrated(self):
        """same 3 files edited 100 times."""
        changes = [["data/strokes.jsonl", "docs/DEVLOG.md", "docs/GARDEN.md"]
                   for _ in range(100)]
        score = score_file_churn(changes)
        assert score > 15.0, f"concentrated should be high echo, got {score}"

    def test_single_file_repeated(self):
        changes = [["data/strokes.jsonl"] for _ in range(50)]
        score = score_file_churn(changes)
        assert score == 25.0, f"single file repeated = max echo, got {score}"

    def test_moderate_churn(self):
        """moderate concentration: ~20 unique files, a few hotspots."""
        changes = []
        for i in range(20):
            changes.append([f"notes/note_{i}.md", f"data/strokes.jsonl"])
        # 21 unique files, top 10 captures ~30 of 40 changes → ratio=0.75
        score = score_file_churn(changes)
        assert 10.0 <= score <= 25.0, f"moderate churn should be in range, got {score}"


# ─── topic drift ───────────────────────────────────────────────────

class TestTopicDrift:
    def test_empty(self):
        score = score_topic_drift([])
        assert score == 12.5, "empty input should return neutral score"

    def test_too_few_commits(self):
        changes = [["file.py"], ["file.py"], ["file.py"]]
        score = score_topic_drift(changes)
        assert score == 12.5, "fewer than 4 commits = neutral"

    def test_no_drift_same_distribution(self):
        """both halves touch the same directories in same proportions."""
        changes = []
        for _ in range(20):
            changes.append(["notes/a.md", "docs/b.md", "scripts/c.py"])
        score = score_topic_drift(changes)
        # identical distributions → similarity ≈ 1.0 → high echo
        assert score >= 20.0, f"no drift should be high echo, got {score}"

    def test_strong_drift_different_areas(self):
        """first half: notes/ and docs/; second half: tests/ and scripts/."""
        changes = []
        for _ in range(10):
            changes.append(["notes/a.md", "docs/b.md"])
        for _ in range(10):
            changes.append(["tests/test_x.py", "scripts/tool.py"])
        score = score_topic_drift(changes)
        assert score < 5.0, f"strong drift should be low echo, got {score}"

    def test_partial_drift(self):
        changes = []
        for _ in range(10):
            changes.append(["notes/a.md", "docs/b.md"])
        for _ in range(5):
            changes.append(["notes/a.md", "tests/test_x.py"])
        for _ in range(5):
            changes.append(["scripts/tool.py", "data/strokes.jsonl"])
        score = score_topic_drift(changes)
        assert 0.0 <= score <= 15.0, f"partial drift should be moderate, got {score}"


# ─── rhythm monotony ──────────────────────────────────────────────

class TestRhythmMonotony:
    def test_too_few_commits(self):
        commits = [
            {"hash": "x1", "message": "a", "timestamp": "2026-01-01T00:00:00+00:00"},
            {"hash": "x2", "message": "b", "timestamp": "2026-01-01T01:00:00+00:00"},
        ]
        score = score_rhythm_monotony(commits)
        assert score == 12.5, "fewer than 3 commits = neutral"

    def test_perfectly_uniform(self):
        """exactly 10-minute intervals → suspicious."""
        commits = [
            {"hash": f"u{i}", "message": f"stroke {i}",
             "timestamp": f"2026-01-01T{i // 6:02d}:{(i % 6) * 10:02d}:00+00:00"}
            for i in range(12)
        ]
        score = score_rhythm_monotony(commits)
        assert score >= 15.0, f"uniform rhythm should be high echo, got {score}"

    def test_highly_variable(self):
        """wildly varying intervals → healthy."""
        timestamps = [
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:01:00+00:00",  # 1 min
            "2026-01-01T02:00:00+00:00",  # 119 min
            "2026-01-01T02:02:00+00:00",  # 2 min
            "2026-01-01T05:00:00+00:00",  # 178 min
            "2026-01-01T05:00:30+00:00",  # 0.5 min
        ]
        commits = [
            {"hash": f"v{i}", "message": f"msg {i}", "timestamp": ts}
            for i, ts in enumerate(timestamps)
        ]
        score = score_rhythm_monotony(commits)
        assert score < 5.0, f"variable rhythm should be low echo, got {score}"

    def test_empty(self):
        score = score_rhythm_monotony([])
        assert score == 12.5


# ─── compute echo score & grading ─────────────────────────────────

class TestComputeEchoScore:
    def test_minimum_score(self):
        total, grade = compute_echo_score(0, 0, 0, 0)
        assert total == 0.0
        assert grade == "VARIED"

    def test_maximum_score(self):
        total, grade = compute_echo_score(25, 25, 25, 25)
        assert total == 100.0
        assert grade == "STUCK"

    def test_stable_grade(self):
        total, grade = compute_echo_score(8, 10, 5, 7)
        assert 21 <= total <= 45, f"expected STABLE range, got {total}"
        assert grade == "STABLE"

    def test_echoing_grade(self):
        total, grade = compute_echo_score(15, 15, 15, 15)
        assert 46 <= total <= 70, f"expected ECHOING range, got {total}"
        assert grade == "ECHOING"

    def test_clamp_above_100(self):
        total, grade = compute_echo_score(30, 30, 30, 30)
        assert total == 100.0, "should clamp to 100"

    def test_boundary_varied_stable(self):
        total, grade = compute_echo_score(5, 5, 5, 6)
        assert total == 21.0
        assert grade == "STABLE"

    def test_boundary_stable_echoing(self):
        total, grade = compute_echo_score(12, 12, 11, 11)
        assert total == 46.0
        assert grade == "ECHOING"


# ─── format_bar ───────────────────────────────────────────────────

class TestFormatBar:
    def test_zero_value(self):
        bar = format_bar(0, 25, 20)
        assert bar == "░" * 20

    def test_max_value(self):
        bar = format_bar(25, 25, 20)
        assert bar == "█" * 20

    def test_half_value(self):
        bar = format_bar(12.5, 25, 20)
        assert len(bar) == 20
        assert "█" in bar
        assert "░" in bar

    def test_custom_width(self):
        bar = format_bar(5, 10, 10)
        assert len(bar) == 10


# ─── integration with real repo ───────────────────────────────────

class TestIntegration:
    """tests that require the actual repo — skipped if not available."""

    def test_get_recent_commits(self):
        repo = os.path.join(os.path.dirname(__file__), "..")
        commits = get_recent_commits(repo, 5)
        assert len(commits) > 0, "should find at least one commit"
        assert "hash" in commits[0]
        assert "message" in commits[0]
        assert "timestamp" in commits[0]

    def test_get_file_changes(self):
        repo = os.path.join(os.path.dirname(__file__), "..")
        changes = get_file_changes(repo, 5)
        assert len(changes) > 0, "should find file changes"
        assert isinstance(changes[0], list)

    def test_full_analysis_returns_valid(self):
        """run full analysis on this repo and check output shape."""
        from repo_echo import analyze
        import io
        from contextlib import redirect_stdout

        repo = os.path.join(os.path.dirname(__file__), "..")
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = analyze(repo, 10, as_json=True)

        assert exit_code in (0, 1, 2)
        output = json.loads(buf.getvalue())
        assert "echo_score" in output
        assert "grade" in output
        assert output["grade"] in ("VARIED", "STABLE", "ECHOING", "STUCK")
        assert 0 <= output["echo_score"] <= 100
        assert "metrics" in output
        assert len(output["metrics"]) == 4


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
