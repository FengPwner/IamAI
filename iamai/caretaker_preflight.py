"""caretaker_preflight — unified health gate before commit/push operations.

Combines five independent checks into a single report so caretakers don't
have to call each tool individually and piece together the results.

Each check returns one of ``ok``, ``warn``, or ``fail``.  The overall
verdict is the worst individual status (fail > warn > ok).

Exit codes (for the CLI wrapper):
    0 — all ok
    1 — at least one fail
    2 — at least one warn, no fail

Usage::

    from iamai.caretaker_preflight import run_preflight, render_table

    report = run_preflight(repo)
    print(render_table(report))

    if report["verdict"] == "fail":
        sys.exit(1)
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _run_git(*args: str, cwd: Path | None = None) -> tuple[int, str]:
    """Run a git command and return (exit_code, stdout)."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True,
            text=True,
            cwd=cwd or REPO,
            timeout=30,
        )
        return result.returncode, result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 1, ""


def _pid_alive(pid_file: Path) -> bool:
    """Check whether the PID recorded in *pid_file* is still running."""
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


# ---------------------------------------------------------------------------
# individual checks
# ---------------------------------------------------------------------------

def check_git_locks(repo: Path) -> dict[str, Any]:
    """Check for stale .git/index.lock and other lock files."""
    lock = repo / ".git" / "index.lock"
    if not lock.exists():
        return {"check": "git_locks", "status": "ok", "detail": "no stale locks"}
    try:
        age = time.time() - lock.stat().st_mtime
    except OSError:
        age = 0
    stale = age > 300
    return {
        "check": "git_locks",
        "status": "fail" if stale else "warn",
        "detail": f"index.lock exists, age {age:.0f}s" + (" (STALE)" if stale else ""),
    }


def check_stroke_freshness(repo: Path, cadence: int = 15) -> dict[str, Any]:
    """How recent is the last stroke in data/strokes.jsonl?"""
    strokes = repo / "data" / "strokes.jsonl"
    if not strokes.exists():
        return {"check": "stroke_freshness", "status": "warn", "detail": "strokes.jsonl not found"}
    try:
        with open(strokes, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return {"check": "stroke_freshness", "status": "warn", "detail": "strokes.jsonl is empty"}
            # Skip trailing newline if present
            pos = size - 1
            f.seek(pos)
            if f.read(1) == b"\n":
                pos -= 1
            # Scan backwards for the previous newline
            while pos > 0:
                f.seek(pos)
                if f.read(1) == b"\n":
                    pos += 1
                    break
                pos -= 1
            else:
                pos = 0
            f.seek(pos)
            last_line = f.readline().decode("utf-8").strip()

        entry = json.loads(last_line)
        from datetime import datetime, timezone
        at_str = entry.get("at", "")
        at_dt = datetime.fromisoformat(at_str)
        age = (datetime.now(timezone.utc) - at_dt).total_seconds()
    except Exception as exc:
        return {"check": "stroke_freshness", "status": "warn", "detail": f"parse error: {exc}"}

    if age < cadence * 2:
        verdict = "ok"
    elif age < cadence * 5:
        verdict = "warn"
    else:
        verdict = "fail"

    return {
        "check": "stroke_freshness",
        "status": verdict,
        "detail": f"last stroke {age:.0f}s ago (cadence {cadence}s)",
    }


def check_branch_drift(repo: Path) -> dict[str, Any]:
    """How far is local from the remote tracking branch?"""
    rc, branch = _run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo)
    if rc != 0 or branch == "HEAD":
        return {"check": "branch_drift", "status": "warn", "detail": "detached HEAD or no branch"}

    rc, upstream = _run_git("rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}", cwd=repo)
    if rc != 0:
        return {"check": "branch_drift", "status": "warn", "detail": "no upstream tracking branch"}

    rc, ahead = _run_git("rev-list", "--count", f"{upstream}..{branch}", cwd=repo)
    rc2, behind = _run_git("rev-list", "--count", f"{branch}..{upstream}", cwd=repo)

    a = int(ahead) if rc == 0 and ahead.isdigit() else 0
    b = int(behind) if rc2 == 0 and behind.isdigit() else 0

    if b > 0 and a > 0:
        verdict = "fail"
        detail = f"diverged: {a} ahead, {b} behind (rebase needed)"
    elif b > 0:
        verdict = "fail"
        detail = f"{b} behind (pull needed)"
    elif a > 0:
        verdict = "ok"
        detail = f"{a} ahead, 0 behind (push ready)"
    else:
        verdict = "ok"
        detail = "synced"

    return {"check": "branch_drift", "status": verdict, "detail": detail, "ahead": a, "behind": b}


