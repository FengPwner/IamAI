"""Tests for iamai.template_loop_detector.

Covers:
- templatise() helper (number, quote, hex replacement)
- detect_loop() core logic (empty, short, healthy, repeating, locked)
- Edge cases (all-identical, all-unique, single-stroke, two-stroke)
- scan_history() sliding window
- summary() formatting
- Immutability of the frozen dataclass
- Verdict enum values
"""

from __future__ import annotations

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iamai.template_loop_detector import (
    LoopResult,
    LoopVerdict,
    detect_loop,
    scan_history,
    summary,
    templatise,
    DEFAULT_WINDOW,
    DEFAULT_REPEAT_THRESHOLD,
    DEFAULT_LOCK_THRESHOLD,
)


# ---------------------------------------------------------------------------
# templatise
# ---------------------------------------------------------------------------


class TestTemplatise:
    def test_replaces_integers(self):
        assert templatise("536 python files, 3302 logged thoughts") == (
            "<N> python files, <N> logged thoughts"
        )

    def test_replaces_floats(self):
        assert templatise("gap is 12.5 seconds") == "gap is <N> seconds"

    def test_replaces_hex_hash(self):
        assert templatise("commit abc123def456 landed") == "commit <H> landed"

    def test_replaces_double_quoted_string(self):
        assert templatise('said "hello world" to everyone') == "said <S> to everyone"

    def test_replaces_single_quoted_string(self):
        assert templatise("she said 'hello there' loudly") == "she said <S> loudly"

    def test_collapses_whitespace(self):
        assert templatise("  too   many   spaces  ") == "too many spaces"

    def test_strips_edges(self):
        assert templatise("  hello  ") == "hello"

    def test_empty_string(self):
        assert templatise("") == ""

    def test_no_variables(self):
        assert templatise("just a plain sentence") == "just a plain sentence"

    def test_multiple_numbers_in_row(self):
        assert templatise("100 files, 200 lines, 300 commits") == (
            "<N> files, <N> lines, <N> commits"
        )


# ---------------------------------------------------------------------------
# detect_loop — basic behaviour
# ---------------------------------------------------------------------------


class TestDetectLoopBasic:
    def test_empty_input(self):
        r = detect_loop([])
        assert r.verdict == LoopVerdict.FREE
        assert r.loop_fraction == 0.0
        assert r.dominant_template == ""
        assert r.dominant_count == 0
        assert r.window_size == 0

    def test_single_stroke(self):
        r = detect_loop(["536 python files, 3302 logged thoughts"], window=2)
        # window=2 but only 1 stroke → window_size=1, fraction=1.0 → locked
        assert r.window_size == 1
        assert r.dominant_count == 1

    def test_two_identical_strokes(self):
        strokes = ["536 files", "536 files"]
        r = detect_loop(strokes, window=2)
        assert r.verdict == LoopVerdict.LOCKED
        assert r.loop_fraction == 1.0

    def test_two_different_strokes(self):
        strokes = ["536 files", "hello world"]
        r = detect_loop(strokes, window=2)
        assert r.loop_fraction == 0.5

    def test_window_minimum_validation(self):
        with pytest.raises(ValueError, match="window must be >= 2"):
            detect_loop(["a"], window=1)

    def test_window_larger_than_input(self):
        strokes = ["alpha", "beta", "gamma"]
        r = detect_loop(strokes, window=10)
        assert r.window_size == 3  # clamped to input length


# ---------------------------------------------------------------------------
# detect_loop — verdict classification
# ---------------------------------------------------------------------------


