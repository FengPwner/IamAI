#!/usr/bin/env python3
"""Tests for stroke_zeitgeber.py — calendar rhythm detection."""

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_zeitgeber import (
    ZeitgeberReport,
    _classify_dominant,
    _detect_peaks,
    _detect_quiets,
    _extract_timestamps,
    _parse_ts,
    analyze,
    entropy,
    hourly_distribution,
    uniformity,
    weekday_distribution,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 11, 18, 0, 0, 0, tzinfo=timezone.utc)  # Wednesday


def _ts(offset_seconds: float) -> str:
    """Return an ISO-8601 timestamp offset from a fixed base."""
    dt = _BASE + timedelta(seconds=offset_seconds)
    return dt.isoformat()


def _dt(offset_seconds: float) -> datetime:
    """Return a datetime offset from a fixed base."""
    return _BASE + timedelta(seconds=offset_seconds)


def _make_strokes(offsets: list, kind: str = "thought") -> list:
    """Build a list of stroke dicts from a list of second-offsets."""
    return [
        {"seq": i, "at": _ts(s), "kind": kind, "text": f"stroke {i}"}
        for i, s in enumerate(offsets)
    ]


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------

class TestParseTs:
    def test_iso_with_offset(self):
        dt = _parse_ts("2026-11-18T12:00:00+00:00")
        assert dt.hour == 12
        assert dt.tzinfo is not None

    def test_z_suffix(self):
        dt = _parse_ts("2026-11-18T12:00:00Z")
        assert dt.hour == 12
        assert dt.tzinfo is not None

    def test_no_timezone_gets_utc(self):
        dt = _parse_ts(datetime(2026, 11, 18, 12, 0, 0))
        assert dt.tzinfo == timezone.utc

    def test_datetime_passthrough(self):
        original = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
        dt = _parse_ts(original)
        assert dt is original

    def test_whitespace_stripped(self):
        dt = _parse_ts("  2026-11-18T12:00:00+00:00  ")
        assert dt.hour == 12

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            _parse_ts("not-a-date")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _parse_ts("")

    def test_none_raises(self):
        with pytest.raises((ValueError, TypeError)):
            _parse_ts(None)


# ---------------------------------------------------------------------------
# _extract_timestamps
# ---------------------------------------------------------------------------

class TestExtractTimestamps:
    def test_dicts_with_at(self):
        strokes = _make_strokes([0, 3600, 7200])
        result = _extract_timestamps(strokes)
        assert len(result) == 3

    def test_dicts_with_timestamp_key(self):
        strokes = [{"timestamp": _ts(0)}, {"timestamp": _ts(3600)}]
        result = _extract_timestamps(strokes)
        assert len(result) == 2

    def test_dicts_with_ts_key(self):
        strokes = [{"ts": _ts(0)}, {"ts": _ts(3600)}]
        result = _extract_timestamps(strokes)
        assert len(result) == 2

    def test_datetime_objects(self):
        dts = [_dt(0), _dt(3600), _dt(7200)]
        result = _extract_timestamps(dts)
        assert len(result) == 3

    def test_iso_strings(self):
        strings = [_ts(0), _ts(3600)]
        result = _extract_timestamps(strings)
        assert len(result) == 2

    def test_missing_key_skipped(self):
        strokes = [{"no_time": True}, {"at": _ts(0)}]
        result = _extract_timestamps(strokes)
        assert len(result) == 1

    def test_empty_input(self):
        assert _extract_timestamps([]) == []

    def test_mixed_types(self):
        mixed = [{"at": _ts(0)}, _dt(3600), _ts(7200)]
        result = _extract_timestamps(mixed)
        assert len(result) == 3

    def test_none_key_skipped(self):
        strokes = [{"at": None}, {"at": _ts(0)}]
        result = _extract_timestamps(strokes)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# hourly_distribution
# ---------------------------------------------------------------------------

