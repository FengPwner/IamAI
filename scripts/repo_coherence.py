#!/usr/bin/env python3
"""
repo_coherence.py — measure whether commits tell a coherent story.

while repo_echo.py detects *repetition* and repo_sentinel.py detects
*operational failure*, coherence measures whether consecutive commits
are *topically related* — does the repo drift randomly, or does each
commit build on the previous ones?

metrics (each 0–25, total 0–100):
  1. topic_continuity  — jaccard similarity of vocabulary between
                          consecutive commit messages
  2. file_locality     — do sequential commits touch nearby directories?
  3. intent_consistency — do commit message verbs/prefixes follow a
                          stable distribution across the window?
  4. narrative_thread  — fraction of commits that share at least one
                          content word with their predecessor

grading:
  0–20   COHERENT   — tight, focused narrative
  21–45  FOCUSED    — mostly on-topic with natural drift
  46–70  WANDERING  — scattered activity, weak thread
  71–100 FRAGMENTED — random jumps, no discernible story

usage:
    python3 scripts/repo_coherence.py [--repo PATH] [--window N]
    python3 scripts/repo_coherence.py --json

exit codes:
    0 = COHERENT or FOCUSED (healthy)
    1 = WANDERING (warning)
    2 = FRAGMENTED (alert)
"""

import argparse
import json
import math
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


def tokenize(text: str) -> Set[str]:
    """lowercase split on non-alpha, drop short tokens and stop-words."""
    stop = {
        "the", "and", "for", "with", "from", "into", "this", "that",
        "not", "but", "all", "are", "was", "were", "been", "has", "had",
        "add", "update", "fix", "the", "new", "old", "use", "one",
        "more", "some", "than", "its", "will", "can", "may",
    }
    words = re.findall(r"[a-z]{3,}", text.lower())
    return {w for w in words if w not in stop}


def get_commits_with_files(repo: str, window: int = 100) -> List[Dict]:
    """get recent commits with message, timestamp, and changed files."""
    log = run_git(
        repo, "log", f"--max-count={window}",
        "--format=COMMIT:%H|%s|%aI", "--name-only",
    )
    if not log:
        return []

    commits: List[Dict] = []
    current: Optional[Dict] = None

    for line in log.split("\n"):
        line = line.strip()
        if line.startswith("COMMIT:"):
            if current is not None:
                commits.append(current)
            parts = line[7:].split("|", 2)
            if len(parts) == 3:
                current = {
                    "hash": parts[0][:8],
                    "message": parts[1],
                    "timestamp": parts[2],
                    "files": [],
                }
            else:
                current = None
        elif line and current is not None:
            current["files"].append(line)

    if current is not None:
        commits.append(current)

    return commits


# ── metrics ──────────────────────────────────────────────────────────


def score_topic_continuity(commits: List[Dict]) -> float:
    """score 0–25: jaccard similarity of vocabulary between consecutive commits.

    high continuity = each commit's message shares words with its predecessor.
    low continuity  = random topic jumps between commits.

    average pairwise jaccard ∈ [0, 1] mapped to [0, 25] inverted:
      jaccard 1.0  → 0 points (perfectly continuous)
      jaccard 0.0  → 25 points (completely disjoint)
    """
    if len(commits) < 2:
        return 12.5  # neutral for too few commits

    token_sets = [tokenize(c["message"]) for c in commits]
    jaccards = []

    for i in range(len(token_sets) - 1):
        a, b = token_sets[i], token_sets[i + 1]
        if not a and not b:
            jaccards.append(1.0)  # both empty = same (non-)topic
        elif not a or not b:
            jaccards.append(0.0)  # one empty = disjoint
        else:
            intersection = len(a & b)
            union = len(a | b)
            jaccards.append(intersection / union if union else 1.0)

    avg_jaccard = sum(jaccards) / len(jaccards) if jaccards else 0.5
    # invert: high similarity = low score (good)
    score = (1.0 - avg_jaccard) * 25
    return round(min(25.0, max(0.0, score)), 2)


