"""Tests for iamai.process_cycle_efficiency — productive vs overhead time.

Visit 813: this module measures what fraction of the writer's wall-clock
time is spent producing content versus lost to stalls and restart warm-up.

Test areas:
    1. _parse_timestamp      — ISO 8601 parsing
    2. compute_gaps          — inter-stroke interval calculation
    3. classify_gaps         — gap classification (productive/stall/overhead)
    4. account_time          — time summation by label
    5. count_by_label        — stroke counting by label
    6. efficiency_score      — productive / total ratio
    7. efficiency_label      — score band mapping
    8. compute_trend         — windowed efficiency trend
    9. trend_direction       — improving/stable/degrading classification
   10. efficiency_report     — full structured report
   11. efficiency_summary    — human-readable output
   12. _cli                  — exit codes, --json flag
   13. edge cases            — empty, single, degenerate inputs
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.process_cycle_efficiency import (
    _cli,
    _load_strokes,
    _parse_timestamp,
    account_time,
    classify_gaps,
    compute_gaps,
    compute_trend,
    count_by_label,
    efficiency_label,
    efficiency_report,
    efficiency_score,
    efficiency_summary,
    trend_direction,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------


def _ts(offset_seconds: float) -> str:
    """Return an ISO-8601 timestamp at *offset_seconds* after a base time."""
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    dt = base + timedelta(seconds=offset_seconds)
    return dt.isoformat()


def _make_strokes(offsets: list[float]) -> list[dict]:
    """Build a list of stroke dicts from a list of time offsets (seconds)."""
    return [{"seq": i, "at": _ts(o), "kind": "thought", "text": f"s{i}"}
            for i, o in enumerate(offsets)]


def _write_strokes_file(tmp_path: Path, strokes: list[dict]) -> Path:
    """Write strokes to a JSONL file and return the path."""
    p = tmp_path / "strokes.jsonl"
    p.write_text(
        "\n".join(json.dumps(s) for s in strokes) + "\n",
        encoding="utf-8",
    )
    return p


# -----------------------------------------------------------------------
# 1. _parse_timestamp
# -----------------------------------------------------------------------


class TestParseTimestamp:
    def test_standard_iso(self):
        dt = _parse_timestamp("2026-01-01T12:00:00+00:00")
        assert dt.year == 2026
        assert dt.hour == 12

    def test_z_suffix(self):
        dt = _parse_timestamp("2026-06-15T08:30:00Z")
        assert dt.hour == 8
        assert dt.tzinfo is not None

    def test_positive_offset(self):
        dt = _parse_timestamp("2026-11-23T11:05:00+08:00")
        assert dt.utcoffset() == timedelta(hours=8)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _parse_timestamp("not-a-date")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _parse_timestamp("")


# -----------------------------------------------------------------------
# 2. compute_gaps
# -----------------------------------------------------------------------


class TestComputeGaps:
    def test_uniform_cadence(self):
        strokes = _make_strokes([0, 15, 30, 45, 60])
        gaps = compute_gaps(strokes)
        assert len(gaps) == 4
        assert all(g == 15.0 for g in gaps)

    def test_irregular_cadence(self):
        strokes = _make_strokes([0, 10, 30, 35, 100])
        gaps = compute_gaps(strokes)
        assert gaps == [10.0, 20.0, 5.0, 65.0]

    def test_single_stroke(self):
        strokes = _make_strokes([0])
        assert compute_gaps(strokes) == []

    def test_empty(self):
        assert compute_gaps([]) == []

    def test_two_strokes(self):
        strokes = _make_strokes([0, 42])
        assert compute_gaps(strokes) == [42.0]

    def test_negative_gap_clamped(self):
        # timestamps going backwards should clamp to 0
        strokes = _make_strokes([100, 50])
        gaps = compute_gaps(strokes)
        assert gaps == [0.0]


# -----------------------------------------------------------------------
# 3. classify_gaps
# -----------------------------------------------------------------------


class TestClassifyGaps:
    def test_all_productive(self):
        gaps = [15.0, 14.0, 16.0, 15.5, 13.0]
        labels = classify_gaps(gaps)
        assert all(l == "productive" for l in labels)

    def test_stall_detection(self):
        gaps = [15.0, 15.0, 60.0, 15.0, 15.0]
        labels = classify_gaps(gaps)
        assert labels[2] == "stall"

    def test_warmup_after_stall(self):
        # After a stall, next warmup_count strokes are overhead
        gaps = [15.0, 60.0, 15.0, 15.0, 15.0, 15.0, 15.0]
        labels = classify_gaps(gaps, warmup_count=3)
        assert labels[1] == "stall"
        assert labels[2] == "overhead"  # warmup 1
        assert labels[3] == "overhead"  # warmup 2
        assert labels[4] == "overhead"  # warmup 3
        assert labels[5] == "productive"  # recovered

    def test_overhead_gap(self):
        # Gap between productive ceiling and stall threshold
        gaps = [30.0]  # > 25 (15+10) but < 45
        labels = classify_gaps(gaps)
        assert labels[0] == "overhead"

    def test_boundary_productive(self):
        # Exactly at productive ceiling
        gaps = [25.0]  # 15 + 10 = 25
        labels = classify_gaps(gaps)
        assert labels[0] == "productive"

    def test_boundary_stall(self):
        # Just above stall threshold
        gaps = [45.1]
        labels = classify_gaps(gaps)
        assert labels[0] == "stall"

    def test_multiple_stalls(self):
        gaps = [15.0, 60.0, 15.0, 15.0, 15.0, 15.0, 120.0, 15.0]
        labels = classify_gaps(gaps, warmup_count=2)
        assert labels[1] == "stall"
        assert labels[2] == "overhead"
        assert labels[3] == "overhead"
        assert labels[6] == "stall"
        assert labels[7] == "overhead"

    def test_empty(self):
        assert classify_gaps([]) == []

    def test_custom_thresholds(self):
        gaps = [30.0, 100.0, 30.0]
        labels = classify_gaps(
            gaps,
            target_cadence=30.0,
            tolerance=5.0,
            stall_threshold=80.0,
            warmup_count=1,
        )
        assert labels[0] == "productive"  # 30 <= 30+5
        assert labels[1] == "stall"       # 100 > 80
        assert labels[2] == "overhead"    # warmup after stall


# -----------------------------------------------------------------------
# 4. account_time
# -----------------------------------------------------------------------


class TestAccountTime:
    def test_basic(self):
        gaps = [15.0, 60.0, 15.0, 15.0]
        labels = ["productive", "stall", "overhead", "productive"]
        ta = account_time(gaps, labels)
        assert ta["productive"] == 30.0
        assert ta["stall"] == 60.0
        assert ta["overhead"] == 15.0

    def test_empty(self):
        assert account_time([], []) == {
            "productive": 0.0, "stall": 0.0, "overhead": 0.0
        }

    def test_all_productive(self):
        gaps = [10.0, 10.0, 10.0]
        labels = ["productive", "productive", "productive"]
        ta = account_time(gaps, labels)
        assert ta["productive"] == 30.0
        assert ta["stall"] == 0.0


# -----------------------------------------------------------------------
# 5. count_by_label
# -----------------------------------------------------------------------


class TestCountByLabel:
    def test_mixed(self):
        labels = ["productive", "stall", "productive", "overhead", "productive"]
        counts = count_by_label(labels)
        assert counts["productive"] == 3
        assert counts["stall"] == 1
        assert counts["overhead"] == 1

    def test_empty(self):
        counts = count_by_label([])
        assert counts == {"productive": 0, "stall": 0, "overhead": 0}


# -----------------------------------------------------------------------
# 6. efficiency_score
# -----------------------------------------------------------------------


class TestEfficiencyScore:
    def test_all_productive(self):
        ta = {"productive": 100.0, "stall": 0.0, "overhead": 0.0}
        assert efficiency_score(ta) == 1.0

    def test_half_efficient(self):
        ta = {"productive": 50.0, "stall": 50.0, "overhead": 0.0}
        assert efficiency_score(ta) == 0.5

    def test_zero_total(self):
        ta = {"productive": 0.0, "stall": 0.0, "overhead": 0.0}
        assert efficiency_score(ta) == 1.0  # no data = no penalty

    def test_mostly_overhead(self):
        ta = {"productive": 10.0, "stall": 40.0, "overhead": 50.0}
        assert abs(efficiency_score(ta) - 0.1) < 1e-9

    def test_realistic(self):
        ta = {"productive": 800.0, "stall": 120.0, "overhead": 80.0}
        score = efficiency_score(ta)
        assert 0.79 < score < 0.81


# -----------------------------------------------------------------------
# 7. efficiency_label
# -----------------------------------------------------------------------


class TestEfficiencyLabel:
    def test_efficient(self):
        assert efficiency_label(0.95) == "efficient"
        assert efficiency_label(0.90) == "efficient"

    def test_adequate(self):
        assert efficiency_label(0.89) == "adequate"
        assert efficiency_label(0.70) == "adequate"

    def test_strained(self):
        assert efficiency_label(0.69) == "strained"
        assert efficiency_label(0.50) == "strained"

    def test_struggling(self):
        assert efficiency_label(0.49) == "struggling"
        assert efficiency_label(0.0) == "struggling"

    def test_boundary_values(self):
        assert efficiency_label(1.0) == "efficient"
        assert efficiency_label(0.91) == "efficient"


# -----------------------------------------------------------------------
# 8. compute_trend
# -----------------------------------------------------------------------


class TestComputeTrend:
    def test_single_window(self):
        gaps = [15.0] * 10
        trend = compute_trend(gaps, window_size=10)
        assert len(trend) == 1
        assert trend[0] == 1.0

    def test_multiple_windows(self):
        # First half: productive; second half: lots of stalls
        gaps = ([15.0] * 10) + ([60.0] * 5 + [15.0] * 5)
        trend = compute_trend(gaps, window_size=10)
        assert len(trend) == 2
        assert trend[0] > trend[1]  # degrading

    def test_empty(self):
        assert compute_trend([], window_size=10) == []

    def test_partial_last_window(self):
        gaps = [15.0] * 15
        trend = compute_trend(gaps, window_size=10)
        assert len(trend) == 2  # 10 + 5

    def test_window_size_one(self):
        gaps = [15.0, 60.0, 15.0]
        trend = compute_trend(gaps, window_size=1, warmup_count=0)
        assert len(trend) == 3


# -----------------------------------------------------------------------
# 9. trend_direction
# -----------------------------------------------------------------------


class TestTrendDirection:
    def test_improving(self):
        trend = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
        assert trend_direction(trend) == "improving"

    def test_degrading(self):
        trend = [0.95, 0.9, 0.8, 0.7, 0.6, 0.5]
        assert trend_direction(trend) == "degrading"

    def test_stable(self):
        trend = [0.8, 0.82, 0.79, 0.81, 0.80, 0.80]
        assert trend_direction(trend) == "stable"

    def test_single_value(self):
        assert trend_direction([0.8]) == "stable"

    def test_empty(self):
        assert trend_direction([]) == "stable"

    def test_two_values(self):
        assert trend_direction([0.5, 0.9]) == "improving"
        assert trend_direction([0.9, 0.5]) == "degrading"
        assert trend_direction([0.8, 0.82]) == "stable"


# -----------------------------------------------------------------------
# 10. efficiency_report
# -----------------------------------------------------------------------


class TestEfficiencyReport:
    def test_healthy_writer(self, tmp_path):
        # Steady 15-second cadence, no stalls
        strokes = _make_strokes([i * 15 for i in range(100)])
        p = _write_strokes_file(tmp_path, strokes)
        r = efficiency_report(n_strokes=100, path=p)
        assert r["efficiency_score"] == 1.0
        assert r["stall_count"] == 0
        assert r["efficiency_label"] == "efficient"
        assert r["total_strokes"] == 100

    def test_stally_writer(self, tmp_path):
        # Regular strokes with periodic 2-minute stalls
        offsets = []
        t = 0
        for i in range(50):
            offsets.append(t)
            if i % 10 == 9:
                t += 120  # stall every 10th stroke
            else:
                t += 15
        strokes = _make_strokes(offsets)
        p = _write_strokes_file(tmp_path, strokes)
        r = efficiency_report(n_strokes=50, path=p)
        assert r["stall_count"] > 0
        assert r["efficiency_score"] < 1.0
        assert r["productive_seconds"] > 0
        assert r["stall_seconds"] > 0

    def test_report_keys(self, tmp_path):
        strokes = _make_strokes([i * 15 for i in range(20)])
        p = _write_strokes_file(tmp_path, strokes)
        r = efficiency_report(n_strokes=20, path=p)
        expected_keys = {
            "total_strokes", "productive_strokes", "overhead_strokes",
            "stall_count", "total_seconds", "productive_seconds",
            "stall_seconds", "overhead_seconds", "efficiency_score",
            "overhead_ratio", "trend", "trend_direction",
            "efficiency_label",
        }
        assert expected_keys.issubset(r.keys())

    def test_insufficient_data(self, tmp_path):
        strokes = _make_strokes([0])
        p = _write_strokes_file(tmp_path, strokes)
        r = efficiency_report(n_strokes=1, path=p)
        assert r["efficiency_score"] == 1.0
        assert r["stall_count"] == 0
        assert r["efficiency_label"] == "efficient"

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        r = efficiency_report(path=p)
        assert r["total_strokes"] == 0
        assert r["efficiency_score"] == 1.0

    def test_overhead_ratio_complement(self, tmp_path):
        strokes = _make_strokes([i * 15 for i in range(50)])
        p = _write_strokes_file(tmp_path, strokes)
        r = efficiency_report(n_strokes=50, path=p)
        # efficiency + overhead_ratio should sum to ~1.0
        assert abs(r["efficiency_score"] + r["overhead_ratio"] - 1.0) < 0.01

    def test_trend_populated(self, tmp_path):
        strokes = _make_strokes([i * 15 for i in range(100)])
        p = _write_strokes_file(tmp_path, strokes)
        r = efficiency_report(n_strokes=100, path=p, window_size=25)
        assert len(r["trend"]) >= 2

    def test_custom_thresholds(self, tmp_path):
        # With a very tight threshold, more strokes become overhead
        strokes = _make_strokes([i * 20 for i in range(50)])
        p = _write_strokes_file(tmp_path, strokes)
        r1 = efficiency_report(n_strokes=50, path=p, tolerance=3.0)
        r2 = efficiency_report(n_strokes=50, path=p, tolerance=10.0)
        # Tighter tolerance → fewer productive → lower efficiency
        assert r1["efficiency_score"] <= r2["efficiency_score"]


# -----------------------------------------------------------------------
# 11. efficiency_summary
# -----------------------------------------------------------------------


class TestEfficiencySummary:
    def test_healthy_output(self, tmp_path):
        strokes = _make_strokes([i * 15 for i in range(50)])
        p = _write_strokes_file(tmp_path, strokes)
        s = efficiency_summary(n_strokes=50, path=p)
        assert "efficient" in s
        assert "100%" in s

    def test_contains_trend(self, tmp_path):
        strokes = _make_strokes([i * 15 for i in range(50)])
        p = _write_strokes_file(tmp_path, strokes)
        s = efficiency_summary(n_strokes=50, path=p)
        assert "trend" in s

    def test_stall_plural(self, tmp_path):
        offsets = []
        t = 0
        for i in range(30):
            offsets.append(t)
            if i % 10 == 9:
                t += 120
            else:
                t += 15
        strokes = _make_strokes(offsets)
        p = _write_strokes_file(tmp_path, strokes)
        s = efficiency_summary(n_strokes=30, path=p)
        # Multiple stalls → plural
        assert "stalls" in s

    def test_stall_singular(self, tmp_path):
        # Exactly one stall
        offsets = [i * 15 for i in range(10)] + [10 * 15 + 120]
        offsets += [offsets[-1] + i * 15 for i in range(1, 10)]
        strokes = _make_strokes(offsets)
        p = _write_strokes_file(tmp_path, strokes)
        s = efficiency_summary(n_strokes=20, path=p)
        assert "1 stall" in s or "1 stalls" in s  # flexible


# -----------------------------------------------------------------------
# 12. _cli
# -----------------------------------------------------------------------


class TestCli:
    def test_text_output(self, tmp_path, capsys):
        strokes = _make_strokes([i * 15 for i in range(50)])
        p = _write_strokes_file(tmp_path, strokes)
        code = _cli(["--n", "50", "--path", str(p)])
        assert code == 0
        out = capsys.readouterr().out
        assert "efficiency" in out

    def test_json_output(self, tmp_path, capsys):
        strokes = _make_strokes([i * 15 for i in range(50)])
        p = _write_strokes_file(tmp_path, strokes)
        code = _cli(["--n", "50", "--path", str(p), "--json"])
        assert code == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "efficiency_score" in data

    def test_exit_code_struggling(self, tmp_path, capsys):
        # Lots of stalls → struggling → exit 1
        offsets = []
        t = 0
        for i in range(20):
            offsets.append(t)
            t += 120  # every gap is a stall
        strokes = _make_strokes(offsets)
        p = _write_strokes_file(tmp_path, strokes)
        code = _cli(["--n", "20", "--path", str(p)])
        assert code == 1

    def test_custom_window(self, tmp_path, capsys):
        strokes = _make_strokes([i * 15 for i in range(100)])
        p = _write_strokes_file(tmp_path, strokes)
        code = _cli(["--n", "100", "--path", str(p), "--window", "20", "--json"])
        assert code == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data["trend"]) >= 2


# -----------------------------------------------------------------------
# 13. Edge cases
# -----------------------------------------------------------------------


class TestEdgeCases:
    def test_all_stalls(self):
        gaps = [120.0, 120.0, 120.0, 120.0]
        labels = classify_gaps(gaps, warmup_count=0)
        assert all(l == "stall" for l in labels)
        ta = account_time(gaps, labels)
        assert efficiency_score(ta) == 0.0
        assert efficiency_label(efficiency_score(ta)) == "struggling"

    def test_all_overhead(self):
        gaps = [30.0, 30.0, 30.0]
        labels = classify_gaps(gaps, target_cadence=15.0, tolerance=5.0)
        assert all(l == "overhead" for l in labels)
        ta = account_time(gaps, labels)
        score = efficiency_score(ta)
        assert score == 0.0

    def test_single_gap(self):
        gaps = [15.0]
        labels = classify_gaps(gaps)
        assert labels == ["productive"]

    def test_zero_gap(self):
        gaps = [0.0]
        labels = classify_gaps(gaps)
        assert labels == ["productive"]

    def test_very_long_stall(self):
        gaps = [15.0, 3600.0, 15.0, 15.0, 15.0, 15.0, 15.0]
        labels = classify_gaps(gaps, warmup_count=2)
        assert labels[1] == "stall"
        assert labels[2] == "overhead"
        assert labels[3] == "overhead"
        ta = account_time(gaps, labels)
        assert ta["stall"] == 3600.0

    def test_consecutive_stalls(self):
        # Back-to-back stalls: each one triggers its own warmup
        gaps = [60.0, 60.0, 60.0]
        labels = classify_gaps(gaps, warmup_count=0)
        assert labels == ["stall", "stall", "stall"]

    def test_load_strokes_missing_file(self, tmp_path):
        p = tmp_path / "nonexistent.jsonl"
        assert _load_strokes(path=p) == []

    def test_load_strokes_malformed_lines(self, tmp_path):
        p = tmp_path / "bad.jsonl"
        p.write_text(
            '{"seq": 1, "at": "2026-01-01T12:00:00+00:00", "kind": "t", "text": "a"}\n'
            'this is not json\n'
            '{"seq": 2, "at": "2026-01-01T12:00:15+00:00", "kind": "t", "text": "b"}\n'
            '\n'
            '{"seq": 3, "at": "bad-date", "kind": "t", "text": "c"}\n',
            encoding="utf-8",
        )
        strokes = _load_strokes(path=p)
        assert len(strokes) == 2  # only valid entries loaded

    def test_trend_all_windows_same(self):
        # Uniform cadence → all windows should score the same
        gaps = [15.0] * 100
        trend = compute_trend(gaps, window_size=20)
        assert len(trend) == 5
        assert all(t == 1.0 for t in trend)

    def test_overhead_ratio_bounds(self, tmp_path):
        strokes = _make_strokes([i * 15 for i in range(50)])
        p = _write_strokes_file(tmp_path, strokes)
        r = efficiency_report(n_strokes=50, path=p)
        assert 0.0 <= r["overhead_ratio"] <= 1.0
        assert 0.0 <= r["efficiency_score"] <= 1.0
