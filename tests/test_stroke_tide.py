"""Tests for iamai.stroke_tide — stroke-rate trend detection."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.stroke_tide import (
    ACCEL_RATIO,
    DECEL_RATIO,
    DEFAULT_CADENCE,
    DEFAULT_WINDOW,
    _gaps,
    _tail_timestamps,
    tide,
    tide_report,
    tide_stats,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_strokes(path: Path, timestamps: list[str]) -> None:
    """Build a strokes.jsonl with the given ISO timestamps."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for i, ts in enumerate(timestamps, start=1):
            f.write(
                json.dumps(
                    {"seq": i, "at": ts, "kind": "note", "text": f"stroke {i}"}
                )
                + "\n"
            )


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _series(start: datetime, step: timedelta, n: int) -> list[str]:
    return [_iso(start + step * i) for i in range(n)]


BASE = datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# _gaps
# ---------------------------------------------------------------------------

class TestGaps:
    def test_empty(self):
        assert _gaps([]) == []

    def test_single(self):
        assert _gaps([100.0]) == []

    def test_two(self):
        assert _gaps([100.0, 115.0]) == [15.0]

    def test_three(self):
        assert _gaps([100.0, 115.0, 135.0]) == [15.0, 20.0]


# ---------------------------------------------------------------------------
# _tail_timestamps
# ---------------------------------------------------------------------------

class TestTailTimestamps:
    def test_missing_file(self, tmp_path: Path):
        assert _tail_timestamps(tmp_path / "nope.jsonl", n=5) == []

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        f.write_text("")
        assert _tail_timestamps(f, n=5) == []

    def test_returns_last_n(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        ts = _series(BASE, timedelta(seconds=15), 20)
        _write_strokes(f, ts)
        result = _tail_timestamps(f, n=10)
        assert len(result) == 10

    def test_skips_malformed_rows(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 1, "at": _iso(BASE), "kind": "note", "text": "ok"}),
            "not-json",
            json.dumps({"seq": 2, "at": _iso(BASE + timedelta(seconds=15)), "kind": "note", "text": "ok"}),
            json.dumps({"seq": 3, "kind": "note", "text": "no-at"}),  # missing at
            json.dumps({"seq": 4, "at": _iso(BASE + timedelta(seconds=30)), "kind": "note", "text": "ok"}),
        ]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = _tail_timestamps(f, n=10)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# tide — accelerating
# ---------------------------------------------------------------------------

class TestTideAccelerating:
    def test_clear_acceleration(self, tmp_path: Path):
        """First half: 30s gaps.  Second half: 10s gaps."""
        f = tmp_path / "strokes.jsonl"
        # 20 strokes = 19 gaps; split into ~9 first, ~10 second
        timestamps = [BASE]
        # first 9 gaps: 30s each
        for i in range(9):
            timestamps.append(timestamps[-1] + timedelta(seconds=30))
        # next 10 gaps: 10s each
        for i in range(10):
            timestamps.append(timestamps[-1] + timedelta(seconds=10))
        _write_strokes(f, [_iso(t) for t in timestamps])
        assert tide(f, window=20) == "accelerating"

    def test_moderate_acceleration(self, tmp_path: Path):
        """Gaps shrinking by ~30% across the window."""
        f = tmp_path / "strokes.jsonl"
        timestamps = [BASE]
        # first half: 20s gaps
        for _ in range(9):
            timestamps.append(timestamps[-1] + timedelta(seconds=20))
        # second half: 12s gaps
        for _ in range(10):
            timestamps.append(timestamps[-1] + timedelta(seconds=12))
        _write_strokes(f, [_iso(t) for t in timestamps])
        assert tide(f, window=20) == "accelerating"


# ---------------------------------------------------------------------------
# tide — steady
# ---------------------------------------------------------------------------

class TestTideSteady:
    def test_perfectly_steady(self, tmp_path: Path):
        """All gaps identical."""
        f = tmp_path / "strokes.jsonl"
        ts = _series(BASE, timedelta(seconds=15), 20)
        _write_strokes(f, ts)
        assert tide(f, window=20) == "steady"

    def test_slight_variation(self, tmp_path: Path):
        """Gaps vary a little but stay in the steady band."""
        f = tmp_path / "strokes.jsonl"
        timestamps = [BASE]
        gaps = [15, 16, 14, 15, 17, 14, 16, 15, 14,  # first half
                15, 16, 15, 14, 16, 15, 17, 14, 15, 16]  # second half
        for g in gaps:
            timestamps.append(timestamps[-1] + timedelta(seconds=g))
        _write_strokes(f, [_iso(t) for t in timestamps])
        assert tide(f, window=20) == "steady"


