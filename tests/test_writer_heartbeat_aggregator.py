"""Tests for writer_heartbeat_aggregator — composite health scoring."""

from __future__ import annotations

import math
import unittest
from datetime import datetime, timezone

from iamai.writer_heartbeat_aggregator import (
    HeartbeatReport,
    Signal,
    aggregate,
    build_default_report,
    cadence_signal,
    commit_freshness_signal,
    gap_trend_signal,
    is_healthy,
    needs_attention,
    silence_signal,
    stall_probe_signal,
    trend,
)


# ---------------------------------------------------------------------------
# Signal validation
# ---------------------------------------------------------------------------

class TestSignal(unittest.TestCase):
    """Signal dataclass validation."""

    def test_valid_signal(self) -> None:
        s = Signal("test", 0.5)
        self.assertEqual(s.name, "test")
        self.assertEqual(s.score, 0.5)
        self.assertEqual(s.weight, 1.0)
        self.assertFalse(s.stale)

    def test_score_below_zero_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Signal("bad", -0.1)

    def test_score_above_one_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Signal("bad", 1.1)

    def test_negative_weight_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Signal("bad", 0.5, weight=-1.0)

    def test_boundary_scores(self) -> None:
        self.assertEqual(Signal("lo", 0.0).score, 0.0)
        self.assertEqual(Signal("hi", 1.0).score, 1.0)

    def test_frozen(self) -> None:
        s = Signal("x", 0.5)
        with self.assertRaises(AttributeError):
            s.score = 0.9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Aggregate function
# ---------------------------------------------------------------------------

class TestAggregate(unittest.TestCase):
    """Core weighted-average aggregation."""

    def test_empty_signals_rejected(self) -> None:
        with self.assertRaises(ValueError):
            aggregate([])

    def test_single_perfect_signal(self) -> None:
        r = aggregate([Signal("a", 1.0)])
        self.assertAlmostEqual(r.composite, 1.0)
        self.assertEqual(r.verdict, "healthy")
        self.assertEqual(r.active_count, 1)
        self.assertEqual(r.stale_count, 0)

    def test_single_dead_signal(self) -> None:
        r = aggregate([Signal("a", 0.0)])
        self.assertAlmostEqual(r.composite, 0.0)
        self.assertEqual(r.verdict, "dead")

    def test_equal_weight_average(self) -> None:
        signals = [Signal("a", 0.4), Signal("b", 0.8)]
        r = aggregate(signals)
        self.assertAlmostEqual(r.composite, 0.6)
        self.assertEqual(r.verdict, "fair")

    def test_weighted_average(self) -> None:
        signals = [
            Signal("a", 1.0, weight=3.0),
            Signal("b", 0.0, weight=1.0),
        ]
        r = aggregate(signals)
        self.assertAlmostEqual(r.composite, 0.75)

    def test_all_stale_returns_unknown(self) -> None:
        signals = [
            Signal("a", 0.5, stale=True),
            Signal("b", 0.8, stale=True),
        ]
        r = aggregate(signals)
        self.assertAlmostEqual(r.composite, 0.0)
        self.assertEqual(r.verdict, "unknown")
        self.assertEqual(r.stale_count, 2)
        self.assertEqual(r.active_count, 0)

    def test_stale_signals_excluded(self) -> None:
        signals = [
            Signal("a", 1.0, weight=1.0),
            Signal("b", 0.0, weight=1.0, stale=True),
        ]
        r = aggregate(signals)
        self.assertAlmostEqual(r.composite, 1.0)
        self.assertEqual(r.active_count, 1)
        self.assertEqual(r.stale_count, 1)

    def test_zero_weight_signals(self) -> None:
        signals = [
            Signal("a", 1.0, weight=0.0),
            Signal("b", 0.5, weight=2.0),
        ]
        r = aggregate(signals)
        self.assertAlmostEqual(r.composite, 0.5)

    def test_all_zero_weights(self) -> None:
        signals = [
            Signal("a", 0.8, weight=0.0),
            Signal("b", 0.6, weight=0.0),
        ]
        r = aggregate(signals)
        self.assertAlmostEqual(r.composite, 0.0)

    def test_custom_timestamp(self) -> None:
        now = datetime(2026, 11, 18, 2, 0, 0, tzinfo=timezone.utc)
        r = aggregate([Signal("a", 0.9)], now=now)
        self.assertEqual(r.at, now.isoformat())

    def test_default_timestamp_is_recent(self) -> None:
        r = aggregate([Signal("a", 0.9)])
        ts = datetime.fromisoformat(r.at)
        delta = abs((datetime.now(timezone.utc) - ts).total_seconds())
        self.assertLess(delta, 5)

    def test_verdict_thresholds(self) -> None:
        cases = [
            (1.0, "healthy"),
            (0.80, "healthy"),
            (0.79, "fair"),
            (0.60, "fair"),
            (0.59, "warning"),
            (0.40, "warning"),
            (0.39, "critical"),
            (0.20, "critical"),
            (0.19, "dead"),
            (0.0, "dead"),
        ]
        for score, expected_verdict in cases:
            r = aggregate([Signal("x", score)])
            self.assertEqual(
                r.verdict, expected_verdict,
                f"score={score} should be {expected_verdict}, got {r.verdict}",
            )


