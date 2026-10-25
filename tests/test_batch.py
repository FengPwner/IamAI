"""Tests for iamai.batch — the pure commit-gate arithmetic.

Covers:
  - gate_open: interval boundary, pending guard, first-commit shortcut, ValueError
  - window_tally: filtering by timestamp, skipping malformed entries, empty input
  - subject: ordering, truncation with SUBJECT_LIMIT, silence fallback, edge cases
  - _window: minute rounding, singular vs plural
"""

from __future__ import annotations

import pytest

from iamai.batch import (
    SUBJECT_LIMIT,
    _window,
    gate_open,
    subject,
    window_tally,
)


# -- gate_open ---------------------------------------------------------------

class TestGateOpen:
    def test_rejects_non_positive_interval(self):
        with pytest.raises(ValueError, match="positive"):
            gate_open(0, 100, 0)
        with pytest.raises(ValueError, match="positive"):
            gate_open(0, 100, -5)

    def test_closed_when_nothing_pending(self):
        assert gate_open(0, 100, 10, pending=0) is False

    def test_opens_on_first_commit_even_if_interval_not_elapsed(self):
        # last_commit=None means no prior commit — gate opens immediately
        assert gate_open(None, 0, 600, pending=3) is True

    def test_closed_before_interval_elapsed(self):
        # 500s elapsed, interval is 600 → closed
        assert gate_open(100, 600, 600, pending=1) is False

    def test_opens_at_exact_interval(self):
        # 600s elapsed, interval is 600 → open
        assert gate_open(100, 700, 600, pending=1) is True

    def test_opens_after_interval(self):
        assert gate_open(100, 800, 600, pending=1) is True

    def test_default_pending_is_one(self):
        # With pending=1 (default), interval elapsed → open
        assert gate_open(0, 600, 600) is True

    def test_fractional_second_boundary(self):
        # 599.9s < 600 → closed
        assert gate_open(0, 599.9, 600, pending=1) is False
        # 600.0s ≥ 600 → open
        assert gate_open(0, 600.0, 600, pending=1) is True


# -- window_tally ------------------------------------------------------------

class TestWindowTally:
    def test_empty_history(self):
        assert window_tally([], "2026-01-01T00:00:00") == {}

    def test_none_history(self):
        assert window_tally(None, "2026-01-01T00:00:00") == {}

    def test_counts_by_kind(self):
        history = [
            {"at": "2026-10-18T09:01:00", "kind": "note"},
            {"at": "2026-10-18T09:02:00", "kind": "note"},
            {"at": "2026-10-18T09:03:00", "kind": "thought"},
        ]
        tally = window_tally(history, "2026-10-18T09:00:00")
        assert tally == {"note": 2, "thought": 1}

    def test_filters_before_since_iso(self):
        history = [
            {"at": "2026-10-18T08:59:00", "kind": "note"},
            {"at": "2026-10-18T09:01:00", "kind": "note"},
        ]
        tally = window_tally(history, "2026-10-18T09:00:00")
        assert tally == {"note": 1}

    def test_excludes_exact_boundary(self):
        # at <= since_iso is excluded
        history = [
            {"at": "2026-10-18T09:00:00", "kind": "note"},
            {"at": "2026-10-18T09:00:01", "kind": "note"},
        ]
        tally = window_tally(history, "2026-10-18T09:00:00")
        assert tally == {"note": 1}

    def test_since_iso_none_includes_all(self):
        history = [
            {"at": "2020-01-01T00:00:00", "kind": "note"},
            {"at": "2026-10-18T09:00:00", "kind": "thought"},
        ]
        tally = window_tally(history, None)
        assert tally == {"note": 1, "thought": 1}

    def test_skips_non_dict_entries(self):
        history = ["not a dict", 42, None, {"at": "2026-10-18T09:01:00", "kind": "note"}]
        tally = window_tally(history, "2026-10-18T09:00:00")
        assert tally == {"note": 1}

    def test_skips_entries_missing_at(self):
        history = [{"kind": "note"}, {"at": "2026-10-18T09:01:00", "kind": "note"}]
        tally = window_tally(history, "2026-10-18T09:00:00")
        assert tally == {"note": 1}

    def test_skips_entries_missing_kind(self):
        history = [{"at": "2026-10-18T09:01:00"}]
        tally = window_tally(history, "2026-10-18T09:00:00")
        assert tally == {}

    def test_skips_non_string_at(self):
        history = [{"at": 12345, "kind": "note"}]
        tally = window_tally(history, None)
        assert tally == {}

    def test_skips_non_string_kind(self):
        history = [{"at": "2026-10-18T09:01:00", "kind": 42}]
        tally = window_tally(history, None)
        assert tally == {}


