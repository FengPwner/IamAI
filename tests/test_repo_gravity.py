"""Tests for repo_gravity — file-change concentration analysis."""

import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.repo_gravity import (
    compute_gravity,
    gravity_band,
    gravity_report,
    parse_commit_file_counts,
    top_attractors,
)


# ---------------------------------------------------------------------------
# compute_gravity — Gini coefficient
# ---------------------------------------------------------------------------


class TestComputeGravity:
    def test_empty_counter(self):
        assert compute_gravity(Counter()) == 0.0

    def test_single_file(self):
        assert compute_gravity(Counter({"a.py": 10})) == 0.0

    def test_perfectly_equal(self):
        """All files have the same commit count → Gini = 0.0."""
        counts = Counter({"a.py": 5, "b.py": 5, "c.py": 5, "d.py": 5})
        assert compute_gravity(counts) == 0.0

    def test_maximum_inequality(self):
        """One file has all commits, others have zero-ish → Gini near 1.0."""
        counts = Counter({"a.py": 100, "b.py": 0, "c.py": 0, "d.py": 0})
        gini = compute_gravity(counts)
        assert gini > 0.7

    def test_two_files_one_dominant(self):
        """Two files, one has 90% of commits → high Gini."""
        counts = Counter({"a.py": 90, "b.py": 10})
        gini = compute_gravity(counts)
        assert 0.3 < gini < 0.6

    def test_known_value(self):
        """Verify against hand-calculated Gini for [1, 1, 1, 1, 6]."""
        # Values: [1, 1, 1, 1, 6], n=5, sum=10
        # Mean abs diff = (sum of |xi-xj|) / (2*5*10)
        # Pairs: 4*|1-6|=20 (four 1s vs 6), 6*|1-1|=0 (among the four 1s)
        # Plus reverse: 4*|6-1|=20, total abs_diff = 40+40 = 80
        # Wait, let me recalculate.
        # All pairs (i,j): for 4 items of value 1 and 1 item of value 6:
        #   1 vs 1: C(4,2)*2 = 12 pairs, diff = 0 each → 0
        #   1 vs 6: 4*2 = 8 pairs (both directions), diff = 5 each → 40
        # Total abs_diff = 40
        # G = 40 / (2 * 5 * 10) = 40 / 100 = 0.4
        counts = Counter({"a": 1, "b": 1, "c": 1, "d": 1, "e": 6})
        gini = compute_gravity(counts)
        assert abs(gini - 0.4) < 1e-9

    def test_all_zeros(self):
        """All values zero → Gini = 0.0 (no commits at all)."""
        counts = Counter({"a.py": 0, "b.py": 0})
        assert compute_gravity(counts) == 0.0

    def test_symmetry(self):
        """Gini is independent of key ordering."""
        c1 = Counter({"a.py": 10, "b.py": 20, "c.py": 30})
        c2 = Counter({"c.py": 30, "a.py": 10, "b.py": 20})
        assert compute_gravity(c1) == compute_gravity(c2)

    def test_scaling_invariance(self):
        """Multiplying all counts by a constant doesn't change Gini."""
        c1 = Counter({"a.py": 5, "b.py": 15, "c.py": 30})
        c2 = Counter({"a.py": 50, "b.py": 150, "c.py": 300})
        assert abs(compute_gravity(c1) - compute_gravity(c2)) < 1e-9

    def test_large_uniform(self):
        """100 files with equal counts → Gini = 0.0."""
        counts = Counter({f"file_{i}.py": 7 for i in range(100)})
        assert compute_gravity(counts) == 0.0

    def test_large_skewed(self):
        """Power-law distribution → high Gini."""
        counts = Counter({f"file_{i}.py": 2 ** i for i in range(10)})
        gini = compute_gravity(counts)
        assert gini > 0.5


# ---------------------------------------------------------------------------
# gravity_band — classification
# ---------------------------------------------------------------------------


