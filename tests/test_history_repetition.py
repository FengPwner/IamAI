#!/usr/bin/env python3
"""Tests for history_repetition — repetition detection in history logs."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.history_repetition import (
    HistoryRepetitionReport,
    analyse,
    classify,
    longest_identical_run,
    normalize_line,
    repetition_ratio,
)


# ---------------------------------------------------------------------------
# normalize_line
# ---------------------------------------------------------------------------

class TestNormalizeLine:
    def test_strips_stroke_prefix(self):
        line = "- stroke 35012: some content here"
        assert normalize_line(line) == "some content here"

    def test_replaces_backtick_module(self):
        line = "stroke 100: `parse_kv.py` is already in the pool"
        assert normalize_line(line) == "X is already in the pool"

    def test_plain_text_unchanged(self):
        assert normalize_line("hello world") == "hello world"

    def test_full_stuck_line(self):
        line = "- stroke 35012: `parse_kv.py` is already in the pool of 9 modules, nothing new to add there"
        result = normalize_line(line)
        assert result == "X is already in the pool of 9 modules, nothing new to add there"

    def test_different_modules_normalise_same(self):
        a = "- stroke 35012: `parse_kv.py` is already in the pool of 9 modules"
        b = "- stroke 35019: `retry.py` is already in the pool of 9 modules"
        assert normalize_line(a) == normalize_line(b)


# ---------------------------------------------------------------------------
# longest_identical_run
# ---------------------------------------------------------------------------

class TestLongestIdenticalRun:
    def test_empty(self):
        assert longest_identical_run([]) == (0, "")

    def test_single(self):
        assert longest_identical_run(["hello"]) == (1, "hello")

    def test_all_same(self):
        lines = ["x"] * 10
        assert longest_identical_run(lines) == (10, "x")

    def test_run_in_middle(self):
        lines = ["a", "b", "b", "b", "c"]
        length, text = longest_identical_run(lines)
        assert length == 3
        assert text == "b"

    def test_run_at_end(self):
        lines = ["a", "b", "c", "c", "c", "c"]
        length, text = longest_identical_run(lines)
        assert length == 4
        assert text == "c"

    def test_multiple_runs_picks_longest(self):
        lines = ["a", "a", "b", "b", "b", "c", "c"]
        length, text = longest_identical_run(lines)
        assert length == 3
        assert text == "b"

    def test_alternating(self):
        lines = ["a", "b"] * 20
        length, _ = longest_identical_run(lines)
        assert length == 1

    def test_realistic_stuck_pattern(self):
        """Simulate the 'nothing new to add' repetition."""
        modules = ["parse_kv.py", "retry.py", "chunk_text.py"]
        lines = [
            f"- stroke {35000 + i}: `{modules[i % 3]}` is already in the pool "
            f"of 9 modules, nothing new to add there"
            for i in range(60)
        ]
        # Each line is unique (different module name or seq), so run = 1
        length, _ = longest_identical_run(lines)
        assert length == 1  # no exact consecutive duplicates

    def test_exact_duplicate_lines(self):
        """Lines that are character-for-character identical."""
        line = "- stroke 100: `retry.py` is already in the pool of 9 modules"
        lines = [line] * 25 + ["something else"]
        length, text = longest_identical_run(lines)
        assert length == 25
        assert text == line


# ---------------------------------------------------------------------------
# repetition_ratio
# ---------------------------------------------------------------------------

class TestRepetitionRatio:
    def test_empty(self):
        assert repetition_ratio([]) == 0.0

    def test_single(self):
        assert repetition_ratio(["a"]) == 0.0

    def test_all_unique(self):
        lines = [f"line_{i}" for i in range(50)]
        assert repetition_ratio(lines, window=50) == 0.0

    def test_all_same(self):
        lines = ["x"] * 50
        ratio = repetition_ratio(lines, window=50)
        assert ratio == pytest.approx(49 / 50)  # first is unique, rest are dupes

    def test_half_duplicates(self):
        # Alternate between a fixed line and unique lines
        lines = []
        for i in range(50):
            if i % 2 == 0:
                lines.append("repeat")
            else:
                lines.append(f"unique_{i}")
        ratio = repetition_ratio(lines, window=50)
        # In the window, "repeat" appears 25 times; first is unique,
        # the other 24 are dupes.  unique lines are all different.
        # So 24/50 = 0.48
        assert ratio == pytest.approx(24 / 50, abs=0.02)

    def test_small_window(self):
        lines = ["a", "a", "b", "b"]
        ratio = repetition_ratio(lines, window=2)
        # windows: [a,a] -> 1/2, [a,b] -> 0/2, [b,b] -> 1/2
        # average = (0.5 + 0 + 0.5) / 3 = 1/3
        assert ratio == pytest.approx(1 / 3, abs=0.01)

    def test_window_larger_than_data(self):
        lines = ["a", "a", "b"]
        ratio = repetition_ratio(lines, window=100)
        # window is capped at len(lines)=3
        # [a, a, b] -> 1/3
        assert ratio == pytest.approx(1 / 3, abs=0.01)


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_healthy_low_pct(self):
        assert classify(10.0, 3) == "healthy"

    def test_healthy_zero(self):
        assert classify(0.0, 0) == "healthy"

    def test_repeating_by_pct(self):
        assert classify(35.0, 5) == "repeating"

    def test_repeating_by_run(self):
        assert classify(5.0, 15) == "repeating"

    def test_stuck_by_pct(self):
        assert classify(75.0, 3) == "stuck"

    def test_stuck_by_run(self):
        assert classify(10.0, 60) == "stuck"

    def test_boundary_30(self):
        assert classify(30.0, 0) == "repeating"

    def test_boundary_70(self):
        assert classify(70.0, 0) == "stuck"

    def test_boundary_run_10(self):
        assert classify(0.0, 10) == "repeating"

    def test_boundary_run_50(self):
        assert classify(0.0, 50) == "stuck"


# ---------------------------------------------------------------------------
# HistoryRepetitionReport
# ---------------------------------------------------------------------------

class TestReport:
    def test_defaults(self):
        r = HistoryRepetitionReport()
        assert r.total_lines == 0
        assert r.verdict == "healthy"

    def test_to_dict(self):
        r = HistoryRepetitionReport(
            total_lines=100,
            longest_run=15,
            longest_run_text="some repeated text that is quite long" * 5,
            repetition_pct=45.678,
            window_size=50,
            verdict="repeating",
        )
        d = r.to_dict()
        assert d["total_lines"] == 100
        assert d["longest_run"] == 15
        assert d["repetition_pct"] == 45.7  # rounded
        assert d["verdict"] == "repeating"
        assert len(d["longest_run_text"]) <= 120


# ---------------------------------------------------------------------------
# analyse (integration)
# ---------------------------------------------------------------------------

class TestAnalyse:
    def test_missing_file(self, tmp_path):
        report = analyse(path=tmp_path / "nonexistent.md")
        assert report.total_lines == 0
        assert report.verdict == "healthy"

    def test_stuck_history(self, tmp_path):
        """Build a file that simulates the stuck pattern."""
        p = tmp_path / "history.md"
        lines = []
        modules = ["parse_kv.py", "retry.py", "chunk_text.py"]
        for i in range(100):
            mod = modules[i % 3]
            lines.append(
                f"- stroke {35000 + i}: `{mod}` is already in the pool "
                f"of 9 modules, nothing new to add there"
            )
        p.write_text("\n".join(lines) + "\n")

        report = analyse(path=p, window=50)
        assert report.total_lines == 100
        # After normalisation, all lines are identical → run = 100
        assert report.longest_run == 100
        # Repetition ratio: 49/50 dupes per window position = 98%
        assert report.repetition_pct > 90.0
        assert report.verdict == "stuck"

    def test_healthy_history(self, tmp_path):
        """Build a file with diverse entries."""
        p = tmp_path / "history.md"
        lines = [f"- stroke {i}: unique action number {i} with varied content"
                 for i in range(60)]
        p.write_text("\n".join(lines) + "\n")

        report = analyse(path=p, window=50)
        assert report.total_lines == 60
        assert report.longest_run == 1
        assert report.repetition_pct == pytest.approx(0.0, abs=1.0)
        assert report.verdict == "healthy"

    def test_mixed_history(self, tmp_path):
        """Some repetition but not stuck."""
        p = tmp_path / "history.md"
        lines = []
        for i in range(60):
            if i % 3 == 0:
                lines.append("- stroke X: `retry.py` is already in the pool")
            else:
                lines.append(f"- stroke {i}: new feature added to module_{i}")
        p.write_text("\n".join(lines) + "\n")

        report = analyse(path=p, window=50)
        # 20 out of 60 lines are identical → moderate repetition
        assert report.total_lines == 60
        assert report.repetition_pct > 10.0
        assert report.repetition_pct < 50.0
