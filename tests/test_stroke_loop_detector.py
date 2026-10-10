"""Tests for tools/stroke_loop_detector.py — repetitive loop detection."""

import json
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import stroke_loop_detector as sld


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def diverse_strokes():
    """50 strokes, each with unique text — no looping."""
    return [
        {"seq": i, "kind": "thought", "text": f"unique observation number {i}"}
        for i in range(50)
    ]


@pytest.fixture
def looping_strokes():
    """50 strokes cycling through only 3 templates — strong loop signal."""
    templates = [
        "the useful abstraction deletes a branch, it does not add a class",
        "a repo that only accumulates is a landfill with a README",
        "commit history is the only honest documentation because it cannot be backdated",
    ]
    strokes = []
    for i in range(50):
        body = templates[i % len(templates)]
        strokes.append({
            "seq": i,
            "kind": "thought",
            "text": f"{body} -- measured now: tree is {500 + i} files; {100000 + i * 10} lines is a lot for a toy",
        })
    return strokes


@pytest.fixture
def identical_strokes():
    """20 strokes with exactly the same body — maximum loop."""
    return [
        {
            "seq": i,
            "kind": "thought",
            "text": "growth that never stops is a tumour, not a garden -- measured now: commit 1136: the count of times this repo was pushed",
        }
        for i in range(20)
    ]


def _write_strokes_file(strokes: list[dict], tmp_path: Path) -> Path:
    p = tmp_path / "strokes.jsonl"
    p.write_text("\n".join(json.dumps(s) for s in strokes) + "\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# strip_metric_suffix
# ---------------------------------------------------------------------------

class TestStripMetricSuffix:
    def test_strips_measured_now(self):
        text = "some observation -- measured now: tree is 589 files; 109738 lines"
        assert sld.strip_metric_suffix(text) == "some observation"

    def test_strips_commit_suffix(self):
        text = "deleting a file is progress too -- measured now: commit 1136: the count"
        assert sld.strip_metric_suffix(text) == "deleting a file is progress too"

    def test_no_suffix(self):
        text = "just a plain thought without any metric"
        assert sld.strip_metric_suffix(text) == text

    def test_empty_string(self):
        assert sld.strip_metric_suffix("") == ""


# ---------------------------------------------------------------------------
# compute_loop_score
# ---------------------------------------------------------------------------

class TestComputeLoopScore:
    def test_diverse_strokes_low_score(self, diverse_strokes):
        result = sld.compute_loop_score(diverse_strokes)
        assert result["loop_score"] == 0.0
        assert result["is_looping"] is False
        assert result["unique_bodies"] == 50

    def test_looping_strokes_high_score(self, looping_strokes):
        result = sld.compute_loop_score(looping_strokes)
        # 3 unique bodies out of 50 → score = 1 - 3/50 = 0.94
        assert result["loop_score"] == pytest.approx(0.94, abs=0.01)
        assert result["is_looping"] is True
        assert result["unique_bodies"] == 3

    def test_identical_strokes_max_score(self, identical_strokes):
        result = sld.compute_loop_score(identical_strokes)
        # 1 unique body out of 20 → score = 1 - 1/20 = 0.95
        assert result["loop_score"] == pytest.approx(0.95, abs=0.01)
        assert result["is_looping"] is True
        assert result["unique_bodies"] == 1

    def test_empty_input(self):
        result = sld.compute_loop_score([])
        assert result["loop_score"] == 0.0
        assert result["total"] == 0

    def test_top_repeated_populated(self, looping_strokes):
        result = sld.compute_loop_score(looping_strokes)
        assert len(result["top_repeated"]) > 0
        # Each template appears ~16-17 times
        assert result["top_repeated"][0][1] >= 16

    def test_top_repeated_empty_for_diverse(self, diverse_strokes):
        result = sld.compute_loop_score(diverse_strokes)
        assert result["top_repeated"] == []


# ---------------------------------------------------------------------------
# detect_loop (file I/O)
# ---------------------------------------------------------------------------

class TestDetectLoop:
    def test_detects_loop_from_file(self, tmp_path, looping_strokes):
        path = _write_strokes_file(looping_strokes, tmp_path)
        result = sld.detect_loop(path=path, window=50)
        assert result["is_looping"] is True
        assert result["loop_score"] > 0.6

    def test_no_loop_from_file(self, tmp_path, diverse_strokes):
        path = _write_strokes_file(diverse_strokes, tmp_path)
        result = sld.detect_loop(path=path, window=50)
        assert result["is_looping"] is False
        assert result["loop_score"] == 0.0

    def test_custom_threshold(self, tmp_path, looping_strokes):
        path = _write_strokes_file(looping_strokes, tmp_path)
        # Even with threshold=0.99, the score is 0.94 so not looping
        result = sld.detect_loop(path=path, window=50, threshold=0.99)
        assert result["is_looping"] is False

    def test_window_smaller_than_file(self, tmp_path, diverse_strokes):
        path = _write_strokes_file(diverse_strokes, tmp_path)
        result = sld.detect_loop(path=path, window=10)
        assert result["total"] == 10

    def test_missing_file(self, tmp_path):
        result = sld.detect_loop(path=tmp_path / "nonexistent.jsonl")
        assert result["total"] == 0
        assert result["is_looping"] is False

    def test_json_output_keys(self, tmp_path, diverse_strokes):
        path = _write_strokes_file(diverse_strokes, tmp_path)
        result = sld.detect_loop(path=path, window=20, threshold=0.5)
        for key in ("total", "unique_bodies", "loop_score", "is_looping",
                     "top_repeated", "window", "threshold"):
            assert key in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_single_stroke(self):
        strokes = [{"seq": 1, "kind": "note", "text": "only one"}]
        result = sld.compute_loop_score(strokes)
        assert result["loop_score"] == 0.0
        assert result["unique_bodies"] == 1

    def test_two_identical(self):
        strokes = [
            {"seq": 1, "kind": "note", "text": "same -- measured now: x"},
            {"seq": 2, "kind": "note", "text": "same -- measured now: y"},
        ]
        result = sld.compute_loop_score(strokes)
        assert result["loop_score"] == 0.5
        assert result["unique_bodies"] == 1

    def test_malformed_jsonl(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text('{"seq": 1, "text": "ok"}\n{bad json\n{"seq": 2, "text": "also ok"}\n')
        result = sld.detect_loop(path=p, window=10)
        assert result["total"] == 2  # malformed line skipped