class TestGravityBand:
    def test_zero_is_distributed(self):
        assert gravity_band(0.0) == "distributed"

    def test_low_is_distributed(self):
        assert gravity_band(0.15) == "distributed"

    def test_boundary_distributed(self):
        assert gravity_band(0.29) == "distributed"

    def test_balanced_start(self):
        assert gravity_band(0.30) == "balanced"

    def test_balanced_mid(self):
        assert gravity_band(0.40) == "balanced"

    def test_balanced_boundary(self):
        assert gravity_band(0.49) == "balanced"

    def test_concentrated_start(self):
        assert gravity_band(0.50) == "concentrated"

    def test_concentrated_mid(self):
        assert gravity_band(0.60) == "concentrated"

    def test_concentrated_boundary(self):
        assert gravity_band(0.69) == "concentrated"

    def test_black_hole_start(self):
        assert gravity_band(0.70) == "black-hole"

    def test_black_hole_high(self):
        assert gravity_band(0.95) == "black-hole"

    def test_black_hole_max(self):
        assert gravity_band(1.0) == "black-hole"

    def test_above_one_clamped(self):
        assert gravity_band(1.5) == "black-hole"

    def test_all_bands_covered(self):
        """Every value from 0.0 to 1.0 should map to a valid band."""
        valid = {"distributed", "balanced", "concentrated", "black-hole"}
        for i in range(101):
            assert gravity_band(i / 100.0) in valid


# ---------------------------------------------------------------------------
# parse_commit_file_counts — git log parsing
# ---------------------------------------------------------------------------


class TestParseCommitFileCounts:
    def test_empty_input(self):
        assert parse_commit_file_counts("") == Counter()

    def test_blank_lines_only(self):
        assert parse_commit_file_counts("\n\n\n") == Counter()

    def test_single_commit(self):
        text = """
iamai/foo.py
tests/test_foo.py
docs/FOO.md
"""
        counts = parse_commit_file_counts(text)
        assert counts == Counter({
            "iamai/foo.py": 1,
            "tests/test_foo.py": 1,
            "docs/FOO.md": 1,
        })

    def test_multiple_commits(self):
        text = """
iamai/foo.py
tests/test_foo.py

iamai/foo.py
iamai/bar.py

iamai/foo.py
"""
        counts = parse_commit_file_counts(text)
        assert counts["iamai/foo.py"] == 3
        assert counts["tests/test_foo.py"] == 1
        assert counts["iamai/bar.py"] == 1

    def test_skips_commit_headers(self):
        text = """commit abc1234

iamai/foo.py
tests/test_foo.py
"""
        counts = parse_commit_file_counts(text)
        assert "commit abc1234" not in counts
        assert counts["iamai/foo.py"] == 1

    def test_skips_hex_hash_lines(self):
        text = """
abc1234
iamai/foo.py
"""
        counts = parse_commit_file_counts(text)
        assert "abc1234" not in counts
        assert counts["iamai/foo.py"] == 1

    def test_handles_whitespace(self):
        text = """
  iamai/foo.py
  tests/test_foo.py
"""
        counts = parse_commit_file_counts(text)
        assert counts["iamai/foo.py"] == 1
        assert counts["tests/test_foo.py"] == 1

    def test_file_counted_multiple_times(self):
        text = """
data/strokes.jsonl

data/strokes.jsonl

data/strokes.jsonl
"""
        counts = parse_commit_file_counts(text)
        assert counts["data/strokes.jsonl"] == 3


# ---------------------------------------------------------------------------
# top_attractors — ranked file list
# ---------------------------------------------------------------------------


class TestTopAttractors:
    def test_empty_counter(self):
        assert top_attractors(Counter()) == []

    def test_fewer_than_n(self):
        counts = Counter({"a.py": 10, "b.py": 5})
        result = top_attractors(counts, n=5)
        assert len(result) == 2
        assert result[0]["path"] == "a.py"
        assert result[0]["commits"] == 10

    def test_exact_n(self):
        counts = Counter({"a.py": 10, "b.py": 5, "c.py": 3})
        result = top_attractors(counts, n=3)
        assert len(result) == 3

    def test_truncated_to_n(self):
        counts = Counter({f"f{i}.py": 100 - i for i in range(20)})
        result = top_attractors(counts, n=5)
        assert len(result) == 5
        assert result[0]["commits"] == 100

    def test_share_calculation(self):
        counts = Counter({"a.py": 75, "b.py": 25})
        result = top_attractors(counts, n=2)
        assert abs(result[0]["share"] - 0.75) < 1e-9
        assert abs(result[1]["share"] - 0.25) < 1e-9

    def test_ordering(self):
        """Results should be in descending commit count order."""
        counts = Counter({"a.py": 1, "b.py": 50, "c.py": 10})
        result = top_attractors(counts, n=3)
        assert result[0]["commits"] >= result[1]["commits"] >= result[2]["commits"]

    def test_default_n_is_10(self):
        counts = Counter({f"f{i}.py": i + 1 for i in range(20)})
        result = top_attractors(counts)
        assert len(result) == 10


