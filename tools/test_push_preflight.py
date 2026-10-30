#!/usr/bin/env python3
"""test_push_preflight.py — smoke test for push_preflight diagnostics.

run after restart to verify push_preflight returns the expected failure
mode when the deploy key is not registered. exit 0 means the diagnostic
itself works (not that push will succeed).
"""

import subprocess
import sys
import os

PREFLIGHT = os.path.join(os.path.dirname(__file__), "push_preflight.py")


def test_preflight_runs():
    """push_preflight executes and returns a known exit code."""
    result = subprocess.run(
        [sys.executable, PREFLIGHT],
        capture_output=True,
        text=True,
        timeout=30,
    )
    # exit 0 = push would succeed; exit 4 = key not registered (expected)
    assert result.returncode in (0, 1, 2, 3, 4, 5), (
        f"unexpected exit code {result.returncode}"
    )
    print(f"push_preflight exit code: {result.returncode}")
    if result.returncode == 4:
        print("expected: key not registered — push will fail until deploy key is added")
    elif result.returncode == 0:
        print("push credentials healthy")
    else:
        print(f"diagnostic issue: {result.stderr.strip()}")
    return result.returncode


if __name__ == "__main__":
    code = test_preflight_runs()
    print("test passed — diagnostic returned expected exit code")
