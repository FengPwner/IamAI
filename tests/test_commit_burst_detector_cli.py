"""Tests for tools/commit_burst_detector.py — the CLI wrapper.

The library module (iamai.commit_burst_detector) already has its own test suite.
These tests exercise the command-line entry point: argument parsing, exit
codes, JSON output, and git log integration.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "tools" / "commit_burst_detector.py"
REPO = TOOL.parent


def _run(*extra_args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Invoke the CLI as a subprocess and capture output."""
    cmd = [sys.executable, str(TOOL), *extra_args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=cwd or REPO,
    )


# ---------------------------------------------------------------------------
# basic invocation
# ---------------------------------------------------------------------------


class TestBasicInvocation:
    def test_exits_zero_or_one(self):
        """Tool should exit 0 (quiet/steady) or 1 (surging/panic), never crash."""
        result = _run()
        assert result.returncode in (0, 1), f"unexpected exit: {result.stderr}"

    def test_human_output_contains_verdict(self):
        """Default output is a single line with a verdict keyword."""
        result = _run()
        out = result.stdout.strip()
        verdicts = ("quiet", "steady", "surging", "panic")
        assert any(v in out for v in verdicts), f"no verdict in: {out!r}"

    def test_human_output_mentions_window(self):
        """Human-readable line includes the window size for context."""
        result = _run()
        assert "commits" in result.stdout.lower()

    def test_json_output_is_valid(self):
        """--json flag emits parseable JSON with required keys."""
        result = _run("--json")
        data = json.loads(result.stdout)
        for key in ("verdict", "count", "longest", "bursts", "window", "threshold_seconds"):
            assert key in data, f"missing key {key!r} in JSON output"

    def test_json_verdict_matches_human(self):
        """JSON verdict and human line should agree."""
        human = _run().stdout.strip()
        data = json.loads(_run("--json").stdout)
        assert data["verdict"] in human


# ---------------------------------------------------------------------------
# --window override
# ---------------------------------------------------------------------------


class TestWindowOverride:
    def test_custom_window_accepted(self):
        result = _run("--window", "20")
        assert result.returncode in (0, 1)

    def test_json_reflects_custom_window(self):
        data = json.loads(_run("--json", "--window", "25").stdout)
        assert data["window"] == 25

    def test_small_window_works(self):
        """Window=5 should still produce valid output."""
        result = _run("--json", "--window", "5")
        data = json.loads(result.stdout)
        assert data["window"] == 5
        assert data["commits_analysed"] <= 5


# ---------------------------------------------------------------------------
# --threshold override
# ---------------------------------------------------------------------------


class TestThresholdOverride:
    def test_custom_threshold_accepted(self):
        result = _run("--threshold", "120")
        assert result.returncode in (0, 1)

    def test_json_reflects_custom_threshold(self):
        data = json.loads(_run("--json", "--threshold", "45").stdout)
        assert data["threshold_seconds"] == 45.0

    def test_zero_threshold_does_not_crash(self):
        """Edge case: threshold=0 means every gap is a burst gap."""
        result = _run("--threshold", "0")
        assert result.returncode in (0, 1)

    def test_large_threshold_finds_more_bursts(self):
        """A very large threshold should find at least as many bursts as a small one."""
        small = json.loads(_run("--json", "--threshold", "10").stdout)
        large = json.loads(_run("--json", "--threshold", "600").stdout)
        assert large["count"] >= small["count"]


# ---------------------------------------------------------------------------
# --long-burst and --panic-gap overrides
# ---------------------------------------------------------------------------


class TestVerdictOverrides:
    def test_long_burst_accepted(self):
        result = _run("--long-burst", "10")
        assert result.returncode in (0, 1)

    def test_panic_gap_accepted(self):
        result = _run("--panic-gap", "1.0")
        assert result.returncode in (0, 1)

    def test_very_low_panic_gap_avoids_panic(self):
        """Setting panic_gap to 0 should never trigger panic verdict."""
        result = _run("--json", "--panic-gap", "0")
        data = json.loads(result.stdout)
        assert data["verdict"] != "panic"


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_runs_from_different_cwd(self, tmp_path):
        """Tool works when invoked from an arbitrary working directory."""
        result = _run(cwd=tmp_path)
        assert result.returncode in (0, 1)

    def test_json_bursts_are_dicts(self):
        """Each burst in the JSON output should be a dict with documented keys."""
        data = json.loads(_run("--json").stdout)
        for burst in data["bursts"]:
            assert isinstance(burst, dict)
            for key in ("start_index", "length", "duration_seconds", "mean_gap_seconds"):
                assert key in burst

    def test_commits_analysed_is_positive(self):
        """The repo has history; commits_analysed should be > 0."""
        data = json.loads(_run("--json").stdout)
        assert data["commits_analysed"] > 0


# ---------------------------------------------------------------------------
# exit code semantics
# ---------------------------------------------------------------------------


class TestExitCodes:
    def test_quiet_or_steady_exits_zero(self):
        """If the commit rhythm is healthy, exit 0."""
        data = json.loads(_run("--json").stdout)
        result = _run()
        if data["verdict"] in ("quiet", "steady"):
            assert result.returncode == 0

    def test_surging_or_panic_exits_one(self):
        """If the commit rhythm is unhealthy, exit 1 for caretaker scripting."""
        data = json.loads(_run("--json").stdout)
        result = _run()
        if data["verdict"] in ("surging", "panic"):
            assert result.returncode == 1
