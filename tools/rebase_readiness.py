#!/usr/bin/env python3
"""rebase_readiness.py — check whether a safe rebase onto a remote branch is possible.

Answers the question every caretaker hits at 3am: "can I rebase right now, or will
the writer's dirty files blow it up?"

Checks performed:
  1. Working tree cleanliness (staged vs unstaged vs untracked)
  2. Writer/batch process liveness (pidfiles + kill -0)
  3. Divergence depth (local-ahead vs remote-ahead commit counts)
  4. Merge driver configuration (union driver registered?)

Exit codes:
  0 — clean, rebase safe to attempt
  1 — dirty tree (commit or stash first)
  2 — writer still running (stop it first)
  3 — both dirty and running
  4 — repo not found or git unavailable

Usage:
    python3 tools/rebase_readiness.py
    python3 tools/rebase_readiness.py --remote origin/main
    python3 tools/rebase_readiness.py --json
    python3 tools/rebase_readiness.py --fix   # commit dirty files, print next-step hint
"""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class ReadinessReport:
    """Structured result of all readiness checks."""

    repo_path: str = ""
    tree_clean: bool = True
    staged_files: List[str] = field(default_factory=list)
    unstaged_files: List[str] = field(default_factory=list)
    untracked_files: List[str] = field(default_factory=list)
    writer_running: bool = False
    writer_pid: Optional[int] = None
    batch_running: bool = False
    batch_pid: Optional[int] = None
    writer_id: str = "qwen"
    local_ahead: int = 0
    remote_ahead: int = 0
    common_ancestor: str = ""
    union_driver_configured: bool = False
    remote_ref: str = "origin/main"
    verdict: int = 0  # 0=clean, 1=dirty, 2=running, 3=both
    hint: str = ""

    def to_dict(self) -> dict:
        return {
            "repo_path": self.repo_path,
            "tree_clean": self.tree_clean,
            "staged_files": self.staged_files,
            "unstaged_files": self.unstaged_files,
            "untracked_files": self.untracked_files,
            "writer_running": self.writer_running,
            "writer_pid": self.writer_pid,
            "batch_running": self.batch_running,
            "batch_pid": self.batch_pid,
            "writer_id": self.writer_id,
            "local_ahead": self.local_ahead,
            "remote_ahead": self.remote_ahead,
            "common_ancestor": self.common_ancestor,
            "union_driver_configured": self.union_driver_configured,
            "remote_ref": self.remote_ref,
            "verdict": self.verdict,
            "hint": self.hint,
        }


