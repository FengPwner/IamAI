"""process_collision — detect duplicate daemon instances.

Multiple instances of the same daemon (writer_loop, commit_batch) are
dangerous: they race on ``data/strokes.jsonl``, double-commit, and
trigger push rejections.  This failure mode is distinct from every
other process-health module:

======================  ===============================================
module                  what it detects
======================  ===============================================
stale_pid_detector      PID file exists but process is dead
process_zombie          process alive but producing no output
process_supervisor      decides whether to restart a dead process
process_liveness        binary alive/dead check
process_collision       **two or more live instances of the same daemon**
======================  ===============================================

The caretaker visit that created this module (visit 685) found *two*
pairs of writer_loop + commit_batch running simultaneously after a
restart, leading to conflicting file writes and push divergence.

Process record
--------------

Each process is represented as a dict (or any mapping) with:

- ``pid`` (int): process ID
- ``command`` (str): the command line (``/proc/<pid>/cmdline`` style)
- ``uptime_s`` (float, optional): seconds since process started

Functions
---------

``detect_groups(processes)``
    Group processes by command-line signature and return only
    groups with more than one instance.

``collision_risk(groups)``
    Score the collision severity from 0.0 (no collisions) to 1.0
    (many overlapping daemons writing the same files).

``pick_survivor(group)``
    Choose which instance to keep: the one with the lowest PID
    (oldest) wins; ties broken by highest uptime.

``collision_report(processes)``
    One-call summary: groups, risk score, recommended kills.

Zero dependencies.  stdlib only.

>>> procs = [
...     {"pid": 100, "command": "python3 tools/writer_loop.py --writer qwen --every 15", "uptime_s": 300},
...     {"pid": 200, "command": "python3 tools/writer_loop.py --writer qwen --every 15", "uptime_s": 60},
...     {"pid": 300, "command": "python3 tools/commit_batch.py --watch --writer qwen --interval 600", "uptime_s": 300},
... ]
>>> groups = detect_groups(procs)
>>> len(groups)
1
>>> groups[0]["signature"]
'writer_loop.py --writer qwen'
>>> collision_risk(groups) > 0
True
>>> pick_survivor(groups[0]["instances"])["pid"]
100
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Signature extraction
# ---------------------------------------------------------------------------

_DAEMON_PATTERNS = [
    re.compile(r"(writer_loop\.py)\s+--writer\s+(\S+)"),
    re.compile(r"(commit_batch\.py)\s+--watch\s+--writer\s+(\S+)"),
    re.compile(r"(guoban_loop\.py)"),
]


def _extract_signature(command: str) -> str:
    """Derive a grouping key from a command line.

    Two processes belong to the same group iff they run the same
    daemon script with the same primary arguments (writer name).
    Ancillary flags like ``--every 15`` vs ``--every 30`` are
    intentionally ignored so that a restart with different cadence
    still counts as a collision.

    >>> _extract_signature("python3 tools/writer_loop.py --writer qwen --every 15")
    'writer_loop.py --writer qwen'
    >>> _extract_signature("python3 tools/writer_loop.py --writer qwen --every 30")
    'writer_loop.py --writer qwen'
    >>> _extract_signature("python3 tools/commit_batch.py --watch --writer doubao --interval 600")
    'commit_batch.py --writer doubao'
    >>> _extract_signature("python3 tools/guoban_loop.py")
    'guoban_loop.py'
    >>> _extract_signature("python3 -m http.server 8080")
    'unknown'
    """
    for pat in _DAEMON_PATTERNS:
        m = pat.search(command)
        if m:
            groups = m.groups()
            if len(groups) == 2:
                return f"{groups[0]} --writer {groups[1]}"
            return groups[0]
    return "unknown"


# ---------------------------------------------------------------------------
# Group detection
# ---------------------------------------------------------------------------

def detect_groups(
    processes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Find groups of duplicate daemon processes.

    Returns only groups with 2+ instances sharing the same signature.
    Processes with signature ``"unknown"`` are never grouped (they
    are not recognised daemons).

    >>> detect_groups([
    ...     {"pid": 1, "command": "python3 tools/writer_loop.py --writer qwen --every 15"},
    ...     {"pid": 2, "command": "python3 tools/writer_loop.py --writer qwen --every 15"},
    ... ])[0]["count"]
    2
    >>> detect_groups([{"pid": 1, "command": "python3 -m http.server"}])
    []
    """
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for proc in processes:
        sig = _extract_signature(proc.get("command", ""))
        if sig == "unknown":
            continue
        buckets.setdefault(sig, []).append(proc)

    groups = []
    for sig, instances in sorted(buckets.items()):
        if len(instances) >= 2:
            groups.append({
                "signature": sig,
                "count": len(instances),
                "instances": list(instances),
            })
    return groups


