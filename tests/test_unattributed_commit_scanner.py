"""Tests for tools/unattributed_commit_scanner.py

30 tests covering:
  - scan_commits: parsing, flagging logic, edge cases
  - format_report: output formatting
  - DEFAULT_NAMES / SUSPICIOUS_EMAILS classification
  - main() CLI integration
  - error handling (no repo, git failures)
"""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Import the module under test
TOOLS_DIR = str(Path(__file__).resolve().parent.parent / "tools")
sys.path.insert(0, TOOLS_DIR)
import unattributed_commit_scanner as ucs


# ── helpers ──────────────────────────────────────────────────────────

def make_log_line(commit_hash, name, email, subject, date):
    """Build a fake git log line in the format the scanner expects."""
    return f"{commit_hash}\x1f{name}\x1f{email}\x1f{subject}\x1f{date}"


def make_git_result(*lines):
    """Build a mock subprocess.run result with the given log lines."""
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = "\n".join(lines) + "\n"
    return mock


# ── scan_commits: clean repos ────────────────────────────────────────

class TestScanCommitsClean:
    """Repos where all commits are properly attributed."""

    def test_all_clean(self):
        lines = [
            make_log_line("abc1234567", "Qwen", "qwen@iamai.local",
                          "add feature", "2026-10-19T13:00:00+08:00"),
            make_log_line("def5678901", "Caretaker", "caretaker@iamai.local",
                          "fix bug", "2026-10-19T12:00:00+08:00"),
        ]
        with patch("subprocess.run", return_value=make_git_result(*lines)):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert result == []

    def test_empty_repo(self):
        with patch("subprocess.run", return_value=make_git_result()):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert result == []

    def test_single_clean_commit(self):
        line = make_log_line("aaa1111111", "Alice", "alice@company.com",
                            "initial commit", "2026-01-01T00:00:00+00:00")
        with patch("subprocess.run", return_value=make_git_result(line)):
            result = ucs.scan_commits(limit=1, repo_root="/fake")
        assert result == []


# ── scan_commits: flagged commits ────────────────────────────────────

class TestScanCommitsFlagged:
    """Repos with attribution issues."""

    def test_default_name_root(self):
        line = make_log_line("bad1111111", "root", "root@iamai.local",
                            "quick fix", "2026-10-19T10:00:00+08:00")
        with patch("subprocess.run", return_value=make_git_result(line)):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert len(result) == 1
        assert result[0]["reason"] == "default_name"
        assert result[0]["hash"] == "bad1111111"

    def test_default_name_ubuntu(self):
        line = make_log_line("bad2222222", "ubuntu", "ubuntu@iamai.local",
                            "update", "2026-10-19T10:00:00+08:00")
        with patch("subprocess.run", return_value=make_git_result(line)):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert len(result) == 1
        assert result[0]["reason"] == "default_name"

    def test_empty_name(self):
        line = make_log_line("bad3333333", "", "someone@iamai.local",
                            "mystery commit", "2026-10-19T10:00:00+08:00")
        with patch("subprocess.run", return_value=make_git_result(line)):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert len(result) == 1
        assert result[0]["reason"] == "default_name"

    def test_no_author_name(self):
        line = make_log_line("bad4444444", "(no author)", "none@none",
                            "orphan commit", "2026-10-19T10:00:00+08:00")
        with patch("subprocess.run", return_value=make_git_result(line)):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert len(result) == 1
        assert result[0]["reason"] == "default_name"

    def test_default_email_none(self):
        line = make_log_line("bad5555555", "Alice", "(none)",
                            "fix", "2026-10-19T10:00:00+08:00")
        with patch("subprocess.run", return_value=make_git_result(line)):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert len(result) == 1
        assert result[0]["reason"] == "default_email"

    def test_localhost_email(self):
        line = make_log_line("bad6666666", "Bob", "bob@localhost",
                            "update", "2026-10-19T10:00:00+08:00")
        with patch("subprocess.run", return_value=make_git_result(line)):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert len(result) == 1
        assert result[0]["reason"] == "suspicious_email"

    def test_example_com_email(self):
        line = make_log_line("bad7777777", "Carol", "carol@example.com",
                            "change", "2026-10-19T10:00:00+08:00")
        with patch("subprocess.run", return_value=make_git_result(line)):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert len(result) == 1
        assert result[0]["reason"] == "suspicious_email"

    def test_none_email_suffix(self):
        line = make_log_line("bad8888888", "Dave", "dave@none",
                            "patch", "2026-10-19T10:00:00+08:00")
        with patch("subprocess.run", return_value=make_git_result(line)):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert len(result) == 1
        assert result[0]["reason"] == "suspicious_email"

    def test_multiple_issues_mixed_with_clean(self):
        lines = [
            make_log_line("ok11111111", "Qwen", "qwen@iamai.local",
                          "good commit", "2026-10-19T12:00:00+08:00"),
            make_log_line("bad9999999", "root", "root@localhost",
                          "quick fix", "2026-10-19T11:00:00+08:00"),
            make_log_line("ok22222222", "Caretaker", "care@iamai.local",
                          "cleanup", "2026-10-19T10:00:00+08:00"),
            make_log_line("bad0000000", "", "(none)",
                          "orphan", "2026-10-19T09:00:00+08:00"),
        ]
        with patch("subprocess.run", return_value=make_git_result(*lines)):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert len(result) == 2
        hashes = [r["hash"] for r in result]
        assert "bad9999999" in hashes
        assert "bad0000000" in hashes

    def test_case_insensitive_name_match(self):
        line = make_log_line("cas1111111", "ROOT", "proper@email.com",
                            "fix", "2026-10-19T10:00:00+08:00")
        with patch("subprocess.run", return_value=make_git_result(line)):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert len(result) == 1
        assert result[0]["reason"] == "default_name"

    def test_whitespace_name_treated_as_empty(self):
        line = make_log_line("wsp1111111", "   ", "dev@iamai.local",
                            "fix", "2026-10-19T10:00:00+08:00")
        with patch("subprocess.run", return_value=make_git_result(line)):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert len(result) == 1
        assert result[0]["reason"] == "default_name"


