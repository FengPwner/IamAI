"""Tests for stroke_dedup module.

Covers:
- fingerprint: normalisation, determinism, collision resistance
- is_duplicate: exact match, whitespace, case insensitivity
- scan_window: empty, single, no dupes, all dupes, mixed, window>1
- _longest_consecutive_run: empty, single, all same, alternating, runs
- DedupReport: dataclass, is_degenerate, to_dict
- dedup_report: empty, no dupes, all dupes, mixed, real-world pattern
"""

import pytest

from iamai.stroke_dedup import (
    DedupReport,
    dedup_report,
    fingerprint,
    is_duplicate,
    scan_window,
    _longest_consecutive_run,
)


# ===========================================================================
# fingerprint
# ===========================================================================


class TestFingerprint:
    def test_deterministic(self):
        assert fingerprint("hello world") == fingerprint("hello world")

    def test_case_insensitive(self):
        assert fingerprint("Hello World") == fingerprint("hello world")

    def test_whitespace_collapse(self):
        assert fingerprint("hello   world") == fingerprint("hello world")

    def test_leading_trailing_whitespace(self):
        assert fingerprint("  hello  ") == fingerprint("hello")

    def test_empty_strings_match(self):
        assert fingerprint("") == fingerprint("  ")

    def test_different_texts_differ(self):
        assert fingerprint("hello") != fingerprint("world")

    def test_returns_16_hex_chars(self):
        fp = fingerprint("test string")
        assert len(fp) == 16
        assert all(c in "0123456789abcdef" for c in fp)

    def test_unicode(self):
        assert fingerprint("你好世界") == fingerprint("你好世界")
        assert fingerprint("你好世界") != fingerprint("世界你好")


# ===========================================================================
# is_duplicate
# ===========================================================================


class TestIsDuplicate:
    def test_exact_match(self):
        assert is_duplicate("hello", "hello") is True

    def test_different(self):
        assert is_duplicate("hello", "world") is False

    def test_whitespace_normalised(self):
        assert is_duplicate("  Hello  ", "hello") is True

    def test_empty_strings(self):
        assert is_duplicate("", "") is True

    def test_long_identical_texts(self):
        text = "a" * 10000
        assert is_duplicate(text, text) is True

    def test_similar_but_different(self):
        assert is_duplicate("hello world", "hello world!") is False


# ===========================================================================
# scan_window
# ===========================================================================


class TestScanWindow:
    def test_empty(self):
        assert scan_window([]) == []

    def test_single(self):
        assert scan_window(["only one"]) == []

    def test_no_duplicates(self):
        assert scan_window(["a", "b", "c", "d"]) == []

    def test_all_duplicates(self):
        result = scan_window(["a", "a", "a", "a"])
        assert result == [1, 2, 3]

    def test_mixed(self):
        result = scan_window(["a", "b", "b", "c", "c", "c"])
        assert result == [2, 4, 5]

    def test_alternating(self):
        result = scan_window(["a", "b", "a", "b", "a"])
        assert result == []

    def test_duplicate_after_gap(self):
        result = scan_window(["a", "b", "c", "a"])
        # window=1 only looks at immediate predecessor
        assert result == []

    def test_window_2_catches_nearby(self):
        result = scan_window(["a", "b", "a"], window=2)
        assert result == [2]

    def test_window_larger_than_list(self):
        result = scan_window(["a", "b"], window=10)
        assert result == []

    def test_real_world_degenerate_loop(self):
        stroke = "retry.py is already in the pool of 9 modules, nothing new to add there"
        strokes = [stroke] * 20
        result = scan_window(strokes)
        assert result == list(range(1, 20))


# ===========================================================================
# _longest_consecutive_run
# ===========================================================================


class TestLongestConsecutiveRun:
    def test_empty(self):
        assert _longest_consecutive_run([]) == 0

    def test_single(self):
        assert _longest_consecutive_run(["a"]) == 1

    def test_all_same(self):
        assert _longest_consecutive_run(["a", "a", "a", "a"]) == 4

    def test_all_different(self):
        assert _longest_consecutive_run(["a", "b", "c", "d"]) == 1

    def test_two_runs(self):
        assert _longest_consecutive_run(["a", "a", "a", "b", "b"]) == 3

    def test_longer_second_run(self):
        assert _longest_consecutive_run(["a", "a", "b", "b", "b", "b"]) == 4

    def test_alternating(self):
        assert _longest_consecutive_run(["a", "b", "a", "b"]) == 1

    def test_run_at_end(self):
        assert _longest_consecutive_run(["x", "y", "z", "a", "a", "a"]) == 3


