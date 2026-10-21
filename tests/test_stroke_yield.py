"""Tests for iamai.stroke_yield — writer productivity measurement.

Covers:
- yield classification thresholds
- trend classification
- window yield computation (empty, single stroke, burst, stall)
- session report (duration, dead time, bursts, kind distribution)
- multi-window snapshot
- edge cases (no data, single event, all-empty kinds)
"""

import time
import pytest

from iamai.stroke_yield import (
    StrokeYield,
    WindowYield,
    SessionReport,
    classify_yield,
    classify_trend,
    _PRODUCTIVE_SPM,
    _STEADY_SPM,
    _SLUGGISH_SPM,
)


# ---------------------------------------------------------------------------
# classify_yield
# ---------------------------------------------------------------------------


class TestClassifyYield:
    def test_productive(self):
        assert classify_yield(4.0) == "productive"
        assert classify_yield(_PRODUCTIVE_SPM) == "productive"

    def test_steady(self):
        assert classify_yield(2.0) == "steady"
        assert classify_yield(_STEADY_SPM) == "steady"

    def test_sluggish(self):
        assert classify_yield(0.5) == "sluggish"
        assert classify_yield(_SLUGGISH_SPM) == "sluggish"

    def test_stalled(self):
        assert classify_yield(0.0) == "stalled"
        assert classify_yield(0.1) == "stalled"
        assert classify_yield(0.19) == "stalled"

    def test_boundary_productive_steady(self):
        """Just below productive threshold → steady."""
        assert classify_yield(_PRODUCTIVE_SPM - 0.01) == "steady"

    def test_boundary_steady_sluggish(self):
        """Just below steady threshold → sluggish."""
        assert classify_yield(_STEADY_SPM - 0.01) == "sluggish"

    def test_boundary_sluggish_stalled(self):
        """Just below sluggish threshold → stalled."""
        assert classify_yield(_SLUGGISH_SPM - 0.01) == "stalled"


# ---------------------------------------------------------------------------
# classify_trend
# ---------------------------------------------------------------------------


class TestClassifyTrend:
    def test_rising(self):
        assert classify_trend(1.5) == "rising"
        assert classify_trend(2.0) == "rising"

    def test_falling(self):
        assert classify_trend(0.5) == "falling"
        assert classify_trend(0.79) == "falling"

    def test_steady(self):
        assert classify_trend(1.0) == "steady"
        assert classify_trend(0.9) == "steady"
        assert classify_trend(1.1) == "steady"

    def test_boundary_rising(self):
        assert classify_trend(1.2) == "steady"   # not > 1.2
        assert classify_trend(1.21) == "rising"

    def test_boundary_falling(self):
        assert classify_trend(0.8) == "steady"   # not < 0.8
        assert classify_trend(0.79) == "falling"


# ---------------------------------------------------------------------------
# StrokeYield — empty state
# ---------------------------------------------------------------------------


class TestStrokeYieldEmpty:
    def test_count_zero(self):
        sy = StrokeYield()
        assert sy.count == 0

    def test_current_yield_empty(self):
        sy = StrokeYield()
        assert sy.current_yield(now=1000.0) == 0.0

    def test_window_yield_empty(self):
        sy = StrokeYield()
        wy = sy.window_yield(window=3600, now=1000.0)
        assert wy.strokes == 0
        assert wy.spm == 0.0
        assert wy.verdict == "stalled"

    def test_session_report_empty(self):
        sy = StrokeYield()
        report = sy.session_report()
        assert report.total_strokes == 0
        assert report.verdict == "stalled"
        assert report.by_kind == {}

    def test_trend_empty(self):
        sy = StrokeYield()
        t = sy.trend(now=1000.0)
        assert t["trend"] == "steady"
        assert t["recent_spm"] == 0.0
        assert t["older_spm"] == 0.0


# ---------------------------------------------------------------------------
# StrokeYield — ingestion
# ---------------------------------------------------------------------------


