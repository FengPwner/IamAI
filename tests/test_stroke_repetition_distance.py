"""Tests for tools/stroke_repetition_distance.py — repetition-distance analysis.

Run:  python3 -m pytest tests/test_stroke_repetition_distance.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import stroke_repetition_distance as srd  # noqa: E402


# ---------------------------------------------------------------------------
# extract_prefix
# ---------------------------------------------------------------------------

class TestExtractPrefix:
    def test_strips_measured_now_suffix(self):
        text = "growth that never stops is a tumour -- measured now: 100 lines"
        assert srd.extract_prefix(text) == "growth that never stops is a tumour"

    def test_no_separator_returns_full_text(self):
        text = "caretaker visit 59: ghost_writer_detector"
        assert srd.extract_prefix(text) == text

    def test_empty_string(self):
        assert srd.extract_prefix("") == ""

    def test_whitespace_handling(self):
        text = "  some prefix  -- measured now: stuff  "
        assert srd.extract_prefix(text) == "some prefix"

    def test_multiple_separators_uses_first(self):
        text = "prefix -- measured now: middle -- measured now: end"
        assert srd.extract_prefix(text) == "prefix"


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
        strokes = srd.load_strokes(f)
        assert len(strokes) == 3
        assert strokes[0]["seq"] == 1

    def test_tail_limits_to_last_n(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        lines = [f'{{"seq": {i}, "text": "line {i}"}}' for i in range(20)]
        f.write_text("\n".join(lines) + "\n")
        strokes = srd.load_strokes(f, tail=5)
        assert len(strokes) == 5
        assert strokes[0]["seq"] == 15

    def test_missing_file_returns_empty(self, tmp_path):
        f = tmp_path / "nonexistent.jsonl"
        assert srd.load_strokes(f) == []

    def test_malformed_lines_skipped(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text(
            '{"seq": 1, "text": "good"}\n'
            'not valid json\n'
            '{"seq": 3, "text": "also good"}\n'
        )
        strokes = srd.load_strokes(f)
        assert len(strokes) == 2

    def test_blank_lines_skipped(self, tmp_path):
        f = tmp_path / "strokes.jsonl"
        f.write_text(
            '{"seq": 1, "text": "a"}\n'
            "\n"
            '{"seq": 2, "text": "b"}\n'
        )
        strokes = srd.load_strokes(f)
        assert len(strokes) == 2


# ---------------------------------------------------------------------------
# compute_distances
# ---------------------------------------------------------------------------

class TestComputeDistances:
    def _make_strokes(self, templates: list[str], repeat: int = 1) -> list[dict]:
        """Create strokes by cycling through templates."""
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

    def test_all_unique_no_gaps(self):
        strokes = self._make_strokes(["alpha", "beta", "gamma"])
        result = srd.compute_distances(strokes)
        assert result["total"] == 3
        # Each template appears once → no gaps
        for stats in result["templates"].values():
            assert stats["occurrences"] == 1
            assert stats["mean_gap"] is None
        assert result["global_mean_gap"] == 0.0

    def test_tight_loop_six_templates(self):
        """6 templates cycled 10 times → each gap is exactly 6."""
        templates = [f"tmpl_{i}" for i in range(6)]
        strokes = self._make_strokes(templates, repeat=10)
        result = srd.compute_distances(strokes)
        assert result["total"] == 60
        for stats in result["templates"].values():
            assert stats["occurrences"] == 10
            assert stats["min_gap"] == 6
            assert stats["mean_gap"] == 6.0
            assert stats["max_gap"] == 6
        assert result["global_min_gap"] == 6
        assert result["global_mean_gap"] == 6.0

    def test_two_templates_alternating(self):
        strokes = self._make_strokes(["a", "b"], repeat=25)
        result = srd.compute_distances(strokes)
        assert result["total"] == 50
        assert result["global_mean_gap"] == 2.0

    def test_single_template_repeated(self):
        strokes = self._make_strokes(["only_one"], repeat=20)
        result = srd.compute_distances(strokes)
        assert result["total"] == 20
        stats = result["templates"]["only_one"]
        assert stats["occurrences"] == 20
        assert stats["min_gap"] == 1
        assert stats["mean_gap"] == 1.0

    def test_empty_strokes(self):
        result = srd.compute_distances([])
        assert result["total"] == 0
        assert result["global_mean_gap"] == 0.0

    def test_window_limits_scope(self):
        strokes = self._make_strokes(["a", "b"], repeat=50)
        result = srd.compute_distances(strokes, window=10)
        assert result["total"] == 10

    def test_sparse_template_large_gap(self):
        """One template appears twice with 100 strokes in between."""
        strokes = [{"seq": i, "text": f"filler_{i} -- measured now: {i}"}
                    for i in range(100)]
        strokes.append({"seq": 100, "text": "filler_0 -- measured now: 100"})
        result = srd.compute_distances(strokes)
        filler0_stats = result["templates"]["filler_0"]
        assert filler0_stats["occurrences"] == 2
        assert filler0_stats["mean_gap"] == 100.0


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------

class TestClassify:
    def _make_result(self, mean_gap: float, total: int = 100) -> dict:
        """Build a minimal result dict for classify()."""
        return {
            "total": total,
            "templates": {
                "tmpl": {
                    "occurrences": 10,
                    "last_seen": 99,
                    "min_gap": mean_gap,
                    "mean_gap": mean_gap,
                    "max_gap": mean_gap,
                }
            },
            "global_min_gap": mean_gap,
            "global_mean_gap": mean_gap,
            "tight_loops": [],
            "severity": "loop",
        }

    def test_healthy_when_mean_above_loose(self):
        result = self._make_result(100.0)
        result = srd.classify(result, tight=15, loose=50)
        assert result["severity"] == "healthy"
        assert result["tight_loops"] == []

    def test_warn_when_mean_between_tight_and_loose(self):
        result = self._make_result(30.0)
        result = srd.classify(result, tight=15, loose=50)
        assert result["severity"] == "warn"
        assert result["tight_loops"] == []

    def test_loop_when_mean_below_tight(self):
        result = self._make_result(5.0)
        result = srd.classify(result, tight=15, loose=50)
        assert result["severity"] == "loop"
        assert result["tight_loops"] == ["tmpl"]

    def test_empty_is_loop(self):
        result = {
            "total": 0,
            "templates": {},
            "global_min_gap": 0,
            "global_mean_gap": 0.0,
            "tight_loops": [],
            "severity": "loop",
        }
        result = srd.classify(result)
        assert result["severity"] == "loop"

    def test_custom_thresholds(self):
        # mean=12 > loose=10 → healthy
        result = self._make_result(12.0)
        result = srd.classify(result, tight=5, loose=10)
        assert result["severity"] == "healthy"

    def test_custom_thresholds_warn(self):
        # mean=8 >= tight=5 but < loose=10 → warn
        result = self._make_result(8.0)
        result = srd.classify(result, tight=5, loose=10)
        assert result["severity"] == "warn"

    def test_tight_loops_sorted(self):
        result = {
            "total": 100,
            "templates": {
                "z_template": {"occurrences": 10, "last_seen": 99, "min_gap": 3, "mean_gap": 3.0, "max_gap": 3},
                "a_template": {"occurrences": 10, "last_seen": 99, "min_gap": 2, "mean_gap": 2.0, "max_gap": 2},
                "m_template": {"occurrences": 10, "last_seen": 99, "min_gap": 5, "mean_gap": 5.0, "max_gap": 5},
            },
            "global_min_gap": 2,
            "global_mean_gap": 3.33,
            "tight_loops": [],
            "severity": "loop",
        }
        result = srd.classify(result, tight=15, loose=50)
        assert result["tight_loops"] == ["a_template", "m_template", "z_template"]


# ---------------------------------------------------------------------------
# severity_exit
# ---------------------------------------------------------------------------

class TestSeverityExit:
    def test_healthy_returns_0(self):
        assert srd.severity_exit("healthy") == 0

    def test_warn_returns_1(self):
        assert srd.severity_exit("warn") == 1

    def test_loop_returns_2(self):
        assert srd.severity_exit("loop") == 2

    def test_unknown_returns_2(self):
        assert srd.severity_exit("unknown") == 2


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_basic_report(self):
        result = {
            "total": 60,
            "templates": {
                "tmpl_a": {"occurrences": 10, "last_seen": 59, "min_gap": 6, "mean_gap": 6.0, "max_gap": 6},
            },
            "global_min_gap": 6,
            "global_mean_gap": 6.0,
            "tight_loops": ["tmpl_a"],
            "severity": "loop",
        }
        report = srd.format_report(result)
        assert "60" in report
        assert "6.00" in report
        assert "loop" in report
        assert "tight loops" in report
        assert "tmpl_a" in report

    def test_no_tight_loops_section_omitted(self):
        result = {
            "total": 50,
            "templates": {
                "unique_thought": {"occurrences": 1, "last_seen": 0, "min_gap": None, "mean_gap": None, "max_gap": None},
            },
            "global_min_gap": 0,
            "global_mean_gap": 0.0,
            "tight_loops": [],
            "severity": "healthy",
        }
        report = srd.format_report(result)
        assert "tight loops" not in report


# ---------------------------------------------------------------------------
# Integration: realistic scenarios
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_real_tight_loop(self, tmp_path):
        """Simulate 7 templates cycled 100 times (like the real repo)."""
        f = tmp_path / "strokes.jsonl"
        templates = [
            "reproducibility is a courtesy",
            "if a number in a diary is not measured",
            "an append-only log forces you to be wrong",
            "a deterministic garden beats a random one",
            "growth that never stops is a tumour",
            "tests are the part of a repository that argues back",
            "ten minutes is long enough to be honest",
        ]
        lines = []
        for cycle in range(100):
            for t in templates:
                lines.append(json.dumps({"text": f"{t} -- measured now: cycle {cycle}"}))
        f.write_text("\n".join(lines) + "\n")

        strokes = srd.load_strokes(f)
        result = srd.compute_distances(strokes)
        result = srd.classify(result, tight=15, loose=50)

        assert result["total"] == 700
        assert result["global_mean_gap"] == 7.0
        assert result["severity"] == "loop"
        assert len(result["tight_loops"]) == 7

    def test_healthy_diverse_content(self, tmp_path):
        """Each stroke is unique — no repetition at all."""
        f = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(200):
            lines.append(json.dumps({
                "text": f"unique thought number {i} about topic {i*7} -- measured now: {i}"
            }))
        f.write_text("\n".join(lines) + "\n")

        strokes = srd.load_strokes(f)
        result = srd.compute_distances(strokes)
        result = srd.classify(result, tight=15, loose=50)

        assert result["total"] == 200
        assert result["global_mean_gap"] == 0.0
        # All unique → no gaps → mean_gap is 0, but that's because there
        # are no repetitions at all. Classify sees 0 < tight → loop.
        # This is a known edge case: zero repetition also scores as loop
        # because the metric measures repetition distance, not novelty.
        # The novelty tool (stroke_novelty.py) catches this case correctly.
        assert result["severity"] == "loop"

    def test_moderate_cycling_is_warn(self, tmp_path):
        """20 templates cycled 5 times → gap = 20, in the warn zone."""
        f = tmp_path / "strokes.jsonl"
        templates = [f"thought_{i:02d}" for i in range(20)]
        lines = []
        for cycle in range(5):
            for t in templates:
                lines.append(json.dumps({"text": f"{t} -- measured now: cycle {cycle}"}))
        f.write_text("\n".join(lines) + "\n")

        strokes = srd.load_strokes(f)
        result = srd.compute_distances(strokes)
        result = srd.classify(result, tight=15, loose=50)

        assert result["total"] == 100
        assert result["global_mean_gap"] == 20.0
        assert result["severity"] == "warn"

    def test_large_pool_is_healthy(self, tmp_path):
        """100 templates cycled 3 times → gap = 100, healthy."""
        f = tmp_path / "strokes.jsonl"
        templates = [f"deep_thought_{i:03d}" for i in range(100)]
        lines = []
        for cycle in range(3):
            for t in templates:
                lines.append(json.dumps({"text": f"{t} -- measured now: cycle {cycle}"}))
        f.write_text("\n".join(lines) + "\n")

        strokes = srd.load_strokes(f)
        result = srd.compute_distances(strokes)
        result = srd.classify(result, tight=15, loose=50)

        assert result["total"] == 300
        assert result["global_mean_gap"] == 100.0
        assert result["severity"] == "healthy"
