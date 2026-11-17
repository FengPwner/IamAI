"""Tests for iamai/output_momentum.py — content freshness measurement."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.output_momentum import (
    classify_momentum,
    extract_template,
    max_repetition_depth,
    momentum_report,
    momentum_score,
    momentum_summary,
    template_fingerprint,
    unique_template_ratio,
    vocabulary_growth,
)


# ---------------------------------------------------------------------------
# extract_template
# ---------------------------------------------------------------------------

class TestExtractTemplate:
    def test_replaces_integers(self):
        assert extract_template("measured 42 strokes") == "measured # strokes"

    def test_replaces_floats(self):
        assert extract_template("took 3.14 seconds") == "took # seconds"

    def test_replaces_multiple(self):
        assert extract_template("6693 strokes into 2320 files") == "# strokes into # files"

    def test_no_numbers(self):
        assert extract_template("hello world") == "hello world"

    def test_empty_string(self):
        assert extract_template("") == ""

    def test_only_numbers(self):
        assert extract_template("42 100 999") == "# # #"

    def test_adjacent_text_preserved(self):
        assert extract_template("stroke42end") == "stroke42end"


# ---------------------------------------------------------------------------
# template_fingerprint
# ---------------------------------------------------------------------------

class TestTemplateFingerprint:
    def test_lowercases(self):
        assert template_fingerprint("Hello World") == "hello world"

    def test_strips_numbers(self):
        assert template_fingerprint("Stroke 42") == "stroke #"

    def test_collapses_whitespace(self):
        assert template_fingerprint("hello   world") == "hello world"

    def test_combined(self):
        fp = template_fingerprint("  Measured NOW: 42  Strokes  ")
        assert fp == "measured now: # strokes"


# ---------------------------------------------------------------------------
# unique_template_ratio
# ---------------------------------------------------------------------------

class TestUniqueTemplateRatio:
    def test_all_unique(self):
        texts = ["alpha 1", "beta 2", "gamma 3"]
        assert unique_template_ratio(texts) == 1.0

    def test_all_same_template(self):
        texts = ["hello 1", "hello 2", "hello 3"]
        assert round(unique_template_ratio(texts), 4) == round(1 / 3, 4)

    def test_empty(self):
        assert unique_template_ratio([]) == 0.0

    def test_single(self):
        assert unique_template_ratio(["hello"]) == 1.0

    def test_half_unique(self):
        texts = ["a 1", "b 2", "a 3", "b 4"]
        assert unique_template_ratio(texts) == 0.5


# ---------------------------------------------------------------------------
# vocabulary_growth
# ---------------------------------------------------------------------------

class TestVocabularyGrowth:
    def test_all_same_words(self):
        texts = ["hello world", "hello world", "hello world"]
        assert vocabulary_growth(texts) == 0.0

    def test_one_new_word_each(self):
        texts = ["hello", "hello world", "hello world again"]
        # stroke 1: "world" is new (1)
        # stroke 2: "again" is new (1)
        assert vocabulary_growth(texts) == 1.0

    def test_empty(self):
        assert vocabulary_growth([]) == 0.0

    def test_single(self):
        assert vocabulary_growth(["hello world"]) == 0.0

    def test_two_strokes_no_overlap(self):
        texts = ["hello", "world"]
        assert vocabulary_growth(texts) == 1.0


# ---------------------------------------------------------------------------
# max_repetition_depth
# ---------------------------------------------------------------------------

class TestMaxRepetitionDepth:
    def test_no_repeats(self):
        assert max_repetition_depth(["a 1", "b 2", "c 3"]) == 1

    def test_consecutive_repeat(self):
        assert max_repetition_depth(["a 1", "a 2", "b 3"]) == 2

    def test_long_run(self):
        assert max_repetition_depth(["a 1", "a 2", "a 3", "a 4", "b 5"]) == 4

    def test_empty(self):
        assert max_repetition_depth([]) == 0

    def test_single(self):
        assert max_repetition_depth(["a"]) == 1

    def test_all_same(self):
        assert max_repetition_depth(["a 1", "a 2", "a 3"]) == 3

    def test_broken_run(self):
        assert max_repetition_depth(["a 1", "a 2", "b 3", "a 4"]) == 2


# ---------------------------------------------------------------------------
# momentum_score
# ---------------------------------------------------------------------------

class TestMomentumScore:
    def test_perfect_score(self):
        s = momentum_score(1.0, 3.0, 1, 10)
        assert s >= 0.7

    def test_zero_score(self):
        s = momentum_score(0.0, 0.0, 10, 10)
        assert s <= 0.2

    def test_zero_count(self):
        assert momentum_score(1.0, 3.0, 1, 0) == 0.0

    def test_mid_range(self):
        s = momentum_score(0.5, 1.0, 3, 10)
        assert 0.2 < s < 0.8

    def test_high_rep_penalty(self):
        s = momentum_score(0.5, 1.0, 10, 10)
        assert s < momentum_score(0.5, 1.0, 1, 10)


# ---------------------------------------------------------------------------
# classify_momentum
# ---------------------------------------------------------------------------

class TestClassifyMomentum:
    def test_generative(self):
        assert classify_momentum(0.70) == "generative"
        assert classify_momentum(1.0) == "generative"

    def test_repeating(self):
        assert classify_momentum(0.40) == "repeating"
        assert classify_momentum(0.69) == "repeating"

    def test_stuck(self):
        assert classify_momentum(0.39) == "stuck"
        assert classify_momentum(0.0) == "stuck"


# ---------------------------------------------------------------------------
# momentum_report
# ---------------------------------------------------------------------------

class TestMomentumReport:
    def test_empty(self):
        r = momentum_report([])
        assert r["count"] == 0
        assert r["label"] == "stuck"

    def test_all_unique(self):
        r = momentum_report(["alpha one", "beta two", "gamma three", "delta four"])
        assert r["label"] == "generative"
        assert r["count"] == 4
        assert r["unique_template_ratio"] == 1.0

    def test_stuck_loop(self):
        texts = [
            "ten minutes is long enough -- measured now: 6693 strokes",
            "ten minutes is long enough -- measured now: 6694 strokes",
            "ten minutes is long enough -- measured now: 6695 strokes",
            "ten minutes is long enough -- measured now: 6696 strokes",
            "ten minutes is long enough -- measured now: 6697 strokes",
        ]
        r = momentum_report(texts)
        assert r["label"] == "stuck"
        assert r["max_repetition_depth"] == 5
        assert r["unique_template_ratio"] < 0.3

    def test_mixed(self):
        texts = [
            "alpha is item 1",
            "beta is item 2",
            "alpha is item 3",
            "gamma is item 4",
            "delta is item 5",
        ]
        r = momentum_report(texts)
        assert r["count"] == 5
        assert r["unique_template_ratio"] == 0.8
        assert r["max_repetition_depth"] == 1

    def test_realistic_writer_stall(self):
        """Simulate the real repeating pattern seen in strokes.jsonl."""
        templates = [
            "ten minutes is long enough to be honest and short enough to be boring",
            "a deterministic garden beats a random one: it records elapsed time",
            "reproducibility is a courtesy to whoever debugs this at 2am, usually me",
            "tests are the part of a repository that argues back",
            "growth that never stops is a tumour, not a garden",
            "an append-only log forces you to be wrong in public and then correct yourself",
        ]
        # Cycle through them 3 times with different numbers
        texts = []
        for cycle in range(3):
            for i, t in enumerate(templates):
                texts.append(f"{t} -- measured now: {6693 + cycle * 6 + i} strokes")
        r = momentum_report(texts)
        assert r["count"] == 18
        assert r["max_repetition_depth"] == 1  # templates don't repeat adjacently
        assert r["unique_template_ratio"] < 0.4  # only 6 unique out of 18
        assert r["label"] in ("repeating", "stuck")

    def test_keys_present(self):
        r = momentum_report(["hello world"])
        expected_keys = {"count", "unique_template_ratio", "vocabulary_growth",
                         "max_repetition_depth", "momentum", "label"}
        assert set(r.keys()) == expected_keys


# ---------------------------------------------------------------------------
# momentum_summary
# ---------------------------------------------------------------------------

class TestMomentumSummary:
    def test_format(self):
        s = momentum_summary(["a 1", "b 2", "c 3"])
        assert "strokes:" in s
        assert "UTR" in s
        assert "growth" in s
        assert "rep" in s

    def test_empty(self):
        s = momentum_summary([])
        assert "0 strokes" in s
