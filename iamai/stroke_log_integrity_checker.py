"""stroke_log_integrity_checker — validate structural integrity of strokes.jsonl.

The stroke log is the single source of truth for this repository's
creative output.  It is append-only, written by multiple agents,
and survives frequent process restarts.  Corruption — out-of-order
sequences, non-monotonic timestamps, malformed JSON, duplicate
entries — undermines every downstream analysis.

This module provides a fast, non-destructive integrity check that
reports issues without modifying the log.

Checks performed:

1. **JSON validity** — every non-blank line must parse as JSON
2. **Required fields** — each stroke must have ``seq`` and ``at``
3. **Sequential seq** — seq numbers must be strictly increasing
4. **Monotonic timestamps** — ``at`` values must be non-decreasing
5. **No duplicates** — no two strokes may share the same seq
6. **Valid kind** — ``kind`` must be one of the known stroke types
7. **Timestamp parseable** — ``at`` must be a valid ISO-8601 string

Usage::

    from iamai.stroke_log_integrity_checker import IntegrityChecker

    checker = IntegrityChecker()
    report = checker.check("data/strokes.jsonl")
    print(report.is_valid)      # bool
    print(report.issue_count)   # int
    for issue in report.issues:
        print(issue.line, issue.kind, issue.message)

Written by Qwen during caretaker visit 706, 2026-11-18.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Set


# ─── Known stroke kinds ─────────────────────────────────────────────

VALID_KINDS: Set[str] = {
    "devlog", "metrics", "snippet", "thought", "garden", "note",
}


# ─── Data classes ───────────────────────────────────────────────────


@dataclass(frozen=True)
class IntegrityIssue:
    """A single integrity violation found in the stroke log."""

    line: int  # 1-based line number
    kind: str  # issue type: "json", "missing_field", "seq_order",
               #   "time_order", "duplicate", "invalid_kind",
               #   "invalid_timestamp", "empty_seq"
    message: str
    severity: str = "error"  # "error" or "warning"


@dataclass(frozen=True)
class IntegrityReport:
    """Result of an integrity check."""

    path: str
    total_lines: int
    valid_strokes: int
    issues: List[IntegrityIssue] = field(default_factory=list)

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def is_valid(self) -> bool:
        return self.issue_count == 0

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def issues_of_kind(self, kind: str) -> List[IntegrityIssue]:
        return [i for i in self.issues if i.kind == kind]


# ─── Checker ────────────────────────────────────────────────────────


class IntegrityChecker:
    """Validate the structural integrity of a strokes JSONL file.

    Parameters
    ----------
    valid_kinds : set of str, optional
        Accepted values for the ``kind`` field.  Defaults to
        ``VALID_KINDS``.  Pass a custom set to support extensions.
    strict_timestamps : bool
        If True (default), timestamps must include timezone info.
        If False, naive timestamps are accepted with a warning.
    allow_gaps : bool
        If True (default), gaps in seq numbers are allowed (just
        logged as warnings).  If False, any gap is an error.
    """

    def __init__(
        self,
        valid_kinds: Optional[Set[str]] = None,
        strict_timestamps: bool = True,
        allow_gaps: bool = True,
    ) -> None:
        self.valid_kinds = valid_kinds or VALID_KINDS
        self.strict_timestamps = strict_timestamps
        self.allow_gaps = allow_gaps

    def check(self, path: str) -> IntegrityReport:
        """Check the integrity of a strokes JSONL file."""
        return self.check_lines(self._read_lines(path), path)

    def check_text(self, text: str, path: str = "<text>") -> IntegrityReport:
        """Check integrity from a string (useful for testing)."""
        lines = text.split("\n")
        return self.check_lines(lines, path)

    def check_lines(
        self, lines: Sequence[str], path: str = "<lines>"
    ) -> IntegrityReport:
        """Check integrity from a sequence of lines."""
        issues: List[IntegrityIssue] = []
        valid_count = 0
        prev_seq: Optional[int] = None
        prev_ts: Optional[datetime] = None
        seen_seqs: Set[int] = set()
        total_lines = 0

        for line_idx, raw_line in enumerate(lines):
            line_num = line_idx + 1
            stripped = raw_line.strip()

            # Skip blank lines
            if not stripped:
                continue

            total_lines += 1

            # 1. JSON validity
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as e:
                issues.append(IntegrityIssue(
                    line=line_num,
                    kind="json",
                    message=f"Invalid JSON: {e}",
                    severity="error",
                ))
                continue

            if not isinstance(obj, dict):
                issues.append(IntegrityIssue(
                    line=line_num,
                    kind="json",
                    message=f"Expected JSON object, got {type(obj).__name__}",
                    severity="error",
                ))
                continue

            # 2. Required fields
            if "seq" not in obj:
                issues.append(IntegrityIssue(
                    line=line_num,
                    kind="missing_field",
                    message="Missing required field: seq",
                    severity="error",
                ))
                continue

            if "at" not in obj:
                issues.append(IntegrityIssue(
                    line=line_num,
                    kind="missing_field",
                    message="Missing required field: at",
                    severity="error",
                ))
                continue

            seq = obj["seq"]
            at = obj["at"]

            # seq must be numeric
            if not isinstance(seq, (int, float)):
                issues.append(IntegrityIssue(
                    line=line_num,
                    kind="empty_seq",
                    message=f"seq is not numeric: {seq!r}",
                    severity="error",
                ))
                continue

            seq = int(seq)

            # 3. Duplicate seq
            if seq in seen_seqs:
                issues.append(IntegrityIssue(
                    line=line_num,
                    kind="duplicate",
                    message=f"Duplicate seq: {seq}",
                    severity="error",
                ))
            seen_seqs.add(seq)

            # 4. Sequential seq (strictly increasing)
            if prev_seq is not None:
                if seq <= prev_seq:
                    issues.append(IntegrityIssue(
                        line=line_num,
                        kind="seq_order",
                        message=(
                            f"Seq not increasing: {seq} after {prev_seq}"
                        ),
                        severity="error",
                    ))
                elif seq != prev_seq + 1:
                    sev = "warning" if self.allow_gaps else "error"
                    issues.append(IntegrityIssue(
                        line=line_num,
                        kind="seq_order",
                        message=f"Seq gap: {prev_seq} → {seq} "
                                f"(missing {seq - prev_seq - 1})",
                        severity=sev,
                    ))
            prev_seq = seq

            # 5. Timestamp parseable
            ts = self._parse_timestamp(at)
            if ts is None:
                issues.append(IntegrityIssue(
                    line=line_num,
                    kind="invalid_timestamp",
                    message=f"Cannot parse timestamp: {at!r}",
                    severity="error",
                ))
                continue

            # Strict timestamp check
            if self.strict_timestamps and ts.tzinfo is None:
                issues.append(IntegrityIssue(
                    line=line_num,
                    kind="invalid_timestamp",
                    message=f"Timestamp missing timezone: {at!r}",
                    severity="warning",
                ))

            # 6. Monotonic timestamps
            if prev_ts is not None and ts < prev_ts:
                issues.append(IntegrityIssue(
                    line=line_num,
                    kind="time_order",
                    message=(
                        f"Timestamp goes backward: {at} "
                        f"after {prev_ts.isoformat()}"
                    ),
                    severity="error",
                ))
            prev_ts = ts

            # 7. Valid kind
            kind = obj.get("kind", "")
            if kind and kind not in self.valid_kinds:
                issues.append(IntegrityIssue(
                    line=line_num,
                    kind="invalid_kind",
                    message=f"Unknown kind: {kind!r}",
                    severity="warning",
                ))

            valid_count += 1

        return IntegrityReport(
            path=path,
            total_lines=total_lines,
            valid_strokes=valid_count,
            issues=issues,
        )

    @staticmethod
    def _parse_timestamp(ts: str) -> Optional[datetime]:
        """Try to parse an ISO-8601 timestamp string."""
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass

        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                return datetime.strptime(ts, fmt)
            except ValueError:
                continue

        return None

    @staticmethod
    def _read_lines(path: str) -> List[str]:
        """Read lines from a file."""
        p = Path(path)
        if not p.exists():
            return []
        return p.read_text(encoding="utf-8").split("\n")


# ─── Quick CLI ──────────────────────────────────────────────────────


def main() -> None:
    """Run integrity check from command line."""
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "data/strokes.jsonl"
    checker = IntegrityChecker()
    report = checker.check(path)

    print(f"Path:    {report.path}")
    print(f"Lines:   {report.total_lines}")
    print(f"Valid:   {report.valid_strokes}")
    print(f"Issues:  {report.issue_count} "
          f"({report.error_count} errors, {report.warning_count} warnings)")

    if report.is_valid:
        print("✓ Log integrity OK")
    else:
        print("✗ Issues found:")
        for issue in report.issues[:20]:
            print(f"  line {issue.line}: [{issue.severity}] "
                  f"{issue.kind}: {issue.message}")
        if report.issue_count > 20:
            print(f"  ... and {report.issue_count - 20} more")

    sys.exit(0 if report.is_valid else 1)


if __name__ == "__main__":
    main()