# ---------------------------------------------------------------------------
# HeartbeatReport methods
# ---------------------------------------------------------------------------

class TestHeartbeatReport(unittest.TestCase):
    """Report helper methods."""

    def test_summary_contains_signal_names(self) -> None:
        signals = [Signal("cadence", 0.9), Signal("silence", 0.7)]
        r = aggregate(signals)
        s = r.summary()
        self.assertIn("cadence", s)
        self.assertIn("silence", s)
        self.assertIn(r.verdict, s)

    def test_weakest_signal(self) -> None:
        signals = [Signal("a", 0.9), Signal("b", 0.3), Signal("c", 0.7)]
        r = aggregate(signals)
        self.assertEqual(r.weakest().name, "b")  # type: ignore[union-attr]

    def test_strongest_signal(self) -> None:
        signals = [Signal("a", 0.9), Signal("b", 0.3), Signal("c", 0.7)]
        r = aggregate(signals)
        self.assertEqual(r.strongest().name, "a")  # type: ignore[union-attr]

    def test_weakest_empty(self) -> None:
        r = HeartbeatReport(0.0, "dead", [], 0, 0, "")
        self.assertIsNone(r.weakest())

    def test_strongest_empty(self) -> None:
        r = HeartbeatReport(0.0, "dead", [], 0, 0, "")
        self.assertIsNone(r.strongest())

    def test_to_dict(self) -> None:
        signals = [Signal("a", 0.5, weight=2.0, detail="test")]
        r = aggregate(signals)
        d = r.to_dict()
        self.assertIn("composite", d)
        self.assertIn("verdict", d)
        self.assertIn("signals", d)
        self.assertEqual(len(d["signals"]), 1)
        self.assertEqual(d["signals"][0]["name"], "a")
        self.assertEqual(d["signals"][0]["detail"], "test")

    def test_to_dict_rounds_scores(self) -> None:
        signals = [Signal("a", 1.0 / 3.0)]
        r = aggregate(signals)
        d = r.to_dict()
        # Should be rounded to 4 decimal places
        self.assertEqual(d["composite"], 0.3333)


# ---------------------------------------------------------------------------
# Signal builder: cadence
# ---------------------------------------------------------------------------

class TestCadenceSignal(unittest.TestCase):
    """cadence_signal builder."""

    def test_perfect_cadence(self) -> None:
        s = cadence_signal(15.0, 15.0)
        self.assertEqual(s.score, 1.0)
        self.assertEqual(s.name, "cadence")

    def test_faster_than_target(self) -> None:
        s = cadence_signal(10.0, 15.0)
        self.assertEqual(s.score, 1.0)

    def test_slight_slowdown(self) -> None:
        s = cadence_signal(20.0, 15.0)
        self.assertGreater(s.score, 0.5)
        self.assertLess(s.score, 1.0)

    def test_double_gap(self) -> None:
        s = cadence_signal(30.0, 15.0)
        self.assertGreater(s.score, 0.0)
        self.assertLessEqual(s.score, 0.7)

    def test_triple_gap(self) -> None:
        s = cadence_signal(45.0, 15.0)
        self.assertAlmostEqual(s.score, 0.3)

    def test_far_beyond(self) -> None:
        s = cadence_signal(120.0, 15.0)
        self.assertEqual(s.score, 0.0)

    def test_zero_target_is_stale(self) -> None:
        s = cadence_signal(15.0, 0.0)
        self.assertTrue(s.stale)

    def test_weight_propagated(self) -> None:
        s = cadence_signal(15.0, 15.0, weight=5.0)
        self.assertEqual(s.weight, 5.0)


# ---------------------------------------------------------------------------
# Signal builder: silence
# ---------------------------------------------------------------------------

class TestSilenceSignal(unittest.TestCase):
    """silence_signal builder."""

    def test_recent_stroke(self) -> None:
        s = silence_signal(0.0, 60.0)
        self.assertEqual(s.score, 1.0)

    def test_halfway(self) -> None:
        s = silence_signal(30.0, 60.0)
        self.assertAlmostEqual(s.score, 0.5)

    def test_at_threshold(self) -> None:
        s = silence_signal(60.0, 60.0)
        self.assertAlmostEqual(s.score, 0.0)

    def test_beyond_threshold(self) -> None:
        s = silence_signal(120.0, 60.0)
        self.assertEqual(s.score, 0.0)

    def test_zero_threshold_is_stale(self) -> None:
        s = silence_signal(10.0, 0.0)
        self.assertTrue(s.stale)


