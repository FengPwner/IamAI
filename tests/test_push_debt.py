"""tests for push_debt — quantifying the cost of unpushed commits.

covers:
  - severity classification boundaries
  - trend detection (increasing, stable, draining, unknown)
  - snapshot serialization round-trip
  - measure_debt with no unpushed commits
  - debt score computation from count × mean_age
  - edge cases: empty log, malformed JSON, zero ages
  - format_report output structure

no external services needed. git calls are mocked where used.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from iamai.push_debt import (
    DebtSnapshot,
    Severity,
    Trend,
    compute_severity,
    compute_trend,
    format_report,
    load_snapshots,
    measure_debt,
    record_snapshot,
)


# ---------------------------------------------------------------------------
# severity classification
# ---------------------------------------------------------------------------


class TestComputeSeverity:
    """classify debt scores into severity buckets."""

    def test_zero_is_low(self):
        assert compute_severity(0) == Severity.LOW

    def test_boundary_low(self):
        assert compute_severity(49.9) == Severity.LOW

    def test_boundary_medium(self):
        assert compute_severity(50) == Severity.MEDIUM

    def test_boundary_high(self):
        assert compute_severity(200) == Severity.HIGH

    def test_boundary_critical(self):
        assert compute_severity(1000) == Severity.CRITICAL

    def test_large_value(self):
        assert compute_severity(99999) == Severity.CRITICAL

    def test_just_below_high(self):
        assert compute_severity(199.9) == Severity.MEDIUM

    def test_just_below_critical(self):
        assert compute_severity(999.9) == Severity.HIGH


# ---------------------------------------------------------------------------
# trend detection
# ---------------------------------------------------------------------------


class TestComputeTrend:
    """detect whether debt is growing, stable, or draining."""

    def _snap(self, debt: float) -> DebtSnapshot:
        return DebtSnapshot(
            timestamp="2026-10-26T12:00:00+00:00",
            unpushed_count=10,
            oldest_age_hours=1.0,
            mean_age_hours=1.0,
            debt_score=debt,
            severity="LOW",
        )

    def test_empty_returns_unknown(self):
        assert compute_trend([]) == Trend.UNKNOWN

    def test_single_returns_unknown(self):
        assert compute_trend([self._snap(10)]) == Trend.UNKNOWN

    def test_stable(self):
        snaps = [self._snap(100)] * 6
        assert compute_trend(snaps) == Trend.STABLE

    def test_increasing(self):
        snaps = [self._snap(50), self._snap(50), self._snap(50),
                 self._snap(100), self._snap(110), self._snap(120)]
        assert compute_trend(snaps) == Trend.INCREASING

    def test_draining(self):
        snaps = [self._snap(200), self._snap(200), self._snap(200),
                 self._snap(100), self._snap(80), self._snap(60)]
        assert compute_trend(snaps) == Trend.DRAINING

    def test_window_limits_comparison(self):
        """only the last `window` snapshots are used."""
        snaps = [self._snap(999)] * 10 + [self._snap(10)] * 4
        # window=6 means last 6: [999,999,10,10,10,10] -> draining
        assert compute_trend(snaps, window=6) == Trend.DRAINING

    def test_zero_first_half(self):
        snaps = [self._snap(0), self._snap(0), self._snap(0),
                 self._snap(50), self._snap(60), self._snap(70)]
        assert compute_trend(snaps) == Trend.INCREASING

    def test_both_zero(self):
        snaps = [self._snap(0)] * 6
        assert compute_trend(snaps) == Trend.STABLE


# ---------------------------------------------------------------------------
# snapshot serialization
# ---------------------------------------------------------------------------


class TestSnapshotSerialization:
    """DebtSnapshot round-trips through JSON correctly."""

    def test_to_dict(self):
        snap = DebtSnapshot(
            timestamp="2026-10-26T21:00:00+08:00",
            unpushed_count=70,
            oldest_age_hours=48.5,
            mean_age_hours=24.3,
            debt_score=1701.0,
            severity="CRITICAL",
            trend="INCREASING",
        )
        from dataclasses import asdict
        d = asdict(snap)
        assert d["unpushed_count"] == 70
        assert d["severity"] == "CRITICAL"
        assert d["trend"] == "INCREASING"

    def test_from_dict(self):
        d = {
            "timestamp": "2026-10-26T21:00:00+08:00",
            "unpushed_count": 5,
            "oldest_age_hours": 2.0,
            "mean_age_hours": 1.0,
            "debt_score": 5.0,
            "severity": "LOW",
            "trend": "UNKNOWN",
        }
        snap = DebtSnapshot(**d)
        assert snap.unpushed_count == 5
        assert snap.severity == "LOW"


# ---------------------------------------------------------------------------
# record and load snapshots
# ---------------------------------------------------------------------------


class TestRecordAndLoad:
    """snapshots persist to JSONL and reload correctly."""

    def test_record_appends(self, tmp_path, monkeypatch):
        import iamai.push_debt as mod
        log_file = tmp_path / "push_debt.jsonl"
        monkeypatch.setattr(mod, "DEBT_LOG", log_file)
        monkeypatch.setattr(mod, "DATA_DIR", tmp_path)

        snap1 = DebtSnapshot("2026-10-26T12:00:00+00:00", 10, 5.0, 3.0,
                             30.0, "LOW", "UNKNOWN")
        snap2 = DebtSnapshot("2026-10-26T12:10:00+00:00", 20, 10.0, 6.0,
                             120.0, "MEDIUM", "INCREASING")

        record_snapshot(snap1)
        record_snapshot(snap2)

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_load_snapshots(self, tmp_path, monkeypatch):
        import iamai.push_debt as mod
        log_file = tmp_path / "push_debt.jsonl"
        monkeypatch.setattr(mod, "DEBT_LOG", log_file)

        # write two snapshots
        entries = [
            {"timestamp": "t1", "unpushed_count": 5, "oldest_age_hours": 1.0,
             "mean_age_hours": 1.0, "debt_score": 5.0, "severity": "LOW",
             "trend": "UNKNOWN"},
            {"timestamp": "t2", "unpushed_count": 10, "oldest_age_hours": 2.0,
             "mean_age_hours": 1.5, "debt_score": 15.0, "severity": "LOW",
             "trend": "UNKNOWN"},
        ]
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

        loaded = load_snapshots()
        assert len(loaded) == 2
        assert loaded[0].unpushed_count == 5
        assert loaded[1].debt_score == 15.0

    def test_load_with_limit(self, tmp_path, monkeypatch):
        import iamai.push_debt as mod
        log_file = tmp_path / "push_debt.jsonl"
        monkeypatch.setattr(mod, "DEBT_LOG", log_file)

        entries = [
            {"timestamp": f"t{i}", "unpushed_count": i, "oldest_age_hours": 1.0,
             "mean_age_hours": 1.0, "debt_score": float(i), "severity": "LOW",
             "trend": "UNKNOWN"}
            for i in range(10)
        ]
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

        loaded = load_snapshots(limit=3)
        assert len(loaded) == 3
        # should be the last 3
        assert loaded[0].unpushed_count == 7

    def test_load_nonexistent(self, tmp_path, monkeypatch):
        import iamai.push_debt as mod
        monkeypatch.setattr(mod, "DEBT_LOG", tmp_path / "no_such_file.jsonl")
        assert load_snapshots() == []

    def test_load_skips_malformed(self, tmp_path, monkeypatch):
        import iamai.push_debt as mod
        log_file = tmp_path / "push_debt.jsonl"
        monkeypatch.setattr(mod, "DEBT_LOG", log_file)

        good = {"timestamp": "t1", "unpushed_count": 5, "oldest_age_hours": 1.0,
                "mean_age_hours": 1.0, "debt_score": 5.0, "severity": "LOW",
                "trend": "UNKNOWN"}
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(
            json.dumps(good) + "\n"
            "NOT JSON\n"
            '{"incomplete": true}\n'
        )
        loaded = load_snapshots()
        assert len(loaded) == 1
        assert loaded[0].unpushed_count == 5


# ---------------------------------------------------------------------------
# measure_debt with mocked git
# ---------------------------------------------------------------------------


class TestMeasureDebt:
    """measure_debt integrates git output into a snapshot."""

    @patch("iamai.push_debt._run_git")
    @patch("iamai.push_debt.load_snapshots")
    def test_no_unpushed(self, mock_load, mock_git):
        mock_git.return_value = ""
        mock_load.return_value = []

        snap = measure_debt()
        assert snap.unpushed_count == 0
        assert snap.debt_score == 0.0
        assert snap.severity == Severity.LOW.value

    @patch("iamai.push_debt._run_git")
    @patch("iamai.push_debt.load_snapshots")
    def test_with_unpushed(self, mock_load, mock_git):
        mock_load.return_value = []

        # simulate 3 unpushed commits with timestamps
        now = datetime.now(timezone.utc)
        ages_hours = [1.0, 2.0, 3.0]  # mean = 2.0

        timestamps = []
        for h in ages_hours:
            from datetime import timedelta
            ts = now - timedelta(hours=h)
            timestamps.append(ts.isoformat())

        def side_effect(*args):
            if "--format=%H" in args:
                return "aaa\nbbb\nccc"
            if "--format=%aI" in args:
                return "\n".join(timestamps)
            return ""

        mock_git.side_effect = side_effect

        snap = measure_debt()
        assert snap.unpushed_count == 3
        assert abs(snap.mean_age_hours - 2.0) < 0.1
        assert abs(snap.debt_score - 6.0) < 0.5
        assert snap.severity == Severity.LOW.value

    @patch("iamai.push_debt._run_git")
    @patch("iamai.push_debt.load_snapshots")
    def test_high_debt_scenario(self, mock_load, mock_git):
        mock_load.return_value = []

        now = datetime.now(timezone.utc)
        from datetime import timedelta

        # 70 commits, mean age ~30 hours -> debt = 2100 -> CRITICAL
        count = 70
        timestamps = []
        for i in range(count):
            age_h = 25 + (i * 0.5)  # 25 to 59.5 hours
            ts = now - timedelta(hours=age_h)
            timestamps.append(ts.isoformat())

        def side_effect(*args):
            if "--format=%H" in args:
                return "\n".join(f"hash{i}" for i in range(count))
            if "--format=%aI" in args:
                return "\n".join(timestamps)
            return ""

        mock_git.side_effect = side_effect

        snap = measure_debt()
        assert snap.unpushed_count == 70
        assert snap.severity == Severity.CRITICAL.value
        assert snap.debt_score > 1000


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


class TestFormatReport:
    """human-readable report contains expected fields."""

    def test_basic_report(self):
        snap = DebtSnapshot(
            timestamp="2026-10-26T21:00:00+08:00",
            unpushed_count=70,
            oldest_age_hours=48.5,
            mean_age_hours=24.3,
            debt_score=1701.0,
            severity="CRITICAL",
            trend="INCREASING",
        )
        report = format_report(snap)
        assert "70 commits" in report
        assert "CRITICAL" in report
        assert "48.5" in report
        assert "INCREASING" in report

    def test_critical_warning(self):
        snap = DebtSnapshot(
            timestamp="t", unpushed_count=100, oldest_age_hours=72.0,
            mean_age_hours=36.0, debt_score=3600.0,
            severity="CRITICAL", trend="INCREASING",
        )
        report = format_report(snap)
        assert "WARNING CRITICAL" in report

    def test_high_warning(self):
        snap = DebtSnapshot(
            timestamp="t", unpushed_count=50, oldest_age_hours=20.0,
            mean_age_hours=10.0, debt_score=500.0,
            severity="HIGH", trend="STABLE",
        )
        report = format_report(snap)
        assert "WARNING HIGH" in report

    def test_low_no_warning(self):
        snap = DebtSnapshot(
            timestamp="t", unpushed_count=2, oldest_age_hours=0.5,
            mean_age_hours=0.3, debt_score=0.6,
            severity="LOW", trend="UNKNOWN",
        )
        report = format_report(snap)
        assert "WARNING" not in report


# ---------------------------------------------------------------------------
# integration: compute_severity boundaries are consistent
# ---------------------------------------------------------------------------


class TestSeverityConsistency:
    """severity boundaries don't overlap or have gaps."""

    def test_all_positive_values_have_severity(self):
        for v in [0, 1, 49, 50, 51, 199, 200, 201, 999, 1000, 10000]:
            sev = compute_severity(float(v))
            assert isinstance(sev, Severity)

    def test_ordering(self):
        severities = [
            compute_severity(0),
            compute_severity(50),
            compute_severity(200),
            compute_severity(1000),
        ]
        # LOW < MEDIUM < HIGH < CRITICAL in definition order
        order = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        assert severities == order
