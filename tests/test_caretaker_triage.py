#!/usr/bin/env python3
"""Tests for iamai.caretaker_triage — caretaker decision engine."""

from __future__ import annotations

import pytest

from iamai.caretaker_triage import (
    Decision,
    Priority,
    TriageReport,
    triage,
)


# ---------------------------------------------------------------------------
# Fixtures — common signal dicts
# ---------------------------------------------------------------------------

def _healthy_signals() -> dict:
    """Everything is fine."""
    return {
        "writer_alive": True,
        "batch_alive": True,
        "stall_class": "NONE",
        "drift_class": "tight",
        "uncommitted": 0,
        "unpushed": 0,
        "loop_severity": "NONE",
        "uptime_s": 3600,
    }


def _dead_writer_signals() -> dict:
    """Writer and batch both dead, backlog pending."""
    return {
        "writer_alive": False,
        "batch_alive": False,
        "stall_class": "SEVERE",
        "drift_class": "hot",
        "uncommitted": 7,
        "unpushed": 1,
        "loop_severity": "NONE",
        "uptime_s": 0,
    }


def _severe_stall_signals() -> dict:
    """Writer alive but severely degraded."""
    return {
        "writer_alive": True,
        "batch_alive": True,
        "stall_class": "SEVERE",
        "drift_class": "hot",
        "uncommitted": 0,
        "unpushed": 0,
        "loop_severity": "NONE",
        "uptime_s": 7200,
    }


def _mild_issues_signals() -> dict:
    """Minor issues — a few uncommitted files, warm drift."""
    return {
        "writer_alive": True,
        "batch_alive": True,
        "stall_class": "NONE",
        "drift_class": "warm",
        "uncommitted": 3,
        "unpushed": 1,
        "loop_severity": "NONE",
        "uptime_s": 1800,
    }


# ---------------------------------------------------------------------------
# TriageReport dataclass
# ---------------------------------------------------------------------------

class TestTriageReport:
    """TriageReport structure and helpers."""

    def test_empty_report_defaults(self):
        r = TriageReport()
        assert r.decisions == []
        assert r.actions() == []
        assert r.top_action() is None

    def test_triage_healthy_produces_healthy_report(self):
        r = triage(_healthy_signals())
        assert r.healthy is True

    def test_healthy_flag_false_when_critical(self):
        r = triage(_dead_writer_signals())
        assert r.healthy is False

    def test_healthy_flag_true_when_only_info(self):
        signals = _healthy_signals()
        signals["uptime_s"] = 60  # recent restart → INFO only
        r = triage(signals)
        assert r.healthy is True

    def test_actions_sorted_by_priority(self):
        r = triage(_dead_writer_signals())
        actions = r.actions()
        priorities = [a.priority for a in actions]
        assert priorities == sorted(priorities)

    def test_top_action_is_most_urgent(self):
        r = triage(_dead_writer_signals())
        top = r.top_action()
        assert top is not None
        assert top.priority == Priority.CRITICAL

    def test_summary_healthy(self):
        r = triage(_healthy_signals())
        assert "HEALTHY" in r.summary()

    def test_summary_contains_top_action(self):
        r = triage(_dead_writer_signals())
        s = r.summary()
        assert "RESTART_WRITER" in s

    def test_summary_limits_to_three_actions(self):
        r = triage(_dead_writer_signals())
        # summary should contain at most 3 pipe-separated parts
        parts = r.summary().split(" | ")
        assert len(parts) <= 3


# ---------------------------------------------------------------------------
# Decision dataclass
# ---------------------------------------------------------------------------

class TestDecision:
    """Decision string representation."""

    def test_str_format(self):
        d = Decision("PUSH", Priority.MEDIUM, "1 commit not pushed")
        s = str(d)
        assert "PUSH" in s
        assert "MEDIUM" in s
        assert "not pushed" in s

    def test_frozen(self):
        d = Decision("PUSH", Priority.MEDIUM, "reason")
        with pytest.raises(AttributeError):
            d.action = "OTHER"


# ---------------------------------------------------------------------------
# Priority enum
# ---------------------------------------------------------------------------

class TestPriority:
    """Priority ordering."""

    def test_critical_less_than_info(self):
        assert Priority.CRITICAL < Priority.INFO

    def test_ordering(self):
        assert Priority.CRITICAL < Priority.HIGH < Priority.MEDIUM < Priority.LOW < Priority.INFO


# ---------------------------------------------------------------------------
# triage() — critical scenarios
# ---------------------------------------------------------------------------

