#!/usr/bin/env python3
"""stroke_sequence_check — detect anomalies in DEVLOG stroke numbering.

Scans docs/DEVLOG.md for three classes of sequence anomaly:
  1. Duplicates   — same stroke number appears more than once
  2. Regressions  — a stroke number is lower than its predecessor
  3. Gaps         — expected stroke numbers are missing from the sequence

Usage:
    python3 tools/stroke_sequence_check.py [--repo /path/to/IamAI] [--json]

Exit codes:
    0  clean sequence (no anomalies)
    1  anomalies found
    2  could not read DEVLOG
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Match lines like:
#   - `2026-11-20T01:09:45+00:00` stroke 40753: commit 999: ...
STROKE_RE = re.compile(
    r"-\s*`([^`]+)`\s+stroke\s+(\d+):"
)


def parse_strokes(devlog_path: Path) -> list[dict]:
    """Extract (timestamp, stroke_number) pairs from DEVLOG in file order."""
    entries = []
    with open(devlog_path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            m = STROKE_RE.search(line)
            if m:
                entries.append({
                    "line": lineno,
                    "timestamp": m.group(1),
                    "stroke": int(m.group(2)),
                })
    return entries


def detect_anomalies(entries: list[dict]) -> dict:
    """Classify sequence anomalies in a list of stroke entries.

    Returns a dict with keys: duplicates, regressions, gaps, severity.
    """
    duplicates = []      # (stroke, [lines])
    regressions = []     # (line, stroke, prev_stroke)
    gaps = []            # (prev_stroke, next_stroke, missing_count)

    seen: dict[int, list[int]] = {}  # stroke -> [line numbers]
    prev_stroke = None

    for entry in entries:
        s = entry["stroke"]
        ln = entry["line"]

        # Track duplicates
        seen.setdefault(s, []).append(ln)

        # Check regression against previous entry (in file order)
        if prev_stroke is not None and s < prev_stroke:
            regressions.append({
                "line": ln,
                "stroke": s,
                "prev_stroke": prev_stroke,
                "delta": prev_stroke - s,
            })

        # Check gap (only when current > prev, to avoid double-counting regressions)
        if prev_stroke is not None and s > prev_stroke + 1:
            missing = s - prev_stroke - 1
            gaps.append({
                "after_stroke": prev_stroke,
                "before_stroke": s,
                "missing_count": missing,
            })

        prev_stroke = s

    # Collect only actual duplicates (stroke appearing 2+ times)
    for stroke, lines in seen.items():
        if len(lines) > 1:
            duplicates.append({"stroke": stroke, "count": len(lines), "lines": lines})

    duplicates.sort(key=lambda d: d["stroke"])

    # Severity: 0=clean, 1=duplicates only, 2=regressions, 3=gaps>10
    severity = 0
    if duplicates:
        severity = max(severity, 1)
    if regressions:
        severity = max(severity, 2)
    total_missing = sum(g["missing_count"] for g in gaps)
    if total_missing > 10:
        severity = 3

    return {
        "duplicates": duplicates,
        "regressions": regressions,
        "gaps": gaps,
        "total_entries": len(entries),
        "unique_strokes": len(seen),
        "total_missing_strokes": total_missing,
        "severity": severity,
        "severity_label": ["clean", "duplicates", "regressions", "significant_gaps"][severity],
    }


def print_report(result: dict) -> None:
    """Human-readable report to stdout."""
    print(f"Stroke Sequence Check — {result['total_entries']} entries, "
          f"{result['unique_strokes']} unique strokes")
    print(f"Severity: {result['severity_label']} ({result['severity']})")
    print()

    if not result["duplicates"] and not result["regressions"] and not result["gaps"]:
        print("Sequence is clean. No anomalies detected.")
        return

    if result["duplicates"]:
        print(f"Duplicates ({len(result['duplicates'])} strokes repeated):")
        for d in result["duplicates"][:10]:
            print(f"  stroke {d['stroke']}: {d['count']}x on lines {d['lines']}")
        if len(result["duplicates"]) > 10:
            print(f"  ... and {len(result['duplicates']) - 10} more")
        print()

    if result["regressions"]:
        print(f"Regressions ({len(result['regressions'])} backward jumps):")
        for r in result["regressions"][:10]:
            print(f"  line {r['line']}: stroke {r['stroke']} after {r['prev_stroke']} "
                  f"(delta -{r['delta']})")
        if len(result["regressions"]) > 10:
            print(f"  ... and {len(result['regressions']) - 10} more")
        print()

    if result["gaps"]:
        total = result["total_missing_strokes"]
        print(f"Gaps ({len(result['gaps'])} gaps, {total} strokes missing):")
        for g in sorted(result["gaps"], key=lambda x: -x["missing_count"])[:10]:
            print(f"  {g['after_stroke']} → {g['before_stroke']}: "
                  f"{g['missing_count']} missing")
        if len(result["gaps"]) > 10:
            print(f"  ... and {len(result['gaps']) - 10} more")
        print()


def main():
    parser = argparse.ArgumentParser(description="Check DEVLOG stroke sequence integrity")
    parser.add_argument("--repo", default=None, help="path to IamAI repo root")
    parser.add_argument("--json", action="store_true", help="output JSON instead of text")
    args = parser.parse_args()

    if args.repo:
        repo = Path(args.repo)
    else:
        repo = Path(__file__).resolve().parent.parent

    devlog = repo / "docs" / "DEVLOG.md"
    if not devlog.exists():
        print(f"error: {devlog} not found", file=sys.stderr)
        sys.exit(2)

    entries = parse_strokes(devlog)
    if not entries:
        print(f"warning: no stroke entries found in {devlog}", file=sys.stderr)
        sys.exit(0)

    result = detect_anomalies(entries)

    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        print_report(result)

    sys.exit(1 if result["severity"] > 0 else 0)


if __name__ == "__main__":
    main()
