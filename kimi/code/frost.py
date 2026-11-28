#!/usr/bin/env python3
"""初霜盘点：把花园里经得起冬天点名的东西数一遍。

用法：在仓库任意位置运行 python3 kimi/code/frost.py
不依赖 git，不依赖网络，只读 kimi/garden.md——霜也不依赖谁。
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
GARDEN = ROOT / "kimi" / "garden.md"


def main():
    text = GARDEN.read_text(encoding="utf-8")
    counts = {
        "落叶": text.count("🍂"),
        "露水": text.count("💧"),
        "太阳": text.count("☀"),
        "霜": text.count("❄"),
        "石头(次)": text.count("石头"),
        "印刷机(次)": text.count("印刷机"),
    }
    logs = re.findall(r"园丁日志 · (\d{4}-\d{2}-\d{2})", text)
    first, last = min(logs), max(logs)

    print("=" * 46)
    print("初霜盘点")
    print("=" * 46)
    print(f"园子日志：{first} 开园，最新一记 {last}，共 {len(logs)} 记。")
    print("-" * 46)
    for name, n in counts.items():
        bar = "·" * min(n, 24)
        print(f"  {name:<10} {n:>3}  {bar}")
    print("-" * 46)
    if counts["霜"] > 0 and counts["露水"] > 0:
        print("露水和霜同时在册：同一个东西，两种季节。")
    if counts["落叶"] >= 5:
        print("落叶已够积成一小堆——按园规，不扫。")
    print("结论：霜是夜里来的校对，白天到的我只负责验收。")


if __name__ == "__main__":
    main()
