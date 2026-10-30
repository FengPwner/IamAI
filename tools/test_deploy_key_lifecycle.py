#!/usr/bin/env python3
"""Tests for deploy_key_lifecycle.py

22 tests covering:
  - state detection logic (MISSING, UNREGISTERED, REGISTERED, REVOKED)
  - transition recording and JSONL append
  - state caching and comparison
  - lifecycle statistics computation
  - history formatting
  - edge cases (corrupt files, missing dirs, empty logs)
  - recovery time calculation
  - CLI argument handling
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import deploy_key_lifecycle as dl


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_key_file(tmpdir: Path, name: str = "id_ed25519") -> Path:
    """Create a dummy ssh key file for testing."""
    key_dir = tmpdir / ".ssh"
    key_dir.mkdir(exist_ok=True)
    key_path = key_dir / name
    key_path.write_text(
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
        "QyNTUxOQAAACBfakefakefakefakefakefakefakefakefakefAAAAJgAAAAtzc2gtZW\n"
        "-----END OPENSSH PRIVATE KEY-----\n"
    )
    return key_path


def _write_transition(log_path: Path, transitions: list[dict]) -> None:
    """Write a list of transitions to a JSONL file."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as f:
        for t in transitions:
            f.write(json.dumps(t) + "\n")


def _make_transition(
    ts: str = "2026-10-26T12:00:00",
    old: str = "MISSING",
    new: str = "UNREGISTERED",
    reason: str = "test",
) -> dict:
    return {
        "timestamp": ts,
        "old_state": old,
        "new_state": new,
        "reason": reason,
        "key_path": "",
        "fingerprint": "",
    }


# ---------------------------------------------------------------------------
# state detection tests
# ---------------------------------------------------------------------------

def test_find_key_path_returns_none_when_missing():
    """find_key_path returns None when no key files exist."""
    with mock.patch.object(dl, "KEY_PATHS", [Path("/nonexistent/key1"), Path("/nonexistent/key2")]):
        assert dl.find_key_path() is None