class TestTriageCritical:
    """CRITICAL priority decisions."""

    def test_dead_writer_triggers_restart(self):
        r = triage(_dead_writer_signals())
        actions = r.actions()
        assert any(d.action == "RESTART_WRITER" for d in actions)
        assert actions[0].action == "RESTART_WRITER"
        assert actions[0].priority == Priority.CRITICAL

    def test_severe_stall_hot_drift_triggers_restart(self):
        r = triage(_severe_stall_signals())
        restarts = [d for d in r.actions() if d.action == "RESTART_WRITER"]
        assert len(restarts) == 1
        assert restarts[0].priority == Priority.CRITICAL

    def test_dead_writer_and_batch_both_restart(self):
        r = triage(_dead_writer_signals())
        actions = [d.action for d in r.actions()]
        assert "RESTART_WRITER" in actions
        assert "RESTART_BATCH" in actions

    def test_writer_before_batch_in_priority(self):
        r = triage(_dead_writer_signals())
        actions = r.actions()
        writer_idx = next(i for i, d in enumerate(actions) if d.action == "RESTART_WRITER")
        batch_idx = next(i for i, d in enumerate(actions) if d.action == "RESTART_BATCH")
        assert writer_idx < batch_idx


# ---------------------------------------------------------------------------
# triage() — high priority
# ---------------------------------------------------------------------------

class TestTriageHigh:
    """HIGH priority decisions."""

    def test_batch_dead_writer_alive(self):
        signals = _healthy_signals()
        signals["batch_alive"] = False
        r = triage(signals)
        batch_restarts = [d for d in r.actions() if d.action == "RESTART_BATCH"]
        assert len(batch_restarts) == 1
        assert batch_restarts[0].priority == Priority.HIGH

    def test_backlog_exceeds_threshold(self):
        signals = _healthy_signals()
        signals["uncommitted"] = 8
        r = triage(signals)
        commits = [d for d in r.actions() if d.action == "COMMIT_BACKLOG"]
        assert len(commits) == 1
        assert commits[0].priority == Priority.HIGH

    def test_severe_loop_is_high(self):
        signals = _healthy_signals()
        signals["loop_severity"] = "SEVERE"
        r = triage(signals)
        loops = [d for d in r.actions() if d.action == "BREAK_LOOP"]
        assert len(loops) == 1
        assert loops[0].priority == Priority.HIGH


# ---------------------------------------------------------------------------
# triage() — medium priority
# ---------------------------------------------------------------------------

class TestTriageMedium:
    """MEDIUM priority decisions."""

    def test_small_backlog_is_medium(self):
        signals = _healthy_signals()
        signals["uncommitted"] = 3
        r = triage(signals)
        commits = [d for d in r.actions() if d.action == "COMMIT_BACKLOG"]
        assert len(commits) == 1
        assert commits[0].priority == Priority.MEDIUM

    def test_unpushed_commits(self):
        signals = _healthy_signals()
        signals["unpushed"] = 2
        r = triage(signals)
        pushes = [d for d in r.actions() if d.action == "PUSH"]
        assert len(pushes) == 1
        assert pushes[0].priority == Priority.MEDIUM

    def test_moderate_loop_is_medium(self):
        signals = _healthy_signals()
        signals["loop_severity"] = "MODERATE"
        r = triage(signals)
        loops = [d for d in r.actions() if d.action == "BREAK_LOOP"]
        assert len(loops) == 1
        assert loops[0].priority == Priority.MEDIUM

    def test_hot_drift_writer_alive(self):
        signals = _healthy_signals()
        signals["drift_class"] = "hot"
        r = triage(signals)
        drifts = [d for d in r.actions() if d.action == "INVESTIGATE_DRIFT"]
        assert len(drifts) == 1
        assert drifts[0].priority == Priority.MEDIUM


# ---------------------------------------------------------------------------
# triage() — low priority & info
# ---------------------------------------------------------------------------

class TestTriageLow:
    """LOW and INFO priority decisions."""

    def test_warm_drift_is_low(self):
        r = triage(_mild_issues_signals())
        drifts = [d for d in r.actions() if d.action == "INVESTIGATE_DRIFT"]
        assert len(drifts) == 1
        assert drifts[0].priority == Priority.LOW

    def test_recent_restart_is_info(self):
        signals = _healthy_signals()
        signals["uptime_s"] = 120
        r = triage(signals)
        monitors = [d for d in r.actions() if d.action == "MONITOR"]
        assert len(monitors) == 1
        assert monitors[0].priority == Priority.INFO
        assert "120s" in monitors[0].reason

    def test_old_restart_no_monitor(self):
        signals = _healthy_signals()
        signals["uptime_s"] = 7200
        r = triage(signals)
        monitors = [d for d in r.actions() if d.action == "MONITOR"]
        assert len(monitors) == 0


# ---------------------------------------------------------------------------
# triage() — healthy / no action
# ---------------------------------------------------------------------------

class TestTriageHealthy:
    """Healthy scenarios produce minimal or no actions."""

    def test_perfectly_healthy(self):
        r = triage(_healthy_signals())
        assert r.healthy is True
        assert r.top_action() is None

    def test_healthy_summary(self):
        r = triage(_healthy_signals())
        assert "HEALTHY" in r.summary()

    def test_only_info_means_healthy(self):
        signals = _healthy_signals()
        signals["uptime_s"] = 30
        r = triage(signals)
        assert r.healthy is True  # only INFO-level decisions


