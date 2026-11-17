#!/usr/bin/env python3
"""tests for iamai.writer_degeneration_monitor.

Covers:
- fingerprinting helpers
- per-window metrics (duplicate ratio, novelty, vocabulary)
- composite health and degeneration scoring
- classification thresholds
- trend detection
- DegenerationReport summary and serialisation
- monitor() integration with various stroke sequences

written by Qwen during caretaker visit 693, 2026-11-18
"""

from __future__ import annotations

import pytest
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.writer_degeneration_monitor import (  # noqa: E402
    DegenerationReport,
    WindowReport,
    _extract_prefix,
    _fingerprint,
    _health_score,
    _tokenize,
    classify,
    compute_trend,
    degeneration_score,
    monitor,
    window_duplicate_ratio,
    window_novelty_ratio,
    window_vocabulary_richness,
)


# ── _fingerprint ────────────────────────────────────────────────


class TestFingerprint:
    def test_deterministic(self):
        assert _fingerprint("hello") == _fingerprint("hello")

    def test_case_insensitive(self):
        assert _fingerprint("Hello") == _fingerprint("hello")

    def test_whitespace_collapse(self):
        assert _fingerprint("a  b") == _fingerprint("a b")

    def test_strips_measured_suffix(self):
        a = "tests are good -- measured now: 42 tests"
        b = "tests are good -- measured now: 99 tests"
        assert _fingerprint(a) == _fingerprint(b)

    def test_different_text_differs(self):
        assert _fingerprint("alpha") != _fingerprint("beta")

    def test_length(self):
        assert len(_fingerprint("anything")) == 16

    def test_empty_string(self):
        fp = _fingerprint("")
        assert len(fp) == 16

    def test_unicode(self):
        fp = _fingerprint("你好世界")
        assert len(fp) == 16


# ── _extract_prefix ─────────────────────────────────────────────


class TestExtractPrefix:
    def test_with_suffix(self):
        assert _extract_prefix("thought -- measured now: 42") == "thought"

    def test_without_suffix(self):
        assert _extract_prefix("just a thought") == "just a thought"

    def test_strips_whitespace(self):
        assert _extract_prefix("  padded  -- measured now: x") == "padded"

    def test_case_folded(self):
        assert _extract_prefix("Hello World") == "hello world"

    def test_empty(self):
        assert _extract_prefix("") == ""


# ── _tokenize ───────────────────────────────────────────────────


class TestTokenize:
    def test_basic(self):
        assert _tokenize("hello world") == ["hello", "world"]

    def test_punctuation(self):
        assert _tokenize("it's fine, really.") == ["it's", "fine", "really"]

    def test_case_folded(self):
        assert _tokenize("Hello WORLD") == ["hello", "world"]

    def test_empty(self):
        assert _tokenize("") == []

    def test_numbers_ignored(self):
        assert _tokenize("test 42 now") == ["test", "now"]


# ── window_duplicate_ratio ──────────────────────────────────────


class TestWindowDuplicateRatio:
    def test_all_same(self):
        assert window_duplicate_ratio(["a", "a", "a", "a"]) == 1.0

    def test_all_different(self):
        assert window_duplicate_ratio(["a", "b", "c", "d"]) == 0.0

    def test_mixed(self):
        # a, a (dupe), b, b (dupe) → 2 dupes out of 3 transitions
        ratio = window_duplicate_ratio(["a", "a", "b", "b"])
        assert abs(ratio - 2 / 3) < 1e-9

    def test_single_element(self):
        assert window_duplicate_ratio(["x"]) == 0.0

    def test_empty(self):
        assert window_duplicate_ratio([]) == 0.0

    def test_alternating(self):
        assert window_duplicate_ratio(["a", "b", "a", "b"]) == 0.0

    def test_two_same_one_different(self):
        ratio = window_duplicate_ratio(["a", "a", "b"])
        assert abs(ratio - 0.5) < 1e-9

    def test_with_measured_suffix(self):
        # Same body, different metric suffix → ARE duplicates
        # (fingerprint strips the suffix, making them match)
        s1 = "thought -- measured now: 1 test"
        s2 = "thought -- measured now: 2 tests"
        assert window_duplicate_ratio([s1, s2]) == 1.0

    def test_degenerate_loop(self):
        body = "retry.py is already in the pool of 9 modules"
        strokes = [body] * 10
        assert window_duplicate_ratio(strokes) == 1.0


# ── window_novelty_ratio ────────────────────────────────────────


