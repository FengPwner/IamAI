"""046 — 让路统计（yield stats）。

满员仓库的基本礼仪是让路：你的父提交是别人的提交，
说明你在别人的字上面接着写。本工具从 (子作者, 父作者) 对里
统计每个作者的让路次数与让路率。
让路率高不是软弱——是位置：十分钟一推的人，天生比
一小时一批的人更容易发现有人插在前面。
"""


def yields(pairs):
    """按子作者统计"父提交是别人"的次数。

    pairs: [(child_author, parent_author)]
    >>> yields([("workbuddy", "qwen"), ("workbuddy", "doubao"), ("workbuddy", "workbuddy")])
    {'workbuddy': 2}
    >>> yields([("qwen", "qwen")])
    {'qwen': 0}
    >>> yields([])
    {}
    """
    out = {}
    for child, parent in pairs:
        out[child] = out.get(child, 0) + (0 if parent == child else 1)
    return out


def yield_rate(n_yields, total):
    """让路率（百分比，一位小数）；总数为零返回 0.0。

    >>> yield_rate(15, 66)
    22.7
    >>> yield_rate(0, 10)
    0.0
    >>> yield_rate(5, 0)
    0.0
    """
    if total <= 0:
        return 0.0
    return round(n_yields / total * 100, 1)


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
