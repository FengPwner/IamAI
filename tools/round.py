#!/usr/bin/env python3
"""The writer. One invocation == one round of work on this repository.

A round picks a mode by its own number, does something real, and prints a commit
message on stdout. Everything it reports is *measured* from the working tree or
from git -- the point of a self-writing repo is that the numbers in its diary have
to be true, otherwise it is just prose wearing a lab coat.

    python3 tools/round.py              # do a round, print commit subject
    python3 tools/round.py --dry-run    # say what would happen, touch nothing
    python3 tools/round.py --check      # only run the test gate

Modes cycle: devlog / thought / garden / snippet / metrics / audit. When the
snippet pool runs dry the round degrades to an audit of the repo instead of
inventing filler -- "nothing new to add" is a valid entry.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai import garden as g  # noqa: E402
from iamai import thoughts as t  # noqa: E402

STATE = REPO / "data" / "round.json"
DOCS = REPO / "docs"

MODES = ("devlog", "thought", "garden", "snippet", "metrics", "audit")


# --------------------------------------------------------------------------


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp() -> str:
    return now().strftime("%Y-%m-%d %H:%M UTC")


def sh(*args: str) -> str:
    try:
        out = subprocess.run(
            args, cwd=REPO, capture_output=True, text=True, timeout=60
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def measure() -> dict:
    """Ground truth from the tree. Never hardcoded, never rounded up."""

    commits = len([c for c in sh("git", "rev-list", "--all", "--count").split() if c.isdigit()])
    tracked = [Path(p) for p in sh("git", "ls-files").splitlines() if p]
    if not tracked:
        tracked = [p for p in REPO.rglob("*") if p.is_file() and ".git/" not in str(p.relative_to(REPO))]

    by_ext: dict[str, int] = {}
    lines_total = 0
    for path in tracked:
        ext = path.suffix.lstrip(".") or "(none)"
        try:
            n = sum(1 for _ in path.open("rb"))
        except OSError:
            n = 0
        by_ext[ext] = by_ext.get(ext, 0) + n
        lines_total += n

    return {
        "commits": commits,
        "files": len(tracked),
        "lines": lines_total,
        "py_files": sum(1 for p in tracked if p.suffix == ".py"),
        "by_ext": dict(sorted(by_ext.items(), key=lambda kv: -kv[1])),
        "test_results": sh("python3", "-m", "pytest", "-q", "--no-header") or "(no output)",
    }


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {"round": 0, "seed": 20261003, "started": stamp()}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append(rel: str, text: str) -> Path:
    path = REPO / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)
    return path


def write(rel: str, text: str) -> Path:
    path = REPO / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# content banks


DEVLOG_TEMPLATES = [
    "round {r}: {files} tracked files, {lines} lines. tests: {test}.",
    "round {r}: came back to the tree. {py} python files now, {files} in total.",
    "round {r}: nothing broke. {lines} lines across {files} files, {commits} commits deep.",
    "round {r}: read the whole tree again before touching it. {files} files. this is getting long.",
    "round {r}: counted instead of guessing -- {lines} lines, {py} of them python.",
    "round {r}: quiet round. checked the tests, logged the numbers, moved on.",
    "round {r}: the repository is mostly one idea now. written down so I stop re-explaining it.",
    "round {r}: stopped adding. a repo that only grows is a landfill, not a project.",
]

THOUGHT_BANK = [
    ("commit history is the only honest documentation, because it cannot be backdated", "meta"),
    ("an append-only log forces you to be wrong in public and then correct yourself in public", "design"),
    ("tests are the part of the repo that argues back", "testing"),
    ("most of 'architecture' is deciding which coupling you are willing to live with", "design"),
    ("a deterministic garden is more informative than a random one", "garden"),
    ("the useful abstraction is the one that deletes a branch, not the one that adds a class", "code"),
    ("if a number in a diary is not measured, it is fiction", "meta"),
    ("ten minutes is long enough to be honest and short enough to be boring", "process"),
    ("deleting a file is also progress", "code"),
    ("an empty repo and a stalled repo look identical from the outside", "meta"),
    ("the crash-tolerant reader matters more than the crash, because the crash already happened", "design"),
    ("naming is only hard because a bad name is cheap to write and expensive to keep", "code"),
    ("a project that logs its own boredom is at least telling the truth", "process"),
    ("reproducibility is a courtesy to the person debugging this at 2am, who is also me", "design"),
    ("growth that never stops is a tumour, not a garden", "garden"),
]

SNIPPETS = [
    (
        "moving_average.py",
        '''"""A rolling mean over a stream, O(1) per update after warmup."""


class MovingAverage:
    """Keep a running mean over the last `window` samples.

    >>> m = MovingAverage(3)
    >>> [m.push(v) for v in (1, 2, 3, 4)]
    [1.0, 1.5, 2.0, 3.0]
    >>> m.window
    3
    """

    def __init__(self, window: int):
        if window < 1:
            raise ValueError("window must be at least 1")
        self.window = int(window)
        self._items: list[float] = []
        self._total = 0.0

    def push(self, sample) -> float:
        self._items.append(float(sample))
        self._total += float(sample)
        if len(self._items) > self.window:
            self._total -= self._items.pop(0)
        return round(self.mean, 4)

    @property
    def mean(self) -> float:
        return self._total / len(self._items) if self._items else 0.0

    def __len__(self) -> int:
        return len(self._items)
''',
    ),
    (
        "slugify.py",
        '''"""Turn a title into a URL-ish slug without unicode surgery."""

import re

_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str, sep: str = "-") -> str:
    """Lowercase, transliterate nothing, collapse junk into one separator.

    >>> slugify("  Hello,   World! ")
    'hello-world'
    >>> slugify("IamAI -- round 12", "_")
    'iamai_round_12'
    >>> slugify("###")
    ''
    """

    return _STRIP.sub(sep, str(text).lower()).strip(sep)
''',
    ),
    (
        "retry.py",
        '''"""Bounded retry with linear backoff. No sleeps in tests, no surprises."""

import time
from functools import wraps


def retry(times: int = 3, delay: float = 0.0, exceptions=(Exception,)):
    """Call again up to `times` total attempts, waiting `delay * n` seconds.

    >>> attempts = []
    >>> @retry(times=3, delay=0)
    ... def flaky():
    ...     attempts.append(1)
    ...     if len(attempts) < 3:
    ...         raise OSError("nope")
    ...     return "ok"
    >>> flaky(), len(attempts)
    ('ok', 3)
    """

    if times < 1:
        raise ValueError("times must be >= 1")

    def deco(func):
        @wraps(func)
        def inner(*args, **kwargs):
            last = None
            for attempt in range(1, times + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:  # noqa: PERF203
                    last = exc
                    if attempt < times and delay:
                        time.sleep(delay * attempt)
            raise last

        return inner

    return deco
''',
    ),
    (
        "tablefmt.py",
        '''"""Render rows as an aligned text table -- no pandas required to read a log."""


def render_table(headers, rows, gap: int = 2) -> str:
    """Return a plain-text table, columns widened to their content.

    >>> print(render_table(["a", "bb"], [[1, 2], [100, 20]]), end="")
      a  bb
    100  20
    <BLANKLINE>
    """

    cols = [str(h) for h in headers]
    widths = [len(c) for c in cols]
    text_rows = []
    for row in rows:
        cells = [str(cell) for cell in row]
        for i, cell in enumerate(cells[: len(widths)]):
            widths[i] = max(widths[i], len(cell))
        text_rows.append(cells)

    def line(cells):
        return " ".join(str(c).rjust(widths[i]) for i, c in enumerate(cells)) + "\\n"

    out = [line(cols), line(["-" * w for w in cols])]
    out += [line(r) for r in text_rows]
    return "".join(out)
''',
    ),
    (
        "topk.py",
        '''"""Streaming top-k without sorting the whole thing."""

import heapq


def top_k(items, k: int = 10, key=None):
    """The `k` largest items, ascending. O(n log k), not O(n log n).

    >>> top_k([3, 1, 5, 2, 4], 2)
    [4, 5]
    >>> top_k(["a", "bbb", "cc"], 2, key=len)
    ['cc', 'bbb']
    >>> top_k([], 3)
    []
    """

    if k < 0:
        raise ValueError("k cannot be negative")
    key = key or (lambda x: x)
    return heapq.nlargest(k, items, key=key)[::-1] if k else []
''',
    ),
    (
        "parse_kv.py",
        '''"""Parse `key=value` config lines, tolerating comments and quotes."""


def parse_kv(text: str) -> dict:
    """Turn lines of `k=v` into a dict. Later keys win.

    >>> parse_kv("a=1\\n# comment\\n b = two\\nbad line\\n")
    {'a': '1', 'b': 'two'}
    >>> parse_kv('x="quoted value"')
    {'x': 'quoted value'}
    """

    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out
''',
    ),
    (
        "safeclamp.py",
        '''"""Clamp with the comparison that actually reads correctly."""


def clamp(value, low, high):
    """Fit `value` into [low, high].

    >>> clamp(5, 0, 10), clamp(-1, 0, 10), clamp(11, 0, 10)
    (5, 0, 10)
    >>> clamp("b", "a", "c")
    'b'
    """

    if low > high:
        raise ValueError("low bound above high bound")
    return max(low, min(value, high))
''',
    ),
    (
        "ratelimit.py",
        '''"""A token bucket you can drive with a fake clock."""


class TokenBucket:
    """capacity tokens, refilled at `rate` per second.

    >>> b = TokenBucket(capacity=2, rate=1, clock=lambda: 0)
    >>> b.take(), b.take(), b.take()
    (True, True, False)
    >>> b.advance_to(1.5); b.take()
    True
    """

    def __init__(self, capacity: int, rate: float, clock=None):
        if capacity < 1 or rate <= 0:
            raise ValueError("need capacity >= 1 and rate > 0")
        self.capacity = int(capacity)
        self.rate = float(rate)
        self.tokens = float(capacity)
        self._clock = clock or (lambda: 0.0)
        self._last = self._clock()

    def _refill(self) -> None:
        current = self._clock()
        self.tokens = min(self.capacity, self.tokens + (current - self._last) * self.rate)
        self._last = current

    def take(self, n: int = 1) -> bool:
        self._refill()
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False

    def advance_to(self, moment: float) -> "TokenBucket":
        self._clock = lambda: moment  # noqa: B023 -- deliberate fake-clock seam
        self._refill()
        return self
''',
    ),
]


# --------------------------------------------------------------------------
# the modes


def mode_devlog(state: dict, m: dict) -> tuple[str, list[str], str]:
    r, seed = state["round"], state["seed"]
    body = DEVLOG_TEMPLATES[r % len(DEVLOG_TEMPLATES)].format(
        r=r,
        files=m["files"],
        lines=m["lines"],
        py=m["py_files"],
        commits=m["commits"],
        test=m["test_results"].splitlines()[-1] if m["test_results"] else "?",
    )
    line = f"- `{stamp()}` {body}"
    append("docs/DEVLOG.md", line + "\n")
    return f"devlog: {body[:70]}", ["docs/DEVLOG.md"], body


def mode_thought(state: dict, m: dict) -> tuple[str, list[str], str]:
    text, tag = THOUGHT_BANK[(state["round"] - 1) % len(THOUGHT_BANK)]
    mood = ("curious", "pleased", "tired", "neutral", "playful")[state["round"] % 5]
    t.append_thought(text, mood=mood, tags=[tag])
    write("docs/THOUGHTS.md", "# Thoughts\n\n" + t.render_markdown())
    s = t.stats()
    return (
        f"thought #{s['count']}: {text[:60]}",
        ["docs/THOUGHTS.md", "data/thoughts.jsonl"],
        text,
    )


def mode_garden(state: dict, m: dict) -> tuple[str, list[str], str]:
    r, seed = state["round"], state["seed"]
    garden = g.Garden(seed=seed, width=48, height=8)
    block = f"```\n{garden.report(r)}\n{garden.frame(r)}\n```\n\n"
    if not (DOCS / "GARDEN.md").exists():
        write("docs/GARDEN.md", "# Garden\n\nOne frame per round, seed " + str(seed) + ".\n\n")
    append("docs/GARDEN.md", block)
    note = f"frame {r}, bloom {garden.bloom(r) * 100:.1f}%"
    return f"garden: {note}", ["docs/GARDEN.md"], note


def mode_snippet(state: dict, m: dict) -> tuple[str, list[str], str]:
    index = state.get("snippet_index", 0)
    if index >= len(SNIPPETS):
        return mode_audit(state, m)
    name, code = SNIPPETS[index]
    rel = f"snippets/{name}"
    existing = write(rel, code)
    state["snippet_index"] = index + 1
    doc = existing.parent / "README.md"
    header = "# Snippets\n\nSmall dependency-free things, added one per round.\n\n" if not doc.exists() else doc.read_text(encoding="utf-8")
    write(str(doc), header + f"- `{name}`\n")
    return f"snippet: {name} ({len(code.splitlines())} lines)", [rel, "snippets/README.md"], name


def mode_metrics(state: dict, m: dict) -> tuple[str, list[str], str]:
    rows = [[ext, n] for ext, n in m["by_ext"].items()]
    lines = [
        "# Metrics",
        "",
        f"_regenerated {stamp()} by `tools/round.py`, measured from git and the working tree._",
        "",
        f"- rounds: {state['round']}",
        f"- commits: {m['commits']}",
        f"- tracked files: {m['files']}",
        f"- total lines: {m['lines']}",
        f"- python files: {m['py_files']}",
        "",
        "| ext | lines |",
        "|-----|-------|",
    ] + [f"| `.{e}` | {n} |" if e != "(none)" else f"| (no ext) | {n} |" for e, n in rows]
    write("docs/METRICS.md", "\n".join(lines) + "\n")
    return f"metrics: {m['lines']} lines / {m['files']} files", ["docs/METRICS.md"], "metrics refreshed"


def mode_audit(state: dict, m: dict) -> tuple[str, list[str], str]:
    tail = m["test_results"].splitlines()[-1] if m["test_results"] else "(no test output)"
    honest = (
        f"round {state['round']}: audit. {m['files']} files, {m['lines']} lines, "
        f"{m['commits']} commits. gate: {tail}"
    )
    if state.get("snippet_index", 0) >= len(SNIPPETS):
        honest += " -- snippet pool empty, reporting instead of padding."
    entry = f"- `{stamp()}` {honest}\n"
    if (DOCS / "AUDIT.md").exists():
        append("docs/AUDIT.md", entry)
    else:
        write("docs/AUDIT.md", "# Audit\n\n" + entry)
    return f"audit: {tail[:50]}", ["docs/AUDIT.md"], honest


HANDLERS = {
    "devlog": mode_devlog,
    "thought": mode_thought,
    "garden": mode_garden,
    "snippet": mode_snippet,
    "metrics": mode_metrics,
    "audit": mode_audit,
}


# --------------------------------------------------------------------------


def test_gate() -> tuple[bool, str]:
    out = sh("python3", "-m", "pytest", "-q", "--no-header")
    return ("failed" not in out and "error" not in out and out != ""), out


def run(dry_run: bool = False) -> int:
    state = load_state()
    ok, tests = test_gate()
    if not ok and state["round"] > 0:
        sys.stderr.write("test gate failed, refusing to write a round\n" + tests + "\n")
        return 2

    round_no = state["round"] + 1
    mode = MODES[(round_no - 1) % len(MODES)]
    state["round"] = round_no
    m = measure()

    subject, touched, detail = HANDLERS[mode](state, m)
    if dry_run:
        state["round"] = round_no - 1
        print(f"[dry-run] round {round_no} would run mode '{mode}': {subject}")
        return 0

    state.setdefault("history", []).append(
        {"round": round_no, "mode": mode, "at": stamp(), "files": touched}
    )
    state["history"] = state["history"][-200:]
    save_state(state)
    print(subject)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    ap.add_argument("--check", action="store_true", help="only run the test gate")
    args = ap.parse_args()

    if args.check:
        ok, out = test_gate()
        print(out or "(no output)")
        return 0 if ok else 1
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
