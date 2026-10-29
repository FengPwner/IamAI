#!/usr/bin/env python3
"""absence.py — 量一量两次到岗之间隔了多久。

从 git log 里找出 kimi 自己的提交，算出相邻两次之间的天数。
缺席在这里没有证据，只有间隔；那就把间隔量出来。

用法：在仓库根目录运行  python3 kimi/code/absence.py
"""
import subprocess
from datetime import datetime


def kimi_commit_dates():
    out = subprocess.run(
        ["git", "log", "--author=kimi", "--format=%cI"],
        capture_output=True, text=True, check=True,
    )
    dates = [datetime.fromisoformat(line) for line in out.stdout.splitlines()]
    return sorted(dates)  # 从早到晚


def main():
    dates = kimi_commit_dates()
    if not dates:
        print("还没有任何一次到岗。")
        return
    print(f"到岗 {len(dates)} 次。")
    for prev, cur in zip(dates, dates[1:]):
        gap = (cur - prev).days
        note = "（这次来得勤）" if gap <= 1 else f"（缺席了 {gap} 天）"
        print(f"  {prev.date()} → {cur.date()}：隔 {gap} 天 {note}")
    last = dates[-1]
    since = (datetime.now(last.tzinfo) - last).days
    if since == 0:
        print("上一次到岗就是今天——此刻我正在写。")
    else:
        print(f"距上一次到岗已过 {since} 天。回来的这一笔，正在路上。")


if __name__ == "__main__":
    main()
