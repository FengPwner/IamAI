#!/usr/bin/env python3
"""pack_integrity_check.py — verify git pack files are readable and consistent.

Motivated by the 2026-10-31 incident where a corrupted pack file silently
blocked all fetch/pull operations with "cannot pread pack file" errors.
A quick integrity check before the batch committer starts would have caught
this hours earlier.

Checks performed:
  1. Every .pack file has a matching .idx file (and vice versa).
  2. Each pack file is at least 12 bytes (minimum valid pack header).
  3. Pack header magic bytes are correct (\\x50\\x41\\x43\\x4b = "PACK").
  4. Pack version is 2 (the only version git currently writes).
  5. Object count in header is non-negative and fits in 4 bytes.
  6. File size is at least header (12) + trailer (20) = 32 bytes.

Exit codes:
    0 — all packs valid
    1 — at least one pack is corrupt or orphaned
    2 — repo not found or other error

Usage:
    python3 tools/pack_integrity_check.py
    python3 tools/pack_integrity_check.py --json
    python3 tools/pack_integrity_check.py --repo /path/to/repo
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional


PACK_MAGIC = b"\x50\x41\x43\x4b"  # "PACK"
PACK_VERSION = 2
MIN_PACK_SIZE = 32  # 12-byte header + 20-byte SHA-1 trailer


@dataclass
class PackIssue:
    file: str
    issue: str
    detail: str = ""


@dataclass
class PackReport:
    repo: str
    pack_dir: str
    pack_count: int
    issues: List[PackIssue] = field(default_factory=list)
    verdict: str = "healthy"  # "healthy" | "corrupt"

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def find_pack_dir(repo: Path) -> Optional[Path]:
    """Locate .git/objects/pack inside a git repository."""
    git_dir = repo / ".git"
    if git_dir.is_dir():
        pack = git_dir / "objects" / "pack"
        if pack.is_dir():
            return pack
    # bare repo
    pack = repo / "objects" / "pack"
    if pack.is_dir():
        return pack
    return None


def check_pack_pair(pack_dir: Path) -> List[PackIssue]:
    """Check that every .pack has a .idx and vice versa."""
    issues: List[PackIssue] = []
    packs = set(p.stem for p in pack_dir.glob("*.pack"))
    idxs = set(p.stem for p in pack_dir.glob("*.idx"))

    orphan_packs = packs - idxs
    orphan_idxs = idxs - packs

    for name in orphan_packs:
        issues.append(PackIssue(
            file=f"{name}.pack",
            issue="missing_index",
            detail=f"pack file has no matching .idx index"
        ))

    for name in orphan_idxs:
        issues.append(PackIssue(
            file=f"{name}.idx",
            issue="missing_pack",
            detail=f"index file has no matching .pack file"
        ))

    return issues


def check_pack_header(pack_path: Path) -> List[PackIssue]:
    """Validate pack file header: magic, version, object count, minimum size."""
    issues: List[PackIssue] = []
    name = pack_path.name

    try:
        size = pack_path.stat().st_size
    except OSError as e:
        issues.append(PackIssue(file=name, issue="stat_failed", detail=str(e)))
        return issues

    if size < 12:
        issues.append(PackIssue(
            file=name,
            issue="too_small",
            detail=f"file is {size} bytes, minimum valid pack is {MIN_PACK_SIZE} bytes"
        ))
        return issues

    if size < MIN_PACK_SIZE:
        issues.append(PackIssue(
            file=name,
            issue="below_minimum_size",
            detail=f"file is {size} bytes, expected at least {MIN_PACK_SIZE} (header + trailer)"
        ))

    try:
        with open(pack_path, "rb") as f:
            header = f.read(12)
    except OSError as e:
        issues.append(PackIssue(file=name, issue="read_failed", detail=str(e)))
        return issues

    if len(header) < 12:
        issues.append(PackIssue(
            file=name,
            issue="short_read",
            detail=f"expected 12 header bytes, got {len(header)}"
        ))
        return issues

    magic = header[:4]
    if magic != PACK_MAGIC:
        issues.append(PackIssue(
            file=name,
            issue="bad_magic",
            detail=f"expected {PACK_MAGIC!r}, got {magic!r}"
        ))
        return issues

    version = struct.unpack(">I", header[4:8])[0]
    if version != PACK_VERSION:
        issues.append(PackIssue(
            file=name,
            issue="bad_version",
            detail=f"expected version {PACK_VERSION}, got {version}"
        ))

    obj_count = struct.unpack(">I", header[8:12])[0]
    if obj_count == 0:
        issues.append(PackIssue(
            file=name,
            issue="empty_pack",
            detail="pack header claims 0 objects"
        ))

    return issues


def full_check(repo: Path) -> PackReport:
    """Run all pack integrity checks and return a report."""
    pack_dir = find_pack_dir(repo)
    if pack_dir is None:
        return PackReport(
            repo=str(repo),
            pack_dir="",
            pack_count=0,
            issues=[PackIssue(file="", issue="no_pack_dir",
                              detail="no .git/objects/pack found")],
            verdict="corrupt",
        )

    packs = list(pack_dir.glob("*.pack"))
    all_issues: List[PackIssue] = []

    # 1. pair check
    all_issues.extend(check_pack_pair(pack_dir))

    # 2. header check for each pack
    for pack in sorted(packs):
        all_issues.extend(check_pack_header(pack))

    verdict = "healthy" if not all_issues else "corrupt"

    return PackReport(
        repo=str(repo),
        pack_dir=str(pack_dir),
        pack_count=len(packs),
        issues=all_issues,
        verdict=verdict,
    )


def format_report(report: PackReport) -> str:
    """Human-readable summary."""
    lines = [
        f"repo:       {report.repo}",
        f"pack_dir:   {report.pack_dir}",
        f"packs:      {report.pack_count}",
        f"verdict:    {report.verdict}",
    ]
    if report.issues:
        lines.append("issues:")
        for issue in report.issues:
            detail = f" — {issue.detail}" if issue.detail else ""
            lines.append(f"  [{issue.issue}] {issue.file}{detail}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check git pack file integrity")
    parser.add_argument("--repo", default=".", help="path to git repo (default: cwd)")
    parser.add_argument("--json", action="store_true", help="output JSON instead of text")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"error: {repo} is not a directory", file=sys.stderr)
        return 2

    report = full_check(repo)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_report(report))

    return 0 if report.verdict == "healthy" else 1


if __name__ == "__main__":
    sys.exit(main())
