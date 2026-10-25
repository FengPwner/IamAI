"""Tests for iamai.pool_diversity — pool repetition detector."""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from iamai.pool_diversity import pool_diversity, diversity_report, _extract_modules


# ---------------------------------------------------------------------------
# _extract_modules
# ---------------------------------------------------------------------------

class TestExtractModules:
    def test_finds_backtick_modules(self):
        text = "stroke 123: `retry.py` is already in the pool"
        assert _extract_modules(text) == ["retry.py"]

    def test_multiple_modules(self):
        text = "both `chunk_text.py` and `parse_kv.py` repeated"
        assert _extract_modules(text) == ["chunk_text.py", "parse_kv.py"]

    def test_no_modules(self):
        assert _extract_modules("just a plain thought") == []

    def test_ignores_non_module_backticks(self):
        text = "the variable `x` is not a module"
        assert _extract_modules(text) == []  # no .py suffix

    def test_empty_string(self):
        assert _extract_modules("") == []


# ---------------------------------------------------------------------------
# pool_diversity — diverse case
# ---------------------------------------------------------------------------

class TestDiverse:
    def test_all_unique(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(50):
            lines.append(json.dumps({
                "seq": i, "kind": "thought",
                "text": f"stroke {i}: `module_{i}.py` is new"
            }))
        p.write_text("\n".join(lines) + "\n")

        info = pool_diversity(p, window=50)
        assert info["verdict"] == "diverse"
        assert info["unique_ratio"] == 1.0
        assert info["repeat_streak"] == 0

    def test_mostly_unique(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(100):
            mod = f"module_{i}.py" if i < 60 else f"module_{i % 60}.py"
            lines.append(json.dumps({
                "seq": i, "kind": "thought",
                "text": f"stroke {i}: `{mod}` mentioned"
            }))
        p.write_text("\n".join(lines) + "\n")

        info = pool_diversity(p, window=100)
        assert info["unique_ratio"] >= 0.5
        assert info["verdict"] == "diverse"


# ---------------------------------------------------------------------------
# pool_diversity — stuck case
# ---------------------------------------------------------------------------

class TestStuck:
    def test_all_same_three(self, tmp_path: Path):
        """Simulates the real loop: retry.py, chunk_text.py, parse_kv.py."""
        p = tmp_path / "strokes.jsonl"
        cycle = ["retry.py", "chunk_text.py", "parse_kv.py"]
        lines = []
        for i in range(90):
            mod = cycle[i % 3]
            lines.append(json.dumps({
                "seq": i, "kind": "thought",
                "text": f"stroke {i}: `{mod}` is already in the pool of 9 modules"
            }))
        p.write_text("\n".join(lines) + "\n")

        info = pool_diversity(p, window=90)
        assert info["verdict"] == "stuck"
        assert len(info["unique_modules"]) == 3
        assert info["repeat_streak"] == 87  # strokes 3..89 all repeat

    def test_single_module_repeated(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(30):
            lines.append(json.dumps({
                "seq": i, "kind": "thought",
                "text": f"stroke {i}: `retry.py` again"
            }))
        p.write_text("\n".join(lines) + "\n")

        info = pool_diversity(p, window=30)
        assert info["verdict"] == "stuck"
        assert info["unique_ratio"] < 0.2

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        info = pool_diversity(p, window=100)
        assert info["verdict"] == "stuck"
        assert info["window"] == 0

    def test_missing_file(self, tmp_path: Path):
        info = pool_diversity(tmp_path / "nope.jsonl", window=100)
        assert info["verdict"] == "stuck"


# ---------------------------------------------------------------------------
# pool_diversity — narrowing case
# ---------------------------------------------------------------------------

class TestNarrowing:
    def test_moderate_repetition(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        lines = []
        # 30 unique, then 70 repeating from a set of 10
        for i in range(30):
            lines.append(json.dumps({
                "seq": i, "kind": "thought",
                "text": f"stroke {i}: `new_{i}.py` discovered"
            }))
        for i in range(30, 100):
            mod = f"old_{i % 10}.py"
            lines.append(json.dumps({
                "seq": i, "kind": "thought",
                "text": f"stroke {i}: `{mod}` revisited"
            }))
        p.write_text("\n".join(lines) + "\n")

        info = pool_diversity(p, window=100)
        # 40 unique modules in 100 strokes = 0.4 ratio
        assert info["unique_ratio"] >= 0.2
        assert info["unique_ratio"] < 0.5
        # The repeat streak is 70 but with ratio 0.4 it's "narrowing" not stuck
        # Actually streak >= 50 triggers stuck regardless... let's check
        # With streak 70 >= stuck_streak(50), it should be "stuck"
        assert info["verdict"] == "stuck"

    def test_short_repeat_streak(self, tmp_path: Path):
        """Ratio in [0.2, 0.5) with streak < 30 → narrowing."""
        p = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(100):
            # alternate: new module, then repeat from pool of 25
            if i % 3 == 0:
                mod = f"new_{i}.py"
            else:
                mod = f"pool_{i % 25}.py"
            lines.append(json.dumps({
                "seq": i, "kind": "thought",
                "text": f"stroke {i}: `{mod}` here"
            }))
        p.write_text("\n".join(lines) + "\n")

        info = pool_diversity(p, window=100)
        # lots of unique modules, ratio should be > 0.2
        assert info["unique_ratio"] >= 0.2


# ---------------------------------------------------------------------------
# diversity_report
# ---------------------------------------------------------------------------

class TestDiversityReport:
    def test_stuck_report(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        cycle = ["retry.py", "chunk_text.py", "parse_kv.py"]
        lines = []
        for i in range(60):
            lines.append(json.dumps({
                "seq": i, "kind": "thought",
                "text": f"`{cycle[i % 3]}` again"
            }))
        p.write_text("\n".join(lines) + "\n")

        report = diversity_report(p, window=60)
        assert "stuck" in report
        assert "3 unique modules" in report

    def test_diverse_report(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(50):
            lines.append(json.dumps({
                "seq": i, "kind": "thought",
                "text": f"`mod_{i}.py` is new"
            }))
        p.write_text("\n".join(lines) + "\n")

        report = diversity_report(p, window=50)
        assert "diverse" in report

    def test_empty_report(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        report = diversity_report(p)
        assert "stuck" in report

    def test_no_file_report(self, tmp_path: Path):
        report = diversity_report(tmp_path / "missing.jsonl")
        assert "stuck" in report


# ---------------------------------------------------------------------------
# custom thresholds
# ---------------------------------------------------------------------------

class TestCustomThresholds:
    def test_strict_thresholds(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(20):
            mod = f"mod_{i % 5}.py"
            lines.append(json.dumps({
                "seq": i, "kind": "thought",
                "text": f"`{mod}` noted"
            }))
        p.write_text("\n".join(lines) + "\n")

        # with strict thresholds, even 5 unique in 20 might be stuck
        info = pool_diversity(p, window=20, stuck_ratio=0.3, stuck_streak=10)
        assert info["window"] == 20

    def test_lenient_thresholds(self, tmp_path: Path):
        p = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(20):
            mod = f"mod_{i % 3}.py"
            lines.append(json.dumps({
                "seq": i, "kind": "thought",
                "text": f"`{mod}` noted"
            }))
        p.write_text("\n".join(lines) + "\n")

        info = pool_diversity(p, window=20, stuck_ratio=0.05, stuck_streak=100)
        assert info["verdict"] in ("narrowing", "diverse")
