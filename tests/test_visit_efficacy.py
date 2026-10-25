"""Tests for iamai.visit_efficacy."""

import pytest

from iamai.visit_efficacy import (
    CommitClassification,
    EfficacyReport,
    classify_commit,
    classify_commits,
    efficacy_report,
    efficacy_summary,
    REPAIR_KEYWORDS,
    PROGRESS_KEYWORDS,
)


# ---------------------------------------------------------------------------
# classify_commit
# ---------------------------------------------------------------------------

class TestClassifyCommit:
    def test_repair_restart(self):
        c = classify_commit("restart writer after OOM kill")
        assert c.kind == "repair"
        assert c.matched_keyword == "restart"

    def test_repair_flush(self):
        c = classify_commit("flush 9 pending files after lock cleanup")
        assert c.kind == "repair"
        # flush hits first in REPAIR_KEYWORDS
        assert c.matched_keyword == "flush"

    def test_repair_catch_up(self):
        c = classify_commit("catch-up: commit pending changes before restart")
        assert c.kind == "repair"
        # "restart" is checked first in REPAIR_KEYWORDS and appears in message
        assert c.matched_keyword == "restart"

    def test_progress_add_module(self):
        c = classify_commit("add lock_scar module (34 tests pass)")
        assert c.kind == "progress"
        assert c.matched_keyword == "add"

    def test_progress_caretaker_visit(self):
        c = classify_commit(
            "caretaker visit 288: add lock_scar module"
        )
        # No repair keyword matches; "add" is the first PROGRESS_KEYWORD hit
        assert c.kind == "progress"
        assert c.matched_keyword == "add"

    def test_progress_note(self):
        c = classify_commit("add note on commit rhythm as health signal")
        assert c.kind == "progress"

    def test_other_commit(self):
        c = classify_commit("bump version to 0.4.1")
        assert c.kind == "other"

    def test_empty_message(self):
        c = classify_commit("")
        assert c.kind == "other"

    def test_repair_recovery(self):
        c = classify_commit("recovery: re-sync after push race")
        assert c.kind == "repair"
        assert c.matched_keyword == "recovery"

    def test_repair_lock_cleanup(self):
        c = classify_commit("lock cleanup: remove stale index.lock")
        assert c.kind == "repair"
        assert c.matched_keyword == "lock cleanup"

    def test_repair_push_race(self):
        c = classify_commit("push race detected, pulling before push")
        assert c.kind == "repair"
        assert c.matched_keyword == "push race"

    def test_progress_tests_pass(self):
        c = classify_commit("add commit_rhythm module (37 tests pass)")
        assert c.kind == "progress"

    def test_progress_new_feature(self):
        c = classify_commit("new: visit efficacy tracker")
        assert c.kind == "progress"

    def test_progress_caretaker_visit_keyword_only(self):
        c = classify_commit("caretaker visit 290: refactor pipeline")
        # No repair keyword; "caretaker visit" is the matching progress keyword
        assert c.kind == "progress"
        assert c.matched_keyword == "caretaker visit"


# ---------------------------------------------------------------------------
# classify_commits
# ---------------------------------------------------------------------------

class TestClassifyCommits:
    def test_empty_list(self):
        assert classify_commits([]) == []

    def test_mixed(self):
        msgs = [
            "add feature X",
            "restart writer",
            "flush pending files",
            "add note about Y",
        ]
        results = classify_commits(msgs)
        assert len(results) == 4
        assert results[0].kind == "progress"
        assert results[1].kind == "repair"
        assert results[2].kind == "repair"
        assert results[3].kind == "progress"


# ---------------------------------------------------------------------------
# efficacy_report
# ---------------------------------------------------------------------------

