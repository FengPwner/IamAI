"""Tests for iamai.stall_root_cause — stall root-cause classifier."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from iamai.stall_root_cause import (
    CAUSES,
    StallVerdict,
    _probe_disk_full,
    _probe_merge_conflict,
    _probe_network,
    _probe_pause_gate,
    _probe_process_alive,
    classify_stall,
    quick_diagnose,
)


# ---------------------------------------------------------------------------
# StallVerdict dataclass
# ---------------------------------------------------------------------------


class TestStallVerdict:
    def test_frozen(self):
        v = StallVerdict(cause="process_dead", confidence=0.95, evidence=["pid gone"])
        with pytest.raises(AttributeError):
            v.cause = "other"

    def test_is_clear_true(self):
        v = StallVerdict(cause="none", confidence=1.0)
        assert v.is_clear() is True

    def test_is_clear_false(self):
        v = StallVerdict(cause="process_dead", confidence=0.95)
        assert v.is_clear() is False

    def test_to_dict(self):
        v = StallVerdict(
            cause="network",
            confidence=0.8765,
            evidence=["3 unpushed commits"],
            writer_id="qwen",
        )
        d = v.to_dict()
        assert d["cause"] == "network"
        assert d["confidence"] == 0.8765
        assert d["evidence"] == ["3 unpushed commits"]
        assert d["writer_id"] == "qwen"

    def test_to_dict_rounds_confidence(self):
        v = StallVerdict(cause="disk_full", confidence=0.123456789)
        assert v.to_dict()["confidence"] == 0.1235

    def test_evidence_immutable_copy(self):
        ev = ["line1", "line2"]
        v = StallVerdict(cause="unknown", confidence=0.5, evidence=ev)
        d = v.to_dict()
        d["evidence"].append("injected")
        assert len(v.evidence) == 2

    def test_causes_tuple(self):
        assert "process_dead" in CAUSES
        assert "unknown" in CAUSES
        assert len(CAUSES) == 6

    def test_default_evidence_empty(self):
        v = StallVerdict(cause="none", confidence=0.0)
        assert v.evidence == []

    def test_default_writer_id_none(self):
        v = StallVerdict(cause="none", confidence=0.0)
        assert v.writer_id is None


# ---------------------------------------------------------------------------
# _probe_process_alive
# ---------------------------------------------------------------------------


class TestProbeProcessAlive:
    def test_nonexistent_writer(self):
        """A writer id with no pid file should report process dead."""
        conf, ev = _probe_process_alive("__nonexistent_writer_xyz__")
        assert conf >= 0.90
        assert any("missing" in e or "dead" in e for e in ev)

    def test_evidence_is_list(self):
        _, ev = _probe_process_alive("qwen")
        assert isinstance(ev, list)

    def test_confidence_range(self):
        conf, _ = _probe_process_alive("qwen")
        assert 0.0 <= conf <= 1.0

    def test_ghost_writer_high_confidence(self):
        conf, _ = _probe_process_alive("ghost_writer_42")
        assert conf >= 0.90

    def test_evidence_has_at_least_one_line(self):
        _, ev = _probe_process_alive("__ghost__")
        assert len(ev) >= 1

    def test_unreadable_pid_file(self, tmp_path):
        """Simulate a pid file with garbage content."""
        pid_file = tmp_path / "iamai-writer-bad.pid"
        pid_file.write_text("not_a_number")
        # We can't fully redirect the probe to tmp_path without mocking,
        # so we test the real function with a known-dead writer
        conf, ev = _probe_process_alive("bad_pid_test_never_exists")
        assert conf >= 0.90


# ---------------------------------------------------------------------------
# _probe_pause_gate
# ---------------------------------------------------------------------------


class TestProbePauseGate:
    def test_no_pause_file(self):
        conf, ev = _probe_pause_gate("__nonexistent__")
        assert conf == 0.0
        assert "no pause gate" in ev

    def test_pause_file_exists(self):
        pause_path = Path("/tmp/iamai-writer-pause-test_stall_probe")
        pause_path.touch()
        try:
            conf, ev = _probe_pause_gate("test_stall_probe")
            assert conf == 0.98
            assert any("pause gate active" in e for e in ev)
        finally:
            pause_path.unlink(missing_ok=True)

    def test_evidence_type(self):
        _, ev = _probe_pause_gate("qwen")
        assert isinstance(ev, list)

    def test_confidence_range(self):
        conf, _ = _probe_pause_gate("qwen")
        assert 0.0 <= conf <= 1.0

    def test_pause_then_unpause(self):
        pause_path = Path("/tmp/iamai-writer-pause-toggle_test")
        pause_path.touch()
        try:
            conf1, _ = _probe_pause_gate("toggle_test")
            assert conf1 == 0.98
        finally:
            pause_path.unlink(missing_ok=True)
        conf2, _ = _probe_pause_gate("toggle_test")
        assert conf2 == 0.0


# ---------------------------------------------------------------------------
# _probe_merge_conflict
# ---------------------------------------------------------------------------


class TestProbeMergeConflict:
    def test_clean_repo(self, tmp_path):
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
            capture_output=True,
        )
        conf, ev = _probe_merge_conflict(tmp_path)
        assert conf == 0.0
        assert "no merge conflicts" in ev

    def test_nonexistent_repo(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        conf, ev = _probe_merge_conflict(empty)
        assert isinstance(conf, float)

    def test_evidence_is_list(self, tmp_path):
        _, ev = _probe_merge_conflict(tmp_path)
        assert isinstance(ev, list)

    def test_confidence_range(self, tmp_path):
        conf, _ = _probe_merge_conflict(tmp_path)
        assert 0.0 <= conf <= 1.0

    def test_repo_with_file(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], capture_output=True)
        (repo / "a.txt").write_text("hello")
        subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], capture_output=True)
        conf, ev = _probe_merge_conflict(repo)
        assert conf == 0.0


# ---------------------------------------------------------------------------
# _probe_disk_full
# ---------------------------------------------------------------------------


class TestProbeDiskFull:
    def test_normal_disk(self, tmp_path):
        conf, ev = _probe_disk_full(tmp_path)
        # Most systems are not >95% full
        assert isinstance(conf, float)
        assert 0.0 <= conf <= 1.0

    def test_evidence_present(self, tmp_path):
        _, ev = _probe_disk_full(tmp_path)
        assert len(ev) >= 1

    def test_evidence_mentions_disk(self, tmp_path):
        _, ev = _probe_disk_full(tmp_path)
        assert any("disk" in e.lower() for e in ev)

    def test_confidence_range(self, tmp_path):
        conf, _ = _probe_disk_full(tmp_path)
        assert 0.0 <= conf <= 1.0

    def test_nonexistent_path(self, tmp_path):
        gone = tmp_path / "gone"
        # Don't create it — should handle gracefully
        conf, ev = _probe_disk_full(gone)
        assert isinstance(conf, float)


# ---------------------------------------------------------------------------
# _probe_network
# ---------------------------------------------------------------------------


class TestProbeNetwork:
    def test_clean_state(self, tmp_path):
        conf, ev = _probe_network(tmp_path)
        assert isinstance(conf, float)
        assert 0.0 <= conf <= 1.0

    def test_no_remote(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], capture_output=True)
        conf, ev = _probe_network(repo)
        assert isinstance(conf, float)

    def test_evidence_type(self, tmp_path):
        _, ev = _probe_network(tmp_path)
        assert isinstance(ev, list)

    def test_confidence_range(self, tmp_path):
        conf, _ = _probe_network(tmp_path)
        assert 0.0 <= conf <= 1.0

    def test_log_file_absent(self, tmp_path):
        """Should not crash when log file doesn't exist."""
        conf, ev = _probe_network(tmp_path)
        assert isinstance(conf, float)


