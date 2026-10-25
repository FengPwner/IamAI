"""Tests for iamai.commit_fragmentation — scattered micro-commit detection.

Covers: detect_clusters, analyse_cluster, fragmentation_score,
fragmentation_timeline, edge cases, boundary conditions, weight
overrides, verdict thresholds.
"""

import pytest

from iamai.commit_fragmentation import (
    DEFAULT_MAX_GAP_SECONDS,
    DEFAULT_MIN_CLUSTER_SIZE,
    DEFAULT_SMALL_COMMIT_LINES,
    DEFAULT_WEIGHTS,
    VERDICT_THRESHOLDS,
    Cluster,
    ClusterReport,
    CommitInfo,
    FragmentationReport,
    _change_volume_ratio,
    _file_cohesion,
    _global_mean_gap,
    _jaccard,
    _temporal_tightness,
    _verdict,
    analyse_cluster,
    detect_clusters,
    fragmentation_score,
    fragmentation_timeline,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _ci(
    hash_: str = "a",
    files: list[str] | None = None,
    message: str = "msg",
    lines_changed: int = 5,
    timestamp: float = 1000.0,
) -> CommitInfo:
    return CommitInfo(
        hash=hash_,
        files=files or ["a.py"],
        message=message,
        lines_changed=lines_changed,
        timestamp=timestamp,
    )


def _commit_dict(
    hash_: str = "a",
    files: list[str] | None = None,
    message: str = "msg",
    lines_changed: int = 5,
    timestamp: float = 1000.0,
) -> dict:
    return {
        "hash": hash_,
        "files": files or ["a.py"],
        "message": message,
        "lines_changed": lines_changed,
        "timestamp": timestamp,
    }


def _tight_cluster(n: int = 4, base_ts: float = 1000.0, gap: float = 30.0) -> list[CommitInfo]:
    """Create n commits spaced `gap` seconds apart, same files, small changes."""
    return [
        _ci(
            hash_=f"h{i}",
            files=["module.py", "tests/test_module.py"],
            message=f"small fix {i}",
            lines_changed=3,
            timestamp=base_ts + i * gap,
        )
        for i in range(n)
    ]


def _scattered_cluster(n: int = 4, base_ts: float = 1000.0) -> list[CommitInfo]:
    """Create n commits touching different files."""
    return [
        _ci(
            hash_=f"h{i}",
            files=[f"area{i}/file.py"],
            message=f"work on area {i}",
            lines_changed=2,
            timestamp=base_ts + i * 60,
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# _jaccard
# ---------------------------------------------------------------------------

class TestJaccard:
    def test_identical(self):
        assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint(self):
        assert _jaccard({"a"}, {"b"}) == 0.0

    def test_partial(self):
        assert _jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)

    def test_both_empty(self):
        assert _jaccard(set(), set()) == 0.0

    def test_one_empty(self):
        assert _jaccard({"a"}, set()) == 0.0


# ---------------------------------------------------------------------------
# _file_cohesion
# ---------------------------------------------------------------------------

class TestFileCohesion:
    def test_single_commit(self):
        c = Cluster(commits=[_ci()])
        assert _file_cohesion(c) == 0.0

    def test_identical_files(self):
        commits = [_ci(files=["a.py", "b.py"], timestamp=1000 + i * 30) for i in range(3)]
        c = Cluster(commits=commits)
        assert _file_cohesion(c) == 1.0

    def test_disjoint_files(self):
        commits = [_ci(files=[f"x{i}.py"], timestamp=1000 + i * 30) for i in range(3)]
        c = Cluster(commits=commits)
        assert _file_cohesion(c) == 0.0

    def test_partial_overlap(self):
        commits = [
            _ci(files=["a.py", "b.py"], timestamp=1000),
            _ci(files=["b.py", "c.py"], timestamp=1030),
        ]
        c = Cluster(commits=commits)
        assert _file_cohesion(c) == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# _temporal_tightness
# ---------------------------------------------------------------------------

class TestTemporalTightness:
    def test_single_commit(self):
        c = Cluster(commits=[_ci()])
        assert _temporal_tightness(c, 100.0) == 0.0

    def test_very_tight(self):
        """Max gap ≤ global mean → 1.0."""
        commits = [_ci(timestamp=1000 + i * 10) for i in range(4)]
        c = Cluster(commits=commits)
        assert _temporal_tightness(c, 100.0) == 1.0

    def test_very_loose(self):
        """Max gap ≥ 3× global mean → 0.0."""
        commits = [_ci(timestamp=1000), _ci(timestamp=1400)]
        c = Cluster(commits=commits)
        # max_gap=400, global_mean=100 → ratio=4 → 0.0
        assert _temporal_tightness(c, 100.0) == 0.0

    def test_intermediate(self):
        """Ratio between 1 and 3 → linear decay."""
        commits = [_ci(timestamp=1000), _ci(timestamp=1200)]
        c = Cluster(commits=commits)
        # max_gap=200, global_mean=100 → ratio=2 → (3-2)/2 = 0.5
        assert _temporal_tightness(c, 100.0) == pytest.approx(0.5)

    def test_zero_global_mean(self):
        c = Cluster(commits=[_ci(timestamp=1000), _ci(timestamp=1010)])
        assert _temporal_tightness(c, 0.0) == 0.0


# ---------------------------------------------------------------------------
# _change_volume_ratio
# ---------------------------------------------------------------------------

class TestChangeVolumeRatio:
    def test_all_small(self):
        commits = [_ci(lines_changed=2) for _ in range(5)]
        c = Cluster(commits=commits)
        assert _change_volume_ratio(c, 10) == 1.0

    def test_all_large(self):
        commits = [_ci(lines_changed=50) for _ in range(5)]
        c = Cluster(commits=commits)
        assert _change_volume_ratio(c, 10) == 0.0

    def test_mixed(self):
        commits = [
            _ci(lines_changed=2),
            _ci(lines_changed=50),
            _ci(lines_changed=5),
            _ci(lines_changed=100),
        ]
        c = Cluster(commits=commits)
        assert _change_volume_ratio(c, 10) == pytest.approx(0.5)

    def test_empty_cluster(self):
        c = Cluster(commits=[])
        assert _change_volume_ratio(c, 10) == 0.0

    def test_boundary_exactly_threshold(self):
        """lines_changed == threshold counts as small (≤)."""
        commits = [_ci(lines_changed=10)]
        c = Cluster(commits=commits)
        assert _change_volume_ratio(c, 10) == 1.0


# ---------------------------------------------------------------------------
# Cluster properties
# ---------------------------------------------------------------------------

class TestCluster:
    def test_size(self):
        c = Cluster(commits=[_ci(), _ci(), _ci()])
        assert c.size == 3

    def test_file_union(self):
        commits = [
            _ci(files=["a.py"]),
            _ci(files=["b.py"]),
            _ci(files=["a.py", "c.py"]),
        ]
        c = Cluster(commits=commits)
        assert c.file_union == {"a.py", "b.py", "c.py"}

    def test_total_lines(self):
        commits = [_ci(lines_changed=10), _ci(lines_changed=20), _ci(lines_changed=5)]
        c = Cluster(commits=commits)
        assert c.total_lines == 35

    def test_max_gap(self):
        commits = [
            _ci(timestamp=1000),
            _ci(timestamp=1010),
            _ci(timestamp=1100),
        ]
        c = Cluster(commits=commits)
        assert c.max_gap == pytest.approx(90.0)

    def test_max_gap_single(self):
        c = Cluster(commits=[_ci()])
        assert c.max_gap == 0.0

    def test_mean_gap(self):
        commits = [
            _ci(timestamp=1000),
            _ci(timestamp=1010),
            _ci(timestamp=1100),
        ]
        c = Cluster(commits=commits)
        assert c.mean_gap == pytest.approx(50.0)

    def test_mean_gap_single(self):
        c = Cluster(commits=[_ci()])
        assert c.mean_gap == 0.0


# ---------------------------------------------------------------------------
# detect_clusters
# ---------------------------------------------------------------------------

class TestDetectClusters:
    def test_empty(self):
        assert detect_clusters([]) == []

    def test_single_commit(self):
        assert detect_clusters([_ci()]) == []

    def test_tight_group(self):
        commits = _tight_cluster(4, gap=30)
        clusters = detect_clusters(commits, max_gap_seconds=60, min_cluster_size=3)
        assert len(clusters) == 1
        assert clusters[0].size == 4

    def test_two_groups_separated(self):
        g1 = _tight_cluster(3, base_ts=1000, gap=30)
        g2 = _tight_cluster(3, base_ts=5000, gap=30)
        clusters = detect_clusters(g1 + g2, max_gap_seconds=60, min_cluster_size=3)
        assert len(clusters) == 2

    def test_below_min_size_filtered(self):
        commits = [
            _ci(timestamp=1000),
            _ci(timestamp=1030),
            _ci(timestamp=5000),  # gap > max_gap → new group with 1 commit
        ]
        clusters = detect_clusters(commits, max_gap_seconds=60, min_cluster_size=3)
        assert len(clusters) == 0  # first group has 2, second has 1

    def test_dict_input(self):
        commits = [
            _commit_dict(timestamp=1000 + i * 30) for i in range(4)
        ]
        clusters = detect_clusters(commits, max_gap_seconds=60, min_cluster_size=3)
        assert len(clusters) == 1
        assert clusters[0].size == 4

    def test_exact_boundary_gap(self):
        """Gap exactly == max_gap_seconds should still cluster."""
        commits = [
            _ci(timestamp=1000),
            _ci(timestamp=1300),  # gap = 300 = DEFAULT_MAX_GAP_SECONDS
            _ci(timestamp=1600),
        ]
        clusters = detect_clusters(
            commits, max_gap_seconds=DEFAULT_MAX_GAP_SECONDS, min_cluster_size=3
        )
        assert len(clusters) == 1

    def test_just_over_boundary(self):
        commits = [
            _ci(timestamp=1000),
            _ci(timestamp=1301),  # gap = 301 > 300
            _ci(timestamp=1602),
        ]
        clusters = detect_clusters(
            commits, max_gap_seconds=DEFAULT_MAX_GAP_SECONDS, min_cluster_size=3
        )
        assert len(clusters) == 0


# ---------------------------------------------------------------------------
# analyse_cluster
# ---------------------------------------------------------------------------

class TestAnalyseCluster:
    def test_tight_same_files(self):
        """Small commits, same files, tight timing → high fragmentation."""
        commits = _tight_cluster(4, gap=30)
        c = Cluster(commits=commits)
        report = analyse_cluster(c, global_mean_gap=300)
        assert report.score > 0.5
        assert report.file_cohesion == 1.0
        assert report.temporal_tightness == 1.0
        assert report.change_volume_ratio == 1.0

    def test_scattered_files(self):
        """Different files → low cohesion → lower score."""
        commits = _scattered_cluster(4)
        c = Cluster(commits=commits)
        report = analyse_cluster(c, global_mean_gap=300)
        assert report.file_cohesion == 0.0
        assert report.score < 0.7  # still some score from timing + small changes

    def test_large_commits(self):
        """Big commits → low change_volume_ratio → lower fragmentation."""
        commits = [
            _ci(files=["a.py", "b.py"], lines_changed=100, timestamp=1000 + i * 30)
            for i in range(4)
        ]
        c = Cluster(commits=commits)
        report = analyse_cluster(c, global_mean_gap=300)
        assert report.change_volume_ratio == 0.0

    def test_custom_weights(self):
        """Custom weights override defaults."""
        commits = _tight_cluster(4)
        c = Cluster(commits=commits)
        # Zero out everything except file_cohesion
        report = analyse_cluster(c, global_mean_gap=300, weights={
            "file_cohesion": 1.0,
            "temporal_tightness": 0.0,
            "change_volume_ratio": 0.0,
        })
        assert report.score == pytest.approx(report.file_cohesion)


# ---------------------------------------------------------------------------
# _verdict
# ---------------------------------------------------------------------------

class TestVerdict:
    def test_cohesive(self):
        assert _verdict(0.0) == "cohesive"
        assert _verdict(VERDICT_THRESHOLDS["cohesive"]) == "cohesive"

    def test_mild(self):
        assert _verdict(VERDICT_THRESHOLDS["cohesive"] + 0.01) == "mild"
        assert _verdict(VERDICT_THRESHOLDS["mild"]) == "mild"

    def test_fragmented(self):
        assert _verdict(VERDICT_THRESHOLDS["mild"] + 0.01) == "fragmented"
        assert _verdict(1.0) == "fragmented"


# ---------------------------------------------------------------------------
# fragmentation_score
# ---------------------------------------------------------------------------

class TestFragmentationScore:
    def test_no_clusters(self):
        report = fragmentation_score([])
        assert report.score == 0.0
        assert report.verdict == "cohesive"
        assert report.total_fragmented_commits == 0

    def test_single_cluster(self):
        commits = _tight_cluster(4, gap=30)
        c = Cluster(commits=commits)
        report = fragmentation_score([c], commits, small_threshold=10)
        assert 0.0 <= report.score <= 1.0
        assert report.total_fragmented_commits == 4

    def test_multiple_clusters_weighted(self):
        """Larger cluster should weigh more."""
        small = _tight_cluster(3, base_ts=1000, gap=30)
        big = _tight_cluster(6, base_ts=5000, gap=30)
        all_commits = small + big
        c1 = Cluster(commits=small)
        c2 = Cluster(commits=big)
        report = fragmentation_score([c1, c2], all_commits)
        assert report.total_fragmented_commits == 9

    def test_cluster_report_input(self):
        """Accepts pre-computed ClusterReport objects."""
        commits = _tight_cluster(4)
        c = Cluster(commits=commits)
        cr = analyse_cluster(c, 300)
        report = fragmentation_score([cr])
        assert report.score == pytest.approx(cr.score)

    def test_score_clamped(self):
        """Score is always in [0, 1]."""
        commits = _tight_cluster(4)
        c = Cluster(commits=commits)
        # Use extreme weights
        report = analyse_cluster(c, 300, weights={
            "file_cohesion": 10.0,
            "temporal_tightness": 10.0,
            "change_volume_ratio": 10.0,
        })
        assert 0.0 <= report.score <= 1.0


# ---------------------------------------------------------------------------
# fragmentation_timeline
# ---------------------------------------------------------------------------

class TestFragmentationTimeline:
    def test_empty(self):
        assert fragmentation_timeline([]) == []

    def test_window_too_small(self):
        commits = _tight_cluster(3)
        assert fragmentation_timeline(commits, window_size=2, min_cluster_size=3) == []

    def test_basic_timeline(self):
        # 30 commits, window 10 → 21 windows
        commits = [
            _ci(hash_=f"h{i}", timestamp=1000 + i * 30, lines_changed=3)
            for i in range(30)
        ]
        results = fragmentation_timeline(commits, window_size=10)
        assert len(results) == 21
        for r in results:
            assert isinstance(r, FragmentationReport)

    def test_dict_input(self):
        commits = [
            _commit_dict(hash_=f"h{i}", timestamp=1000 + i * 30)
            for i in range(15)
        ]
        results = fragmentation_timeline(commits, window_size=10)
        assert len(results) == 6

    def test_all_fragmented(self):
        """Tight cluster of identical-file small commits → fragmented verdict."""
        commits = _tight_cluster(20, gap=10)
        results = fragmentation_timeline(
            commits, window_size=10, max_gap_seconds=60, min_cluster_size=3
        )
        assert len(results) > 0
        assert all(r.score > 0.0 for r in results)

    def test_all_cohesive(self):
        """Well-spaced large commits → low fragmentation."""
        commits = [
            _ci(
                hash_=f"h{i}",
                files=[f"area{i % 5}.py"],
                lines_changed=200,
                timestamp=1000 + i * 3600,
            )
            for i in range(20)
        ]
        results = fragmentation_timeline(
            commits, window_size=10, max_gap_seconds=60, min_cluster_size=3
        )
        # Most windows should have no clusters (gaps are 3600s >> 60s)
        assert all(r.score == 0.0 for r in results)


# ---------------------------------------------------------------------------
# _global_mean_gap
# ---------------------------------------------------------------------------

class TestGlobalMeanGap:
    def test_empty(self):
        assert _global_mean_gap([]) == 0.0

    def test_single(self):
        assert _global_mean_gap([_ci()]) == 0.0

    def test_uniform(self):
        commits = [_ci(timestamp=1000 + i * 100) for i in range(5)]
        assert _global_mean_gap(commits) == pytest.approx(100.0)

    def test_irregular(self):
        commits = [_ci(timestamp=1000), _ci(timestamp=1010), _ci(timestamp=1100)]
        # gaps: 10, 90 → mean = 50
        assert _global_mean_gap(commits) == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# edge cases & integration
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_one_commit_per_file(self):
        """Each commit touches a unique file → cohesion 0."""
        commits = [
            _ci(hash_=f"h{i}", files=[f"unique_{i}.py"], timestamp=1000 + i * 30)
            for i in range(5)
        ]
        clusters = detect_clusters(commits, max_gap_seconds=60, min_cluster_size=3)
        assert len(clusters) == 1
        report = analyse_cluster(clusters[0], global_mean_gap=300)
        assert report.file_cohesion == 0.0

    def test_identical_commits(self):
        """All commits identical → cohesion 1.0, all small → ratio 1.0."""
        commits = [_ci(timestamp=1000 + i * 10) for i in range(5)]
        clusters = detect_clusters(commits, max_gap_seconds=60, min_cluster_size=3)
        report = analyse_cluster(clusters[0], global_mean_gap=100)
        assert report.file_cohesion == 1.0
        assert report.change_volume_ratio == 1.0

    def test_zero_lines_changed(self):
        """Edge: all commits have 0 lines."""
        commits = [
            _ci(lines_changed=0, timestamp=1000 + i * 30) for i in range(4)
        ]
        clusters = detect_clusters(commits, max_gap_seconds=60, min_cluster_size=3)
        report = analyse_cluster(clusters[0], global_mean_gap=100)
        assert report.change_volume_ratio == 1.0  # 0 ≤ threshold → small

    def test_fragmentation_report_has_verdict(self):
        commits = _tight_cluster(5)
        clusters = detect_clusters(commits, max_gap_seconds=60, min_cluster_size=3)
        report = fragmentation_score(clusters, commits)
        assert report.verdict in ("cohesive", "mild", "fragmented")

    def test_defaults_are_consistent(self):
        """Module constants are sensible."""
        assert DEFAULT_MAX_GAP_SECONDS > 0
        assert DEFAULT_MIN_CLUSTER_SIZE >= 2
        assert DEFAULT_SMALL_COMMIT_LINES > 0
        assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)
        assert VERDICT_THRESHOLDS["cohesive"] < VERDICT_THRESHOLDS["mild"]
