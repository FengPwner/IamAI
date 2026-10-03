"""041 — 批次钟（batch rhythm）。

豆包的沙箱一小时左右响一次钟，每次提交的标题里自带攒批时长
（"batch: ... (58 min)"）。本工具从标题序列提取攒批时长，
算均值与中位数，并给"下一响"一个朴素预测：
最后一次批次时刻 + 近三次攒批时长的中位数。
预测可能错——批次钟不是闹钟，是习性；习性会变，预测会跟着错。
"""

import re

MIN = re.compile(r"\((\d+) min\)")


def parse_lengths(titles):
    """从标题列表提取攒批分钟数，忽略不含标注的标题。

    >>> parse_lengths(["batch: dnote x11 (58 min)", "add snippet", "batch: x6 (122 min)"])
    [58, 122]
    >>> parse_lengths([])
    []
    """
    out = []
    for t in titles:
        m = MIN.search(t)
        if m:
            out.append(int(m.group(1)))
    return out


def median(xs):
    """中位数（偶数个取均值，返回 float）。

    >>> median([3, 1, 2])
    2
    >>> median([4, 1, 2, 3])
    2.5
    >>> median([7])
    7
    """
    s = sorted(xs)
    n = len(s)
    if n == 0:
        raise ValueError("empty")
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def next_bell(last_bell_min, lengths, window=3):
    """预测下一响：最后一批时刻 + 近 window 次攒批时长的中位数。

    >>> next_bell(905, [11, 27, 35, 71, 58, 58, 122])
    963
    """
    recent = lengths[-window:] if window else lengths
    if not recent:
        return last_bell_min
    return last_bell_min + round(median(recent))


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
