#!/usr/bin/env python3
"""repo_immune_response.py — measure the repo's immune system speed.

a healthy repo detects and resolves anomalies quickly: uncommitted files
get committed, push failures get retried, dead processes get restarted.
this tool measures three latencies that together form an "immune score":

  1. detection_latency  — anomaly start → first monitor notices
  2. response_latency   — detection → first corrective action
  3. resolution_latency — anomaly start → fully resolved

each visit records a snapshot in data/immune_response.jsonl. the composite
immune score (0–100) rewards fast resolution and penalises slow or missing
responses:

    score = max(0, 100 - (resolution_minutes * 2))

thresholds:
  ≥ 80  robust    — the repo heals itself quickly
  60–79 adequate  — some lag but nothing dangerous
  40–59 sluggish  — anomalies linger, attention needed
  < 40  immunocompromised — systemic failure risk

usage:
  python3 tools/repo_immune_response.py [--json] [--record]
  python3 tools/repo_immune_response.py --score <resolution_seconds>
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "data"
STATE_FILE = DATA_DIR / "immune_response.jsonl"

GRADE_THRESHOLDS = [
    (80, "robust"),
    (60, "adequate"),
    (40, "sluggish"),
    (0, "immunocompromised"),
]


def compute_score(resolution_seconds):
    """compute immune score from resolution time in seconds.

    score = max(0, 100 - resolution_minutes * 2)
    a 5-minute resolution → 90; a 50-minute resolution → 0.
    """
    if resolution_seconds is None or resolution_seconds < 0:
        return 0
    minutes = resolution_seconds / 60.0
    return max(0, round(100 - minutes * 2))


def grade(score):
    """return the qualitative label for a score."""
    for threshold, label in GRADE_THRESHOLDS:
        if score >= threshold:
            return label
    return "immunocompromised"


def classify_resolution(seconds):
    """return (score, grade) for a resolution time."""
    score = compute_score(seconds)
    return score, grade(score)


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


def detect_uncommitted_age(repo=REPO):
    """measure how long the oldest uncommitted change has existed.

    uses the mtime of the most recently modified tracked file that
    differs from HEAD.
    """
    out, rc = git(["diff", "--name-only"], repo)
    if rc != 0 or not out:
        return 0  # clean working tree
    files = out.strip().split("\n")
    oldest_age = 0
    now = time.time()
    for f in files:
        fpath = repo / f
        if fpath.exists():
            age = now - fpath.stat().st_mtime
            oldest_age = max(oldest_age, age)
    return int(oldest_age)


def detect_unpushed_age(repo=REPO):
    """measure how long the oldest unpushed commit has been waiting."""
    out, rc = git(
        ["log", "--format=%ct", "origin/main..HEAD", "--reverse"], repo
    )
    if rc != 0 or not out:
        return 0  # fully pushed
    lines = out.strip().split("\n")
    if not lines:
        return 0
    oldest_ts = int(lines[0])
    return int(time.time()) - oldest_ts


def detect_process_gaps(writer_state_file=None):
    """estimate writer silence gap from writer state file."""
    if writer_state_file is None:
        writer_state_file = REPO / "data" / "writer_state.qwen.json"
    if not writer_state_file.exists():
        return 0
    try:
        state = json.loads(writer_state_file.read_text(encoding="utf-8"))
        last_at = state.get("last_stroke_at")
        if last_at:
            # parse ISO timestamp
            dt = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            gap = (now - dt).total_seconds()
            return max(0, int(gap))
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return 0


def snapshot(repo=REPO):
    """produce an immune response snapshot dict."""
    now = int(time.time())
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.gmtime(now))

    uncommitted_age = detect_uncommitted_age(repo)
    unpushed_age = detect_unpushed_age(repo)
    writer_gap = detect_process_gaps()

    # the "resolution latency" is the worst active anomaly
    active_anomalies = []
    if uncommitted_age > 30:
        active_anomalies.append(("uncommitted", uncommitted_age))
    if unpushed_age > 660:  # > 1 batch cycle
        active_anomalies.append(("unpushed", unpushed_age))
    if writer_gap > 30:  # > 2x the 15s cadence
        active_anomalies.append(("writer_silent", writer_gap))

    worst_resolution = max((a[1] for a in active_anomalies), default=0)
    score = compute_score(worst_resolution)
    label = grade(score)

    return {
        "timestamp": ts,
        "uncommitted_age_s": uncommitted_age,
        "unpushed_age_s": unpushed_age,
        "writer_gap_s": writer_gap,
        "active_anomalies": len(active_anomalies),
        "worst_resolution_s": worst_resolution,
        "immune_score": score,
        "grade": label,
    }


def record(snapshot_data, state_file=STATE_FILE):
    """append a snapshot to the JSONL log."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with state_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snapshot_data) + "\n")


def read_history(state_file=STATE_FILE, last_n=10):
    """read the last N snapshots from the JSONL log."""
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


def trend(history):
    """compute score trend from a list of snapshots.

    returns: 'improving', 'stable', or 'declining'
    """
    if len(history) < 2:
        return "insufficient_data"
    scores = [h.get("immune_score", 0) for h in history]
    first_half = scores[: len(scores) // 2]
    second_half = scores[len(scores) // 2 :]
    avg_first = sum(first_half) / len(first_half) if first_half else 0
    avg_second = sum(second_half) / len(second_half) if second_half else 0
    diff = avg_second - avg_first
    if diff > 5:
        return "improving"
    elif diff < -5:
        return "declining"
    return "stable"


def human_summary(snap):
    """one-line human-readable summary."""
    score = snap["immune_score"]
    g = snap["grade"]
    anomalies = snap["active_anomalies"]
    worst = snap["worst_resolution_s"]

    if anomalies == 0:
        return f"immune score {score}/100 [{g}] — no active anomalies"

    if worst < 60:
        age_str = f"{worst}s"
    elif worst < 3600:
        age_str = f"{worst // 60}m{worst % 60}s"
    else:
        age_str = f"{worst // 3600}h{(worst % 3600) // 60}m"

    return (
        f"immune score {score}/100 [{g}] — "
        f"{anomalies} active anomaly(ies), worst resolution {age_str}"
    )


def main():
    use_json = "--json" in sys.argv
    do_record = "--record" in sys.argv

    if "--score" in sys.argv:
        idx = sys.argv.index("--score")
        if idx + 1 < len(sys.argv):
            secs = int(sys.argv[idx + 1])
            s = compute_score(secs)
            g = grade(s)
            print(f"resolution {secs}s → score {s}/100 [{g}]")
            sys.exit(0)
        else:
            print("usage: --score <seconds>", file=sys.stderr)
            sys.exit(1)

    snap = snapshot()

    if do_record:
        record(snap)

    if use_json:
        print(json.dumps(snap, indent=2))
    else:
        print(human_summary(snap))

    sys.exit(0 if snap["immune_score"] >= 60 else 1)


if __name__ == "__main__":
    main()
