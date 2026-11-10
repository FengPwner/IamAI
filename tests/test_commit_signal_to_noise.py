#!/usr/bin/env python3
"""Tests for commit_signal_to_noise.py — measure commit content quality.

65 tests covering:
  - boilerplate line detection (all pattern families)
  - file classification (pure-noise vs check)
  - diff parsing (unified diff with added lines)
  - deleted-line counting
  - ratio computation and boundary values
  - classification thresholds (all four boundaries)
  - per-commit analysis with mocked subprocess
  - multi-commit analyse_commits
  - aggregate report (empty, all-noise, all-signal, mixed)
  - trend detection (improving, degrading, stable, insufficient data)
  - CLI output (json mode, text mode, all three exit codes)
  - edge cases (empty diff, timeout, zero added lines)

Run:  pytest tests/test_commit_signal_to_noise.py -v
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamai.commit_signal_to_noise import (
    is_boilerplate_line,
    classify_file,
    _parse_diff_stat,
    _count_deleted,
    _classify_ratio,
    analyse_commit,
    analyse_commits,
    aggregate_report,
    trend_report,
    _cli,
    CommitSNR,
    REPO,
)


# ═══════════════════════════════════════════════════════════════════════
#  Boilerplate line detection
# ═══════════════════════════════════════════════════════════════════════

class TestIsBoilerplateLine:
    """Verify all boilerplate pattern families."""

    # ── Should match ──

    def test_json_state_record(self):
        assert is_boilerplate_line('{"writer": "qwen", "strokes": 401}')

    def test_jsonl_stroke_record(self):
        assert is_boilerplate_line('{"ts": "2026-11-10T12:00:00Z", "writer": "qwen"}')

    def test_metrics_counter_colon(self):
        assert is_boilerplate_line("total_strokes: 401")

    def test_metrics_counter_equals(self):
        assert is_boilerplate_line("commits=594")

    def test_metrics_strokes(self):
        assert is_boilerplate_line("strokes: 67")

    def test_timestamped_log_entry(self):
        assert is_boilerplate_line("[2026-11-10 12:00:00] stroke 401 written")

    def test_devlog_stroke_marker(self):
        assert is_boilerplate_line("## stroke 401")

    def test_pure_numeric_line(self):
        assert is_boilerplate_line("401")

    def test_markdown_table_separator(self):
        assert is_boilerplate_line("|---|---|---|")

    def test_commit_hash_reference(self):
        assert is_boilerplate_line("last_commit: abc1234")

    def test_leading_whitespace_preserved(self):
        assert is_boilerplate_line('    {"ts": "2026-11-10T12:00:00Z"}')

    # ── Should NOT match ──

    def test_regular_prose(self):
        assert not is_boilerplate_line("This module measures commit quality.")

    def test_python_function_def(self):
        assert not is_boilerplate_line("def analyse_commit(hash):")

    def test_comment_line(self):
        assert not is_boilerplate_line("# this is a real comment about design")

    def test_empty_line(self):
        assert not is_boilerplate_line("")

    def test_plain_text(self):
        assert not is_boilerplate_line("The writer has been running for 47 days.")

    def test_test_function_name(self):
        assert not is_boilerplate_line("def test_snr_basic():")

    def test_import_statement(self):
        assert not is_boilerplate_line("from pathlib import Path")


# ═══════════════════════════════════════════════════════════════════════
#  File classification
# ═══════════════════════════════════════════════════════════════════════

class TestClassifyFile:
    """Verify file-level noise classification."""

    def test_writer_state_qwen_is_noise(self):
        assert classify_file("data/writer_state.qwen.json") == "noise"

    def test_writer_state_guoban_is_noise(self):
        assert classify_file("data/writer_state.guoban.json") == "noise"

    def test_strokes_jsonl_is_check(self):
        # Not in pure-noise set — needs line-level inspection
        assert classify_file("data/strokes.jsonl") == "check"

    def test_python_module_is_check(self):
        assert classify_file("iamai/commit_signal_to_noise.py") == "check"

    def test_test_file_is_check(self):
        assert classify_file("tests/test_commit_signal_to_noise.py") == "check"

    def test_note_is_check(self):
        assert classify_file("notes/caretaker-visit-595.md") == "check"


# ═══════════════════════════════════════════════════════════════════════
#  Diff parsing
# ═══════════════════════════════════════════════════════════════════════

class TestParseDiffStat:
    """Verify unified diff parsing into {file: [lines]}."""

    def test_single_file(self):
        raw = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,2 +1,3 @@\n"
            " keep this\n"
            "+added line 1\n"
            "+added line 2\n"
        )
        result = _parse_diff_stat(raw)
        assert result == {"foo.py": ["added line 1", "added line 2"]}

    def test_multiple_files(self):
        raw = (
            "+++ b/a.py\n"
            "+line a1\n"
            "+++ b/b.py\n"
            "+line b1\n"
            "+line b2\n"
        )
        result = _parse_diff_stat(raw)
        assert result == {"a.py": ["line a1"], "b.py": ["line b1", "line b2"]}

    def test_no_additions(self):
        raw = (
            "+++ b/foo.py\n"
            "-removed line\n"
        )
        result = _parse_diff_stat(raw)
        assert result == {"foo.py": []}

    def test_empty_diff(self):
        assert _parse_diff_stat("") == {}

    def test_dev_null_header_ignored(self):
        raw = "+++ /dev/null\n"
        result = _parse_diff_stat(raw)
        assert result == {}

    def test_plus_plus_plus_header_stripped(self):
        raw = "+++ b/foo.py\n"
        result = _parse_diff_stat(raw)
        # Just the header, no added lines
        assert result == {"foo.py": []}


class TestCountDeleted:
    """Verify deleted-line counting."""

    def test_basic(self):
        raw = "--- a/foo.py\n+++ b/foo.py\n-removed\n-also removed\n+added\n"
        assert _count_deleted(raw) == 2

    def test_none(self):
        raw = "+++ b/foo.py\n+only additions\n"
        assert _count_deleted(raw) == 0

    def test_empty(self):
        assert _count_deleted("") == 0


# ═══════════════════════════════════════════════════════════════════════
#  Ratio classification
# ═══════════════════════════════════════════════════════════════════════

class TestClassifyRatio:
    """Verify signal_ratio → classification mapping."""

    def test_noise(self):
        assert _classify_ratio(0.0) == "noise"

    def test_noise_boundary(self):
        assert _classify_ratio(0.19) == "noise"

    def test_mixed_lower(self):
        assert _classify_ratio(0.2) == "mixed"

    def test_mixed_upper(self):
        assert _classify_ratio(0.49) == "mixed"

    def test_signal_lower(self):
        assert _classify_ratio(0.5) == "signal"

    def test_signal_upper(self):
        assert _classify_ratio(0.79) == "signal"

    def test_pure_signal_lower(self):
        assert _classify_ratio(0.8) == "pure-signal"

    def test_pure_signal_max(self):
        assert _classify_ratio(1.0) == "pure-signal"


# ═══════════════════════════════════════════════════════════════════════
#  Per-commit analysis (mocked subprocess)
# ═══════════════════════════════════════════════════════════════════════

class TestAnalyseCommit:
    """Test analyse_commit with mocked git diff output."""

    def _mock_diff(self, raw_diff: str):
        """Return a patch for subprocess.run that yields raw_diff."""
        mock_result = MagicMock()
        mock_result.stdout = raw_diff
        return patch("iamai.commit_signal_to_noise.subprocess.run", return_value=mock_result)

    def test_pure_signal_commit(self):
        """A commit adding a Python module with real code."""
        raw = (
            "+++ b/iamai/new_module.py\n"
            "+def compute_score(data):\n"
            "+    # Analyse the input\n"
            "+    return sum(data) / len(data)\n"
            "+\n"
            "+class ScoreReport:\n"
        )
        with self._mock_diff(raw):
            snr = analyse_commit("abc1234")

        assert snr.signal_ratio == 1.0
        assert snr.classification == "pure-signal"
        assert snr.signal_files == 1
        assert snr.noise_files == 0

    def test_pure_noise_commit(self):
        """A commit only updating writer state JSON."""
        raw = (
            "+++ b/data/writer_state.qwen.json\n"
            '+{"writer": "qwen", "strokes": 401, "pid": 1234}\n'
        )
        with self._mock_diff(raw):
            snr = analyse_commit("abc1234")

        assert snr.signal_ratio == 0.0
        assert snr.classification == "noise"
        assert snr.noise_files == 1

    def test_mixed_commit(self):
        """A commit with both boilerplate and real content."""
        raw = (
            "+++ b/data/strokes.jsonl\n"
            '+{"ts": "2026-11-10T12:00:00Z", "writer": "qwen"}\n'
            "+++ b/notes/visit.md\n"
            "+# Today I analysed signal-to-noise ratios.\n"
            "+The results were interesting.\n"
        )
        with self._mock_diff(raw):
            snr = analyse_commit("abc1234")

        assert snr.added_lines == 3
        assert snr.boilerplate_added == 1
        assert snr.substantive_added == 2
        assert 0.5 < snr.signal_ratio < 0.8  # 2/3 ≈ 0.67

    def test_empty_diff(self):
        """An empty commit (no diff output)."""
        with self._mock_diff(""):
            snr = analyse_commit("abc1234")

        assert snr.added_lines == 0
        assert snr.signal_ratio == 0.0
        assert snr.classification == "noise"

    def test_timeout_returns_empty(self):
        """subprocess.TimeoutExpired should return empty SNR."""
        with patch(
            "iamai.commit_signal_to_noise.subprocess.run",
            side_effect=subprocess.TimeoutExpired("git", 30),
        ):
            snr = analyse_commit("abc1234")

        assert snr.signal_ratio == 0.0
        assert snr.classification == "noise"

    def test_deleted_lines_counted(self):
        """Deleted lines should be tallied even though they don't affect SNR."""
        raw = (
            "+++ b/iamai/mod.py\n"
            "-old line 1\n"
            "-old line 2\n"
            "+new line 1\n"
        )
        with self._mock_diff(raw):
            snr = analyse_commit("abc1234")

        assert snr.deleted_lines == 2
        assert snr.added_lines == 1


