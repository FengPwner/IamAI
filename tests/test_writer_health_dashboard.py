"""Tests for iamai.writer_health_dashboard module."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_health_dashboard import (
    health_report,
    health_summary,
    _compute_grade,
    _format_summary,
    _inter_stroke_gaps,
    _median,
    _parse_ts,
)


# ── helpers ────────────────────────────────────────────────────


def _make_stroke(seq: int, text: str, ts: str, kind: str = "thought") -> dict:
    return {"seq": seq, "text": text, "at": ts, "kind": kind}


def _make_uniform_strokes(
    n: int,
    text: str = "sample stroke",
    gap_seconds: int = 15,
    kind: str = "thought",
    base_ts: str = "2026-10-20T10:00:00+00:00",
) -> list[dict]:
    """Generate n strokes with uniform gap."""
    from datetime import datetime, timedelta, timezone
    base_epoch = _parse_ts(base_ts)
    base_dt = datetime.fromtimestamp(base_epoch, tz=timezone.utc)
    strokes = []
    for i in range(n):
        ts = (base_dt + timedelta(seconds=gap_seconds * i)).isoformat()
        strokes.append(_make_stroke(i + 1, text, ts, kind))
    return strokes


def _make_mixed_strokes(
    n: int,
    kinds: list[str] | None = None,
    gap_seconds: int = 15,
    base_ts: str = "2026-10-20T10:00:00+00:00",
) -> list[dict]:
    """Generate n strokes cycling through kinds."""
    from datetime import datetime, timedelta, timezone
    if kinds is None:
        kinds = ["thought", "note", "snippet", "devlog", "garden", "metrics"]
    base_epoch = _parse_ts(base_ts)
    base_dt = datetime.fromtimestamp(base_epoch, tz=timezone.utc)
    strokes = []
    for i in range(n):
        ts = (base_dt + timedelta(seconds=gap_seconds * i)).isoformat()
        strokes.append(_make_stroke(i + 1, f"stroke {i}", ts, kinds[i % len(kinds)]))
    return strokes


# ── _parse_ts ──────────────────────────────────────────────────


class TestParseTs:
    def test_epoch_float(self):
        assert _parse_ts(1697000000.0) == 1697000000.0

    def test_epoch_int(self):
        assert _parse_ts(1697000000) == 1697000000.0

    def test_iso_string(self):
        result = _parse_ts("2026-10-20T10:00:00+00:00")
        assert result > 0

    def test_z_suffix(self):
        result = _parse_ts("2026-10-20T10:00:00Z")
        assert result > 0

    def test_invalid_string(self):
        assert _parse_ts("not a date") == 0.0

    def test_none(self):
        assert _parse_ts(None) == 0.0

    def test_numeric_string(self):
        assert _parse_ts("1697000000") == 1697000000.0


# ── _inter_stroke_gaps ─────────────────────────────────────────


class TestInterStrokeGaps:
    def test_uniform_gaps(self):
        strokes = _make_uniform_strokes(5, gap_seconds=15)
        gaps = _inter_stroke_gaps(strokes)
        assert len(gaps) == 4
        assert all(g == 15.0 for g in gaps)

    def test_variable_gaps(self):
        strokes = [
            _make_stroke(1, "a", "2026-10-20T10:00:00Z"),
            _make_stroke(2, "b", "2026-10-20T10:00:30Z"),
            _make_stroke(3, "c", "2026-10-20T10:01:00Z"),
        ]
        gaps = _inter_stroke_gaps(strokes)
        assert len(gaps) == 2
        assert gaps[0] == 30.0
        assert gaps[1] == 30.0

    def test_single_stroke(self):
        strokes = [_make_stroke(1, "only", "2026-10-20T10:00:00Z")]
        gaps = _inter_stroke_gaps(strokes)
        assert gaps == []

    def test_empty(self):
        assert _inter_stroke_gaps([]) == []


# ── _median ────────────────────────────────────────────────────


class TestMedian:
    def test_odd(self):
        assert _median([1, 3, 5]) == 3

    def test_even(self):
        assert _median([1, 2, 3, 4]) == 2.5

    def test_single(self):
        assert _median([7]) == 7

    def test_empty(self):
        assert _median([]) == 0.0

    def test_unsorted(self):
        assert _median([5, 1, 3]) == 3


# ── _compute_grade ─────────────────────────────────────────────


class TestComputeGrade:
    def test_healthy(self):
        signals = {"process_alive": "ok", "cadence_ok": "ok", "stall_absent": "ok"}
        assert _compute_grade(signals, True) == "healthy"

    def test_watching(self):
        signals = {"process_alive": "ok", "cadence_ok": "slow", "stall_absent": "ok"}
        assert _compute_grade(signals, True) == "watching"

    def test_attention(self):
        signals = {
            "process_alive": "ok",
            "cadence_ok": "degraded",
            "stall_absent": "ok",
        }
        assert _compute_grade(signals, True) == "attention"

    def test_critical_process_down(self):
        signals = {"process_alive": "down"}
        assert _compute_grade(signals, False) == "critical"

    def test_critical_multiple_problems(self):
        signals = {
            "process_alive": "ok",
            "cadence_ok": "degraded",
            "stall_absent": "stalled",
        }
        assert _compute_grade(signals, True) == "critical"


# ── _format_summary ────────────────────────────────────────────


class TestFormatSummary:
    def test_healthy(self):
        result = _format_summary("healthy", {"a": "ok", "b": "ok"}, [])
        assert "healthy" in result
        assert "2/2" in result

    def test_watching(self):
        result = _format_summary("watching", {"a": "slow"}, ["a: slow"])
        assert "watching" in result

    def test_attention(self):
        result = _format_summary("attention", {"a": "degraded"}, ["a: bad"])
        assert "attention" in result

    def test_critical(self):
        result = _format_summary("critical", {"a": "down"}, ["a: down", "b: stalled"])
        assert "critical" in result


# ── health_report: process alive signal ────────────────────────


class TestProcessAlive:
    def test_alive(self):
        strokes = _make_mixed_strokes(10)
        report = health_report(strokes, process_alive=True)
        assert report["signals"]["process_alive"] == "ok"

    def test_dead(self):
        strokes = _make_mixed_strokes(10)
        report = health_report(strokes, process_alive=False)
        assert report["signals"]["process_alive"] == "down"
        assert report["grade"] == "critical"
        assert any("process" in c for c in report["concerns"])


# ── health_report: cadence signal ──────────────────────────────


class TestCadence:
    def test_good_cadence(self):
        strokes = _make_mixed_strokes(20, gap_seconds=15)
        report = health_report(strokes, target_cadence_s=15)
        assert report["signals"]["cadence_ok"] == "ok"

    def test_slow_cadence(self):
        strokes = _make_mixed_strokes(20, gap_seconds=45)
        report = health_report(strokes, target_cadence_s=15)
        assert report["signals"]["cadence_ok"] == "slow"

    def test_degraded_cadence(self):
        strokes = _make_mixed_strokes(20, gap_seconds=120)
        report = health_report(strokes, target_cadence_s=15)
        assert report["signals"]["cadence_ok"] == "degraded"

    def test_insufficient_data(self):
        strokes = _make_mixed_strokes(3)
        report = health_report(strokes)
        assert report["signals"]["cadence_ok"] == "insufficient_data"


# ── health_report: stall signal ────────────────────────────────


class TestStall:
    def test_no_stall(self):
        strokes = _make_mixed_strokes(20, gap_seconds=15)
        report = health_report(strokes, stall_threshold_s=600)
        assert report["signals"]["stall_absent"] == "ok"

    def test_stall_detected(self):
        from datetime import datetime, timedelta, timezone
        # 10 strokes at 15s gap, then one huge gap
        strokes = _make_mixed_strokes(10, gap_seconds=15)
        last_ts = datetime.fromtimestamp(
            _parse_ts(strokes[-1]["at"]), tz=timezone.utc
        )
        gap_ts = (last_ts + timedelta(seconds=1200)).isoformat()
        strokes.append(_make_stroke(11, "after stall", gap_ts))
        report = health_report(strokes, stall_threshold_s=600)
        assert report["signals"]["stall_absent"] == "stalled"

    def test_insufficient_data(self):
        strokes = [_make_stroke(1, "only", "2026-10-20T10:00:00Z")]
        report = health_report(strokes)
        assert report["signals"]["stall_absent"] == "insufficient_data"


# ── health_report: diversity signal ────────────────────────────


class TestDiversity:
    def test_diverse(self):
        strokes = _make_mixed_strokes(
            30,
            kinds=["thought", "note", "snippet", "devlog", "garden", "metrics"],
        )
        report = health_report(strokes)
        assert report["signals"]["diversity_ok"] == "ok"

    def test_narrowing(self):
        # 60% one kind, 40% others
        kinds = ["thought"] * 12 + ["note"] * 8
        strokes = _make_mixed_strokes(20, kinds=kinds)
        report = health_report(strokes)
        assert report["signals"]["diversity_ok"] == "narrowing"

    def test_loop(self):
        # 80% one kind
        kinds = ["thought"] * 16 + ["note"] * 4
        strokes = _make_mixed_strokes(20, kinds=kinds)
        report = health_report(strokes)
        assert report["signals"]["diversity_ok"] == "loop"


# ── health_report: recovery signal ─────────────────────────────


class TestRecovery:
    def test_full_recovery(self):
        strokes = _make_mixed_strokes(10)
        report = health_report(strokes, recovery_fidelity_grade="full")
        assert report["signals"]["recovery_recent"] == "ok"

    def test_good_recovery(self):
        strokes = _make_mixed_strokes(10)
        report = health_report(strokes, recovery_fidelity_grade="good")
        assert report["signals"]["recovery_recent"] == "ok"

    def test_partial_recovery(self):
        strokes = _make_mixed_strokes(10)
        report = health_report(strokes, recovery_fidelity_grade="partial")
        assert report["signals"]["recovery_recent"] == "recovering"
        assert any("recovering" in c or "partial" in c for c in report["concerns"])

    def test_poor_recovery(self):
        strokes = _make_mixed_strokes(10)
        report = health_report(strokes, recovery_fidelity_grade="poor")
        assert report["signals"]["recovery_recent"] == "degraded"
        assert any("poor" in c for c in report["concerns"])

    def test_not_applicable(self):
        strokes = _make_mixed_strokes(10)
        report = health_report(strokes, recovery_fidelity_grade=None)
        assert report["signals"]["recovery_recent"] == "not_applicable"


# ── health_report: overall grade ───────────────────────────────


class TestOverallGrade:
    def test_all_healthy(self):
        strokes = _make_mixed_strokes(20, gap_seconds=15)
        report = health_report(strokes, target_cadence_s=15, stall_threshold_s=600)
        assert report["grade"] == "healthy"

    def test_process_down_is_critical(self):
        strokes = _make_mixed_strokes(20, gap_seconds=15)
        report = health_report(strokes, process_alive=False)
        assert report["grade"] == "critical"

    def test_stall_is_attention(self):
        from datetime import datetime, timedelta, timezone
        strokes = _make_mixed_strokes(10, gap_seconds=15)
        last_ts = datetime.fromtimestamp(
            _parse_ts(strokes[-1]["at"]), tz=timezone.utc
        )
        gap_ts = (last_ts + timedelta(seconds=1200)).isoformat()
        strokes.append(_make_stroke(11, "after", gap_ts))
        report = health_report(strokes, stall_threshold_s=600)
        assert report["grade"] in ("attention", "critical")


# ── health_report: report structure ────────────────────────────


class TestReportStructure:
    def test_has_required_keys(self):
        strokes = _make_mixed_strokes(10)
        report = health_report(strokes)
        assert "grade" in report
        assert "signals" in report
        assert "concerns" in report
        assert "summary" in report

    def test_summary_is_string(self):
        strokes = _make_mixed_strokes(10)
        report = health_report(strokes)
        assert isinstance(report["summary"], str)
        assert len(report["summary"]) > 0

    def test_concerns_is_list(self):
        strokes = _make_mixed_strokes(10)
        report = health_report(strokes)
        assert isinstance(report["concerns"], list)


# ── health_summary ─────────────────────────────────────────────


class TestHealthSummary:
    def test_returns_string(self):
        strokes = _make_mixed_strokes(20, gap_seconds=15)
        result = health_summary(strokes, target_cadence_s=15)
        assert isinstance(result, str)
        assert "healthy" in result or "watching" in result or "attention" in result

    def test_healthy_output(self):
        strokes = _make_mixed_strokes(20, gap_seconds=15)
        result = health_summary(strokes, target_cadence_s=15, stall_threshold_s=600)
        assert "healthy" in result

    def test_critical_output(self):
        strokes = _make_mixed_strokes(10)
        result = health_summary(strokes, process_alive=False)
        assert "critical" in result
