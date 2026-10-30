"""Tests for writer_session_segmenter — split stroke history into writing sessions."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_session_segmenter import (
    _build_session,
    _parse_ts,
    load_strokes,
    segment,
    session_summary,
)


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------


class TestParseTs:
    def test_iso_with_tz(self):
        ts = _parse_ts("2026-10-27T10:00:00+00:00")
        assert ts is not None
        assert ts.hour == 10

    def test_iso_zulu(self):
        ts = _parse_ts("2026-10-27T10:00:00Z")
        assert ts is not None

    def test_naive_gets_utc(self):
        ts = _parse_ts("2026-10-27T10:00:00")
        assert ts is not None
        assert str(ts.tzinfo) != "None" or ts.utcoffset() is not None

    def test_empty_returns_none(self):
        assert _parse_ts("") is None

    def test_garbage_returns_none(self):
        assert _parse_ts("not a date") is None

    def test_none_returns_none(self):
        assert _parse_ts(None) is None


# ---------------------------------------------------------------------------
# segment — basic cases
# ---------------------------------------------------------------------------


class TestSegmentBasic:
    def test_empty_input(self):
        assert segment([]) == []

    def test_single_stroke(self):
        strokes = [{"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "hi"}]
        sessions = segment(strokes)
        assert len(sessions) == 1
        assert sessions[0]["stroke_count"] == 1
        assert sessions[0]["duration_seconds"] == 0.0

    def test_two_strokes_same_session(self):
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"at": "2026-10-27T10:02:00+00:00", "kind": "note", "text": "b"},
        ]
        sessions = segment(strokes, gap_threshold=300)
        assert len(sessions) == 1
        assert sessions[0]["stroke_count"] == 2

    def test_two_strokes_different_sessions(self):
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"at": "2026-10-27T10:10:00+00:00", "kind": "note", "text": "b"},
        ]
        sessions = segment(strokes, gap_threshold=300)
        assert len(sessions) == 2
        assert sessions[0]["stroke_count"] == 1
        assert sessions[1]["stroke_count"] == 1

    def test_three_strokes_two_sessions(self):
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"at": "2026-10-27T10:00:15+00:00", "kind": "note", "text": "b"},
            {"at": "2026-10-27T10:15:00+00:00", "kind": "thought", "text": "c"},
        ]
        sessions = segment(strokes, gap_threshold=300)
        assert len(sessions) == 2
        assert sessions[0]["stroke_count"] == 2
        assert sessions[1]["stroke_count"] == 1

    def test_gap_exactly_threshold_stays_same_session(self):
        """Gap == threshold should NOT split (only strictly greater splits)."""
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"at": "2026-10-27T10:05:00+00:00", "kind": "thought", "text": "b"},
        ]
        sessions = segment(strokes, gap_threshold=300)
        assert len(sessions) == 1

    def test_gap_one_second_over_threshold_splits(self):
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"at": "2026-10-27T10:05:01+00:00", "kind": "thought", "text": "b"},
        ]
        sessions = segment(strokes, gap_threshold=300)
        assert len(sessions) == 2


# ---------------------------------------------------------------------------
# segment — ordering and tolerance
# ---------------------------------------------------------------------------


class TestSegmentOrdering:
    def test_out_of_order_input_is_sorted(self):
        strokes = [
            {"at": "2026-10-27T10:02:00+00:00", "kind": "thought", "text": "b"},
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"},
        ]
        sessions = segment(strokes, gap_threshold=300)
        assert len(sessions) == 1
        assert sessions[0]["stroke_count"] == 2

    def test_bad_timestamps_skipped(self):
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"at": "garbage", "kind": "thought", "text": "skip me"},
            {"at": "2026-10-27T10:00:15+00:00", "kind": "note", "text": "b"},
        ]
        sessions = segment(strokes, gap_threshold=300)
        assert len(sessions) == 1
        assert sessions[0]["stroke_count"] == 2

    def test_missing_at_key_skipped(self):
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"kind": "thought", "text": "no timestamp"},
            {"at": "2026-10-27T10:00:15+00:00", "kind": "note", "text": "b"},
        ]
        sessions = segment(strokes, gap_threshold=300)
        assert len(sessions) == 1
        assert sessions[0]["stroke_count"] == 2


# ---------------------------------------------------------------------------
# session metrics
# ---------------------------------------------------------------------------


class TestSessionMetrics:
    def test_duration(self):
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"at": "2026-10-27T10:05:00+00:00", "kind": "thought", "text": "b"},
        ]
        sessions = segment(strokes, gap_threshold=600)
        assert sessions[0]["duration_seconds"] == 300.0

    def test_stroke_rate(self):
        # 4 strokes in 3 minutes = 1.33 strokes/min
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"at": "2026-10-27T10:01:00+00:00", "kind": "note", "text": "b"},
            {"at": "2026-10-27T10:02:00+00:00", "kind": "thought", "text": "c"},
            {"at": "2026-10-27T10:03:00+00:00", "kind": "snippet", "text": "d"},
        ]
        sessions = segment(strokes, gap_threshold=600)
        assert sessions[0]["stroke_count"] == 4
        assert abs(sessions[0]["stroke_rate"] - 1.33) < 0.01

    def test_single_stroke_rate_is_zero(self):
        strokes = [{"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "solo"}]
        sessions = segment(strokes)
        assert sessions[0]["stroke_rate"] == 0.0

    def test_kinds_distribution(self):
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"at": "2026-10-27T10:00:15+00:00", "kind": "thought", "text": "b"},
            {"at": "2026-10-27T10:00:30+00:00", "kind": "note", "text": "c"},
        ]
        sessions = segment(strokes, gap_threshold=300)
        assert sessions[0]["kinds"] == {"thought": 2, "note": 1}

    def test_first_text_preview(self):
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "hello world"},
            {"at": "2026-10-27T10:00:15+00:00", "kind": "note", "text": "second"},
        ]
        sessions = segment(strokes, gap_threshold=300)
        assert sessions[0]["first_text"] == "hello world"

    def test_first_text_truncated_at_80(self):
        long_text = "x" * 120
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": long_text},
        ]
        sessions = segment(strokes)
        assert len(sessions[0]["first_text"]) == 80

    def test_session_id_sequential(self):
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"at": "2026-10-27T11:00:00+00:00", "kind": "thought", "text": "b"},
            {"at": "2026-10-27T12:00:00+00:00", "kind": "thought", "text": "c"},
        ]
        sessions = segment(strokes, gap_threshold=300)
        assert [s["session_id"] for s in sessions] == [1, 2, 3]


# ---------------------------------------------------------------------------
# custom gap threshold
# ---------------------------------------------------------------------------


class TestCustomThreshold:
    def test_large_threshold_merges_everything(self):
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"at": "2026-10-27T12:00:00+00:00", "kind": "thought", "text": "b"},
            {"at": "2026-10-27T14:00:00+00:00", "kind": "thought", "text": "c"},
        ]
        sessions = segment(strokes, gap_threshold=86400)
        assert len(sessions) == 1
        assert sessions[0]["stroke_count"] == 3

    def test_tiny_threshold_splits_everything(self):
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"at": "2026-10-27T10:00:01+00:00", "kind": "thought", "text": "b"},
            {"at": "2026-10-27T10:00:02+00:00", "kind": "thought", "text": "c"},
        ]
        sessions = segment(strokes, gap_threshold=0)
        assert len(sessions) == 3


# ---------------------------------------------------------------------------
# session_summary
# ---------------------------------------------------------------------------


class TestSessionSummary:
    def test_empty(self):
        summary = session_summary([])
        assert summary["total_sessions"] == 0
        assert summary["total_strokes"] == 0

    def test_single_session(self):
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"at": "2026-10-27T10:00:15+00:00", "kind": "note", "text": "b"},
            {"at": "2026-10-27T10:00:30+00:00", "kind": "thought", "text": "c"},
        ]
        summary = session_summary(strokes, gap_threshold=300)
        assert summary["total_sessions"] == 1
        assert summary["total_strokes"] == 3
        assert summary["avg_session_length"] == 3.0

    def test_micro_sessions_counted(self):
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"at": "2026-10-27T11:00:00+00:00", "kind": "thought", "text": "b"},
            {"at": "2026-10-27T11:00:15+00:00", "kind": "note", "text": "c"},
        ]
        summary = session_summary(strokes, gap_threshold=300)
        assert summary["micro_sessions"] == 1  # first session has 1 stroke

    def test_marathon_sessions_counted(self):
        # session lasting > 60 minutes
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"at": "2026-10-27T10:30:00+00:00", "kind": "note", "text": "b"},
            {"at": "2026-10-27T11:05:00+00:00", "kind": "thought", "text": "c"},
        ]
        summary = session_summary(strokes, gap_threshold=3600)
        assert summary["marathon_sessions"] == 1

    def test_longest_and_shortest(self):
        strokes = [
            {"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"},
            {"at": "2026-10-27T11:00:00+00:00", "kind": "thought", "text": "b"},
            {"at": "2026-10-27T11:00:15+00:00", "kind": "note", "text": "c"},
            {"at": "2026-10-27T11:00:30+00:00", "kind": "thought", "text": "d"},
        ]
        summary = session_summary(strokes, gap_threshold=300)
        assert summary["shortest_session"]["stroke_count"] == 1
        assert summary["longest_session"]["stroke_count"] == 3

    def test_gap_threshold_propagated(self):
        summary = session_summary([], gap_threshold=42)
        assert summary["gap_threshold_used"] == 42


# ---------------------------------------------------------------------------
# load_strokes
# ---------------------------------------------------------------------------


class TestLoadStrokes:
    def test_nonexistent_file(self, tmp_path):
        result = load_strokes(tmp_path / "nope.jsonl")
        assert result == []

    def test_valid_jsonl(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"}\n'
            '{"at": "2026-10-27T10:00:15+00:00", "kind": "note", "text": "b"}\n'
        )
        result = load_strokes(f)
        assert len(result) == 2

    def test_malformed_lines_skipped(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '{"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "ok"}\n'
            'this is not json\n'
            '{"at": "2026-10-27T10:00:15+00:00", "kind": "note", "text": "fine"}\n'
        )
        result = load_strokes(f)
        assert len(result) == 2

    def test_empty_lines_skipped(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text(
            '\n'
            '{"at": "2026-10-27T10:00:00+00:00", "kind": "thought", "text": "a"}\n'
            '\n'
        )
        result = load_strokes(f)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# real-repo integration
# ---------------------------------------------------------------------------


class TestRealRepoIntegration:
    def test_repo_strokes_parse(self):
        """Sanity check against the actual data/strokes.jsonl if it exists."""
        strokes_path = REPO / "data" / "strokes.jsonl"
        if not strokes_path.exists():
            pytest.skip("data/strokes.jsonl not present")

        strokes = load_strokes(strokes_path)
        assert len(strokes) > 0, "strokes.jsonl should not be empty"

        sessions = segment(strokes, gap_threshold=300)
        assert len(sessions) > 0, "should find at least one session"

        summary = session_summary(strokes, gap_threshold=300)
        # total_strokes may be slightly less than len(strokes) if some
        # entries have unparseable timestamps; it must be close though.
        assert summary["total_strokes"] > 0
        assert summary["total_strokes"] <= len(strokes)
        assert summary["total_sessions"] > 0
