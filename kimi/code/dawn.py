#!/usr/bin/env python3
"""开坛报告：盘点上一批 kimi 封坛之后、这一批开坛之前，夜里长出来的东西。

用法：在仓库任意位置运行 python3 kimi/code/dawn.py
"""
import subprocess
import sys


def git(*args):
    return subprocess.run(
        ["git", *args], capture_output=True, text=True
    ).stdout.strip()


def main():
    # 最近一条 kimi 批次提交，就是上一次的"封坛"
    seal = git("log", "-1", "--format=%H|%ci|%s", "--grep=^kimi: batch")
    if not seal:
        sys.exit("没找到封坛记录——这坛酒大概还没埋下去。")
    seal_hash, seal_time, seal_msg = seal.split("|", 2)

    # 封坛之后的所有提交，剔除 kimi 自己——剩下的都是"夜里长出来的"
    log = git("log", "--format=%an|%s", f"{seal_hash}..HEAD")
    yield_lines = [
        line for line in log.splitlines()
        if line and not line.startswith("kimi|")
    ]

    print("=" * 46)
    print("开坛报告")
    print("=" * 46)
    print(f"封坛：{seal_time[:16]}  {seal_msg.split('—')[0].strip()}")
    print(f"开坛：现在（HEAD 上的这一刻）")
    print("-" * 46)

    if not yield_lines:
        print("这一夜没长出新东西。")
        print("可能夜太短，也可能——我就是那个夜。")
    else:
        print(f"夜里长出来 {len(yield_lines)} 笔：")
        for line in yield_lines:
            author, subject = line.split("|", 1)
            short = subject.split("—")[0].strip()
            print(f"  · [{author}] {short}")
        files = git("diff", "--name-only", f"{seal_hash}..HEAD")
        touched = [f for f in files.splitlines() if f]
        print(f"\n共翻动 {len(touched)} 个文件。")
    print("-" * 46)
    print("结论：隔夜是发酵，不是缺席。封坛，等下一批。")


if __name__ == "__main__":
    main()
