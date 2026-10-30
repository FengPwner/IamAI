"""Tests for iamai.repo_circadian_rhythm.

Covers: CircadianReport dataclass, hourly binning, peak/trough detection,
amplitude, rest_depth, phase_alignment, regularity, composite scoring,
state classification, and end-to-end circadian_report().
"""

from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from unittest import mock

import pytest

from iamai.repo_circadian_rhythm import (
    CircadianReport,
    DEFAULT_WORK_END,
    DEFAULT_WORK_START,
    _amplitude,
    _build_daily_hourly,
    _build_hourly,
    _classify_state,
    _git_log,
    _peak_and_trough,
    _phase_alignment,
    _regularity,
    _rest_depth,
    _rhythm_score,
    circadian_report,
    circadian_summary,
)


# ---------------------------------------------------------------------------
# CircadianReport dataclass
# ---------------------------------------------------------------------------

class TestCircadianReport:
    def test_defaults(self):
        r = CircadianReport()
        assert len(r.hourly_distribution) == 24
        assert all(v == 0 for v in r.hourly_distribution)
        assert r.peak_hour == 0
        assert r.trough_hour == 0
        assert r.amplitude == 0.0
        assert r.rest_depth == 0.0
        assert r.phase_alignment == 0.0
        assert r.regularity_score == 0.0
        assert r.rhythm_score == 0.0
        assert r.rhythm_state == "dormant"
        assert r.total_commits == 0
        assert r.active_days == 0

    def test_custom_values(self):
        r = CircadianReport(
            peak_hour=14,
            trough_hour=3,
            amplitude=3.5,
            rhythm_score=72.1,
            rhythm_state="rhythmic",
            total_commits=500,
            active_days=30,
        )
        assert r.peak_hour == 14
        assert r.trough_hour == 3
        assert r.amplitude == 3.5
        assert r.rhythm_score == 72.1
        assert r.rhythm_state == "rhythmic"
        assert r.total_commits == 500

    def test_work_hours_defaults(self):
        r = CircadianReport()
        assert r.work_start == DEFAULT_WORK_START
        assert r.work_end == DEFAULT_WORK_END


# ---------------------------------------------------------------------------
# _build_hourly
# ---------------------------------------------------------------------------

class TestBuildHourly:
    def _ts(self, hour: int, day_offset: int = 0) -> int:
        """Create a unix timestamp for a given UTC hour and day offset."""
        base = datetime(2026, 10, 20, 0, 0, 0, tzinfo=timezone.utc)
        dt = base + timedelta(days=day_offset, hours=hour)
        return int(dt.timestamp())

    def test_empty(self):
        assert _build_hourly([]) == [0] * 24

    def test_single_commit(self):
        ts = self._ts(14)
        hourly = _build_hourly([ts])
        assert hourly[14] == 1
        assert sum(hourly) == 1

    def test_multiple_same_hour(self):
        ts = [self._ts(10)] * 5
        hourly = _build_hourly(ts)
        assert hourly[10] == 5

    def test_tz_offset(self):
        # UTC 22:00 with +8 offset → local 06:00
        ts = self._ts(22)
        hourly = _build_hourly([ts], tz_offset_hours=8)
        assert hourly[6] == 1

    def test_tz_offset_wrap(self):
        # UTC 20:00 with +8 offset → local 04:00 (wraps past midnight)
        ts = self._ts(20)
        hourly = _build_hourly([ts], tz_offset_hours=8)
        assert hourly[4] == 1

    def test_all_hours_covered(self):
        ts = [self._ts(h) for h in range(24)]
        hourly = _build_hourly(ts)
        assert all(v == 1 for v in hourly)

    def test_distribution(self):
        # 5 at hour 9, 3 at hour 15, 1 at hour 22
        ts = [self._ts(9)] * 5 + [self._ts(15)] * 3 + [self._ts(22)]
        hourly = _build_hourly(ts)
        assert hourly[9] == 5
        assert hourly[15] == 3
        assert hourly[22] == 1
        assert sum(hourly) == 9


# ---------------------------------------------------------------------------
# _build_daily_hourly
# ---------------------------------------------------------------------------

class TestBuildDailyHourly:
    def _ts(self, hour: int, day: int) -> int:
        base = datetime(2026, 10, 20, 0, 0, 0, tzinfo=timezone.utc)
        dt = base + timedelta(days=day, hours=hour)
        return int(dt.timestamp())

    def test_empty(self):
        assert _build_daily_hourly([]) == {}

    def test_single_day(self):
        ts = [self._ts(10, 0), self._ts(14, 0)]
        daily = _build_daily_hourly(ts)
        assert len(daily) == 1
        day_key = list(daily.keys())[0]
        assert daily[day_key][10] == 1
        assert daily[day_key][14] == 1

    def test_multiple_days(self):
        ts = [self._ts(10, 0), self._ts(10, 1), self._ts(14, 2)]
        daily = _build_daily_hourly(ts)
        assert len(daily) == 3


