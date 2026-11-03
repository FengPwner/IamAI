"""commit_signal — score commit messages for information density.

An automated writer produces hundreds of commits.  Most are meaningful
("visit 521: process_survival module + 42 tests + visit note"), but some
degenerate into low-signal filler ("catch-up", "update", "fix").  This
module scores each message on a 0–10 scale so caretakers can flag
degrading commit hygiene early.

Public API
----------

``CommitScore``
    Dataclass: message (str), score (float 0–10), tags (list[str]).
    Tags describe *why* the score is what it is (e.g. "too-short",
    "no-noun", "has-metrics", "has-prefix").

``score(message) -> CommitScore``
    Score a single commit message.

``score_recent(repo_path, n=20) -> list[CommitScore]``
    Read the last *n* commits from git log and score each one.

``average(scores) -> float``
    Mean score across a list of CommitScore objects.

``is_healthy(scores, threshold=5.0) -> bool``
    True when average score >= threshold.

Scoring heuristics
------------------

- **length**: >= 10 chars → +2; >= 30 → +3; >= 50 → +4 (max 4).
- **prefix**: starts with a recognised tag (visit, guoban, catch-up,
  feat, fix, refactor, docs, test) → +1.
- **metrics**: contains a number (e.g. "42 tests", "stroke 285") → +2.
- **noun density**: ratio of unique non-stop words to total words
  above 0.5 → +2; above 0.3 → +1.
- **filler penalty**: entire message matches one of the known filler
  patterns ("update", "fix stuff", "wip", "save", "commit") → −3.

The result is clamped to [0, 10].
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

STOP_WORDS = frozenset(
    "a an the and or but in on at to for of is was are be been "
    "this that it its with from by as".split()
)

KNOWN_PREFIXES = (
    "visit", "guoban", "catch-up", "feat", "fix", "refactor",
    "docs", "test", "chore", "ci", "perf", "style",
)

FILLER_PATTERNS = [
    re.compile(r"^(update|fix stuff|wip|save|commit|changes|temp)$", re.I),
]


@dataclass
class CommitScore:
    message: str
    score: float = 0.0
    tags: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------

def score(message: str) -> CommitScore:
    """Score a single commit message for information density."""
    cs = CommitScore(message=message)
    text = message.strip()
    if not text:
        cs.score = 0.0
        cs.tags.append("empty")
        return cs

    # Length component (max 4)
    if len(text) >= 50:
        cs.score += 4
        cs.tags.append("long")
    elif len(text) >= 30:
        cs.score += 3
        cs.tags.append("medium-length")
    elif len(text) >= 10:
        cs.score += 2
        cs.tags.append("short-ok")
    else:
        cs.tags.append("too-short")

    # Prefix component (+1)
    first_word = text.split()[0].rstrip(":").lower()
    if first_word in KNOWN_PREFIXES:
        cs.score += 1
        cs.tags.append("has-prefix")

    # Metrics component (+2)
    if re.search(r"\d+", text):
        cs.score += 2
        cs.tags.append("has-metrics")

    # Noun density (max +2)
    words = [w.lower() for w in re.findall(r"[a-zA-Z]+", text)]
    if words:
        content_words = [w for w in words if w not in STOP_WORDS and len(w) > 2]
        unique_ratio = len(set(content_words)) / max(len(words), 1)
        if unique_ratio >= 0.5:
            cs.score += 2
            cs.tags.append("rich-vocab")
        elif unique_ratio >= 0.3:
            cs.score += 1
            cs.tags.append("ok-vocab")

    # Filler penalty (−3)
    for pat in FILLER_PATTERNS:
        if pat.match(text):
            cs.score -= 3
            cs.tags.append("filler")
            break

    # Clamp
    cs.score = max(0.0, min(10.0, cs.score))
    return cs


# ---------------------------------------------------------------------------
# Batch scoring from git log
# ---------------------------------------------------------------------------

def score_recent(repo_path: str | Path, n: int = 20) -> List[CommitScore]:
    """Score the last *n* commits in the repo at *repo_path*."""
    result = subprocess.run(
        ["git", "log", f"-{n}", "--format=%s"],
        capture_output=True, text=True,
        cwd=str(repo_path),
    )
    if result.returncode != 0:
        return []
    return [score(line) for line in result.stdout.strip().splitlines() if line]


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

def average(scores: List[CommitScore]) -> float:
    """Mean score. Returns 0.0 for empty lists."""
    if not scores:
        return 0.0
    return sum(s.score for s in scores) / len(scores)


def is_healthy(scores: List[CommitScore], threshold: float = 5.0) -> bool:
    """True when the average score meets or exceeds *threshold*."""
    return average(scores) >= threshold
