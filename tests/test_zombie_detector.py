#!/usr/bin/env python3
"""Tests for zombie_detector.py — detect alive-but-stalled processes."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from dataclasses import asdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from zombie_detector import (
    ZombieSignal,
    ZombieReport,
    _is_alive,
    _file_age_seconds,
    _process_cpu_seconds,
    _process_rss_kb,
    check_stale_output,
    check_cpu_starvation,
    check_memory_frozen,
    zombie_check,
)


class TestZombieSignal(unittest.TestCase):
    """Test signal severity classification."""

    def test_clear_when_not_triggered(self):
        s = ZombieSignal(name="test", triggered=False, value=10.0, threshold=5.0, detail="ok")
        self.assertEqual(s.severity, "clear")

    def test_critical_when_value_exceeds_3x_threshold(self):
        s = ZombieSignal(name="test", triggered=True, value=20.0, threshold=5.0, detail="high")
        self.assertEqual(s.severity, "critical")

    def test_warning_when_value_exceeds_1_5x_threshold(self):
        s = ZombieSignal(name="test", triggered=True, value=10.0, threshold=5.0, detail="medium")
        self.assertEqual(s.severity, "warning")

    def test_marginal_when_just_above_threshold(self):
        s = ZombieSignal(name="test", triggered=True, value=6.0, threshold=5.0, detail="low")
        self.assertEqual(s.severity, "marginal")

    def test_severity_with_zero_threshold(self):
        s = ZombieSignal(name="test", triggered=True, value=1.0, threshold=0.0, detail="inf")
        self.assertEqual(s.severity, "critical")

    def test_severity_boundary_at_3x(self):
        # Exactly 3x is the boundary — severity uses > so 3.0 falls into "warning"
        s = ZombieSignal(name="test", triggered=True, value=15.0, threshold=5.0, detail="exact")
        self.assertEqual(s.severity, "warning")
        # Just over 3x → critical
        s2 = ZombieSignal(name="test", triggered=True, value=15.1, threshold=5.0, detail="over")
        self.assertEqual(s2.severity, "critical")

    def test_severity_boundary_at_1_5x(self):
        # Exactly 1.5x falls into "marginal" (severity uses > not >=)
        s = ZombieSignal(name="test", triggered=True, value=7.5, threshold=5.0, detail="exact")
        self.assertEqual(s.severity, "marginal")
        # Just over 1.5x → warning
        s2 = ZombieSignal(name="test", triggered=True, value=7.6, threshold=5.0, detail="over")
        self.assertEqual(s2.severity, "warning")


class TestZombieReport(unittest.TestCase):
    """Test report verdict and exit code logic."""

    def _make_report(self, alive=True, triggered=0):
        signals = [
            ZombieSignal(name=f"sig{i}", triggered=(i < triggered),
                         value=float(i), threshold=5.0, detail="test")
            for i in range(3)
        ]
        return ZombieReport(pid=1234, alive=alive, signals=signals)

    def test_dead_verdict(self):
        r = self._make_report(alive=False)
        self.assertEqual(r.verdict, "dead")
        self.assertEqual(r.exit_code, 2)

    def test_healthy_verdict(self):
        r = self._make_report(alive=True, triggered=0)
        self.assertEqual(r.verdict, "healthy")
        self.assertEqual(r.exit_code, 0)

    def test_degraded_verdict(self):
        r = self._make_report(alive=True, triggered=1)
        self.assertEqual(r.verdict, "degraded")
        self.assertEqual(r.exit_code, 0)

    def test_zombie_verdict(self):
        r = self._make_report(alive=True, triggered=2)
        self.assertEqual(r.verdict, "zombie")
        self.assertEqual(r.exit_code, 1)

    def test_zombie_verdict_all_triggered(self):
        r = self._make_report(alive=True, triggered=3)
        self.assertEqual(r.verdict, "zombie")
        self.assertEqual(r.exit_code, 1)

    def test_triggered_count(self):
        r = self._make_report(alive=True, triggered=2)
        self.assertEqual(r.triggered_count, 2)

    def test_empty_signals(self):
        r = ZombieReport(pid=999, alive=True)
        self.assertEqual(r.verdict, "healthy")
        self.assertEqual(r.triggered_count, 0)


class TestIsAlive(unittest.TestCase):
    """Test process existence check."""

    def test_current_process_is_alive(self):
        self.assertTrue(_is_alive(os.getpid()))

    def test_nonexistent_pid(self):
        # Use a very high PID that almost certainly doesn't exist
        self.assertFalse(_is_alive(9999999))

    @patch("os.kill", side_effect=PermissionError)
    def test_permission_error_means_alive(self, mock_kill):
        # PermissionError means process exists but we can't signal it
        self.assertTrue(_is_alive(1234))

    @patch("os.kill", side_effect=ProcessLookupError)
    def test_process_lookup_error_means_dead(self, mock_kill):
        self.assertFalse(_is_alive(1234))


class TestFileAge(unittest.TestCase):
    """Test output file age calculation."""

    def test_existing_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test")
            f.flush()
            age = _file_age_seconds(f.name)
            self.assertIsNotNone(age)
            self.assertGreaterEqual(age, 0.0)
            self.assertLess(age, 5.0)
            os.unlink(f.name)

    def test_missing_file(self):
        age = _file_age_seconds("/tmp/definitely_does_not_exist_zzz_12345.txt")
        self.assertIsNone(age)


class TestCheckStaleOutput(unittest.TestCase):
    """Test stale output detection."""

    def test_fresh_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"recent")
            f.flush()
            sig = check_stale_output(f.name, expected_interval=15.0, multiplier=4.0)
            self.assertFalse(sig.triggered)
            self.assertEqual(sig.name, "stale_output")
            os.unlink(f.name)

    def test_stale_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"old")
            f.flush()
            # Set mtime to 5 minutes ago
            old_time = time.time() - 300
            os.utime(f.name, (old_time, old_time))
            sig = check_stale_output(f.name, expected_interval=15.0, multiplier=4.0)
            self.assertTrue(sig.triggered)
            self.assertGreater(sig.value, 290.0)
            os.unlink(f.name)

    def test_missing_file_is_stale(self):
        sig = check_stale_output(
            "/tmp/nonexistent_output_file_zzz.txt",
            expected_interval=15.0,
        )
        self.assertTrue(sig.triggered)
        self.assertEqual(sig.value, float("inf"))

    def test_custom_multiplier(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x")
            f.flush()
            old_time = time.time() - 20
            os.utime(f.name, (old_time, old_time))
            # With multiplier=1.0 and interval=15, threshold=15s; 20s old should trigger
            sig1 = check_stale_output(f.name, expected_interval=15.0, multiplier=1.0)
            self.assertTrue(sig1.triggered)
            # With multiplier=2.0 and interval=15, threshold=30s; 20s old should not
            sig2 = check_stale_output(f.name, expected_interval=15.0, multiplier=2.0)
            self.assertFalse(sig2.triggered)
            os.unlink(f.name)


class TestCheckCpuStarvation(unittest.TestCase):
    """Test CPU starvation detection."""

    def test_current_process_not_starved(self):
        # Current process is definitely using CPU
        sig = check_cpu_starvation(os.getpid())
        # We can't guarantee it won't be triggered (depends on timing)
        # but we can check the signal structure
        self.assertEqual(sig.name, "cpu_starvation")
        self.assertIsInstance(sig.triggered, bool)

    def test_nonexistent_pid_returns_clear(self):
        sig = check_cpu_starvation(9999999)
        # Should return insufficient data, not triggered
        self.assertFalse(sig.triggered)
        self.assertIn("insufficient", sig.detail)

    @patch("zombie_detector._process_cpu_seconds", return_value=0.001)
    @patch("zombie_detector._process_uptime_seconds", return_value=3600.0)
    def test_starved_process(self, mock_uptime, mock_cpu):
        sig = check_cpu_starvation(1234, min_cpu_ratio=0.01)
        self.assertTrue(sig.triggered)
        self.assertLess(sig.value, 0.01)

    @patch("zombie_detector._process_cpu_seconds", return_value=100.0)
    @patch("zombie_detector._process_uptime_seconds", return_value=3600.0)
    def test_healthy_cpu_ratio(self, mock_uptime, mock_cpu):
        sig = check_cpu_starvation(1234, min_cpu_ratio=0.01)
        self.assertFalse(sig.triggered)

    @patch("zombie_detector._process_cpu_seconds", return_value=None)
    @patch("zombie_detector._process_uptime_seconds", return_value=3600.0)
    def test_none_cpu_returns_clear(self, mock_uptime, mock_cpu):
        sig = check_cpu_starvation(1234)
        self.assertFalse(sig.triggered)

    @patch("zombie_detector._process_cpu_seconds", return_value=5.0)
    @patch("zombie_detector._process_uptime_seconds", return_value=0.5)
    def test_short_uptime_returns_clear(self, mock_uptime, mock_cpu):
        # Less than 1 second uptime → insufficient data
        sig = check_cpu_starvation(1234)
        self.assertFalse(sig.triggered)


class TestCheckMemoryFrozen(unittest.TestCase):
    """Test memory frozen detection."""

    def test_with_mock_varying_rss(self):
        """Varying RSS across samples → not frozen."""
        with patch("zombie_detector._process_rss_kb", side_effect=[1000, 1024, 1048]):
            sig = check_memory_frozen(1234, samples=3, interval=0.01)
            self.assertFalse(sig.triggered)

    def test_with_mock_constant_rss(self):
        """Identical RSS across samples → frozen."""
        with patch("zombie_detector._process_rss_kb", return_value=2048):
            sig = check_memory_frozen(1234, samples=3, interval=0.01)
            self.assertTrue(sig.triggered)

    def test_with_insufficient_samples(self):
        """None returns → insufficient data."""
        with patch("zombie_detector._process_rss_kb", return_value=None):
            sig = check_memory_frozen(1234, samples=3, interval=0.01)
            self.assertFalse(sig.triggered)
            self.assertIn("insufficient", sig.detail)

    def test_single_valid_sample(self):
        """Only one valid sample out of three → insufficient."""
        with patch("zombie_detector._process_rss_kb", side_effect=[1000, None, None]):
            sig = check_memory_frozen(1234, samples=3, interval=0.01)
            self.assertFalse(sig.triggered)

    def test_two_identical_samples(self):
        """Two identical samples → frozen (unique=1)."""
        with patch("zombie_detector._process_rss_kb", side_effect=[512, 512]):
            sig = check_memory_frozen(1234, samples=2, interval=0.01)
            self.assertTrue(sig.triggered)

    def test_two_different_samples(self):
        """Two different samples → not frozen."""
        with patch("zombie_detector._process_rss_kb", side_effect=[512, 768]):
            sig = check_memory_frozen(1234, samples=2, interval=0.01)
            self.assertFalse(sig.triggered)


class TestZombieCheck(unittest.TestCase):
    """Integration tests for the full zombie check."""

    def test_dead_process_returns_dead(self):
        with patch("zombie_detector._is_alive", return_value=False):
            report = zombie_check(
                pid=99999,
                output_path="/tmp/whatever",
                expected_interval=15.0,
            )
            self.assertEqual(report.verdict, "dead")
            self.assertEqual(report.exit_code, 2)
            self.assertEqual(len(report.signals), 0)

    def test_healthy_process(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"active")
            f.flush()
            with patch("zombie_detector._is_alive", return_value=True), \
                 patch("zombie_detector._process_cpu_seconds", return_value=50.0), \
                 patch("zombie_detector._process_uptime_seconds", return_value=300.0), \
                 patch("zombie_detector._process_rss_kb", side_effect=[1000, 1024, 1048]):
                report = zombie_check(
                    pid=1234,
                    output_path=f.name,
                    expected_interval=15.0,
                    samples=3,
                    sample_interval=0.01,
                )
                self.assertEqual(report.verdict, "healthy")
                self.assertEqual(report.exit_code, 0)
            os.unlink(f.name)

    def test_zombie_process(self):
        old_time = time.time() - 300
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"stale")
            f.flush()
            os.utime(f.name, (old_time, old_time))
            with patch("zombie_detector._is_alive", return_value=True), \
                 patch("zombie_detector._process_cpu_seconds", return_value=0.001), \
                 patch("zombie_detector._process_uptime_seconds", return_value=3600.0), \
                 patch("zombie_detector._process_rss_kb", return_value=2048):
                report = zombie_check(
                    pid=1234,
                    output_path=f.name,
                    expected_interval=15.0,
                    samples=3,
                    sample_interval=0.01,
                )
                # stale_output + cpu_starvation + memory_frozen = zombie
                self.assertEqual(report.verdict, "zombie")
                self.assertGreaterEqual(report.triggered_count, 2)
            os.unlink(f.name)

    def test_skip_memory_flag(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"ok")
            f.flush()
            with patch("zombie_detector._is_alive", return_value=True), \
                 patch("zombie_detector._process_cpu_seconds", return_value=50.0), \
                 patch("zombie_detector._process_uptime_seconds", return_value=300.0):
                report = zombie_check(
                    pid=1234,
                    output_path=f.name,
                    expected_interval=15.0,
                    skip_memory=True,
                )
                # Only stale_output and cpu_starvation signals
                self.assertEqual(len(report.signals), 2)
                signal_names = [s.name for s in report.signals]
                self.assertNotIn("memory_frozen", signal_names)
            os.unlink(f.name)

    def test_report_json_serializable(self):
        with patch("zombie_detector._is_alive", return_value=False):
            report = zombie_check(
                pid=999, output_path="/tmp/x", expected_interval=15.0,
            )
            # Should not raise
            data = asdict(report)
            json.dumps(data)  # must be JSON-serializable

    def test_elapsed_seconds_populated(self):
        with patch("zombie_detector._is_alive", return_value=True), \
             patch("zombie_detector._process_cpu_seconds", return_value=10.0), \
             patch("zombie_detector._process_uptime_seconds", return_value=100.0), \
             patch("zombie_detector._process_rss_kb", side_effect=[100, 200, 300]):
            report = zombie_check(
                pid=1234,
                output_path="/tmp/nonexistent_zzz",
                expected_interval=15.0,
                samples=3,
                sample_interval=0.01,
            )
            self.assertGreater(report.elapsed_seconds, 0.0)


class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def test_file_age_at_exact_threshold(self):
        """File just under threshold age should not trigger (strict >)."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x")
            f.flush()
            # Set age to just under the threshold (59s vs 60s threshold)
            # to avoid timing jitter between utime and the check
            threshold_age = 59.0  # interval=15 * multiplier=4 = 60s
            old_time = time.time() - threshold_age
            os.utime(f.name, (old_time, old_time))
            sig = check_stale_output(f.name, expected_interval=15.0, multiplier=4.0)
            # Under threshold → should not trigger
            self.assertFalse(sig.triggered)
            os.unlink(f.name)

    def test_file_age_just_over_threshold(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x")
            f.flush()
            old_time = time.time() - 61.0
            os.utime(f.name, (old_time, old_time))
            sig = check_stale_output(f.name, expected_interval=15.0, multiplier=4.0)
            self.assertTrue(sig.triggered)
            os.unlink(f.name)

    @patch("zombie_detector._process_cpu_seconds", return_value=0.01)
    @patch("zombie_detector._process_uptime_seconds", return_value=1.0)
    def test_cpu_ratio_at_exact_threshold(self, mock_uptime, mock_cpu):
        # ratio = 0.01 / 1.0 = 0.01, min_cpu_ratio = 0.01
        # 0.01 < 0.01 is False → not triggered
        sig = check_cpu_starvation(1234, min_cpu_ratio=0.01)
        self.assertFalse(sig.triggered)

    @patch("zombie_detector._process_cpu_seconds", return_value=0.009)
    @patch("zombie_detector._process_uptime_seconds", return_value=1.0)
    def test_cpu_ratio_just_under_threshold(self, mock_uptime, mock_cpu):
        sig = check_cpu_starvation(1234, min_cpu_ratio=0.01)
        self.assertTrue(sig.triggered)


if __name__ == "__main__":
    unittest.main()