# ===========================================================================
# DedupReport
# ===========================================================================


class TestDedupReport:
    def test_basic_fields(self):
        r = DedupReport(total=10, duplicate_count=3, duplicate_ratio=0.3, longest_run=2)
        assert r.total == 10
        assert r.duplicate_count == 3
        assert r.duplicate_ratio == 0.3
        assert r.longest_run == 2

    def test_is_degenerate_false(self):
        r = DedupReport(total=10, duplicate_count=3, duplicate_ratio=0.3, longest_run=2)
        assert r.is_degenerate is False

    def test_is_degenerate_true(self):
        r = DedupReport(total=10, duplicate_count=8, duplicate_ratio=0.8, longest_run=5)
        assert r.is_degenerate is True

    def test_is_degenerate_boundary(self):
        # exactly 0.5 is not degenerate (must exceed)
        r = DedupReport(total=10, duplicate_count=5, duplicate_ratio=0.5, longest_run=3)
        assert r.is_degenerate is False

    def test_to_dict(self):
        r = DedupReport(
            total=5,
            duplicate_count=2,
            duplicate_ratio=0.4,
            longest_run=2,
            flagged_indices=[1, 3],
        )
        d = r.to_dict()
        assert d == {
            "total": 5,
            "duplicate_count": 2,
            "duplicate_ratio": 0.4,
            "longest_run": 2,
            "flagged_indices": [1, 3],
            "is_degenerate": False,
        }

    def test_flagged_indices_default_empty(self):
        r = DedupReport(total=0, duplicate_count=0, duplicate_ratio=0.0, longest_run=0)
        assert r.flagged_indices == []


# ===========================================================================
# dedup_report (integration)
# ===========================================================================


class TestDedupReportFunction:
    def test_empty(self):
        r = dedup_report([])
        assert r.total == 0
        assert r.duplicate_count == 0
        assert r.duplicate_ratio == 0.0
        assert r.longest_run == 0
        assert r.flagged_indices == []
        assert r.is_degenerate is False

    def test_no_duplicates(self):
        r = dedup_report(["alpha", "beta", "gamma", "delta"])
        assert r.total == 4
        assert r.duplicate_count == 0
        assert r.duplicate_ratio == 0.0
        assert r.longest_run == 1

    def test_all_duplicates(self):
        r = dedup_report(["x", "x", "x", "x"])
        assert r.total == 4
        assert r.duplicate_count == 3
        assert r.duplicate_ratio == 0.75
        assert r.longest_run == 4
        assert r.is_degenerate is True

    def test_mixed(self):
        r = dedup_report(["a", "a", "b", "a", "a", "a"])
        assert r.total == 6
        assert r.duplicate_count == 3
        assert r.longest_run == 3
        assert r.flagged_indices == [1, 4, 5]

    def test_real_world_degenerate_loop(self):
        stroke = "retry.py is already in the pool of 9 modules, nothing new to add there"
        strokes = [stroke] * 30
        r = dedup_report(strokes)
        assert r.total == 30
        assert r.duplicate_count == 29
        assert r.duplicate_ratio == pytest.approx(29 / 30)
        assert r.longest_run == 30
        assert r.is_degenerate is True

    def test_mostly_unique_with_some_dupes(self):
        strokes = [
            "thought about architecture",
            "reviewed the test suite",
            "reviewed the test suite",
            "explored new caching strategy",
            "wrote documentation",
            "fixed a bug in the parser",
            "wrote documentation",
        ]
        r = dedup_report(strokes)
        assert r.total == 7
        # window=1 only catches index 2 (immediate dup of index 1);
        # index 6 ("wrote documentation") is not adjacent to index 4
        assert r.duplicate_count == 1
        assert r.flagged_indices == [2]
        assert r.longest_run == 2
        assert r.is_degenerate is False

    def test_window_2(self):
        strokes = ["a", "b", "a", "c", "b"]
        r = dedup_report(strokes, window=2)
        # index 2 matches index 0 (within window 2)
        # index 4 matches index 3? no, "b" != "c"
        # index 4 matches index 2? no, "b" != "a"  -- wait
        # actually: i=2, look_back=min(2,2)=2, check j=0("a"=="a") -> flagged
        # i=4, look_back=min(4,2)=2, check j=2("b"=="a"? no), j=3("b"=="c"? no)
        assert r.duplicate_count == 1
        assert r.flagged_indices == [2]