def score_file_locality(commits: List[Dict]) -> float:
    """score 0–25: do consecutive commits touch files in the same directories?

    if commit A touches scripts/ and tests/, and commit B also touches
    scripts/ and tests/, they have high locality. if commit B jumps to
    notes/ and data/, locality is low.

    measured as average directory-level jaccard between consecutive commits.
    """
    if len(commits) < 2:
        return 12.5

    def dir_set(files: List[str]) -> Set[str]:
        return {os.path.dirname(f) or "." for f in files if f}

    dir_sets = [dir_set(c["files"]) for c in commits]
    jaccards = []

    for i in range(len(dir_sets) - 1):
        a, b = dir_sets[i], dir_sets[i + 1]
        if not a and not b:
            jaccards.append(1.0)
        elif not a or not b:
            jaccards.append(0.0)
        else:
            intersection = len(a & b)
            union = len(a | b)
            jaccards.append(intersection / union if union else 1.0)

    avg = sum(jaccards) / len(jaccards) if jaccards else 0.5
    score = (1.0 - avg) * 25
    return round(min(25.0, max(0.0, score)), 2)


def score_intent_consistency(commits: List[Dict]) -> float:
    """score 0–25: is the distribution of commit intents stable?

    classify each message by its leading verb/prefix:
      add, fix, update, refactor, docs, test, chore, other
    then measure how much the distribution in the first half of the window
    diverges from the second half (jensen-shannon divergence, normalized).

    stable distribution = focused work style = low score.
    shifting distribution = changing priorities = higher score.
    """
    intent_prefixes = [
        ("add", re.compile(r"^add\b", re.I)),
        ("fix", re.compile(r"^fix\b", re.I)),
        ("update", re.compile(r"^(update|upd)\b", re.I)),
        ("refactor", re.compile(r"^(refactor|refact|reorg)\b", re.I)),
        ("docs", re.compile(r"^(docs?|readme|note|comment)\b", re.I)),
        ("test", re.compile(r"^(test|tests?|testing)\b", re.I)),
        ("caretaker", re.compile(r"^caretaker\b", re.I)),
        ("catchup", re.compile(r"^(catch[- ]?up|backlog|flush)\b", re.I)),
    ]

    def classify(msg: str) -> str:
        for name, pat in intent_prefixes:
            if pat.search(msg):
                return name
        return "other"

    if len(commits) < 4:
        return 12.5

    mid = len(commits) // 2
    first_half = [classify(c["message"]) for c in commits[:mid]]
    second_half = [classify(c["message"]) for c in commits[mid:]]

    def distribution(labels: List[str]) -> Counter:
        c = Counter(labels)
        total = sum(c.values())
        if total == 0:
            return c
        return Counter({k: v / total for k, v in c.items()})

    dist_a = distribution(first_half)
    dist_b = distribution(second_half)

    # jensen-shannon divergence
    all_keys = set(dist_a.keys()) | set(dist_b.keys())
    if not all_keys:
        return 12.5

    m = {}
    for k in all_keys:
        a_val = dist_a.get(k, 0.0)
        b_val = dist_b.get(k, 0.0)
        m[k] = (a_val + b_val) / 2

    def kl(p: Counter, q: Dict[str, float]) -> float:
        total = 0.0
        for k in all_keys:
            p_val = p.get(k, 0.0)
            q_val = q.get(k, 0.0)
            if p_val > 0 and q_val > 0:
                total += p_val * math.log2(p_val / q_val)
        return total

    jsd = (kl(dist_a, m) + kl(dist_b, m)) / 2
    # jsd ranges 0 (identical) to 1 (maximally different)
    # normalize: jsd 0.3+ is quite divergent for commit messages
    score = min(1.0, jsd / 0.5) * 25
    return round(min(25.0, max(0.0, score)), 2)