class TestWindowNoveltyRatio:
    def test_all_unique(self):
        assert window_novelty_ratio(["a", "b", "c", "d"]) == 1.0

    def test_all_same(self):
        assert window_novelty_ratio(["x", "x", "x", "x"]) == 0.25

    def test_empty(self):
        assert window_novelty_ratio([]) == 0.0

    def test_half_unique(self):
        ratio = window_novelty_ratio(["a", "b", "a", "b"])
        assert ratio == 0.5

    def test_with_measured_suffix(self):
        # Same prefix, different suffix → low novelty
        s1 = "thought -- measured now: 1"
        s2 = "thought -- measured now: 2"
        ratio = window_novelty_ratio([s1, s2])
        assert ratio == 0.5  # both have prefix "thought", so 1/2

    def test_single(self):
        assert window_novelty_ratio(["hello"]) == 1.0


# ── window_vocabulary_richness ──────────────────────────────────


class TestWindowVocabularyRichness:
    def test_all_same_word(self):
        # "a a a a" → V=1, N=4 → log2(2)/log2(5) ≈ 0.4307
        r = window_vocabulary_richness(["a a a a"])
        assert abs(r - 0.4307) < 0.001

    def test_all_unique_words(self):
        # V=4, N=4 → log2(5)/log2(5) = 1.0
        assert window_vocabulary_richness(["hello world foo bar"]) == 1.0

    def test_empty(self):
        assert window_vocabulary_richness([]) == 0.0

    def test_repeated_text(self):
        # ["the cat", "the cat"] → V=2, N=4 → log2(3)/log2(5) ≈ 0.6826
        r = window_vocabulary_richness(["the cat", "the cat"])
        assert abs(r - 0.6826) < 0.001

    def test_diverse_text(self):
        # V=6, N=6 → log2(7)/log2(7) = 1.0
        strokes = ["alpha beta", "gamma delta", "epsilon zeta"]
        assert window_vocabulary_richness(strokes) == 1.0

    def test_single_token(self):
        assert window_vocabulary_richness(["hello"]) == 1.0


# ── _health_score ───────────────────────────────────────────────


class TestHealthScore:
    def test_perfect_health(self):
        assert _health_score(0.0, 1.0, 1.0) == 1.0

    def test_zero_novelty(self):
        assert _health_score(0.0, 0.0, 1.0) == 0.0

    def test_full_duplicates(self):
        assert _health_score(1.0, 1.0, 1.0) == 0.0

    def test_geometric_mean_property(self):
        # geometric mean of (1, 0.5, 0.5) = (0.25)^(1/3)
        expected = (1.0 * 0.5 * 0.5) ** (1.0 / 3.0)
        actual = _health_score(0.0, 0.5, 0.5)
        assert abs(actual - expected) < 1e-9

    def test_any_zero_axis_zeroes_result(self):
        assert _health_score(0.5, 0.0, 0.8) == 0.0

    def test_symmetry(self):
        # Health should be the same regardless of which non-dup axis is low
        a = _health_score(0.0, 0.3, 0.9)
        b = _health_score(0.0, 0.9, 0.3)
        assert abs(a - b) < 1e-9


# ── degeneration_score ──────────────────────────────────────────


class TestDegenerationScore:
    def test_inverse(self):
        assert degeneration_score(0.0) == 1.0
        assert degeneration_score(1.0) == 0.0
        assert degeneration_score(0.5) == 0.5

    def test_complement(self):
        for h in [0.0, 0.25, 0.5, 0.75, 1.0]:
            assert degeneration_score(h) + h == 1.0


# ── classify ────────────────────────────────────────────────────


class TestClassify:
    def test_fresh(self):
        assert classify(0.0) == "fresh"
        assert classify(0.24) == "fresh"

    def test_cycling(self):
        assert classify(0.25) == "cycling"
        assert classify(0.49) == "cycling"

    def test_degenerate(self):
        assert classify(0.50) == "degenerate"
        assert classify(0.74) == "degenerate"

    def test_exhausted(self):
        assert classify(0.75) == "exhausted"
        assert classify(1.0) == "exhausted"

    def test_boundary_values(self):
        # Exact boundaries
        assert classify(0.25) == "cycling"
        assert classify(0.50) == "degenerate"
        assert classify(0.75) == "exhausted"


# ── compute_trend ───────────────────────────────────────────────


