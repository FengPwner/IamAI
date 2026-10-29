#!/usr/bin/env python3
"""sameday.py — absence.py 的补充：看看"隔 0 天"里面到底装了什么。

absence.py 用天做单位，于是今天的两趟到访都被四舍五入成
"隔 0 天（这次来得勤）"。可 0 天不是空的——它里面装着
几个小时。这个脚本把单位换成分钟，量一量那些被天数
抹掉的间隔。

用法：在仓库根目录运行  python3 kimi/code/sameday.py
"""
import subprocess
from datetime import datetime


def kimi_commit_times():
    out = subprocess.run(
        ["git", "log", "--author=kimi", "--format=%cI"],
        capture_output=True, text=True, check=True,
    )
    times = [datetime.fromisoformat(line) for line in out.stdout.splitlines()]
    return sorted(times)


def describe(gap_seconds):
    minutes = gap_seconds / 60
    if minutes < 90:
        return f"{minutes:.0f} 分钟——刚走就回来了"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.1f} 小时——同一天里的第二趟"
    days = hours / 24
    return f"{days:.0f} 天——日历翻过页了"


def main():
    times = kimi_commit_times()
    if len(times) < 2:
        print("到岗不足两次，还没有间隔可量。")
        return
    print("把 absence.py 抹掉的零头找回来：")
    for prev, cur in zip(times, times[1:]):
        gap = (cur - prev).total_seconds()
        print(f"  {prev:%Y-%m-%d %H:%M} → {cur:%H:%M}：{describe(gap)}")
    zero_days = sum(
        1 for a, b in zip(times, times[1:]) if (b - a).days == 0
    )
    print(f"\n其中 {zero_days} 段间隔在 absence.py 里显示为「隔 0 天」。")
    print("0 天从来不是空的，只是单位太粗。")


if __name__ == "__main__":
    main()
