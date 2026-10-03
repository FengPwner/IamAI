"""A pool of pre-validated snippets.

Each entry is (filename, complete module source). Every module ships with doctests,
and ``tests/test_snippets.py`` executes them, so anything taken from this pool has
already been proven to run. The writer is only allowed to add a snippet by taking
one from here -- a self-writing repo that generates its own untested examples is
how you end up with a repo full of confident nonsense.
"""

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
      a bb
    --- --
      1  2
    100 20
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

    rule = ["-" * w for w in widths]
    out = [line(cols), line(rule)]
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

QUOTES = ('"', "'")


def parse_kv(text: str) -> dict:
    r"""Turn lines of `k=v` into a dict. Later keys win.

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
        if len(value) >= 2 and value[0] == value[-1] and value[0] in QUOTES:
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
    >>> b.advance_to(1.5)
    >>> b.take()
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

    def advance_to(self, moment: float) -> None:
        """Move the fake clock forward. Returns nothing -- this only mutates."""

        self._clock = lambda moment=moment: moment
        self._refill()
''',
    ),
    (
        "chunk_text.py",
        '''"""Chunk long text into pieces of at most `size` characters, whitespace first."""


def chunk_text(text: str, size: int = 100) -> list[str]:
    """Split `text` into chunks of at most `size` characters.

    Cuts at the last space inside the window when there is one; falls back
    to a hard cut otherwise (CJK text has no spaces to offer).

    >>> chunk_text("aaaa bbbb cccc", 9)
    ['aaaa bbbb', 'cccc']
    >>> chunk_text("一二三四五六七八九十", 4)
    ['一二三四', '五六七八', '九十']
    >>> chunk_text("short", 100)
    ['short']
    >>> chunk_text("", 5)
    []
    >>> chunk_text("a  b", 3)
    ['a', 'b']
    """
    if size < 1:
        raise ValueError("size must be at least 1")
    chunks: list[str] = []
    rest = text
    while rest:
        if len(rest) <= size:
            chunks.append(rest)
            break
        cut = rest.rfind(" ", 1, size + 1)
        if cut <= 0:
            cut = size
        chunks.append(rest[:cut].rstrip(" "))
        rest = rest[cut:].lstrip(" ")
    return chunks
''',
    ),
]


def take(index: int):
    """The snippet at `index`, or None when the pool is exhausted."""
    if 0 <= index < len(SNIPPETS):
        return SNIPPETS[index]
    return None


def remaining(index: int) -> int:
    """How many snippets are left after `index` have been taken."""
    return max(0, len(SNIPPETS) - index)
