"""Tests for iamai.commit_intent."""

from __future__ import annotations

import pytest
from iamai.commit_intent import (
    classify_commit,
    classify_commits,
    focus_verdict,
    focus_summary,
    BALANCED_THRESHOLD,
    NARROW_THRESHOLD,
)


# ---------------------------------------------------------------------------
# classify_commit — single message
# ---------------------------------------------------------------------------


class TestClassifyCommit:
    # --- fix ---
    def test_fix_simple(self):
        assert classify_commit("fix off-by-one in gap classifier") == "fix"

    def test_fix_past_tense(self):
        assert classify_commit("fixed race condition in push") == "fix"

    def test_fix_hotfix(self):
        assert classify_commit("hotfix: writer crash on empty strokes") == "fix"

    def test_fix_correct(self):
        assert classify_commit("correct typo in readme") == "fix"

    # --- refactor ---
    def test_refactor_basic(self):
        assert classify_commit("refactor caretaker yield into own module") == "refactor"

    def test_refactor_restructure(self):
        assert classify_commit("restructure test directory layout") == "refactor"

    def test_refactor_rename(self):
        assert classify_commit("rename stall_event to stall_classifier") == "refactor"

    def test_refactor_cleanup(self):
        assert classify_commit("clean up unused imports") == "refactor"

    # --- tooling ---
    def test_tooling_script(self):
        assert classify_commit("add commit_batch script") == "tooling"

    def test_tooling_ci(self):
        assert classify_commit("update ci workflow for nightly runs") == "tooling"

    def test_tooling_monitor(self):
        assert classify_commit("add caretaker monitor daemon") == "tooling"

    def test_tooling_pytest(self):
        assert classify_commit("add pytest config and fixtures") == "tooling"

    # --- content ---
    def test_content_note(self):
        assert classify_commit("new note on afternoon reclamation") == "content"

    def test_content_garden(self):
        assert classify_commit("add garden entry about entropy rhythm") == "content"

    def test_content_stroke(self):
        assert classify_commit("stroke 400: cadence is early warning") == "content"

    def test_content_devlog(self):
        assert classify_commit("update devlog with overnight push race") == "content"

    def test_content_prose(self):
        assert classify_commit("writing: essay on commit message quality") == "content"

    # --- meta ---
    def test_meta_catchup(self):
        assert classify_commit("catch-up: commit pending changes") == "meta"

    def test_meta_catchup_no_hyphen(self):
        assert classify_commit("catch up: commit before restart") == "meta"

    def test_meta_merge(self):
        assert classify_commit("merge branch 'main' of origin") == "meta"

    def test_meta_wip(self):
        assert classify_commit("wip: saving progress") == "meta"

    def test_meta_fallback(self):
        assert classify_commit("update stuff") == "meta"

    def test_meta_empty(self):
        assert classify_commit("") == "meta"


# ---------------------------------------------------------------------------
# classify_commits — batch
# ---------------------------------------------------------------------------


class TestClassifyCommits:
    def test_basic_report_structure(self):
        messages = [
            "add stall cluster detector",
            "fix off-by-one in gap classifier",
            "refactor caretaker yield into own module",
            "catch-up: commit pending changes",
            "new note on afternoon reclamation",
        ]
        report = classify_commits(messages)

        assert report["total"] == 5
        # "add stall cluster detector" has no content keyword → meta
        assert report["content"] == 1
        assert report["fix"] == 1
        assert report["refactor"] == 1
        assert report["meta"] == 2  # detector + catch-up

    def test_empty_input(self):
        report = classify_commits([])
        assert report["total"] == 0
        assert report["focus_score"] == 0.0
        assert report["dominant"] == "meta"

    def test_single_commit(self):
        report = classify_commits(["fix the thing"])
        assert report["total"] == 1
        assert report["fix"] == 1
        assert report["focus_score"] == 1.0

    def test_all_same_category(self):
        report = classify_commits([
            "fix bug a",
            "fix bug b",
            "fix bug c",
            "fix bug d",
        ])
        assert report["total"] == 4
        assert report["fix"] == 4
        assert report["focus_score"] == 1.0
        assert report["dominant"] == "fix"

    def test_breakdown_preserved(self):
        messages = ["fix x", "note about y"]
        report = classify_commits(messages)
        breakdown = report["breakdown"]
        assert len(breakdown) == 2
        assert breakdown[0] == ("fix x", "fix")
        assert breakdown[1][1] == "content"

    def test_dominant_is_max_category(self):
        report = classify_commits([
            "add note one",
            "add note two",
            "add note three",
            "fix something",
        ])
        assert report["dominant"] == "content"

    def test_focus_score_calculation(self):
        # 3 out of 4 in one category → 0.75
        report = classify_commits([
            "fix a",
            "fix b",
            "fix c",
            "note about something",
        ])
        assert report["focus_score"] == 0.75


# ---------------------------------------------------------------------------
# focus_verdict
# ---------------------------------------------------------------------------


class TestFocusVerdict:
    def test_balanced(self):
        report = {"focus_score": 0.3, "total": 10}
        assert focus_verdict(report) == "balanced"

    def test_balanced_at_boundary(self):
        report = {"focus_score": BALANCED_THRESHOLD - 0.01, "total": 10}
        assert focus_verdict(report) == "balanced"

    def test_narrow(self):
        report = {"focus_score": 0.6, "total": 10}
        assert focus_verdict(report) == "narrow"

    def test_narrow_at_boundary(self):
        report = {"focus_score": NARROW_THRESHOLD - 0.01, "total": 10}
        assert focus_verdict(report) == "narrow"

    def test_fixation(self):
        report = {"focus_score": 0.8, "total": 10}
        assert focus_verdict(report) == "fixation"

    def test_fixation_at_max(self):
        report = {"focus_score": 1.0, "total": 10}
        assert focus_verdict(report) == "fixation"

    def test_zero_score(self):
        report = {"focus_score": 0.0, "total": 0}
        assert focus_verdict(report) == "balanced"


# ---------------------------------------------------------------------------
# focus_summary
# ---------------------------------------------------------------------------


class TestFocusSummary:
    def test_balanced_summary(self):
        report = {
            "focus_score": 0.35,
            "dominant": "content",
            "total": 20,
        }
        result = focus_summary(report)
        assert "balanced" in result
        assert "content" in result
        assert "20" in result

    def test_fixation_summary(self):
        report = {
            "focus_score": 0.9,
            "dominant": "meta",
            "total": 10,
        }
        result = focus_summary(report)
        assert "fixation" in result
        assert "meta" in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_case_insensitive(self):
        assert classify_commit("FIX: broken thing") == "fix"
        assert classify_commit("Refactor the module") == "refactor"
        assert classify_commit("TOOLING: add script") == "tooling"

    def test_hyphenated_catchup(self):
        assert classify_commit("catch-up: pending before restart") == "meta"

    def test_multiline_only_first_matters(self):
        # Real commit messages may have body; we only look at subject
        assert classify_commit("fix: thing\n\nDetailed explanation") == "fix"

    def test_no_false_positive_fix_in_word(self):
        # "prefix" contains "fix" but should not match as fix
        # The \b word boundary should prevent this
        result = classify_commit("add prefix handler for routes")
        assert result != "fix"

    def test_report_has_all_keys(self):
        report = classify_commits(["something"])
        for key in ("content", "tooling", "fix", "refactor", "meta",
                     "total", "dominant", "focus_score", "breakdown"):
            assert key in report
