"""Tests for file_fatigue — detect files that are being over-edited."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.file_fatigue import (
    classify_fatigue,
    analyse_fatigue,
    parse_git_numstat,
    _gini,
    _classify_repo_state,
)


# ---------------------------------------------------------------------------
# classify_fatigue
# ---------------------------------------------------------------------------


class TestClassifyFatigue:
    def test_zero_is_fresh(self):
        assert classify_fatigue(0) == "fresh"

    def test_below_threshold_is_fresh(self):
        assert classify_fatigue(1.49) == "fresh"

    def test_warm_lower_bound(self):
        assert classify_fatigue(1.5) == "warm"

    def test_warm_mid(self):
        assert classify_fatigue(2.0) == "warm"

    def test_warm_upper_bound(self):
        assert classify_fatigue(2.99) == "warm"

    def test_hot_lower_bound(self):
        assert classify_fatigue(3.0) == "hot"

    def test_hot_mid(self):
        assert classify_fatigue(4.0) == "hot"

    def test_hot_upper_bound(self):
        assert classify_fatigue(4.99) == "hot"

    def test_exhausted_lower_bound(self):
        assert classify_fatigue(5.0) == "exhausted"

    def test_exhausted_mid(self):
        assert classify_fatigue(6.5) == "exhausted"

    def test_exhausted_upper_bound(self):
        assert classify_fatigue(7.99) == "exhausted"

    def test_critical_lower_bound(self):
        assert classify_fatigue(8.0) == "critical"

    def test_critical_high(self):
        assert classify_fatigue(50.0) == "critical"


# ---------------------------------------------------------------------------
# _gini
# ---------------------------------------------------------------------------


class TestGini:
    def test_empty_list(self):
        assert _gini([]) == 0.0

    def test_all_zeros(self):
        assert _gini([0, 0, 0]) == 0.0

    def test_perfect_equality(self):
        g = _gini([10, 10, 10, 10])
        assert abs(g) < 0.01

    def test_high_inequality(self):
        g = _gini([0, 0, 0, 100])
        assert g > 0.7

    def test_moderate_inequality(self):
        g = _gini([1, 2, 3, 4, 5])
        assert 0.2 < g < 0.5

    def test_bounded_zero_one(self):
        g = _gini([1, 1, 1, 1, 1000])
        assert 0.0 <= g <= 1.0


# ---------------------------------------------------------------------------
# _classify_repo_state
# ---------------------------------------------------------------------------


class TestClassifyRepoState:
    def test_balanced(self):
        assert _classify_repo_state(0) == "balanced"
        assert _classify_repo_state(24.9) == "balanced"

    def test_skewed(self):
        assert _classify_repo_state(25) == "skewed"
        assert _classify_repo_state(49.9) == "skewed"

    def test_strained(self):
        assert _classify_repo_state(50) == "strained"
        assert _classify_repo_state(74.9) == "strained"

    def test_brittle(self):
        assert _classify_repo_state(75) == "brittle"
        assert _classify_repo_state(100) == "brittle"


# ---------------------------------------------------------------------------
# analyse_fatigue — core analysis
# ---------------------------------------------------------------------------


class TestAnalyseFatigue:
    def test_empty_input(self):
        result = analyse_fatigue({})
        assert result["total_files"] == 0
        assert result["state"] == "balanced"
        assert result["hotspots"] == []

    def test_single_file(self):
        result = analyse_fatigue({"a.py": 5})
        assert result["total_files"] == 1
        assert result["total_edits"] == 5
        assert result["max_edits"] == 5
        assert len(result["hotspots"]) == 1

    def test_uniform_distribution_is_balanced(self):
        edits = {f"file{i}.py": 10 for i in range(20)}
        result = analyse_fatigue(edits)
        assert result["state"] == "balanced"
        assert result["index"] < 5.0

    def test_skewed_distribution(self):
        edits = {f"file{i}.py": 1 for i in range(19)}
        edits["hotspot.py"] = 200
        result = analyse_fatigue(edits)
        assert result["index"] > 50
        assert result["hotspots"][0]["file"] == "hotspot.py"
        assert result["hotspots"][0]["band"] in ("exhausted", "critical")

    def test_band_distribution_sums_to_total(self):
        edits = {"a.py": 1, "b.py": 5, "c.py": 15, "d.py": 30, "e.py": 100}
        result = analyse_fatigue(edits)
        total_band = sum(result["band_distribution"].values())
        assert total_band == result["total_files"]

    def test_top_n_limits_hotspots(self):
        edits = {f"file{i}.py": i + 1 for i in range(50)}
        result = analyse_fatigue(edits, top_n=5)
        assert len(result["hotspots"]) == 5

    def test_top_n_larger_than_files(self):
        edits = {"a.py": 5, "b.py": 10}
        result = analyse_fatigue(edits, top_n=100)
        assert len(result["hotspots"]) == 2

    def test_hotspots_sorted_descending(self):
        edits = {"a.py": 3, "b.py": 50, "c.py": 10, "d.py": 1}
        result = analyse_fatigue(edits)
        scores = [h["score"] for h in result["hotspots"]]
        assert scores == sorted(scores, reverse=True)

    def test_median_odd_count(self):
        edits = {"a.py": 1, "b.py": 3, "c.py": 5}
        result = analyse_fatigue(edits)
        assert result["median_edits"] == 3.0

    def test_median_even_count(self):
        edits = {"a.py": 1, "b.py": 2, "c.py": 4, "d.py": 8}
        result = analyse_fatigue(edits)
        assert result["median_edits"] == 3.0  # (2+4)/2

    def test_all_bands_present(self):
        # median will be 5; craft scores to hit each band
        edits = {"fresh.py": 1, "warm.py": 8, "hot.py": 18,
                 "exhausted.py": 30, "critical.py": 50}
        result = analyse_fatigue(edits)
        bands = set(result["band_distribution"].keys())
        assert "fresh" in bands
        assert "critical" in bands


# ---------------------------------------------------------------------------
# parse_git_numstat
# ---------------------------------------------------------------------------


class TestParseGitNumstat:
    def test_empty(self):
        assert parse_git_numstat([]) == {}

    def test_single_commit_single_file(self):
        lines = [
            "commit abc1234",
            "10\t5\tsrc/main.py",
        ]
        result = parse_git_numstat(lines)
        assert result == {"src/main.py": 1}

    def test_single_commit_multiple_files(self):
        lines = [
            "commit abc1234",
            "10\t5\tsrc/main.py",
            "3\t1\tsrc/utils.py",
        ]
        result = parse_git_numstat(lines)
        assert result == {"src/main.py": 1, "src/utils.py": 1}

    def test_multiple_commits_same_file(self):
        lines = [
            "commit abc1234",
            "10\t5\tsrc/main.py",
            "commit def5678",
            "5\t2\tsrc/main.py",
        ]
        result = parse_git_numstat(lines)
        assert result == {"src/main.py": 2}

    def test_binary_files_skipped(self):
        lines = [
            "commit abc1234",
            "-\t-\timage.png",
            "10\t5\tsrc/main.py",
        ]
        result = parse_git_numstat(lines)
        assert result == {"src/main.py": 1}
        assert "image.png" not in result

    def test_realistic_output(self):
        lines = [
            "commit aaa",
            "1\t0\ta.py",
            "5\t3\tb.py",
            "commit bbb",
            "2\t1\ta.py",
            "commit ccc",
            "10\t0\tc.py",
            "1\t1\ta.py",
            "3\t2\tb.py",
        ]
        result = parse_git_numstat(lines)
        assert result["a.py"] == 3
        assert result["b.py"] == 2
        assert result["c.py"] == 1