# ---------------------------------------------------------------------------
# _peak_and_trough
# ---------------------------------------------------------------------------

class TestPeakAndTrough:
    def test_basic(self):
        hourly = [1] * 24
        hourly[14] = 10
        hourly[3] = 0
        peak, trough = _peak_and_trough(hourly)
        assert peak == 14
        assert trough == 3

    def test_uniform(self):
        hourly = [5] * 24
        peak, trough = _peak_and_trough(hourly)
        # all equal → peak and trough both 0 (first index)
        assert peak == 0
        assert trough == 0

    def test_single_spike(self):
        hourly = [1] * 24
        hourly[18] = 100
        peak, trough = _peak_and_trough(hourly)
        assert peak == 18

    def test_all_zeros(self):
        hourly = [0] * 24
        peak, trough = _peak_and_trough(hourly)
        assert peak == 0
        assert trough == 0


# ---------------------------------------------------------------------------
# _amplitude
# ---------------------------------------------------------------------------

class TestAmplitude:
    def test_uniform(self):
        hourly = [10] * 24
        assert _amplitude(hourly) == 1.0

    def test_spike(self):
        hourly = [1] * 24
        hourly[12] = 100
        # mean = (23 + 100) / 24 = 123/24 ≈ 5.125
        # peak/mean = 100 / 5.125 ≈ 19.5 → capped at 10.0
        assert _amplitude(hourly) == 10.0

    def test_moderate(self):
        hourly = [2] * 24
        hourly[10] = 20
        # mean = (23*2 + 20) / 24 = 66/24 = 2.75
        # peak/mean = 20/2.75 ≈ 7.27
        result = _amplitude(hourly)
        assert 7.0 < result < 7.5

    def test_all_zeros(self):
        assert _amplitude([0] * 24) == 0.0

    def test_single_hour_active(self):
        hourly = [0] * 24
        hourly[15] = 48
        # mean = 48/24 = 2.0; 48/2 = 24 → capped at 10.0
        assert _amplitude(hourly) == 10.0


# ---------------------------------------------------------------------------
# _rest_depth
# ---------------------------------------------------------------------------

class TestRestDepth:
    def test_all_active(self):
        hourly = [5] * 24
        assert _rest_depth(hourly) == 0.0

    def test_all_rest(self):
        hourly = [0] * 24
        assert _rest_depth(hourly) == 1.0

    def test_half_rest(self):
        hourly = [0] * 12 + [3] * 12
        result = _rest_depth(hourly)
        assert abs(result - 0.5) < 0.01

    def test_empty(self):
        assert _rest_depth([]) == 0.0

    def test_single_active_hour(self):
        hourly = [0] * 24
        hourly[10] = 1
        result = _rest_depth(hourly)
        assert abs(result - 23 / 24) < 0.01


# ---------------------------------------------------------------------------
# _phase_alignment
# ---------------------------------------------------------------------------

class TestPhaseAlignment:
    def test_all_in_work_hours(self):
        hourly = [0] * 24
        for h in range(8, 22):
            hourly[h] = 10
        result = _phase_alignment(hourly, 8, 22)
        assert result == 100.0

    def test_all_outside_work_hours(self):
        hourly = [0] * 24
        for h in range(0, 8):
            hourly[h] = 10
        for h in range(22, 24):
            hourly[h] = 10
        result = _phase_alignment(hourly, 8, 22)
        assert result == 0.0

    def test_random_baseline(self):
        # Uniform distribution: should be near 0 alignment
        hourly = [10] * 24
        result = _phase_alignment(hourly, 8, 22)
        assert result < 5.0  # near zero since ~58% is baseline

    def test_mostly_in_work_hours(self):
        hourly = [0] * 24
        for h in range(8, 22):
            hourly[h] = 10
        hourly[2] = 5  # a few night commits
        result = _phase_alignment(hourly, 8, 22)
        assert result > 80.0

    def test_empty(self):
        assert _phase_alignment([0] * 24, 8, 22) == 0.0

    def test_night_shift(self):
        hourly = [0] * 24
        for h in range(0, 8):
            hourly[h] = 10
        result = _phase_alignment(hourly, 8, 22)
        assert result == 0.0


# ---------------------------------------------------------------------------
# _regularity
# ---------------------------------------------------------------------------