# ═══════════════════════════════════════════════════════════════════════
#  Multi-commit analysis
# ═══════════════════════════════════════════════════════════════════════

class TestAnalyseCommits:
    """Test analyse_commits with mocked git log + git diff."""

    def test_returns_correct_count(self):
        log_mock = MagicMock()
        log_mock.stdout = "aaa\nbbb\nccc\n"

        diff_mock = MagicMock()
        diff_mock.stdout = "+++ b/foo.py\n+real content here\n"

        with patch("iamai.commit_signal_to_noise.subprocess.run") as mock_run:
            mock_run.side_effect = [log_mock, diff_mock, diff_mock, diff_mock]
            results = analyse_commits(count=3)

        assert len(results) == 3

    def test_empty_log(self):
        log_mock = MagicMock()
        log_mock.stdout = ""

        with patch("iamai.commit_signal_to_noise.subprocess.run", return_value=log_mock):
            results = analyse_commits(count=10)

        assert results == []

    def test_timeout_on_log(self):
        with patch(
            "iamai.commit_signal_to_noise.subprocess.run",
            side_effect=subprocess.TimeoutExpired("git", 15),
        ):
            results = analyse_commits(count=5)

        assert results == []


# ═══════════════════════════════════════════════════════════════════════
#  Aggregate report
# ═══════════════════════════════════════════════════════════════════════