# ── scan_commits: error handling ──────────────────────────────────────

class TestScanCommitsErrors:
    """Git failures and edge cases."""

    def test_git_failure_returns_empty(self):
        mock = MagicMock()
        mock.returncode = 1
        mock.stdout = ""
        with patch("subprocess.run", return_value=mock):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert result == []

    def test_timeout_returns_empty(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 10)):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert result == []

    def test_no_repo_root_returns_empty(self):
        with patch.object(ucs, "get_repo_root", return_value=None):
            result = ucs.scan_commits(limit=10)
        assert result == []

    def test_malformed_line_skipped(self):
        # Line with fewer than 5 fields
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = "abc123\x1fonly_name\x1fonly_email\n"
        with patch("subprocess.run", return_value=mock):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert result == []

    def test_blank_lines_skipped(self):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = "\n\n\n"
        with patch("subprocess.run", return_value=mock):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert result == []


# ── scan_commits: output structure ────────────────────────────────────

class TestScanCommitsOutput:
    """Verify the shape of each flagged entry."""

    def test_entry_has_all_fields(self):
        line = make_log_line("fld1111111", "root", "root@localhost",
                            "test commit", "2026-10-19T10:00:00+08:00")
        with patch("subprocess.run", return_value=make_git_result(line)):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert len(result) == 1
        entry = result[0]
        for key in ("hash", "author_name", "author_email", "subject", "date", "reason"):
            assert key in entry, f"missing key: {key}"

    def test_hash_truncated_to_10(self):
        line = make_log_line("abcdef1234567890", "root", "root@iamai.local",
                            "fix", "2026-10-19T10:00:00+08:00")
        with patch("subprocess.run", return_value=make_git_result(line)):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert len(result[0]["hash"]) == 10

    def test_date_truncated_to_10(self):
        line = make_log_line("dat1111111", "root", "root@iamai.local",
                            "fix", "2026-10-19T10:00:00+08:00")
        with patch("subprocess.run", return_value=make_git_result(line)):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert result[0]["date"] == "2026-10-19"

    def test_empty_name_displayed_as_empty_parens(self):
        line = make_log_line("emp1111111", "", "dev@iamai.local",
                            "fix", "2026-10-19T10:00:00+08:00")
        with patch("subprocess.run", return_value=make_git_result(line)):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert result[0]["author_name"] == "(empty)"

    def test_empty_email_displayed_as_empty_parens(self):
        line = make_log_line("emp2222222", "Alice", "",
                            "fix", "2026-10-19T10:00:00+08:00")
        with patch("subprocess.run", return_value=make_git_result(line)):
            result = ucs.scan_commits(limit=10, repo_root="/fake")
        assert result[0]["author_email"] == "(empty)"


