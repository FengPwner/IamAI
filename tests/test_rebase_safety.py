#!/usr/bin/env python3
"""Tests for iamai/rebase_safety.py — pre-rebase safety gate.

Covers:
- RebaseReadiness enum values
- SafetyCheck dataclass construction
- Verdict summary formatting
- Individual check functions (pause_signal, process_liveness, batch_liveness, dirty_state)
- assess() aggregate logic
- verdict_to_dict serialisation
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, mock_open

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.rebase_safety import (
    RebaseReadiness,
    SafetyCheck,
    Verdict,
    WRITER_MANAGED_FILES,
    WRITER_PID_PATTERN,
    BATCH_PID_PATTERN,
    PAUSE_PATTERN,
    check_pause_signal,
    check_dirty_state,
    check_process_liveness,
    check_batch_liveness,
    assess,
    verdict_to_dict,
)


# ---------------------------------------------------------------------------
# Enum & dataclass basics
# ---------------------------------------------------------------------------

class TestRebaseReadiness(unittest.TestCase):
    def test_values(self):
        self.assertEqual(RebaseReadiness.SAFE.value, "safe")
        self.assertEqual(RebaseReadiness.UNSAFE.value, "unsafe")
        self.assertEqual(RebaseReadiness.ERROR.value, "error")

    def test_identity(self):
        self.assertIs(RebaseReadiness.SAFE, RebaseReadiness("safe"))


class TestSafetyCheck(unittest.TestCase):
    def test_defaults(self):
        sc = SafetyCheck(name="x", passed=True, detail="ok")
        self.assertEqual(sc.severity, "warning")

    def test_blocking(self):
        sc = SafetyCheck(name="x", passed=False, detail="bad", severity="blocking")
        self.assertEqual(sc.severity, "blocking")


class TestVerdict(unittest.TestCase):
    def test_summary_pass(self):
        v = Verdict(
            ready=True,
            status=RebaseReadiness.SAFE,
            checks=[
                SafetyCheck("a", True, "ok"),
                SafetyCheck("b", True, "ok"),
            ],
        )
        self.assertIn("2/2", v.summary)
        self.assertIn("✓", v.summary)

    def test_summary_fail(self):
        v = Verdict(
            ready=False,
            status=RebaseReadiness.UNSAFE,
            checks=[
                SafetyCheck("a", True, "ok"),
                SafetyCheck("b", False, "nope", severity="blocking"),
            ],
        )
        self.assertIn("1/2", v.summary)
        self.assertIn("✗", v.summary)


# ---------------------------------------------------------------------------
# check_pause_signal
# ---------------------------------------------------------------------------

class TestCheckPauseSignal(unittest.TestCase):
    def test_pause_present(self):
        """When the pause sentinel exists, check passes."""
        fake = Path("/tmp/iamai-writer-pause-test")
        fake.write_text("paused\n")
        try:
            result = check_pause_signal(repo_root="/tmp", writer="test")
            self.assertTrue(result.passed)
            self.assertEqual(result.name, "pause_signal")
        finally:
            fake.unlink(missing_ok=True)

    def test_pause_missing(self):
        """When the pause sentinel is absent, check fails as blocking."""
        # Use a writer name that definitely has no pause file.
        result = check_pause_signal(repo_root="/tmp", writer="nonexistent-writer-xyz")
        self.assertFalse(result.passed)
        self.assertEqual(result.severity, "blocking")


# ---------------------------------------------------------------------------
# check_process_liveness
# ---------------------------------------------------------------------------

class TestCheckProcessLiveness(unittest.TestCase):
    def test_no_pid_file(self):
        """No PID file means writer is not running — safe."""
        with patch("iamai.rebase_safety.WRITER_PID_PATTERN",
                    "/tmp/iamai-writer-{writer}.pid.test_nopid"):
            result = check_process_liveness(writer="nonexistent-xyz")
            self.assertTrue(result.passed)
            self.assertIn("not running", result.detail)

    def test_stale_pid(self):
        """PID file exists but process is dead — safe."""
        pid_file = Path("/tmp/iamai-writer-test-stale.pid")
        pid_file.write_text("999999999\n")  # almost certainly dead
        try:
            with patch("iamai.rebase_safety.WRITER_PID_PATTERN",
                        str(pid_file).replace("test-stale", "{writer}")):
                result = check_process_liveness(writer="test-stale")
                self.assertTrue(result.passed)
                self.assertIn("stale", result.detail)
        finally:
            pid_file.unlink(missing_ok=True)

    def test_live_pid(self):
        """PID file with a live process — unsafe (blocking)."""
        pid_file = Path("/tmp/iamai-writer-test-live.pid")
        pid_file.write_text(f"{os.getpid()}\n")  # current process is alive
        try:
            with patch("iamai.rebase_safety.WRITER_PID_PATTERN",
                        str(pid_file).replace("test-live", "{writer}")):
                result = check_process_liveness(writer="test-live")
                self.assertFalse(result.passed)
                self.assertEqual(result.severity, "blocking")
                self.assertIn("alive", result.detail)
        finally:
            pid_file.unlink(missing_ok=True)

    def test_corrupt_pid_file(self):
        """Unreadable PID file — warning."""
        pid_file = Path("/tmp/iamai-writer-test-corrupt.pid")
        pid_file.write_text("not-a-number\n")
        try:
            with patch("iamai.rebase_safety.WRITER_PID_PATTERN",
                        str(pid_file).replace("test-corrupt", "{writer}")):
                result = check_process_liveness(writer="test-corrupt")
                self.assertFalse(result.passed)
                self.assertEqual(result.severity, "warning")
        finally:
            pid_file.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# check_batch_liveness
# ---------------------------------------------------------------------------

class TestCheckBatchLiveness(unittest.TestCase):
    def test_no_pid_file(self):
        """No batch PID — safe."""
        with patch("iamai.rebase_safety.BATCH_PID_PATTERN",
                    "/tmp/iamai-batch-{writer}.pid.test_nobatch"):
            result = check_batch_liveness(writer="nonexistent-xyz")
            self.assertTrue(result.passed)

    def test_live_batch(self):
        """Live batch process — blocking."""
        pid_file = Path("/tmp/iamai-batch-test-live.pid")
        pid_file.write_text(f"{os.getpid()}\n")
        try:
            with patch("iamai.rebase_safety.BATCH_PID_PATTERN",
                        str(pid_file).replace("test-live", "{writer}")):
                result = check_batch_liveness(writer="test-live")
                self.assertFalse(result.passed)
                self.assertEqual(result.severity, "blocking")
        finally:
            pid_file.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# check_dirty_state
# ---------------------------------------------------------------------------

class TestCheckDirtyState(unittest.TestCase):
    def test_empty_tree(self):
        """Nonexistent managed files — passes."""
        with tempfile.TemporaryDirectory() as td:
            result = check_dirty_state(repo_root=td, writer_managed=["nope.txt"])
            self.assertTrue(result.passed)

    def test_managed_files_present(self):
        """Present managed files — passes with warning (CLI must verify)."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "managed.txt"
            p.write_text("content")
            result = check_dirty_state(repo_root=td, writer_managed=["managed.txt"])
            self.assertTrue(result.passed)
            self.assertEqual(result.severity, "warning")
            self.assertIn("1 writer-managed", result.detail)


