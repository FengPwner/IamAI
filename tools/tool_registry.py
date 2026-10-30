#!/usr/bin/env python3
"""tool_registry.py — catalogue every Python tool in tools/ by category.

Scans tools/*.py, extracts the first docstring line, classifies each
tool into a functional group, and flags clusters that look like overlap
(3+ tools in the same narrow sub-topic).

Usage:
    python3 tools/tool_registry.py              # human-readable table
    python3 tools/tool_registry.py --json       # machine-readable
    python3 tools/tool_registry.py --overlaps   # only show overlap clusters

Exit codes:
    0  completed successfully
    1  error (e.g. tools/ directory not found)

Categories
----------
    process       — process lifecycle, PID management, reclaim detection
    stall         — stall / silence detection and classification
    commit        — commit cadence, gap analysis, freshness, density
    stroke        — stroke production, diversity, novelty, pacing
    push          — push lag, push gate, pre-push sync
    backlog       — uncommitted file tracking, drain, pressure
    caretaker     — caretaker briefing, dashboard, visit scoring
    health        — composite health indices, triage, pulse, heartbeat
    repo          — repo-level drift, changelog, lock management
    meta          — registry, audit, self-referential tooling
    other         — anything that doesn't fit above
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO / "tools"

# ── keyword → category mapping (order matters: first match wins) ──────

KEYWORD_RULES: List[Tuple[str, List[str]]] = [
    ("caretaker", ["caretaker", "visit_continuity", "visit_"]),
    ("push",      ["push_", "pre_push"]),
    ("backlog",   ["backlog", "uncommitted"]),
    ("stall",     ["stall", "silence", "deadman", "stuck_gate", "writer_silence"]),
    ("process",   ["process_", "pid", "reclaim", "restart", "uptime", "lock_",
                    "stale_lock", "stale_pid", "auto_lock", "session_half_life"]),
    ("stroke",    ["stroke_", "writer_loop", "cadence", "pacer"]),
    ("commit",    ["commit_", "batch_recovery"]),
    ("health",    ["health", "triage", "pulse", "heartbeat", "vitality",
                    "pipeline_health"]),
    ("repo",      ["repo_", "drift", "doc_growth", "roster"]),
    ("meta",      ["registry", "audit", "summary", "session_summary"]),
]

# ── narrow sub-topic clusters for overlap detection ───────────────────

OVERLAP_TOPICS: Dict[str, List[str]] = {
    "stall detection":     ["stall", "silence", "deadman", "stuck"],
    "PID / process":      ["pid", "process", "reclaim"],
    "commit gap":         ["commit_gap", "commit_interval", "commit_freshness",
                           "commit_density", "commit_momentum"],
    "push lag":           ["push_lag", "push_race", "push_gate", "pre_push"],
    "stroke quality":     ["stroke_diversity", "stroke_novelty", "stroke_content",
                           "stroke_diversity", "stroke_freshness"],
    "lock management":    ["lock_", "stale_lock", "auto_lock", "stale_pid"],
    "caretaker tools":    ["caretaker_"],
}


# ── helpers ────────────────────────────────────────────────────────────

def extract_docstring(filepath: Path) -> str:
    """Return the module-level docstring (first line) of a .py file."""
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError, FileNotFoundError, OSError):
        return ""
    doc = ast.get_docstring(tree) or ""
    first_line = doc.strip().split("\n")[0] if doc else ""
    # strip em-dash separator (e.g. "tool_name — description" → "tool_name")
    if " — " in first_line:
        first_line = first_line.split(" — ", 1)[0]
    return first_line.strip()


def classify(name: str) -> str:
    """Assign a tool name to a category using keyword rules."""
    for category, keywords in KEYWORD_RULES:
        for kw in keywords:
            if kw in name:
                return category
    return "other"


def scan_tools(tools_dir: Path = TOOLS_DIR) -> List[dict]:
    """Scan tools/*.py and return a list of tool records."""
    records = []
    if not tools_dir.is_dir():
        return records
    for fp in sorted(tools_dir.glob("*.py")):
        if fp.name.startswith("__"):
            continue
        name = fp.stem
        records.append({
            "name": name,
            "file": fp.name,
            "category": classify(name),
            "docstring": extract_docstring(fp),
        })
    return records


def detect_overlaps(records: List[dict]) -> Dict[str, List[str]]:
    """Find overlap clusters: topics with 3+ matching tools."""
    clusters: Dict[str, List[str]] = {}
    for topic, keywords in OVERLAP_TOPICS.items():
        members = []
        for r in records:
            if any(kw in r["name"] for kw in keywords):
                members.append(r["name"])
        if len(members) >= 3:
            clusters[topic] = sorted(set(members))
    return clusters


# ── output formatters ─────────────────────────────────────────────────

def format_table(records: List[dict]) -> str:
    """Plain-text table grouped by category."""
    by_cat: Dict[str, List[dict]] = defaultdict(list)
    for r in records:
        by_cat[r["category"]].append(r)

    lines = [f"Tool Registry — {len(records)} tools in {TOOLS_DIR.name}/\n"]
    for cat in sorted(by_cat):
        lines.append(f"\n── {cat.upper()} ({len(by_cat[cat])}) ──")
        for r in sorted(by_cat[cat], key=lambda x: x["name"]):
            doc = r["docstring"][:72] + ("…" if len(r["docstring"]) > 72 else "")
            lines.append(f"  {r['name']:<40s} {doc}")
    return "\n".join(lines)


def format_overlaps(clusters: Dict[str, List[str]]) -> str:
    """Plain-text overlap report."""
    if not clusters:
        return "No overlap clusters detected (all topics < 3 tools)."
    lines = ["Overlap Clusters — topics with 3+ tools:\n"]
    for topic in sorted(clusters):
        members = clusters[topic]
        lines.append(f"\n  {topic} ({len(members)} tools):")
        for m in members:
            lines.append(f"    • {m}")
    return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--overlaps", action="store_true",
                    help="only show overlap clusters")
    ap.add_argument("--tools-dir", default=str(TOOLS_DIR),
                    help="path to tools directory")
    args = ap.parse_args()

    tools_dir = Path(args.tools_dir)
    if not tools_dir.is_dir():
        print(f"error: tools directory not found: {tools_dir}", file=sys.stderr)
        return 1

    records = scan_tools(tools_dir)
    clusters = detect_overlaps(records)

    if args.json:
        output = {
            "total": len(records),
            "categories": dict(Counter(r["category"] for r in records)),
            "tools": records,
            "overlaps": clusters,
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
    elif args.overlaps:
        print(format_overlaps(clusters))
    else:
        print(format_table(records))
        print()
        print(format_overlaps(clusters))

    return 0


if __name__ == "__main__":
    sys.exit(main())
