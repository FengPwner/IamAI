"""Tests for tools/stroke_freshness.py — the CLI wrapper.

The library module (iamai.stroke_freshness) already has its own test suite.
These tests exercise the command-line entry point: argument parsing, exit
codes, and output format.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parent.parent / "tools" / "stroke_freshness.py"
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
        """Tool should exit 0 (fresh/warm) or 1 (stale/dead), never crash."""
        result = _run()
        assert result.returncode in (0, 1), f"unexpected exit: {result.stderr}"

    def test_human_output_contains_verdict(self):
        """Default output is a single human-readable line with a verdict keyword."""
        result = _run()
        out = result.stdout.strip()
        verdicts = ("fresh", "warm", "stale", "dead")
        assert any(v in out for v in verdicts), f"no verdict in: {out!r}"

    def test_human_output_mentions_cadence(self):
        """Human-readable line includes the cadence for context."""
        result = _run()
        assert "cadence" in result.stdout.lower()

    def test_json_output_is_valid(self):
        """--json flag emits parseable JSON with required keys."""
        result = _run("--json")
        data = json.loads(result.stdout)
        for key in ("verdict", "age_seconds", "cadence_seconds"):
            assert key in data, f"missing key {key!r} in JSON output"

    def test_json_verdict_matches_human(self):
        """JSON verdict and human line should agree on the tier."""
        human = _run().stdout.strip()
        data = json.loads(_run("--json").stdout)
        assert data["verdict"] in human


# ---------------------------------------------------------------------------
# --cadence override
# ---------------------------------------------------------------------------


class TestCadenceOverride:
    def test_custom_cadence_accepted(self):
        result = _run("--cadence", "10")
        assert result.returncode in (0, 1)

    def test_json_reflects_custom_cadence(self):
        data = json.loads(_run("--json", "--cadence", "42").stdout)
        assert data["cadence_seconds"] == 42.0

    def test_zero_cadence_does_not_crash(self):
        """Edge case: cadence=0 should not divide-by-zero (all verdicts become dead)."""
        result = _run("--cadence", "0")
        # should still exit cleanly
        assert result.returncode in (0, 1)


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_runs_from_different_cwd(self, tmp_path):
        """Tool works when invoked from an arbitrary working directory."""
        result = _run(cwd=tmp_path)
        assert result.returncode in (0, 1)
        # Should still find the repo via REPO = Path(__file__).resolve().parent.parent

    def test_json_output_keys_are_stable(self):
        """JSON output always contains the documented keys regardless of verdict."""
        result = _run("--json")
        data = json.loads(result.stdout)
        expected_keys = {"verdict", "age_seconds", "cadence_seconds", "last_stroke_at", "strokes_path"}
        assert expected_keys == set(data.keys())


# ---------------------------------------------------------------------------
# exit code semantics
# ---------------------------------------------------------------------------


class TestExitCodes:
    def test_fresh_or_warm_exits_zero(self):
        """If the repo is healthy, exit 0."""
        data = json.loads(_run("--json").stdout)
        result = _run()
        if data["verdict"] in ("fresh", "warm"):
            assert result.returncode == 0

    def test_stale_or_dead_exits_one(self):
        """If the repo is unhealthy, exit 1 for caretaker scripting."""
        data = json.loads(_run("--json").stdout)
        result = _run()
        if data["verdict"] in ("stale", "dead"):
            assert result.returncode == 1
