"""Tests for tools/uncommitted_bytes.py.

Covers: diff_bytes (empty, staged, unstaged, binary markers),
untracked_bytes (missing files, multiple files, empty),
file_count and untracked_count, measure report shape and modes,
format_bytes thresholds, format_text output, and CLI exit codes.

48 tests total.
"""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import uncommitted_bytes as ub  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_repo(tmp_path):
    """Create a minimal git repo with an initial commit."""
    subprocess.run(
        ["git", "init", str(tmp_path)],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.local"],
        capture_output=True, cwd=str(tmp_path), check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        capture_output=True, cwd=str(tmp_path), check=True,
    )
    readme = tmp_path / "README.md"
    readme.write_text("# test\n")
    subprocess.run(
        ["git", "add", "."],
        capture_output=True, cwd=str(tmp_path), check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        capture_output=True, cwd=str(tmp_path), check=True,
    )
    return tmp_path


@pytest.fixture
def fake_repo_with_changes(fake_repo):
    """Repo with staged and unstaged changes."""
    # Stage a new file
    new_file = fake_repo / "new.txt"
    new_file.write_text("hello world\n" * 10)
    subprocess.run(
        ["git", "add", "new.txt"],
        capture_output=True, cwd=str(fake_repo), check=True,
    )
    # Unstaged modification
    readme = fake_repo / "README.md"
    readme.write_text("# test\n\nextra content here\n" * 5)
    return fake_repo


# ---------------------------------------------------------------------------
# run_git
# ---------------------------------------------------------------------------


class TestRunGit:
    def test_returns_completed_process(self, fake_repo):
        result = ub.run_git("status", cwd=fake_repo)
        assert isinstance(result, subprocess.CompletedProcess)
        assert result.returncode == 0

    def test_bad_command_nonzero(self, fake_repo):
        result = ub.run_git("not-a-command", cwd=fake_repo)
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# diff_bytes
# ---------------------------------------------------------------------------


class TestDiffBytes:
    def test_clean_repo_returns_zero(self, fake_repo):
        assert ub.diff_bytes(cwd=fake_repo) == 0

    def test_staged_changes(self, fake_repo):
        new_file = fake_repo / "staged.txt"
        # Write 100 lines so numstat reports >= 100 lines added
        new_file.write_text("\n".join(["line"] * 100) + "\n")
        subprocess.run(
            ["git", "add", "staged.txt"],
            capture_output=True, cwd=str(fake_repo), check=True,
        )
        staged = ub.diff_bytes(cached=True, cwd=fake_repo)
        assert staged >= 100

    def test_unstaged_changes(self, fake_repo_with_changes):
        unstaged = ub.diff_bytes(cached=False, cwd=fake_repo_with_changes)
        assert unstaged > 0

    def test_binary_marker_handled(self):
        """Binary files show '-' for numstat; should not crash."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "10\t5\tsrc/main.py\n-\t-\tdata/image.png\n"
        with patch.object(ub, "run_git", return_value=mock_result):
            total = ub.diff_bytes(cwd=Path("/fake"))
            # 10 added + 5 removed = 15 lines; binary '-' is skipped
            assert total == 15


# ---------------------------------------------------------------------------
# untracked_bytes
# ---------------------------------------------------------------------------


class TestUntrackedBytes:
    def test_no_untracked_returns_zero(self, fake_repo):
        assert ub.untracked_bytes(cwd=fake_repo) == 0

    def test_counts_untracked_file_size(self, fake_repo):
        ut = fake_repo / "untracked.txt"
        ut.write_text("x" * 200)
        result = ub.untracked_bytes(cwd=fake_repo)
        assert result >= 200

    def test_multiple_untracked_files(self, fake_repo):
        (fake_repo / "a.txt").write_text("a" * 50)
        (fake_repo / "b.txt").write_text("b" * 75)
        result = ub.untracked_bytes(cwd=fake_repo)
        assert result >= 125

    def test_missing_file_returns_zero(self, fake_repo):
        """If ls-files lists a file that vanished, don't crash."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ghost_file.txt\n"
        with patch.object(ub, "run_git", return_value=mock_result):
            result = ub.untracked_bytes(cwd=fake_repo)
            assert result == 0


# ---------------------------------------------------------------------------
# file_count / untracked_count
# ---------------------------------------------------------------------------


