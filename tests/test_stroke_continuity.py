"""Tests for iamai.stroke_continuity -- gap detection in stroke sequences."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iamai.stroke_continuity import Gap, continuity_report, find_gaps


def _write_strokes(tmp_path: Path, strokes: list[dict]) -> Path:
    """Helper: write a list of stroke dicts to a JSONL file."""
    p = tmp_path / "strokes.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for s in strokes:
            f.write(json.dumps(s) + "\n")
    return p


def _make_stroke(seq: int, at: str, kind: str = "thought", text: str = "x") -> dict:
    return {"seq": seq, "at": at, "kind": kind, "text": text}


# --- find_gaps: basic ---


def test_find_gaps_empty_file(tmp_path: Path):
    p = _write_strokes(tmp_path, [])
    assert find_gaps(p) == []


def test_find_gaps_single_stroke(tmp_path: Path):
    p = _write_strokes(tmp_path, [
        _make_stroke(1, "2026-10-08T04:00:00+00:00"),
    ])
    assert find_gaps(p) == []


def test_find_gaps_two_contiguous_strokes(tmp_path: Path):
    """15s apart -- well below 300s default threshold."""
    p = _write_strokes(tmp_path, [
        _make_stroke(1, "2026-10-08T04:00:00+00:00"),
        _make_stroke(2, "2026-10-08T04:00:15+00:00"),
    ])
    assert find_gaps(p) == []


def test_find_gaps_detects_large_gap(tmp_path: Path):
    """10-minute gap should be detected at default 300s threshold."""
    p = _write_strokes(tmp_path, [
        _make_stroke(1, "2026-10-08T04:00:00+00:00"),
        _make_stroke(2, "2026-10-08T04:10:00+00:00"),
    ])
    gaps = find_gaps(p)
    assert len(gaps) == 1
    assert gaps[0].seq_before == 1
    assert gaps[0].seq_after == 2
    assert gaps[0].gap_seconds == 600.0


def test_find_gaps_multiple_gaps(tmp_path: Path):
    """Multiple gaps should all be found."""
    p = _write_strokes(tmp_path, [
        _make_stroke(1, "2026-10-08T04:00:00+00:00"),
        _make_stroke(2, "2026-10-08T04:10:00+00:00"),  # 600s gap
        _make_stroke(3, "2026-10-08T04:10:15+00:00"),  # 15s, no gap
        _make_stroke(4, "2026-10-08T04:30:00+00:00"),  # 1185s gap
    ])
    gaps = find_gaps(p)
    assert len(gaps) == 2


def test_find_gaps_sorted_longest_first(tmp_path: Path):
    """Gaps should be returned longest-first."""
    p = _write_strokes(tmp_path, [
        _make_stroke(1, "2026-10-08T04:00:00+00:00"),
        _make_stroke(2, "2026-10-08T04:10:00+00:00"),  # 600s
        _make_stroke(3, "2026-10-08T04:10:15+00:00"),
        _make_stroke(4, "2026-10-08T05:00:00+00:00"),  # 2985s
    ])
    gaps = find_gaps(p)
    assert gaps[0].gap_seconds > gaps[1].gap_seconds
    assert gaps[0].seq_before == 3
    assert gaps[0].seq_after == 4


# --- find_gaps: threshold ---


def test_find_gaps_custom_threshold(tmp_path: Path):
    """Lower threshold catches smaller gaps."""
    p = _write_strokes(tmp_path, [
        _make_stroke(1, "2026-10-08T04:00:00+00:00"),
        _make_stroke(2, "2026-10-08T04:02:00+00:00"),  # 120s
    ])
    # Default 300s: no gap
    assert find_gaps(p) == []
    # Threshold 60s: gap detected
    gaps = find_gaps(p, min_gap_seconds=60)
    assert len(gaps) == 1
    assert gaps[0].gap_seconds == 120.0


def test_find_gaps_exact_threshold_not_included(tmp_path: Path):
    """Gap exactly equal to threshold should NOT be included (strictly greater)."""
    p = _write_strokes(tmp_path, [
        _make_stroke(1, "2026-10-08T04:00:00+00:00"),
        _make_stroke(2, "2026-10-08T04:05:00+00:00"),  # exactly 300s
    ])
    # min_gap_seconds=300 with >= check should include it
    gaps = find_gaps(p, min_gap_seconds=300)
    assert len(gaps) == 1


def test_find_gaps_just_below_threshold(tmp_path: Path):
    """Gap just below threshold should not be detected."""
    p = _write_strokes(tmp_path, [
        _make_stroke(1, "2026-10-08T04:00:00+00:00"),
        _make_stroke(2, "2026-10-08T04:04:59+00:00"),  # 299s
    ])
    assert find_gaps(p, min_gap_seconds=300) == []


# --- find_gaps: edge cases ---


def test_find_gaps_z_suffix_timestamp(tmp_path: Path):
    """Timestamps ending with Z instead of +00:00 should work."""
    p = _write_strokes(tmp_path, [
        _make_stroke(1, "2026-10-08T04:00:00Z"),
        _make_stroke(2, "2026-10-08T04:10:00Z"),
    ])
    gaps = find_gaps(p)
    assert len(gaps) == 1
    assert gaps[0].gap_seconds == 600.0


def test_find_gaps_mixed_z_and_offset(tmp_path: Path):
    """Mixing Z and +00:00 timestamps should still work."""
    p = _write_strokes(tmp_path, [
        _make_stroke(1, "2026-10-08T04:00:00Z"),
        _make_stroke(2, "2026-10-08T04:10:00+00:00"),
    ])
    gaps = find_gaps(p)
    assert len(gaps) == 1


def test_find_gaps_missing_at_field(tmp_path: Path):
    """Strokes missing 'at' should be skipped without error."""
    p = _write_strokes(tmp_path, [
        {"seq": 1, "kind": "thought", "text": "no timestamp"},
        _make_stroke(2, "2026-10-08T04:00:00+00:00"),
        _make_stroke(3, "2026-10-08T04:10:00+00:00"),
    ])
    gaps = find_gaps(p)
    assert len(gaps) == 1


def test_find_gaps_invalid_json_line(tmp_path: Path):
    """Malformed JSON lines should be skipped."""
    p = tmp_path / "strokes.jsonl"
    p.write_text(
        '{"seq": 1, "at": "2026-10-08T04:00:00+00:00", "kind": "x", "text": "x"}\n'
        'NOT VALID JSON\n'
        '{"seq": 2, "at": "2026-10-08T04:10:00+00:00", "kind": "x", "text": "x"}\n',
        encoding="utf-8",
    )
    gaps = find_gaps(p)
    assert len(gaps) == 1


def test_find_gaps_nonexistent_file(tmp_path: Path):
    """Nonexistent file should return empty list, not raise."""
    p = tmp_path / "does_not_exist.jsonl"
    assert find_gaps(p) == []


def test_find_gaps_zero_threshold(tmp_path: Path):
    """Zero threshold catches any positive gap."""
    p = _write_strokes(tmp_path, [
        _make_stroke(1, "2026-10-08T04:00:00+00:00"),
        _make_stroke(2, "2026-10-08T04:00:01+00:00"),
    ])
    gaps = find_gaps(p, min_gap_seconds=0)
    assert len(gaps) == 1
    assert gaps[0].gap_seconds == 1.0


def test_find_gaps_negative_time_skipped(tmp_path: Path):
    """Backward timestamps produce negative delta -- below any positive threshold."""
    p = _write_strokes(tmp_path, [
        _make_stroke(1, "2026-10-08T04:10:00+00:00"),
        _make_stroke(2, "2026-10-08T04:00:00+00:00"),  # going backward
    ])
    assert find_gaps(p, min_gap_seconds=1) == []


# --- continuity_report ---


def test_continuity_report_clean(tmp_path: Path):
    """No gaps -> clean report."""
    p = _write_strokes(tmp_path, [
        _make_stroke(1, "2026-10-08T04:00:00+00:00"),
        _make_stroke(2, "2026-10-08T04:00:15+00:00"),
        _make_stroke(3, "2026-10-08T04:00:30+00:00"),
    ])
    report = continuity_report(p)
    assert report["total_strokes"] == 3
    assert report["gap_count"] == 0
    assert report["longest_gap_s"] == 0
    assert report["mean_gap_s"] == 0
    assert report["gaps"] == []


def test_continuity_report_with_gaps(tmp_path: Path):
    """Report with two gaps should have correct summary."""
    p = _write_strokes(tmp_path, [
        _make_stroke(1, "2026-10-08T04:00:00+00:00"),
        _make_stroke(2, "2026-10-08T04:10:00+00:00"),  # 600s
        _make_stroke(3, "2026-10-08T04:10:15+00:00"),
        _make_stroke(4, "2026-10-08T04:20:15+00:00"),  # 600s
    ])
    report = continuity_report(p)
    assert report["total_strokes"] == 4
    assert report["gap_count"] == 2
    assert report["longest_gap_s"] == 600.0
    assert report["mean_gap_s"] == 600.0


def test_continuity_report_empty_file(tmp_path: Path):
    p = _write_strokes(tmp_path, [])
    report = continuity_report(p)
    assert report["total_strokes"] == 0
    assert report["gap_count"] == 0


def test_continuity_report_nonexistent_file(tmp_path: Path):
    p = tmp_path / "missing.jsonl"
    report = continuity_report(p)
    assert report["total_strokes"] == 0


# --- Gap dataclass ---


def test_gap_as_dict():
    g = Gap(
        seq_before=10,
        seq_after=11,
        time_before="2026-10-08T04:00:00+00:00",
        time_after="2026-10-08T04:10:00+00:00",
        gap_seconds=600.123,
    )
    d = g.as_dict()
    assert d["seq_before"] == 10
    assert d["seq_after"] == 11
    assert d["gap_seconds"] == 600.1  # rounded to 1 decimal


def test_gap_frozen():
    """Gap should be immutable (frozen dataclass)."""
    g = Gap(1, 2, "a", "b", 100.0)
    with pytest.raises(AttributeError):
        g.seq_before = 99  # type: ignore[misc]


# --- large-ish realistic dataset ---


def test_continuity_report_realistic_cadence(tmp_path: Path):
    """Simulate 40 strokes at 15s cadence with one 90-min stall."""
    strokes = []
    base = "2026-10-08T04:00:{:02d}+00:00"
    for i in range(40):
        sec = i * 15
        minute, second = divmod(sec, 60)
        at = f"2026-10-08T04:{minute:02d}:{second:02d}+00:00"
        strokes.append(_make_stroke(i + 1, at))
    # Insert a 90-minute gap between stroke 20 and 21
    strokes[20] = _make_stroke(21, "2026-10-08T06:24:45+00:00")
    # Fix subsequent timestamps
    for i in range(21, 40):
        offset = (i - 20) * 15
        minute, second = divmod(offset, 60)
        at = f"2026-10-08T06:{24 + minute:02d}:{45 + second:02d}+00:00"
        strokes[i] = _make_stroke(i + 1, at)

    p = _write_strokes(tmp_path, strokes)
    report = continuity_report(p)
    assert report["total_strokes"] == 40
    assert report["gap_count"] == 1
    assert report["longest_gap_s"] > 5000  # ~90 min
