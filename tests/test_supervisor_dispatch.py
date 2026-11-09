"""Tests for snippets/supervisor_dispatch.py — escalation level → recovery strategy dispatcher."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from supervisor_dispatch import DispatchResult, SupervisorDispatch  # noqa: E402


# ---------------------------------------------------------------------------
# DispatchResult
# ---------------------------------------------------------------------------


def test_dispatch_result_ok_is_truthy():
    r = DispatchResult("restarted", True, "pid 42")
    assert bool(r) is True


def test_dispatch_result_fail_is_falsy():
    r = DispatchResult("error", False, "boom")
    assert bool(r) is False


def test_dispatch_result_frozen():
    r = DispatchResult("logged", True)
    with pytest.raises(AttributeError):
        r.action = "changed"  # type: ignore[misc]


def test_dispatch_result_default_detail_empty():
    r = DispatchResult("noop", True)
    assert r.detail == ""


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


def test_default_construction():
    d = SupervisorDispatch()
    assert d.dispatch_count == 0
    assert d.error_count == 0
    assert d.registered_levels == []


def test_construction_with_custom_default():
    def my_default(lvl, ctx):
        return DispatchResult("custom_default", True, lvl)

    d = SupervisorDispatch(default=my_default)
    result = d.dispatch("unknown_level")
    assert result.action == "custom_default"
    assert result.detail == "unknown_level"


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


def test_register_handler():
    d = SupervisorDispatch()
    d.register("yellow", lambda lvl, ctx: DispatchResult("logged", True))
    assert "yellow" in d.registered_levels


def test_register_multiple_levels():
    d = SupervisorDispatch()
    d.register("yellow", lambda lvl, ctx: DispatchResult("logged", True))
    d.register("red", lambda lvl, ctx: DispatchResult("restarted", True))
    d.register("critical", lambda lvl, ctx: DispatchResult("paged", True))
    assert d.registered_levels == ["critical", "red", "yellow"]


def test_register_replaces_existing():
    d = SupervisorDispatch()
    d.register("yellow", lambda lvl, ctx: DispatchResult("v1", True))
    d.register("yellow", lambda lvl, ctx: DispatchResult("v2", True))
    result = d.dispatch("yellow")
    assert result.action == "v2"


def test_register_none_handler_raises():
    d = SupervisorDispatch()
    with pytest.raises(ValueError, match="handler must not be None"):
        d.register("yellow", None)  # type: ignore[arg-type]


def test_register_empty_level_raises():
    d = SupervisorDispatch()
    with pytest.raises(ValueError, match="non-empty string"):
        d.register("", lambda lvl, ctx: DispatchResult("x", True))


def test_unregister_existing():
    d = SupervisorDispatch()
    d.register("yellow", lambda lvl, ctx: DispatchResult("logged", True))
    assert d.unregister("yellow") is True
    assert "yellow" not in d.registered_levels


def test_unregister_missing():
    d = SupervisorDispatch()
    assert d.unregister("nonexistent") is False


# ---------------------------------------------------------------------------
# dispatch — happy path
# ---------------------------------------------------------------------------


def test_dispatch_registered_level():
    d = SupervisorDispatch()
    d.register("yellow", lambda lvl, ctx: DispatchResult("logged", True, f"at {lvl}"))
    result = d.dispatch("yellow", {"ts": 100.0})
    assert result.action == "logged"
    assert result.ok is True
    assert result.detail == "at yellow"


def test_dispatch_unregistered_level_uses_default():
    d = SupervisorDispatch()
    result = d.dispatch("critical")
    assert result.action == "default"
    assert result.ok is True
    assert "no handler" in result.detail


def test_dispatch_increments_count():
    d = SupervisorDispatch()
    d.register("yellow", lambda lvl, ctx: DispatchResult("logged", True))
    d.dispatch("yellow")
    d.dispatch("red")
    d.dispatch("yellow")
    assert d.dispatch_count == 3


def test_dispatch_passes_context():
    d = SupervisorDispatch()
    captured = {}

    def handler(lvl, ctx):
        captured.update(ctx)
        return DispatchResult("ok", True)

    d.register("red", handler)
    d.dispatch("red", {"pid": 42, "reason": "stall"})
    assert captured["pid"] == 42
    assert captured["reason"] == "stall"


def test_dispatch_empty_context_when_none():
    d = SupervisorDispatch()

    def handler(lvl, ctx):
        assert ctx == {}
        return DispatchResult("ok", True)

    d.register("yellow", handler)
    d.dispatch("yellow")


# ---------------------------------------------------------------------------
# dispatch — error isolation
# ---------------------------------------------------------------------------


def test_handler_exception_is_caught():
    d = SupervisorDispatch()

    def boom(lvl, ctx):
        raise RuntimeError("kaboom")

    d.register("red", boom)
    result = d.dispatch("red")
    assert result.ok is False
    assert result.action == "error"
    assert "kaboom" in result.detail


def test_handler_exception_increments_error_count():
    d = SupervisorDispatch()

    def boom(lvl, ctx):
        raise ValueError("bad")

    d.register("red", boom)
    d.dispatch("red")
    d.dispatch("red")
    assert d.error_count == 2


def test_handler_exception_does_not_stop_dispatching():
    d = SupervisorDispatch()
    calls = []

    def boom(lvl, ctx):
        calls.append(lvl)
        raise RuntimeError("fail")

    d.register("red", boom)
    d.dispatch("red")
    d.dispatch("red")
    d.dispatch("red")
    assert len(calls) == 3
    assert d.dispatch_count == 3


def test_different_exception_types_reported():
    d = SupervisorDispatch()

    def handler(lvl, ctx):
        if lvl == "a":
            raise TypeError("wrong type")
        raise KeyError("missing key")

    d.register("a", handler)
    d.register("b", handler)

    r1 = d.dispatch("a")
    r2 = d.dispatch("b")
    assert "TypeError" in r1.detail
    assert "KeyError" in r2.detail


# ---------------------------------------------------------------------------
# dispatch_many
# ---------------------------------------------------------------------------


def test_dispatch_many_returns_all_results():
    d = SupervisorDispatch()
    d.register("yellow", lambda lvl, ctx: DispatchResult("logged", True))
    d.register("red", lambda lvl, ctx: DispatchResult("restarted", True))

    results = d.dispatch_many(["yellow", "red", "yellow"])
    assert len(results) == 3
    assert results[0].action == "logged"
    assert results[1].action == "restarted"
    assert results[2].action == "logged"


def test_dispatch_many_empty_list():
    d = SupervisorDispatch()
    results = d.dispatch_many([])
    assert results == []


def test_dispatch_many_shares_context():
    d = SupervisorDispatch()
    seen_contexts = []

    def handler(lvl, ctx):
        seen_contexts.append(id(ctx))
        return DispatchResult("ok", True)

    d.register("yellow", handler)
    ctx = {"batch_id": 7}
    d.dispatch_many(["yellow", "yellow"], context=ctx)
    # same context object passed both times
    assert seen_contexts[0] == seen_contexts[1]


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


def test_history_records_all_dispatches():
    d = SupervisorDispatch(clock=lambda: 42.0)
    d.register("yellow", lambda lvl, ctx: DispatchResult("logged", True))
    d.dispatch("yellow")
    d.dispatch("red")

    h = d.history
    assert len(h) == 2
    assert h[0][0] == "yellow"
    assert h[0][1].action == "logged"
    assert h[0][2] == 42.0
    assert h[1][0] == "red"
    assert h[1][1].action == "default"


def test_history_is_copy():
    d = SupervisorDispatch()
    d.dispatch("yellow")
    h1 = d.history
    h2 = d.history
    assert h1 == h2
    assert h1 is not h2


def test_history_preserved_after_unregister():
    d = SupervisorDispatch()
    d.register("yellow", lambda lvl, ctx: DispatchResult("logged", True))
    d.dispatch("yellow")
    d.unregister("yellow")
    # history still has the dispatch
    assert len(d.history) == 1
    assert d.history[0][1].action == "logged"


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------


def test_summary_clean():
    d = SupervisorDispatch()
    d.register("yellow", lambda lvl, ctx: DispatchResult("logged", True))
    d.dispatch("yellow")
    d.dispatch("yellow")

    s = d.summary()
    assert s["total"] == 2
    assert s["ok"] == 2
    assert s["errors"] == 0
    assert "yellow" in s["levels"]


def test_summary_with_errors():
    d = SupervisorDispatch()

    def boom(lvl, ctx):
        raise RuntimeError("x")

    d.register("red", boom)
    d.dispatch("red")
    d.dispatch("red")
    d.dispatch("yellow")  # default

    s = d.summary()
    assert s["total"] == 3
    assert s["ok"] == 1  # only the default "yellow"
    assert s["errors"] == 2


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


def test_reset_clears_counts_and_history():
    d = SupervisorDispatch()
    d.register("yellow", lambda lvl, ctx: DispatchResult("logged", True))
    d.dispatch("yellow")
    d.dispatch("red")

    d.reset()
    assert d.dispatch_count == 0
    assert d.error_count == 0
    assert d.history == []


def test_reset_preserves_handlers():
    d = SupervisorDispatch()
    d.register("yellow", lambda lvl, ctx: DispatchResult("logged", True))
    d.reset()
    # handler still registered
    result = d.dispatch("yellow")
    assert result.action == "logged"


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


def test_repr_contains_levels():
    d = SupervisorDispatch()
    d.register("yellow", lambda lvl, ctx: DispatchResult("x", True))
    d.register("red", lambda lvl, ctx: DispatchResult("x", True))
    r = repr(d)
    assert "yellow" in r
    assert "red" in r


def test_repr_contains_counts():
    d = SupervisorDispatch()
    d.dispatch("yellow")
    r = repr(d)
    assert "dispatches=1" in r
    assert "errors=0" in r


# ---------------------------------------------------------------------------
# integration: escalation chain scenario
# ---------------------------------------------------------------------------


def test_full_escalation_chain():
    """Simulate: yellow → log, red → restart, critical → page."""
    d = SupervisorDispatch(clock=lambda: 1.0)
    actions = []

    d.register(
        "yellow",
        lambda lvl, ctx: DispatchResult("log_warning", True, f"warn at {lvl}"),
    )
    d.register(
        "red",
        lambda lvl, ctx: DispatchResult("restart_writer", True, "restarted pid 99"),
    )
    d.register(
        "critical",
        lambda lvl, ctx: DispatchResult("page_oncall", True, "paged alice"),
    )

    # escalation progresses
    for level in ["yellow", "yellow", "red", "red", "critical"]:
        d.dispatch(level, {"escalation_count": d.dispatch_count})

    assert d.dispatch_count == 5
    assert d.error_count == 0
    assert d.history[0][1].action == "log_warning"
    assert d.history[2][1].action == "restart_writer"
    assert d.history[4][1].action == "page_oncall"


def test_mixed_success_and_failure_chain():
    d = SupervisorDispatch(clock=lambda: 2.0)

    def flaky(lvl, ctx):
        if ctx.get("attempt", 0) % 2 == 0:
            raise RuntimeError("flaky handler")
        return DispatchResult("ok", True)

    d.register("red", flaky)

    r1 = d.dispatch("red", {"attempt": 0})  # raises
    r2 = d.dispatch("red", {"attempt": 1})  # ok
    r3 = d.dispatch("red", {"attempt": 2})  # raises

    assert r1.ok is False
    assert r2.ok is True
    assert r3.ok is False
    assert d.error_count == 2
