#!/usr/bin/env python3
"""
commit_vocabulary_richness.py — measure lexical diversity in commit messages.

A healthy repo's commit messages should describe varied work. When vocabulary
richness drops, it signals repetitive output — the same kind of fix, the same
pattern, over and over. This tool quantifies that signal.

metrics (each 0–25, total 0–100, higher is more diverse):
  1. type_token_ratio     — unique words / total words across N messages
  2. hapax_ratio          — words appearing exactly once / total unique words
  3. vocabulary_growth    — rate at which new unique words appear
  4. category_entropy     — Shannon entropy of commit category distribution

grading:
  0–25   MONOTONOUS  — severely repetitive, content loop likely
  26–50  FORMULAIC   — mostly template-driven, low creativity
  51–75  VARIED      — good mix of work types and descriptions
  76–100 RICH        — highly diverse vocabulary and commit patterns

usage:
    python3 scripts/commit_vocabulary_richness.py [--repo PATH] [--last N]
    python3 scripts/commit_vocabulary_richness.py --json

exit codes:
    0 = RICH or VARIED (good)
    1 = FORMULAIC (warning)
    2 = MONOTONOUS (alert)
"""

import argparse
import json
import math
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path


# Category keywords for commit classification
CATEGORIES = {
    "add": ["add", "added", "adding", "new", "create", "introduce"],
    "fix": ["fix", "fixed", "fixing", "repair", "resolve", "patch"],
    "update": ["update", "updated", "updating", "modify", "change", "adjust"],
    "refactor": ["refactor", "refactored", "rewrite", "restructure", "clean"],
    "docs": ["docs", "documentation", "readme", "note", "comment"],
    "caretaker": ["caretaker", "visit", "check", "health", "monitor"],
    "ops": ["push", "deploy", "restart", "recovery", "rescue", "sync"],
    "test": ["test", "tests", "testing", "coverage", "assert"],
}


def get_commit_messages(repo_path: str, last_n: int = 50) -> list[str]:
    """Extract commit messages from git log."""
    result = subprocess.run(
        ["git", "-C", repo_path, "log", f"--max-count={last_n}", "--format=%s"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]


def tokenize(messages: list[str]) -> list[str]:
    """Split messages into lowercase word tokens, removing punctuation."""
    tokens = []
    for msg in messages:
        words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", msg.lower())
        tokens.extend(words)
    return tokens


def compute_type_token_ratio(tokens: list[str]) -> float:
    """Unique words / total words. Higher = more diverse vocabulary."""
    if not tokens:
        return 0.0
    return len(set(tokens)) / len(tokens)


def compute_hapax_ratio(tokens: list[str]) -> float:
    """Words appearing exactly once / total unique words."""
    if not tokens:
        return 0.0
    freq = Counter(tokens)
    hapax = sum(1 for w, c in freq.items() if c == 1)
    unique = len(freq)
    return hapax / unique if unique > 0 else 0.0


def compute_vocabulary_growth(messages: list[str]) -> float:
    """Rate of new unique word introduction across the message sequence.

    For each message, count how many words appear for the first time.
    Return the average ratio of new words per message.
    """
    if not messages:
        return 0.0

    seen = set()
    total_new_ratio = 0.0
    counted = 0

    for msg in messages:
        words = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", msg.lower()))
        if not words:
            continue
        new_words = words - seen
        total_new_ratio += len(new_words) / len(words)
        seen |= words
        counted += 1

    return total_new_ratio / counted if counted > 0 else 0.0


def classify_commit(message: str) -> str:
    """Classify a commit message into a semantic category."""
    lower = message.lower()
    for category, keywords in CATEGORIES.items():
        if any(kw in lower for kw in keywords):
            return category
    return "other"


def compute_category_entropy(messages: list[str]) -> float:
    """Shannon entropy of the category distribution. Higher = more balanced."""
    if not messages:
        return 0.0

    categories = [classify_commit(msg) for msg in messages]
    freq = Counter(categories)
    total = len(categories)

    entropy = 0.0
    for count in freq.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)

    # Normalize by max possible entropy (log2 of number of categories)
    max_entropy = math.log2(len(CATEGORIES) + 1)  # +1 for "other"
    return entropy / max_entropy if max_entropy > 0 else 0.0


def analyze(repo_path: str, last_n: int = 50) -> dict:
    """Run full vocabulary richness analysis."""
    messages = get_commit_messages(repo_path, last_n)

    if not messages:
        return {
            "score": 0,
            "grade": "MONOTONOUS",
            "total_messages": 0,
            "type_token_ratio": 0.0,
            "hapax_ratio": 0.0,
            "vocabulary_growth": 0.0,
            "category_entropy": 0.0,
            "categories": {},
        }

    tokens = tokenize(messages)
    ttr = compute_type_token_ratio(tokens)
    hapax = compute_hapax_ratio(tokens)
    growth = compute_vocabulary_growth(messages)
    cat_entropy = compute_category_entropy(messages)

    # Score each dimension 0-25
    ttr_score = min(25, ttr * 50)  # TTR ~0.5 maps to 25
    hapax_score = min(25, hapax * 35)  # hapax ~0.7 maps to ~25
    growth_score = min(25, growth * 40)  # growth ~0.6 maps to ~24
    entropy_score = min(25, cat_entropy * 25)  # entropy ~1.0 maps to 25

    total_score = round(ttr_score + hapax_score + growth_score + entropy_score)

    if total_score >= 76:
        grade = "RICH"
    elif total_score >= 51:
        grade = "VARIED"
    elif total_score >= 26:
        grade = "FORMULAIC"
    else:
        grade = "MONOTONOUS"

    categories = dict(Counter(classify_commit(msg) for msg in messages))

    return {
        "score": total_score,
        "grade": grade,
        "total_messages": len(messages),
        "type_token_ratio": round(ttr, 4),
        "hapax_ratio": round(hapax, 4),
        "vocabulary_growth": round(growth, 4),
        "category_entropy": round(cat_entropy, 4),
        "categories": categories,
    }


def format_report(stats: dict) -> str:
    """Format the analysis report."""
    if stats["total_messages"] == 0:
        return "No commit messages to analyze."

    lines = [
        "=== Commit Vocabulary Richness Report ===",
        f"Messages analyzed: {stats['total_messages']}",
        f"Score: {stats['score']}/100 ({stats['grade']})",
        "",
        f"  Type-token ratio:    {stats['type_token_ratio']:.4f}",
        f"  Hapax ratio:         {stats['hapax_ratio']:.4f}",
        f"  Vocabulary growth:   {stats['vocabulary_growth']:.4f}",
        f"  Category entropy:    {stats['category_entropy']:.4f}",
        "",
        "  Category breakdown:",
    ]
    for cat, count in sorted(stats["categories"].items(), key=lambda x: -x[1]):
        pct = count / stats["total_messages"] * 100
        lines.append(f"    {cat:12s}: {count:3d} ({pct:.0f}%)")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Measure commit message vocabulary richness"
    )
    parser.add_argument("--repo", default=".", help="Repository path")
    parser.add_argument("--last", type=int, default=50, help="Analyze last N commits")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    stats = analyze(args.repo, args.last)

    if args.json:
        print(json.dumps(stats, indent=2, ensure_ascii=False))
    else:
        print(format_report(stats))

    # Exit code based on grade
    if stats["grade"] == "MONOTONOUS":
        sys.exit(2)
    elif stats["grade"] == "FORMULAIC":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
