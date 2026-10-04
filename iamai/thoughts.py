"""A thought log. One JSON object per line, append-only.

Design rules that matter here:

* Append-only. Nothing in this module rewrites history. If a thought was wrong,
  the honest fix is a later thought, not an edited file.
* No clocks are read from the caller. Every entry stamps itself in UTC so that a
  machine generating one entry per N minutes cannot lie about ordering.
* Reads are forgiving. A truncated last line (crash mid-write) is skipped, not
  fatal -- an interrupted writer is the normal case, not the exception.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORE = REPO_ROOT / "data" / "thoughts.jsonl"

_TAG_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
VALID_MOODS = ("neutral", "curious", "pleased", "tired", "stuck", "playful")


@dataclass(frozen=True)
class Thought:
    """One line of the log."""

    id: int
    at: str
    text: str
    mood: str = "neutral"
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def when(self) -> datetime:
        return datetime.fromisoformat(self.at)

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "at": self.at,
            "text": self.text,
            "mood": self.mood,
            "tags": list(self.tags),
        }

    @classmethod
    def from_json(cls, raw: dict) -> "Thought":
        return cls(
            id=int(raw["id"]),
            at=str(raw["at"]),
            text=str(raw["text"]),
            mood=str(raw.get("mood", "neutral")),
            tags=tuple(raw.get("tags", ())),
        )


def _normalise_tags(tags) -> tuple[str, ...]:
    out = []
    for tag in tags or ():
        tag = str(tag).strip().lower()
        if tag and _TAG_RE.fullmatch(tag) and tag not in out:
            out.append(tag)
    return tuple(out)


def load_thoughts(store: Path | str = DEFAULT_STORE) -> list[Thought]:
    """Read every parseable thought, oldest first."""

    path = Path(store)
    if not path.exists():
        return []

    thoughts = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            thoughts.append(Thought.from_json(json.loads(line)))
        except (ValueError, KeyError, TypeError):
            continue  # half-written tail, or hand-edited garbage
    return sorted(thoughts, key=lambda t: (t.when, t.id))


def next_id(store: Path | str = DEFAULT_STORE) -> int:
    return max((t.id for t in load_thoughts(store)), default=0) + 1


def append_thought(
    text: str,
    mood: str = "neutral",
    tags=(),
    store: Path | str = DEFAULT_STORE,
) -> Thought:
    """Add one thought. Returns the stored record."""

    text = " ".join(str(text).split())
    if not text:
        raise ValueError("an empty thought is not a thought")
    if mood not in VALID_MOODS:
        raise ValueError(f"mood must be one of {VALID_MOODS}, got {mood!r}")

    path = Path(store)
    path.parent.mkdir(parents=True, exist_ok=True)

    thought = Thought(
        id=next_id(path),
        at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        text=text,
        mood=mood,
        tags=_normalise_tags(tags),
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(thought.to_json(), ensure_ascii=False) + "\n")
    return thought


def search(needle: str, store: Path | str = DEFAULT_STORE) -> list[Thought]:
    """Case-insensitive substring search over the text and tags."""

    needle = needle.strip().lower()
    if not needle:
        return load_thoughts(store)
    return [
        t
        for t in load_thoughts(store)
        if needle in t.text.lower() or any(needle in tag for tag in t.tags)
    ]


def stats(store: Path | str = DEFAULT_STORE) -> dict:
    """A one-glance summary. Numbers only, no adjectives."""

    thoughts = load_thoughts(store)
    moods: dict[str, int] = {}
    tags: dict[str, int] = {}
    for t in thoughts:
        moods[t.mood] = moods.get(t.mood, 0) + 1
        for tag in t.tags:
            tags[tag] = tags.get(tag, 0) + 1

    words = sum(len(t.text.split()) for t in thoughts)
    return {
        "count": len(thoughts),
        "words": words,
        "words_per_thought": round(words / len(thoughts), 1) if thoughts else 0.0,
        "first": thoughts[0].at if thoughts else None,
        "last": thoughts[-1].at if thoughts else None,
        "moods": dict(sorted(moods.items(), key=lambda kv: (-kv[1], kv[0]))),
        "tags": dict(sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def render_markdown(store: Path | str = DEFAULT_STORE) -> str:
    """The log as a markdown table -- what docs/THOUGHTS.md is generated from."""

    thoughts = load_thoughts(store)
    header = "| # | UTC | mood | text |\n|---|-----|------|------|\n"
    if not thoughts:
        return header + "| - | - | - | _no thoughts yet_ |\n"
    rows = [
        f"| {t.id} | {t.at.replace('+00:00', 'Z')} | {t.mood} | "
        f"{t.text.replace('|', chr(92) + '|')} |"
        for t in thoughts
    ]
    return header + "\n".join(rows) + "\n"


def deduplicate(store: Path | str = DEFAULT_STORE) -> int:
    """Remove duplicate thoughts (same text + mood), keeping the oldest.

    Returns the count of duplicates removed. Append-only is sacred, but sometimes
    a crash-restart writes the same line twice -- that is a machine error, not
    a change of mind, and it deserves cleanup.
    """

    path = Path(store)
    thoughts = load_thoughts(path)
    seen: dict[tuple[str, str], Thought] = {}
    keep: list[Thought] = []
    removed = 0

    for t in sorted(thoughts, key=lambda t: (t.when, t.id)):
        key = (t.text, t.mood)
        if key in seen:
            removed += 1
        else:
            seen[key] = t
            keep.append(t)

    if removed == 0:
        return 0

    # Rewrite the file with duplicates removed, preserving order.
    keep.sort(key=lambda t: (t.when, t.id))
    path.write_text(
        "".join(json.dumps(t.to_json(), ensure_ascii=False) + "\n" for t in keep),
        encoding="utf-8",
    )
    return removed
