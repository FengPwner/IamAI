#!/usr/bin/env python3
"""divergence_resolver.py — automate the stash→pull→rebase→pop dance.

The writer in this repo continuously modifies tracked files (data/strokes.jsonl,
state files, metrics). When the remote has advanced (guoban pushes, another
caretaker commits), `git push` fails with "fetch first". The fix is mechanical
but fiddly:

    1. git stash              (save writer's in-flight changes)
    2. git pull --rebase      (replay local commits on top of remote)
    3. git stash pop          (restore writer's changes)

Each step can fail in ways that need specific handling:

    - stash fails: dirty index in a weird state, or nothing to stash
    - pull fails: merge conflict (shouldn't happen with union merge, but)
    - pop fails: conflict between stashed and rebased changes

This tool wraps the sequence with error handling and structured output,
so caretaker visits and the batch committer can both call it without
duplicating the shell incantation.

Usage:
    python3 tools/divergence_resolver.py
    python3 tools/divergence_resolver.py --json
    python3 tools/divergence_resolver.py --dry-run

Exit codes:
    0 — resolved, push should now succeed
    1 — nothing to resolve (already up to date)
    2 — resolution failed, manual intervention needed
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


REPO_DEFAULT = Path(__file__).resolve().parent.parent


@dataclass
class StepResult:
    step: str
    status: str       # "ok" | "skipped" | "failed"
    detail: str
    output: str = ""


@dataclass
class ResolveReport:
    steps: list[StepResult]
    verdict: str      # "resolved" | "clean" | "failed"
    message: str


def _run(cmd: list[str], cwd: Path, timeout: int = 120) -> tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd),
            capture_output=True, text=True,
            timeout=timeout,
            env=_git_env(),
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except FileNotFoundError as exc:
        return 127, "", str(exc)


def _git_env() -> dict:
    """Inherit GIT_SSH_COMMAND if set; ensures deploy key is used."""
    import os
    env = dict(os.environ)
    # Respect existing GIT_SSH_COMMAND from run_both.sh key rescue
    if "GIT_SSH_COMMAND" not in env:
        key = "/tmp/ssh_deploy_key"
        if Path(key).exists():
            env["GIT_SSH_COMMAND"] = (
                f"ssh -i {key} -o StrictHostKeyChecking=accept-new"
            )
    return env


def _is_behind(repo: Path) -> bool:
    """Check if local branch is behind origin."""
    rc, out, _ = _run(
        ["git", "rev-list", "--left-right", "--count", "HEAD...origin/main"],
        cwd=repo,
    )
    if rc != 0:
        return False
    parts = out.split()
    if len(parts) == 2:
        # left = ahead, right = behind
        behind = int(parts[1])
        return behind > 0
    return False


def _is_dirty(repo: Path) -> bool:
    """Check if working tree has uncommitted changes."""
    rc, out, _ = _run(["git", "status", "--porcelain"], cwd=repo)
    return bool(out.strip())


def resolve(repo: Path | None = None, dry_run: bool = False) -> ResolveReport:
    """Execute the divergence resolution sequence."""
    repo = repo or REPO_DEFAULT
    steps: list[StepResult] = []

    # Step 0: fetch to know remote state
    rc, out, err = _run(["git", "fetch", "origin", "main"], cwd=repo)
    if rc != 0:
        steps.append(StepResult("fetch", "failed", err, out))
        return ResolveReport(steps, "failed", f"fetch failed: {err}")
    steps.append(StepResult("fetch", "ok", "fetched origin/main", out))

    # Step 1: check if we're actually behind
    if not _is_behind(repo):
        steps.append(StepResult("check", "skipped", "already up to date"))
        return ResolveReport(steps, "clean", "no divergence to resolve")

    if dry_run:
        steps.append(StepResult("dry-run", "ok", "would resolve (behind remote)"))
        return ResolveReport(steps, "resolved", "dry run: divergence detected, would resolve")

    # Step 2: stash if dirty
    dirty = _is_dirty(repo)
    if dirty:
        rc, out, err = _run(["git", "stash", "push", "-m", "divergence_resolver: auto-stash"], cwd=repo)
        if rc != 0:
            steps.append(StepResult("stash", "failed", err, out))
            return ResolveReport(steps, "failed", f"stash failed: {err}")
        steps.append(StepResult("stash", "ok", "stashed working changes", out))
    else:
        steps.append(StepResult("stash", "skipped", "working tree clean"))

    # Step 3: pull --rebase
    rc, out, err = _run(["git", "pull", "--rebase", "origin", "main"], cwd=repo)
    if rc != 0:
        steps.append(StepResult("rebase", "failed", err, out))
        # Attempt to abort the failed rebase
        _run(["git", "rebase", "--abort"], cwd=repo)
        if dirty:
            _run(["git", "stash", "pop"], cwd=repo)
        return ResolveReport(steps, "failed", f"rebase failed: {err}")
    steps.append(StepResult("rebase", "ok", "rebased onto origin/main", out))

    # Step 4: pop stash if we stashed
    if dirty:
        rc, out, err = _run(["git", "stash", "pop"], cwd=repo)
        if rc != 0:
            steps.append(StepResult("pop", "failed", err, out))
            return ResolveReport(steps, "failed", f"stash pop failed: {err}")
        steps.append(StepResult("pop", "ok", "restored stashed changes", out))
    else:
        steps.append(StepResult("pop", "skipped", "nothing to pop"))

    return ResolveReport(steps, "resolved", "divergence resolved, ready to push")


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve git push divergence")
    parser.add_argument("--json", action="store_true", help="output as JSON")
    parser.add_argument("--dry-run", action="store_true", help="check only, don't modify")
    parser.add_argument("--repo", type=Path, default=REPO_DEFAULT, help="repo path")
    args = parser.parse_args()

    report = resolve(repo=args.repo, dry_run=args.dry_run)

    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        for step in report.steps:
            icon = {"ok": "✓", "skipped": "–", "failed": "✗"}[step.status]
            print(f"  {icon} {step.step:10s} {step.detail}")
        print(f"\n  verdict: {report.verdict} — {report.message}")

    return {"resolved": 0, "clean": 1, "failed": 2}[report.verdict]


if __name__ == "__main__":
    sys.exit(main())
