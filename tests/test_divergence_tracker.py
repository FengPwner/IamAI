"""Tests for iamai.divergence_tracker."""

import pytest
from datetime import datetime, timezone

from iamai.divergence_tracker import DivergenceTracker


class TestInit:
    def test_default_max_history(self):
        t = DivergenceTracker()
        assert t._max_history == 1000

    def test_custom_max_history(self):
        t = DivergenceTracker(max_history=50)
        assert t._max_history == 50

    def test_invalid_max_history(self):
        with pytest.raises(ValueError, match="max_history must be >= 1"):
            DivergenceTracker(max_history=0)

    def test_initial_state(self):
        t = DivergenceTracker()
        assert t.total() == 0
        assert t.streak() == 0
        assert t.longest_streak() == 0
        assert t.clean_pushes() == 0


class TestRecord:
    def test_single_event(self):
        t = DivergenceTracker()
        t.record("merge")
        assert t.total() == 1

    def test_multiple_events(self):
        t = DivergenceTracker()
        t.record("merge")
        t.record("rebase")
        t.record("merge")
        assert t.total() == 3

    def test_empty_resolution_rejected(self):
        t = DivergenceTracker()
        with pytest.raises(ValueError, match="non-empty string"):
            t.record("")

    def test_whitespace_resolution_rejected(self):
        t = DivergenceTracker()
        with pytest.raises(ValueError, match="non-empty string"):
            t.record("   ")

    def test_resolution_stripped(self):
        t = DivergenceTracker()
        t.record("  merge  ")
        assert t.by_resolution() == {"merge": 1}

    def test_custom_timestamp(self):
        t = DivergenceTracker()
        ts = datetime(2026, 10, 15, 4, 0, 0, tzinfo=timezone.utc)
        t.record("merge", now=ts)
        state = t.to_dict()
        assert "2026-10-15" in state["events"][0]["timestamp"]

    def test_breaks_streak(self):
        t = DivergenceTracker()
        t.mark_clean_push()
        t.mark_clean_push()
        assert t.streak() == 2
        t.record("merge")
        assert t.streak() == 0

    def test_max_history_trims(self):
        t = DivergenceTracker(max_history=3)
        for i in range(5):
            t.record(f"method_{i}")
        assert t.total() == 3
        by = t.by_resolution()
        assert "method_0" not in by
        assert "method_1" not in by
        assert "method_2" in by


class TestCleanPush:
    def test_streak_increments(self):
        t = DivergenceTracker()
        t.mark_clean_push()
        assert t.streak() == 1
        t.mark_clean_push()
        assert t.streak() == 2

    def test_longest_streak_tracked(self):
        t = DivergenceTracker()
        t.mark_clean_push()
        t.mark_clean_push()
        t.mark_clean_push()
        t.record("merge")  # breaks streak
        t.mark_clean_push()
        assert t.streak() == 1
        assert t.longest_streak() == 3

    def test_clean_pushes_total(self):
        t = DivergenceTracker()
        t.mark_clean_push()
        t.mark_clean_push()
        t.record("merge")
        t.mark_clean_push()
        assert t.clean_pushes() == 3


class TestByResolution:
    def test_counts(self):
        t = DivergenceTracker()
        t.record("merge")
        t.record("merge")
        t.record("rebase")
        t.record("force_push")
        t.record("merge")
        assert t.by_resolution() == {"merge": 3, "rebase": 1, "force_push": 1}

    def test_empty(self):
        t = DivergenceTracker()
        assert t.by_resolution() == {}


class TestDivergenceRate:
    def test_no_pushes(self):
        t = DivergenceTracker()
        assert t.divergence_rate() == 0.0

    def test_all_clean(self):
        t = DivergenceTracker()
        for _ in range(10):
            t.mark_clean_push()
        assert t.divergence_rate() == 0.0

    def test_all_divergent(self):
        t = DivergenceTracker()
        for _ in range(5):
            t.record("merge")
        assert t.divergence_rate() == 1.0

    def test_mixed(self):
        t = DivergenceTracker()
        for _ in range(3):
            t.mark_clean_push()
        t.record("merge")
        # 1 divergence out of 4 total pushes
        assert t.divergence_rate() == 0.25


class TestSummary:
    def test_keys(self):
        t = DivergenceTracker()
        t.record("merge")
        t.mark_clean_push()
        s = t.summary()
        assert "divergences" in s
        assert "clean_pushes" in s
        assert "current_streak" in s
        assert "longest_streak" in s
        assert "divergence_rate" in s
        assert "by_resolution" in s

    def test_values(self):
        t = DivergenceTracker()
        t.record("merge")
        t.record("rebase")
        t.mark_clean_push()
        s = t.summary()
        assert s["divergences"] == 2
        assert s["clean_pushes"] == 1
        assert s["current_streak"] == 1
        assert s["by_resolution"] == {"merge": 1, "rebase": 1}


class TestSerialisation:
    def test_roundtrip(self):
        t = DivergenceTracker(max_history=50)
        t.record("merge")
        t.record("rebase")
        t.mark_clean_push()
        t.mark_clean_push()
        t.record("merge")
        t.mark_clean_push()

        data = t.to_dict()
        restored = DivergenceTracker.from_dict(data)

        assert restored.total() == t.total()
        assert restored.clean_pushes() == t.clean_pushes()
        assert restored.streak() == t.streak()
        assert restored.longest_streak() == t.longest_streak()
        assert restored.by_resolution() == t.by_resolution()
        assert restored._max_history == 50

    def test_from_empty_dict(self):
        t = DivergenceTracker.from_dict({})
        assert t.total() == 0
        assert t._max_history == 1000


class TestRepr:
    def test_contains_key_info(self):
        t = DivergenceTracker()
        t.record("merge")
        t.mark_clean_push()
        r = repr(t)
        assert "DivergenceTracker" in r
        assert "divergences=1" in r
        assert "clean=1" in r