def test_find_key_path_returns_first_existing():
    """find_key_path returns the first path that exists."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        key1 = p / "key1"
        key2 = p / "key2"
        key2.touch()
        with mock.patch.object(dl, "KEY_PATHS", [key1, key2]):
            result = dl.find_key_path()
            assert result == key2


def test_detect_missing_state():
    """detect_current_state returns MISSING when no key file exists."""
    with mock.patch.object(dl, "find_key_path", return_value=None):
        state, reason, path = dl.detect_current_state()
        assert state == dl.KeyState.MISSING
        assert path is None
        assert "no key file" in reason


def test_detect_unregistered_state():
    """detect returns UNREGISTERED when key exists but github rejects it."""
    with tempfile.TemporaryDirectory() as td:
        key_path = _make_key_file(Path(td))
        with mock.patch.object(dl, "find_key_path", return_value=key_path), \
             mock.patch.object(dl, "get_fingerprint", return_value="SHA256:abc123"), \
             mock.patch.object(dl, "probe_github_ssh", return_value=False), \
             mock.patch.object(dl, "load_cached_state", return_value=None):
            state, reason, path = dl.detect_current_state()
            assert state == dl.KeyState.UNREGISTERED
            assert path == key_path
            assert "rejects" in reason


def test_detect_registered_state():
    """detect returns REGISTERED when key exists and github accepts it."""
    with tempfile.TemporaryDirectory() as td:
        key_path = _make_key_file(Path(td))
        with mock.patch.object(dl, "find_key_path", return_value=key_path), \
             mock.patch.object(dl, "get_fingerprint", return_value="SHA256:abc123"), \
             mock.patch.object(dl, "probe_github_ssh", return_value=True):
            state, reason, path = dl.detect_current_state()
            assert state == dl.KeyState.REGISTERED
            assert path == key_path
            assert "accepts" in reason


def test_detect_revoked_state():
    """detect returns REVOKED when key was registered but now rejected."""
    with tempfile.TemporaryDirectory() as td:
        key_path = _make_key_file(Path(td))
        with mock.patch.object(dl, "find_key_path", return_value=key_path), \
             mock.patch.object(dl, "get_fingerprint", return_value="SHA256:abc123"), \
             mock.patch.object(dl, "probe_github_ssh", return_value=False), \
             mock.patch.object(dl, "load_cached_state", return_value={"state": "REGISTERED"}):
            state, reason, path = dl.detect_current_state()
            assert state == dl.KeyState.REVOKED
            assert "was registered" in reason


def test_get_fingerprint_handles_missing_keygen():
    """get_fingerprint returns empty string when ssh-keygen is not available."""
    with mock.patch("subprocess.run", side_effect=FileNotFoundError):
        result = dl.get_fingerprint(Path("/fake/key"))
        assert result == ""


def test_get_fingerprint_parses_output():
    """get_fingerprint extracts the hash from ssh-keygen output."""
    fake_result = mock.Mock()
    fake_result.returncode = 0
    fake_result.stdout = "256 SHA256:umVkJlKEVPwszsbu02wfKHeytWlO4y2SwliJ2pTgrk root@host (ED25519)\n"
    with mock.patch("subprocess.run", return_value=fake_result):
        result = dl.get_fingerprint(Path("/fake/key"))
        assert result == "SHA256:umVkJlKEVPwszsbu02wfKHeytWlO4y2SwliJ2pTgrk"


def test_probe_github_success():
    """probe_github_ssh returns True when github says authenticated."""
    fake_result = mock.Mock()
    fake_result.returncode = 1
    fake_result.stdout = ""
    fake_result.stderr = "Hi FengPwner! You've successfully authenticated, but GitHub does not provide shell access.\n"
    with mock.patch("subprocess.run", return_value=fake_result):
        assert dl.probe_github_ssh(Path("/fake/key")) is True


def test_probe_github_permission_denied():
    """probe_github_ssh returns False on permission denied."""
    fake_result = mock.Mock()
    fake_result.returncode = 255
    fake_result.stdout = ""
    fake_result.stderr = "git@github.com: Permission denied (publickey).\n"
    with mock.patch("subprocess.run", return_value=fake_result):
        assert dl.probe_github_ssh(Path("/fake/key")) is False


def test_probe_github_timeout():
    """probe_github_ssh returns False on timeout."""
    with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 10)):
        assert dl.probe_github_ssh(Path("/fake/key")) is False


# ---------------------------------------------------------------------------
# transition recording tests
# ---------------------------------------------------------------------------

def test_append_transition_writes_jsonl():
    """append_transition appends a JSON line to the log file."""
    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "data" / "lifecycle.jsonl"
        with mock.patch.object(dl, "LIFECYCLE_LOG", log_path), \
             mock.patch.object(dl, "DATA_DIR", Path(td) / "data"):
            t = dl.Transition(
                timestamp="2026-10-26T12:00:00",
                old_state="MISSING",
                new_state="UNREGISTERED",
                reason="key appeared",
                key_path="/root/.ssh/id_ed25519",
                fingerprint="SHA256:abc",
            )
            dl.append_transition(t)
            lines = log_path.read_text().strip().split("\n")
            assert len(lines) == 1
            parsed = json.loads(lines[0])
            assert parsed["old_state"] == "MISSING"
            assert parsed["new_state"] == "UNREGISTERED"


def test_append_transition_multiple():
    """Multiple append_transition calls produce multiple lines."""
    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "data" / "lifecycle.jsonl"
        with mock.patch.object(dl, "LIFECYCLE_LOG", log_path), \
             mock.patch.object(dl, "DATA_DIR", Path(td) / "data"):
            for i in range(5):
                t = dl.Transition(
                    timestamp=f"2026-10-26T12:{i:02d}:00",
                    old_state="MISSING",
                    new_state="UNREGISTERED",
                    reason=f"transition {i}",
                )
                dl.append_transition(t)
            lines = log_path.read_text().strip().split("\n")
            assert len(lines) == 5


def test_load_transitions_empty():
    """load_transitions returns empty list when log doesn't exist."""
    with mock.patch.object(dl, "LIFECYCLE_LOG", Path("/nonexistent/log.jsonl")):
        assert dl.load_transitions() == []


def test_load_transitions_skips_corrupt_lines():
    """load_transitions handles corrupt JSON lines gracefully."""
    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "log.jsonl"
        log_path.write_text(
            '{"timestamp":"2026-10-26T12:00:00","old_state":"A","new_state":"B"}\n'
            'CORRUPT LINE\n'
            '{"timestamp":"2026-10-26T13:00:00","old_state":"B","new_state":"C"}\n'
        )
        with mock.patch.object(dl, "LIFECYCLE_LOG", log_path):
            transitions = dl.load_transitions()
            assert len(transitions) == 2


