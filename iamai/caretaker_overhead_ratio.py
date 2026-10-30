"""caretaker_overhead_ratio — measure how much recent history is pure maintenance.

every commit in this repo falls into one of three buckets:

===========  ============================================================
category     what it means
===========  ============================================================
substantive  new feature, tool, test, note, or content the writer produced
overhead     caretaker catch-up, process restart, watchdog auto-commit,
             backlog drain — work *about* the repo, not *in* the repo
hybrid       a feat: commit that also restarts processes or commits
             backlog as part of a caretaker visit
===========  ============================================================

the overhead ratio is::

    overhead_ratio = (overhead + 0.5 * hybrid) / total

bands:

=========  ============  ===========================================
band       ratio         meaning
=========  ============  ===========================================
lean       0.00–0.19     most work is substantive
moderate   0.20–0.39     noticeable maintenance but manageable
heavy      0.40–0.59     more than half of effort is upkeep
critical   0.60–1.00     repo is spending most of its time on itself
=========  ============  ===========================================

usage::

    from iamai.caretaker_overhead_ratio import classify_commits, overhead_report

    messages = [
        "feat: add push_exposure_index (28 tests); caretaker visit 392",
        "catch-up: commit pending changes before process restart",
        "watchdog: auto-commit 9 pending file(s) at check #6",
    ]
    result = overhead_report(messages)
    print(result["ratio"])     # 0.50
    print(result["band"])      # "heavy"
    print(result["summary"])   # "2 of 3 commits are overhead (ratio 0.50)"
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# classification patterns
# ---------------------------------------------------------------------------

# patterns that indicate pure overhead
_OVERHEAD_PATTERNS = [
    re.compile(r"^catch-up:", re.IGNORECASE),
    re.compile(r"^watchdog:\s*auto-commit", re.IGNORECASE),
    re.compile(r"process restart", re.IGNORECASE),
    re.compile(r"backlog drain", re.IGNORECASE),
    re.compile(r"hourly monitor auto-commit", re.IGNORECASE),
]

# patterns that indicate substantive work
_SUBSTANTIVE_PATTERNS = [
    re.compile(r"^feat:", re.IGNORECASE),
    re.compile(r"^fix:", re.IGNORECASE),
    re.compile(r"^refactor:", re.IGNORECASE),
    re.compile(r"^docs:", re.IGNORECASE),
    re.compile(r"^stroke\s+\d+", re.IGNORECASE),
]

# patterns that indicate a hybrid commit (caretaker visit with new tool)
_HYBRID_PATTERNS = [
    re.compile(r"caretaker visit \d+", re.IGNORECASE),
    re.compile(r"restarted both processes", re.IGNORECASE),
    re.compile(r"committed backlog", re.IGNORECASE),
]


def classify_commit(message: str) -> str:
    """Classify a single commit message as 'substantive', 'overhead', or 'hybrid'.

    Rules (applied in order):
    1. If message matches an overhead pattern AND a substantive pattern,
       it is hybrid (e.g. "feat: add tool; caretaker visit 392").
    2. If message matches only overhead patterns → overhead.
    3. If message matches a substantive pattern → substantive.
    4. Otherwise → substantive (default for unclassified commits).
    """
    if not message or not message.strip():
        return "substantive"

    msg = message.strip()

    is_overhead = any(p.search(msg) for p in _OVERHEAD_PATTERNS)
    is_substantive = any(p.search(msg) for p in _SUBSTANTIVE_PATTERNS)
    has_hybrid_signal = any(p.search(msg) for p in _HYBRID_PATTERNS)

    # hybrid: has both substantive content and caretaker overhead
    if is_substantive and (is_overhead or has_hybrid_signal):
        return "hybrid"

    if is_overhead:
        return "overhead"

    return "substantive"


def classify_commits(messages: List[str]) -> List[Tuple[str, str]]:
    """Classify a list of commit messages.

    Returns list of (message, category) tuples.
    """
    return [(msg, classify_commit(msg)) for msg in messages]


def overhead_ratio(categories: List[str]) -> float:
    """Compute the overhead ratio from a list of categories.

    Formula: (overhead + 0.5 * hybrid) / total
    Returns 0.0 for empty input.
    """
    if not categories:
        return 0.0

    total = len(categories)
    overhead_count = sum(1 for c in categories if c == "overhead")
    hybrid_count = sum(1 for c in categories if c == "hybrid")

    return (overhead_count + 0.5 * hybrid_count) / total


def _band(ratio: float) -> str:
    """Map ratio to a human-readable band."""
    if ratio < 0.20:
        return "lean"
    if ratio < 0.40:
        return "moderate"
    if ratio < 0.60:
        return "heavy"
    return "critical"


def overhead_report(messages: List[str]) -> Dict:
    """Produce a full overhead analysis report.

    Returns dict with keys:
        total, substantive, overhead, hybrid, ratio, band, summary, breakdown
    """
    classified = classify_commits(messages)
    categories = [cat for _, cat in classified]

    total = len(categories)
    sub_count = sum(1 for c in categories if c == "substantive")
    ovr_count = sum(1 for c in categories if c == "overhead")
    hyb_count = sum(1 for c in categories if c == "hybrid")

    ratio = overhead_ratio(categories)
    band = _band(ratio)

    if total == 0:
        summary = "no commits to analyse"
    else:
        overhead_equiv = ovr_count + 0.5 * hyb_count
        summary = (
            f"{overhead_equiv:.1f} of {total} commits are overhead "
            f"(ratio {ratio:.2f}, band: {band})"
        )

    return {
        "total": total,
        "substantive": sub_count,
        "overhead": ovr_count,
        "hybrid": hyb_count,
        "ratio": round(ratio, 4),
        "band": band,
        "summary": summary,
        "breakdown": classified,
    }
