"""Tests for iamai.commit_audit — commit history health scoring.

Covers:
  - _clamp01 boundary values
  - _has_known_prefix for all recognised prefixes and unknown ones
  - _parse_log_line with valid, malformed, and empty input
  - AuditReport.score weighted composite
  - AuditReport.healthy threshold
  - AuditReport.summary format
  - audit() format check with mock git log
  - audit() order check (out-of-order dates)
  - audit() duplicate detection
  - audit() burst detection with check_files=True
  - audit() with empty log → empty report
  - Integration: audit() against the real repo
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from iamai.commit_audit import (
    BURST_SCORE_PENALTY,
    DEFAULT_LOOKBACK,
    DUPLICATE_PENALTY,
    FORMAT_PENALTY,
    KNOWN_PREFIXES,
    MAX_FILES_NORMAL,
    OOO_PENALTY,
    AuditReport,
    _clamp01,
    _count_files_in_commit,
    _get_log,
    _has_known_prefix,
    _parse_log_line,
    audit,
)


# ── _clamp01 ──────────────────────────────────────────────────────────

class TestClamp01:
    def test_below_zero(self):
        assert _clamp01(-0.5) == 0.0

    def test_above_one(self):
        assert _clamp01(1.5) == 1.0

    def test_zero(self):
        assert _clamp01(0.0) == 0.0

    def test_one(self):
        assert _clamp01(1.0) == 1.0

    def test_middle(self):
        assert _clamp01(0.5) == 0.5

    def test_negative_large(self):
        assert _clamp01(-100) == 0.0

    def test_positive_large(self):
        assert _clamp01(100) == 1.0


# ── _has_known_prefix ────────────────────────────────────────────────

class TestHasKnownPrefix:
    def test_caretaker(self):
        assert _has_known_prefix("caretaker: flush 3 pending files")

    def test_caretaker_numbered(self):
        assert _has_known_prefix("caretaker-98: add module")

    def test_catch_up(self):
        assert _has_known_prefix("catch-up: hourly caretaker restart")

    def test_guoban(self):
        assert _has_known_prefix("guoban: note (stroke 120)")

    def test_backlog_flush(self):
        assert _has_known_prefix("backlog flush: clear stale lock")

    def test_backlog(self):
        assert _has_known_prefix("backlog: something")

    def test_flush(self):
        assert _has_known_prefix("flush: pending files")

    def test_manual(self):
        assert _has_known_prefix("manual: intervention")

    def test_initial(self):
        assert _has_known_prefix("initial commit")

    def test_merge(self):
        assert _has_known_prefix("merge branch 'main'")

    def test_revert(self):
        assert _has_known_prefix("revert: bad commit")

    def test_chore(self):
        assert _has_known_prefix("chore: update deps")

    def test_feat(self):
        assert _has_known_prefix("feat: new module")

    def test_fix(self):
        assert _has_known_prefix("fix: broken test")

    def test_docs(self):
        assert _has_known_prefix("docs: update readme")

    def test_test(self):
        assert _has_known_prefix("test: add coverage")

    def test_refactor(self):
        assert _has_known_prefix("refactor: simplify logic")

    def test_case_insensitive(self):
        assert _has_known_prefix("Caretaker: uppercase")
        assert _has_known_prefix("CATCH-UP: shouting")

    def test_unknown_prefix(self):
        assert not _has_known_prefix("random message without prefix")

    def test_empty_string(self):
        assert not _has_known_prefix("")

    def test_single_word(self):
        assert not _has_known_prefix("yolo")


# ── _parse_log_line ──────────────────────────────────────────────────

class TestParseLogLine:
    def test_valid(self):
        line = "abc123|caretaker: flush|2026-10-09T08:00:00+08:00"
        sha, msg, date = _parse_log_line(line)
        assert sha == "abc123"
        assert msg == "caretaker: flush"
        assert date == "2026-10-09T08:00:00+08:00"

    def test_pipe_in_message(self):
        line = "abc|msg with | pipe|2026-10-09"
        sha, msg, date = _parse_log_line(line)
        assert sha == "abc"
        assert msg == "msg with | pipe"
        assert date == "2026-10-09"

    def test_too_few_parts(self):
        sha, msg, date = _parse_log_line("abc|only-two")
        assert sha == ""
        assert msg == ""
        assert date == ""

    def test_empty_string(self):
        sha, msg, date = _parse_log_line("")
        assert sha == ""

    def test_whitespace_stripped(self):
        line = "  abc123  |  some msg  |  2026-10-09  "
        sha, msg, date = _parse_log_line(line)
        assert sha == "abc123"
        assert msg == "some msg"
        assert date == "2026-10-09"


# ── AuditReport ──────────────────────────────────────────────────────

class TestAuditReport:
    def test_perfect_score(self):
        r = AuditReport()
        assert r.score == 1.0
        assert r.healthy

    def test_score_degrades_with_format_violations(self):
        r = AuditReport(
            format_score=_clamp01(1.0 - 3 * FORMAT_PENALTY),
            format_violations=["a", "b", "c"],
        )
        assert r.score < 1.0
        assert len(r.format_violations) == 3

    def test_score_degrades_with_ooo(self):
        r = AuditReport(
            order_score=_clamp01(1.0 - 2 * OOO_PENALTY),
            ooo_pairs=[("a", "b"), ("c", "d")],
        )
        assert r.score < 1.0

    def test_healthy_threshold(self):
        r = AuditReport(format_score=0.6, burst_score=0.8, order_score=0.8, dedup_score=0.8)
        assert r.score == pytest.approx(0.75)
        assert r.healthy

    def test_unhealthy(self):
        r = AuditReport(format_score=0.3, burst_score=0.5, order_score=0.5, dedup_score=0.5)
        assert r.score == pytest.approx(0.45)
        assert not r.healthy

    def test_summary_clean(self):
        r = AuditReport(total_commits=50)
        assert "score=1.00" in r.summary

    def test_summary_with_issues(self):
        r = AuditReport(
            format_score=0.9,
            format_violations=["x"],
            duplicate_groups=["dup1"],
            total_commits=50,
        )
        assert "format×1" in r.summary
        assert "dup×1" in r.summary

    def test_str_healthy(self):
        r = AuditReport(total_commits=10)
        s = str(r)
        assert "healthy" in s
        assert "n=10" in s

    def test_str_unhealthy(self):
        r = AuditReport(
            format_score=0.3,
            burst_score=0.5,
            order_score=0.5,
            dedup_score=0.5,
            total_commits=10,
        )
        s = str(r)
        assert "needs attention" in s

    def test_score_clamped_low(self):
        r = AuditReport(format_score=0.0, burst_score=0.0, order_score=0.0, dedup_score=0.0)
        assert r.score == 0.0

    def test_total_commits_default(self):
        r = AuditReport()
        assert r.total_commits == 0


# ── audit() with mocked git ──────────────────────────────────────────

class TestAuditMocked:
    def _mock_log(self, entries: list[str]):
        """Return a patched _get_log that returns *entries*."""
        return patch(
            "iamai.commit_audit._get_log",
            return_value=entries,
        )

    def test_empty_log(self):
        with self._mock_log([]):
            r = audit()
            assert r.total_commits == 0
            assert r.score == 1.0

    def test_all_clean(self):
        lines = [
            "aaa|caretaker: flush files|2026-10-09T10:00:00+08:00",
            "bbb|catch-up: restart|2026-10-09T09:00:00+08:00",
            "ccc|guoban: note|2026-10-09T08:00:00+08:00",
        ]
        with self._mock_log(lines):
            r = audit()
            assert r.total_commits == 3
            assert r.format_score == 1.0
            assert r.order_score == 1.0
            assert r.dedup_score == 1.0
            assert r.healthy

    def test_format_violations(self):
        lines = [
            "aaa|random message|2026-10-09T10:00:00+08:00",
            "bbb|another bad one|2026-10-09T09:00:00+08:00",
            "ccc|caretaker: good|2026-10-09T08:00:00+08:00",
        ]
        with self._mock_log(lines):
            r = audit()
            assert len(r.format_violations) == 2
            assert r.format_score == pytest.approx(1.0 - 2 * FORMAT_PENALTY)

    def test_out_of_order(self):
        # Git log is newest-first; dates should decrease.
        # If date[i] < date[i+1], that's out of order.
        lines = [
            "aaa|caretaker: a|2026-10-09T08:00:00+08:00",
            "bbb|caretaker: b|2026-10-09T10:00:00+08:00",  # newer than aaa → ooo
            "ccc|caretaker: c|2026-10-09T07:00:00+08:00",
        ]
        with self._mock_log(lines):
            r = audit()
            assert len(r.ooo_pairs) == 1
            assert r.order_score == pytest.approx(1.0 - OOO_PENALTY)

    def test_duplicate_messages(self):
        lines = [
            "aaa|catch-up: hourly caretaker restart|2026-10-09T10:00:00+08:00",
            "bbb|catch-up: hourly caretaker restart|2026-10-09T09:00:00+08:00",
            "ccc|caretaker: unique|2026-10-09T08:00:00+08:00",
        ]
        with self._mock_log(lines):
            r = audit()
            assert len(r.duplicate_groups) == 1
            assert r.dedup_score == pytest.approx(1.0 - DUPLICATE_PENALTY)

    def test_multiple_duplicates(self):
        lines = [
            "aaa|catch-up: restart|2026-10-09T10:00:00+08:00",
            "bbb|catch-up: restart|2026-10-09T09:00:00+08:00",
            "ccc|caretaker: flush|2026-10-09T08:00:00+08:00",
            "ddd|caretaker: flush|2026-10-09T07:00:00+08:00",
        ]
        with self._mock_log(lines):
            r = audit()
            assert len(r.duplicate_groups) == 2
            assert r.dedup_score == pytest.approx(1.0 - 2 * DUPLICATE_PENALTY)

    def test_burst_detection(self):
        lines = [
            "aaa|caretaker: flush 50 files|2026-10-09T10:00:00+08:00",
            "bbb|caretaker: normal|2026-10-09T09:00:00+08:00",
        ]
        with self._mock_log(lines), patch(
            "iamai.commit_audit._count_files_in_commit",
            side_effect=[50, 3],
        ):
            r = audit(check_files=True)
            assert len(r.burst_commits) == 1
            assert r.burst_commits[0][1] == 50
            assert r.burst_score == pytest.approx(1.0 - BURST_SCORE_PENALTY)

    def test_burst_not_checked_by_default(self):
        lines = [
            "aaa|caretaker: big flush|2026-10-09T10:00:00+08:00",
        ]
        with self._mock_log(lines), patch(
            "iamai.commit_audit._count_files_in_commit",
        ) as mock_count:
            r = audit(check_files=False)
            mock_count.assert_not_called()
            assert r.burst_score == 1.0

    def test_all_prefixes_recognised(self):
        lines = [
            f"sha{i}|{p}: something|2026-10-09T{10-i:02d}:00:00+08:00"
            for i, p in enumerate(KNOWN_PREFIXES[:10])
        ]
        with self._mock_log(lines):
            r = audit()
            assert r.format_score == 1.0

    def test_score_floor_at_zero(self):
        # 20 format violations would push score negative without clamping
        lines = [
            f"sha{i}|bad message {i}|2026-10-09T{10-i:02d}:00:00+08:00"
            for i in range(20)
        ]
        with self._mock_log(lines):
            r = audit()
            assert r.format_score == 0.0
            assert r.score >= 0.0

    def test_lookback_passed_through(self):
        with patch("iamai.commit_audit._get_log", return_value=[]) as mock_get:
            audit(lookback=10)
            mock_get.assert_called_once()
            assert mock_get.call_args[1].get("n") == 10 or mock_get.call_args[0][1] == 10


# ── Integration: real repo ───────────────────────────────────────────

class TestAuditIntegration:
    def test_real_repo_has_commits(self):
        r = audit(lookback=20)
        assert r.total_commits > 0
        assert r.total_commits <= 20

    def test_real_repo_healthy_enough(self):
        r = audit(lookback=50)
        # This repo has lots of "catch-up: hourly caretaker restart" dupes,
        # so dedup_score may be degraded.  Overall should still be > 0.3.
        assert r.score > 0.3

    def test_real_repo_summary_not_empty(self):
        r = audit(lookback=10)
        assert len(r.summary) > 0