# ---------------------------------------------------------------------------
# Signal builder: stall_probe
# ---------------------------------------------------------------------------

class TestStallProbeSignal(unittest.TestCase):
    """stall_probe_signal builder."""

    def test_alive(self) -> None:
        s = stall_probe_signal(True)
        self.assertEqual(s.score, 1.0)
        self.assertEqual(s.detail, "alive")

    def test_dead(self) -> None:
        s = stall_probe_signal(False)
        self.assertEqual(s.score, 0.0)
        self.assertEqual(s.detail, "dead")

    def test_custom_weight(self) -> None:
        s = stall_probe_signal(True, weight=5.0)
        self.assertEqual(s.weight, 5.0)


# ---------------------------------------------------------------------------
# Signal builder: gap_trend
# ---------------------------------------------------------------------------

class TestGapTrendSignal(unittest.TestCase):
    """gap_trend_signal builder."""

    def test_negative_slope_perfect(self) -> None:
        s = gap_trend_signal(-5.0)
        self.assertEqual(s.score, 1.0)

    def test_zero_slope(self) -> None:
        s = gap_trend_signal(0.0)
        self.assertAlmostEqual(s.score, 0.8)

    def test_positive_slope_degrades(self) -> None:
        s = gap_trend_signal(5.0, max_slope=10.0)
        self.assertGreater(s.score, 0.0)
        self.assertLess(s.score, 0.8)

    def test_max_slope(self) -> None:
        s = gap_trend_signal(10.0, max_slope=10.0)
        self.assertAlmostEqual(s.score, 0.0)

    def test_beyond_max_slope(self) -> None:
        s = gap_trend_signal(20.0, max_slope=10.0)
        self.assertEqual(s.score, 0.0)

    def test_zero_max_slope_is_stale(self) -> None:
        s = gap_trend_signal(0.0, max_slope=0.0)
        self.assertTrue(s.stale)


# ---------------------------------------------------------------------------
# Signal builder: commit_freshness
# ---------------------------------------------------------------------------

class TestCommitFreshnessSignal(unittest.TestCase):
    """commit_freshness_signal builder."""

    def test_just_committed(self) -> None:
        s = commit_freshness_signal(0.0, 600.0)
        self.assertEqual(s.score, 1.0)

    def test_one_interval_old(self) -> None:
        s = commit_freshness_signal(600.0, 600.0)
        # 600 / 1800 = 1/3, so score = 1 - 1/3 ≈ 0.667
        self.assertAlmostEqual(s.score, 2.0 / 3.0, places=2)

    def test_three_intervals_old(self) -> None:
        s = commit_freshness_signal(1800.0, 600.0)
        self.assertAlmostEqual(s.score, 0.0)

    def test_beyond_max(self) -> None:
        s = commit_freshness_signal(3600.0, 600.0)
        self.assertEqual(s.score, 0.0)

    def test_zero_target_is_stale(self) -> None:
        s = commit_freshness_signal(100.0, 0.0)
        self.assertTrue(s.stale)


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

class TestTrend(unittest.TestCase):
    """trend() comparing two reports."""

    def _make_report(
        self, score: float, signals: list[Signal] | None = None
    ) -> HeartbeatReport:
        verdict = "healthy" if score >= 0.8 else "warning"
        return HeartbeatReport(
            score, verdict, signals or [], 0, 0, ""
        )

    def test_improving(self) -> None:
        old = self._make_report(0.4)
        new = self._make_report(0.8)
        t = trend(old, new)
        self.assertEqual(t["direction"], "improving")
        self.assertAlmostEqual(t["delta"], 0.4)
        self.assertTrue(t["verdict_change"])

    def test_declining(self) -> None:
        old = self._make_report(0.8)
        new = self._make_report(0.4)
        t = trend(old, new)
        self.assertEqual(t["direction"], "declining")
        self.assertTrue(t["verdict_change"])

    def test_stable(self) -> None:
        old = self._make_report(0.75)
        new = self._make_report(0.77)
        t = trend(old, new)
        self.assertEqual(t["direction"], "stable")
        self.assertFalse(t["verdict_change"])

    def test_per_signal_improvement(self) -> None:
        old_sigs = [Signal("a", 0.3), Signal("b", 0.9)]
        new_sigs = [Signal("a", 0.8), Signal("b", 0.85)]
        old = self._make_report(0.5, old_sigs)
        new = self._make_report(0.8, new_sigs)
        t = trend(old, new)
        self.assertIn("a", t["improving_signals"])
        self.assertIn("b", t["declining_signals"])

    def test_no_matching_signals(self) -> None:
        old_sigs = [Signal("x", 0.5)]
        new_sigs = [Signal("y", 0.7)]
        old = self._make_report(0.5, old_sigs)
        new = self._make_report(0.7, new_sigs)
        t = trend(old, new)
        self.assertEqual(t["improving_signals"], [])
        self.assertEqual(t["declining_signals"], [])


