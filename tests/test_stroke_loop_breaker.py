"""Tests for stroke_loop_breaker — detect writer module-repetition loops."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.stroke_loop_breaker import (
    _band,
    analyse_strokes,
    extract_module,
    loop_report,
    normalise_strokes,
    parse_history_lines,
)


# ---------------------------------------------------------------------------
# extract_module
# ---------------------------------------------------------------------------


class TestExtractModule:
    def test_backtick_wrapped(self):
        assert extract_module("`retry.py` is already in the pool") == "retry.py"

    def test_plain_module_name(self):
        assert extract_module("chunk_text.py is already in the pool") == "chunk_text.py"

    def test_underscore_module(self):
        assert extract_module("parse_kv.py is already in the pool of 9 modules") == "parse_kv.py"

    def test_no_module(self):
        assert extract_module("just some random text without a module") is None

    def test_first_module_wins(self):
        result = extract_module("retry.py and chunk_text.py are both present")
        assert result == "retry.py"


# ---------------------------------------------------------------------------
# _band — severity mapping
# ---------------------------------------------------------------------------


class TestBand:
    def test_healthy_zero(self):
        assert _band(0.0) == "healthy"

    def test_healthy_boundary(self):
        assert _band(0.29) == "healthy"

    def test_mild_start(self):
        assert _band(0.30) == "mild"

    def test_mild_boundary(self):
        assert _band(0.59) == "mild"

    def test_stuck_start(self):
        assert _band(0.60) == "stuck"

    def test_stuck_boundary(self):
        assert _band(0.89) == "stuck"

    def test_dead_loop_start(self):
        assert _band(0.90) == "dead_loop"

    def test_dead_loop_one(self):
        assert _band(1.0) == "dead_loop"


# ---------------------------------------------------------------------------
# normalise_strokes
# ---------------------------------------------------------------------------


class TestNormaliseStrokes:
    def test_dict_with_module_key(self):
        strokes = [{"module": "retry.py"}, {"module": "chunk_text.py"}]
        assert normalise_strokes(strokes) == ["retry.py", "chunk_text.py"]

    def test_dict_with_text_key(self):
        strokes = [
            {"text": "`retry.py` is already in the pool"},
            {"text": "chunk_text.py is already in the pool"},
        ]
        assert normalise_strokes(strokes) == ["retry.py", "chunk_text.py"]

    def test_plain_strings(self):
        strokes = ["`parse_kv.py` is already in the pool"]
        assert normalise_strokes(strokes) == ["parse_kv.py"]

    def test_mixed_input(self):
        strokes = [
            {"module": "retry.py"},
            {"text": "`chunk_text.py` already there"},
            "parse_kv.py is in the pool",
        ]
        assert normalise_strokes(strokes) == ["retry.py", "chunk_text.py", "parse_kv.py"]

    def test_skips_no_module(self):
        strokes = [{"text": "nothing here"}, {"module": "retry.py"}, "also nothing"]
        assert normalise_strokes(strokes) == ["retry.py"]

    def test_empty_list(self):
        assert normalise_strokes([]) == []


# ---------------------------------------------------------------------------
# analyse_strokes
# ---------------------------------------------------------------------------


class TestAnalyseStrokes:
    def test_empty_input(self):
        result = analyse_strokes([])
        assert result["total"] == 0
        assert result["score"] == 0.0
        assert result["band"] == "healthy"

    def test_all_unique_modules(self):
        strokes = [
            {"module": f"mod_{i}.py"} for i in range(10)
        ]
        result = analyse_strokes(strokes)
        assert result["unique"] == 10
        assert result["score"] == 0.0
        assert result["band"] == "healthy"

    def test_all_same_module(self):
        strokes = [{"module": "retry.py"} for _ in range(10)]
        result = analyse_strokes(strokes)
        assert result["unique"] == 1
        assert result["total"] == 10
        assert result["score"] == 0.9
        assert result["band"] == "dead_loop"

    def test_repeating_cycle(self):
        """Three modules cycling 10 times = 30 strokes, 3 unique."""
        cycle = ["retry.py", "chunk_text.py", "parse_kv.py"]
        strokes = [{"module": cycle[i % 3]} for i in range(30)]
        result = analyse_strokes(strokes)
        assert result["total"] == 30
        assert result["unique"] == 3
        assert result["score"] == 0.9
        assert result["band"] == "dead_loop"

    def test_window_truncation(self):
        """Only the last `window` strokes should be considered."""
        strokes = [{"module": f"old_{i}.py"} for i in range(50)]
        strokes += [{"module": "retry.py"} for _ in range(10)]
        result = analyse_strokes(strokes, window=10)
        assert result["total"] == 10
        assert result["unique"] == 1
        assert result["score"] == 0.9

    def test_window_larger_than_data(self):
        strokes = [{"module": "retry.py"}, {"module": "chunk_text.py"}]
        result = analyse_strokes(strokes, window=100)
        assert result["total"] == 2
        assert result["unique"] == 2
        assert result["score"] == 0.0

    def test_top_modules_sorted(self):
        strokes = (
            [{"module": "retry.py"}] * 5
            + [{"module": "chunk_text.py"}] * 3
            + [{"module": "parse_kv.py"}] * 2
        )
        result = analyse_strokes(strokes)
        assert result["top_modules"][0] == ("retry.py", 5)
        assert result["top_modules"][1] == ("chunk_text.py", 3)

    def test_repeated_modules(self):
        strokes = [
            {"module": "retry.py"},
            {"module": "chunk_text.py"},
            {"module": "retry.py"},
            {"module": "parse_kv.py"},
        ]
        result = analyse_strokes(strokes)
        assert "retry.py" in result["repeated_modules"]
        assert "chunk_text.py" not in result["repeated_modules"]

    def test_mild_band(self):
        """5 unique modules over 10 strokes → score 0.5 → mild."""
        cycle = [f"mod_{i}.py" for i in range(5)]
        strokes = [{"module": cycle[i % 5]} for i in range(10)]
        result = analyse_strokes(strokes)
        assert result["score"] == 0.5
        assert result["band"] == "mild"

    def test_stuck_band(self):
        """3 unique modules over 10 strokes → score 0.7 → stuck."""
        cycle = ["a.py", "b.py", "c.py"]
        strokes = [{"module": cycle[i % 3]} for i in range(10)]
        result = analyse_strokes(strokes)
        # score = 1 - 3/10 = 0.7
        assert result["score"] == 0.7
        assert result["band"] == "stuck"


# ---------------------------------------------------------------------------
# loop_report
# ---------------------------------------------------------------------------


class TestLoopReport:
    def test_summary_empty(self):
        result = loop_report([])
        assert result["summary"] == "no analysable strokes in window"

    def test_summary_populated(self):
        strokes = [{"module": "retry.py"} for _ in range(10)]
        result = loop_report(strokes, window=10)
        assert "1 unique module" in result["summary"]
        assert "10 strokes" in result["summary"]
        assert "dead_loop" in result["summary"]

    def test_summary_plural(self):
        strokes = [{"module": f"m{i}.py"} for i in range(5)]
        result = loop_report(strokes)
        assert "5 unique modules" in result["summary"]

    def test_summary_singular(self):
        strokes = [{"module": "retry.py"}]
        result = loop_report(strokes)
        assert "1 unique module" in result["summary"]
        assert "1 stroke" in result["summary"]


# ---------------------------------------------------------------------------
# parse_history_lines
# ---------------------------------------------------------------------------


class TestParseHistoryLines:
    def test_standard_line(self):
        lines = ["- stroke 33599: `retry.py` is already in the pool of 9 modules, nothing new to add there"]
        result = parse_history_lines(lines)
        assert len(result) == 1
        assert result[0]["stroke_id"] == "33599"
        assert result[0]["module"] == "retry.py"

    def test_multiple_lines(self):
        lines = [
            "- stroke 33599: `retry.py` is already in the pool of 9 modules, nothing new to add there",
            "- stroke 33605: `chunk_text.py` is already in the pool of 9 modules, nothing new to add there",
            "- stroke 33611: `parse_kv.py` is already in the pool of 9 modules, nothing new to add there",
        ]
        result = parse_history_lines(lines)
        assert len(result) == 3
        assert result[0]["module"] == "retry.py"
        assert result[1]["module"] == "chunk_text.py"
        assert result[2]["module"] == "parse_kv.py"

    def test_non_matching_lines_skipped(self):
        lines = [
            "some random header text",
            "- stroke 33599: `retry.py` is already in the pool",
            "another non-matching line",
        ]
        result = parse_history_lines(lines)
        assert len(result) == 1

    def test_empty_input(self):
        assert parse_history_lines([]) == []


# ---------------------------------------------------------------------------
# integration: real history file (if available)
# ---------------------------------------------------------------------------


class TestIntegration:
    @pytest.fixture
    def history_path(self):
        return REPO / "notes" / "history.md"

    def test_real_history(self, history_path):
        if not history_path.exists():
            pytest.skip("notes/history.md not present")
        lines = history_path.read_text(encoding="utf-8").splitlines()
        strokes = parse_history_lines(lines)
        if not strokes:
            pytest.skip("no stroke entries found in history.md")
        result = loop_report(strokes, window=30)
        assert result["total"] > 0
        assert result["band"] in ("healthy", "mild", "stuck", "dead_loop")
        assert 0.0 <= result["score"] <= 1.0
        assert "summary" in result
