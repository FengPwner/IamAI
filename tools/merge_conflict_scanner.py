#!/usr/bin/env python3
"""merge_conflict_scanner.py — find unresolved merge conflict markers.

After a pull, merge, or rebase, conflict markers (<<<<<<<, =======, >>>>>>>)
can be left in files if the resolution step is skipped or incomplete.
This tool scans tracked files and reports any markers found, so the
caretaker can resolve them before the next commit.

Usage:
    python3 tools/merge_conflict_scanner.py
    python3 tools/merge_conflict_scanner.py --json
    python3 tools/merge_conflict_scanner.py --paths src/ tools/

Exit codes:
    0 — no conflict markers found
    1 — conflict markers detected
    2 — error (not a git repo, etc.)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent

# Conflict marker patterns (git default style).
MARKER_OURS = "<<<<<<< "
MARKER_SEP = "======="
MARKER_THEIRS = ">>>>>>> "


@dataclass
class ConflictHit:
    """A single conflict marker found in a file."""
    file: str
    line: int
    marker: str          # 'ours', 'separator', or 'theirs'
    content: str         # the full line text


@dataclass
class ScanResult:
    """Summary of a conflict scan."""
    scanned: int = 0
    conflicts: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return len(self.conflicts) == 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["clean"] = self.clean
        return d


def _git_tracked_files(repo: Path, paths: Optional[list[str]] = None) -> list[str]:
    """Return list of tracked file paths relative to repo root."""
    cmd = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
    if paths:
        cmd.extend(paths)
    try:
        proc = subprocess.run(
            cmd, cwd=str(repo), capture_output=True, text=True, timeout=15
        )
        if proc.returncode != 0:
            return []
        return [
            f for f in proc.stdout.strip().splitlines()
            if f and not f.startswith(".git/")
        ]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def _is_binary(filepath: Path) -> bool:
    """Quick binary check: read first 8192 bytes and look for NUL."""
    try:
        with open(filepath, "rb") as fh:
            chunk = fh.read(8192)
            return b"\x00" in chunk
    except OSError:
        return True


def scan_file(filepath: Path, rel_path: str) -> list[ConflictHit]:
    """Scan a single file for conflict markers."""
    hits: list[ConflictHit] = []
    if _is_binary(filepath):
        return hits
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            for lineno, line in enumerate(fh, start=1):
                stripped = line.rstrip("\n\r")
                if stripped.startswith(MARKER_OURS):
                    hits.append(ConflictHit(rel_path, lineno, "ours", stripped))
                elif stripped == MARKER_SEP:
                    hits.append(ConflictHit(rel_path, lineno, "separator", stripped))
                elif stripped.startswith(MARKER_THEIRS):
                    hits.append(ConflictHit(rel_path, lineno, "theirs", stripped))
    except OSError:
        pass
    return hits


def scan_repo(
    repo: Path = REPO,
    paths: Optional[list[str]] = None,
) -> ScanResult:
    """Scan all tracked files in *repo* for conflict markers."""
    result = ScanResult()
    files = _git_tracked_files(repo, paths)
    result.scanned = len(files)
    for rel in files:
        abs_path = repo / rel
        if not abs_path.is_file():
            continue
        hits = scan_file(abs_path, rel)
        if hits:
            result.conflicts.extend([asdict(h) for h in hits])
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Scan for merge conflict markers.")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--paths", nargs="*", default=None, help="limit scan to these paths")
    args = parser.parse_args(argv)

    if not (REPO / ".git").is_dir():
        print(f"error: {REPO} is not a git repository", file=sys.stderr)
        return 2

    result = scan_repo(REPO, args.paths)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"merge_conflict_scanner: scanned {result.scanned} files")
        if result.clean:
            print("  clean — no conflict markers found")
        else:
            print(f"  found {len(result.conflicts)} conflict marker(s):")
            for hit in result.conflicts:
                print(f"    {hit['file']}:{hit['line']}  [{hit['marker']}]  {hit['content'][:72]}")

    return 0 if result.clean else 1


if __name__ == "__main__":
    sys.exit(main())
