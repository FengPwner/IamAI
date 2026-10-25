"""Tests for iamai.commit_file_overlap — consecutive commit file similarity."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from iamai.commit_file_overlap import (
    FileOverlapReport,
    _READING_DEFAULT,
    _classify,
    jaccard,
    file_overlap_report,
    overlap_summary,
)


# ---------------------------------------------------------------------------
# jaccard()
# ---------------------------------------------------------------------------

class TestJaccard:
    """Unit tests for the Jaccard similarity helper."""

    def test_identical_sets(self):
        assert jaccard({"a", "b", "c"}, {"a", "b", "c"}) == 1.0

    def test_disjoint_sets(self):
        assert jaccard({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial_overlap(self):
        # {a} ∩ {a, b} = {a}, {a} ∪ {a, b} = {a, b}
        assert jaccard({"a"}, {"a", "b"}) == pytest.approx(0.5)

    def test_subset(self):
        # {a, b} ∩ {a, b, c, d} = {a, b}, union = {a, b, c, d}
        assert jaccard({"a", "b"}, {"a", "b", "c", "d"}) == pytest.approx(0.5)

    def test_both_empty(self):
        assert jaccard(set(), set()) == 0.0

    def test_one_empty(self):
        # {a} ∩ {} = {}, {a} ∪ {} = {a}
        assert jaccard({"a"}, set()) == 0.0

    def test_single_element_overlap(self):
        assert jaccard({"x"}, {"x"}) == 1.0

    def test_large_sets(self):
        a = set(range(100))
        b = set(range(50, 150))
        # intersection = {50..99} = 50, union = {0..149} = 150
        assert jaccard(a, b) == pytest.approx(50 / 150)


# ---------------------------------------------------------------------------
# _classify()
# ---------------------------------------------------------------------------

class TestClassify:
    """Verify the reading thresholds."""

    def test_reworking(self):
        assert _classify(0.50) == "reworking"
        assert _classify(0.99) == "reworking"

    def test_iterating(self):
        assert _classify(0.25) == "iterating"
        assert _classify(0.49) == "iterating"

    def test_exploring(self):
        assert _classify(0.10) == "exploring"
        assert _classify(0.24) == "exploring"

    def test_scattered(self):
        assert _classify(0.0) == _READING_DEFAULT
        assert _classify(0.09) == _READING_DEFAULT

    def test_boundary_exact(self):
        assert _classify(0.50) == "reworking"
        assert _classify(0.25) == "iterating"
        assert _classify(0.10) == "exploring"


# ---------------------------------------------------------------------------
# FileOverlapReport defaults
# ---------------------------------------------------------------------------

class TestReportDefaults:
    def test_empty_report(self):
        report = FileOverlapReport()
        assert report.pair_count == 0
        assert report.scores == []
        assert report.overlap_score == 0.0
        assert report.reading == _READING_DEFAULT

    def test_to_dict_empty(self):
        d = FileOverlapReport().to_dict()
        assert d["pair_count"] == 0
        assert d["overlap_score"] == 0.0

    def test_to_dict_with_data(self):
        report = FileOverlapReport(
            pair_count=2,
            scores=[0.5, 0.3],
            overlap_score=0.4,
            reading="iterating",
        )
        d = report.to_dict()
        assert d["pair_count"] == 2
        assert d["overlap_score"] == 0.4
        assert d["reading"] == "iterating"
        assert d["scores"] == [0.5, 0.3]


# ---------------------------------------------------------------------------
# overlap_summary()
# ---------------------------------------------------------------------------

class TestOverlapSummary:
    def test_empty(self):
        assert overlap_summary(FileOverlapReport()) == (
            "commit_file_overlap: no pairs to analyse"
        )

    def test_with_data(self):
        report = FileOverlapReport(
            pair_count=10,
            overlap_score=0.345,
            reading="iterating",
        )
        text = overlap_summary(report)
        assert "34.5%" in text
        assert "iterating" in text
        assert "10 commit pairs" in text

    def test_zero_overlap(self):
        report = FileOverlapReport(
            pair_count=5,
            overlap_score=0.0,
            reading=_READING_DEFAULT,
        )
        text = overlap_summary(report)
        assert "0.0%" in text
        assert _READING_DEFAULT in text


# ---------------------------------------------------------------------------
# file_overlap_report() — integration with mocked git
# ---------------------------------------------------------------------------

class TestFileOverlapReport:
    """Test the full pipeline with mocked git output."""

    def _mock_git(self, side_effect_map):
        """Create a mock for subprocess.run keyed by args."""
        def fake_run(cmd, **kwargs):
            key = " ".join(cmd)
            for pattern, output in side_effect_map.items():
                if pattern in key:
                    result = type("R", (), {
                        "returncode": 0,
                        "stdout": output,
                        "stderr": "",
                    })()
                    return result
            result = type("R", (), {
                "returncode": 0, "stdout": "", "stderr": ""
            })()
            return result
        return fake_run

    @patch("iamai.commit_file_overlap.subprocess.run")
    def test_single_commit_no_pairs(self, mock_run):
        """With only one commit, there are no pairs."""
        mock_run.side_effect = self._mock_git({
            "log": "abc123\n",
            "diff-tree": "file.py\n",
        })
        report = file_overlap_report(repo_path="/tmp/fake", last=50)
        assert report.pair_count == 0

    @patch("iamai.commit_file_overlap.subprocess.run")
    def test_two_identical_commits(self, mock_run):
        """Two commits touching the same files → overlap 1.0."""
        log_output = "aaa\nbbb\n"
        diff_output = "foo.py\nbar.py\n"

        def fake_run(cmd, **kwargs):
            key = " ".join(cmd)
            if "log" in key:
                return type("R", (), {"returncode": 0, "stdout": log_output, "stderr": ""})()
            if "diff-tree" in key:
                return type("R", (), {"returncode": 0, "stdout": diff_output, "stderr": ""})()
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        mock_run.side_effect = fake_run
        report = file_overlap_report(repo_path="/tmp/fake", last=50)
        assert report.pair_count == 1
        assert report.overlap_score == 1.0
        assert report.reading == "reworking"

    @patch("iamai.commit_file_overlap.subprocess.run")
    def test_two_disjoint_commits(self, mock_run):
        """Two commits with no file overlap → overlap 0.0."""
        call_count = [0]

        def fake_run(cmd, **kwargs):
            key = " ".join(cmd)
            if "log" in key:
                return type("R", (), {"returncode": 0, "stdout": "aaa\nbbb\n", "stderr": ""})()
            if "diff-tree" in key:
                call_count[0] += 1
                if call_count[0] == 1:
                    return type("R", (), {"returncode": 0, "stdout": "foo.py\n", "stderr": ""})()
                else:
                    return type("R", (), {"returncode": 0, "stdout": "bar.py\n", "stderr": ""})()
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        mock_run.side_effect = fake_run
        report = file_overlap_report(repo_path="/tmp/fake", last=50)
        assert report.pair_count == 1
        assert report.overlap_score == 0.0
        assert report.reading == "scattered"

    @patch("iamai.commit_file_overlap.subprocess.run")
    def test_three_commits_partial_overlap(self, mock_run):
        """Three commits: A→B shares files, B→C does not."""
        file_map = {
            "aaa": "x.py\ny.py\n",
            "bbb": "y.py\nz.py\n",
            "ccc": "w.py\nv.py\n",
        }

        def fake_run(cmd, **kwargs):
            key = " ".join(cmd)
            if "log" in key:
                return type("R", (), {"returncode": 0, "stdout": "aaa\nbbb\nccc\n", "stderr": ""})()
            if "diff-tree" in key:
                for sha, files in file_map.items():
                    if sha in key:
                        return type("R", (), {"returncode": 0, "stdout": files, "stderr": ""})()
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        mock_run.side_effect = fake_run
        report = file_overlap_report(repo_path="/tmp/fake", last=50)
        assert report.pair_count == 2
        # Pair 1 (ccc→bbb): {w,v} vs {y,z} → 0.0
        # Pair 2 (bbb→aaa): {y,z} vs {x,y} → 1/3 ≈ 0.333
        assert report.scores[0] == 0.0
        assert report.scores[1] == pytest.approx(1 / 3)
        assert report.overlap_score == pytest.approx(1 / 6)
        assert report.reading == "exploring"