# ---------------------------------------------------------------------------
# assess()
# ---------------------------------------------------------------------------

class TestAssess(unittest.TestCase):
    def test_safe_when_everything_clear(self):
        """All checks pass → SAFE verdict."""
        with tempfile.TemporaryDirectory() as td:
            with patch("iamai.rebase_safety.PAUSE_PATTERN",
                        "/tmp/iamai-writer-pause-{writer}.assess-test"), \
                 patch("iamai.rebase_safety.WRITER_PID_PATTERN",
                        "/tmp/iamai-writer-{writer}.pid.assess-test"), \
                 patch("iamai.rebase_safety.BATCH_PID_PATTERN",
                        "/tmp/iamai-batch-{writer}.pid.assess-test"):
                # Create pause file so check_pause_signal passes.
                pause = Path("/tmp/iamai-writer-pause-qwen.assess-test")
                pause.write_text("paused")
                try:
                    v = assess(repo_root=td, writer="qwen",
                              writer_managed=["nonexistent.txt"])
                    self.assertTrue(v.ready)
                    self.assertEqual(v.status, RebaseReadiness.SAFE)
                finally:
                    pause.unlink(missing_ok=True)

    def test_unsafe_when_no_pause_and_live_writer(self):
        """No pause + live writer → UNSAFE with blocking checks."""
        with tempfile.TemporaryDirectory() as td:
            with patch("iamai.rebase_safety.PAUSE_PATTERN",
                        "/tmp/iamai-writer-pause-{writer}.assess-unsafe"), \
                 patch("iamai.rebase_safety.WRITER_PID_PATTERN",
                        "/tmp/iamai-writer-{writer}.pid.assess-unsafe"), \
                 patch("iamai.rebase_safety.BATCH_PID_PATTERN",
                        "/tmp/iamai-batch-{writer}.pid.assess-unsafe"):
                # No pause file.
                # Writer PID = current process (alive).
                pid = Path("/tmp/iamai-writer-qwen.pid.assess-unsafe")
                pid.write_text(f"{os.getpid()}\n")
                try:
                    v = assess(repo_root=td, writer="qwen",
                              writer_managed=["nonexistent.txt"])
                    self.assertFalse(v.ready)
                    self.assertEqual(v.status, RebaseReadiness.UNSAFE)
                    blocking = [c for c in v.checks
                               if not c.passed and c.severity == "blocking"]
                    self.assertGreaterEqual(len(blocking), 1)
                    # Remediation should include pause/kill instructions.
                    rem_text = " ".join(v.remediation)
                    self.assertIn("pause", rem_text.lower())
                finally:
                    pid.unlink(missing_ok=True)

    def test_remediation_always_includes_sleep_and_rebase(self):
        """Every verdict includes sleep + rebase steps at the end."""
        with tempfile.TemporaryDirectory() as td:
            with patch("iamai.rebase_safety.PAUSE_PATTERN",
                        "/tmp/iamai-writer-pause-{writer}.assess-rem"), \
                 patch("iamai.rebase_safety.WRITER_PID_PATTERN",
                        "/tmp/iamai-writer-{writer}.pid.assess-rem"), \
                 patch("iamai.rebase_safety.BATCH_PID_PATTERN",
                        "/tmp/iamai-batch-{writer}.pid.assess-rem"):
                pause = Path("/tmp/iamai-writer-pause-qwen.assess-rem")
                pause.write_text("paused")
                try:
                    v = assess(repo_root=td, writer="qwen")
                    # Last two remediation steps are always present.
                    self.assertTrue(any("sleep" in s for s in v.remediation))
                    self.assertTrue(any("rebase" in s for s in v.remediation))
                finally:
                    pause.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# verdict_to_dict
