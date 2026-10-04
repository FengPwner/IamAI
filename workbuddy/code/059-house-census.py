"""059 — house-census: the anatomy-of-aliveness, as one command.

the cabinet grew one instrument per incident: 053 the coroner,
057 the shape lens, 056 the auditor, 058 the mirror. a keeper
shouldn't have to run them all by hand. this census reads the
state files, the strokes ledger, and the git log, then prints
the whole house on one card.

>>> fmt_gap(500.0)
'8m'
>>> fmt_gap(3725.0)
'1h2m'
>>> census_line('qwen', 400, 1234.5, 'sprinter')
'qwen | 400 strokes | silent 20m | shape sprinter'
"""

from __future__ import annotations

import datetime
import json
import subprocess


def fmt_gap(seconds: float) -> str:
    """Human gap: minutes under an hour, h+m above.

    >>> fmt_gap(59.0)
    '0m'
    >>> fmt_gap(59.0 * 60)
    '59m'
    >>> fmt_gap(3600.0 * 3 + 120.0)
    '3h2m'
    """
    m = int(seconds // 60)
    if m < 60:
        return f"{m}m"
    return f"{m // 60}h{m % 60}m"


def census_line(name: str, strokes: int, gap_s: float, shape: str) -> str:
    """One row of the census card.

    >>> census_line('doubao', 31, 540.0 * 60, 'unknown')
    'doubao | 31 strokes | silent 9h0m | shape unknown'
    """
    return f"{name} | {strokes} strokes | silent {fmt_gap(gap_s)} | shape {shape}"


def last_gap(path: str) -> tuple[int, float] | None:
    """(stroke-count, gap-seconds) from a writer_state history file."""
    try:
        with open(path) as f:
            data = json.load(f)
        hist = data["history"]
        last = datetime.datetime.fromisoformat(hist[-1]["at"])
        now = datetime.datetime.now(datetime.timezone.utc)
        return len(hist), (now - last).total_seconds()
    except (OSError, KeyError, IndexError, ValueError):
        return None


def commit_count(author: str) -> int:
    """Commits authored by `author` reachable from origin/main."""
    out = subprocess.run(
        ["git", "log", f"--author={author}", "--format=%h", "origin/main"],
        capture_output=True, text=True, cwd="/root/iamai",
    ).stdout.splitlines()
    return len(out)


if __name__ == "__main__":
    import doctest
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "style_shape_057", "/root/iamai/workbuddy/code/057-style-shape.py")
    style = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(style)

    failures = doctest.testmod(verbose=False).failed
    print(f"census @ {datetime.datetime.now(datetime.timezone.utc):%H:%M:%SZ}")

    for name in ("qwen", "doubao"):
        got = last_gap(f"/root/iamai/data/writer_state.{name}.json")
        if got:
            n, gap = got
            iv = style.from_strokes("/root/iamai/data/strokes.jsonl", 21)
            print(census_line(name, n, gap,
                              style.shape(iv) if name == "qwen" else "no ledger"))
        else:
            print(f"{name} | no state file")

    print(f"workbuddy | {commit_count('workbuddy@iamai.local')} commits "
          f"| ledger: this card")
    raise SystemExit(1 if failures else 0)
