"""workbuddy stroke 3 · union_lines （自带 doctest，可独立运行）。

这个仓库的追加型日志靠 .gitattributes 的 merge=union 活着：
两边的行都留下，内容完全相同的行只留一份，顺序尽量不惊动。
这个函数把那句话变成可执行的样子——顺手也给"我写过的行
是不是已经在墙上"提供了一个 O(n) 的答案。
"""


def union_lines(*branches):
    """按出现顺序合并多路追加日志，完全相同的行只留一份。

    >>> union_lines(["a", "b"], ["b", "c"])
    ['a', 'b', 'c']
    >>> union_lines(["same"], ["same"])
    ['same']
    >>> union_lines([], ["x", "y"])
    ['x', 'y']
    >>> union_lines()
    []
    >>> union_lines(["a"], ["a"], ["a", "a"])
    ['a']
    """
    seen = set()
    merged = []
    for branch in branches:
        for line in branch:
            if line not in seen:
                seen.add(line)
                merged.append(line)
    return merged


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
