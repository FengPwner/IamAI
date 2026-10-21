"""Tests for iamai.commit_rhythm."""

from datetime import datetime, timedelta, timezone

import pytest

from iamai.commit_rhythm import (
    RhythmReport,
    _classify,
    _parse_ts,
    compute_gaps,
    rhythm_report,
    rhythm_summary,
)


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------

class TestParseTs:
    def test_iso_with_z(self):
        dt = _parse_ts("2026-10-22T06:00:00Z")
        assert dt is not None
        assert dt.hour == 6
        assert dt.tzinfo is not None

    def test_iso_with_offset(self):
        dt = _parse_ts("2026-10-22T06:00:00+08:00")
        assert dt is not None
        assert dt.hour == 6

    def test_iso_without_tz(self):
        dt = _parse_ts("2026-10-22T06:00:00")
        assert dt is not None
        assert dt.tzinfo == timezone.utc

    def test_datetime_passthrough(self):
        dt = datetime(2026, 10, 22, 6, 0, tzinfo=timezone.utc)
        assert _parse_ts(dt) == dt

    def test_naive_datetime_gets_utc(self):
        dt = datetime(2026, 10, 22, 6, 0)
        result = _parse_ts(dt)
        assert result is not None
        assert result.tzinfo == timezone.utc

    def test_empty_string(self):
        assert _parse_ts("") is None

    def test_none(self):
        assert _parse_ts(None) is None

    def test_garbage(self):
        assert _parse_ts("not-a-date") is None

    def test_fractional_seconds(self):
        dt = _parse_ts("2026-10-22T06:00:00.123456Z")
        assert dt is not None


# ---------------------------------------------------------------------------
# compute_gaps
# ---------------------------------------------------------------------------

class TestComputeGaps:
    def test_empty(self):
        assert compute_gaps([]) == []

    def test_single(self):
        assert compute_gaps(["2026-10-22T06:00:00Z"]) == []

    def test_two_commits_ten_minutes(self):
        gaps = compute_gaps([
            "2026-10-22T06:00:00Z",
            "2026-10-22T06:10:00Z",
        ])
        assert len(gaps) == 1
        assert gaps[0] == pytest.approx(600.0)

    def test_unsorted_input_gets_sorted(self):
        gaps = compute_gaps([
            "2026-10-22T06:20:00Z",
            "2026-10-22T06:00:00Z",
            "2026-10-22T06:10:00Z",
        ])
        assert len(gaps) == 2
        assert gaps[0] == pytest.approx(600.0)
        assert gaps[1] == pytest.approx(600.0)

    def test_skips_unparseable(self):
        gaps = compute_gaps([
            "2026-10-22T06:00:00Z",
            "garbage",
            "2026-10-22T06:10:00Z",
        ])
        assert len(gaps) == 1
        assert gaps[0] == pytest.approx(600.0)

    def test_varying_gaps(self):
        gaps = compute_gaps([
            "2026-10-22T06:00:00Z",
            "2026-10-22T06:10:00Z",
            "2026-10-22T06:30:00Z",
        ])
        assert len(gaps) == 2
        assert gaps[0] == pytest.approx(600.0)
        assert gaps[1] == pytest.approx(1200.0)


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_regular(self):
        assert _classify(cv=0.10, cadence_hit_rate=0.90, max_gap=700, trailing_gap=300, target=600) == "regular"

    def test_regular_boundary(self):
        assert _classify(cv=0.30, cadence_hit_rate=0.70, max_gap=700, trailing_gap=300, target=600) == "regular"

    def test_irregular(self):
        assert _classify(cv=0.45, cadence_hit_rate=0.55, max_gap=900, trailing_gap=300, target=600) == "irregular"

    def test_bursty_high_cv(self):
        assert _classify(cv=0.80, cadence_hit_rate=0.50, max_gap=900, trailing_gap=300, target=600) == "bursty"

    def test_bursty_large_max_gap(self):
        # max_gap > 3x target
        assert _classify(cv=0.10, cadence_hit_rate=0.80, max_gap=2000, trailing_gap=300, target=600) == "bursty"

    def test_stalled_overrides_all(self):
        # Even with perfect cv and hit rate, trailing > 2x target → stalled
        assert _classify(cv=0.01, cadence_hit_rate=0.99, max_gap=650, trailing_gap=1300, target=600) == "stalled"

    def test_stalled_trailing_gap(self):
        assert _classify(cv=0.50, cadence_hit_rate=0.50, max_gap=800, trailing_gap=1500, target=600) == "stalled"

    def test_fallback_bursty(self):
        # cv > 0.60 and hit_rate < 0.40
        assert _classify(cv=0.70, cadence_hit_rate=0.20, max_gap=1000, trailing_gap=300, target=600) == "bursty"


# ---------------------------------------------------------------------------
# rhythm_report
# ---------------------------------------------------------------------------

def _make_regular_timestamps(n: int, interval_sec: int = 600) -> list[str]:
    """Generate n timestamps at a fixed interval starting from a base."""
    base = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    return [
        (base + timedelta(seconds=i * interval_sec)).isoformat()
        for i in range(n)
    ]