class TestAggregateReport:
    """Test aggregate_report summarisation."""

    def test_empty_input(self):
        r = aggregate_report([])
        assert r["total_commits"] == 0
        assert r["assessment"] == "no-data"

    def test_all_noise(self):
        results = [
            {"added_lines": 10, "substantive_added": 0, "classification": "noise",
             "signal_ratio": 0.0},
            {"added_lines": 5, "substantive_added": 0, "classification": "noise",
             "signal_ratio": 0.0},
        ]
        r = aggregate_report(results)
        assert r["total_commits"] == 2
        assert r["avg_signal_ratio"] == 0.0
        assert r["assessment"] == "noise-dominated"

    def test_all_signal(self):
        results = [
            {"added_lines": 100, "substantive_added": 90, "classification": "pure-signal",
             "signal_ratio": 0.9},
            {"added_lines": 50, "substantive_added": 40, "classification": "signal",
             "signal_ratio": 0.8},
        ]
        r = aggregate_report(results)
        assert r["assessment"] == "healthy"
        # (90 + 40) / (100 + 50) = 130/150 ≈ 0.867
        assert abs(r["avg_signal_ratio"] - 0.8667) < 0.01

    def test_mixed_results(self):
        results = [
            {"added_lines": 100, "substantive_added": 30, "classification": "mixed",
             "signal_ratio": 0.3},
            {"added_lines": 100, "substantive_added": 30, "classification": "mixed",
             "signal_ratio": 0.3},
        ]
        r = aggregate_report(results)
        assert r["assessment"] == "mixed"


