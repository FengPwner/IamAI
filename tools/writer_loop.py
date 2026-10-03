#!/usr/bin/env python3
"""The writer process: applies one stroke every N seconds, forever.

Two files steer it from outside:

    /tmp/iamai-stop         -> shut down cleanly at the next tick
    /tmp/iamai-writer-pause -> idle (write nothing) until the gate goes green again

The pause file exists because a continuous writer is a fire hose: if the test gate
fails, the worst thing it can do is keep piling content on top of a broken tree.
So the committer touches that file, and this loop stops feeding it.

    python3 tools/writer_loop.py --every 15
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

from iamai import writer  # noqa: E402

STOP = Path("/tmp/iamai-stop")
PIDFILE = writer.pid_file()
# 红闸门标记按写手分文件；模块加载时就算好，不依赖参数解析的顺序。
PAUSE = writer.pause_file()
MAX_TRACKED_LINES = 400_000  # if we ever get here, stop and say so instead of filling the disk


def log(message: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}Z] writer {message}"
    # stdout may already be redirected into the same file; only echo it when a human is watching.
    if sys.stderr and sys.stderr.isatty():
        print(line, flush=True)
    try:
        with (Path("/tmp/iamai-writer.log")).open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--every", type=int, default=15, help="seconds between strokes")
    ap.add_argument("--writer", default=None, help="writer id, e.g. qwen / kimi (or env IAMAII_WRITER)")
    ap.add_argument("--seed", type=int, default=20261003, help="variant seed for the writer")
    ap.add_argument("--once", action="store_true", help="apply exactly one stroke and exit")
    args = ap.parse_args()

    global PAUSE, PIDFILE
    PAUSE, PIDFILE = writer.pause_file(args.writer), writer.pid_file(args.writer)
    PIDFILE.write_text(str(os.getpid()) + "\n")
    state = writer.States(writer_id=args.writer)
    jitter = random.Random(args.seed)
    log(f"start pid={__import__('os').getpid()} every={args.every}s seq={state.next_seq()}")

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

        if writer.snapshot()["lines"] > MAX_TRACKED_LINES:
            log("tree exceeded the line budget; refusing to keep padding it")
            PIDFILE.unlink(missing_ok=True)
            return 3

        seq = state.next_seq()
        stroke = writer.plan_strokes(seed=args.seed, count=1, start=seq - 1)[0]
        try:
            path = writer.apply_stroke(stroke)
        except Exception as exc:  # a bad stroke must not kill a long-running process
            log(f"stroke {seq} ({stroke['kind']}) failed: {type(exc).__name__}: {exc}")
            time.sleep(max(args.every, 30))
            continue

        state.record(kind=stroke["kind"], path=str(path.relative_to(REPO)))
        log(f"stroke {seq}: {stroke['kind']} -> {path.relative_to(REPO)}")

        if args.once:
            return 0
        time.sleep(max(1, args.every) + jitter.randint(-2, 4))


if __name__ == "__main__":
    raise SystemExit(main())
