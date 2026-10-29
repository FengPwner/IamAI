#!/usr/bin/env python3
"""push_round_trip.py — measure the latency from commit to remote push.

a commit that sits unpushed for ten minutes is normal batch behaviour.
one that sits for three hours means the pipeline is broken and nobody
noticed. this tool answers: how long did it take for the most recent
commits to reach origin/main?

the metric matters because:
  - batch interval is 600s; anything under ~700s is healthy.
  - 1–2 batch cycles (600–1200s) is nominal after a transient push failure.
  - >3600s means something is genuinely stuck.

state is a JSONL log at data/push_round_trip.jsonl so it survives restarts.

exit codes:
  0 — healthy  (latest round-trip < 1200s or synced)
  1 — nominal  (latest round-trip 1200–3600s)
  2 — degraded (latest round-trip > 3600s)
  3 — unknown  (cannot determine)

usage:
  python3 tools/push_round_trip.py [--json] [--record]
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
STATE_FILE = DATA_DIR / "push_round_trip.jsonl"

THRESHOLDS = [
    (1200, 0, "healthy"),
    (3600, 1, "nominal"),
    (float("inf"), 2, "degraded"),
]


def classify(seconds):
    """return (exit_code, label) for a given round-trip latency."""
    if seconds is None:
        return 3, "unknown"
    for threshold, code, label in THRESHOLDS:
        if seconds < threshold:
            return code, label
    return 2, "degraded"


def git(args, repo=REPO):
    """run a git command and return (stdout, returncode)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=str(repo),
            timeout=15,
        )
        return result.stdout.strip(), result.returncode
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return str(exc), -1


def get_unpushed_commits(repo=REPO):
    """list commits on HEAD not yet on origin/main."""
    out, rc = git(["log", "--format=%H %ct", "origin/main..HEAD"], repo)
    if rc != 0 or not out:
        return []
    commits = []
    for line in out.strip().split("\n"):
        parts = line.split()
        if len(parts) == 2:
            commits.append({"sha": parts[0][:12], "timestamp": int(parts[1])})
    return commits


def get_latest_remote_sync(repo=REPO):
    """get the timestamp of the latest commit that IS on origin/main."""
    out, rc = git(["log", "-1", "--format=%ct", "origin/main"], repo)
    if rc != 0:
        return None
    try:
        return int(out)
    except ValueError:
        return None


def measure(repo=REPO):
    """produce a round-trip report dict."""
    now = int(time.time())
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.gmtime(now))
    unpushed = get_unpushed_commits(repo)

    if not unpushed:
        # fully synced — round-trip is effectively zero
        return {
            "timestamp": ts,
            "unpushed": 0,
            "oldest_unpushed_age": 0,
            "newest_unpushed_age": 0,
            "severity": "healthy",
            "exit_code": 0,
        }

    oldest = min(c["timestamp"] for c in unpushed)
    newest = max(c["timestamp"] for c in unpushed)
    oldest_age = now - oldest
    newest_age = now - newest
    exit_code, label = classify(oldest_age)

    return {
        "timestamp": ts,
        "unpushed": len(unpushed),
        "oldest_unpushed_age": oldest_age,
        "newest_unpushed_age": newest_age,
        "oldest_sha": unpushed[-1]["sha"],  # oldest is last in the list
        "newest_sha": unpushed[0]["sha"],
        "severity": label,
        "exit_code": exit_code,
    }


def record(report, state_file=STATE_FILE):
    """append a report line to the JSONL log."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with state_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(report) + "\n")


def read_history(state_file=STATE_FILE, last_n=10):
    """read the last N entries from the JSONL log."""
    if not state_file.exists():
        return []
    lines = state_file.read_text(encoding="utf-8").strip().split("\n")
    entries = []
    for line in lines[-last_n:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def human_summary(report):
    """one-line human-readable summary."""
    n = report["unpushed"]
    if n == 0:
        return "synced — all commits reached origin/main"
    oldest = report["oldest_unpushed_age"]
    if oldest < 60:
        age_str = f"{oldest}s"
    elif oldest < 3600:
        age_str = f"{oldest // 60}m{oldest % 60}s"
    else:
        age_str = f"{oldest // 3600}h{(oldest % 3600) // 60}m"
    return (
        f"{n} unpushed commit(s), oldest pending {age_str} "
        f"[{report['severity']}]"
    )


def main():
    use_json = "--json" in sys.argv
    do_record = "--record" in sys.argv

    report = measure()

    if do_record:
        record(report)

    if use_json:
        print(json.dumps(report, indent=2))
    else:
        print(human_summary(report))

    sys.exit(report["exit_code"])


if __name__ == "__main__":
    main()