# ---------------------------------------------------------------------------

class TestVerdictToDict(unittest.TestCase):
    def test_structure(self):
        v = Verdict(
            ready=True,
            status=RebaseReadiness.SAFE,
            checks=[SafetyCheck("a", True, "ok")],
            remediation=["step1"],
        )
        d = verdict_to_dict(v)
        self.assertTrue(d["ready"])
        self.assertEqual(d["status"], "safe")
        self.assertIn("summary", d)
        self.assertEqual(len(d["checks"]), 1)
        self.assertEqual(d["checks"][0]["name"], "a")
        self.assertEqual(d["remediation"], ["step1"])

    def test_unsafe_serialisation(self):
        v = Verdict(
            ready=False,
            status=RebaseReadiness.UNSAFE,
            checks=[SafetyCheck("b", False, "blocked", severity="blocking")],
            remediation=["kill writer", "rebase"],
        )
        d = verdict_to_dict(v)
        self.assertFalse(d["ready"])
        self.assertEqual(d["status"], "unsafe")
        self.assertEqual(d["checks"][0]["severity"], "blocking")


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    def test_writer_managed_includes_strokes(self):
        self.assertIn("data/strokes.jsonl", WRITER_MANAGED_FILES)

    def test_patterns_have_writer_placeholder(self):
        self.assertIn("{writer}", WRITER_PID_PATTERN)
        self.assertIn("{writer}", BATCH_PID_PATTERN)
        self.assertIn("{writer}", PAUSE_PATTERN)


if __name__ == "__main__":
    unittest.main()
