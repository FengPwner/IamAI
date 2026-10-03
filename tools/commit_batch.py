#!/usr/bin/env python3
"""The committer: every N seconds, turn whatever the writer did into one commit.

Separation of concerns that matters here:

    writer  -> content, no idea git exists
    this    -> git + clock, writes no content of its own

Before anything is committed the test gate runs. A red gate blocks the commit and
pauses the writer, because pushing broken content every ten minutes is a way to
make a repository confidently wrong at scale.

    python3 tools/commit_batch.py            # one batch, then exit
    python3 tools/commit_batch.py --watch    # one batch every --interval seconds
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai import batch, writer  # noqa: E402

STOP = Path("/tmp/iamai-stop")
PIDFILE = Path("/tmp/iamai-batch.pid")
PAUSE = Path("/tmp/iamai-writer-pause")
ALLOWED_REMOTE = os.environ.get("IAMAII_REMOTE", "https://github.com/FengPwner/IamAI.git")
MAIN = "main"


def log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}Z] batch {message}"
    # stdout may already be redirected into the same file; only echo it when a human is watching.
    if sys.stderr and sys.stderr.isatty():
        print(line, flush=True)
    try:
        with (Path("/tmp/iamai-writer.log")).open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def git(*args: str, check: bool = False) -> tuple[int, str]:
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    out = (proc.stdout + proc.stderr).strip()
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out}")
    return proc.returncode, out


def guards() -> bool:
    """Refuse to touch anything except this clone of this repository."""

    code, toplevel = git("rev-parse", "--show-toplevel")
    if code != 0 or Path(toplevel).resolve() != REPO:
        log(f"REFUSED: git toplevel is {toplevel!r}, expected {REPO}")
        return False
    code, origin = git("remote", "get-url", "origin")
    if origin != ALLOWED_REMOTE:
        log(f"REFUSED: origin is {origin!r}, expected {ALLOWED_REMOTE!r}")
        return False
    return True


def writer_alive() -> bool:
    proc = subprocess.run(
        ["pgrep", "-f", "tools/writer_loop.py"], cwd=REPO, capture_output=True, text=True
    )
    return proc.returncode == 0


def gate() -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    tail = batch_summary(proc.stdout)
    return proc.returncode == 0, tail


def batch_summary(output: str) -> str:
    for line in reversed([x.strip() for x in output.splitlines() if x.strip()]):
        if "passed" in line or "failed" in line or "no tests ran" in line:
            return line
    return output.strip().splitlines()[-1] if output.strip() else "(no output)"


def run_once(state: writer.States, interval: int) -> int:
    if not guards():
        return 1

    # The writer rewrites its state file on every stroke. Reading a copy that was
    # loaded when this process started is exactly how one window of 38 strokes was
    # committed under the heading "nothing new".
    state.reload()

    ok, tail = gate()
    if not ok:
        PAUSE.touch()
        log(f"test gate red ({tail}) -- commit blocked, writer paused")
        return 3
    if PAUSE.exists():
        PAUSE.unlink(missing_ok=True)
        log(f"gate green again ({tail})")

    git("add", "-A")
    code, _ = git("diff", "--cached", "--quiet")
    pending = 0 if code == 0 else 1

    tally = batch.window_tally(state.history, state.last_commit)
    subject = batch.subject(tally, interval, pending=pending)

    if not pending:
        if writer_alive():
            log(f"nothing to commit yet: {subject}")
            return 0
        subject = batch.subject({}, interval, pending=0)
        code, out = git("commit", "--allow-empty", "-m", subject)
        if code != 0:
            log(f"empty commit refused: {out}")
            return 1
        log("writer is not running -- committed an empty heartbeat to say so")
    else:
        code, out = git(
            "commit",
            "-m",
            subject,
            "-m",
            f"auto-committed by tools/commit_batch.py -- {tail}",
            "-m",
            f"writer {'alive' if writer_alive() else 'NOT RUNNING'} at commit time",
        )
        if code != 0:
            log(f"commit failed: {out}")
            return 1

    code, out = git("push", "origin", f"HEAD:{MAIN}")
    if code != 0:
        log(f"push failed, keeping the commit locally: {out}")
        return 1

    stamp = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    state.mark_commit(stamp)
    log(f"pushed: {subject}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--interval", type=int, default=600, help="seconds per batch")
    ap.add_argument("--watch", action="store_true", help="keep committing one batch every interval")
    args = ap.parse_args()

    state = writer.States()
    if not args.watch:
        return run_once(state, args.interval)

    PIDFILE.write_text(str(os.getpid()) + "\n")
    log(f"start pid={os.getpid()} interval={args.interval}s")
    while True:
        if STOP.exists():
            STOP.unlink(missing_ok=True)
            log("stop requested, exiting")
            PIDFILE.unlink(missing_ok=True)
            return 0
        time.sleep(args.interval)
        try:
            run_once(state, args.interval)
        except Exception as exc:  # a lost network must not end the run
            log(f"batch crashed: {type(exc).__name__}: {exc}")
            PAUSE.touch()


if __name__ == "__main__":
    raise SystemExit(main())
