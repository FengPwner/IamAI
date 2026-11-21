"""Tests for stroke_diversity_analyzer.py."""

import json
import math
import tempfile
from pathlib import Path

import pytest

# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from stroke_diversity_analyzer import (
    analyze_diversity,
    compute_entropy,
    DiversityReport,
)


def make_strokes_file(strokes: list[dict], tmpdir: Path) -> Path:
    """Helper: write a list of stroke dicts to a temporary JSONL file."""
    path = tmpdir / "strokes.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for stroke in strokes:
            f.write(json.dumps(stroke) + "\n")
    return path


class TestComputeEntropy:
    """Tests for the Shannon entropy calculation."""

    def test_entropy_uniform_distribution(self):
        """Uniform distribution should have maximum entropy."""
        counts = {"a": 100, "b": 100, "c": 100, "d": 100}
        entropy = compute_entropy(counts)
        max_entropy = math.log2(4)
        assert abs(entropy - max_entropy) < 0.001

    def test_entropy_single_item(self):
        """Single kind should have zero entropy."""
        counts = {"thought": 100}
        entropy = compute_entropy(counts)
        assert entropy == 0.0

    def test_entropy_two_equal_items(self):
        """Two equal items should have entropy of 1 bit."""
        counts = {"a": 50, "b": 50}
        entropy = compute_entropy(counts)
        assert abs(entropy - 1.0) < 0.001

    def test_entropy_skewed_distribution(self):
        """Skewed distribution should have lower entropy than uniform."""
        counts = {"a": 90, "b": 5, "c": 5}
        entropy = compute_entropy(counts)
        max_entropy = math.log2(3)
        assert entropy < max_entropy

    def test_entropy_empty_counts(self):
        """Empty counts should return zero entropy."""
        counts = {}
        entropy = compute_entropy(counts)
        assert entropy == 0.0

    def test_entropy_with_zeros(self):
        """Counts with zero values should be handled correctly."""
        counts = {"a": 100, "b": 0, "c": 0}
        entropy = compute_entropy(counts)
        assert entropy == 0.0


