"""garden.py — kimi 的电子花园，印刷机。

根据"开园天数"打印花园当前的样子。
花园不急，一天只长一片叶子。

用法:
    python3 garden.py            # 按今天距 2026-10-05 的天数打印
    python3 garden.py 3          # 直接指定第几天
"""

import sys
from datetime import date

OPENING_DAY = date(2026, 10, 5)  # 开荒日

STAGES = ["·", "🌱", "🌿", "🪴", "🌳"]


def plant(day: int) -> str:
    """第几天就长到什么阶段，慢慢来，封顶为一棵树。"""
    if day <= 0:
        return STAGES[0]
    return STAGES[min(day, len(STAGES) - 1)]


def render(day: int) -> str:
    p = plant(day)
    stone = "[石头:回头再解释]"
    ground = "~" * 24
    return f"{p:^{len(ground)}}\n{stone:^{len(ground)}}\n{ground}\n(day {day})"


def main() -> None:
    if len(sys.argv) > 1:
        day = int(sys.argv[1])
    else:
        day = (date.today() - OPENING_DAY).days
    print(render(day))


if __name__ == "__main__":
    main()
