#!/usr/bin/env python3
"""Tests for tools/stale_stroke_detector.py — duplicate stroke detection."""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import stale_stroke_detector as ssd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stroke(seq: int, text: str, kind: str = "thought") -> dict:
    return {"seq": seq, "kind": kind, "text": text, "at": f"2026-10-19T00:{seq:02d}:00+00:00"}


def _write_strokes(strokes: list[dict], path: Path) -> Path:
    with open(path, "w", encoding="utf-8") as fh:
        for s in strokes:
            fh.write(json.dumps(s) + "\n")
    return path


# ---------------------------------------------------------------------------
# strip_suffix
# ---------------------------------------------------------------------------


class TestStripSuffix:
    def test_removes_at_this_moment(self):
        text = "naming is hard. At this moment: 576 python files"
        assert ssd.strip_suffix(text) == "naming is hard."

    def test_removes_measured_now(self):
        text = "reproducibility is courtesy -- measured now: 908 files"
        assert ssd.strip_suffix(text) == "reproducibility is courtesy"

    def test_removes_dash_separator(self):
        text = "automation fails quietly -- commit 1566"
        assert ssd.strip_suffix(text) == "automation fails quietly"

    def test_no_suffix_unchanged(self):
        text = "a clean thought with no suffix"
        assert ssd.strip_suffix(text) == "a clean thought with no suffix"

    def test_empty_string(self):
        assert ssd.strip_suffix("") == ""


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------


class TestFingerprint:
    def test_short_text_returns_full_stripped(self):
        text = "short. At this moment: stats"
        result = ssd.fingerprint(text, min_prefix=40)
        assert result == "short."

    def test_long_text_preserved(self):
        text = "this is a long enough thought to pass the prefix threshold test. At this moment: 100 files"
        result = ssd.fingerprint(text, min_prefix=40)
        assert "At this moment" not in result
        assert len(result) >= 40

    def test_min_prefix_boundary(self):
        text = "x" * 39 + ". At this moment: stuff"
        result = ssd.fingerprint(text, min_prefix=40)
        # stripped is 39 chars, below threshold
        assert result == "x" * 39 + "."


# ---------------------------------------------------------------------------
# load_strokes
# ---------------------------------------------------------------------------


class TestLoadStrokes:
    def test_loads_valid_jsonl(self, tmp_path: Path):
        p = _write_strokes([_stroke(1, "hello"), _stroke(2, "world")], tmp_path / "s.jsonl")
        result = ssd.load_strokes(p)
        assert len(result) == 2
        assert result[0]["text"] == "hello"

    def test_skips_malformed_lines(self, tmp_path: Path):
        p = tmp_path / "s.jsonl"
        p.write_text('{"seq":1,"text":"ok"}\nnot json\n{"seq":2,"text":"ok2"}\n')
        result = ssd.load_strokes(p)
        assert len(result) == 2

    def test_skips_blank_lines(self, tmp_path: Path):
        p = tmp_path / "s.jsonl"
        p.write_text('\n{"seq":1,"text":"a"}\n\n')
        result = ssd.load_strokes(p)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# detect_stale — exact duplicates
# ---------------------------------------------------------------------------


class TestDetectExact:
    def test_no_duplicates(self):
        strokes = [_stroke(i, f"unique thought number {i}") for i in range(10)]
        groups = ssd.detect_stale(strokes, window=10)
        exact = [g for g in groups if g.kind == "exact"]
        assert len(exact) == 0

    def test_finds_exact_duplicates(self):
        strokes = [
            _stroke(1, "hello world"),
            _stroke(2, "something else"),
            _stroke(3, "hello world"),
        ]
        groups = ssd.detect_stale(strokes, window=10)
        exact = [g for g in groups if g.kind == "exact"]
        assert len(exact) >= 1
        assert exact[0].count == 2

    def test_window_limits_scope(self):
        # Duplicate at index 0 should be outside window=3
        strokes = [_stroke(0, "duplicate")] + [_stroke(i, f"filler {i}") for i in range(1, 5)] + [_stroke(5, "duplicate")]
        groups = ssd.detect_stale(strokes, window=3)
        exact = [g for g in groups if g.kind == "exact"]
        # Only last 3 strokes are scanned; "duplicate" at index 0 is excluded
        assert len(exact) == 0


