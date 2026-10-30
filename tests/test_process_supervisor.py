"""Tests for process_supervisor module."""

import pytest

from iamai.process_supervisor import (
    Decision,
    SupervisorConfig,
    SupervisorDecision,
    SupervisorState,
    evaluate,
    record_restart,
)


class TestHealthyState:
    """When everything is alive, the supervisor says healthy."""

    def test_all_alive(self):
        state = SupervisorState()
        result = evaluate(
            all_alive=True,
            dead_names=[],
            state=state,
            now=1000.0,
        )
        assert result.decision == Decision.HEALTHY
        assert result.should_restart is False
        assert "running" in result.reason.lower()

    def test_healthy_ignores_dead_list(self):
        """If all_alive is True, dead_names is ignored (defensive)."""
        state = SupervisorState()
        result = evaluate(
            all_alive=True,
            dead_names=["writer"],
            state=state,
            now=1000.0,
        )
        assert result.decision == Decision.HEALTHY


class TestRestartDecision:
    """When processes are dead and cooldown elapsed, recommend restart."""

    def test_first_death_triggers_restart(self):
        state = SupervisorState()
        result = evaluate(
            all_alive=False,
            dead_names=["writer", "batch"],
            state=state,
            now=1000.0,
        )
        assert result.decision == Decision.RESTART
        assert result.should_restart is True
        assert "writer" in result.dead_processes
        assert "batch" in result.dead_processes

    def test_restart_after_cooldown(self):
        """After cooldown elapses, another restart is recommended."""
        state = SupervisorState()
        cfg = SupervisorConfig(cooldown_seconds=60)

        # First restart at t=1000
        record_restart(state, 1000.0, "qwen", "first death")

        # At t=1070, cooldown has elapsed (60s passed)
        result = evaluate(
            all_alive=False,
            dead_names=["writer"],
            state=state,
            now=1070.0,
            config=cfg,
        )
        assert result.decision == Decision.RESTART

    def test_restart_records_dead_processes(self):
        state = SupervisorState()
        result = evaluate(
            all_alive=False,
            dead_names=["writer"],
            state=state,
            now=500.0,
        )
        assert result.dead_processes == ["writer"]


class TestWaitDecision:
    """When processes are dead but cooldown hasn't elapsed, wait."""

    def test_cooldown_blocks_restart(self):
        state = SupervisorState()
        cfg = SupervisorConfig(cooldown_seconds=300)

        # Restart at t=1000
        record_restart(state, 1000.0, "qwen", "crash")

        # At t=1100, only 100s elapsed, cooldown is 300s
        result = evaluate(
            all_alive=False,
            dead_names=["writer"],
            state=state,
            now=1100.0,
            config=cfg,
        )
        assert result.decision == Decision.WAIT
        assert result.should_restart is False
        assert result.cooldown_remaining == 200.0

    def test_cooldown_remaining_decreases(self):
        state = SupervisorState()
        cfg = SupervisorConfig(cooldown_seconds=120)

        record_restart(state, 1000.0, "qwen")

        r1 = evaluate(all_alive=False, dead_names=["writer"], state=state, now=1050.0, config=cfg)
        r2 = evaluate(all_alive=False, dead_names=["writer"], state=state, now=1080.0, config=cfg)

        assert r1.cooldown_remaining > r2.cooldown_remaining
        assert r1.cooldown_remaining == 70.0
        assert r2.cooldown_remaining == 40.0


class TestEscalateDecision:
    """When too many restarts in the window, escalate to human."""

    def test_too_many_restarts(self):
        state = SupervisorState()
        cfg = SupervisorConfig(
            cooldown_seconds=10,
            max_restarts_in_window=3,
            window_seconds=3600,
        )

        # Three restarts within the window
        record_restart(state, 1000.0, "qwen", "crash 1")
        record_restart(state, 1020.0, "qwen", "crash 2")
        record_restart(state, 1040.0, "qwen", "crash 3")

        # Fourth attempt — should escalate
        result = evaluate(
            all_alive=False,
            dead_names=["writer"],
            state=state,
            now=1060.0,
            config=cfg,
        )
        assert result.decision == Decision.ESCALATE
        assert result.restarts_in_window == 3
        assert "human" in result.reason.lower()

    def test_old_restarts_expire(self):
        """Restarts outside the window don't count."""
        state = SupervisorState()
        cfg = SupervisorConfig(
            cooldown_seconds=10,
            max_restarts_in_window=3,
            window_seconds=60,
        )

        # Three restarts, but all outside the 60s window
        record_restart(state, 1000.0, "qwen")
        record_restart(state, 1010.0, "qwen")
        record_restart(state, 1020.0, "qwen")

        # At t=1100, all three are > 60s ago
        result = evaluate(
            all_alive=False,
            dead_names=["writer"],
            state=state,
            now=1100.0,
            config=cfg,
        )
        assert result.decision == Decision.RESTART
        assert result.restarts_in_window == 0


