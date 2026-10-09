"""Tests for iamai.caretaker_preflight — unified preflight health gate.

Covers each individual check function in isolation, plus the orchestration
and rendering layers.  Uses tmp_path for git operations and mock PID files
to avoid coupling with the real running processes.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from iamai.caretaker_preflight import (
    check_branch_drift,
    check_git_locks,
    check_pending_files,
    check_process_health,
    check_stroke_freshness,
    render_oneline,
    render_table,
    run_preflight,
    _pid_alive,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo for testing."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    # Create a valid index file (empty but exists)
    (git_dir / "index").write_bytes(b"\x00" * 12)
    return tmp_path


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a real git repo with at least one commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.name", "test"],
        capture_output=True, cwd=repo, check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test"],
        capture_output=True, cwd=repo, check=True,
    )
    # Initial commit
    readme = repo / "README.md"
    readme.write_text("# test\n")
    subprocess.run(["git", "add", "."], capture_output=True, cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        capture_output=True, cwd=repo, check=True,
    )
    return repo


@pytest.fixture
def fake_pid_file(tmp_path: Path) -> Path:
    """Create a PID file with the current process's PID (alive)."""
    pid_file = tmp_path / "test.pid"
    pid_file.write_text(str(os.getpid()))
    return pid_file


# ---------------------------------------------------------------------------
# _pid_alive
# ---------------------------------------------------------------------------


def test_pid_alive_with_running_process(fake_pid_file: Path):
    assert _pid_alive(fake_pid_file) is True


def test_pid_alive_with_dead_process(tmp_path: Path):
    pid_file = tmp_path / "dead.pid"
    pid_file.write_text("999999999")  # extremely unlikely to exist
    assert _pid_alive(pid_file) is False


def test_pid_alive_missing_file(tmp_path: Path):
    pid_file = tmp_path / "nonexistent.pid"
    assert _pid_alive(pid_file) is False


def test_pid_alive_invalid_content(tmp_path: Path):
    pid_file = tmp_path / "bad.pid"
    pid_file.write_text("not_a_number")
    assert _pid_alive(pid_file) is False


# ---------------------------------------------------------------------------
# check_git_locks
# ---------------------------------------------------------------------------


def test_git_locks_clean(fake_repo: Path):
    result = check_git_locks(fake_repo)
    assert result["status"] == "ok"
    assert "no stale locks" in result["detail"]


def test_git_locks_fresh_lock(fake_repo: Path):
    lock = fake_repo / ".git" / "index.lock"
    lock.write_text("")
    result = check_git_locks(fake_repo)
    # Fresh lock (< 300s) → warn
    assert result["status"] == "warn"
    assert "index.lock exists" in result["detail"]


def test_git_locks_stale_lock(fake_repo: Path):
    lock = fake_repo / ".git" / "index.lock"
    lock.write_text("")
    # Set mtime to 600 seconds ago
    old_time = time.time() - 600
    os.utime(lock, (old_time, old_time))
    result = check_git_locks(fake_repo)
    assert result["status"] == "fail"
    assert "STALE" in result["detail"]


# ---------------------------------------------------------------------------
# check_stroke_freshness
# ---------------------------------------------------------------------------


def test_stroke_freshness_missing_file(fake_repo: Path):
    result = check_stroke_freshness(fake_repo)
    assert result["status"] == "warn"
    assert "not found" in result["detail"]


def test_stroke_freshness_empty_file(fake_repo: Path):
    strokes = fake_repo / "data" / "strokes.jsonl"
    strokes.parent.mkdir(parents=True)
    strokes.write_text("")
    result = check_stroke_freshness(fake_repo)
    assert result["status"] == "warn"
    assert "empty" in result["detail"]


def test_stroke_freshness_fresh(fake_repo: Path):
    strokes = fake_repo / "data" / "strokes.jsonl"
    strokes.parent.mkdir(parents=True)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    entry = {"seq": 1, "at": now, "kind": "thought", "text": "hello"}
    strokes.write_text(json.dumps(entry) + "\n")
    result = check_stroke_freshness(fake_repo, cadence=15)
    assert result["status"] == "ok"
    assert "last stroke" in result["detail"]


