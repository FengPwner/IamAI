"""Tests for iamai.stroke_coverage — stroke category balance analysis."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iamai.stroke_coverage import (
    _read_strokes,
    _evenness,
    stroke_coverage,
    coverage_report,
    EXPECTED_KINDS,
)


# ---------------------------------------------------------------------------
# _read_strokes
# ---------------------------------------------------------------------------


class TestReadStrokes:
    def test_basic(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            '{"kind":"note","seq":1}\n'
            '{"kind":"thought","seq":2}\n'
        )
        strokes = _read_strokes(tmp_path)
        assert len(strokes) == 2
        assert strokes[0]["kind"] == "note"
        assert strokes[1]["kind"] == "thought"

    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        assert _read_strokes(tmp_path) == []

    def test_missing_file(self, tmp_path):
        assert _read_strokes(tmp_path) == []

    def test_limit(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [json.dumps({"kind": "note", "seq": i}) for i in range(10)]
        p.write_text("\n".join(lines) + "\n")
        strokes = _read_strokes(tmp_path, limit=3)
        assert len(strokes) == 3
        assert strokes[0]["seq"] == 7  # last 3

    def test_corrupted_lines(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            '{"kind":"note","seq":1}\n'
            'not valid json\n'
            '{"kind":"thought","seq":3}\n'
        )
        strokes = _read_strokes(tmp_path)
        assert len(strokes) == 2

    def test_limit_larger_than_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text('{"kind":"note","seq":1}\n')
        strokes = _read_strokes(tmp_path, limit=100)
        assert len(strokes) == 1


# ---------------------------------------------------------------------------
# _evenness
# ---------------------------------------------------------------------------


class TestEvenness:
    def test_perfect_balance(self):
        counts = {"a": 10, "b": 10, "c": 10}
        assert _evenness(counts) == pytest.approx(1.0, abs=1e-6)

    def test_single_category(self):
        counts = {"a": 10}
        assert _evenness(counts) == 0.0

    def test_empty(self):
        assert _evenness({}) == 0.0

    def test_highly_skewed(self):
        counts = {"a": 100, "b": 1, "c": 1}
        even = _evenness(counts)
        assert 0 < even < 0.5

    def test_two_equal(self):
        counts = {"a": 50, "b": 50}
        assert _evenness(counts) == pytest.approx(1.0, abs=1e-6)

    def test_zero_counts_filtered(self):
        counts = {"a": 10, "b": 10, "c": 0}
        # Only 2 non-zero categories, both equal → evenness = 1.0
        assert _evenness(counts) == pytest.approx(1.0, abs=1e-6)

    def test_returns_float(self):
        result = _evenness({"a": 5, "b": 5, "c": 5})
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# stroke_coverage
# ---------------------------------------------------------------------------


class TestStrokeCoverage:
    def _write_strokes(self, tmp_path, strokes):
        p = tmp_path / "strokes.jsonl"
        lines = [json.dumps(s) for s in strokes]
        p.write_text("\n".join(lines) + "\n")

    def test_balanced(self, tmp_path):
        strokes = []
        for i, kind in enumerate(sorted(EXPECTED_KINDS) * 10):
            strokes.append({"kind": kind, "seq": i})
        self._write_strokes(tmp_path, strokes)
        info = stroke_coverage(tmp_path)
        assert info["verdict"] == "balanced"
        assert info["evenness"] == pytest.approx(1.0, abs=0.01)
        assert info["missing"] == []
        assert info["deficit"] == []
        assert info["total"] == 60

    def test_depleted(self, tmp_path):
        # Only 2 kinds present → 4 missing → depleted
        strokes = [{"kind": "thought", "seq": i} for i in range(10)]
        strokes += [{"kind": "note", "seq": i} for i in range(10, 20)]
        self._write_strokes(tmp_path, strokes)
        info = stroke_coverage(tmp_path)
        assert info["verdict"] == "depleted"
        assert len(info["missing"]) == 4

    def test_skewed(self, tmp_path):
        # All kinds present but one dominates heavily
        strokes = [{"kind": "thought", "seq": i} for i in range(500)]
        for j, kind in enumerate(["devlog", "garden", "metrics", "note", "snippet"]):
            for i in range(5):
                strokes.append({"kind": kind, "seq": 500 + j * 5 + i})
        self._write_strokes(tmp_path, strokes)
        info = stroke_coverage(tmp_path)
        # All present so not depleted, but very uneven
        assert info["missing"] == []
        assert info["evenness"] < 0.7
        assert info["verdict"] == "skewed"

    def test_missing_single_kind(self, tmp_path):
        # 5 of 6 kinds present → 1 missing → not depleted (need ≥2)
        kinds = ["devlog", "garden", "metrics", "note", "snippet"]
        strokes = []
        for i, kind in enumerate(kinds * 10):
            strokes.append({"kind": kind, "seq": i})
        self._write_strokes(tmp_path, strokes)
        info = stroke_coverage(tmp_path)
        assert "thought" in info["missing"]
        assert len(info["missing"]) == 1
        # Should be skewed or balanced depending on evenness
        assert info["verdict"] in ("balanced", "skewed")

    def test_deficit_detection(self, tmp_path):
        # All kinds present but "metrics" has only 1 stroke out of 60
        strokes = []
        for kind in ["devlog", "garden", "note", "snippet", "thought"]:
            for i in range(11):
                strokes.append({"kind": kind, "seq": len(strokes)})
        strokes.append({"kind": "metrics", "seq": len(strokes)})
        self._write_strokes(tmp_path, strokes)
        info = stroke_coverage(tmp_path)
        # metrics is ~1/56 of total, well below 50% of expected 1/6
        assert "metrics" in info["deficit"]

    def test_empty_data(self, tmp_path):
        info = stroke_coverage(tmp_path)
        assert info["total"] == 0
        assert info["verdict"] == "depleted"
        assert info["evenness"] == 0.0
        assert len(info["missing"]) == 6

    def test_with_limit(self, tmp_path):
        strokes = [{"kind": "thought", "seq": i} for i in range(100)]
        strokes += [{"kind": "note", "seq": i} for i in range(100, 110)]
        self._write_strokes(tmp_path, strokes)
        info_all = stroke_coverage(tmp_path)
        info_limited = stroke_coverage(tmp_path, limit=10)
        assert info_all["total"] == 110
        assert info_limited["total"] == 10

    def test_custom_expected_kinds(self, tmp_path):
        strokes = [{"kind": "alpha", "seq": i} for i in range(10)]
        strokes += [{"kind": "beta", "seq": i} for i in range(10, 20)]
        self._write_strokes(tmp_path, strokes)
        info = stroke_coverage(tmp_path, expected_kinds={"alpha", "beta"})
        assert info["verdict"] == "balanced"
        assert info["missing"] == []

    def test_counts_dict(self, tmp_path):
        strokes = [{"kind": "note", "seq": i} for i in range(5)]
        self._write_strokes(tmp_path, strokes)
        info = stroke_coverage(tmp_path)
        assert isinstance(info["counts"], dict)
        assert info["counts"].get("note") == 5

    def test_total_matches(self, tmp_path):
        strokes = [{"kind": kind, "seq": i}
                   for i, kind in enumerate(sorted(EXPECTED_KINDS) * 5)]
        self._write_strokes(tmp_path, strokes)
        info = stroke_coverage(tmp_path)
        assert info["total"] == sum(info["counts"].values())


# ---------------------------------------------------------------------------
# coverage_report
# ---------------------------------------------------------------------------


class TestCoverageReport:
    def _write_strokes(self, tmp_path, strokes):
        p = tmp_path / "strokes.jsonl"
        lines = [json.dumps(s) for s in strokes]
        p.write_text("\n".join(lines) + "\n")

    def test_balanced_report(self, tmp_path):
        strokes = []
        for i, kind in enumerate(sorted(EXPECTED_KINDS) * 10):
            strokes.append({"kind": kind, "seq": i})
        self._write_strokes(tmp_path, strokes)
        report = coverage_report(tmp_path)
        assert "balanced" in report
        assert "no deficit" in report

    def test_report_contains_evenness(self, tmp_path):
        strokes = [{"kind": "thought", "seq": i} for i in range(10)]
        self._write_strokes(tmp_path, strokes)
        report = coverage_report(tmp_path)
        assert "evenness" in report

    def test_report_shows_missing(self, tmp_path):
        strokes = [{"kind": "thought", "seq": i} for i in range(10)]
        self._write_strokes(tmp_path, strokes)
        report = coverage_report(tmp_path)
        assert "missing" in report

    def test_report_is_string(self, tmp_path):
        report = coverage_report(tmp_path)
        assert isinstance(report, str)
        assert len(report) > 0