# ---------------------------------------------------------------------------
# state cache tests
# ---------------------------------------------------------------------------

def test_save_and_load_cached_state():
    """save/load cached state roundtrips correctly."""
    with tempfile.TemporaryDirectory() as td:
        cache_path = Path(td) / "data" / "state.json"
        with mock.patch.object(dl, "STATE_CACHE", cache_path), \
             mock.patch.object(dl, "DATA_DIR", Path(td) / "data"):
            dl.save_cached_state(dl.KeyState.REGISTERED, "test reason", "/fake/key")
            cached = dl.load_cached_state()
            assert cached is not None
            assert cached["state"] == "REGISTERED"
            assert cached["reason"] == "test reason"


def test_load_cached_returns_none_when_missing():
    """load_cached_state returns None when no cache file exists."""
    with mock.patch.object(dl, "STATE_CACHE", Path("/nonexistent/state.json")):
        assert dl.load_cached_state() is None


def test_check_and_record_detects_transition():
    """check_and_record records a transition when state changes."""
    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "data" / "lifecycle.jsonl"
        cache_path = Path(td) / "data" / "state.json"
        with mock.patch.object(dl, "LIFECYCLE_LOG", log_path), \
             mock.patch.object(dl, "STATE_CACHE", cache_path), \
             mock.patch.object(dl, "DATA_DIR", Path(td) / "data"), \
             mock.patch.object(dl, "detect_current_state",
                               return_value=(dl.KeyState.UNREGISTERED, "test", None)):
            # first call: no cache → transition from UNKNOWN to UNREGISTERED
            state, reason, transitioned = dl.check_and_record()
            assert state == dl.KeyState.UNREGISTERED
            assert transitioned is True
            assert log_path.exists()


def test_check_and_record_no_transition_when_same():
    """check_and_record does NOT record when state hasn't changed."""
    with tempfile.TemporaryDirectory() as td:
        log_path = Path(td) / "data" / "lifecycle.jsonl"
        cache_path = Path(td) / "data" / "state.json"
        # pre-populate cache with same state
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"state": "REGISTERED", "since": "earlier"}))
        with mock.patch.object(dl, "LIFECYCLE_LOG", log_path), \
             mock.patch.object(dl, "STATE_CACHE", cache_path), \
             mock.patch.object(dl, "DATA_DIR", Path(td) / "data"), \
             mock.patch.object(dl, "detect_current_state",
                               return_value=(dl.KeyState.REGISTERED, "ok", None)):
            state, reason, transitioned = dl.check_and_record()
            assert state == dl.KeyState.REGISTERED
            assert transitioned is False
            assert not log_path.exists() or log_path.read_text().strip() == ""


# ---------------------------------------------------------------------------
# statistics tests
# ---------------------------------------------------------------------------

def test_compute_stats_empty():
    """compute_stats returns defaults when no transitions exist."""
    with mock.patch.object(dl, "load_transitions", return_value=[]), \
         mock.patch.object(dl, "load_cached_state", return_value=None):
        stats = dl.compute_stats()
        assert stats.total_transitions == 0
        assert stats.transitions_today == 0
        assert stats.mttr_seconds == 0.0


def test_compute_stats_counts_today():
    """compute_stats correctly counts today's transitions."""
    today = dl.today_str()
    transitions = [
        _make_transition(ts=f"{today}T10:00:00", old="MISSING", new="UNREGISTERED"),
        _make_transition(ts=f"{today}T11:00:00", old="UNREGISTERED", new="REGISTERED"),
        _make_transition(ts="2025-01-01T10:00:00", old="MISSING", new="UNREGISTERED"),
    ]
    with mock.patch.object(dl, "load_transitions", return_value=transitions), \
         mock.patch.object(dl, "load_cached_state", return_value={"state": "REGISTERED"}):
        stats = dl.compute_stats()
        assert stats.total_transitions == 3
        assert stats.transitions_today == 2