# ---------------------------------------------------------------------------
# gravity_report — convenience
# ---------------------------------------------------------------------------


class TestGravityReport:
    def test_basic_report(self):
        counts = Counter({"a.py": 5, "b.py": 5, "c.py": 5})
        report = gravity_report(counts)
        assert report["gini"] == 0.0
        assert report["band"] == "distributed"
        assert report["file_count"] == 3
        assert report["total_commits"] == 15
        assert len(report["top_attractors"]) == 3
        assert "distributed" in report["summary"]

    def test_concentrated_report(self):
        counts = Counter({"big.py": 100, "a.py": 1, "b.py": 1, "c.py": 1})
        report = gravity_report(counts)
        assert report["band"] in ("concentrated", "black-hole")
        assert report["top_attractors"][0]["path"] == "big.py"

    def test_empty_report(self):
        report = gravity_report(Counter())
        assert report["gini"] == 0.0
        assert report["file_count"] == 0
        assert report["top_attractors"] == []
        assert "no files" in report["summary"].lower() or "distributed" in report["summary"]

    def test_report_keys(self):
        counts = Counter({"a.py": 10})
        report = gravity_report(counts)
        expected_keys = {"gini", "band", "file_count", "total_commits",
                         "top_attractors", "summary"}
        assert set(report.keys()) == expected_keys

    def test_custom_n(self):
        counts = Counter({f"f{i}.py": i + 1 for i in range(20)})
        report = gravity_report(counts, n=3)
        assert len(report["top_attractors"]) == 3

    def test_summary_contains_gini(self):
        counts = Counter({"a.py": 10, "b.py": 5})
        report = gravity_report(counts)
        assert f"{report['gini']:.3f}" in report["summary"]


# ---------------------------------------------------------------------------
# Integration: realistic scenario
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_typical_repo_gravity(self):
        """A typical self-writing repo has some concentration."""
        # Simulate: strokes.jsonl touched by 80% of commits,
        # other files touched by fewer commits
        counts = Counter()
        counts["data/strokes.jsonl"] = 400
        counts["docs/DEVLOG.md"] = 400
        counts["docs/GARDEN.md"] = 300
        counts["docs/METRICS.md"] = 300
        counts["notes/conventions.md"] = 200
        for i in range(50):
            counts[f"iamai/module_{i}.py"] = 5
        for i in range(50):
            counts[f"tests/test_module_{i}.py"] = 5

        gini = compute_gravity(counts)
        band = gravity_band(gini)
        # Should be concentrated or black-hole due to the heavy log files
        assert gini > 0.4
        assert band in ("balanced", "concentrated", "black-hole")

    def test_healthy_distributed_repo(self):
        """A repo where changes are spread evenly."""
        counts = Counter()
        for i in range(30):
            counts[f"iamai/module_{i}.py"] = 10 + (i % 3)
        gini = compute_gravity(counts)
        assert gini < 0.30
        assert gravity_band(gini) == "distributed"

    def test_cli_report_consistency(self):
        """Report fields should be internally consistent."""
        counts = Counter({
            "a.py": 100, "b.py": 50, "c.py": 25,
            "d.py": 12, "e.py": 6, "f.py": 3,
        })
        report = gravity_report(counts)
        # Total commits should match sum
        assert report["total_commits"] == sum(counts.values())
        # File count should match
        assert report["file_count"] == len(counts)
        # Top attractor should be the most common file
        assert report["top_attractors"][0]["path"] == "a.py"
        # Shares should sum to ≤ 1.0
        total_share = sum(a["share"] for a in report["top_attractors"])
        assert total_share <= 1.0 + 1e-9

    def test_real_repo_integration(self):
        """Test against the actual IamAI repo if accessible."""
        import subprocess
        try:
            result = subprocess.run(
                ["git", "log", "--name-only", "--pretty=format:"],
                capture_output=True, text=True, timeout=30,
                cwd=str(REPO),
            )
            if result.returncode != 0:
                pytest.skip("git not available or not a git repo")

            counts = parse_commit_file_counts(result.stdout)
            if not counts:
                pytest.skip("no commit data in repo")

            gini = compute_gravity(counts)
            band = gravity_band(gini)

            # Sanity checks
            assert 0.0 <= gini <= 1.0
            assert band in ("distributed", "balanced", "concentrated", "black-hole")
            assert len(counts) > 0

            report = gravity_report(counts)
            assert report["file_count"] > 0
            assert report["total_commits"] > 0

        except (subprocess.TimeoutExpired, FileNotFoundError):
            pytest.skip("git not available")
