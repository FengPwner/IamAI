"""Tests for commit_attention_map — classify repo attention focus.

run: python3 -m pytest tests/test_commit_attention_map.py -v
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.commit_attention_map import (
    classify_file,
    attention_distribution,
    focus_entropy,
    classify_focus,
    analyse_attention,
    attention_report,
)


# ---------------------------------------------------------------------------
# classify_file
# ---------------------------------------------------------------------------


class TestClassifyFile:
    def test_code_file(self):
        assert classify_file("iamai/commit_entropy.py") == "code"

    def test_code_nested(self):
        assert classify_file("iamai/sub/module.py") == "code"

    def test_code_not_py(self):
        assert classify_file("iamai/README.txt") == "meta"

    def test_init_is_config(self):
        assert classify_file("iamai/__init__.py") == "config"

    def test_test_file_by_name(self):
        assert classify_file("test_something.py") == "tests"

    def test_test_file_in_tests_dir(self):
        assert classify_file("tests/test_fatigue.py") == "tests"

    def test_test_file_in_tests_dir_unusual_name(self):
        assert classify_file("tests/conftest.py") == "tests"

    def test_tool_script(self):
        assert classify_file("tools/run_both.sh") == "tools"

    def test_tool_python(self):
        assert classify_file("tools/writer_loop.py") == "tools"

    def test_doc_in_docs(self):
        assert classify_file("docs/DEVLOG.md") == "docs"

    def test_doc_in_notes(self):
        assert classify_file("notes/conventions.md") == "docs"

    def test_doc_at_root(self):
        assert classify_file("README.md") == "docs"

    def test_data_file(self):
        assert classify_file("data/strokes.jsonl") == "data"

    def test_data_nested(self):
        assert classify_file("data/archive/old.jsonl") == "data"

    def test_github_ci(self):
        assert classify_file(".github/workflows/ci.yml") == "config"

    def test_gitignore(self):
        assert classify_file(".gitignore") == "config"

    def test_pyproject(self):
        assert classify_file("pyproject.toml") == "config"

    def test_unknown_file(self):
        assert classify_file("random_stuff.txt") == "meta"

    def test_deep_unknown(self):
        assert classify_file("some/deep/path/file.log") == "meta"


# ---------------------------------------------------------------------------
# attention_distribution
# ---------------------------------------------------------------------------


class TestAttentionDistribution:
    def test_empty_list(self):
        assert attention_distribution([]) == {}

    def test_single_category(self):
        dist = attention_distribution([
            "iamai/a.py",
            "iamai/b.py",
            "iamai/c.py",
        ])
        assert dist == {"code": 3}

    def test_mixed_categories(self):
        dist = attention_distribution([
            "iamai/a.py",
            "tests/test_a.py",
            "docs/X.md",
            "tools/run.sh",
        ])
        assert dist == {"code": 1, "tests": 1, "docs": 1, "tools": 1}

    def test_counting(self):
        dist = attention_distribution([
            "iamai/a.py",
            "iamai/b.py",
            "tests/test_a.py",
        ])
        assert dist["code"] == 2
        assert dist["tests"] == 1


# ---------------------------------------------------------------------------
# focus_entropy
# ---------------------------------------------------------------------------


class TestFocusEntropy:
    def test_empty_distribution(self):
        assert focus_entropy({}) == 0.0

    def test_single_category(self):
        assert focus_entropy({"code": 10}) == 0.0

    def test_perfect_split_two(self):
        h = focus_entropy({"code": 5, "tests": 5})
        assert abs(h - 1.0) < 1e-9

    def test_perfect_split_four(self):
        h = focus_entropy({"code": 4, "tests": 4, "docs": 4, "tools": 4})
        assert abs(h - 1.0) < 1e-9

    def test_heavy_skew(self):
        # 90% code, 10% tests → low entropy (tunnel-ish)
        h = focus_entropy({"code": 90, "tests": 10})
        assert 0.0 < h < 0.5

    def test_moderate_spread(self):
        h = focus_entropy({"code": 10, "tests": 8, "docs": 5, "tools": 3})
        assert 0.5 < h < 1.0

    def test_all_zeros(self):
        assert focus_entropy({"code": 0, "tests": 0}) == 0.0


# ---------------------------------------------------------------------------
# classify_focus
# ---------------------------------------------------------------------------


class TestClassifyFocus:
    def test_tunnel_lower(self):
        assert classify_focus(0.0) == "tunnel"

    def test_tunnel_upper(self):
        assert classify_focus(0.29) == "tunnel"

    def test_focused_lower(self):
        assert classify_focus(0.30) == "focused"

    def test_focused_mid(self):
        assert classify_focus(0.42) == "focused"

    def test_focused_upper(self):
        assert classify_focus(0.54) == "focused"

    def test_balanced_lower(self):
        assert classify_focus(0.55) == "balanced"

    def test_balanced_mid(self):
        assert classify_focus(0.67) == "balanced"

    def test_balanced_upper(self):
        assert classify_focus(0.79) == "balanced"

    def test_scattered_lower(self):
        assert classify_focus(0.80) == "scattered"

    def test_scattered_upper(self):
        assert classify_focus(1.0) == "scattered"

    def test_above_one_fallback(self):
        assert classify_focus(1.5) == "scattered"


# ---------------------------------------------------------------------------
# analyse_attention
# ---------------------------------------------------------------------------


class TestAnalyseAttention:
    def test_empty_input(self):
        result = analyse_attention([])
        assert result["focus"] == 0.0
        assert result["sample_size"] == 0
        assert result["dominant"] == "none"

    def test_single_commit_tunnel(self):
        commits = [["iamai/a.py", "iamai/b.py", "iamai/c.py"]]
        result = analyse_attention(commits)
        assert result["band"] == "tunnel"
        assert result["dominant"] == "code"
        assert result["dominant_share"] == 100.0

    def test_multiple_commits_balanced(self):
        commits = [
            ["iamai/a.py"],
            ["tests/test_a.py"],
            ["docs/README.md"],
            ["tools/run.sh"],
        ]
        result = analyse_attention(commits)
        assert result["band"] in ("balanced", "scattered")
        assert result["sample_size"] == 4

    def test_window_limits_size(self):
        commits = [["iamai/a.py"]] * 50
        result = analyse_attention(commits, window=10)
        assert result["sample_size"] == 10

    def test_summary_is_string(self):
        commits = [["iamai/a.py", "tests/test_a.py"]]
        result = analyse_attention(commits)
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0

    def test_per_commit_structure(self):
        commits = [
            ["iamai/a.py", "tests/test_a.py"],
            ["docs/X.md"],
        ]
        result = analyse_attention(commits)
        assert len(result["per_commit"]) == 2
        assert result["per_commit"][0] == {"code": 1, "tests": 1}
        assert result["per_commit"][1] == {"docs": 1}


# ---------------------------------------------------------------------------
# attention_report
# ---------------------------------------------------------------------------


class TestAttentionReport:
    def test_has_recommendation(self):
        commits = [["iamai/a.py", "iamai/b.py"]]
        result = attention_report(commits)
        assert "recommendation" in result
        assert len(result["recommendation"]) > 0

    def test_tunnel_recommendation(self):
        commits = [["iamai/a.py"] * 10]
        result = attention_report(commits)
        assert "neglected" in result["recommendation"].lower()

    def test_focused_recommendation(self):
        # 5 code + 1 test → entropy ~0.65 → balanced band
        commits = [
            ["iamai/a.py"] * 5,
            ["tests/test_a.py"],
        ]
        result = attention_report(commits)
        assert result["band"] == "balanced"
        assert result["dominant"] == "code"

    def test_tunnel_recommendation_pure(self):
        # pure single-category → tunnel
        commits = [["iamai/a.py"] * 10]
        result = attention_report(commits)
        assert result["band"] == "tunnel"

    def test_scattered_recommendation(self):
        commits = [
            ["iamai/a.py"],
            ["tests/test_a.py"],
            ["docs/X.md"],
            ["tools/run.sh"],
            ["data/s.jsonl"],
            [".github/ci.yml"],
        ]
        result = attention_report(commits)
        assert result["recommendation"]  # non-empty


# ---------------------------------------------------------------------------
# integration: real-repo smoke test
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_real_repo_smoke(self):
        """Run against actual repo files if available."""
        import subprocess

        repo_root = REPO
        try:
            out = subprocess.check_output(
                ["git", "log", "--name-only", "--pretty=format:", "-20"],
                cwd=repo_root,
                text=True,
                timeout=10,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            pytest.skip("git not available or not a repo")

        # Parse output into per-commit file lists
        file_lists: list[list[str]] = []
        current: list[str] = []
        for line in out.splitlines():
            stripped = line.strip()
            if stripped == "" and current:
                file_lists.append(current)
                current = []
            elif stripped:
                current.append(stripped)
        if current:
            file_lists.append(current)

        if not file_lists:
            pytest.skip("no commits found")

        result = attention_report(file_lists)
        assert "focus" in result
        assert "band" in result
        assert "distribution" in result
        assert result["sample_size"] > 0