class TestFileCount:
    def test_clean_repo_returns_zero(self, fake_repo):
        assert ub.file_count(cwd=fake_repo) == 0

    def test_staged_count(self, fake_repo):
        (fake_repo / "x.txt").write_text("x")
        (fake_repo / "y.txt").write_text("y")
        subprocess.run(
            ["git", "add", "x.txt", "y.txt"],
            capture_output=True, cwd=str(fake_repo), check=True,
        )
        assert ub.file_count(cached=True, cwd=fake_repo) == 2

    def test_unstaged_count(self, fake_repo_with_changes):
        assert ub.file_count(cached=False, cwd=fake_repo_with_changes) >= 1


class TestUntrackedCount:
    def test_clean_repo_returns_zero(self, fake_repo):
        assert ub.untracked_count(cwd=fake_repo) == 0

    def test_counts_untracked(self, fake_repo):
        (fake_repo / "u1.txt").write_text("u1")
        (fake_repo / "u2.txt").write_text("u2")
        (fake_repo / "u3.txt").write_text("u3")
        assert ub.untracked_count(cwd=fake_repo) == 3


# ---------------------------------------------------------------------------
# measure
# ---------------------------------------------------------------------------


class TestMeasure:
    def test_default_mode(self, fake_repo):
        report = ub.measure(cwd=fake_repo)
        assert report["mode"] == "working-tree"
        assert "staged_bytes" in report
        assert "unstaged_bytes" in report
        assert "total_exposure" in report
        assert report["total_exposure"] == report["staged_bytes"] + report["unstaged_bytes"]

    def test_full_mode(self, fake_repo):
        report = ub.measure(full=True, cwd=fake_repo)
        assert report["mode"] == "full"
        assert "untracked_bytes" in report
        assert "untracked_files" in report

    def test_diff_only_mode(self, fake_repo):
        report = ub.measure(diff_only=True, cwd=fake_repo)
        assert report["mode"] == "diff-only"
        assert report["unstaged_bytes"] == 0
        assert report["untracked_bytes"] == 0
        assert report["total_exposure"] == report["staged_bytes"]

    def test_with_changes(self, fake_repo_with_changes):
        report = ub.measure(cwd=fake_repo_with_changes)
        assert report["staged_bytes"] > 0
        assert report["unstaged_bytes"] > 0
        assert report["total_exposure"] > 0

    def test_full_includes_untracked(self, fake_repo_with_changes):
        (fake_repo_with_changes / "extra.bin").write_bytes(b"\x00" * 500)
        report = ub.measure(full=True, cwd=fake_repo_with_changes)
        assert report["untracked_bytes"] >= 500
        assert report["total_exposure"] >= 500

    def test_diff_only_ignores_unstaged(self, fake_repo_with_changes):
        report = ub.measure(diff_only=True, cwd=fake_repo_with_changes)
        assert report["unstaged_bytes"] == 0
        assert report["untracked_bytes"] == 0

    def test_report_keys_complete(self, fake_repo):
        report = ub.measure(cwd=fake_repo)
        expected_keys = {
            "mode", "staged_bytes", "staged_files",
            "unstaged_bytes", "unstaged_files",
            "untracked_bytes", "untracked_files",
            "total_exposure",
        }
        assert set(report.keys()) == expected_keys


# ---------------------------------------------------------------------------
# format_bytes
# ---------------------------------------------------------------------------


class TestFormatBytes:
    def test_bytes(self):
        assert ub.format_bytes(0) == "0B"
        assert ub.format_bytes(512) == "512B"
        assert ub.format_bytes(1023) == "1023B"

    def test_kilobytes(self):
        assert ub.format_bytes(1024) == "1.0KB"
        assert ub.format_bytes(2560) == "2.5KB"

    def test_megabytes(self):
        assert ub.format_bytes(1048576) == "1.0MB"
        assert ub.format_bytes(5242880) == "5.0MB"


# ---------------------------------------------------------------------------
# format_text
# ---------------------------------------------------------------------------


