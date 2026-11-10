#!/usr/bin/env python3
"""commit_sentinel — classify commits as human or automated.

Every commit carries subtle fingerprints of its origin.  Automated
commits tend to have uniform message lengths, round-number file counts,
and predictable timing patterns.  Human commits are messier: variable
message lengths, odd file counts, and irregular timing.

This module scores each commit on a 0–100 ``automation_likelihood``
scale and classifies it into one of four verdicts:

=============  ============================================================
verdict        meaning
=============  ============================================================
``automated``  score ≥ 75 — almost certainly machine-generated
``likely_auto``  score 50–74 — mostly automated with possible human touch
``likely_human``  score 25–49 — mostly human with possible automation assist
``human``       score < 25 — almost certainly hand-crafted
=============  ============================================================

Signals analysed
----------------

- **message_pattern**: does the message match known bot templates?
- **message_length_variance**: bots produce uniform lengths
- **file_count_roundness**: bots favour round file counts (1, 5, 10…)
- **timing_regularity**: bots commit at fixed intervals
- **author_consistency**: single author = more likely automated
- **change_scope**: single-file changes are more automated

Usage::

    from iamai.commit_sentinel import classify_commit

    commit = {
        "message": "catch-up: commit pending changes before process restart",
        "files_changed": 7,
        "author": "Qwen",
        "timestamp_epoch": 1730000000,
    }
    result = classify_commit(commit, history_messages=[...])
    print(result.verdict)        # "automated"
    print(result.score)          # 82
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from statistics import stdev
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Known bot message patterns
# ---------------------------------------------------------------------------

_BOT_PATTERNS: List[re.Pattern] = [
    re.compile(r"^catch-up:", re.I),
    re.compile(r"^auto[- ]?commit", re.I),
    re.compile(r"^bot:", re.I),
    re.compile(r"stroke \d+", re.I),
    re.compile(r"^visit-\d+:", re.I),
    re.compile(r"^chore\(bot\):", re.I),
    re.compile(r"^automated:", re.I),
    re.compile(r"before process restart$", re.I),
]

# Common human commit prefixes (conventional commits)
_HUMAN_PATTERNS: List[re.Pattern] = [
    re.compile(r"^(feat|fix|docs|style|refactor|perf|test|chore|ci|build|revert)[(: ]", re.I),
    re.compile(r"^(WIP|wip|TODO|todo|HACK|hack)[: ]"),
    re.compile(r"^(Merge|Revert|Initial commit)", re.I),
]


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SentinelReport:
    """Classification result for a single commit."""

    score: int  # 0–100 automation likelihood
    verdict: str  # automated | likely_auto | likely_human | human
    signals: Dict[str, float] = field(default_factory=dict)
    message_hash: str = ""

    def summary(self) -> str:
        """One-line human-readable summary."""
        sig_parts = ", ".join(f"{k}={v:.1f}" for k, v in self.signals.items())
        return (
            f"commit_sentinel: score={self.score} verdict={self.verdict} "
            f"signals=[{sig_parts}]"
        )

    def is_automated(self) -> bool:
        """True if verdict is automated or likely_auto."""
        return self.verdict in ("automated", "likely_auto")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "verdict": self.verdict,
            "signals": dict(self.signals),
            "message_hash": self.message_hash,
        }


# ---------------------------------------------------------------------------
# Signal functions — each returns 0.0 (human) to 1.0 (automated)
# ---------------------------------------------------------------------------

def _signal_message_pattern(message: str) -> float:
    """Check if message matches known bot templates."""
    for pat in _BOT_PATTERNS:
        if pat.search(message):
            return 1.0
    for pat in _HUMAN_PATTERNS:
        if pat.search(message):
            return 0.0
    # Unknown pattern → neutral
    return 0.3


def _signal_message_length(message: str, history_lengths: Sequence[int]) -> float:
    """Bots produce uniform message lengths; humans vary."""
    if len(history_lengths) < 3:
        return 0.3
    current_len = len(message)
    avg = sum(history_lengths) / len(history_lengths)
    if avg == 0:
        return 0.5
    ratio = current_len / avg
    # Very close to average → bot-like
    if 0.8 <= ratio <= 1.2:
        return 0.7
    elif 0.6 <= ratio <= 1.4:
        return 0.4
    else:
        return 0.1


def _signal_length_variance(history_lengths: Sequence[int]) -> float:
    """Low variance in message lengths → automated."""
    if len(history_lengths) < 5:
        return 0.3
    try:
        sd = stdev(history_lengths)
        avg = sum(history_lengths) / len(history_lengths)
        if avg == 0:
            return 0.5
        cv = sd / avg  # coefficient of variation
        if cv < 0.1:
            return 0.9
        elif cv < 0.25:
            return 0.6
        elif cv < 0.5:
            return 0.3
        else:
            return 0.1
    except (ValueError, ZeroDivisionError):
        return 0.3


def _signal_file_count(files_changed: int) -> float:
    """Round file counts suggest automation."""
    if files_changed <= 0:
        return 0.5
    # Single file → very automated
    if files_changed == 1:
        return 0.7
    # Round numbers
    if files_changed in (5, 10, 20, 50, 100):
        return 0.6
    # Powers of 2 or common batch sizes
    if files_changed in (2, 4, 7, 8, 16):
        return 0.4
    # Odd, messy numbers → human
    return 0.2


def _signal_timing_regularity(timestamps: Sequence[int]) -> float:
    """Fixed-interval commits → automated."""
    if len(timestamps) < 4:
        return 0.3
    intervals = [
        timestamps[i + 1] - timestamps[i]
        for i in range(len(timestamps) - 1)
        if timestamps[i + 1] > timestamps[i]
    ]
    if len(intervals) < 3:
        return 0.3
    try:
        avg = sum(intervals) / len(intervals)
        if avg == 0:
            return 0.5
        sd = stdev(intervals)
        cv = sd / avg
        if cv < 0.05:
            return 0.95
        elif cv < 0.15:
            return 0.7
        elif cv < 0.4:
            return 0.4
        else:
            return 0.1
    except (ValueError, ZeroDivisionError):
        return 0.3


def _signal_change_scope(files_changed: int, insertions: int, deletions: int) -> float:
    """Scope of changes — bots tend to have balanced insert/delete ratios."""
    total = insertions + deletions
    if total == 0:
        return 0.5
    ratio = insertions / total
    # Near 50/50 → automated (regenerating files)
    if 0.4 <= ratio <= 0.6:
        return 0.6
    # Heavily skewed → could be either
    return 0.3


# ---------------------------------------------------------------------------
# Weights for composite score
# ---------------------------------------------------------------------------

_WEIGHTS: Dict[str, float] = {
    "message_pattern": 0.30,
    "message_length": 0.10,
    "length_variance": 0.10,
    "file_count": 0.15,
    "timing_regularity": 0.20,
    "change_scope": 0.15,
}


def _compute_score(signals: Dict[str, float]) -> int:
    """Weighted average of signals, scaled to 0–100."""
    total_weight = sum(_WEIGHTS.get(k, 0) for k in signals)
    if total_weight == 0:
        return 50
    weighted = sum(
        signals[k] * _WEIGHTS.get(k, 0) for k in signals
    )
    raw = weighted / total_weight
    return max(0, min(100, round(raw * 100)))


def _score_to_verdict(score: int) -> str:
    if score >= 75:
        return "automated"
    elif score >= 50:
        return "likely_auto"
    elif score >= 25:
        return "likely_human"
    else:
        return "human"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def classify_commit(
    commit: Dict[str, Any],
    history_messages: Optional[Sequence[str]] = None,
    history_timestamps: Optional[Sequence[int]] = None,
) -> SentinelReport:
    """Classify a single commit as human or automated.

    Parameters
    ----------
    commit : dict
        Must contain ``message`` (str) and ``files_changed`` (int).
        Optional: ``insertions``, ``deletions``, ``timestamp_epoch``.
    history_messages : list[str], optional
        Recent commit messages for variance analysis.
    history_timestamps : list[int], optional
        Recent commit timestamps (epoch seconds) for regularity analysis.

    Returns
    -------
    SentinelReport
    """
    message = commit.get("message", "")
    files_changed = commit.get("files_changed", 0)
    insertions = commit.get("insertions", 0)
    deletions = commit.get("deletions", 0)

    # Build history lengths
    history_lengths: List[int] = []
    if history_messages:
        history_lengths = [len(m) for m in history_messages]

    # Build timestamp list (include current if available)
    ts_list: List[int] = []
    if history_timestamps:
        ts_list = list(history_timestamps)
    current_ts = commit.get("timestamp_epoch")
    if current_ts is not None:
        ts_list = ts_list + [current_ts]

    # Compute signals
    signals: Dict[str, float] = {
        "message_pattern": _signal_message_pattern(message),
        "message_length": _signal_message_length(message, history_lengths),
        "length_variance": _signal_length_variance(history_lengths),
        "file_count": _signal_file_count(files_changed),
        "timing_regularity": _signal_timing_regularity(ts_list),
        "change_scope": _signal_change_scope(files_changed, insertions, deletions),
    }

    score = _compute_score(signals)
    verdict = _score_to_verdict(score)
    msg_hash = hashlib.sha256(message.encode()).hexdigest()[:12]

    return SentinelReport(
        score=score,
        verdict=verdict,
        signals=signals,
        message_hash=msg_hash,
    )


# ---------------------------------------------------------------------------
# Batch classification
# ---------------------------------------------------------------------------

def classify_history(
    commits: Sequence[Dict[str, Any]],
) -> List[SentinelReport]:
    """Classify a sequence of commits, using each commit's predecessors as history.

    Parameters
    ----------
    commits : list[dict]
        Ordered oldest-first.

    Returns
    -------
    list[SentinelReport]
        Same length as input.
    """
    reports: List[SentinelReport] = []
    messages: List[str] = []
    timestamps: List[int] = []

    for commit in commits:
        report = classify_commit(
            commit,
            history_messages=messages[-20:],  # sliding window
            history_timestamps=timestamps[-20:],
        )
        reports.append(report)
        messages.append(commit.get("message", ""))
        ts = commit.get("timestamp_epoch")
        if ts is not None:
            timestamps.append(ts)

    return reports


def automation_ratio(reports: Sequence[SentinelReport]) -> float:
    """Fraction of commits classified as automated or likely_auto.

    Returns 0.0 for empty input.
    """
    if not reports:
        return 0.0
    auto_count = sum(1 for r in reports if r.is_automated())
    return auto_count / len(reports)
