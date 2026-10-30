#!/usr/bin/env python3
"""
session_handoff_quality.py — measure continuity between caretaker visits.

each caretaker visit is a discrete session. good handoffs mean the next
visit can pick up where the last left off without re-discovering context.

metrics (each 0–25, total 0–100):
  1. handoff_note_presence    — does the visit note have a summary/handoff
                                 section with actionable next steps?
  2. recommendation_followthrough — were previous visit's recommendations
                                     actually implemented?
  3. context_continuity       — does the current visit reference or build
                                 on the previous visit's work?
  4. pending_items_tracking   — are open items documented and carried
                                 forward across visits?

grading:
  0–20   SEAMLESS  — excellent continuity, minimal re-orientation
  21–45  SMOOTH    — good handoff, minor gaps
  46–70  ROUGH     — weak continuity, some re-discovery needed
  71–100 BROKEN    — no handoff, each visit starts from scratch

usage:
    python3 scripts/session_handoff_quality.py [--repo PATH] [--visits N]
    python3 scripts/session_handoff_quality.py --json

exit codes:
    0 = SEAMLESS or SMOOTH (healthy)
    1 = ROUGH (warning)
    2 = BROKEN (alert)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ── helpers ──────────────────────────────────────────────────────────

def run_git(repo: str, *args: str) -> str:
    """run a git command and return stdout."""
    result = subprocess.run(
        ["git", "-C", repo] + list(args),
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def read_file(repo: str, path: str) -> str:
    """read a file from the repo, return empty string if missing."""
    full = os.path.join(repo, path)
    if not os.path.isfile(full):
        return ""
    try:
        with open(full, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""


def get_visit_notes(repo: str, max_visits: int = 20) -> List[Dict]:
    """find recent caretaker visit notes in reverse chronological order."""
    notes_dir = os.path.join(repo, "notes")
    if not os.path.isdir(notes_dir):
        return []

    pattern = re.compile(r"caretaker-visit-(\d+)(?:-\d{4}-\d{2}-\d{2})?\.md$")
    visits = []

    for fname in os.listdir(notes_dir):
        m = pattern.match(fname)
        if m:
            visit_num = int(m.group(1))
            visits.append({
                "number": visit_num,
                "filename": fname,
                "path": f"notes/{fname}",
            })

    visits.sort(key=lambda v: v["number"], reverse=True)
    return visits[:max_visits]


def extract_sections(content: str) -> Dict[str, str]:
    """split markdown into sections by heading."""
    sections = {}
    current_heading = "intro"
    current_lines = []

    for line in content.split("\n"):
        if line.startswith("#"):
            if current_lines:
                sections[current_heading.lower()] = "\n".join(current_lines)
            # extract heading text (strip # and whitespace)
            heading = re.sub(r"^#+\s*", "", line).strip().lower()
            current_heading = heading or "section"
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections[current_heading.lower()] = "\n".join(current_lines)

    return sections


def tokenize(text: str) -> Set[str]:
    """lowercase split, drop stop words and short tokens."""
    stop = {
        "the", "and", "for", "with", "from", "into", "this", "that",
        "not", "but", "all", "are", "was", "were", "been", "has", "had",
        "add", "update", "fix", "new", "old", "use", "one", "more",
        "some", "than", "its", "will", "can", "may", "should", "would",
    }
    words = re.findall(r"[a-z]{3,}", text.lower())
    return {w for w in words if w not in stop}


# ── metric 1: handoff note presence ──────────────────────────────────

def score_handoff_presence(content: str) -> Tuple[int, str]:
    """check if the visit note has a clear handoff/summary section.

    looks for: summary, handoff, next steps, todo, open items, pending.
    """
    sections = extract_sections(content)
    section_keys = set(sections.keys())

    # check for handoff-related section headings
    handoff_keywords = {
        "summary", "handoff", "next steps", "todo", "open items",
        "pending", "follow-up", "action items", "recommendations",
        "what's next", "carry forward",
    }

    found = section_keys & handoff_keywords

    if not found:
        # also check for bullet lists with actionable items
        if re.search(r"^\s*[-*]\s+\w", content, re.MULTILINE):
            return 15, "no explicit handoff section, but has bullet lists"
        return 25, "no handoff section or actionable summary found"

    # check if the handoff section has substance (not just a header)
    for key in found:
        section_text = sections[key].strip()
        if len(section_text) > 50:
            # check for actionable content (verbs, specific items)
            if re.search(r"\b(need|should|must|todo|fix|add|update)\b", section_text, re.I):
                return 0, f"clear '{key}' section with actionable items"
            return 5, f"'{key}' section present but lacks actionable content"

    return 10, f"found sections {found} but content is thin"


# ── metric 2: recommendation followthrough ───────────────────────────

def score_followthrough(
    current_content: str,
    previous_content: str,
) -> Tuple[int, str]:
    """check if previous visit's recommendations appear in current visit.

    extracts action words from previous visit's handoff section and checks
    if they appear in the current visit's content or commits.
    """
    if not previous_content:
        return 0, "no previous visit to compare against"

    prev_sections = extract_sections(previous_content)

    # find handoff/recommendation sections in previous visit
    handoff_keys = {
        "recommendations", "next steps", "todo", "action items",
        "follow-up", "what's next",
    }

    prev_handoff = ""
    for key in handoff_keys:
        if key in prev_sections:
            prev_handoff += prev_sections[key] + "\n"

    if not prev_handoff.strip():
        # fallback: use the whole previous note
        prev_handoff = previous_content

    # extract key terms from previous handoff
    prev_tokens = tokenize(prev_handoff)

    if not prev_tokens:
        return 0, "no extractable recommendations from previous visit"

    # check how many appear in current visit
    current_tokens = tokenize(current_content)
    overlap = prev_tokens & current_tokens

    if not overlap:
        return 25, "no overlap with previous visit's recommendations"

    coverage = len(overlap) / min(len(prev_tokens), 10)
    score = max(0, 25 - int(coverage * 25))

    if coverage > 0.5:
        return score, f"good followthrough: {len(overlap)}/{len(prev_tokens)} terms carried forward"
    elif coverage > 0.2:
        return score, f"partial followthrough: {len(overlap)}/{len(prev_tokens)} terms"
    else:
        return score, f"weak followthrough: only {len(overlap)}/{len(prev_tokens)} terms"


# ── metric 3: context continuity ─────────────────────────────────────

def score_context_continuity(
    current_content: str,
    previous_content: str,
) -> Tuple[int, str]:
    """measure topical overlap between consecutive visits.

    uses jaccard similarity of content words to assess whether the
    current visit is building on the previous one's work.
    """
    if not previous_content:
        return 0, "no previous visit to compare against"

    current_tokens = tokenize(current_content)
    previous_tokens = tokenize(previous_content)

    if not current_tokens or not previous_tokens:
        return 25, "insufficient content to measure continuity"

    intersection = current_tokens & previous_tokens
    union = current_tokens | previous_tokens

    jaccard = len(intersection) / len(union) if union else 0

    # scale: 0.3+ is good continuity, 0.1-0.3 is moderate, <0.1 is weak
    if jaccard >= 0.3:
        score = max(0, int(25 * (1 - (jaccard - 0.3) / 0.7)))
        return score, f"strong continuity: jaccard={jaccard:.2f}"
    elif jaccard >= 0.1:
        score = max(5, int(25 * (1 - (jaccard - 0.1) / 0.2)))
        return score, f"moderate continuity: jaccard={jaccard:.2f}"
    else:
        return 25, f"weak continuity: jaccard={jaccard:.2f}"


# ── metric 4: pending items tracking ─────────────────────────────────

def score_pending_tracking(content: str) -> Tuple[int, str]:
    """check if the visit note documents pending/open items.

    looks for: todo lists, known issues, open questions, backlog items.
    """
    sections = extract_sections(content)
    section_keys = set(sections.keys())

    pending_keywords = {
        "pending", "open items", "todo", "known issues",
        "backlog", "open questions", "to investigate",
        "needs work", "follow-up", "carry forward",
    }

    # match if any keyword appears as substring in a section key
    found = set()
    for key in section_keys:
        for kw in pending_keywords:
            if kw in key or key in kw:
                found.add(key)
                break

    if found:
        # check if the section has actual items
        for key in found:
            section_text = sections[key].strip()
            # look for list items or multiple lines
            if re.search(r"^\s*[-*]\s+\w", section_text, re.MULTILINE):
                item_count = len(re.findall(r"^\s*[-*]\s+\w", section_text, re.MULTILINE))
                if item_count >= 3:
                    return 0, f"'{key}' section has {item_count} documented items"
                elif item_count >= 1:
                    return 5, f"'{key}' section has {item_count} item(s)"
            elif len(section_text) > 100:
                return 10, f"'{key}' section present but not in list format"

        return 15, f"found {found} but no structured items"

    # fallback: check for inline todo markers
    todo_markers = re.findall(r"\b(TODO|FIXME|XXX|HACK)\b", content, re.I)
    if todo_markers:
        return 10, f"found {len(todo_markers)} inline TODO markers (no dedicated section)"

    return 25, "no pending items section or markers found"


# ── aggregation ──────────────────────────────────────────────────────

def compute_handoff_quality(
    current_content: str,
    previous_content: str,
) -> Dict:
    """compute all four metrics and return structured result."""
    m1_score, m1_detail = score_handoff_presence(current_content)
    m2_score, m2_detail = score_followthrough(current_content, previous_content)
    m3_score, m3_detail = score_context_continuity(current_content, previous_content)
    m4_score, m4_detail = score_pending_tracking(current_content)

    total = m1_score + m2_score + m3_score + m4_score

    if total <= 20:
        grade = "SEAMLESS"
    elif total <= 45:
        grade = "SMOOTH"
    elif total <= 70:
        grade = "ROUGH"
    else:
        grade = "BROKEN"

    return {
        "total_score": total,
        "grade": grade,
        "metrics": {
            "handoff_note_presence": {
                "score": m1_score,
                "max": 25,
                "detail": m1_detail,
            },
            "recommendation_followthrough": {
                "score": m2_score,
                "max": 25,
                "detail": m2_detail,
            },
            "context_continuity": {
                "score": m3_score,
                "max": 25,
                "detail": m3_detail,
            },
            "pending_items_tracking": {
                "score": m4_score,
                "max": 25,
                "detail": m4_detail,
            },
        },
    }


def format_bar(score: int, max_score: int = 25, width: int = 20) -> str:
    """render a simple progress bar."""
    filled = int((score / max_score) * width) if max_score > 0 else 0
    return "[" + "#" * filled + "-" * (width - filled) + "]"


# ── cli ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="measure handoff quality between caretaker visits",
    )
    parser.add_argument("--repo", default=".", help="path to git repo")
    parser.add_argument("--visits", type=int, default=10, help="number of recent visits to analyze")
    parser.add_argument("--json", action="store_true", help="output JSON")
    args = parser.parse_args()

    repo = os.path.abspath(args.repo)
    visits = get_visit_notes(repo, max_visits=args.visits + 1)

    if len(visits) < 2:
        print("insufficient visit data (need at least 2 visits)")
        sys.exit(1)

    results = []
    for i in range(min(args.visits, len(visits) - 1)):
        current = visits[i]
        previous = visits[i + 1]

        current_content = read_file(repo, current["path"])
        previous_content = read_file(repo, previous["path"])

        quality = compute_handoff_quality(current_content, previous_content)
        quality["visit_number"] = current["number"]
        quality["previous_visit"] = previous["number"]
        results.append(quality)

    if args.json:
        print(json.dumps({"visits": results}, indent=2))
    else:
        print(f"session handoff quality report ({len(results)} visit pairs)")
        print("=" * 70)

        for r in results:
            print(f"\nvisit {r['visit_number']} → {r['previous_visit']}:")
            print(f"  total: {r['total_score']:3d}/100  [{r['grade']}]")
            print(f"  handoff presence:    {format_bar(r['metrics']['handoff_note_presence']['score'])} {r['metrics']['handoff_note_presence']['score']:2d}/25")
            print(f"  followthrough:       {format_bar(r['metrics']['recommendation_followthrough']['score'])} {r['metrics']['recommendation_followthrough']['score']:2d}/25")
            print(f"  context continuity:  {format_bar(r['metrics']['context_continuity']['score'])} {r['metrics']['context_continuity']['score']:2d}/25")
            print(f"  pending tracking:    {format_bar(r['metrics']['pending_items_tracking']['score'])} {r['metrics']['pending_items_tracking']['score']:2d}/25")

        # summary
        avg_score = sum(r["total_score"] for r in results) / len(results) if results else 0
        print(f"\n{'=' * 70}")
        print(f"average handoff quality: {avg_score:.1f}/100")

        if avg_score <= 20:
            print("status: SEAMLESS — excellent continuity across sessions")
        elif avg_score <= 45:
            print("status: SMOOTH — good handoff practices")
        elif avg_score <= 70:
            print("status: ROUGH — consider adding explicit handoff sections")
        else:
            print("status: BROKEN — visits lack continuity, add handoff notes")

    # exit code based on average
    avg = sum(r["total_score"] for r in results) / len(results) if results else 0
    if avg <= 45:
        sys.exit(0)
    elif avg <= 70:
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
