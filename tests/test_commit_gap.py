"""Tests for iamai/commit_gap.py — gap measurement, severity tiers, and log parsing."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.commit_gap import (  # noqa: E402
    GapReport,
    STALL_THRESHOLD,
    WARN_THRESHOLD,
    gap_from_log,
    measure_gap,
)


class TestMeasureGapHealthy:
    """Gaps well within the warn threshold are healthy."""

    def test_zero_gap(self):
        now = 1_700_000_000.0
        report = measure_gap(now, now=now)
        assert report.severity == "healthy"
        assert report.gap_seconds == 0.0
        assert not report.needs_restart
        assert report.is_healthy

    def test_small_gap(self):
        now = 1_700_000_000.0
        report = measure_gap(now - 300, now=now)
        assert report.severity == "healthy"
        assert report.gap_seconds == 300.0
        assert not report.needs_restart

    def test_just_under_warn(self):
        now = 1_700_000_000.0
        report = measure_gap(now - (WARN_THRESHOLD - 1), now=now)
        assert report.severity == "healthy"

    def test_future_commit_clamped_to_zero(self):
        """A commit timestamp in the future should produce gap=0."""
        now = 1_700_000_000.0
        report = measure_gap(now + 1000, now=now)
        assert report.gap_seconds == 0.0
        assert report.severity == "healthy"


class TestMeasureGapWarn:
    """Gaps between warn and stall thresholds are warn."""

    def test_at_warn_threshold(self):
        now = 1_700_000_000.0
        report = measure_gap(now - WARN_THRESHOLD, now=now)
        assert report.severity == "warn"
        assert not report.needs_restart

    def test_mid_range(self):
        now = 1_700_000_000.0
        mid = (WARN_THRESHOLD + STALL_THRESHOLD) / 2
        report = measure_gap(now - mid, now=now)
        assert report.severity == "warn"

    def test_just_under_stall(self):
        now = 1_700_000_000.0
        report = measure_gap(now - (STALL_THRESHOLD - 1), now=now)
        assert report.severity == "warn"
        assert not report.needs_restart


class TestMeasureGapStall:
    """Gaps at or beyond stall threshold are stall."""

    def test_at_stall_threshold(self):
        now = 1_700_000_000.0
        report = measure_gap(now - STALL_THRESHOLD, now=now)
        assert report.severity == "stall"
        assert report.needs_restart
        assert not report.is_healthy

    def test_well_beyond_stall(self):
        now = 1_700_000_000.0
        report = measure_gap(now - STALL_THRESHOLD * 5, now=now)
        assert report.severity == "stall"
        assert report.needs_restart

    def test_message_contains_seconds(self):
        now = 1_700_000_000.0
        report = measure_gap(now - 3600, now=now)
        assert "3600" in report.message


class TestCustomThresholds:
    """Callers can override thresholds for different writer cadences."""

    def test_tight_thresholds(self):
        now = 1_700_000_000.0
        report = measure_gap(now - 50, now=now,
                             warn_threshold=30, stall_threshold=60)
        assert report.severity == "warn"

    def test_loose_thresholds(self):
        now = 1_700_000_000.0
        report = measure_gap(now - 300, now=now,
                             warn_threshold=600, stall_threshold=1200)
        assert report.severity == "healthy"


class TestGapReportDataclass:
    """GapReport is frozen and serializable."""

    def test_frozen(self):
        report = measure_gap(1_700_000_000.0, now=1_700_000_000.0)
        with pytest.raises(AttributeError):
            report.severity = "panic"

    def test_as_dict(self):
        now = 1_700_000_000.0
        report = measure_gap(now - 100, now=now)
        d = report.as_dict()
        assert d["severity"] == "healthy"
        assert d["gap_seconds"] == 100.0
        assert d["needs_restart"] is False
        assert "message" in d

    def test_as_dict_rounds_gap(self):
        now = 1_700_000_000.0
        report = measure_gap(now - 99.123456, now=now)
        d = report.as_dict()
        assert d["gap_seconds"] == 99.1


class TestGapFromLog:
    """Parse commit timestamps from a git-log-style file."""

    def test_single_line(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log",
                                         delete=False) as f:
            f.write("2026-10-07T02:45:12+08:00  abc1234  some message\n")
            path = f.name
        try:
            # Use a "now" that is 60s after the log entry
            from datetime import datetime
            dt = datetime.fromisoformat("2026-10-07T02:45:12+08:00")
            report = gap_from_log(path, now=dt.timestamp() + 60)
            assert report.severity == "healthy"
            assert report.gap_seconds == 60.0
        finally:
            os.unlink(path)

    def test_multiple_lines_uses_last(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log",
                                         delete=False) as f:
            f.write("2026-10-07T01:00:00+08:00  aaa  old commit\n")
            f.write("2026-10-07T02:00:00+08:00  bbb  newer commit\n")
            f.write("2026-10-07T03:00:00+08:00  ccc  newest commit\n")
            path = f.name
        try:
            from datetime import datetime
            dt = datetime.fromisoformat("2026-10-07T03:00:00+08:00")
            report = gap_from_log(path, now=dt.timestamp() + 120)
            assert report.gap_seconds == 120.0
            assert report.severity == "healthy"
        finally:
            os.unlink(path)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log",
                                         delete=False) as f:
            path = f.name
        try:
            report = gap_from_log(path)
            assert report.severity == "stall"
            assert report.needs_restart
            assert "empty" in report.message
        finally:
            os.unlink(path)

    def test_unparseable_timestamp(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log",
                                         delete=False) as f:
            f.write("not-a-timestamp  abc  garbage\n")
            path = f.name
        try:
            report = gap_from_log(path)
            assert report.severity == "stall"
            assert "could not parse" in report.message
        finally:
            os.unlink(path)

    def test_blank_lines_skipped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log",
                                         delete=False) as f:
            f.write("\n\n2026-10-07T04:00:00+08:00  ddd  real\n\n")
            path = f.name
        try:
            from datetime import datetime
            dt = datetime.fromisoformat("2026-10-07T04:00:00+08:00")
            report = gap_from_log(path, now=dt.timestamp() + 30)
            assert report.gap_seconds == 30.0
        finally:
            os.unlink(path)
