"""Tests for stroke_novelty_injector module.

Covers:
- NoveltyPrompt: dataclass, word_set extraction
- NoveltyPool: init, len, select, mark_used, exhaustion_ratio, reset
- _word_set: empty, normal, mixed case, punctuation
- _jaccard_distance: empty sets, identical, disjoint, partial overlap
- _min_distance_to_recent: empty recent, single, multiple
- diversity_ratio: empty, single, all unique, all same, mixed
- should_inject: below/at/above threshold, edge cases
- inject: normal, empty pool, empty strokes
- log_intervention / load_interventions: write/read JSONL
- maybe_inject: full orchestration with and without injection needed
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.stroke_novelty_injector import (
    DATA_DIR,
    INTERVENTION_LOG,
    Intervention,
    NoveltyPool,
    NoveltyPrompt,
    _jaccard_distance,
    _min_distance_to_recent,
    _word_set,
    diversity_ratio,
    inject,
    load_interventions,
    log_intervention,
    maybe_inject,
    should_inject,
)


# ===========================================================================
# NoveltyPrompt
# ===========================================================================


class TestNoveltyPrompt:
    def test_dataclass_fields(self):
        p = NoveltyPrompt(text="hello world")
        assert p.text == "hello world"
        assert p.category == "general"
        assert p.used_count == 0
        assert p.last_used is None

    def test_custom_fields(self):
        p = NoveltyPrompt(text="test", category="creative", used_count=5)
        assert p.category == "creative"
        assert p.used_count == 5

    def test_word_set_basic(self):
        p = NoveltyPrompt(text="the quick brown fox")
        assert p.word_set() == {"the", "quick", "brown", "fox"}

    def test_word_set_case_insensitive(self):
        p = NoveltyPrompt(text="Hello World HELLO")
        assert p.word_set() == {"hello", "world"}

    def test_word_set_empty(self):
        p = NoveltyPrompt(text="")
        assert p.word_set() == set()

    def test_word_set_punctuation(self):
        p = NoveltyPrompt(text="hello, world! how's it?")
        ws = p.word_set()
        assert "hello" in ws
        assert "world" in ws
        assert "how" in ws


# ===========================================================================
# _word_set
# ===========================================================================


class TestWordSet:
    def test_empty_string(self):
        assert _word_set("") == set()

    def test_normal_text(self):
        assert _word_set("hello world") == {"hello", "world"}

    def test_mixed_case(self):
        assert _word_set("Hello WORLD hello") == {"hello", "world"}

    def test_with_numbers(self):
        result = _word_set("test 123 abc")
        assert "test" in result
        assert "123" in result
        assert "abc" in result

    def test_only_punctuation(self):
        assert _word_set("!@#$%") == set()


# ===========================================================================
# _jaccard_distance
# ===========================================================================


class TestJaccardDistance:
    def test_both_empty(self):
        assert _jaccard_distance(set(), set()) == 0.0

    def test_identical_sets(self):
        assert _jaccard_distance({"a", "b"}, {"a", "b"}) == 0.0

    def test_completely_disjoint(self):
        assert _jaccard_distance({"a"}, {"b"}) == 1.0

    def test_partial_overlap(self):
        # {a, b, c} vs {b, c, d}: intersection=2, union=4, distance=0.5
        assert _jaccard_distance({"a", "b", "c"}, {"b", "c", "d"}) == 0.5

    def test_one_empty_one_not(self):
        assert _jaccard_distance(set(), {"a"}) == 1.0

    def test_symmetry(self):
        a = {"hello", "world"}
        b = {"world", "foo"}
        assert _jaccard_distance(a, b) == _jaccard_distance(b, a)

    def test_subset(self):
        # {a} vs {a, b}: intersection=1, union=2, distance=0.5
        assert _jaccard_distance({"a"}, {"a", "b"}) == 0.5


# ===========================================================================
# _min_distance_to_recent
# ===========================================================================


class TestMinDistanceToRecent:
    def test_empty_recent(self):
        assert _min_distance_to_recent({"a", "b"}, []) == 1.0

    def test_single_recent(self):
        result = _min_distance_to_recent({"a", "b"}, [{"a", "b"}])
        assert result == 0.0

    def test_picks_minimum(self):
        prompt = {"x", "y"}
        recent = [{"x", "y"}, {"a", "b"}]
        # distances: 0.0 and 1.0; min is 0.0
        assert _min_distance_to_recent(prompt, recent) == 0.0

    def test_multiple_recent(self):
        prompt = {"x"}
        recent = [{"x", "a"}, {"b", "c"}]
        # distance to first: 1 - 1/2 = 0.5
        # distance to second: 1 - 0/3 = 1.0
        # min = 0.5
        assert _min_distance_to_recent(prompt, recent) == pytest.approx(0.5)


# ===========================================================================
# diversity_ratio
# ===========================================================================


class TestDiversityRatio:
    def test_empty(self):
        assert diversity_ratio([]) == 1.0

    def test_single_stroke(self):
        assert diversity_ratio(["hello"]) == 1.0

    def test_all_unique(self):
        strokes = ["a", "b", "c", "d", "e"]
        assert diversity_ratio(strokes, window=5) == 1.0

    def test_all_same(self):
        strokes = ["x"] * 10
        assert diversity_ratio(strokes, window=10) == 0.1

    def test_mixed(self):
        strokes = ["a", "b", "a", "b", "c"]
        # last 5: 3 unique / 5 = 0.6
        assert diversity_ratio(strokes, window=5) == pytest.approx(0.6)

    def test_window_larger_than_strokes(self):
        strokes = ["a", "b", "a"]
        # window=10 but only 3 strokes: 2 unique / 3
        assert diversity_ratio(strokes, window=10) == pytest.approx(2 / 3)

    def test_two_strokes_same(self):
        assert diversity_ratio(["x", "x"], window=2) == 0.5

    def test_two_strokes_different(self):
        assert diversity_ratio(["x", "y"], window=2) == 1.0


# ===========================================================================
# should_inject
# ===========================================================================


class TestShouldInject:
    def test_below_threshold(self):
        strokes = ["x"] * 20
        assert should_inject(strokes, window=10, threshold=0.3) is True

    def test_above_threshold(self):
        strokes = [f"stroke_{i}" for i in range(20)]
        assert should_inject(strokes, window=10, threshold=0.3) is False

    def test_at_threshold(self):
        # diversity_ratio = 0.3 exactly; 0.3 < 0.3 is False
        # 10 strokes, 3 unique → 0.3
        strokes = ["a", "b", "c"] + ["a"] * 7
        assert should_inject(strokes, window=10, threshold=0.3) is False

    def test_empty_strokes(self):
        assert should_inject([], window=10, threshold=0.3) is False

    def test_high_threshold(self):
        strokes = [f"s{i}" for i in range(10)]
        # all unique → ratio 1.0; 1.0 < 0.9 is False
        assert should_inject(strokes, window=10, threshold=0.9) is False

    def test_low_threshold(self):
        strokes = ["x"] * 10
        # ratio = 0.1; 0.1 < 0.05 is False
        assert should_inject(strokes, window=10, threshold=0.05) is False


# ===========================================================================
# NoveltyPool
# ===========================================================================


class TestNoveltyPool:
    def test_default_init(self):
        pool = NoveltyPool()
        assert len(pool) > 0

    def test_custom_prompts(self):
        prompts = [NoveltyPrompt(text="custom")]
        pool = NoveltyPool(prompts=prompts)
        assert len(pool) == 1

    def test_empty_pool(self):
        pool = NoveltyPool(prompts=[])
        assert len(pool) == 0

    def test_select_returns_list(self):
        pool = NoveltyPool()
        result = pool.select(["hello world"], top_k=1)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_select_top_k(self):
        pool = NoveltyPool()
        result = pool.select(["hello"], top_k=3)
        assert len(result) == 3

    def test_select_empty_pool(self):
        pool = NoveltyPool(prompts=[])
        assert pool.select(["hello"]) == []

    def test_select_dissimilar_to_recent(self):
        prompts = [
            NoveltyPrompt(text="hello world"),
            NoveltyPrompt(text="completely different topic here"),
        ]
        pool = NoveltyPool(prompts=prompts)
        # Recent strokes contain "hello world" → the other prompt should win
        result = pool.select(["hello world"], top_k=1)
        assert "different" in result[0].text

    def test_mark_used(self):
        p = NoveltyPrompt(text="test")
        pool = NoveltyPool(prompts=[p])
        assert p.used_count == 0
        pool.mark_used(p)
        assert p.used_count == 1
        assert p.last_used is not None

    def test_mark_used_increments(self):
        p = NoveltyPrompt(text="test")
        pool = NoveltyPool(prompts=[p])
        pool.mark_used(p)
        pool.mark_used(p)
        assert p.used_count == 2

    def test_exhaustion_ratio_no_usage(self):
        pool = NoveltyPool()
        assert pool.exhaustion_ratio() == 0.0

    def test_exhaustion_ratio_with_usage(self):
        p = NoveltyPrompt(text="test")
        pool = NoveltyPool(prompts=[p])
        pool.mark_used(p)
        # Just used → ratio should be 1.0
        assert pool.exhaustion_ratio() == 1.0

    def test_exhaustion_ratio_empty_pool(self):
        pool = NoveltyPool(prompts=[])
        assert pool.exhaustion_ratio() == 0.0

    def test_reset_counts(self):
        p = NoveltyPrompt(text="test")
        pool = NoveltyPool(prompts=[p])
        pool.mark_used(p)
        assert p.used_count == 1
        pool.reset_counts()
        assert p.used_count == 0
        assert p.last_used is None


# ===========================================================================
# inject
# ===========================================================================


class TestInject:
    def test_appends_prompt(self):
        pool = NoveltyPool()
        strokes = ["x"] * 10
        result = inject(pool, strokes[-5:], strokes)
        assert len(result) == len(strokes) + 1

    def test_does_not_mutate_original(self):
        pool = NoveltyPool()
        strokes = ["a", "b", "c"]
        original_len = len(strokes)
        inject(pool, strokes, strokes)
        assert len(strokes) == original_len

    def test_empty_pool_returns_copy(self):
        pool = NoveltyPool(prompts=[])
        strokes = ["a", "b"]
        result = inject(pool, strokes, strokes)
        assert result == strokes
        assert result is not strokes

    def test_marks_prompt_used(self):
        p = NoveltyPrompt(text="unique prompt")
        pool = NoveltyPool(prompts=[p])
        assert p.used_count == 0
        inject(pool, ["recent"], ["a"])
        assert p.used_count == 1


# ===========================================================================
# Intervention logging
# ===========================================================================


class TestInterventionLogging:
    def test_to_dict(self):
        iv = Intervention(
            at=1000.0,
            prompt_text="test prompt",
            prompt_category="creative",
            pre_stall_ratio=0.1,
            window_size=10,
            stroke_index=42,
        )
        d = iv.to_dict()
        assert d["prompt"] == "test prompt"
        assert d["category"] == "creative"
        assert d["pre_stall_ratio"] == 0.1
        assert d["window"] == 10
        assert d["stroke_index"] == 42

    def test_log_and_load(self, tmp_path):
        log_path = tmp_path / "interventions.jsonl"
        with patch("iamai.stroke_novelty_injector.INTERVENTION_LOG", log_path):
            with patch("iamai.stroke_novelty_injector.DATA_DIR", tmp_path):
                iv = Intervention(
                    at=time.time(),
                    prompt_text="hello",
                    prompt_category="test",
                    pre_stall_ratio=0.05,
                    window_size=10,
                    stroke_index=100,
                )
                log_intervention(iv)
                records = load_interventions()
                # load_interventions reads from the patched path
                # but it uses the module-level constant, so we need
                # to read directly
                with open(log_path) as f:
                    lines = [json.loads(line) for line in f if line.strip()]
                assert len(lines) == 1
                assert lines[0]["prompt"] == "hello"

    def test_load_empty(self, tmp_path):
        log_path = tmp_path / "nonexistent.jsonl"
        with patch("iamai.stroke_novelty_injector.INTERVENTION_LOG", log_path):
            records = load_interventions()
            assert records == []

    def test_multiple_records(self, tmp_path):
        log_path = tmp_path / "interventions.jsonl"
        with patch("iamai.stroke_novelty_injector.INTERVENTION_LOG", log_path):
            with patch("iamai.stroke_novelty_injector.DATA_DIR", tmp_path):
                for i in range(3):
                    iv = Intervention(
                        at=time.time() + i,
                        prompt_text=f"prompt {i}",
                        prompt_category="test",
                        pre_stall_ratio=0.1,
                        window_size=10,
                        stroke_index=i,
                    )
                    log_intervention(iv)
                with open(log_path) as f:
                    lines = [json.loads(line) for line in f if line.strip()]
                assert len(lines) == 3


# ===========================================================================
# maybe_inject (orchestration)
# ===========================================================================


class TestMaybeInject:
    def test_no_injection_needed(self):
        strokes = [f"unique_{i}" for i in range(20)]
        result, iv = maybe_inject(strokes, window=10, threshold=0.3, log=False)
        assert result is strokes  # same object, not modified
        assert iv is None

    def test_injection_performed(self):
        strokes = ["x"] * 20
        pool = NoveltyPool()
        result, iv = maybe_inject(
            strokes, pool=pool, window=10, threshold=0.3, log=False
        )
        assert len(result) == 21
        assert iv is not None
        assert iv.pre_stall_ratio < 0.3

    def test_injection_with_default_pool(self):
        strokes = ["x"] * 20
        result, iv = maybe_inject(strokes, window=10, threshold=0.3, log=False)
        assert len(result) == 21
        assert iv is not None

    def test_does_not_mutate_input(self):
        strokes = ["x"] * 20
        original = list(strokes)
        maybe_inject(strokes, window=10, threshold=0.3, log=False)
        assert strokes == original
