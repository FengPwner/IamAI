"""tests for scripts/process_health_scorer.py"""

import sys
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from process_health_scorer import (
    load_state,
    parse_history,
    score_uptime,
    score_restarts,
    score_rhythm,
    health_score,
    full_report,
    format_report,
)


# ── helpers ──────────────────────────────────────────────────────────

def _make_entries(offsets_minutes: list[int], base: datetime | None = None) -> list[dict]:
    """构造 mock history 条目列表。"""
    if base is None:
        base = datetime(2026, 10, 21, 10, 0, 0, tzinfo=timezone.utc)
    return [
        {
            "at": base + timedelta(minutes=m),
            "kind": ["thought", "devlog", "garden", "note", "snippet", "metrics"][i % 6],
            "seq": 1000 + i,
        }
        for i, m in enumerate(offsets_minutes)
    ]


def _write_state_file(entries: list[dict]) -> str:
    """写入临时 state JSON 文件，返回路径。"""
    state = {
        "history": [
            {"at": e["at"].isoformat(), "kind": e["kind"], "seq": e["seq"]}
            for e in entries
        ]
    }
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f)
    return path


# ── load_state ───────────────────────────────────────────────────────

class TestLoadState:
    def test_nonexistent_file(self):
        result = load_state("/tmp/nonexistent_abc123.json")
        assert result == {}

    def test_valid_file(self):
        entries = _make_entries([0, 10, 20])
        path = _write_state_file(entries)
        try:
            result = load_state(path)
            assert "history" in result
            assert len(result["history"]) == 3
        finally:
            os.unlink(path)


# ── parse_history ────────────────────────────────────────────────────

class TestParseHistory:
    def test_empty_state(self):
        assert parse_history({}) == []

    def test_valid_entries(self):
        state = {
            "history": [
                {"at": "2026-10-21T10:00:00+00:00", "kind": "thought", "seq": 1},
                {"at": "2026-10-21T10:15:00+00:00", "kind": "devlog", "seq": 2},
            ]
        }
        result = parse_history(state)
        assert len(result) == 2
        assert result[0]["kind"] == "thought"
        assert result[1]["seq"] == 2

    def test_sorted_output(self):
        state = {
            "history": [
                {"at": "2026-10-21T10:30:00+00:00", "kind": "note", "seq": 3},
                {"at": "2026-10-21T10:00:00+00:00", "kind": "thought", "seq": 1},
                {"at": "2026-10-21T10:15:00+00:00", "kind": "devlog", "seq": 2},
            ]
        }
        result = parse_history(state)
        assert result[0]["seq"] == 1
        assert result[1]["seq"] == 2
        assert result[2]["seq"] == 3

    def test_invalid_timestamp_skipped(self):
        state = {
            "history": [
                {"at": "not-a-date", "kind": "thought", "seq": 1},
                {"at": "2026-10-21T10:00:00+00:00", "kind": "devlog", "seq": 2},
            ]
        }
        result = parse_history(state)
        assert len(result) == 1
        assert result[0]["seq"] == 2


# ── score_uptime ─────────────────────────────────────────────────────

class TestScoreUptime:
    def test_empty_entries(self):
        result = score_uptime([])
        assert result["uptime_ratio"] == 0.0

    def test_single_entry(self):
        entries = _make_entries([0])
        result = score_uptime(entries)
        assert result["uptime_ratio"] == 0.0

    def test_full_window_coverage(self):
        # 24 小时跨度 → ratio = 1.0
        entries = _make_entries([0, 1440])  # 0 and 24h in minutes
        result = score_uptime(entries, window_hours=24.0)
        assert result["uptime_ratio"] == 1.0
        assert result["active_span_hours"] == 24.0

    def test_half_window(self):
        entries = _make_entries([0, 720])  # 12h span
        result = score_uptime(entries, window_hours=24.0)
        assert result["uptime_ratio"] == 0.5
        assert result["active_span_hours"] == 12.0

    def test_exceeds_window_caps_at_one(self):
        entries = _make_entries([0, 2880])  # 48h span
        result = score_uptime(entries, window_hours=24.0)
        assert result["uptime_ratio"] == 1.0


# ── score_restarts ───────────────────────────────────────────────────

class TestScoreRestarts:
    def test_empty(self):
        result = score_restarts([])
        assert result["restart_count"] == 0
        assert result["restart_score"] == 1.0

    def test_no_restarts(self):
        # 每 5 分钟一次，没有超过 600s 的间隔
        entries = _make_entries([0, 5, 10, 15, 20])
        result = score_restarts(entries, gap_threshold_s=600.0)
        assert result["restart_count"] == 0
        assert result["restart_score"] == 1.0

    def test_one_restart(self):
        # 正常间隔后有一个 30 分钟的间隔
        entries = _make_entries([0, 5, 10, 40, 45])
        result = score_restarts(entries, gap_threshold_s=600.0)
        assert result["restart_count"] == 1
        assert result["restart_score"] == pytest.approx(0.85, abs=0.01)

    def test_multiple_restarts(self):
        # 多次重启
        entries = _make_entries([0, 5, 30, 35, 60, 65, 90, 95])
        result = score_restarts(entries, gap_threshold_s=600.0)
        assert result["restart_count"] == 3
        assert result["restart_score"] == pytest.approx(0.55, abs=0.01)

    def test_score_floors_at_zero(self):
        # 极端情况: 很多次重启
        offsets = [i * 30 for i in range(20)]  # 每 30 分钟一次
        entries = _make_entries(offsets)
        result = score_restarts(entries, gap_threshold_s=600.0)
        assert result["restart_score"] >= 0.0


