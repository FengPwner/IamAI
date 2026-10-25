"""Tests for iamai.writer_heartbeat — live-writer stall detection."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.writer_heartbeat import (
    DEFAULT_CADENCE,
    DEFAULT_WINDOW,
    STALL_MULTIPLE,
    _parse_iso,
    _tail_timestamps,
    diagnose,
    pulse,
    report,
    stats,
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
# _parse_iso
# ---------------------------------------------------------------------------

class TestParseIso:
    def test_z_suffix(self):
        assert _parse_iso("2026-10-19T00:00:00Z") == BASE.timestamp()

    def test_offset_suffix(self):
        dt = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
        assert _parse_iso("2026-10-19T08:00:00+00:00") == dt.timestamp()

    def test_garbage_raises(self):
        with pytest.raises(ValueError):
            _parse_iso("not-a-date")


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

    def test_reads_last_n_plus_one(self, tmp_path: Path):
        ts = _series(BASE, timedelta(seconds=15), 20)
        f = tmp_path / "strokes.jsonl"
        _write_strokes(f, ts)
        out = _tail_timestamps(f, n=4)
        assert len(out) == 5
        # should be the *last* 5 timestamps, not the first 5
        expected = sorted(_parse_iso(t) for t in ts[-5:])
        assert out == pytest.approx(expected, abs=1e-3)

    def test_skips_malformed_rows(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        lines = []
        for i, t in enumerate(_series(BASE, timedelta(seconds=15), 5)):
            if i == 2:
                lines.append("not json at all\n")
            else:
                lines.append(json.dumps({"seq": i, "at": t, "kind": "n"}) + "\n")
        f.write_text("".join(lines))
        out = _tail_timestamps(f, n=10)
        assert len(out) == 4  # 5 good rows - 1 malformed = 4

    def test_skips_rows_without_at(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        f.write_text(json.dumps({"seq": 1}) + "\n")
        f.write_text(json.dumps({"seq": 2, "at": _iso(BASE)}) + "\n")
        out = _tail_timestamps(f, n=5)
        assert len(out) == 1


# ---------------------------------------------------------------------------
# pulse
# ---------------------------------------------------------------------------

class TestPulse:
    def test_zero_window(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        _write_strokes(f, _series(BASE, timedelta(seconds=15), 10))
        assert pulse(f, window=0) == []

    def test_negative_window(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        _write_strokes(f, _series(BASE, timedelta(seconds=15), 10))
        assert pulse(f, window=-3) == []

    def test_fewer_rows_than_window(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        _write_strokes(f, _series(BASE, timedelta(seconds=15), 3))
        gaps = pulse(f, window=10)
        assert len(gaps) == 2  # 3 rows → 2 gaps

    def test_regular_cadence(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        _write_strokes(f, _series(BASE, timedelta(seconds=15), 20))
        gaps = pulse(f, window=5)
        assert len(gaps) == 5
        assert all(g == pytest.approx(15.0, abs=1e-3) for g in gaps)

    def test_irregular_gaps_preserved(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        ts = [
            _iso(BASE),
            _iso(BASE + timedelta(seconds=10)),
            _iso(BASE + timedelta(seconds=100)),   # 90s gap
            _iso(BASE + timedelta(seconds=110)),
            _iso(BASE + timedelta(seconds=500)),   # 390s gap
        ]
        _write_strokes(f, ts)
        gaps = pulse(f, window=10)
        assert gaps == pytest.approx([10.0, 90.0, 10.0, 390.0], abs=1e-3)


# ---------------------------------------------------------------------------
# diagnose
# ---------------------------------------------------------------------------

class TestDiagnose:
    def test_empty_is_unknown(self):
        assert diagnose([], cadence=15) == "unknown"

    def test_healthy_when_all_small(self):
        assert diagnose([14, 16, 15, 20], cadence=15) == "healthy"

    def test_irregular_on_moderate_gap(self):
        # stall ceiling = 20 × 15 = 300; 120s is below that, above 2×15=30
        assert diagnose([15, 15, 120, 15], cadence=15) == "irregular"

    def test_stalled_on_large_gap(self):
        assert diagnose([15, 15, 600, 15], cadence=15) == "stalled"

    def test_boundary_exactly_at_healthy_ceiling_is_irregular(self):
        # worst == 2 × cadence → NOT strictly less → irregular
        assert diagnose([15, 30], cadence=15) == "irregular"

    def test_boundary_exactly_at_stall_ceiling_is_stalled(self):
        # worst == stall_multiple × cadence → stalled
        assert diagnose([15, 300], cadence=15) == "stalled"

    def test_custom_cadence(self):
        assert diagnose([5, 6, 7], cadence=5) == "healthy"
        assert diagnose([5, 50], cadence=5) == "irregular"
        assert diagnose([5, 200], cadence=5) == "stalled"


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

class TestStats:
    def test_empty(self):
        assert stats([]) == (0.0, 0.0, 0.0)

    def test_basic(self):
        lo, mean, hi = stats([10, 20, 30])
        assert lo == 10
        assert mean == 20
        assert hi == 30

    def test_single(self):
        assert stats([42]) == (42, 42, 42)


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

class TestReport:
    def test_missing_file(self, tmp_path: Path):
        out = report(tmp_path / "missing.jsonl")
        assert out.startswith("heartbeat: unknown")

    def test_healthy_report(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        _write_strokes(f, _series(BASE, timedelta(seconds=15), 15))
        out = report(f)
        assert out.startswith("heartbeat: healthy")
        assert "mean=15s" in out

    def test_stalled_report(self, tmp_path: Path):
        f = tmp_path / "strokes.jsonl"
        ts = [_iso(BASE), _iso(BASE + timedelta(seconds=15)),
              _iso(BASE + timedelta(seconds=900))]
        _write_strokes(f, ts)
        out = report(f, window=2)
        assert "stalled" in out


# ---------------------------------------------------------------------------
# module constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_defaults_are_sane(self):
        assert DEFAULT_CADENCE == 15
        assert DEFAULT_WINDOW == 10
        assert STALL_MULTIPLE == 20