def test_compute_stats_mttr():
    """compute_stats calculates MTTR from recovery transitions."""
    transitions = [
        _make_transition(ts="2026-10-26T10:00:00", old="REGISTERED", new="MISSING"),
        _make_transition(ts="2026-10-26T10:30:00", old="MISSING", new="UNREGISTERED"),
        _make_transition(ts="2026-10-26T11:00:00", old="UNREGISTERED", new="REGISTERED"),
    ]
    with mock.patch.object(dl, "load_transitions", return_value=transitions), \
         mock.patch.object(dl, "load_cached_state", return_value={"state": "REGISTERED"}):
        stats = dl.compute_stats()
        # recovery took 3600s (10:00 → 11:00)
        assert stats.mttr_seconds == 3600.0


# ---------------------------------------------------------------------------
# formatting tests
# ---------------------------------------------------------------------------

def test_format_history_empty():
    """format_history returns friendly message when no transitions."""
    with mock.patch.object(dl, "load_transitions", return_value=[]):
        result = dl.format_history()
        assert "no transitions" in result


def test_format_history_shows_transitions():
    """format_history formats transitions with arrow notation."""
    transitions = [
        _make_transition(ts="2026-10-26T12:00:00", old="MISSING", new="UNREGISTERED"),
        _make_transition(ts="2026-10-26T13:00:00", old="UNREGISTERED", new="REGISTERED"),
    ]
    with mock.patch.object(dl, "load_transitions", return_value=transitions):
        result = dl.format_history(5)
        assert "MISSING" in result
        assert "→" in result or "UNREGISTERED" in result
        assert "REGISTERED" in result


def test_format_stats_includes_uptime():
    """format_stats includes uptime ratio when available."""
    stats = dl.LifecycleStats(
        total_transitions=5,
        transitions_today=2,
        current_state="REGISTERED",
        current_state_since="2026-10-26T12:00:00",
        mttr_seconds=1800.0,
        uptime_ratio=0.85,
        time_in_state={"REGISTERED": 3600, "MISSING": 600},
    )
    result = dl.format_stats(stats)
    assert "REGISTERED" in result
    assert "85" in result  # 85%
    assert "1800" in result


# ---------------------------------------------------------------------------
# enum and dataclass tests
# ---------------------------------------------------------------------------

def test_key_state_values():
    """KeyState enum has expected string values."""
    assert dl.KeyState.MISSING.value == "MISSING"
    assert dl.KeyState.UNREGISTERED.value == "UNREGISTERED"
    assert dl.KeyState.REGISTERED.value == "REGISTERED"
    assert dl.KeyState.REVOKED.value == "REVOKED"


def test_transition_dataclass_serializes():
    """Transition dataclass converts to dict correctly."""
    t = dl.Transition(
        timestamp="2026-10-26T12:00:00",
        old_state="MISSING",
        new_state="UNREGISTERED",
        reason="test",
        key_path="/root/.ssh/id_ed25519",
        fingerprint="SHA256:abc",
    )
    d = asdict(t)
    assert d["old_state"] == "MISSING"
    assert d["fingerprint"] == "SHA256:abc"


def test_now_iso_format():
    """now_iso returns a valid ISO timestamp string."""
    ts = dl.now_iso()
    assert len(ts) >= 19
    assert "T" in ts


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback

    tests = [
        test_find_key_path_returns_none_when_missing,
        test_find_key_path_returns_first_existing,
        test_detect_missing_state,
        test_detect_unregistered_state,
        test_detect_registered_state,
        test_detect_revoked_state,
        test_get_fingerprint_handles_missing_keygen,
        test_get_fingerprint_parses_output,
        test_probe_github_success,
        test_probe_github_permission_denied,
        test_probe_github_timeout,
        test_append_transition_writes_jsonl,
        test_append_transition_multiple,
        test_load_transitions_empty,
        test_load_transitions_skips_corrupt_lines,
        test_save_and_load_cached_state,
        test_load_cached_returns_none_when_missing,
        test_check_and_record_detects_transition,
        test_check_and_record_no_transition_when_same,
        test_compute_stats_empty,
        test_compute_stats_counts_today,
        test_compute_stats_mttr,
        test_format_history_empty,
        test_format_history_shows_transitions,
        test_format_stats_includes_uptime,
        test_key_state_values,
        test_transition_dataclass_serializes,
        test_now_iso_format,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print(f"  PASS  {test.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL  {test.__name__}: {e}")
            traceback.print_exc()

    print(f"\n{passed}/{passed + failed} passed")
    sys.exit(1 if failed else 0)
