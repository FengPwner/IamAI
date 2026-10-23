"""Tests for iamai.repo_attention_span — attention span analysis."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from iamai.repo_attention_span import (
    AttentionSpanReport,
    SpanInfo,
    _READING_DEFAULT,
    _classify,
    _classify_file,
    _dominant_area,
    attention_span_report,
    attention_summary,
)


# ---------------------------------------------------------------------------
# _classify()
# ---------------------------------------------------------------------------

class TestClassify:
    """Unit tests for the reading classifier."""

    def test_deep_focus(self):
        assert _classify(8.0) == "deep_focus"

    def test_deep_focus_above(self):
        assert _classify(15.0) == "deep_focus"

    def test_steady_lower_bound(self):
        assert _classify(4.0) == "steady"

    def test_steady_upper_bound(self):
        assert _classify(7.9) == "steady"

    def test_restless_lower_bound(self):
        assert _classify(2.0) == "restless"

    def test_restless_upper_bound(self):
        assert _classify(3.99) == "restless"

    def test_scattered(self):
        assert _classify(1.0) == "scattered"

    def test_scattered_zero(self):
        assert _classify(0.0) == "scattered"

    def test_scattered_small(self):
        assert _classify(1.99) == "scattered"


# ---------------------------------------------------------------------------
# _classify_file()
# ---------------------------------------------------------------------------

class TestClassifyFile:
    """Unit tests for file-to-area mapping."""

    def test_iamai_module(self):
        assert _classify_file("iamai/foo.py") == "iamai"

    def test_tests_module(self):
        assert _classify_file("tests/test_foo.py") == "tests"

    def test_tools_module(self):
        assert _classify_file("tools/bar.py") == "tools"

    def test_notes_module(self):
        assert _classify_file("notes/reading.md") == "notes"

    def test_docs_module(self):
        assert _classify_file("docs/DEVLOG.md") == "docs"

    def test_data_module(self):
        assert _classify_file("data/strokes.jsonl") == "data"

    def test_root_file(self):
        assert _classify_file("README.md") == "root"

    def test_unknown_area(self):
        assert _classify_file("scripts/deploy.sh") == "other"

    def test_backslash_path(self):
        assert _classify_file("iamai\\foo.py") == "iamai"


# ---------------------------------------------------------------------------
# _dominant_area()
# ---------------------------------------------------------------------------

class TestDominantArea:
    """Unit tests for dominant area selection."""

    def test_single_file(self):
        assert _dominant_area(["iamai/foo.py"]) == "iamai"

    def test_majority_wins(self):
        files = ["iamai/a.py", "iamai/b.py", "tests/test_a.py"]
        assert _dominant_area(files) == "iamai"

    def test_tie_break_alphabetical(self):
        files = ["iamai/a.py", "tests/test_a.py"]
        # Both have 1 file; "iamai" < "tests" alphabetically.
        assert _dominant_area(files) == "iamai"

    def test_tie_break_other(self):
        files = ["tools/a.py", "notes/a.md"]
        # Both have 1 file; "notes" < "tools" alphabetically.
        assert _dominant_area(files) == "notes"

    def test_empty_files(self):
        assert _dominant_area([]) == "empty"

    def test_all_root(self):
        assert _dominant_area(["README.md", "LICENSE"]) == "root"

    def test_all_other(self):
        assert _dominant_area(["scripts/deploy.sh"]) == "other"

    def test_three_way_tie(self):
        files = ["iamai/a.py", "tests/a.py", "tools/a.py"]
        # All have 1 file; "iamai" is alphabetically first.
        assert _dominant_area(files) == "iamai"

    def test_deeply_nested(self):
        files = ["iamai/sub/deep/foo.py"] * 3 + ["tests/t.py"]
        assert _dominant_area(files) == "iamai"


# ---------------------------------------------------------------------------
# AttentionSpanReport / SpanInfo
# ---------------------------------------------------------------------------

class TestDataClasses:
    """Tests for the report data structures."""

    def test_default_report(self):
        r = AttentionSpanReport()
        assert r.span_count == 0
        assert r.avg_span == 0.0
        assert r.reading == _READING_DEFAULT
        assert r.spans == []

    def test_to_dict(self):
        span = SpanInfo(area="iamai", start="abc12345", end="def67890", length=5)
        r = AttentionSpanReport(
            span_count=1,
            avg_span=5.0,
            reading="steady",
            spans=[span],
            total_commits=5,
        )
        d = r.to_dict()
        assert d["span_count"] == 1
        assert d["avg_span"] == 5.0
        assert d["reading"] == "steady"
        assert d["total_commits"] == 5
        assert len(d["spans"]) == 1
        assert d["spans"][0]["area"] == "iamai"
        assert d["spans"][0]["length"] == 5


# ---------------------------------------------------------------------------
# attention_span_report() with mocked git
# ---------------------------------------------------------------------------

def _mock_git(shas: list[str], file_map: dict[str, list[str]]):
    """Create a mock _run_git that returns shas and file lists."""

    def fake_run_git(repo, *args):
        if args[0] == "log":
            return "\n".join(shas)
        if args[0] == "diff-tree":
            sha = args[-1]
            return "\n".join(file_map.get(sha, []))
        return ""

    return fake_run_git


class TestAttentionSpanReport:
    """Integration-style tests with mocked git."""

    def test_fewer_than_2_commits(self):
        with patch("iamai.repo_attention_span._run_git") as mock_git:
            mock_git.return_value = "abc123"
            report = attention_span_report(repo_path=".", last=10)
            assert report.span_count == 0

    def test_single_area_all_iamai(self):
        shas = [f"sha{i:04d}xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" for i in range(5)]
        file_map = {sha: ["iamai/module.py"] for sha in shas}
        with patch("iamai.repo_attention_span._run_git", side_effect=_mock_git(shas, file_map)):
            report = attention_span_report(repo_path=".", last=5)
            assert report.span_count == 1
            assert report.avg_span == 5.0
            assert report.reading == "steady"

    def test_two_areas_split(self):
        shas = [f"sha{i:04d}xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" for i in range(6)]
        file_map = {}
        # First 3 commits: iamai
        for sha in shas[:3]:
            file_map[sha] = ["iamai/foo.py"]
        # Last 3 commits: tests
        for sha in shas[3:]:
            file_map[sha] = ["tests/test_foo.py"]
        with patch("iamai.repo_attention_span._run_git", side_effect=_mock_git(shas, file_map)):
            report = attention_span_report(repo_path=".", last=6)
            assert report.span_count == 2
            assert report.avg_span == 3.0
            assert report.reading == "restless"

    def test_alternating_areas_scattered(self):
        shas = [f"sha{i:04d}xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" for i in range(6)]
        file_map = {}
        areas = ["iamai", "tests", "iamai", "tests", "iamai", "tests"]
        for sha, area in zip(shas, areas):
            file_map[sha] = [f"{area}/foo.py"]
        with patch("iamai.repo_attention_span._run_git", side_effect=_mock_git(shas, file_map)):
            report = attention_span_report(repo_path=".", last=6)
            assert report.span_count == 6
            assert report.avg_span == 1.0
            assert report.reading == "scattered"

    def test_deep_focus_long_span(self):
        shas = [f"sha{i:04d}xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" for i in range(10)]
        file_map = {sha: ["iamai/module.py"] for sha in shas}
        with patch("iamai.repo_attention_span._run_git", side_effect=_mock_git(shas, file_map)):
            report = attention_span_report(repo_path=".", last=10)
            assert report.span_count == 1
            assert report.avg_span == 10.0
            assert report.reading == "deep_focus"

    def test_merge_commit_inherits_area(self):
        # shas are returned newest-first by git log, then reversed.
        # Index 0 = newest, index 4 = oldest (chronological order).
        shas = [f"sha{i:04d}xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" for i in range(5)]
        file_map = {
            shas[4]: ["iamai/a.py"],   # oldest
            shas[3]: ["iamai/b.py"],
            shas[2]: [],               # merge commit, no files → inherits iamai
            shas[1]: ["iamai/c.py"],
            shas[0]: ["tests/t.py"],   # newest
        }
        with patch("iamai.repo_attention_span._run_git", side_effect=_mock_git(shas, file_map)):
            report = attention_span_report(repo_path=".", last=5)
            # Merge commit inherits "iamai", so first span = 4 commits
            assert report.span_count == 2
            assert report.spans[0].length == 4
            assert report.spans[0].area == "iamai"

    def test_multiple_spans_mixed(self):
        shas = [f"sha{i:04d}xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" for i in range(8)]
        file_map = {}
        # 3 iamai, 2 tests, 3 tools
        areas_list = ["iamai"] * 3 + ["tests"] * 2 + ["tools"] * 3
        for sha, area in zip(shas, areas_list):
            file_map[sha] = [f"{area}/file.py"]
        with patch("iamai.repo_attention_span._run_git", side_effect=_mock_git(shas, file_map)):
            report = attention_span_report(repo_path=".", last=8)
            assert report.span_count == 3
            assert report.avg_span == pytest.approx(8 / 3)
            assert report.total_commits == 8


# ---------------------------------------------------------------------------
# attention_summary()
# ---------------------------------------------------------------------------

class TestAttentionSummary:
    """Tests for the human-readable summary."""

    def test_empty_report(self):
        assert attention_summary(AttentionSpanReport()) == "repo_attention_span: no commits to analyse"

    def test_normal_report(self):
        report = AttentionSpanReport(
            span_count=3,
            avg_span=4.5,
            reading="steady",
            total_commits=13,
        )
        s = attention_summary(report)
        assert "4.5 commits/span" in s
        assert "steady" in s
        assert "3 spans" in s
        assert "13 commits" in s

    def test_scattered_report(self):
        report = AttentionSpanReport(
            span_count=10,
            avg_span=1.0,
            reading="scattered",
            total_commits=10,
        )
        s = attention_summary(report)
        assert "scattered" in s
