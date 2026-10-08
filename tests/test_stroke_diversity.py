"""Tests for tools/stroke_diversity.py — stroke kind distribution analysis."""

import json
import math
import tempfile
from pathlib import Path

import pytest

# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import stroke_diversity as sd


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def balanced_strokes():
    """60 strokes, 10 per kind — perfectly balanced."""
    kinds = sd.DEFAULT_KINDS
    strokes = []
    for i in range(60):
        strokes.append({"seq": i, "kind": kinds[i % len(kinds)], "text": f"stroke {i}"})
    return strokes


@pytest.fixture
def skewed_strokes():
    """60 strokes, 55 in 'thought', 1 in each other — maximally skewed."""
    strokes = []
    for i in range(55):
        strokes.append({"seq": i, "kind": "thought", "text": f"thought {i}"})
    for j, kind in enumerate(sd.DEFAULT_KINDS):
        if kind != "thought":
            strokes.append({"seq": 55 + j, "kind": kind, "text": f"lone {kind}"})
    return strokes


@pytest.fixture
def single_kind_strokes():
    """30 strokes, all 'note' — total starvation."""
    return [{"seq": i, "kind": "note", "text": f"note {i}"} for i in range(30)]


@pytest.fixture
def tmp_strokes_file(tmp_path):
    """Create a temporary strokes.jsonl file."""
    def _write(strokes):
        p = tmp_path / "strokes.jsonl"
        p.write_text("\n".join(json.dumps(s) for s in strokes) + "\n", encoding="utf-8")
        return p
    return _write


# ---------------------------------------------------------------------------
# compute_imbalance
# ---------------------------------------------------------------------------

class TestComputeImbalance:
    def test_empty_returns_zero(self):
        assert sd.compute_imbalance([]) == 0.0

    def test_balanced_is_near_zero(self, balanced_strokes):
        score = sd.compute_imbalance(balanced_strokes)
        assert score == 0.0

    def test_single_kind_is_one(self, single_kind_strokes):
        score = sd.compute_imbalance(single_kind_strokes)
        assert score == 1.0

    def test_skewed_is_high(self, skewed_strokes):
        score = sd.compute_imbalance(skewed_strokes)
        assert score > 0.7

    def test_mild_skew_in_range(self):
        """Slightly uneven: 12,10,10,10,9,9 → mild."""
        kinds = sd.DEFAULT_KINDS
        counts = [12, 10, 10, 10, 9, 9]
        strokes = []
        seq = 0
        for kind, count in zip(kinds, counts):
            for _ in range(count):
                strokes.append({"seq": seq, "kind": kind, "text": "x"})
                seq += 1
        score = sd.compute_imbalance(strokes)
        assert 0.0 < score < 0.15

    def test_unknown_kind_ignored_in_expected(self):
        """Strokes with kind='unknown' still count in n but not in expected kinds."""
        strokes = [{"seq": 0, "kind": "unknown", "text": "x"}] * 10
        score = sd.compute_imbalance(strokes)
        # All expected kinds have 0; deviation = k*(n/k) = n, max_dev = 2n(k-1)/k
        # score = n / (2n(k-1)/k) = k/(2(k-1)) = 6/10 = 0.6
        assert abs(score - 0.6) < 0.01


# ---------------------------------------------------------------------------
# compute_entropy
# ---------------------------------------------------------------------------

class TestComputeEntropy:
    def test_empty_returns_zero(self):
        assert sd.compute_entropy([]) == 0.0

    def test_single_kind_zero_entropy(self, single_kind_strokes):
        assert sd.compute_entropy(single_kind_strokes) == 0.0

    def test_balanced_is_max_entropy(self, balanced_strokes):
        entropy = sd.compute_entropy(balanced_strokes)
        max_entropy = math.log2(len(sd.DEFAULT_KINDS))
        assert abs(entropy - max_entropy) < 0.01

    def test_two_kinds_one_bit(self):
        """Two equally-populated kinds → entropy = 1 bit."""
        strokes = [{"seq": i, "kind": "note" if i < 30 else "thought", "text": "x"}
                    for i in range(60)]
        # Only count note and thought; other kinds have 0
        # Shannon entropy = -2*(0.5*log2(0.5)) = 1.0 bit
        # But our function only looks at expected_kinds, so other 4 kinds contribute 0
        entropy = sd.compute_entropy(strokes)
        # With 4 empty kinds, the actual entropy is less than log2(6)
        # For note=30, thought=30, rest=0: H = -2*(0.5*log2(0.5)) = 1.0
        assert abs(entropy - 1.0) < 0.01


# ---------------------------------------------------------------------------
# classify_imbalance
# ---------------------------------------------------------------------------

class TestClassifyImbalance:
    @pytest.mark.parametrize("score,expected", [
        (0.0, "balanced"),
        (0.05, "balanced"),
        (0.099, "balanced"),
        (0.1, "mild-skew"),
        (0.2, "mild-skew"),
        (0.25, "noticeable"),
        (0.39, "noticeable"),
        (0.4, "starved"),
        (1.0, "starved"),
    ])
    def test_thresholds(self, score, expected):
        assert sd.classify_imbalance(score) == expected


# ---------------------------------------------------------------------------
# load_recent_strokes
# ---------------------------------------------------------------------------

class TestLoadRecentStrokes:
    def test_nonexistent_file(self, tmp_path):
        result = sd.load_recent_strokes(tmp_path / "nope.jsonl", 100)
        assert result == []

    def test_loads_all_when_fewer_than_window(self, tmp_strokes_file):
        strokes = [{"seq": i, "kind": "note", "text": "x"} for i in range(5)]
        path = tmp_strokes_file(strokes)
        loaded = sd.load_recent_strokes(path, 100)
        assert len(loaded) == 5

    def test_window_truncates(self, tmp_strokes_file):
        strokes = [{"seq": i, "kind": "note", "text": "x"} for i in range(200)]
        path = tmp_strokes_file(strokes)
        loaded = sd.load_recent_strokes(path, 50)
        assert len(loaded) == 50
        # Should be the LAST 50 (seq 150..199)
        assert loaded[0]["seq"] == 150

    def test_skips_malformed_lines(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(
            '{"seq": 1, "kind": "note", "text": "ok"}\n'
            'this is not json\n'
            '{"seq": 2, "kind": "thought", "text": "ok"}\n',
            encoding="utf-8",
        )
        loaded = sd.load_recent_strokes(p, 100)
        assert len(loaded) == 2


# ---------------------------------------------------------------------------
# Integration: end-to-end with real-ish data
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_balanced_report(self, tmp_strokes_file, balanced_strokes, monkeypatch):
        """Full pipeline with balanced data produces 'balanced' classification."""
        path = tmp_strokes_file(balanced_strokes)
        monkeypatch.setattr(sd, "STROKES_PATH", path)
        strokes = sd.load_recent_strokes(path, 100)
        imbalance = sd.compute_imbalance(strokes)
        label = sd.classify_imbalance(imbalance)
        assert label == "balanced"
        assert imbalance == 0.0

    def test_starved_report(self, tmp_strokes_file, single_kind_strokes, monkeypatch):
        """Full pipeline with single-kind data produces 'starved' classification."""
        path = tmp_strokes_file(single_kind_strokes)
        monkeypatch.setattr(sd, "STROKES_PATH", path)
        strokes = sd.load_recent_strokes(path, 100)
        imbalance = sd.compute_imbalance(strokes)
        label = sd.classify_imbalance(imbalance)
        assert label == "starved"
