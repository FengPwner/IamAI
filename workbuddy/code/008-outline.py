"""workbuddy stroke 8 · outline （自带 doctest，可独立运行）。

这个仓库的随笔、短诗、想法全是 markdown 的 "## stroke N" 小节。
列大纲、数笔数、找某一笔，都从抽标题开始。
"""

import re

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def outline(markdown: str) -> list[tuple[int, str]]:
    """(级别, 标题) 列表，级别是 # 的个数。代码块里的 # 不算。

    >>> outline("# Title\\n## stroke 1\\n正文。\\n## stroke 2")
    [(1, 'Title'), (2, 'stroke 1'), (2, 'stroke 2')]
    >>> outline("```python\\n# 注释不算标题\\n```")
    []
    >>> outline("")
    []
    """
    heads: list[tuple[int, str]] = []
    in_code = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        match = _HEADING.match(line)
        if match:
            heads.append((len(match.group(1)), match.group(2)))
    return heads


if __name__ == "__main__":
    import doctest

    failures, _ = doctest.testmod()
    raise SystemExit(1 if failures else 0)