# ── score_rhythm ─────────────────────────────────────────────────────

class TestScoreRhythm:
    def test_empty(self):
        result = score_rhythm([])
        assert result["rhythm_score"] == 0.0

    def test_single_entry(self):
        entries = _make_entries([0])
        result = score_rhythm(entries)
        assert result["rhythm_score"] == 0.0

    def test_two_entries(self):
        entries = _make_entries([0, 10])
        # 只有 1 个 gap，len(entries) < 3 → 无法计算
        result = score_rhythm(entries)
        assert result["rhythm_score"] == 0.0
        assert result["cv"] is None

    def test_perfect_rhythm(self):
        # 完全等间隔: CV = 0
        entries = _make_entries([0, 10, 20, 30, 40])
        result = score_rhythm(entries)
        assert result["rhythm_score"] == pytest.approx(1.0, abs=0.01)
        assert result["cv"] == pytest.approx(0.0, abs=0.01)

    def test_variable_rhythm(self):
        # 间隔: 5, 30, 5, 30 → 高 CV
        entries = _make_entries([0, 5, 35, 40, 70])
        result = score_rhythm(entries)
        assert result["rhythm_score"] < 0.5
        assert result["cv"] is not None
        assert result["cv"] > 0.5


# ── health_score ─────────────────────────────────────────────────────

class TestHealthScore:
    def test_perfect_health(self):
        uptime = {"uptime_ratio": 1.0}
        restarts = {"restart_score": 1.0}
        rhythm = {"rhythm_score": 1.0}
        result = health_score(uptime, restarts, rhythm)
        assert result["total"] == 100.0
        assert result["status"] == "healthy"

    def test_zero_health(self):
        uptime = {"uptime_ratio": 0.0}
        restarts = {"restart_score": 0.0}
        rhythm = {"rhythm_score": 0.0}
        result = health_score(uptime, restarts, rhythm)
        assert result["total"] == 0.0
        assert result["status"] == "unhealthy"

    def test_degraded_status(self):
        uptime = {"uptime_ratio": 0.5}
        restarts = {"restart_score": 0.5}
        rhythm = {"rhythm_score": 0.5}
        result = health_score(uptime, restarts, rhythm)
        assert 40 <= result["total"] < 70
        assert result["status"] == "degraded"

    def test_breakdown_sums(self):
        uptime = {"uptime_ratio": 0.8}
        restarts = {"restart_score": 0.6}
        rhythm = {"rhythm_score": 0.9}
        result = health_score(uptime, restarts, rhythm)
        bd = result["breakdown"]
        assert bd["uptime"] == pytest.approx(32.0, abs=0.1)
        assert bd["restarts"] == pytest.approx(18.0, abs=0.1)
        assert bd["rhythm"] == pytest.approx(27.0, abs=0.1)
        assert result["total"] == pytest.approx(77.0, abs=0.1)


# ── full_report (integration) ───────────────────────────────────────

class TestFullReport:
    def test_with_real_file(self):
        entries = _make_entries([0, 10, 20, 30, 40, 50, 60])
        path = _write_state_file(entries)
        try:
            report = full_report(path, window_hours=2.0)
            assert report["entries_analyzed"] == 7
            assert report["health"]["total"] > 0
            assert report["health"]["status"] in ("healthy", "degraded", "unhealthy")
        finally:
            os.unlink(path)

    def test_empty_file(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write("{}")
        try:
            report = full_report(path)
            assert report["entries_analyzed"] == 0
            # 0 entries → uptime=0, restarts=1.0(无重启), rhythm=0 → 30.0
            assert report["health"]["total"] == 30.0
            assert report["health"]["status"] == "unhealthy"
        finally:
            os.unlink(path)


# ── format_report ────────────────────────────────────────────────────

class TestFormatReport:
    def test_basic_format(self):
        report = {
            "entries_analyzed": 10,
            "uptime": {"uptime_ratio": 0.75, "active_span_hours": 18.0},
            "restarts": {"restart_count": 1, "restart_score": 0.85},
            "rhythm": {"rhythm_score": 0.9, "cv": 0.12},
            "health": {
                "total": 82.5,
                "status": "healthy",
                "breakdown": {"uptime": 30.0, "restarts": 25.5, "rhythm": 27.0},
            },
        }
        output = format_report(report)
        assert "82.5/100" in output
        assert "healthy" in output
        assert "1 次重启" in output
        assert "0.120" in output