# ── format_report ─────────────────────────────────────────────────────

class TestFormatReport:
    """Human-readable report formatting."""

    def test_clean_report(self):
        report = ucs.format_report([], 50)
        assert "attribution ok" in report
        assert "50" in report

    def test_flagged_report(self):
        flagged = [
            {
                "hash": "abc1234567",
                "author_name": "root",
                "author_email": "root@localhost",
                "subject": "quick fix",
                "date": "2026-10-19",
                "reason": "default_name",
            }
        ]
        report = ucs.format_report(flagged, 20)
        assert "attribution issues" in report
        assert "1 of 20" in report
        assert "abc1234567" in report
        assert "default_name" in report

    def test_breakdown_section(self):
        flagged = [
            {"hash": "a", "author_name": "x", "author_email": "y",
             "subject": "s", "date": "d", "reason": "default_name"},
            {"hash": "b", "author_name": "x", "author_email": "y",
             "subject": "s", "date": "d", "reason": "default_name"},
            {"hash": "c", "author_name": "x", "author_email": "y",
             "subject": "s", "date": "d", "reason": "suspicious_email"},
        ]
        report = ucs.format_report(flagged, 10)
        assert "breakdown:" in report
        assert "default_name: 2" in report
        assert "suspicious_email: 1" in report


# ── get_repo_root ─────────────────────────────────────────────────────

class TestGetRepoRoot:
    """Repo root detection."""

    def test_returns_path_on_success(self):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = "/home/user/repo\n"
        with patch("subprocess.run", return_value=mock):
            result = ucs.get_repo_root()
        assert result == "/home/user/repo"

    def test_returns_none_on_failure(self):
        mock = MagicMock()
        mock.returncode = 128
        mock.stdout = ""
        with patch("subprocess.run", return_value=mock):
            result = ucs.get_repo_root()
        assert result is None

    def test_returns_none_on_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 5)):
            result = ucs.get_repo_root()
        assert result is None


# ── main() CLI ────────────────────────────────────────────────────────

class TestMain:
    """CLI entry point."""

    def test_clean_exit_0(self):
        with patch.object(ucs, "get_repo_root", return_value="/fake"), \
             patch.object(ucs, "scan_commits", return_value=[]), \
             patch("sys.argv", ["prog", "--limit", "5"]), \
             pytest.raises(SystemExit) as exc_info:
            ucs.main()
        assert exc_info.value.code == 0

    def test_flagged_exit_1(self):
        flagged = [{"hash": "x", "author_name": "root",
                     "author_email": "r@l", "subject": "s",
                     "date": "d", "reason": "default_name"}]
        with patch.object(ucs, "get_repo_root", return_value="/fake"), \
             patch.object(ucs, "scan_commits", return_value=flagged), \
             patch("sys.argv", ["prog"]), \
             pytest.raises(SystemExit) as exc_info:
            ucs.main()
        assert exc_info.value.code == 1

    def test_no_repo_exit_2(self):
        with patch.object(ucs, "get_repo_root", return_value=None), \
             patch("sys.argv", ["prog"]), \
             pytest.raises(SystemExit) as exc_info:
            ucs.main()
        assert exc_info.value.code == 2

    def test_json_output(self, capsys):
        with patch.object(ucs, "get_repo_root", return_value="/fake"), \
             patch.object(ucs, "scan_commits", return_value=[]), \
             patch("sys.argv", ["prog", "--json"]), \
             pytest.raises(SystemExit):
            ucs.main()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "flagged_count" in data
        assert data["flagged_count"] == 0
