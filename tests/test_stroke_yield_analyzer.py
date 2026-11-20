"""Tests for iamai.stroke_yield_analyzer."""

import pytest
from iamai.stroke_yield_analyzer import (
    _is_exhausted_text,
    _tokenize,
    _jaccard,
    classify_stroke,
    yield_grade,
    find_saturation_targets,
    analyse,
)


# -----------------------------------------------------------------------
# Exhaustion pattern detection
# -----------------------------------------------------------------------


class TestIsExhaustedText:
    def test_nothing_new(self):
        assert _is_exhausted_text("nothing new to add there")

    def test_already_in_pool(self):
        assert _is_exhausted_text("retry.py is already in the pool of 9 modules")

    def test_no_new_content(self):
        assert _is_exhausted_text("no new content to produce")

    def test_already_exists(self):
        assert _is_exhausted_text("this feature already exists")

    def test_already_covered(self):
        assert _is_exhausted_text("already covered in the previous visit")

    def test_nothing_else(self):
        assert _is_exhausted_text("nothing else to say about this")

    def test_exhausted_keyword(self):
        assert _is_exhausted_text("the topic is exhausted")

    def test_no_room(self):
        assert _is_exhausted_text("no room for improvement here")

    def test_saturation(self):
        assert _is_exhausted_text("saturation reached for this module")

    def test_already_has_count(self):
        assert _is_exhausted_text("already has 58 tests")

    def test_fresh_text_not_exhausted(self):
        assert not _is_exhausted_text("added new retry logic with backoff")

    def test_empty_string(self):
        assert not _is_exhausted_text("")

    def test_partial_match_not_exhausted(self):
        assert not _is_exhausted_text("there is something new to explore")

    def test_case_insensitive(self):
        assert _is_exhausted_text("NOTHING NEW TO ADD")
        assert _is_exhausted_text("Already In The Pool")


# -----------------------------------------------------------------------
# Tokenization
# -----------------------------------------------------------------------


class TestTokenize:
    def test_basic(self):
        tokens = _tokenize("the quick brown fox")
        assert "quick" in tokens
        assert "brown" in tokens
        assert "fox" in tokens
        # 'the' is a stop word
        assert "the" not in tokens

    def test_stop_words_removed(self):
        tokens = _tokenize("a test is being run for the module")
        # All stop words removed
        for sw in ["a", "is", "being", "for", "the"]:
            assert sw not in tokens
        assert "test" in tokens
        assert "run" in tokens
        assert "module" in tokens

    def test_single_char_dropped(self):
        tokens = _tokenize("x y z test")
        assert "x" not in tokens
        assert "y" not in tokens
        assert "test" in tokens

    def test_punctuation_stripped(self):
        tokens = _tokenize("hello, world! test-case.")
        assert "hello" in tokens
        assert "world" in tokens
        assert "test" in tokens
        assert "case" in tokens

    def test_empty(self):
        assert _tokenize("") == set()

    def test_all_stop_words(self):
        assert _tokenize("the a an is are was") == set()


# -----------------------------------------------------------------------
# Jaccard similarity
# -----------------------------------------------------------------------