# ═══════════════════════════════════════════════════════════════════════
#  Trend detection
# ═══════════════════════════════════════════════════════════════════════

class TestTrendReport:
    """Test trend_report comparing halves."""

    def test_insufficient_data(self):
        results = [{"signal_ratio": 0.5}] * 3
        r = trend_report(results)
        assert r["direction"] == "insufficient-data"

    def test_improving(self):
        # newer-first: first half is newer (high SNR), second half is older (low)
        results = [{"signal_ratio": 0.8}] * 3 + [{"signal_ratio": 0.3}] * 3
        r = trend_report(results)
        assert r["direction"] == "improving"

    def test_degrading(self):
        # newer commits have lower SNR than older
        results = [{"signal_ratio": 0.2}] * 3 + [{"signal_ratio": 0.8}] * 3
        r = trend_report(results)
        assert r["direction"] == "degrading"

    def test_stable(self):
        results = [{"signal_ratio": 0.5}] * 6
        r = trend_report(results)
        assert r["direction"] == "stable"

    def test_empty_input(self):
        r = trend_report([])
        assert r["direction"] == "insufficient-data"


# ═══════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════

class TestCLI:
    """Test CLI exit codes and output modes."""

    def test_json_mode(self, capsys):
        with patch("iamai.commit_signal_to_noise.analyse_commits") as mock_ac:
            mock_ac.return_value = [
                {"commit_hash": "abc123", "classification": "signal",
                 "signal_ratio": 0.7, "added_lines": 50,
                 "substantive_added": 35, "boilerplate_added": 15,
                 "deleted_lines": 5, "boilerplate_ratio": 0.3,
                 "signal_files": 2, "noise_files": 0, "per_file": []},
            ]
            with patch("sys.argv", ["prog", "--json"]):
                code = _cli()
            out = capsys.readouterr().out
            data = json.loads(out)
            assert "commits" in data
            assert "report" in data
            assert "trend" in data

    def test_text_mode(self, capsys):
        with patch("iamai.commit_signal_to_noise.analyse_commits") as mock_ac:
            mock_ac.return_value = [
                {"commit_hash": "abc123", "classification": "pure-signal",
                 "signal_ratio": 0.9, "added_lines": 100,
                 "substantive_added": 90, "boilerplate_added": 10,
                 "deleted_lines": 3, "boilerplate_ratio": 0.1,
                 "signal_files": 3, "noise_files": 0, "per_file": []},
            ]
            with patch("sys.argv", ["prog"]):
                code = _cli()
            out = capsys.readouterr().out
            assert "pure-signal" in out
            assert "healthy" in out

    def test_exit_0_all_signal(self, capsys):
        with patch("iamai.commit_signal_to_noise.analyse_commits") as mock_ac:
            mock_ac.return_value = [
                {"commit_hash": "x", "classification": "signal",
                 "signal_ratio": 0.7, "added_lines": 50,
                 "substantive_added": 35, "boilerplate_added": 15,
                 "deleted_lines": 0, "boilerplate_ratio": 0.3,
                 "signal_files": 1, "noise_files": 0, "per_file": []},
            ]
            with patch("sys.argv", ["prog", "--json"]):
                code = _cli()
            # mixed count > 0 because "signal" != pure-signal... wait
            # signal is not noise and not mixed, so exit should be 0
            # Actually re-read: exit 1 if mixed_count > 0 or noise_count > 0
            # "signal" is neither mixed nor noise → exit 0
            assert code == 0

    def test_exit_2_majority_noise(self, capsys):
        with patch("iamai.commit_signal_to_noise.analyse_commits") as mock_ac:
            mock_ac.return_value = [
                {"commit_hash": "x", "classification": "noise",
                 "signal_ratio": 0.0, "added_lines": 5,
                 "substantive_added": 0, "boilerplate_added": 5,
                 "deleted_lines": 0, "boilerplate_ratio": 1.0,
                 "signal_files": 0, "noise_files": 1, "per_file": []},
            ] * 3
            with patch("sys.argv", ["prog", "--json"]):
                code = _cli()
            assert code == 2

    def test_exit_1_some_mixed(self, capsys):
        with patch("iamai.commit_signal_to_noise.analyse_commits") as mock_ac:
            mock_ac.return_value = [
                {"commit_hash": "a", "classification": "mixed",
                 "signal_ratio": 0.3, "added_lines": 10,
                 "substantive_added": 3, "boilerplate_added": 7,
                 "deleted_lines": 0, "boilerplate_ratio": 0.7,
                 "signal_files": 1, "noise_files": 0, "per_file": []},
                {"commit_hash": "b", "classification": "signal",
                 "signal_ratio": 0.6, "added_lines": 20,
                 "substantive_added": 12, "boilerplate_added": 8,
                 "deleted_lines": 0, "boilerplate_ratio": 0.4,
                 "signal_files": 1, "noise_files": 0, "per_file": []},
            ]
            with patch("sys.argv", ["prog", "--json"]):
                code = _cli()
            assert code == 1