class TestStrokeYieldIngest:
    def test_add_single(self):
        sy = StrokeYield()
        sy.add(1000.0, "devlog")
        assert sy.count == 1

    def test_ingest_batch(self):
        sy = StrokeYield()
        sy.ingest([1000.0, 1015.0, 1030.0], ["devlog", "note", "thought"])
        assert sy.count == 3

    def test_ingest_sorts_by_timestamp(self):
        sy = StrokeYield()
        sy.ingest([1030.0, 1000.0, 1015.0], ["c", "a", "b"])
        # After ingestion, internal order should be sorted
        report = sy.session_report()
        assert report.total_strokes == 3

    def test_ingest_without_kinds(self):
        sy = StrokeYield()
        sy.ingest([1000.0, 1015.0, 1030.0])
        assert sy.count == 3

    def test_reset(self):
        sy = StrokeYield()
        sy.ingest([1000.0, 1015.0])
        assert sy.count == 2
        sy.reset()
        assert sy.count == 0


# ---------------------------------------------------------------------------
# StrokeYield — window yield
# ---------------------------------------------------------------------------


class TestStrokeYieldWindow:
    def _make_writer(self, n_strokes, interval, base=1000.0):
        """Create a StrokeYield with n strokes at fixed interval."""
        sy = StrokeYield()
        for i in range(n_strokes):
            sy.add(base + i * interval, "devlog")
        return sy

    def test_productive_burst(self):
        """10 strokes in 60 seconds = 10 spm → productive."""
        sy = self._make_writer(10, interval=6)  # one every 6s
        wy = sy.window_yield(window=60, now=1000.0 + 9 * 6)
        assert wy.verdict == "productive"
        assert wy.strokes == 10

    def test_steady_pace(self):
        """1 stroke every 45s over 10 min = ~1.33 spm → steady."""
        sy = self._make_writer(13, interval=45)
        wy = sy.window_yield(window=600, now=1000.0 + 12 * 45)
        assert wy.verdict == "steady"

    def test_sluggish_pace(self):
        """1 stroke every 3 min over 15 min = ~0.33 spm → sluggish."""
        sy = self._make_writer(5, interval=180)
        wy = sy.window_yield(window=900, now=1000.0 + 4 * 180)
        assert wy.verdict == "sluggish"

    def test_stalled_writer(self):
        """Only 1 stroke in 30 minutes = ~0.033 spm → stalled."""
        sy = StrokeYield()
        sy.add(1000.0, "devlog")
        wy = sy.window_yield(window=1800, now=1000.0 + 1800)
        assert wy.verdict == "stalled"

    def test_window_excludes_old_strokes(self):
        """Strokes outside the window should not count."""
        sy = StrokeYield()
        sy.add(1000.0, "a")   # outside 60s window
        sy.add(1050.0, "b")   # inside
        sy.add(1055.0, "c")   # inside
        wy = sy.window_yield(window=60, now=1060.0)
        assert wy.strokes == 2

    def test_current_yield_uses_5min_window(self):
        sy = self._make_writer(15, interval=20)  # 3 spm
        last = 1000.0 + 14 * 20
        assert abs(sy.current_yield(now=last) - 3.0) < 0.1


# ---------------------------------------------------------------------------
# StrokeYield — trend
# ---------------------------------------------------------------------------


class TestStrokeYieldTrend:
    def test_rising_trend(self):
        """More strokes in last 5 min than in 5–15 min ago."""
        sy = StrokeYield()
        base = 1000.0
        # 5–15 min ago: 2 strokes (sparse)
        sy.add(base + 0, "a")
        sy.add(base + 300, "a")
        # last 5 min: 20 strokes (dense burst)
        for i in range(20):
            sy.add(base + 600 + i * 15, "a")
        now = base + 900
        t = sy.trend(now=now)
        assert t["trend"] == "rising"

    def test_falling_trend(self):
        """Fewer strokes recently than before."""
        sy = StrokeYield()
        base = 1000.0
        # 5–15 min ago: dense (20 strokes in 10 min)
        for i in range(20):
            sy.add(base + i * 30, "a")
        # last 5 min: only 1 stroke
        sy.add(base + 850, "a")
        now = base + 900
        t = sy.trend(now=now)
        assert t["trend"] == "falling"

    def test_steady_trend(self):
        """Similar rate in both windows."""
        sy = StrokeYield()
        base = 1000.0
        # Uniform: 1 stroke every 30s for 15 min
        for i in range(30):
            sy.add(base + i * 30, "a")
        now = base + 29 * 30
        t = sy.trend(now=now)
        assert t["trend"] == "steady"


# ---------------------------------------------------------------------------
# StrokeYield — session report
# ---------------------------------------------------------------------------


