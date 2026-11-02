"""Tests for tools/stroke_novelty.py — content-stall detection.

Run:  python3 -m pytest tests/test_stroke_novelty.py -v
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import stroke_novelty as sn  # noqa: E402


# ---------------------------------------------------------------------------
# extract_prefix
# ---------------------------------------------------------------------------

class TestExtractPrefix:
    def test_strips_measured_now_suffix(self):
        text = "growth that never stops is a tumour -- measured now: 100 lines"
        assert sn.extract_prefix(text) == "growth that never stops is a tumour"

    def test_no_separator_returns_full_text(self):
        text = "caretaker visit 59: ghost_writer_detector — four states"
        assert sn.extract_prefix(text) == text

    def test_empty_string(self):
        assert sn.extract_prefix("") == ""

    def test_whitespace_handling(self):
        text = "  some prefix  -- measured now: stuff  "
        assert sn.extract_prefix(text) == "some prefix"

    def test_multiple_separators_uses_first(self):
        text = "prefix -- measured now: middle -- measured now: end"
        assert sn.extract_prefix(text) == "prefix"


# ---------------------------------------------------------------------------
# load_strokes
# ---------------------------------------------------------------------------

class TestLoadStrokes:
    def test_load_from_jsonl(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text(
            '{"seq": 1, "text": "alpha -- measured now: 1"}\n'
            '{"seq": 2, "text": "beta -- measured now: 2"}\n'
            '{"seq": 3, "text": "alpha -- measured now: 3"}\n'
        )
        strokes = sn.load_strokes(f)
        assert len(strokes) == 3
        assert strokes[0]["seq"] == 1

    def test_tail_limits_to_last_n(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        lines = [f'{{"seq": {i}, "text": "line {i}"}}' for i in range(20)]
        f.write_text("\n".join(lines) + "\n")
        strokes = sn.load_strokes(f, tail=5)
        assert len(strokes) == 5
        assert strokes[0]["seq"] == 15

    def test_missing_file_returns_empty(self, tmp_path):
        f = tmp_path / "nonexistent.jsonl"
        assert sn.load_strokes(f) == []

    def test_malformed_lines_skipped(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text(
            '{"seq": 1, "text": "good"}\n'
            'not valid json\n'
            '{"seq": 3, "text": "also good"}\n'
        )
        strokes = sn.load_strokes(f)
        assert len(strokes) == 2

    def test_blank_lines_skipped(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text(
            '{"seq": 1, "text": "a"}\n'
            "\n"
            '{"seq": 2, "text": "b"}\n'
        )
        strokes = sn.load_strokes(f)
        assert len(strokes) == 2


# ---------------------------------------------------------------------------
# compute_novelty
# ---------------------------------------------------------------------------

class TestComputeNovelty:
    def _make_strokes(self, templates: list[str], repeat: int = 1) -> list[dict]:
        strokes = []
        seq = 0
        for _ in range(repeat):
            for t in templates:
                seq += 1
                strokes.append({
                    "seq": seq,
                    "text": f"{t} -- measured now: {seq}",
                })
        return strokes

    def test_all_unique_is_healthy(self):
        strokes = self._make_strokes(["alpha", "beta", "gamma", "delta", "epsilon"])
        result = sn.compute_novelty(strokes)
        assert result["ratio"] == 1.0
        assert result["severity"] == "healthy"

    def test_heavy_repetition_is_stall(self):
        strokes = self._make_strokes(["only_one_template"], repeat=50)
        result = sn.compute_novelty(strokes)
        assert result["ratio"] == pytest.approx(1 / 50, abs=0.01)
        assert result["severity"] == "stall"

    def test_moderate_repetition_is_warn(self):
        # 5 templates repeated 20 times = 100 strokes, ratio = 5/100 = 0.05 -> stall
        # We need ratio between 0.2 and 0.5 for warn
        # 3 templates, no repeat -> ratio = 1.0 (healthy)
        # Let's use a custom set
        strokes = []
        for i in range(10):
            strokes.append({"seq": i, "text": f"tmpl{i % 3} -- measured now: {i}"})
        # 3 unique out of 10 = 0.3 -> warn
        result = sn.compute_novelty(strokes)
        assert result["ratio"] == pytest.approx(0.3, abs=0.01)
        assert result["severity"] == "warn"

    def test_empty_strokes(self):
        result = sn.compute_novelty([])
        assert result["total"] == 0
        assert result["severity"] == "stall"

    def test_window_limits_scope(self):
        # 50 strokes with 2 templates, but window=10 sees only last 10
        strokes = self._make_strokes(["a", "b"], repeat=25)
        result = sn.compute_novelty(strokes, window=10)
        assert result["total"] == 10
        assert result["unique"] == 2
        assert result["ratio"] == pytest.approx(0.2, abs=0.01)

    def test_top_templates_populated(self):
        strokes = self._make_strokes(["alpha", "beta", "gamma"], repeat=10)
        result = sn.compute_novelty(strokes)
        assert len(result["top_templates"]) == 3
        assert result["top_templates"][0]["count"] == 10

    def test_top_templates_capped_at_five(self):
        strokes = self._make_strokes([f"t{i}" for i in range(20)], repeat=3)
        result = sn.compute_novelty(strokes)
        assert len(result["top_templates"]) == 5

    def test_prefix_truncated_to_80_chars(self):
        long_template = "x" * 200
        strokes = [{"seq": 1, "text": f"{long_template} -- measured now: 1"}]
        result = sn.compute_novelty(strokes)
        assert len(result["top_templates"][0]["prefix"]) == 80


# ---------------------------------------------------------------------------
# severity_exit
# ---------------------------------------------------------------------------

class TestSeverityExit:
    def test_healthy_returns_0(self):
        assert sn.severity_exit("healthy") == 0

    def test_warn_returns_1(self):
        assert sn.severity_exit("warn") == 1

    def test_stall_returns_2(self):
        assert sn.severity_exit("stall") == 2

    def test_unknown_returns_2(self):
        assert sn.severity_exit("unknown") == 2


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_basic_report_contains_key_fields(self):
        result = {
            "total": 100,
            "unique": 5,
            "ratio": 0.05,
            "top_templates": [
                {"prefix": "alpha", "count": 50},
                {"prefix": "beta", "count": 30},
            ],
            "severity": "stall",
        }
        report = sn.format_report(result)
        assert "100" in report
        assert "5" in report
        assert "5.00%" in report
        assert "stall" in report
        assert "alpha" in report
        assert "beta" in report

    def test_empty_report_no_templates_section(self):
        result = {
            "total": 0,
            "unique": 0,
            "ratio": 0.0,
            "top_templates": [],
            "severity": "stall",
        }
        report = sn.format_report(result)
        assert "most repeated" not in report


# ---------------------------------------------------------------------------
# Integration: realistic scenario
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_realistic_stall_scenario(self, tmp_path):
        """Simulate the real repo: 7 templates cycled 857+ times each."""
        f = tmp_path / "strokes.jsonl"
        templates = [
            "reproducibility is a courtesy to whoever debugs this at 2am",
            "if a number in a diary is not measured, it is fiction",
            "an append-only log forces you to be wrong in public",
            "a deterministic garden beats a random one",
            "growth that never stops is a tumour",
            "tests are the part of a repository that argues back",
            "ten minutes is long enough to be honest",
        ]
        lines = []
        for cycle in range(100):
            for t in templates:
                lines.append(json.dumps({
                    "text": f"{t} -- measured now: cycle {cycle}"
                }))
        f.write_text("\n".join(lines) + "\n")

        strokes = sn.load_strokes(f)
        result = sn.compute_novelty(strokes)
        assert result["total"] == 700
        assert result["unique"] == 7
        assert result["severity"] == "stall"

    def test_realistic_healthy_scenario(self, tmp_path):
        """Each stroke has a genuinely different prefix."""
        f = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(50):
            lines.append(json.dumps({
                "text": f"unique thought number {i} about topic {i*3} -- measured now: {i}"
            }))
        f.write_text("\n".join(lines) + "\n")

        strokes = sn.load_strokes(f)
        result = sn.compute_novelty(strokes)
        assert result["ratio"] == 1.0
        assert result["severity"] == "healthy"