# ═══════════════════════════════════════════════════════════════════════
#  Edge cases
# ═══════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Boundary and edge case tests."""

    def test_zero_added_lines_in_commit(self):
        """A commit that only deletes lines."""
        snr = CommitSNR(added_lines=0, deleted_lines=10)
        assert snr.boilerplate_ratio == 0.0
        assert snr.signal_ratio == 0.0

    def test_single_boilerplate_line(self):
        """One added line that happens to be boilerplate."""
        raw = '+++ b/data/strokes.jsonl\n+{"ts": "2026-11-10T00:00:00Z", "writer": "qwen"}\n'
        with patch("iamai.commit_signal_to_noise.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=raw)
            snr = analyse_commit("abc")
        assert snr.signal_ratio == 0.0
        assert snr.classification == "noise"

    def test_single_substantive_line(self):
        """One added line of real content."""
        raw = "+++ b/notes/thought.md\n+I wonder if SNR is the right metric here.\n"
        with patch("iamai.commit_signal_to_noise.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=raw)
            snr = analyse_commit("abc")
        assert snr.signal_ratio == 1.0
        assert snr.classification == "pure-signal"

    def test_trend_exactly_four_commits(self):
        """Minimum number for trend detection."""
        results = [{"signal_ratio": 0.5}] * 4
        r = trend_report(results)
        assert r["direction"] == "stable"

    def test_aggregate_single_commit(self):
        results = [
            {"added_lines": 10, "substantive_added": 10, "classification": "pure-signal",
             "signal_ratio": 1.0},
        ]
        r = aggregate_report(results)
        assert r["total_commits"] == 1
        assert r["avg_signal_ratio"] == 1.0
        assert r["assessment"] == "healthy"


# ═══════════════════════════════════════════════════════════════════════
#  Integration (real repo, best-effort)
# ═══════════════════════════════════════════════════════════════════════

class TestIntegration:
    """Run against the real repo — skipped if not in a git repo."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_repo(self):
        if not (REPO / ".git").exists():
            pytest.skip("not inside the IamAI repo")

    def test_analyse_head(self):
        snr = analyse_commit("HEAD")
        assert snr.commit_hash == "HEAD"
        # Just verify it does not crash and returns valid fields
        assert 0.0 <= snr.signal_ratio <= 1.0
        assert snr.classification in ("noise", "mixed", "signal", "pure-signal")

    def test_analyse_last_3(self):
        results = analyse_commits(count=3)
        assert len(results) <= 3
        for r in results:
            assert "classification" in r
            assert "signal_ratio" in r