class TestFormatText:
    def test_contains_mode(self, fake_repo):
        report = ub.measure(cwd=fake_repo)
        text = ub.format_text(report)
        assert "working-tree" in text

    def test_contains_total_exposure(self, fake_repo):
        report = ub.measure(cwd=fake_repo)
        text = ub.format_text(report)
        assert "total exposure" in text

    def test_full_mode_shows_untracked(self, fake_repo):
        report = ub.measure(full=True, cwd=fake_repo)
        text = ub.format_text(report)
        assert "untracked" in text

    def test_working_tree_mode_hides_untracked(self, fake_repo):
        report = ub.measure(full=False, cwd=fake_repo)
        text = ub.format_text(report)
        assert "untracked" not in text

    def test_diff_only_mode(self, fake_repo):
        report = ub.measure(diff_only=True, cwd=fake_repo)
        text = ub.format_text(report)
        assert "diff-only" in text


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCLI:
    def test_default_text_output(self, fake_repo):
        result = subprocess.run(
            [sys.executable, str(TOOLS / "uncommitted_bytes.py"),
             "--repo", str(fake_repo)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "total exposure" in result.stdout

    def test_json_output(self, fake_repo):
        result = subprocess.run(
            [sys.executable, str(TOOLS / "uncommitted_bytes.py"),
             "--repo", str(fake_repo), "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "total_exposure" in data
        assert "mode" in data

    def test_full_flag(self, fake_repo):
        result = subprocess.run(
            [sys.executable, str(TOOLS / "uncommitted_bytes.py"),
             "--repo", str(fake_repo), "--full", "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["mode"] == "full"

    def test_diff_only_flag(self, fake_repo):
        result = subprocess.run(
            [sys.executable, str(TOOLS / "uncommitted_bytes.py"),
             "--repo", str(fake_repo), "--diff-only", "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["mode"] == "diff-only"

    def test_threshold_pass(self, fake_repo):
        result = subprocess.run(
            [sys.executable, str(TOOLS / "uncommitted_bytes.py"),
             "--repo", str(fake_repo), "--threshold", "999999999"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_threshold_fail(self, fake_repo_with_changes):
        result = subprocess.run(
            [sys.executable, str(TOOLS / "uncommitted_bytes.py"),
             "--repo", str(fake_repo_with_changes), "--threshold", "1"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "WARNING" in result.stdout

    def test_json_threshold_fail_still_exits_1(self, fake_repo_with_changes):
        result = subprocess.run(
            [sys.executable, str(TOOLS / "uncommitted_bytes.py"),
             "--repo", str(fake_repo_with_changes),
             "--threshold", "1", "--json"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_lines_in_numstat(self):
        """Trailing newline in numstat should not crash."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "3\t1\tfile.py\n\n"
        with patch.object(ub, "run_git", return_value=mock_result):
            total = ub.diff_bytes(cwd=Path("/fake"))
            assert total == 4

    def test_git_error_returns_zero(self):
        """If git fails, diff_bytes returns 0 (not exception)."""
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        with patch.object(ub, "run_git", return_value=mock_result):
            assert ub.diff_bytes(cwd=Path("/fake")) == 0

    def test_empty_filename_in_ls_files(self):
        """Empty lines in ls-files output should be skipped."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "\n\n"
        with patch.object(ub, "run_git", return_value=mock_result):
            assert ub.untracked_count(cwd=Path("/fake")) == 0

    def test_format_bytes_boundary_1024(self):
        """Exactly 1024 bytes should be 1.0KB, not 1024B."""
        assert ub.format_bytes(1024) == "1.0KB"

    def test_format_bytes_boundary_1MB(self):
        """Exactly 1MB should be 1.0MB."""
        assert ub.format_bytes(1024 * 1024) == "1.0MB"

    def test_measure_consistency(self, fake_repo_with_changes):
        """total_exposure should equal sum of components in default mode."""
        report = ub.measure(cwd=fake_repo_with_changes)
        expected = report["staged_bytes"] + report["unstaged_bytes"]
        assert report["total_exposure"] == expected

    def test_measure_full_consistency(self, fake_repo_with_changes):
        """In full mode, total = staged + unstaged + untracked."""
        (fake_repo_with_changes / "z.bin").write_bytes(b"\xff" * 300)
        report = ub.measure(full=True, cwd=fake_repo_with_changes)
        expected = (
            report["staged_bytes"]
            + report["unstaged_bytes"]
            + report["untracked_bytes"]
        )
        assert report["total_exposure"] == expected
