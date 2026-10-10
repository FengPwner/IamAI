"""Tests for snippets/state_machine.py — finite-state machine with guarded transitions."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from state_machine import InvalidTransition, StateMachine  # noqa: E402


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


def _simple() -> StateMachine:
    return StateMachine(
        "idle",
        transitions={
            ("idle", "start"): "running",
            ("running", "pause"): "paused",
            ("paused", "resume"): "running",
            ("running", "stop"): "stopped",
            ("paused", "stop"): "stopped",
        },
    )


def test_initial_state():
    sm = _simple()
    assert sm.state == "idle"


def test_states_includes_all_from_table():
    sm = _simple()
    assert sm.states == frozenset({"idle", "running", "paused", "stopped"})


def test_states_includes_initial_even_if_not_in_table():
    sm = StateMachine("orphan", transitions={("a", "go"): "b"})
    assert "orphan" in sm.states


# ---------------------------------------------------------------------------
# transitions
# ---------------------------------------------------------------------------


def test_basic_transition():
    sm = _simple()
    result = sm.fire("start")
    assert result == "running"
    assert sm.state == "running"


def test_chain_transitions():
    sm = _simple()
    sm.fire("start")
    sm.fire("pause")
    assert sm.state == "paused"
    sm.fire("resume")
    assert sm.state == "running"
    sm.fire("stop")
    assert sm.state == "stopped"


def test_invalid_transition_raises():
    sm = _simple()
    with pytest.raises(InvalidTransition) as exc_info:
        sm.fire("stop")  # no transition from "idle" on "stop"
    assert exc_info.value.state == "idle"
    assert exc_info.value.event == "stop"


def test_state_unchanged_after_invalid_transition():
    sm = _simple()
    with pytest.raises(InvalidTransition):
        sm.fire("pause")
    assert sm.state == "idle"


def test_terminal_state_has_no_transitions():
    sm = _simple()
    sm.fire("start")
    sm.fire("stop")
    assert sm.allowed == set()
    with pytest.raises(InvalidTransition):
        sm.fire("start")


# ---------------------------------------------------------------------------
# allowed events
# ---------------------------------------------------------------------------


def test_allowed_from_idle():
    sm = _simple()
    assert sm.allowed == {"start"}


def test_allowed_from_running():
    sm = _simple()
    sm.fire("start")
    assert sm.allowed == {"pause", "stop"}


def test_allowed_from_paused():
    sm = _simple()
    sm.fire("start")
    sm.fire("pause")
    assert sm.allowed == {"resume", "stop"}


# ---------------------------------------------------------------------------
# reachability
# ---------------------------------------------------------------------------


def test_can_reach_direct():
    sm = _simple()
    assert sm.can_reach("running") is True


def test_can_reach_multi_hop():
    sm = _simple()
    assert sm.can_reach("stopped") is True  # idle → running → stopped


def test_cannot_reach_self_after_terminal():
    sm = _simple()
    sm.fire("start")
    sm.fire("stop")
    assert sm.can_reach("idle") is False


def test_can_reach_self():
    sm = _simple()
    assert sm.can_reach("idle") is True


# ---------------------------------------------------------------------------
# callbacks
# ---------------------------------------------------------------------------


def test_on_enter_callback():
    log = []
    sm = StateMachine(
        "idle",
        transitions={("idle", "start"): "running"},
        on_enter={"running": lambda ev, src, tgt: log.append(("enter", ev, src, tgt))},
    )
    sm.fire("start")
    assert log == [("enter", "start", "idle", "running")]


def test_on_exit_callback():
    log = []
    sm = StateMachine(
        "idle",
        transitions={("idle", "start"): "running"},
        on_exit={"idle": lambda ev, src, tgt: log.append(("exit", ev, src, tgt))},
    )
    sm.fire("start")
    assert log == [("exit", "start", "idle", "running")]


def test_exit_fires_before_enter():
    order = []
    sm = StateMachine(
        "a",
        transitions={("a", "go"): "b"},
        on_exit={"a": lambda ev, src, tgt: order.append("exit_a")},
        on_enter={"b": lambda ev, src, tgt: order.append("enter_b")},
    )
    sm.fire("go")
    assert order == ["exit_a", "enter_b"]


def test_callback_not_fired_for_unrelated_state():
    log = []
    sm = StateMachine(
        "idle",
        transitions={
            ("idle", "start"): "running",
            ("running", "stop"): "stopped",
        },
        on_enter={"stopped": lambda ev, src, tgt: log.append("entered_stopped")},
    )
    sm.fire("start")  # enters "running", not "stopped"
    assert log == []


def test_no_callback_defined_is_fine():
    sm = StateMachine("a", transitions={("a", "go"): "b"})
    result = sm.fire("go")  # no callbacks, should not raise
    assert result == "b"


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


def test_repr():
    sm = _simple()
    r = repr(sm)
    assert "idle" in r
    assert "StateMachine" in r


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


def test_self_loop_transition():
    sm = StateMachine(
        "on",
        transitions={("on", "ping"): "on", ("on", "off"): "off"},
    )
    sm.fire("ping")
    assert sm.state == "on"
    sm.fire("off")
    assert sm.state == "off"


def test_empty_transition_table():
    sm = StateMachine("idle", transitions={})
    assert sm.allowed == set()
    with pytest.raises(InvalidTransition):
        sm.fire("anything")


def test_exception_message_includes_context():
    sm = StateMachine("idle", transitions={})
    with pytest.raises(InvalidTransition, match="idle.*anything"):
        sm.fire("anything")
