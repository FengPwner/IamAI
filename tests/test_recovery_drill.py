"""Tests for iamai.recovery_drill."""

import pytest

from iamai.recovery_drill import (
    DrillResult,
    DrillStep,
    ScenarioTick,
    default_scenario,
    run_drill,
)
from iamai.recovery_coordinator import (
    RecoveryAction,
    RecoveryCoordinator,
    default_coordinator,
)


# ---------------------------------------------------------------------------
# DrillStep
# ---------------------------------------------------------------------------

class TestDrillStep:
    def test_to_dict_basic(self):
        step = DrillStep(
            tick_index=0,
            health=0.9,
            strokes=["hello"],
            expected_action=RecoveryAction.CONTINUE,
            actual_action=RecoveryAction.CONTINUE,
            breaker_state="closed",
            passed=True,
            note="test",
        )
        d = step.to_dict()
        assert d["tick_index"] == 0
        assert d["health"] == 0.9
        assert d["expected_action"] == "continue"
        assert d["actual_action"] == "continue"
        assert d["passed"] is True

    def test_to_dict_none_actions(self):
        step = DrillStep(tick_index=0, health=0.5, strokes=[])
        d = step.to_dict()
        assert d["expected_action"] is None
        assert d["actual_action"] is None


# ---------------------------------------------------------------------------
# DrillResult
# ---------------------------------------------------------------------------

class TestDrillResult:
    def test_to_dict(self):
        result = DrillResult(
            passed=True,
            steps=[],
            failures=[],
            total_ticks=0,
            actions_seen=[],
            duration_ms=1.5,
        )
        d = result.to_dict()
        assert d["passed"] is True
        assert d["steps"] == []
        assert d["duration_ms"] == 1.5

    def test_summary_pass(self):
        result = DrillResult(
            passed=True,
            steps=[],
            total_ticks=10,
            actions_seen=["continue", "pause"],
            duration_ms=42.3,
        )
        s = result.summary()
        assert "PASS" in s
        assert "10 ticks" in s
        assert "continue → pause" in s

    def test_summary_fail(self):
        result = DrillResult(
            passed=False,
            steps=[],
            failures=["tick 5: expected pause, got continue"],
            total_ticks=10,
            actions_seen=[],
            duration_ms=0.0,
        )
        s = result.summary()
        assert "FAIL" in s
        assert "1 failure(s)" in s


# ---------------------------------------------------------------------------
# default_scenario
# ---------------------------------------------------------------------------

class TestDefaultScenario:
    def test_returns_list(self):
        scenario = default_scenario()
        assert isinstance(scenario, list)
        assert len(scenario) > 0

    def test_all_are_scenario_ticks(self):
        for tick in default_scenario():
            assert isinstance(tick, ScenarioTick)

    def test_has_healthy_phase(self):
        scenario = default_scenario()
        healthy = [t for t in scenario if t.health > 0.5]
        assert len(healthy) >= 3

    def test_has_degradation_phase(self):
        scenario = default_scenario()
        bad = [t for t in scenario if t.health < 0.5]
        assert len(bad) >= 3

    def test_total_tick_count(self):
        scenario = default_scenario()
        # 3 healthy + 3 degradation + 4 cooldown + 2 probe + 4 recovered = 16
        assert len(scenario) == 16


# ---------------------------------------------------------------------------
# run_drill — default scenario
# ---------------------------------------------------------------------------

class TestRunDrillDefault:
    def test_passes(self):
        result = run_drill()
        assert result.passed, f"drill failed: {result.failures}"

    def test_has_steps(self):
        result = run_drill()
        assert len(result.steps) == 16

    def test_total_ticks(self):
        result = run_drill()
        assert result.total_ticks == 16

    def test_no_failures(self):
        result = run_drill()
        assert result.failures == []

    def test_actions_seen_nonempty(self):
        result = run_drill()
        assert len(result.actions_seen) == 16

    def test_starts_with_continue(self):
        result = run_drill()
        assert result.actions_seen[0] == "continue"

    def test_ends_with_continue(self):
        result = run_drill()
        assert result.actions_seen[-1] == "continue"

    def test_contains_pause(self):
        result = run_drill()
        assert "pause" in result.actions_seen

    def test_contains_wait(self):
        result = run_drill()
        assert "wait" in result.actions_seen

    def test_contains_probe(self):
        result = run_drill()
        assert "probe" in result.actions_seen

    def test_duration_recorded(self):
        result = run_drill()
        assert result.duration_ms >= 0

    def test_summary_readable(self):
        result = run_drill()
        s = result.summary()
        assert "PASS" in s
        assert "16 ticks" in s

    def test_action_sequence_exact(self):
        result = run_drill()
        expected = [
            "continue", "continue", "continue",   # healthy
            "continue", "continue", "pause",       # degradation
            "wait", "wait", "wait", "wait",         # cooldown
            "probe", "probe",                       # half-open
            "continue", "continue", "continue", "continue",  # recovered
        ]
        assert result.actions_seen == expected


