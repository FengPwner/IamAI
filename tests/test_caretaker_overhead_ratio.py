"""Tests for caretaker_overhead_ratio — maintenance vs substantive work classification."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.caretaker_overhead_ratio import (
    classify_commit,
    classify_commits,
    overhead_ratio,
    overhead_report,
    _band,
)


# ---------------------------------------------------------------------------
# classify_commit — overhead detection
# ---------------------------------------------------------------------------

class TestClassifyOverhead:
    def test_catch_up_is_overhead(self):
        assert classify_commit("catch-up: commit pending changes before process restart") == "overhead"

    def test_watchdog_auto_commit_is_overhead(self):
        assert classify_commit("watchdog: auto-commit 9 pending file(s) at check #6") == "overhead"

    def test_hourly_monitor_is_overhead(self):
        assert classify_commit("catch-up: hourly monitor auto-commit") == "overhead"

    def test_process_restart_is_overhead(self):
        assert classify_commit("catch-up: commit pending changes before process restart") == "overhead"

    def test_backlog_drain_is_overhead(self):
        assert classify_commit("backlog drain: clearing accumulated commits") == "overhead"


# ---------------------------------------------------------------------------
# classify_commit — substantive detection
# ---------------------------------------------------------------------------

class TestClassifySubstantive:
    def test_plain_feat_is_substantive(self):
        assert classify_commit("feat: add new monitoring tool") == "substantive"

    def test_fix_is_substantive(self):
        assert classify_commit("fix: correct off-by-one in stroke counter") == "substantive"

    def test_refactor_is_substantive(self):
        assert classify_commit("refactor: simplify push retry logic") == "substantive"

    def test_docs_is_substantive(self):
        assert classify_commit("docs: update README with new tool descriptions") == "substantive"

    def test_stroke_is_substantive(self):
        assert classify_commit("stroke 256 — the push race is a clock") == "substantive"

    def test_unknown_prefix_defaults_substantive(self):
        assert classify_commit("update configuration") == "substantive"


# ---------------------------------------------------------------------------
# classify_commit — hybrid detection
# ---------------------------------------------------------------------------

class TestClassifyHybrid:
    def test_feat_with_caretaker_visit_is_hybrid(self):
        msg = "feat: add push_exposure_index (28 tests); caretaker visit 392 at 15:01"
        assert classify_commit(msg) == "hybrid"

    def test_feat_with_restart_is_hybrid(self):
        msg = "feat: add tool; caretaker visit 394, restarted both processes after container recycle"
        assert classify_commit(msg) == "hybrid"

    def test_feat_with_backlog_is_hybrid(self):
        msg = "feat: add commit_churn_index; committed backlog (9 files)"
        assert classify_commit(msg) == "hybrid"

    def test_fix_with_caretaker_visit_is_hybrid(self):
        msg = "fix: watchdog PID tracking — use BASHPID; caretaker visit 390 follow-up"
        # "caretaker visit" matches hybrid pattern, "fix:" matches substantive
        assert classify_commit(msg) == "hybrid"


# ---------------------------------------------------------------------------
# classify_commit — edge cases
# ---------------------------------------------------------------------------

class TestClassifyEdgeCases:
    def test_empty_string_is_substantive(self):
        assert classify_commit("") == "substantive"

    def test_whitespace_only_is_substantive(self):
        assert classify_commit("   ") == "substantive"

    def test_case_insensitive_overhead(self):
        assert classify_commit("CATCH-UP: something") == "overhead"

    def test_case_insensitive_substantive(self):
        assert classify_commit("FEAT: something new") == "substantive"


# ---------------------------------------------------------------------------
# classify_commits
# ---------------------------------------------------------------------------

class TestClassifyCommits:
    def test_returns_tuples(self):
        messages = ["feat: new thing", "catch-up: backlog"]
        result = classify_commits(messages)
        assert len(result) == 2
        assert result[0] == ("feat: new thing", "substantive")
        assert result[1] == ("catch-up: backlog", "overhead")

    def test_empty_list(self):
        assert classify_commits([]) == []

    def test_mixed_batch(self):
        messages = [
            "feat: add tool (28 tests); caretaker visit 392",
            "catch-up: commit pending changes before process restart",
            "watchdog: auto-commit 9 pending file(s) at check #6",
            "fix: correct typo in README",
            "stroke 100 — a repo that only accumulates",
        ]
        result = classify_commits(messages)
        cats = [c for _, c in result]
        assert cats == ["hybrid", "overhead", "overhead", "substantive", "substantive"]


# ---------------------------------------------------------------------------
# overhead_ratio
# ---------------------------------------------------------------------------

class TestOverheadRatio:
    def test_empty_returns_zero(self):
        assert overhead_ratio([]) == 0.0

    def test_all_substantive_returns_zero(self):
        assert overhead_ratio(["substantive", "substantive", "substantive"]) == 0.0

    def test_all_overhead_returns_one(self):
        assert overhead_ratio(["overhead", "overhead", "overhead"]) == pytest.approx(1.0)

    def test_half_overhead_half_substantive(self):
        ratio = overhead_ratio(["overhead", "substantive"])
        assert ratio == pytest.approx(0.5)

    def test_hybrid_counts_half(self):
        # 1 overhead + 0.5*1 hybrid = 1.5 / 3 = 0.5
        ratio = overhead_ratio(["overhead", "hybrid", "substantive"])
        assert ratio == pytest.approx(0.5)

    def test_all_hybrid_returns_half(self):
        ratio = overhead_ratio(["hybrid", "hybrid", "hybrid"])
        assert ratio == pytest.approx(0.5)

    def test_mixed_realistic(self):
        # 3 overhead, 2 hybrid, 5 substantive = (3 + 1) / 10 = 0.4
        cats = ["overhead"] * 3 + ["hybrid"] * 2 + ["substantive"] * 5
        assert overhead_ratio(cats) == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# _band
# ---------------------------------------------------------------------------

class TestBand:
    def test_zero_is_lean(self):
        assert _band(0.0) == "lean"

    def test_nineteen_is_lean(self):
        assert _band(0.19) == "lean"

    def test_twenty_is_moderate(self):
        assert _band(0.20) == "moderate"

    def test_thirty_nine_is_moderate(self):
        assert _band(0.39) == "moderate"

    def test_forty_is_heavy(self):
        assert _band(0.40) == "heavy"

    def test_fifty_nine_is_heavy(self):
        assert _band(0.59) == "heavy"

    def test_sixty_is_critical(self):
        assert _band(0.60) == "critical"

    def test_one_is_critical(self):
        assert _band(1.0) == "critical"


# ---------------------------------------------------------------------------
# overhead_report
# ---------------------------------------------------------------------------

class TestOverheadReport:
    def test_empty_input(self):
        report = overhead_report([])
        assert report["total"] == 0
        assert report["ratio"] == 0.0
        assert report["band"] == "lean"
        assert report["summary"] == "no commits to analyse"

    def test_realistic_batch(self):
        messages = [
            "feat: add push_exposure_index (28 tests); caretaker visit 392",
            "catch-up: commit pending changes before process restart",
            "watchdog: auto-commit 9 pending file(s) at check #6",
            "fix: correct typo in README",
            "stroke 100 — a repo that only accumulates",
        ]
        report = overhead_report(messages)
        assert report["total"] == 5
        assert report["substantive"] == 2
        assert report["overhead"] == 2
        assert report["hybrid"] == 1
        # (2 + 0.5*1) / 5 = 0.5
        assert report["ratio"] == pytest.approx(0.5)
        assert report["band"] == "heavy"
        assert "2.5 of 5" in report["summary"]

    def test_all_substantive(self):
        messages = ["feat: a", "fix: b", "docs: c"]
        report = overhead_report(messages)
        assert report["ratio"] == 0.0
        assert report["band"] == "lean"

    def test_all_overhead(self):
        messages = [
            "catch-up: x",
            "watchdog: auto-commit 3 file(s) at check #1",
            "catch-up: hourly monitor auto-commit",
        ]
        report = overhead_report(messages)
        assert report["ratio"] == pytest.approx(1.0)
        assert report["band"] == "critical"

    def test_breakdown_present(self):
        messages = ["feat: x", "catch-up: y"]
        report = overhead_report(messages)
        assert "breakdown" in report
        assert len(report["breakdown"]) == 2
        assert report["breakdown"][0] == ("feat: x", "substantive")
        assert report["breakdown"][1] == ("catch-up: y", "overhead")

    def test_repo_actual_history(self):
        """Test against actual repo commit messages — sanity check."""
        # These are real messages from the repo's recent history
        messages = [
            "catch-up: commit pending changes before process restart",
            "feat: add last_sync_age — measure time since last successful push (34 tests); caretaker visit 396 at 19:01",
            "catch-up: commit pending changes before process restart",
            "feat: add caretaker_visit_escalation — detect when caretaker repeats the same fix too many times (20 tests); caretaker visit 395 at 18:01",
            "catch-up: commit pending changes before process restart",
            "feat: add commit_churn_index — detect writer rewrite loops (23 tests); caretaker visit 394 at 17:01, restarted both processes",
            "catch-up: hourly monitor auto-commit",
            "catch-up: commit pending changes before process restart",
            "feat: add push_readiness_probe — pre-flight check before git push (24 tests); caretaker visit 393 at 16:01, restarted both processes",
            "catch-up: commit pending changes before process restart",
        ]
        report = overhead_report(messages)
        assert report["total"] == 10
        # 6 overhead: indices 0,2,4,6,7,9 (all "catch-up:" prefixed)
        assert report["overhead"] == 6
        # 4 hybrid: indices 1,3,5,8 (feat: + caretaker visit/restarted)
        assert report["hybrid"] == 4
        assert report["substantive"] == 0
        # (6 + 0.5*4) / 10 = 0.8
        assert report["ratio"] == pytest.approx(0.8)
        assert report["band"] == "critical"
