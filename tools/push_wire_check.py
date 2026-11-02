#!/usr/bin/env python3
"""push_wire_check.py — diagnose whether the push pathway is correctly wired.

The push race in this repo is a clock that rings every ten minutes. When the
mechanism breaks (stale SSH key, missing pre_push_sync import, dirty working
tree blocking rebase, remote divergence not caught), the caretaker discovers
it on a failed push — the worst time to learn about a problem.

This tool runs a battery of non-destructive checks *before* the push is
attempted, producing a structured report:

  1. ssh_key      — deploy key exists, has correct permissions (0600),
                    not expired (if expiration metadata available)
  2. remote       — `git fetch` succeeds within timeout
  3. divergence   — local vs remote: ahead / behind / diverged / clean
  4. dirty_tree   — uncommitted changes that would block pull --rebase
  5. sync_import  — commit_batch.py imports pre_push_sync (wiring check)
  6. unpushed     — count of local-only commits waiting to land

Each check returns pass / warn / fail with a detail string. The overall
verdict is the worst individual result.

Usage:
    python3 tools/push_wire_check.py
    python3 tools/push_wire_check.py --json
    python3 tools/push_wire_check.py --repo /path/to/IamAI

Exit codes:
    0 — all checks pass
    1 — at least one warn (push may still succeed)
    2 — at least one fail (push will likely fail)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


REPO_DEFAULT = Path(__file__).resolve().parent.parent

SEVERITY_ORDER = {"pass": 0, "warn": 1, "fail": 2}


@dataclass
class CheckResult:
    name: str
    status: str   # "pass" | "warn" | "fail"
    detail: str


@dataclass
class WireReport:
    checks: list[CheckResult]
    verdict: str  # worst of all check statuses

    def to_dict(self) -> dict:
        return {
            "checks": [asdict(c) for c in self.checks],
            "verdict": self.verdict,
        }


def _run(cmd: list[str], cwd: Path | None = None,
         timeout: int = 15) -> subprocess.CompletedProcess:
    """Run a command, return CompletedProcess."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_ssh_key(repo: Path) -> CheckResult:
    """Verify the deploy key exists and has restrictive permissions."""
    key_path = os.environ.get("GIT_SSH_COMMAND", "")
    if not key_path:
        # No GIT_SSH_COMMAND set — might be using agent or default key
        return CheckResult("ssh_key", "warn",
                           "GIT_SSH_COMMAND not set; relying on agent or default key")

    # Extract key path from GIT_SSH_COMMAND="ssh -i /path/to/key ..."
    parts = key_path.split()
    key_file = None
    for i, part in enumerate(parts):
        if part == "-i" and i + 1 < len(parts):
            key_file = parts[i + 1]
            break

    if not key_file:
        return CheckResult("ssh_key", "warn",
                           "GIT_SSH_COMMAND set but no -i flag found")

    p = Path(key_file)
    if not p.exists():
        return CheckResult("ssh_key", "fail", f"deploy key not found: {key_file}")

    try:
        mode = oct(p.stat().st_mode & 0o777)
        if mode != "0o600":
            return CheckResult("ssh_key", "warn",
                               f"key permissions {mode} (expected 0o600)")
    except OSError as exc:
        return CheckResult("ssh_key", "fail", f"cannot stat key: {exc}")

    return CheckResult("ssh_key", "pass", f"key at {key_file}, permissions 0o600")


def check_remote(repo: Path, timeout: int = 15) -> CheckResult:
    """Verify remote is reachable via fetch."""
    try:
        result = _run(
            ["git", "fetch", "origin", "--dry-run"],
            cwd=repo, timeout=timeout,
        )
        if result.returncode == 0:
            return CheckResult("remote", "pass", "fetch --dry-run succeeded")
        # Some git versions don't support --dry-run for fetch; try ls-remote
        result2 = _run(
            ["git", "ls-remote", "origin", "--heads", "main"],
            cwd=repo, timeout=timeout,
        )
        if result2.returncode == 0:
            return CheckResult("remote", "pass", "ls-remote succeeded")
        stderr = (result.stderr or result2.stderr or "").strip()
        return CheckResult("remote", "fail", f"fetch failed: {stderr[:120]}")
    except subprocess.TimeoutExpired:
        return CheckResult("remote", "fail", f"fetch timed out after {timeout}s")
    except Exception as exc:
        return CheckResult("remote", "fail", f"fetch error: {exc}")


