#!/usr/bin/env python3
"""zombie_detector.py — detect processes that are alive but not making progress.

A zombie process is technically running (has a PID, responds to signal 0)
but has not produced any observable output in longer than expected. This
is distinct from a dead process: the PID exists, the process exists, but
work has stopped.

Three detection signals:

1. **stale_output** — the output file the process should be writing to
   has not been modified within the expected interval.
2. **cpu_starvation** — the process has accumulated near-zero CPU time
   relative to its wall-clock uptime (stuck in sleep/wait).
3. **memory_frozen** — the process RSS has not changed across multiple
   samples (suggesting no allocation activity).

Each signal alone is a warning. Two or more together are a diagnosis.

Usage:
    python3 tools/zombie_detector.py --pid 4747 --output data/strokes.jsonl \\
        --interval 15 --samples 3

Exit codes:
    0  process is alive and making progress
    1  process is a zombie (alive but stalled)
    2  process is dead
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class ZombieSignal:
    """A single detection signal."""
    name: str
    triggered: bool
    value: float
    threshold: float
    detail: str

    @property
    def severity(self) -> str:
        if not self.triggered:
            return "clear"
        ratio = self.value / self.threshold if self.threshold > 0 else float("inf")
        if ratio > 3.0:
            return "critical"
        if ratio > 1.5:
            return "warning"
        return "marginal"


@dataclass
class ZombieReport:
    """Full zombie detection report for one process."""
    pid: int
    alive: bool
    signals: List[ZombieSignal] = field(default_factory=list)
    sample_count: int = 0
    elapsed_seconds: float = 0.0

    @property
    def triggered_count(self) -> int:
        return sum(1 for s in self.signals if s.triggered)

    @property
    def verdict(self) -> str:
        if not self.alive:
            return "dead"
        if self.triggered_count >= 2:
            return "zombie"
        if self.triggered_count == 1:
            return "degraded"
        return "healthy"

    @property
    def exit_code(self) -> int:
        v = self.verdict
        if v == "dead":
            return 2
        if v == "zombie":
            return 1
        return 0


def _is_alive(pid: int) -> bool:
    """Check if a process exists by sending signal 0."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # PermissionError means the process exists but we lack permission
        return True


def _file_age_seconds(path: str) -> Optional[float]:
    """How long since a file was last modified. None if file missing."""
    try:
        return time.time() - os.path.getmtime(path)
    except OSError:
        return None


def _process_cpu_seconds(pid: int) -> Optional[float]:
    """Total CPU time consumed by a process (user + system)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().split()
        utime = int(stat[13])
        stime = int(stat[14])
        ticks = os.sysconf("SC_CLK_TCK")
        return (utime + stime) / ticks
    except (OSError, IndexError, ValueError):
        return None


def _process_uptime_seconds(pid: int) -> Optional[float]:
    """Wall-clock seconds since the process started."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().split()
        starttime_ticks = int(stat[21])
        ticks = os.sysconf("SC_CLK_TCK")
        boot_time = float(Path("/proc/stat").read_text().split("\n")[0].split()[1])
        # starttime is relative to boot; we need wall clock
        # simpler: use /proc/{pid}/stat mtime approximation
        proc_mtime = os.path.getmtime(f"/proc/{pid}")
        return time.time() - proc_mtime
    except (OSError, IndexError, ValueError):
        return None


