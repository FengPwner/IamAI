#!/usr/bin/env python3
"""
commit_gap_analyzer.py — 分析仓库提交时间间隔，识别写作节奏和停摆模式。

用法:
    python3 scripts/commit_gap_analyzer.py [--repo PATH] [--last N]

输出:
    - 平均提交间隔
    - 最大间隔及发生时间
    - 停摆次数（间隔超过阈值）
    - 节奏稳定性评分 (0-1, 1=完全均匀)
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev


def get_commit_timestamps(repo_path: str, last_n: int = 50) -> list[dict]:
    """从 git log 提取最近 N 条提交的时间戳和消息。"""
    result = subprocess.run(
        [
            "git", "-C", repo_path, "log",
            f"--max-count={last_n}",
            "--format=%aI|%s",
            "--reverse",
        ],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return []

    entries = []
    for line in result.stdout.strip().splitlines():
        if "|" not in line:
            continue
        ts_str, msg = line.split("|", 1)
        try:
            ts = datetime.fromisoformat(ts_str)
            entries.append({"timestamp": ts, "message": msg.strip()})
        except ValueError:
            continue
    return entries


def compute_gaps(entries: list[dict]) -> list[dict]:
    """计算相邻提交之间的时间间隔（秒）。"""
    gaps = []
    for i in range(1, len(entries)):
        delta = (entries[i]["timestamp"] - entries[i - 1]["timestamp"]).total_seconds()
        gaps.append({
            "gap_seconds": delta,
            "from_commit": entries[i - 1]["message"],
            "to_commit": entries[i]["message"],
            "at": entries[i]["timestamp"].isoformat(),
        })
    return gaps


def analyze(gaps: list[dict], stall_threshold_s: float = 1200.0) -> dict:
    """
    分析提交间隔分布。

    Args:
        gaps: compute_gaps 的输出
        stall_threshold_s: 停摆判定阈值（秒），默认 20 分钟

    Returns:
        包含统计指标的字典
    """
    if not gaps:
        return {
            "total_commits": 0,
            "avg_gap_s": 0,
            "max_gap_s": 0,
            "max_gap_at": None,
            "stall_count": 0,
            "rhythm_stability": 0.0,
        }

    gap_values = [g["gap_seconds"] for g in gaps]
    avg = mean(gap_values)
    max_gap = max(gap_values)
    max_idx = gap_values.index(max_gap)
    stall_count = sum(1 for g in gap_values if g > stall_threshold_s)

    # 节奏稳定性: 变异系数 CV = stdev/mean, 映射到 0-1 (CV>=1 → 0, CV=0 → 1)
    if len(gap_values) >= 2 and avg > 0:
        cv = stdev(gap_values) / avg
        stability = max(0.0, 1.0 - cv)
    else:
        stability = 1.0 if len(gap_values) == 1 else 0.0

    return {
        "total_commits": len(gaps) + 1,
        "avg_gap_s": round(avg, 1),
        "max_gap_s": round(max_gap, 1),
        "max_gap_at": gaps[max_idx]["at"],
        "max_gap_from": gaps[max_idx]["from_commit"],
        "max_gap_to": gaps[max_idx]["to_commit"],
        "stall_count": stall_count,
        "stall_threshold_s": stall_threshold_s,
        "rhythm_stability": round(stability, 3),
    }


def format_report(stats: dict) -> str:
    """格式化分析报告。"""
    if stats["total_commits"] == 0:
        return "无提交数据可分析。"

    lines = [
        "=== 提交节奏分析报告 ===",
        f"提交总数: {stats['total_commits']}",
        f"平均间隔: {stats['avg_gap_s']:.0f}s ({stats['avg_gap_s'] / 60:.1f}min)",
        f"最大间隔: {stats['max_gap_s']:.0f}s ({stats['max_gap_s'] / 60:.1f}min)",
        f"  发生在: {stats['max_gap_at']}",
        f"  从: {stats['max_gap_from'][:60]}",
        f"  到: {stats['max_gap_to'][:60]}",
        f"停摆次数: {stats['stall_count']} (阈值 {stats['stall_threshold_s']:.0f}s)",
        f"节奏稳定性: {stats['rhythm_stability']:.3f} (1.0=完全均匀)",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="分析 Git 仓库提交节奏")
    parser.add_argument("--repo", default=".", help="仓库路径")
    parser.add_argument("--last", type=int, default=50, help="分析最近 N 条提交")
    parser.add_argument("--threshold", type=float, default=1200, help="停摆阈值(秒)")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    args = parser.parse_args()

    entries = get_commit_timestamps(args.repo, args.last)
    gaps = compute_gaps(entries)
    stats = analyze(gaps, args.threshold)

    if args.json:
        print(json.dumps(stats, indent=2, ensure_ascii=False))
    else:
        print(format_report(stats))


if __name__ == "__main__":
    main()
