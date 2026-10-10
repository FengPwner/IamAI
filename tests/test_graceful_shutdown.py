"""Tests for snippets/graceful_shutdown.py"""

import pytest
import signal
from snippets.graceful_shutdown import ShutdownCoordinator


class TestRegistration:
    def test_register_single_handler(self):
        sd = ShutdownCoordinator()
        sd.register("h1", lambda: None)
        assert len(sd._handlers) == 1
        assert sd._handlers[0].name == "h1"

    def test_register_multiple_handlers(self):
        sd = ShutdownCoordinator()
        sd.register("a", lambda: None)
        sd.register("b", lambda: None)
        sd.register("c", lambda: None)
        assert len(sd._handlers) == 3

    def test_handler_timeout_stored(self):
        sd = ShutdownCoordinator()
        sd.register("h", lambda: None, timeout=3.0)
        assert sd._handlers[0].timeout == 3.0

    def test_handler_timeout_default_none(self):
        sd = ShutdownCoordinator()
        sd.register("h", lambda: None)
        assert sd._handlers[0].timeout is None


class TestLIFOExecution:
    def test_handlers_run_in_reverse_order(self):
        order = []
        sd = ShutdownCoordinator()
        sd.register("first", lambda: order.append("first"))
        sd.register("second", lambda: order.append("second"))
        sd.register("third", lambda: order.append("third"))
        sd._run_handlers()
        assert order == ["third", "second", "first"]

    def test_single_handler_runs(self):
        called = []
        sd = ShutdownCoordinator()
        sd.register("only", lambda: called.append(True))
        sd._run_handlers()
        assert called == [True]

    def test_empty_handlers_no_error(self):
        sd = ShutdownCoordinator()
        result = sd._run_handlers()
        assert result == []


class TestErrorHandling:
    def test_failing_handler_does_not_stop_others(self):
        order = []
        sd = ShutdownCoordinator()
        sd.register("good1", lambda: order.append("good1"))
        sd.register("bad", lambda: (_ for _ in ()).throw(ValueError("boom")))
        sd.register("good2", lambda: order.append("good2"))
        sd._run_handlers()
        assert "good1" in order
        assert "good2" in order

    def test_failing_handler_still_reported_as_executed(self):
        def raiser():
            raise RuntimeError("oops")

        sd = ShutdownCoordinator()
        sd.register("fail", raiser)
        result = sd._run_handlers()
        assert result == ["fail"]


class TestShutdownFlag:
    def test_initial_state_not_requested(self):
        sd = ShutdownCoordinator()
        assert sd.shutdown_requested is False

    def test_request_shutdown_sets_flag(self):
        sd = ShutdownCoordinator()
        sd.request_shutdown()
        assert sd.shutdown_requested is True

    def test_signal_handler_sets_flag(self):
        sd = ShutdownCoordinator()
        sd.request_shutdown(signal.SIGTERM, None)
        assert sd.shutdown_requested is True


class TestShutdownNow:
    def test_shutdown_now_runs_handlers(self):
        order = []
        sd = ShutdownCoordinator()
        sd.register("x", lambda: order.append("x"))
        sd.register("y", lambda: order.append("y"))
        result = sd.shutdown_now()
        assert order == ["y", "x"]
        assert result == ["y", "x"]

    def test_shutdown_now_sets_flag(self):
        sd = ShutdownCoordinator()
        sd.register("z", lambda: None)
        sd.shutdown_now()
        assert sd.shutdown_requested is True


class TestTimeoutConfig:
    def test_default_timeout(self):
        sd = ShutdownCoordinator()
        assert sd.timeout == 10.0

    def test_custom_timeout(self):
        sd = ShutdownCoordinator(timeout=5.0)
        assert sd.timeout == 5.0

    def test_on_timeout_default_force(self):
        sd = ShutdownCoordinator()
        assert sd.on_timeout == "force"

    def test_on_timeout_custom_warn(self):
        sd = ShutdownCoordinator(on_timeout="warn")
        assert sd.on_timeout == "warn"
