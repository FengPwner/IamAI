"""Tests for iamai.topic_drift."""

import json
import math
from collections import Counter
from pathlib import Path

import pytest

from iamai.topic_drift import (
    _classify,
    _jsd,
    _load_kinds,
    _normalise,
    drift,
    drift_report,
    kind_distribution,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_strokes_file(tmp_path: Path, strokes: list[dict]) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    p = data_dir / "strokes.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for s in strokes:
            f.write(json.dumps(s) + "\n")
    return p


def _stroke(seq: int, kind: str = "thought") -> dict:
    return {"seq": seq, "at": "2026-10-15T00:00:00+00:00", "kind": kind, "text": "x"}


# ---------------------------------------------------------------------------
# _normalise
# ---------------------------------------------------------------------------

class TestNormalise:
    def test_empty(self):
        assert _normalise(Counter()) == {}

    def test_uniform(self):
        result = _normalise(Counter({"a": 5, "b": 5}))
        assert result == {"a": 0.5, "b": 0.5}

    def test_single(self):
        result = _normalise(Counter({"x": 10}))
        assert result == {"x": 1.0}

    def test_zero_values(self):
        result = _normalise(Counter({"a": 0, "b": 0}))
        assert result == {}


# ---------------------------------------------------------------------------
# _jsd
# ---------------------------------------------------------------------------

class TestJSD:
    def test_identical(self):
        p = {"a": 0.5, "b": 0.5}
        assert _jsd(p, p) == pytest.approx(0.0, abs=1e-9)

    def test_both_empty(self):
        assert _jsd({}, {}) == 0.0

    def test_maximal_divergence(self):
        # Completely disjoint supports → JSD = 1.0
        p = {"a": 1.0}
        q = {"b": 1.0}
        assert _jsd(p, q) == pytest.approx(1.0, abs=1e-9)

    def test_symmetry(self):
        p = {"a": 0.7, "b": 0.3}
        q = {"a": 0.3, "b": 0.7}
        assert _jsd(p, q) == pytest.approx(_jsd(q, p), abs=1e-9)

    def test_partial_overlap(self):
        p = {"a": 0.5, "b": 0.5}
        q = {"b": 0.5, "c": 0.5}
        val = _jsd(p, q)
        assert 0.0 < val < 1.0

    def test_one_empty(self):
        p = {"a": 1.0}
        q = {}
        # When one is empty and the other has support, JSD > 0
        val = _jsd(p, q)
        assert val > 0.0


# ---------------------------------------------------------------------------
# _classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_stable(self):
        assert _classify(0.0) == "stable"
        assert _classify(0.049) == "stable"

    def test_shift(self):
        assert _classify(0.05) == "shift"
        assert _classify(0.199) == "shift"

    def test_drift(self):
        assert _classify(0.20) == "drift"
        assert _classify(0.5) == "drift"
        assert _classify(1.0) == "drift"


# ---------------------------------------------------------------------------
# _load_kinds
# ---------------------------------------------------------------------------

class TestLoadKinds:
    def test_missing_file(self, tmp_path: Path):
        result = _load_kinds(tmp_path / "nope.jsonl", 10)
        assert result == []

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        assert _load_kinds(p, 10) == []

    def test_basic_load(self, tmp_path: Path):
        strokes = [_stroke(i, "thought") for i in range(5)]
        strokes += [_stroke(i + 5, "snippet") for i in range(5)]
        p = _make_strokes_file(tmp_path, strokes)
        kinds = _load_kinds(p, 10)
        assert len(kinds) == 10
        assert kinds[:5] == ["thought"] * 5
        assert kinds[5:] == ["snippet"] * 5

    def test_window_smaller_than_file(self, tmp_path: Path):
        strokes = [_stroke(i, "thought") for i in range(20)]
        strokes += [_stroke(i + 20, "note") for i in range(20)]
        p = _make_strokes_file(tmp_path, strokes)
        kinds = _load_kinds(p, 5)
        assert len(kinds) == 5
        assert all(k == "note" for k in kinds)

    def test_with_offset(self, tmp_path: Path):
        # 10 thoughts then 10 snippets
        strokes = [_stroke(i, "thought") for i in range(10)]
        strokes += [_stroke(i + 10, "snippet") for i in range(10)]
        p = _make_strokes_file(tmp_path, strokes)
        # offset=10 → skip the last 10, return the 10 before that
        kinds = _load_kinds(p, 10, offset=10)
        assert len(kinds) == 10
        assert all(k == "thought" for k in kinds)

    def test_malformed_lines_skipped(self, tmp_path: Path):
        p = tmp_path / "data" / "strokes.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            '{"seq":1,"kind":"thought","at":"","text":"x"}\n'
            'NOT JSON\n'
            '{"seq":2,"kind":"note","at":"","text":"y"}\n'
        )
        kinds = _load_kinds(p, 10)
        assert kinds == ["thought", "note"]


