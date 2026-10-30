#!/usr/bin/env python3
"""Tests for stall_cooldown.py — restart backoff controller."""

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from stall_cooldown import (
    CooldownState,
    BACKOFF_SCHEDULE,
    STABLE_WINDOW_DEFAULT,
    main,
)


def _make_state(tmpdir: Path | None = None) -> CooldownState:
    """Create a CooldownState with a temp file."""
    if tmpdir is None:
        tmpdir = Path(tempfile.mkdtemp())
    state_file = tmpdir / "cooldown.json"
    return CooldownState(state_file)


class TestCooldownState:
    """Unit tests for CooldownState."""

    def test_fresh_state_allows_restart(self):
        state = _make_state()
        assert state.restart_count == 0
        assert state.last_restart_ts is None
        assert state.should_restart() is True
        assert state.cooldown_remaining() == 0.0

    def test_first_restart_no_cooldown(self):
        state = _make_state()
        state.record_restart()
        assert state.restart_count == 1
        # First restart has 0s backoff (BACKOFF_SCHEDULE[0] = 0)
        assert state.should_restart() is True

    def test_second_restart_has_cooldown(self):
        state = _make_state()
        state.record_restart()  # attempt 1
        state.record_restart()  # attempt 2
        assert state.restart_count == 2
        # Second restart has 60s backoff
        remaining = state.cooldown_remaining()
        assert 55 < remaining <= 60

    def test_exponential_backoff_increases(self):
        state = _make_state()
        for i in range(5):
            state.record_restart()

        # After 5 rapid restarts, should be at BACKOFF_SCHEDULE[4] = 3600s
        remaining = state.cooldown_remaining()
        assert remaining > 3500  # close to 3600s

    def test_should_restart_after_cooldown_expires(self):
        state = _make_state()
        state.record_restart()
        # Manually set the last restart to 2 minutes ago
        state.data["restarts"][-1] = time.time() - 120
        # Second attempt needs 60s, we waited 120s
        assert state.should_restart() is True

    def test_mark_stable_resets_counter(self):
        state = _make_state()
        state.record_restart()
        state.record_restart()
        state.record_restart()
        assert state.restart_count == 3

        state.mark_stable()
        assert state.restart_count == 0
        assert state.should_restart() is True
        assert state.data["last_stable"] is not None

    def test_check_stability_resets_after_window(self):
        state = _make_state()
        state.record_restart()
        # Set restart to 700s ago (past the 600s stable window)
        state.data["restarts"][-1] = time.time() - 700

        result = state.check_stability(
            writer_alive=True, batch_alive=True, stable_window=600
        )
        assert result is True
        assert state.restart_count == 0

    def test_check_stability_not_enough_time(self):
        state = _make_state()
        state.record_restart()
        # Set restart to 100s ago (less than 600s stable window)
        state.data["restarts"][-1] = time.time() - 100

        result = state.check_stability(
            writer_alive=True, batch_alive=True, stable_window=600
        )
        assert result is False
        assert state.restart_count == 1  # not reset

    def test_check_stability_dead_process_does_not_reset(self):
        state = _make_state()
        state.record_restart()
        state.data["restarts"][-1] = time.time() - 700

        result = state.check_stability(
            writer_alive=True, batch_alive=False, stable_window=600
        )
        assert result is False
        assert state.restart_count == 1

    def test_reset_clears_everything(self):
        state = _make_state()
        state.record_restart()
        state.record_restart()
        state.mark_stable()

        state.reset()
        assert state.restart_count == 0
        assert state.last_restart_ts is None
        assert state.data["last_stable"] is None

    def test_persistence_across_instances(self):
        tmpdir = Path(tempfile.mkdtemp())
        state1 = CooldownState(tmpdir / "cooldown.json")
        state1.record_restart()
        state1.record_restart()

        # New instance reads from same file
        state2 = CooldownState(tmpdir / "cooldown.json")
        assert state2.restart_count == 2
        assert state2.cooldown_remaining() > 0

    def test_corrupt_state_file_falls_back(self):
        tmpdir = Path(tempfile.mkdtemp())
        state_file = tmpdir / "cooldown.json"
        state_file.write_text("not valid json{{{")

        state = CooldownState(state_file)
        assert state.restart_count == 0
        assert state.should_restart() is True

    def test_summary_dict_structure(self):
        state = _make_state()
        state.record_restart()
        summary = state.summary()

        assert "restart_count" in summary
        assert "last_restart_ts" in summary
        assert "cooldown_remaining_s" in summary
        assert "should_restart" in summary
        assert "last_stable" in summary
        assert "backoff_schedule" in summary
        assert summary["restart_count"] == 1

    def test_restart_history_capped_at_20(self):
        state = _make_state()
        for _ in range(30):
            state.record_restart()
        assert len(state.data["restarts"]) == 20

    def test_backoff_schedule_not_exceeded(self):
        state = _make_state()
        # Record 10 rapid restarts
        for _ in range(10):
            state.record_restart()

        # Should cap at BACKOFF_SCHEDULE[-1] = 3600s
        remaining = state.cooldown_remaining()
        assert remaining <= 3600


class TestMainCLI:
    """Integration tests for the CLI interface."""

    def test_main_default_allows_restart(self, monkeypatch, capsys):
        tmpdir = Path(tempfile.mkdtemp())
        monkeypatch.setattr(sys, "argv", [
            "stall_cooldown.py", "--state-file", str(tmpdir / "cd.json")
        ])
        assert main() == 0
        assert "Restart allowed" in capsys.readouterr().out

    def test_main_record_then_check(self, monkeypatch, capsys):
        tmpdir = Path(tempfile.mkdtemp())
        state_file = str(tmpdir / "cd.json")

        # Record two restarts
        monkeypatch.setattr(sys, "argv", [
            "stall_cooldown.py", "--state-file", state_file, "--record"
        ])
        main()
        main()

        # Check — should be in cooldown
        monkeypatch.setattr(sys, "argv", [
            "stall_cooldown.py", "--state-file", state_file
        ])
        assert main() == 1

    def test_main_status_json(self, monkeypatch, capsys):
        tmpdir = Path(tempfile.mkdtemp())
        monkeypatch.setattr(sys, "argv", [
            "stall_cooldown.py", "--state-file", str(tmpdir / "cd.json"),
            "--status", "--json"
        ])
        main()
        output = capsys.readouterr().out
        data = json.loads(output)
        assert "restart_count" in data

    def test_main_reset(self, monkeypatch, capsys):
        tmpdir = Path(tempfile.mkdtemp())
        state_file = str(tmpdir / "cd.json")

        # Record some restarts
        monkeypatch.setattr(sys, "argv", [
            "stall_cooldown.py", "--state-file", state_file, "--record"
        ])
        main()
        main()  # second restart
        capsys.readouterr()  # drain earlier output

        # Reset
        monkeypatch.setattr(sys, "argv", [
            "stall_cooldown.py", "--state-file", state_file, "--reset"
        ])
        main()
        capsys.readouterr()  # drain reset output

        # Verify cleared
        monkeypatch.setattr(sys, "argv", [
            "stall_cooldown.py", "--state-file", state_file, "--status", "--json"
        ])
        main()
        data = json.loads(capsys.readouterr().out)
        assert data["restart_count"] == 0
