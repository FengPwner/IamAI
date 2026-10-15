"""Tests for iamai.stroke_pause."""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from iamai.stroke_pause import (
    _classify_gap,
    _load_timestamps,
    _parse_iso,
    detect_pauses,
    longest_pauses,
    pause_report,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_strokes_file(tmp_path: Path, strokes: list[dict]) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    p = data_dir / "strokes.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for s in strokes:
            f.write(json.dumps(s) + "\n")
    return p


_BASE = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)


def _stroke(seq: int, offset_seconds: int, kind: str = "thought") -> dict:
    ts = (_BASE + timedelta(seconds=offset_seconds)).isoformat()
    return {"seq": seq, "at": ts, "kind": kind, "text": f"stroke {seq}"}


# ---------------------------------------------------------------------------
# _parse_iso
# ---------------------------------------------------------------------------

class TestParseIso:
    def test_valid_utc(self):
        dt = _parse_iso("2026-10-15T12:00:00+00:00")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 10

    def test_z_suffix(self):
        dt = _parse_iso("2026-10-15T12:00:00Z")
        assert dt is not None

    def test_empty_string(self):
        assert _parse_iso("") is None

    def test_none_input(self):
        assert _parse_iso(None) is None  # type: ignore

    def test_garbage(self):
        assert _parse_iso("not-a-date") is None

    def test_integer_input(self):
        assert _parse_iso(42) is None  # type: ignore


# ---------------------------------------------------------------------------
# _load_timestamps
# ---------------------------------------------------------------------------

class TestLoadTimestamps:
    def test_missing_file(self, tmp_path: Path):
        result = _load_timestamps(tmp_path / "nope.jsonl", 10)
        assert result == []

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        assert _load_timestamps(p, 10) == []

    def test_basic_load(self, tmp_path: Path):
        strokes = [_stroke(i, i * 60) for i in range(5)]
        p = _make_strokes_file(tmp_path, strokes)
        ts = _load_timestamps(p, 10)
        assert len(ts) == 5

    def test_window_truncation(self, tmp_path: Path):
        strokes = [_stroke(i, i * 60) for i in range(20)]
        p = _make_strokes_file(tmp_path, strokes)
        ts = _load_timestamps(p, 10)
        assert len(ts) == 10

    def test_malformed_lines_skipped(self, tmp_path: Path):
        p = tmp_path / "data" / "strokes.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        content = (
            json.dumps(_stroke(1, 0)) + "\n"
            + "NOT JSON\n"
            + json.dumps(_stroke(2, 60)) + "\n"
        )
        p.write_text(content)
        ts = _load_timestamps(p, 10)
        assert len(ts) == 2

    def test_bad_timestamp_skipped(self, tmp_path: Path):
        strokes = [
            _stroke(1, 0),
            {"seq": 2, "at": "garbage", "kind": "thought", "text": "x"},
            _stroke(3, 120),
        ]
        p = _make_strokes_file(tmp_path, strokes)
        ts = _load_timestamps(p, 10)
        assert len(ts) == 2  # middle one dropped


# ---------------------------------------------------------------------------
# _classify_gap
# ---------------------------------------------------------------------------

class TestClassifyGap:
    def test_normal(self):
        assert _classify_gap(60.0, 120.0) == "normal"
        assert _classify_gap(120.0, 120.0) == "normal"

    def test_elongated(self):
        assert _classify_gap(121.0, 120.0) == "elongated"
        assert _classify_gap(240.0, 120.0) == "elongated"

    def test_stalled(self):
        assert _classify_gap(241.0, 120.0) == "stalled"
        assert _classify_gap(600.0, 120.0) == "stalled"

    def test_zero_threshold(self):
        assert _classify_gap(0.0, 0.0) == "normal"
        assert _classify_gap(1.0, 0.0) == "stalled"


# ---------------------------------------------------------------------------
# detect_pauses
# ---------------------------------------------------------------------------

class TestDetectPauses:
    def test_no_pauses(self, tmp_path: Path):
        # Strokes 15s apart, threshold 120s → no pauses
        strokes = [_stroke(i, i * 15) for i in range(10)]
        p = _make_strokes_file(tmp_path, strokes)
        result = detect_pauses(p, window=10, threshold_seconds=120.0)
        assert result == []

    def test_one_pause(self, tmp_path: Path):
        # Normal 15s gaps, but one 300s gap between stroke 4 and 5
        strokes = [_stroke(i, i * 15) for i in range(5)]
        strokes.append(_stroke(5, 4 * 15 + 300))  # 300s gap
        for i in range(6, 10):
            strokes.append(_stroke(i, 4 * 15 + 300 + (i - 5) * 15))
        p = _make_strokes_file(tmp_path, strokes)
        result = detect_pauses(p, window=10, threshold_seconds=120.0)
        assert len(result) == 1
        assert result[0]["gap_seconds"] == 300.0
        assert result[0]["verdict"] == "stalled"

    def test_multiple_pauses_sorted(self, tmp_path: Path):
        # Two pauses: 200s and 500s
        strokes = [_stroke(0, 0), _stroke(1, 15)]
        strokes.append(_stroke(2, 15 + 200))  # 200s gap
        strokes.append(_stroke(3, 15 + 200 + 15))
        strokes.append(_stroke(4, 15 + 200 + 15 + 500))  # 500s gap
        strokes.append(_stroke(5, 15 + 200 + 15 + 500 + 15))
        p = _make_strokes_file(tmp_path, strokes)
        result = detect_pauses(p, window=10, threshold_seconds=120.0)
        assert len(result) == 2
        assert result[0]["gap_seconds"] == 500.0  # sorted desc
        assert result[1]["gap_seconds"] == 200.0

    def test_insufficient_data(self, tmp_path: Path):
        strokes = [_stroke(0, 0)]
        p = _make_strokes_file(tmp_path, strokes)
        result = detect_pauses(p, window=10, threshold_seconds=120.0)
        assert result == []

    def test_empty_file(self, tmp_path: Path):
        p = _make_strokes_file(tmp_path, [])
        result = detect_pauses(p, window=10)
        assert result == []

    def test_elongated_verdict(self, tmp_path: Path):
        # Gap of 180s with threshold 120 → elongated (120 < 180 ≤ 240)
        strokes = [_stroke(0, 0), _stroke(1, 180)]
        p = _make_strokes_file(tmp_path, strokes)
        result = detect_pauses(p, window=10, threshold_seconds=120.0)
        assert len(result) == 1
        assert result[0]["verdict"] == "elongated"

    def test_exactly_at_threshold(self, tmp_path: Path):
        # Gap of exactly 120s with threshold 120 → normal (≤ threshold)
        strokes = [_stroke(0, 0), _stroke(1, 120)]
        p = _make_strokes_file(tmp_path, strokes)
        result = detect_pauses(p, window=10, threshold_seconds=120.0)
        assert result == []

    def test_window_respected(self, tmp_path: Path):
        # 20 strokes, window=5 → only last 5 examined
        strokes = [_stroke(i, i * 15) for i in range(20)]
        # Insert a big gap early (between stroke 2 and 3) — outside window=5
        strokes[3] = _stroke(3, 2 * 15 + 600)
        for i in range(4, 20):
            strokes[i] = _stroke(i, 2 * 15 + 600 + (i - 3) * 15)
        p = _make_strokes_file(tmp_path, strokes)
        # window=5 → last 5 strokes, all 15s apart
        result = detect_pauses(p, window=5, threshold_seconds=120.0)
        assert result == []


