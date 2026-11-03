"""Tests for iamai.stroke_diversity."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from iamai.stroke_diversity import (
    DiversityReport,
    DuplicatePair,
    diversity_score,
    find_duplicates,
    load_strokes,
    pair_similarity,
    strip_metric,
)


# -- strip_metric --

def test_strip_metric_removes_suffix():
    assert strip_metric("hello world -- measured now: 42 files") == "hello world"

def test_strip_metric_no_suffix():
    assert strip_metric("just a thought") == "just a thought"

def test_strip_metric_empty():
    assert strip_metric("") == ""

def test_strip_metric_multiline_measured():
    text = "a thought -- measured now: line1\nline2"
    assert strip_metric(text) == "a thought"


# -- pair_similarity --

def test_identical_texts():
    assert pair_similarity("hello world", "hello world") == 1.0

def test_completely_different():
    assert pair_similarity("hello world", "foo bar baz") == 0.0

def test_partial_overlap():
    sim = pair_similarity("the quick brown fox", "the quick red dog")
    # tokens: {the, quick, brown, fox} vs {the, quick, red, dog}
    # intersection=2, union=6 -> 2/6 ≈ 0.333
    assert abs(sim - 2 / 6) < 0.01

def test_empty_both():
    assert pair_similarity("", "") == 1.0

def test_one_empty():
    assert pair_similarity("hello", "") == 0.0

def test_metric_stripped_before_comparison():
    a = "hello world -- measured now: 10 files"
    b = "hello world -- measured now: 20 files"
    # After stripping, both are "hello world"
    assert pair_similarity(a, b) == 1.0

def test_case_insensitive():
    assert pair_similarity("Hello World", "hello world") == 1.0


# -- diversity_score --

def test_diversity_all_unique():
    # Use highly distinct texts — each with a unique long random-ish word
    import hashlib
    strokes = [
        {"seq": i, "text": hashlib.sha256(str(i).encode()).hexdigest()[:24]}
        for i in range(50)
    ]
    report = diversity_score(strokes, window=50)
    assert report.health == "healthy"
    assert report.diversity > 0.7
    assert report.total == 50

def test_diversity_all_identical():
    strokes = [{"seq": i, "text": "same thought repeated every single time"} for i in range(50)]
    report = diversity_score(strokes, window=50)
    assert report.health == "looping"
    assert report.diversity < 0.4
    assert report.total == 50

def test_diversity_empty():
    report = diversity_score([], window=50)
    assert report.total == 0
    assert report.diversity == 1.0

def test_diversity_window_larger_than_data():
    strokes = [{"seq": i, "text": f"thought {i}"} for i in range(5)]
    report = diversity_score(strokes, window=50)
    assert report.total == 5

def test_diversity_report_summary():
    report = DiversityReport(
        total=50, unique_bodies=45, diversity=0.85, mean_similarity=0.15
    )
    s = report.summary()
    assert "0.85" in s
    assert "healthy" in s

def test_diversity_health_levels():
    assert DiversityReport(total=1, unique_bodies=1, diversity=0.8, mean_similarity=0.2).health == "healthy"
    assert DiversityReport(total=1, unique_bodies=1, diversity=0.5, mean_similarity=0.5).health == "repetitive"
    assert DiversityReport(total=1, unique_bodies=1, diversity=0.2, mean_similarity=0.8).health == "looping"

def test_diversity_mixed_content():
    strokes = []
    for i in range(50):
        if i % 3 == 0:
            text = "deleting a file is progress too, eventually"
        elif i % 3 == 1:
            text = f"naming is hard because a bad name is cheap to type {i}"
        else:
            text = f"completely original thought about number {i} and its square {i*i}"
        strokes.append({"seq": i, "text": text})
    report = diversity_score(strokes, window=50)
    assert report.total == 50
    assert report.unique_bodies < 50  # some are repeated
    assert report.diversity > 0.0


# -- find_duplicates --

def test_find_duplicates_detects_pairs():
    strokes = [
        {"seq": 1, "text": "the quick brown fox jumps over"},
        {"seq": 2, "text": "something entirely different here"},
        {"seq": 3, "text": "the quick brown fox leaps over"},
    ]
    dupes = find_duplicates(strokes, threshold=0.5)
    assert len(dupes) >= 1
    assert dupes[0].seq_a == 1
    assert dupes[0].seq_b == 3

def test_find_duplicates_no_matches():
    strokes = [
        {"seq": 1, "text": "alpha bravo charlie"},
        {"seq": 2, "text": "delta echo foxtrot"},
        {"seq": 3, "text": "golf hotel india"},
    ]
    dupes = find_duplicates(strokes, threshold=0.5)
    assert len(dupes) == 0

def test_find_duplicates_respects_threshold():
    strokes = [
        {"seq": 1, "text": "the quick brown fox"},
        {"seq": 2, "text": "the quick brown cat"},
    ]
    # sim should be ~0.6 (3/5 intersection over union)
    low = find_duplicates(strokes, threshold=0.5)
    high = find_duplicates(strokes, threshold=0.9)
    assert len(low) >= len(high)

def test_find_duplicates_limit_window():
    strokes = [{"seq": i, "text": "repeated text"} for i in range(1000)]
    dupes = find_duplicates(strokes, threshold=0.5, limit=10)
    # With limit=10, only last 10 strokes considered -> C(10,2) = 45 pairs max
    assert all(d.seq_a >= 990 for d in dupes)


# -- load_strokes --

def test_load_strokes_from_file(tmp_path):
    f = tmp_path / "test_strokes.jsonl"
    lines = [
        json.dumps({"seq": 1, "text": "hello", "kind": "thought", "at": "2026-01-01T00:00:00+00:00"}),
        json.dumps({"seq": 2, "text": "world", "kind": "thought", "at": "2026-01-01T00:01:00+00:00"}),
    ]
    f.write_text("\n".join(lines))
    result = load_strokes(f, tail=10)
    assert len(result) == 2
    assert result[0]["seq"] == 1

def test_load_strokes_tail_limit(tmp_path):
    f = tmp_path / "test_strokes.jsonl"
    lines = [json.dumps({"seq": i, "text": f"t{i}"}) for i in range(100)]
    f.write_text("\n".join(lines))
    result = load_strokes(f, tail=10)
    assert len(result) == 10
    assert result[0]["seq"] == 90

def test_load_strokes_missing_file(tmp_path):
    result = load_strokes(tmp_path / "nonexistent.jsonl")
    assert result == []

def test_load_strokes_malformed_lines(tmp_path):
    f = tmp_path / "test_strokes.jsonl"
    f.write_text('{"seq":1,"text":"ok"}\nnot json\n{"seq":2,"text":"fine"}\n')
    result = load_strokes(f, tail=10)
    assert len(result) == 2
