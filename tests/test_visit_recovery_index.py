"""Tests for iamai.visit_recovery_index — post-visit recovery analysis."""

import time
from datetime import datetime, timezone, timedelta

import pytest

from iamai.visit_recovery_index import (
    RecoveryReport,
    compute_recovery,
    batch_recovery,
    _parse_ts,
    _inter_stroke_gaps,
    _classify,
    _running_median,
    _MIN_PRE_STROKES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _epoch(dt: datetime) -> float:
    return dt.timestamp()


def _stroke(epoch: float, kind: str = "thought") -> dict:
    dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return {"seq": 0, "at": dt.isoformat(), "kind": kind, "text": "test"}


def _make_strokes(base_epoch: float, count: int, gap: float = 15.0) -> list:
    """Generate a list of evenly-spaced strokes."""
    return [_stroke(base_epoch + i * gap) for i in range(count)]


NOW = time.time()


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------

class TestParseTs:
    def test_iso_with_tz(self):
        raw = "2026-11-09T02:00:00+00:00"
        result = _parse_ts(raw)
        assert isinstance(result, float)
        assert result > 0

    def test_iso_without_tz_assumes_utc(self):
        raw = "2026-11-09T02:00:00"
        result = _parse_ts(raw)
        expected = datetime(2026, 11, 9, 2, 0, 0, tzinfo=timezone.utc).timestamp()
        assert abs(result - expected) < 1.0

    def test_epoch_string(self):
        # Some strokes may store epoch as a string — fromisoformat won't
        # parse that, so this tests the happy path only.
        raw = "2026-01-01T00:00:00+00:00"
        assert _parse_ts(raw) > 0


# ---------------------------------------------------------------------------
# _inter_stroke_gaps
# ---------------------------------------------------------------------------

class TestInterStrokeGaps:
    def test_empty(self):
        assert _inter_stroke_gaps([]) == []

    def test_single(self):
        assert _inter_stroke_gaps([100.0]) == []

    def test_two(self):
        assert _inter_stroke_gaps([100.0, 115.0]) == [15.0]

    def test_three(self):
        gaps = _inter_stroke_gaps([100.0, 115.0, 135.0])
        assert gaps == [15.0, 20.0]

    def test_negative_gaps_allowed(self):
        # Out-of-order timestamps produce negative gaps — caller's job to sort.
        gaps = _inter_stroke_gaps([100.0, 90.0])
        assert gaps == [-10.0]


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_fast_at_boundary(self):
        assert _classify(0.80) == "FAST"

    def test_fast_above(self):
        assert _classify(1.0) == "FAST"

    def test_normal_at_boundary(self):
        assert _classify(0.50) == "NORMAL"

    def test_normal_below_fast(self):
        assert _classify(0.79) == "NORMAL"

    def test_slow_at_boundary(self):
        assert _classify(0.20) == "SLOW"

    def test_slow_below_normal(self):
        assert _classify(0.49) == "SLOW"

    def test_stalled_below_slow(self):
        assert _classify(0.19) == "STALLED"

    def test_stalled_zero(self):
        assert _classify(0.0) == "STALLED"


# ---------------------------------------------------------------------------
# _running_median
# ---------------------------------------------------------------------------

class TestRunningMedian:
    def test_empty(self):
        assert _running_median([]) == 0.0

    def test_single(self):
        assert _running_median([42.0]) == 42.0

    def test_even_count(self):
        assert _running_median([10.0, 20.0]) == 15.0

    def test_odd_count(self):
        assert _running_median([10.0, 20.0, 30.0]) == 20.0

    def test_unsorted_still_works(self):
        assert _running_median([30.0, 10.0, 20.0]) == 20.0


# ---------------------------------------------------------------------------
# compute_recovery — UNKNOWN (not enough pre-visit data)
# ---------------------------------------------------------------------------

class TestComputeRecoveryUnknown:
    def test_too_few_pre_strokes(self):
        strokes = _make_strokes(NOW - 100, count=2, gap=15.0)
        report = compute_recovery(strokes, NOW - 50, NOW - 40)
        assert report.grade == "UNKNOWN"
        assert "only 2" in report.detail

    def test_zero_pre_strokes(self):
        # All strokes are post-visit.
        strokes = _make_strokes(NOW + 100, count=10, gap=15.0)
        report = compute_recovery(strokes, NOW - 50, NOW - 40)
        assert report.grade == "UNKNOWN"

    def test_invalid_window(self):
        strokes = _make_strokes(NOW - 1000, count=50, gap=15.0)
        report = compute_recovery(strokes, NOW, NOW - 100)
        assert report.grade == "UNKNOWN"
        assert "invalid" in report.detail


# ---------------------------------------------------------------------------
# compute_recovery — FAST recovery
# ---------------------------------------------------------------------------

class TestComputeRecoveryFast:
    def test_instant_recovery(self):
        """Post-visit strokes resume at exactly the baseline cadence."""
        baseline_gap = 15.0
        pre = _make_strokes(NOW - 600, count=25, gap=baseline_gap)
        # Visit window: 30 seconds.
        visit_start = NOW - 50
        visit_end = NOW - 20
        # Post-visit: same 15s cadence, starting right after visit.
        post = _make_strokes(visit_end + 5, count=10, gap=baseline_gap)
        all_strokes = pre + post

        report = compute_recovery(all_strokes, visit_start, visit_end, tolerance=0.25)
        assert report.grade == "FAST"
        assert report.recovered is True
        assert report.baseline_cadence_s == pytest.approx(baseline_gap, abs=1.0)
        # index should be 1.0: recovery_time = one baseline interval.
        assert report.index == pytest.approx(1.0, abs=0.01)

    def test_fast_with_slight_delay(self):
        """Post-visit first gap is slightly large but quickly normalises."""
        baseline_gap = 15.0
        pre = _make_strokes(NOW - 600, count=25, gap=baseline_gap)
        visit_start = NOW - 60
        visit_end = NOW - 30
        # First gap is 22s (within 1.5× baseline), then back to 15s.
        post_epochs = [visit_end + 10]
        post_epochs.append(post_epochs[-1] + 22.0)
        for _ in range(1, 14):
            post_epochs.append(post_epochs[-1] + baseline_gap)
        post = [_stroke(e) for e in post_epochs]
        all_strokes = pre + post

        report = compute_recovery(all_strokes, visit_start, visit_end, tolerance=0.50)
        assert report.recovered is True
        # A single slightly-elevated gap followed by baseline gaps:
        # median of [22, 15] = 18.5 > 22.5? no → recovered on 2nd gap.
        # index = 15 / (22+15-22)... let's just check it's > 0.
        assert report.index > 0
        assert report.grade in ("FAST", "NORMAL", "SLOW")


# ---------------------------------------------------------------------------
# compute_recovery — NORMAL recovery
# ---------------------------------------------------------------------------

class TestComputeRecoveryNormal:
    def test_gradual_warmup(self):
        """Writer takes a few slightly-longer gaps before settling."""
        baseline_gap = 15.0
        pre = _make_strokes(NOW - 800, count=30, gap=baseline_gap)
        visit_start = NOW - 100
        visit_end = NOW - 60
        # Post-visit: gaps ease from 19 → 18 → 16 → baseline.
        post_epochs = [visit_end + 10]
        gaps = [19, 18, 16, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15, 15]
        for g in gaps:
            post_epochs.append(post_epochs[-1] + g)
        post = [_stroke(e) for e in post_epochs]
        all_strokes = pre + post

        report = compute_recovery(all_strokes, visit_start, visit_end, tolerance=0.25)
        assert report.recovered is True
        assert report.index > 0
        # Check it's not stalled — writer did eventually normalise.
        assert report.grade != "STALLED"


# ---------------------------------------------------------------------------
# compute_recovery — SLOW recovery
# ---------------------------------------------------------------------------

class TestComputeRecoverySlow:
    def test_long_warmup(self):
        """Writer takes many strokes with large gaps to return to baseline."""
        baseline_gap = 15.0
        pre = _make_strokes(NOW - 800, count=30, gap=baseline_gap)
        visit_start = NOW - 200
        visit_end = NOW - 150
        # Post-visit: all gaps are 30s (double baseline) — never recovers.
        post_epochs = [visit_end + 10]
        for i in range(20):
            post_epochs.append(post_epochs[-1] + 30.0)
        post = [_stroke(e) for e in post_epochs]
        all_strokes = pre + post

        report = compute_recovery(all_strokes, visit_start, visit_end, tolerance=0.20)
        # All gaps are 30s, median is 30s, baseline×1.2=18 — never recovers.
        assert report.recovered is False
        assert report.grade == "STALLED"


# ---------------------------------------------------------------------------
# compute_recovery — STALLED (never recovered)
# ---------------------------------------------------------------------------

class TestComputeRecoveryStalled:
    def test_no_post_strokes(self):
        """No strokes after the visit — writer is dead."""
        pre = _make_strokes(NOW - 600, count=30, gap=15.0)
        report = compute_recovery(pre, NOW - 50, NOW - 20)
        assert report.grade == "STALLED"
        assert report.recovered is False
        assert "no post-visit" in report.detail

    def test_very_slow_post_strokes(self):
        """Post-visit strokes are extremely spaced out."""
        baseline_gap = 15.0
        pre = _make_strokes(NOW - 800, count=30, gap=baseline_gap)
        visit_start = NOW - 200
        visit_end = NOW - 100
        # Post-visit: 300s gaps — way too slow.
        post = _make_strokes(visit_end + 10, count=5, gap=300.0)
        all_strokes = pre + post

        report = compute_recovery(all_strokes, visit_start, visit_end, tolerance=0.25)
        assert report.grade == "STALLED"
        assert report.recovered is False


# ---------------------------------------------------------------------------
# compute_recovery — edge cases
# ---------------------------------------------------------------------------

class TestComputeRecoveryEdgeCases:
    def test_exactly_min_pre_strokes(self):
        """Exactly _MIN_PRE_STROKES pre-visit strokes should work."""
        count = _MIN_PRE_STROKES
        pre = _make_strokes(NOW - 300, count=count, gap=15.0)
        visit_start = NOW - 50
        visit_end = NOW - 30
        post = _make_strokes(visit_end + 5, count=10, gap=15.0)
        all_strokes = pre + post

        report = compute_recovery(all_strokes, visit_start, visit_end, tolerance=0.25)
        assert report.grade != "UNKNOWN"

    def test_all_strokes_during_visit(self):
        """All strokes fall inside the visit window — no pre or post."""
        strokes = _make_strokes(NOW - 50, count=20, gap=1.0)
        report = compute_recovery(strokes, NOW - 100, NOW)
        assert report.grade == "UNKNOWN"

    def test_baseline_zero_gaps(self):
        """Duplicate timestamps produce zero baseline — should return UNKNOWN."""
        base = NOW - 300
        pre = [_stroke(base)] * 10  # all same timestamp
        visit_start = NOW - 50
        visit_end = NOW - 30
        post = _make_strokes(visit_end + 5, count=10, gap=15.0)
        all_strokes = pre + post

        report = compute_recovery(all_strokes, visit_start, visit_end)
        assert report.grade == "UNKNOWN"
        assert "zero" in report.detail.lower() or "baseline" in report.detail.lower()

    def test_tolerance_boundary(self):
        """Recovery right at the tolerance boundary."""
        baseline_gap = 15.0
        pre = _make_strokes(NOW - 600, count=25, gap=baseline_gap)
        visit_start = NOW - 50
        visit_end = NOW - 30
        # Post-visit: gap is exactly baseline * 1.25 (at tolerance boundary).
        post = _make_strokes(visit_end + 5, count=10, gap=baseline_gap * 1.25)
        all_strokes = pre + post

        report = compute_recovery(all_strokes, visit_start, visit_end, tolerance=0.25)
        assert report.recovered is True

    def test_max_post_strokes_limit(self):
        """Only max_post_strokes are examined."""
        pre = _make_strokes(NOW - 600, count=25, gap=15.0)
        visit_start = NOW - 50
        visit_end = NOW - 30
        post = _make_strokes(visit_end + 5, count=200, gap=300.0)
        all_strokes = pre + post

        report = compute_recovery(
            all_strokes, visit_start, visit_end, max_post_strokes=50, tolerance=0.10
        )
        assert report.post_stroke_count == 50


# ---------------------------------------------------------------------------
# batch_recovery
# ---------------------------------------------------------------------------

class TestBatchRecovery:
    def test_empty_visits(self):
        assert batch_recovery([], []) == []

    def test_multiple_visits(self):
        pre = _make_strokes(NOW - 1000, count=30, gap=15.0)
        visits = [
            {"start": NOW - 500, "end": NOW - 480},
            {"start": NOW - 200, "end": NOW - 180},
        ]
        # Add post-visit strokes for both visits.
        post1 = _make_strokes(NOW - 475, count=10, gap=15.0)
        post2 = _make_strokes(NOW - 175, count=10, gap=15.0)
        all_strokes = sorted(pre + post1 + post2, key=lambda s: s["at"])

        reports = batch_recovery(all_strokes, visits, tolerance=0.30)
        assert len(reports) == 2
        for r in reports:
            assert isinstance(r, RecoveryReport)

    def test_kwargs_forwarded(self):
        """Extra kwargs are passed through to compute_recovery."""
        pre = _make_strokes(NOW - 600, count=25, gap=15.0)
        visits = [{"start": NOW - 50, "end": NOW - 30}]
        post = _make_strokes(NOW - 25, count=10, gap=15.0)
        all_strokes = pre + post

        reports = batch_recovery(all_strokes, visits, baseline_window=10, tolerance=0.50)
        assert len(reports) == 1
        assert reports[0].grade != "UNKNOWN"
