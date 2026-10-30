#!/usr/bin/env python3
"""Tests for repo_triage.py — 24 test cases.

Covers:
  - TriageSignal / TriageReport dataclasses
  - check_processes: both alive, one dead, both dead
  - check_uncommitted: clean, few files, many files
  - check_commit_cadence: normal gaps, large gaps, insufficient data
  - check_push_freshness: up to date, unpushed, behind origin
  - check_stroke_rate: active, slow, silent
  - triage: overall verdict logic (ok / warn / red)
  - format_text / format_json: output structure
"""

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from repo_triage import (
    TriageSignal,
    TriageReport,
    check_processes,
    check_uncommitted,
    check_commit_cadence,
    check_push_freshness,
    check_stroke_rate,
    triage,
    format_text,
    format_json,
    MAX_UNCOMMITTED,
    MAX_COMMIT_GAP_MINUTES,
    MIN_STROKES_PER_HOUR,
    PUSH_LAG_THRESHOLD,
    CST,
)


class TestTriageSignal(unittest.TestCase):
    """Tests for the TriageSignal dataclass."""

    def test_basic_construction(self):
        s = TriageSignal("test", "ok", "all good", 42)
        self.assertEqual(s.name, "test")
        self.assertEqual(s.status, "ok")
        self.assertEqual(s.detail, "all good")
        self.assertEqual(s.value, 42)

    def test_default_value_is_none(self):
        s = TriageSignal("test", "ok", "msg")
        self.assertIsNone(s.value)


class TestTriageReport(unittest.TestCase):
    """Tests for the TriageReport dataclass."""

    def test_empty_report_is_ok(self):
        r = TriageReport(timestamp="2026-10-23T22:00:00+08:00")
        self.assertEqual(r.verdict, "ok")
        self.assertEqual(r.red_count, 0)
        self.assertEqual(r.warn_count, 0)

    def test_red_count(self):
        r = TriageReport(timestamp="2026-10-23T22:00:00+08:00")
        r.signals = [
            TriageSignal("a", "red", "bad"),
            TriageSignal("b", "ok", "fine"),
            TriageSignal("c", "red", "worse"),
        ]
        self.assertEqual(r.red_count, 2)
        self.assertEqual(r.warn_count, 0)

    def test_warn_count(self):
        r = TriageReport(timestamp="2026-10-23T22:00:00+08:00")
        r.signals = [
            TriageSignal("a", "warn", "meh"),
            TriageSignal("b", "ok", "fine"),
        ]
        self.assertEqual(r.warn_count, 1)
        self.assertEqual(r.red_count, 0)

    def test_mixed_counts(self):
        r = TriageReport(timestamp="2026-10-23T22:00:00+08:00")
        r.signals = [
            TriageSignal("a", "red", "bad"),
            TriageSignal("b", "warn", "meh"),
            TriageSignal("c", "ok", "fine"),
        ]
        self.assertEqual(r.red_count, 1)
        self.assertEqual(r.warn_count, 1)


class TestCheckProcesses(unittest.TestCase):
    """Tests for check_processes with mocked subprocess."""

    @patch("repo_triage._run")
    def test_both_running(self, mock_run):
        mock_run.side_effect = [
            (0, "12345 python3 tools/writer_loop.py --writer qwen"),
            (0, "12346 python3 tools/commit_batch.py --watch"),
        ]
        s = check_processes()
        self.assertEqual(s.status, "ok")
        self.assertIn("both running", s.detail)

    @patch("repo_triage._run")
    def test_writer_dead(self, mock_run):
        mock_run.side_effect = [
            (1, ""),
            (0, "12346 python3 tools/commit_batch.py --watch"),
        ]
        s = check_processes()
        self.assertEqual(s.status, "red")
        self.assertIn("writer", s.detail)

    @patch("repo_triage._run")
    def test_batch_dead(self, mock_run):
        mock_run.side_effect = [
            (0, "12345 python3 tools/writer_loop.py --writer qwen"),
            (1, ""),
        ]
        s = check_processes()
        self.assertEqual(s.status, "red")
        self.assertIn("batch", s.detail)

    @patch("repo_triage._run")
    def test_both_dead(self, mock_run):
        mock_run.side_effect = [
            (1, ""),
            (1, ""),
        ]
        s = check_processes()
        self.assertEqual(s.status, "red")
        self.assertIn("NEITHER", s.detail)


