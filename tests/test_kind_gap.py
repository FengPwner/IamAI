"""Tests for iamai.kind_gap — per-kind stroke recency tracker."""

import json
from pathlib import Path

import pytest

from iamai.kind_gap import (
    DEFAULT_KINDS,
    _read_tail,
    kind_gap,
    kind_gap_report,
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
    return {"seq": seq, "at": "2026-10-08T12:00:00+00:00", "kind": kind, "text": f"t{seq}"}


def _balanced(n: int = 60) -> list[dict]:
    """n strokes, round-robin across all kinds."""
    kinds = DEFAULT_KINDS
    return [_stroke(i, kinds[i % len(kinds)]) for i in range(n)]


def _skewed_single(kind: str = "thought", n: int = 50) -> list[dict]:
    """n strokes, all one kind."""
    return [_stroke(i, kind) for i in range(n)]


def _starve_one(starved: str = "garden", n: int = 60) -> list[dict]:
    """Balanced except one kind is completely absent."""
    kinds = tuple(k for k in DEFAULT_KINDS if k != starved)
    strokes = []
    for i in range(n):
        strokes.append(_stroke(i, kinds[i % len(kinds)]))
    return strokes


# ---------------------------------------------------------------------------
# _read_tail
# ---------------------------------------------------------------------------

class TestReadTail:
    def test_missing_file(self, tmp_path):
        assert _read_tail(tmp_path / "nope.jsonl") == []

    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        assert _read_tail(p) == []

    def test_parses_valid_lines(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        with open(p, "w") as f:
            f.write(json.dumps({"seq": 1}) + "\n")
            f.write(json.dumps({"seq": 2}) + "\n")
        result = _read_tail(p)
        assert len(result) == 2
        assert result[0]["seq"] == 1

    def test_skips_malformed_lines(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        with open(p, "w") as f:
            f.write("not json\n")
            f.write(json.dumps({"seq": 1}) + "\n")
            f.write("also bad\n")
        result = _read_tail(p)
        assert len(result) == 1

    def test_reads_only_tail(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        # Write a lot of data, then read only last 256 bytes
        lines = [json.dumps({"seq": i}) for i in range(200)]
        p.write_text("\n".join(lines) + "\n")
        result = _read_tail(p, nbytes=256)
        # Should get only the last few entries
        assert len(result) < 200
        assert len(result) > 0
        # Last entry should be seq 199
        assert result[-1]["seq"] == 199


# ---------------------------------------------------------------------------
# kind_gap — empty / edge cases
# ---------------------------------------------------------------------------

class TestKindGapEmpty:
    def test_no_strokes_file(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=None)
        info = kind_gap(repo)
        assert info["verdict"] == "empty"
        assert info["total_scanned"] == 0
        assert all(g is None for g in info["gaps"].values())

    def test_empty_file(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=[])
        info = kind_gap(repo)
        assert info["verdict"] == "empty"


# ---------------------------------------------------------------------------
# kind_gap — balanced
# ---------------------------------------------------------------------------

class TestKindGapBalanced:
    def test_perfectly_balanced(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=_balanced(60))
        info = kind_gap(repo, window=50)
        assert info["verdict"] == "balanced"
        assert info["starved_kinds"] == []
        assert info["max_gap"] is not None
        # With 6 kinds round-robin, max gap should be 5
        assert info["max_gap"] <= 5

    def test_slightly_uneven_still_balanced(self, tmp_path):
        # 50 strokes, but garden appears only once at position 0
        strokes = [_stroke(0, "garden")]
        kinds_no_garden = tuple(k for k in DEFAULT_KINDS if k != "garden")
        for i in range(1, 50):
            strokes.append(_stroke(i, kinds_no_garden[i % len(kinds_no_garden)]))
        repo = _make_repo(tmp_path, strokes=strokes)
        info = kind_gap(repo, window=50, threshold=48)
        # garden last seen at position 0, gap = 49, which is > threshold
        # This should be starved
        assert info["verdict"] == "starved"
        assert "garden" in info["starved_kinds"]


# ---------------------------------------------------------------------------
# kind_gap — starved
# ---------------------------------------------------------------------------

class TestKindGapStarved:
    def test_one_kind_absent(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=_starve_one("garden", 60))
        info = kind_gap(repo, window=50)
        assert info["verdict"] == "starved"
        assert "garden" in info["starved_kinds"]
        assert info["gaps"]["garden"] is None  # absent in window

    def test_all_one_kind(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=_skewed_single("thought", 50))
        info = kind_gap(repo, window=50)
        assert info["verdict"] == "starved"
        starved = [k for k in DEFAULT_KINDS if k != "thought"]
        assert set(info["starved_kinds"]) == set(starved)
        assert info["gaps"]["thought"] == 0  # last stroke is thought

    def test_custom_threshold(self, tmp_path):
        # Balanced round-robin but with very tight threshold
        repo = _make_repo(tmp_path, strokes=_balanced(60))
        info = kind_gap(repo, window=50, threshold=3)
        # Round-robin gap is 5, which exceeds threshold of 3
        assert info["verdict"] == "starved"

    def test_gap_values_correct(self, tmp_path):
        # thought at positions 0,6,12,...; devlog at 1,7,13,...; etc.
        strokes = _balanced(30)  # 5 full rounds of 6 kinds
        repo = _make_repo(tmp_path, strokes=strokes)
        info = kind_gap(repo, window=30)
        # In last 30 strokes (all of them), each kind appears every 6 positions
        # The last stroke is seq 29, kind = snippet (29 % 6 = 5 → snippet)
        # snippet gap = 0, thought gap = 5, devlog gap = 4, garden gap = 3,
        # note gap = 2, metrics gap = 1
        assert info["gaps"]["snippet"] == 0
        assert info["total_scanned"] == 30


# ---------------------------------------------------------------------------
# kind_gap — window
# ---------------------------------------------------------------------------

class TestKindGapWindow:
    def test_small_window(self, tmp_path):
        # 60 strokes total, but window=10 only sees last 10
        repo = _make_repo(tmp_path, strokes=_balanced(60))
        info = kind_gap(repo, window=10)
        assert info["total_scanned"] == 10

    def test_window_larger_than_file(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=_balanced(5))
        info = kind_gap(repo, window=100)
        assert info["total_scanned"] == 5


# ---------------------------------------------------------------------------
# kind_gap_report
# ---------------------------------------------------------------------------

class TestKindGapReport:
    def test_empty(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=None)
        report = kind_gap_report(repo)
        assert "empty" in report

    def test_balanced(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=_balanced(60))
        report = kind_gap_report(repo, window=50)
        assert "balanced" in report
        assert "6 kinds" in report

    def test_starved(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=_starve_one("garden", 60))
        report = kind_gap_report(repo, window=50)
        assert "starved" in report
        assert "garden" in report

    def test_custom_threshold_in_report(self, tmp_path):
        repo = _make_repo(tmp_path, strokes=_balanced(60))
        report = kind_gap_report(repo, window=50, threshold=24)
        assert "24" in report
