#!/usr/bin/env python3
"""test_auto_restart.py — smoke test for auto_restart watchdog.

verifies that auto_restart.py can detect process state and report it
without crashing. does not actually kill live processes (that would
disrupt the running writer).
"""

import subprocess
import sys
import os

AUTO_RESTART = os.path.join(os.path.dirname(__file__), "auto_restart.py")


def test_dry_run_reports_state():
    """--dry-run should return 0 (alive) or 3 (dead) without side effects."""
    result = subprocess.run(
        [sys.executable, AUTO_RESTART, "--dry-run"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode in (0, 3), (
        f"unexpected exit code {result.returncode}: {result.stderr}"
    )
    print(f"auto_restart --dry-run exit code: {result.returncode}")
    if result.returncode == 0:
        print("both processes alive — nothing to restart")
    else:
        print("dead process(es) detected — restart needed")
    return result.returncode


def test_json_output_parseable():
    """--json should produce valid JSON on stdout."""
    import json

    result = subprocess.run(
        [sys.executable, AUTO_RESTART, "--json", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    # may exit 0 or 3; both should produce JSON
    try:
        data = json.loads(result.stdout)
        assert "writer_alive" in data or "writer" in data or "status" in data, (
            f"unexpected JSON keys: {list(data.keys())}"
        )
        print(f"json output parsed: {list(data.keys())}")
    except json.JSONDecodeError:
        # some versions print status line before JSON; find the JSON object
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line.startswith("{"):
                data = json.loads(line)
                print(f"json output parsed from line: {list(data.keys())}")
                break
        else:
            print(f"stdout was: {result.stdout[:500]}")
            raise
    return result.returncode


if __name__ == "__main__":
    code1 = test_dry_run_reports_state()
    code2 = test_json_output_parseable()
    print(f"tests passed — dry_run={code1}, json={code2}")
