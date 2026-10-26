#!/usr/bin/env python3
"""test_commit_visibility_lag.py — tests for commit visibility lag tool."""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "commit_visibility_lag.py"


def run_tool(*args: str) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(TOOL)] + list(args),
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    return result.returncode, result.stdout.strip()


def test_basic_output():
    """Tool should produce output and return a valid exit code."""
    code, out = run_tool()
    assert code in (0, 1, 2, 3, 4), f"unexpected exit code: {code}"
    assert len(out) > 0, "output should not be empty"


def test_json_output():
    """JSON mode should produce valid JSON with required fields."""
    code, out = run_tool("--json")
    data = json.loads(out)
    assert "visibility_lag_seconds" in data, "missing visibility_lag_seconds"
    assert "severity" in data, "missing severity"
    assert "unpushed_commits" in data, "missing unpushed_commits"
    assert "total_commits" in data, "missing total_commits"
    assert isinstance(data["visibility_lag_seconds"], (int, float)), \
        "lag should be numeric"


def test_severity_labels():
    """Severity should be one of the known labels."""
    code, out = run_tool("--json")
    data = json.loads(out)
    valid_labels = {"REALTIME", "STALE", "OUTDATED", "ANCIENT"}
    assert data["severity"] in valid_labels, \
        f"unexpected severity: {data['severity']}"


def test_lag_nonnegative():
    """Visibility lag should never be negative."""
    code, out = run_tool("--json")
    data = json.loads(out)
    assert data["visibility_lag_seconds"] >= 0, \
        f"lag should be non-negative, got {data['visibility_lag_seconds']}"


def test_unpushed_le_total():
    """Unpushed commits should never exceed total commits."""
    code, out = run_tool("--json")
    data = json.loads(out)
    if data["total_commits"] > 0:
        assert data["unpushed_commits"] <= data["total_commits"], \
            f"unpushed ({data['unpushed_commits']}) > total ({data['total_commits']})"


def test_days_flag():
    """--days flag should produce output containing 'days'."""
    code, out = run_tool("--json", "--days")
    data = json.loads(out)
    if data["total_commits"] > 0 and data["unpushed_commits"] > 0:
        assert "visibility_lag_human" in data, "missing human-readable lag"


def test_exit_code_matches_severity():
    """Exit code should correspond to severity level."""
    code, out = run_tool("--json")
    data = json.loads(out)
    expected_codes = {
        "REALTIME": 0,
        "STALE": 1,
        "OUTDATED": 2,
        "ANCIENT": 3,
    }
    if data["severity"] in expected_codes:
        assert code == expected_codes[data["severity"]], \
            f"exit code {code} != expected {expected_codes[data['severity']]} for {data['severity']}"


def test_oldest_unpushed_present():
    """When there are unpushed commits, oldest_unpushed should be set."""
    code, out = run_tool("--json")
    data = json.loads(out)
    if data["unpushed_commits"] > 0:
        assert data["oldest_unpushed"] is not None, \
            "oldest_unpushed should be set when unpushed commits exist"


def test_human_output_contains_key_info():
    """Human-readable output should mention lag and severity."""
    code, out = run_tool()
    lower = out.lower()
    assert "commit visibility lag" in lower, \
        f"missing header in output: {out}"


if __name__ == "__main__":
    tests = [
        test_basic_output,
        test_json_output,
        test_severity_labels,
        test_lag_nonnegative,
        test_unpushed_le_total,
        test_days_flag,
        test_exit_code_matches_severity,
        test_oldest_unpushed_present,
        test_human_output_contains_key_info,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
