"""commit_fragmentation — detect scattered micro-commits that belong together.

A well-paced writer batches related changes into cohesive commits.  When
each tiny change gets its own commit — a one-line fix here, a whitespace
tweak there — the history becomes noisy and bisect-unfriendly.  This
module fills the gap between:

- ``commit_redundancy``, which flags *overlapping* successive commits but
  says nothing about commits that are disjoint yet logically related;
- ``commit_substance``, which scores individual commit quality but does
  not reason about grouping;
- ``commit_session_segmenter``, which groups commits by time gaps but
  does not evaluate whether the grouping makes semantic sense.

The fragmentation analyser answers: *are consecutive small commits
touching related areas, and would batching them have produced a more
coherent history?*

Metrics
-------

========================  ================================================
metric                    what it measures
========================  ================================================
file_cohesion             Jaccard similarity of file sets across a
                          candidate cluster — higher means tighter
temporal_tightness        inverse of max gap within cluster normalised
                          by mean inter-commit gap
change_volume_ratio       sum of small-commit sizes vs. what a single
                          merged commit would look like
fragmentation_score       weighted blend: 0 = well-batched,
                          1 = maximally scattered
========================  ================================================

Usage::

    from iamai.commit_fragmentation import (
        detect_clusters, fragmentation_score, FragmentationReport,
    )

    commits = [...]  # list of dicts: hash, files, message, lines_changed, timestamp
    clusters = detect_clusters(commits, max_gap_seconds=300)
    report = fragmentation_score(clusters)
    print(report.score)       # 0.0 .. 1.0
    print(report.verdict)     # "cohesive" / "mild" / "fragmented"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# defaults
# ---------------------------------------------------------------------------

DEFAULT_MAX_GAP_SECONDS = 300       # 5 min: commits within this are cluster candidates
DEFAULT_MIN_CLUSTER_SIZE = 3        # need at least 3 commits to call it fragmented
DEFAULT_SMALL_COMMIT_LINES = 10     # commits with <= this many lines are "small"
DEFAULT_WEIGHTS = {
    "file_cohesion": 0.35,
    "temporal_tightness": 0.30,
    "change_volume_ratio": 0.35,
}
VERDICT_THRESHOLDS = {
    "cohesive": 0.25,
    "mild": 0.55,
    # above mild threshold → "fragmented"
}


# ---------------------------------------------------------------------------
# data classes
# ---------------------------------------------------------------------------

@dataclass
class CommitInfo:
    """Minimal commit representation for fragmentation analysis."""
    hash: str = ""
    files: List[str] = field(default_factory=list)
    message: str = ""
    lines_changed: int = 0
    timestamp: float = 0.0          # Unix epoch


@dataclass
class Cluster:
    """A group of consecutive commits that are candidates for batching."""
    commits: List[CommitInfo] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.commits)

    @property
    def file_union(self) -> set:
        s: set = set()
        for c in self.commits:
            s.update(c.files)
        return s

    @property
    def total_lines(self) -> int:
        return sum(c.lines_changed for c in self.commits)

    @property
    def max_gap(self) -> float:
        if self.size < 2:
            return 0.0
        gaps = [
            self.commits[i + 1].timestamp - self.commits[i].timestamp
            for i in range(self.size - 1)
        ]
        return max(gaps)

    @property
    def mean_gap(self) -> float:
        if self.size < 2:
            return 0.0
        gaps = [
            self.commits[i + 1].timestamp - self.commits[i].timestamp
            for i in range(self.size - 1)
        ]
        return sum(gaps) / len(gaps)


@dataclass
class ClusterReport:
    """Per-cluster fragmentation metrics."""
    cluster: Cluster
    file_cohesion: float = 0.0
    temporal_tightness: float = 0.0
    change_volume_ratio: float = 0.0
    score: float = 0.0


@dataclass
class FragmentationReport:
    """Aggregate fragmentation across all detected clusters."""
    clusters: List[ClusterReport] = field(default_factory=list)
    score: float = 0.0
    verdict: str = "cohesive"
    total_fragmented_commits: int = 0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two sets."""
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _file_cohesion(cluster: Cluster) -> float:
    """Average pairwise Jaccard between consecutive commits in cluster."""
    if cluster.size < 2:
        return 0.0
    scores = []
    for i in range(cluster.size - 1):
        a = set(cluster.commits[i].files)
        b = set(cluster.commits[i + 1].files)
        scores.append(_jaccard(a, b))
    return sum(scores) / len(scores)


def _temporal_tightness(cluster: Cluster, global_mean_gap: float) -> float:
    """How tightly packed the cluster is relative to overall cadence.

    Returns 1.0 when max internal gap ≤ global mean (very tight),
    decaying toward 0.0 as the max gap grows.
    """
    if cluster.size < 2 or global_mean_gap <= 0:
        return 0.0
    ratio = cluster.max_gap / global_mean_gap
    # Clamp: ratio ≤ 1 → tightness 1.0; ratio ≥ 3 → tightness 0.0
    if ratio <= 1.0:
        return 1.0
    if ratio >= 3.0:
        return 0.0
    return (3.0 - ratio) / 2.0


def _change_volume_ratio(cluster: Cluster, small_threshold: int) -> float:
    """Fraction of commits in the cluster that are 'small'.

    1.0 = every commit is tiny (high fragmentation potential).
    0.0 = every commit carries substantial change.
    """
    if cluster.size == 0:
        return 0.0
    small_count = sum(
        1 for c in cluster.commits if c.lines_changed <= small_threshold
    )
    return small_count / cluster.size


