"""Tests for iamai.note_rotation — stroke distribution tracker.

covers:
  - NOTE_SLOTS: completeness and count
  - fairness_score: uniform, skewed, empty, single slot, real distributions
  - hot_slot: normal, tie, empty
  - cold_slot: normal, tie, empty
  - RotationWindow: add, counts, maxlen eviction, unknown slot ignored
  - RotationMonitor: record, record_many, fairness, verdict states
  - RotationVerdict: str representation
  - Edge cases: single stroke, all same slot, threshold boundaries
"""

import pytest

from iamai.note_rotation import (
    NOTE_SLOTS,
    SLOT_COUNT,
    DEFAULT_WARM_THRESHOLD,
    DEFAULT_SKEW_THRESHOLD,
    RotationVerdict,
    fairness_score,
    hot_slot,
    cold_slot,
    RotationWindow,
    RotationMonitor,
)


# ─── Constants ──────────────────────────────────────────────────────


class TestConstants:
    def test_six_slots(self):
        assert SLOT_COUNT == 6

    def test_expected_slots(self):
        assert set(NOTE_SLOTS) == {
            "devlog", "garden", "metrics", "note", "snippet", "thought"
        }

    def test_slots_are_strings(self):
        for s in NOTE_SLOTS:
            assert isinstance(s, str)

    def test_thresholds_ordered(self):
        assert DEFAULT_WARM_THRESHOLD < DEFAULT_SKEW_THRESHOLD


# ─── fairness_score ─────────────────────────────────────────────────


class TestFairnessScore:
    def test_empty_counts(self):
        assert fairness_score({}) == 0.0

    def test_all_zeros(self):
        counts = {s: 0 for s in NOTE_SLOTS}
        assert fairness_score(counts) == 0.0

    def test_perfectly_uniform(self):
        counts = {s: 10 for s in NOTE_SLOTS}
        assert fairness_score(counts) == 0.0

    def test_perfectly_uniform_large(self):
        counts = {s: 1000 for s in NOTE_SLOTS}
        assert fairness_score(counts) == 0.0

    def test_maximally_skewed(self):
        """All strokes in one slot."""
        counts = {s: 0 for s in NOTE_SLOTS}
        counts["garden"] = 60
        score = fairness_score(counts)
        assert score == pytest.approx(1.0, abs=0.001)

    def test_single_stroke(self):
        """One stroke is maximally skewed."""
        counts = {s: 0 for s in NOTE_SLOTS}
        counts["devlog"] = 1
        score = fairness_score(counts)
        assert score == pytest.approx(1.0, abs=0.001)

    def test_moderate_skew(self):
        counts = {
            "devlog": 20, "garden": 10, "metrics": 10,
            "note": 10, "snippet": 5, "thought": 5,
        }
        score = fairness_score(counts)
        assert 0.0 < score < 1.0

    def test_slightly_uneven(self):
        counts = {
            "devlog": 11, "garden": 10, "metrics": 10,
            "note": 10, "snippet": 10, "thought": 9,
        }
        score = fairness_score(counts)
        assert score < 0.1  # very close to uniform

    def test_two_slots_only(self):
        counts = {s: 0 for s in NOTE_SLOTS}
        counts["devlog"] = 30
        counts["garden"] = 30
        score = fairness_score(counts)
        # Two slots equally served, four empty — moderately skewed
        assert 0.2 < score < 0.6

    def test_score_bounded(self):
        """Score always in [0, 1]."""
        import random
        random.seed(42)
        for _ in range(100):
            counts = {s: random.randint(0, 100) for s in NOTE_SLOTS}
            score = fairness_score(counts)
            assert 0.0 <= score <= 1.0

    def test_more_skewed_means_higher_score(self):
        uniform = {s: 10 for s in NOTE_SLOTS}
        skewed = {s: 10 for s in NOTE_SLOTS}
        skewed["garden"] = 30
        skewed["devlog"] = 2
        assert fairness_score(skewed) > fairness_score(uniform)


# ─── hot_slot / cold_slot ──────────────────────────────────────────


