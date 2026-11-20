#!/usr/bin/env python3
"""stroke_jsonl_integrity.py — validate structural integrity of data/strokes.jsonl.

Checks:
  1. Every line is valid JSON
  2. Required fields (seq, at, kind, text) are present
  3. Sequence numbers are strictly increasing (no duplicates, no regressions)
  4. Timestamps are non-decreasing (a stroke should not predate its predecessor)
  5. No duplicate (seq, kind) tuples

Exit codes:
  0 — clean
  1 — warnings only (ordering drift within tolerance)
  2 — errors found (malformed lines, missing fields, duplicates)
  3 — cannot read file

Usage:
    python3 tools/stroke_jsonl_integrity.py
    python3 tools/stroke_jsonl_integrity.py --repo /path/to/IamAI
    python3 tools/stroke_jsonl_integrity.py --tail 500     # only check last N lines
    python3 tools/stroke_jsonl_integrity.py --json          # output JSON summary
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def find_repo(start: Path | None = None) -> Path:
    p = start or Path.cwd()
    for parent in [p, *p.parents]:
        if (parent / "data" / "strokes.jsonl").exists():
            return parent
    return p


REQUIRED_FIELDS = {"seq", "at", "kind", "text"}
TIMESTAMP_DRIFT_TOLERANCE_S = 300  # 5 minutes


def validate(lines: list[str], *, offset: int = 0) -> dict:
    """Validate a list of JSONL lines and return a report dict."""
    errors: list[dict] = []
    warnings: list[dict] = []
    seen_seqs: set[int] = set()
    prev_seq: int | None = None
    prev_ts: datetime | None = None
    seen_pairs: set[tuple[int, str]] = set()
    valid = 0

    for i, raw in enumerate(lines):
        lineno = offset + i + 1
        stripped = raw.strip()
        if not stripped:
            continue

        # 1. JSON parse
        try:
            rec = json.loads(stripped)
        except json.JSONDecodeError as exc:
            errors.append({"line": lineno, "issue": "bad_json", "detail": str(exc)})
            continue

        # 2. required fields
        missing = REQUIRED_FIELDS - set(rec.keys())
        if missing:
            errors.append({"line": lineno, "issue": "missing_fields", "detail": sorted(missing)})
            continue

        seq = rec["seq"]
        kind = rec["kind"]

        # 3. sequence ordering
        if seq in seen_seqs:
            errors.append({"line": lineno, "issue": "duplicate_seq", "detail": seq})
        else:
            seen_seqs.add(seq)

        if prev_seq is not None and seq < prev_seq:
            errors.append({
                "line": lineno,
                "issue": "seq_regression",
                "detail": f"seq {seq} after {prev_seq}",
            })

        # 4. timestamp ordering
        try:
            ts = datetime.fromisoformat(rec["at"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            errors.append({"line": lineno, "issue": "bad_timestamp", "detail": rec["at"]})
            ts = None

        if ts and prev_ts:
            delta_s = (prev_ts - ts).total_seconds()
            if delta_s > TIMESTAMP_DRIFT_TOLERANCE_S:
                errors.append({
                    "line": lineno,
                    "issue": "timestamp_regression",
                    "detail": f"{rec['at']} is {delta_s:.0f}s before predecessor",
                })
            elif delta_s > 0:
                warnings.append({
                    "line": lineno,
                    "issue": "timestamp_drift",
                    "detail": f"{delta_s:.0f}s drift (within tolerance)",
                })

        # 5. duplicate (seq, kind) pair
        pair = (seq, kind)
        if pair in seen_pairs:
            errors.append({"line": lineno, "issue": "duplicate_pair", "detail": list(pair)})
        seen_pairs.add(pair)

        prev_seq = seq
        if ts:
            prev_ts = ts
        valid += 1

    return {
        "total_lines": len(lines),
        "valid": valid,
        "errors": len(errors),
        "warnings": len(warnings),
        "error_details": errors[:50],
        "warning_details": warnings[:50],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, default=None)
    ap.add_argument("--tail", type=int, default=0, help="only validate last N lines (0=all)")
    ap.add_argument("--json", action="store_true", dest="json_out", help="emit JSON summary")
    args = ap.parse_args()

    repo = find_repo(args.repo)
    path = repo / "data" / "strokes.jsonl"
    if not path.exists():
        print(f"strokes.jsonl not found at {path}", file=sys.stderr)
        return 3

    lines = path.read_text(encoding="utf-8").splitlines()
    offset = 0
    if args.tail and args.tail < len(lines):
        offset = len(lines) - args.tail
        lines = lines[-args.tail:]

    report = validate(lines, offset=offset)
    report["file"] = str(path)
    report["checked_from_line"] = offset + 1

    if args.json_out:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        status = "CLEAN" if report["errors"] == 0 and report["warnings"] == 0 else \
                 "WARN" if report["errors"] == 0 else "ERROR"
        print(f"[{status}] {report['valid']}/{report['total_lines']} valid lines "
              f"({report['errors']} errors, {report['warnings']} warnings)")
        for e in report["error_details"][:10]:
            print(f"  ERROR line {e['line']}: {e['issue']} — {e['detail']}")
        for w in report["warning_details"][:10]:
            print(f"  WARN  line {w['line']}: {w['issue']} — {w['detail']}")

    if report["errors"]:
        return 2
    if report["warnings"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