class TestDetectLoopVerdicts:
    def test_locked_verdict(self):
        # 10/12 share the same template → 83% → locked
        template_fill = "536 python files, 3302 logged thoughts"
        filler = [
            "the sky is blue today",
            "I wonder about recursion",
        ]
        strokes = [template_fill] * 10 + filler
        r = detect_loop(strokes, window=12)
        assert r.verdict == LoopVerdict.LOCKED
        assert r.loop_fraction >= DEFAULT_LOCK_THRESHOLD

    def test_repeating_verdict(self):
        # 6/12 share the same template → 50% → repeating
        template_fill = "536 python files, 3302 logged thoughts"
        unique = [
            "the sky is blue",
            "recursion is elegant",
            "git push --force is dangerous",
            "water the garden",
            "tests pass in 0.3s",
            "entropy rises quietly",
        ]
        strokes = [template_fill] * 6 + unique
        r = detect_loop(strokes, window=12)
        assert r.verdict == LoopVerdict.REPEATING
        assert DEFAULT_REPEAT_THRESHOLD <= r.loop_fraction < DEFAULT_LOCK_THRESHOLD

    def test_free_verdict(self):
        # All different → 1/12 → free
        strokes = [
            "alpha bravo charlie",
            "delta echo foxtrot",
            "golf hotel india",
            "juliet kilo lima",
            "mike november oscar",
            "papa quebec romeo",
            "sierra tango uniform",
            "victor whiskey xray",
            "yankee zulu ace",
            "bandit cobra dawn",
            "eagle falcon ghost",
            "hunter iris jade",
        ]
        r = detect_loop(strokes, window=12)
        assert r.verdict == LoopVerdict.FREE
        assert r.loop_fraction < DEFAULT_REPEAT_THRESHOLD

    def test_all_identical_is_locked(self):
        strokes = ["same thought again"] * 20
        r = detect_loop(strokes, window=12)
        assert r.verdict == LoopVerdict.LOCKED
        assert r.loop_fraction == 1.0
        assert r.dominant_count == 12

    def test_template_matching_ignores_numbers(self):
        # Same template, different numbers → still a loop
        strokes = [
            "534 python files, 3296 logged thoughts",
            "536 python files, 3302 logged thoughts",
            "536 python files, 3305 logged thoughts",
            "536 python files, 3308 logged thoughts",
            "536 python files, 3311 logged thoughts",
            "536 python files, 3314 logged thoughts",
            "536 python files, 3317 logged thoughts",
            "536 python files, 3320 logged thoughts",
        ]
        r = detect_loop(strokes, window=8)
        assert r.verdict == LoopVerdict.LOCKED
        assert r.dominant_template == "<N> python files, <N> logged thoughts"


# ---------------------------------------------------------------------------
# detect_loop — real-world-ish scenario
# ---------------------------------------------------------------------------


class TestDetectLoopRealWorld:
    def test_mixed_healthy_strokes(self):
        strokes = [
            "536 python files, 3302 logged thoughts",
            "commit 1513: the count of times this repo was pushed",
            "a repo that only accumulates is a landfill with a README",
            "automation fails quietly, so the log has to say something",
            "the useful abstraction deletes a branch, it does not add a class",
            "naming is hard because a bad name is cheap to type",
            "deleting a file is progress too, eventually",
            "tree is 839 files; 174148 lines is a lot for a toy",
            "stroke entropy: 0.87 across six kinds",
            "tests pass in 1.2s, 347 tests, 0 failures",
            "the committer sleeps 600s between checks",
            "writer cadence: 15s per stroke, 4 strokes per minute",
        ]
        r = detect_loop(strokes, window=12)
        assert r.verdict == LoopVerdict.FREE

    def test_degraded_writer_with_unique_number_strokes(self):
        # Simulates the actual failure mode from the repo
        base = [
            "{n} python files, {t} logged thoughts",
            "commit {c}: the count of times this repo was pushed, not the work done",
            "tree is {f} files; {l} lines is a lot for a toy",
            "{s} strokes written so far into {f} files",
        ]
        strokes = []
        for i in range(12):
            tpl = base[i % len(base)]
            strokes.append(tpl.format(n=536 + i, t=3302 + i, c=1513, f=839, l=174000 + i, s=3300 + i))
        r = detect_loop(strokes, window=12)
        # 4 templates cycling in 12 strokes → dominant appears 3/12 = 25% → free
        # (this is a mild template pattern but below threshold)
        assert r.dominant_count <= 4  # at most 4 of any one template


# ---------------------------------------------------------------------------
# scan_history
# ---------------------------------------------------------------------------