def _process_rss_kb(pid: int) -> Optional[int]:
    """Resident set size in KB."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().split()
        pages = int(stat[23])
        page_kb = os.sysconf("SC_PAGE_SIZE") // 1024
        return pages * page_kb
    except (OSError, IndexError, ValueError):
        return None


def check_stale_output(
    output_path: str,
    expected_interval: float,
    multiplier: float = 4.0,
) -> ZombieSignal:
    """Signal: output file has not been updated within expected_interval * multiplier."""
    age = _file_age_seconds(output_path)
    threshold = expected_interval * multiplier
    if age is None:
        return ZombieSignal(
            name="stale_output",
            triggered=True,
            value=float("inf"),
            threshold=threshold,
            detail=f"output file {output_path} does not exist",
        )
    return ZombieSignal(
        name="stale_output",
        triggered=age > threshold,
        value=age,
        threshold=threshold,
        detail=f"output age {age:.0f}s, threshold {threshold:.0f}s",
    )


def check_cpu_starvation(
    pid: int,
    min_cpu_ratio: float = 0.01,
) -> ZombieSignal:
    """Signal: CPU time / wall-clock uptime is below min_cpu_ratio.

    A process stuck in uninterruptible sleep (D state) or waiting on I/O
    will show near-zero CPU despite high wall-clock time.
    """
    cpu = _process_cpu_seconds(pid)
    uptime = _process_uptime_seconds(pid)
    if cpu is None or uptime is None or uptime < 1.0:
        return ZombieSignal(
            name="cpu_starvation",
            triggered=False,
            value=0.0,
            threshold=min_cpu_ratio,
            detail="insufficient data for CPU ratio",
        )
    ratio = cpu / uptime
    return ZombieSignal(
        name="cpu_starvation",
        triggered=ratio < min_cpu_ratio,
        value=ratio,
        threshold=min_cpu_ratio,
        detail=f"cpu_ratio={ratio:.4f}, uptime={uptime:.0f}s, cpu={cpu:.2f}s",
    )


def check_memory_frozen(
    pid: int,
    samples: int = 3,
    interval: float = 1.0,
) -> ZombieSignal:
    """Signal: RSS has not changed across multiple samples.

    A process doing real work allocates and frees memory. A frozen RSS
    across several samples suggests the process is stuck.
    """
    rss_values: List[int] = []
    for _ in range(samples):
        rss = _process_rss_kb(pid)
        if rss is not None:
            rss_values.append(rss)
        if len(rss_values) < samples:
            time.sleep(interval)

    if len(rss_values) < 2:
        return ZombieSignal(
            name="memory_frozen",
            triggered=False,
            value=0.0,
            threshold=1.0,
            detail="insufficient RSS samples",
        )

    unique_count = len(set(rss_values))
    triggered = unique_count == 1  # all samples identical
    return ZombieSignal(
        name="memory_frozen",
        triggered=triggered,
        value=float(unique_count),
        threshold=2.0,
        detail=f"rss_samples={rss_values}, unique={unique_count}/{len(rss_values)}",
    )


def zombie_check(
    pid: int,
    output_path: str,
    expected_interval: float,
    samples: int = 3,
    sample_interval: float = 1.0,
    skip_memory: bool = False,
) -> ZombieReport:
    """Run all zombie detection signals against a process."""
    alive = _is_alive(pid)
    report = ZombieReport(pid=pid, alive=alive)

    if not alive:
        return report

    start = time.time()

    # Signal 1: stale output (instant)
    report.signals.append(
        check_stale_output(output_path, expected_interval)
    )

    # Signal 2: CPU starvation (instant read from /proc)
    report.signals.append(
        check_cpu_starvation(pid)
    )

    # Signal 3: memory frozen (requires sampling over time)
    if not skip_memory:
        report.signals.append(
            check_memory_frozen(pid, samples=samples, interval=sample_interval)
        )

    report.elapsed_seconds = time.time() - start
    report.sample_count = samples
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Detect zombie processes: alive but not making progress."
    )
    parser.add_argument("--pid", type=int, required=True, help="Process PID to check")
    parser.add_argument(
        "--output", type=str, required=True,
        help="Path to the output file the process should be writing to",
    )
    parser.add_argument(
        "--interval", type=float, default=15.0,
        help="Expected write interval in seconds (default: 15)",
    )
    parser.add_argument(
        "--samples", type=int, default=3,
        help="Number of RSS samples for memory check (default: 3)",
    )
    parser.add_argument(
        "--sample-interval", type=float, default=1.0,
        help="Seconds between RSS samples (default: 1.0)",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--skip-memory", action="store_true",
        help="Skip the memory frozen check (avoids waiting)",
    )
    args = parser.parse_args()

    report = zombie_check(
        pid=args.pid,
        output_path=args.output,
        expected_interval=args.interval,
        samples=args.samples,
        sample_interval=args.sample_interval,
        skip_memory=args.skip_memory,
    )

    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(f"PID {report.pid}: {report.verdict}")
        print(f"  alive: {report.alive}")
        for sig in report.signals:
            status = "TRIGGERED" if sig.triggered else "clear"
            print(f"  [{status}] {sig.name}: {sig.detail}")
        print(f"  triggered: {report.triggered_count}/{len(report.signals)}")

    sys.exit(report.exit_code)


if __name__ == "__main__":
    main()
