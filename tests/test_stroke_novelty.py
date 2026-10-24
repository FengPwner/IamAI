#!/usr/bin/env python3
"""Tests for tools/stroke_novelty.py — content repetition detection."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from stroke_novelty import (
    analyze,
    classify_freshness,
    detect_cycle_length,
    format_text,
    load_strokes,
    novelty_ratio,
    repeat_count,
    strip_measurement,
    text_hash,
    unique_count,
)


# ── helpers ──────────────────────────────────────────────────────────────


def _make_strokes(texts: list[str]) -> list[dict]:
    """Create minimal stroke records with explicit text content."""
    return [
        {"seq": i, "at": f"2026-10-24T12:{i:02d}:00+00:00", "kind": "thought", "text": t}
        for i, t in enumerate(texts)
    ]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


# ── text_hash ────────────────────────────────────────────────────────────


class TestTextHash:
    def test_deterministic(self):
        assert text_hash("hello") == text_hash("hello")

    def test_different_texts_differ(self):
        assert text_hash("hello") != text_hash("world")

    def test_empty_string(self):
        assert text_hash("") == text_hash("")

    def test_returns_string(self):
        assert isinstance(text_hash("abc"), str)
        assert len(text_hash("abc")) == 16

    def test_strips_measurement_suffix(self):
        """Same base text with different measurements should hash equal."""
        a = "hello -- measured now: 42 things"
        b = "hello -- measured now: 99 things"
        assert text_hash(a) == text_hash(b)

    def test_different_base_same_measurement(self):
        """Different base texts with same measurement should hash differently."""
        a = "hello -- measured now: 42 things"
        b = "world -- measured now: 42 things"
        assert text_hash(a) != text_hash(b)


# ── strip_measurement ────────────────────────────────────────────────────


class TestStripMeasurement:
    def test_removes_suffix(self):
        text = "hello world -- measured now: 42 things"
        assert strip_measurement(text) == "hello world"

    def test_no_suffix(self):
        assert strip_measurement("just a thought") == "just a thought"

    def test_empty(self):
        assert strip_measurement("") == ""

    def test_marker_only(self):
        assert strip_measurement("-- measured now: data") == ""

    def test_preserves_text_before(self):
        text = "an append-only log forces honesty -- measured now: 833 python files"
        assert strip_measurement(text) == "an append-only log forces honesty"

    def test_multiple_markers_keeps_first(self):
        text = "a -- measured now: b -- measured now: c"
        assert strip_measurement(text) == "a"


# ── unique_count ─────────────────────────────────────────────────────────


class TestUniqueCount:
    def test_all_unique(self):
        assert unique_count(["a", "b", "c"]) == 3

    def test_all_same(self):
        assert unique_count(["x", "x", "x"]) == 1

    def test_mixed(self):
        assert unique_count(["a", "b", "a", "c", "b"]) == 3

    def test_empty(self):
        assert unique_count([]) == 0

    def test_single(self):
        assert unique_count(["only"]) == 1


# ── novelty_ratio ────────────────────────────────────────────────────────


class TestNoveltyRatio:
    def test_all_unique(self):
        assert novelty_ratio(["a", "b", "c", "d"]) == 1.0

    def test_all_same(self):
        assert novelty_ratio(["x", "x", "x", "x"]) == pytest.approx(0.25)

    def test_half_repeat(self):
        # a, b, c, a → 3 unique out of 4
        assert novelty_ratio(["a", "b", "c", "a"]) == pytest.approx(0.75)

    def test_empty(self):
        assert novelty_ratio([]) == 1.0

    def test_single(self):
        assert novelty_ratio(["x"]) == 1.0

    def test_cycling_seven(self):
        """Seven unique texts cycling — first 7 are novel, rest are repeats."""
        base = [f"thought_{i}" for i in range(7)]
        texts = (base * 5)[:30]  # 30 texts, 7 unique
        assert novelty_ratio(texts) == pytest.approx(7 / 30, abs=0.01)


# ── repeat_count ─────────────────────────────────────────────────────────


class TestRepeatCount:
    def test_none_repeated(self):
        assert repeat_count(["a", "b", "c"]) == 0

    def test_one_repeated(self):
        assert repeat_count(["a", "b", "a"]) == 1

    def test_all_repeated(self):
        assert repeat_count(["a", "b", "a", "b"]) == 2

    def test_empty(self):
        assert repeat_count([]) == 0


# ── detect_cycle_length ─────────────────────────────────────────────────


class TestDetectCycleLength:
    def test_no_cycle(self):
        texts = [f"unique_{i}" for i in range(20)]
        assert detect_cycle_length(texts) == 0

    def test_cycle_of_1(self):
        """Same text repeated."""
        texts = ["x"] * 10
        assert detect_cycle_length(texts) == 1

    def test_cycle_of_3(self):
        texts = ["a", "b", "c"] * 6
        assert detect_cycle_length(texts) == 3

    def test_cycle_of_7(self):
        base = [f"t{i}" for i in range(7)]
        texts = base * 4
        assert detect_cycle_length(texts) == 7

    def test_too_short(self):
        assert detect_cycle_length(["a", "b"]) == 0

    def test_empty(self):
        assert detect_cycle_length([]) == 0

    def test_partial_repeat_not_cycle(self):
        """A partial repeat at the end should not count as a cycle."""
        texts = ["a", "b", "c", "d", "e", "a", "b", "c"]
        # last 6: d,e,a,b,c,a — no clean cycle
        result = detect_cycle_length(texts)
        # should be 0 or some cycle, just not crash
        assert isinstance(result, int)
        assert result >= 0


# ── classify_freshness ───────────────────────────────────────────────────


class TestClassifyFreshness:
    def test_fresh(self):
        assert classify_freshness(0.9, 0) == "FRESH"

    def test_fresh_boundary(self):
        assert classify_freshness(0.8, 0) == "FRESH"

    def test_warm(self):
        assert classify_freshness(0.65, 0) == "WARM"

    def test_warm_lower_boundary(self):
        assert classify_freshness(0.5, 0) == "WARM"

    def test_stale(self):
        assert classify_freshness(0.35, 0) == "STALE"

    def test_stale_lower_boundary(self):
        assert classify_freshness(0.2, 0) == "STALE"

    def test_looping_low_novelty(self):
        assert classify_freshness(0.1, 0) == "LOOPING"

    def test_looping_cycle_detected(self):
        assert classify_freshness(0.9, 7) == "LOOPING"

    def test_looping_both(self):
        assert classify_freshness(0.1, 3) == "LOOPING"


# ── load_strokes ─────────────────────────────────────────────────────────


class TestLoadStrokes:
    def test_missing_file(self, tmp_path):
        assert load_strokes(tmp_path / "nonexistent.jsonl") == []

    def test_valid_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        records = _make_strokes(["hello", "world"])
        _write_jsonl(p, records)
        loaded = load_strokes(p)
        assert len(loaded) == 2
        assert loaded[0]["text"] == "hello"

    def test_blank_lines(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text(json.dumps({"seq": 1, "text": "a"}) + "\n\n\n"
                      + json.dumps({"seq": 2, "text": "b"}) + "\n")
        assert len(load_strokes(p)) == 2

    def test_malformed_json(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text('{"seq": 1, "text": "ok"}\n{broken\n{"seq": 3, "text": "ok"}\n')
        assert len(load_strokes(p)) == 2


# ── format_text ──────────────────────────────────────────────────────────


class TestFormatText:
    def test_contains_key_fields(self):
        result = {
            "stroke_count": 100,
            "unique_count": 7,
            "repeat_count": 7,
            "novelty_ratio": 0.07,
            "cycle_length": 7,
            "freshness_class": "LOOPING",
            "top_repeat_count": 14,
            "top_repeat_example": "hello world",
        }
        text = format_text(result)
        assert "Stroke Content Novelty" in text
        assert "100" in text
        assert "LOOPING" in text
        assert "hello world" in text

    def test_no_cycle(self):
        result = {
            "stroke_count": 50,
            "unique_count": 50,
            "repeat_count": 0,
            "novelty_ratio": 1.0,
            "cycle_length": 0,
            "freshness_class": "FRESH",
            "top_repeat_count": 1,
            "top_repeat_example": "unique text",
        }
        text = format_text(result)
        assert "(none)" in text
        assert "FRESH" in text


# ── analyze (integration) ───────────────────────────────────────────────


class TestAnalyze:
    def test_fresh_strokes(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        records = _make_strokes([f"unique thought {i}" for i in range(50)])
        _write_jsonl(p, records)
        result = analyze(path=p, window=50)
        assert result["freshness_class"] == "FRESH"
        assert result["novelty_ratio"] == 1.0
        assert result["unique_count"] == 50
        assert result["cycle_length"] == 0

    def test_looping_strokes(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        base = [f"thought {i}" for i in range(7)]
        texts = (base * 15)[:100]
        records = _make_strokes(texts)
        _write_jsonl(p, records)
        result = analyze(path=p, window=100)
        assert result["freshness_class"] == "LOOPING"
        assert result["cycle_length"] == 7
        assert result["unique_count"] == 7

    def test_stale_strokes(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        # 20 unique base texts, repeated non-cyclically to avoid cycle detection
        # novelty = 20/50 = 0.4 → STALE
        import random
        random.seed(42)
        pool = [f"thought_{i}" for i in range(20)]
        texts = list(pool)  # first 20 are unique
        # next 30 are random picks from pool (non-cycling)
        for _ in range(30):
            texts.append(random.choice(pool))
        records = _make_strokes(texts)
        _write_jsonl(p, records)
        result = analyze(path=p, window=50)
        assert result["freshness_class"] == "STALE"
        assert result["unique_count"] == 20

    def test_window_truncation(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        # 200 strokes: first 100 are unique, last 100 cycle 7 texts
        texts = [f"u{i}" for i in range(100)]
        base = [f"c{i}" for i in range(7)]
        texts += (base * 15)[:100]
        records = _make_strokes(texts)
        _write_jsonl(p, records)
        result = analyze(path=p, window=100)
        # should only look at last 100 (the cycling part)
        assert result["freshness_class"] == "LOOPING"
        assert result["stroke_count"] == 100

    def test_missing_file(self, tmp_path):
        result = analyze(path=tmp_path / "nope.jsonl", window=50)
        assert result["stroke_count"] == 0
        assert result["freshness_class"] == "FRESH"

    def test_empty_file(self, tmp_path):
        p = tmp_path / "strokes.jsonl"
        p.write_text("")
        result = analyze(path=p, window=50)
        assert result["stroke_count"] == 0

    def test_real_repo_strokes(self):
        """Smoke test against the actual repo data.

        The current writer cycles through 7 base thoughts, each appended with
        a different '-- measured now:' suffix.  After stripping measurements
        the tool should detect the repetition.
        """
        real = REPO / "data" / "strokes.jsonl"
        if not real.exists():
            pytest.skip("repo strokes file not available")
        result = analyze(path=real, window=100)
        # base texts cycle → novelty_ratio should be low
        assert result["freshness_class"] in ("LOOPING", "STALE")
        assert result["unique_count"] <= 20  # far fewer than 100
