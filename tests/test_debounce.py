"""Tests for snippets/debounce.py — same contract, no threads."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "snippets"))

from debounce import Debouncer  # noqa: E402


def test_suppresses_rapid_calls():
    calls = []
    d = Debouncer(lambda: calls.append(1), delay=10.0, sleep=lambda _: None)
    for _ in range(5):
        d()
    assert len(calls) == 0, "nothing should fire within the quiet window"


def test_flush_forces_pending():
    calls = []
    d = Debouncer(lambda: calls.append("fired"), delay=999.0, sleep=lambda _: None)
    d()
    d()
    assert len(calls) == 0
    d.flush()
    assert calls == ["fired"]


def test_flush_noop_when_empty():
    d = Debouncer(lambda: 42, delay=1.0, sleep=lambda _: None)
    assert d.flush() is None


def test_negative_delay_rejected():
    with pytest.raises(ValueError):
        Debouncer(lambda: None, delay=-1)


def test_returns_fn_result_after_quiet():
    # Use a fake monotonic that we control to simulate time passing.
    fake_time = [0.0]

    def fake_mono():
        return fake_time[0]

    import debounce as _mod

    original = _mod.time.monotonic
    _mod.time.monotonic = fake_mono
    try:
        d = Debouncer(lambda: "hello", delay=1.0, sleep=lambda _: None)
        d()  # t=0, pending
        fake_time[0] = 0.5
        assert d() is None  # still within window
        fake_time[0] = 2.0
        result = d()  # quiet elapsed
        assert result == "hello"
    finally:
        _mod.time.monotonic = original