# ---------------------------------------------------------------------------
# kind_distribution
# ---------------------------------------------------------------------------

class TestKindDistribution:
    def test_empty(self, tmp_path: Path):
        p = _make_strokes_file(tmp_path, [])
        result = kind_distribution(p)
        assert result == {}

    def test_uniform(self, tmp_path: Path):
        strokes = [_stroke(i, "thought") for i in range(5)]
        strokes += [_stroke(i + 5, "snippet") for i in range(5)]
        p = _make_strokes_file(tmp_path, strokes)
        result = kind_distribution(p, window=10)
        assert result == {"thought": 0.5, "snippet": 0.5}

    def test_single_kind(self, tmp_path: Path):
        strokes = [_stroke(i, "note") for i in range(10)]
        p = _make_strokes_file(tmp_path, strokes)
        result = kind_distribution(p, window=10)
        assert result == {"note": 1.0}

    def test_three_way_split(self, tmp_path: Path):
        strokes = [_stroke(i, "thought") for i in range(4)]
        strokes += [_stroke(i + 4, "snippet") for i in range(3)]
        strokes += [_stroke(i + 7, "note") for i in range(3)]
        p = _make_strokes_file(tmp_path, strokes)
        result = kind_distribution(p, window=10)
        assert result["thought"] == pytest.approx(0.4)
        assert result["snippet"] == pytest.approx(0.3)
        assert result["note"] == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# drift
# ---------------------------------------------------------------------------

class TestDrift:
    def test_identical(self):
        dist = {"a": 0.5, "b": 0.5}
        result = drift(dist, dist)
        assert result["jsd"] == 0.0
        assert result["verdict"] == "stable"

    def test_completely_different(self):
        before = {"a": 1.0}
        after = {"b": 1.0}
        result = drift(before, after)
        assert result["jsd"] == pytest.approx(1.0, abs=0.001)
        assert result["verdict"] == "drift"

    def test_keys_populated(self):
        before = {"a": 0.5, "b": 0.5}
        after = {"b": 0.5, "c": 0.5}
        result = drift(before, after)
        assert result["before_keys"] == 2
        assert result["after_keys"] == 2
        assert result["shared_keys"] == 1

    def test_both_empty(self):
        result = drift({}, {})
        assert result["jsd"] == 0.0
        assert result["verdict"] == "stable"

    def test_partial_overlap_verdict(self):
        before = {"a": 0.5, "b": 0.3, "c": 0.2}
        after = {"a": 0.2, "b": 0.3, "d": 0.5}
        result = drift(before, after)
        assert result["verdict"] in ("shift", "drift")
        assert result["shared_keys"] == 2


# ---------------------------------------------------------------------------
# drift_report
# ---------------------------------------------------------------------------

class TestDriftReport:
    def test_stable_report(self, tmp_path: Path):
        # Same kinds throughout → stable
        strokes = [_stroke(i, "thought") for i in range(60)]
        _make_strokes_file(tmp_path, strokes)
        report = drift_report(tmp_path, window=30)
        assert "stable" in report
        assert "JSD" in report

    def test_drift_report(self, tmp_path: Path):
        # First half: all "thought"; second half: all "snippet"
        strokes = [_stroke(i, "thought") for i in range(30)]
        strokes += [_stroke(i + 30, "snippet") for i in range(30)]
        _make_strokes_file(tmp_path, strokes)
        report = drift_report(tmp_path, window=30)
        assert "drift" in report

    def test_empty_repo(self, tmp_path: Path):
        _make_strokes_file(tmp_path, [])
        report = drift_report(tmp_path, window=30)
        assert "stable" in report

    def test_report_format(self, tmp_path: Path):
        strokes = [_stroke(i, "thought") for i in range(30)]
        strokes += [_stroke(i + 30, "snippet") for i in range(15)]
        strokes += [_stroke(i + 45, "note") for i in range(15)]
        _make_strokes_file(tmp_path, strokes)
        report = drift_report(tmp_path, window=30)
        assert "→" in report
        assert "shared" in report