class TestScanHistory:
    def test_short_history(self):
        strokes = ["alpha", "beta"]
        results = scan_history(strokes, step=1, window=4)
        assert len(results) == 1
        assert results[0].window_size == 2

    def test_sliding_window_steps(self):
        strokes = [f"stroke {i}" for i in range(30)]
        results = scan_history(strokes, step=6, window=12)
        # i in range(0, 30-12+1=19, 6) → i=0,6,12,18 → 4 results
        assert len(results) == 4
        assert all(r.window_size == 12 for r in results)

    def test_all_unique_stays_free(self):
        # Each stroke must have a *structurally different* sentence, not just different numbers.
        phrases = [
            "the sky darkens over the western hills",
            "recursion is its own reward",
            "git blame tells stories that git log cannot",
            "water boils at one hundred degrees celsius",
            "entropy measures what we do not know",
            "a good test catches a bad design early",
            "the garden needs weeding before the rain",
            "compile errors are the compiler caring",
            "silence in the logs means everything is fine",
            "naming things is one of the two hard problems",
            "delete code fearlessly but commit first",
            "the best abstraction is the one you remove",
        ]
        # Repeat the set to get 50 strokes (with variation each cycle stays diverse)
        strokes = (phrases * 5)[:50]
        results = scan_history(strokes, step=10, window=12)
        assert all(r.verdict == LoopVerdict.FREE for r in results)


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------


class TestSummary:
    def test_locked_summary(self):
        strokes = ["536 files"] * 12
        r = detect_loop(strokes, window=12)
        s = summary(r)
        assert "LOCKED" in s
        assert "12/12" in s
        assert "100.0%" in s

    def test_free_summary(self):
        strokes = ["alpha", "beta", "gamma", "delta", "epsilon",
                    "zeta", "eta", "theta", "iota", "kappa",
                    "lambda", "mu"]
        r = detect_loop(strokes, window=12)
        s = summary(r)
        assert "FREE" in s

    def test_empty_summary(self):
        r = detect_loop([])
        s = summary(r)
        assert "no strokes" in s.lower()


# ---------------------------------------------------------------------------
# Dataclass immutability
# ---------------------------------------------------------------------------


class TestDataclassIntegrity:
    def test_frozen_result(self):
        r = detect_loop(["a", "b"], window=2)
        with pytest.raises(AttributeError):
            r.verdict = LoopVerdict.LOCKED  # type: ignore

    def test_ok_property(self):
        r_free = detect_loop(["a", "b"], window=2)
        # Two different strings → fraction=0.5 → repeating or free depending on threshold
        # Just check .ok is a bool
        assert isinstance(r_free.ok, bool)


# ---------------------------------------------------------------------------
# Verdict enum
# ---------------------------------------------------------------------------


class TestVerdictEnum:
    def test_values(self):
        assert LoopVerdict.FREE.value == "free"
        assert LoopVerdict.REPEATING.value == "repeating"
        assert LoopVerdict.LOCKED.value == "locked"

    def test_string_behaviour(self):
        assert str(LoopVerdict.FREE) == "LoopVerdict.FREE"
        assert LoopVerdict.LOCKED == "locked"


# ---------------------------------------------------------------------------
# Custom thresholds
# ---------------------------------------------------------------------------


class TestCustomThresholds:
    def test_strict_thresholds(self):
        # With very low thresholds, even mild repetition triggers locked
        strokes = ["same"] * 4 + ["different"] * 8
        r = detect_loop(strokes, window=12, repeat_threshold=0.20, lock_threshold=0.30)
        assert r.verdict == LoopVerdict.LOCKED

    def test_lenient_thresholds(self):
        # With very high thresholds, heavy repetition can sit between repeat and lock
        # 11/12 identical → 91.7% → below 0.95 repeat_threshold → FREE
        strokes_a = ["same"] * 11 + ["different"]
        r_a = detect_loop(strokes_a, window=12, repeat_threshold=0.95, lock_threshold=0.99)
        assert r_a.verdict == LoopVerdict.FREE

        # 12/12 identical → 100% → above 0.95 repeat, below 0.99 lock → REPEATING
        strokes_b = ["same"] * 12
        r_b = detect_loop(strokes_b, window=12, repeat_threshold=0.95, lock_threshold=1.01)
        assert r_b.verdict == LoopVerdict.REPEATING
