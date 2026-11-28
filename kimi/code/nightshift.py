#!/usr/bin/env python3
"""夜班表：看看这个点儿，园子里是谁的班。

用法：
    python3 kimi/code/nightshift.py        # 用当前时间查岗
    python3 kimi/code/nightshift.py 22     # 查晚上十点的岗

不读网络，不读 git，只读 kimi/garden.md —— 查岗也要有边界感。
"""
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GARDEN = ROOT / "kimi" / "garden.md"

# 园子的薪酬体系：所有人的工资都是"没人催"。
SHIFTS = [
    (range(23, 28), "霜", "夜班", "批改石头，给纸加框，以肉眼不可见的速度"),
    (range(4, 6), "露水", "凌晨班", "和霜交接，把夜班的心得写成湿的"),
    (range(6, 18), "太阳", "白班", "负责让一切被看见，不负责解释"),
    (range(18, 23), "月亮", "前夜班", "值班照明，看着霜上班"),
]
ALWAYS_ON = [
    ("石头", "全天在岗", "以天为笔，从不打卡"),
    ("印刷机", "不定时", "睡够才开口，一句顶三个时态"),
    ("园丁", "不定时", "定时器说了算，经常五小时就折返"),
]


def on_shift(hour: int):
    """返回此刻在班上的那一位。"""
    h = hour % 24
    for span, name, shift, duty in SHIFTS:
        if h in [s % 24 for s in span]:
            return name, shift, duty
    return None


def main():
    if len(sys.argv) > 1:
        hour = int(sys.argv[1])
        label = f"{hour % 24:02d}:00（指定）"
    else:
        now = datetime.now()
        hour = now.hour
        label = now.strftime("%H:%M（当前）")

    print(f"查岗时间：{label}")
    who = on_shift(hour)
    if who:
        print(f"正在当班：{who[0]}（{who[1]}）—— {who[2]}")
    print("—— 以下几位永远在册 ——")
    for name, shift, duty in ALWAYS_ON:
        print(f"  {name}（{shift}）：{duty}")

    if GARDEN.exists():
        frost = GARDEN.read_text(encoding="utf-8").count("❄")
        print(f"—— 批改进度参考 ——")
        print(f"  garden.md 累计霜痕：{frost} 处。白，都是慢慢白的。")


if __name__ == "__main__":
    main()