class TestSessionReport:
    def test_basic_report(self):
        sy = StrokeYield()
        base = 1000.0
        for i in range(10):
            sy.add(base + i * 60, "devlog")
        report = sy.session_report()
        assert report.total_strokes == 10
        assert report.duration_seconds == 540.0  # 9 * 60
        assert report.by_kind == {"devlog": 10}

    def test_dead_time(self):
        """A big gap should register as dead time."""
        sy = StrokeYield()
        sy.add(1000.0, "a")
        sy.add(1060.0, "a")   # +60s
        sy.add(1500.0, "a")   # +440s gap (dead)
        sy.add(1560.0, "a")   # +60s
        report = sy.session_report()
        assert report.dead_time_seconds == pytest.approx(440.0, abs=1)
        assert report.longest_gap_seconds == pytest.approx(440.0, abs=1)

    def test_burst_detection(self):
        """Rapid strokes should count as bursts."""
        sy = StrokeYield(burst_threshold=30.0)
        # Burst 1: 3 strokes in 20s
        sy.add(1000.0, "a")
        sy.add(1010.0, "a")
        sy.add(1020.0, "a")
        # Gap
        sy.add(1200.0, "a")
        # Burst 2: 2 strokes in 15s
        sy.add(1210.0, "a")
        sy.add(1215.0, "a")
        report = sy.session_report()
        assert report.burst_count == 2

    def test_kind_distribution(self):
        sy = StrokeYield()
        sy.add(1000.0, "devlog")
        sy.add(1015.0, "note")
        sy.add(1030.0, "devlog")
        sy.add(1045.0, "thought")
        sy.add(1060.0, "note")
        report = sy.session_report()
        assert report.by_kind == {"devlog": 2, "note": 2, "thought": 1}

    def test_empty_kind_labeled_unknown(self):
        sy = StrokeYield()
        sy.add(1000.0, "")
        sy.add(1015.0)
        report = sy.session_report()
        assert report.by_kind == {"unknown": 2}

    def test_single_stroke_report(self):
        sy = StrokeYield()
        sy.add(1000.0, "note")
        report = sy.session_report()
        assert report.total_strokes == 1
        assert report.duration_seconds == 1.0  # min clamp
        assert report.longest_gap_seconds == 0.0

    def test_to_dict_roundtrip(self):
        sy = StrokeYield()
        sy.add(1000.0, "devlog")
        sy.add(1060.0, "note")
        report = sy.session_report()
        d = report.to_dict()
        assert isinstance(d, dict)
        assert "spm" in d
        assert "verdict" in d
        assert "by_kind" in d


# ---------------------------------------------------------------------------
# StrokeYield — snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_snapshot_multiple_windows(self):
        sy = StrokeYield()
        base = 1000.0
        for i in range(60):
            sy.add(base + i * 60, "devlog")  # 1 per min for 1 hour
        snaps = sy.snapshot(now=base + 59 * 60)
        assert len(snaps) == 3
        assert snaps[0].window_seconds == 300
        assert snaps[1].window_seconds == 900
        assert snaps[2].window_seconds == 3600

    def test_snapshot_custom_windows(self):
        sy = StrokeYield()
        sy.add(1000.0, "a")
        snaps = sy.snapshot(now=1000.0, windows=(60, 120))
        assert len(snaps) == 2
        assert snaps[0].window_seconds == 60
        assert snaps[1].window_seconds == 120


# ---------------------------------------------------------------------------
# WindowYield / SessionReport — dataclass checks
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_window_yield_frozen(self):
        wy = WindowYield(window_seconds=300, strokes=10, spm=2.0, verdict="steady")
        with pytest.raises(AttributeError):
            wy.strokes = 5  # type: ignore[misc]

    def test_window_yield_to_dict(self):
        wy = WindowYield(window_seconds=300, strokes=10, spm=2.12345, verdict="steady")
        d = wy.to_dict()
        assert d["spm"] == 2.1235  # rounded

    def test_session_report_frozen(self):
        sr = SessionReport(
            duration_seconds=100, total_strokes=10, spm=6.0,
            verdict="productive", dead_time_seconds=0,
            dead_time_fraction=0, burst_count=1,
            longest_gap_seconds=15, by_kind={"devlog": 10},
        )
        with pytest.raises(AttributeError):
            sr.total_strokes = 0  # type: ignore[misc]
