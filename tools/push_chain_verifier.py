#!/usr/bin/env python3
"""push_chain_verifier — check that write → commit → push is healthy.

The IamAI repo has three failure modes that compound:
1. Writer dies → strokes stop accumulating
2. Batch committer dies → strokes accumulate but don't get committed
3. Push fails → commits accumulate locally but don't reach GitHub

Each failure is silent on its own. This tool checks all three at once
and returns a structured verdict so caretakers can act on the first
failure instead of discovering the third.

Usage:
    python3 tools/push_chain_verifier.py          # check all three stages
    python3 tools/push_chain_verifier.py --json    # machine-readable output

Exit codes:
    0 = all stages healthy
    1 = at least one stage unhealthy
    2 = could not determine (missing tools, repo not found, etc.)
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple, Optional


REPO = Path(__file__).resolve().parent.parent


class StageResult(NamedTuple):
    name: str
    healthy: bool
    detail: str
    latency_ms: int = 0


def _run(cmd: list[str], cwd: Optional[Path] = None, timeout: int = 15) -> tuple[int, str, str]:
    """Run a command and return (exit_code, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError:
        return -2, "", f"command not found: {cmd[0]}"


def check_writer(repo: Path = REPO) -> StageResult:
    """Stage 1: Is the writer process running?"""
    t0 = time.monotonic()
    pid_file = Path("/tmp/iamai-writer-qwen.pid")
    if not pid_file.exists():
        ms = int((time.monotonic() - t0) * 1000)
        return StageResult("writer", False, "no pid file", ms)
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError) as e:
        ms = int((time.monotonic() - t0) * 1000)
        return StageResult("writer", False, f"bad pid file: {e}", ms)
    code, _, _ = _run(["kill", "-0", str(pid)])
    ms = int((time.monotonic() - t0) * 1000)
    if code == 0:
        return StageResult("writer", True, f"pid {pid} alive", ms)
    return StageResult("writer", False, f"pid {pid} not running", ms)


def check_batch(repo: Path = REPO) -> StageResult:
    """Stage 2: Is the batch committer running?"""
    t0 = time.monotonic()
    pid_file = Path("/tmp/iamai-batch-qwen.pid")
    if not pid_file.exists():
        ms = int((time.monotonic() - t0) * 1000)
        return StageResult("batch", False, "no pid file", ms)
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError) as e:
        ms = int((time.monotonic() - t0) * 1000)
        return StageResult("batch", False, f"bad pid file: {e}", ms)
    code, _, _ = _run(["kill", "-0", str(pid)])
    ms = int((time.monotonic() - t0) * 1000)
    if code == 0:
        return StageResult("batch", True, f"pid {pid} alive", ms)
    return StageResult("batch", False, f"pid {pid} not running", ms)


def check_uncommitted(repo: Path = REPO) -> StageResult:
    """Stage 2b: How many files are uncommitted?"""
    t0 = time.monotonic()
    code, out, err = _run(
        ["git", "status", "--porcelain"],
        cwd=repo,
    )
    ms = int((time.monotonic() - t0) * 1000)
    if code != 0:
        return StageResult("uncommitted", False, f"git error: {err}", ms)
    count = len(out.splitlines()) if out.strip() else 0
    healthy = count <= 5  # a few transient writes are fine
    return StageResult("uncommitted", healthy, f"{count} file(s) uncommitted", ms)


def check_unpushed(repo: Path = REPO) -> StageResult:
    """Stage 3: How many commits are unpushed?"""
    t0 = time.monotonic()
    code, out, err = _run(
        ["git", "log", "--oneline", "origin/main..HEAD"],
        cwd=repo,
    )
    ms = int((time.monotonic() - t0) * 1000)
    if code != 0:
        return StageResult("unpushed", False, f"git error: {err}", ms)
    count = len(out.splitlines()) if out.strip() else 0
    healthy = count <= 2  # one or two ahead is normal between batches
    return StageResult("unpushed", healthy, f"{count} commit(s) unpushed", ms)


def check_ssh_key() -> StageResult:
    """Stage 3a: Is the SSH deploy key present and usable?"""
    t0 = time.monotonic()
    key_path = Path("/tmp/ssh_deploy_key")
    if not key_path.exists():
        ms = int((time.monotonic() - t0) * 1000)
        return StageResult("ssh_key", False, "deploy key missing", ms)
    stat = key_path.stat()
    mode = oct(stat.st_mode)[-3:]
    if mode != "600":
        ms = int((time.monotonic() - t0) * 1000)
        return StageResult("ssh_key", False, f"bad permissions: {mode}", ms)
    ms = int((time.monotonic() - t0) * 1000)
    return StageResult("ssh_key", True, f"present, mode {mode}", ms)


def check_remote(repo: Path = REPO) -> StageResult:
    """Stage 3b: Can we reach the remote?"""
    t0 = time.monotonic()
    ssh_cmd = os.environ.get(
        "GIT_SSH_COMMAND",
        "ssh -i /tmp/ssh_deploy_key -o StrictHostKeyChecking=no -o BatchMode=yes",
    )
    env = {**os.environ, "GIT_SSH_COMMAND": ssh_cmd}
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--exit-code", "origin", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        ms = int((time.monotonic() - t0) * 1000)
        if proc.returncode == 0:
            return StageResult("remote", True, "reachable", ms)
        return StageResult("remote", False, proc.stderr.strip() or "unreachable", ms)
    except subprocess.TimeoutExpired:
        ms = int((time.monotonic() - t0) * 1000)
        return StageResult("remote", False, "timeout after 15s", ms)


def verify_chain(repo: Path = REPO) -> list[StageResult]:
    """Run all chain checks and return results."""
    return [
        check_writer(repo),
        check_batch(repo),
        check_uncommitted(repo),
        check_unpushed(repo),
        check_ssh_key(),
        check_remote(repo),
    ]


def format_results(results: list[StageResult], as_json: bool = False) -> str:
    """Format results for display."""
    if as_json:
        return json.dumps(
            [
                {
                    "stage": r.name,
                    "healthy": r.healthy,
                    "detail": r.detail,
                    "latency_ms": r.latency_ms,
                }
                for r in results
            ],
            indent=2,
        )
    lines = []
    for r in results:
        status = "OK" if r.healthy else "FAIL"
        lines.append(f"  [{status:4s}] {r.name:12s} {r.detail} ({r.latency_ms}ms)")
    all_ok = all(r.healthy for r in results)
    header = "CHAIN HEALTHY" if all_ok else "CHAIN UNHEALTHY"
    return f"{header}\n" + "\n".join(lines)


def main():
    as_json = "--json" in sys.argv
    results = verify_chain()
    print(format_results(results, as_json))
    all_ok = all(r.healthy for r in results)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
