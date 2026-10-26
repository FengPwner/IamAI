"""edit_thrash_detector — detect when the writer loops on the same files.

An automated writer that keeps editing the same three files over and over
is not making progress; it is *thrashing*.  This happens when the model
gets stuck in a local pattern — rewriting a paragraph, tweaking a metric
label, touching the same note every stroke.

This module answers two questions for the caretaker:

  1. **Which files are being over-edited?**
  2. **How severe is the thrashing right now?**

Thrash detection uses a sliding time window.  Within that window, every
file that was touched more than ``hot_threshold`` times is flagged as
*hot*.  The thrash score is:

    score = (hot_edits / total_edits) × 100

where ``hot_edits`` is the sum of edit counts for hot files and
``total_edits`` is every edit in the window.  When the window is empty
(no recent strokes) the score is 0 — absence of activity is not thrashing.

Severity levels:

    NONE       score == 0       — no recent edits, nothing to flag
    LOW        0 < score < 25   — healthy editing spread
    MODERATE   25 ≤ score < 50  — some concentration, watch it
    HIGH       50 ≤ score < 75  — clear loop, writer may be stuck
    SEVERE     score ≥ 75       — almost all edits on the same files

Remediation hints are printed alongside the score so the caretaker can
act: pause the writer, clear the writer's short-term context, or rotate
the topic pool.

Usage::

    from iamai.edit_thrash_detector import detect_thrash, ThrashReport

    report = detect_thrash(window_minutes=30, hot_threshold=3)
    print(report)
    # ThrashReport(score=42.5, severity=MODERATE, hot_files=['notes/limits.md'])

Design notes:

- Reads only ``data/strokes.jsonl`` — no git history needed.
- Streaming-safe: the function re-reads the file each call, so it
  reflects the latest state even while the writer is running.
- Zero external dependencies beyond the standard library.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import List, Optional


REPO = Path(__file__).resolve().parent.parent
STROKES_FILE = REPO / "data" / "strokes.jsonl"


class ThrashSeverity(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"


@dataclass
class ThrashReport:
    """Snapshot of editing concentration in a time window."""

    timestamp: str
    window_minutes: int
    hot_threshold: int
    total_edits: int
    hot_edits: int
    score: float
    severity: str
    hot_files: List[str] = field(default_factory=list)
    unique_files: int = 0
    top_file: str = ""
    top_file_edits: int = 0

    def __str__(self) -> str:
        if self.total_edits == 0:
            return (
                f"thrash[{self.window_minutes}m]: no edits in window "
                f"→ score=0 NONE"
            )
        return (
            f"thrash[{self.window_minutes}m]: score={self.score:.1f} "
            f"{self.severity}  hot={self.hot_files}  "
            f"top={self.top_file}({self.top_file_edits}×)  "
            f"unique_files={self.unique_files}  total={self.total_edits}"
        )


# ---------------------------------------------------------------------------
# core logic
# ---------------------------------------------------------------------------


def _parse_ts(raw: str) -> datetime:
    """Parse an ISO timestamp, tolerating Z and offset formats."""
    raw = raw.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw)


def _load_strokes_in_window(
    strokes_path: Path,
    cutoff: datetime,
) -> List[str]:
    """Return file paths for every stroke newer than *cutoff*.

    Each line in strokes.jsonl is a JSON object with at least ``ts`` and
    ``path`` (or ``file``) keys.  Malformed lines are silently skipped —
    the detector should never crash on a half-written log entry.
    """
    if not strokes_path.exists():
        return []

    paths: List[str] = []
    with strokes_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts_raw = obj.get("ts") or obj.get("timestamp") or ""
            if not ts_raw:
                continue
            try:
                ts = _parse_ts(ts_raw)
            except (ValueError, TypeError):
                continue
            if ts < cutoff:
                continue

            # The path field is called "path" in newer strokes, "file"
            # in older ones.  Fall back to empty string if neither exists.
            fpath = obj.get("path") or obj.get("file") or ""
            if fpath:
                paths.append(fpath)

    return paths


def classify_severity(score: float) -> ThrashSeverity:
    """Map a 0–100 thrash score to a severity bucket."""
    if score == 0:
        return ThrashSeverity.NONE
    if score < 25:
        return ThrashSeverity.LOW
    if score < 50:
        return ThrashSeverity.MODERATE
    if score < 75:
        return ThrashSeverity.HIGH
    return ThrashSeverity.SEVERE


def detect_thrash(
    window_minutes: int = 30,
    hot_threshold: int = 3,
    strokes_path: Optional[Path] = None,
) -> ThrashReport:
    """Analyse recent strokes and return a thrash report.

    Parameters
    ----------
    window_minutes:
        How far back to look (default 30 minutes).
    hot_threshold:
        A file edited this many times or more within the window is *hot*.
    strokes_path:
        Override the default strokes file location (for testing).
    """
    if strokes_path is None:
        strokes_path = STROKES_FILE

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=window_minutes)
    file_paths = _load_strokes_in_window(strokes_path, cutoff)

    if not file_paths:
        return ThrashReport(
            timestamp=now.isoformat(),
            window_minutes=window_minutes,
            hot_threshold=hot_threshold,
            total_edits=0,
            hot_edits=0,
            score=0.0,
            severity=ThrashSeverity.NONE.value,
            hot_files=[],
            unique_files=0,
            top_file="",
            top_file_edits=0,
        )

    counts = Counter(file_paths)
    total_edits = len(file_paths)
    unique_files = len(counts)

    hot_files = sorted(
        [f for f, c in counts.items() if c >= hot_threshold],
        key=lambda f: counts[f],
        reverse=True,
    )
    hot_edits = sum(counts[f] for f in hot_files)

    score = (hot_edits / total_edits) * 100 if total_edits > 0 else 0.0
    severity = classify_severity(score)

    top_file, top_count = counts.most_common(1)[0]

    return ThrashReport(
        timestamp=now.isoformat(),
        window_minutes=window_minutes,
        hot_threshold=hot_threshold,
        total_edits=total_edits,
        hot_edits=hot_edits,
        score=round(score, 1),
        severity=severity.value,
        hot_files=hot_files,
        unique_files=unique_files,
        top_file=top_file,
        top_file_edits=top_count,
    )


def remediation_hint(severity: str) -> str:
    """Return a one-line action suggestion for the given severity."""
    hints = {
        ThrashSeverity.NONE.value: "no action needed",
        ThrashSeverity.LOW.value: "healthy editing; continue monitoring",
        ThrashSeverity.MODERATE.value: "watch next cycle; consider rotating topic pool",
        ThrashSeverity.HIGH.value: "pause writer briefly; clear short-term context cache",
        ThrashSeverity.SEVERE.value: "stop writer; inspect context window for loop; reset topic",
    }
    return hints.get(severity, "unknown severity — investigate manually")


def format_report(report: ThrashReport) -> str:
    """Format a ThrashReport as a multi-line human-readable string."""
    lines = [
        f"=== edit thrash report ===",
        f"window:     {report.window_minutes} minutes",
        f"threshold:  {report.hot_threshold} edits",
        f"total edits: {report.total_edits}",
        f"unique files: {report.unique_files}",
        f"hot files:  {report.hot_files}",
        f"top file:   {report.top_file} ({report.top_file_edits}×)",
        f"score:      {report.score:.1f} / 100",
        f"severity:   {report.severity}",
        f"hint:       {remediation_hint(report.severity)}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="detect editing thrash in the writer's recent strokes"
    )
    parser.add_argument(
        "--window", type=int, default=30, help="look-back window in minutes (default 30)"
    )
    parser.add_argument(
        "--threshold", type=int, default=3, help="edits to flag a file as hot (default 3)"
    )
    parser.add_argument(
        "--json", action="store_true", help="output JSON instead of text"
    )
    args = parser.parse_args()

    report = detect_thrash(window_minutes=args.window, hot_threshold=args.threshold)

    if args.json:
        print(json.dumps(asdict(report), indent=2, ensure_ascii=False))
    else:
        print(format_report(report))


if __name__ == "__main__":
    main()
