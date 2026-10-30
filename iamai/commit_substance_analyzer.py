"""commit_substance_analyzer — detect whether commits carry real substance.

The writing pipeline produces a high volume of commits.  Many are
genuinely useful (new modules, bug fixes, notes); others are boilerplate
strokes that pad the log without adding information.  A caretaker needs
to know: *is the pipeline producing real work, or just noise?*

This module classifies each commit into one of three intent buckets:

    ┌─────────────┬──────────────────────────────────────────────────┐
    │ Label       │ Meaning                                          │
    ├─────────────┼──────────────────────────────────────────────────┤
    │ substantial │ New module, bug fix, meaningful note, refactor   │
    │ routine     │ Regular stroke with varied content               │
    │ filler      │ Template-driven, repetitive, low-information     │
    └─────────────┴──────────────────────────────────────────────────┘

Detection signals
-----------------
1. **Template ratio** — fraction of lines matching known boilerplate
   patterns (``## stroke NNNNN``, ``At this moment:``, repeated aphorisms).
2. **Lexical novelty** — Jaccard distance between this commit's diff
   and the previous N commits.  Low novelty → filler.
3. **Net additions** — pure line additions minus deletions, normalised
   against file size.  Copy-paste strokes have high gross additions but
   near-zero net information.
4. **Message entropy** — commit messages that are byte-identical to
   recent messages (except the stroke number) are flagged as template.

Each signal is scored 0.0–1.0; a weighted sum decides the label.

    substance = 0.35 * novelty + 0.25 * (1 - template_ratio)
              + 0.25 * net_info + 0.15 * message_entropy

Thresholds:
    substance >= 0.65  → substantial
    substance >= 0.40  → routine
    substance <  0.40  → filler

Usage
-----
    from iamai.commit_substance_analyzer import CommitSubstanceAnalyzer
    csa = CommitSubstanceAnalyzer(repo_path)
    report = csa.analyze_last(n=20)
    for entry in report.entries:
        print(entry.sha[:7], entry.label, f"{entry.score:.2f}")
    print(f"substance ratio: {report.substance_ratio:.1%}")
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# Known boilerplate patterns
# ---------------------------------------------------------------------------
_BOILERPLATE_PATTERNS = [
    re.compile(r"^## stroke \d+"),
    re.compile(r"^At this moment:"),
    re.compile(r"^automation fails quietly"),
    re.compile(r"^deleting a file is progress too"),
    re.compile(r"^naming is hard"),
    re.compile(r"^the useful abstraction"),
    re.compile(r"^most architecture is choosing"),
    re.compile(r"^commit history is the only honest"),
    re.compile(r"catch-up: commit pending changes"),
    re.compile(r"^## stroke \d+\s*$"),
]

# Aphorism bank — lines that appear verbatim across many strokes
_APHTHORISMS = {
    "automation fails quietly, so the log has to say something even when nothing happened.",
    "deleting a file is progress too, eventually.",
    "naming is hard because a bad name is cheap to type and expensive to keep.",
    "the useful abstraction deletes a branch, it does not add a class.",
    "most architecture is choosing which coupling you will live with.",
    "commit history is the only honest documentation because it cannot be backdated.",
}


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
SUBSTANTIAL_THRESHOLD = 0.65
ROUTINE_THRESHOLD = 0.40
NOVELTY_WINDOW = 5          # compare against last N commits
TEMPLATE_RATIO_WEIGHT = 0.25
NOVELTY_WEIGHT = 0.35
NET_INFO_WEIGHT = 0.25
MESSAGE_ENTROPY_WEIGHT = 0.15


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class CommitEntry:
    """Substance analysis result for a single commit."""

    sha: str = ""
    message: str = ""
    label: str = "routine"        # substantial | routine | filler
    score: float = 0.5
    template_ratio: float = 0.0
    novelty: float = 0.5
    net_info: float = 0.5
    message_entropy: float = 0.5
    files_changed: int = 0
    lines_added: int = 0
    lines_deleted: int = 0


@dataclass
class SubstanceReport:
    """Aggregate substance report over N commits."""

    entries: List[CommitEntry] = field(default_factory=list)

    @property
    def substance_ratio(self) -> float:
        """Fraction of commits that are substantial or routine."""
        if not self.entries:
            return 0.0
        good = sum(1 for e in self.entries if e.label != "filler")
        return good / len(self.entries)

    @property
    def filler_count(self) -> int:
        return sum(1 for e in self.entries if e.label == "filler")

    @property
    def substantial_count(self) -> int:
        return sum(1 for e in self.entries if e.label == "substantial")

    @property
    def routine_count(self) -> int:
        return sum(1 for e in self.entries if e.label == "routine")

    @property
    def avg_score(self) -> float:
        if not self.entries:
            return 0.0
        return sum(e.score for e in self.entries) / len(self.entries)

    @property
    def summary(self) -> str:
        n = len(self.entries)
        return (
            f"substance: {self.substance_ratio:.0%} real "
            f"({self.substantial_count} substantial, "
            f"{self.routine_count} routine, "
            f"{self.filler_count} filler) "
            f"over {n} commits, avg {self.avg_score:.2f}"
        )


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------
class CommitSubstanceAnalyzer:
    """Analyse commit substance for a writing-pipeline repo."""

    def __init__(self, repo_path: str | Path | None = None):
        self.repo = Path(repo_path) if repo_path else Path(__file__).resolve().parent.parent

    # -- git helpers --------------------------------------------------------

    def _git(self, *args: str, timeout: int = 15) -> str:
        cmd = ["git", "-C", str(self.repo)] + list(args)
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.stdout

    def _recent_shas(self, n: int = 20) -> List[str]:
        raw = self._git("log", f"--max-count={n}", "--format=%H")
        return [s for s in raw.splitlines() if s.strip()]

    def _commit_message(self, sha: str) -> str:
        return self._git("log", "-1", "--format=%B", sha).strip()

    def _commit_diff(self, sha: str) -> str:
        return self._git("diff", f"{sha}~1..{sha}", "--stat", "--patch")

    def _commit_numstat(self, sha: str) -> tuple[int, int, int]:
        """Return (files_changed, lines_added, lines_deleted)."""
        raw = self._git("diff", "--numstat", f"{sha}~1..{sha}")
        files = 0
        added = 0
        deleted = 0
        for line in raw.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                files += 1
                a = parts[0].strip()
                d = parts[1].strip()
                if a != "-":
                    added += int(a)
                if d != "-":
                    deleted += int(d)
        return files, added, deleted

    # -- signal computations -----------------------------------------------

    @staticmethod
    def template_ratio(diff_text: str) -> float:
        """Fraction of added lines that match boilerplate patterns."""
        added_lines = [
            l[1:].strip()
            for l in diff_text.splitlines()
            if l.startswith("+") and not l.startswith("+++")
        ]
        if not added_lines:
            return 0.0
        hits = 0
        for line in added_lines:
            for pat in _BOILERPLATE_PATTERNS:
                if pat.search(line):
                    hits += 1
                    break
            else:
                # Check aphorism bank (fuzzy: strip stroke number)
                cleaned = re.sub(r"## stroke \d+", "", line).strip()
                if cleaned in _APHTHORISMS:
                    hits += 1
        return hits / len(added_lines)

    @staticmethod
    def lexical_novelty(current_diff: str, previous_diffs: Sequence[str]) -> float:
        """Jaccard-based novelty against previous N commits.

        Returns 1.0 when completely novel, 0.0 when identical.
        """
        if not previous_diffs:
            return 1.0

        def _tokens(text: str) -> set:
            words = re.findall(r"\w+", text.lower())
            return set(words)

        current_tokens = _tokens(current_diff)
        if not current_tokens:
            return 0.0

        similarities = []
        for prev in previous_diffs:
            prev_tokens = _tokens(prev)
            if not prev_tokens:
                similarities.append(0.0)
                continue
            intersection = current_tokens & prev_tokens
            union = current_tokens | prev_tokens
            jaccard = len(intersection) / len(union) if union else 0.0
            similarities.append(jaccard)

        avg_similarity = sum(similarities) / len(similarities)
        return 1.0 - avg_similarity  # novelty = 1 - similarity

    @staticmethod
    def net_info_score(files: int, added: int, deleted: int) -> float:
        """Score based on net meaningful additions.

        Pure copy-paste (high additions, zero deletions, single file)
        scores low.  Refactors (balanced add/delete, multi-file) score high.
        """
        if files == 0 and added == 0:
            return 0.0
        total_changes = added + deleted
        if total_changes == 0:
            return 0.0

        # Multi-file bonus: changes spread across files are more likely real
        file_diversity = min(files / 5.0, 1.0)

        # Balance ratio: pure additions are suspicious; balanced is better
        if added == 0 or deleted == 0:
            balance = 0.3  # one-sided
        else:
            ratio = min(added, deleted) / max(added, deleted)
            balance = 0.3 + 0.7 * ratio  # 0.3–1.0

        # Volume (log scale): very large diffs aren't proportionally more useful
        import math
        volume = math.log1p(total_changes) / math.log1p(500)  # normalise
        volume = min(volume, 1.0)

        return 0.4 * balance + 0.3 * file_diversity + 0.3 * volume

    @staticmethod
    def message_entropy_score(message: str, recent_messages: Sequence[str]) -> float:
        """Score based on how different this message is from recent ones.

        Byte-identical messages (except stroke numbers) → low score.
        """
        if not recent_messages:
            return 1.0

        def _normalise(msg: str) -> str:
            # Strip stroke numbers and timestamps for comparison
            msg = re.sub(r"stroke \d+", "stroke N", msg)
            msg = re.sub(r"\d{4}-\d{2}-\d{2}", "DATE", msg)
            msg = re.sub(r"\d+:\d+:\d+", "TIME", msg)
            msg = re.sub(r"[0-9a-f]{7,40}", "SHA", msg)
            return msg.strip()

        norm_current = _normalise(message)
        if not norm_current:
            return 0.5

        matches = 0
        for prev in recent_messages:
            if _normalise(prev) == norm_current:
                matches += 1

        # 0 matches → 1.0 (fully novel); all match → 0.0
        return 1.0 - (matches / len(recent_messages))

    # -- classification ----------------------------------------------------

    @staticmethod
    def classify(score: float) -> str:
        if score >= SUBSTANTIAL_THRESHOLD:
            return "substantial"
        if score >= ROUTINE_THRESHOLD:
            return "routine"
        return "filler"

    # -- main analysis -----------------------------------------------------

    def analyze_commit(self, sha: str,
                       prev_diffs: Optional[Sequence[str]] = None,
                       prev_messages: Optional[Sequence[str]] = None) -> CommitEntry:
        """Analyse a single commit by SHA."""
        message = self._commit_message(sha)
        diff = self._commit_diff(sha)
        files, added, deleted = self._commit_numstat(sha)

        t_ratio = self.template_ratio(diff)
        novelty = self.lexical_novelty(diff, prev_diffs or [])
        net_info = self.net_info_score(files, added, deleted)
        msg_entropy = self.message_entropy_score(message, prev_messages or [])

        score = (
            NOVELTY_WEIGHT * novelty
            + TEMPLATE_RATIO_WEIGHT * (1.0 - t_ratio)
            + NET_INFO_WEIGHT * net_info
            + MESSAGE_ENTROPY_WEIGHT * msg_entropy
        )

        return CommitEntry(
            sha=sha,
            message=message.split("\n")[0][:120],
            label=self.classify(score),
            score=score,
            template_ratio=t_ratio,
            novelty=novelty,
            net_info=net_info,
            message_entropy=msg_entropy,
            files_changed=files,
            lines_added=added,
            lines_deleted=deleted,
        )

    def analyze_last(self, n: int = 20) -> SubstanceReport:
        """Analyse the last *n* commits and return a SubstanceReport."""
        shas = self._recent_shas(n)
        if not shas:
            return SubstanceReport()

        # Collect diffs and messages for novelty context
        all_diffs: List[str] = []
        all_messages: List[str] = []
        entries: List[CommitEntry] = []

        for i, sha in enumerate(shas):
            prev_diffs = all_diffs[:NOVELTY_WINDOW]
            prev_msgs = all_messages[:NOVELTY_WINDOW]

            entry = self.analyze_commit(sha, prev_diffs, prev_msgs)
            entries.append(entry)

            diff = self._commit_diff(sha)
            msg = self._commit_message(sha)
            all_diffs.insert(0, diff)
            all_messages.insert(0, msg)

        return SubstanceReport(entries=entries)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    import argparse
    p = argparse.ArgumentParser(description="Commit substance analyzer")
    p.add_argument("--repo", default=None, help="repo path (default: auto)")
    p.add_argument("-n", "--count", type=int, default=20,
                   help="number of recent commits to analyse")
    p.add_argument("--json", action="store_true", help="output as JSON")
    args = p.parse_args()

    csa = CommitSubstanceAnalyzer(args.repo)
    report = csa.analyze_last(n=args.count)

    if args.json:
        import json
        print(json.dumps({
            "substance_ratio": round(report.substance_ratio, 3),
            "filler_count": report.filler_count,
            "substantial_count": report.substantial_count,
            "routine_count": report.routine_count,
            "avg_score": round(report.avg_score, 3),
            "entries": [
                {
                    "sha": e.sha[:7],
                    "label": e.label,
                    "score": round(e.score, 3),
                    "template_ratio": round(e.template_ratio, 3),
                    "novelty": round(e.novelty, 3),
                    "message": e.message[:80],
                }
                for e in report.entries
            ],
        }, indent=2))
    else:
        print(report.summary)
        print()
        for e in report.entries:
            tag = {"substantial": "●", "routine": "○", "filler": "·"}[e.label]
            print(f"  {tag} {e.sha[:7]}  {e.score:.2f}  {e.label:<12}  {e.message[:60]}")


if __name__ == "__main__":
    main()
