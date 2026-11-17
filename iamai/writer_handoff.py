#!/usr/bin/env python3
"""writer_handoff — preserve writer context across restarts.

When a writer process stops — whether from a crash, reclaim, or
planned restart — the next instance starts cold: it knows nothing
about what the previous writer was working on, how far it got, or
whether its last strokes were persisted.

This module bridges that gap with a lightweight handoff protocol:

1. **Snapshot** the writer's state on shutdown (or periodically).
2. **Persist** the snapshot to a JSON file.
3. **Restore** the snapshot on startup so the new writer can resume
   context — last topic, sequence position, recent strokes, and
   whether the previous session ended cleanly.

Public API::

    from iamai.writer_handoff import HandoffManager

    mgr = HandoffManager(path="/tmp/writer_handoff.json")

    # --- on shutdown ---
    mgr.snapshot(
        seq=6711,
        last_strokes=[
            {"seq": 6710, "kind": "thought", "text": "..."},
            {"seq": 6711, "kind": "note", "text": "..."},
        ],
        topic="caretaker automation",
        clean=True,
    )

    # --- on startup ---
    ctx = mgr.restore()
    if ctx:
        print(f"Resuming from seq {ctx['seq']}, topic: {ctx['topic']}")
        print(f"Clean shutdown: {ctx['clean']}")
        print(f"Gap since last: {ctx['gap_s']:.0f}s")

Snapshot schema
---------------
.. code-block:: json

    {
        "seq": 6711,
        "topic": "caretaker automation",
        "clean": true,
        "at": "2026-11-17T10:15:00+00:00",
        "last_strokes": [
            {"seq": 6710, "kind": "thought", "text": "..."},
            {"seq": 6711, "kind": "note", "text": "..."}
        ],
        "stroke_count": 6711,
        "writer": "qwen"
    }

Design decisions
----------------
- **Atomic writes.**  The snapshot is written to a temp file and
  renamed, so a crash mid-write never corrupts the handoff file.
- **Bounded stroke history.**  Only the last ``max_strokes`` (default
  20) strokes are retained.  This is enough to prime a language model
  with recent context without bloating the file.
- **Graceful degradation.**  If the handoff file is missing, corrupt,
  or stale (older than ``stale_s`` seconds), ``restore()`` returns
  ``None`` and the caller starts fresh.
- **No process coupling.**  The manager is pure I/O — it does not
  signal, kill, or restart any process.  The batch committer or
  caretaker calls ``snapshot()`` at appropriate moments.

Staleness
---------
A handoff older than ``stale_s`` (default 3600 s / 1 hour) is
considered stale.  This prevents a writer that crashed overnight
from loading yesterday's context when it restarts in the morning —
the repo has moved on, and so should the writer.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_MAX_STROKES = 20
DEFAULT_STALE_S = 3600.0  # 1 hour


class HandoffManager:
    """Manage writer handoff snapshots."""

    def __init__(
        self,
        path: str | Path = "data/writer_handoff.json",
        max_strokes: int = DEFAULT_MAX_STROKES,
        stale_s: float = DEFAULT_STALE_S,
        now: float | None = None,
    ) -> None:
        self._path = Path(path)
        self._max_strokes = max_strokes
        self._stale_s = stale_s
        self._now = now

    # -- internal clock --------------------------------------------------

    def _clock(self) -> float:
        if self._now is not None:
            return self._now
        return time.time()

    # -- snapshot --------------------------------------------------------

    def snapshot(
        self,
        seq: int,
        last_strokes: List[Dict[str, Any]] | None = None,
        topic: str = "",
        clean: bool = True,
        writer: str = "qwen",
        now: float | None = None,
    ) -> Path:
        """Write a handoff snapshot atomically.

        Parameters
        ----------
        seq : int
            The last stroke sequence number.
        last_strokes : list of dict, optional
            Recent strokes to preserve for context.  Trimmed to
            *max_strokes* entries (keeping the most recent).
        topic : str
            Free-text description of the current writing topic.
        clean : bool
            ``True`` if the writer shut down gracefully; ``False``
            if it crashed or was reclaimed.
        writer : str
            Identity of the writer (e.g. ``"qwen"``).
        now : float, optional
            Override for the current timestamp (for testing).

        Returns
        -------
        Path
            The path to the written handoff file.
        """
        ts = now if now is not None else self._clock()
        strokes = list(last_strokes or [])
        # Keep only the most recent max_strokes entries.
        if len(strokes) > self._max_strokes:
            strokes = strokes[-self._max_strokes:]

        payload = {
            "seq": seq,
            "topic": topic,
            "clean": clean,
            "at": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
            "at_epoch": ts,
            "last_strokes": strokes,
            "stroke_count": seq,
            "writer": writer,
        }

        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: write to temp then rename.
        fd, tmp = tempfile.mkstemp(
            dir=str(self._path.parent),
            suffix=".tmp",
            prefix=".handoff_",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp, str(self._path))
        except BaseException:
            # Clean up temp on failure.
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

        return self._path

    # -- restore ---------------------------------------------------------

    def restore(
        self,
        now: float | None = None,
    ) -> Optional[Dict[str, Any]]:
        """Load the handoff snapshot if it exists and is fresh.

        Returns
        -------
        dict or None
            The snapshot data augmented with ``gap_s`` (seconds since
            the snapshot was written).  Returns ``None`` if:

            - The file does not exist.
            - The file is not valid JSON.
            - The snapshot is older than ``stale_s`` seconds.
        """
        if not self._path.exists():
            return None

        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

        # Check staleness.
        ts = now if now is not None else self._clock()
        at_epoch = data.get("at_epoch")
        if at_epoch is None:
            # Legacy snapshot without epoch — treat as stale.
            return None

        gap_s = ts - at_epoch
        if gap_s > self._stale_s:
            return None

        data["gap_s"] = round(gap_s, 1)
        return data

    # -- clear -----------------------------------------------------------

    def clear(self) -> bool:
        """Remove the handoff file.

        Returns
        -------
        bool
            ``True`` if the file was removed, ``False`` if it did
            not exist.
        """
        try:
            self._path.unlink()
            return True
        except FileNotFoundError:
            return False

    # -- status ----------------------------------------------------------

    def status(self, now: float | None = None) -> Dict[str, Any]:
        """Return a diagnostic status dict.

        Unlike ``restore()``, this always returns a dict — even when
        the handoff is missing or stale — making it suitable for
        dashboards and caretaker reports.
        """
        ts = now if now is not None else self._clock()

        if not self._path.exists():
            return {
                "available": False,
                "stale": False,
                "detail": "no handoff file",
            }

        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            return {
                "available": False,
                "stale": False,
                "detail": f"corrupt handoff: {exc}",
            }

        at_epoch = data.get("at_epoch")
        if at_epoch is None:
            return {
                "available": False,
                "stale": True,
                "detail": "handoff missing at_epoch — legacy format",
            }

        gap_s = ts - at_epoch
        stale = gap_s > self._stale_s

        return {
            "available": not stale,
            "stale": stale,
            "seq": data.get("seq"),
            "topic": data.get("topic", ""),
            "clean": data.get("clean"),
            "writer": data.get("writer", ""),
            "gap_s": round(gap_s, 1),
            "stroke_count": data.get("stroke_count"),
            "detail": (
                f"handoff from {data.get('writer', '?')} "
                f"seq {data.get('seq', '?')} "
                f"({gap_s:.0f}s ago, {'stale' if stale else 'fresh'})"
            ),
        }