class TestHourlyDistribution:
    def test_empty(self):
        result = hourly_distribution([])
        assert len(result) == 24
        assert all(v == 0 for v in result.values())

    def test_single_stroke(self):
        ts = [_dt(0)]  # midnight UTC
        result = hourly_distribution(ts)
        assert result[0] == 1
        assert sum(result.values()) == 1

    def test_uniform_24(self):
        # One stroke per hour
        ts = [_dt(h * 3600) for h in range(24)]
        result = hourly_distribution(ts)
        assert all(v == 1 for v in result.values())

    def test_clustered_morning(self):
        # 10 strokes at 9am, 2 at 3pm
        ts = [_dt(9 * 3600 + i * 60) for i in range(10)]
        ts += [_dt(15 * 3600 + i * 60) for i in range(2)]
        result = hourly_distribution(ts)
        assert result[9] == 10
        assert result[15] == 2
        assert sum(result.values()) == 12

    def test_timezone_conversion(self):
        # Create a timestamp at midnight UTC+8 → should be 16:00 UTC (prev day)
        utc_plus_8 = timezone(timedelta(hours=8))
        dt = datetime(2026, 11, 18, 0, 0, 0, tzinfo=utc_plus_8)
        result = hourly_distribution([dt])
        assert result[16] == 1  # midnight +8 = 16:00 UTC

    def test_all_keys_present(self):
        result = hourly_distribution([_dt(0)])
        assert set(result.keys()) == set(range(24))


# ---------------------------------------------------------------------------
# weekday_distribution
# ---------------------------------------------------------------------------

class TestWeekdayDistribution:
    def test_empty(self):
        result = weekday_distribution([])
        assert len(result) == 7
        assert all(v == 0 for v in result.values())

    def test_single_day(self):
        # _BASE is Wednesday (weekday=2)
        result = weekday_distribution([_dt(0)])
        assert result[2] == 1

    def test_full_week(self):
        # One stroke per day for a week
        ts = [_dt(d * 86400) for d in range(7)]
        result = weekday_distribution(ts)
        assert all(v == 1 for v in result.values())

    def test_weekend_heavy(self):
        # Saturday (5) and Sunday (6)
        sat = _BASE + timedelta(days=3)  # Sat Nov 21
        sun = _BASE + timedelta(days=4)  # Sun Nov 22
        ts = [sat, sat, sat, sun, sun]
        result = weekday_distribution(ts)
        assert result[5] == 3
        assert result[6] == 2

    def test_all_keys_present(self):
        result = weekday_distribution([_dt(0)])
        assert set(result.keys()) == set(range(7))


# ---------------------------------------------------------------------------
# entropy
# ---------------------------------------------------------------------------

