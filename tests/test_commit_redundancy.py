"""Tests for iamai.commit_redundancy — inter-commit redundancy detection.

Covers: analyse_pair, analyse_window, redundancy_timeline, edge cases,
boundary conditions, weight overrides, verdict thresholds.
"""

import pytest

from iamai.commit_redundancy import (
    DEFAULT_WEIGHTS,
    VERDICT_THRESHOLDS,
    RedundancyReport,
    WindowReport,
    analyse_pair,
    analyse_window,
    redundancy_timeline,
    _jaccard,
    _bigram_similarity,
    _normalise_path_set,
    _avg_path_depth,
    _verdict,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _commit(hash_: str = "", files: list[str] | None = None, message: str = "") -> dict:
    return {"hash": hash_, "files": files or [], "message": message}


# ---------------------------------------------------------------------------
# _jaccard
# ---------------------------------------------------------------------------

class TestJaccard:
    def test_identical_sets(self):
        s = {"a", "b", "c"}
        assert _jaccard(s, s) == 1.0

    def test_disjoint_sets(self):
        assert _jaccard({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial_overlap(self):
        assert _jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)

    def test_both_empty(self):
        assert _jaccard(set(), set()) == 0.0

    def test_one_empty(self):
        assert _jaccard({"a"}, set()) == 0.0


# ---------------------------------------------------------------------------
# _bigram_similarity
# ---------------------------------------------------------------------------

class TestBigramSimilarity:
    def test_identical_strings(self):
        assert _bigram_similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        sim = _bigram_similarity("abc", "xyz")
        assert sim == 0.0

    def test_similar_strings(self):
        sim = _bigram_similarity("add feature x", "add feature y")
        assert sim > 0.5

    def test_empty_strings(self):
        assert _bigram_similarity("", "") == 0.0

    def test_single_char(self):
        assert _bigram_similarity("a", "b") == 0.0


# ---------------------------------------------------------------------------
# _normalise_path_set
# ---------------------------------------------------------------------------

class TestNormalisePathSet:
    def test_strips_dot_slash(self):
        assert _normalise_path_set(["./foo/bar.py"]) == {"foo/bar.py"}

    def test_strips_whitespace(self):
        assert _normalise_path_set(["  foo.py  "]) == {"foo.py"}

    def test_filters_empty(self):
        assert _normalise_path_set(["", "  ", "a.py"]) == {"a.py"}


# ---------------------------------------------------------------------------
# _avg_path_depth
# ---------------------------------------------------------------------------

class TestAvgPathDepth:
    def test_root_files(self):
        assert _avg_path_depth(["a.py", "b.py"]) == 0.0

    def test_nested(self):
        assert _avg_path_depth(["a/b/c.py"]) == 2.0

    def test_empty(self):
        assert _avg_path_depth([]) == 0.0

    def test_mixed(self):
        result = _avg_path_depth(["a.py", "x/y/z.py"])
        assert result == pytest.approx(1.0)  # (0 + 2) / 2


# ---------------------------------------------------------------------------
# _verdict
# ---------------------------------------------------------------------------

class TestVerdict:
    def test_severe(self):
        assert _verdict(0.65) == "severe"
        assert _verdict(1.0) == "severe"

    def test_mild(self):
        assert _verdict(0.35) == "mild"
        assert _verdict(0.5) == "mild"

    def test_healthy(self):
        assert _verdict(0.0) == "healthy"
        assert _verdict(0.34) == "healthy"


# ---------------------------------------------------------------------------
# analyse_pair
# ---------------------------------------------------------------------------

class TestAnalysePair:
    def test_identical_commits(self):
        c = _commit("aaa", ["src/foo.py", "src/bar.py"], "add foo and bar")
        r = analyse_pair(c, c)
        assert r.file_overlap == 1.0
        assert r.message_similarity > 0.8
        assert r.verdict == "severe"

    def test_completely_different(self):
        a = _commit("aaa", ["src/foo.py"], "add foo")
        b = _commit("bbb", ["docs/readme.md", "tests/test_bar.py"], "write docs and tests")
        r = analyse_pair(a, b)
        assert r.file_overlap == 0.0
        assert r.message_similarity < 0.3
        assert r.verdict == "healthy"

    def test_same_files_different_messages(self):
        a = _commit("aaa", ["src/foo.py"], "implement login")
        b = _commit("bbb", ["src/foo.py"], "fix logout bug in session handler")
        r = analyse_pair(a, b)
        assert r.file_overlap == 1.0
        assert r.message_similarity < 0.5

    def test_composite_bounded(self):
        a = _commit("aaa", [f"src/mod_{i}.py" for i in range(50)], "x" * 100)
        b = _commit("bbb", [f"src/mod_{i}.py" for i in range(50)], "x" * 100)
        r = analyse_pair(a, b)
        assert 0.0 <= r.composite <= 1.0

    def test_empty_commits(self):
        r = analyse_pair(_commit(), _commit())
        assert r.composite >= 0.0
        assert r.file_overlap == 0.0

    def test_as_dict(self):
        a = _commit("aaa", ["a.py"], "first")
        b = _commit("bbb", ["b.py"], "second")
        r = analyse_pair(a, b)
        d = r.as_dict()
        assert "commit_a" in d
        assert "composite" in d
        assert "verdict" in d
        assert d["commit_a"] == "aaa"

    def test_custom_weights(self):
        a = _commit("aaa", ["src/foo.py"], "add foo")
        b = _commit("bbb", ["src/foo.py"], "something entirely different now")
        # Zero out file_overlap weight
        w = {"file_overlap": 0.0, "path_depth_delta": 0.5, "message_similarity": 0.5}
        r = analyse_pair(a, b, weights=w)
        # file_overlap is 1.0 but weight is 0, so composite < 1.0
        assert r.composite < 1.0

    def test_path_depth_same_area(self):
        a = _commit("a", ["src/x/y/a.py"], "msg1")
        b = _commit("b", ["src/x/y/b.py"], "msg2")
        r = analyse_pair(a, b)
        # Same depth → delta = 0 → pd_score = 1.0 (high redundancy signal)
        assert r.path_depth_delta == 1.0

    def test_path_depth_different_area(self):
        a = _commit("a", ["a.py"], "msg1")
        b = _commit("b", ["src/deep/nested/b.py"], "msg2")
        r = analyse_pair(a, b)
        # depth delta = 3, normalised = 3/5 = 0.6, pd_score = 0.4
        assert r.path_depth_delta < 0.5


# ---------------------------------------------------------------------------
# analyse_window
# ---------------------------------------------------------------------------

class TestAnalyseWindow:
    def test_empty(self):
        r = analyse_window([])
        assert r.verdict == "healthy"
        assert r.window_size == 0

    def test_single_commit(self):
        r = analyse_window([_commit("a", ["a.py"], "init")])
        assert r.verdict == "healthy"
        assert r.window_size == 1

    def test_two_different(self):
        commits = [
            _commit("a", ["a.py"], "init"),
            _commit("b", ["b.py"], "add b"),
        ]
        r = analyse_window(commits)
        assert r.window_size == 2
        assert len(r.pairs) == 1

    def test_window_truncation(self):
        commits = [_commit(str(i), [f"f{i}.py"], f"commit {i}") for i in range(20)]
        r = analyse_window(commits, window_size=5)
        assert r.window_size == 5
        assert len(r.pairs) == 4

    def test_severe_window(self):
        # All identical commits → severe
        c = _commit("x", ["a.py", "b.py"], "same message every time")
        r = analyse_window([c] * 6)
        assert r.verdict == "severe"
        assert r.severe_count > 0

    def test_healthy_window(self):
        msgs = [
            "implement login flow",
            "refactor database connection pooling",
            "write unit tests for parser module",
            "add dark mode toggle to settings",
            "fix memory leak in cache layer",
            "document public API endpoints",
        ]
        commits = [
            _commit(str(i), [f"dir{i}/unique_{i}.py"], msgs[i])
            for i in range(6)
        ]
        r = analyse_window(commits)
        assert r.verdict in ("healthy", "mild")

    def test_as_dict(self):
        commits = [
            _commit("a", ["a.py"], "init"),
            _commit("b", ["b.py"], "second"),
        ]
        r = analyse_window(commits)
        d = r.as_dict()
        assert "mean_redundancy" in d
        assert "verdict" in d
        assert "pair_count" in d

    def test_counts_sum(self):
        c = _commit("x", ["a.py"], "msg")
        r = analyse_window([c] * 5)
        assert r.severe_count + r.mild_count + r.healthy_count == len(r.pairs)


# ---------------------------------------------------------------------------
# redundancy_timeline
# ---------------------------------------------------------------------------

class TestRedundancyTimeline:
    def test_empty(self):
        assert redundancy_timeline([]) == []

    def test_single(self):
        assert redundancy_timeline([_commit("a", ["a.py"], "init")]) == []

    def test_multiple(self):
        commits = [
            _commit("a", ["a.py"], "first"),
            _commit("b", ["b.py"], "second"),
            _commit("c", ["c.py"], "third"),
        ]
        timeline = redundancy_timeline(commits)
        assert len(timeline) == 2
        for entry in timeline:
            assert "commit_a" in entry
            assert "commit_b" in entry
            assert "composite" in entry
            assert "verdict" in entry

    def test_values_bounded(self):
        commits = [_commit(str(i), [f"f{i}.py"], f"msg {i}") for i in range(5)]
        for entry in redundancy_timeline(commits):
            assert 0.0 <= entry["composite"] <= 1.0


# ---------------------------------------------------------------------------
# dataclass frozen
# ---------------------------------------------------------------------------

class TestDataclasses:
    def test_report_frozen(self):
        r = RedundancyReport()
        with pytest.raises(AttributeError):
            r.composite = 0.5  # type: ignore

    def test_window_report_frozen(self):
        r = WindowReport()
        with pytest.raises(AttributeError):
            r.verdict = "severe"  # type: ignore


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_weights_sum_to_one(self):
        assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)

    def test_thresholds_ordered(self):
        assert VERDICT_THRESHOLDS["mild"] < VERDICT_THRESHOLDS["severe"]