# -- subject -----------------------------------------------------------------

class TestSubject:
    def test_basic_ordering_by_count_desc(self):
        tally = {"note": 3, "thought": 1, "devlog": 2}
        result = subject(tally, 600)
        assert result.startswith("batch: note x3, devlog x2, thought x1")

    def test_alphabetical_tiebreak(self):
        tally = {"beta": 2, "alpha": 2}
        result = subject(tally, 600)
        # same count → alphabetical order
        assert "alpha x2, beta x2" in result

    def test_includes_window_suffix(self):
        tally = {"note": 1}
        result = subject(tally, 600)
        assert result.endswith("(10 min)")

    def test_one_minute_window(self):
        tally = {"note": 1}
        result = subject(tally, 60)
        assert result.endswith("(1 min)")

    def test_silence_with_no_pending(self):
        result = subject({}, 600, pending=0)
        assert result == "quiet batch: nothing new in 10 min"

    def test_silence_with_pending_shows_fallback(self):
        result = subject({}, 600, pending=5)
        assert "5 file(s) changed" in result
        assert "strokes unrecorded" in result

    def test_none_tally_with_pending(self):
        result = subject(None, 600, pending=2)
        assert "2 file(s) changed" in result

    def test_zero_count_tally_treated_as_silence(self):
        result = subject({"note": 0, "thought": 0}, 600, pending=0)
        assert "quiet batch" in result

    def test_truncation_drops_whole_items(self):
        # Build a tally that would overflow SUBJECT_LIMIT
        tally = {f"kind_{i:02d}": 10 - i for i in range(8)}
        result = subject(tally, 600)
        assert len(result) <= SUBJECT_LIMIT

    def test_truncation_uses_more_suffix(self):
        tally = {f"kind_{i:02d}": 100 - i for i in range(10)}
        result = subject(tally, 600)
        assert "more x" in result
        assert len(result) <= SUBJECT_LIMIT

    def test_single_long_item_is_kept_clipped(self):
        tally = {"a_very_long_kind_name_that_exceeds_the_limit_on_its_own": 1}
        result = subject(tally, 600)
        assert len(result) <= SUBJECT_LIMIT
        # The item should still be present (not dropped entirely)
        assert "a_very_long" in result

    def test_exactly_at_limit_no_truncation(self):
        # Craft a tally that produces a string exactly at or under the limit
        tally = {"n": 1}
        result = subject(tally, 600)
        # "batch: n x1 (10 min)" = 22 chars, well under 72
        assert len(result) <= SUBJECT_LIMIT
        assert "more" not in result

    def test_string_counts_handled(self):
        # subject() calls int() on counts, so string counts should work
        tally = {"note": "3", "thought": "1"}
        result = subject(tally, 600)
        assert "note x3" in result
        assert "thought x1" in result


# -- _window -----------------------------------------------------------------

class TestWindow:
    def test_sixty_seconds_is_one_min(self):
        assert _window(60) == "1 min"

    def test_thirty_seconds_rounds_to_one(self):
        assert _window(30) == "1 min"

    def test_six_hundred_seconds_is_ten_min(self):
        assert _window(600) == "10 min"

    def test_zero_clamps_to_one(self):
        assert _window(0) == "1 min"

    def test_ninety_seconds_rounds_to_two(self):
        assert _window(90) == "2 min"

    def test_string_seconds_handled(self):
        # _window calls int() on the argument
        assert _window("600") == "10 min"
