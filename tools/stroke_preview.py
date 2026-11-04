#!/usr/bin/env python3
"""stroke_preview.py — preview recent strokes from the JSONL log.

Caretakers need a quick human-readable view of what the writer has been
producing without opening the raw JSONL.  This tool reads the last N
entries from ``data/strokes.jsonl``, parses each JSON line, and prints
a compact summary: timestamp, kind, and a truncated text preview.

It also surfaces basic health signals:

* **duplicate detection** — flags when consecutive strokes share the
  same text (a sign of template loop / echo).
* **kind distribution** — shows how many of each kind appear in the
  window, so a caretaker can see at a glance whether the writer is
  cycling through all six kinds or stuck on one.

Usage:
    python3 tools/stroke_preview.py
    python3 tools/stroke_preview.py --count 20
    python3 tools/stroke_preview.py --strokes /path/to/strokes.jsonl
    python3 tools/stroke_preview.py --json
"""

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StrokeEntry:
    seq: int
    at: str
    kind: str
    text: str
    is_duplicate: bool = False


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from *start* (or cwd) to find a git repo root."""
    p = start or Path.cwd()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return parent
    return p


def read_strokes(path: Path, count: int) -> list[dict]:
    """Read the last *count* valid JSON lines from a strokes JSONL file."""
    if not path.exists():
        return []
    entries: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entries.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue
    return entries[-count:]


def parse_strokes(raw: list[dict]) -> list[StrokeEntry]:
    """Convert raw dicts to StrokeEntry objects, marking consecutive dupes."""
    results: list[StrokeEntry] = []
    prev_text: str | None = None
    for entry in raw:
        seq = entry.get("seq", 0)
        at = entry.get("at", "")
        kind = entry.get("kind", "unknown")
        text = entry.get("text", "")
        is_dup = prev_text is not None and text == prev_text and len(text) > 0
        results.append(StrokeEntry(seq=seq, at=at, kind=kind, text=text, is_duplicate=is_dup))
        prev_text = text
    return results


def truncate(text: str, max_len: int = 80) -> str:
    """Truncate text to *max_len*, appending '…' if clipped."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "\u2026"


def format_stroke(entry: StrokeEntry, max_len: int = 80) -> str:
    """Format one stroke as a single readable line."""
    preview = truncate(entry.text, max_len)
    dup_flag = " [DUP]" if entry.is_duplicate else ""
    return f"#{entry.seq} [{entry.at}] ({entry.kind}) {preview}{dup_flag}"


def format_summary(entries: list[StrokeEntry]) -> str:
    """Produce a multi-line summary: kind distribution + duplicate count."""
    if not entries:
        return "no strokes in window"
    kinds = Counter(e.kind for e in entries)
    dup_count = sum(1 for e in entries if e.is_duplicate)
    kind_line = ", ".join(f"{k} x{v}" for k, v in sorted(kinds.items()))
    lines = [
        f"window: {len(entries)} strokes",
        f"kinds:  {kind_line}",
        f"duplicates: {dup_count}",
    ]
    return "\n".join(lines)


def to_json(entries: list[StrokeEntry]) -> str:
    """Serialise entries to a JSON array."""
    return json.dumps(
        [
            {
                "seq": e.seq,
                "at": e.at,
                "kind": e.kind,
                "text": e.text,
                "is_duplicate": e.is_duplicate,
            }
            for e in entries
        ],
        ensure_ascii=False,
        indent=2,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview recent strokes.")
    parser.add_argument("--count", type=int, default=10, help="Number of recent strokes to show")
    parser.add_argument("--strokes", type=Path, default=None, help="Path to strokes JSONL")
    parser.add_argument("--max-len", type=int, default=80, help="Max text preview length")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--summary", action="store_true", help="Show summary only")
    args = parser.parse_args()

    if args.strokes:
        strokes_path = args.strokes
    else:
        repo = find_repo_root()
        strokes_path = repo / "data" / "strokes.jsonl"

    raw = read_strokes(strokes_path, args.count)
    entries = parse_strokes(raw)

    if args.json:
        print(to_json(entries))
    elif args.summary:
        print(format_summary(entries))
    else:
        for entry in entries:
            print(format_stroke(entry, args.max_len))
        print()
        print(format_summary(entries))

    return 0


if __name__ == "__main__":
    sys.exit(main())
