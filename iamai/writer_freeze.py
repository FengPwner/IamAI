"""writer_freeze — pause writer and stabilize the working tree for git ops.

The recurring failure mode across caretaker visits 503–512 is the
**writer-race**: between any two git operations (stash → rebase,
stop → commit), the writer produces new changes that invalidate the
previous step.  ``git pull --rebase`` on a dirty tree is a hard abort,
not a conflict.

The fix is a two-phase freeze:

1. **Pause** — touch the writer's pause file so it idles at the next
   tick boundary (up to ``--every`` seconds, typically 15 s).
2. **Stabilize** — poll ``git status --porcelain`` until the output
   is identical across two consecutive reads, meaning no process is
   mid-write.

Usage::

    from iamai.writer_freeze import writer_freeze

    with writer_freeze("qwen", repo="/path/to/repo"):
        # working tree is stable; safe to stash → rebase → push
        ...

On exit the pause file is removed and the writer resumes at its next
tick.  If the pause file already existed (e.g. the test gate is red),
the context manager preserves it instead of deleting it.
"""

from __future__ import annotations

import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from iamai.writer import pause_file as _pause_file


def _run_git(repo: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git"] + list(args),
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _tree_snapshot(repo: Path) -> str:
    """Return the porcelain status output — a fingerprint of the tree."""
    rc, out = _run_git(repo, "status", "--porcelain")
    return out if rc == 0 else ""


def wait_for_stable_tree(
    repo: str | Path,
    *,
    settle: float = 1.0,
    timeout: float = 30.0,
) -> bool:
    """Block until ``git status`` output is identical across two reads.

    Returns True if the tree stabilized within *timeout* seconds,
    False otherwise.  A *settle* gap of 1 s (default) between reads
    catches writers mid-flush.
    """
    repo = Path(repo)
    deadline = time.monotonic() + timeout
    prev = _tree_snapshot(repo)
    while time.monotonic() < deadline:
        time.sleep(settle)
        curr = _tree_snapshot(repo)
        if curr == prev:
            return True
        prev = curr
    return False


def is_writer_paused(writer_id: str | None = None) -> bool:
    """Return True if the writer's pause file exists."""
    return _pause_file(writer_id).exists()


@contextmanager
def writer_freeze(
    writer_id: str | None = None,
    *,
    repo: str | Path = ".",
    settle: float = 1.0,
    timeout: float = 30.0,
) -> Iterator[dict]:
    """Context manager: pause writer, stabilize tree, yield, resume.

    Yields a dict with diagnostic info::

        {"paused": True, "stable": True, "settled_in": 2.3}

    On exit, removes the pause file **only if this context created it**.
    If the pause file pre-existed (e.g. test gate is red), it is left
    untouched.
    """
    repo = Path(repo).resolve()
    pf = _pause_file(writer_id)
    pre_existing = pf.exists()

    # -- freeze --
    pf.touch()
    t0 = time.monotonic()
    stable = wait_for_stable_tree(repo, settle=settle, timeout=timeout)
    settled_in = round(time.monotonic() - t0, 2)

    info = {"paused": True, "stable": stable, "settled_in": settled_in}
    try:
        yield info
    finally:
        # -- thaw --
        if not pre_existing and pf.exists():
            pf.unlink(missing_ok=True)