class TestHotSlot:
    def test_empty(self):
        assert hot_slot({}) is None

    def test_all_zeros(self):
        counts = {s: 0 for s in NOTE_SLOTS}
        assert hot_slot(counts) is None

    def test_single_nonzero(self):
        counts = {s: 0 for s in NOTE_SLOTS}
        counts["snippet"] = 5
        assert hot_slot(counts) == "snippet"

    def test_highest_wins(self):
        counts = {
            "devlog": 5, "garden": 20, "metrics": 10,
            "note": 3, "snippet": 15, "thought": 8,
        }
        assert hot_slot(counts) == "garden"

    def test_tie_returns_first_in_order(self):
        counts = {s: 10 for s in NOTE_SLOTS}
        # When all equal, max returns the first by NOTE_SLOTS order
        assert hot_slot(counts) == NOTE_SLOTS[0]


class TestColdSlot:
    def test_empty(self):
        assert cold_slot({}) is None

    def test_all_zeros(self):
        counts = {s: 0 for s in NOTE_SLOTS}
        assert cold_slot(counts) is None

    def test_single_nonzero(self):
        counts = {s: 0 for s in NOTE_SLOTS}
        counts["snippet"] = 5
        # All others are zero — cold slot is first zero-valued slot
        cold = cold_slot(counts)
        assert cold is not None
        assert counts[cold] == 0

    def test_lowest_wins(self):
        counts = {
            "devlog": 5, "garden": 20, "metrics": 10,
            "note": 3, "snippet": 15, "thought": 8,
        }
        assert cold_slot(counts) == "note"


# ─── RotationWindow ────────────────────────────────────────────────


class TestRotationWindow:
    def test_empty_window(self):
        w = RotationWindow(maxlen=10)
        assert len(w) == 0
        assert all(v == 0 for v in w.counts().values())

    def test_add_and_count(self):
        w = RotationWindow(maxlen=10)
        w.add("garden")
        w.add("devlog")
        w.add("garden")
        counts = w.counts()
        assert counts["garden"] == 2
        assert counts["devlog"] == 1
        assert counts["metrics"] == 0

    def test_maxlen_eviction(self):
        w = RotationWindow(maxlen=3)
        w.add("garden")
        w.add("devlog")
        w.add("metrics")
        w.add("note")  # evicts "garden"
        counts = w.counts()
        assert counts["garden"] == 0
        assert counts["devlog"] == 1
        assert counts["metrics"] == 1
        assert counts["note"] == 1

    def test_unknown_slot_ignored(self):
        w = RotationWindow(maxlen=10)
        w.add("unknown_file")
        w.add("garden")
        assert len(w) == 1
        assert w.counts()["garden"] == 1

    def test_clear(self):
        w = RotationWindow(maxlen=10)
        w.add("garden")
        w.add("devlog")
        w.clear()
        assert len(w) == 0
        assert all(v == 0 for v in w.counts().values())

    def test_maxlen_property(self):
        w = RotationWindow(maxlen=42)
        assert w.maxlen == 42

    def test_invalid_maxlen(self):
        with pytest.raises(ValueError):
            RotationWindow(maxlen=0)
        with pytest.raises(ValueError):
            RotationWindow(maxlen=-5)

    def test_counts_always_has_all_slots(self):
        w = RotationWindow(maxlen=10)
        w.add("garden")
        counts = w.counts()
        assert set(counts.keys()) == set(NOTE_SLOTS)


# ─── RotationMonitor ───────────────────────────────────────────────