# ---------------------------------------------------------------------------
# Risk scoring
# ---------------------------------------------------------------------------

def collision_risk(groups: List[Dict[str, Any]]) -> float:
    """Score collision severity from 0.0 (clean) to 1.0 (critical).

    The score is the minimum of 1.0 and the sum of per-group risk
    contributions:

    - Each duplicate instance adds 0.25.
    - A group touching ``writer_loop`` gets a 0.1 bonus (write-race
      risk is higher than batch-commit races).

    >>> collision_risk([])
    0.0
    >>> collision_risk([{"signature": "writer_loop.py --writer qwen", "count": 2, "instances": []}])
    0.35
    >>> collision_risk([
    ...     {"signature": "writer_loop.py --writer qwen", "count": 2, "instances": []},
    ...     {"signature": "commit_batch.py --writer qwen", "count": 2, "instances": []},
    ... ])
    0.6
    """
    if not groups:
        return 0.0

    total = 0.0
    for g in groups:
        extras = g["count"] - 1  # number of *duplicate* instances
        total += extras * 0.25
        if "writer_loop" in g.get("signature", ""):
            total += 0.1  # write-race premium
    return min(total, 1.0)


# ---------------------------------------------------------------------------
# Survivor selection
# ---------------------------------------------------------------------------

def pick_survivor(instances: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Choose which instance to keep: lowest PID, then highest uptime.

    The oldest process (lowest PID) is most likely to have a valid
    working state.  If PIDs are somehow equal (shouldn't happen), the
    one with more uptime wins.

    >>> pick_survivor([
    ...     {"pid": 200, "command": "c", "uptime_s": 60},
    ...     {"pid": 100, "command": "c", "uptime_s": 300},
    ... ])["pid"]
    100
    >>> pick_survivor([
    ...     {"pid": 100, "command": "c", "uptime_s": 60},
    ...     {"pid": 100, "command": "c", "uptime_s": 300},
    ... ])["uptime_s"]
    300
    """
    return min(
        instances,
        key=lambda p: (p.get("pid", 0), -p.get("uptime_s", 0)),
    )


def pick_victims(instances: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return all instances except the survivor (the ones to kill).

    >>> victims = pick_victims([
    ...     {"pid": 100, "command": "c", "uptime_s": 300},
    ...     {"pid": 200, "command": "c", "uptime_s": 60},
    ... ])
    >>> [v["pid"] for v in victims]
    [200]
    """
    survivor = pick_survivor(instances)
    return [p for p in instances if p is not survivor]


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------

def collision_report(
    processes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """One-call summary of process collisions.

    Returns a dict with:

    - ``total_processes``: input count
    - ``groups``: list of collision groups
    - ``risk``: 0.0–1.0 score
    - ``recommendations``: list of ``{"kill_pid": ..., "keep_pid": ..., "reason": ...}``
    - ``clean``: bool — True iff no collisions detected

    >>> r = collision_report([
    ...     {"pid": 100, "command": "python3 tools/writer_loop.py --writer qwen --every 15", "uptime_s": 300},
    ...     {"pid": 200, "command": "python3 tools/writer_loop.py --writer qwen --every 15", "uptime_s": 60},
    ...     {"pid": 300, "command": "python3 tools/commit_batch.py --watch --writer qwen --interval 600", "uptime_s": 300},
    ... ])
    >>> r["clean"]
    False
    >>> r["risk"] > 0
    True
    >>> len(r["recommendations"])
    1
    >>> r["recommendations"][0]["kill_pid"]
    200

    >>> r2 = collision_report([
    ...     {"pid": 100, "command": "python3 tools/writer_loop.py --writer qwen --every 15"},
    ...     {"pid": 300, "command": "python3 tools/commit_batch.py --watch --writer qwen --interval 600"},
    ... ])
    >>> r2["clean"]
    True
    """
    groups = detect_groups(processes)
    risk = collision_risk(groups)

    recommendations = []
    for g in groups:
        survivor = pick_survivor(g["instances"])
        for victim in pick_victims(g["instances"]):
            recommendations.append({
                "kill_pid": victim.get("pid"),
                "keep_pid": survivor.get("pid"),
                "signature": g["signature"],
                "reason": (
                    f"duplicate {g['signature']}: "
                    f"pid {victim.get('pid')} is younger than pid {survivor.get('pid')}"
                ),
            })

    return {
        "total_processes": len(processes),
        "groups": groups,
        "risk": risk,
        "recommendations": recommendations,
        "clean": len(groups) == 0,
    }
