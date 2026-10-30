#!/usr/bin/env python3
"""Tests for env_inheritance_check.py.

uses the current process's own /proc entry to validate the checker without
mocking the filesystem. also covers error paths with synthetic inputs.

run:
    python3 -m pytest tools/test_env_inheritance_check.py -v
    python3 tools/test_env_inheritance_check.py
"""

import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import env_inheritance_check as eic  # noqa: E402


class TestReadProcEnv(unittest.TestCase):
    """test reading /proc/<pid>/environ for the current process."""

    def test_read_self(self):
        """we can read our own environment from /proc/self/environ."""
        pid = os.getpid()
        env = eic.read_proc_env(pid)
        # PATH is almost universally set; if it isn't, this test is meaningless
        self.assertIn("PATH", env)
        self.assertEqual(env["PATH"], os.environ.get("PATH", ""))

    def test_child_contains_set_var(self):
        """a variable set before launch appears in the child's /proc."""
        env = os.environ.copy()
        env["IAMAII_TEST_MARKER"] = "hello_from_test"
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            e = eic.read_proc_env(proc.pid)
            self.assertEqual(e.get("IAMAII_TEST_MARKER"), "hello_from_test")
        finally:
            proc.kill()
            proc.wait()

    def test_nonexistent_pid_raises(self):
        """a pid that doesn't exist raises FileNotFoundError."""
        # use a very high pid that is extremely unlikely to exist
        with self.assertRaises(FileNotFoundError):
            eic.read_proc_env(999999999)


class TestCheckEnv(unittest.TestCase):
    """test the check_env report builder."""

    def test_all_present(self):
        """when all required vars exist, report is ok with empty missing list."""
        report = eic.check_env(os.getpid(), ["PATH", "HOME"])
        self.assertTrue(report["ok"])
        self.assertEqual(report["missing"], [])
        self.assertIn("PATH", report["present"])
        self.assertIn("HOME", report["present"])

    def test_missing_var(self):
        """a variable that doesn't exist shows up in missing list."""
        report = eic.check_env(os.getpid(), ["THIS_VAR_DEFINITELY_NOT_SET_XYZ"])
        self.assertFalse(report["ok"])
        self.assertIn("THIS_VAR_DEFINITELY_NOT_SET_XYZ", report["missing"])

    def test_mixed_present_and_missing(self):
        """some present, some missing — report reflects both correctly."""
        report = eic.check_env(
            os.getpid(),
            ["PATH", "THIS_VAR_DEFINITELY_NOT_SET_XYZ"],
        )
        self.assertFalse(report["ok"])
        self.assertIn("PATH", report["present"])
        self.assertIn("THIS_VAR_DEFINITELY_NOT_SET_XYZ", report["missing"])

    def test_long_value_truncated(self):
        """values longer than 120 chars are truncated with ellipsis."""
        long_val = "x" * 200
        env = os.environ.copy()
        env["IAMAII_LONG_TEST_VAR"] = long_val
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            report = eic.check_env(proc.pid, ["IAMAII_LONG_TEST_VAR"])
            self.assertTrue(report["ok"])
            val = report["present"]["IAMAII_LONG_TEST_VAR"]
            self.assertTrue(val.endswith("..."))
            self.assertLessEqual(len(val), 120)
        finally:
            proc.kill()
            proc.wait()

    def test_nonexistent_pid_report(self):
        """a missing pid produces an error report, not a crash."""
        report = eic.check_env(999999999, ["PATH"])
        self.assertFalse(report["ok"])
        self.assertIn("error", report)
        # missing list should contain all required vars when process is unreadable
        self.assertEqual(report["missing"], ["PATH"])

    def test_empty_required_list(self):
        """an empty required list is trivially ok."""
        report = eic.check_env(os.getpid(), [])
        self.assertTrue(report["ok"])
        self.assertEqual(report["missing"], [])
        self.assertEqual(report["required"], [])


class TestParseRequired(unittest.TestCase):
    """test the comma-separated required list parser."""

    def test_simple(self):
        self.assertEqual(eic.parse_required("A,B,C"), ["A", "B", "C"])

    def test_whitespace(self):
        self.assertEqual(eic.parse_required(" A , B , C "), ["A", "B", "C"])

    def test_empty_entries(self):
        self.assertEqual(eic.parse_required("A,,B,,"), ["A", "B"])

    def test_single(self):
        self.assertEqual(eic.parse_required("GIT_SSH_COMMAND"), ["GIT_SSH_COMMAND"])


class TestChildProcessInheritance(unittest.TestCase):
    """test that a child process actually inherits env vars — the real scenario."""

    def test_child_inherits_custom_var(self):
        """a subprocess launched with a custom var has it in /proc."""
        env = os.environ.copy()
        env["IAMAII_CHILD_TEST"] = "inherited_value"
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            report = eic.check_env(proc.pid, ["IAMAII_CHILD_TEST", "PATH"])
            self.assertTrue(report["ok"])
            self.assertEqual(
                report["present"]["IAMAII_CHILD_TEST"], "inherited_value"
            )
        finally:
            proc.kill()
            proc.wait()

    def test_child_without_var_reports_missing(self):
        """a subprocess launched without a required var shows it as missing."""
        env = os.environ.copy()
        env.pop("IAMAII_SHOULD_NOT_EXIST", None)
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            report = eic.check_env(proc.pid, ["IAMAII_SHOULD_NOT_EXIST"])
            self.assertFalse(report["ok"])
            self.assertIn("IAMAII_SHOULD_NOT_EXIST", report["missing"])
        finally:
            proc.kill()
            proc.wait()


if __name__ == "__main__":
    unittest.main()
