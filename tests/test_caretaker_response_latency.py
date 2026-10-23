"""Tests for iamai.caretaker_response_latency.

Measures the gap between 'something broke' and 'someone noticed'.
If the caretaker visits every 10 minutes but a stall sits for an hour,
that is a monitoring failure.  These tests ensure the math is right
so the verdict can be trusted.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from iamai.caretaker_response_latency import (
    CaretakerResponse,
    ResponseTracker,
    _to_datetime,
    _latency_seconds,
)


# ------------------------------------------------------------------
# _to_datetime helpers
# ------------------------------------------------------------------


class TestToDatetime:
    def test_iso_string(self):
        dt = _to_datetime("2026-10-23T12:00:00+08:00")
        assert dt.tzinfo is not None
        assert dt.year == 2026

    def test_iso_string_naive_gets_utc(self):
        dt = _to_datetime("2026-10-23T12:00:00")
        assert dt.tzinfo == timezone.utc

    def test_datetime_aware(self):
        aware = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
        assert _to_datetime(aware) is aware

    def test_datetime_naive_gets_utc(self):
        naive = datetime(2026, 10, 23, 12, 0)
        result = _to_datetime(naive)
        assert result.tzinfo == timezone.utc

    def test_epoch_float(self):
        dt = _to_datetime(0.0)
        assert dt == datetime(1970, 1, 1, tzinfo=timezone.utc)

    def test_epoch_int(self):
        dt = _to_datetime(1698000000)
        assert dt.year == 2023

    def test_bad_type_raises(self):
        with pytest.raises(TypeError):
            _to_datetime([1, 2, 3])


# ------------------------------------------------------------------
# _latency_seconds
# ------------------------------------------------------------------


class TestLatencySeconds:
    def test_basic(self):
        assert _latency_seconds(
            "2026-10-23T12:00:00+00:00",
            "2026-10-23T12:10:00+00:00",
        ) == pytest.approx(600.0)

    def test_zero(self):
        assert _latency_seconds(
            "2026-10-23T12:00:00+00:00",
            "2026-10-23T12:00:00+00:00",
        ) == 0.0

    def test_negative_clamped_to_zero(self):
        """Restart before stall detection → clamp to 0."""
        assert _latency_seconds(
            "2026-10-23T12:10:00+00:00",
            "2026-10-23T12:00:00+00:00",
        ) == 0.0

    def test_cross_timezone(self):
        assert _latency_seconds(
            "2026-10-23T20:00:00+08:00",
            "2026-10-23T12:10:00+00:00",
        ) == pytest.approx(600.0)


# ------------------------------------------------------------------
# CaretakerResponse
# ------------------------------------------------------------------


class TestCaretakerResponse:
    def test_from_timestamps(self):
        r = CaretakerResponse.from_timestamps(
            "2026-10-23T12:00:00+00:00",
            "2026-10-23T12:05:00+00:00",
        )
        assert r.latency_s == pytest.approx(300.0)
        assert r.source == "caretaker"

    def test_tier_fast(self):
        r = CaretakerResponse.from_timestamps(
            "2026-10-23T12:00:00+00:00",
            "2026-10-23T12:05:00+00:00",
        )
        # 300s / 600s cadence = 0.5x → fast
        assert r.tier(caretaker_cadence_s=600) == "fast"

    def test_tier_slow(self):
        r = CaretakerResponse.from_timestamps(
            "2026-10-23T12:00:00+00:00",
            "2026-10-23T12:30:00+00:00",
        )
        # 1800s / 600s = 3x → slow (≥2x, <10x)
        assert r.tier(caretaker_cadence_s=600) == "slow"

    def test_tier_missed(self):
        r = CaretakerResponse.from_timestamps(
            "2026-10-23T12:00:00+00:00",
            "2026-10-23T14:00:00+00:00",
        )
        # 7200s / 600s = 12x → missed (≥10x)
        assert r.tier(caretaker_cadence_s=600) == "missed"

    def test_lost_strokes(self):
        r = CaretakerResponse.from_timestamps(
            "2026-10-23T12:00:00+00:00",
            "2026-10-23T12:05:00+00:00",
        )
        # 300s / 15s cadence = 20 strokes
        assert r.lost_strokes(writer_cadence_s=15) == pytest.approx(20.0)

    def test_lost_strokes_zero_cadence(self):
        r = CaretakerResponse.from_timestamps(
            "2026-10-23T12:00:00+00:00",
            "2026-10-23T12:05:00+00:00",
        )
        assert r.lost_strokes(writer_cadence_s=0) == 0.0

    def test_invalid_source_raises(self):
        with pytest.raises(ValueError, match="source"):
            CaretakerResponse(
                stall_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                restart_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                latency_s=0.0,
                source="bogus",
            )

    def test_negative_latency_raises(self):
        with pytest.raises(ValueError, match="latency_s"):
            CaretakerResponse(
                stall_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                restart_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                latency_s=-1.0,
                source="caretaker",
            )

    def test_frozen(self):
        r = CaretakerResponse.from_timestamps(
            "2026-10-23T12:00:00+00:00",
            "2026-10-23T12:05:00+00:00",
        )
        with pytest.raises(AttributeError):
            r.latency_s = 999.0

    def test_tier_zero_cadence(self):
        r = CaretakerResponse.from_timestamps(
            "2026-10-23T12:00:00+00:00",
            "2026-10-23T12:05:00+00:00",
        )
        assert r.tier(caretaker_cadence_s=0) == "fast"


# ------------------------------------------------------------------
# ResponseTracker — recording
# ------------------------------------------------------------------


class TestResponseTrackerRecording:
    def test_record_and_count(self):
        t = ResponseTracker()
        assert t.count == 0
        t.record("2026-10-23T12:00:00+00:00", "2026-10-23T12:05:00+00:00")
        assert t.count == 1

    def test_max_history(self):
        t = ResponseTracker(max_history=3)
        for i in range(10):
            base = f"2026-10-23T{12 + i // 60:02d}:{i % 60:02d}:00+00:00"
            end = f"2026-10-23T{12 + i // 60:02d}:{i % 60:02d}:30+00:00"
            t.record(base, end)
        assert t.count == 3

    def test_invalid_cadence_raises(self):
        with pytest.raises(ValueError):
            ResponseTracker(caretaker_cadence_s=0)

    def test_invalid_writer_cadence_raises(self):
        with pytest.raises(ValueError):
            ResponseTracker(writer_cadence_s=-1)

    def test_invalid_max_history_raises(self):
        with pytest.raises(ValueError):
            ResponseTracker(max_history=0)


# ------------------------------------------------------------------
# ResponseTracker — queries
# ------------------------------------------------------------------


class TestResponseTrackerQueries:
    @pytest.fixture
    def tracker(self):
        t = ResponseTracker(caretaker_cadence_s=600, writer_cadence_s=15)
        # fast: 300s
        t.record("2026-10-23T12:00:00+00:00", "2026-10-23T12:05:00+00:00")
        # slow: 1800s
        t.record("2026-10-23T14:00:00+00:00", "2026-10-23T14:30:00+00:00")
        # missed: 7200s
        t.record("2026-10-23T16:00:00+00:00", "2026-10-23T18:00:00+00:00")
        return t

    def test_mean_latency(self, tracker):
        # (300 + 1800 + 7200) / 3 = 3100
        assert tracker.mean_latency_s() == pytest.approx(3100.0)

    def test_median_latency(self, tracker):
        # sorted: [300, 1800, 7200] → median = 1800
        assert tracker.median_latency_s() == pytest.approx(1800.0)

    def test_worst_latency(self, tracker):
        assert tracker.worst_latency_s() == pytest.approx(7200.0)

    def test_best_latency(self, tracker):
        assert tracker.best_latency_s() == pytest.approx(300.0)

    def test_total_latency(self, tracker):
        assert tracker.total_latency_s == pytest.approx(9300.0)

    def test_total_lost_strokes(self, tracker):
        # 9300 / 15 = 620
        assert tracker.total_lost_strokes() == pytest.approx(620.0)

    def test_empty_tracker(self):
        t = ResponseTracker()
        assert t.mean_latency_s() == 0.0
        assert t.median_latency_s() == 0.0
        assert t.worst_latency_s() == 0.0
        assert t.best_latency_s() == 0.0
        assert t.total_latency_s == 0.0
        assert t.total_lost_strokes() == 0.0


# ------------------------------------------------------------------
# ResponseTracker — tier breakdown
# ------------------------------------------------------------------


class TestResponseTrackerTiers:
    @pytest.fixture
    def tracker(self):
        t = ResponseTracker(caretaker_cadence_s=600)
        # 2 fast, 1 slow, 1 missed
        t.record("2026-10-23T12:00:00+00:00", "2026-10-23T12:05:00+00:00")  # 300s fast
        t.record("2026-10-23T13:00:00+00:00", "2026-10-23T13:08:00+00:00")  # 480s fast
        t.record("2026-10-23T14:00:00+00:00", "2026-10-23T14:25:00+00:00")  # 1500s slow
        t.record("2026-10-23T16:00:00+00:00", "2026-10-23T17:40:00+00:00")  # 6000s missed
        return t

    def test_tier_counts(self, tracker):
        assert tracker.tier_counts() == {"fast": 2, "slow": 1, "missed": 1}

    def test_fast_pct(self, tracker):
        assert tracker.fast_pct() == pytest.approx(50.0)

    def test_slow_pct(self, tracker):
        assert tracker.slow_pct() == pytest.approx(25.0)

    def test_missed_pct(self, tracker):
        assert tracker.missed_pct() == pytest.approx(25.0)


# ------------------------------------------------------------------
# ResponseTracker — source breakdown
# ------------------------------------------------------------------


class TestResponseTrackerSources:
    def test_source_counts(self):
        t = ResponseTracker()
        t.record("2026-10-23T12:00:00+00:00", "2026-10-23T12:05:00+00:00", source="caretaker")
        t.record("2026-10-23T13:00:00+00:00", "2026-10-23T13:05:00+00:00", source="cron")
        t.record("2026-10-23T14:00:00+00:00", "2026-10-23T14:05:00+00:00", source="caretaker")
        assert t.source_counts() == {"caretaker": 2, "cron": 1}

    def test_mean_latency_by_source(self):
        t = ResponseTracker()
        t.record("2026-10-23T12:00:00+00:00", "2026-10-23T12:05:00+00:00", source="caretaker")  # 300
        t.record("2026-10-23T13:00:00+00:00", "2026-10-23T13:10:00+00:00", source="cron")  # 600
        t.record("2026-10-23T14:00:00+00:00", "2026-10-23T14:15:00+00:00", source="caretaker")  # 900
        by_src = t.mean_latency_by_source()
        assert by_src["caretaker"] == pytest.approx(600.0)
        assert by_src["cron"] == pytest.approx(600.0)


# ------------------------------------------------------------------
# ResponseTracker — trend
# ------------------------------------------------------------------


class TestResponseTrackerTrend:
    def test_improving(self):
        t = ResponseTracker(caretaker_cadence_s=600)
        # first half: slow (1800s each), second half: fast (60s each)
        t.record("2026-10-23T12:00:00+00:00", "2026-10-23T12:30:00+00:00")
        t.record("2026-10-23T13:00:00+00:00", "2026-10-23T13:30:00+00:00")
        t.record("2026-10-23T14:00:00+00:00", "2026-10-23T14:01:00+00:00")
        t.record("2026-10-23T15:00:00+00:00", "2026-10-23T15:01:00+00:00")
        assert t.trend() == "improving"

    def test_worsening(self):
        t = ResponseTracker(caretaker_cadence_s=600)
        # first half: fast (60s), second half: slow (1800s)
        t.record("2026-10-23T12:00:00+00:00", "2026-10-23T12:01:00+00:00")
        t.record("2026-10-23T13:00:00+00:00", "2026-10-23T13:01:00+00:00")
        t.record("2026-10-23T14:00:00+00:00", "2026-10-23T14:30:00+00:00")
        t.record("2026-10-23T15:00:00+00:00", "2026-10-23T15:30:00+00:00")
        assert t.trend() == "worsening"

    def test_stable_few_events(self):
        t = ResponseTracker()
        t.record("2026-10-23T12:00:00+00:00", "2026-10-23T12:05:00+00:00")
        assert t.trend() == "stable"

    def test_stable_same(self):
        t = ResponseTracker(caretaker_cadence_s=600)
        for i in range(6):
            h = 12 + i
            t.record(
                f"2026-10-23T{h:02d}:00:00+00:00",
                f"2026-10-23T{h:02d}:05:00+00:00",
            )
        assert t.trend() == "stable"


# ------------------------------------------------------------------
# ResponseTracker — health
# ------------------------------------------------------------------


class TestResponseTrackerHealth:
    def test_responsive_empty(self):
        assert ResponseTracker().health() == "responsive"

    def test_responsive_all_fast(self):
        t = ResponseTracker(caretaker_cadence_s=600)
        t.record("2026-10-23T12:00:00+00:00", "2026-10-23T12:05:00+00:00")
        t.record("2026-10-23T13:00:00+00:00", "2026-10-23T13:08:00+00:00")
        assert t.health() == "responsive"

    def test_lagging(self):
        t = ResponseTracker(caretaker_cadence_s=600)
        # mean = (1500+1500)/2 = 1500 > 2*600=1200, no missed
        t.record("2026-10-23T12:00:00+00:00", "2026-10-23T12:25:00+00:00")
        t.record("2026-10-23T13:00:00+00:00", "2026-10-23T13:25:00+00:00")
        assert t.health() == "lagging"

    def test_absent_missed_present(self):
        t = ResponseTracker(caretaker_cadence_s=600)
        t.record("2026-10-23T12:00:00+00:00", "2026-10-23T12:05:00+00:00")  # fast
        t.record("2026-10-23T14:00:00+00:00", "2026-10-23T16:00:00+00:00")  # missed
        assert t.health() == "absent"


# ------------------------------------------------------------------
# ResponseTracker — reporting
# ------------------------------------------------------------------


class TestResponseTrackerReporting:
    def test_summarize_keys(self):
        t = ResponseTracker()
        t.record("2026-10-23T12:00:00+00:00", "2026-10-23T12:05:00+00:00")
        s = t.summarize()
        expected_keys = {
            "count", "caretaker_cadence_s", "writer_cadence_s",
            "mean_latency_s", "median_latency_s",
            "worst_latency_s", "best_latency_s",
            "total_lost_strokes", "tier_counts",
            "fast_pct", "slow_pct", "missed_pct",
            "source_counts", "health", "trend",
        }
        assert set(s.keys()) == expected_keys

    def test_report_line_contains_key_info(self):
        t = ResponseTracker(caretaker_cadence_s=600)
        t.record("2026-10-23T12:00:00+00:00", "2026-10-23T12:05:00+00:00")
        line = t.report_line()
        assert "caretaker_response" in line
        assert "responsive" in line
        assert "1 events" in line

    def test_reset(self):
        t = ResponseTracker()
        t.record("2026-10-23T12:00:00+00:00", "2026-10-23T12:05:00+00:00")
        assert t.count == 1
        t.reset()
        assert t.count == 0


# ------------------------------------------------------------------
# Median edge cases
# ------------------------------------------------------------------


class TestMedianEdgeCases:
    def test_single_event(self):
        t = ResponseTracker()
        t.record("2026-10-23T12:00:00+00:00", "2026-10-23T12:05:00+00:00")
        assert t.median_latency_s() == pytest.approx(300.0)

    def test_even_count(self):
        t = ResponseTracker()
        t.record("2026-10-23T12:00:00+00:00", "2026-10-23T12:05:00+00:00")  # 300
        t.record("2026-10-23T13:00:00+00:00", "2026-10-23T13:10:00+00:00")  # 600
        # median of [300, 600] = 450
        assert t.median_latency_s() == pytest.approx(450.0)
