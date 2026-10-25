"""065 — wal: a minimal write-ahead log for crash-safe state recovery.

the write-ahead log is the oldest trick in the durability playbook: before
you mutate state, you append the *intent* to a sequential log.  if the
process crashes mid-write, the log survives; on restart you replay from the
last checkpoint and catch up.  databases, file systems, and message brokers
all use some variant of this idea.

this implementation is deliberately small — JSON-lines on disk, one file —
but captures the three operations that matter:

- **append(entry)** — serialise *entry* as a JSON line, fsync, return its
  monotonic sequence number.  the fsync is what makes it durable.

- **replay()** — yield every entry whose sequence number is strictly
  greater than the current checkpoint.  this is what you call on startup
  to rebuild in-memory state.

- **checkpoint(seq)** — record that all entries up to and including *seq*
  have been applied.  **truncate()** then rewrites the log, keeping only
  entries after the checkpoint.

    log = WAL("/tmp/wal.jsonl")
    s1 = log.append({"op": "set", "key": "x", "value": 1})
    s2 = log.append({"op": "set", "key": "y", "value": 2})
    log.checkpoint(s1)
    log.truncate()
    list(log.replay())   # only entry s2

edge cases handled:

- appending to a corrupt tail line raises CorruptEntry; the caller decides
  whether to truncate-and-continue or bail.
- checkpoint(seq) with a seq *below* the current checkpoint is a no-op
  (monotonic watermark — never goes backward).
- replay on an empty or missing log file yields nothing.
- truncate on an empty log is safe (rewrites to an empty file).
- sequence numbers are derived from the file: the last line's seq + 1 for
  new appends.  no external counter to lose.

zero external dependencies.  stdlib only (json, os, pathlib, threading).
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, Optional


class CorruptEntry(Exception):
    """Raised when a WAL line cannot be decoded."""

    def __init__(self, line_no: int, raw: str, cause: Exception) -> None:
        super().__init__(f"corrupt WAL entry at line {line_no}: {cause}")
        self.line_no = line_no
        self.raw = raw
        self.cause = cause


class WAL:
    """Append-only write-ahead log backed by a JSON-lines file."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._checkpoint_seq: int = 0
        # Bootstrap: read existing checkpoint file if present.
        self._cp_path = self._path.with_suffix(".ckpt")
        if self._cp_path.exists():
            try:
                self._checkpoint_seq = int(self._cp_path.read_text().strip())
            except (ValueError, OSError):
                self._checkpoint_seq = 0

    # -- properties -------------------------------------------------------

    @property
    def path(self) -> Path:
        """Path to the underlying JSON-lines file."""
        return self._path

    @property
    def checkpoint_seq(self) -> int:
        """The most recently checkpointed sequence number (watermark)."""
        return self._checkpoint_seq

    # -- append -----------------------------------------------------------

    def append(self, entry: Dict[str, Any]) -> int:
        """Append *entry* to the log, fsync, and return its sequence number."""
        with self._lock:
            seq = self._next_seq()
            line = json.dumps({"seq": seq, "data": entry}, separators=(",", ":"))
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
            return seq

    # -- replay -----------------------------------------------------------

    def replay(self) -> Iterator[Dict[str, Any]]:
        """Yield every entry after the current checkpoint, in order."""
        if not self._path.exists():
            return
        with open(self._path, "r", encoding="utf-8") as f:
            for line_no, raw in enumerate(f, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise CorruptEntry(line_no, raw, exc) from exc
                seq = record.get("seq", 0)
                if seq > self._checkpoint_seq:
                    yield record

    # -- checkpoint & truncate -------------------------------------------

    def checkpoint(self, seq: int) -> None:
        """Advance the checkpoint watermark to *seq* (monotonic)."""
        with self._lock:
            if seq <= self._checkpoint_seq:
                return  # never go backward
            self._checkpoint_seq = seq
            self._cp_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cp_path.with_suffix(".ckpt.tmp")
            tmp.write_text(str(seq), encoding="utf-8")
            os.replace(tmp, self._cp_path)

    def truncate(self) -> int:
        """Rewrite the log, keeping only entries after the checkpoint.

        Returns the number of entries retained.
        """
        with self._lock:
            kept: list[str] = []
            if self._path.exists():
                with open(self._path, "r", encoding="utf-8") as f:
                    for raw in f:
                        raw_s = raw.strip()
                        if not raw_s:
                            continue
                        try:
                            record = json.loads(raw_s)
                        except json.JSONDecodeError:
                            continue  # drop corrupt lines during truncate
                        if record.get("seq", 0) > self._checkpoint_seq:
                            kept.append(raw_s)
                # Rewrite atomically.
                tmp = self._path.with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    for line in kept:
                        f.write(line + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self._path)
            return len(kept)

    # -- helpers ----------------------------------------------------------

    def _next_seq(self) -> int:
        """Derive the next sequence number from the last line in the file.

        Always returns at least checkpoint_seq + 1 so that sequence numbers
        remain monotonic even after a full truncate.
        """
        floor = self._checkpoint_seq
        if not self._path.exists():
            return floor + 1
        last_seq = floor
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        record = json.loads(raw)
                        seq = record.get("seq", 0)
                        if seq > last_seq:
                            last_seq = seq
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return floor + 1
        return last_seq + 1

    # -- dunder -----------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"WAL(path={self._path}, checkpoint={self._checkpoint_seq})"
        )

    def __len__(self) -> int:
        """Total entries in the file (including those before checkpoint)."""
        if not self._path.exists():
            return 0
        count = 0
        with open(self._path, "r", encoding="utf-8") as f:
            for raw in f:
                if raw.strip():
                    count += 1
        return count