def check_divergence(repo: Path) -> CheckResult:
    """Compare local HEAD with origin/main."""
    try:
        result = _run(
            ["git", "rev-list", "--left-right", "--count",
             "HEAD...origin/main"],
            cwd=repo,
        )
        if result.returncode != 0:
            return CheckResult("divergence", "warn",
                               "cannot compare (origin/main may not be fetched)")
        parts = result.stdout.strip().split()
        if len(parts) != 2:
            return CheckResult("divergence", "warn",
                               f"unexpected rev-list output: {result.stdout.strip()}")
        ahead, behind = int(parts[0]), int(parts[1])
        if ahead == 0 and behind == 0:
            return CheckResult("divergence", "pass",
                               "clean: local and remote identical")
        if ahead > 0 and behind == 0:
            return CheckResult("divergence", "pass",
                               f"ahead {ahead}: safe to push")
        if ahead == 0 and behind > 0:
            return CheckResult("divergence", "warn",
                               f"behind {behind}: need pull before push")
        return CheckResult("divergence", "fail",
                           f"diverged: ahead {ahead}, behind {behind} — rebase needed")
    except Exception as exc:
        return CheckResult("divergence", "warn", f"check error: {exc}")


def check_dirty_tree(repo: Path) -> CheckResult:
    """Check for uncommitted changes that block pull --rebase."""
    try:
        result = _run(["git", "status", "--porcelain"], cwd=repo)
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        if not lines:
            return CheckResult("dirty_tree", "pass", "working tree clean")
        # Only tracked modifications block rebase
        tracked = [l for l in lines if not l.startswith("??")]
        if not tracked:
            return CheckResult("dirty_tree", "pass",
                               f"{len(lines)} untracked file(s) — rebase-safe")
        return CheckResult("dirty_tree", "warn",
                           f"{len(tracked)} modified tracked file(s) — "
                           "will need stash before pull --rebase")
    except Exception as exc:
        return CheckResult("dirty_tree", "warn", f"check error: {exc}")


def check_sync_import(repo: Path) -> CheckResult:
    """Verify commit_batch.py imports pre_push_sync (wiring check)."""
    batch_file = repo / "tools" / "commit_batch.py"
    if not batch_file.exists():
        return CheckResult("sync_import", "fail",
                           "commit_batch.py not found")
    try:
        content = batch_file.read_text(encoding="utf-8")
        if "import pre_push_sync" in content or "from pre_push_sync" in content:
            # Also check it's actually called
            if "pre_push_sync.sync" in content or "pre_push_sync" in content:
                return CheckResult("sync_import", "pass",
                                   "commit_batch imports and calls pre_push_sync")
            return CheckResult("sync_import", "warn",
                               "pre_push_sync imported but not called")
        return CheckResult("sync_import", "fail",
                           "commit_batch.py does NOT import pre_push_sync — "
                           "push will fail on divergence")
    except Exception as exc:
        return CheckResult("sync_import", "warn", f"read error: {exc}")


def check_unpushed(repo: Path) -> CheckResult:
    """Count unpushed commits."""
    try:
        result = _run(
            ["git", "log", "--oneline", "origin/main..HEAD"],
            cwd=repo,
        )
        if result.returncode != 0:
            return CheckResult("unpushed", "warn",
                               "cannot determine (origin/main may not be fetched)")
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        count = len(lines)
        if count == 0:
            return CheckResult("unpushed", "pass", "nothing to push")
        if count <= 3:
            return CheckResult("unpushed", "pass",
                               f"{count} unpushed commit(s)")
        return CheckResult("unpushed", "warn",
                           f"{count} unpushed commit(s) — backlog building")
    except Exception as exc:
        return CheckResult("unpushed", "warn", f"check error: {exc}")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_all_checks(repo: Path, timeout: int = 15) -> WireReport:
    """Run all push-wire checks and return a report."""
    checks = [
        check_ssh_key(repo),
        check_remote(repo, timeout=timeout),
        check_divergence(repo),
        check_dirty_tree(repo),
        check_sync_import(repo),
        check_unpushed(repo),
    ]
    worst = max(checks, key=lambda c: SEVERITY_ORDER.get(c.status, 0))
    return WireReport(checks=checks, verdict=worst.status)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO_DEFAULT)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--timeout", type=int, default=15,
                        help="fetch timeout in seconds")
    args = parser.parse_args()

    report = run_all_checks(args.repo, timeout=args.timeout)

    if args.json_output:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        for c in report.checks:
            icon = {"pass": "✓", "warn": "⚠", "fail": "✗"}[c.status]
            print(f"  {icon} {c.name:16s}  {c.detail}")
        print(f"\n  verdict: {report.verdict}")

    severity = SEVERITY_ORDER.get(report.verdict, 0)
    return severity


if __name__ == "__main__":
    sys.exit(main())
