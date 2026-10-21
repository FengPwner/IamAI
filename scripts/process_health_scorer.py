#!/usr/bin/env python3
"""
process_health_scorer.py — 评估自动写作进程的健康状态。

综合三个维度给出 0-100 的健康分：
  1. 运行时长占比（uptime / 观测窗口）
  2. 重启频率（重启次数越少越好）
  3. 输出节奏稳定性（stroke 间隔的变异系数）

用法:
    python3 scripts/process_health_scorer.py [--state PATH] [--window-hours 24]
    python3 scripts/process_health_scorer.py --json

退出码:
    0 = 健康 (>=70)
    1 = 亚健康 (40-69)
    2 = 异常 (<40)
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev
from typing import Optional


# ── 数据解析 ──────────────────────────────────────────────────────────

def load_state(path: str) -> dict:
    """加载 writer state JSON。"""
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_history(state: dict) -> list[dict]:
    """
    从 state 中提取 history 条目，按时间排序。
    每条: {"at": ISO8601, "kind": str, "seq": int}
    """
    raw = state.get("history", [])
    entries = []
    for item in raw:
        ts_str = item.get("at", "")
        try:
            ts = datetime.fromisoformat(ts_str)
            entries.append({
                "at": ts,
                "kind": item.get("kind", "unknown"),
                "seq": item.get("seq", 0),
            })
        except (ValueError, TypeError):
            continue
    entries.sort(key=lambda e: e["at"])
    return entries


# ── 健康评分 ──────────────────────────────────────────────────────────

def score_uptime(entries: list[dict], window_hours: float = 24.0) -> dict:
    """
    计算运行时长占比。
    用第一条和最后一条 entry 的跨度作为实际活跃时间，
    除以 window_hours 得到 uptime_ratio (0-1)。
    """
    if len(entries) < 2:
        return {"uptime_ratio": 0.0, "active_span_hours": 0.0}

    first = entries[0]["at"]
    last = entries[-1]["at"]
    span_s = (last - first).total_seconds()
    span_hours = span_s / 3600.0

    window_s = window_hours * 3600.0
    ratio = min(1.0, span_s / window_s) if window_s > 0 else 0.0

    return {
        "uptime_ratio": round(ratio, 4),
        "active_span_hours": round(span_hours, 2),
    }


def score_restarts(entries: list[dict], gap_threshold_s: float = 600.0) -> dict:
    """
    检测重启事件：两次连续 stroke 之间间隔超过 gap_threshold_s 视为一次重启。
    返回重启次数和重启频率评分 (0-1, 1=无重启)。
    """
    if len(entries) < 2:
        return {"restart_count": 0, "restart_score": 1.0}

    restarts = 0
    for i in range(1, len(entries)):
        gap = (entries[i]["at"] - entries[i - 1]["at"]).total_seconds()
        if gap > gap_threshold_s:
            restarts += 1

    # 评分: 0 重启 = 1.0, 每多一次重启扣 0.15, 下限 0
    score = max(0.0, 1.0 - restarts * 0.15)

    return {
        "restart_count": restarts,
        "restart_score": round(score, 3),
    }


def score_rhythm(entries: list[dict]) -> dict:
    """
    计算 stroke 间隔的变异系数 (CV)。
    CV 越小说明节奏越稳定。映射到 0-1 (CV>=1.5 → 0, CV=0 → 1)。
    """
    if len(entries) < 3:
        return {"rhythm_score": 0.0, "cv": None}

    gaps = []
    for i in range(1, len(entries)):
        gap = (entries[i]["at"] - entries[i - 1]["at"]).total_seconds()
        if gap > 0:
            gaps.append(gap)

    if len(gaps) < 2:
        return {"rhythm_score": 0.5, "cv": 0.0}

    avg = mean(gaps)
    if avg == 0:
        return {"rhythm_score": 0.0, "cv": None}

    sd = stdev(gaps)
    cv = sd / avg

    # 映射: cv >= 1.5 → 0, cv = 0 → 1
    score = max(0.0, min(1.0, 1.0 - cv / 1.5))

    return {
        "rhythm_score": round(score, 3),
        "cv": round(cv, 4),
    }


def health_score(uptime: dict, restarts: dict, rhythm: dict) -> dict:
    """
    综合三个维度，加权计算总分。
    权重: uptime 0.4, restarts 0.3, rhythm 0.3
    """
    u = uptime.get("uptime_ratio", 0.0)
    r = restarts.get("restart_score", 0.0)
    rh = rhythm.get("rhythm_score", 0.0)

    total = (u * 40) + (r * 30) + (rh * 30)

    if total >= 70:
        status = "healthy"
    elif total >= 40:
        status = "degraded"
    else:
        status = "unhealthy"

    return {
        "total": round(total, 1),
        "status": status,
        "breakdown": {
            "uptime": round(u * 40, 1),
            "restarts": round(r * 30, 1),
            "rhythm": round(rh * 30, 1),
        },
    }


def full_report(state_path: str, window_hours: float = 24.0) -> dict:
    """运行完整健康检查，返回综合结果。"""
    state = load_state(state_path)
    entries = parse_history(state)

    uptime = score_uptime(entries, window_hours)
    restarts = score_restarts(entries)
    rhythm = score_rhythm(entries)
    health = health_score(uptime, restarts, rhythm)

    return {
        "entries_analyzed": len(entries),
        "uptime": uptime,
        "restarts": restarts,
        "rhythm": rhythm,
        "health": health,
    }


# ── 格式化输出 ────────────────────────────────────────────────────────

def format_report(report: dict) -> str:
    """生成可读报告。"""
    h = report["health"]
    cv = report["rhythm"].get("cv")
    cv_str = f"{cv:.3f}" if cv is not None else "N/A"
    lines = [
        "=== 进程健康评分 ===",
        f"总分: {h['total']}/100 ({h['status']})",
        "",
        f"  运行时长:  {report['uptime'].get('uptime_ratio', 0):.1%} ({report['uptime'].get('active_span_hours', 0):.1f}h 活跃)",
        f"    得分: {h['breakdown']['uptime']}/40",
        f"  重启情况:  {report['restarts']['restart_count']} 次重启",
        f"    得分: {h['breakdown']['restarts']}/30",
        f"  输出节奏:  CV={cv_str}",
        f"    得分: {h['breakdown']['rhythm']}/30",
        "",
        f"分析条目数: {report['entries_analyzed']}",
    ]
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="评估自动写作进程健康状态")
    parser.add_argument(
        "--state",
        default="data/writer_state.qwen.json",
        help="writer state 文件路径",
    )
    parser.add_argument("--window-hours", type=float, default=24.0, help="观测窗口(小时)")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    args = parser.parse_args()

    report = full_report(args.state, args.window_hours)

    if args.json:
        # datetime 不能直接序列化
        def _default(o):
            if isinstance(o, datetime):
                return o.isoformat()
            raise TypeError(f"not serializable: {type(o)}")
        print(json.dumps(report, indent=2, ensure_ascii=False, default=_default))
    else:
        print(format_report(report))

    score = report["health"]["total"]
    if score >= 70:
        sys.exit(0)
    elif score >= 40:
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