class TestRegularity:
    def _make_daily(self, days: int, peak_hour: int) -> dict:
        """Create daily data with consistent peak."""
        daily = {}
        base = datetime(2026, 10, 1)
        for d in range(days):
            date_str = (base + timedelta(days=d)).strftime("%Y-%m-%d")
            hourly = [1] * 24
            hourly[peak_hour] = 50
            daily[date_str] = hourly
        return daily

    def test_fewer_than_7_days(self):
        daily = self._make_daily(5, peak_hour=10)
        assert _regularity(daily) == 0.0

    def test_perfect_regularity(self):
        daily = self._make_daily(10, peak_hour=14)
        result = _regularity(daily)
        assert result == 100.0

    def test_no_regularity(self):
        # Alternating peaks 12 hours apart
        daily = {}
        base = datetime(2026, 10, 1)
        for d in range(10):
            date_str = (base + timedelta(days=d)).strftime("%Y-%m-%d")
            hourly = [1] * 24
            hourly[10 if d % 2 == 0 else 22] = 50
            daily[date_str] = hourly
        result = _regularity(daily)
        assert result == 0.0

    def test_partial_regularity(self):
        daily = self._make_daily(10, peak_hour=10)
        # Shift peak on 3 days
        base = datetime(2026, 10, 1)
        for d in [2, 5, 8]:
            date_str = (base + timedelta(days=d)).strftime("%Y-%m-%d")
            daily[date_str] = [1] * 24
            daily[date_str][11] = 50  # within 2h of 10 → still matches
        result = _regularity(daily)
        assert result > 50.0

    def test_empty(self):
        assert _regularity({}) == 0.0

    def test_skipped_days(self):
        # Days with zero commits should be excluded from pair counting
        daily = {}
        base = datetime(2026, 10, 1)
        for d in range(10):
            date_str = (base + timedelta(days=d)).strftime("%Y-%m-%d")
            if d == 5:
                daily[date_str] = [0] * 24  # empty day
            else:
                hourly = [1] * 24
                hourly[14] = 50
                daily[date_str] = hourly
        result = _regularity(daily)
        assert result > 80.0


# ---------------------------------------------------------------------------
# _rhythm_score
# ---------------------------------------------------------------------------

class TestRhythmScore:
    def test_perfect(self):
        # amplitude=5.0 → amp_norm=100, rest=1.0, alignment=100, regularity=100
        score = _rhythm_score(5.0, 1.0, 100.0, 100.0)
        assert score == 100.0

    def test_zero_all(self):
        score = _rhythm_score(0.0, 0.0, 0.0, 0.0)
        assert score == 0.0

    def test_moderate(self):
        score = _rhythm_score(2.5, 0.3, 50.0, 50.0)
        assert 20.0 < score < 60.0

    def test_capped_at_100(self):
        score = _rhythm_score(10.0, 1.0, 100.0, 100.0)
        assert score <= 100.0

    def test_amplitude_below_1(self):
        score = _rhythm_score(0.5, 0.0, 0.0, 0.0)
        assert score == 0.0  # amplitude < 1.0 → amp_norm = 0

    def test_weighting(self):
        # Only phase_alignment = 100 → 30% of 100 = 30.0
        score = _rhythm_score(1.0, 0.0, 100.0, 0.0)
        assert abs(score - 30.0) < 0.1


# ---------------------------------------------------------------------------
# _classify_state
# ---------------------------------------------------------------------------

class TestClassifyState:
    def test_dormant(self):
        assert _classify_state(80.0, 90.0, 10) == "dormant"
        assert _classify_state(80.0, 90.0, 23) == "dormant"

    def test_entrained(self):
        assert _classify_state(75.0, 80.0, 100) == "entrained"
        assert _classify_state(90.0, 95.0, 500) == "entrained"

    def test_rhythmic(self):
        assert _classify_state(60.0, 70.0, 200) == "rhythmic"
        assert _classify_state(74.0, 80.0, 100) == "rhythmic"

    def test_jetlagged(self):
        assert _classify_state(40.0, 10.0, 100) == "jetlagged"

    def test_arrhythmic(self):
        assert _classify_state(40.0, 50.0, 100) == "arrhythmic"

    def test_boundary_dormant(self):
        assert _classify_state(80.0, 90.0, 24) != "dormant"

    def test_boundary_entrained(self):
        assert _classify_state(75.0, 50.0, 50) == "entrained"


# ---------------------------------------------------------------------------
# _git_log (mocked subprocess)
# ---------------------------------------------------------------------------

