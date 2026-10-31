#!/usr/bin/env python3
"""content_stall_detector.py — detect when writer output becomes repetitive.

The writer loop should produce diverse strokes. When the same content
pattern repeats across many consecutive strokes (e.g. the same "already
in the pool" message cycling through modules), the writer is stalled —
producing output but no new information. This is distinct from a process
stall (no output at all); it's a *content* stall.

Strategy:
  1. Read the last N lines from a target file (e.g. notes/history.md).
  2. Extract the "payload" portion of each line (after the stroke marker).
  3. Compute a repetition ratio: how many of the last N lines share the
     same core message template.
  4. If the ratio exceeds a threshold, flag as stalled.

Detection methods:
  - **exact_repeat**: Count lines with identical payload text.
  - **template_repeat**: Strip variable parts (numbers, module names)
    and count lines with the same template.
  - **unique_ratio**: Count unique payloads / total lines. Low = stall.

Reports:
  - "healthy"    : diverse content, unique_ratio > threshold
  - "stall"      : repetitive content detected
  - "insufficient": not enough data to judge

Usage:
    python3 tools/content_stall_detector.py
    python3 tools/content_stall_detector.py --file notes/history.md --window 20
    python3 tools/content_stall_detector.py --threshold 0.3 --json

Exit codes:
    0 — healthy (no stall detected)
    1 — stall detected
    2 — insufficient data or error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List


@dataclass
class StallReport:
    """Result of content stall analysis."""
    file: str
    window: int
    lines_read: int
    unique_payloads: int
    unique_ratio: float
    top_template: str
    top_template_count: int
    state: str  # "healthy", "stall", "insufficient"
    threshold: float

    def to_dict(self) -> dict:
        return asdict(self)


def read_tail(filepath: Path, n: int = 20) -> List[str]:
    """Read the last n non-empty lines from a file."""
    if not filepath.exists():
        return []
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except (OSError, IOError):
        return []
    lines = [l for l in text.splitlines() if l.strip()]
    return lines[-n:]


def extract_payload(line: str) -> str:
    """Extract the content portion of a stroke line.

    Handles formats like:
      - stroke 12345: `some content here`
      - ## stroke 211 · 2026-10-31 09:56
      - `2026-10-31T08:02:07+00:00` stroke 35629: content here
      - - stroke 35621: `module.py` is already in the pool
    """
    line = line.strip()
    # Strip leading list markers (-, *, +)
    line = re.sub(r"^[-*+]\s+", "", line)
    # Strip timestamp prefix (backtick-wrapped ISO-like timestamp at start)
    line = re.sub(r"^`\d{4}-\d{2}-\d{2}[^`]*`\s*", "", line)
    # Strip markdown header + stroke number prefix
    # Handles: "stroke 12345: ...", "## stroke 211 · ..."
    line = re.sub(r"^#{0,6}\s*stroke\s+\d+\s*[:·]\s*", "", line)
    # Remove all backticks (used for inline code in stroke content)
    line = line.replace("`", "").strip()
    return line


def normalize_for_template(text: str) -> str:
    """Strip variable parts to get the template of a message.

    Replaces numbers, module names in backticks, and dates with placeholders.
    """
    # Replace backtick-quoted identifiers (module names, file names)
    text = re.sub(r"`[^`]+`", "<MOD>", text)
    # Replace numbers
    text = re.sub(r"\b\d+\b", "<N>", text)
    # Replace dates/timestamps
    text = re.sub(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\s]*", "<TS>", text)
    return text


def detect_stall(
    filepath: Path,
    window: int = 20,
    threshold: float = 0.3,
) -> StallReport:
    """Analyze a file for content stalls.

    Args:
        filepath: Path to the file to analyze.
        window: Number of recent lines to examine.
        threshold: Minimum unique_ratio to be considered healthy.

    Returns:
        StallReport with analysis results.
    """
    lines = read_tail(filepath, window)
    if len(lines) < 3:
        return StallReport(
            file=str(filepath),
            window=window,
            lines_read=len(lines),
            unique_payloads=0,
            unique_ratio=0.0,
            top_template="",
            top_template_count=0,
            state="insufficient",
            threshold=threshold,
        )

    payloads = [extract_payload(line) for line in lines]
    unique = set(payloads)
    unique_ratio = len(unique) / len(payloads)

    # Find the most common template
    templates = [normalize_for_template(p) for p in payloads]
    template_counts: dict[str, int] = {}
    for t in templates:
        template_counts[t] = template_counts.get(t, 0) + 1

    top_template = max(template_counts, key=template_counts.get)
    top_count = template_counts[top_template]
    top_template_ratio = top_count / len(templates)

    # Determine stall state using two signals:
    # 1. Low unique_ratio → exact repetition (stall)
    # 2. High template ratio + low unique count → structural repetition (stall)
    #    (e.g. same message with only module name changing)
    # Template alone is unreliable since diverse content often shares structure.
    state = "healthy"
    if unique_ratio < threshold:
        state = "stall"
    elif top_template_ratio > 0.8 and len(unique) <= 5:
        state = "stall"

    return StallReport(
        file=str(filepath),
        window=window,
        lines_read=len(lines),
        unique_payloads=len(unique),
        unique_ratio=round(unique_ratio, 4),
        top_template=top_template,
        top_template_count=top_count,
        state=state,
        threshold=threshold,
    )


def format_report(report: StallReport) -> str:
    """Format a StallReport as a human-readable string."""
    if report.state == "insufficient":
        return f"{report.file}: insufficient data ({report.lines_read} lines, need ≥3)"

    lines = [
        f"content stall check: {report.file}",
        f"  window: {report.lines_read}/{report.window} lines",
        f"  unique payloads: {report.unique_payloads}/{report.lines_read}",
        f"  unique ratio: {report.unique_ratio:.2%} (threshold: {report.threshold:.0%})",
        f"  top template ({report.top_template_count}×): {report.top_template[:80]}",
        f"  state: {report.state}",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Detect content stalls in writer output files."
    )
    parser.add_argument(
        "--file", "-f",
        default="notes/history.md",
        help="File to check (default: notes/history.md)",
    )
    parser.add_argument(
        "--window", "-w",
        type=int, default=20,
        help="Number of recent lines to examine (default: 20)",
    )
    parser.add_argument(
        "--threshold", "-t",
        type=float, default=0.3,
        help="Minimum unique ratio for healthy (default: 0.3)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    # Resolve path relative to repo root
    repo_root = Path(__file__).resolve().parent.parent
    filepath = repo_root / args.file if not Path(args.file).is_absolute() else Path(args.file)

    report = detect_stall(filepath, window=args.window, threshold=args.threshold)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_report(report))

    sys.exit({"healthy": 0, "stall": 1, "insufficient": 2}[report.state])


if __name__ == "__main__":
    main()