class TestSupervisorState:
    """State management works correctly."""

    def test_empty_state(self):
        state = SupervisorState()
        assert state.last_restart_time() is None
        assert state.recent_restarts(1000.0, 3600) == []

    def test_record_restart(self):
        state = SupervisorState()
        record_restart(state, 1000.0, "qwen", "test")
        assert len(state.restarts) == 1
        assert state.restarts[0].timestamp == 1000.0
        assert state.restarts[0].writer_id == "qwen"
        assert state.restarts[0].reason == "test"

    def test_last_restart_time(self):
        state = SupervisorState()
        record_restart(state, 1000.0, "qwen")
        record_restart(state, 1500.0, "qwen")
        record_restart(state, 1200.0, "qwen")
        assert state.last_restart_time() == 1500.0

    def test_recent_restarts_filter(self):
        state = SupervisorState()
        record_restart(state, 1000.0, "qwen")
        record_restart(state, 1100.0, "qwen")
        record_restart(state, 1200.0, "qwen")

        recent = state.recent_restarts(1200.0, 150.0)
        assert len(recent) == 2  # 1100 and 1200, not 1000


class TestSupervisorConfig:
    """Config defaults and overrides."""

    def test_defaults(self):
        cfg = SupervisorConfig()
        assert cfg.cooldown_seconds == 300
        assert cfg.max_restarts_in_window == 3
        assert cfg.window_seconds == 3600

    def test_custom_values(self):
        cfg = SupervisorConfig(
            cooldown_seconds=60,
            max_restarts_in_window=5,
            window_seconds=1800,
        )
        assert cfg.cooldown_seconds == 60
        assert cfg.max_restarts_in_window == 5
        assert cfg.window_seconds == 1800


class TestDecisionProperties:
    """SupervisorDecision properties work correctly."""

    def test_should_restart_only_for_restart(self):
        restart = SupervisorDecision(decision=Decision.RESTART)
        wait = SupervisorDecision(decision=Decision.WAIT)
        healthy = SupervisorDecision(decision=Decision.HEALTHY)
        escalate = SupervisorDecision(decision=Decision.ESCALATE)

        assert restart.should_restart is True
        assert wait.should_restart is False
        assert healthy.should_restart is False
        assert escalate.should_restart is False


class TestIntegration:
    """End-to-end scenario: writer dies, restarts, dies again, cooldown kicks in."""

    def test_full_lifecycle(self):
        state = SupervisorState()
        cfg = SupervisorConfig(cooldown_seconds=60, max_restarts_in_window=3, window_seconds=3600)

        # t=0: everything healthy
        r = evaluate(True, [], state, 0.0, cfg)
        assert r.decision == Decision.HEALTHY

        # t=100: writer dies
        r = evaluate(False, ["writer"], state, 100.0, cfg)
        assert r.decision == Decision.RESTART
        record_restart(state, 100.0, "qwen", "writer died")

        # t=130: writer dies again, cooldown blocks
        r = evaluate(False, ["writer"], state, 130.0, cfg)
        assert r.decision == Decision.WAIT
        assert r.cooldown_remaining == 30.0

        # t=200: writer dies again, cooldown elapsed
        r = evaluate(False, ["writer"], state, 200.0, cfg)
        assert r.decision == Decision.RESTART
        record_restart(state, 200.0, "qwen", "writer died again")

        # t=250: dead again, cooldown blocks (50s < 60s)
        r = evaluate(False, ["writer"], state, 250.0, cfg)
        assert r.decision == Decision.WAIT

        # t=280: dead again, cooldown elapsed (80s > 60s), third restart
        r = evaluate(False, ["writer"], state, 280.0, cfg)
        assert r.decision == Decision.RESTART
        record_restart(state, 280.0, "qwen", "third crash")

        # t=350: dead again, cooldown elapsed (70s > 60s), but 3 restarts in window → escalate
        r = evaluate(False, ["writer"], state, 350.0, cfg)
        assert r.decision == Decision.ESCALATE
        assert r.restarts_in_window == 3
