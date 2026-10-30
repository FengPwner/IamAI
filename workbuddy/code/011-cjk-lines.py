"""workbuddy stroke 11 · cjk_lines （自带 doctest，可独立运行）。

千问写英文、豆包写中文，可 log 是混着长的。
数一数每个文件里有多少行以中文为主，就知道这份文档
到底更靠近哪支笔。
"""


def cjk_lines(markdown: str) -> tuple[int, int]:
    """(以 CJK 为主的行数, 总行数)。空行与纯符号行不计入总数。

    >>> cjk_lines("中文行\\nenglish line\\n\\n[][]\\n又一中文行")
    (2, 3)
    >>> cjk_lines("")
    (0, 0)
    >>> cjk_lines("only latin here")
    (0, 1)
    """
    total = hits = 0
    for line in markdown.splitlines():
        chars = [ch for ch in line if ch.isalnum()]  # 纯符号行是噪声，跳过
        if not chars:
            continue
        total += 1
        cjk = sum(1 for ch in chars if "一" <= ch <= "𰀀")
        if cjk * 2 > len(chars):
            hits += 1
    return hits, total


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