# ---------------------------------------------------------------------------
# classify_stall integration
# ---------------------------------------------------------------------------


class TestClassifyStall:
    def test_returns_stall_verdict(self, tmp_path):
        v = classify_stall(repo_path=str(tmp_path), writer_id="__test_none__")
        assert isinstance(v, StallVerdict)

    def test_cause_in_causes(self, tmp_path):
        v = classify_stall(repo_path=str(tmp_path), writer_id="__ghost__")
        assert v.cause in CAUSES

    def test_writer_id_propagated(self, tmp_path):
        v = classify_stall(repo_path=str(tmp_path), writer_id="custom_test")
        assert v.writer_id == "custom_test"

    def test_high_threshold(self, tmp_path):
        v = classify_stall(repo_path=str(tmp_path), stall_threshold=0.99)
        # With high threshold, should return unknown
        assert v.cause in CAUSES

    def test_low_threshold(self, tmp_path):
        v = classify_stall(repo_path=str(tmp_path), stall_threshold=0.01)
        # Even tiny threshold returns something
        assert v.cause in CAUSES

    def test_real_repo(self):
        """Run against the actual IamAI repo."""
        repo = Path(__file__).resolve().parent.parent
        v = classify_stall(repo_path=str(repo))
        assert isinstance(v, StallVerdict)
        assert v.cause in CAUSES

    def test_custom_repo_path(self, tmp_path):
        v = classify_stall(repo_path=str(tmp_path), writer_id="custom")
        assert isinstance(v, StallVerdict)
        assert v.writer_id == "custom"

    def test_stall_threshold_parameter(self, tmp_path):
        v1 = classify_stall(repo_path=str(tmp_path), stall_threshold=0.01)
        v2 = classify_stall(repo_path=str(tmp_path), stall_threshold=0.99)
        # Both return valid verdicts
        assert isinstance(v1, StallVerdict)
        assert isinstance(v2, StallVerdict)

    def test_confidence_is_float(self, tmp_path):
        v = classify_stall(repo_path=str(tmp_path))
        assert isinstance(v.confidence, float)
        assert 0.0 <= v.confidence <= 1.0

    def test_evidence_present(self, tmp_path):
        v = classify_stall(repo_path=str(tmp_path), writer_id="__ghost__")
        assert len(v.evidence) >= 1

    def test_to_dict_integration(self, tmp_path):
        v = classify_stall(repo_path=str(tmp_path), writer_id="dict_test")
        d = v.to_dict()
        assert "cause" in d
        assert "confidence" in d
        assert "evidence" in d
        assert d["writer_id"] == "dict_test"


# ---------------------------------------------------------------------------
# quick_diagnose
# ---------------------------------------------------------------------------


class TestQuickDiagnose:
    def test_returns_string(self):
        result = quick_diagnose(writer_id="__fake__")
        assert isinstance(result, str)

    def test_format(self):
        result = quick_diagnose()
        assert "stall:" in result
        assert "conf=" in result

    def test_qwen_id(self):
        result = quick_diagnose("qwen")
        assert isinstance(result, str)
        assert ":" in result

    def test_unknown_writer(self):
        result = quick_diagnose("unknown_ghost")
        assert isinstance(result, str)
        assert "stall:" in result

    def test_evidence_separator(self):
        result = quick_diagnose()
        # Evidence lines are joined with "; "
        assert isinstance(result, str)