class TestEfficacyReport:
    def test_empty_messages(self):
        r = efficacy_report([])
        assert r.total == 0
        assert r.verdict == "stuck"

    def test_all_progress(self):
        msgs = [
            "add module A",
            "add module B",
            "new note about C",
            "create test suite",
            "implement feature D",
        ]
        r = efficacy_report(msgs)
        assert r.total == 5
        assert r.progress_count == 5
        assert r.repair_count == 0
        assert r.efficacy_ratio == 1.0
        assert r.repair_streak == 0
        assert r.verdict == "thriving"

    def test_all_repair(self):
        msgs = [
            "restart writer",
            "flush pending files",
            "catch-up commit",
            "recovery sync",
            "restart writer again",
        ]
        r = efficacy_report(msgs)
        assert r.total == 5
        assert r.repair_count == 5
        assert r.efficacy_ratio == 0.0
        assert r.repair_streak == 5
        # streak 5 ≤ 6 → maintenance (not stuck)
        assert r.verdict == "maintenance"

    def test_mixed_thriving(self):
        msgs = [
            "add module A",
            "add note B",
            "new feature C",
            "restart writer",
            "add module D",
            "create test E",
            "add feature F",
        ]
        r = efficacy_report(msgs)
        # 6 progress, 1 repair out of 7
        assert r.progress_count == 6
        assert r.repair_count == 1
        assert r.efficacy_ratio > 0.70
        assert r.repair_streak == 1
        assert r.verdict == "thriving"

    def test_mixed_verdict(self):
        msgs = [
            "add module A",
            "restart writer",
            "flush files",
            "add note B",
            "new feature C",
            "restart writer",
            "flush files",
            "catch-up",
            "add module D",
            "add module E",
        ]
        r = efficacy_report(msgs)
        # 5 progress, 5 repair out of 10
        assert r.progress_count == 5
        assert r.repair_count == 5
        assert r.efficacy_ratio == 0.5
        assert r.repair_streak == 3
        assert r.verdict == "mixed"

    def test_maintenance_verdict(self):
        msgs = [
            "restart writer",
            "flush files",
            "restart writer",
            "flush files",
            "restart writer",
            "flush files",
            "restart writer",
            "add note",
            "flush files",
            "restart writer",
        ]
        r = efficacy_report(msgs)
        # 1 progress, 9 repair
        assert r.progress_count == 1
        assert r.efficacy_ratio == 0.1
        assert r.repair_streak == 7
        # ratio 0.1 < 0.20 AND streak 7 > 6 → stuck
        assert r.verdict == "stuck"

    def test_repeat_repair_detection(self):
        msgs = [
            "restart writer",
            "restart writer after OOM",
            "restart writer again",
        ]
        r = efficacy_report(msgs)
        # All three match "restart" keyword, consecutive
        assert r.repeat_repair_count == 2

    def test_no_repeat_repairs(self):
        msgs = [
            "restart writer",
            "flush files",
            "catch-up commit",
        ]
        r = efficacy_report(msgs)
        # All different keywords
        assert r.repeat_repair_count == 0

    def test_single_commit_progress(self):
        r = efficacy_report(["add new module"])
        assert r.total == 1
        assert r.progress_count == 1
        assert r.efficacy_ratio == 1.0
        assert r.verdict == "thriving"

    def test_single_commit_repair(self):
        r = efficacy_report(["restart writer"])
        assert r.total == 1
        assert r.repair_count == 1
        assert r.efficacy_ratio == 0.0
        assert r.repair_streak == 1
        # ratio < 0.20 but streak 1 ≤ 6 → maintenance
        assert r.verdict == "maintenance"

    def test_stuck_verdict_long_repair_streak(self):
        msgs = [
            "restart writer",
            "flush files",
            "restart writer",
            "flush files",
            "restart writer",
            "flush files",
            "restart writer",
            "flush files",
        ]
        r = efficacy_report(msgs)
        # 0 progress, 8 repair → ratio 0.0, streak 8 > 6 → stuck
        assert r.progress_count == 0
        assert r.efficacy_ratio == 0.0
        assert r.repair_streak == 8
        assert r.verdict == "stuck"


# ---------------------------------------------------------------------------
# efficacy_summary
# ---------------------------------------------------------------------------

class TestEfficacySummary:
    def test_empty_report(self):
        r = efficacy_report([])
        assert efficacy_summary(r) == "no commits to evaluate"

    def test_thriving(self):
        msgs = ["add A", "add B", "add C", "add D"]
        r = efficacy_report(msgs)
        s = efficacy_summary(r)
        assert "thriving" in s
        assert "100%" in s

    def test_stuck(self):
        msgs = ["restart A", "flush B", "restart C", "flush D",
                "restart E", "flush F", "restart G", "flush H"]
        r = efficacy_report(msgs)
        s = efficacy_summary(r)
        assert "stuck" in s or "maintenance" in s

    def test_summary_format(self):
        msgs = ["add A", "restart B", "add C"]
        r = efficacy_report(msgs)
        s = efficacy_summary(r)
        assert "progress" in s
        assert "repair streak" in s
        assert "repeat repairs" in s


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_case_insensitive(self):
        c = classify_commit("RESTART WRITER")
        assert c.kind == "repair"

    def test_partial_keyword_match(self):
        c = classify_commit("restarting the writer process")
        assert c.kind == "repair"  # "restart" substring match

    def test_message_with_multiple_keywords(self):
        c = classify_commit("restart and flush pending files")
        # "restart" hits first in REPAIR_KEYWORDS
        assert c.kind == "repair"
        assert c.matched_keyword == "restart"

    def test_large_batch(self):
        msgs = ["add module" if i % 3 == 0 else "restart writer"
                for i in range(100)]
        r = efficacy_report(msgs)
        assert r.total == 100
        assert r.progress_count + r.repair_count + r.other_count == 100
