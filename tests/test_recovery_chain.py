#!/usr/bin/env python3
"""Tests for iamai.recovery_latency.RecoveryChain — three-phase recovery tracker."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from iamai.recovery_latency import RecoveryChain


class TestRecoveryChainCreation:
    def test_empty_chain(self):
        chain = RecoveryChain()
        assert not chain.is_complete
        assert not chain.is_degraded
        assert chain.phases_done == 0
        assert chain.total_seconds is None

    def test_default_values(self):
        chain = RecoveryChain()
        assert chain.restart_ts is None
        assert chain.backlog_ts is None
        assert chain.push_ts is None
        assert chain.backlog_files == 0
        assert chain.backlog_commit is None
        assert chain.push_remote_ref is None


class TestRecoveryChainPhases:
    def test_mark_restart(self):
        chain = RecoveryChain()
        chain.mark_restart(ts=1000.0, pid=6157)
        assert chain.restart_ts == 1000.0
        assert chain.restart_ok is True
        assert chain.restart_pid == 6157
        assert chain.phases_done == 1
        assert not chain.is_complete

    def test_mark_backlog(self):
        chain = RecoveryChain()
        chain.mark_restart(ts=1000.0)
        chain.mark_backlog(ts=1001.5, files=8, commit="920e72e")
        assert chain.backlog_ts == 1001.5
        assert chain.backlog_ok is True
        assert chain.backlog_files == 8
        assert chain.backlog_commit == "920e72e"
        assert chain.phases_done == 2
        assert not chain.is_complete

    def test_mark_push(self):
        chain = RecoveryChain()
        chain.mark_restart(ts=1000.0)
        chain.mark_backlog(ts=1001.5, files=8)
        chain.mark_push(ts=1003.0, remote_ref="8fd30e5..920e72e  main -> main")
        assert chain.push_ts == 1003.0
        assert chain.push_ok is True
        assert chain.push_remote_ref == "8fd30e5..920e72e  main -> main"
        assert chain.phases_done == 3
        assert chain.is_complete

    def test_full_chain_latency(self):
        chain = RecoveryChain()
        chain.mark_restart(ts=1000.0, pid=6157)
        chain.mark_backlog(ts=1002.0, files=8, commit="920e72e")
        chain.mark_push(ts=1005.0)
        assert chain.is_complete
        assert not chain.is_degraded
        assert chain.total_seconds == pytest.approx(5.0)


class TestRecoveryChainDegraded:
    def test_restart_failure(self):
        chain = RecoveryChain()
        chain.mark_restart(ts=1000.0, ok=False)
        chain.mark_backlog(ts=1002.0)
        chain.mark_push(ts=1005.0)
        assert chain.is_complete
        assert chain.is_degraded

    def test_backlog_failure(self):
        chain = RecoveryChain()
        chain.mark_restart(ts=1000.0)
        chain.mark_backlog(ts=1002.0, ok=False, files=0)
        chain.mark_push(ts=1005.0)
        assert chain.is_complete
        assert chain.is_degraded

    def test_push_failure(self):
        chain = RecoveryChain()
        chain.mark_restart(ts=1000.0)
        chain.mark_backlog(ts=1002.0, files=8, commit="920e72e")
        chain.mark_push(ts=1005.0, ok=False)
        assert chain.is_complete
        assert chain.is_degraded

    def test_all_phases_ok_not_degraded(self):
        chain = RecoveryChain()
        chain.mark_restart(ts=1000.0)
        chain.mark_backlog(ts=1002.0)
        chain.mark_push(ts=1005.0)
        assert chain.is_complete
        assert not chain.is_degraded


class TestRecoveryChainSerialization:
    def test_to_dict(self):
        chain = RecoveryChain()
        chain.mark_restart(ts=1000.0, pid=6157)
        chain.mark_backlog(ts=1002.0, files=8, commit="920e72e")
        chain.mark_push(ts=1005.0)

        d = chain.to_dict()
        assert d["restart_ts"] == 1000.0
        assert d["restart_pid"] == 6157
        assert d["backlog_files"] == 8
        assert d["backlog_commit"] == "920e72e"
        assert d["push_ok"] is True

    def test_from_dict(self):
        original = RecoveryChain()
        original.mark_restart(ts=1000.0, pid=6157)
        original.mark_backlog(ts=1002.0, files=8, commit="920e72e")
        original.mark_push(ts=1005.0)

        d = original.to_dict()
        restored = RecoveryChain.from_dict(d)

        assert restored.restart_ts == 1000.0
        assert restored.restart_pid == 6157
        assert restored.backlog_files == 8
        assert restored.is_complete
        assert not restored.is_degraded

    def test_roundtrip_preserves_degraded(self):
        chain = RecoveryChain()
        chain.mark_restart(ts=1000.0)
        chain.mark_backlog(ts=1002.0, ok=False)
        chain.mark_push(ts=1005.0)

        restored = RecoveryChain.from_dict(chain.to_dict())
        assert restored.is_degraded


class TestRecoveryChainSummary:
    def test_summary_complete(self):
        chain = RecoveryChain()
        chain.mark_restart(ts=1000.0, pid=6157)
        chain.mark_backlog(ts=1002.0, files=8)
        chain.mark_push(ts=1005.0)

        text = chain.summary()
        assert "restart=ok@1000" in text
        assert "backlog=ok@1002" in text
        assert "push=ok@1005" in text
        assert "total=5.0s" in text
        assert "DEGRADED" not in text

    def test_summary_degraded(self):
        chain = RecoveryChain()
        chain.mark_restart(ts=1000.0)
        chain.mark_backlog(ts=1002.0, ok=False)
        chain.mark_push(ts=1005.0)

        text = chain.summary()
        assert "backlog=FAIL@1002" in text
        assert "DEGRADED" in text

    def test_summary_pending(self):
        chain = RecoveryChain()
        chain.mark_restart(ts=1000.0)
        text = chain.summary()
        assert "backlog=pending" in text
        assert "push=pending" in text
        assert "total=n/a" in text


class TestRecoveryChainEdgeCases:
    def test_auto_timestamp(self):
        """mark_* with ts=None should use time.time()."""
        chain = RecoveryChain()
        chain.mark_restart()
        assert chain.restart_ts is not None
        assert chain.restart_ts > 0

    def test_total_seconds_partial(self):
        chain = RecoveryChain()
        chain.mark_restart(ts=1000.0)
        # push not yet marked
        assert chain.total_seconds is None

    def test_backlog_before_restart(self):
        """Phases can be marked in any order — the class is a data holder."""
        chain = RecoveryChain()
        chain.mark_backlog(ts=999.0)
        chain.mark_restart(ts=1000.0)
        chain.mark_push(ts=1005.0)
        assert chain.is_complete
        # total_seconds is push - restart regardless of mark order
        assert chain.total_seconds == pytest.approx(5.0)