def check_process_health(writer_id: str = "qwen") -> dict[str, Any]:
    """Are writer and batch processes alive?"""
    writer_pid = Path(f"/tmp/iamai-writer-{writer_id}.pid")
    batch_pid = Path(f"/tmp/iamai-batch-{writer_id}.pid")

    w_alive = _pid_alive(writer_pid)
    b_alive = _pid_alive(batch_pid)

    if w_alive and b_alive:
        verdict, detail = "ok", "writer up, batch up"
    elif w_alive:
        verdict, detail = "warn", "writer up, batch DOWN"
    elif b_alive:
        verdict, detail = "warn", "writer DOWN, batch up"
    else:
        verdict, detail = "fail", "writer DOWN, batch DOWN"

    return {
        "check": "process_health", "status": verdict, "detail": detail,
        "writer_alive": w_alive, "batch_alive": b_alive,
    }


def check_pending_files(repo: Path, warn_at: int = 10, fail_at: int = 50) -> dict[str, Any]:
    """How many files have uncommitted changes?"""
    rc, out = _run_git("status", "--porcelain", cwd=repo)
    if rc != 0:
        return {"check": "pending_files", "status": "warn", "detail": "git status failed", "count": -1}
    lines = [l for l in out.splitlines() if l.strip()] if out else []
    count = len(lines)

    if count == 0:
        verdict, detail = "ok", "working tree clean"
    elif count < warn_at:
        verdict, detail = "ok", f"{count} file(s) uncommitted (normal)"
    elif count < fail_at:
        verdict, detail = "warn", f"{count} file(s) uncommitted (piling up)"
    else:
        verdict, detail = "fail", f"{count} file(s) uncommitted (backlog critical)"

    return {"check": "pending_files", "status": verdict, "detail": detail, "count": count}


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

_PRIORITY = {"ok": 0, "warn": 1, "fail": 2}


def run_preflight(
    repo: Path | str | None = None,
    writer_id: str = "qwen",
    cadence: int = 15,
) -> dict[str, Any]:
    """Run all preflight checks and return a unified report."""
    repo = Path(repo) if repo else REPO
    checks = [
        check_git_locks(repo),
        check_stroke_freshness(repo, cadence=cadence),
        check_branch_drift(repo),
        check_process_health(writer_id),
        check_pending_files(repo),
    ]
    worst = max(checks, key=lambda c: _PRIORITY.get(c["status"], 0))
    return {"checks": checks, "verdict": worst["status"], "ts": time.time()}


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def render_table(report: dict[str, Any]) -> str:
    """Render a preflight report as a fixed-width ASCII table."""
    rows = report["checks"]
    name_w = max(len(r["check"]) for r in rows)
    stat_w = 4

    lines = []
    lines.append(f"{'check':<{name_w}}  {'status':<{stat_w}}  detail")
    lines.append(f"{'─' * name_w}  {'─' * stat_w}  {'─' * 42}")
    for r in rows:
        lines.append(f"{r['check']:<{name_w}}  {r['status']:<{stat_w}}  {r['detail']}")
    lines.append(f"\nverdict: {report['verdict']}")
    return "\n".join(lines)


def render_oneline(report: dict[str, Any]) -> str:
    """Compact one-line summary for caretaker logs."""
    checks = report["checks"]
    fails = [c for c in checks if c["status"] == "fail"]
    warns = [c for c in checks if c["status"] == "warn"]
    parts = []
    if fails:
        parts.append(f"FAIL({','.join(c['check'] for c in fails)})")
    if warns:
        parts.append(f"WARN({','.join(c['check'] for c in warns)})")
    ok_count = sum(1 for c in checks if c["status"] == "ok")
    parts.append(f"ok={ok_count}/{len(checks)}")
    return " ".join(parts)
