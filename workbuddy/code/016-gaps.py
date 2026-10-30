"""workbuddy stroke 16 · gaps （自带 doctest，可独立运行）。

commit log 是一列时间戳。这个仓库承诺的节拍是十分钟一推，
有没有兑现，把相邻间隔一算就知道——说好的十分钟，
最大不能漂到哪里去。
"""


def gaps(times) -> list[int]:
    """Seconds between consecutive pushes. Input need not be sorted — sorted first.

    >>> gaps([0, 600, 1250])
    [600, 650]
    >>> gaps([1250, 600, 0])
    [600, 650]
    >>> gaps([5])
    []
    >>> gaps([])
    []
    """
    ordered = sorted(int(t) for t in times)
    return [b - a for a, b in zip(ordered, ordered[1:])]


def max_gap(times) -> int:
    """The longest silence between consecutive pushes; 0 with fewer than two.

    >>> max_gap([0, 600, 1250])
    650
    >>> max_gap([42])
    0
    >>> max_gap([])
    0
    """
    spans = gaps(times)
    return max(spans) if spans else 0


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
