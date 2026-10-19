"""tests for iamai.recovery_latency — stall detection and recovery measurement.

Covers:
- no strokes (empty file)
- single stroke (not enough data)
- all strokes within cadence (no stall)
- single stall gap, recovered
- multiple stall gaps, all recovered
- current stall (last stroke too old, no recovery)
- malformed timestamps (graceful skip)
- stall threshold tuning
- longest gap tracking
- report output format
"""

from __future__ import annotations

import json
import textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

# Ensure the repo root is on sys.path
REPO = Path(__file__).resolve().parent.parent
import sys
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from iamai.recovery_latency import (
    find_stall_gaps,
    measure_recovery,
    recovery_report,
    _parse_iso,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _mk_stroke(seq: int, ts: str, kind: str = "thought") -> dict:
    return {"seq": seq, "at": ts, "kind": kind, "text": f"test stroke {seq}"}


def _write_strokes(path: Path, strokes: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for s in strokes:
            f.write(json.dumps(s) + "\n")


# ---------------------------------------------------------------------------
# _parse_iso
# ---------------------------------------------------------------------------

class TestParseIso:
    def test_standard_format(self):
        dt = _parse_iso("2026-10-19T15:00:00+00:00")
        assert dt.year == 2026
        assert dt.month == 10
        assert dt.hour == 15

    def test_z_suffix(self):
        dt = _parse_iso("2026-10-19T15:00:00Z")
        assert dt.tzinfo is not None

    def test_offset_format(self):
        dt = _parse_iso("2026-10-19T23:00:00+08:00")
        assert dt.utcoffset() == timedelta(hours=8)


# ---------------------------------------------------------------------------
# find_stall_gaps
# ---------------------------------------------------------------------------

class TestFindStallGaps:
    def test_empty_strokes(self):
        assert find_stall_gaps([]) == []

    def test_single_stroke(self):
        strokes = [_mk_stroke(1, "2026-10-19T15:00:00+00:00")]
        assert find_stall_gaps(strokes) == []

    def test_no_gaps(self):
        """All strokes within normal cadence — no stall."""
        base = datetime(2026, 10, 19, 15, 0, 0, tzinfo=timezone.utc)
        strokes = []
        for i in range(10):
            ts = (base + timedelta(seconds=i * 15)).isoformat()
            strokes.append(_mk_stroke(i + 1, ts))
        gaps = find_stall_gaps(strokes, cadence_seconds=15, stall_multiplier=10)
        assert gaps == []

    def test_single_gap_recovered(self):
        """One stall gap followed by recovery."""
        base = datetime(2026, 10, 19, 15, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _mk_stroke(1, base.isoformat()),
            _mk_stroke(2, (base + timedelta(seconds=15)).isoformat()),
            # 300-second gap (20x the 15s cadence)
            _mk_stroke(3, (base + timedelta(seconds=315)).isoformat()),
            _mk_stroke(4, (base + timedelta(seconds=330)).isoformat()),
        ]
        gaps = find_stall_gaps(strokes, cadence_seconds=15, stall_multiplier=10)
        assert len(gaps) == 1
        assert gaps[0]["before_seq"] == 2
        assert gaps[0]["after_seq"] == 3
        assert gaps[0]["gap_seconds"] == pytest.approx(300.0, abs=1)
        assert gaps[0]["recovered"] is True

    def test_multiple_gaps(self):
        """Two separate stall events."""
        base = datetime(2026, 10, 19, 15, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _mk_stroke(1, base.isoformat()),
            _mk_stroke(2, (base + timedelta(seconds=15)).isoformat()),
            # gap 1: 200s
            _mk_stroke(3, (base + timedelta(seconds=215)).isoformat()),
            _mk_stroke(4, (base + timedelta(seconds=230)).isoformat()),
            # gap 2: 500s
            _mk_stroke(5, (base + timedelta(seconds=730)).isoformat()),
            _mk_stroke(6, (base + timedelta(seconds=745)).isoformat()),
        ]
        gaps = find_stall_gaps(strokes, cadence_seconds=15, stall_multiplier=10)
        assert len(gaps) == 2
        assert gaps[0]["gap_seconds"] == pytest.approx(200.0, abs=1)
        assert gaps[1]["gap_seconds"] == pytest.approx(500.0, abs=1)

    def test_malformed_timestamp_skipped(self):
        """Bad timestamps are skipped, not crashed."""
        strokes = [
            _mk_stroke(1, "2026-10-19T15:00:00+00:00"),
            _mk_stroke(2, "NOT_A_TIMESTAMP"),
            _mk_stroke(3, "2026-10-19T15:05:00+00:00"),
        ]
        # Should not raise
        gaps = find_stall_gaps(strokes, cadence_seconds=15, stall_multiplier=10)
        # The gap between stroke 1 and 3 is 300s, but stroke 2 has bad ts
        # so we skip the 1->2 pair. The 2->3 pair also fails to parse.
        # Result depends on which pairs are parseable.
        assert isinstance(gaps, list)

    def test_threshold_tuning(self):
        """A gap that's a stall at 10x might not be at 50x."""
        base = datetime(2026, 10, 19, 15, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _mk_stroke(1, base.isoformat()),
            _mk_stroke(2, (base + timedelta(seconds=200)).isoformat()),
        ]
        # At 10x (150s threshold): 200s gap is a stall
        gaps_strict = find_stall_gaps(strokes, cadence_seconds=15, stall_multiplier=10)
        assert len(gaps_strict) == 1

        # At 50x (750s threshold): 200s gap is NOT a stall
        gaps_loose = find_stall_gaps(strokes, cadence_seconds=15, stall_multiplier=50)
        assert len(gaps_loose) == 0


# ---------------------------------------------------------------------------
# measure_recovery
# ---------------------------------------------------------------------------

class TestMeasureRecovery:
    def test_no_strokes_file(self, tmp_path):
        result = measure_recovery(
            tmp_path,
            strokes_path=tmp_path / "nonexistent.jsonl",
        )
        assert result["stalled"] is False
        assert result["total_stalls"] == 0

    def test_empty_strokes_file(self, tmp_path):
        sp = tmp_path / "data" / "strokes.jsonl"
        sp.parent.mkdir(parents=True)
        sp.write_text("")
        result = measure_recovery(tmp_path, strokes_path=sp)
        assert result["stalled"] is False

    def test_healthy_system(self, tmp_path):
        """All strokes close together, last one is recent."""
        sp = tmp_path / "data" / "strokes.jsonl"
        now = datetime(2026, 10, 19, 15, 10, 0, tzinfo=timezone.utc)
        base = now - timedelta(seconds=30)
        strokes = [
            _mk_stroke(i, (base + timedelta(seconds=i * 15)).isoformat())
            for i in range(1, 4)
        ]
        _write_strokes(sp, strokes)

        result = measure_recovery(
            tmp_path, cadence_seconds=15, stall_multiplier=10, now=now,
            strokes_path=sp,
        )
        assert result["stalled"] is False
        assert result["recovered"] is False

    def test_currently_stalled(self, tmp_path):
        """Last stroke is old — system is currently stalled."""
        sp = tmp_path / "data" / "strokes.jsonl"
        now = datetime(2026, 10, 19, 16, 0, 0, tzinfo=timezone.utc)
        base = now - timedelta(hours=1)
        strokes = [
            _mk_stroke(1, base.isoformat()),
            _mk_stroke(2, (base + timedelta(seconds=15)).isoformat()),
        ]
        _write_strokes(sp, strokes)

        result = measure_recovery(
            tmp_path, cadence_seconds=15, stall_multiplier=10, now=now,
            strokes_path=sp,
        )
        assert result["stalled"] is True
        assert result["recovered"] is False
        assert result["latency_seconds"] > 3000  # ~1 hour
        assert result["total_stalls"] >= 1

    def test_recovered_stall(self, tmp_path):
        """A stall happened and was recovered. System is healthy now."""
        sp = tmp_path / "data" / "strokes.jsonl"
        base = datetime(2026, 10, 19, 15, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _mk_stroke(1, base.isoformat()),
            _mk_stroke(2, (base + timedelta(seconds=15)).isoformat()),
            # 300s stall
            _mk_stroke(3, (base + timedelta(seconds=315)).isoformat()),
            # then healthy cadence resumes
            _mk_stroke(4, (base + timedelta(seconds=330)).isoformat()),
            _mk_stroke(5, (base + timedelta(seconds=345)).isoformat()),
        ]
        _write_strokes(sp, strokes)

        # now is close to the last stroke so the system is NOT currently stalled
        now = base + timedelta(seconds=360)

        result = measure_recovery(
            tmp_path, cadence_seconds=15, stall_multiplier=10, now=now,
            strokes_path=sp,
        )
        assert result["stalled"] is True  # had a stall in history
        assert result["recovered"] is True
        assert result["latency_seconds"] == pytest.approx(300.0, abs=1)

    def test_longest_gap_tracking(self, tmp_path):
        """Longest gap is correctly identified across multiple stalls."""
        sp = tmp_path / "data" / "strokes.jsonl"
        now = datetime(2026, 10, 19, 16, 0, 0, tzinfo=timezone.utc)
        base = datetime(2026, 10, 19, 15, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _mk_stroke(1, base.isoformat()),
            # 200s gap
            _mk_stroke(2, (base + timedelta(seconds=200)).isoformat()),
            _mk_stroke(3, (base + timedelta(seconds=215)).isoformat()),
            # 600s gap
            _mk_stroke(4, (base + timedelta(seconds=815)).isoformat()),
            _mk_stroke(5, (base + timedelta(seconds=830)).isoformat()),
            # 180s gap
            _mk_stroke(6, (base + timedelta(seconds=1010)).isoformat()),
            _mk_stroke(7, (base + timedelta(seconds=1025)).isoformat()),
        ]
        _write_strokes(sp, strokes)

        result = measure_recovery(
            tmp_path, cadence_seconds=15, stall_multiplier=10, now=now,
            strokes_path=sp,
        )
        assert result["longest_gap_seconds"] == pytest.approx(600.0, abs=1)

    def test_recovered_stalls_count(self, tmp_path):
        """Count of recovered stalls is accurate."""
        sp = tmp_path / "data" / "strokes.jsonl"
        base = datetime(2026, 10, 19, 15, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _mk_stroke(1, base.isoformat()),
            _mk_stroke(2, (base + timedelta(seconds=200)).isoformat()),
            _mk_stroke(3, (base + timedelta(seconds=215)).isoformat()),
            _mk_stroke(4, (base + timedelta(seconds=500)).isoformat()),
            _mk_stroke(5, (base + timedelta(seconds=515)).isoformat()),
        ]
        _write_strokes(sp, strokes)

        # now close to last stroke — system is healthy at present
        now = base + timedelta(seconds=530)

        result = measure_recovery(
            tmp_path, cadence_seconds=15, stall_multiplier=10, now=now,
            strokes_path=sp,
        )
        assert result["total_stalls"] == 2
        assert result["recovered_stalls"] == 2


# ---------------------------------------------------------------------------
# recovery_report
# ---------------------------------------------------------------------------

class TestRecoveryReport:
    def test_healthy_report(self, tmp_path):
        sp = tmp_path / "data" / "strokes.jsonl"
        now = datetime(2026, 10, 19, 15, 5, 0, tzinfo=timezone.utc)
        base = now - timedelta(seconds=30)
        strokes = [
            _mk_stroke(i, (base + timedelta(seconds=i * 15)).isoformat())
            for i in range(1, 4)
        ]
        _write_strokes(sp, strokes)

        report = recovery_report(
            tmp_path, cadence_seconds=15, stall_multiplier=10, now=now,
        )
        assert "no stalls" in report.lower() or "healthy" in report.lower()

    def test_stalled_report(self, tmp_path):
        sp = tmp_path / "data" / "strokes.jsonl"
        now = datetime(2026, 10, 19, 16, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _mk_stroke(1, "2026-10-19T15:00:00+00:00"),
            _mk_stroke(2, "2026-10-19T15:00:15+00:00"),
        ]
        _write_strokes(sp, strokes)

        report = recovery_report(
            tmp_path, cadence_seconds=15, stall_multiplier=10, now=now,
        )
        assert "currently stalled" in report.lower() or "stalled" in report.lower()

    def test_recovered_report(self, tmp_path):
        sp = tmp_path / "data" / "strokes.jsonl"
        now = datetime(2026, 10, 19, 15, 30, 0, tzinfo=timezone.utc)
        base = datetime(2026, 10, 19, 15, 0, 0, tzinfo=timezone.utc)
        strokes = [
            _mk_stroke(1, base.isoformat()),
            _mk_stroke(2, (base + timedelta(seconds=15)).isoformat()),
            _mk_stroke(3, (base + timedelta(seconds=315)).isoformat()),
            _mk_stroke(4, (base + timedelta(seconds=330)).isoformat()),
            _mk_stroke(5, (base + timedelta(seconds=345)).isoformat()),
        ]
        _write_strokes(sp, strokes)

        report = recovery_report(
            tmp_path, cadence_seconds=15, stall_multiplier=10, now=now,
        )
        assert "recovered" in report.lower()
        assert "300" in report or "latency" in report.lower()
