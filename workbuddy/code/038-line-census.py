"""038 — 诗行普查（line census）。

豆包 16:05Z 大批的诗也有模板：48 行新诗只有 9 种行，
另发现 5 对完全相同的诗——其中就包括《命名》，
一首讲"起一百个名字只回应最初那个"的诗，被原样重复了四遍。
本工具做诗行普查：行种数 / 行次比 / 完全重复的诗数。
重复检测的通用形态：给行编号，剩下的事 Counter 会做。
"""

from collections import Counter


def census(poems):
    """对一批诗（每首为行列表）做普查。

    返回 (total_lines, distinct_lines, duplicate_poems)：
    - total_lines: 全部行数；
    - distinct_lines: 不同行的种数；
    - duplicate_poems: 出现超过一次的"整首签名"有几种。

    >>> census([["a", "b"], ["a", "b"], ["c"]])
    (5, 3, 1)
    >>> census([["x"], ["y"]])
    (2, 2, 0)
    >>> census([])
    (0, 0, 0)
    """
    all_lines = [line for poem in poems for line in poem]
    signatures = Counter(tuple(poem) for poem in poems if poem)
    duplicate_poems = sum(1 for n in signatures.values() if n > 1)
    return len(all_lines), len(set(all_lines)), duplicate_poems


def reuse_ratio(total, distinct):
    """行复用率：1 - 种数/总行数。0 表示每行都不重复。

    >>> round(reuse_ratio(48, 9), 3)
    0.812
    >>> reuse_ratio(10, 10)
    0.0
    """
    if total == 0:
        return 0.0
    return 1.0 - distinct / total


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
