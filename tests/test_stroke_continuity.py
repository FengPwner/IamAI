"""Tests for iamai.stroke_continuity — stroke sequence continuity metrics."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.stroke_continuity import (
    _load_strokes,
    _parse_timestamp,
    continuity,
    continuity_summary,
    sequence_integrity,
    temporal_regularity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_strokes(
    count: int,
    start: datetime,
    interval_seconds: int = 15,
    seq_start: int = 1,
    kind: str = "thought",
) -> list[dict]:
    """Generate synthetic stroke records with clean sequential seq numbers."""
    strokes = []
    for i in range(count):
        dt = start + timedelta(seconds=interval_seconds * i)
        strokes.append({
            "seq": seq_start + i,
            "at": dt.isoformat(),
            "kind": kind,
            "text": f"test stroke {seq_start + i}",
        })
    return strokes


def _write_strokes_file(strokes: list[dict], tmpdir: Path) -> Path:
    """Write stroke records to a temporary JSONL file."""
    path = tmpdir / "strokes.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for s in strokes:
            f.write(json.dumps(s) + "\n")
    return path


# ---------------------------------------------------------------------------
# _parse_timestamp
# ---------------------------------------------------------------------------


class TestParseTimestamp:
    def test_utc_offset(self):
        dt = _parse_timestamp("2026-10-18T12:00:00+00:00")
        assert dt.tzinfo is not None
        assert dt.year == 2026

    def test_z_suffix(self):
        dt = _parse_timestamp("2026-10-18T12:00:00Z")
        assert dt.tzinfo is not None

    def test_bare_datetime(self):
        dt = _parse_timestamp("2026-10-18T12:00:00")
        assert dt.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# sequence_integrity
# ---------------------------------------------------------------------------


class TestSequenceIntegrity:
    def test_empty(self):
        assert sequence_integrity([]) == 1.0

    def test_single_stroke(self):
        strokes = [{"_seq": 1}]
        assert sequence_integrity(strokes) == 1.0

    def test_perfect_sequence(self):
        strokes = [{"_seq": i} for i in range(1, 11)]
        assert sequence_integrity(strokes) == 1.0

    def test_gap_in_sequence(self):
        # seq: 1, 2, 3, 5, 6 — one violation (3→5)
        strokes = [{"_seq": s} for s in [1, 2, 3, 5, 6]]
        score = sequence_integrity(strokes)
        assert score == 3 / 4  # 3 ok out of 4 pairs

    def test_duplicate_seq(self):
        # seq: 1, 2, 2, 3 — one violation (2→2, not strictly increasing)
        strokes = [{"_seq": s} for s in [1, 2, 2, 3]]
        score = sequence_integrity(strokes)
        assert score == 2 / 3

    def test_descending_seq(self):
        # All pairs are violations
        strokes = [{"_seq": s} for s in [5, 4, 3, 2, 1]]
        assert sequence_integrity(strokes) == 0.0

    def test_mixed_violations(self):
        # seq: 1, 3, 2, 4 — all pairs are non-consecutive:
        # 1→3 (gap +2), 3→2 (descent), 2→4 (gap +2) → 0 ok / 3 total
        strokes = [{"_seq": s} for s in [1, 3, 2, 4]]
        score = sequence_integrity(strokes)
        assert score == pytest.approx(0.0)

    def test_large_clean_sequence(self):
        strokes = [{"_seq": i} for i in range(100, 200)]
        assert sequence_integrity(strokes) == 1.0


# ---------------------------------------------------------------------------
# temporal_regularity
# ---------------------------------------------------------------------------


class TestTemporalRegularity:
    def test_empty(self):
        assert temporal_regularity([]) == 1.0

    def test_single_stroke(self):
        strokes = [{"_dt": datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)}]
        assert temporal_regularity(strokes) == 1.0

    def test_perfect_uniform(self):
        """All intervals exactly 15s → CV=0 → regularity=1.0."""
        base = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        strokes = [{"_dt": base + timedelta(seconds=15 * i)} for i in range(20)]
        assert temporal_regularity(strokes) == 1.0

    def test_jittered_intervals(self):
        """Some jitter → regularity < 1.0 but > 0."""
        base = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        # Alternating 10s and 20s intervals → mean=15, CV>0
        offsets = [0]
        for i in range(19):
            offsets.append(offsets[-1] + (10 if i % 2 == 0 else 20))
        strokes = [{"_dt": base + timedelta(seconds=o)} for o in offsets]
        reg = temporal_regularity(strokes)
        assert 0.0 < reg < 1.0

    def test_extreme_irregularity(self):
        """One huge gap among tiny intervals → low regularity."""
        base = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        # 9 intervals of 1s, then one interval of 10000s
        offsets = list(range(10)) + [10010]
        strokes = [{"_dt": base + timedelta(seconds=o)} for o in offsets]
        reg = temporal_regularity(strokes)
        assert reg < 0.5

    def test_all_same_time(self):
        """All strokes at the same instant → mean=0 → regularity=0."""
        base = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        strokes = [{"_dt": base} for _ in range(5)]
        assert temporal_regularity(strokes) == 0.0

    def test_negative_intervals_clamped(self):
        """Backward timestamps → negative intervals clamped to 0."""
        base = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        strokes = [
            {"_dt": base + timedelta(seconds=30)},
            {"_dt": base + timedelta(seconds=10)},  # backward
            {"_dt": base + timedelta(seconds=50)},
        ]
        reg = temporal_regularity(strokes)
        assert 0.0 <= reg <= 1.0


# ---------------------------------------------------------------------------
# continuity (composite)
# ---------------------------------------------------------------------------


class TestContinuity:
    def test_perfect_continuity(self, tmp_path):
        """Clean sequence with uniform intervals → score near 1.0."""
        strokes = _make_strokes(
            50,
            start=datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc),
            interval_seconds=15,
        )
        path = _write_strokes_file(strokes, tmp_path)
        info = continuity(strokes_path=path)
        assert info["continuity_score"] == pytest.approx(1.0)
        assert info["sequence_integrity"] == 1.0
        assert info["temporal_regularity"] == 1.0
        assert info["stroke_count"] == 50
        assert info["seq_violations"] == 0

    def test_degraded_sequence(self, tmp_path):
        """Gaps in seq numbers → integrity < 1.0."""
        strokes = [
            {"seq": 1, "at": "2026-10-18T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"seq": 2, "at": "2026-10-18T10:00:15+00:00", "kind": "thought", "text": "b"},
            {"seq": 5, "at": "2026-10-18T10:00:30+00:00", "kind": "thought", "text": "c"},
            {"seq": 6, "at": "2026-10-18T10:00:45+00:00", "kind": "thought", "text": "d"},
        ]
        path = _write_strokes_file(strokes, tmp_path)
        info = continuity(strokes_path=path)
        assert info["sequence_integrity"] < 1.0
        assert info["seq_violations"] == 1
        assert info["continuity_score"] < 1.0

    def test_empty_file(self, tmp_path):
        """Empty JSONL → score 0.0 (no data to evaluate)."""
        path = _write_strokes_file([], tmp_path)
        info = continuity(strokes_path=path)
        assert info["stroke_count"] == 0
        # Empty → vacuously 1.0 for both → geometric mean 1.0
        # But we return score 0 only when one metric is 0
        assert info["continuity_score"] == 1.0  # vacuous truth

    def test_tail_parameter(self, tmp_path):
        """tail=N examines only the last N strokes."""
        strokes = _make_strokes(
            100,
            start=datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc),
            interval_seconds=15,
        )
        path = _write_strokes_file(strokes, tmp_path)
        info = continuity(strokes_path=path, tail=20)
        assert info["stroke_count"] == 20
        assert info["sequence_integrity"] == 1.0

    def test_mean_interval_computed(self, tmp_path):
        """mean_interval_s is correct for uniform strokes."""
        strokes = _make_strokes(
            10,
            start=datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc),
            interval_seconds=30,
        )
        path = _write_strokes_file(strokes, tmp_path)
        info = continuity(strokes_path=path)
        assert info["mean_interval_s"] == pytest.approx(30.0)

    def test_geometric_mean_not_arithmetic(self, tmp_path):
        """Composite uses geometric mean: sqrt(a*b), not (a+b)/2."""
        # Construct strokes with known integrity and regularity
        # seq: 1,2,3,5 → integrity = 2/3 ≈ 0.6667
        # uniform 15s intervals → regularity = 1.0
        strokes = [
            {"seq": 1, "at": "2026-10-18T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"seq": 2, "at": "2026-10-18T10:00:15+00:00", "kind": "thought", "text": "b"},
            {"seq": 3, "at": "2026-10-18T10:00:30+00:00", "kind": "thought", "text": "c"},
            {"seq": 5, "at": "2026-10-18T10:00:45+00:00", "kind": "thought", "text": "d"},
        ]
        path = _write_strokes_file(strokes, tmp_path)
        info = continuity(strokes_path=path)
        expected = math.sqrt(info["sequence_integrity"] * info["temporal_regularity"])
        assert info["continuity_score"] == pytest.approx(expected, abs=0.001)

    def test_malformed_lines_skipped(self, tmp_path):
        """Bad JSON lines are silently dropped."""
        path = tmp_path / "strokes.jsonl"
        with open(path, "w") as f:
            f.write('{"seq":1,"at":"2026-10-18T10:00:00+00:00","kind":"t","text":"a"}\n')
            f.write("GARBAGE\n")
            f.write('{"seq":2,"at":"2026-10-18T10:00:15+00:00","kind":"t","text":"b"}\n')
        info = continuity(strokes_path=path)
        assert info["stroke_count"] == 2
        assert info["sequence_integrity"] == 1.0


# ---------------------------------------------------------------------------
# continuity_summary
# ---------------------------------------------------------------------------


class TestContinuitySummary:
    def test_summary_string_format(self, tmp_path):
        strokes = _make_strokes(
            30,
            start=datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc),
            interval_seconds=15,
        )
        path = _write_strokes_file(strokes, tmp_path)
        text = continuity_summary(strokes_path=path, tail=30)
        assert isinstance(text, str)
        assert "continuity" in text
        assert "seq_integrity" in text
        assert "temporal_regularity" in text
        assert "30 strokes" in text

    def test_summary_score_matches(self, tmp_path):
        strokes = _make_strokes(
            20,
            start=datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc),
            interval_seconds=15,
        )
        path = _write_strokes_file(strokes, tmp_path)
        info = continuity(strokes_path=path, tail=20)
        text = continuity_summary(strokes_path=path, tail=20)
        assert str(info["continuity_score"]) in text
