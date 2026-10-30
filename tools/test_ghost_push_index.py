#!/usr/bin/env python3
"""test_ghost_push_index.py — tests for ghost push index tool."""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "ghost_push_index.py"


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
    assert code in (0, 1, 2), f"unexpected exit code: {code}"
    assert "ghost push index" in out.lower(), f"missing index in output: {out}"


def test_json_output():
    """JSON mode should produce valid JSON with required fields."""
    import json
    code, out = run_tool("--json")
    data = json.loads(out)
    assert "ghost_push_index" in data, "missing ghost_push_index field"
    assert "unpushed_commits" in data, "missing unpushed_commits field"
    assert "total_commits" in data, "missing total_commits field"
    assert "severity" in data, "missing severity field"
    assert isinstance(data["ghost_push_index"], float), "index should be float"
    assert 0.0 <= data["ghost_push_index"] <= 1.0, "index should be between 0 and 1"


def test_remedy_output():
    """Remedy mode should include recovery instructions."""
    code, out = run_tool("--remedy")
    assert "github.com" in out.lower() or "ssh-keygen" in out.lower(), \
        f"remedy should mention github or ssh-keygen: {out}"


def test_severity_labels():
    """Severity should be one of the known labels."""
    import json
    code, out = run_tool("--json")
    data = json.loads(out)
    valid_labels = {"HEALTHY", "WARNING", "CRITICAL", "TOTAL_GHOST"}
    assert data["severity"] in valid_labels, \
        f"unexpected severity: {data['severity']}"


def test_unpushed_le_total():
    """Unpushed commits should never exceed total commits."""
    import json
    code, out = run_tool("--json")
    data = json.loads(out)
    assert data["unpushed_commits"] <= data["total_commits"], \
        f"unpushed ({data['unpushed_commits']}) > total ({data['total_commits']})"


if __name__ == "__main__":
    tests = [
        test_basic_output,
        test_json_output,
        test_remedy_output,
        test_severity_labels,
        test_unpushed_le_total,
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
