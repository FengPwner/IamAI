"""Tests for iamai.stroke_category_recency — category cooling detector.

Visit 807: this module was created to complement stroke_category_balance
(which measures distribution) by adding the temporal dimension — how
long since each category was last written to.  A category that was
historically well-represent can still go cold if the writer focuses
exclusively on other categories for an extended period.

Test areas:
    1. _load_strokes       — file reading, missing file, malformed lines
    2. _parse_timestamp    — ISO-8601 parsing, Z suffix, timezone-naive
    3. category_recency    — seconds since last stroke per category
    4. warmth_score        — composite 0–100, edge cases
    5. cold_categories     — threshold-based cold detection
    6. coldest_category    — max-recency selection
    7. suggestion          — which category to write next
    8. recency_report      — full report structure
    9. recency_summary     — human-readable format
   10. _cli                — exit codes, --json flag
   11. edge cases          — empty strokes, single category, all cold
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_category_recency import (
    _cli,
    _load_strokes,
    _parse_timestamp,
    category_recency,
    cold_categories,
    coldest_category,
    recency_report,
    recency_summary,
    suggestion,
    warmth_score,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _stroke(kind: str, at: str, seq: int = 0) -> dict:
    return {"seq": seq, "kind": kind, "at": at, "text": "test stroke"}


def _write_strokes(tmp_path: Path, strokes: list[dict]) -> Path:
    p = tmp_path / "strokes.jsonl"
    lines = [json.dumps(s) for s in strokes]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


NOW = 1700000000.0  # fixed epoch for deterministic tests
BASE = "2023-11-14T22:13:20+00:00"  # matches NOW


def _ts(offset_seconds: float) -> str:
    """Return an ISO timestamp offset from NOW by the given seconds."""
    from datetime import datetime, timezone

    dt = datetime.fromtimestamp(NOW - offset_seconds, tz=timezone.utc)
    return dt.isoformat()


# -----------------------------------------------------------------------
# 1. _load_strokes
# -----------------------------------------------------------------------


class TestLoadStrokes:
    def test_load_basic(self, tmp_path):
        strokes = [_stroke("thought", _ts(10), 1), _stroke("note", _ts(5), 2)]
        path = _write_strokes(tmp_path, strokes)
        loaded = _load_strokes(path)
        assert len(loaded) == 2
        assert loaded[0]["kind"] == "thought"

    def test_load_with_n(self, tmp_path):
        strokes = [_stroke("thought", _ts(i * 10), i) for i in range(10)]
        path = _write_strokes(tmp_path, strokes)
        loaded = _load_strokes(path, n=3)
        assert len(loaded) == 3
        assert loaded[0]["seq"] == 7  # last 3

    def test_missing_file(self, tmp_path):
        loaded = _load_strokes(tmp_path / "nonexistent.jsonl")
        assert loaded == []

    def test_malformed_lines_skipped(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            '{"seq": 1, "kind": "thought", "at": "2023-01-01T00:00:00+00:00", "text": "ok"}\n'
            "not json at all\n"
            "\n"
            '{"seq": 2, "kind": "note", "at": "2023-01-01T00:01:00+00:00", "text": "ok"}\n',
            encoding="utf-8",
        )
        loaded = _load_strokes(p)
        assert len(loaded) == 2

    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("", encoding="utf-8")
        assert _load_strokes(p) == []


# -----------------------------------------------------------------------
# 2. _parse_timestamp
# -----------------------------------------------------------------------


class TestParseTimestamp:
    def test_iso_with_offset(self):
        ts = _parse_timestamp("2023-11-14T22:13:20+00:00")
        assert ts > 0

    def test_z_suffix(self):
        ts = _parse_timestamp("2023-11-14T22:13:20Z")
        assert ts > 0

    def test_invalid_returns_zero(self):
        assert _parse_timestamp("not a timestamp") == 0.0

    def test_empty_returns_zero(self):
        assert _parse_timestamp("") == 0.0

    def test_consistent_ordering(self):
        ts1 = _parse_timestamp("2023-01-01T00:00:00+00:00")
        ts2 = _parse_timestamp("2023-12-01T00:00:00+00:00")
        assert ts2 > ts1


# -----------------------------------------------------------------------
# 3. category_recency
# -----------------------------------------------------------------------


class TestCategoryRecency:
    def test_all_categories_present(self):
        strokes = [
            _stroke("thought", _ts(100)),
            _stroke("note", _ts(200)),
            _stroke("devlog", _ts(300)),
            _stroke("garden", _ts(400)),
            _stroke("metrics", _ts(500)),
            _stroke("snippet", _ts(600)),
        ]
        rec = category_recency(strokes, now=NOW)
        assert abs(rec["thought"] - 100) < 2
        assert abs(rec["snippet"] - 600) < 2
        assert len(rec) == 6

    def test_missing_categories_get_inf(self):
        strokes = [_stroke("thought", _ts(50))]
        rec = category_recency(strokes, now=NOW)
        assert rec["thought"] < 60
        assert rec["note"] == float("inf")
        assert rec["devlog"] == float("inf")

    def test_uses_most_recent_stroke(self):
        strokes = [
            _stroke("thought", _ts(1000)),  # older
            _stroke("thought", _ts(50)),    # newer
        ]
        rec = category_recency(strokes, now=NOW)
        assert rec["thought"] < 60  # should use the newer one

    def test_custom_categories(self):
        strokes = [_stroke("alpha", _ts(30)), _stroke("beta", _ts(60))]
        rec = category_recency(strokes, now=NOW, categories={"alpha", "beta"})
        assert abs(rec["alpha"] - 30) < 2
        assert abs(rec["beta"] - 60) < 2

    def test_empty_strokes(self):
        rec = category_recency([], now=NOW)
        assert all(v == float("inf") for v in rec.values())


# -----------------------------------------------------------------------
# 4. warmth_score
# -----------------------------------------------------------------------


class TestWarmthScore:
    def test_all_warm(self):
        rec = {"a": 0.0, "b": 0.0, "c": 0.0}
        ws = warmth_score(rec, half_life=100)
        assert ws == 100.0

    def test_all_cold(self):
        rec = {"a": 10000.0, "b": 10000.0}
        ws = warmth_score(rec, half_life=100)
        assert ws < 5.0

    def test_mixed(self):
        rec = {"a": 0.0, "b": 100.0}  # one warm, one at half-life
        ws = warmth_score(rec, half_life=100)
        # a contributes 1.0, b contributes 0.5 → mean 0.75 → 75.0
        assert abs(ws - 75.0) < 0.1

    def test_inf_gets_zero(self):
        rec = {"a": 0.0, "b": float("inf")}
        ws = warmth_score(rec, half_life=100)
        # a=1.0, b=0.0 → mean 0.5 → 50.0
        assert abs(ws - 50.0) < 0.1

    def test_empty_returns_zero(self):
        assert warmth_score({}) == 0.0

    def test_scale_0_to_100(self):
        rec = {f"cat_{i}": i * 100.0 for i in range(10)}
        ws = warmth_score(rec, half_life=500)
        assert 0 <= ws <= 100


# -----------------------------------------------------------------------
# 5. cold_categories
# -----------------------------------------------------------------------


class TestColdCategories:
    def test_detects_cold(self):
        rec = {"a": 10.0, "b": 5000.0, "c": 10000.0}
        cold = cold_categories(rec, half_life=100, cold_multiplier=3.0)
        assert "b" in cold
        assert "c" in cold
        assert "a" not in cold

    def test_all_warm(self):
        rec = {"a": 10.0, "b": 20.0}
        cold = cold_categories(rec, half_life=100, cold_multiplier=3.0)
        assert cold == []

    def test_all_cold(self):
        rec = {"a": 5000.0, "b": 8000.0}
        cold = cold_categories(rec, half_life=100, cold_multiplier=3.0)
        assert set(cold) == {"a", "b"}

    def test_inf_is_cold(self):
        rec = {"a": float("inf"), "b": 10.0}
        cold = cold_categories(rec, half_life=100, cold_multiplier=3.0)
        assert "a" in cold

    def test_sorted_output(self):
        rec = {"z": 9000.0, "a": 5000.0, "m": 7000.0}
        cold = cold_categories(rec, half_life=100, cold_multiplier=3.0)
        assert cold == sorted(cold)

    def test_custom_multiplier(self):
        rec = {"a": 500.0}
        # with multiplier 2 → threshold = 200, so 500 is cold
        assert "a" in cold_categories(rec, half_life=100, cold_multiplier=2.0)
        # with multiplier 10 → threshold = 1000, so 500 is warm
        assert "a" not in cold_categories(rec, half_life=100, cold_multiplier=10.0)


# -----------------------------------------------------------------------
# 6. coldest_category
# -----------------------------------------------------------------------


class TestColdestCategory:
    def test_basic(self):
        rec = {"a": 100.0, "b": 500.0, "c": 50.0}
        assert coldest_category(rec) == "b"

    def test_empty(self):
        assert coldest_category({}) is None

    def test_single(self):
        assert coldest_category({"only": 42.0}) == "only"

    def test_tie(self):
        rec = {"a": 100.0, "b": 100.0}
        result = coldest_category(rec)
        assert result in ("a", "b")

    def test_inf_wins(self):
        rec = {"a": 100.0, "b": float("inf")}
        assert coldest_category(rec) == "b"


# -----------------------------------------------------------------------
# 7. suggestion
# -----------------------------------------------------------------------


class TestSuggestion:
    def test_suggests_coldest_cold(self):
        rec = {"a": 10.0, "b": 5000.0, "c": 8000.0}
        sugg = suggestion(rec, half_life=100, cold_multiplier=3.0)
        assert sugg == "c"

    def test_none_when_all_warm(self):
        rec = {"a": 10.0, "b": 20.0}
        sugg = suggestion(rec, half_life=100, cold_multiplier=3.0)
        assert sugg is None

    def test_picks_among_cold(self):
        rec = {"a": 10.0, "b": 1000.0, "c": 2000.0}
        sugg = suggestion(rec, half_life=100, cold_multiplier=3.0)
        assert sugg == "c"  # coldest of the two cold ones


# -----------------------------------------------------------------------
# 8. recency_report
# -----------------------------------------------------------------------


class TestRecencyReport:
    def test_report_structure(self, tmp_path):
        strokes = [
            _stroke("thought", _ts(100)),
            _stroke("note", _ts(200)),
            _stroke("devlog", _ts(300)),
            _stroke("garden", _ts(400)),
            _stroke("metrics", _ts(500)),
            _stroke("snippet", _ts(600)),
        ]
        path = _write_strokes(tmp_path, strokes)
        report = recency_report(strokes_path=path, now=NOW)

        assert "category_recency" in report
        assert "warmth_score" in report
        assert "coldest_category" in report
        assert "cold_categories" in report
        assert "suggestion" in report
        assert "total_strokes" in report
        assert report["total_strokes"] == 6
        assert isinstance(report["warmth_score"], float)

    def test_inf_encoded_as_negative(self, tmp_path):
        # only write one category, rest should be -1 in output
        strokes = [_stroke("thought", _ts(50))]
        path = _write_strokes(tmp_path, strokes)
        report = recency_report(strokes_path=path, now=NOW)
        assert report["category_recency"]["thought"] >= 0
        assert report["category_recency"]["note"] == -1

    def test_empty_strokes(self, tmp_path):
        path = _write_strokes(tmp_path, [])
        report = recency_report(strokes_path=path, now=NOW)
        assert report["total_strokes"] == 0
        assert report["warmth_score"] == 0.0


# -----------------------------------------------------------------------
# 9. recency_summary
# -----------------------------------------------------------------------


class TestRecencySummary:
    def test_contains_warmth(self):
        report = {
            "category_recency": {"thought": 50.0, "note": 300.0},
            "warmth_score": 72.5,
            "cold_categories": [],
            "suggestion": None,
        }
        text = recency_summary(report)
        assert "72.5" in text
        assert "all categories warm" in text

    def test_shows_cold_marker(self):
        report = {
            "category_recency": {"thought": 50.0, "note": 9000.0},
            "warmth_score": 30.0,
            "cold_categories": ["note"],
            "suggestion": "note",
        }
        text = recency_summary(report)
        assert "❄" in text
        assert "suggest writing: note" in text

    def test_time_formatting(self):
        report = {
            "category_recency": {
                "seconds": 30.0,
                "minutes": 300.0,
                "hours": 7200.0,
                "days": 172800.0,
                "never": -1,
            },
            "warmth_score": 50.0,
            "cold_categories": [],
            "suggestion": None,
        }
        text = recency_summary(report)
        assert "30s ago" in text
        assert "5m ago" in text
        assert "2.0h ago" in text
        assert "2.0d ago" in text
        assert "never" in text


# -----------------------------------------------------------------------
# 10. _cli
# -----------------------------------------------------------------------


class TestCli:
    def test_json_output(self, tmp_path, capsys):
        strokes = [
            _stroke("thought", _ts(100)),
            _stroke("note", _ts(200)),
        ]
        path = _write_strokes(tmp_path, strokes)
        exit_code = _cli(["--strokes", str(path), "--json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "warmth_score" in data
        assert exit_code in (0, 1)

    def test_text_output(self, tmp_path, capsys):
        strokes = [_stroke("thought", _ts(50))]
        path = _write_strokes(tmp_path, strokes)
        exit_code = _cli(["--strokes", str(path)])
        captured = capsys.readouterr()
        assert "warmth" in captured.out

    def test_exit_1_when_cold(self, tmp_path):
        # write only one category — others will be inf (cold)
        strokes = [_stroke("thought", _ts(50))]
        path = _write_strokes(tmp_path, strokes)
        exit_code = _cli(["--strokes", str(path)])
        assert exit_code == 1

    def test_exit_0_when_all_warm(self, tmp_path):
        # write all 6 categories recently (use real current time for CLI)
        import time as _time

        real_now = _time.time()

        def _real_ts(offset: float) -> str:
            from datetime import datetime, timezone

            dt = datetime.fromtimestamp(real_now - offset, tz=timezone.utc)
            return dt.isoformat()

        strokes = [
            _stroke("thought", _real_ts(10)),
            _stroke("note", _real_ts(20)),
            _stroke("devlog", _real_ts(30)),
            _stroke("garden", _real_ts(40)),
            _stroke("metrics", _real_ts(50)),
            _stroke("snippet", _real_ts(60)),
        ]
        path = _write_strokes(tmp_path, strokes)
        exit_code = _cli([
            "--strokes", str(path),
            "--cold-multiplier", "100",
        ])
        assert exit_code == 0


# -----------------------------------------------------------------------
# 11. Edge cases
# -----------------------------------------------------------------------


class TestEdgeCases:
    def test_single_stroke(self):
        strokes = [_stroke("thought", _ts(100))]
        rec = category_recency(strokes, now=NOW)
        assert rec["thought"] < 110
        assert rec["note"] == float("inf")

    def test_duplicate_category_uses_latest(self):
        strokes = [
            _stroke("thought", _ts(1000)),
            _stroke("note", _ts(500)),
            _stroke("thought", _ts(10)),  # newer thought
        ]
        rec = category_recency(strokes, now=NOW)
        assert rec["thought"] < 20
        assert abs(rec["note"] - 500) < 2

    def test_custom_half_life(self):
        rec = {"a": 50.0, "b": 50.0}
        # with large half-life, 50s is warm
        ws_warm = warmth_score(rec, half_life=1000)
        # with tiny half-life, 50s is cold
        ws_cold = warmth_score(rec, half_life=1)
        assert ws_warm > ws_cold

    def test_zero_half_life_guard(self):
        rec = {"a": 100.0}
        ws = warmth_score(rec, half_life=0)
        # should not crash; half_life gets clamped to 1.0
        assert 0 <= ws <= 100
