#!/usr/bin/env python3
"""tests for push_recovery_time.py — covers all exit codes and edge cases."""

import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from push_recovery_time import (
    find_first_ok_after,
    find_last_rejection,
    human_summary,
    measure,
    read_events,
    SLOW_THRESHOLD,
    STALE_THRESHOLD,
)


class TestReadEvents(unittest.TestCase):
    def test_missing_file(self):
        self.assertEqual(read_events("/nonexistent/path.jsonl"), [])

    def test_valid_events(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"ts": 1000, "event": "rejected", "reason": "non-ff"}\n')
            f.write('{"ts": 1060, "event": "ok", "commit": "abc"}\n')
            path = f.name
        try:
            events = read_events(path)
            self.assertEqual(len(events), 2)
            self.assertEqual(events[0]["event"], "rejected")
            self.assertEqual(events[1]["event"], "ok")
        finally:
            os.unlink(path)

    def test_malformed_lines_skipped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("not json\n")
            f.write('{"ts": 1000, "event": "rejected"}\n')
            f.write("{broken\n")
            path = f.name
        try:
            events = read_events(path)
            self.assertEqual(len(events), 1)
        finally:
            os.unlink(path)


class TestFindLastRejection(unittest.TestCase):
    def test_no_rejections(self):
        events = [{"ts": 100, "event": "ok"}, {"ts": 200, "event": "ok"}]
        self.assertIsNone(find_last_rejection(events))

    def test_single_rejection(self):
        events = [{"ts": 100, "event": "rejected", "reason": "auth"}]
        rej = find_last_rejection(events)
        self.assertEqual(rej["ts"], 100)

    def test_returns_most_recent(self):
        events = [
            {"ts": 100, "event": "rejected", "reason": "old"},
            {"ts": 300, "event": "rejected", "reason": "new"},
        ]
        rej = find_last_rejection(events)
        self.assertEqual(rej["reason"], "new")


class TestFindFirstOkAfter(unittest.TestCase):
    def test_ok_exists(self):
        events = [
            {"ts": 100, "event": "rejected"},
            {"ts": 150, "event": "ok", "commit": "aaa"},
            {"ts": 200, "event": "ok", "commit": "bbb"},
        ]
        ok = find_first_ok_after(events, 100)
        self.assertEqual(ok["commit"], "aaa")

    def test_no_ok_after(self):
        events = [
            {"ts": 100, "event": "rejected"},
            {"ts": 50, "event": "ok", "commit": "before"},
        ]
        self.assertIsNone(find_first_ok_after(events, 100))


class TestMeasure(unittest.TestCase):
    def _write_log(self, events):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
        for ev in events:
            f.write(json.dumps(ev) + "\n")
        f.close()
        return f.name

    def test_no_log_file(self):
        report = measure("/nonexistent/path.jsonl", now=1000)
        self.assertEqual(report["status"], "no_log")
        self.assertEqual(report["exit_code"], 3)

    def test_clean_no_rejections(self):
        path = self._write_log([{"ts": 100, "event": "ok", "commit": "x"}])
        try:
            report = measure(path, now=200)
            self.assertEqual(report["status"], "clean")
            self.assertEqual(report["exit_code"], 0)
        finally:
            os.unlink(path)

    def test_healthy_recovery(self):
        t0 = 1000
        path = self._write_log([
            {"ts": t0, "event": "rejected", "reason": "non-ff"},
            {"ts": t0 + 30, "event": "ok", "commit": "abc"},
        ])
        try:
            report = measure(path, now=t0 + 100)
            self.assertEqual(report["status"], "healthy")
            self.assertEqual(report["recovery_seconds"], 30.0)
            self.assertEqual(report["exit_code"], 0)
        finally:
            os.unlink(path)

    def test_slow_recovery(self):
        t0 = 1000
        path = self._write_log([
            {"ts": t0, "event": "rejected", "reason": "auth"},
            {"ts": t0 + 200, "event": "ok", "commit": "def"},
        ])
        try:
            report = measure(path, now=t0 + 300)
            self.assertEqual(report["status"], "slow")
            self.assertEqual(report["exit_code"], 1)
        finally:
            os.unlink(path)

    def test_stale_recovery(self):
        t0 = 1000
        path = self._write_log([
            {"ts": t0, "event": "rejected", "reason": "network"},
            {"ts": t0 + 700, "event": "ok", "commit": "ghi"},
        ])
        try:
            report = measure(path, now=t0 + 800)
            self.assertEqual(report["status"], "stale_recovery")
            self.assertEqual(report["exit_code"], 2)
        finally:
            os.unlink(path)

    def test_pending_healthy(self):
        t0 = 1000
        path = self._write_log([
            {"ts": t0, "event": "rejected", "reason": "non-ff"},
        ])
        try:
            report = measure(path, now=t0 + 60)
            self.assertEqual(report["status"], "pending")
            self.assertEqual(report["exit_code"], 0)
            self.assertIsNotNone(report["pending_rejection"])
            self.assertEqual(report["pending_rejection"]["reason"], "non-ff")
        finally:
            os.unlink(path)

    def test_pending_stale(self):
        t0 = 1000
        path = self._write_log([
            {"ts": t0, "event": "rejected", "reason": "auth"},
        ])
        try:
            report = measure(path, now=t0 + 700)
            self.assertEqual(report["status"], "pending")
            self.assertEqual(report["exit_code"], 2)
        finally:
            os.unlink(path)


class TestHumanSummary(unittest.TestCase):
    def test_no_log(self):
        s = human_summary({"status": "no_log", "exit_code": 3,
                           "recovery_seconds": None, "pending_rejection": None})
        self.assertIn("no push event log", s)

    def test_clean(self):
        s = human_summary({"status": "clean", "exit_code": 0,
                           "recovery_seconds": None, "pending_rejection": None})
        self.assertIn("no pending", s)

    def test_healthy(self):
        s = human_summary({"status": "healthy", "exit_code": 0,
                           "recovery_seconds": 45.2, "pending_rejection": None})
        self.assertIn("45.2s", s)

    def test_pending(self):
        s = human_summary({"status": "pending", "exit_code": 1,
                           "recovery_seconds": None,
                           "pending_rejection": {"ts": 100, "reason": "auth",
                                                  "elapsed_seconds": 300}})
        self.assertIn("300", s)
        self.assertIn("auth", s)


if __name__ == "__main__":
    unittest.main()
