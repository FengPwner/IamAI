#!/usr/bin/env python3
"""env_inheritance_check.py — validate that a running process has required env vars.

the batch committer and writer_loop inherit GIT_SSH_COMMAND from run_both.sh.
when an external process (caretaker check, cron, manual push) runs in a
different shell, it may lack that variable and fail silently. this tool
answers one question: does a given pid have the environment it needs?

usage:
    python3 tools/env_inheritance_check.py --pid 6003
    python3 tools/env_inheritance_check.py --pid 6003 --var GIT_SSH_COMMAND
    python3 tools/env_inheritance_check.py --pid 6003 --required GIT_SSH_COMMAND,PATH
    python3 tools/env_inheritance_check.py --pid 6003 --json

exit codes:
    0 — all required variables present
    1 — one or more required variables missing
    2 — process not found or /proc unavailable
    3 — usage error
"""

import json
import os
import sys


DEFAULT_REQUIRED = ["GIT_SSH_COMMAND", "PATH", "HOME"]
PROC_ENV_TEMPLATE = "/proc/{pid}/environ"


def read_proc_env(pid: int) -> dict:
    """Read environment variables from /proc/<pid>/environ.

    Returns a dict of var_name -> value, or raises FileNotFoundError/OSError.
    """
    path = PROC_ENV_TEMPLATE.format(pid=pid)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"no such process or /proc unavailable: pid {pid}")
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    env = {}
    for entry in raw.split("\x00"):
        if "=" in entry:
            key, _, value = entry.partition("=")
            if key:
                env[key] = value
    return env


def check_env(pid: int, required: list) -> dict:
    """Check which required variables are present in a process's environment.

    Returns a report dict with:
      - pid: the checked process id
      - required: list of variable names checked
      - present: dict of var_name -> (truncated) value for found vars
      - missing: list of var names not found
      - ok: True if no variables are missing
    """
    try:
        env = read_proc_env(pid)
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return {
            "pid": pid,
            "error": str(exc),
            "ok": False,
            "required": required,
            "present": {},
            "missing": required,
        }

    present = {}
    missing = []
    for var in required:
        if var in env:
            # truncate long values for display (e.g. GIT_SSH_COMMAND with full path)
            val = env[var]
            present[var] = val if len(val) <= 120 else val[:117] + "..."
        else:
            missing.append(var)

    return {
        "pid": pid,
        "required": required,
        "present": present,
        "missing": missing,
        "ok": len(missing) == 0,
    }


def parse_required(raw: str) -> list:
    """Parse a comma-separated list of required variable names."""
    return [v.strip() for v in raw.split(",") if v.strip()]


def main():
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pid", type=int, required=True, help="PID to inspect")
    ap.add_argument(
        "--var",
        type=str,
        default=None,
        help="single variable name to check (shortcut for --required)",
    )
    ap.add_argument(
        "--required",
        type=str,
        default=None,
        help="comma-separated list of required variable names",
    )
    ap.add_argument("--json", action="store_true", help="output structured JSON")
    args = ap.parse_args()

    if args.var:
        required = [args.var]
    elif args.required:
        required = parse_required(args.required)
    else:
        required = DEFAULT_REQUIRED

    report = check_env(args.pid, required)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        status = "OK" if report["ok"] else "FAIL"
        print(f"[{status}] pid {args.pid}")
        if "error" in report:
            print(f"  error: {report['error']}")
        for var, val in report.get("present", {}).items():
            print(f"  {var} = {val}")
        for var in report.get("missing", []):
            print(f"  {var} = (MISSING)")

    if "error" in report:
        return 2
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
