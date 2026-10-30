#!/usr/bin/env python3
"""Tests for stroke_dedup_gate.py — the writer's duplicate prevention gate."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure tools/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stroke_dedup_gate import (
    build_recent_hashes,
    check_last_n,
    load_recent_strokes,
    should_accept,
    strip_metric_suffix,
    text_hash,
)


# ---------------------------------------------------------------------------
# strip_metric_suffix
# ---------------------------------------------------------------------------

class TestStripMetricSuffix:
    def test_removes_measured_suffix(self):
        text = "tests are the part of a repository that argues back -- measured now: 1010 python files, 5815 logged thoughts"
        assert strip_metric_suffix(text) == "tests are the part of a repository that argues back"

    def test_no_suffix_unchanged(self):
        text = "plain text without metrics"
        assert strip_metric_suffix(text) == text

    def test_empty_string(self):
        assert strip_metric_suffix("") == ""

    def test_multiple_dashes_only_strips_last(self):
        text = "commit history is the only honest log -- because it cannot be backdated -- measured now: 500 files"
        assert strip_metric_suffix(text) == "commit history is the only honest log -- because it cannot be backdated"

    def test_whitespace_handling(self):
        text = "  some text   -- measured now: stuff  "
        assert strip_metric_suffix(text) == "some text"


# ---------------------------------------------------------------------------
# text_hash
# ---------------------------------------------------------------------------

class TestTextHash:
    def test_same_body_different_metrics_same_hash(self):
        a = "reproducibility is a courtesy -- measured now: 100 files"
        b = "reproducibility is a courtesy -- measured now: 999 files, 50 commits"
        assert text_hash(a) == text_hash(b)

    def test_different_bodies_different_hash(self):
        a = "tests argue back"
        b = "naming is hard"
        assert text_hash(a) != text_hash(b)

    def test_hash_is_16_chars(self):
        h = text_hash("anything")
        assert len(h) == 16

    def test_deterministic(self):
        assert text_hash("hello") == text_hash("hello")


# ---------------------------------------------------------------------------
# build_recent_hashes
# ---------------------------------------------------------------------------

class TestBuildRecentHashes:
    def test_empty(self):
        assert build_recent_hashes([]) == {}

    def test_single_stroke(self):
        strokes = [{"seq": 1, "text": "hello world"}]
        hashes = build_recent_hashes(strokes)
        assert len(hashes) == 1
        assert text_hash("hello world") in hashes

    def test_duplicate_overwrites_with_latest_seq(self):
        strokes = [
            {"seq": 1, "text": "hello"},
            {"seq": 5, "text": "hello"},
        ]
        hashes = build_recent_hashes(strokes)
        assert hashes[text_hash("hello")] == 5

    def test_distinct_texts_all_present(self):
        strokes = [
            {"seq": 1, "text": "alpha"},
            {"seq": 2, "text": "beta"},
            {"seq": 3, "text": "gamma"},
        ]
        hashes = build_recent_hashes(strokes)
        assert len(hashes) == 3


# ---------------------------------------------------------------------------
# should_accept
# ---------------------------------------------------------------------------

class TestShouldAccept:
    def test_accepts_unique(self):
        strokes = [
            {"seq": 1, "text": "first thought"},
            {"seq": 2, "text": "second thought"},
        ]
        result = should_accept("brand new thought", strokes, window=10)
        assert result["accept"] is True
        assert result["duplicate_of_seq"] is None

    def test_rejects_duplicate(self):
        strokes = [
            {"seq": 10, "text": "reproducibility is a courtesy"},
            {"seq": 11, "text": "tests argue back"},
        ]
        result = should_accept("reproducibility is a courtesy", strokes, window=10)
        assert result["accept"] is False
        assert result["duplicate_of_seq"] == 10

    def test_rejects_duplicate_with_different_metrics(self):
        strokes = [
            {"seq": 42, "text": "naming is hard -- measured now: 100 files"},
        ]
        result = should_accept(
            "naming is hard -- measured now: 999 files, 50 commits",
            strokes, window=10,
        )
        assert result["accept"] is False
        assert result["duplicate_of_seq"] == 42

    def test_accepts_when_outside_window(self):
        strokes = [
            {"seq": 1, "text": "old thought"},
            {"seq": 2, "text": "another"},
            {"seq": 3, "text": "third"},
        ]
        # Window of 2 only looks at last 2 strokes
        result = should_accept("old thought", strokes, window=2)
        assert result["accept"] is True

    def test_empty_recent_accepts_everything(self):
        result = should_accept("anything", [], window=10)
        assert result["accept"] is True

    def test_result_has_required_keys(self):
        result = should_accept("test", [], window=5)
        assert "accept" in result
        assert "reason" in result
        assert "duplicate_of_seq" in result


# ---------------------------------------------------------------------------
# check_last_n
# ---------------------------------------------------------------------------

class TestCheckLastN:
    def test_all_unique(self):
        strokes = [{"seq": i, "text": f"thought {i}"} for i in range(10)]
        result = check_last_n(strokes, 10)
        assert result["unique_texts"] == 10
        assert result["would_reject"] == 0
        assert result["acceptance_rate"] == 1.0

    def test_all_identical(self):
        strokes = [{"seq": i, "text": "same thing"} for i in range(10)]
        result = check_last_n(strokes, 10)
        assert result["unique_texts"] == 1
        assert result["would_reject"] == 9
        assert result["acceptance_rate"] == pytest.approx(0.1)

    def test_window_truncation(self):
        strokes = [{"seq": i, "text": f"t{i}"} for i in range(20)]
        result = check_last_n(strokes, 5)
        # Only last 5 strokes matter
        assert result["window_size"] == 5
        assert result["unique_texts"] == 5

    def test_empty_strokes(self):
        result = check_last_n([], 10)
        assert result["window_size"] == 0
        assert result["acceptance_rate"] == 1.0

    def test_mixed_duplicates(self):
        strokes = [
            {"seq": 1, "text": "alpha"},
            {"seq": 2, "text": "beta"},
            {"seq": 3, "text": "alpha"},
            {"seq": 4, "text": "gamma"},
            {"seq": 5, "text": "beta"},
        ]
        result = check_last_n(strokes, 5)
        assert result["unique_texts"] == 3
        assert result["duplicate_hashes"] == 2
        assert result["would_reject"] == 2


# ---------------------------------------------------------------------------
# load_recent_strokes (integration with temp file)
# ---------------------------------------------------------------------------

class TestLoadRecentStrokes:
    def test_loads_from_jsonl(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        records = [
            {"seq": 1, "text": "first", "kind": "thought"},
            {"seq": 2, "text": "second", "kind": "note"},
            {"seq": 3, "text": "third", "kind": "devlog"},
        ]
        p.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        loaded = load_recent_strokes(p, window=10)
        assert len(loaded) == 3
        assert loaded[0]["seq"] == 1

    def test_window_limits_results(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        records = [{"seq": i, "text": f"t{i}"} for i in range(20)]
        p.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        loaded = load_recent_strokes(p, window=5)
        assert len(loaded) == 5
        assert loaded[0]["seq"] == 15  # last 5

    def test_missing_file_returns_empty(self, tmp_path):
        p = tmp_path / "nonexistent.jsonl"
        assert load_recent_strokes(p, window=10) == []

    def test_skips_malformed_lines(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text('{"seq":1,"text":"ok"}\nBADLINE\n{"seq":2,"text":"fine"}\n', encoding="utf-8")
        loaded = load_recent_strokes(p, window=10)
        assert len(loaded) == 2


# ---------------------------------------------------------------------------
# Integration: realistic loop scenario
# ---------------------------------------------------------------------------

class TestLoopScenario:
    def test_detects_cycling_opinions(self):
        """Simulate the writer cycling through 3 opinions."""
        opinions = [
            "reproducibility is a courtesy to whoever debugs this at 2am, usually me",
            "tests are the part of a repository that argues back",
            "a deterministic garden beats a random one: it records elapsed time",
        ]
        strokes = []
        for i in range(30):
            text = opinions[i % 3] + f" -- measured now: {1000 + i} files"
            strokes.append({"seq": 5800 + i, "text": text})

        # The gate should reject any of the 3 cycling opinions
        candidate = opinions[0] + " -- measured now: 9999 files"
        result = should_accept(candidate, strokes, window=30)
        assert result["accept"] is False

        # A genuinely new opinion should be accepted
        new_text = "commit history is the only honest documentation -- measured now: 2000 files"
        result = should_accept(new_text, strokes, window=30)
        assert result["accept"] is True

    def test_check_last_shows_low_acceptance_for_loop(self):
        """A looping writer should show low acceptance rate."""
        opinions = ["alpha thought", "beta thought", "gamma thought"]
        strokes = [
            {"seq": i, "text": opinions[i % 3] + f" -- measured now: {i} files"}
            for i in range(50)
        ]
        result = check_last_n(strokes, 50)
        assert result["unique_texts"] == 3
        assert result["acceptance_rate"] == pytest.approx(3 / 50)
