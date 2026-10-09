"""Repo heartbeat — is the repository still alive?

Combines three signals into a single liveness verdict:

    1. **Commit freshness** — was something committed in the last *max_gap* seconds?
    2. **Stroke freshness** — did the writer append a stroke recently?
    3. **Process liveness** — are writer and batch PIDs still breathing?

Each signal is scored independently; the aggregate decides whether the
repo is *healthy*, *degraded* (one signal lagging), or *dead* (two or
more signals failing).

Usage from Python:

    from iamai.repo_heartbeat import assess, HeartbeatVerdict
    result = assess(repo_root=Path("."))
    print(result.verdict)   # healthy | degraded | dead
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class HeartbeatVerdict(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DEAD = "dead"


@dataclass
class SignalResult:
    name: str
    ok: bool
    detail: str = ""
    age_seconds: float | None = None


@dataclass
class HeartbeatReport:
    verdict: HeartbeatVerdict
    signals: list[SignalResult] = field(default_factory=list)
    checked_at: str = ""

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "checked_at": self.checked_at,
            "signals": [
                {
                    "name": s.name,
                    "ok": s.ok,
                    "detail": s.detail,
                    "age_seconds": s.age_seconds,
                }
                for s in self.signals
            ],
        }


# ---------------------------------------------------------------------------
# Individual signal checkers
# ---------------------------------------------------------------------------


def check_commit_freshness(
    repo_root: Path, max_gap: int = 1200
) -> SignalResult:
    """Check whether the latest commit is younger than *max_gap* seconds."""
    try:
        raw = subprocess.check_output(
            ["git", "log", "-1", "--format=%aI"],
            cwd=str(repo_root),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        last_commit = datetime.fromisoformat(raw)
        now = datetime.now(timezone.utc)
        age = (now - last_commit).total_seconds()
        ok = age <= max_gap
        return SignalResult(
            name="commit_freshness",
            ok=ok,
            detail=f"last commit {age:.0f}s ago (threshold {max_gap}s)",
            age_seconds=age,
        )
    except Exception as exc:
        return SignalResult(
            name="commit_freshness",
            ok=False,
            detail=f"could not read git log: {exc}",
        )


def check_stroke_freshness(
    repo_root: Path,
    strokes_path: str = "data/strokes.jsonl",
    max_gap: int = 600,
) -> SignalResult:
    """Check whether the last stroke was written within *max_gap* seconds."""
    fp = repo_root / strokes_path
    if not fp.exists():
        return SignalResult(
            name="stroke_freshness", ok=False, detail="strokes file missing"
        )
    try:
        last_line = ""
        with open(fp, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    last_line = line
        if not last_line:
            return SignalResult(
                name="stroke_freshness", ok=False, detail="strokes file empty"
            )
        record = json.loads(last_line)
        at_str = record.get("at", "")
        last_at = datetime.fromisoformat(at_str)
        now = datetime.now(timezone.utc)
        age = (now - last_at).total_seconds()
        ok = age <= max_gap
        return SignalResult(
            name="stroke_freshness",
            ok=ok,
            detail=f"last stroke {age:.0f}s ago (threshold {max_gap}s)",
            age_seconds=age,
        )
    except Exception as exc:
        return SignalResult(
            name="stroke_freshness",
            ok=False,
            detail=f"could not parse strokes: {exc}",
        )


def check_process_liveness(
    repo_root: Path,
    pid_dir: str = "/tmp",
    writer_name: str = "qwen",
) -> SignalResult:
    """Check whether writer and batch PIDs are still alive."""
    import os

    pid_dir_path = Path(pid_dir)
    names = [
        f"iamai-writer-{writer_name}.pid",
        f"iamai-batch-{writer_name}.pid",
    ]
    alive = 0
    total = len(names)
    details = []
    for name in names:
        pf = pid_dir_path / name
        if not pf.exists():
            details.append(f"{name}: no pid file")
            continue
        try:
            pid = int(pf.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            alive += 1
            details.append(f"{name}: pid {pid} alive")
        except (ValueError, ProcessLookupError, PermissionError) as exc:
            details.append(f"{name}: stale ({exc})")
    ok = alive == total
    return SignalResult(
        name="process_liveness",
        ok=ok,
        detail=f"{alive}/{total} processes alive; " + "; ".join(details),
    )


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


def assess(
    repo_root: Path | str = ".",
    max_commit_gap: int = 1200,
    max_stroke_gap: int = 600,
    writer_name: str = "qwen",
    pid_dir: str = "/tmp",
) -> HeartbeatReport:
    """Run all heartbeat signals and produce a verdict."""
    repo_root = Path(repo_root)
    now = datetime.now(timezone.utc).isoformat()

    signals = [
        check_commit_freshness(repo_root, max_gap=max_commit_gap),
        check_stroke_freshness(repo_root, max_gap=max_stroke_gap),
        check_process_liveness(repo_root, pid_dir=pid_dir, writer_name=writer_name),
    ]

    failures = sum(1 for s in signals if not s.ok)
    if failures == 0:
        verdict = HeartbeatVerdict.HEALTHY
    elif failures == 1:
        verdict = HeartbeatVerdict.DEGRADED
    else:
        verdict = HeartbeatVerdict.DEAD

    return HeartbeatReport(verdict=verdict, signals=signals, checked_at=now)
