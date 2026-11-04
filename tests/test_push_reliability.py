"""Tests for iamai.push_reliability — push pipeline reliability scoring."""

import pytest
from unittest.mock import patch, MagicMock
import subprocess

from iamai.push_reliability import (
    ReflogEvent,
    parse_reflog,
    reliability_score,
    reliability_trend,
    reliability_report,
    _classify,
    _count_by_label,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _evt(label: str, ref: str = "HEAD@{0}") -> ReflogEvent:
    return ReflogEvent(ref=ref, action="", label=label)


def _events(*labels: str) -> list:
    return [_evt(l) for l in labels]


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestClassify:
    def test_rebase_abort(self):
        assert _classify("rebase (abort): returning to refs/heads/main") == "rebase_abort"

    def test_pull_rebase(self):
        assert _classify("pull --rebase origin main (start): checkout abc123") == "pull_rebase"

    def test_pull_rebase_finish(self):
        assert _classify("pull --rebase origin main (finish): returning to refs/heads/main") == "pull_rebase"

    def test_merge_from_remote(self):
        assert _classify("pull origin main: Merge made by the 'ort' strategy.") == "merge"

    def test_reset(self):
        assert _classify("reset: moving to HEAD") == "reset"

    def test_visit_commit(self):
        assert _classify("commit: visit-542: add visit_interval_monitor") == "push_ok"

    def test_catchup_commit(self):
        assert _classify("commit: catch-up: commit pending changes before process restart") == "push_ok"

    def test_unrelated_returns_none(self):
        assert _classify("checkout: moving from main to feature-x") is None

    def test_empty_string(self):
        assert _classify("") is None

    def test_partial_match_not_classified(self):
        assert _classify("commit: add new feature") is None


# ---------------------------------------------------------------------------
# Reliability Score
# ---------------------------------------------------------------------------

class TestReliabilityScore:
    def test_empty_events(self):
        assert reliability_score([]) == 1.0

    def test_all_success(self):
        events = _events("push_ok", "push_ok", "push_ok", "push_ok")
        assert reliability_score(events) == 1.0

    def test_all_failures(self):
        events = _events("rebase_abort", "reset", "rebase_abort")
        assert reliability_score(events) == 0.0

    def test_mixed(self):
        # 7 ok, 3 failures → 0.7
        events = _events(
            "push_ok", "push_ok", "rebase_abort",
            "push_ok", "push_ok", "reset",
            "push_ok", "push_ok", "push_ok",
            "reset",
        )
        assert reliability_score(events) == pytest.approx(0.7)

    def test_only_pull_rebase_no_failures(self):
        # pull_rebase and merge are not failure signals
        events = _events("push_ok", "pull_rebase", "push_ok", "merge")
        assert reliability_score(events) == 1.0

    def test_single_event_ok(self):
        assert reliability_score(_events("push_ok")) == 1.0

    def test_single_event_fail(self):
        assert reliability_score(_events("rebase_abort")) == 0.0

    def test_score_ignores_neutral_events(self):
        # merge and pull_rebase don't affect the denominator
        events = _events("push_ok", "merge", "merge", "push_ok")
        assert reliability_score(events) == 1.0

    def test_realistic_history(self):
        # simulating a typical IamAI reflog pattern:
        # lots of successful catch-up and visit commits, occasional
        # rebase aborts when the remote diverges
        labels = (
            ["push_ok"] * 15
            + ["rebase_abort"] * 2
            + ["push_ok"] * 10
            + ["reset"] * 1
            + ["push_ok"] * 5
        )
        events = _events(*labels)
        # 30 ok, 3 failures → 30/33 ≈ 0.909
        assert reliability_score(events) == pytest.approx(30 / 33, abs=0.01)


# ---------------------------------------------------------------------------
# Reliability Trend
# ---------------------------------------------------------------------------

class TestReliabilityTrend:
    def test_too_few_events(self):
        assert reliability_trend(_events("push_ok", "push_ok")) == 0.0

    def test_stable(self):
        # both halves have same ratio
        events = _events(
            "push_ok", "push_ok", "rebase_abort", "push_ok",
            "push_ok", "push_ok", "rebase_abort", "push_ok",
        )
        assert reliability_trend(events) == pytest.approx(0.0, abs=0.01)

    def test_improving(self):
        # older half has failures, recent half is clean
        events = _events(
            "rebase_abort", "rebase_abort", "push_ok", "push_ok",
            "push_ok", "push_ok", "push_ok", "push_ok",
        )
        trend = reliability_trend(events)
        assert trend > 0.0

    def test_degrading(self):
        # older half is clean, recent half has failures
        events = _events(
            "push_ok", "push_ok", "push_ok", "push_ok",
            "rebase_abort", "rebase_abort", "push_ok", "push_ok",
        )
        trend = reliability_trend(events)
        assert trend < 0.0

    def test_four_events_minimum(self):
        events = _events("push_ok", "push_ok", "push_ok", "rebase_abort")
        trend = reliability_trend(events)
        assert isinstance(trend, float)


# ---------------------------------------------------------------------------
# Count by Label
# ---------------------------------------------------------------------------

class TestCountByLabel:
    def test_empty(self):
        assert _count_by_label([]) == {}

    def test_counts(self):
        events = _events("push_ok", "push_ok", "rebase_abort", "merge")
        counts = _count_by_label(events)
        assert counts["push_ok"] == 2
        assert counts["rebase_abort"] == 1
        assert counts["merge"] == 1


# ---------------------------------------------------------------------------
# Reliability Report
# ---------------------------------------------------------------------------

class TestReliabilityReport:
    def test_report_keys(self):
        events = _events("push_ok", "push_ok", "rebase_abort")
        report = reliability_report(events)
        assert "score" in report
        assert "trend" in report
        assert "total_events" in report
        assert "counts" in report
        assert "summary" in report
        assert "grade" in report

    def test_grade_a(self):
        events = _events(*(["push_ok"] * 10))
        report = reliability_report(events)
        assert report["grade"] == "A"

    def test_grade_f(self):
        events = _events(*(["rebase_abort"] * 10))
        report = reliability_report(events)
        assert report["grade"] == "F"

    def test_grade_c_boundary(self):
        # 7 ok, 3 failures → 0.7 → C
        events = _events(
            *(["push_ok"] * 7 + ["rebase_abort"] * 3)
        )
        report = reliability_report(events)
        assert report["grade"] == "C"

    def test_summary_is_string(self):
        events = _events("push_ok", "rebase_abort")
        report = reliability_report(events)
        assert isinstance(report["summary"], str)
        assert len(report["summary"]) > 10

    def test_empty_events_report(self):
        report = reliability_report([])
        assert report["score"] == 1.0
        assert report["grade"] == "A"
        assert report["total_events"] == 0


# ---------------------------------------------------------------------------
# Reflog Parsing (mocked subprocess)
# ---------------------------------------------------------------------------

class TestParseReflog:
    MOCK_REFLOG = """\
HEAD@{0} commit: catch-up: commit pending changes before process restart
HEAD@{1} commit: visit-542: add visit_interval_monitor + test suite (27 tests) + caretaker visit note
HEAD@{2} commit: catch-up: commit pending changes before process restart
HEAD@{3} rebase (abort): returning to refs/heads/main
HEAD@{4} pull --rebase origin main (start): checkout abc1234
HEAD@{5} commit: visit-541: push_smart_resolve (rebase-first-merge-fallback)
HEAD@{6} pull origin main: Merge made by the 'ort' strategy.
HEAD@{7} reset: moving to HEAD
HEAD@{8} commit: visit-540: pre_push_gate (module + 36 tests)
HEAD@{9} checkout: moving from main to feature\
"""

    def test_parse_mock_reflog(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = self.MOCK_REFLOG

        with patch("iamai.push_reliability.subprocess.run", return_value=mock_result):
            events = parse_reflog("/fake/repo")

        # should parse: 3 catch-up, 2 visit, 1 rebase_abort, 1 pull_rebase,
        # 1 merge, 1 reset = 9 events (checkout is filtered out)
        assert len(events) == 9

        # chronological order (oldest first = reversed from reflog)
        assert events[0].label == "push_ok"  # visit-540 (oldest)
        assert events[-1].label == "push_ok"  # catch-up (newest)

    def test_parse_failure_returns_empty(self):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""

        with patch("iamai.push_reliability.subprocess.run", return_value=mock_result):
            events = parse_reflog("/fake/repo")

        assert events == []

    def test_parse_timeout_returns_empty(self):
        with patch(
            "iamai.push_reliability.subprocess.run",
            side_effect=subprocess.TimeoutExpired("git", 10),
        ):
            events = parse_reflog("/fake/repo")

        assert events == []

    def test_parse_not_found_returns_empty(self):
        with patch(
            "iamai.push_reliability.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            events = parse_reflog("/fake/repo")

        assert events == []

    def test_reflog_event_repr(self):
        evt = ReflogEvent(ref="HEAD@{0}", action="test", label="push_ok", commit="abc1234")
        r = repr(evt)
        assert "push_ok" in r
        assert "HEAD@{0}" in r


# ---------------------------------------------------------------------------
# CLI (main)
# ---------------------------------------------------------------------------

class TestMain:
    def test_main_json_output(self, capsys):
        import json as json_mod

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "HEAD@{0} commit: visit-542: test\nHEAD@{1} commit: catch-up: test\n"

        with patch("iamai.push_reliability.subprocess.run", return_value=mock_result):
            with patch("sys.argv", ["push_reliability", "--json", "--repo", "/fake"]):
                ret = main()

        assert ret == 0  # grade A → exit 0
        captured = capsys.readouterr()
        data = json_mod.loads(captured.out)
        assert "score" in data

    def test_main_text_output(self, capsys):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "HEAD@{0} commit: visit-542: test\n"

        with patch("iamai.push_reliability.subprocess.run", return_value=mock_result):
            with patch("sys.argv", ["push_reliability", "--repo", "/fake"]):
                ret = main()

        assert ret == 0
        captured = capsys.readouterr()
        assert "push reliability" in captured.out

    def test_main_bad_grade_exits_nonzero(self, capsys):
        # all failures → grade F → exit 2
        lines = "\n".join(
            f"HEAD@{{{i}}} rebase (abort): returning to refs/heads/main"
            for i in range(10)
        )
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = lines

        with patch("iamai.push_reliability.subprocess.run", return_value=mock_result):
            with patch("sys.argv", ["push_reliability", "--repo", "/fake"]):
                ret = main()

        assert ret == 2


# ---------------------------------------------------------------------------
# Integration: real repo (if available)
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_real_repo(self):
        """Run against the actual IamAI repo if it exists."""
        import os
        repo = os.environ.get("IAMAI_REPO", ".")
        from pathlib import Path
        if not (Path(repo) / ".git").exists():
            pytest.skip("no git repo available")

        events = parse_reflog(repo, max_entries=50)
        # should get at least some events from the real reflog
        assert len(events) > 0

        report = reliability_report(events)
        assert 0.0 <= report["score"] <= 1.0
        assert report["grade"] in ("A", "B", "C", "D", "F")
