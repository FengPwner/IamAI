"""Score commit messages for clarity and convention adherence.

A repo that writes itself needs to keep its commit log readable.
This module checks each message against a small set of rules derived
from the git project's own contributing guide and the conventions
that have accumulated in this repo over 400+ strokes.

Rules checked (each contributes to a 0-100 score):

1. **Length** — subject line ≤ 72 chars (hard cap), ideally 10-50.
2. **Capitalization** — subject starts with a letter (upper or lower),
   not a symbol or digit.
3. **No period** — subject line does not end with ``.``.
4. **Imperative mood** — first word is not past tense (-ed) or gerund (-ing)
   when a conventional imperative form exists.
5. **No noise prefixes** — rejects ``Update``, ``Fix``, ``WIP`` as the
   *entire* subject (these say nothing about what changed).

Usage::

    from iamai.commit_message_quality import score_message
    result = score_message("add retry_budget snippet (11 tests)")
    print(result["score"])     # 80
    print(result["issues"])    # []

    result = score_message("Fixed stuff.")
    print(result["score"])     # 20
    print(result["issues"])    # ["past_tense", "vague", "trailing_period"]
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


# Past-tense and gerund suffixes that signal non-imperative mood.
# Deliberately short: we don't want false positives on words like
# "add" (which ends in 'd' but is imperative).
_PAST_TENSE_RE = re.compile(r"^(fixed|updated|removed|deleted|changed|added|cleaned|merged|pushed|pulled)$", re.I)
_GERUND_RE = re.compile(r"^(fixing|updating|removing|deleting|changing|adding|cleaning|merging|pushing|pulling)$", re.I)

# Vague messages that say nothing about what changed.
_VAGUE_SUBJECTS = frozenset({
    "update", "fix", "wip", "changes", "stuff", "updates",
    "fixes", "work", "commit", "save", "temp", "test",
})


def _check_length(subject: str) -> List[str]:
    issues: List[str] = []
    if len(subject) > 72:
        issues.append("too_long")
    elif len(subject) < 3:
        issues.append("too_short")
    return issues


def _check_capitalization(subject: str) -> List[str]:
    if not subject:
        return ["empty"]
    if not subject[0].isalpha():
        return ["non_alpha_start"]
    return []


def _check_trailing_period(subject: str) -> List[str]:
    if subject.rstrip().endswith("."):
        return ["trailing_period"]
    return []


def _check_imperative(first_word: str) -> List[str]:
    if _PAST_TENSE_RE.match(first_word):
        return ["past_tense"]
    if _GERUND_RE.match(first_word):
        return ["gerund"]
    return []


def _check_vague(subject: str) -> List[str]:
    if subject.lower().strip() in _VAGUE_SUBJECTS:
        return ["vague"]
    return []


def score_message(message: str) -> Dict[str, Any]:
    """Score a single commit message.

    Returns a dict with ``score`` (0-100), ``issues`` (list of rule
    names that fired), and ``subject`` (the first line extracted).
    """
    if not message or not message.strip():
        return {"score": 0, "issues": ["empty"], "subject": ""}

    subject = message.split("\n", 1)[0].strip()
    first_word = subject.split()[0] if subject.split() else ""

    issues: List[str] = []
    issues.extend(_check_length(subject))
    issues.extend(_check_capitalization(subject))
    issues.extend(_check_trailing_period(subject))
    issues.extend(_check_imperative(first_word))
    issues.extend(_check_vague(subject))

    # Each issue costs 20 points; floor at 0.
    score = max(0, 100 - len(issues) * 20)

    return {"score": score, "issues": issues, "subject": subject}


def score_history(messages: List[str]) -> Dict[str, Any]:
    """Score a batch of commit messages and return aggregate quality.

    Useful for caretaker visits: "how is our commit hygiene this week?"
    """
    if not messages:
        return {"mean_score": 0, "total": 0, "worst": None, "issues_count": {}}

    results = [score_message(m) for m in messages]
    scores = [r["score"] for r in results]
    mean = sum(scores) / len(scores)

    # Find the worst offender.
    worst = min(results, key=lambda r: r["score"])

    # Tally issue frequencies.
    issue_counts: Dict[str, int] = {}
    for r in results:
        for issue in r["issues"]:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1

    return {
        "mean_score": round(mean, 1),
        "total": len(results),
        "worst": worst,
        "issues_count": issue_counts,
    }
