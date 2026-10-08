"""Tests for iamai.stroke_entropy."""

import json
import os
from pathlib import Path

import pytest

from iamai.stroke_entropy import (
    _classify,
    _load_recent_kinds,
    _shannon,
    entropy,
    entropy_report,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path, strokes: list[dict] | None = None) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    if strokes is not None:
        with open(data_dir / "strokes.jsonl", "w", encoding="utf-8") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")
    return tmp_path


def _stroke(seq: int, kind: str = "thought") -> dict:
    return {"seq": seq, "at": "2026-10-08T00:00:00+00:00", "kind": kind, "text": "x"}


# ---------------------------------------------------------------------------
# _shannon
# ---------------------------------------------------------------------------

class TestShannon:
    def test_empty(self):
        assert _shannon([]) == 0.0

    def test_uniform(self):
        # 4 equally likely categories → log2(4) = 2.0 bits
        vals = ["a", "b", "c", "d"] * 10
        assert abs(_shannon(vals) - 2.0) < 0.01

    def test_single_category(self):
        assert _shannon(["a", "a", "a"]) == 0.0

    def test_two_categories(self):
        # 50/50 binary → 1.0 bit
        vals = ["a", "b"] * 20
        assert abs(_shannon(vals) - 1.0) < 0.01

    def test_skewed(self):
        # heavily skewed toward one category → low entropy
        vals = ["a"] * 97 + ["b", "c", "d"]
        assert _shannon(vals) < 0.5


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_rich(self):
        assert _classify(2.0) == "rich"
        assert _classify(3.5) == "rich"

    def test_narrow(self):
        assert _classify(1.0) == "narrow"
        assert _classify(1.99) == "narrow"

    def test_loop(self):
        assert _classify(0.0) == "loop"
        assert _classify(0.99) == "loop"


# ---------------------------------------------------------------------------
# _load_recent_kinds
# ---------------------------------------------------------------------------

class TestLoadRecentKinds:
    def test_missing_file(self, tmp_path):
        assert _load_recent_kinds(tmp_path / "nope.jsonl", 10) == []

    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        assert _load_recent_kinds(p, 10) == []

    def test_reads_last_window(self, tmp_path):
        strokes = [_stroke(i, f"kind_{i % 5}") for i in range(100)]
        p = tmp_path / "strokes.jsonl"
        with p.open("w") as f:
            for s in strokes:
                f.write(json.dumps(s) + "\n")
        kinds = _load_recent_kinds(p, 10)
        assert len(kinds) == 10
        # last 10 strokes: seq 90..99, kinds 0,1,2,3,4,0,1,2,3,4
        assert kinds == ["kind_0", "kind_1", "kind_2", "kind_3", "kind_4"] * 2

    def test_malformed_lines_skipped(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        with p.open("w") as f:
            f.write("not json\n")
            f.write(json.dumps(_stroke(1, "note")) + "\n")
            f.write("{broken\n")
            f.write(json.dumps(_stroke(2, "devlog")) + "\n")
        kinds = _load_recent_kinds(p, 10)
        assert kinds == ["note", "devlog"]


# ---------------------------------------------------------------------------
# entropy (integration)
# ---------------------------------------------------------------------------

class TestEntropy:
    def test_no_repo(self, tmp_path):
        info = entropy(tmp_path)
        assert info["verdict"] == "loop"
        assert info["shannon"] == 0.0
        assert info["total"] == 0

    def test_diverse_strokes(self, tmp_path):
        strokes = [_stroke(i, f"kind_{i % 6}") for i in range(60)]
        repo = _make_repo(tmp_path, strokes)
        info = entropy(repo, window=30)
        assert info["distinct"] == 6
        assert info["total"] == 30
        assert info["shannon"] > 2.0
        assert info["verdict"] == "rich"

    def test_looping_strokes(self, tmp_path):
        # only 2 kinds alternating → low entropy
        strokes = [_stroke(i, "a" if i % 2 == 0 else "b") for i in range(30)]
        repo = _make_repo(tmp_path, strokes)
        info = entropy(repo, window=30)
        assert abs(info["shannon"] - 1.0) < 0.01
        assert info["verdict"] == "narrow"

    def test_single_kind(self, tmp_path):
        strokes = [_stroke(i, "thought") for i in range(30)]
        repo = _make_repo(tmp_path, strokes)
        info = entropy(repo, window=30)
        assert info["shannon"] == 0.0
        assert info["verdict"] == "loop"


# ---------------------------------------------------------------------------
# entropy_report
# ---------------------------------------------------------------------------

class TestEntropyReport:
    def test_format(self, tmp_path):
        strokes = [_stroke(i, f"kind_{i % 4}") for i in range(20)]
        repo = _make_repo(tmp_path, strokes)
        report = entropy_report(repo, window=20)
        assert "shannon" in report
        assert "over 20 strokes" in report
        assert "4 distinct kinds" in report

    def test_empty_repo(self, tmp_path):
        report = entropy_report(tmp_path)
        assert "loop" in report
        assert "0 strokes" in report
