"""Tests for iamai.caretaker_burnout module."""

import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.caretaker_burnout import (
    BurnoutReport,
    burnout_report,
    burnout_summary,
    _classify_severity,
    _fix_durability_hours,
    _intervention_rate,
    _parse_ts,
    _repeat_issue_ratio,
    _sort_interventions,
)


# ── helpers ────────────────────────────────────────────────────


def _iv(ts: str, kind: str = "restart") -> dict:
    return {"ts": ts, "kind": kind}


def _make_timeline(kinds: list[str], gap_hours: float = 2.0,
                   base: str = "2026-10-22T00:00:00+00:00") -> list[dict]:
    """Build a list of interventions with uniform gaps."""
    from datetime import datetime, timedelta, timezone
    t = _parse_ts(base)
    ivs = []
    for i, k in enumerate(kinds):
        ts = (t + timedelta(hours=gap_hours * i)).isoformat()
        ivs.append(_iv(ts, k))
    return ivs


# ── _parse_ts ─────────────────────────────────────────────────


class TestParseTs:
    def test_utc_z(self):
        dt = _parse_ts("2026-10-22T12:00:00Z")
        assert dt.hour == 12
        assert dt.utcoffset().total_seconds() == 0

    def test_offset(self):
        dt = _parse_ts("2026-10-22T12:00:00+08:00")
        assert dt.utcoffset().total_seconds() == 8 * 3600

    def test_space_separator(self):
        dt = _parse_ts("2026-10-22 12:00:00+00:00")
        assert dt.hour == 12

    def test_no_tz(self):
        dt = _parse_ts("2026-10-22T12:00:00")
        # defaults to UTC
        assert dt.utcoffset().total_seconds() == 0

    def test_invalid(self):
        with pytest.raises(ValueError):
            _parse_ts("not-a-date")

    def test_fractional_seconds(self):
        dt = _parse_ts("2026-10-22T12:00:00.123456+00:00")
        assert dt.hour == 12


# ── _sort_interventions ───────────────────────────────────────


class TestSortInterventions:
    def test_sorted(self):
        ivs = [
            _iv("2026-10-22T03:00:00Z", "restart"),
            _iv("2026-10-22T01:00:00Z", "flush"),
            _iv("2026-10-22T02:00:00Z", "restart"),
        ]
        s = _sort_interventions(ivs)
        assert [d["kind"] for d in s] == ["flush", "restart", "restart"]

    def test_skips_bad_ts(self):
        ivs = [_iv("bad", "x"), _iv("2026-10-22T01:00:00Z", "ok")]
        s = _sort_interventions(ivs)
        assert len(s) == 1
        assert s[0]["kind"] == "ok"

    def test_empty(self):
        assert _sort_interventions([]) == []


# ── _intervention_rate ────────────────────────────────────────


class TestInterventionRate:
    def test_single(self):
        s = _sort_interventions([_iv("2026-10-22T00:00:00Z")])
        assert _intervention_rate(s) == 1.0

    def test_empty(self):
        assert _intervention_rate([]) == 0.0

    def test_one_per_day(self):
        ivs = _make_timeline(["restart"] * 4, gap_hours=24)
        s = _sort_interventions(ivs)
        # 4 over 72 h → 4 / 3 = 1.333/day
        rate = _intervention_rate(s)
        assert abs(rate - 4 / 3) < 0.01

    def test_high_rate(self):
        # 12 interventions in 6 hours → 48/day
        ivs = _make_timeline(["restart"] * 12, gap_hours=0.5)
        s = _sort_interventions(ivs)
        rate = _intervention_rate(s)
        assert rate > 40

    def test_same_timestamp(self):
        ivs = [
            _iv("2026-10-22T00:00:00Z"),
            _iv("2026-10-22T00:00:00Z"),
            _iv("2026-10-22T00:00:00Z"),
        ]
        s = _sort_interventions(ivs)
        # falls back to 1h window → 3 interventions
        assert _intervention_rate(s) == 3.0


# ── _repeat_issue_ratio ──────────────────────────────────────


class TestRepeatIssueRatio:
    def test_no_repeats(self):
        ivs = _sort_interventions(
            _make_timeline(["restart", "flush", "lock_cleanup"])
        )
        assert _repeat_issue_ratio(ivs) == 0.0

    def test_all_repeats(self):
        ivs = _sort_interventions(
            _make_timeline(["restart", "restart", "restart", "restart"])
        )
        assert _repeat_issue_ratio(ivs) == 1.0

    def test_half_repeats(self):
        # restart, restart, flush, flush → 2 repeats out of 3 transitions
        ivs = _sort_interventions(
            _make_timeline(["restart", "restart", "flush", "flush"])
        )
        ratio = _repeat_issue_ratio(ivs)
        assert abs(ratio - 2 / 3) < 0.01

    def test_single(self):
        s = _sort_interventions([_iv("2026-10-22T00:00:00Z")])
        assert _repeat_issue_ratio(s) == 0.0

    def test_empty(self):
        assert _repeat_issue_ratio([]) == 0.0


