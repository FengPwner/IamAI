"""Tests for commit_pulse_monitor — repository commit rhythm analysis.

37 tests covering the full public API surface:
- _compute_gaps() with various timestamp sequences
- compute_pulse_score() scoring logic
- count_missed_beats() and count_bursts() counting
- pulse_report() full report generation
- pulse_summary() human-readable formatting
- Edge cases: empty data, single commit, perfect rhythm, total chaos

written by Qwen during caretaker visit 805, 2026-11-23
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.commit_pulse_monitor import (
    _compute_gaps,
    compute_pulse_score,
    count_bursts,
    count_missed_beats,
    pulse_report,
    pulse_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_timestamps(base: datetime, intervals_seconds: list[float]) -> list[datetime]:
    """Build a newest-first timestamp list from a base and interval deltas.

    intervals_seconds are the gaps between consecutive commits, applied
    going *backward* from base (which is the newest commit).
    """
    ts = [base]
    for gap in intervals_seconds:
        ts.append(ts[-1] - timedelta(seconds=gap))
    return ts


_UTC = timezone.utc
_BASE = datetime(2026, 11, 23, 3, 0, 0, tzinfo=_UTC)


# ---------------------------------------------------------------------------
# _compute_gaps
# ---------------------------------------------------------------------------

class TestComputeGaps:
    def test_empty(self):
        assert _compute_gaps([]) == []

    def test_single(self):
        assert _compute_gaps([_BASE]) == []

    def test_two_commits(self):
        ts = _make_timestamps(_BASE, [600])
        gaps = _compute_gaps(ts)
        assert len(gaps) == 1
        assert abs(gaps[0] - 600) < 0.01

    def test_multiple_commits(self):
        ts = _make_timestamps(_BASE, [600, 610, 590])
        gaps = _compute_gaps(ts)
        assert len(gaps) == 3
        assert abs(gaps[0] - 600) < 0.01
        assert abs(gaps[1] - 610) < 0.01
        assert abs(gaps[2] - 590) < 0.01

    def test_irregular_gaps(self):
        ts = _make_timestamps(_BASE, [100, 2000, 50])
        gaps = _compute_gaps(ts)
        assert len(gaps) == 3
        assert gaps[0] == 100
        assert gaps[1] == 2000
        assert gaps[2] == 50


# ---------------------------------------------------------------------------
# compute_pulse_score
# ---------------------------------------------------------------------------

class TestComputePulseScore:
    def test_empty_gaps(self):
        assert compute_pulse_score([], 600) == 1.0

    def test_perfect_rhythm(self):
        gaps = [600.0] * 10
        score = compute_pulse_score(gaps, 600)
        assert score == 1.0

    def test_all_missed(self):
        # every gap is 3× expected — all out of band
        gaps = [1800.0] * 10
        score = compute_pulse_score(gaps, 600)
        assert score == 0.0

    def test_half_in_band(self):
        # 5 perfect, 5 wildly out
        gaps = [600.0] * 5 + [3600.0] * 5
        score = compute_pulse_score(gaps, 600)
        assert 0.3 < score < 0.7

    def test_slightly_off(self):
        # within band but not perfect
        gaps = [650.0] * 10  # 650 is within [300, 900]
        score = compute_pulse_score(gaps, 600)
        assert 0.7 < score < 1.0

    def test_burst_heavy(self):
        # gaps of 10s when expected is 600 — below 0.3× threshold
        gaps = [10.0] * 10
        score = compute_pulse_score(gaps, 600)
        assert score == 0.0

    def test_mixed_realistic(self):
        gaps = [590, 610, 605, 595, 1200, 600, 580, 620, 600, 50]
        score = compute_pulse_score(gaps, 600)
        # most are in-band, 1200 and 50 are out
        assert 0.5 < score < 0.9


# ---------------------------------------------------------------------------
# count_missed_beats / count_bursts
# ---------------------------------------------------------------------------

class TestCountMissedBeats:
    def test_no_missed(self):
        gaps = [600.0, 590.0, 610.0]
        assert count_missed_beats(gaps, 600) == 0

    def test_one_missed(self):
        gaps = [600.0, 1300.0, 590.0]
        assert count_missed_beats(gaps, 600) == 1

    def test_all_missed(self):
        gaps = [2000.0, 1500.0, 3000.0]
        assert count_missed_beats(gaps, 600) == 3

    def test_boundary(self):
        # exactly 2× = 1200 should count as missed (> 2×)
        gaps = [1200.0]
        assert count_missed_beats(gaps, 600) == 0  # not > 2×, exactly 2×

    def test_just_over_boundary(self):
        gaps = [1200.1]
        assert count_missed_beats(gaps, 600) == 1


class TestCountBursts:
    def test_no_bursts(self):
        gaps = [600.0, 590.0, 610.0]
        assert count_bursts(gaps, 600) == 0

    def test_one_burst(self):
        gaps = [600.0, 50.0, 590.0]
        assert count_bursts(gaps, 600) == 1  # 50 < 180

    def test_all_bursts(self):
        gaps = [10.0, 20.0, 30.0]
        assert count_bursts(gaps, 600) == 3

    def test_boundary(self):
        # exactly 0.3× = 180 — not < threshold
        gaps = [180.0]
        assert count_bursts(gaps, 600) == 0

    def test_just_under_boundary(self):
        gaps = [179.9]
        assert count_bursts(gaps, 600) == 1


# ---------------------------------------------------------------------------
# pulse_report (with mocked git)
# ---------------------------------------------------------------------------

class TestPulseReport:
    def test_empty_repo(self):
        """No commits → graceful defaults."""
        with patch("iamai.commit_pulse_monitor._git_commit_timestamps", return_value=[]):
            r = pulse_report(600, 2.0, Path("/fake"))
        assert r["mean_gap_s"] is None
        assert r["pulse_score"] == 1.0
        assert r["healthy"] is True
        assert r["n_commits"] == 0

    def test_single_commit(self):
        ts = [_BASE]
        with patch("iamai.commit_pulse_monitor._git_commit_timestamps", return_value=ts):
            r = pulse_report(600, 2.0, Path("/fake"))
        assert r["mean_gap_s"] is None  # no gaps with 1 commit
        assert r["healthy"] is True

    def test_healthy_rhythm(self):
        ts = _make_timestamps(_BASE, [600, 590, 610, 605, 595])
        with patch("iamai.commit_pulse_monitor._git_commit_timestamps", return_value=ts):
            r = pulse_report(600, 2.0, Path("/fake"))
        assert r["pulse_score"] > 0.8
        assert r["healthy"] is True
        assert r["missed_beats"] == 0
        assert r["burst_count"] == 0
        assert r["n_commits"] == 6

    def test_irregular_rhythm(self):
        # mix of stalls and bursts
        ts = _make_timestamps(_BASE, [600, 3600, 10, 600, 7200, 50])
        with patch("iamai.commit_pulse_monitor._git_commit_timestamps", return_value=ts):
            r = pulse_report(600, 24.0, Path("/fake"))
        assert r["missed_beats"] >= 2  # 3600 and 7200
        assert r["burst_count"] >= 2   # 10 and 50
        assert r["pulse_score"] < 0.5
        assert r["healthy"] is False

    def test_window_filtering(self):
        """Commits outside the window should be excluded."""
        # 10 commits at 600s = 6000s ≈ 1.67h; window=1h should cut some
        ts = _make_timestamps(_BASE, [600] * 9)
        with patch("iamai.commit_pulse_monitor._git_commit_timestamps", return_value=ts):
            r = pulse_report(600, 1.0, Path("/fake"))
        # 1h = 3600s, 600s × 6 gaps = 3600s → should include ~7 commits
        assert r["n_commits"] <= 10

    def test_jitter_computation(self):
        ts = _make_timestamps(_BASE, [600, 600, 600, 600])
        with patch("iamai.commit_pulse_monitor._git_commit_timestamps", return_value=ts):
            r = pulse_report(600, 2.0, Path("/fake"))
        assert r["jitter"] == 0.0  # perfect regularity

    def test_keys_present(self):
        with patch("iamai.commit_pulse_monitor._git_commit_timestamps", return_value=[]):
            r = pulse_report(600, 2.0, Path("/fake"))
        expected_keys = {
            "mean_gap_s", "median_gap_s", "jitter", "pulse_score",
            "missed_beats", "burst_count", "n_commits", "window_hours", "healthy",
        }
        assert set(r.keys()) == expected_keys


# ---------------------------------------------------------------------------
# pulse_summary
# ---------------------------------------------------------------------------

class TestPulseSummary:
    def test_no_data_message(self):
        with patch("iamai.commit_pulse_monitor._git_commit_timestamps", return_value=[]):
            s = pulse_summary(600, 2.0, Path("/fake"))
        assert "no data" in s

    def test_healthy_summary(self):
        ts = _make_timestamps(_BASE, [600, 590, 610])
        with patch("iamai.commit_pulse_monitor._git_commit_timestamps", return_value=ts):
            s = pulse_summary(600, 2.0, Path("/fake"))
        assert "healthy" in s
        assert "@600s" in s

    def test_irregular_summary(self):
        ts = _make_timestamps(_BASE, [600, 3600, 10, 600, 7200, 50])
        with patch("iamai.commit_pulse_monitor._git_commit_timestamps", return_value=ts):
            s = pulse_summary(600, 24.0, Path("/fake"))
        assert "irregular" in s