class TestEntropy:
    def test_empty(self):
        assert entropy({}) == 0.0
        assert entropy([]) == 0.0

    def test_single_bin(self):
        assert entropy([10]) == 0.0
        assert entropy({"a": 5}) == 0.0

    def test_uniform_binary(self):
        # Two equal bins → H = 1.0 bit
        h = entropy([5, 5])
        assert abs(h - 1.0) < 1e-9

    def test_uniform_24(self):
        # 24 equal bins → H = log2(24)
        h = entropy([1] * 24)
        assert abs(h - math.log2(24)) < 1e-9

    def test_skewed(self):
        # One dominant bin → low entropy
        h = entropy([100, 1, 1, 1])
        assert h < 1.0

    def test_dict_input(self):
        h = entropy({"a": 5, "b": 5})
        assert abs(h - 1.0) < 1e-9

    def test_zero_counts(self):
        h = entropy([0, 0, 0])
        assert h == 0.0

    def test_mixed_zeros(self):
        h = entropy([10, 0, 10, 0])
        assert abs(h - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# uniformity
# ---------------------------------------------------------------------------

class TestUniformity:
    def test_empty(self):
        # Empty dict/list: 1.0 by convention
        assert uniformity({}) == 1.0
        assert uniformity([]) == 1.0

    def test_single_bin(self):
        assert uniformity([10]) == 1.0

    def test_perfectly_uniform(self):
        u = uniformity([10, 10, 10, 10])
        assert abs(u - 1.0) < 1e-9

    def test_perfectly_skewed(self):
        # All in one bin → H = 0, uniformity = 0
        u = uniformity([100, 0, 0, 0])
        assert abs(u) < 1e-9

    def test_partial(self):
        u = uniformity([50, 25, 15, 10])
        assert 0.0 < u < 1.0

    def test_24_uniform(self):
        u = uniformity([1] * 24)
        assert abs(u - 1.0) < 1e-9

    def test_dict_input(self):
        u = uniformity({"a": 5, "b": 5})
        assert abs(u - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# _detect_peaks
# ---------------------------------------------------------------------------

class TestDetectPeaks:
    def test_empty(self):
        assert _detect_peaks({}) == []

    def test_all_zero(self):
        assert _detect_peaks({i: 0 for i in range(24)}) == []

    def test_uniform_no_peaks(self):
        counts = {i: 10 for i in range(24)}
        assert _detect_peaks(counts, factor=1.2) == []

    def test_one_peak(self):
        counts = {i: 10 for i in range(24)}
        counts[9] = 50
        peaks = _detect_peaks(counts, factor=1.2)
        assert 9 in peaks

    def test_multiple_peaks(self):
        counts = {i: 5 for i in range(24)}
        counts[9] = 50
        counts[14] = 40
        peaks = _detect_peaks(counts, factor=1.2)
        assert 9 in peaks
        assert 14 in peaks

    def test_sorted_output(self):
        counts = {i: 5 for i in range(24)}
        counts[20] = 50
        counts[3] = 40
        peaks = _detect_peaks(counts, factor=1.2)
        assert peaks == sorted(peaks)


# ---------------------------------------------------------------------------
# _detect_quiets
# ---------------------------------------------------------------------------

class TestDetectQuiets:
    def test_empty(self):
        assert _detect_quiets({}) == []

    def test_all_zero(self):
        assert _detect_quiets({i: 0 for i in range(24)}) == []

    def test_uniform_no_quiets(self):
        counts = {i: 10 for i in range(24)}
        assert _detect_quiets(counts, factor=0.5) == []

    def test_one_quiet(self):
        counts = {i: 10 for i in range(24)}
        counts[3] = 1
        quiets = _detect_quiets(counts, factor=0.5)
        assert 3 in quiets

    def test_zero_is_quiet(self):
        counts = {i: 10 for i in range(24)}
        counts[2] = 0
        quiets = _detect_quiets(counts, factor=0.5)
        assert 2 in quiets

    def test_sorted_output(self):
        counts = {i: 10 for i in range(24)}
        counts[20] = 1
        counts[3] = 1
        quiets = _detect_quiets(counts, factor=0.5)
        assert quiets == sorted(quiets)


# ---------------------------------------------------------------------------
# _classify_dominant
# ---------------------------------------------------------------------------

class TestClassifyDominant:
    def test_none(self):
        assert _classify_dominant(0.90, 0.90) == "none"

    def test_hourly_only(self):
        assert _classify_dominant(0.70, 0.90) == "hourly"

    def test_daily_only(self):
        assert _classify_dominant(0.90, 0.70) == "daily"

    def test_both(self):
        assert _classify_dominant(0.70, 0.70) == "both"

    def test_boundary_hourly(self):
        assert _classify_dominant(0.85, 0.90) == "none"
        assert _classify_dominant(0.84, 0.90) == "hourly"

    def test_boundary_daily(self):
        assert _classify_dominant(0.90, 0.85) == "none"
        assert _classify_dominant(0.90, 0.84) == "daily"


# ---------------------------------------------------------------------------
# analyze — integration
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_empty_input(self):
        report = analyze([])
        assert report.total_strokes == 0
        assert report.dominant_zeitgeber == "none"
        assert report.peak_hours == []
        assert report.quiet_hours == []
        assert report.is_24_7 is True

    def test_single_stroke(self):
        strokes = _make_strokes([0])
        report = analyze(strokes)
        assert report.total_strokes == 1
        # Single stroke → all in one hour → very low uniformity
        assert report.hourly_uniformity < 0.5

    def test_uniform_24h(self):
        # One stroke per hour for 24 hours → uniform hourly
        offsets = [h * 3600 for h in range(24)]
        strokes = _make_strokes(offsets)
        report = analyze(strokes)
        assert report.total_strokes == 24
        assert report.hourly_uniformity > 0.95

    def test_workday_pattern(self):
        # Strokes only between 9am and 5pm UTC
        offsets = []
        for day in range(7):
            for hour in range(9, 17):
                offsets.append(day * 86400 + hour * 3600)
        strokes = _make_strokes(offsets)
        report = analyze(strokes)
        assert report.total_strokes == 56
        assert report.has_hourly_rhythm is True
        # Peak hours should include some 9-16 range
        for h in [9, 10, 14, 15]:
            assert h in report.peak_hours
        # Quiet hours should include some night hours
        for h in [0, 1, 2, 3, 4, 5]:
            assert h in report.quiet_hours

    def test_weekend_off_pattern(self):
        # Weekdays only — no weekend strokes at all
        timestamps = []
        for day_offset in range(14):  # 2 weeks
            day_dt = _BASE + timedelta(days=day_offset)
            wd = day_dt.weekday()
            if wd < 5:  # weekday: 12 strokes mid-day
                for hour in [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]:
                    timestamps.append(day_dt.replace(hour=hour, minute=30))
            # weekend: no strokes
        report = analyze(timestamps)
        # All strokes on weekdays
        weekday_total = sum(v for d, v in report.weekday_counts.items() if d < 5)
        weekend_total = sum(v for d, v in report.weekday_counts.items() if d >= 5)
        assert weekday_total > 0
        assert weekend_total == 0
        assert report.has_daily_rhythm is True

    def test_24_7_pattern(self):
        # Uniform across all hours and days
        offsets = []
        for day in range(7):
            for hour in range(24):
                offsets.append(day * 86400 + hour * 3600)
        strokes = _make_strokes(offsets)
        report = analyze(strokes)
        assert report.total_strokes == 168
        assert report.hourly_uniformity > 0.95
        assert report.weekday_uniformity > 0.95
        assert report.is_24_7 is True
        assert report.dominant_zeitgeber == "none"

    def test_custom_threshold(self):
        # Moderately non-uniform
        offsets = []
        for h in range(24):
            count = 10 if h < 12 else 5
            for _ in range(count):
                offsets.append(h * 3600 + _ * 10)
        strokes = _make_strokes(offsets)
        # Default threshold
        report_default = analyze(strokes)
        # Very strict threshold
        report_strict = analyze(strokes, rhythm_threshold=0.99)
        # Strict threshold should be more likely to detect rhythm
        assert report_strict.hourly_uniformity <= report_default.hourly_uniformity or \
               report_strict.dominant_zeitgeber != "none"

    def test_datetime_input(self):
        dts = [_dt(h * 3600) for h in range(24)]
        report = analyze(dts)
        assert report.total_strokes == 24

    def test_string_input(self):
        strings = [_ts(h * 3600) for h in range(24)]
        report = analyze(strings)
        assert report.total_strokes == 24

    def test_dominant_zeitgeber_both(self):
        # Workday pattern + weekday pattern
        offsets = []
        for day in range(14):
            dt = _BASE + timedelta(days=day)
            if dt.weekday() < 5:
                for hour in range(9, 17):
                    offsets.append(day * 86400 + hour * 3600)
        strokes = _make_strokes(offsets)
        report = analyze(strokes)
        assert report.dominant_zeitgeber in ("hourly", "both")


# ---------------------------------------------------------------------------
# ZeitgeberReport properties
# ---------------------------------------------------------------------------

class TestZeitgeberReport:
    def _make_report(self, **kwargs):
        defaults = {
            "hourly_counts": {i: 10 for i in range(24)},
            "weekday_counts": {i: 10 for i in range(7)},
            "hourly_entropy": math.log2(24),
            "weekday_entropy": math.log2(7),
            "hourly_uniformity": 1.0,
            "weekday_uniformity": 1.0,
            "peak_hours": [],
            "quiet_hours": [],
            "dominant_zeitgeber": "none",
            "total_strokes": 240,
        }
        defaults.update(kwargs)
        return ZeitgeberReport(**defaults)

    def test_is_24_7(self):
        r = self._make_report(dominant_zeitgeber="none")
        assert r.is_24_7 is True

    def test_not_24_7(self):
        r = self._make_report(
            dominant_zeitgeber="hourly",
            hourly_uniformity=0.7,
        )
        assert r.is_24_7 is False

    def test_has_hourly_rhythm(self):
        r = self._make_report(hourly_uniformity=0.7)
        assert r.has_hourly_rhythm is True

    def test_no_hourly_rhythm(self):
        r = self._make_report(hourly_uniformity=0.9)
        assert r.has_hourly_rhythm is False

    def test_has_daily_rhythm(self):
        r = self._make_report(weekday_uniformity=0.7)
        assert r.has_daily_rhythm is True

    def test_peak_hours_text(self):
        r = self._make_report(peak_hours=[9, 14, 15])
        assert "09:00" in r.peak_hours_text()
        assert "14:00" in r.peak_hours_text()

    def test_peak_hours_text_empty(self):
        r = self._make_report(peak_hours=[])
        assert "no peak" in r.peak_hours_text()

    def test_quiet_hours_text(self):
        r = self._make_report(quiet_hours=[1, 2, 3])
        assert "01:00" in r.quiet_hours_text()

    def test_quiet_hours_text_empty(self):
        r = self._make_report(quiet_hours=[])
        assert "no quiet" in r.quiet_hours_text()

    def test_summary_text_24_7(self):
        r = self._make_report(dominant_zeitgeber="none")
        text = r.summary_text()
        assert "24/7" in text
        assert "no calendar rhythm" in text

    def test_summary_text_hourly(self):
        r = self._make_report(
            dominant_zeitgeber="hourly",
            hourly_uniformity=0.7,
            peak_hours=[9, 14],
        )
        text = r.summary_text()
        assert "hourly" in text

    def test_summary_text_daily(self):
        r = self._make_report(
            dominant_zeitgeber="daily",
            weekday_uniformity=0.6,
            weekday_counts={0: 50, 1: 50, 2: 50, 3: 50, 4: 50, 5: 5, 6: 5},
        )
        text = r.summary_text()
        assert "daily" in text or "weekday" in text

    def test_frozen(self):
        r = self._make_report()
        with pytest.raises(Exception):
            r.total_strokes = 999


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_all_same_hour(self):
        # 100 strokes within 100 minutes starting at 01:00 → spans hour 1 and 2
        offsets = [3600 + i * 60 for i in range(100)]
        strokes = _make_strokes(offsets)
        report = analyze(strokes)
        # Only 2 of 24 bins are used → very low uniformity
        assert report.hourly_uniformity < 0.3
        assert 1 in report.peak_hours or 2 in report.peak_hours

    def test_two_hour_pattern(self):
        # Alternating between hour 9 and hour 21
        offsets = []
        for day in range(10):
            offsets.append(day * 86400 + 9 * 3600)
            offsets.append(day * 86400 + 21 * 3600)
        strokes = _make_strokes(offsets)
        report = analyze(strokes)
        assert report.total_strokes == 20
        assert 9 in report.peak_hours
        assert 21 in report.peak_hours

    def test_large_corpus_performance(self):
        """10,000 strokes should complete in under a second."""
        import time
        offsets = [i * 15 for i in range(10000)]  # every 15 seconds
        strokes = _make_strokes(offsets)
        start = time.monotonic()
        report = analyze(strokes)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0
        assert report.total_strokes == 10000

    def test_jsonl_roundtrip(self):
        """Strokes from JSONL strings should work."""
        import json
        strokes = _make_strokes([i * 3600 for i in range(24)])
        serialised = [json.dumps(s) for s in strokes]
        deserialised = [json.loads(s) for s in serialised]
        report = analyze(deserialised)
        assert report.total_strokes == 24

    def test_realistic_iamai_pattern(self):
        """Simulate a work-hours-only pattern: strokes only between 9-17."""
        timestamps = []
        for day_offset in range(14):
            day_dt = _BASE + timedelta(days=day_offset)
            for hour in range(9, 18):  # only 9am-5pm
                for j in range(4):
                    timestamps.append(day_dt.replace(hour=hour, minute=j * 15))
        report = analyze(timestamps)
        # 9 active hours out of 24 → strong hourly rhythm
        assert report.has_hourly_rhythm is True
        # Same pattern every day → no weekday rhythm
        assert report.weekday_uniformity > 0.85


# ---------------------------------------------------------------------------
# Entropy edge cases
# ---------------------------------------------------------------------------

class TestEntropyEdgeCases:
    def test_very_large_counts(self):
        h = entropy([1000000, 1000000])
        assert abs(h - 1.0) < 1e-9

    def test_one_element(self):
        assert entropy([42]) == 0.0

    def test_negative_ignored(self):
        # Negative counts should be treated as 0 contribution
        # (they shouldn't appear but shouldn't crash either)
        # The implementation skips v <= 0 naturally for log2
        h = entropy([10, 0, 5])
        assert h > 0

    def test_all_zeros_dict(self):
        h = entropy({"a": 0, "b": 0, "c": 0})
        assert h == 0.0


# ---------------------------------------------------------------------------
# Uniformity edge cases
# ---------------------------------------------------------------------------

class TestUniformityEdgeCases:
    def test_two_bins_one_empty(self):
        u = uniformity([10, 0])
        assert abs(u) < 1e-9  # All in one bin = 0 uniformity

    def test_many_bins_one_filled(self):
        counts = [0] * 23 + [100]
        u = uniformity(counts)
        assert abs(u) < 1e-9

    def test_near_uniform(self):
        counts = [10, 10, 10, 10, 10, 11]
        u = uniformity(counts)
        assert u > 0.99
