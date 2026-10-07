"""Tests for iamai.stroke_pacer."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iamai.stroke_pacer import (
    _load_strokes,
    _parse_ts,
    _strokes_since,
    _verdict,
    pace_report,
    pace_summary,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_repo(tmp_path: Path, strokes: list[dict] | None = None) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    if strokes is not None:
        with open(data_dir / "strokes.jsonl", "w", encoding="utf-8") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")
    return tmp_path


def _stroke(hours_ago: float, kind: str = "thought") -> dict:
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {"seq": 1, "at": ts.isoformat(), "kind": kind, "text": "test"}


# ---------------------------------------------------------------------------
# _load_strokes
# ---------------------------------------------------------------------------


class TestLoadStrokes:
    def test_missing_file(self, tmp_path):
        assert _load_strokes(tmp_path / "nonexistent.jsonl") == []

    def test_loads_valid_lines(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            '{"seq":1,"at":"2026-10-07T10:00:00+00:00","kind":"thought","text":"a"}\n'
            '{"seq":2,"at":"2026-10-07T10:01:00+00:00","kind":"note","text":"b"}\n',
            encoding="utf-8",
        )
        result = _load_strokes(p)
        assert len(result) == 2
        assert result[0]["seq"] == 1

    def test_skips_malformed_lines(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            '{"seq":1,"at":"2026-10-07T10:00:00+00:00","kind":"thought","text":"ok"}\n'
            "this is not json\n"
            '{"seq":2,"at":"2026-10-07T10:01:00+00:00","kind":"note","text":"ok2"}\n',
            encoding="utf-8",
        )
        result = _load_strokes(p)
        assert len(result) == 2

    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("", encoding="utf-8")
        assert _load_strokes(p) == []


# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------


class TestParseTs:
    def test_utc_iso(self):
        dt = _parse_ts("2026-10-07T12:00:00+00:00")
        assert dt.hour == 12
        assert dt.tzinfo is not None

    def test_naive_assumed_utc(self):
        dt = _parse_ts("2026-10-07T12:00:00")
        assert dt.tzinfo == timezone.utc

    def test_offset_converted_to_utc(self):
        dt = _parse_ts("2026-10-07T20:00:00+08:00")
        assert dt.hour == 12  # 20:00 CST = 12:00 UTC


# ---------------------------------------------------------------------------
# _strokes_since
# ---------------------------------------------------------------------------


class TestStrokesSince:
    def test_counts_after_cutoff(self):
        now = datetime.now(timezone.utc)
        strokes = [
            {"seq": 1, "at": (now - timedelta(hours=1)).isoformat()},
            {"seq": 2, "at": (now - timedelta(hours=3)).isoformat()},
            {"seq": 3, "at": (now - timedelta(hours=5)).isoformat()},
        ]
        cutoff = now - timedelta(hours=4)
        assert _strokes_since(strokes, cutoff) == 2

    def test_skips_bad_entries(self):
        strokes = [
            {"seq": 1, "at": "not-a-date"},
            {"seq": 2},  # missing 'at'
            {"seq": 3, "at": datetime.now(timezone.utc).isoformat()},
        ]
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        assert _strokes_since(strokes, cutoff) == 1

    def test_empty_list(self):
        assert _strokes_since([], datetime.now(timezone.utc)) == 0


# ---------------------------------------------------------------------------
# _verdict
# ---------------------------------------------------------------------------


class TestVerdict:
    def test_ahead_when_target_met(self):
        assert _verdict(1000, 1000, 5.0, 200.0) == "ahead"

    def test_ahead_when_exceeding(self):
        assert _verdict(1100, 1000, 2.0, 100.0) == "ahead"

    def test_behind_when_no_time_left(self):
        assert _verdict(500, 1000, 0.0, 200.0) == "behind"

    def test_on_track_when_rate_sufficient(self):
        # 500 remaining, 5 hours left → need 100/hr; have 90/hr
        # 90 >= 100*0.8=80 → on_track
        assert _verdict(500, 1000, 5.0, 90.0) == "on_track"

    def test_behind_when_rate_too_low(self):
        # 800 remaining, 4 hours left → need 200/hr; have 50/hr
        # 50 < 200*0.8=160 → behind
        assert _verdict(200, 1000, 4.0, 50.0) == "behind"

    def test_ahead_when_rate_exceeds_required(self):
        # 100 remaining, 5 hours left → need 20/hr; have 50/hr
        # 50 >= 20*1.2=24 → ahead
        assert _verdict(900, 1000, 5.0, 50.0) == "ahead"


# ---------------------------------------------------------------------------
# pace_report
# ---------------------------------------------------------------------------


class TestPaceReport:
    def test_basic_report(self, tmp_path):
        now = datetime.now(timezone.utc)
        # 10 strokes in the last 30 min, 10 strokes from 2 hours ago
        recent = [
            _stroke(hours_ago=0.1 * i) for i in range(1, 11)
        ]
        old = [_stroke(hours_ago=2.0 + i) for i in range(10)]
        repo = _make_repo(tmp_path, recent + old)
        report = pace_report(
            daily_target=200,
            strokes_path=repo / "data" / "strokes.jsonl",
            now=now,
        )
        assert report["daily_target"] == 200
        assert report["strokes_today"] == 20
        assert report["remaining"] == 180
        assert report["hours_left"] > 0
        assert report["verdict"] in ("ahead", "on_track", "behind")
        assert report["projected_total"] >= 20

    def test_target_already_met(self, tmp_path):
        now = datetime(2026, 10, 7, 14, 0, 0, tzinfo=timezone.utc)
        strokes = [
            {
                "seq": i,
                "at": (now - timedelta(minutes=i)).isoformat(),
                "kind": "thought",
                "text": f"stroke {i}",
            }
            for i in range(1, 51)  # 50 strokes today
        ]
        repo = _make_repo(tmp_path, strokes)
        report = pace_report(
            daily_target=50,
            strokes_path=repo / "data" / "strokes.jsonl",
            now=now,
        )
        assert report["verdict"] == "ahead"
        assert report["remaining"] == 0

    def test_empty_repo(self, tmp_path):
        repo = _make_repo(tmp_path)
        now = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
        report = pace_report(
            daily_target=100,
            strokes_path=repo / "data" / "strokes.jsonl",
            now=now,
        )
        assert report["strokes_today"] == 0
        assert report["remaining"] == 100
        assert report["verdict"] == "behind"

    def test_end_of_day_behind(self, tmp_path):
        # 23:30 UTC, only 10 strokes vs target 100
        now = datetime(2026, 10, 7, 23, 30, 0, tzinfo=timezone.utc)
        strokes = [
            {
                "seq": i,
                "at": (now - timedelta(minutes=i * 2)).isoformat(),
                "kind": "thought",
                "text": f"stroke {i}",
            }
            for i in range(1, 11)
        ]
        repo = _make_repo(tmp_path, strokes)
        report = pace_report(
            daily_target=100,
            strokes_path=repo / "data" / "strokes.jsonl",
            now=now,
        )
        assert report["hours_left"] == pytest.approx(0.5, abs=0.01)
        assert report["remaining"] == 90
        assert report["verdict"] == "behind"

    def test_projected_total_uses_current_rate(self, tmp_path):
        now = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
        # 60 strokes in last hour → rate = 60/hr; 12 hours left → +720
        strokes = [
            {
                "seq": i,
                "at": (now - timedelta(minutes=i)).isoformat(),
                "kind": "thought",
                "text": f"stroke {i}",
            }
            for i in range(1, 61)
        ]
        repo = _make_repo(tmp_path, strokes)
        report = pace_report(
            daily_target=1000,
            strokes_path=repo / "data" / "strokes.jsonl",
            now=now,
        )
        # 60 done + 60*12 = 780 projected
        assert report["projected_total"] == pytest.approx(780, abs=5)


# ---------------------------------------------------------------------------
# pace_summary
# ---------------------------------------------------------------------------


class TestPaceSummary:
    def test_returns_string(self, tmp_path):
        repo = _make_repo(tmp_path, [_stroke(0.5), _stroke(1.0)])
        result = pace_summary(
            daily_target=100,
            strokes_path=repo / "data" / "strokes.jsonl",
        )
        assert isinstance(result, str)
        assert "/100" in result
        assert "strokes today" in result

    def test_empty_repo(self, tmp_path):
        repo = _make_repo(tmp_path)
        result = pace_summary(
            daily_target=50,
            strokes_path=repo / "data" / "strokes.jsonl",
        )
        assert "0/50" in result
        assert "behind" in result