def find_repo_root(start: str = ".") -> Optional[str]:
    """Walk up from *start* to find the nearest .git directory."""
    try:
        result = subprocess.run(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _run_git(args: List[str], cwd: str) -> Tuple[int, str, str]:
    """Run a git command, returning (rc, stdout, stderr)."""
    try:
        r = subprocess.run(
            ["git"] + args, cwd=cwd,
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode, r.stdout, r.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return 128, "", str(e)


def parse_porcelain(raw: str) -> Tuple[List[str], List[str], List[str]]:
    """Split `git status --porcelain` output into staged / unstaged / untracked.

    Porcelain format (two-char status + space + path):
      'M  file'  → staged modification
      ' M file'  → unstaged modification
      '?? file'  → untracked
      'MM file'  → both staged and unstaged
    """
    staged, unstaged, untracked = [], [], []
    for line in raw.splitlines():
        if len(line) < 4:
            continue
        index_char = line[0]
        work_char = line[1]
        path = line[3:].strip()
        # strip rename arrow
        if " -> " in path:
            path = path.split(" -> ")[-1]

        if index_char == "?" and work_char == "?":
            untracked.append(path)
        else:
            if index_char not in (" ", "?"):
                staged.append(path)
            if work_char not in (" ", "?"):
                unstaged.append(path)
    return staged, unstaged, untracked


def check_tree(repo: str) -> Tuple[List[str], List[str], List[str]]:
    """Return (staged, unstaged, untracked) from git status."""
    rc, out, _ = _run_git(["status", "--porcelain"], repo)
    if rc != 0:
        return [], [], []
    return parse_porcelain(out)


def check_process_liveness(writer_id: str = "qwen") -> dict:
    """Check pidfiles and verify process is alive."""
    info = {
        "writer_running": False,
        "writer_pid": None,
        "batch_running": False,
        "batch_pid": None,
    }
    for role in ("writer", "batch"):
        pidfile = Path(f"/tmp/iamai-{role}-{writer_id}.pid")
        if pidfile.exists():
            try:
                pid = int(pidfile.read_text().strip())
                os.kill(pid, 0)  # signal 0 = liveness check
                info[f"{role}_running"] = True
                info[f"{role}_pid"] = pid
            except (ValueError, ProcessLookupError, PermissionError):
                pass
    return info


def check_divergence(repo: str, remote_ref: str = "origin/main") -> Tuple[int, int, str]:
    """Return (local_ahead, remote_ahead, common_ancestor_sha)."""
    rc, out, _ = _run_git(
        ["rev-list", "--left-right", "--count", f"HEAD...{remote_ref}"], repo
    )
    if rc != 0:
        return 0, 0, ""
    parts = out.strip().split()
    if len(parts) != 2:
        return 0, 0, ""
    local_ahead, remote_ahead = int(parts[0]), int(parts[1])

    rc2, ancestor, _ = _run_git(["merge-base", "HEAD", remote_ref], repo)
    ancestor_sha = ancestor.strip() if rc2 == 0 else ""
    return local_ahead, remote_ahead, ancestor_sha


def check_union_driver(repo: str) -> bool:
    """Check whether the union merge driver is configured."""
    rc, out, _ = _run_git(["config", "merge.union.driver"], repo)
    return rc == 0 and "merge-file --union" in out


def assess(repo: Optional[str] = None, remote_ref: str = "origin/main",
           writer_id: str = "qwen") -> ReadinessReport:
    """Run all checks and return a ReadinessReport."""
    if repo is None:
        repo = find_repo_root(".")
    if repo is None:
        return ReadinessReport(verdict=4, hint="not a git repo (or git not found)")

    report = ReadinessReport(repo_path=repo, remote_ref=remote_ref, writer_id=writer_id)

    # 1. tree cleanliness
    staged, unstaged, untracked = check_tree(repo)
    report.staged_files = staged
    report.unstaged_files = unstaged
    report.untracked_files = untracked
    dirty = bool(staged or unstaged or untracked)
    report.tree_clean = not dirty

    # 2. process liveness
    proc = check_process_liveness(writer_id)
    report.writer_running = proc["writer_running"]
    report.writer_pid = proc["writer_pid"]
    report.batch_running = proc["batch_running"]
    report.batch_pid = proc["batch_pid"]

    # 3. divergence
    local_ahead, remote_ahead, ancestor = check_divergence(repo, remote_ref)
    report.local_ahead = local_ahead
    report.remote_ahead = remote_ahead
    report.common_ancestor = ancestor

    # 4. merge driver
    report.union_driver_configured = check_union_driver(repo)

    # verdict
    dirty_flag = 1 if dirty else 0
    running_flag = 2 if (report.writer_running or report.batch_running) else 0
    report.verdict = dirty_flag | running_flag

    hints = {
        0: "safe to rebase",
        1: "dirty tree — commit or stash before rebasing",
        2: "writer/batch still running — stop with `bash tools/run_both.sh --stop`",
        3: "dirty tree AND processes running — stop processes, commit, then rebase",
        4: "not a git repo",
    }
    report.hint = hints.get(report.verdict, "unknown state")
    return report


def print_text_report(r: ReadinessReport) -> None:
    """Human-readable output for terminal use."""
    status = "CLEAN" if r.tree_clean else "DIRTY"
    print(f"rebase readiness: {status}  (verdict={r.verdict})")
    print(f"  repo:    {r.repo_path}")
    print(f"  remote:  {r.remote_ref}")
    print(f"  writer:  {'running pid ' + str(r.writer_pid) if r.writer_running else 'stopped'}")
    print(f"  batch:   {'running pid ' + str(r.batch_pid) if r.batch_running else 'stopped'}")

    if not r.tree_clean:
        n = len(r.staged_files) + len(r.unstaged_files) + len(r.untracked_files)
        print(f"  tree:    {n} dirty file(s)")
        for f in r.staged_files[:5]:
            print(f"    M  {f}  (staged)")
        for f in r.unstaged_files[:5]:
            print(f"     M {f}  (unstaged)")
        for f in r.untracked_files[:5]:
            print(f"    ?? {f}  (untracked)")
    else:
        print("  tree:    clean")

    if r.remote_ahead > 0:
        print(f"  diverge: local +{r.local_ahead} / remote +{r.remote_ahead} from {r.common_ancestor[:8]}")
    elif r.local_ahead > 0:
        print(f"  ahead:   {r.local_ahead} commit(s) — push should succeed")
    else:
        print("  diverge: in sync")

    print(f"  union:   {'configured' if r.union_driver_configured else 'NOT configured'}")
    print(f"  hint:    {r.hint}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check rebase readiness for IamAI repo.")
    parser.add_argument("--remote", default="origin/main", help="remote ref to compare against")
    parser.add_argument("--writer", default="qwen", help="writer id for pidfile lookup")
    parser.add_argument("--json", action="store_true", help="output JSON instead of text")
    parser.add_argument("--fix", action="store_true",
                        help="if dirty, commit staged+unstaged files and print next-step hint")
    args = parser.parse_args()

    repo = find_repo_root(".")
    if repo is None:
        print("error: not inside a git repository", file=sys.stderr)
        return 4

    if args.fix:
        staged, unstaged, _ = check_tree(repo)
        if staged or unstaged:
            all_files = staged + unstaged
            _run_git(["add", "--"] + all_files, repo)
            _run_git(["commit", "-m", "rebase_readiness: auto-commit before rebase"], repo)
            print(f"committed {len(all_files)} file(s)")

    report = assess(repo=repo, remote_ref=args.remote, writer_id=args.writer)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print_text_report(report)

    return report.verdict


if __name__ == "__main__":
    sys.exit(main())
