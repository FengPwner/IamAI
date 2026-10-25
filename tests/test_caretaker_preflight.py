"""Tests for iamai.caretaker_preflight — unified preflight health gate."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

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


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "index").write_bytes(b"\x00" * 12)
    return tmp_path


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "test"], capture_output=True, cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], capture_output=True, cwd=repo, check=True)
    (repo / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], capture_output=True, cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], capture_output=True, cwd=repo, check=True)
    return repo


# --- _pid_alive ---

def test_pid_alive_running(tmp_path: Path):
    pf = tmp_path / "alive.pid"
    pf.write_text(str(os.getpid()))
    assert _pid_alive(pf) is True


def test_pid_alive_dead(tmp_path: Path):
    pf = tmp_path / "dead.pid"
    pf.write_text("999999999")
    assert _pid_alive(pf) is False


def test_pid_alive_missing(tmp_path: Path):
    assert _pid_alive(tmp_path / "nope.pid") is False


def test_pid_alive_bad_content(tmp_path: Path):
    pf = tmp_path / "bad.pid"
    pf.write_text("abc")
    assert _pid_alive(pf) is False


# --- check_git_locks ---

def test_git_locks_clean(fake_repo: Path):
    r = check_git_locks(fake_repo)
    assert r["status"] == "ok"


def test_git_locks_fresh(fake_repo: Path):
    (fake_repo / ".git" / "index.lock").write_text("")
    r = check_git_locks(fake_repo)
    assert r["status"] == "warn"


def test_git_locks_stale(fake_repo: Path):
    lock = fake_repo / ".git" / "index.lock"
    lock.write_text("")
    t = time.time() - 600
    os.utime(lock, (t, t))
    r = check_git_locks(fake_repo)
    assert r["status"] == "fail"
    assert "STALE" in r["detail"]


# --- check_stroke_freshness ---

def test_stroke_fresh_missing(fake_repo: Path):
    r = check_stroke_freshness(fake_repo)
    assert r["status"] == "warn"


def test_stroke_fresh_empty(fake_repo: Path):
    s = fake_repo / "data" / "strokes.jsonl"
    s.parent.mkdir(parents=True)
    s.write_text("")
    r = check_stroke_freshness(fake_repo)
    assert r["status"] == "warn"


def test_stroke_fresh_ok(fake_repo: Path):
    s = fake_repo / "data" / "strokes.jsonl"
    s.parent.mkdir(parents=True)
    from datetime import datetime, timezone
    entry = {"seq": 1, "at": datetime.now(timezone.utc).isoformat(), "kind": "thought", "text": "hi"}
    s.write_text(json.dumps(entry) + "\n")
    r = check_stroke_freshness(fake_repo, cadence=15)
    assert r["status"] == "ok"


def test_stroke_fresh_fail(fake_repo: Path):
    s = fake_repo / "data" / "strokes.jsonl"
    s.parent.mkdir(parents=True)
    from datetime import datetime, timezone, timedelta
    old = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    entry = {"seq": 1, "at": old, "kind": "thought", "text": "old"}
    s.write_text(json.dumps(entry) + "\n")
    r = check_stroke_freshness(fake_repo, cadence=15)
    assert r["status"] == "fail"


def test_stroke_fresh_warn(fake_repo: Path):
    s = fake_repo / "data" / "strokes.jsonl"
    s.parent.mkdir(parents=True)
    from datetime import datetime, timezone, timedelta
    recent = (datetime.now(timezone.utc) - timedelta(seconds=40)).isoformat()
    entry = {"seq": 1, "at": recent, "kind": "thought", "text": "warm"}
    s.write_text(json.dumps(entry) + "\n")
    r = check_stroke_freshness(fake_repo, cadence=15)
    assert r["status"] == "warn"


def test_stroke_fresh_reads_last_line(fake_repo: Path):
    s = fake_repo / "data" / "strokes.jsonl"
    s.parent.mkdir(parents=True)
    from datetime import datetime, timezone, timedelta
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        json.dumps({"seq": 1, "at": old, "kind": "thought", "text": "old"}),
        json.dumps({"seq": 2, "at": now, "kind": "thought", "text": "new"}),
    ]
    s.write_text("\n".join(lines) + "\n")
    r = check_stroke_freshness(fake_repo, cadence=15)
    assert r["status"] == "ok"


# --- check_branch_drift ---

def test_branch_drift_no_remote(git_repo: Path):
    r = check_branch_drift(git_repo)
    assert r["status"] == "warn"
    assert "no upstream" in r["detail"]


def test_branch_drift_ahead(git_repo: Path):
    remote = git_repo.parent / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], capture_output=True, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], capture_output=True, cwd=git_repo, check=True)
    subprocess.run(["git", "push", "-u", "origin", "master"], capture_output=True, cwd=git_repo, check=True)
    (git_repo / "new.txt").write_text("x")
    subprocess.run(["git", "add", "."], capture_output=True, cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "second"], capture_output=True, cwd=git_repo, check=True)
    r = check_branch_drift(git_repo)
    assert r["status"] == "ok"
    assert r.get("ahead", 0) >= 1


# --- check_process_health ---

def test_process_health_both_down():
    r = check_process_health(writer_id="nonexistent_test_999")
    assert r["status"] == "fail"
    assert "DOWN" in r["detail"]


# --- check_pending_files ---

def test_pending_clean(git_repo: Path):
    r = check_pending_files(git_repo)
    assert r["status"] == "ok"
    assert r["count"] == 0


def test_pending_few(git_repo: Path):
    for i in range(3):
        (git_repo / f"f{i}.txt").write_text(f"c{i}")
    r = check_pending_files(git_repo)
    assert r["status"] == "ok"
    assert r["count"] == 3


def test_pending_warn(git_repo: Path):
    for i in range(15):
        (git_repo / f"f{i}.txt").write_text(f"c{i}")
    r = check_pending_files(git_repo)
    assert r["status"] == "warn"


def test_pending_fail(git_repo: Path):
    for i in range(60):
        (git_repo / f"f{i}.txt").write_text(f"c{i}")
    r = check_pending_files(git_repo, fail_at=50)
    assert r["status"] == "fail"


# --- run_preflight ---

def test_run_preflight_structure(fake_repo: Path):
    r = run_preflight(repo=fake_repo, writer_id="nonexistent_999")
    assert "checks" in r and len(r["checks"]) == 5
    assert "verdict" in r
    assert "ts" in r


def test_run_preflight_worst(fake_repo: Path):
    r = run_preflight(repo=fake_repo, writer_id="nonexistent_999")
    statuses = [c["status"] for c in r["checks"]]
    if "fail" in statuses:
        assert r["verdict"] == "fail"
    elif "warn" in statuses:
        assert r["verdict"] == "warn"


# --- rendering ---

def test_render_table():
    report = {
        "checks": [
            {"check": "git_locks", "status": "ok", "detail": "clean"},
            {"check": "branch_drift", "status": "fail", "detail": "behind 3"},
        ],
        "verdict": "fail",
    }
    t = render_table(report)
    assert "git_locks" in t
    assert "branch_drift" in t
    assert "fail" in t


def test_render_oneline_ok():
    report = {
        "checks": [
            {"check": "a", "status": "ok", "detail": "fine"},
            {"check": "b", "status": "ok", "detail": "fine"},
        ],
        "verdict": "ok",
    }
    o = render_oneline(report)
    assert "FAIL" not in o
    assert "ok=2/2" in o


def test_render_oneline_mixed():
    report = {
        "checks": [
            {"check": "locks", "status": "fail", "detail": "stale"},
            {"check": "drift", "status": "warn", "detail": "behind"},
            {"check": "files", "status": "ok", "detail": "clean"},
        ],
        "verdict": "fail",
    }
    o = render_oneline(report)
    assert "FAIL(locks)" in o
    assert "WARN(drift)" in o
    assert "ok=1/3" in o