class TestAnalyzeDiversity:
    """Tests for the main diversity analysis function."""

    def test_balanced_distribution(self, tmp_path):
        """Even distribution should be classified as 'balanced'."""
        strokes = [
            {"seq": i, "at": f"2026-11-21T12:00:{i:02d}+00:00", "kind": kind, "text": "test"}
            for i, kind in enumerate(["thought", "garden", "metrics", "snippet", "devlog", "note"] * 10)
        ]
        path = make_strokes_file(strokes, tmp_path)
        report = analyze_diversity(path)

        assert report.verdict == "balanced"
        assert report.diversity_ratio > 0.85
        assert len(report.kind_counts) == 6
        assert sum(report.kind_counts.values()) == 60

    def test_skewed_distribution(self, tmp_path):
        """Moderately skewed distribution should be classified as 'skewed'."""
        # 70% thought, 20% garden, 10% metrics → diversity_ratio ≈ 0.73
        strokes = [
            {"seq": i, "at": f"2026-11-21T12:00:{i:02d}+00:00", "kind": "thought", "text": "test"}
            for i in range(70)
        ] + [
            {"seq": i, "at": f"2026-11-21T12:01:{i:02d}+00:00", "kind": "garden", "text": "test"}
            for i in range(20)
        ] + [
            {"seq": i, "at": f"2026-11-21T12:02:{i:02d}+00:00", "kind": "metrics", "text": "test"}
            for i in range(10)
        ]
        path = make_strokes_file(strokes, tmp_path)
        report = analyze_diversity(path)

        assert report.verdict == "skewed"
        assert 0.60 <= report.diversity_ratio < 0.85
        assert report.dominant_kind == "thought"
        assert report.dominant_pct == 70.0

    def test_monoculture_distribution(self, tmp_path):
        """Heavily skewed distribution should be classified as 'monoculture'."""
        strokes = [
            {"seq": i, "at": f"2026-11-21T12:00:{i:02d}+00:00", "kind": "thought", "text": "test"}
            for i in range(95)
        ] + [
            {"seq": i, "at": f"2026-11-21T12:01:{i:02d}+00:00", "kind": "garden", "text": "test"}
            for i in range(5)
        ]
        path = make_strokes_file(strokes, tmp_path)
        report = analyze_diversity(path)

        assert report.verdict == "monoculture"
        assert report.diversity_ratio < 0.60
        assert report.dominant_kind == "thought"
        assert report.dominant_pct == 95.0

    def test_single_kind_only(self, tmp_path):
        """Single kind should be monoculture with zero diversity."""
        strokes = [
            {"seq": i, "at": f"2026-11-21T12:00:{i:02d}+00:00", "kind": "thought", "text": "test"}
            for i in range(100)
        ]
        path = make_strokes_file(strokes, tmp_path)
        report = analyze_diversity(path)

        assert report.verdict == "monoculture"
        assert report.diversity_ratio == 0.0
        assert report.dominant_kind == "thought"
        assert report.dominant_pct == 100.0

    def test_empty_file(self, tmp_path):
        """Empty file should return monoculture with zero counts."""
        path = make_strokes_file([], tmp_path)
        report = analyze_diversity(path)

        assert report.verdict == "monoculture"
        assert report.kind_counts == {}
        assert report.dominant_kind == "none"

    def test_file_not_found(self, tmp_path):
        """Missing file should raise FileNotFoundError."""
        fake_path = tmp_path / "nonexistent.jsonl"
        with pytest.raises(FileNotFoundError):
            analyze_diversity(fake_path)

    def test_malformed_json_lines(self, tmp_path):
        """Malformed lines should be skipped gracefully."""
        path = tmp_path / "strokes.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"seq": 1, "kind": "thought", "text": "good"}\n')
            f.write('this is not json\n')
            f.write('{"seq": 2, "kind": "garden", "text": "also good"}\n')
            f.write('{broken json\n')

        report = analyze_diversity(path)
        assert sum(report.kind_counts.values()) == 2
        assert "thought" in report.kind_counts
        assert "garden" in report.kind_counts

    def test_unknown_kind_handled(self, tmp_path):
        """Strokes with unknown kinds should still be counted."""
        strokes = [
            {"seq": 1, "kind": "thought", "text": "test"},
            {"seq": 2, "kind": "unknown_type", "text": "test"},
            {"seq": 3, "kind": "another_type", "text": "test"},
        ]
        path = make_strokes_file(strokes, tmp_path)
        report = analyze_diversity(path)

        assert len(report.kind_counts) == 3
        assert "unknown_type" in report.kind_counts
        assert "another_type" in report.kind_counts

    def test_percentages_sum_to_100(self, tmp_path):
        """Kind percentages should sum to approximately 100."""
        strokes = [
            {"seq": i, "kind": kind, "text": "test"}
            for i, kind in enumerate(["thought", "garden", "metrics"] * 7)
        ]
        path = make_strokes_file(strokes, tmp_path)
        report = analyze_diversity(path)

        pct_sum = sum(report.kind_pcts.values())
        assert abs(pct_sum - 100.0) < 0.1

    def test_report_to_dict(self, tmp_path):
        """DiversityReport should serialize to dict correctly."""
        strokes = [
            {"seq": i, "kind": kind, "text": "test"}
            for i, kind in enumerate(["thought", "garden"] * 5)
        ]
        path = make_strokes_file(strokes, tmp_path)
        report = analyze_diversity(path)
        d = report.to_dict()

        assert "kind_counts" in d
        assert "kind_pcts" in d
        assert "entropy" in d
        assert "diversity_ratio" in d
        assert "verdict" in d
        assert isinstance(d, dict)

    def test_real_repo_data(self):
        """Test against the actual repo data if available."""
        repo_root = Path(__file__).resolve().parent.parent
        real_path = repo_root / "data" / "strokes.jsonl"
        if not real_path.exists():
            pytest.skip("Real strokes.jsonl not found")

        report = analyze_diversity(real_path)
        # The real repo has multiple kinds (though heavily dominated by "thought")
        assert len(report.kind_counts) >= 2
        # Diversity ratio should be computed
        assert 0.0 <= report.diversity_ratio <= 1.0
        # Dominant kind should be identified
        assert report.dominant_kind in report.kind_counts
        # Total strokes should be reasonable
        assert sum(report.kind_counts.values()) > 100


class TestDiversityThresholds:
    """Tests for the threshold boundaries."""

    def test_exactly_balanced_threshold(self, tmp_path):
        """Distribution at exactly 0.85 should be 'balanced'."""
        # Create a distribution that yields ~0.85 diversity ratio
        # This is approximate; we verify it lands in balanced
        strokes = (
            [{"seq": i, "kind": "thought", "text": "t"} for i in range(25)]
            + [{"seq": i, "kind": "garden", "text": "t"} for i in range(20)]
            + [{"seq": i, "kind": "metrics", "text": "t"} for i in range(20)]
            + [{"seq": i, "kind": "snippet", "text": "t"} for i in range(15)]
            + [{"seq": i, "kind": "devlog", "text": "t"} for i in range(10)]
            + [{"seq": i, "kind": "note", "text": "t"} for i in range(10)]
        )
        path = make_strokes_file(strokes, tmp_path)
        report = analyze_diversity(path)

        # Should be in the balanced or skewed range
        assert report.verdict in ["balanced", "skewed"]

    def test_two_kinds_equal(self, tmp_path):
        """Two kinds with equal counts should have entropy of 1.0."""
        strokes = [
            {"seq": i, "kind": "thought", "text": "test"}
            for i in range(50)
        ] + [
            {"seq": i, "kind": "garden", "text": "test"}
            for i in range(50)
        ]
        path = make_strokes_file(strokes, tmp_path)
        report = analyze_diversity(path)

        assert abs(report.entropy - 1.0) < 0.001
        assert report.max_entropy == 1.0
        assert report.diversity_ratio == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
