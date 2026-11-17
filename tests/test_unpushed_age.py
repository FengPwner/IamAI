"""tests for iamai.unpushed_age — unpushed commit age checker.

covers:
  - AgeResult dataclass (to_dict, summary)
  - classify() threshold logic
  - measure_unpushed_age() with mocked subprocess calls
  - edge cases: no remote, detached HEAD, bad output
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.unpushed_age import (
    CRITICAL_LABEL,
    EXIT_AGING,
    EXIT_CRITICAL,
    EXIT_FRESH,
    EXIT_STALE,
    EXIT_SYNCED,
    EXIT_UNKNOWN,
    AgeResult,
    classify,
    measure_unpushed_age,
)


# ---------------------------------------------------------------------------
# AgeResult
# ---------------------------------------------------------------------------

class TestAgeResult:
    def test_to_dict_synced(self):
        r = AgeResult(age_seconds=None, unpushed_count=0, label="synced", exit_code=EXIT_SYNCED)
        d = r.to_dict()
        assert d["label"] == "synced"
        assert d["age_seconds"] is None
        assert d["unpushed_count"] == 0
        assert d["exit_code"] == EXIT_SYNCED
        assert d["oldest_hash"] is None
        assert d["error"] is None

    def test_to_dict_with_error(self):
        r = AgeResult(
            age_seconds=None,
            unpushed_count=0,
            label="unknown",
            exit_code=EXIT_UNKNOWN,
            error="git not found",
        )
        d = r.to_dict()
        assert d["error"] == "git not found"

    def test_summary_synced(self):
        r = AgeResult(age_seconds=None, unpushed_count=0, label="synced", exit_code=EXIT_SYNCED)
        assert "synced" in r.summary()

    def test_summary_with_error(self):
        r = AgeResult(
            age_seconds=None,
            unpushed_count=0,
            label="unknown",
            exit_code=EXIT_UNKNOWN,
            error="detached HEAD",
        )
        assert "unknown" in r.summary()
        assert "detached HEAD" in r.summary()

    def test_summary_with_age(self):
        r = AgeResult(
            age_seconds=300,
            unpushed_count=2,
            label="fresh",
            exit_code=EXIT_FRESH,
            oldest_hash="abc12345",
        )
        s = r.summary()
        assert "fresh" in s
        assert "abc12345" in s
        assert "5.0 min" in s
        assert "2 unpushed" in s


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------

class TestClassify:
    def test_zero_unpushed_is_synced(self):
        label, code = classify(9999, 0)
        assert label == "synced"
        assert code == EXIT_SYNCED

    def test_fresh_under_600(self):
        label, code = classify(300, 1)
        assert label == "fresh"
        assert code == EXIT_FRESH

    def test_fresh_at_boundary(self):
        label, code = classify(599, 3)
        assert label == "fresh"
        assert code == EXIT_FRESH

    def test_aging_at_600(self):
        label, code = classify(600, 1)
        assert label == "aging"
        assert code == EXIT_AGING

    def test_aging_mid_range(self):
        label, code = classify(1200, 5)
        assert label == "aging"
        assert code == EXIT_AGING

    def test_stale_at_1800(self):
        label, code = classify(1800, 2)
        assert label == "stale"
        assert code == EXIT_STALE

    def test_stale_mid_range(self):
        label, code = classify(2700, 8)
        assert label == "stale"
        assert code == EXIT_STALE

    def test_critical_at_3600(self):
        label, code = classify(3600, 10)
        assert label == CRITICAL_LABEL
        assert code == EXIT_CRITICAL

    def test_critical_well_over(self):
        label, code = classify(7200, 50)
        assert label == CRITICAL_LABEL
        assert code == EXIT_CRITICAL

    def test_none_age_with_unpushed_is_unknown(self):
        label, code = classify(None, 3)
        assert label == "unknown"
        assert code == EXIT_UNKNOWN


# ---------------------------------------------------------------------------
# measure_unpushed_age — mocked subprocess
# ---------------------------------------------------------------------------

def _make_run_side_effect(responses: dict):
    """build a side_effect for _run(cmd, repo, ...) keyed on the first few args."""

    def _side_effect(cmd, repo=None, timeout=10, **kwargs):
        key = tuple(cmd[:3])
        if key in responses:
            resp = responses[key]
        else:
            # try shorter keys
            for k, v in responses.items():
                if cmd[: len(k)] == list(k):
                    resp = v
                    break
            else:
                resp = {"rc": 1, "stdout": "", "stderr": f"unmocked: {cmd}"}
        mock = MagicMock()
        mock.returncode = resp.get("rc", 0)
        mock.stdout = resp.get("stdout", "")
        mock.stderr = resp.get("stderr", "")
        return mock

    return _side_effect


class TestMeasureUnpushedAge:
    def test_synced_no_unpushed(self):
        responses = {
            ("git", "rev-list", "--count"): {"rc": 0, "stdout": "0\n"},
        }
        with patch("iamai.unpushed_age._run", side_effect=_make_run_side_effect(responses)):
            result = measure_unpushed_age("/fake/repo")
        assert result.label == "synced"
        assert result.exit_code == EXIT_SYNCED
        assert result.unpushed_count == 0
        assert result.age_seconds is None

    def test_fresh_one_commit(self):
        commit_hash = "abcdef1234567890"
        now_ts = int(time.time())
        commit_ts = now_ts - 120  # 2 minutes ago
        responses = {
            ("git", "rev-list", "--count"): {"rc": 0, "stdout": "1\n"},
            ("git", "rev-list", "origin/main..HEAD"): {
                "rc": 0,
                "stdout": f"{commit_hash}\n",
            },
            ("git", "show", "-s"): {"rc": 0, "stdout": f"{commit_ts}\n"},
        }
        with patch("iamai.unpushed_age._run", side_effect=_make_run_side_effect(responses)):
            result = measure_unpushed_age("/fake/repo")
        assert result.label == "fresh"
        assert result.exit_code == EXIT_FRESH
        assert result.unpushed_count == 1
        assert result.oldest_hash == "abcdef12"
        assert 100 <= result.age_seconds <= 140

    def test_aging_multiple_commits(self):
        oldest = "aaaa1111bbbb2222"
        newer = "cccc3333dddd4444"
        now_ts = int(time.time())
        oldest_ts = now_ts - 900  # 15 minutes ago
        responses = {
            ("git", "rev-list", "--count"): {"rc": 0, "stdout": "3\n"},
            ("git", "rev-list", "origin/main..HEAD"): {
                "rc": 0,
                "stdout": f"{oldest}\n{newer}\nbbbb5555cccc6666\n",
            },
            ("git", "show", "-s"): {"rc": 0, "stdout": f"{oldest_ts}\n"},
        }
        with patch("iamai.unpushed_age._run", side_effect=_make_run_side_effect(responses)):
            result = measure_unpushed_age("/fake/repo")
        assert result.label == "aging"
        assert result.exit_code == EXIT_AGING
        assert result.unpushed_count == 3
        assert result.oldest_hash == "aaaa1111"

    def test_stale_commit(self):
        now_ts = int(time.time())
        commit_ts = now_ts - 2400  # 40 minutes ago
        responses = {
            ("git", "rev-list", "--count"): {"rc": 0, "stdout": "5\n"},
            ("git", "rev-list", "origin/main..HEAD"): {
                "rc": 0,
                "stdout": "deadbeef12345678\n" * 5,
            },
            ("git", "show", "-s"): {"rc": 0, "stdout": f"{commit_ts}\n"},
        }
        with patch("iamai.unpushed_age._run", side_effect=_make_run_side_effect(responses)):
            result = measure_unpushed_age("/fake/repo")
        assert result.label == "stale"
        assert result.exit_code == EXIT_STALE

    def test_critical_commit(self):
        now_ts = int(time.time())
        commit_ts = now_ts - 7200  # 2 hours ago
        responses = {
            ("git", "rev-list", "--count"): {"rc": 0, "stdout": "20\n"},
            ("git", "rev-list", "origin/main..HEAD"): {
                "rc": 0,
                "stdout": "cafebabe12345678\n" * 20,
            },
            ("git", "show", "-s"): {"rc": 0, "stdout": f"{commit_ts}\n"},
        }
        with patch("iamai.unpushed_age._run", side_effect=_make_run_side_effect(responses)):
            result = measure_unpushed_age("/fake/repo")
        assert result.label == CRITICAL_LABEL
        assert result.exit_code == EXIT_CRITICAL

    def test_rev_list_failure(self):
        responses = {
            ("git", "rev-list", "--count"): {
                "rc": 128,
                "stderr": "fatal: no upstream configured for 'main'",
            },
        }
        with patch("iamai.unpushed_age._run", side_effect=_make_run_side_effect(responses)):
            result = measure_unpushed_age("/fake/repo")
        assert result.label == "unknown"
        assert result.exit_code == EXIT_UNKNOWN
        assert "no upstream" in result.error

    def test_rev_list_bad_output(self):
        responses = {
            ("git", "rev-list", "--count"): {"rc": 0, "stdout": "not-a-number\n"},
        }
        with patch("iamai.unpushed_age._run", side_effect=_make_run_side_effect(responses)):
            result = measure_unpushed_age("/fake/repo")
        assert result.label == "unknown"
        assert result.exit_code == EXIT_UNKNOWN
        assert "non-integer" in result.error

    def test_rev_list_empty_commits_despite_nonzero(self):
        responses = {
            ("git", "rev-list", "--count"): {"rc": 0, "stdout": "3\n"},
            ("git", "rev-list", "origin/main..HEAD"): {"rc": 0, "stdout": "\n"},
        }
        with patch("iamai.unpushed_age._run", side_effect=_make_run_side_effect(responses)):
            result = measure_unpushed_age("/fake/repo")
        assert result.label == "unknown"
        assert result.exit_code == EXIT_UNKNOWN
        assert result.unpushed_count == 3

    def test_show_failure(self):
        responses = {
            ("git", "rev-list", "--count"): {"rc": 0, "stdout": "1\n"},
            ("git", "rev-list", "origin/main..HEAD"): {
                "rc": 0,
                "stdout": "abcdef1234567890\n",
            },
            ("git", "show", "-s"): {"rc": 128, "stderr": "fatal: bad object"},
        }
        with patch("iamai.unpushed_age._run", side_effect=_make_run_side_effect(responses)):
            result = measure_unpushed_age("/fake/repo")
        assert result.label == "unknown"
        assert result.exit_code == EXIT_UNKNOWN
        assert "bad object" in result.error

    def test_show_bad_timestamp(self):
        responses = {
            ("git", "rev-list", "--count"): {"rc": 0, "stdout": "1\n"},
            ("git", "rev-list", "origin/main..HEAD"): {
                "rc": 0,
                "stdout": "abcdef1234567890\n",
            },
            ("git", "show", "-s"): {"rc": 0, "stdout": "not-a-timestamp\n"},
        }
        with patch("iamai.unpushed_age._run", side_effect=_make_run_side_effect(responses)):
            result = measure_unpushed_age("/fake/repo")
        assert result.label == "unknown"
        assert result.exit_code == EXIT_UNKNOWN
        assert "non-integer timestamp" in result.error

    def test_reverse_list_failure(self):
        responses = {
            ("git", "rev-list", "--count"): {"rc": 0, "stdout": "2\n"},
            ("git", "rev-list", "origin/main..HEAD"): {
                "rc": 128,
                "stderr": "fatal: ambiguous argument",
            },
        }
        with patch("iamai.unpushed_age._run", side_effect=_make_run_side_effect(responses)):
            result = measure_unpushed_age("/fake/repo")
        assert result.label == "unknown"
        assert result.exit_code == EXIT_UNKNOWN
        assert result.unpushed_count == 2


# ---------------------------------------------------------------------------
# CLI wrapper
# ---------------------------------------------------------------------------

class TestCLI:
    def test_cli_module_loads(self):
        """verify the CLI tool file exists and has a main function."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "unpushed_age_cli", str(REPO / "tools" / "unpushed_age.py")
        )
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(mod.main)

    def test_classify_exits_are_distinct(self):
        """all exit codes must be unique integers."""
        codes = [EXIT_SYNCED, EXIT_FRESH, EXIT_AGING, EXIT_STALE, EXIT_CRITICAL, EXIT_UNKNOWN]
        assert len(set(codes)) == len(codes)