class TestRotationMonitor:
    def test_fresh_monitor_balanced(self):
        mon = RotationMonitor()
        v = mon.verdict()
        assert v.balanced is True
        assert v.state == "balanced"
        assert v.fairness == 0.0

    def test_uniform_records_balanced(self):
        mon = RotationMonitor(window_size=60)
        for _ in range(10):
            for s in NOTE_SLOTS:
                mon.record(s)
        v = mon.verdict()
        assert v.balanced is True
        assert v.fairness == 0.0

    def test_skewed_records(self):
        mon = RotationMonitor(window_size=60)
        for _ in range(60):
            mon.record("garden")
        v = mon.verdict()
        assert v.balanced is False
        assert v.state == "skewed"
        assert v.fairness == pytest.approx(1.0, abs=0.001)
        assert v.hot == "garden"

    def test_warming_state(self):
        mon = RotationMonitor(window_size=60)
        # Create moderate imbalance
        picks = ["garden"] * 20 + ["devlog"] * 10 + ["metrics"] * 10
        picks += ["note"] * 8 + ["snippet"] * 6 + ["thought"] * 6
        mon.record_many(picks)
        v = mon.verdict()
        # Should be somewhere between balanced and maximally skewed
        assert 0.0 < v.fairness < 1.0

    def test_record_many(self):
        mon = RotationMonitor(window_size=100)
        picks = ["garden", "devlog", "metrics", "note", "snippet", "thought"] * 5
        mon.record_many(picks)
        assert mon.fairness() == 0.0

    def test_reset(self):
        mon = RotationMonitor()
        for _ in range(10):
            mon.record("garden")
        mon.reset()
        v = mon.verdict()
        assert v.balanced is True
        assert v.fairness == 0.0

    def test_window_property(self):
        mon = RotationMonitor(window_size=30)
        mon.record("garden")
        assert len(mon.window) == 1

    def test_custom_thresholds(self):
        # Very tight thresholds
        mon = RotationMonitor(
            window_size=60,
            warm_threshold=0.01,
            skew_threshold=0.05,
        )
        picks = ["garden"] * 12 + ["devlog"] * 10 + ["metrics"] * 10
        picks += ["note"] * 10 + ["snippet"] * 9 + ["thought"] * 9
        mon.record_many(picks)
        v = mon.verdict()
        # With tight thresholds, even slight imbalance triggers warming/skewed
        assert v.fairness > 0.0

    def test_verdict_counts_populated(self):
        mon = RotationMonitor(window_size=60)
        mon.record("garden")
        mon.record("devlog")
        mon.record("garden")
        v = mon.verdict()
        assert v.counts["garden"] == 2
        assert v.counts["devlog"] == 1
        assert sum(v.counts.values()) == 3


# ─── RotationVerdict ───────────────────────────────────────────────


class TestRotationVerdict:
    def test_balanced_str(self):
        v = RotationVerdict(
            balanced=True, state="balanced", fairness=0.05,
            hot="garden", cold="thought", counts={},
        )
        s = str(v)
        assert "balanced" in s
        assert "0.050" in s

    def test_skewed_str(self):
        v = RotationVerdict(
            balanced=False, state="skewed", fairness=0.85,
            hot="garden", cold="thought",
            counts={"garden": 50, "thought": 2},
        )
        s = str(v)
        assert "skewed" in s
        assert "garden" in s
        assert "thought" in s

    def test_warming_str(self):
        v = RotationVerdict(
            balanced=False, state="warming", fairness=0.40,
            hot="devlog", cold="note", counts={},
        )
        s = str(v)
        assert "warming" in s

    def test_frozen(self):
        v = RotationVerdict(
            balanced=True, state="balanced", fairness=0.0,
            hot=None, cold=None, counts={},
        )
        with pytest.raises(AttributeError):
            v.balanced = False  # type: ignore[misc]


# ─── Integration: realistic cadence ────────────────────────────────


class TestIntegration:
    def test_60_strokes_uniform_rotation(self):
        """Simulate 60 strokes with perfect round-robin rotation."""
        mon = RotationMonitor(window_size=60)
        for i in range(60):
            mon.record(NOTE_SLOTS[i % SLOT_COUNT])
        v = mon.verdict()
        assert v.balanced is True
        assert v.fairness == 0.0
        assert all(c == 10 for c in v.counts.values())

    def test_60_strokes_burst_on_one(self):
        """Simulate 60 strokes where one slot gets a burst."""
        mon = RotationMonitor(window_size=60)
        # First 50 all go to garden, then 10 to other slots
        for _ in range(50):
            mon.record("garden")
        for i in range(10):
            mon.record(NOTE_SLOTS[i % SLOT_COUNT])
        v = mon.verdict()
        assert v.balanced is False
        assert v.hot == "garden"

    def test_window_eviction_changes_verdict(self):
        """As old skewed data falls out, verdict should improve."""
        mon = RotationMonitor(window_size=12)
        # Fill with skewed data
        for _ in range(12):
            mon.record("garden")
        assert mon.verdict().state == "skewed"

        # Now add uniform data — old skewed data gets evicted
        for _ in range(2):
            for s in NOTE_SLOTS:
                mon.record(s)
        v = mon.verdict()
        assert v.balanced is True
        assert v.fairness == 0.0
