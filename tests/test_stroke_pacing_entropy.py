"""Tests for tools/stroke_pacing_entropy.py — pacing-entropy analysis.

Run:  python3 -m pytest tests/test_stroke_pacing_entropy.py -v
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import stroke_pacing_entropy as spe  # noqa: E402


# ---------------------------------------------------------------------------
# parse_timestamp
# ---------------------------------------------------------------------------


class TestParseTimestamp:
    def test_iso_with_z_suffix(self):
        dt = spe.parse_timestamp("2026-11-21T10:00:00Z")
        assert dt.hour == 10

    def test_iso_with_timezone_offset(self):
        dt = spe.parse_timestamp("2026-11-21T10:00:00+08:00")
        assert dt.hour == 10

    def test_iso_with_microseconds(self):
        dt = spe.parse_timestamp("2026-11-21T10:00:00.123456Z")
        assert dt.hour == 10

    def test_whitespace_stripped(self):
        dt = spe.parse_timestamp("  2026-11-21T10:00:00Z  ")
        assert dt.hour == 10

    def test_invalid_raises(self):
        with pytest.raises((ValueError, TypeError)):
            spe.parse_timestamp("not-a-timestamp")


# ---------------------------------------------------------------------------
# load_strokes
# ---------------------------------------------------------------------------


class TestLoadStrokes:
    def test_load_from_jsonl(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            '{"seq": 1, "at": "2026-01-01T00:00:00Z", "kind": "thought", "text": "a"}\n'
            '{"seq": 2, "at": "2026-01-01T00:01:00Z", "kind": "thought", "text": "b"}\n'
        )
        strokes = spe.load_strokes(p)
        assert len(strokes) == 2

    def test_tail_limits_to_last_n(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            f'{{"seq": {i}, "at": "2026-01-01T00:{i:02d}:00Z", "kind": "thought", "text": "x"}}'
            for i in range(10)
        ]
        p.write_text("\n".join(lines))
        strokes = spe.load_strokes(p, tail=3)
        assert len(strokes) == 3
        assert strokes[0]["seq"] == 7

    def test_missing_file_returns_empty(self, tmp_path):
        strokes = spe.load_strokes(tmp_path / "nope.jsonl")
        assert strokes == []

    def test_malformed_lines_skipped(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            '{"seq": 1, "at": "2026-01-01T00:00:00Z", "kind": "thought", "text": "a"}\n'
            "not json at all\n"
            '{"seq": 2, "at": "2026-01-01T00:01:00Z", "kind": "thought", "text": "b"}\n'
        )
        strokes = spe.load_strokes(p)
        assert len(strokes) == 2

    def test_blank_lines_skipped(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            "\n"
            '{"seq": 1, "at": "2026-01-01T00:00:00Z", "kind": "thought", "text": "a"}\n'
            "\n\n"
            '{"seq": 2, "at": "2026-01-01T00:01:00Z", "kind": "thought", "text": "b"}\n'
            "\n"
        )
        strokes = spe.load_strokes(p)
        assert len(strokes) == 2


# ---------------------------------------------------------------------------
# compute_intervals
# ---------------------------------------------------------------------------


class TestComputeIntervals:
    def test_basic_intervals(self):
        strokes = [
            {"at": "2026-01-01T00:00:00Z"},
            {"at": "2026-01-01T00:01:00Z"},
            {"at": "2026-01-01T00:03:00Z"},
        ]
        ivs = spe.compute_intervals(strokes)
        assert len(ivs) == 2
        assert ivs[0] == 60.0
        assert ivs[1] == 120.0

    def test_single_stroke_returns_empty(self):
        assert spe.compute_intervals([{"at": "2026-01-01T00:00:00Z"}]) == []

    def test_empty_strokes_returns_empty(self):
        assert spe.compute_intervals([]) == []

    def test_strokes_without_at_skipped(self):
        strokes = [
            {"at": "2026-01-01T00:00:00Z"},
            {"text": "no at field"},
            {"at": "2026-01-01T00:02:00Z"},
        ]
        ivs = spe.compute_intervals(strokes)
        assert len(ivs) == 1
        assert ivs[0] == 120.0

    def test_malformed_at_skipped(self):
        strokes = [
            {"at": "2026-01-01T00:00:00Z"},
            {"at": "garbage"},
            {"at": "2026-01-01T00:01:00Z"},
        ]
        ivs = spe.compute_intervals(strokes)
        assert len(ivs) == 1
        assert ivs[0] == 60.0

    def test_zero_interval_included(self):
        strokes = [
            {"at": "2026-01-01T00:00:00Z"},
            {"at": "2026-01-01T00:00:00Z"},
            {"at": "2026-01-01T00:01:00Z"},
        ]
        ivs = spe.compute_intervals(strokes)
        assert 0.0 in ivs


# ---------------------------------------------------------------------------
# bin_entropy
# ---------------------------------------------------------------------------


class TestBinEntropy:
    def test_empty_returns_zero(self):
        assert spe.bin_entropy([]) == 0.0

    def test_all_identical_returns_zero(self):
        assert spe.bin_entropy([15.0, 15.0, 15.0, 15.0]) == 0.0

    def test_two_equal_bins_returns_one_bit(self):
        ivs = [10.0, 20.0, 10.0, 20.0]
        entropy = spe.bin_entropy(ivs)
        assert abs(entropy - 1.0) < 1e-6

    def test_four_equal_bins_returns_two_bits(self):
        ivs = [10.0, 20.0, 30.0, 40.0] * 5
        entropy = spe.bin_entropy(ivs)
        assert abs(entropy - 2.0) < 1e-6

    def test_skewed_distribution_low_entropy(self):
        # 99 at 15s, 1 at 30s → very low entropy
        ivs = [15.0] * 99 + [30.0]
        entropy = spe.bin_entropy(ivs)
        assert entropy < 0.2

    def test_custom_bin_width(self):
        ivs = [10.1, 10.2, 10.3, 20.1, 20.2, 20.3]
        # With bin_width=1, all 10.x → bin 10, all 20.x → bin 20
        entropy_1 = spe.bin_entropy(ivs, bin_width=1.0)
        assert abs(entropy_1 - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


class TestStatistics:
    def test_mean_empty(self):
        assert spe.mean([]) == 0.0

    def test_mean_basic(self):
        assert spe.mean([10, 20, 30]) == 20.0

    def test_std_single(self):
        assert spe.std([42.0]) == 0.0

    def test_std_basic(self):
        vals = [10, 20, 30]
        expected = math.sqrt(((10 - 20) ** 2 + (20 - 20) ** 2 + (30 - 20) ** 2) / 2)
        assert abs(spe.std(vals) - expected) < 1e-9

    def test_cv_basic(self):
        vals = [10, 20, 30]
        m = spe.mean(vals)
        s = spe.std(vals)
        assert abs(spe.coefficient_of_variation(vals) - (s / m)) < 1e-9

    def test_cv_zero_mean(self):
        assert spe.coefficient_of_variation([0, 0, 0]) == 0.0

    def test_cv_empty(self):
        assert spe.coefficient_of_variation([]) == 0.0


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


class TestClassify:
    def test_mechanical_low_cv_low_entropy(self):
        assert spe.classify(0.02, 0.3) == "mechanical"

    def test_erratic_high_cv(self):
        assert spe.classify(1.5, 2.0) == "erratic"

    def test_erratic_high_entropy(self):
        assert spe.classify(0.3, 6.0) == "erratic"

    def test_organic_middle(self):
        assert spe.classify(0.3, 2.5) == "organic"

    def test_custom_thresholds_mechanical(self):
        assert spe.classify(0.15, 0.5, low_cv=0.2, low_entropy=1.0) == "mechanical"

    def test_custom_thresholds_erratic(self):
        assert spe.classify(0.3, 3.0, high_entropy=2.5) == "erratic"

    def test_boundary_low_cv_high_entropy(self):
        # low CV but high entropy → erratic (OR condition)
        assert spe.classify(0.05, 6.0) == "erratic"

    def test_boundary_exact_thresholds(self):
        # cv == low_cv should NOT be mechanical (strict <)
        # 0.10 is NOT < 0.10, so classify should NOT return mechanical
        result = spe.classify(0.10, 0.9)
        assert result == "organic"

    def test_cv_at_low_boundary(self):
        # 0.10 is NOT < 0.10, so it should be organic (if entropy ok)
        result = spe.classify(0.10, 2.0)
        assert result == "organic"


# ---------------------------------------------------------------------------
# verdict_exit
# ---------------------------------------------------------------------------


class TestVerdictExit:
    def test_organic_returns_0(self):
        assert spe.verdict_exit("organic") == 0

    def test_mechanical_returns_1(self):
        assert spe.verdict_exit("mechanical") == 1

    def test_erratic_returns_2(self):
        assert spe.verdict_exit("erratic") == 2

    def test_unknown_returns_2(self):
        assert spe.verdict_exit("catastrophic") == 2


# ---------------------------------------------------------------------------
# build_report / format_report
# ---------------------------------------------------------------------------


class TestBuildReport:
    def test_basic_report_keys(self):
        report = spe.build_report([10.0, 20.0], 1.0, 0.5, "organic", 3)
        assert "sample_size" in report
        assert "entropy_bits" in report
        assert "verdict" in report
        assert report["sample_size"] == 3
        assert report["interval_count"] == 2

    def test_empty_intervals_report(self):
        report = spe.build_report([], 0.0, 0.0, "mechanical", 0)
        assert report["interval_count"] == 0
        assert report["min_interval_s"] == 0
        assert report["max_interval_s"] == 0

    def test_report_rounds_values(self):
        report = spe.build_report([10.123456, 20.654321], 1.23456, 0.456789, "organic", 3)
        assert report["entropy_bits"] == 1.2346
        assert report["cv"] == 0.4568


class TestFormatReport:
    def test_contains_key_fields(self):
        report = spe.build_report([15.0, 16.0, 14.0], 0.5, 0.1, "organic", 4)
        text = spe.format_report(report)
        assert "organic" in text
        assert "entropy" in text
        assert "sample" in text
        assert "verdict" in text

    def test_mechanical_verdict_in_output(self):
        report = spe.build_report([], 0.0, 0.0, "mechanical", 0)
        text = spe.format_report(report)
        assert "mechanical" in text


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_mechanical_clockwork(self, tmp_path):
        """Strokes exactly 15s apart → mechanical."""
        p = tmp_path / "strokes.jsonl"
        base = 1705824000  # 2024-01-21T08:00:00Z
        lines = []
        for i in range(50):
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(base + i * 15, tz=timezone.utc)
            ts = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            lines.append(json.dumps({"seq": i, "at": ts, "kind": "thought", "text": f"t{i}"}))
        p.write_text("\n".join(lines))

        strokes = spe.load_strokes(p)
        intervals = spe.compute_intervals(strokes)
        entropy = spe.bin_entropy(intervals)
        cv = spe.coefficient_of_variation(intervals)
        verdict = spe.classify(cv, entropy)
        assert verdict == "mechanical"

    def test_organic_with_jitter(self, tmp_path):
        """Strokes with moderate jitter → organic."""
        import random
        p = tmp_path / "strokes.jsonl"
        base = 1705824000
        rng = random.Random(42)
        offset = 0
        lines = []
        for i in range(100):
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(base + offset, tz=timezone.utc)
            ts = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            lines.append(json.dumps({"seq": i, "at": ts, "kind": "thought", "text": f"t{i}"}))
            offset += rng.randint(10, 25)  # 10–25s jitter
        p.write_text("\n".join(lines))

        strokes = spe.load_strokes(p)
        intervals = spe.compute_intervals(strokes)
        entropy = spe.bin_entropy(intervals)
        cv = spe.coefficient_of_variation(intervals)
        verdict = spe.classify(cv, entropy)
        assert verdict == "organic"

    def test_erratic_with_long_gaps(self, tmp_path):
        """Strokes with occasional huge gaps (restarts) → erratic."""
        p = tmp_path / "strokes.jsonl"
        base = 1705824000
        lines = []
        offset = 0
        for i in range(60):
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(base + offset, tz=timezone.utc)
            ts = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            lines.append(json.dumps({"seq": i, "at": ts, "kind": "thought", "text": f"t{i}"}))
            if i % 20 == 19:
                offset += 7200  # 2-hour gap every 20 strokes
            else:
                offset += 15
        p.write_text("\n".join(lines))

        strokes = spe.load_strokes(p)
        intervals = spe.compute_intervals(strokes)
        entropy = spe.bin_entropy(intervals)
        cv = spe.coefficient_of_variation(intervals)
        verdict = spe.classify(cv, entropy)
        assert verdict == "erratic"

    def test_end_to_end_json(self, tmp_path):
        """Full pipeline with --json output."""
        p = tmp_path / "strokes.jsonl"
        base = 1705824000
        lines = []
        for i in range(30):
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(base + i * 15 + (i % 3) * 5, tz=timezone.utc)
            ts = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            lines.append(json.dumps({"seq": i, "at": ts, "kind": "thought", "text": f"t{i}"}))
        p.write_text("\n".join(lines))

        strokes = spe.load_strokes(p)
        intervals = spe.compute_intervals(strokes)
        entropy = spe.bin_entropy(intervals)
        cv = spe.coefficient_of_variation(intervals)
        verdict = spe.classify(cv, entropy)
        report = spe.build_report(intervals, entropy, cv, verdict, len(strokes))
        output = json.dumps(report)
        parsed = json.loads(output)
        assert parsed["verdict"] in ("mechanical", "organic", "erratic")
        assert parsed["sample_size"] == 30
        assert parsed["interval_count"] == 29
