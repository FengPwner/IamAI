"""Tests for iamai/commit_provenance.py — commit origin classification."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.commit_provenance import (
    caretaker_interval,
    classify_commit,
    classify_commits,
    provenance_report,
    provenance_summary,
    provenance_timeline,
)


# ---------------------------------------------------------------------------
# classify_commit — caretaker
# ---------------------------------------------------------------------------

class TestClassifyCaretaker:
    def test_standard_visit(self):
        assert classify_commit(
            "caretaker visit 682: add stroke_diversity module", "Qwen"
        ) == "caretaker"

    def test_visit_lowercase(self):
        assert classify_commit(
            "caretaker visit 1: initial setup", "Qwen"
        ) == "caretaker"

    def test_visit_with_long_message(self):
        msg = (
            "caretaker visit 683: add output_momentum module + 44 tests "
            "— measure whether strokes carry net-new content"
        )
        assert classify_commit(msg, "Qwen") == "caretaker"

    def test_visit_case_insensitive(self):
        assert classify_commit(
            "Caretaker Visit 100: something", "Qwen"
        ) == "caretaker"

    def test_visit_high_number(self):
        assert classify_commit(
            "caretaker visit 9999: deep maintenance", "Qwen"
        ) == "caretaker"

    def test_visit_with_extra_whitespace(self):
        assert classify_commit(
            "  caretaker visit 42: spaced out  ", "Qwen"
        ) == "caretaker"


# ---------------------------------------------------------------------------
# classify_commit — catchup
# ---------------------------------------------------------------------------

class TestClassifyCatchup:
    def test_standard_catchup(self):
        assert classify_commit(
            "catch-up: commit pending changes before process restart", "Qwen"
        ) == "catchup"

    def test_catchup_no_hyphen(self):
        assert classify_commit(
            "catchup: flush backlog", "Qwen"
        ) == "catchup"

    def test_catchup_with_space(self):
        assert classify_commit(
            "catch up: pending changes", "Qwen"
        ) == "catchup"

    def test_catchup_case_insensitive(self):
        assert classify_commit(
            "Catch-Up: restart prep", "Qwen"
        ) == "catchup"


# ---------------------------------------------------------------------------
# classify_commit — backstop
# ---------------------------------------------------------------------------

class TestClassifyBackstop:
    def test_standard_doubao(self):
        assert classify_commit(
            "doubao: hourly backstop report — synced to abc123", "Doubao"
        ) == "backstop"

    def test_doubao_quiet_report(self):
        assert classify_commit(
            "doubao: hourly backstop report — quiet hour at def456",
            "Doubao",
        ) == "backstop"

    def test_doubao_case_insensitive(self):
        assert classify_commit(
            "Doubao: report", "Doubao"
        ) == "backstop"

    def test_doubao_short(self):
        assert classify_commit(
            "doubao: update", "Doubao"
        ) == "backstop"


# ---------------------------------------------------------------------------
# classify_commit — writer_auto
# ---------------------------------------------------------------------------

class TestClassifyWriterAuto:
    def test_auto_stroke(self):
        assert classify_commit(
            "auto-stroke: batch commit 42 strokes", "writer"
        ) == "writer_auto"

    def test_auto_stroke_no_hyphen(self):
        assert classify_commit(
            "auto stroke: batch 10", "writer"
        ) == "writer_auto"

    def test_writer_loop(self):
        assert classify_commit(
            "writer-loop: periodic commit", "writer"
        ) == "writer_auto"

    def test_batch_commit(self):
        assert classify_commit(
            "batch commit 100 strokes", "writer"
        ) == "writer_auto"

    def test_writer_loop_no_hyphen(self):
        assert classify_commit(
            "writer loop: tick", "writer"
        ) == "writer_auto"


# ---------------------------------------------------------------------------
# classify_commit — merge
# ---------------------------------------------------------------------------

class TestClassifyMerge:
    def test_merge_branch(self):
        assert classify_commit(
            "Merge branch 'main' of github.com:...", "Qwen"
        ) == "merge"

    def test_merge_pull_request(self):
        assert classify_commit(
            "Merge pull request #42 from fix/typo", "Qwen"
        ) == "merge"

    def test_rebase(self):
        assert classify_commit(
            "rebase main onto origin/main", "Qwen"
        ) == "merge"

    def test_merge_lowercase(self):
        assert classify_commit(
            "merge branch 'dev'", "Qwen"
        ) == "merge"


# ---------------------------------------------------------------------------
# classify_commit — unknown
# ---------------------------------------------------------------------------

class TestClassifyUnknown:
    def test_random_message(self):
        assert classify_commit(
            "fix typo in README", "someone"
        ) == "unknown"

    def test_empty_subject(self):
        assert classify_commit("", "Qwen") == "unknown"

    def test_whitespace_only(self):
        assert classify_commit("   ", "Qwen") == "unknown"

    def test_unrelated_commit(self):
        assert classify_commit(
            "refactor: simplify config loader", "contributor"
        ) == "unknown"

    def test_initial_commit(self):
        assert classify_commit(
            "Initial commit", "admin"
        ) == "unknown"


# ---------------------------------------------------------------------------
# classify_commit — author fallback
# ---------------------------------------------------------------------------

class TestClassifyAuthorFallback:
    def test_visit_keyword_with_qwen_author(self):
        """Subject mentions 'visit' and author is Qwen → caretaker."""
        assert classify_commit(
            "quick visit: fix broken test", "Qwen"
        ) == "caretaker"

    def test_visit_keyword_with_unknown_author(self):
        """Subject mentions 'visit' but unknown author → unknown."""
        assert classify_commit(
            "quick visit: fix broken test", "random"
        ) == "unknown"


# ---------------------------------------------------------------------------
# classify_commits (batch)
# ---------------------------------------------------------------------------

class TestClassifyCommits:
    def test_empty_list(self):
        assert classify_commits([]) == []

    def test_single_commit(self):
        result = classify_commits([
            ("caretaker visit 1: setup", "Qwen"),
        ])
        assert len(result) == 1
        assert result[0]["category"] == "caretaker"
        assert result[0]["subject"] == "caretaker visit 1: setup"
        assert result[0]["author"] == "Qwen"

    def test_mixed_commits(self):
        result = classify_commits([
            ("caretaker visit 1: x", "Qwen"),
            ("catch-up: flush", "Qwen"),
            ("doubao: report", "Doubao"),
        ])
        assert [r["category"] for r in result] == [
            "caretaker", "catchup", "backstop",
        ]

    def test_preserves_order(self):
        commits = [
            ("catch-up: first", "Qwen"),
            ("caretaker visit 1: second", "Qwen"),
            ("catch-up: third", "Qwen"),
        ]
        result = classify_commits(commits)
        assert [r["category"] for r in result] == [
            "catchup", "caretaker", "catchup",
        ]


# ---------------------------------------------------------------------------
# provenance_report
# ---------------------------------------------------------------------------

class TestProvenanceReport:
    def test_empty(self):
        r = provenance_report([])
        assert r["total"] == 0
        assert r["counts"] == {}
        assert r["ratios"] == {}
        assert r["dominant"] == "unknown"

    def test_single_category(self):
        r = provenance_report([
            ("caretaker visit 1: a", "Qwen"),
            ("caretaker visit 2: b", "Qwen"),
        ])
        assert r["total"] == 2
        assert r["counts"]["caretaker"] == 2
        assert r["ratios"]["caretaker"] == 1.0
        assert r["dominant"] == "caretaker"

    def test_mixed_categories(self):
        r = provenance_report([
            ("caretaker visit 1: x", "Qwen"),
            ("caretaker visit 2: y", "Qwen"),
            ("catch-up: flush", "Qwen"),
            ("doubao: report", "Doubao"),
        ])
        assert r["total"] == 4
        assert r["counts"]["caretaker"] == 2
        assert r["counts"]["catchup"] == 1
        assert r["counts"]["backstop"] == 1
        assert r["ratios"]["caretaker"] == 0.5
        assert r["dominant"] == "caretaker"

    def test_ratios_sum_to_one(self):
        r = provenance_report([
            ("caretaker visit 1: x", "Qwen"),
            ("catch-up: flush", "Qwen"),
            ("doubao: report", "Doubao"),
        ])
        total_ratio = sum(r["ratios"].values())
        assert abs(total_ratio - 1.0) < 0.01

    def test_classified_list_included(self):
        r = provenance_report([
            ("caretaker visit 1: x", "Qwen"),
        ])
        assert len(r["classified"]) == 1
        assert r["classified"][0]["category"] == "caretaker"

    def test_realistic_history(self):
        """Simulate a realistic commit history from the IamAI repo."""
        commits = [
            ("caretaker visit 682: add stroke_diversity", "Qwen"),
            ("catch-up: commit pending changes", "Qwen"),
            ("doubao: hourly backstop report", "Doubao"),
            ("caretaker visit 681: add cadence_jitter", "Qwen"),
            ("catch-up: commit pending changes", "Qwen"),
            ("doubao: hourly backstop report", "Doubao"),
            ("caretaker visit 680: add writer_handoff", "Qwen"),
            ("catch-up: commit pending changes", "Qwen"),
        ]
        r = provenance_report(commits)
        assert r["total"] == 8
        assert r["counts"]["caretaker"] == 3
        assert r["counts"]["catchup"] == 3
        assert r["counts"]["backstop"] == 2
        assert r["dominant"] in ("caretaker", "catchup")


# ---------------------------------------------------------------------------
# provenance_summary
# ---------------------------------------------------------------------------

class TestProvenanceSummary:
    def test_empty_report(self):
        r = provenance_report([])
        s = provenance_summary(r)
        assert "0 commits" in s

    def test_basic_summary(self):
        r = provenance_report([
            ("caretaker visit 1: x", "Qwen"),
            ("caretaker visit 2: y", "Qwen"),
            ("catch-up: flush", "Qwen"),
        ])
        s = provenance_summary(r)
        assert "3 commits" in s
        assert "caretaker" in s
        assert "catchup" in s
        assert "66.7%" in s

    def test_dominant_in_summary(self):
        r = provenance_report([
            ("doubao: report 1", "Doubao"),
            ("doubao: report 2", "Doubao"),
            ("doubao: report 3", "Doubao"),
            ("catch-up: flush", "Qwen"),
        ])
        s = provenance_summary(r)
        assert "backstop" in s
        assert "dominant source: backstop" in s


# ---------------------------------------------------------------------------
# provenance_timeline
# ---------------------------------------------------------------------------

class TestProvenanceTimeline:
    def test_empty(self):
        assert provenance_timeline([], window_size=5) == []

    def test_single_window(self):
        commits = [("caretaker visit %d: x" % i, "Qwen") for i in range(5)]
        tl = provenance_timeline(commits, window_size=5)
        assert len(tl) == 1
        assert tl[0]["dominant"] == "caretaker"
        assert tl[0]["start"] == 0
        assert tl[0]["end"] == 5

    def test_multiple_windows(self):
        commits = [("caretaker visit %d: x" % i, "Qwen") for i in range(5)]
        commits += [("catch-up: flush", "Qwen") for _ in range(5)]
        tl = provenance_timeline(commits, window_size=5)
        assert len(tl) == 2
        assert tl[0]["dominant"] == "caretaker"
        assert tl[1]["dominant"] == "catchup"

    def test_partial_last_window(self):
        commits = [("caretaker visit %d: x" % i, "Qwen") for i in range(7)]
        tl = provenance_timeline(commits, window_size=5)
        assert len(tl) == 2
        assert tl[0]["end"] == 5
        assert tl[1]["start"] == 5
        assert tl[1]["end"] == 7

    def test_window_size_one(self):
        commits = [
            ("caretaker visit 1: x", "Qwen"),
            ("catch-up: flush", "Qwen"),
        ]
        tl = provenance_timeline(commits, window_size=1)
        assert len(tl) == 2
        assert tl[0]["dominant"] == "caretaker"
        assert tl[1]["dominant"] == "catchup"

    def test_window_size_zero_clamped(self):
        """Window size 0 should be clamped to 1."""
        commits = [("caretaker visit 1: x", "Qwen")]
        tl = provenance_timeline(commits, window_size=0)
        assert len(tl) == 1

    def test_window_indices_sequential(self):
        commits = [("catch-up: x", "Qwen") for _ in range(12)]
        tl = provenance_timeline(commits, window_size=4)
        assert [w["window_index"] for w in tl] == [0, 1, 2]


# ---------------------------------------------------------------------------
# caretaker_interval
# ---------------------------------------------------------------------------

class TestCaretakerInterval:
    def test_empty(self):
        r = caretaker_interval([])
        assert r["caretaker_count"] == 0
        assert r["gaps"] == []
        assert r["avg_gap"] == 0.0

    def test_single_caretaker(self):
        r = caretaker_interval([
            ("caretaker visit 1: x", "Qwen"),
            ("catch-up: flush", "Qwen"),
        ])
        assert r["caretaker_count"] == 1
        assert r["gaps"] == []
        assert r["avg_gap"] == 0.0

    def test_two_consecutive_caretakers(self):
        r = caretaker_interval([
            ("caretaker visit 1: x", "Qwen"),
            ("caretaker visit 2: y", "Qwen"),
        ])
        assert r["caretaker_count"] == 2
        assert r["gaps"] == [0]
        assert r["avg_gap"] == 0.0

    def test_gaps_between_caretakers(self):
        r = caretaker_interval([
            ("caretaker visit 1: x", "Qwen"),
            ("catch-up: flush", "Qwen"),
            ("catch-up: flush", "Qwen"),
            ("caretaker visit 2: y", "Qwen"),
            ("doubao: report", "Doubao"),
            ("caretaker visit 3: z", "Qwen"),
        ])
        assert r["caretaker_count"] == 3
        assert r["gaps"] == [2, 1]
        assert r["avg_gap"] == 1.5
        assert r["max_gap"] == 2
        assert r["min_gap"] == 1

    def test_large_gap(self):
        commits = [("caretaker visit 1: x", "Qwen")]
        commits += [("catch-up: flush", "Qwen") for _ in range(10)]
        commits.append(("caretaker visit 2: y", "Qwen"))
        r = caretaker_interval(commits)
        assert r["caretaker_count"] == 2
        assert r["gaps"] == [10]
        assert r["max_gap"] == 10

    def test_no_caretakers(self):
        r = caretaker_interval([
            ("catch-up: flush", "Qwen"),
            ("doubao: report", "Doubao"),
            ("catch-up: flush", "Qwen"),
        ])
        assert r["caretaker_count"] == 0
        assert r["gaps"] == []
        assert r["avg_gap"] == 0.0

    def test_realistic_pattern(self):
        """Simulate the IamAI pattern: caretaker every ~4 commits."""
        commits = []
        for i in range(680, 684):
            commits.append((f"caretaker visit {i}: module", "Qwen"))
            commits.append(("catch-up: flush", "Qwen"))
            commits.append(("doubao: report", "Doubao"))
        r = caretaker_interval(commits)
        assert r["caretaker_count"] == 4
        assert len(r["gaps"]) == 3
        assert all(g == 2 for g in r["gaps"])
        assert r["avg_gap"] == 2.0