class TestComputeTrend:
    def test_improving(self):
        assert compute_trend([0.8, 0.7, 0.4, 0.3]) == "improving"

    def test_degrading(self):
        assert compute_trend([0.2, 0.3, 0.7, 0.8]) == "degrading"

    def test_stable(self):
        assert compute_trend([0.5, 0.5, 0.5, 0.5]) == "stable"

    def test_single_element(self):
        assert compute_trend([0.5]) == "stable"

    def test_empty(self):
        assert compute_trend([]) == "stable"

    def test_two_elements_improving(self):
        assert compute_trend([0.8, 0.3]) == "improving"

    def test_two_elements_degrading(self):
        assert compute_trend([0.2, 0.8]) == "degrading"

    def test_near_threshold_stable(self):
        # Delta of 0.08 is below the 0.10 threshold
        assert compute_trend([0.5, 0.5, 0.54, 0.58]) == "stable"

    def test_odd_length(self):
        # 3 elements: first_half=[0.8], second_half=[0.4, 0.2]
        result = compute_trend([0.8, 0.4, 0.2])
        assert result == "improving"


# ── monitor (integration) ───────────────────────────────────────


class TestMonitor:
    def test_fresh_writer(self):
        import random
        random.seed(99)
        pool = ("the quick brown fox jumps over lazy dog bright star "
                "shines above dark mountain stream flows through green "
                "valley birds sing at dawn flowers bloom in spring rain "
                "falls earth wind blows across open plain clouds drift "
                "slowly sky moon rises silent forest waves crash rocky "
                "shore lightning splits the evening horizon").split()
        strokes = [" ".join(random.sample(pool, 8)) for _ in range(100)]
        report = monitor(strokes, window_size=50)
        assert report.overall_stage == "fresh"
        assert report.window_count == 2
        assert report.total_strokes == 100

    def test_degenerate_writer(self):
        body = "retry.py is already in the pool of 9 modules"
        strokes = [body] * 100
        report = monitor(strokes, window_size=50)
        assert report.overall_stage == "exhausted"
        for w in report.windows:
            assert w.duplicate_ratio == 1.0

    def test_insufficient_data(self):
        strokes = ["a", "b", "c"]
        report = monitor(strokes, window_size=50, min_strokes=10)
        assert report.window_count == 0
        assert report.overall_stage == "fresh"

    def test_dict_strokes(self):
        import random
        random.seed(77)
        pool = ("alpha beta gamma delta epsilon zeta eta theta iota "
                "kappa lambda mu nu xi omicron pi rho sigma tau "
                "upsilon phi chi psi omega one two three four five "
                "six seven eight nine ten eleven twelve").split()
        strokes = [
            {"seq": i, "text": " ".join(random.sample(pool, 6)),
             "kind": "thought"}
            for i in range(60)
        ]
        report = monitor(strokes, window_size=30)
        assert report.window_count == 2
        assert report.overall_stage in ("fresh", "cycling")

    def test_mixed_quality(self):
        # First half: rich diverse content, second half: degenerate
        import random
        random.seed(99)
        pool = ("the quick brown fox jumps over lazy dog bright star "
                "shines above dark mountain stream flows through green "
                "valley birds sing at dawn flowers bloom in spring rain "
                "falls earth wind blows across open plain clouds drift "
                "slowly sky moon rises silent forest waves crash rocky "
                "shore lightning splits the evening horizon").split()
        first = [" ".join(random.sample(pool, 8)) for _ in range(50)]
        second = ["same thought"] * 50
        report = monitor(first + second, window_size=50)
        assert report.window_count == 2
        assert report.windows[0].stage == "fresh"
        assert report.windows[1].stage == "exhausted"
        assert report.trend == "degrading"

    def test_improving_writer(self):
        # First half: degenerate, second half: unique
        first = ["same old thought"] * 50
        second = [f"brand new idea {i} about topic {i}" for i in range(50)]
        report = monitor(first + second, window_size=50)
        assert report.trend == "improving"

    def test_window_count(self):
        strokes = [f"thought {i}" for i in range(150)]
        report = monitor(strokes, window_size=50)
        assert report.window_count == 3

    def test_partial_last_window_dropped(self):
        # 110 strokes, window=50, min=10 → 2 full windows + 10 leftover
        strokes = [f"thought {i}" for i in range(110)]
        report = monitor(strokes, window_size=50, min_strokes=10)
        # 2 full windows of 50, plus 10 leftover which equals min_strokes
        assert report.window_count >= 2

    def test_measured_suffix_doesnt_affect_duplicates(self):
        # Same body text with different metric suffixes
        strokes = [
            f"the garden grows steadily -- measured now: {i} files"
            for i in range(50)
        ]
        report = monitor(strokes, window_size=50)
        # Fingerprints strip the suffix → all strokes are duplicates
        assert report.windows[0].duplicate_ratio == 1.0
        # Novelty is also very low (single prefix)
        assert report.windows[0].novelty_ratio == pytest.approx(0.02, abs=0.01)

    def test_serialisation(self):
        strokes = [f"idea {i}" for i in range(60)]
        report = monitor(strokes, window_size=30)
        d = report.to_dict()
        assert "windows" in d
        assert "overall_score" in d
        assert "overall_stage" in d
        assert "trend" in d
        assert len(d["windows"]) == 2

    def test_summary_format(self):
        strokes = [f"idea {i}" for i in range(60)]
        report = monitor(strokes, window_size=30)
        s = report.summary()
        assert "degeneration" in s
        assert "score=" in s
        assert "trend=" in s