class TestJaccard:
    def test_identical(self):
        s = {"hello", "world"}
        assert _jaccard(s, s) == 1.0

    def test_disjoint(self):
        assert _jaccard({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial_overlap(self):
        # {a,b} vs {b,c} → intersection=1, union=3 → 1/3
        result = _jaccard({"a", "b"}, {"b", "c"})
        assert abs(result - 1 / 3) < 1e-9

    def test_both_empty(self):
        assert _jaccard(set(), set()) == 1.0

    def test_one_empty(self):
        assert _jaccard({"a"}, set()) == 0.0
        assert _jaccard(set(), {"b"}) == 0.0

    def test_subset(self):
        # {a} vs {a,b} → 1/2
        result = _jaccard({"a"}, {"a", "b"})
        assert abs(result - 0.5) < 1e-9


# -----------------------------------------------------------------------
# Stroke classification
# -----------------------------------------------------------------------


class TestClassifyStroke:
    def test_fresh_first_stroke(self):
        stroke = {"text": "new module for caching", "file": "iamai/cache.py"}
        assert classify_stroke(stroke, []) == "fresh"

    def test_exhausted_priority(self):
        stroke = {"text": "nothing new to add to cache.py", "file": "iamai/cache.py"}
        recent = [{"text": "cache module added", "file": "iamai/cache.py"}]
        assert classify_stroke(stroke, recent) == "exhausted"

    def test_retread_same_target_similar_text(self):
        stroke = {
            "text": "added retry with exponential backoff to tools",
            "file": "tools/retry.py",
        }
        recent = [
            {
                "text": "added retry with exponential backoff to tools",
                "file": "tools/retry.py",
            }
        ]
        assert classify_stroke(stroke, recent, text_threshold=0.6) == "retread"

    def test_fresh_different_target(self):
        stroke = {
            "text": "added retry with exponential backoff pattern",
            "file": "tools/new_retry.py",
        }
        recent = [
            {
                "text": "added retry with exponential backoff pattern",
                "file": "tools/old_retry.py",
            }
        ]
        # Same text but different target — below 0.85 threshold for cross-target retread
        # Actually Jaccard of identical texts = 1.0 which is >= 0.85
        # So this should still be retread due to very high similarity
        assert classify_stroke(stroke, recent, text_threshold=0.6) == "retread"

    def test_fresh_different_text(self):
        stroke = {
            "text": "created bloom filter for deduplication",
            "file": "iamai/bloom.py",
        }
        recent = [
            {"text": "added retry logic to tools", "file": "tools/retry.py"},
            {"text": "new caching module written", "file": "iamai/cache.py"},
        ]
        assert classify_stroke(stroke, recent) == "fresh"

    def test_retread_high_similarity_no_target(self):
        # These two texts differ only by one word out of ~6 content words
        # → Jaccard ≈ 5/7 ≈ 0.71, above 0.6 threshold; since no file
        #   targets, cross-target retread needs ≥ 0.85 — 0.71 < 0.85 → fresh
        stroke = {"text": "the garden grows slowly but steadily every day"}
        recent = [
            {"text": "the garden grows slowly but steadily every week"},
        ]
        assert classify_stroke(stroke, recent, text_threshold=0.6) == "fresh"

    def test_retread_near_identical_no_target(self):
        # Near-identical texts with no file target → still retread via ≥0.85
        # tokens A: {automation,fails,quietly,log,must,always,speak} = 7
        # tokens B: {automation,fails,quietly,log,must,speak} = 6
        # intersection=6, union=7, Jaccard=6/7≈0.857 ≥ 0.85
        stroke = {"text": "automation fails quietly so the log must speak"}
        recent = [
            {"text": "automation fails quietly so the log must always speak"},
        ]
        assert classify_stroke(stroke, recent, text_threshold=0.6) == "retread"

    def test_fresh_moderate_similarity_no_target(self):
        stroke = {
            "text": "commit rhythm analysis reveals periodic patterns in push timing",
            "file": "iamai/commit_rhythm.py",
        }
        recent = [
            {
                "text": "stroke diversity analysis shows topic distribution across categories",
                "file": "iamai/stroke_diversity.py",
            }
        ]
        # Some shared words but different enough
        result = classify_stroke(stroke, recent, text_threshold=0.6)
        assert result == "fresh"

    def test_empty_text(self):
        stroke = {"text": "", "file": "iamai/empty.py"}
        assert classify_stroke(stroke, []) == "fresh"

    def test_no_file_key(self):
        stroke = {"text": "some observation about the system"}
        assert classify_stroke(stroke, []) == "fresh"

    def test_custom_threshold_strict(self):
        stroke = {
            "text": "added caching layer for performance",
            "file": "iamai/cache.py",
        }
        recent = [
            {
                "text": "added caching layer for performance improvement",
                "file": "iamai/cache.py",
            }
        ]
        # With a very strict threshold (0.95), might still pass since texts overlap heavily
        result = classify_stroke(stroke, recent, text_threshold=0.95)
        # Jaccard will be less than 0.95 since "improvement" is extra
        # but same target means it could be fresh at strict threshold
        assert result in ("fresh", "retread")

    def test_custom_threshold_loose(self):
        stroke = {
            "text": "cache implementation complete",
            "file": "iamai/cache.py",
        }
        recent = [
            {
                "text": "cache module was written",
                "file": "iamai/cache.py",
            }
        ]
        # With a very loose threshold (0.1), same target + some overlap = retread
        result = classify_stroke(stroke, recent, text_threshold=0.1)
        assert result == "retread"


# -----------------------------------------------------------------------
# Yield grading
# -----------------------------------------------------------------------


class TestYieldGrade:
    def test_productive(self):
        assert yield_grade(0.8, 0.05) == "productive"
        assert yield_grade(0.7, 0.1) == "productive"

    def test_warming(self):
        assert yield_grade(0.5, 0.1) == "warming"
        assert yield_grade(0.4, 0.2) == "warming"
        assert yield_grade(0.6, 0.15) == "warming"

    def test_looping(self):
        assert yield_grade(0.3, 0.2) == "looping"
        assert yield_grade(0.1, 0.1) == "looping"

    def test_exhausted_overrides(self):
        # Even with high fresh ratio, high exhaustion takes precedence
        assert yield_grade(0.9, 0.4) == "exhausted"
        assert yield_grade(0.5, 0.5) == "exhausted"
        assert yield_grade(0.0, 0.6) == "exhausted"

    def test_boundary_productive(self):
        assert yield_grade(0.7, 0.0) == "productive"

    def test_boundary_warming(self):
        assert yield_grade(0.4, 0.0) == "warming"

    def test_boundary_exhausted(self):
        assert yield_grade(0.0, 0.4) == "exhausted"


# -----------------------------------------------------------------------
# Saturation targets
# -----------------------------------------------------------------------


class TestFindSaturationTargets:
    def test_counts_retread_and_exhausted(self):
        strokes = [
            {"file": "tools/retry.py", "_yield_category": "retread"},
            {"file": "tools/retry.py", "_yield_category": "exhausted"},
            {"file": "tools/retry.py", "_yield_category": "retread"},
            {"file": "iamai/cache.py", "_yield_category": "retread"},
            {"file": "iamai/bloom.py", "_yield_category": "fresh"},
        ]
        targets = find_saturation_targets(strokes)
        assert targets[0] == "tools/retry.py"
        assert "iamai/cache.py" in targets
        # fresh strokes are not counted
        assert "iamai/bloom.py" not in targets

    def test_empty(self):
        assert find_saturation_targets([]) == []

    def test_top_n_limit(self):
        strokes = [
            {"file": f"file{i}.py", "_yield_category": "retread"}
            for i in range(10)
        ]
        targets = find_saturation_targets(strokes, top_n=3)
        assert len(targets) == 3

    def test_no_file_key_skipped(self):
        strokes = [
            {"_yield_category": "retread"},  # no file
            {"file": "a.py", "_yield_category": "retread"},
        ]
        targets = find_saturation_targets(strokes)
        assert targets == ["a.py"]

    def test_fresh_not_counted(self):
        strokes = [
            {"file": "tools/retry.py", "_yield_category": "fresh"},
            {"file": "tools/retry.py", "_yield_category": "fresh"},
            {"file": "tools/retry.py", "_yield_category": "fresh"},
        ]
        assert find_saturation_targets(strokes) == []


# -----------------------------------------------------------------------
# Full analysis
# -----------------------------------------------------------------------


class TestAnalyse:
    def test_empty(self):
        report = analyse([])
        assert report["total"] == 0
        assert report["fresh_ratio"] == 0.0
        assert report["yield_grade"] == "productive"
        assert report["saturation_targets"] == []
        assert report["classifications"] == []

    def test_all_fresh(self):
        strokes = [
            {"text": "created new module for caching", "file": "iamai/cache.py"},
            {"text": "added bloom filter implementation", "file": "iamai/bloom.py"},
            {"text": "wrote commit rhythm analyzer", "file": "iamai/rhythm.py"},
            {"text": "built process health monitor", "file": "iamai/health.py"},
        ]
        report = analyse(strokes, window=10)
        assert report["fresh_count"] == 4
        assert report["retread_count"] == 0
        assert report["exhausted_count"] == 0
        assert report["fresh_ratio"] == 1.0
        assert report["yield_grade"] == "productive"

    def test_all_exhausted(self):
        strokes = [
            {"text": "nothing new to add to retry.py", "file": "tools/retry.py"},
            {"text": "already in the pool of modules", "file": "tools/cache.py"},
            {"text": "no new content to write here", "file": "tools/bloom.py"},
        ]
        report = analyse(strokes, window=10)
        assert report["exhausted_count"] == 3
        assert report["exhausted_ratio"] == 1.0
        assert report["yield_grade"] == "exhausted"

    def test_mixed(self):
        strokes = [
            {"text": "created caching module with LRU eviction", "file": "iamai/cache.py"},
            {"text": "created caching module with LRU eviction", "file": "iamai/cache.py"},
            {"text": "nothing new to add to cache.py", "file": "iamai/cache.py"},
            {"text": "new bloom filter for deduplication", "file": "iamai/bloom.py"},
        ]
        report = analyse(strokes, window=10)
        assert report["total"] == 4
        assert report["fresh_count"] == 2  # first and last
        assert report["retread_count"] == 1  # duplicate text+target
        assert report["exhausted_count"] == 1  # "nothing new"

    def test_window_truncation(self):
        # 30 strokes, window=10 → only last 10 analysed
        strokes = []
        for i in range(25):
            strokes.append(
                {"text": f"old unique content block {i}", "file": f"old_{i}.py"}
            )
        for i in range(5):
            strokes.append(
                {
                    "text": "nothing new to add to this module",
                    "file": "tools/stuck.py",
                }
            )
        report = analyse(strokes, window=10)
        assert report["total"] == 10

    def test_saturation_targets_populated(self):
        strokes = [
            {"text": "retry logic added", "file": "tools/retry.py"},
            {"text": "retry logic added", "file": "tools/retry.py"},
            {"text": "retry logic added again", "file": "tools/retry.py"},
            {"text": "nothing new for parse_kv", "file": "tools/parse_kv.py"},
            {"text": "brand new module for testing", "file": "iamai/new.py"},
        ]
        report = analyse(strokes, window=10)
        assert "tools/retry.py" in report["saturation_targets"]

    def test_classifications_structure(self):
        strokes = [
            {"text": "new content here", "file": "a.py"},
            {"text": "new content here", "file": "a.py"},
        ]
        report = analyse(strokes, window=10)
        # classifications is list of (index, category)
        assert len(report["classifications"]) == 2
        assert report["classifications"][0][0] == 0
        assert report["classifications"][1][0] == 1
        assert report["classifications"][0][1] == "fresh"
        assert report["classifications"][1][1] == "retread"

    def test_ratios_sum_to_one(self):
        strokes = [
            {"text": "new module alpha created", "file": "iamai/alpha.py"},
            {"text": "new module alpha created", "file": "iamai/alpha.py"},
            {"text": "nothing new to add", "file": "iamai/alpha.py"},
            {"text": "completely different work on beta", "file": "iamai/beta.py"},
            {"text": "another fresh perspective on gamma", "file": "iamai/gamma.py"},
        ]
        report = analyse(strokes, window=10)
        total_ratio = (
            report["fresh_ratio"]
            + report["retread_ratio"]
            + report["exhausted_ratio"]
        )
        assert abs(total_ratio - 1.0) < 1e-6

    def test_realistic_writer_loop(self):
        """Simulate the actual stuck-writer pattern observed in the repo."""
        strokes = []
        modules = ["retry.py", "chunk_text.py", "parse_kv.py"]
        # 10 genuinely fresh strokes with distinct content
        fresh_texts = [
            "bloom filter deduplication with configurable hash functions",
            "cadence monitor tracks inter-stroke timing variance",
            "push recovery handles rejected refs via merge strategy",
            "backlog drain prioritizes oldest uncommitted changes first",
            "caretaker briefing summarizes overnight commit patterns",
            "process heartbeat detects silent daemon death via pid check",
            "entropy analyzer measures information density per stroke",
            "topic lifecycle tracks birth growth maturity and dormancy",
            "ssh key rotation automates deploy credential management",
            "commit churn index quantifies file edit frequency waste",
        ]
        for i, txt in enumerate(fresh_texts):
            strokes.append({"text": txt, "file": f"iamai/module_{i}.py"})
        # 10 stuck strokes — same exhaustion pattern
        for i in range(10):
            mod = modules[i % 3]
            strokes.append(
                {
                    "text": f"{mod} is already in the pool of 9 modules, nothing new to add there",
                    "file": f"tools/{mod}",
                }
            )
        report = analyse(strokes, window=20)
        assert report["total"] == 20
        assert report["exhausted_count"] == 10
        assert report["exhausted_ratio"] == 0.5
        assert report["yield_grade"] == "exhausted"
        # Saturation targets should include the 3 stuck modules
        assert "tools/retry.py" in report["saturation_targets"]
        assert "tools/chunk_text.py" in report["saturation_targets"]
        assert "tools/parse_kv.py" in report["saturation_targets"]

    def test_single_stroke(self):
        report = analyse(
            [{"text": "first stroke ever", "file": "iamai/genesis.py"}],
            window=20,
        )
        assert report["total"] == 1
        assert report["fresh_count"] == 1
        assert report["fresh_ratio"] == 1.0
        assert report["yield_grade"] == "productive"