# ---------------------------------------------------------------------------
# triage() — edge cases
# ---------------------------------------------------------------------------

class TestTriageEdgeCases:
    """Edge cases and missing signals."""

    def test_empty_signals_uses_defaults(self):
        r = triage({})
        assert r.healthy is True  # all defaults are benign

    def test_partial_signals(self):
        r = triage({"writer_alive": False})
        assert not r.healthy
        assert any(d.action == "RESTART_WRITER" for d in r.actions())

    def test_custom_threshold(self):
        signals = _healthy_signals()
        signals["uncommitted"] = 2
        signals["uncommitted_threshold"] = 1
        r = triage(signals)
        commits = [d for d in r.actions() if d.action == "COMMIT_BACKLOG"]
        assert commits[0].priority == Priority.HIGH

    def test_no_loop_mild_or_none(self):
        signals = _healthy_signals()
        signals["loop_severity"] = "MILD"
        r = triage(signals)
        loops = [d for d in r.actions() if d.action == "BREAK_LOOP"]
        assert len(loops) == 0  # MILD does not trigger action

    def test_none_loop_severity(self):
        signals = _healthy_signals()
        signals["loop_severity"] = "NONE"
        r = triage(signals)
        loops = [d for d in r.actions() if d.action == "BREAK_LOOP"]
        assert len(loops) == 0

    def test_uptime_zero_no_monitor(self):
        """uptime_s == 0 means not recently restarted, no MONITOR."""
        r = triage(_healthy_signals())
        monitors = [d for d in r.actions() if d.action == "MONITOR"]
        assert len(monitors) == 0


# ---------------------------------------------------------------------------
# triage() — complex multi-signal scenarios
# ---------------------------------------------------------------------------

class TestTriageComplex:
    """Realistic multi-signal scenarios."""

    def test_typical_caretaker_arrival(self):
        """Writer dead, batch dead, backlog, unpushed — common scenario."""
        signals = {
            "writer_alive": False,
            "batch_alive": False,
            "stall_class": "SEVERE",
            "drift_class": "hot",
            "uncommitted": 7,
            "unpushed": 1,
            "loop_severity": "MILD",
            "uptime_s": 0,
        }
        r = triage(signals)
        assert not r.healthy
        actions = r.actions()
        # RESTART_WRITER should be first
        assert actions[0].action == "RESTART_WRITER"
        # Should also have RESTART_BATCH, COMMIT_BACKLOG, PUSH
        action_names = [d.action for d in actions]
        assert "RESTART_BATCH" in action_names
        assert "COMMIT_BACKLOG" in action_names
        assert "PUSH" in action_names

    def test_degraded_but_running(self):
        """Writer alive but struggling — loop + warm drift + small backlog."""
        signals = {
            "writer_alive": True,
            "batch_alive": True,
            "stall_class": "MILD",
            "drift_class": "warm",
            "uncommitted": 4,
            "unpushed": 2,
            "loop_severity": "MODERATE",
            "uptime_s": 600,
        }
        r = triage(signals)
        action_names = [d.action for d in r.actions()]
        assert "BREAK_LOOP" in action_names
        assert "COMMIT_BACKLOG" in action_names
        assert "PUSH" in action_names
        assert "INVESTIGATE_DRIFT" in action_names
        # No restart needed
        assert "RESTART_WRITER" not in action_names

    def test_only_batch_dead(self):
        """Writer is fine, only batch committer died."""
        signals = {
            "writer_alive": True,
            "batch_alive": False,
            "stall_class": "NONE",
            "drift_class": "tight",
            "uncommitted": 6,
            "unpushed": 0,
            "loop_severity": "NONE",
            "uptime_s": 3600,
        }
        r = triage(signals)
        actions = r.actions()
        # RESTART_BATCH should be present and HIGH
        batch_actions = [d for d in actions if d.action == "RESTART_BATCH"]
        assert len(batch_actions) == 1
        assert batch_actions[0].priority == Priority.HIGH
        # No writer restart
        assert not any(d.action == "RESTART_WRITER" for d in actions)

    def test_all_signals_benign_except_uptime(self):
        """Everything fine but just restarted — should still be healthy."""
        signals = {
            "writer_alive": True,
            "batch_alive": True,
            "stall_class": "NONE",
            "drift_class": "tight",
            "uncommitted": 0,
            "unpushed": 0,
            "loop_severity": "NONE",
            "uptime_s": 45,
        }
        r = triage(signals)
        assert r.healthy is True
        # Has INFO-level MONITOR
        monitors = [d for d in r.actions() if d.action == "MONITOR"]
        assert len(monitors) == 1
