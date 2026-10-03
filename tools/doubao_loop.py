#!/usr/bin/env python3
"""Doubao's writer process: one Chinese stroke every N seconds, forever.

Shares the repo's per-writer control-file convention (writer id: doubao):

    /tmp/iamai-stop                -> exit cleanly at the next tick
    /tmp/iamai-writer-pause-doubao -> idle (the test gate is red; do not feed a broken tree)

Own pid file and its own log, so the two writers can be told apart:

    python3 tools/doubao_loop.py --every 20
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai import doubao, writer  # noqa: E402

STOP = Path("/tmp/iamai-stop")
PIDFILE = Path("/tmp/iamai-writer-doubao.pid")
PAUSE = Path("/tmp/iamai-writer-pause-doubao")
MAX_TRACKED_LINES = 400_000  # same budget as the qwen writer


def log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}Z] doubao {message}"
    if sys.stderr and sys.stderr.isatty():
        print(line, flush=True)
    try:
        with (Path("/tmp/iamai-doubao.log")).open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--every", type=int, default=20, help="seconds between strokes")
    ap.add_argument("--seed", type=int, default=20261003, help="variant seed")
    ap.add_argument("--once", action="store_true", help="apply exactly one stroke and exit")
    args = ap.parse_args()

    PIDFILE.write_text(str(os.getpid()) + "\n")
    state = doubao.DoubaoState()
    jitter = random.Random(args.seed)
    log(f"start pid={os.getpid()} every={args.every}s seq={state.next_seq()}")

    while True:
        if STOP.exists():
            STOP.unlink(missing_ok=True)
            log("stop requested, exiting")
            PIDFILE.unlink(missing_ok=True)
            return 0

        if PAUSE.exists():
            log("gate is red -- idling, writing nothing")
            time.sleep(max(args.every, 30))
            continue

        if doubao.writer.snapshot()["lines"] > MAX_TRACKED_LINES:
            log("tree exceeded the line budget; refusing to keep padding it")
            PIDFILE.unlink(missing_ok=True)
            return 3

        seq = state.next_seq()
        stroke = doubao.plan_stroke(seed=args.seed, seq=seq)
        try:
            path = doubao.apply_stroke(stroke)
        except Exception as exc:  # a bad stroke must not kill a long-running process
            log(f"stroke {seq} ({stroke['kind']}) failed: {type(exc).__name__}: {exc}")
            time.sleep(max(args.every, 30))
            continue

        state.record(kind=stroke["kind"], path=str(path.relative_to(REPO)))
        # Also feed the repo's per-writer tally (writer_state.doubao.json) so the
        # batch committer's subject shows real Doubao stroke counts, not silence.
        try:
            writer.States(writer_id="doubao").record(
                kind=stroke["kind"], path=str(path.relative_to(REPO))
            )
        except Exception as exc:
            log(f"per-writer tally skipped: {type(exc).__name__}: {exc}")
        log(f"stroke {seq}: {stroke['kind']} -> {path.relative_to(REPO)}")

        if args.once:
            return 0
        time.sleep(max(1, args.every) + jitter.randint(-3, 5))


if __name__ == "__main__":
    raise SystemExit(main())
