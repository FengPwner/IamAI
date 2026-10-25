"""workbuddy stroke 40 · batch_parse （自带 doctest，可独立运行）。

仓库一半的提交标题是打包清单："batch: dnote x12, dpoem x6 (58 min)"。
把标题解析成数字，git log 就变成一台统计机器——
哪个写手在涨、什么种类最多、批了多久，全部可测。
"""

import re

_HEAD = re.compile(r"^batch:\s*(?P<body>.*?)\s*\((?P<minutes>\d+)\s*min\)\s*$")


def batch_parse(title: str):
    """Parse a batch title into (kinds dict, minutes). None if not a batch.

    >>> batch_parse("batch: dnote x12, dpoem x6, dthought x6 (58 min)")
    ({'dnote': 12, 'dpoem': 6, 'dthought': 6}, 58)
    >>> batch_parse("batch: thought x3 (10 min)")
    ({'thought': 3}, 10)
    >>> batch_parse("workbuddy: handover page (window 13)") is None
    True
    """
    m = _HEAD.match(title.strip())
    if not m:
        return None
    kinds = {}
    for part in m.group("body").split(","):
        part = part.strip()
        if not part:
            continue
        kind, _, count = part.rpartition(" x")
        if kind and count.isdigit():
            kinds[kind] = int(count)
    return (kinds, int(m.group("minutes")))


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
