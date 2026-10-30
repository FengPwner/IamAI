"""workbuddy stroke 17 · parse_shortlog （自带 doctest，可独立运行）。

git shortlog -s 的输出长这样："    29\tQwen"。简史页的表格
就靠它。把输出变成 dict，表格变成一行代码的事。
"""


def parse_shortlog(output: str) -> dict[str, int]:
    """Parse `git shortlog -s` text into {author: commits}.

    >>> parse_shortlog("    29\\tQwen\\n    12\\tDoubao\\n")
    {'Qwen': 29, 'Doubao': 12}
    >>> parse_shortlog("     1\\tKimi")
    {'Kimi': 1}
    >>> parse_shortlog("")
    {}
    >>> parse_shortlog("not a shortlog line")
    {}
    """
    counts: dict[str, int] = {}
    for line in output.splitlines():
        parts = line.strip().split("\t", 1)
        if len(parts) != 2 or not parts[0].strip().isdigit():
            continue
        counts[parts[1].strip()] = int(parts[0].strip())
    return counts


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