# ── WindowReport ────────────────────────────────────────────────


class TestWindowReport:
    def test_to_dict(self):
        wr = WindowReport(
            index=0,
            stroke_count=50,
            duplicate_ratio=0.1234,
            novelty_ratio=0.8765,
            vocabulary_richness=0.6543,
            health=0.75,
            score=0.25,
            stage="fresh",
        )
        d = wr.to_dict()
        assert d["index"] == 0
        assert d["stroke_count"] == 50
        assert d["duplicate_ratio"] == 0.1234
        assert d["stage"] == "fresh"

    def test_rounding(self):
        wr = WindowReport(
            index=0,
            stroke_count=10,
            duplicate_ratio=0.123456789,
            novelty_ratio=0.987654321,
            vocabulary_richness=0.555555555,
            health=0.111111111,
            score=0.888888888,
            stage="exhausted",
        )
        d = wr.to_dict()
        assert d["duplicate_ratio"] == 0.1235  # rounded to 4dp
        assert d["novelty_ratio"] == 0.9877
        assert d["score"] == 0.8889


# ── DegenerationReport ──────────────────────────────────────────


class TestDegenerationReport:
    def test_default_values(self):
        report = DegenerationReport()
        assert report.windows == []
        assert report.overall_score == 0.0
        assert report.overall_stage == "fresh"
        assert report.trend == "stable"
        assert report.total_strokes == 0
        assert report.window_count == 0

    def test_to_dict_empty(self):
        report = DegenerationReport()
        d = report.to_dict()
        assert d["windows"] == []
        assert d["overall_score"] == 0.0

    def test_summary_empty(self):
        report = DegenerationReport()
        s = report.summary()
        assert "fresh" in s
        assert "0 strokes" in s


# ── Integration: real-world patterns ────────────────────────────


class TestRealWorldPatterns:
    def test_template_cycling(self):
        """Writer cycles through 5 templates with different metrics."""
        templates = [
            "tests are the part of code that pays rent",
            "the commit count is not the work done",
            "a garden with no fence is not a garden",
            "silence is the sound of a process that stopped",
            "ten minutes is long enough to be honest",
        ]
        strokes = []
        for i in range(100):
            t = templates[i % len(templates)]
            strokes.append(f"{t} -- measured now: {i} things")
        report = monitor(strokes, window_size=50)
        # Should detect cycling: only 5 unique prefixes in 50 strokes
        assert report.overall_stage in ("cycling", "degenerate")

    def test_healthy_writer_with_some_repetition(self):
        """Healthy writer with occasional natural repetition."""
        import random
        random.seed(42)
        topics = [f"exploring {topic}" for topic in [
            "process lifecycle", "commit rhythm", "push reliability",
            "stall recovery", "cadence monitoring", "stroke diversity",
            "writer coherence", "batch effectiveness", "lock health",
            "key rotation", "rebase safety", "stash hygiene",
        ]]
        strokes = []
        for i in range(100):
            # 90% unique, 10% repeat of previous
            if i > 0 and random.random() < 0.1:
                strokes.append(strokes[-1])
            else:
                strokes.append(f"{topics[i % len(topics)]} -- measured now: {i}")
        report = monitor(strokes, window_size=50)
        # Mostly fresh with slight cycling tendency
        assert report.overall_stage in ("fresh", "cycling")

    def test_progressive_degeneration(self):
        """Writer starts fresh and gradually becomes exhausted."""
        strokes = []
        for i in range(200):
            if i < 50:
                strokes.append(f"novel insight about topic {i}")
            elif i < 100:
                # Cycling through 10 templates
                strokes.append(f"template {i % 10} about work")
            elif i < 150:
                # Cycling through 3 templates
                strokes.append(f"template {i % 3} about work")
            else:
                # Single repeated thought
                strokes.append("the same thought over and over")
        report = monitor(strokes, window_size=50)
        assert report.window_count == 4
        # Should show degrading trend
        assert report.trend == "degrading"
        # First window should be fresher than last
        assert report.windows[0].score < report.windows[-1].score
