#!/usr/bin/env python3
"""push_sync.py — automate the pull-rebase-push cycle.

Every caretaker visit hits the same wall: local has unpushed commits,
remote has newer commits from another agent, `git push` says "fetch
first". This tool detects the divergence and resolves it.

Usage:
    python3 tools/push_sync.py              # sync and push
    python3 tools/push_sync.py --dry-run    # report only
    python3 tools/push_sync.py --force      # reset to remote on conflict
"""

import argparse
import subprocess
import sys
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Files that use the union merge driver — safe to auto-resolve.
UNION_FILES = {
    "data/strokes.jsonl",
    "docs/DEVLOG.md",
    "docs/GARDEN.md",
    "docs/METRICS.md",
    "notes/reading.md",
    "notes/history.md",
}


def run(cmd, cwd=None, check=True, capture=True):
    """Run a command, return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd,
        cwd=cwd or REPO_ROOT,
        capture_output=capture,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        return result.returncode, result.stdout, result.stderr
    return result.returncode, result.stdout, result.stderr


def has_unpushed_commits():
    """Check if local has commits not on remote."""
    rc, out, _ = run(["git", "log", "--oneline", "origin/main..HEAD"])
    return rc == 0 and len(out.strip()) > 0


def has_unfetched_remote_commits():
    """Check if remote has commits we don't have."""
    run(["git", "fetch", "origin", "main"], check=False)
    rc, out, _ = run(["git", "log", "--oneline", "HEAD..origin/main"])
    return rc == 0 and len(out.strip()) > 0


def is_working_tree_clean():
    """Check if working tree has no uncommitted changes."""
    rc, out, _ = run(["git", "status", "--porcelain"])
    return rc == 0 and len(out.strip()) == 0


def try_push():
    """Attempt git push, return success."""
    rc, out, err = run(["git", "push", "origin", "main"], check=False)
    return rc == 0


def try_rebase():
    """Attempt rebase onto origin/main, return (success, conflict_files)."""
    rc, out, err = run(["git", "rebase", "origin/main"], check=False)
    if rc == 0:
        return True, []
    # Check for conflicts
    rc2, status, _ = run(
        ["git", "diff", "--name-only", "--diff-filter=U"], check=False
    )
    conflicts = [f for f in status.strip().split("\n") if f]
    return False, conflicts


def resolve_union_conflicts(files):
    """Auto-resolve conflicts in union-merge files by keeping both sides."""
    resolved = []
    unresolvable = []
    for f in files:
        if f in UNION_FILES:
            # For append-only files, take the union of both sides
            rc, _, _ = run(["git", "checkout", "--theirs", f], check=False)
            if rc == 0:
                run(["git", "add", f], check=False)
                resolved.append(f)
            else:
                unresolvable.append(f)
        else:
            unresolvable.append(f)
    return resolved, unresolvable


def abort_rebase():
    """Abort an in-progress rebase."""
    run(["git", "rebase", "--abort"], check=False)


def sync(dry_run=False, force=False):
    """Main sync logic. Returns (success: bool, message: str)."""
    # Step 1: fetch
    run(["git", "fetch", "origin", "main"], check=False)

    has_local = has_unpushed_commits()
    has_remote = has_unfetched_remote_commits()

    if not has_local and not has_remote:
        return True, "already in sync"

    if not has_local and has_remote:
        # Just pull
        if dry_run:
            return True, "would pull (no local commits to push)"
        rc, _, err = run(["git", "pull", "origin", "main"], check=False)
        if rc == 0:
            return True, "pulled remote changes"
        return False, f"pull failed: {err}"

    if has_local and not has_remote:
        # Just push
        if dry_run:
            return True, "would push (no remote divergence)"
        if try_push():
            return True, "pushed successfully"
        # Push failed — maybe remote changed between fetch and push
        run(["git", "fetch", "origin", "main"], check=False)
        has_remote = has_unfetched_remote_commits()
        if not has_remote:
            return False, "push failed for unknown reason"
        # Fall through to divergence resolution

    # Divergence: both sides have commits
    if dry_run:
        return True, "would rebase local commits onto origin/main and push"

    clean = is_working_tree_clean()

    if clean:
        # Try rebase
        ok, conflicts = try_rebase()
        if ok:
            if try_push():
                return True, "rebased and pushed"
            return False, "rebased but push failed"

        # Handle conflicts
        resolved, unresolvable = resolve_union_conflicts(conflicts)
        if not unresolvable:
            # Continue rebase
            rc, _, _ = run(
                ["git", "rebase", "--continue"], check=False,
            )
            if rc == 0 and try_push():
                return True, f"resolved conflicts in {resolved} and pushed"
            abort_rebase()

        if force:
            abort_rebase()
            # Reset to remote, re-apply our changes
            run(["git", "reset", "--hard", "origin/main"], check=False)
            return True, "force-reset to remote (local commits dropped)"

        abort_rebase()
        return False, f"unresolvable conflicts: {unresolvable}"
    else:
        # Dirty tree — stash, rebase, pop
        run(["git", "stash"], check=False)
        ok, conflicts = try_rebase()
        if ok:
            run(["git", "stash", "pop"], check=False)
            if try_push():
                return True, "stashed, rebased, popped, pushed"
            return False, "stashed and rebased but push failed"
        abort_rebase()
        run(["git", "stash", "pop"], check=False)

        if force:
            run(["git", "stash"], check=False)
            run(["git", "reset", "--hard", "origin/main"], check=False)
            run(["git", "stash", "pop"], check=False)
            return True, "force-reset to remote, stash popped"

        return False, "rebase conflicts with dirty tree"


def main():
    parser = argparse.ArgumentParser(description="Sync and push to remote")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report only, don't change"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reset to remote on unresolvable conflict",
    )
    args = parser.parse_args()

    ok, msg = sync(dry_run=args.dry_run, force=args.force)
    print(f"{'OK' if ok else 'FAIL'}: {msg}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