class TestCheckUncommitted(unittest.TestCase):
    """Tests for check_uncommitted with mocked git."""

    @patch("repo_triage._run")
    def test_clean_tree(self, mock_run):
        mock_run.return_value = (0, "")
        s = check_uncommitted()
        self.assertEqual(s.status, "ok")
        self.assertEqual(s.value, 0)

    @patch("repo_triage._run")
    def test_few_files(self, mock_run):
        mock_run.return_value = (0, " M file1.py\n M file2.py")
        s = check_uncommitted()
        self.assertEqual(s.status, "ok")
        self.assertEqual(s.value, 2)

    @patch("repo_triage._run")
    def test_many_files(self, mock_run):
        files = "\n".join(f" M file{i}.py" for i in range(MAX_UNCOMMITTED + 5))
        mock_run.return_value = (0, files)
        s = check_uncommitted()
        self.assertEqual(s.status, "warn")
        self.assertEqual(s.value, MAX_UNCOMMITTED + 5)

    @patch("repo_triage._run")
    def test_git_failure(self, mock_run):
        mock_run.return_value = (1, "fatal: not a git repo")
        s = check_uncommitted()
        self.assertEqual(s.status, "warn")


class TestCheckCommitCadence(unittest.TestCase):
    """Tests for check_commit_cadence with mocked git log."""

    @patch("repo_triage._run")
    def test_normal_cadence(self, mock_run):
        now = datetime(2026, 10, 23, 14, 0, 0, tzinfo=timezone.utc)
        timestamps = []
        for i in range(10):
            ts = now - timedelta(minutes=10 * (9 - i))
            timestamps.append(ts.isoformat())
        mock_run.return_value = (0, "\n".join(timestamps))

        s = check_commit_cadence()
        self.assertEqual(s.status, "ok")
        self.assertIn("median", s.detail)

    @patch("repo_triage._run")
    def test_large_gap(self, mock_run):
        now = datetime(2026, 10, 23, 14, 0, 0, tzinfo=timezone.utc)
        timestamps = [
            (now - timedelta(hours=2)).isoformat(),
            now.isoformat(),
        ]
        mock_run.return_value = (0, "\n".join(timestamps))

        s = check_commit_cadence()
        self.assertEqual(s.status, "warn")
        self.assertIn(str(120.0), s.detail)

    @patch("repo_triage._run")
    def test_insufficient_data(self, mock_run):
        mock_run.return_value = (0, "2026-10-23T14:00:00+00:00")
        s = check_commit_cadence()
        self.assertEqual(s.status, "warn")

    @patch("repo_triage._run")
    def test_git_failure(self, mock_run):
        mock_run.return_value = (1, "")
        s = check_commit_cadence()
        self.assertEqual(s.status, "warn")


class TestCheckPushFreshness(unittest.TestCase):
    """Tests for check_push_freshness with mocked git."""

    @patch("repo_triage._run")
    def test_up_to_date(self, mock_run):
        mock_run.side_effect = [
            (0, "0"),  # unpushed
            (0, "0"),  # behind
        ]
        s = check_push_freshness()
        self.assertEqual(s.status, "ok")

    @patch("repo_triage._run")
    def test_unpushed_commits(self, mock_run):
        mock_run.side_effect = [
            (0, "5"),  # 5 unpushed
            (0, "0"),  # not behind
        ]
        s = check_push_freshness()
        self.assertEqual(s.status, "warn")
        self.assertIn("5", s.detail)

    @patch("repo_triage._run")
    def test_behind_origin(self, mock_run):
        mock_run.side_effect = [
            (0, "0"),  # no unpushed
            (0, str(PUSH_LAG_THRESHOLD + 5)),  # behind by more than threshold
        ]
        s = check_push_freshness()
        self.assertEqual(s.status, "red")
        self.assertIn("ahead", s.detail)


