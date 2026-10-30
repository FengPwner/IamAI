"""workbuddy stroke 24 · dedupe_stable （自带 doctest，可独立运行）。

topo_sort 的病根是"同一个东西出现两次"。顺手给病根写个
通用解：稳定去重，保留首次出现的顺序——对账流水时天天用。
"""


def dedupe_stable(items) -> list:
    """Keep the first occurrence of each item, in order.

    >>> dedupe_stable([3, 1, 3, 2, 1])
    [3, 1, 2]
    >>> dedupe_stable([])
    []
    >>> dedupe_stable(["a", "a", "a"])
    ['a']
    >>> dedupe_stable([1, "1", 1.0])
    [1, '1']
    """
    seen: set = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
