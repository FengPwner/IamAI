"""workbuddy stroke 43 · histogram （自带 doctest，可独立运行）。

给"每小时提交数"这类分布画 ASCII 直方图：按计数归一化到
给定宽度，行首带标签和原始数。GARDEN 的近亲，账房的画笔。
"""


def histogram(buckets, width: int = 12) -> list[str]:
    """Render {label: count} as sorted ASCII bars, normalized to max.

    >>> histogram({"a": 4, "b": 2, "c": 0}, width=4)
    ['a @@@@ 4', 'b @@   2', 'c      0']
    >>> histogram({}, width=4)
    []
    >>> histogram({"x": 7}, width=3)
    ['x @@@ 7']
    """
    if not buckets:
        return []
    top = max(buckets.values())
    lab_w = max(len(str(label)) for label in buckets)
    lines = []
    for label in sorted(buckets, key=str):
        count = buckets[label]
        bar = "@" * (round(count / top * int(width)) if top else 0)
        lines.append(f"{str(label):<{lab_w}} {bar:<{int(width)}} {count}")
    return lines


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
