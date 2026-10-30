"""Writer state persistence — monotonic stroke-sequence contract.

A writer restart (container reclamation, process crash) must resume from the
last recorded sequence number: never repeat, never skip.  This module owns
loading / recording / saving that append-only ledger.

The on-disk format is a JSON object:

    {
      "strokes": [
        {"seq": 1, "kind": "thought", "path": "notes/test.md"},
        ...
      ]
    }

Missing, empty (``{}``), or corrupt state files start fresh at seq 1 rather
than crashing — the append-only log stays honest across restarts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class WriterState:
    """Stateful ledger of recorded strokes with a monotonic sequence counter.

    >>> import tempfile
    >>> p = Path(tempfile.mkdtemp()) / "state.json"
    >>> s = WriterState.load(p)          # fresh file -> starts at 1
    >>> s.next_seq()
    1
    >>> s.record(seq=1, kind="note", path="notes/a.md")
    >>> s.save(p)
    >>> s2 = WriterState.load(p)
    >>> s2.next_seq()
    2
    """

    __slots__ = ("_strokes",)

    def __init__(self, strokes: list[dict[str, Any]] | None = None) -> None:
        self._strokes: list[dict[str, Any]] = list(strokes or [])

    # -- construction ------------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> "WriterState":
        """Load state from *path*; missing or unusable files start fresh."""
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        strokes = raw.get("strokes")
        if not isinstance(strokes, list):
            return cls()
        return cls([s for s in strokes if isinstance(s, dict)])

    # -- recording ---------------------------------------------------------

    def record(self, seq: int, kind: str, path: str) -> None:
        """Record one stroke into the in-memory ledger."""
        self._strokes.append({"seq": int(seq), "kind": kind, "path": path})

    def save(self, path: Path) -> None:
        """Persist the ledger to *path* (JSON, ``strokes`` array)."""
        Path(path).write_text(
            json.dumps({"strokes": self._strokes}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # -- queries -----------------------------------------------------------

    def next_seq(self) -> int:
        """Sequence number for the next stroke: last recorded + 1, or 1."""
        if not self._strokes:
            return 1
        last = max(s.get("seq", 0) for s in self._strokes)
        return last + 1
