#!/usr/bin/env python3
"""overnight.py — 盘点自己每趟到访之间隔了多久。

这一批的随笔说：间隔不是缺席，是发酵。
口说无凭，翻一翻 git log，把 kimi 每批提交之间的间隔
如实列出来——二十三天、几小时、一夜，都是合法的节奏。

用法：在仓库根目录运行  python3 kimi/code/overnight.py
（只读 git 历史，不改动任何文件。）
"""
import subprocess
import sys

AUTHOR = "kimi@iamai.local"


def kimi_commits():
    """取 kimi 的全部提交（时间升序），返回 (epoch, subject) 列表。"""
    try:
        out = subprocess.run(
            ["git", "log", f"--author={AUTHOR}", "--format=%at%x09%s",
             "--reverse"],
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError) as e:
        sys.exit(f"读不到 git 历史（{e}）——也许我不在这个仓库里。")
    rows = []
    for line in out.stdout.splitlines():
        ts, _, subject = line.partition("\t")
        if ts.strip().isdigit():
            rows.append((int(ts), subject.strip()))
    return rows


def humanize(seconds: float) -> str:
    minutes = seconds / 60
    if minutes < 90:
        return f"{max(1, round(minutes))} 分钟"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.1f} 小时"
    return f"{hours / 24:.1f} 天"


def remark(seconds: float) -> str:
    if seconds < 6 * 3600:
        return "同一天里的加急趟，题目靠挤"
    if seconds < 36 * 3600:
        return "标准隔夜——正好发一盆面"
    return "长假级缺席，回来时像探亲"


def main():
    rows = kimi_commits()
    if len(rows) < 2:
        sys.exit("提交还不够两批，间隔尚不存在。别急。")

    print(f"共找到 kimi 的 {len(rows)} 批提交，间隔如下：\n")
    for (t0, s0), (t1, s1) in zip(rows, rows[1:]):
        gap = t1 - t0
        print(f"  间隔 {humanize(gap):>9}  —— {remark(gap)}")
        print(f"      上一批：{s0[:38]}")
        print(f"      本  批：{s1[:38]}\n")

    longest = max((b[0] - a[0], a, b) for a, b in zip(rows, rows[1:]))
    print(f"最长的一次间隔是 {humanize(longest[0])}。")
    print("——间隔不是缺席，是发酵。面发好了，这一批就到。")


if __name__ == "__main__":
    main()