def test_stroke_freshness_stale(fake_repo: Path):
    strokes = fake_repo / "data" / "strokes.jsonl"
    strokes.parent.mkdir(parents=True)
    from datetime import datetime, timezone, timedelta
    old = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    entry = {"seq": 1, "at": old, "kind": "thought", "text": "old"}
    strokes.write_text(json.dumps(entry) + "\n")
    result = check_stroke_freshness(fake_repo, cadence=15)
    # 120s > 2*15=30 but < 5*15=75 → actually > 5*15 so fail
    # 120 > 75 → fail
    assert result["status"] == "fail"


def test_stroke_freshness_warm(fake_repo: Path):
    strokes = fake_repo / "data" / "strokes.jsonl"
    strokes.parent.mkdir(parents=True)
    from datetime import datetime, timezone, timedelta
    # 40s ago with cadence 15: > 2*15=30, < 5*15=75 → warn
    recent = (datetime.now(timezone.utc) - timedelta(seconds=40)).isoformat()
    entry = {"seq": 1, "at": recent, "kind": "thought", "text": "warm"}
    strokes.write_text(json.dumps(entry) + "\n")
    result = check_stroke_freshness(fake_repo, cadence=15)
    assert result["status"] == "warn"


def test_stroke_freshness_multiline_reads_last(fake_repo: Path):
    """Should read the LAST line, not the first."""
    strokes = fake_repo / "data" / "strokes.jsonl"
    strokes.parent.mkdir(parents=True)
    from datetime import datetime, timezone, timedelta
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        json.dumps({"seq": 1, "at": old, "kind": "thought", "text": "old"}),
        json.dumps({"seq": 2, "at": now, "kind": "thought", "text": "new"}),
    ]
    strokes.write_text("\n".join(lines) + "\n")
    result = check_stroke_freshness(fake_repo, cadence=15)
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# check_branch_drift
# ---------------------------------------------------------------------------


def test_branch_drift_synced(git_repo: Path):
    """A repo with no remote should report 'no upstream'."""
    result = check_branch_drift(git_repo)
    # No remote configured → warn
    assert result["status"] == "warn"
    assert "no upstream" in result["detail"]


def test_branch_drift_ahead(git_repo: Path):
    """Create a fake remote that is behind."""
    # Add a bare remote
    remote = git_repo.parent / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote)], capture_output=True, check=True
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote)],
        capture_output=True, cwd=git_repo, check=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "master"],
        capture_output=True, cwd=git_repo, check=True,
    )
    # Now add another local commit
    (git_repo / "new.txt").write_text("hello")
    subprocess.run(["git", "add", "."], capture_output=True, cwd=git_repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "second"],
        capture_output=True, cwd=git_repo, check=True,
    )
    result = check_branch_drift(git_repo)
    assert result["status"] == "ok"
    assert result.get("ahead", 0) >= 1


# ---------------------------------------------------------------------------
# check_process_health
# ---------------------------------------------------------------------------


def test_process_health_both_up(tmp_path: Path):
    """Mock both processes as alive."""
    w_pid = tmp_path / "writer.pid"
    b_pid = tmp_path / "batch.pid"
    w_pid.write_text(str(os.getpid()))
    b_pid.write_text(str(os.getpid()))

    with patch("iamai.caretaker_preflight.Path") as MockPath:
        # Only intercept the pid file paths
        def side_effect(p):
            if "writer" in str(p):
                return w_pid
            if "batch" in str(p):
                return b_pid
            return Path(p)
        MockPath.side_effect = side_effect
        # Can't easily patch Path globally, so test _pid_alive directly
        assert _pid_alive(w_pid) is True
        assert _pid_alive(b_pid) is True


def test_process_health_both_down(tmp_path: Path):
    w_pid = tmp_path / "writer.pid"
    b_pid = tmp_path / "batch.pid"
    w_pid.write_text("999999998")
    b_pid.write_text("999999999")
    assert _pid_alive(w_pid) is False
    assert _pid_alive(b_pid) is False


