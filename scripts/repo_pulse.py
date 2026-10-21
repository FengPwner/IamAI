#!/usr/bin/env python3
"""
repo_pulse.py — 一秒读懂仓库健康状态的脉搏指标。

将四个维度压缩成 0-100 的 pulse 分数：
  1. commit_freshness  — 最新提交距今多久（越新鲜越好）
  2. backlog_pressure  — 未提交文件数（越少越好）
  3. process_liveness  — writer/batch 进程是否存活
  4. rhythm_stability  — 提交间隔变异系数（越稳定越好）

用法:
    python3 scripts/repo_pulse.py [--repo PATH] [--state PATH]
    python3 scripts/repo_pulse.py --json

退出码:
    0 = 健康 (>=70)
    1 = 亚健康 (40-69)
    2 = 异常 (<40)
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev
from typing import Optional


# ── 数据采集 ──────────────────────────────────────────────────────────

def get_last_commit_age(repo_path: str) -> Optional[float]:
    """返回最近一次提交距今的秒数，失败返回 None。"""
    result = subprocess.run(
        ["git", "-C", repo_path, "log", "-1", "--format=%aI"],
        capture_output=True, text=True, timeout=5,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        ts = datetime.fromisoformat(result.stdout.strip())
        now = datetime.now(timezone.utc)
        return (now - ts).total_seconds()
    except ValueError:
        return None


def count_uncommitted(repo_path: str) -> int:
    """返回未提交（含暂存）的文件数。"""
    result = subprocess.run(
        ["git", "-C", repo_path, "status", "--porcelain"],
        capture_output=True, text=True, timeout=5,
    )
    if result.returncode != 0:
        return -1
    lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
    return len(lines)


def check_processes(writer_name: str = "qwen") -> dict:
    """检测 writer 和 batch 进程是否存活。"""
    writer_alive = False
    batch_alive = False
    try:
        result = subprocess.run(
            ["pgrep", "-af", f"writer_loop.*{writer_name}"],
            capture_output=True, text=True, timeout=3,
        )
        writer_alive = result.returncode == 0
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["pgrep", "-af", f"commit_batch.*{writer_name}"],
            capture_output=True, text=True, timeout=3,
        )
        batch_alive = result.returncode == 0
    except Exception:
        pass
    return {"writer": writer_alive, "batch": batch_alive}


def get_recent_commit_gaps(repo_path: str, last_n: int = 20) -> list[float]:
    """取最近 N 条提交的间隔秒数列表。"""
    result = subprocess.run(
        ["git", "-C", repo_path, "log", f"--max-count={last_n}",
         "--format=%aI", "--reverse"],
        capture_output=True, text=True, timeout=5,
    )
    if result.returncode != 0:
        return []
    timestamps = []
    for line in result.stdout.strip().splitlines():
        try:
            timestamps.append(datetime.fromisoformat(line.strip()))
        except ValueError:
            continue
    gaps = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]).total_seconds()
        if delta >= 0:
            gaps.append(delta)
    return gaps


# ── 评分函数 ──────────────────────────────────────────────────────────

def score_freshness(age_seconds: Optional[float], target_s: float = 600.0) -> float:
    """
    提交新鲜度评分 0-100。
    target_s 秒内提交 → 100 分；超过 target_s 线性衰减到 0。
    """
    if age_seconds is None:
        return 0.0
    if age_seconds <= 0:
        return 100.0
    # 超过 3 倍 target 就 0 分
    ceiling = target_s * 3.0
    if age_seconds >= ceiling:
        return 0.0
    return max(0.0, 100.0 * (1.0 - age_seconds / ceiling))


def score_backlog(uncommitted_count: int, threshold: int = 10) -> float:
    """
    积压评分 0-100。
    0 个未提交 → 100；>= threshold 个 → 0。
    """
    if uncommitted_count < 0:
        return 0.0  # 无法检测视为最差
    if uncommitted_count == 0:
        return 100.0
    if uncommitted_count >= threshold:
        return 0.0
    return max(0.0, 100.0 * (1.0 - uncommitted_count / threshold))


def score_liveness(process_info: dict) -> float:
    """
    进程存活评分 0-100。
    writer + batch 都活 → 100；只活一个 → 50；都死 → 0。
    """
    alive_count = sum([
        process_info.get("writer", False),
        process_info.get("batch", False),
    ])
    return alive_count * 50.0


def score_rhythm(gaps: list[float]) -> float:
    """
    节奏稳定性评分 0-100。
    CV (变异系数) = stdev/mean, 映射到 0-100 (CV>=1.5 → 0, CV=0 → 100)。
    """
    if len(gaps) < 2:
        return 50.0  # 数据不足给中间分
    avg = mean(gaps)
    if avg <= 0:
        return 0.0
    cv = stdev(gaps) / avg
    return max(0.0, 100.0 * (1.0 - cv / 1.5))


# ── 综合脉搏 ──────────────────────────────────────────────────────────

WEIGHTS = {
    "freshness": 0.30,
    "backlog": 0.25,
    "liveness": 0.25,
    "rhythm": 0.20,
}


def compute_pulse(
    freshness: float,
    backlog: float,
    liveness: float,
    rhythm: float,
) -> dict:
    """加权求和得到总分及分类。"""
    total = (
        WEIGHTS["freshness"] * freshness
        + WEIGHTS["backlog"] * backlog
        + WEIGHTS["liveness"] * liveness
        + WEIGHTS["rhythm"] * rhythm
    )
    total = round(max(0.0, min(100.0, total)), 1)

    if total >= 70:
        label = "healthy"
    elif total >= 40:
        label = "degraded"
    else:
        label = "critical"

    return {
        "pulse": total,
        "label": label,
        "scores": {
            "freshness": round(freshness, 1),
            "backlog": round(backlog, 1),
            "liveness": round(liveness, 1),
            "rhythm": round(rhythm, 1),
        },
    }


def format_pulse(result: dict) -> str:
    """单行可读格式。"""
    s = result["scores"]
    icon = {"healthy": "●", "degraded": "◐", "critical": "○"}.get(result["label"], "?")
    return (
        f"{icon} pulse {result['pulse']}/100 [{result['label']}]  "
        f"fresh={s['freshness']} backlog={s['backlog']} "
        f"live={s['liveness']} rhythm={s['rhythm']}"
    )


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="仓库脉搏一键检测")
    parser.add_argument("--repo", default=".", help="仓库路径")
    parser.add_argument("--state", default="", help="writer state JSON 路径（可选）")
    parser.add_argument("--writer", default="qwen", help="writer 名称")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    args = parser.parse_args()

    age = get_last_commit_age(args.repo)
    uncommitted = count_uncommitted(args.repo)
    procs = check_processes(args.writer)
    gaps = get_recent_commit_gaps(args.repo)

    f = score_freshness(age)
    b = score_backlog(uncommitted)
    lv = score_liveness(procs)
    r = score_rhythm(gaps)

    result = compute_pulse(f, b, lv, r)
    result["raw"] = {
        "last_commit_age_s": round(age, 1) if age is not None else None,
        "uncommitted_files": uncommitted,
        "processes": procs,
        "recent_gaps_count": len(gaps),
    }

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_pulse(result))

    # 退出码
    if result["label"] == "healthy":
        sys.exit(0)
    elif result["label"] == "degraded":
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
