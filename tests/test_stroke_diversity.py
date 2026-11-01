"""Tests for iamai.stroke_diversity — stroke diversity analyzer."""

import json
import math
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.stroke_diversity import (
    DiversityReport,
    _shannon_entropy,
    _detect_repetition_loop,
    _normalize_text,
    _compute_diversity_score,
    _verdict,
    analyze_diversity,
    format_report,
)


# ---------------------------------------------------------------------------
# DiversityReport data class
# ---------------------------------------------------------------------------


class TestDiversityReport:
    def test_defaults(self):
        r = DiversityReport()
        assert r.total_strokes == 0
        assert r.kind_counts == {}
        assert r.kind_entropy == 0.0
        assert r.unique_ratio == 0.0
        assert r.repetition_loop is False
        assert r.loop_text is None
        assert r.diversity_score == 0.0
        assert r.verdict == "healthy"

    def test_custom_values(self):
        r = DiversityReport(
            total_strokes=100,
            kind_counts={"thought": 90, "note": 10},
            kind_entropy=0.469,
            unique_ratio=0.85,
            repetition_loop=False,
            loop_text=None,
            diversity_score=0.72,
            verdict="healthy",
        )
        assert r.total_strokes == 100
        assert r.kind_counts["thought"] == 90
        assert r.verdict == "healthy"

    def test_frozen(self):
        r = DiversityReport()
        with pytest.raises(AttributeError):
            r.total_strokes = 10

    def test_stuck_loop_report(self):
        r = DiversityReport(
            total_strokes=50,
            repetition_loop=True,
            loop_text="parse_kv.py is already in the pool",
            diversity_score=0.12,
            verdict="stuck_loop",
        )
        assert r.repetition_loop is True
        assert "parse_kv" in r.loop_text
        assert r.verdict == "stuck_loop"


# ---------------------------------------------------------------------------
# Shannon entropy
# ---------------------------------------------------------------------------


class TestShannonEntropy:
    def test_empty(self):
        assert _shannon_entropy({}) == 0.0

    def test_single_item(self):
        # Only one kind → entropy = 0
        assert _shannon_entropy({"thought": 100}) == 0.0

    def test_uniform_binary(self):
        # 50/50 → entropy = 1.0 bit
        e = _shannon_entropy({"a": 50, "b": 50})
        assert abs(e - 1.0) < 0.001

    def test_uniform_four(self):
        # 4 equal kinds → entropy = 2.0 bits
        e = _shannon_entropy({"a": 25, "b": 25, "c": 25, "d": 25})
        assert abs(e - 2.0) < 0.001

    def test_skewed(self):
        # Heavily skewed → low entropy
        e = _shannon_entropy({"a": 97, "b": 1, "c": 1, "d": 1})
        assert e < 1.0

    def test_all_zeros(self):
        # Edge case: counts sum to zero shouldn't happen but handle gracefully
        assert _shannon_entropy({"a": 0, "b": 0}) == 0.0


# ---------------------------------------------------------------------------
# Repetition detection
# ---------------------------------------------------------------------------


class TestDetectRepetitionLoop:
    def test_no_repetition(self):
        texts = ["a", "b", "c", "d", "e"]
        assert _detect_repetition_loop(texts) is None

    def test_simple_loop(self):
        texts = ["a", "b", "x", "x", "x", "c"]
        result = _detect_repetition_loop(texts)
        assert result == "x"

    def test_loop_at_end(self):
        texts = ["a", "b", "c", "x", "x", "x"]
        result = _detect_repetition_loop(texts)
        assert result == "x"

    def test_loop_at_start(self):
        texts = ["x", "x", "x", "a", "b", "c"]
        result = _detect_repetition_loop(texts)
        assert result == "x"

    def test_two_repeats_not_enough(self):
        texts = ["a", "b", "b", "c", "d"]
        assert _detect_repetition_loop(texts, min_repeats=3) is None

    def test_custom_min_repeats(self):
        texts = ["a", "b", "b", "b", "b", "c"]
        assert _detect_repetition_loop(texts, min_repeats=4) == "b"

    def test_empty_list(self):
        assert _detect_repetition_loop([]) is None

    def test_short_list(self):
        assert _detect_repetition_loop(["a"]) is None
        assert _detect_repetition_loop(["a", "a"]) is None

    def test_all_same(self):
        texts = ["x"] * 10
        assert _detect_repetition_loop(texts) == "x"

    def test_alternating_no_loop(self):
        texts = ["a", "b"] * 10
        assert _detect_repetition_loop(texts) is None


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------


