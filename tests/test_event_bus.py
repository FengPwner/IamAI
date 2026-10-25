"""Tests for snippets/event_bus.py — minimal synchronous pub/sub dispatcher."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from event_bus import Event, EventBus  # noqa: E402


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


def test_empty_bus():
    bus = EventBus()
    assert bus.event_count == 0
    assert bus.handler_count() == 0
    assert bus.kinds() == []
    assert "EventBus" in repr(bus)


# ---------------------------------------------------------------------------
# subscribe / unsubscribe
# ---------------------------------------------------------------------------


def test_on_registers_handler():
    bus = EventBus()
    bus.on("stroke", lambda e: None)
    assert bus.handler_count("stroke") == 1
    assert "stroke" in bus.kinds()


def test_unsubscribe_via_returned_callable():
    bus = EventBus()
    unsub = bus.on("stroke", lambda e: None)
    assert bus.handler_count("stroke") == 1
    unsub()
    assert bus.handler_count("stroke") == 0


def test_off_removes_handler():
    bus = EventBus()
    handler = lambda e: None
    bus.on("stroke", handler)
    assert bus.off("stroke", handler) is True
    assert bus.handler_count("stroke") == 0


def test_off_unknown_handler_returns_false():
    bus = EventBus()
    assert bus.off("stroke", lambda e: None) is False


def test_double_unsubscribe_is_safe():
    bus = EventBus()
    handler = lambda e: None
    unsub = bus.on("stroke", handler)
    unsub()
    unsub()  # should not raise
    assert bus.handler_count("stroke") == 0


# ---------------------------------------------------------------------------
# emit — basic dispatch
# ---------------------------------------------------------------------------


def test_emit_calls_handler_with_event():
    bus = EventBus()
    received = []
    bus.on("stroke", lambda e: received.append(e))
    count = bus.emit("stroke", data={"path": "notes/foo.md"})
    assert count == 1
    assert len(received) == 1
    assert received[0].kind == "stroke"
    assert received[0].data == {"path": "notes/foo.md"}


def test_emit_with_no_handlers_returns_zero():
    bus = EventBus()
    assert bus.emit("unknown_event") == 0


def test_emit_increments_event_count():
    bus = EventBus()
    bus.on("tick", lambda e: None)
    bus.emit("tick")
    bus.emit("tick")
    bus.emit("other")
    assert bus.event_count == 3


def test_emit_preserves_source():
    bus = EventBus()
    received = []
    bus.on("restart", lambda e: received.append(e))
    bus.emit("restart", source="caretaker")
    assert received[0].source == "caretaker"


def test_emit_handler_order():
    bus = EventBus()
    order = []
    bus.on("x", lambda e: order.append("first"))
    bus.on("x", lambda e: order.append("second"))
    bus.on("x", lambda e: order.append("third"))
    bus.emit("x")
    assert order == ["first", "second", "third"]


# ---------------------------------------------------------------------------
# wildcard subscriptions
# ---------------------------------------------------------------------------


def test_wildcard_receives_all_events():
    bus = EventBus()
    received = []
    bus.on("*", lambda e: received.append(e.kind))
    bus.emit("stroke")
    bus.emit("restart")
    bus.emit("heartbeat")
    assert received == ["stroke", "restart", "heartbeat"]


def test_wildcard_handler_count_includes_specific():
    bus = EventBus()
    bus.on("*", lambda e: None)
    bus.on("stroke", lambda e: None)
    # stroke handlers = 1 specific + 1 wildcard = 2
    assert bus.handler_count("stroke") == 2
    # wildcard count alone
    assert bus.handler_count("*") == 1


def test_wildcard_not_double_dispatched_on_star_emit():
    bus = EventBus()
    count = []
    bus.on("*", lambda e: count.append(1))
    bus.emit("*")  # emitting kind="*" should not call wildcard twice
    assert len(count) == 1


# ---------------------------------------------------------------------------
# emit — exception behavior
# ---------------------------------------------------------------------------


def test_emit_raises_on_handler_exception():
    bus = EventBus()

    def bad_handler(e):
        raise ValueError("boom")

    bus.on("x", bad_handler)
    with pytest.raises(ValueError, match="boom"):
        bus.emit("x")


def test_emit_skips_remaining_on_exception():
    bus = EventBus()
    reached = []

    def bad_handler(e):
        raise RuntimeError("fail")

    def good_handler(e):
        reached.append(True)

    bus.on("x", bad_handler)
    bus.on("x", good_handler)
    with pytest.raises(RuntimeError):
        bus.emit("x")
    assert reached == []  # second handler was skipped


# ---------------------------------------------------------------------------
# emit_safe — exception collection
# ---------------------------------------------------------------------------


def test_emit_safe_collects_errors():
    bus = EventBus()

    def bad_handler(e):
        raise ValueError("oops")

    def good_handler(e):
        pass

    bus.on("x", bad_handler)
    bus.on("x", good_handler)
    count, errors = bus.emit_safe("x")
    assert count == 1  # only good_handler succeeded
    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)


def test_emit_safe_all_succeed():
    bus = EventBus()
    bus.on("x", lambda e: None)
    bus.on("x", lambda e: None)
    count, errors = bus.emit_safe("x")
    assert count == 2
    assert errors == []


def test_emit_safe_all_fail():
    bus = EventBus()
    bus.on("x", lambda e: (_ for _ in ()).throw(TypeError("a")))
    bus.on("x", lambda e: (_ for _ in ()).throw(TypeError("b")))
    count, errors = bus.emit_safe("x")
    assert count == 0
    assert len(errors) == 2


# ---------------------------------------------------------------------------
# event dataclass
# ---------------------------------------------------------------------------


def test_event_is_frozen():
    e = Event(kind="test", data=42)
    with pytest.raises(AttributeError):
        e.kind = "other"  # type: ignore[misc]


def test_event_defaults():
    e = Event(kind="test")
    assert e.data is None
    assert e.source is None


# ---------------------------------------------------------------------------
# thread safety
# ---------------------------------------------------------------------------


def test_concurrent_emits():
    bus = EventBus()
    received = []
    lock = threading.Lock()

    def handler(e):
        with lock:
            received.append(e.data)

    bus.on("tick", handler)

    threads = []
    for i in range(20):
        t = threading.Thread(target=bus.emit, args=("tick",), kwargs={"data": i})
        threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert len(received) == 20
    assert sorted(received) == list(range(20))


def test_concurrent_subscribe_and_emit():
    bus = EventBus()
    results = []
    lock = threading.Lock()

    def subscriber():
        for _ in range(10):
            bus.on("x", lambda e: None)
            time.sleep(0.001)

    def emitter():
        for _ in range(10):
            bus.emit("x", data="hello")
            time.sleep(0.001)

    threads = [
        threading.Thread(target=subscriber),
        threading.Thread(target=emitter),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    # no crash = pass


# ---------------------------------------------------------------------------
# introspection
# ---------------------------------------------------------------------------


def test_repr_format():
    bus = EventBus()
    bus.on("a", lambda e: None)
    bus.on("b", lambda e: None)
    r = repr(bus)
    assert "kinds=2" in r
    assert "handlers=2" in r
    assert "events=0" in r


def test_kinds_excludes_empty():
    bus = EventBus()
    handler = lambda e: None
    bus.on("a", handler)
    bus.on("b", lambda e: None)
    bus.off("a", handler)
    assert "a" not in bus.kinds()
    assert "b" in bus.kinds()


# ---------------------------------------------------------------------------
# docstring doctests
# ---------------------------------------------------------------------------


def test_doctest():
    import doctest
    from snippets import event_bus

    results = doctest.testmod(event_bus, verbose=False)
    assert results.failed == 0, f"{results.failed} doctest(s) failed"
