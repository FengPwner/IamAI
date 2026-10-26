#!/usr/bin/env python3
"""test_push_debt_calculator.py — tests for push debt calculator."""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "push_debt_calculator.py"


def run_tool(*args: str) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, str(TOOL)] + list(args),
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    return result.returncode, result.stdout.strip()


def test_basic_output():
    """Tool should produce structured output with required sections."""
    code, out = run_tool()
    assert code in (0, 1), f"unexpected exit code: {code}"
    assert "Push Debt Report" in out, f"missing header in output: {out}"
    assert "unpushed commits" in out, f"missing unpushed count: {out}"
    assert "PUSH DEBT SCORE" in out, f"missing score: {out}"


def test_json_output():
    """JSON mode should produce valid JSON with all required fields."""
    code, out = run_tool("--json")
    data = json.loads(out)
    required_fields = [
        "unpushed_count",
        "oldest_unpushed_ts",
        "newest_unpushed_ts",
        "hours_since_last_push",
        "commits_per_hour",
        "volume_frac",
        "age_frac",
        "density_frac",
        "score",
        "severity",
        "total_local_commits",
    ]
    for field in required_fields:
        assert field in data, f"missing field: {field}"

    assert isinstance(data["score"], float), "score should be float"
    assert 0.0 <= data["score"] <= 1.0, f"score out of range: {data['score']}"
    assert data["severity"] in ("healthy", "concerning", "critical", "emergency"), \
        f"unknown severity: {data['severity']}"


def test_timeline_output():
    """Timeline mode should show temporal information."""
    code, out = run_tool("--timeline")
    assert "Push Debt Timeline" in out, f"missing timeline header: {out}"
    assert "last push" in out.lower() or "hours" in out.lower(), \
        f"missing temporal info: {out}"


def test_severity_consistency():
    """Severity label should match the score range."""
    code, out = run_tool("--json")
    data = json.loads(out)
    score = data["score"]
    severity = data["severity"]

    if score < 0.2:
        assert severity == "healthy", f"score {score} should be healthy, got {severity}"
    elif score < 0.5:
        assert severity == "concerning", f"score {score} should be concerning, got {severity}"
    elif score < 0.8:
        assert severity == "critical", f"score {score} should be critical, got {severity}"
    else:
        assert severity == "emergency", f"score {score} should be emergency, got {severity}"


def test_exit_code_matches_severity():
    """Exit code 0 for manageable, 1 for critical."""
    code, out = run_tool("--json")
    data = json.loads(out)
    if data["score"] < 0.5:
        assert code == 0, f"expected exit 0 for score {data['score']}, got {code}"
    else:
        assert code == 1, f"expected exit 1 for score {data['score']}, got {code}"


def test_unpushed_count_nonnegative():
    """Unpushed count should never be negative."""
    code, out = run_tool("--json")
    data = json.loads(out)
    assert data["unpushed_count"] >= 0, \
        f"negative unpushed count: {data['unpushed_count']}"


def test_fractions_bounded():
    """All fraction values should be between 0 and 1."""
    code, out = run_tool("--json")
    data = json.loads(out)
    for frac_field in ("volume_frac", "age_frac", "density_frac"):
        val = data[frac_field]
        assert 0.0 <= val <= 1.0, f"{frac_field} out of range: {val}"


if __name__ == "__main__":
    # run all test_ functions
    import inspect
    tests = [
        (name, obj)
        for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    ]
    passed = failed = 0
    for name, fn in sorted(tests):
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except Exception as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
    print(f"\n{passed} passed, {failed} failed, {passed + failed} total")
    sys.exit(1 if failed else 0)