# ---------------------------------------------------------------------------
# tide — decelerating
# ---------------------------------------------------------------------------

class TestTideDecelerating:
    def test_clear_deceleration(self, tmp_path: Path):
        """First half: 10s gaps.  Second half: 30s gaps."""
        f = tmp_path / "strokes.jsonl"
        timestamps = [BASE]
        for _ in range(9):
            timestamps.append(timestamps[-1] + timedelta(seconds=10))
        for _ in range(10):
            timestamps.append(timestamps[-1] + timedelta(seconds=30))
        _write_strokes(f, [_iso(t) for t in timestamps])
        assert tide(f, window=20) == "decelerating"

    def test_gradual_deceleration(self, tmp_path: Path):
        """Gaps slowly grow from 15s to ~40s."""
        f = tmp_path / "strokes.jsonl"
        timestamps = [BASE]
        # first half: 15s
        for _ in range(9):
            timestamps.append(timestamps[-1] + timedelta(seconds=15))
        # second half: 35s
        for _ in range(10):
            timestamps.append(timestamps[-1] + timedelta(seconds=35))
        _write_strokes(f, [_iso(t) for t in timestamps])
        assert tide(f, window=20) == "decelerating"


# ---------------------------------------------------------------------------
# tide — unknown
# ---------------------------------------------------------------------------

class TestTideUnknown:
    def test_missing_file(self, tmp_path: Path):
        assert tide(tmp_path / "nope.jsonl") == "unknown"

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        f.write_text("")
        assert tide(f) == "unknown"

    def test_single_stroke(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        _write_strokes(f, [_iso(BASE)])
        assert tide(f) == "unknown"

    def test_two_strokes(self, tmp_path: Path):
        """Only one gap — not enough for a split."""
        f = tmp_path / "strokes.jsonl"
        _write_strokes(f, [_iso(BASE), _iso(BASE + timedelta(seconds=15))])
        assert tide(f) == "unknown"

    def test_three_strokes(self, tmp_path: Path):
        """Two gaps — just barely enough for a split (1 first, 1 second)."""
        f = tmp_path / "strokes.jsonl"
        ts = _series(BASE, timedelta(seconds=15), 3)
        _write_strokes(f, ts)
        # With 2 gaps: mid=1, first=[gap0], second=[gap1]. Both same → steady.
        assert tide(f) == "steady"


# ---------------------------------------------------------------------------
# tide_stats
# ---------------------------------------------------------------------------

class TestTideStats:
    def test_unknown_stats(self, tmp_path: Path):
        s = tide_stats(tmp_path / "nope.jsonl")
        assert s["verdict"] == "unknown"
        assert s["stroke_count"] == 0
        assert s["ratio"] is None

    def test_steady_stats(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        ts = _series(BASE, timedelta(seconds=15), 20)
        _write_strokes(f, ts)
        s = tide_stats(f, window=20)
        assert s["verdict"] == "steady"
        assert s["stroke_count"] == 20
        assert s["first_half_median"] == 15.0
        assert s["second_half_median"] == 15.0
        assert s["ratio"] == 1.0

    def test_decelerating_stats(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        timestamps = [BASE]
        for _ in range(9):
            timestamps.append(timestamps[-1] + timedelta(seconds=10))
        for _ in range(10):
            timestamps.append(timestamps[-1] + timedelta(seconds=30))
        _write_strokes(f, [_iso(t) for t in timestamps])
        s = tide_stats(f, window=20)
        assert s["verdict"] == "decelerating"
        assert s["second_half_median"] > s["first_half_median"]
        assert s["ratio"] > DECEL_RATIO


# ---------------------------------------------------------------------------
# tide_report
# ---------------------------------------------------------------------------

class TestTideReport:
    def test_unknown_report(self, tmp_path: Path):
        r = tide_report(tmp_path / "nope.jsonl")
        assert "unknown" in r
        assert "0 strokes" in r

    def test_steady_report(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        ts = _series(BASE, timedelta(seconds=15), 20)
        _write_strokes(f, ts)
        r = tide_report(f, window=20)
        assert "steady" in r
        assert "15.0s" in r

    def test_report_contains_verdict(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        timestamps = [BASE]
        for _ in range(9):
            timestamps.append(timestamps[-1] + timedelta(seconds=30))
        for _ in range(10):
            timestamps.append(timestamps[-1] + timedelta(seconds=10))
        _write_strokes(f, [_iso(t) for t in timestamps])
        r = tide_report(f, window=20)
        assert "accelerating" in r