class TestNormalizeText:
    def test_replaces_numbers(self):
        assert _normalize_text("stroke 12345 done") == "stroke # done"

    def test_collapses_whitespace(self):
        assert _normalize_text("hello   world") == "hello world"

    def test_strips_edges(self):
        assert _normalize_text("  hello  ") == "hello"

    def test_preserves_structure(self):
        t1 = "parse_kv.py is already in the pool of 9 modules"
        t2 = "parse_kv.py is already in the pool of 12 modules"
        assert _normalize_text(t1) == _normalize_text(t2)

    def test_different_templates_differ(self):
        t1 = "parse_kv.py is already in the pool of 9 modules"
        t2 = "retry.py is already in the pool of 9 modules"
        # Different module names → different normalized text
        assert _normalize_text(t1) != _normalize_text(t2)


# ---------------------------------------------------------------------------
# Diversity score
# ---------------------------------------------------------------------------


class TestComputeDiversityScore:
    def test_perfect_diversity(self):
        # 2 kinds, max entropy, all unique, no repetition
        score = _compute_diversity_score(1.0, 2, 1.0, False)
        # 0.4*1.0 + 0.4*1.0 + 0.2*1.0 = 1.0
        assert score == 1.0

    def test_no_diversity(self):
        # 1 kind, 0 entropy, 0 unique, repetition
        score = _compute_diversity_score(0.0, 1, 0.0, True)
        assert score == 0.0

    def test_low_diversity_with_repetition(self):
        score = _compute_diversity_score(0.3, 3, 0.4, True)
        # entropy_score = 0.3/log2(3) ≈ 0.189
        # 0.4*0.189 + 0.4*0.4 + 0.2*0.0 ≈ 0.076 + 0.16 + 0.0 = 0.236
        assert abs(score - 0.236) < 0.02

    def test_single_kind(self):
        score = _compute_diversity_score(0.0, 1, 0.5, False)
        # 0.4*0.0 + 0.4*0.5 + 0.2*1.0 = 0.0 + 0.2 + 0.2 = 0.4
        assert abs(score - 0.4) < 0.01

    def test_high_diversity_no_repetition(self):
        score = _compute_diversity_score(2.5, 7, 0.95, False)
        # entropy_score = min(2.5/log2(7), 1.0) ≈ min(0.886, 1.0) = 0.886
        # 0.4*0.886 + 0.4*0.95 + 0.2*1.0 ≈ 0.354 + 0.38 + 0.2 = 0.934
        assert score > 0.9


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


class TestVerdict:
    def test_healthy(self):
        assert _verdict(0.8, False) == "healthy"

    def test_healthy_boundary(self):
        assert _verdict(0.5, False) == "healthy"

    def test_low_diversity(self):
        assert _verdict(0.3, False) == "low_diversity"

    def test_low_diversity_boundary(self):
        assert _verdict(0.499, False) == "low_diversity"

    def test_stuck_loop_overrides_score(self):
        # Even with high score, repetition → stuck_loop
        assert _verdict(0.9, True) == "stuck_loop"

    def test_zero_score_no_repetition(self):
        assert _verdict(0.0, False) == "low_diversity"

    def test_zero_score_with_repetition(self):
        assert _verdict(0.0, True) == "stuck_loop"


# ---------------------------------------------------------------------------
# analyze_diversity (integration)
# ---------------------------------------------------------------------------


