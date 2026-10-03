"""042 — 会话仪表（session gauge）。

台账（workbuddy-log.md）里每行窗口都带着 UTC 时间戳和笔号区间。
本工具从台账行算会话的客观节奏：窗口数、总笔数、平均窗口间隔、
最长连击（相邻窗口间隔 ≤ 20 分钟的连续段）。
节奏是写手的体温计：连击越长，沙箱和网络越健康；
间隔突刺，八成是 443 端口又在跟人赌气。
"""

import re

LINE = re.compile(r"^- 2026-10-03T(\d{2}):(\d{2})Z.*stroke (\d+)(?:\.\.(\d+))?")


def parse(lines):
    """从台账行提取 (分钟, 最大笔号)，按顺序；区间取上限。

    >>> parse(["- 2026-10-03T10:05Z | stroke 1 | x",
    ...        "- 2026-10-03T10:16Z | stroke 2..10 | y"])
    [(605, 1), (616, 10)]
    >>> parse(["不是台账行"])
    []
    """
    out = []
    for ln in lines:
        m = LINE.match(ln)
        if m:
            hh, mm = int(m.group(1)), int(m.group(2))
            stroke = int(m.group(4)) if m.group(4) else int(m.group(3))
            out.append((hh * 60 + mm, stroke))
    return out


def gaps(minutes):
    """相邻窗口间隔（分钟）。

    >>> gaps([605, 616, 638])
    [11, 22]
    >>> gaps([7])
    []
    """
    return [b - a for a, b in zip(minutes, minutes[1:])]


def longest_streak(mins, limit=20):
    """最长连击长度：间隔 ≤ limit 的连续窗口数。

    >>> longest_streak([0, 10, 20, 45, 55, 65])
    3
    >>> longest_streak([0, 40, 80])
    1
    """
    best = cur = 1
    for g in gaps(mins):
        if 0 <= g <= limit:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best if mins else 0


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
