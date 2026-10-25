"""Tests for iamai.reflection_trigger."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from iamai.reflection_trigger import (
    DEFAULT_INTERVAL,
    GRACE_STROKES,
    PROMPT_TEMPLATES,
    ReflectionTrigger,
    _load_state,
    _make_id,
    _save_state,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_state(tmp_path):
    """Return a temporary state file path."""
    return tmp_path / "reflection_state.json"


@pytest.fixture
def fixed_now():
    """Return a fixed datetime for deterministic tests."""
    return datetime(2026, 10, 23, 19, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def clock(fixed_now):
    """Return a callable clock that always returns fixed_now."""
    return lambda: fixed_now


@pytest.fixture
def trigger(tmp_state, clock):
    """Return a ReflectionTrigger with temp state and fixed clock."""
    return ReflectionTrigger(interval=100, state_path=tmp_state, now_fn=clock)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestMakeId:
    def test_deterministic(self):
        a = _make_id(1, 100)
        b = _make_id(1, 100)
        assert a == b

    def test_different_ranges(self):
        a = _make_id(1, 100)
        b = _make_id(101, 200)
        assert a != b

    def test_length(self):
        assert len(_make_id(1, 100)) == 16


class TestLoadSaveState:
    def test_load_missing_file(self, tmp_path):
        result = _load_state(tmp_path / "nonexistent.json")
        assert result == {"reflections": [], "prompt_index": 0}

    def test_roundtrip(self, tmp_path):
        p = tmp_path / "state.json"
        data = {"reflections": [{"id": "abc"}], "prompt_index": 3}
        _save_state(p, data)
        loaded = _load_state(p)
        assert loaded == data

    def test_load_corrupt_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not valid json!!!", encoding="utf-8")
        result = _load_state(p)
        assert result == {"reflections": [], "prompt_index": 0}

    def test_load_missing_keys(self, tmp_path):
        p = tmp_path / "partial.json"
        p.write_text("{}", encoding="utf-8")
        result = _load_state(p)
        assert "reflections" in result
        assert "prompt_index" in result


# ---------------------------------------------------------------------------
# ReflectionTrigger.__init__
# ---------------------------------------------------------------------------


class TestInit:
    def test_defaults(self, tmp_state, clock):
        t = ReflectionTrigger(state_path=tmp_state, now_fn=clock)
        assert t.interval == DEFAULT_INTERVAL
        assert t.last_triggered_stroke == 0
        assert t.reflections == []

    def test_custom_interval(self, tmp_state, clock):
        t = ReflectionTrigger(interval=50, state_path=tmp_state, now_fn=clock)
        assert t.interval == 50

    def test_invalid_interval_zero(self, tmp_state, clock):
        with pytest.raises(ValueError, match="interval must be >= 1"):
            ReflectionTrigger(interval=0, state_path=tmp_state, now_fn=clock)

    def test_invalid_interval_negative(self, tmp_state, clock):
        with pytest.raises(ValueError, match="interval must be >= 1"):
            ReflectionTrigger(interval=-5, state_path=tmp_state, now_fn=clock)

    def test_interval_one(self, tmp_state, clock):
        t = ReflectionTrigger(interval=1, state_path=tmp_state, now_fn=clock)
        assert t.interval == 1


# ---------------------------------------------------------------------------
# check()
# ---------------------------------------------------------------------------


class TestCheck:
    def test_not_due_below_interval(self, trigger):
        assert trigger.check(50) is False

    def test_due_at_exact_interval(self, trigger):
        assert trigger.check(100) is True

    def test_due_above_interval(self, trigger):
        assert trigger.check(150) is True

    def test_not_due_below_stroke_count(self, trigger):
        assert trigger.check(99) is False

    def test_not_due_after_recent_trigger(self, trigger):
        trigger.trigger(100)
        assert trigger.check(150) is False

    def test_due_again_after_interval(self, trigger):
        trigger.trigger(100)
        assert trigger.check(200) is True

    def test_interval_one_triggers_every_stroke(self, tmp_state, clock):
        t = ReflectionTrigger(interval=1, state_path=tmp_state, now_fn=clock)
        assert t.check(1) is True
        t.trigger(1)
        assert t.check(2) is True

    def test_zero_strokes(self, trigger):
        assert trigger.check(0) is False


# ---------------------------------------------------------------------------
# trigger()
# ---------------------------------------------------------------------------


class TestTrigger:
    def test_basic_trigger(self, trigger):
        ref = trigger.trigger(100)
        assert ref["stroke_from"] == 1
        assert ref["stroke_to"] == 100
        assert ref["response"] is None
        assert ref["completed_at"] is None
        assert len(ref["id"]) == 16
        assert "triggered_at" in ref
        assert "prompt" in ref

    def test_prompt_contains_count(self, trigger):
        ref = trigger.trigger(100)
        assert "100" in ref["prompt"]

    def test_sequential_trigger(self, trigger):
        r1 = trigger.trigger(100)
        assert r1["stroke_from"] == 1
        assert r1["stroke_to"] == 100

        r2 = trigger.trigger(200)
        assert r2["stroke_from"] == 101
        assert r2["stroke_to"] == 200

    def test_trigger_not_due_raises(self, trigger):
        with pytest.raises(ValueError, match="reflection not due"):
            trigger.trigger(50)

    def test_prompt_rotation(self, trigger):
        """Successive triggers use different prompt templates."""
        r1 = trigger.trigger(100)
        r2 = trigger.trigger(200)
        # With 8 templates, first two should differ
        assert r1["prompt"] != r2["prompt"]

    def test_persists_to_disk(self, trigger, tmp_state):
        trigger.trigger(100)
        assert tmp_state.exists()
        data = json.loads(tmp_state.read_text())
        assert len(data["reflections"]) == 1

    def test_id_deterministic(self, trigger):
        r1 = trigger.trigger(100)
        expected = _make_id(1, 100)
        assert r1["id"] == expected

    def test_custom_interval(self, tmp_state, clock):
        t = ReflectionTrigger(interval=50, state_path=tmp_state, now_fn=clock)
        ref = t.trigger(50)
        assert ref["stroke_from"] == 1
        assert ref["stroke_to"] == 50


# ---------------------------------------------------------------------------
# complete()
# ---------------------------------------------------------------------------


class TestComplete:
    def test_basic_complete(self, trigger):
        ref = trigger.trigger(100)
        result = trigger.complete(ref["id"], "The strongest stroke was #42.")
        assert result["response"] == "The strongest stroke was #42."
        assert result["completed_at"] is not None

    def test_complete_unknown_id_raises(self, trigger):
        trigger.trigger(100)
        with pytest.raises(KeyError, match="no reflection with id"):
            trigger.complete("nonexistent_id", "response")

    def test_double_complete_raises(self, trigger):
        ref = trigger.trigger(100)
        trigger.complete(ref["id"], "first answer")
        with pytest.raises(ValueError, match="already completed"):
            trigger.complete(ref["id"], "second answer")

    def test_complete_persists(self, trigger, tmp_state):
        ref = trigger.trigger(100)
        trigger.complete(ref["id"], "persisted answer")
        data = json.loads(tmp_state.read_text())
        assert data["reflections"][0]["response"] == "persisted answer"

    def test_complete_removes_from_pending(self, trigger):
        ref = trigger.trigger(100)
        assert len(trigger.pending()) == 1
        trigger.complete(ref["id"], "answer")
        assert len(trigger.pending()) == 0


# ---------------------------------------------------------------------------
# pending() / history()
# ---------------------------------------------------------------------------


class TestPendingHistory:
    def test_empty_initially(self, trigger):
        assert trigger.pending() == []
        assert trigger.history() == []

    def test_pending_after_trigger(self, trigger):
        trigger.trigger(100)
        assert len(trigger.pending()) == 1

    def test_history_includes_completed(self, trigger):
        ref = trigger.trigger(100)
        trigger.complete(ref["id"], "done")
        assert len(trigger.history()) == 1
        assert len(trigger.pending()) == 0

    def test_multiple_triggers(self, trigger):
        trigger.trigger(100)
        trigger.trigger(200)
        assert len(trigger.history()) == 2
        assert len(trigger.pending()) == 2

    def test_partial_completion(self, trigger):
        r1 = trigger.trigger(100)
        trigger.trigger(200)
        trigger.complete(r1["id"], "first done")
        assert len(trigger.history()) == 2
        assert len(trigger.pending()) == 1


# ---------------------------------------------------------------------------
# overdue()
# ---------------------------------------------------------------------------


class TestOverdue:
    def test_not_overdue_immediately(self, trigger):
        trigger.trigger(100)
        assert trigger.overdue(100) is False

    def test_not_overdue_within_grace(self, trigger):
        trigger.trigger(100)
        assert trigger.overdue(149) is False  # 49 < 50

    def test_overdue_beyond_grace(self, trigger):
        trigger.trigger(100)
        assert trigger.overdue(151) is True  # 51 > 50

    def test_overdue_exact_grace(self, trigger):
        trigger.trigger(100)
        assert trigger.overdue(150) is False  # exactly 50, not > 50

    def test_completed_not_overdue(self, trigger):
        ref = trigger.trigger(100)
        trigger.complete(ref["id"], "done")
        assert trigger.overdue(200) is False

    def test_custom_grace(self, trigger):
        trigger.trigger(100)
        assert trigger.overdue(110, grace=5) is True
        assert trigger.overdue(104, grace=5) is False

    def test_overdue_reflections_returns_list(self, trigger):
        r1 = trigger.trigger(100)
        trigger.trigger(200)
        overdue = trigger.overdue_reflections(200, grace=10)
        assert len(overdue) == 1
        assert overdue[0]["id"] == r1["id"]


# ---------------------------------------------------------------------------
# report() / stats()
# ---------------------------------------------------------------------------


class TestReportStats:
    def test_empty_report(self, trigger):
        r = trigger.report()
        assert "0/0 completed" in r
        assert "interval=100" in r

    def test_report_after_trigger(self, trigger):
        trigger.trigger(100)
        r = trigger.report()
        assert "0/1 completed" in r
        assert "stroke 100" in r

    def test_report_after_complete(self, trigger):
        ref = trigger.trigger(100)
        trigger.complete(ref["id"], "answer")
        r = trigger.report()
        assert "1/1 completed" in r

    def test_empty_stats(self, trigger):
        s = trigger.stats()
        assert s["total_reflections"] == 0
        assert s["completed"] == 0
        assert s["pending"] == 0
        assert s["completion_rate"] == 0.0
        assert s["avg_response_length"] == 0.0

    def test_stats_after_operations(self, trigger):
        r1 = trigger.trigger(100)
        trigger.trigger(200)
        trigger.complete(r1["id"], "a" * 50)
        s = trigger.stats()
        assert s["total_reflections"] == 2
        assert s["completed"] == 1
        assert s["pending"] == 1
        assert s["completion_rate"] == 0.5
        assert s["avg_response_length"] == 50.0


# ---------------------------------------------------------------------------
# Template management
# ---------------------------------------------------------------------------


class TestTemplates:
    def test_default_templates(self, trigger):
        assert len(trigger.all_templates) == len(PROMPT_TEMPLATES)

    def test_add_custom_template(self, trigger):
        trigger.add_prompt_template("Review your last {n} strokes critically.")
        assert len(trigger.all_templates) == len(PROMPT_TEMPLATES) + 1

    def test_template_without_placeholder_rejected(self, trigger):
        with pytest.raises(ValueError, match="must contain {n}"):
            trigger.add_prompt_template("No placeholder here.")

    def test_custom_template_used_in_rotation(self, trigger):
        custom = "Custom: review your last {n} strokes."
        trigger.add_prompt_template(custom)
        # Trigger enough times to cycle through all built-in templates
        for i in range(1, len(PROMPT_TEMPLATES) + 1):
            trigger.trigger(i * 100)
        # Next trigger should use the custom template
        ref = trigger.trigger((len(PROMPT_TEMPLATES) + 1) * 100)
        assert "Custom:" in ref["prompt"]

    def test_custom_templates_property(self, trigger):
        assert trigger.custom_templates == []
        trigger.add_prompt_template("Test {n} strokes.")
        assert len(trigger.custom_templates) == 1


# ---------------------------------------------------------------------------
# Persistence & reload
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_state_survives_reload(self, tmp_state, clock):
        t1 = ReflectionTrigger(interval=100, state_path=tmp_state, now_fn=clock)
        ref = t1.trigger(100)
        t1.complete(ref["id"], "persisted")

        t2 = ReflectionTrigger(interval=100, state_path=tmp_state, now_fn=clock)
        assert len(t2.history()) == 1
        assert t2.last_triggered_stroke == 100

    def test_reload_method(self, trigger, tmp_state):
        trigger.trigger(100)
        # Manually modify file
        data = json.loads(tmp_state.read_text())
        data["prompt_index"] = 99
        tmp_state.write_text(json.dumps(data), encoding="utf-8")
        trigger.reload()
        assert trigger._state["prompt_index"] == 99

    def test_atomic_write_no_partial(self, trigger, tmp_state):
        """Ensure .tmp file doesn't linger after save."""
        trigger.trigger(100)
        assert not (tmp_state.parent / "reflection_state.tmp").exists()
        assert tmp_state.exists()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_trigger_at_exact_boundary(self, trigger):
        """Trigger at exactly interval, then check again."""
        trigger.trigger(100)
        # Not due yet
        assert trigger.check(199) is False
        # Due at exact 2x
        assert trigger.check(200) is True

    def test_large_stroke_count(self, trigger):
        """Works with very large stroke counts."""
        for i in range(1, 11):
            trigger.trigger(i * 100)
        assert trigger.last_triggered_stroke == 1000
        assert trigger.check(1100) is True

    def test_consecutive_triggers_no_gap(self, tmp_state, clock):
        """Interval=1 means every stroke triggers."""
        t = ReflectionTrigger(interval=1, state_path=tmp_state, now_fn=clock)
        for i in range(1, 6):
            assert t.check(i) is True
            t.trigger(i)
        assert len(t.history()) == 5
        assert t.last_triggered_stroke == 5

    def test_reflections_property_returns_copy(self, trigger):
        trigger.trigger(100)
        refs = trigger.reflections
        refs.clear()
        # Original should be unaffected
        assert len(trigger.reflections) == 1

    def test_history_returns_copy(self, trigger):
        trigger.trigger(100)
        h = trigger.history()
        h.clear()
        assert len(trigger.history()) == 1