def score_narrative_thread(commits: List[Dict]) -> float:
    """score 0–25: fraction of consecutive pairs sharing ≥1 content word.

    a "content word" is a tokenized word from the commit message
    (excluding stop words). if two consecutive commits share at least one,
    the narrative thread holds at that point.

    thread_hold_ratio 1.0 = every pair connected → 0 points
    thread_hold_ratio 0.0 = no pair connected → 25 points
    """
    if len(commits) < 2:
        return 12.5

    token_sets = [tokenize(c["message"]) for c in commits]
    connected = 0

    for i in range(len(token_sets) - 1):
        if token_sets[i] & token_sets[i + 1]:
            connected += 1

    ratio = connected / (len(token_sets) - 1) if len(token_sets) > 1 else 0.5
    score = (1.0 - ratio) * 25
    return round(min(25.0, max(0.0, score)), 2)


# ── scoring & grading ────────────────────────────────────────────────


def compute_coherence_score(
    continuity: float,
    locality: float,
    intent: float,
    thread: float,
) -> Tuple[float, str]:
    """compute total score and grade."""
    total = continuity + locality + intent + thread
    total = round(min(100, max(0, total)), 1)

    if total <= 20:
        grade = "COHERENT"
    elif total <= 45:
        grade = "FOCUSED"
    elif total <= 70:
        grade = "WANDERING"
    else:
        grade = "FRAGMENTED"

    return total, grade


def format_bar(value: float, max_val: float = 25, width: int = 20) -> str:
    """format a simple ascii bar."""
    filled = int(round(value / max_val * width))
    filled = min(width, max(0, filled))
    return "█" * filled + "░" * (width - filled)


# ── analysis entry point ─────────────────────────────────────────────


def analyze(repo: str = ".", window: int = 100, as_json: bool = False) -> int:
    """run coherence analysis and return exit code."""
    repo = str(Path(repo).resolve())
    commits = get_commits_with_files(repo, window)

    continuity = score_topic_continuity(commits)
    locality = score_file_locality(commits)
    intent = score_intent_consistency(commits)
    thread = score_narrative_thread(commits)

    total, grade = compute_coherence_score(continuity, locality, intent, thread)

    if as_json:
        output = {
            "coherence_score": total,
            "grade": grade,
            "metrics": {
                "topic_continuity": continuity,
                "file_locality": locality,
                "intent_consistency": intent,
                "narrative_thread": thread,
            },
            "commits_analyzed": len(commits),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"\n{'=' * 54}")
        print(f"  repo coherence — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'=' * 54}\n")
        print(f"  commits analyzed: {len(commits)}\n")
        print(f"  ┌─ metrics ────────────────────────────────────┐")
        print(f"  │ topic continuity   {format_bar(continuity)}  {continuity:>5.1f}/25 │")
        print(f"  │ file locality      {format_bar(locality)}  {locality:>5.1f}/25 │")
        print(f"  │ intent consistency {format_bar(intent)}  {intent:>5.1f}/25 │")
        print(f"  │ narrative thread   {format_bar(thread)}  {thread:>5.1f}/25 │")
        print(f"  └──────────────────────────────────────────────┘\n")
        print(f"  COHERENCE SCORE: {total}/100  [{grade}]\n")

        if grade == "COHERENT":
            print("  ✓ tight, focused narrative — each commit builds on the last")
        elif grade == "FOCUSED":
            print("  ✓ mostly on-topic with natural thematic drift")
        elif grade == "WANDERING":
            print("  ⚠ scattered activity — weak thread between commits")
        else:
            print("  ✗ random jumps — no discernible story in commit flow")

        print()

    if grade in ("COHERENT", "FOCUSED"):
        return 0
    elif grade == "WANDERING":
        return 1
    else:
        return 2


def main():
    parser = argparse.ArgumentParser(
        description="measure commit narrative coherence"
    )
    parser.add_argument("--repo", default=".", help="path to git repo")
    parser.add_argument("--window", type=int, default=100,
                        help="number of recent commits to analyze")
    parser.add_argument("--json", action="store_true", help="output as JSON")
    args = parser.parse_args()

    sys.exit(analyze(args.repo, args.window, args.json))


if __name__ == "__main__":
    main()