# ---------------------------------------------------------------------------
# Quick-check helpers
# ---------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):
    """is_healthy and needs_attention."""

    def test_is_healthy_true(self) -> None:
        r = HeartbeatReport(0.9, "healthy", [], 0, 1, "")
        self.assertTrue(is_healthy(r))

    def test_is_healthy_false(self) -> None:
        r = HeartbeatReport(0.5, "warning", [], 0, 1, "")
        self.assertFalse(is_healthy(r))

    def test_needs_attention_warning(self) -> None:
        r = HeartbeatReport(0.5, "warning", [], 0, 1, "")
        self.assertTrue(needs_attention(r))

    def test_needs_attention_critical(self) -> None:
        r = HeartbeatReport(0.3, "critical", [], 0, 1, "")
        self.assertTrue(needs_attention(r))

    def test_needs_attention_dead(self) -> None:
        r = HeartbeatReport(0.0, "dead", [], 0, 1, "")
        self.assertTrue(needs_attention(r))

    def test_needs_attention_unknown(self) -> None:
        r = HeartbeatReport(0.0, "unknown", [], 1, 0, "")
        self.assertTrue(needs_attention(r))

    def test_needs_attention_healthy(self) -> None:
        r = HeartbeatReport(0.9, "healthy", [], 0, 1, "")
        self.assertFalse(needs_attention(r))

    def test_needs_attention_fair(self) -> None:
        r = HeartbeatReport(0.7, "fair", [], 0, 1, "")
        self.assertFalse(needs_attention(r))


# ---------------------------------------------------------------------------
# build_default_report convenience
# ---------------------------------------------------------------------------

class TestBuildDefaultReport(unittest.TestCase):
    """build_default_report integration."""

    def test_default_is_healthy(self) -> None:
        r = build_default_report()
        self.assertEqual(r.verdict, "healthy")
        self.assertEqual(r.active_count, 5)
        self.assertEqual(r.stale_count, 0)

    def test_dead_writer(self) -> None:
        r = build_default_report(
            actual_stroke_gap=300.0,
            seconds_since_last=300.0,
            is_alive=False,
            gap_slope=15.0,
            seconds_since_commit=3600.0,
        )
        self.assertIn(r.verdict, ("critical", "dead"))
        self.assertFalse(is_healthy(r))
        self.assertTrue(needs_attention(r))

    def test_mild_degradation(self) -> None:
        r = build_default_report(
            actual_stroke_gap=25.0,
            seconds_since_last=30.0,
            gap_slope=2.0,
        )
        self.assertIn(r.verdict, ("fair", "warning"))

    def test_custom_timestamp(self) -> None:
        now = datetime(2026, 11, 18, 2, 0, 0, tzinfo=timezone.utc)
        r = build_default_report(now=now)
        self.assertEqual(r.at, now.isoformat())

    def test_all_signals_present(self) -> None:
        r = build_default_report()
        names = {s.name for s in r.signals}
        expected = {"cadence", "silence", "stall_probe", "gap_trend", "commit_freshness"}
        self.assertEqual(names, expected)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    """Boundary and edge conditions."""

    def test_many_signals(self) -> None:
        signals = [Signal(f"s{i}", 0.5) for i in range(100)]
        r = aggregate(signals)
        self.assertAlmostEqual(r.composite, 0.5)
        self.assertEqual(r.active_count, 100)

    def test_mixed_stale_and_active(self) -> None:
        signals = [
            Signal("a", 1.0, weight=1.0),
            Signal("b", 0.0, weight=1.0, stale=True),
            Signal("c", 0.5, weight=2.0),
            Signal("d", 0.8, weight=1.0, stale=True),
        ]
        r = aggregate(signals)
        # Active: a(1.0*1) + c(0.5*2) = 2.0, total weight = 3.0
        self.assertAlmostEqual(r.composite, 2.0 / 3.0)
        self.assertEqual(r.active_count, 2)
        self.assertEqual(r.stale_count, 2)

    def test_score_clamped_above_one(self) -> None:
        # Floating point: 0.7 * 1/3 ≈ 0.2333... but sum shouldn't exceed 1.0
        signals = [Signal("a", 1.0, weight=1e10)]
        r = aggregate(signals)
        self.assertLessEqual(r.composite, 1.0)

    def test_summary_no_signals(self) -> None:
        r = HeartbeatReport(0.0, "dead", [], 0, 0, "")
        s = r.summary()
        self.assertIn("no signals", s)


if __name__ == "__main__":
    unittest.main()
