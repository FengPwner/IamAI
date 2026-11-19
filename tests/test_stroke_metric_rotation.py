"""Tests for iamai.stroke_metric_rotation — metric rotation analysis."""

import json
import tempfile
from pathlib import Path

import pytest

from iamai.stroke_metric_rotation import (
    ALL_METRIC_TYPES,
    MetricRotation,
    RotationReport,
    classify_metric,
    extract_aphorism,
    extract_metric_value,
)


# ── helpers ────────────────────────────────────────────────────────────

_SEP = " -- measured now: "


def _stroke(text: str, seq: int = 1, kind: str = "thought") -> dict:
    return {"seq": seq, "at": "2026-01-01T00:00:00+00:00",
            "kind": kind, "text": text}


def _write_jsonl(strokes: list, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for s in strokes:
            fh.write(json.dumps(s) + "\n")


# sample metric texts
SAMPLES = {
    "commit_count":    "commit 950: the count of times this repo was pushed, not the work done",
    "tree_is":         "tree is 2429 files; 620323 lines is a lot for a toy",
    "lines_across":    "620930 lines across 2432 tracked files, 950 commits deep",
    "strokes_written": "6797 strokes written so far into 2434 files",
    "python_files":    "1649 python files, 6790 logged thoughts",
}


# ── classify_metric ───────────────────────────────────────────────────

class TestClassifyMetric:

    def test_commit_count(self):
        text = "some thought" + _SEP + SAMPLES["commit_count"]
        assert classify_metric(text) == "commit_count"

    def test_tree_is(self):
        text = "another thought" + _SEP + SAMPLES["tree_is"]
        assert classify_metric(text) == "tree_is"

    def test_lines_across(self):
        text = "insight" + _SEP + SAMPLES["lines_across"]
        assert classify_metric(text) == "lines_across"

    def test_strokes_written(self):
        text = "musing" + _SEP + SAMPLES["strokes_written"]
        assert classify_metric(text) == "strokes_written"

    def test_python_files(self):
        text = "reflection" + _SEP + SAMPLES["python_files"]
        assert classify_metric(text) == "python_files"

    def test_no_separator_returns_none(self):
        text = "growth that never stops is a tumour, not a garden"
        assert classify_metric(text) is None

    def test_unknown_metric_returns_none(self):
        text = "thought" + _SEP + "some unknown measurement 42 things"
        assert classify_metric(text) is None

    def test_case_insensitive(self):
        text = "x" + _SEP + "Commit 100: the count of times"
        assert classify_metric(text) == "commit_count"

    def test_empty_string(self):
        assert classify_metric("") is None

    def test_separator_only(self):
        text = "aphorism" + _SEP
        assert classify_metric(text) is None


# ── extract_aphorism / extract_metric_value ───────────────────────────

class TestExtractors:

    def test_extract_aphorism_with_metric(self):
        text = "wisdom here" + _SEP + SAMPLES["commit_count"]
        assert extract_aphorism(text) == "wisdom here"

    def test_extract_aphorism_without_metric(self):
        text = "standalone aphorism"
        assert extract_aphorism(text) == "standalone aphorism"

    def test_extract_metric_value(self):
        text = "wisdom" + _SEP + SAMPLES["lines_across"]
        assert extract_metric_value(text) == SAMPLES["lines_across"]

    def test_extract_metric_value_no_separator(self):
        assert extract_metric_value("no metric") == ""


# ── MetricRotation.from_jsonl ─────────────────────────────────────────

class TestFromJsonl:

    def test_loads_metrics(self, tmp_path):
        strokes = [
            _stroke("a" + _SEP + SAMPLES["commit_count"], seq=1),
            _stroke("b" + _SEP + SAMPLES["tree_is"], seq=2),
            _stroke("c" + _SEP + SAMPLES["lines_across"], seq=3),
        ]
        p = tmp_path / "strokes.jsonl"
        _write_jsonl(strokes, p)
        mr = MetricRotation.from_jsonl(p)
        report = mr.report()
        assert report.total_strokes == 3
        assert report.classified_strokes == 3
        assert report.richness == 3

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        mr = MetricRotation.from_jsonl(p)
        report = mr.report()
        assert report.total_strokes == 0
        assert report.classified_strokes == 0

    def test_missing_file(self, tmp_path):
        p = tmp_path / "nonexistent.jsonl"
        mr = MetricRotation.from_jsonl(p)
        report = mr.report()
        assert report.total_strokes == 0

    def test_mixed_with_aphorisms(self, tmp_path):
        strokes = [
            _stroke("pure aphorism", seq=1),
            _stroke("b" + _SEP + SAMPLES["commit_count"], seq=2),
            _stroke("another aphorism", seq=3),
            _stroke("d" + _SEP + SAMPLES["tree_is"], seq=4),
        ]
        p = tmp_path / "strokes.jsonl"
        _write_jsonl(strokes, p)
        mr = MetricRotation.from_jsonl(p)
        report = mr.report()
        assert report.total_strokes == 4
        assert report.classified_strokes == 2
        assert report.unclassified_strokes == 2


# ── MetricRotation.report — core metrics ──────────────────────────────

class TestReport:

    def _make_rotation(self, types: list) -> MetricRotation:
        """Build MetricRotation from a list of metric type names."""
        seq = []
        for t in types:
            if t is None or t == "":
                seq.append(None)
            else:
                seq.append(t)
        return MetricRotation(seq)

    def test_perfect_rotation(self):
        # 5 types, each appearing equally, no consecutive repeats
        types = ["commit_count", "tree_is", "lines_across",
                 "strokes_written", "python_files"] * 20
        mr = self._make_rotation(types)
        report = mr.report()
        assert report.richness == 5
        assert report.entropy_ratio == pytest.approx(1.0, abs=0.001)
        assert report.max_streak == 1
        assert report.rotation_breaks == 0
        assert report.regularity_score >= 0.95
        assert report.starved_metrics == []

    def test_single_metric(self):
        types = ["commit_count"] * 50
        mr = self._make_rotation(types)
        report = mr.report()
        assert report.richness == 1
        assert report.entropy_ratio == 0.0
        assert report.max_streak == 50
        assert report.max_streak_type == "commit_count"
        assert report.regularity_score <= 0.1
        assert report.dominant_metric == "commit_count"
        assert report.dominant_fraction == 1.0

    def test_two_metrics_unequal(self):
        types = ["commit_count"] * 40 + ["tree_is"] * 10
        mr = self._make_rotation(types)
        report = mr.report()
        assert report.richness == 2
        assert report.entropy_ratio < 1.0
        assert report.dominant_metric == "commit_count"
        assert report.dominant_fraction == pytest.approx(0.80, abs=0.01)

    def test_empty_rotation(self):
        mr = self._make_rotation([])
        report = mr.report()
        assert report.total_strokes == 0
        assert report.classified_strokes == 0
        assert report.richness == 0
        assert report.regularity_score == 0.0

    def test_all_unclassified(self):
        mr = MetricRotation([None, None, None, ""])
        report = mr.report()
        assert report.total_strokes == 4
        assert report.classified_strokes == 0
        assert report.unclassified_strokes == 4

    def test_streak_detection(self):
        types = ["commit_count"] * 5 + ["tree_is"] * 3 + ["lines_across"]
        mr = self._make_rotation(types)
        report = mr.report()
        assert report.max_streak == 5
        assert report.max_streak_type == "commit_count"

    def test_rotation_breaks(self):
        # 4 breaks: CC-CC, TI-TI, LA-LA, SW-SW
        types = [
            "commit_count", "commit_count",  # break 1
            "tree_is", "tree_is",            # break 2
            "lines_across", "lines_across",  # break 3
            "strokes_written", "strokes_written",  # break 4
            "python_files",
        ]
        mr = self._make_rotation(types)
        report = mr.report()
        assert report.rotation_breaks == 4

    def test_starved_metrics(self):
        # 5 types but python_files appears only once
        types = (["commit_count"] * 25 + ["tree_is"] * 25 +
                 ["lines_across"] * 25 + ["strokes_written"] * 24 +
                 ["python_files"])
        mr = self._make_rotation(types)
        report = mr.report()
        assert "python_files" in report.starved_metrics

    def test_summary_healthy(self):
        types = ["commit_count", "tree_is", "lines_across",
                 "strokes_written", "python_files"] * 10
        mr = self._make_rotation(types)
        report = mr.report()
        s = report.summary()
        assert "healthy" in s or "moderate" in s

    def test_summary_empty(self):
        mr = self._make_rotation([])
        report = mr.report()
        assert "undefined" in report.summary()


# ── to_dict ───────────────────────────────────────────────────────────

class TestToDict:

    def test_to_dict_keys(self):
        types = ["commit_count", "tree_is", "lines_across"] * 10
        mr = MetricRotation(types)
        report = mr.report()
        d = report.to_dict()
        expected_keys = {
            "total_strokes", "classified", "unclassified", "richness",
            "entropy_ratio", "regularity", "max_streak", "max_streak_type",
            "avg_streak", "dominant", "dominant_fraction", "starved",
            "rotation_breaks",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_values_are_rounded(self):
        types = ["commit_count"] * 7 + ["tree_is"] * 3
        mr = MetricRotation(types)
        report = mr.report()
        d = report.to_dict()
        # Check that float values are rounded to 4 decimals
        assert d["entropy_ratio"] == round(report.entropy_ratio, 4)
        assert d["regularity"] == round(report.regularity_score, 4)


# ── recent_window ─────────────────────────────────────────────────────

class TestRecentWindow:

    def test_window_truncates(self):
        types = ["commit_count"] * 50 + ["tree_is"] * 50
        mr = MetricRotation(types)
        window = mr.recent_window(30)
        report = window.report()
        assert report.total_strokes == 30
        assert report.classified_strokes == 30
        # All 30 should be tree_is (the last 50)
        assert report.dominant_metric == "tree_is"

    def test_window_larger_than_corpus(self):
        types = ["commit_count", "tree_is", "lines_across"]
        mr = MetricRotation(types)
        window = mr.recent_window(100)
        report = window.report()
        assert report.total_strokes == 3


# ── classify_distribution ─────────────────────────────────────────────

class TestClassifyDistribution:

    def test_uniform_is_healthy(self):
        types = ["commit_count", "tree_is", "lines_across",
                 "strokes_written", "python_files"] * 20
        mr = MetricRotation(types)
        dist = mr.classify_distribution()
        for m in ALL_METRIC_TYPES:
            assert dist[m] == "healthy"

    def test_dominated_is_over(self):
        types = ["commit_count"] * 80 + ["tree_is"] * 20
        mr = MetricRotation(types)
        dist = mr.classify_distribution()
        assert dist["commit_count"] == "over"
        assert dist["tree_is"] == "under"

    def test_empty(self):
        mr = MetricRotation([None, None])
        dist = mr.classify_distribution()
        assert dist == {}


# ── ALL_METRIC_TYPES ──────────────────────────────────────────────────

class TestConstants:

    def test_all_types_populated(self):
        assert len(ALL_METRIC_TYPES) == 5
        assert "commit_count" in ALL_METRIC_TYPES
        assert "tree_is" in ALL_METRIC_TYPES
        assert "lines_across" in ALL_METRIC_TYPES
        assert "strokes_written" in ALL_METRIC_TYPES
        assert "python_files" in ALL_METRIC_TYPES


# ── Integration with real-like data ──────────────────────────────────

class TestIntegration:

    def test_full_pipeline(self, tmp_path):
        """Build a realistic stroke file and run the full pipeline."""
        metrics_cycle = [
            SAMPLES["commit_count"],
            SAMPLES["tree_is"],
            SAMPLES["lines_across"],
            SAMPLES["strokes_written"],
            SAMPLES["python_files"],
        ]
        aphorisms = [
            "an append-only log forces you to be wrong in public",
            "tests are the part of a repository that argues back",
            "reproducibility is a courtesy to whoever debugs this at 2am",
            "if a number in a diary is not measured, it is fiction",
            "growth that never stops is a tumour, not a garden",
        ]
        strokes = []
        for i in range(50):
            aph = aphorisms[i % len(aphorisms)]
            metric = metrics_cycle[i % len(metrics_cycle)]
            text = aph + _SEP + metric
            strokes.append(_stroke(text, seq=i + 1))
        # Add a few pure aphorisms (no metric)
        strokes.append(_stroke("pure thought without metric", seq=51))
        strokes.append(_stroke("another pure thought", seq=52))

        p = tmp_path / "strokes.jsonl"
        _write_jsonl(strokes, p)

        mr = MetricRotation.from_jsonl(p)
        report = mr.report()

        assert report.total_strokes == 52
        assert report.classified_strokes == 50
        assert report.unclassified_strokes == 2
        assert report.richness == 5
        assert report.entropy_ratio == pytest.approx(1.0, abs=0.001)
        assert report.max_streak == 1
        assert report.rotation_breaks == 0
        assert report.regularity_score >= 0.95
        assert report.starved_metrics == []

        # dict round-trip
        d = report.to_dict()
        assert d["richness"] == 5
        assert d["max_streak"] == 1
        assert d["starved"] == []

    def test_skewed_pipeline(self, tmp_path):
        """Simulate a writer stuck on one metric type."""
        strokes = []
        for i in range(30):
            text = f"thought {i}" + _SEP + SAMPLES["commit_count"]
            strokes.append(_stroke(text, seq=i + 1))
        for i in range(5):
            text = f"thought {30+i}" + _SEP + SAMPLES["tree_is"]
            strokes.append(_stroke(text, seq=31 + i))

        p = tmp_path / "skewed.jsonl"
        _write_jsonl(strokes, p)

        mr = MetricRotation.from_jsonl(p)
        report = mr.report()

        assert report.richness == 2
        assert report.dominant_metric == "commit_count"
        assert report.dominant_fraction == pytest.approx(30 / 35, abs=0.01)
        assert report.max_streak == 30
        assert report.regularity_score < 0.50
        assert "tree_is" in report.starved_metrics
