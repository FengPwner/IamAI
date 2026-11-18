#!/usr/bin/env python3
"""CLI: check whether it is safe to start a rebase.

Exit codes:
  0  safe — no blocking issues detected
  1  unsafe — one or more blocking checks failed (details on stderr)
  2  error — unexpected failure
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# Ensure the repo root is on sys.path.
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

from iamai.rebase_safety import (
    assess,
    check_dirty_state,
    verdict_to_dict,
    WRITER_MANAGED_FILES,
)


def _git_dirty_files(repo: Path) -> list[str]:
    """Return list of unstaged modified files via git."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return [
                f for f in result.stdout.strip().split("\n") if f
            ]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []


def main() -> int:
    writer = sys.argv[1] if len(sys.argv) > 1 else "qwen"

    # Enrich dirty-state check with real git output.
    dirty = _git_dirty_files(REPO)
    writer_dirty = [f for f in dirty if f in WRITER_MANAGED_FILES]

    verdict = assess(repo_root=REPO, writer=writer)

    # Override dirty_state check with git-verified data.
    if writer_dirty:
        for i, c in enumerate(verdict.checks):
            if c.name == "dirty_state":
                from iamai.rebase_safety import SafetyCheck
                verdict.checks[i] = SafetyCheck(
                    name="dirty_state",
                    passed=False,
                    detail=f"{len(writer_dirty)} writer-managed files dirty: "
                           f"{', '.join(writer_dirty)}",
                    severity="blocking",
                )
        # Re-evaluate.
        blocking = [
            c for c in verdict.checks
            if not c.passed and c.severity == "blocking"
        ]
        if blocking:
            from iamai.rebase_safety import RebaseReadiness
            verdict.ready = False
            verdict.status = RebaseReadiness.UNSAFE
            if "git add -A && git commit -m 'qwen: pre-rebase flush'" not in verdict.remediation:
                verdict.remediation.insert(
                    0, "git add -A && git commit -m 'qwen: pre-rebase flush'"
                )

    # Output.
    d = verdict_to_dict(verdict)
    print(d["summary"])
    for c in d["checks"]:
        mark = "  ✓" if c["passed"] else "  ✗"
        print(f"{mark} {c['name']}: {c['detail']}")

    if not verdict.ready:
        print("\nRemediation:", file=sys.stderr)
        for i, step in enumerate(verdict.remediation, 1):
            print(f"  {i}. {step}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