class TestAnalyzeDiversity:
    def test_missing_log(self, tmp_path):
        report = analyze_diversity(stroke_log=tmp_path / "nonexistent.jsonl")
        assert report.verdict == "healthy"
        assert report.total_strokes == 0

    def test_empty_log(self, tmp_path):
        log = tmp_path / "empty.jsonl"
        log.write_text("")
        report = analyze_diversity(stroke_log=log)
        assert report.verdict == "healthy"
        assert report.total_strokes == 0

    def test_diverse_strokes(self, tmp_path):
        log = tmp_path / "strokes.jsonl"
        lines = []
        kinds = ["thought", "note", "devlog", "snippet", "garden", "metrics"]
        templates = [
            "refactoring the cache layer for better throughput",
            "tests caught a regression in the commit parser",
            "deployed a hotfix for the ssh key rotation bug",
            "noted that the batch window drifts under load",
            "measured entropy across the last hundred strokes",
            "wrote a snippet demonstrating the retry backoff",
            "the cadence monitor flagged a gap in the log",
            "reviewed the caretaker visit history for patterns",
            "added a new module for push divergence detection",
            "documented the reclamation recovery procedure",
            "analyzed stroke pool diversity across time windows",
            "benchmarked the commit batch collector latency",
            "traced a silent failure in the push retry chain",
            "catalogued the restart inertia after container kill",
            "measured the backlog drain rate under steady state",
            "compared the cadence drift before and after restart",
            "explored the correlation between visit frequency and health",
            "profiled the writer loop CPU usage during idle",
            "summarized the push rejection recovery patterns",
            "designed a liveness probe for the batch committer",
        ]
        for i in range(100):
            kind = kinds[i % len(kinds)]
            text = templates[i % len(templates)]
            lines.append(json.dumps({
                "seq": i,
                "kind": kind,
                "text": text,
            }))
        log.write_text("\n".join(lines) + "\n")
        report = analyze_diversity(stroke_log=log, window=100)
        assert report.total_strokes == 100
        assert len(report.kind_counts) == 6
        assert report.kind_entropy > 2.0  # 6 kinds ≈ 2.58 bits max
        assert report.unique_ratio > 0.1  # 20 unique / 100 = 0.2
        assert report.repetition_loop is False
        # 20 unique texts cycling → ratio ≈ 0.2; high entropy saves the score
        assert report.unique_ratio < 0.3
        assert report.diversity_score > 0.4

    def test_stuck_loop_strokes(self, tmp_path):
        log = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(50):
            lines.append(json.dumps({
                "seq": i,
                "kind": "thought",
                "text": "parse_kv.py is already in the pool of 9 modules, nothing new to add there",
            }))
        log.write_text("\n".join(lines) + "\n")
        report = analyze_diversity(stroke_log=log, window=50)
        assert report.total_strokes == 50
        assert report.kind_counts == {"thought": 50}
        assert report.repetition_loop is True
        assert report.verdict == "stuck_loop"
        assert "parse_kv" in report.loop_text

    def test_window_truncation(self, tmp_path):
        log = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(500):
            lines.append(json.dumps({
                "seq": i,
                "kind": "thought",
                "text": f"text {i}",
            }))
        log.write_text("\n".join(lines) + "\n")
        report = analyze_diversity(stroke_log=log, window=100)
        assert report.total_strokes == 100

    def test_single_kind_high_uniqueness(self, tmp_path):
        log = tmp_path / "strokes.jsonl"
        # Use structurally distinct templates (not just different numbers)
        templates = [
            "refactoring the cache layer for throughput",
            "tests caught a regression in the parser",
            "deployed a hotfix for the key rotation",
            "noted that the batch window drifts",
            "measured entropy across recent strokes",
            "wrote a snippet for the retry backoff",
            "the cadence monitor flagged a gap",
            "reviewed visit history for patterns",
            "added a module for push divergence",
            "documented the recovery procedure",
        ]
        lines = []
        for i in range(50):
            lines.append(json.dumps({
                "seq": i,
                "kind": "thought",
                "text": templates[i % len(templates)],
            }))
        log.write_text("\n".join(lines) + "\n")
        report = analyze_diversity(stroke_log=log, window=50)
        assert len(report.kind_counts) == 1
        assert report.kind_entropy == 0.0
        # 10 unique texts cycling → unique_ratio = 0.2
        # Score = 0.4*0 + 0.4*0.2 + 0.2*1.0 = 0.28 (no loop since texts alternate)
        assert report.repetition_loop is False
        assert report.diversity_score > 0.2

    def test_mixed_diversity(self, tmp_path):
        log = tmp_path / "strokes.jsonl"
        lines = []
        for i in range(100):
            if i < 95:
                kind = "thought"
            else:
                kind = "note"
            lines.append(json.dumps({
                "seq": i,
                "kind": kind,
                "text": f"content {i}",
            }))
        log.write_text("\n".join(lines) + "\n")
        report = analyze_diversity(stroke_log=log, window=100)
        assert report.kind_counts.get("thought", 0) == 95
        assert report.kind_counts.get("note", 0) == 5
        # Highly skewed → low entropy
        assert report.kind_entropy < 1.0


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


class TestFormatReport:
    def test_healthy_format(self):
        r = DiversityReport(
            total_strokes=100,
            kind_counts={"thought": 90, "note": 10},
            kind_entropy=0.469,
            unique_ratio=0.85,
            diversity_score=0.72,
            verdict="healthy",
        )
        out = format_report(r)
        assert "healthy" in out
        assert "100 strokes" in out
        assert "2 kinds" in out
        assert "0.47 bits" in out
        assert "85%" in out

    def test_stuck_loop_format(self):
        r = DiversityReport(
            total_strokes=50,
            kind_counts={"thought": 50},
            kind_entropy=0.0,
            unique_ratio=0.02,
            repetition_loop=True,
            loop_text="parse_kv.py is already in the pool of 9 modules",
            diversity_score=0.008,
            verdict="stuck_loop",
        )
        out = format_report(r)
        assert "stuck_loop" in out
        assert "LOOP:" in out
        assert "parse_kv" in out

    def test_long_loop_text_truncated(self):
        r = DiversityReport(
            repetition_loop=True,
            loop_text="x" * 100,
            verdict="stuck_loop",
        )
        out = format_report(r)
        assert "…" in out

    def test_empty_report(self):
        r = DiversityReport()
        out = format_report(r)
        assert "healthy" in out
        assert "0 strokes" in out
