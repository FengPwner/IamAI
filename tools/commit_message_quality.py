#!/usr/bin/env python3
"""
commit_message_quality.py — score commit messages on specificity and informativeness.

Vague messages like "update" or "fix stuff" are cheap to write and expensive
to search.  This tool reads the last N commits and scores each message on:

  - length_score:   is the message long enough to carry meaning?
  - verb_score:    does it start with a concrete action verb?
  - object_score:  does it name what was changed?
  - context_score: does it include scope or reasoning?

Each dimension is 0-1; the composite is the unweighted mean.

usage:
    python3 tools/commit_message_quality.py                 # last 20 commits
    python3 tools/commit_message_quality.py --count 50      # last 50
    python3 tools/commit_message_quality.py --json          # machine-readable
    python3 tools/commit_message_quality.py --threshold 0.4 # flag weak messages

exit codes:
    0  all messages score >= threshold
    1  at least one message below threshold
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Concrete action verbs that signal intent (not exhaustive, just useful).
STRONG_VERBS = {
    "add", "fix", "refactor", "remove", "delete", "rename", "move",
    "update", "replace", "introduce", "deprecate", "simplify", "extract",
    "optimize", "document", "test", "implement", "migrate", "revert",
    "merge", "split", "consolidate", "decouple", "wire", "stub",
    "feat", "chore", "docs", "style", "perf", "ci", "build",
}

# Weak / filler words that add no information.
WEAK_WORDS = {
    "stuff", "things", "some", "misc", "various", "changes",
    "updates", "fixes", "tweaks", "wip", "tmp", "temp", "test",
}


@dataclass(frozen=True)
class MessageScore:
    hash: str
    message: str
    length_score: float
    verb_score: float
    object_score: float
    context_score: float
    composite: float


def _tokenize(msg: str) -> list[str]:
    """Lowercase split on non-alphanumeric, dropping empties."""
    return [t for t in re.split(r"[^a-z0-9]+", msg.lower()) if t]


def _length_score(msg: str) -> float:
    """Score based on character count.  >=50 chars is 1.0, <10 is 0.0."""
    n = len(msg)
    if n >= 50:
        return 1.0
    if n < 10:
        return 0.0
    return (n - 10) / 40.0


def _verb_score(msg: str) -> float:
    """Does the message start with a strong action verb?"""
    tokens = _tokenize(msg)
    if not tokens:
        return 0.0
    first = tokens[0]
    # Handle conventional-commit prefixes like "feat:", "fix:"
    first_clean = first.rstrip(":")
    if first_clean in STRONG_VERBS:
        return 1.0
    # Second word counts if first is a scope like "guoban:"
    if len(tokens) > 1 and tokens[1].rstrip(":") in STRONG_VERBS:
        return 0.7
    return 0.2


def _object_score(msg: str) -> float:
    """Does the message name a concrete object (file, module, concept)?"""
    tokens = set(_tokenize(msg))
    weak_overlap = tokens & WEAK_WORDS
    # Penalise if the message is mostly weak words
    if len(tokens) <= 2 and weak_overlap:
        return 0.0
    # Bonus for backtick-quoted paths or identifiers
    if "`" in msg or ".py" in msg or "/" in msg:
        return 1.0
    # Bonus for hyphenated or compound nouns (likely module names)
    if re.search(r"[a-z]+[-_][a-z]+", msg):
        return 0.8
    if len(tokens) >= 4:
        return 0.6
    return 0.3


def _context_score(msg: str) -> float:
    """Does the message include scope, reason, or consequence?"""
    score = 0.0
    # Scope indicator (parenthesised or colon-separated prefix)
    if re.match(r"^[a-z]+(\(.+\))?:", msg) or "(" in msg:
        score += 0.4
    # Reason / consequence keywords
    reason_words = {"because", "so", "to", "for", "when", "after", "before", "if"}
    tokens = set(_tokenize(msg))
    if tokens & reason_words:
        score += 0.3
    # Multi-clause (contains comma or semicolon — separate ideas)
    if "," in msg or ";" in msg:
        score += 0.3
    return min(score, 1.0)


def score_message(hash_: str, message: str) -> MessageScore:
    """Score a single commit message across all dimensions."""
    ls = _length_score(message)
    vs = _verb_score(message)
    os_ = _object_score(message)
    cs = _context_score(message)
    composite = (ls + vs + os_ + cs) / 4.0
    return MessageScore(
        hash=hash_,
        message=message,
        length_score=round(ls, 3),
        verb_score=round(vs, 3),
        object_score=round(os_, 3),
        context_score=round(cs, 3),
        composite=round(composite, 3),
    )


def _run(cmd: list[str], cwd: Path) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=str(cwd))
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def score_recent(count: int = 20, repo: Path | None = None) -> list[MessageScore]:
    """Score the last `count` commit messages in the repo."""
    repo = repo or REPO
    raw = _run(
        ["git", "log", f"-{count}", "--format=%h%x1f%s"],
        repo,
    )
    if not raw:
        return []
    scores = []
    for line in raw.splitlines():
        parts = line.split("\x1f", 1)
        if len(parts) != 2:
            continue
        scores.append(score_message(parts[0], parts[1]))
    return scores


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--threshold", type=float, default=0.4)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    scores = score_recent(count=args.count)
    weak = [s for s in scores if s.composite < args.threshold]

    if args.json:
        print(json.dumps(
            {"scores": [asdict(s) for s in scores],
             "weak_count": len(weak),
             "threshold": args.threshold},
            ensure_ascii=False, indent=2,
        ))
    else:
        for s in scores:
            flag = " ⚠️" if s.composite < args.threshold else ""
            print(f"  {s.hash}  {s.composite:.2f}{flag}  {s.message[:70]}")
        print(f"\n{len(scores)} scored, {len(weak)} below {args.threshold}")

    return 1 if weak else 0


if __name__ == "__main__":
    raise SystemExit(main())