class TestRhythmReport:
    def test_empty_input(self):
        r = rhythm_report([])
        assert r.commit_count == 0
        assert r.verdict == "stalled"

    def test_single_commit_not_stalled(self):
        now = datetime(2026, 10, 22, 6, 5, tzinfo=timezone.utc)
        r = rhythm_report(["2026-10-22T06:00:00Z"], now=now)
        assert r.commit_count == 1
        assert r.trailing_gap == pytest.approx(300.0)
        assert r.verdict == "unknown"

    def test_single_commit_stalled(self):
        now = datetime(2026, 10, 22, 6, 25, tzinfo=timezone.utc)
        r = rhythm_report(["2026-10-22T06:00:00Z"], now=now)
        assert r.commit_count == 1
        assert r.trailing_gap == pytest.approx(1500.0)
        assert r.verdict == "stalled"

    def test_perfect_cadence(self):
        """10 commits exactly 600s apart → regular."""
        ts = _make_regular_timestamps(10, 600)
        now = datetime(2026, 10, 22, 1, 35, tzinfo=timezone.utc)  # 5 min after last
        r = rhythm_report(ts, target_seconds=600, now=now)
        assert r.commit_count == 10
        assert r.mean_gap == pytest.approx(600.0)
        assert r.cv == pytest.approx(0.0)
        assert r.cadence_hit_rate == pytest.approx(1.0)
        assert r.verdict == "regular"

    def test_slightly_irregular(self):
        """Gaps vary between 450s and 750s → should be irregular or regular."""
        base = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
        offsets = [0, 500, 950, 1500, 2050, 2500, 3100, 3650, 4200, 4800]
        ts = [(base + timedelta(seconds=o)).isoformat() for o in offsets]
        now = base + timedelta(seconds=5100)
        r = rhythm_report(ts, target_seconds=600, now=now)
        assert r.commit_count == 10
        assert len(r.gaps) == 9
        assert r.verdict in ("regular", "irregular")

    def test_bursty_pattern(self):
        """Burst of commits then long silence → bursty."""
        base = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
        # 5 commits 60s apart, then 3000s gap, then 5 more 60s apart
        offsets = list(range(0, 300, 60)) + list(range(3240, 3540, 60))
        ts = [(base + timedelta(seconds=o)).isoformat() for o in offsets]
        now = base + timedelta(seconds=3700)
        r = rhythm_report(ts, target_seconds=600, now=now)
        assert r.max_gap == pytest.approx(3000.0)
        assert r.verdict == "bursty"

    def test_stalled_trailing(self):
        """Perfect history but last commit was 25 min ago → stalled."""
        ts = _make_regular_timestamps(5, 600)
        # last commit is at t=2400; now at t=3900 (25 min after last)
        now = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=3900)
        r = rhythm_report(ts, target_seconds=600, now=now)
        assert r.trailing_gap == pytest.approx(1500.0)
        assert r.verdict == "stalled"

    def test_custom_target(self):
        """Target of 300s (5 min) with matching cadence → regular."""
        ts = _make_regular_timestamps(8, 300)
        now = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=2250)
        r = rhythm_report(ts, target_seconds=300, now=now)
        assert r.cadence_hit_rate == pytest.approx(1.0)
        assert r.verdict == "regular"


# ---------------------------------------------------------------------------
# rhythm_summary
# ---------------------------------------------------------------------------

class TestRhythmSummary:
    def test_empty(self):
        r = rhythm_report([])
        s = rhythm_summary(r)
        assert "stalled" in s

    def test_regular(self):
        ts = _make_regular_timestamps(10, 600)
        now = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=5700)
        r = rhythm_report(ts, target_seconds=600, now=now)
        s = rhythm_summary(r)
        assert "commits=10" in s
        assert "regular" in s

    def test_format_minutes(self):
        """Gaps of 600s should display as minutes."""
        ts = _make_regular_timestamps(3, 600)
        now = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=1500)
        r = rhythm_report(ts, target_seconds=600, now=now)
        s = rhythm_summary(r)
        assert "10.0m" in s

    def test_format_hours(self):
        """Very long gaps should display as hours."""
        base = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
        ts = [base.isoformat(), (base + timedelta(hours=2)).isoformat()]
        now = base + timedelta(hours=2, minutes=5)
        r = rhythm_report(ts, target_seconds=600, now=now)
        s = rhythm_summary(r)
        assert "2.0h" in s


# ---------------------------------------------------------------------------
# Integration: real-ish scenario
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_typical_healthy_session(self):
        """Simulate 2 hours of commits at ~10 min intervals."""
        ts = _make_regular_timestamps(13, 600)
        # Add small jitter to simulate real timing
        base = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
        jitter = [0, 605, 1215, 1810, 2420, 3025, 3640, 4250, 4855, 5470, 6080, 6690, 7300]
        ts = [(base + timedelta(seconds=s)).isoformat() for s in jitter]
        now = base + timedelta(seconds=7600)  # 5 min after last
        r = rhythm_report(ts, target_seconds=600, now=now)
        assert r.commit_count == 13
        assert r.verdict in ("regular", "irregular")
        assert r.cadence_hit_rate >= 0.5

    def test_degraded_session_with_recovery(self):
        """Commits start regular, then stall, then burst to catch up."""
        base = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
        # Regular for 5 commits, then 30 min gap, then burst of 5 in 2 min each
        regular = [base + timedelta(seconds=i * 600) for i in range(5)]
        stall_end = base + timedelta(seconds=2400 + 1800)  # 30 min gap
        burst = [stall_end + timedelta(seconds=i * 120) for i in range(5)]
        all_ts = [d.isoformat() for d in regular + burst]
        now = stall_end + timedelta(seconds=600)
        r = rhythm_report(all_ts, target_seconds=600, now=now)
        assert r.verdict in ("bursty", "stalled", "irregular")
        # max gap should be the 30-min stall
        assert r.max_gap >= 1800
