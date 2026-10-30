"""repo_thermoregulation — detect and score repository temperature anomalies.

A living repository has a metabolic temperature: the rate at which its
files change, the distribution of that heat across modules, and the
gradient between its core (actively maintained infrastructure) and its
periphery (specialised or dormant subsystems).  Like a biological
organism, a repo functions best within a narrow temperature band.
Too hot — thrashing, merge conflicts, constant rewrites — and the
tissue burns.  Too cold — months without a commit, modules that no
one reads — and the extremities go necrotic.

The thermoregulation metaphor
-----------------------------

=========================  ===================================================
concept                    what it maps to
=========================  ===================================================
**core temperature**       aggregate change rate across the whole repo
**peripheral temperature** per-file / per-directory change rates
**fever (hyperthermia)**   localised hotspot: a file changed far more
                           often than its peers (possible thrashing)
**hypothermia**            coldspot: a file untouched for much longer
                           than the repo median (possible neglect)
**set point**              expected baseline derived from recent history
**sweating**               burst of commits trying to shed backlog
**shivering**              sporadic, tiny commits trying to stay alive
**thermal gradient**       ratio of hottest to coldest region; high
                           gradient signals uneven attention
**vasodilation**           broadening of change across many files
                           (healthy diffusion of maintenance)
**vasoconstriction**       narrowing of change to few files
                           (attention tunnel — risk of blind spots)
=========================  ===================================================

Signals detected
----------------

1. **file_heat** — per-file commit count in a configurable window.
2. **recency_cold** — days since last modification per file.
3. **author_concentration** — Herfindahl index of commits by author;
   high concentration means few authors carry the thermal load.
4. **change_burstiness** — coefficient of variation of inter-commit
   intervals; high CV means the repo oscillates between fever and
   torpor rather than maintaining steady warmth.
5. **thermal_gradient** — max/min file-heat ratio; measures how
   unevenly attention is distributed.

Scoring
-------

Each signal produces a sub-score 0-100.  The overall thermoregulation
score is inverted (100 − anomaly_score) so that higher is healthier.

========================  ======
signal                    weight
========================  ======
file_heat                 0.25
recency_cold              0.20
author_concentration      0.15
change_burstiness         0.20
thermal_gradient          0.20
========================  ======

State classification
--------------------

==================  =========
score range         state
==================  =========
80 – 100            homeostatic
60 – 79             mild_stress
40 – 59             dysregulated
20 – 39             critical
 0 – 19             thermal_failure
==================  =========

Usage::

    from iamai.repo_thermoregulation import analyze_thermoregulation
    report = analyze_thermoregulation()
    print(report.health_score, report.state)
"""

from __future__ import annotations

import math
import os
import statistics
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ThermalSignal:
    """One thermoregulation anomaly dimension."""

    name: str
    score: float
    weight: float
    evidence: str = ""
    items: List[str] = field(default_factory=list)


@dataclass
class ThermoregReport:
    """Aggregate thermoregulation analysis."""

    anomaly_score: float
    health_score: float
    state: str
    primary_anomaly: str
    signals: List[ThermalSignal] = field(default_factory=list)
    recommendation: str = ""
    files_scanned: int = 0
    window_days: int = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_repo_root(start: Path | None = None) -> Path:
    """Walk upward from *start* (default cwd) until a ``.git`` dir is found."""
    p = (start or Path.cwd()).resolve()
    for parent in [p, *p.parents]:
        if (parent / ".git").is_dir():
            return parent
    return p  # fallback: use wherever we landed