# ---------------------------------------------------------------------------
# run_drill — custom scenario
# ---------------------------------------------------------------------------

class TestRunDrillCustom:
    def test_all_healthy(self):
        scenario = [
            ScenarioTick(
                health=0.9,
                strokes=["good stuff"],
                expect_action=RecoveryAction.CONTINUE,
                expect_state="closed",
            )
            for _ in range(5)
        ]
        result = run_drill(scenario=scenario)
        assert result.passed
        assert result.total_ticks == 5
        assert all(a == "continue" for a in result.actions_seen)

    def test_wrong_expectation_causes_failure(self):
        scenario = [
            ScenarioTick(
                health=0.9,
                strokes=["good"],
                expect_action=RecoveryAction.PAUSE,  # wrong!
                expect_state="closed",
            ),
        ]
        result = run_drill(scenario=scenario)
        assert not result.passed
        assert len(result.failures) == 1
        assert "expected pause" in result.failures[0]

    def test_custom_coordinator(self):
        coord = default_coordinator(trip_after=2, cooldown_ticks=3)
        scenario = [
            # healthy
            ScenarioTick(health=0.9, strokes=["a"], expect_action=RecoveryAction.CONTINUE),
            # 2 bad ticks trip the breaker (trip_after=2)
            ScenarioTick(health=0.1, strokes=["b"], expect_action=RecoveryAction.CONTINUE),
            ScenarioTick(health=0.1, strokes=["b"], expect_action=RecoveryAction.PAUSE),
            # cooldown (cooldown_ticks=3: 2 WAIT + 1 PROBE)
            ScenarioTick(health=0.1, strokes=["b"], expect_action=RecoveryAction.WAIT),
            ScenarioTick(health=0.1, strokes=["b"], expect_action=RecoveryAction.WAIT),
            ScenarioTick(health=0.1, strokes=["b"], expect_action=RecoveryAction.PROBE),
            # probe with good health (probe_window=2)
            ScenarioTick(health=0.9, strokes=["c"], expect_action=RecoveryAction.PROBE),
            # recovery
            ScenarioTick(health=0.9, strokes=["c"], expect_action=RecoveryAction.CONTINUE),
        ]
        result = run_drill(scenario=scenario, coordinator=coord)
        assert result.passed, f"failed: {result.failures}"

    def test_empty_scenario(self):
        result = run_drill(scenario=[])
        assert result.passed
        assert result.total_ticks == 0

    def test_none_expectation_skips_check(self):
        scenario = [
            ScenarioTick(
                health=0.9,
                strokes=["ok"],
                expect_action=None,  # no check
            ),
        ]
        result = run_drill(scenario=scenario)
        assert result.passed

    def test_wrong_state_expectation_causes_failure(self):
        scenario = [
            ScenarioTick(
                health=0.9,
                strokes=["good"],
                expect_action=RecoveryAction.CONTINUE,
                expect_state="open",  # wrong! should be closed
            ),
        ]
        result = run_drill(scenario=scenario)
        assert not result.passed
        assert any("state" in f for f in result.failures)


# ---------------------------------------------------------------------------
# run_drill — parameter overrides
# ---------------------------------------------------------------------------

class TestRunDrillOverrides:
    def test_trip_after_override(self):
        # With trip_after=1, a single bad tick should trip
        scenario = [
            ScenarioTick(health=0.9, strokes=["a"], expect_action=RecoveryAction.CONTINUE),
            ScenarioTick(health=0.1, strokes=["b"], expect_action=RecoveryAction.PAUSE),
        ]
        result = run_drill(
            scenario=scenario,
            trip_after=1,
            cooldown_ticks=1,
        )
        assert result.passed, f"failed: {result.failures}"

    def test_health_threshold_override(self):
        # With threshold=0.8, even 0.7 health is "bad"
        scenario = [
            ScenarioTick(health=0.9, strokes=["a"], expect_action=RecoveryAction.CONTINUE),
            ScenarioTick(health=0.7, strokes=["b"], expect_action=RecoveryAction.CONTINUE),
            ScenarioTick(health=0.7, strokes=["b"], expect_action=RecoveryAction.CONTINUE),
            ScenarioTick(health=0.7, strokes=["b"], expect_action=RecoveryAction.PAUSE),
        ]
        result = run_drill(
            scenario=scenario,
            trip_after=3,
            health_threshold=0.8,
        )
        assert result.passed, f"failed: {result.failures}"


# ---------------------------------------------------------------------------
# Integration: drill result serialisation
# ---------------------------------------------------------------------------

class TestDrillSerialisation:
    def test_result_to_dict_roundtrip(self):
        result = run_drill()
        d = result.to_dict()
        assert d["passed"] is True
        assert len(d["steps"]) == 16
        assert isinstance(d["steps"][0], dict)
        assert "tick_index" in d["steps"][0]

    def test_all_steps_have_actions(self):
        result = run_drill()
        for step in result.steps:
            assert step.actual_action is not None
