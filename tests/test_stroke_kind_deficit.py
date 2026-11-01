#!/usr/bin/env python3
"""Tests for tools/stroke_kind_deficit.py."""

from __future__ import annotations

import json
import tempfile
from collections import Counter
from pathlib import Path

import pytest
import sys

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from stroke_kind_deficit import (
    compute_deficits,
    format_table,
    load_kind_counts,
    EXPECTED_KINDS,
)


# ---------------------------------------------------------------------------
# load_kind_counts
# ---------------------------------------------------------------------------

class TestLoadKindCounts:
    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        counts = load_kind_counts(p)
        assert dict(counts) == {}

    def test_missing_file(self, tmp_path):
        p = tmp_path / "nope.jsonl"
        counts = load_kind_counts(p)
        assert dict(counts) == {}

    def test_basic_parsing(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 1, "kind": "thought", "text": "a"}),
            json.dumps({"seq": 2, "kind": "thought", "text": "b"}),
            json.dumps({"seq": 3, "kind": "devlog", "text": "c"}),
        ]
        p.write_text("\n".join(lines) + "\n")
        counts = load_kind_counts(p)
        assert counts["thought"] == 2
        assert counts["devlog"] == 1

    def test_missing_kind_field(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 1, "text": "no kind"}),
            json.dumps({"seq": 2, "kind": "note", "text": "has kind"}),
        ]
        p.write_text("\n".join(lines) + "\n")
        counts = load_kind_counts(p)
        assert counts["unknown"] == 1
        assert counts["note"] == 1

    def test_malformed_lines_skipped(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        lines = [
            json.dumps({"seq": 1, "kind": "thought", "text": "ok"}),
            "this is not json",
            "",
            json.dumps({"seq": 3, "kind": "note", "text": "ok"}),
        ]
        p.write_text("\n".join(lines) + "\n")
        counts = load_kind_counts(p)
        assert counts["thought"] == 1
        assert counts["note"] == 1

    def test_blank_lines_ignored(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("\n\n\n")
        counts = load_kind_counts(p)
        assert dict(counts) == {}


# ---------------------------------------------------------------------------
# compute_deficits
# ---------------------------------------------------------------------------

class TestComputeDeficits:
    def test_all_balanced(self):
        # 1000 strokes, each kind has >= 10
        counts = Counter({k: 125 for k in EXPECTED_KINDS})
        deficits = compute_deficits(counts, min_per_1k=10)
        assert all(d["deficit"] == 0 for d in deficits)

    def test_starved_kind_detected(self):
        counts = Counter({"thought": 990, "devlog": 2, "garden": 1})
        for k in EXPECTED_KINDS:
            counts.setdefault(k, 0)
        deficits = compute_deficits(counts, min_per_1k=10)
        # Most kinds should have a deficit
        starved = [d for d in deficits if d["deficit"] > 0]
        assert len(starved) > 0

    def test_deficit_sorted_largest_first(self):
        counts = Counter({"thought": 1000})
        for k in EXPECTED_KINDS:
            counts.setdefault(k, 0)
        deficits = compute_deficits(counts, min_per_1k=10)
        # First item should have the largest deficit
        if len(deficits) > 1:
            assert deficits[0]["deficit"] >= deficits[1]["deficit"]

    def test_pct_calculation(self):
        counts = Counter({"thought": 500, "devlog": 500})
        for k in EXPECTED_KINDS:
            counts.setdefault(k, 0)
        deficits = compute_deficits(counts, min_per_1k=10)
        thought_rec = next(d for d in deficits if d["kind"] == "thought")
        assert thought_rec["pct"] == 50.0

    def test_custom_target(self):
        counts = Counter({k: 50 for k in EXPECTED_KINDS})
        # With target=100 per 1k and 400 total, expected = 100 * 0.4 = 40
        deficits = compute_deficits(counts, min_per_1k=100)
        assert all(d["deficit"] == 0 for d in deficits)

    def test_empty_counts(self):
        counts = Counter()
        deficits = compute_deficits(counts, min_per_1k=10)
        # total is clamped to 1; expected per kind = int(10 * 0.001) = 0
        # so deficit should be 0 for all
        assert all(d["deficit"] == 0 for d in deficits)

    def test_zero_count_kind_has_deficit(self):
        counts = Counter({"thought": 10000})
        for k in EXPECTED_KINDS:
            counts.setdefault(k, 0)
        deficits = compute_deficits(counts, min_per_1k=10)
        devlog_rec = next(d for d in deficits if d["kind"] == "devlog")
        assert devlog_rec["deficit"] > 0
        assert devlog_rec["count"] == 0


# ---------------------------------------------------------------------------
# format_table
# ---------------------------------------------------------------------------

class TestFormatTable:
    def test_contains_starved_marker(self):
        deficits = [
            {"kind": "devlog", "count": 0, "expected": 10, "deficit": 10, "pct": 0.0},
            {"kind": "thought", "count": 100, "expected": 10, "deficit": 0, "pct": 100.0},
        ]
        table = format_table(deficits, total=100)
        assert "STARVED" in table
        assert "devlog" in table

    def test_balanced_message(self):
        deficits = [
            {"kind": "thought", "count": 50, "expected": 10, "deficit": 0, "pct": 50.0},
            {"kind": "devlog", "count": 50, "expected": 10, "deficit": 0, "pct": 50.0},
        ]
        table = format_table(deficits, total=100)
        assert "balanced" in table

    def test_recommendation_present(self):
        deficits = [
            {"kind": "garden", "count": 1, "expected": 10, "deficit": 9, "pct": 1.0},
            {"kind": "note", "count": 2, "expected": 10, "deficit": 8, "pct": 2.0},
            {"kind": "devlog", "count": 5, "expected": 10, "deficit": 5, "pct": 5.0},
            {"kind": "thought", "count": 92, "expected": 10, "deficit": 0, "pct": 92.0},
        ]
        table = format_table(deficits, total=100)
        assert "recommendation" in table
        # Top 3 starved kinds should be mentioned
        assert "garden" in table

    def test_total_shown(self):
        table = format_table([], total=42)
        assert "42" in table


# ---------------------------------------------------------------------------
# Integration: run against real strokes.jsonl
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_real_data_has_deficit(self):
        """The real stroke log should show deficits (thought dominates)."""
        real_path = REPO / "data" / "strokes.jsonl"
        if not real_path.exists():
            pytest.skip("strokes.jsonl not found")
        counts = load_kind_counts(real_path)
        deficits = compute_deficits(counts, min_per_1k=10)
        starved = [d for d in deficits if d["deficit"] > 0]
        # We know from inspection that non-thought kinds are starved
        assert len(starved) > 0, "Expected at least one starved kind"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
