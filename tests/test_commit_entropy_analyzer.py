#!/usr/bin/env python3
"""Tests for tools/commit_entropy_analyzer.py — stroke category entropy analysis."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from commit_entropy_analyzer import (
    analyze,
    category_breakdown,
    diversity_score,
    extract_categories,
    format_text,
    grade_diversity,
    load_strokes,
    max_entropy,
    normalized_entropy,
    shannon_entropy,
)


# ── helpers ─────────────────────────────────────────────────────────────


def _make_strokes(categories: list[str], start_seq: int = 1) -> list[dict]:
    """Create minimal stroke records with the given categories."""
    return [
        {"seq": start_seq + i, "kind": cat, "text": f"stroke {i}"}
        for i, cat in enumerate(categories)
    ]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


# ── TestLoadStrokes ─────────────────────────────────────────────────────


class TestLoadStrokes:
    def test_returns_empty_when_file_missing(self, tmp_path: Path):
        assert load_strokes(tmp_path / "nonexistent.jsonl") == []

    def test_loads_valid_records(self, tmp_path: Path):
        path = tmp_path / "strokes.jsonl"
        records = _make_strokes(["note", "thought", "devlog"])
        _write_jsonl(path, records)
        loaded = load_strokes(path)
        assert len(loaded) == 3
        assert loaded[0]["kind"] == "note"

    def test_skips_blank_lines(self, tmp_path: Path):
        path = tmp_path / "strokes.jsonl"
        with open(path, "w") as f:
            f.write('{"seq":1,"kind":"note","text":"a"}\n')
            f.write("\n")
            f.write("  \n")
            f.write('{"seq":2,"kind":"thought","text":"b"}\n')
        loaded = load_strokes(path)
        assert len(loaded) == 2

    def test_skips_malformed_json(self, tmp_path: Path):
        path = tmp_path / "strokes.jsonl"
        with open(path, "w") as f:
            f.write('{"seq":1,"kind":"note","text":"a"}\n')
            f.write("not json\n")
            f.write('{"seq":3,"kind":"devlog","text":"c"}\n')
        loaded = load_strokes(path)
        assert len(loaded) == 2

    def test_empty_file(self, tmp_path: Path):
        path = tmp_path / "strokes.jsonl"
        path.write_text("")
        assert load_strokes(path) == []


# ── TestExtractCategories ───────────────────────────────────────────────


class TestExtractCategories:
    def test_extracts_all_when_under_window(self):
        records = _make_strokes(["note", "thought", "note"])
        cats = extract_categories(records, window=10)
        assert cats == ["note", "thought", "note"]

    def test_takes_last_window(self):
        records = _make_strokes(["note"] * 5 + ["thought"] * 5)
        cats = extract_categories(records, window=5)
        assert cats == ["thought"] * 5

    def test_falls_back_to_kind_key(self):
        records = [{"seq": 1, "kind": "devlog", "text": "x"}]
        cats = extract_categories(records)
        assert cats == ["devlog"]

    def test_falls_back_to_category_key(self):
        records = [{"seq": 1, "category": "snippet", "text": "x"}]
        cats = extract_categories(records)
        assert cats == ["snippet"]

    def test_defaults_unknown(self):
        records = [{"seq": 1, "text": "x"}]
        cats = extract_categories(records)
        assert cats == ["unknown"]

    def test_empty_records(self):
        assert extract_categories([]) == []


# ── TestShannonEntropy ──────────────────────────────────────────────────


class TestShannonEntropy:
    def test_empty_list(self):
        assert shannon_entropy([]) == 0.0

    def test_single_element(self):
        assert shannon_entropy(["note"]) == 0.0

    def test_two_equal_categories(self):
        # H = -2 * (0.5 * log2(0.5)) = 1.0
        cats = ["a", "b"]
        assert abs(shannon_entropy(cats) - 1.0) < 1e-9

    def test_four_equal_categories(self):
        # H = log2(4) = 2.0
        cats = ["a", "b", "c", "d"] * 10
        assert abs(shannon_entropy(cats) - 2.0) < 1e-9

    def test_all_same_category(self):
        cats = ["note"] * 20
        assert shannon_entropy(cats) == 0.0

    def test_skewed_distribution(self):
        # Mostly one category → low entropy
        cats = ["a"] * 99 + ["b"]
        ent = shannon_entropy(cats)
        assert 0 < ent < 0.2

    def test_known_value(self):
        # 3 categories, equal → log2(3) ≈ 1.585
        cats = ["a", "b", "c"] * 10
        assert abs(shannon_entropy(cats) - math.log2(3)) < 1e-9


# ── TestMaxEntropy ──────────────────────────────────────────────────────


class TestMaxEntropy:
    def test_empty(self):
        assert max_entropy([]) == 0.0

    def test_single_category(self):
        assert max_entropy(["a"]) == 0.0

    def test_two_categories(self):
        assert abs(max_entropy(["a", "b"]) - 1.0) < 1e-9

    def test_four_categories(self):
        assert abs(max_entropy(["a", "b", "c", "d"]) - 2.0) < 1e-9

    def test_ignores_duplicates(self):
        # max_entropy only depends on unique count
        assert abs(max_entropy(["a", "a", "b", "b"]) - 1.0) < 1e-9


# ── TestNormalizedEntropy ───────────────────────────────────────────────


class TestNormalizedEntropy:
    def test_empty(self):
        assert normalized_entropy([]) == 0.0

    def test_single_category(self):
        assert normalized_entropy(["a", "a", "a"]) == 0.0

    def test_uniform_two(self):
        cats = ["a", "b"] * 20
        assert abs(normalized_entropy(cats) - 1.0) < 1e-9

    def test_uniform_six(self):
        cats = ["a", "b", "c", "d", "e", "f"] * 10
        assert abs(normalized_entropy(cats) - 1.0) < 1e-9

    def test_skewed_low_normalized(self):
        cats = ["a"] * 95 + ["b", "c", "d", "e", "f"]
        norm = normalized_entropy(cats)
        assert 0 < norm < 0.5


# ── TestCategoryBreakdown ──────────────────────────────────────────────


class TestCategoryBreakdown:
    def test_empty(self):
        assert category_breakdown([]) == {}

    def test_single(self):
        bd = category_breakdown(["note"])
        assert bd == {"note": {"count": 1, "pct": 100.0}}

    def test_equal_split(self):
        bd = category_breakdown(["note", "thought", "note", "thought"])
        assert bd["note"]["count"] == 2
        assert bd["note"]["pct"] == 50.0
        assert bd["thought"]["count"] == 2

    def test_sorted_by_count_desc(self):
        bd = category_breakdown(["a", "b", "b", "c", "c", "c"])
        keys = list(bd.keys())
        assert keys[0] == "c"
        assert keys[-1] == "a"

    def test_percentage_precision(self):
        bd = category_breakdown(["a"] * 1 + ["b"] * 2)
        assert bd["a"]["pct"] == 33.3
        assert bd["b"]["pct"] == 66.7


# ── TestDiversityScore ──────────────────────────────────────────────────


class TestDiversityScore:
    def test_uniform_six_categories(self):
        cats = ["a", "b", "c", "d", "e", "f"] * 10
        report = diversity_score(cats)
        assert report["total_strokes"] == 60
        assert report["unique_categories"] == 6
        assert report["normalized_entropy"] == pytest.approx(1.0, abs=0.01)
        assert report["grade"] == "UNIFORM"

    def test_single_category(self):
        cats = ["note"] * 50
        report = diversity_score(cats)
        assert report["entropy_bits"] == 0.0
        assert report["grade"] == "NARROW"

    def test_moderate_spread(self):
        cats = ["a"] * 40 + ["b"] * 35 + ["c"] * 25
        report = diversity_score(cats)
        assert report["unique_categories"] == 3
        assert report["normalized_entropy"] > 0.9

    def test_empty(self):
        report = diversity_score([])
        assert report["total_strokes"] == 0
        assert report["grade"] == "NARROW"


# ── TestGradeDiversity ──────────────────────────────────────────────────


class TestGradeDiversity:
    def test_uniform(self):
        assert grade_diversity(0.95) == "UNIFORM"

    def test_diverse(self):
        assert grade_diversity(0.80) == "DIVERSE"

    def test_moderate(self):
        assert grade_diversity(0.60) == "MODERATE"

    def test_skewed(self):
        assert grade_diversity(0.30) == "SKEWED"

    def test_narrow(self):
        assert grade_diversity(0.10) == "NARROW"

    def test_boundary_values(self):
        assert grade_diversity(0.90) == "UNIFORM"
        assert grade_diversity(0.75) == "DIVERSE"
        assert grade_diversity(0.50) == "MODERATE"
        assert grade_diversity(0.25) == "SKEWED"
        assert grade_diversity(0.0) == "NARROW"


# ── TestFormatText ──────────────────────────────────────────────────────


class TestFormatText:
    def test_contains_key_info(self):
        report = diversity_score(["note", "thought", "devlog"] * 10)
        text = format_text(report)
        assert "Commit Entropy Analysis" in text
        assert "30 strokes" in text
        assert "entropy" in text.lower()
        assert "note" in text
        assert "thought" in text
        assert "devlog" in text

    def test_empty_report(self):
        report = diversity_score([])
        text = format_text(report)
        assert "0 strokes" in text


# ── TestAnalyze (integration) ──────────────────────────────────────────


class TestAnalyze:
    def test_analyze_from_file(self, tmp_path: Path):
        path = tmp_path / "strokes.jsonl"
        records = _make_strokes(["note", "thought", "devlog"] * 20)
        _write_jsonl(path, records)
        report = analyze(path=path, window=50)
        assert report["total_strokes"] == 50
        assert report["unique_categories"] == 3
        assert report["normalized_entropy"] > 0.9

    def test_analyze_empty_file(self, tmp_path: Path):
        path = tmp_path / "strokes.jsonl"
        path.write_text("")
        report = analyze(path=path)
        assert report["total_strokes"] == 0
        assert report["grade"] == "NARROW"

    def test_analyze_window_truncation(self, tmp_path: Path):
        path = tmp_path / "strokes.jsonl"
        # 100 "note" strokes followed by 100 "thought" strokes
        records = _make_strokes(["note"] * 100 + ["thought"] * 100)
        _write_jsonl(path, records)
        # With window=50, should only see the last 50 "thought" strokes
        report = analyze(path=path, window=50)
        assert report["unique_categories"] == 1
        assert report["grade"] == "NARROW"

    def test_analyze_missing_file(self, tmp_path: Path):
        report = analyze(path=tmp_path / "missing.jsonl")
        assert report["total_strokes"] == 0