# ── _fix_durability_hours ─────────────────────────────────────


class TestFixDurability:
    def test_uniform_gaps(self):
        ivs = _sort_interventions(
            _make_timeline(["restart"] * 4, gap_hours=3.0)
        )
        dur = _fix_durability_hours(ivs)
        assert abs(dur - 3.0) < 0.01

    def test_single(self):
        s = _sort_interventions([_iv("2026-10-22T00:00:00Z")])
        assert _fix_durability_hours(s) == float("inf")

    def test_empty(self):
        assert _fix_durability_hours([]) == float("inf")

    def test_two_with_large_gap(self):
        ivs = [
            _iv("2026-10-22T00:00:00Z"),
            _iv("2026-10-22T12:00:00Z"),
        ]
        s = _sort_interventions(ivs)
        assert abs(_fix_durability_hours(s) - 12.0) < 0.01


# ── _classify_severity ────────────────────────────────────────


class TestClassifySeverity:
    def test_healthy(self):
        assert _classify_severity(1.0, 0.1, 8.0) == "healthy"

    def test_healthy_boundary(self):
        # rate just under 3, repeat just under 0.30, durability just over 4
        assert _classify_severity(2.9, 0.29, 4.1) == "healthy"

    def test_stressed(self):
        assert _classify_severity(4.0, 0.4, 3.0) == "stressed"

    def test_stressed_rate_boundary(self):
        assert _classify_severity(5.9, 0.49, 2.1) == "stressed"

    def test_overworked(self):
        assert _classify_severity(8.0, 0.6, 1.5) == "overworked"

    def test_burnt_out_high_rate(self):
        assert _classify_severity(15.0, 0.5, 3.0) == "burnt_out"

    def test_burnt_out_high_repeat(self):
        assert _classify_severity(2.0, 0.8, 3.0) == "burnt_out"

    def test_burnt_out_low_durability(self):
        assert _classify_severity(2.0, 0.1, 0.5) == "burnt_out"

    def test_stressed_from_durability(self):
        # rate and repeat are fine but durability is between 2 and 4 → stressed
        assert _classify_severity(2.0, 0.1, 3.0) == "stressed"


# ── burnout_report ────────────────────────────────────────────


class TestBurnoutReport:
    def test_empty(self):
        r = burnout_report([])
        assert r.total_interventions == 0
        assert r.severity == "healthy"
        assert r.fix_durability_h == float("inf")

    def test_healthy_scenario(self):
        # 2 interventions, 48 h apart, different kinds → rate < 3/day
        ivs = [
            _iv("2026-10-20T00:00:00Z", "restart"),
            _iv("2026-10-22T00:00:00Z", "flush"),
        ]
        r = burnout_report(ivs)
        assert r.total_interventions == 2
        assert r.severity == "healthy"
        assert abs(r.fix_durability_h - 48.0) < 0.1
        assert r.repeat_issue_ratio == 0.0

    def test_burnt_out_scenario(self):
        # 20 restarts in 10 hours (0.5h apart) — all same kind
        ivs = _make_timeline(["restart"] * 20, gap_hours=0.5)
        r = burnout_report(ivs)
        assert r.severity == "burnt_out"
        assert r.repeat_issue_ratio == 1.0
        assert r.fix_durability_h < 1.0

    def test_stressed_scenario(self):
        # 5 interventions over 24 h (gap=6h), mix of kinds → rate ~5/day
        ivs = _make_timeline(
            ["restart", "flush", "restart", "lock_cleanup", "restart"],
            gap_hours=6.0,
        )
        r = burnout_report(ivs)
        assert r.severity == "stressed"
        assert r.total_interventions == 5

    def test_returns_dataclass(self):
        r = burnout_report([_iv("2026-10-22T00:00:00Z")])
        assert isinstance(r, BurnoutReport)

    def test_details_populated(self):
        ivs = _make_timeline(["restart", "flush"], gap_hours=6)
        r = burnout_report(ivs)
        assert "rate_per_day" in r.details
        assert "repeat_pct" in r.details
        assert "mean_gap_h" in r.details


# ── burnout_summary ──────────────────────────────────────────


class TestBurnoutSummary:
    def test_healthy_text(self):
        s = burnout_summary([])
        assert "healthy" in s

    def test_non_healthy_text(self):
        ivs = _make_timeline(["restart"] * 20, gap_hours=0.5)
        s = burnout_summary(ivs)
        assert "burnt_out" in s
        assert "repeat" in s

    def test_includes_count(self):
        ivs = _make_timeline(["restart", "flush", "restart"], gap_hours=3)
        s = burnout_summary(ivs)
        assert "3 interventions" in s