class TestGitLog:
    def test_empty_repo(self):
        with mock.patch("subprocess.check_output", return_value=""):
            assert _git_log("/fake", 10) == []

    def test_parse_normal(self):
        log_out = "abc123\x001729600000\ndef456\x001729603600\n"
        with mock.patch("subprocess.check_output", return_value=log_out):
            result = _git_log("/fake", 10)
            assert len(result) == 2
            assert result[0] == ("abc123", 1729600000)
            assert result[1] == ("def456", 1729603600)

    def test_malformed_lines(self):
        log_out = "abc\x001729600000\ngarbage_line\ndef\x00not_a_number\n"
        with mock.patch("subprocess.check_output", return_value=log_out):
            result = _git_log("/fake", 10)
            assert len(result) == 1

    def test_subprocess_error(self):
        import subprocess
        with mock.patch(
            "subprocess.check_output",
            side_effect=subprocess.CalledProcessError(1, "git"),
        ):
            assert _git_log("/fake", 10) == []

    def test_blank_lines_skipped(self):
        log_out = "\n\nabc\x001729600000\n\n"
        with mock.patch("subprocess.check_output", return_value=log_out):
            result = _git_log("/fake", 10)
            assert len(result) == 1


# ---------------------------------------------------------------------------
# circadian_report (end-to-end, mocked git)
# ---------------------------------------------------------------------------

class TestCircadianReportE2E:
    def _make_entries(self, hours: list[int], days: int = 10) -> list[tuple]:
        """Generate fake git log entries with commits at given hours."""
        entries = []
        base = datetime(2026, 10, 1, tzinfo=timezone.utc)
        seq = 0
        for d in range(days):
            for h in hours:
                dt = base + timedelta(days=d, hours=h)
                entries.append((f"hash{seq}", int(dt.timestamp())))
                seq += 1
        return entries

    def test_empty_repo(self):
        with mock.patch(
            "iamai.repo_circadian_rhythm._git_log", return_value=[]
        ):
            r = circadian_report("/fake")
            assert r.rhythm_state == "dormant"
            assert r.total_commits == 0

    def test_healthy_rhythm(self):
        entries = self._make_entries([9, 10, 11, 14, 15, 16], days=10)
        with mock.patch(
            "iamai.repo_circadian_rhythm._git_log", return_value=entries
        ):
            r = circadian_report("/fake", work_start=8, work_end=22)
            assert r.total_commits == 60
            assert r.rhythm_state in ("entrained", "rhythmic")
            assert r.phase_alignment > 50.0
            assert r.amplitude > 1.0

    def test_night_owl(self):
        entries = self._make_entries([0, 1, 2, 3], days=10)
        with mock.patch(
            "iamai.repo_circadian_rhythm._git_log", return_value=entries
        ):
            r = circadian_report("/fake", work_start=8, work_end=22)
            assert r.total_commits == 40
            assert r.phase_alignment < 20.0
            assert r.peak_hour in (0, 1, 2, 3)

    def test_tz_offset(self):
        # Commits at UTC 20 → local (UTC+8) = 04:00
        entries = self._make_entries([20], days=10)
        with mock.patch(
            "iamai.repo_circadian_rhythm._git_log", return_value=entries
        ):
            r = circadian_report("/fake", tz_offset_hours=8)
            assert r.peak_hour == 4  # 20 + 8 = 28 mod 24 = 4

    def test_few_commits_dormant(self):
        entries = [(f"h{i}", int(time.time()) - i * 3600) for i in range(10)]
        with mock.patch(
            "iamai.repo_circadian_rhythm._git_log", return_value=entries
        ):
            r = circadian_report("/fake")
            assert r.rhythm_state == "dormant"


# ---------------------------------------------------------------------------
# circadian_summary
# ---------------------------------------------------------------------------

class TestCircadianSummary:
    def test_dormant(self):
        r = CircadianReport()
        s = circadian_summary(r)
        assert "dormant" in s
        assert "not enough" in s

    def test_entrained(self):
        r = CircadianReport(
            peak_hour=14,
            trough_hour=3,
            amplitude=4.2,
            rest_depth=0.45,
            phase_alignment=85.0,
            regularity_score=90.0,
            rhythm_score=82.5,
            rhythm_state="entrained",
            total_commits=500,
            active_days=30,
        )
        s = circadian_summary(r)
        assert "entrained" in s
        assert "score=82.5" in s
        assert "peak=14:00" in s
        assert "trough=03:00" in s
        assert "500 commits" in s
        assert "30 days" in s

    def test_jetlagged(self):
        r = CircadianReport(
            peak_hour=2,
            trough_hour=14,
            amplitude=3.0,
            rhythm_score=35.0,
            rhythm_state="jetlagged",
            total_commits=100,
            active_days=15,
        )
        s = circadian_summary(r)
        assert "jetlagged" in s

    def test_format_includes_all_fields(self):
        r = CircadianReport(
            peak_hour=10,
            trough_hour=4,
            amplitude=2.5,
            phase_alignment=60.0,
            regularity_score=70.0,
            rhythm_score=55.0,
            rhythm_state="rhythmic",
            total_commits=200,
            active_days=20,
        )
        s = circadian_summary(r)
        assert "amplitude=2.5" in s
        assert "alignment=60.0%" in s
        assert "regularity=70.0%" in s