# ---------------------------------------------------------------------------
# longest_pauses
# ---------------------------------------------------------------------------

class TestLongestPauses:
    def test_basic(self, tmp_path: Path):
        strokes = [_stroke(0, 0), _stroke(1, 100), _stroke(2, 115), _stroke(3, 500)]
        p = _make_strokes_file(tmp_path, strokes)
        result = longest_pauses(p, window=10, top_n=2)
        assert len(result) == 2
        assert result[0]["gap_seconds"] == 385.0  # 500 - 115
        assert result[1]["gap_seconds"] == 100.0

    def test_top_n_larger_than_available(self, tmp_path: Path):
        strokes = [_stroke(0, 0), _stroke(1, 60)]
        p = _make_strokes_file(tmp_path, strokes)
        result = longest_pauses(p, window=10, top_n=10)
        assert len(result) == 1

    def test_insufficient_data(self, tmp_path: Path):
        strokes = [_stroke(0, 0)]
        p = _make_strokes_file(tmp_path, strokes)
        result = longest_pauses(p, window=10, top_n=5)
        assert result == []

    def test_empty_file(self, tmp_path: Path):
        p = _make_strokes_file(tmp_path, [])
        result = longest_pauses(p, window=10)
        assert result == []

    def test_sorted_descending(self, tmp_path: Path):
        strokes = [
            _stroke(0, 0),
            _stroke(1, 50),
            _stroke(2, 50 + 300),
            _stroke(3, 50 + 300 + 10),
            _stroke(4, 50 + 300 + 10 + 200),
        ]
        p = _make_strokes_file(tmp_path, strokes)
        result = longest_pauses(p, window=10, top_n=3)
        gaps = [r["gap_seconds"] for r in result]
        assert gaps == sorted(gaps, reverse=True)


# ---------------------------------------------------------------------------
# pause_report
# ---------------------------------------------------------------------------

class TestPauseReport:
    def test_no_pauses(self, tmp_path: Path):
        strokes = [_stroke(i, i * 15) for i in range(10)]
        _make_strokes_file(tmp_path, strokes)
        report = pause_report(tmp_path, window=10, threshold_seconds=120.0)
        assert "no pauses" in report
        assert "10 strokes" in report

    def test_with_pauses(self, tmp_path: Path):
        strokes = [_stroke(0, 0), _stroke(1, 300), _stroke(2, 315)]
        _make_strokes_file(tmp_path, strokes)
        report = pause_report(tmp_path, window=10, threshold_seconds=120.0)
        assert "1 pause" in report
        assert "300" in report
        assert "stalled" in report

    def test_insufficient_data(self, tmp_path: Path):
        strokes = [_stroke(0, 0)]
        _make_strokes_file(tmp_path, strokes)
        report = pause_report(tmp_path, window=10)
        assert "insufficient" in report

    def test_empty(self, tmp_path: Path):
        _make_strokes_file(tmp_path, [])
        report = pause_report(tmp_path, window=10)
        assert "insufficient" in report

    def test_default_repo_path(self):
        # Calling with no args should not crash.
        report = pause_report(window=5)
        assert isinstance(report, str)

    def test_multiple_pauses_count(self, tmp_path: Path):
        strokes = [
            _stroke(0, 0),
            _stroke(1, 200),   # 200s gap
            _stroke(2, 215),
            _stroke(3, 600),   # 385s gap
            _stroke(4, 615),
        ]
        _make_strokes_file(tmp_path, strokes)
        report = pause_report(tmp_path, window=10, threshold_seconds=120.0)
        assert "2 pause" in report

    def test_elongated_in_report(self, tmp_path: Path):
        # Gap of 150s with threshold 120 → elongated
        strokes = [_stroke(0, 0), _stroke(1, 150)]
        _make_strokes_file(tmp_path, strokes)
        report = pause_report(tmp_path, window=10, threshold_seconds=120.0)
        assert "elongated" in report
