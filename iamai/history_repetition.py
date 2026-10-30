"""history_repetition — detect when the history log is stuck in a loop.

The writer appends a line to ``notes/history.md`` for every stroke it
processes.  A healthy history is *diverse*: each line describes a
different action (new file, new thought, module update, caretaker visit,
etc.).  A stalled history is a wall of near-identical lines — the
classic symptom is the "``X.py`` is already in the pool of N modules,
nothing new to add there" pattern repeating hundreds of times.

This module answers two questions:

1. **How long is the longest consecutive run of identical entries?**
   A run of 10+ identical lines means the writer is burning cycles on
   the same decision over and over.

2. **What fraction of the recent window is repetitive?**
   Even if the exact text varies slightly, the same *shape* of message
   appearing 90% of the time signals stagnation.

Public API
----------

.. code-block:: python

    from iamai.history_repetition import (
        longest_identical_run,
        repetition_ratio,
        analyse,
        HistoryRepetitionReport,
    )

    report = analyse("notes/history.md")
    print(report.longest_run)      # int
    print(report.repetition_pct)   # float 0–100
    print(report.verdict)          # "healthy" | "repeating" | "stuck"

Design
------

- Pure functions over a list of stripped lines — no filesystem access
  in the core logic.  The ``analyse()`` convenience wrapper reads the
  file.
- "Identical" means exact string match after stripping whitespace.
- "Repetitive" is measured via a sliding-window dedup ratio: in any
  window of W consecutive lines, what fraction are duplicates of an
  earlier line *within the same window*?
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

HISTORY_PATH = Path("notes/history.md")
DEFAULT_WINDOW = 50

# Pattern to strip leading stroke-seq markers like "- stroke 35012: "
# so that structurally identical entries compare as equal.
_STROKE_PREFIX_RE = re.compile(r"^-?\s*stroke\s+\d+\s*:\s*")
# Pattern to normalise module/file names inside backticks so that
# "parse_kv.py" and "retry.py" compare as the same placeholder.
_BACKTICK_RE = re.compile(r"`[^`]+`")


# ---------------------------------------------------------------------------
# data class
# ---------------------------------------------------------------------------

@dataclass
class HistoryRepetitionReport:
    """Summary of repetition analysis on a history log."""

    total_lines: int = 0
    longest_run: int = 0
    longest_run_text: str = ""
    repetition_pct: float = 0.0
    window_size: int = DEFAULT_WINDOW
    verdict: str = "healthy"

    def to_dict(self) -> dict:
        return {
            "total_lines": self.total_lines,
            "longest_run": self.longest_run,
            "longest_run_text": self.longest_run_text[:120],
            "repetition_pct": round(self.repetition_pct, 1),
            "window_size": self.window_size,
            "verdict": self.verdict,
        }


# ---------------------------------------------------------------------------
# normalisation
# ---------------------------------------------------------------------------

def normalize_line(line: str) -> str:
    """Strip variable parts (stroke numbers, module names) for comparison.

    >>> normalize_line("- stroke 35012: `parse_kv.py` is already in the pool of 9 modules")
    'X is already in the pool of 9 modules'
    >>> normalize_line("plain text without markers")
    'plain text without markers'
    """
    s = _STROKE_PREFIX_RE.sub("", line)
    s = _BACKTICK_RE.sub("X", s)
    return s.strip()


# ---------------------------------------------------------------------------
# core functions (pure, no I/O)
# ---------------------------------------------------------------------------

def longest_identical_run(lines: Sequence[str]) -> tuple[int, str]:
    """Return (length, text) of the longest consecutive run of identical lines.

    >>> longest_identical_run(["a", "a", "a", "b", "b"])
    (3, 'a')
    >>> longest_identical_run([])
    (0, '')
    >>> longest_identical_run(["x"])
    (1, 'x')
    """
    if not lines:
        return 0, ""

    best_len = 1
    best_text = lines[0]
    cur_len = 1
    cur_text = lines[0]

    for line in lines[1:]:
        if line == cur_text:
            cur_len += 1
        else:
            if cur_len > best_len:
                best_len = cur_len
                best_text = cur_text
            cur_len = 1
            cur_text = line

    # check the tail
    if cur_len > best_len:
        best_len = cur_len
        best_text = cur_text

    return best_len, best_text


def repetition_ratio(
    lines: Sequence[str],
    window: int = DEFAULT_WINDOW,
) -> float:
    """Fraction of lines that are duplicates within a sliding window.

    Returns a float in [0.0, 1.0].  0.0 means every line in every
    window is unique; 1.0 means every line is a repeat.

    The window slides one line at a time.  For each window position,
    we count lines that already appeared *earlier in that window*.
    The ratio is averaged across all window positions.

    >>> repetition_ratio(["a", "b", "c", "d"], window=4)
    0.0
    >>> repetition_ratio(["a", "a", "a", "a"], window=4)
    0.75
    """
    if len(lines) < 2:
        return 0.0

    w = min(window, len(lines))
    ratios: list[float] = []

    for start in range(len(lines) - w + 1):
        chunk = lines[start : start + w]
        seen: set[str] = set()
        dupes = 0
        for item in chunk:
            if item in seen:
                dupes += 1
            else:
                seen.add(item)
        ratios.append(dupes / w)

    return sum(ratios) / len(ratios)


def classify(repetition_pct: float, longest_run: int) -> str:
    """Map metrics to a verdict string.

    Thresholds (empirically chosen from this repo's history):

    =========  ====================  ============================
    verdict    repetition_pct        longest_run
    =========  ====================  ============================
    healthy    < 30%                 any
    repeating  30–69%                or longest_run >= 10
    stuck      >= 70%                or longest_run >= 50
    =========  ====================  ============================
    """
    if repetition_pct >= 70.0 or longest_run >= 50:
        return "stuck"
    if repetition_pct >= 30.0 or longest_run >= 10:
        return "repeating"
    return "healthy"


# ---------------------------------------------------------------------------
# convenience wrapper (does I/O)
# ---------------------------------------------------------------------------

def _read_history_lines(path: Path) -> list[str]:
    """Read history.md and return non-blank, stripped lines."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip()]


def analyse(
    path: str | Path | None = None,
    window: int = DEFAULT_WINDOW,
) -> HistoryRepetitionReport:
    """Read the history file and return a repetition report.

    Both exact and normalised comparisons are used:

    - ``longest_run`` is measured on the **normalised** lines so that
      entries differing only in stroke number or module name are still
      counted as consecutive repeats.
    - ``repetition_pct`` is measured on the **normalised** lines to
      catch structural repetition (same template, different numbers).
    """
    p = Path(path) if path else HISTORY_PATH
    raw_lines = _read_history_lines(p)

    if not raw_lines:
        return HistoryRepetitionReport(window_size=window)

    norm_lines = [normalize_line(line) for line in raw_lines]

    run_len, run_text = longest_identical_run(norm_lines)
    rep_pct = repetition_ratio(norm_lines, window=window) * 100.0
    verdict = classify(rep_pct, run_len)

    return HistoryRepetitionReport(
        total_lines=len(raw_lines),
        longest_run=run_len,
        longest_run_text=run_text,
        repetition_pct=rep_pct,
        window_size=window,
        verdict=verdict,
    )