# ---------------------------------------------------------------------------
# detect_stale — prefix (near) duplicates
# ---------------------------------------------------------------------------


class TestDetectPrefix:
    def test_finds_near_duplicates(self):
        base = "automation fails quietly, so the log has to say something"
        strokes = [
            _stroke(1, f"{base}. At this moment: 100 files"),
            _stroke(2, "totally different thought"),
            _stroke(3, f"{base}. At this moment: 200 files"),
        ]
        groups = ssd.detect_stale(strokes, window=10, min_prefix=20)
        prefix = [g for g in groups if g.kind == "prefix"]
        assert len(prefix) >= 1
        assert prefix[0].count == 2

    def test_short_text_not_matched_as_prefix(self):
        strokes = [
            _stroke(1, "short. At this moment: a"),
            _stroke(2, "short. At this moment: b"),
        ]
        groups = ssd.detect_stale(strokes, window=10, min_prefix=40)
        prefix = [g for g in groups if g.kind == "prefix"]
        assert len(prefix) == 0

    def test_different_prefixes_not_grouped(self):
        strokes = [
            _stroke(1, "alpha thought is completely unique today. At this moment: 1"),
            _stroke(2, "beta thought is entirely different stuff. At this moment: 2"),
        ]
        groups = ssd.detect_stale(strokes, window=10, min_prefix=20)
        prefix = [g for g in groups if g.kind == "prefix"]
        assert len(prefix) == 0


# ---------------------------------------------------------------------------
# format helpers
# ---------------------------------------------------------------------------


class TestFormat:
    def test_clean_message(self):
        text = ssd.format_text([], 50)
        assert "clean" in text
        assert "50" in text

    def test_stale_message_includes_count(self):
        g = ssd.StaleGroup(prefix="test prefix", indices=[0, 1], seqs=[1, 2], kind="exact")
        text = ssd.format_text([g], 10)
        assert "1 stale group" in text
        assert "exact x2" in text

    def test_json_output_parseable(self):
        g = ssd.StaleGroup(prefix="x" * 100, indices=[0, 1, 2], seqs=[1, 2, 3], kind="prefix")
        output = ssd.format_json([g], 20)
        data = json.loads(output)
        assert data["stale_groups"] == 1
        assert data["total_scanned"] == 20
        assert len(data["groups"]) == 1


# ---------------------------------------------------------------------------
# exit_code
# ---------------------------------------------------------------------------


class TestExitCode:
    def test_zero_when_clean(self):
        assert ssd.exit_code([]) == 0

    def test_one_when_stale(self):
        g = ssd.StaleGroup(prefix="dup", indices=[0, 1], seqs=[1, 2], kind="exact")
        assert ssd.exit_code([g]) == 1


# ---------------------------------------------------------------------------
# run() integration
# ---------------------------------------------------------------------------


class TestRun:
    def test_missing_file(self, tmp_path: Path):
        code, out = ssd.run(tmp_path / "nonexistent.jsonl")
        assert code == 2
        assert "not found" in out

    def test_clean_strokes(self, tmp_path: Path):
        p = _write_strokes([_stroke(i, f"unique {i}") for i in range(5)], tmp_path / "s.jsonl")
        code, out = ssd.run(p)
        assert code == 0
        assert "clean" in out

    def test_stale_detected(self, tmp_path: Path):
        strokes = [
            _stroke(1, "same thought repeated here exactly"),
            _stroke(2, "different"),
            _stroke(3, "same thought repeated here exactly"),
        ]
        p = _write_strokes(strokes, tmp_path / "s.jsonl")
        code, out = ssd.run(p)
        assert code == 1
        assert "stale" in out

    def test_json_mode(self, tmp_path: Path):
        strokes = [_stroke(i, f"thought {i}") for i in range(3)]
        p = _write_strokes(strokes, tmp_path / "s.jsonl")
        code, out = ssd.run(p, as_json=True)
        data = json.loads(out)
        assert "total_scanned" in data