def _verdict(score: float) -> str:
    if score <= VERDICT_THRESHOLDS["cohesive"]:
        return "cohesive"
    if score <= VERDICT_THRESHOLDS["mild"]:
        return "mild"
    return "fragmented"


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def _global_mean_gap(commits: Sequence[CommitInfo]) -> float:
    if len(commits) < 2:
        return 0.0
    gaps = [
        commits[i + 1].timestamp - commits[i].timestamp
        for i in range(len(commits) - 1)
    ]
    return sum(gaps) / len(gaps) if gaps else 0.0


def detect_clusters(
    commits: Sequence[CommitInfo | Dict[str, Any]],
    max_gap_seconds: float = DEFAULT_MAX_GAP_SECONDS,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
) -> List[Cluster]:
    """Group consecutive commits separated by ≤ *max_gap_seconds*.

    Only clusters with ≥ *min_cluster_size* commits are returned.
    Accepts ``CommitInfo`` instances or plain dicts with keys:
    ``hash``, ``files``, ``message``, ``lines_changed``, ``timestamp``.
    """
    if not commits:
        return []

    normalised: List[CommitInfo] = []
    for c in commits:
        if isinstance(c, CommitInfo):
            normalised.append(c)
        else:
            normalised.append(CommitInfo(
                hash=c.get("hash", ""),
                files=c.get("files", []),
                message=c.get("message", ""),
                lines_changed=c.get("lines_changed", 0),
                timestamp=float(c.get("timestamp", 0)),
            ))

    clusters: List[Cluster] = []
    current: List[CommitInfo] = [normalised[0]]

    for i in range(1, len(normalised)):
        gap = normalised[i].timestamp - normalised[i - 1].timestamp
        if gap <= max_gap_seconds:
            current.append(normalised[i])
        else:
            if len(current) >= min_cluster_size:
                clusters.append(Cluster(commits=list(current)))
            current = [normalised[i]]

    if len(current) >= min_cluster_size:
        clusters.append(Cluster(commits=list(current)))

    return clusters


def analyse_cluster(
    cluster: Cluster,
    global_mean_gap: float,
    small_threshold: int = DEFAULT_SMALL_COMMIT_LINES,
    weights: Optional[Dict[str, float]] = None,
) -> ClusterReport:
    """Compute fragmentation metrics for a single cluster."""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}

    fc = _file_cohesion(cluster)
    tt = _temporal_tightness(cluster, global_mean_gap)
    cvr = _change_volume_ratio(cluster, small_threshold)

    # Score: high cohesion + high temporal tightness + high small-commit
    # ratio → more fragmented.  Invert cohesion so that *low* overlap
    # between neighbours means they were doing separate things (good).
    score = (
        w["file_cohesion"] * fc
        + w["temporal_tightness"] * tt
        + w["change_volume_ratio"] * cvr
    )
    score = max(0.0, min(1.0, score))

    return ClusterReport(
        cluster=cluster,
        file_cohesion=round(fc, 4),
        temporal_tightness=round(tt, 4),
        change_volume_ratio=round(cvr, 4),
        score=round(score, 4),
    )


def fragmentation_score(
    clusters: Sequence[Cluster] | Sequence[ClusterReport],
    commits: Optional[Sequence[CommitInfo | Dict[str, Any]]] = None,
    small_threshold: int = DEFAULT_SMALL_COMMIT_LINES,
    weights: Optional[Dict[str, float]] = None,
) -> FragmentationReport:
    """Aggregate fragmentation across clusters.

    If raw ``Cluster`` objects are passed, they are analysed first.
    The overall score is the size-weighted mean of cluster scores.
    """
    if not clusters:
        return FragmentationReport(score=0.0, verdict="cohesive")

    # Analyse if needed
    reports: List[ClusterReport] = []
    for c in clusters:
        if isinstance(c, ClusterReport):
            reports.append(c)
        else:
            gmg = 0.0
            if commits:
                gmg = _global_mean_gap(
                    [CommitInfo(**x) if isinstance(x, dict) else x for x in commits]
                )
            else:
                gmg = c.mean_gap * 3  # rough fallback
            reports.append(analyse_cluster(c, gmg, small_threshold, weights))

    # Size-weighted score
    total_size = sum(r.cluster.size for r in reports)
    if total_size == 0:
        return FragmentationReport(score=0.0, verdict="cohesive")

    weighted_sum = sum(r.score * r.cluster.size for r in reports)
    overall = weighted_sum / total_size

    return FragmentationReport(
        clusters=reports,
        score=round(overall, 4),
        verdict=_verdict(overall),
        total_fragmented_commits=total_size,
    )


def fragmentation_timeline(
    commits: Sequence[CommitInfo | Dict[str, Any]],
    window_size: int = 20,
    max_gap_seconds: float = DEFAULT_MAX_GAP_SECONDS,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    small_threshold: int = DEFAULT_SMALL_COMMIT_LINES,
    weights: Optional[Dict[str, float]] = None,
) -> List[FragmentationReport]:
    """Sliding-window fragmentation analysis over a commit stream.

    Returns one ``FragmentationReport`` per window position.
    """
    if not commits or window_size < min_cluster_size:
        return []

    normalised: List[CommitInfo] = []
    for c in commits:
        if isinstance(c, CommitInfo):
            normalised.append(c)
        else:
            normalised.append(CommitInfo(
                hash=c.get("hash", ""),
                files=c.get("files", []),
                message=c.get("message", ""),
                lines_changed=c.get("lines_changed", 0),
                timestamp=float(c.get("timestamp", 0)),
            ))

    results: List[FragmentationReport] = []
    for start in range(len(normalised) - window_size + 1):
        window = normalised[start:start + window_size]
        clusters = detect_clusters(window, max_gap_seconds, min_cluster_size)
        report = fragmentation_score(clusters, window, small_threshold, weights)
        results.append(report)

    return results