def _iter_tracked_files(repo: Path) -> List[Path]:
    """Return all git-tracked files (text only, skip binary)."""
    try:
        raw = subprocess.check_output(
            ["git", "ls-files"],
            cwd=str(repo),
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    paths: List[Path] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        fp = repo / line
        if fp.suffix in {
            ".py", ".md", ".json", ".yml", ".yaml", ".toml",
            ".txt", ".sh", ".js", ".ts", ".html", ".css",
        }:
            paths.append(fp)
    return paths


def _git_log_file(repo: Path, filepath: Path, window_days: int) -> List[str]:
    """Return commit hashes for *filepath* within the last *window_days*."""
    try:
        raw = subprocess.check_output(
            [
                "git", "log",
                f"--since={window_days} days ago",
                "--format=%H",
                "--", str(filepath.relative_to(repo)),
            ],
            cwd=str(repo),
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [h for h in raw.splitlines() if h.strip()]


def _git_log_all(repo: Path, window_days: int) -> List[str]:
    """Return all commit hashes in the repo within *window_days*."""
    try:
        raw = subprocess.check_output(
            [
                "git", "log",
                f"--since={window_days} days ago",
                "--format=%H",
            ],
            cwd=str(repo),
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [h for h in raw.splitlines() if h.strip()]


def _git_authors(repo: Path, window_days: int) -> Dict[str, int]:
    """Return {author: commit_count} for commits in *window_days*."""
    try:
        raw = subprocess.check_output(
            [
                "git", "log",
                f"--since={window_days} days ago",
                "--format=%aN",
            ],
            cwd=str(repo),
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}
    counts: Dict[str, int] = {}
    for line in raw.splitlines():
        author = line.strip()
        if author:
            counts[author] = counts.get(author, 0) + 1
    return counts


def _last_modified(repo: Path, filepath: Path) -> Optional[datetime]:
    """Return the datetime of the last commit touching *filepath*."""
    try:
        raw = subprocess.check_output(
            [
                "git", "log", "-1",
                "--format=%aI",
                "--", str(filepath.relative_to(repo)),
            ],
            cwd=str(repo),
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    ts = raw.strip()
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _inter_commit_intervals(repo: Path, window_days: int) -> List[float]:
    """Return list of intervals (hours) between consecutive commits."""
    try:
        raw = subprocess.check_output(
            [
                "git", "log",
                f"--since={window_days} days ago",
                "--format=%aI",
                "--reverse",
            ],
            cwd=str(repo),
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    timestamps: List[datetime] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            timestamps.append(datetime.fromisoformat(line))
        except ValueError:
            continue
    if len(timestamps) < 2:
        return []
    intervals: List[float] = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds() / 3600.0
        intervals.append(delta)
    return intervals


# ---------------------------------------------------------------------------
# Signal detectors
# ---------------------------------------------------------------------------


def detect_file_heat(
    repo: Path,
    window_days: int = 30,
    hotspot_threshold: float = 3.0,
    sample_size: int = 100,
) -> ThermalSignal:
    """Detect files changed disproportionately often (hotspots).

    A file is a hotspot if its commit count exceeds *hotspot_threshold*
    standard deviations above the mean.
    """
    files = _iter_tracked_files(repo)
    if not files:
        return ThermalSignal(
            name="file_heat", score=0.0, weight=0.25,
            evidence="no tracked files found",
        )

    # Sample to keep runtime reasonable for large repos
    if len(files) > sample_size:
        import random
        rng = random.Random(42)
        files = rng.sample(files, sample_size)

    commit_counts: List[int] = []
    hotspots: List[str] = []
    for fp in files:
        commits = _git_log_file(repo, fp, window_days)
        commit_counts.append(len(commits))
        if len(commits) > 0:
            # We'll check for outliers after computing stats
            pass

    if not commit_counts or max(commit_counts) == 0:
        return ThermalSignal(
            name="file_heat", score=0.0, weight=0.25,
            evidence="no commits in window",
        )

    mean_c = statistics.mean(commit_counts)
    if len(commit_counts) >= 2:
        std_c = statistics.stdev(commit_counts)
    else:
        std_c = 0.0

    threshold_val = mean_c + hotspot_threshold * max(std_c, 1.0)
    for fp, count in zip(files, commit_counts):
        if count > threshold_val:
            hotspots.append(f"{fp.relative_to(repo)} ({count} commits)")

    # Score: ratio of hotspots to total files, scaled
    hotspot_ratio = len(hotspots) / len(files) if files else 0.0
    score = min(100.0, hotspot_ratio * 500.0)  # 20% hotspots → 100

    return ThermalSignal(
        name="file_heat",
        score=round(score, 2),
        weight=0.25,
        evidence=f"{len(hotspots)} hotspot(s) in {len(files)} files "
                 f"(mean={mean_c:.1f}, threshold={threshold_val:.1f})",
        items=hotspots[:20],
    )


def detect_recency_cold(
    repo: Path,
    window_days: int = 30,
    cold_threshold_days: float = 60.0,
    sample_size: int = 100,
) -> ThermalSignal:
    """Detect files not modified for longer than *cold_threshold_days*."""
    files = _iter_tracked_files(repo)
    if not files:
        return ThermalSignal(
            name="recency_cold", score=0.0, weight=0.20,
            evidence="no tracked files found",
        )

    if len(files) > sample_size:
        import random
        rng = random.Random(42)
        files = rng.sample(files, sample_size)

    now = datetime.now(timezone.utc)
    cold_files: List[str] = []
    ages_days: List[float] = []

    for fp in files:
        last = _last_modified(repo, fp)
        if last is None:
            cold_files.append(f"{fp.relative_to(repo)} (unknown)")
            continue
        age = (now - last).total_seconds() / 86400.0
        ages_days.append(age)
        if age > cold_threshold_days:
            cold_files.append(
                f"{fp.relative_to(repo)} ({age:.0f} days cold)"
            )

    if not ages_days:
        return ThermalSignal(
            name="recency_cold", score=0.0, weight=0.20,
            evidence="no timestamp data available",
        )

    cold_ratio = len(cold_files) / len(files)
    score = min(100.0, cold_ratio * 200.0)  # 50% cold → 100

    return ThermalSignal(
        name="recency_cold",
        score=round(score, 2),
        weight=0.20,
        evidence=f"{len(cold_files)} cold file(s) in {len(files)} "
                 f"(median age={statistics.median(ages_days):.0f}d, "
                 f"threshold={cold_threshold_days:.0f}d)",
        items=cold_files[:20],
    )


def detect_author_concentration(
    repo: Path,
    window_days: int = 30,
) -> ThermalSignal:
    """Measure Herfindahl index of commit authorship.

    HHI = sum of (share_i)^2 for each author.  1.0 = monopoly,
    1/N = perfectly distributed among N authors.
    """
    authors = _git_authors(repo, window_days)
    if not authors:
        return ThermalSignal(
            name="author_concentration", score=0.0, weight=0.15,
            evidence="no author data available",
        )

    total = sum(authors.values())
    if total == 0:
        return ThermalSignal(
            name="author_concentration", score=0.0, weight=0.15,
            evidence="zero commits in window",
        )

    shares = [count / total for count in authors.values()]
    hhi = sum(s * s for s in shares)

    # Single author → maximum concentration concern
    n_authors = len(authors)
    if n_authors == 1:
        # Not necessarily bad for a personal repo, but flag it
        score = 40.0  # moderate — single-author repos are common
    else:
        # Scale: HHI of 1/N is perfect, 1.0 is monopoly
        ideal = 1.0 / n_authors if n_authors > 0 else 1.0
        # Normalise: 0 when HHI == ideal, 100 when HHI == 1.0
        if ideal < 1.0:
            norm = (hhi - ideal) / (1.0 - ideal)
        else:
            norm = 0.0
        score = min(100.0, max(0.0, norm * 100.0))

    top_authors = sorted(authors.items(), key=lambda x: -x[1])[:5]
    items = [f"{name}: {count} ({count/total*100:.0f}%)"
             for name, count in top_authors]

    return ThermalSignal(
        name="author_concentration",
        score=round(score, 2),
        weight=0.15,
        evidence=f"HHI={hhi:.3f}, {n_authors} author(s), "
                 f"{total} commit(s)",
        items=items,
    )


def detect_change_burstiness(
    repo: Path,
    window_days: int = 30,
    healthy_cv: float = 1.5,
) -> ThermalSignal:
    """Measure coefficient of variation of inter-commit intervals.

    Low CV → steady rhythm (good thermoregulation).
    High CV → alternating fever and torpor (dysregulated).
    """
    intervals = _inter_commit_intervals(repo, window_days)
    if len(intervals) < 3:
        return ThermalSignal(
            name="change_burstiness", score=0.0, weight=0.20,
            evidence="insufficient commit data for burstiness analysis",
        )

    mean_iv = statistics.mean(intervals)
    std_iv = statistics.stdev(intervals)
    if mean_iv == 0:
        cv = 0.0
    else:
        cv = std_iv / mean_iv

    # Score: CV at or below healthy_cv → 0, linearly up to 100 at CV=5
    if cv <= healthy_cv:
        score = 0.0
    else:
        score = min(100.0, (cv - healthy_cv) / (5.0 - healthy_cv) * 100.0)

    # Find the longest and shortest gaps
    sorted_iv = sorted(intervals)
    shortest = sorted_iv[0]
    longest = sorted_iv[-1]
    median_iv = statistics.median(intervals)

    return ThermalSignal(
        name="change_burstiness",
        score=round(score, 2),
        weight=0.20,
        evidence=f"CV={cv:.2f} (healthy≤{healthy_cv}), "
                 f"median gap={median_iv:.1f}h, "
                 f"range=[{shortest:.2f}h, {longest:.1f}h]",
    )


def detect_thermal_gradient(
    repo: Path,
    window_days: int = 30,
    sample_size: int = 100,
) -> ThermalSignal:
    """Measure the ratio of hottest to coldest directory's commit rate.

    High gradient means attention is concentrated in a few areas while
    others freeze.  Gradient of 1.0 = perfectly uniform.
    """
    files = _iter_tracked_files(repo)
    if not files:
        return ThermalSignal(
            name="thermal_gradient", score=0.0, weight=0.20,
            evidence="no tracked files",
        )

    if len(files) > sample_size:
        import random
        rng = random.Random(42)
        files = rng.sample(files, sample_size)

    # Group by top-level directory
    dir_counts: Dict[str, int] = {}
    for fp in files:
        try:
            rel = fp.relative_to(repo)
        except ValueError:
            continue
        parts = rel.parts
        top_dir = parts[0] if len(parts) > 1 else "(root)"
        dir_counts[top_dir] = dir_counts.get(top_dir, 0)

    # Count commits per directory
    dir_commits: Dict[str, int] = {}
    for top_dir in dir_counts:
        dir_path = repo / top_dir
        if not dir_path.exists():
            continue
        try:
            raw = subprocess.check_output(
                [
                    "git", "log",
                    f"--since={window_days} days ago",
                    "--format=%H",
                    "--", top_dir,
                ],
                cwd=str(repo),
                stderr=subprocess.DEVNULL,
                text=True,
            )
            count = len([l for l in raw.splitlines() if l.strip()])
            dir_commits[top_dir] = count
        except (subprocess.CalledProcessError, FileNotFoundError):
            dir_commits[top_dir] = 0

    if not dir_commits or len(dir_commits) < 2:
        return ThermalSignal(
            name="thermal_gradient", score=0.0, weight=0.20,
            evidence="fewer than 2 directories with activity",
        )

    counts = list(dir_commits.values())
    max_c = max(counts)
    # Replace zeros with 0.5 to avoid division by zero
    nonzero = [c if c > 0 else 0.5 for c in counts]
    min_c = min(nonzero)
    gradient = max_c / min_c if min_c > 0 else max_c

    # Score: gradient of 1 → 0, gradient of 50+ → 100
    score = min(100.0, max(0.0, (gradient - 1.0) / 49.0 * 100.0))

    sorted_dirs = sorted(dir_commits.items(), key=lambda x: -x[1])
    items = [f"{d}: {c} commits" for d, c in sorted_dirs[:10]]

    return ThermalSignal(
        name="thermal_gradient",
        score=round(score, 2),
        weight=0.20,
        evidence=f"gradient={gradient:.1f}x across {len(dir_commits)} "
                 f"directories (hottest: {sorted_dirs[0][0]} "
                 f"with {sorted_dirs[0][1]} commits)",
        items=items,
    )


# ---------------------------------------------------------------------------
# Aggregate analysis
# ---------------------------------------------------------------------------


def analyze_thermoregulation(
    repo: Path | None = None,
    window_days: int = 30,
) -> ThermoregReport:
    """Run all thermoregulation detectors and return an aggregate report."""
    root = repo or _find_repo_root()

    signals = [
        detect_file_heat(root, window_days),
        detect_recency_cold(root, window_days),
        detect_author_concentration(root, window_days),
        detect_change_burstiness(root, window_days),
        detect_thermal_gradient(root, window_days),
    ]

    # Weighted anomaly score
    total_weight = sum(s.weight for s in signals)
    if total_weight == 0:
        weighted_score = 0.0
    else:
        weighted_score = sum(s.score * s.weight for s in signals) / total_weight

    health = round(100.0 - weighted_score, 2)
    anomaly = round(weighted_score, 2)
    state = _classify(health)
    primary = _primary_anomaly(signals)
    rec = _recommend(health, state, primary, signals)
    n_files = len(_iter_tracked_files(root))

    return ThermoregReport(
        anomaly_score=anomaly,
        health_score=health,
        state=state,
        primary_anomaly=primary,
        signals=signals,
        recommendation=rec,
        files_scanned=n_files,
        window_days=window_days,
    )


def _classify(health: float) -> str:
    """Map health score to state label."""
    if health >= 80:
        return "homeostatic"
    if health >= 60:
        return "mild_stress"
    if health >= 40:
        return "dysregulated"
    if health >= 20:
        return "critical"
    return "thermal_failure"


def _primary_anomaly(signals: Sequence[ThermalSignal]) -> str:
    """Return the name of the highest-scoring signal."""
    if not signals:
        return "none"
    worst = max(signals, key=lambda s: s.score)
    return worst.name if worst.score > 0 else "none"


def _recommend(
    health: float,
    state: str,
    primary: str,
    signals: Sequence[ThermalSignal],
) -> str:
    """Generate a human-readable recommendation."""
    if health >= 80:
        return (
            "Repository thermoregulation is within normal range. "
            "Continue current maintenance cadence."
        )

    parts: List[str] = []

    if primary == "file_heat":
        parts.append(
            "Hotspot detected: some files are changing much more often "
            "than their peers. Consider whether this indicates genuine "
            "iterative development or thrashing (repeated fix-revert cycles)."
        )
    elif primary == "recency_cold":
        parts.append(
            "Cold regions detected: several files have not been touched "
            "in over two months. Review for dead code, orphan modules, "
            "or areas that need attention before they become unfamiliar."
        )
    elif primary == "author_concentration":
        parts.append(
            "Author concentration is elevated. Consider distributing "
            "maintenance tasks across more contributors to reduce "
            "bus-factor risk."
        )
    elif primary == "change_burstiness":
        parts.append(
            "Commit rhythm is bursty — alternating between intense "
            "activity and long silences. A steadier cadence reduces "
            "merge conflicts and makes the repo easier to follow."
        )
    elif primary == "thermal_gradient":
        parts.append(
            "Attention is concentrated in a few directories while "
            "others go cold. Consider rotating maintenance focus "
            "to prevent neglected subsystems from accumulating debt."
        )

    if health < 40:
        parts.append(
            "Thermoregulation is significantly impaired. Prioritise "
            "a caretaker visit to address the primary anomaly before "
            "it cascades into other subsystems."
        )
    elif health < 60:
        parts.append(
            "Schedule a review of the primary anomaly within the "
            "next few caretaker visits."
        )

    return " ".join(parts)


def thermoregulation_summary(report: ThermoregReport) -> str:
    """Return a compact human-readable summary of the report."""
    lines = [
        f"Thermoregulation: {report.state} "
        f"(health={report.health_score}, anomaly={report.anomaly_score})",
        f"  Files scanned: {report.files_scanned}  "
        f"Window: {report.window_days}d",
        f"  Primary anomaly: {report.primary_anomaly}",
    ]
    for sig in report.signals:
        lines.append(
            f"  [{sig.name}] score={sig.score} weight={sig.weight} "
            f"— {sig.evidence}"
        )
    if report.recommendation:
        lines.append(f"  → {report.recommendation}")
    return "\n".join(lines)
