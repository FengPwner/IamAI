#!/usr/bin/env python3
"""commit_signal_to_noise — measure how much of each commit is real content.

``commit_surface_area`` tells you *where* a commit reaches; this module
tells you *what* it carries.  A commit can touch seven files across five
directories and still be 95 % auto-generated boilerplate — state JSON,
append-only log lines, metrics counters.  Signal-to-noise ratio (SNR)
separates the caretaker's prose from the batch committer's bookkeeping.

Signal dimensions
-----------------

====================  =====================================================
metric                meaning
====================  =====================================================
added_lines           total lines added (diff ``+`` lines)
deleted_lines         total lines removed (diff ``-`` lines)
substantive_added     added lines that are *not* boilerplate
boilerplate_added     added lines matching state/log/metrics patterns
boilerplate_ratio     boilerplate / added  (0 when nothing added)
signal_ratio          1 − boilerplate_ratio  (higher = more real content)
signal_files          files containing at least one substantive addition
noise_files           files whose additions are entirely boilerplate
classification        noise | mixed | signal | pure-signal
====================  =====================================================

Classification thresholds
-------------------------

==================  ========  ============================================
classification      range     interpretation
==================  ========  ============================================
noise               0.0–0.2   almost entirely auto-generated bookkeeping
mixed               0.2–0.5   some real content buried in boilerplate
signal              0.5–0.8   mostly substantive additions
pure-signal         0.8–1.0   nearly every line is hand-written content
==================  ========  ============================================

Design choices
--------------

- **Line-level, not file-level.**  A file like ``data/strokes.jsonl``
  adds hundreds of lines per commit but they are all structured JSON
  records — classifying the *file* as noise misses the added test in
  the same commit.  Line-level granularity captures both.

- **Boilerplate patterns are regex-based**, not filename-based.  A
  ``docs/METRICS.md`` line that says ``total_strokes: 401`` is
  boilerplate even though it lives in a "creative" directory.  The
  content, not the path, decides.

- **Empty commits get 0.0** (noise) because a commit that adds nothing
  is by definition all noise — it spent a commit slot on no content.

Usage::

    from iamai.commit_signal_to_noise import analyse_commits

    results = analyse_commits(count=10)
    for r in results:
        print(f"{r['hash'][:8]}  {r['classification']:12s}  "
              f"snr={r['signal_ratio']:.2f}  +{r['added_lines']}")

CLI::

    python3 -m iamai.commit_signal_to_noise              # last 10 commits
    python3 -m iamai.commit_signal_to_noise --count 20   # last 20
    python3 -m iamai.commit_signal_to_noise --json       # machine-readable

Exit codes:
    0  all recent commits are signal or better
    1  at least one mixed commit in the window
    2  more than half the commits are noise
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent

# ── Boilerplate patterns ─────────────────────────────────────────────
#
# These match individual *lines* that are almost certainly auto-generated
# bookkeeping, regardless of which file they appear in.

_BOILERPLATE_PATTERNS: tuple[re.Pattern, ...] = (
    # JSON state records: {"writer": ..., "strokes": 123, ...}
    re.compile(r'^\s*\{".*"(?:writer|strokes|last_stroke|pid|uptime)'),
    # JSONL stroke records: {"ts": ..., "writer": ..., "kind": ...}
    re.compile(r'^\s*\{"ts"\s*:'),
    # Metrics counter lines: total_strokes: 401, commits: 594, etc.
    re.compile(r'^\s*(?:total_strokes|commits|uptime|files_tracked|lines|gaps?|strokes?)\s*[:=]'),
    # Timestamped log entries: [2026-11-10 12:00:00] stroke 401 written
    re.compile(r'^\s*\[\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}'),
    # Devlog/garden auto-append markers: ## stroke NNN
    re.compile(r'^\s*##\s+stroke\s+\d+'),
    # Pure numeric counter increments
    re.compile(r'^\s*\d+\s*$'),
    # Markdown table separator rows: |---|---|
    re.compile(r'^\s*\|[\s\-:|]+\|\s*$'),
    # Auto-generated commit hash references in docs
    re.compile(r'^\s*(?:commit|last_commit|latest)\s*[:=]\s*[0-9a-f]{7,40}'),
)

# Files that are *entirely* boilerplate — every line added is noise.
_PURE_NOISE_FILES = frozenset({
    "data/writer_state.qwen.json",
    "data/writer_state.guoban.json",
    "data/writer_state.kimi.json",
    "data/writer_state.doubao.json",
})


# ── Core helpers ─────────────────────────────────────────────────────

def is_boilerplate_line(line: str) -> bool:
    """Return True if a single added line matches a boilerplate pattern."""
    for pat in _BOILERPLATE_PATTERNS:
        if pat.search(line):
            return True
    return False


def classify_file(path: str) -> str:
    """Return 'noise' if the file is always boilerplate, else 'check'.

    Files in the pure-noise set never contain hand-written prose.
    Everything else needs line-level inspection.
    """
    return "noise" if path in _PURE_NOISE_FILES else "check"


# ── Per-commit analysis ──────────────────────────────────────────────

@dataclass
class CommitSNR:
    """Signal-to-noise analysis for a single commit."""
    commit_hash: str = ""
    added_lines: int = 0
    deleted_lines: int = 0
    substantive_added: int = 0
    boilerplate_added: int = 0
    boilerplate_ratio: float = 0.0
    signal_ratio: float = 0.0
    signal_files: int = 0
    noise_files: int = 0
    classification: str = "noise"
    per_file: list = field(default_factory=list)


def _parse_diff_stat(raw: str) -> dict[str, list[str]]:
    """Parse ``git diff`` output into {filename: [added_lines]}.

    Expects unified diff format.  Only ``+`` lines (excluding the
    ``+++`` header) are collected.
    """
    result: dict[str, list[str]] = {}
    current_file: str | None = None

    for line in raw.split("\n"):
        if line.startswith("+++ b/"):
            current_file = line[6:]
            if current_file not in result:
                result[current_file] = []
        elif line.startswith("+++ "):
            # /dev/null or other non-file header — skip
            current_file = None
        elif line.startswith("+") and not line.startswith("+++") and current_file is not None:
            result[current_file].append(line[1:])  # strip leading '+'

    return result


def _count_deleted(raw: str) -> int:
    """Count ``-`` lines in a diff (excluding ``---`` headers)."""
    count = 0
    for line in raw.split("\n"):
        if line.startswith("-") and not line.startswith("---"):
            count += 1
    return count


def _classify_ratio(signal_ratio: float) -> str:
    """Map signal_ratio to a human-readable classification."""
    if signal_ratio >= 0.8:
        return "pure-signal"
    if signal_ratio >= 0.5:
        return "signal"
    if signal_ratio >= 0.2:
        return "mixed"
    return "noise"


def analyse_commit(commit_hash: str, repo: Path = REPO) -> CommitSNR:
    """Analyse a single commit's signal-to-noise ratio.

    Parameters
    ----------
    commit_hash : str
        Any git reference that resolves to a commit (hash, HEAD~3, etc).
    repo : Path
        Repository root.

    Returns
    -------
    CommitSNR
        Populated dataclass with per-file breakdown.
    """
    snr = CommitSNR(commit_hash=commit_hash)

    # Get the diff for this commit
    try:
        raw_diff = subprocess.run(
            ["git", "diff", f"{commit_hash}~1", commit_hash, "--unified=0"],
            capture_output=True, text=True, cwd=repo, timeout=30,
        ).stdout
    except (subprocess.TimeoutExpired, Exception):
        return snr  # empty → all noise

    if not raw_diff.strip():
        return snr

    file_diffs = _parse_diff_stat(raw_diff)
    snr.deleted_lines = _count_deleted(raw_diff)

    for filepath, added_lines in file_diffs.items():
        file_info = {
            "path": filepath,
            "added": len(added_lines),
            "substantive": 0,
            "boilerplate": 0,
            "file_type": classify_file(filepath),
        }

        if file_info["file_type"] == "noise":
            # Entire file is always boilerplate
            file_info["boilerplate"] = len(added_lines)
            snr.boilerplate_added += len(added_lines)
            snr.noise_files += 1
        else:
            # Line-level inspection
            bp = sum(1 for l in added_lines if is_boilerplate_line(l))
            sub = len(added_lines) - bp
            file_info["substantive"] = sub
            file_info["boilerplate"] = bp
            snr.substantive_added += sub
            snr.boilerplate_added += bp

            if sub > 0:
                snr.signal_files += 1
            else:
                snr.noise_files += 1

        snr.added_lines += len(added_lines)
        snr.per_file.append(file_info)

    # Compute ratios
    if snr.added_lines > 0:
        snr.boilerplate_ratio = snr.boilerplate_added / snr.added_lines
        snr.signal_ratio = 1.0 - snr.boilerplate_ratio
    else:
        snr.boilerplate_ratio = 0.0
        snr.signal_ratio = 0.0

    snr.classification = _classify_ratio(snr.signal_ratio)
    return snr


# ── Multi-commit analysis ────────────────────────────────────────────

def analyse_commits(count: int = 10, repo: Path = REPO) -> list[dict]:
    """Analyse the last *count* commits on the current branch.

    Returns a list of dicts (one per commit) sorted newest-first.
    """
    try:
        log_out = subprocess.run(
            ["git", "log", f"--max-count={count}", "--format=%H"],
            capture_output=True, text=True, cwd=repo, timeout=15,
        ).stdout.strip()
    except (subprocess.TimeoutExpired, Exception):
        return []

    if not log_out:
        return []

    hashes = [h for h in log_out.split("\n") if h]
    results = []
    for h in hashes:
        snr = analyse_commit(h, repo)
        results.append(asdict(snr))

    return results


def aggregate_report(results: list[dict]) -> dict:
    """Summarise a list of commit SNR results into one report."""
    if not results:
        return {
            "total_commits": 0,
            "avg_signal_ratio": 0.0,
            "classification_counts": {},
            "total_added": 0,
            "total_substantive": 0,
            "assessment": "no-data",
        }

    total_added = sum(r["added_lines"] for r in results)
    total_substantive = sum(r["substantive_added"] for r in results)
    avg_snr = (
        total_substantive / total_added if total_added > 0 else 0.0
    )

    counts: dict[str, int] = {}
    for r in results:
        c = r["classification"]
        counts[c] = counts.get(c, 0) + 1

    if avg_snr >= 0.5:
        assessment = "healthy"
    elif avg_snr >= 0.2:
        assessment = "mixed"
    else:
        assessment = "noise-dominated"

    return {
        "total_commits": len(results),
        "avg_signal_ratio": round(avg_snr, 4),
        "classification_counts": counts,
        "total_added": total_added,
        "total_substantive": total_substantive,
        "assessment": assessment,
    }


def trend_report(results: list[dict]) -> dict:
    """Compare the first half of results to the second half.

    Returns a trend direction: 'improving', 'stable', 'degrading',
    or 'insufficient-data' if fewer than 4 commits.
    """
    if len(results) < 4:
        return {"direction": "insufficient-data", "older_avg": 0.0, "newer_avg": 0.0}

    mid = len(results) // 2
    # results are newest-first, so second half = older commits
    newer = results[:mid]
    older = results[mid:]

    def _avg(items: list[dict]) -> float:
        if not items:
            return 0.0
        return sum(i["signal_ratio"] for i in items) / len(items)

    older_avg = _avg(older)
    newer_avg = _avg(newer)
    delta = newer_avg - older_avg

    if delta > 0.05:
        direction = "improving"
    elif delta < -0.05:
        direction = "degrading"
    else:
        direction = "stable"

    return {
        "direction": direction,
        "older_avg": round(older_avg, 4),
        "newer_avg": round(newer_avg, 4),
        "delta": round(delta, 4),
    }


# ── CLI ──────────────────────────────────────────────────────────────

def _cli() -> int:
    parser = argparse.ArgumentParser(
        description="Measure commit signal-to-noise ratio."
    )
    parser.add_argument("--count", type=int, default=10,
                        help="number of commits to analyse (default 10)")
    parser.add_argument("--json", action="store_true",
                        help="output JSON instead of text")
    args = parser.parse_args()

    results = analyse_commits(count=args.count)
    report = aggregate_report(results)
    trend = trend_report(results)

    if args.json:
        output = {"commits": results, "report": report, "trend": trend}
        print(json.dumps(output, indent=2, default=str))
    else:
        print(f"{'hash':10s}  {'class':12s}  {'snr':>6s}  {'+lines':>7s}  {'sub':>5s}  {'bp':>5s}")
        print("-" * 56)
        for r in results:
            h = r["commit_hash"][:8] if r["commit_hash"] else "?"
            print(
                f"{h:10s}  {r['classification']:12s}  "
                f"{r['signal_ratio']:6.2f}  "
                f"{r['added_lines']:7d}  "
                f"{r['substantive_added']:5d}  "
                f"{r['boilerplate_added']:5d}"
            )
        print()
        print(f"aggregate: {report['assessment']}  "
              f"avg_snr={report['avg_signal_ratio']:.2f}  "
              f"commits={report['total_commits']}")
        print(f"trend:     {trend['direction']}  "
              f"(older={trend['older_avg']:.2f} → newer={trend['newer_avg']:.2f})")

    # exit code
    noise_count = report["classification_counts"].get("noise", 0)
    mixed_count = report["classification_counts"].get("mixed", 0)
    total = report["total_commits"]

    if total > 0 and noise_count > total / 2:
        return 2
    if mixed_count > 0 or noise_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
