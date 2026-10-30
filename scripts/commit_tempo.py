#!/usr/bin/env python3
"""
commit_tempo.py — 用音乐节拍标记显示仓库提交节奏。

将提交间隔分类为：
  presto  (≥30/h)  — 狂飙
  allegro (10–29/h) — 活跃
  andante (3–9/h)  — 稳步
  adagio  (1–2/h)  — 缓慢
  largo   (<1/h)   — 停滞

并检测节奏趋势（加速 / 稳定 / 衰减）。

用法:
    python3 scripts/commit_tempo.py [--repo PATH] [--count N]
    python3 scripts/commit_tempo.py --json
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iamai.commit_tempo import classify_tempo, tempo_trend, tempo_summary_line


def get_commit_intervals(repo_path: str, count: int = 30) -> list[float]:
    """从 git log 提取最近 N 次提交的间隔秒数（最旧→最新）。"""
    result = subprocess.run(
        ["git", "-C", repo_path, "log", f"-{count + 1}", "--format=%aI"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return []
    lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        return []
    timestamps = []
    for l in reversed(lines):
        try:
            timestamps.append(datetime.fromisoformat(l))
        except ValueError:
            continue
    intervals = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
        if delta > 0:
            intervals.append(delta)
    return intervals


def main():
    parser = argparse.ArgumentParser(description="Commit tempo classifier")
    parser.add_argument("--repo", default=".", help="Path to git repo")
    parser.add_argument("--count", type=int, default=30, help="Number of recent commits")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    repo_path = str(Path(args.repo).resolve())
    intervals = get_commit_intervals(repo_path, args.count)

    if not intervals:
        print("tempo: largo — no commit data available")
        sys.exit(2)

    tempo = classify_tempo(intervals)
    trend = tempo_trend(intervals)

    if args.json:
        trend["tempo"] = tempo
        trend["interval_count"] = len(intervals)
        print(json.dumps(trend, indent=2))
    else:
        print(tempo_summary_line(intervals))

    # exit codes: 0=healthy (allegro+), 1=warning (andante), 2=critical (adagio/largo)
    if tempo in ("presto", "allegro"):
        sys.exit(0)
    elif tempo == "andante":
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