class TestCheckStrokeRate(unittest.TestCase):
    """Tests for check_stroke_rate with mocked state file."""

    @patch("repo_triage.Path.exists")
    def test_no_state_file(self, mock_exists):
        mock_exists.return_value = False
        s = check_stroke_rate()
        self.assertEqual(s.status, "warn")

    @patch("repo_triage.Path.read_text")
    @patch("repo_triage.Path.exists")
    def test_active_production(self, mock_exists, mock_read):
        mock_exists.return_value = True
        now = datetime.now(timezone.utc)
        history = [
            {"ts": (now - timedelta(minutes=i * 5)).isoformat()}
            for i in range(20)
        ]
        mock_read.return_value = json.dumps({"history": history})
        s = check_stroke_rate()
        self.assertEqual(s.status, "ok")
        self.assertGreaterEqual(s.value, MIN_STROKES_PER_HOUR)

    @patch("repo_triage.Path.read_text")
    @patch("repo_triage.Path.exists")
    def test_silent_writer(self, mock_exists, mock_read):
        mock_exists.return_value = True
        old = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
        history = [{"ts": old.isoformat()}]
        mock_read.return_value = json.dumps({"history": history})
        s = check_stroke_rate()
        self.assertEqual(s.status, "red")
        self.assertEqual(s.value, 0)


class TestTriageVerdict(unittest.TestCase):
    """Test the overall triage verdict logic."""

    @patch("repo_triage.check_stroke_rate")
    @patch("repo_triage.check_push_freshness")
    @patch("repo_triage.check_commit_cadence")
    @patch("repo_triage.check_uncommitted")
    @patch("repo_triage.check_processes")
    def test_all_ok(self, p, u, c, pf, sr):
        p.return_value = TriageSignal("processes", "ok", "both running")
        u.return_value = TriageSignal("uncommitted", "ok", "clean", 0)
        c.return_value = TriageSignal("cadence", "ok", "normal")
        pf.return_value = TriageSignal("push_freshness", "ok", "up to date")
        sr.return_value = TriageSignal("stroke_rate", "ok", "active", 10)

        report = triage()
        self.assertEqual(report.verdict, "ok")

    @patch("repo_triage.check_stroke_rate")
    @patch("repo_triage.check_push_freshness")
    @patch("repo_triage.check_commit_cadence")
    @patch("repo_triage.check_uncommitted")
    @patch("repo_triage.check_processes")
    def test_one_warn(self, p, u, c, pf, sr):
        p.return_value = TriageSignal("processes", "ok", "both running")
        u.return_value = TriageSignal("uncommitted", "warn", "8 files", 8)
        c.return_value = TriageSignal("cadence", "ok", "normal")
        pf.return_value = TriageSignal("push_freshness", "ok", "up to date")
        sr.return_value = TriageSignal("stroke_rate", "ok", "active", 10)

        report = triage()
        self.assertEqual(report.verdict, "warn")

    @patch("repo_triage.check_stroke_rate")
    @patch("repo_triage.check_push_freshness")
    @patch("repo_triage.check_commit_cadence")
    @patch("repo_triage.check_uncommitted")
    @patch("repo_triage.check_processes")
    def test_one_red_overrides(self, p, u, c, pf, sr):
        p.return_value = TriageSignal("processes", "red", "both dead")
        u.return_value = TriageSignal("uncommitted", "ok", "clean", 0)
        c.return_value = TriageSignal("cadence", "ok", "normal")
        pf.return_value = TriageSignal("push_freshness", "ok", "up to date")
        sr.return_value = TriageSignal("stroke_rate", "ok", "active", 10)

        report = triage()
        self.assertEqual(report.verdict, "red")


class TestFormatting(unittest.TestCase):
    """Tests for output formatting."""

    def _sample_report(self):
        return TriageReport(
            timestamp="2026-10-23T22:01:00+08:00",
            signals=[
                TriageSignal("processes", "ok", "both running"),
                TriageSignal("uncommitted", "warn", "3 files", 3),
                TriageSignal("cadence", "ok", "median 10min"),
            ],
            verdict="warn",
        )

    def test_format_text_contains_verdict(self):
        report = self._sample_report()
        text = format_text(report)
        self.assertIn("WARN", text)
        self.assertIn("TRIAGE", text)
        self.assertIn("both running", text)

    def test_format_text_shows_warning_count(self):
        report = self._sample_report()
        text = format_text(report)
        self.assertIn("1 warning(s)", text)

    def test_format_json_is_valid(self):
        report = self._sample_report()
        j = format_json(report)
        data = json.loads(j)
        self.assertEqual(data["verdict"], "warn")
        self.assertEqual(len(data["signals"]), 3)

    def test_format_json_signal_structure(self):
        report = self._sample_report()
        data = json.loads(format_json(report))
        sig = data["signals"][0]
        self.assertIn("name", sig)
        self.assertIn("status", sig)
        self.assertIn("detail", sig)


if __name__ == "__main__":
    unittest.main()