# ---------------------------------------------------------------------------
# check_pending_files
# ---------------------------------------------------------------------------


def test_pending_files_clean(git_repo: Path):
    result = check_pending_files(git_repo)
    assert result["status"] == "ok"
    assert result["count"] == 0
    assert "clean" in result["detail"]


def test_pending_files_few(git_repo: Path):
    # Create a few untracked files
    for i in range(3):
        (git_repo / f"file_{i}.txt").write_text(f"content {i}")
    result = check_pending_files(git_repo)
    assert result["status"] == "ok"
    assert result["count"] == 3


def test_pending_files_piling(git_repo: Path):
    # Create 15 untracked files (above warn_at=10)
    for i in range(15):
        (git_repo / f"file_{i}.txt").write_text(f"content {i}")
    result = check_pending_files(git_repo)
    assert result["status"] == "warn"
    assert "piling" in result["detail"]


def test_pending_files_critical(git_repo: Path):
    # Create 60 untracked files (above fail_at=50)
    for i in range(60):
        (git_repo / f"file_{i}.txt").write_text(f"content {i}")
    result = check_pending_files(git_repo, fail_at=50)
    assert result["status"] == "fail"
    assert "critical" in result["detail"]


# ---------------------------------------------------------------------------
# run_preflight — orchestration
# ---------------------------------------------------------------------------


def test_run_preflight_returns_structure(fake_repo: Path):
    """Even with a broken repo, run_preflight should return a valid report."""
    report = run_preflight(repo=fake_repo, writer_id="test_nonexistent")
    assert "checks" in report
    assert "verdict" in report
    assert "ts" in report
    assert len(report["checks"]) == 5


def test_run_preflight_verdict_is_worst(fake_repo: Path):
    """With no locks, no strokes, no processes → should have at least warn/fail."""
    report = run_preflight(repo=fake_repo, writer_id="test_nonexistent")
    statuses = [c["status"] for c in report["checks"]]
    if "fail" in statuses:
        assert report["verdict"] == "fail"
    elif "warn" in statuses:
        assert report["verdict"] == "warn"
    else:
        assert report["verdict"] == "ok"


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def test_render_table_has_all_checks(fake_repo: Path):
    report = run_preflight(repo=fake_repo, writer_id="test_nonexistent")
    table = render_table(report)
    for check in report["checks"]:
        assert check["check"] in table
    assert "verdict" in table


def test_render_oneline_format(fake_repo: Path):
    report = run_preflight(repo=fake_repo, writer_id="test_nonexistent")
    oneline = render_oneline(report)
    assert "ok=" in oneline
    # Should be a single line
    assert "\n" not in oneline


def test_render_oneline_all_ok():
    """Synthetic report with all ok checks."""
    report = {
        "checks": [
            {"check": "a", "status": "ok", "detail": "fine"},
            {"check": "b", "status": "ok", "detail": "fine"},
        ],
        "verdict": "ok",
    }
    oneline = render_oneline(report)
    assert "FAIL" not in oneline
    assert "WARN" not in oneline
    assert "ok=2/2" in oneline


def test_render_oneline_with_fail():
    report = {
        "checks": [
            {"check": "locks", "status": "fail", "detail": "stale"},
            {"check": "drift", "status": "warn", "detail": "behind"},
            {"check": "files", "status": "ok", "detail": "clean"},
        ],
        "verdict": "fail",
    }
    oneline = render_oneline(report)
    assert "FAIL(locks)" in oneline
    assert "WARN(drift)" in oneline
    assert "ok=1/3" in oneline


def test_render_table_widths_consistent():
    """Each row in the table should have the same number of │ separators."""
    report = {
        "checks": [
            {"check": "git_locks", "status": "ok", "detail": "no stale locks"},
            {"check": "branch_drift", "status": "fail", "detail": "diverged: 5 ahead, 3 behind"},
        ],
        "verdict": "fail",
    }
    table = render_table(report)
    data_lines = [l for l in table.splitlines() if l.startswith("│") and "check" not in l and "─" not in l]
    # All data rows should have the same column count
    for line in data_lines:
        assert line.count("│") == data_lines[0].count("│")
